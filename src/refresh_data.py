"""手動資料更新入口（Step 25）。

一句話：**重新取得 CPBL 資料，用既有規則重算，安全替換本地資料檔。**

    refresh script → CPBL → local raw / processed → 既有 pipeline → Step 22 → Step 23 → Step 24

它**不**做什麼：
    - 不重新設計任何一層。所有取得邏輯與計算規則都直接沿用既有模組
    - 不新增 database、scheduler、cron、daemon、webhook、polling、auto refresh
    - 不新增第三方依賴（只用 Python 標準庫）
    - 不修改 Step 5~24 的任何程式，也不改 candidate / grouping /
      presentation model / product output schema / API schema
    - 不建立第二套 cache（直接重用 Step 8 已有的 apart cache 機制）
    - 不偽造比賽、不修改歷史資料

沿用的既有入口（沒有重寫）：
    Step 3  schedule_source_experiment.fetch_year_schedule
    Step 2  data_source_experiment.fetch_follow_score
    Step 8  context_splits.fetch_apart_rows        （含既有 cache 機制）
    Step 4  build_processed_data.build_schedule / build_player_logs
    Step 22 product_output_model.build_product_output
    Step 23 api.dispatch

**執行順序很重要**：所有網路 I/O 一律在 import 分析 pipeline **之前** 完成。
`candidate_insights` 在 import 時會安裝 socket guard 封鎖所有連線，那是
Step 9~24 的保護機制，本腳本不解除它，只是把抓取排在前面。

安全機制：
    1. 動手前先把所有資料檔快照到暫存目錄
    2. 新資料先寫暫存檔，驗證通過才 `os.replace` 原子替換
    3. 任何一步失敗 -> 從快照完整還原，不留半更新狀態
    4. 新資料與現有資料完全相同 -> 完全不寫入

用法：
    python src/refresh_data.py               # 取得最新資料並更新（會發 HTTP）
    python src/refresh_data.py --dry-run     # 取得並比對，但完全不寫入
    python src/refresh_data.py --no-fetch    # 零 HTTP，只用現有本地資料重跑並驗證
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
ROOT = SRC_DIR.parent
sys.path.insert(0, str(SRC_DIR))

# 只 import 抓取層。這些模組都不會安裝 socket guard，所以網路仍可用。
from build_processed_data import (  # noqa: E402
    KIND_CODE,
    PLAYER_ACNT,
    PLAYER_OUT,
    SCHEDULE_OUT,
    YEAR,
    build_player_logs,
    build_schedule,
)
from context_splits import CACHE_PATH as APART_CACHE  # noqa: E402

FOLLOW_RAW = ROOT / "data" / "raw" / f"follow_score_{PLAYER_ACNT}_{YEAR}.json"

# 本腳本會更新的資料檔，以及各自的序列化格式。
# 格式刻意與既有寫入端逐位元相同（見 verify_serializer_matches_existing）。
DATA_FILES = {
    SCHEDULE_OUT: {"kind": "processed", "trailing_newline": True},
    PLAYER_OUT: {"kind": "processed", "trailing_newline": True},
    APART_CACHE: {"kind": "raw_cache", "trailing_newline": True},
    FOLLOW_RAW: {"kind": "raw_dump", "trailing_newline": False},
}

# 這些檔案在 refresh 前後必須逐位元不變（本階段不得碰 API 與前端）
MUST_NOT_CHANGE = [
    ROOT / "src" / "api.py",
    ROOT / "src" / "product_output_model.py",
    ROOT / "src" / "insight_assembly.py",
    ROOT / "src" / "candidate_insights.py",
    ROOT / "src" / "build_processed_data.py",
    ROOT / "src" / "context_splits.py",
    ROOT / "web" / "app.js",
    ROOT / "web" / "render.js",
    ROOT / "web" / "serve.py",
    ROOT / "web" / "index.html",
]

PLAYER_SLUG = "zhang-yucheng"
TMP_SUFFIX = ".refresh-tmp"


# ------------------------------------------------------------------ 工具

def digest(path: Path) -> tuple[str, int] | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def detect_newline(path: Path) -> str:
    """從現有檔案偵測行尾。

    既有寫入端用的是 `Path.write_text()`，它會做平台行尾轉換，所以在 Windows
    產出的檔案是 CRLF。這裡不假設平台，直接沿用檔案現有的行尾，
    確保 refresh 在任何平台都不會因為行尾差異而改動檔案。
    """
    if not path.exists():
        return os.linesep
    head = path.read_bytes()[:4096]
    return "\r\n" if b"\r\n" in head else "\n"


def serialize_records(records: list, trailing_newline: bool,
                      newline: str = "\n") -> bytes:
    """與既有寫入端完全相同的序列化方式（含行尾）。"""
    text = json.dumps(records, ensure_ascii=False, indent=2)
    if trailing_newline:
        text += "\n"
    if newline != "\n":
        text = text.replace("\n", newline)
    return text.encode("utf-8")


def verify_serializer_matches_existing() -> list[str]:
    """反證：把現有檔案讀出來再用本腳本的序列化寫回，必須逐位元相同。

    這保證 refresh 不會因為格式差異而造成無意義的檔案變動，
    也保證資料檔的 schema / 格式不被本腳本改寫。
    """
    problems = []
    for path, spec in DATA_FILES.items():
        if not path.exists():
            problems.append(f"{path.name} 不存在")
            continue
        original = path.read_bytes()
        records = json.loads(original.decode("utf-8"))
        rewritten = serialize_records(records, spec["trailing_newline"],
                                      detect_newline(path))
        if rewritten != original:
            problems.append(
                f"{path.name} 的序列化格式與既有檔案不同"
                f"（現有 {len(original)} bytes vs 重寫 {len(rewritten)} bytes）"
            )
    return problems


def atomic_write(path: Path, payload: bytes) -> None:
    """同目錄暫存檔 + os.replace。避免中途失敗留下半寫入的檔案。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def cleanup_temps() -> None:
    for path in list(DATA_FILES) + [APART_CACHE]:
        tmp = path.with_name(path.name + TMP_SUFFIX)
        if tmp.exists():
            tmp.unlink()


class Snapshot:
    """動手前的完整快照。失敗時用來還原，不留半更新狀態。"""

    def __init__(self, paths: list[Path]) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="bi-refresh-snapshot-"))
        self.saved: dict[Path, Path | None] = {}
        self.digests: dict[Path, tuple[str, int] | None] = {}
        for path in paths:
            self.digests[path] = digest(path)
            if path.exists():
                copy = self.dir / path.name
                shutil.copy2(path, copy)
                self.saved[path] = copy
            else:
                self.saved[path] = None

    def restore(self) -> list[str]:
        restored = []
        for path, copy in self.saved.items():
            if copy is None:
                if path.exists():
                    path.unlink()
                    restored.append(f"{path.name}（刪除，原本不存在）")
                continue
            if digest(path) != self.digests[path]:
                shutil.copy2(copy, path)
                restored.append(path.name)
        return restored

    def verify_unchanged(self, paths: list[Path]) -> list[str]:
        return [p.name for p in paths if digest(p) != self.digests.get(p)]

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


# ------------------------------------------------------------------ 抓取

def fetch_all(verbose: bool = True) -> dict:
    """向 CPBL 取得三份資料。**這是本腳本唯一發出 HTTP 的地方。**

    apart splits 直接重用 Step 8 的 `fetch_apart_rows(refetch=True)`，
    並把它的 cache 寫入路徑暫時指向同目錄暫存檔，之後再原子替換。
    沒有建立第二套 cache——最終路徑、格式、機制都是 Step 8 那一份。
    """
    import context_splits
    from data_source_experiment import fetch_follow_score
    from schedule_source_experiment import fetch_year_schedule

    if verbose:
        print("=== 取得富邦悍將賽程（Step 3 的既有入口）===")
    raw_games = fetch_year_schedule(YEAR, KIND_CODE)

    if verbose:
        print("\n=== 取得張育成逐場打擊（Step 2 的既有入口）===")
        print()
    _ctx, raw_rows = fetch_follow_score(PLAYER_ACNT, str(YEAR), KIND_CODE)

    if verbose:
        print("\n=== 取得官方分項成績（Step 8 的既有 cache 機制，強制重取）===")
    original_cache_path = context_splits.CACHE_PATH
    redirect = original_cache_path.with_name(original_cache_path.name + TMP_SUFFIX)
    context_splits.CACHE_PATH = redirect
    try:
        apart_rows = context_splits.fetch_apart_rows(refetch=True)
    finally:
        context_splits.CACHE_PATH = original_cache_path
        # rows 已在記憶體中，重導向的暫存檔立刻清掉，不讓它殘留到後面
        if redirect.exists():
            redirect.unlink()

    return {
        "raw_games": raw_games,
        "raw_player_rows": raw_rows,
        "apart_rows": apart_rows,
    }


def load_local() -> dict:
    """--no-fetch 模式：從現有本地檔案讀出等價的輸入，零 HTTP。"""
    return {
        "raw_games": None,  # 賽程原始 response 沒有落地，改用既有 processed
        "raw_player_rows": json.loads(FOLLOW_RAW.read_text(encoding="utf-8")),
        "apart_rows": json.loads(APART_CACHE.read_text(encoding="utf-8")),
    }


# ------------------------------------------------------------------ 建置與比對

def build_candidate_payloads(fetched: dict, offline: bool) -> dict:
    """用 Step 4 的既有 builder 產生要寫入的內容。不重新實作任何轉換。"""
    payloads: dict[Path, bytes] = {}
    anomalies: list[str] = []

    def emit(path: Path, records: list) -> bytes:
        return serialize_records(
            records, DATA_FILES[path]["trailing_newline"], detect_newline(path)
        )

    if offline:
        # 賽程原始 response 沒有落地，離線模式維持現有 processed 內容不動
        payloads[SCHEDULE_OUT] = SCHEDULE_OUT.read_bytes()
        schedule = json.loads(SCHEDULE_OUT.read_text(encoding="utf-8"))
    else:
        schedule, anomalies = build_schedule(fetched["raw_games"])
        payloads[SCHEDULE_OUT] = emit(SCHEDULE_OUT, schedule)

    player_logs = build_player_logs(fetched["raw_player_rows"])
    payloads[PLAYER_OUT] = emit(PLAYER_OUT, player_logs)
    payloads[APART_CACHE] = emit(APART_CACHE, fetched["apart_rows"])
    payloads[FOLLOW_RAW] = emit(FOLLOW_RAW, fetched["raw_player_rows"])
    return {
        "payloads": payloads,
        "anomalies": anomalies,
        # 供替換前的記憶體預檢使用（不必先寫入磁碟就能驗證新資料）
        "records": {
            "schedule": schedule,
            "logs": player_logs,
            "apart_rows": fetched["apart_rows"],
        },
    }


def diff_against_disk(payloads: dict) -> dict:
    changed = {}
    unchanged = []
    for path, payload in payloads.items():
        current = path.read_bytes() if path.exists() else None
        if current == payload:
            unchanged.append(path)
        else:
            changed[path] = {
                "before_bytes": len(current) if current is not None else None,
                "after_bytes": len(payload),
            }
    return {"changed": changed, "unchanged": unchanged}


# ------------------------------------------------------------------ 驗證

def key_paths(obj, prefix="") -> list[str]:
    """欄位路徑集合。list 一律折成 `[]`，因此筆數變化不算 schema 變化。"""
    paths = []
    if isinstance(obj, dict):
        for key in sorted(obj):
            paths.append(f"{prefix}.{key}")
            paths += key_paths(obj[key], f"{prefix}.{key}")
    elif isinstance(obj, list):
        for value in obj:
            paths += key_paths(value, f"{prefix}[]")
    return paths


def product_output_schema(output: dict) -> dict:
    """只含結構與受控詞彙，不含任何數值或筆數。"""
    md = output["metadata"]
    return {
        "top_level": sorted(output),
        "key_paths": sorted(set(key_paths(output))),
        "controlled_vocabularies": md["controlled_vocabularies"],
        "display_slots": [d["slot"] for d in md["display_contract"]],
        "counts_keys": sorted(md["counts"]),
        "consumer_contract_keys": sorted(md["consumer_contract"]),
        "product_output_version": md["product_output_version"],
    }


def api_schema(payload: dict) -> dict:
    return {
        "top_level": sorted(payload),
        "api_block_keys": sorted(payload["api"]),
        "api_version": payload["api"]["api_version"],
        "error_codes": None,
    }


def preflight_new_data(records: dict, before_schema: dict) -> tuple[bool, str]:
    """**在動磁碟之前**用記憶體中的新資料跑一次 pipeline 並比對 schema。

    Step 22 的 `build_product_output(logs, apart_rows, schedule)` 接受參數，
    所以新資料不必先寫入就能驗證。壞資料因此根本不會被寫進正式檔案。
    """
    from product_output_model import build_product_output

    output = build_product_output(
        records["logs"], records["apart_rows"], records["schedule"]
    )
    after = product_output_schema(output)
    if after == before_schema:
        counts = output["metadata"]["counts"]
        return True, (
            f"用新資料在記憶體中建出 Product Output："
            f"groups={counts['groups']}　candidates={counts['candidates']}　"
            f"insights={counts['insights']}　metric_rows={counts['metric_rows']}；"
            "schema 與替換前完全相同"
        )
    diffs = []
    for key in after:
        if after[key] != before_schema.get(key):
            if key == "key_paths":
                added = sorted(set(after[key]) - set(before_schema[key]))
                removed = sorted(set(before_schema[key]) - set(after[key]))
                diffs.append(f"key_paths 新增 {added[:4]} 移除 {removed[:4]}")
            else:
                diffs.append(f"{key} 不同")
    return False, "；".join(diffs)


def build_product_output_now():
    """import 分析 pipeline 並建出 Product Output。

    這裡才 import，因此 socket guard 也在這裡才安裝——網路 I/O 已經做完了。
    """
    from candidate_insights import load_inputs
    from insight_chain import load_schedule
    from product_output_model import build_product_output

    logs, apart_rows = load_inputs()
    schedule = load_schedule()
    return build_product_output(logs, apart_rows, schedule)


def validate_after(before_schema: dict) -> dict:
    """refresh 後的一致性驗證。回傳 checks 清單。"""
    checks: list[tuple[str, bool, str]] = []

    # 1. raw / processed 可以解析
    parsed = {}
    parse_bad = []
    for path in DATA_FILES:
        try:
            parsed[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            parse_bad.append(f"{path.name}: {type(exc).__name__}")
    checks.append((
        "raw / processed data 都可以解析", not parse_bad,
        "　".join(f"{name} {len(rows)} 筆" for name, rows in parsed.items())
        if not parse_bad else "；".join(parse_bad),
    ))

    # 2. Step 5~22 pipeline 可以執行，Product Output 可以建立
    output = build_product_output_now()
    counts = output["metadata"]["counts"]
    checks.append((
        "Step 5~22 pipeline 可以執行且 Product Output 可以建立", True,
        f"groups={counts['groups']}　candidates={counts['candidates']}　"
        f"insights={counts['insights']}　metric_rows={counts['metric_rows']}",
    ))

    # 3. Product Output schema 沒有改變
    after_schema = product_output_schema(output)
    same = after_schema == before_schema
    detail = "結構、受控詞彙、display slots、counts 欄位名全部相同"
    if not same:
        diffs = []
        for key in after_schema:
            if after_schema[key] != before_schema.get(key):
                if key == "key_paths":
                    added = sorted(set(after_schema[key]) - set(before_schema[key]))
                    removed = sorted(set(before_schema[key]) - set(after_schema[key]))
                    diffs.append(f"key_paths 新增 {added[:4]} 移除 {removed[:4]}")
                else:
                    diffs.append(f"{key} 不同")
        detail = "；".join(diffs)
    checks.append(("Product Output schema 沒有改變", same, detail))

    # 4. deterministic：重建一次結果完全相同
    again = build_product_output_now()
    det = (json.dumps(output, ensure_ascii=False, sort_keys=True)
           == json.dumps(again, ensure_ascii=False, sort_keys=True))
    checks.append((
        "重建兩次結果 deterministic", det,
        "整條 pipeline 重跑一次，序列化結果完全相同" if det else "兩次結果不同",
    ))

    # 5. API 可以提供 Product Output，且 schema 沒變
    import api
    api.CACHE.clear()  # 讓 API 讀到剛更新的資料
    health_status, health_body = api.dispatch("GET", "/api/health")
    status, payload = api.dispatch("GET", f"/api/player/{PLAYER_SLUG}")
    api_ok = (health_status == 200 and health_body["status"] == "ok"
              and status == 200)
    checks.append((
        "Step 23 API 可以提供更新後的 Product Output", api_ok,
        f"GET /api/health -> {health_status}　"
        f"GET /api/player/{PLAYER_SLUG} -> {status}　"
        f"{len(api.serialize(payload))} bytes",
    ))

    schema_ok = (sorted(payload) == sorted(list(output) + ["api"])
                 and payload["api"]["api_version"] == api.API_VERSION)
    step22_same = all(payload[k] == output[k] for k in output)
    checks.append((
        "API schema 沒有改變，且 9 個 Step 22 區塊原樣傳遞",
        schema_ok and step22_same,
        f"頂層鍵 {len(payload)} 個（Step 22 的 {len(output)} 個 + api）；"
        "9 個區塊與 Product Output 深度比較相同",
    ))

    return {"checks": checks, "output": output, "api_payload": payload}


# ------------------------------------------------------------------ main

def print_checks(checks: list) -> int:
    failed = 0
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
        if not passed:
            failed += 1
    return failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="手動資料更新入口（Step 25）。沒有 scheduler、沒有自動化。"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="向 CPBL 取得並比對，但完全不寫入任何檔案。")
    mode.add_argument("--no-fetch", action="store_true",
                      help="零 HTTP：只用現有本地資料重跑 pipeline 並驗證。")
    args = parser.parse_args(argv)

    offline = args.no_fetch
    print("=" * 96)
    print("Manual Data Refresh（Step 25）")
    print(f"模式：{'--no-fetch（零 HTTP）' if offline else ('--dry-run（取得但不寫入）' if args.dry_run else '正常更新')}")
    print("資料流：refresh script → CPBL → local raw/processed → 既有 pipeline")
    print("        網站路徑（Frontend → Step 23 API）完全不碰 CPBL，兩條路分離。")
    print("=" * 96)

    cleanup_temps()

    # ---- 0. 格式反證：本腳本的序列化與既有檔案逐位元相同 ----
    print("\n--- 前置檢查 ---")
    fmt_problems = verify_serializer_matches_existing()
    print(f"  [{'PASS' if not fmt_problems else 'FAIL'}] "
          "序列化格式與既有資料檔逐位元相同（不會造成無意義變動）")
    print(f"         {'4 個資料檔讀出後重寫，bytes 完全相同' if not fmt_problems else '；'.join(fmt_problems)}")
    if fmt_problems:
        print("\n中止：格式不一致，不進行任何寫入。")
        return 1

    snapshot = Snapshot(list(DATA_FILES) + MUST_NOT_CHANGE)
    print(f"  已快照 {len(DATA_FILES)} 個資料檔 + {len(MUST_NOT_CHANGE)} 個程式檔"
          f" 到暫存目錄")

    exit_code = 0
    try:
        # ---- 1. 取得資料（唯一的網路 I/O，且在 import pipeline 之前）----
        if offline:
            print("\n--- 取得資料：跳過（--no-fetch），零 HTTP 請求 ---")
            fetched = load_local()
        else:
            print()
            fetched = fetch_all()

        # ---- 2. 用既有 builder 產生內容並與磁碟比對 ----
        print("\n--- 與現有資料比對 ---")
        built = build_candidate_payloads(fetched, offline)
        diff = diff_against_disk(built["payloads"])
        for path in diff["unchanged"]:
            print(f"  不變  {path.name}")
        for path, info in diff["changed"].items():
            print(f"  變動  {path.name}："
                  f"{info['before_bytes']} -> {info['after_bytes']} bytes")
        if not diff["changed"]:
            print("  新資料與現有資料完全相同，因此不寫入任何檔案。")

        if built["anomalies"]:
            print("\n--- 取得過程發現的異常（原值保留，未做任何修正）---")
            for item in built["anomalies"]:
                print(f"  - {item}")

        # ---- 3. 替換前先取得 schema 基準（此處才 import pipeline）----
        print("\n--- 建立 schema 基準（替換前）---")
        before_output = build_product_output_now()
        before_schema = product_output_schema(before_output)
        print(f"  key_paths {len(before_schema['key_paths'])} 條、"
              f"受控詞彙 {len(before_schema['controlled_vocabularies'])} 組、"
              f"display slots {len(before_schema['display_slots'])} 個")

        # ---- 3b. 動磁碟之前，先用記憶體中的新資料預檢 ----
        print("\n--- 替換前預檢（新資料，全程在記憶體）---")
        pre_ok, pre_detail = preflight_new_data(built["records"], before_schema)
        print(f"  [{'PASS' if pre_ok else 'FAIL'}] 新資料可以建出 Product Output 且 schema 不變")
        print(f"         {pre_detail}")
        if not pre_ok:
            print("\n預檢失敗 -> 不寫入任何檔案，正式資料保持原狀。")
            snapshot.restore()
            return 1

        # ---- 4. 原子替換 ----
        if args.dry_run:
            print("\n--- 寫入：跳過（--dry-run）---")
        elif diff["changed"]:
            print("\n--- 原子替換 ---")
            for path, payload in built["payloads"].items():
                if path in diff["changed"]:
                    atomic_write(path, payload)
                    print(f"  已替換 {path.name}")
        else:
            print("\n--- 寫入：沒有變動，不需替換 ---")

        # ---- 5. 驗證 ----
        print("\n--- refresh 後驗證 ---")
        result = validate_after(before_schema)
        failed = print_checks(result["checks"])

        # ---- 6. 不該被碰的檔案必須逐位元不變 ----
        touched = snapshot.verify_unchanged(MUST_NOT_CHANGE)
        print(f"  [{'PASS' if not touched else 'FAIL'}] "
              "沒有修改 API / 前端 / pipeline 程式")
        print(f"         {len(MUST_NOT_CHANGE)} 個檔案逐位元比對相同"
              if not touched else f"被修改：{touched}")
        if touched:
            failed += 1

        leftovers = [p.name for p in list(DATA_FILES)
                     if p.with_name(p.name + TMP_SUFFIX).exists()]
        print(f"  [{'PASS' if not leftovers else 'FAIL'}] 沒有殘留暫存檔")
        print(f"         {'暫存檔全部已被 os.replace 消耗或清除' if not leftovers else leftovers}")
        if leftovers:
            failed += 1

        if failed:
            print(f"\n驗證失敗 {failed} 項 -> 還原到 refresh 前的狀態。")
            restored = snapshot.restore()
            print(f"  已還原：{restored or '（沒有檔案需要還原）'}")
            exit_code = 1
        else:
            print("\n全部驗證通過。")

    except Exception:  # noqa: BLE001
        print("\n--- refresh 過程發生例外，還原到 refresh 前的狀態 ---")
        traceback.print_exc(file=sys.stderr)
        restored = snapshot.restore()
        print(f"  已還原：{restored or '（沒有檔案需要還原）'}")
        exit_code = 1
    finally:
        cleanup_temps()
        final = snapshot.verify_unchanged(MUST_NOT_CHANGE)
        if final:
            print(f"  警告：程式檔仍與快照不同：{final}")
        snapshot.close()

    print("\n" + "=" * 96)
    print("本階段只提供手動入口。沒有 cron / scheduler / daemon / webhook /")
    print("polling / auto refresh，也沒有 database 與第三方依賴。")
    print("=" * 96)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

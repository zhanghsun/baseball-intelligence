"""張育成 2026 一軍例行賽：三組官方情境 Context Evidence（Step 8）。

三組情境全部來自同一次官方回傳（`POST /team/getapartscore`，`ItemGroupCode == 3`）：

    1. 投手手別  VS. 右投 / VS. 左投
    2. 投手角色  VS. 先發 / VS. 中繼 / VS. 救援
    3. 投手背景  VS. 本土投手 / VS. 外籍投手

**粒度聲明：全部都是 2026 球季累計。**
不是最近 10 場、不是最近 15 場、不是單場、不是單一打席。

本階段只建立 Context Facts。不排名、不判斷強弱、不設門檻、不預測、不產生自然語言結論。

為什麼另建這支程式而不是擴充 `splits_vs_hand.py`：
    `splits_vs_hand.py` 是 Step 7B 的產物，主體是「確認 BasesONBallsCnt 是否含故意四壞」
    的一次性判定邏輯，與兩個手別分項綁得很緊。本階段要處理三組、七個分項，
    改寫會讓那份判定紀錄變得難讀。因此保留原檔不動，另建這支通用版本。

請求量：**2 個**（分項頁取 token + endpoint 取資料）。一次回傳涵蓋全部三組，不需額外請求。

用法：
    python src/context_splits.py
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_source_experiment import request  # noqa: E402  沿用 Step 2 已驗證的請求邏輯

# 球員身分與資料路徑的唯一來源（Step 29B）
import player_registry as registry  # noqa: E402

BASE = "https://www.cpbl.com.tw"
APART_PAGE = BASE + "/team/apart"
APART_API = BASE + "/team/getapartscore"

# ---- 以下全部由 registry 衍生，本模組不再自己宣告球員身分 ----
_ACTIVE_PLAYER_ID = registry.default_player_id()
_SUBJECT = registry.subject(_ACTIVE_PLAYER_ID)
_DATA_PATHS = registry.data_paths(_ACTIVE_PLAYER_ID)

PLAYER_ACNT = _SUBJECT["player_acnt"]
PLAYER_LABEL = f"{_SUBJECT['player_name']}（Acnt {PLAYER_ACNT}）"
YEAR = str(_SUBJECT["season"])
KIND_CODE = _SUBJECT["kind_code"]
POSITION_BATTER = "01"  # 01 = 野手
PITCHER_ATTR_GROUP = "3"  # ItemGroupCode 3 = 投手屬性分項

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PLAYER_LOG_PATH = _DATA_PATHS["player_log"]
RAW_LOG_PATH = _DATA_PATHS["follow_raw"]

# 三組情境。key = 組名，value = [(官方 ItemName, 本專案標籤), ...]
CONTEXT_GROUPS: dict[str, list[tuple[str, str]]] = {
    "投手手別": [
        ("VS. 右投", "VS RIGHT"),
        ("VS. 左投", "VS LEFT"),
    ],
    "投手角色": [
        ("VS. 先發", "VS STARTER"),
        ("VS. 中繼", "VS RELIEF"),
        ("VS. 救援", "VS CLOSER"),
    ],
    "投手背景": [
        ("VS. 本土投手", "VS DOMESTIC"),
        ("VS. 外籍投手", "VS FOREIGN"),
    ],
}

# 官方欄位 -> 本專案欄位名
FIELD_MAP = {
    "plate_appearances": "PlateAppearances",
    "at_bats": "HitCnt",  # 官網 HitCnt = 打數
    "hits": "HittingCnt",  # 官網 HittingCnt = 安打
    "doubles": "TwoBaseHitCnt",
    "triples": "ThreeBaseHitCnt",
    "home_runs": "HomeRunCnt",
    "walks": "BasesONBallsCnt",  # Step 7B 已確認：已包含故意四壞
    "intentional_walks": "IntentionalBasesONBallsCnt",
    "hit_by_pitch": "HitBYPitchCnt",
    "sacrifice_flies": "SacrificeFlyCnt",
    "sacrifice_hits": "SacrificeHitCnt",  # 用於打席恆等式檢查
    "strikeouts": "StrikeOutCnt",
    "rbi": "RunBattedINCnt",
    "total_bases": "TotalBases",
}

COUNT_FIELDS_FOR_OUTPUT = [
    "plate_appearances", "at_bats", "hits", "doubles", "triples", "home_runs",
    "walks", "intentional_walks", "hit_by_pitch", "sacrifice_flies",
    "strikeouts", "rbi", "total_bases",
]

# 對帳用的核心欄位
RECONCILE_FIELDS = [
    ("plate_appearances", "PA"),
    ("at_bats", "AB"),
    ("hits", "H"),
    ("total_bases", "TB"),
]


# ---------------------------------------------------------------- 工具

def sha256_of(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def ratio(numerator: int, denominator: int) -> float | None:
    """分母為 0 回傳 None，不填 0，不除零。"""
    if denominator == 0:
        return None
    return numerator / denominator


def trunc4(value: float) -> float:
    """截斷到小數第 4 位（不進位）。

    加上 1e-9 是為了避開浮點誤差把剛好落在邊界的值多砍一位
    （例如 0.3105 在二進位浮點下可能表示成 0.31049999999）。
    """
    return math.floor(value * 10**4 + 1e-9) / 10**4


def fmt_full(value: float | None) -> str:
    """完整精度顯示（本專案內部值一律保留完整精度）。"""
    return "N/A" if value is None else f"{value:.8f}"


def fmt4(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.4f}"


# ---------------------------------------------------------------- 取資料

CACHE_PATH = _DATA_PATHS["apart_raw"]


def fetch_apart_rows(refetch: bool = False) -> list:
    """取得分項成績原始 rows。共 2 個請求，一次涵蓋全部三組情境。

    取得後會存到 data/raw/ 作為快取。之後執行預設讀快取，不再發請求，
    避免為了重跑驗證而重複打官網。要重新取得請加 --refetch。
    """
    if not refetch and CACHE_PATH.exists():
        rows = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        print(f"[cache] 讀取本地快取 {CACHE_PATH.name}（0 個 HTTP 請求）")
        print(f"        分項總列數：{len(rows)}")
        print("        要重新向官網取得請執行：python src/context_splits.py --refetch")
        return rows

    jar = http.cookiejar.CookieJar()

    print(f"[1/2] GET {APART_PAGE}?Acnt={PLAYER_ACNT}")
    html = request(jar, f"{APART_PAGE}?Acnt={PLAYER_ACNT}")
    m = re.search(
        r'url:\s*"/team/getapartscore".*?RequestVerificationToken:\s*\'([^\']+)\'',
        html,
        re.S,
    )
    token = m.group(1) if m else None
    print(f"      token 取得：{'是' if token else '否'}")
    if not token:
        raise RuntimeError("找不到 RequestVerificationToken，頁面結構可能已改變")

    payload = {
        "acnt": PLAYER_ACNT,
        "kindCode": KIND_CODE,
        "position": POSITION_BATTER,
        "year": YEAR,
    }
    print(f"[2/2] POST {APART_API}  data={payload}")
    time.sleep(1)
    raw = request(jar, APART_API, data=payload, headers={"RequestVerificationToken": token})

    outer = json.loads(raw)
    print(f"      回傳最外層鍵值：{sorted(outer.keys())}")
    rows = json.loads(outer.get("ApartScore") or "[]")
    print(f"      分項總列數：{len(rows)}")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"      已存快取：{CACHE_PATH.name}（下次執行不需再發請求）")
    return rows


# ---------------------------------------------------------------- 建 context

def build_context(row: dict, label: str) -> dict:
    """把一列官方分項轉成本專案的 context fact。"""
    out: dict = {"label": label, "item_name": row["ItemName"].strip()}
    for our, official in FIELD_MAP.items():
        out[our] = row[official]
    out["runs"] = None  # 官方分項 response 沒有得分欄位，維持 None，不推估

    ab = out["at_bats"]
    pa = out["plate_appearances"]
    bb = out["walks"]
    hbp = out["hit_by_pitch"]
    sf = out["sacrifice_flies"]
    h = out["hits"]

    # AVG = H / AB
    out["batting_average"] = ratio(h, ab)
    # SLG = TB / AB
    out["slugging_percentage"] = ratio(out["total_bases"], ab)
    # OBP = (H + BB + HBP) / (AB + BB + HBP + SF)
    # BB 已含 IBB（Step 7B 實證確認），因此不再加 intentional_walks
    obp_num = h + bb + hbp
    obp_den = ab + bb + hbp + sf
    out["obp_numerator"] = obp_num
    out["obp_denominator"] = obp_den
    out["on_base_percentage"] = ratio(obp_num, obp_den)

    # 打席恆等式檢查：PA 應等於 AB + BB + HBP + SF + SH（BB 已含 IBB）
    out["pa_identity_sum"] = ab + bb + hbp + sf + out["sacrifice_hits"]
    out["pa_identity_ok"] = out["pa_identity_sum"] == pa

    # 官方比率，只作為 validation reference
    out["official_avg"] = row.get("Avg")
    out["official_obp"] = row.get("Obp")
    out["official_slg"] = row.get("Slg")
    out["official_ops"] = row.get("Ops")
    return out


def print_context(c: dict) -> None:
    print(f"\n--- {c['label']}（官方 ItemName: {c['item_name']}）---")
    for key in COUNT_FIELDS_FOR_OUTPUT:
        print(f"  {key:<21}: {c[key]}")
    print(f"  {'runs':<21}: None（官方分項無此欄位，維持 None）")
    print(f"  {'batting_average':<21}: {fmt_full(c['batting_average'])}"
          f"   = {c['hits']} / {c['at_bats']}")
    print(f"  {'on_base_percentage':<21}: {fmt_full(c['on_base_percentage'])}"
          f"   = {c['obp_numerator']} / {c['obp_denominator']}")
    print(f"  {'slugging_percentage':<21}: {fmt_full(c['slugging_percentage'])}"
          f"   = {c['total_bases']} / {c['at_bats']}")
    print(f"  官方比率（僅 reference）: AVG={c['official_avg']} OBP={c['official_obp']} "
          f"SLG={c['official_slg']} OPS={c['official_ops']}")


# ---------------------------------------------------------------- 驗證

def reconcile_group(group_name: str, contexts: list, season: dict) -> list:
    """把一組情境加總後與 season totals 對帳。回傳檢查結果清單。"""
    checks = []
    for field, short in RECONCILE_FIELDS:
        parts = [c[field] for c in contexts]
        total = sum(parts)
        expected = season[field]
        detail = " + ".join(str(p) for p in parts) + f" = {total}，Season {short} = {expected}"
        if total != expected:
            detail += f"　**差異 {total - expected:+d}**"
        checks.append((f"[{group_name}] 加總 {short} == Season {short}", total == expected, detail))
    return checks


SUPPLEMENTARY_FIELDS = [
    ("doubles", "二安"), ("triples", "三安"), ("home_runs", "全壘打"),
    ("walks", "四壞"), ("intentional_walks", "故意四壞"), ("hit_by_pitch", "死球"),
    ("sacrifice_flies", "犧飛"), ("strikeouts", "三振"), ("rbi", "打點"),
]


def cross_group_consistency(built: dict) -> list:
    """補充驗證：三組切分對同一個欄位加總後應該互相一致。

    三組是同一批打席的三種切法，因此每個計數欄位在三組的加總必須相同。
    這比只對帳 PA/AB/H/TB 更嚴格，而且不需要額外請求。
    """
    checks = []
    for field, name in SUPPLEMENTARY_FIELDS:
        totals = {g: sum(c[field] for c in cs) for g, cs in built.items()}
        values = set(totals.values())
        detail = "　".join(f"{g}={v}" for g, v in totals.items())
        checks.append(
            (f"三組切分的 {field}（{name}）加總一致", len(values) == 1, detail)
        )
    return checks


def check_official_ratios(contexts: list) -> list:
    """本專案計算值截斷到 4 位後與官方值比較。完整精度值同時記錄。"""
    checks = []
    for c in contexts:
        for metric, ours_key, official_key in (
            ("AVG", "batting_average", "official_avg"),
            ("OBP", "on_base_percentage", "official_obp"),
            ("SLG", "slugging_percentage", "official_slg"),
        ):
            ours = c[ours_key]
            official = c[official_key]
            if ours is None or official is None:
                checks.append(
                    (f"{c['label']} {metric}：截斷 4 位後 == 官方值", False,
                     f"無法比較（自算={fmt_full(ours)}，官方={official}）")
                )
                continue
            truncated = trunc4(ours)
            ok = abs(truncated - official) < 1e-9
            checks.append(
                (f"{c['label']} {metric}：截斷 4 位後 == 官方值", ok,
                 f"完整精度 {fmt_full(ours)}　截斷 {truncated:.4f}　官方 {official}")
            )
    return checks


def main() -> None:
    fp_before = sha256_of(PLAYER_LOG_PATH)

    # Season totals 由 processed data 逐筆獨立加總，不使用官方彙總值
    logs = json.loads(PLAYER_LOG_PATH.read_text(encoding="utf-8"))
    season = {
        k: sum(g[k] for g in logs)
        for k in ("plate_appearances", "at_bats", "hits", "total_bases")
    }

    print("=" * 92)
    print(f"Context Evidence：{PLAYER_LABEL}　{YEAR} 一軍例行賽")
    print("粒度：【2026 球季累計】。不是最近 10 場、不是最近 15 場、不是單場、不是單一打席。")
    print("=" * 92)
    print(f"\nSeason totals（由 processed data {len(logs)} 筆逐場獨立加總）：")
    print(f"  PA={season['plate_appearances']}  AB={season['at_bats']}  "
          f"H={season['hits']}  TB={season['total_bases']}\n")

    rows = fetch_apart_rows(refetch="--refetch" in sys.argv)
    group3 = [r for r in rows if str(r.get("ItemGroupCode")) == PITCHER_ATTR_GROUP]
    print(f"      ItemGroupCode == 3 的分項：{[r['ItemName'].strip() for r in group3]}")

    by_name = {r["ItemName"].strip(): r for r in group3}

    # ---------- 建三組 context ----------
    built: dict[str, list] = {}
    for group_name, members in CONTEXT_GROUPS.items():
        missing = [n for n, _ in members if n not in by_name]
        if missing:
            raise RuntimeError(f"[{group_name}] 找不到分項：{missing}")
        built[group_name] = [build_context(by_name[n], label) for n, label in members]

    for group_name, contexts in built.items():
        print("\n" + "=" * 92)
        print(f"Context Facts — {group_name}")
        print("=" * 92)
        for c in contexts:
            print_context(c)

    # ---------- 驗證 ----------
    print("\n" + "=" * 92)
    print("Validation 1：三組各自加總是否與 Season totals 對上")
    print("=" * 92)
    recon_checks = []
    for group_name, contexts in built.items():
        recon_checks += reconcile_group(group_name, contexts, season)
    for name, passed, detail in recon_checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")

    print("\n" + "=" * 92)
    print("Validation 2：打席恆等式 PA == AB + BB + HBP + SF + SH（BB 已含 IBB）")
    print("=" * 92)
    identity_checks = []
    for group_name, contexts in built.items():
        for c in contexts:
            identity_checks.append(
                (f"{c['label']} 打席恆等式", c["pa_identity_ok"],
                 f"AB+BB+HBP+SF+SH = {c['pa_identity_sum']}，PA = {c['plate_appearances']}"
                 f"（IBB = {c['intentional_walks']}）")
            )
    for name, passed, detail in identity_checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")

    print("\n" + "=" * 92)
    print("Validation 3：三組切分在其他計數欄位上的加總是否互相一致")
    print("=" * 92)
    cross_checks = cross_group_consistency(built)
    for name, passed, detail in cross_checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")

    print("\n" + "=" * 92)
    print("Validation 4：自算比率（完整精度）截斷到 4 位後與官方值比較")
    print("=" * 92)
    ratio_checks = []
    for group_name, contexts in built.items():
        ratio_checks += check_official_ratios(contexts)
    for name, passed, detail in ratio_checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")

    print("\n" + "=" * 92)
    print("Validation 5：processed data 未被修改")
    print("=" * 92)
    fp_after = sha256_of(PLAYER_LOG_PATH)
    ok = fp_before == fp_after
    print(f"  [{'PASS' if ok else 'FAIL'}] sha256 與檔案大小前後一致")
    print(f"         sha256 前 8 碼 {fp_before[0][:8]}，{fp_before[1]} bytes")

    all_checks = (
        recon_checks + identity_checks + cross_checks + ratio_checks
        + [("processed data 未修改", ok, "")]
    )
    failed = [c for c in all_checks if not c[1]]
    print("\n" + "=" * 92)
    print(f"總計 {len(all_checks)} 項檢查，通過 {len(all_checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("失敗項目未被修正或補值，原值保留：")
        for name, _, detail in failed:
            print(f"  - {name}：{detail}")
    print("=" * 92)


if __name__ == "__main__":
    main()

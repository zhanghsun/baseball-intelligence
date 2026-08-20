"""張育成 2026 一軍例行賽：VS. 右投 / VS. 左投 情境 evidence（Step 7B）。

資料來源：CPBL 官方「分項成績」`POST /team/getapartscore`，取 ItemGroupCode == 3。
不使用第三方資料，不使用「對手先發投手」proxy。

**重要：這是整季累計的 VS. 左投 / VS. 右投 資料，不是最近 10 / 15 場。**
與 Step 6 的 rolling baseline 是不同東西，不可混用。

本階段只計算事實，不判斷強弱、不設門檻、不產生自然語言結論。

請求量：2 個（分項頁取 token + endpoint 取資料）。

用法：
    python src/splits_vs_hand.py
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_source_experiment import request  # noqa: E402  沿用 Step 2 已驗證的請求邏輯

BASE = "https://www.cpbl.com.tw"
APART_PAGE = BASE + "/team/apart"
APART_API = BASE + "/team/getapartscore"

PLAYER_ACNT = "0000006888"  # 張育成
PLAYER_LABEL = "張育成（Acnt 0000006888）"
YEAR = "2026"
KIND_CODE = "A"  # 一軍例行賽
POSITION_BATTER = "01"  # 01 = 野手（打擊分項）
PITCHER_HAND_GROUP = "3"  # ItemGroupCode 3 = 投手屬性分項

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PLAYER_LOG_PATH = PROCESSED_DIR / "zhang_yucheng_game_logs_2026.json"

TARGET_ITEMS = {"VS. 右投": "VS RIGHT", "VS. 左投": "VS LEFT"}

# 官方欄位 -> 本專案欄位名
FIELD_MAP = {
    "plate_appearances": "PlateAppearances",
    "at_bats": "HitCnt",  # 官網 HitCnt = 打數
    "hits": "HittingCnt",  # 官網 HittingCnt = 安打
    "doubles": "TwoBaseHitCnt",
    "triples": "ThreeBaseHitCnt",
    "home_runs": "HomeRunCnt",
    "walks": "BasesONBallsCnt",
    "intentional_walks": "IntentionalBasesONBallsCnt",
    "sacrifice_flies": "SacrificeFlyCnt",
    "sacrifice_hits": "SacrificeHitCnt",
    "hit_by_pitch": "HitBYPitchCnt",
    "strikeouts": "StrikeOutCnt",
    "rbi": "RunBattedINCnt",
    "total_bases": "TotalBases",
}
# runs（得分）：分項成績回傳中沒有這個欄位，見文件 Limitations。


def sha256_of(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def fmt(value: float | None, digits: int = 4) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def fetch_apart_splits() -> list:
    """取得分項成績原始 rows。共 2 個請求。"""
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
    print(f"      分項列數：{len(rows)}")
    return rows


def determine_bb_semantics(row: dict) -> dict:
    """用打席恆等式判定 BasesONBallsCnt 是否已包含故意四壞。

    打席恆等式：PA = AB + BB + HBP + SF + SH
    若 BB 不含 IBB，則需寫成 PA = AB + BB + IBB + HBP + SF + SH。
    兩式相差正好是 IBB，只要 IBB > 0 就能分辨。
    """
    pa = row["PlateAppearances"]
    ab = row["HitCnt"]
    bb = row["BasesONBallsCnt"]
    ibb = row["IntentionalBasesONBallsCnt"]
    hbp = row["HitBYPitchCnt"]
    sf = row["SacrificeFlyCnt"]
    sh = row["SacrificeHitCnt"]
    without_ibb = ab + bb + hbp + sf + sh
    with_ibb = ab + bb + ibb + hbp + sf + sh
    return {
        "pa": pa,
        "ibb": ibb,
        "identity_bb_includes_ibb": without_ibb,
        "identity_bb_excludes_ibb": with_ibb,
        "matches_includes": without_ibb == pa,
        "matches_excludes": with_ibb == pa,
        # IBB == 0 時兩式相同，無法分辨
        "discriminating": ibb > 0,
    }


def build_split(row: dict, label: str, bb_includes_ibb: bool) -> dict:
    out = {"label": label, "item_name": row["ItemName"]}
    for our, official in FIELD_MAP.items():
        out[our] = row[official]
    out["runs"] = None  # 分項成績沒有得分欄位

    ab = out["at_bats"]
    out["batting_average"] = ratio(out["hits"], ab)
    out["slugging_percentage"] = ratio(out["total_bases"], ab)

    # OBP：只有在 BB 語意已確認的情況下才計算
    if bb_includes_ibb:
        num = out["hits"] + out["walks"] + out["hit_by_pitch"]
        den = ab + out["walks"] + out["hit_by_pitch"] + out["sacrifice_flies"]
        out["on_base_percentage"] = ratio(num, den)
        out["obp_numerator"] = num
        out["obp_denominator"] = den
    else:
        out["on_base_percentage"] = None
        out["obp_numerator"] = None
        out["obp_denominator"] = None

    # 官方提供的比率，只用來對帳，不當計算結果
    out["official_avg"] = row.get("Avg")
    out["official_obp"] = row.get("Obp")
    out["official_slg"] = row.get("Slg")
    out["official_ops"] = row.get("Ops")
    return out


def print_split(s: dict) -> None:
    print(f"\n--- {s['label']}（官方 ItemName: {s['item_name']}）---")
    for key in (
        "plate_appearances", "at_bats", "hits", "doubles", "triples", "home_runs",
        "walks", "intentional_walks", "sacrifice_flies", "sacrifice_hits",
        "hit_by_pitch", "strikeouts", "rbi", "total_bases",
    ):
        print(f"  {key:<20}: {s[key]}")
    print(f"  {'runs':<20}: None（官方分項成績沒有得分欄位）")
    print(f"  {'batting_average':<20}: {fmt(s['batting_average'])}"
          f"   = {s['hits']} / {s['at_bats']}")
    print(f"  {'slugging_percentage':<20}: {fmt(s['slugging_percentage'])}"
          f"   = {s['total_bases']} / {s['at_bats']}")
    if s["on_base_percentage"] is None:
        print(f"  {'on_base_percentage':<20}: 未計算（BB 語意未確認，見文件）")
    else:
        print(f"  {'on_base_percentage':<20}: {fmt(s['on_base_percentage'])}"
              f"   = {s['obp_numerator']} / {s['obp_denominator']}")
    print(f"  官方比率（僅對帳用）  : AVG={s['official_avg']} OBP={s['official_obp']} "
          f"SLG={s['official_slg']} OPS={s['official_ops']}")


def print_difference(right: dict, left: dict) -> None:
    print("\n--- DIFFERENCE（VS LEFT 減 VS RIGHT，僅記錄數值差，不做任何解讀）---")
    for key in (
        "plate_appearances", "at_bats", "hits", "doubles", "triples", "home_runs",
        "walks", "intentional_walks", "sacrifice_flies", "hit_by_pitch",
        "strikeouts", "rbi", "total_bases",
    ):
        print(f"  {key:<20}: {left[key] - right[key]:+d}"
              f"   （右投 {right[key]} / 左投 {left[key]}）")
    for key in ("batting_average", "on_base_percentage", "slugging_percentage"):
        a, b = right[key], left[key]
        diff = "N/A" if (a is None or b is None) else f"{b - a:+.4f}"
        print(f"  {key:<20}: {diff}   （右投 {fmt(a)} / 左投 {fmt(b)}）")


def trunc4(value: float) -> float:
    """截斷到小數第 4 位（不進位）。"""
    return int(value * 10**4) / 10**4


def diagnose_official_rounding(group3: list) -> dict:
    """用 ItemGroupCode==3 的全部分項，判定官方比率是四捨五入還是截斷到 4 位小數。

    不做任何修正，只是找出官方的呈現慣例，用來解釋自算值與官方值的尾數差異。
    """
    cases = []
    for r in group3:
        ab = r["HitCnt"]
        if ab == 0:
            continue
        exact = {
            "Avg": r["HittingCnt"] / ab,
            "Slg": r["TotalBases"] / ab,
        }
        for key, value in exact.items():
            official = r.get(key)
            if official is None:
                continue
            cases.append(
                {
                    "item": r["ItemName"],
                    "metric": key,
                    "exact": value,
                    "official": official,
                    "round4_match": abs(round(value, 4) - official) < 1e-9,
                    "trunc4_match": abs(trunc4(value) - official) < 1e-9,
                }
            )
    return {
        "cases": cases,
        "n": len(cases),
        "round4_matches": sum(1 for c in cases if c["round4_match"]),
        "trunc4_matches": sum(1 for c in cases if c["trunc4_match"]),
    }


def run_validation(
    right: dict, left: dict, season: dict, fp_before: tuple, extra_season: dict
) -> list:
    checks: list[tuple[str, bool, str]] = []

    # 1~4：分項加總 == season totals（season 由 processed data 獨立算出）
    for our_key, season_key, name in (
        ("plate_appearances", "plate_appearances", "PA"),
        ("at_bats", "at_bats", "AB"),
        ("hits", "hits", "H"),
        ("total_bases", "total_bases", "TB"),
    ):
        total = right[our_key] + left[our_key]
        expected = season[season_key]
        checks.append(
            (f"VS Right {name} + VS Left {name} == Season {name}",
             total == expected,
             f"{right[our_key]} + {left[our_key]} = {total}，Season = {expected}")
        )

    # 5：自算 AVG 與官方 AVG 一致
    for s in (right, left):
        ours = s["batting_average"]
        official = s["official_avg"]
        ok = (
            ours is not None
            and official is not None
            and abs(round(ours, 4) - round(official, 4)) < 1e-9
        )
        checks.append(
            (f"{s['label']}：自算 AVG 與官方 AVG 一致",
             ok, f"自算 {fmt(ours)} vs 官方 {official}")
        )

    # 6：自算 OBP 與官方一致（僅在有計算時）
    for s in (right, left):
        ours = s["on_base_percentage"]
        official = s["official_obp"]
        if ours is None:
            checks.append(
                (f"{s['label']}：OBP 對帳", False, "未計算 OBP，無法對帳")
            )
            continue
        ok = official is not None and abs(round(ours, 4) - round(official, 4)) < 1e-9
        checks.append(
            (f"{s['label']}：自算 OBP 與官方 OBP 一致",
             ok, f"自算 {fmt(ours)} vs 官方 {official}")
        )

    # 7：自算 SLG 與官方一致
    for s in (right, left):
        ours = s["slugging_percentage"]
        official = s["official_slg"]
        ok = (
            ours is not None
            and official is not None
            and abs(round(ours, 4) - round(official, 4)) < 1e-9
        )
        checks.append(
            (f"{s['label']}：自算 SLG 與官方 SLG 一致",
             ok, f"自算 {fmt(ours)} vs 官方 {official}")
        )

    # 7b：SLG 在官方的 4 位小數截斷慣例下是否一致（補充檢查，不取代第 7 項）
    for s in (right, left):
        ours = s["slugging_percentage"]
        official = s["official_slg"]
        ok = (
            ours is not None
            and official is not None
            and abs(trunc4(ours) - official) < 1e-9
        )
        checks.append(
            (f"{s['label']}：自算 SLG 截斷到 4 位小數後與官方一致",
             ok, f"截斷 {trunc4(ours):.4f} vs 官方 {official}（未截斷 {fmt(ours)}）")
        )

    # 補充：其他計數欄位也與 processed data 加總對帳
    for our_key, name in (
        ("doubles", "二安"), ("triples", "三安"), ("home_runs", "全壘打"),
        ("walks", "四壞"), ("strikeouts", "三振"), ("rbi", "打點"),
        ("hit_by_pitch", "死球"), ("sacrifice_flies", "犧飛"),
        ("intentional_walks", "故意四壞"),
    ):
        total = right[our_key] + left[our_key]
        expected = extra_season.get(our_key)
        if expected is None:
            continue
        checks.append(
            (f"VS Right + VS Left {our_key}（{name}）== processed data 加總",
             total == expected,
             f"{right[our_key]} + {left[our_key]} = {total}，processed = {expected}")
        )

    # 8：processed data 未被修改
    fp_after = sha256_of(PLAYER_LOG_PATH)
    checks.append(
        ("processed data 未被修改（sha256 與大小不變）",
         fp_before == fp_after,
         f"sha256 前 8 碼 {fp_before[0][:8]}，{fp_before[1]} bytes")
    )

    return checks


def main() -> None:
    fp_before = sha256_of(PLAYER_LOG_PATH)

    # Season totals 由 processed data 獨立加總，不使用官方彙總值
    logs = json.loads(PLAYER_LOG_PATH.read_text(encoding="utf-8"))
    season = {
        k: sum(g[k] for g in logs)
        for k in ("plate_appearances", "at_bats", "hits", "total_bases")
    }
    season["games"] = len(logs)

    # 補充對帳用的其他計數欄位（processed data 有的部分）
    extra_season = {
        k: sum(g[k] for g in logs)
        for k in ("doubles", "triples", "home_runs", "walks", "strikeouts", "rbi",
                  "hit_by_pitch")
    }
    # 犧飛與故意四壞不在 processed data 中；若 Step 2 存下的原始檔還在，就拿來對帳
    raw_path = PROCESSED_DIR.parent / "raw" / "follow_score_0000006888_2026.json"
    if raw_path.exists():
        raw_logs = json.loads(raw_path.read_text(encoding="utf-8"))
        extra_season["sacrifice_flies"] = sum(g["SacrificeFlyCnt"] for g in raw_logs)
        extra_season["intentional_walks"] = sum(
            g["IntentionalBasesONBallsCnt"] for g in raw_logs
        )
        print(f"（找到 Step 2 原始檔，犧飛與故意四壞也納入對帳）")
    else:
        print("（找不到 Step 2 原始檔，犧飛與故意四壞略過對帳）")

    print("=" * 88)
    print(f"VS. 右投 / VS. 左投 Evidence：{PLAYER_LABEL}　{YEAR} 一軍例行賽")
    print("這是【整季累計】資料，不是最近 10 / 15 場，與 Step 6 rolling baseline 無關")
    print("=" * 88)

    rows = fetch_apart_splits()
    group3 = [r for r in rows if str(r.get("ItemGroupCode")) == PITCHER_HAND_GROUP]
    print(f"\nItemGroupCode == 3 的分項：{[r['ItemName'] for r in group3]}")

    by_name = {r["ItemName"].strip(): r for r in group3}
    missing = [n for n in TARGET_ITEMS if n not in by_name]
    if missing:
        raise RuntimeError(f"找不到分項：{missing}")

    # ---------- 先確認 BB 語意 ----------
    print("\n" + "=" * 88)
    print("欄位語意確認：BasesONBallsCnt 是否已包含故意四壞？")
    print("=" * 88)
    print("  判定方式：打席恆等式 PA = AB + BB + HBP + SF + SH")
    print("  若 BB 不含 IBB，則等式必須改為 PA = AB + BB + IBB + HBP + SF + SH")
    print("  兩式相差正好是 IBB，只要 IBB > 0 就能分辨。\n")

    verdicts = []
    for name, label in TARGET_ITEMS.items():
        v = determine_bb_semantics(by_name[name])
        verdicts.append((label, v))
        print(f"  {label}（{name}）")
        print(f"    PA = {v['pa']}　IBB = {v['ibb']}")
        print(f"    AB+BB+HBP+SF+SH     = {v['identity_bb_includes_ibb']}"
              f"  -> {'符合 PA' if v['matches_includes'] else '不符 PA'}")
        print(f"    AB+BB+IBB+HBP+SF+SH = {v['identity_bb_excludes_ibb']}"
              f"  -> {'符合 PA' if v['matches_excludes'] else '不符 PA'}")
        print(f"    IBB > 0（可分辨）    : {v['discriminating']}")

    discriminating = [v for _, v in verdicts if v["discriminating"]]
    bb_includes_ibb = bool(discriminating) and all(
        v["matches_includes"] and not v["matches_excludes"] for v in discriminating
    )
    print()
    if bb_includes_ibb:
        print("  判定結果：BasesONBallsCnt **已包含** 故意四壞，")
        print("  IntentionalBasesONBallsCnt 是其中的細項拆解，不可再相加。")
        print("  因此 OBP = (H + BB + HBP) / (AB + BB + HBP + SF)，不另外加 IBB。")
    else:
        print("  判定結果：無法確認 BB 語意（IBB 為 0 或兩式皆不符），因此不計算 OBP。")

    # ---------- 建立 evidence ----------
    right = build_split(by_name["VS. 右投"], "VS RIGHT", bb_includes_ibb)
    left = build_split(by_name["VS. 左投"], "VS LEFT", bb_includes_ibb)

    print("\n" + "=" * 88)
    print("Evidence")
    print("=" * 88)
    print_split(right)
    print_split(left)
    print_difference(right, left)

    # ---------- Validation ----------
    print("\n" + "=" * 88)
    print("Validation")
    print("=" * 88)
    print(f"  Season totals（由 processed data {season['games']} 筆獨立加總）：")
    print(f"    PA={season['plate_appearances']} AB={season['at_bats']} "
          f"H={season['hits']} TB={season['total_bases']}\n")
    # 先診斷官方比率的呈現慣例，用來解釋尾數差異
    diag = diagnose_official_rounding(group3)
    print("  官方比率呈現慣例診斷（用 ItemGroupCode==3 全部分項的 AVG 與 SLG）：")
    print(f"    樣本數 {diag['n']}　"
          f"四捨五入到 4 位小數相符 {diag['round4_matches']}　"
          f"截斷到 4 位小數相符 {diag['trunc4_matches']}")
    for c in diag["cases"]:
        if not c["round4_match"]:
            print(f"    尾數不同：{c['item']} {c['metric']}　"
                  f"精確值 {c['exact']:.8f}　官方 {c['official']}　"
                  f"round4={round(c['exact'], 4)}　trunc4={trunc4(c['exact']):.4f}")
    print()

    checks = run_validation(right, left, season, fp_before, extra_season)
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/VS_HAND_EVIDENCE.md。")


if __name__ == "__main__":
    main()

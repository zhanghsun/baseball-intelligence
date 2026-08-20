"""張育成 2026 年近期打擊狀態的 evidence 計算（Step 5）。

這一步**只計算事實**，不產生任何自然語言結論。
輸出的每個數字都附帶可追溯資訊（日期範圍與 game_sno 清單），
讓人能回頭核對數字來自哪幾場比賽。

原則：
    - 純 Python 標準函式庫，不用 pandas，不連網。
    - 不修改 data/processed/ 下的原始檔案（唯讀）。
    - batting_average 一律由 hits / at_bats 自行計算，
      **不使用**官方逐場資料中的 batting_average 欄位。
    - at_bats == 0 時 batting_average 為 None，不填 0，不除以零。
    - 發現不一致一律記錄，不偷偷修正。

用法：
    python src/player_form_analysis.py
"""

from __future__ import annotations

import json
from pathlib import Path

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PLAYER_PATH = PROCESSED_DIR / "zhang_yucheng_game_logs_2026.json"

PLAYER_LABEL = "張育成（Acnt 0000006888）"
SEASON_LABEL = "2026 一軍例行賽"

# 要加總的計數型欄位
COUNTING_FIELDS = [
    "plate_appearances",
    "at_bats",
    "hits",
    "walks",
    "strikeouts",
    "home_runs",
    "rbi",
    "total_bases",
    "doubles",
    "triples",
    "hit_by_pitch",
]


def load_game_logs() -> list:
    if not PLAYER_PATH.exists():
        raise SystemExit(
            f"找不到 {PLAYER_PATH}\n請先執行：python src/build_processed_data.py"
        )
    return json.loads(PLAYER_PATH.read_text(encoding="utf-8"))


def sort_by_date(records: list) -> list:
    """明確依 (game_date, game_sno) 升冪排序，不依賴檔案原有順序。"""
    return sorted(records, key=lambda r: (r["game_date"], r["game_sno"]))


def safe_ratio(numerator: int, denominator: int) -> float | None:
    """分母為 0 時回傳 None，不回傳 0，也不拋除零錯誤。"""
    if denominator == 0:
        return None
    return numerator / denominator


def fmt_ratio(value: float | None, digits: int = 3) -> str:
    return "N/A（分母為 0）" if value is None else f"{value:.{digits}f}"


def fmt_diff(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.3f}"


def build_window(name: str, games: list) -> dict:
    """對一個窗口計算事實。games 必須已依日期升冪排序。"""
    totals = {field: sum(g[field] for g in games) for field in COUNTING_FIELDS}

    batting_average = safe_ratio(totals["hits"], totals["at_bats"])
    # SLG = 壘打數 / 打數。total_bases 是官方欄位，可靠性已在 validation 中檢查
    slugging = safe_ratio(totals["total_bases"], totals["at_bats"])

    return {
        "window": name,
        "games": len(games),
        "first_game_date": games[0]["game_date"] if games else None,
        "last_game_date": games[-1]["game_date"] if games else None,
        "game_snos": [g["game_sno"] for g in games],
        "plate_appearances": totals["plate_appearances"],
        "at_bats": totals["at_bats"],
        "hits": totals["hits"],
        "walks": totals["walks"],
        "strikeouts": totals["strikeouts"],
        "home_runs": totals["home_runs"],
        "rbi": totals["rbi"],
        "total_bases": totals["total_bases"],
        "doubles": totals["doubles"],
        "triples": totals["triples"],
        "hit_by_pitch": totals["hit_by_pitch"],
        "batting_average": batting_average,
        "slugging": slugging,
        # 記錄 at_bats 為 0 的比賽，讓分母問題可被追溯
        "games_with_zero_at_bats": [
            g["game_sno"] for g in games if g["at_bats"] == 0
        ],
    }


def print_window(w: dict) -> None:
    print(f"\n--- {w['window']} ---")
    print(f"  games            : {w['games']}")
    print(f"  first_game_date  : {w['first_game_date']}")
    print(f"  last_game_date   : {w['last_game_date']}")
    print(f"  plate_appearances: {w['plate_appearances']}")
    print(f"  at_bats          : {w['at_bats']}")
    print(f"  hits             : {w['hits']}")
    print(f"  walks            : {w['walks']}")
    print(f"  strikeouts       : {w['strikeouts']}")
    print(f"  home_runs        : {w['home_runs']}")
    print(f"  rbi              : {w['rbi']}")
    print(f"  total_bases      : {w['total_bases']}")
    print(f"  batting_average  : {fmt_ratio(w['batting_average'])}  (= hits / at_bats"
          f" = {w['hits']} / {w['at_bats']})")
    print(f"  slugging         : {fmt_ratio(w['slugging'])}  (= total_bases / at_bats"
          f" = {w['total_bases']} / {w['at_bats']})")
    if w["games_with_zero_at_bats"]:
        print(f"  至少有一場 at_bats == 0，game_sno: {w['games_with_zero_at_bats']}")
    print(f"  game_snos        : {w['game_snos']}")


def print_comparison(season: dict, window: dict) -> None:
    avg_diff = None
    if season["batting_average"] is not None and window["batting_average"] is not None:
        avg_diff = window["batting_average"] - season["batting_average"]
    slg_diff = None
    if season["slugging"] is not None and window["slugging"] is not None:
        slg_diff = window["slugging"] - season["slugging"]

    print(f"\n--- {window['window']} vs Season-to-date ---")
    print(
        f"  AVG: {fmt_ratio(window['batting_average'])} vs "
        f"{fmt_ratio(season['batting_average'])}  差異 {fmt_diff(avg_diff)}"
    )
    print(
        f"  SLG: {fmt_ratio(window['slugging'])} vs "
        f"{fmt_ratio(season['slugging'])}  差異 {fmt_diff(slg_diff)}"
    )
    print("  OBP: 未計算。processed data 缺少犧牲飛球與故意四壞，無法可靠計算（見文件）")


def run_validation(all_games: list, season: dict, r15: dict, r10: dict) -> list:
    """回傳 (檢查項目, 是否通過, 說明) 的清單。"""
    checks: list[tuple[str, bool, str]] = []

    # 1. Recent 10 的 games == 10
    checks.append(("Recent 10 的 games == 10", r10["games"] == 10, f"實際 {r10['games']}"))

    # 2. Recent 15 的 games == 15
    checks.append(("Recent 15 的 games == 15", r15["games"] == 15, f"實際 {r15['games']}"))

    # 3. Recent 10 是 Recent 15 的子集合
    is_subset = set(r10["game_snos"]).issubset(set(r15["game_snos"]))
    checks.append(
        ("Recent 10 是 Recent 15 的子集合", is_subset,
         "是子集合" if is_subset else f"差集 {set(r10['game_snos']) - set(r15['game_snos'])}")
    )

    # 4. 日期排序正確（升冪、無逆序）
    dates = [g["game_date"] for g in all_games]
    sorted_ok = all(dates[i] <= dates[i + 1] for i in range(len(dates) - 1))
    checks.append(
        ("排序後 game_date 為升冪", sorted_ok,
         f"{dates[0]} ~ {dates[-1]}" if sorted_ok else "存在逆序")
    )

    # 5. 沒有重複 game_sno
    snos = [g["game_sno"] for g in all_games]
    no_dup = len(snos) == len(set(snos))
    dup_list = sorted({s for s in snos if snos.count(s) > 1})
    checks.append(
        ("game_sno 無重複", no_dup, "無重複" if no_dup else f"重複：{dup_list}")
    )

    # 6. AVG == H / AB（用獨立算式重算一次比對）
    avg_ok = True
    avg_detail = []
    for w in (season, r15, r10):
        expected = safe_ratio(w["hits"], w["at_bats"])
        same = (expected is None and w["batting_average"] is None) or (
            expected is not None
            and w["batting_average"] is not None
            and abs(expected - w["batting_average"]) < 1e-12
        )
        avg_ok = avg_ok and same
        avg_detail.append(f"{w['window']}={fmt_ratio(w['batting_average'])}")
    checks.append(("AVG == hits / at_bats", avg_ok, "、".join(avg_detail)))

    # 7. Season totals 與 processed data 逐筆加總一致（獨立重算）
    mismatches = []
    for field in COUNTING_FIELDS:
        direct = 0
        for g in all_games:
            direct += g[field]
        if direct != season[field]:
            mismatches.append(f"{field}: window={season[field]} direct={direct}")
    checks.append(
        ("Season totals 與逐筆加總一致", not mismatches,
         "全部一致" if not mismatches else "；".join(mismatches))
    )

    # 8. Season games 數量 == processed data 筆數
    checks.append(
        ("Season games == processed data 筆數",
         season["games"] == len(all_games),
         f"{season['games']} vs {len(all_games)}")
    )

    # 9. total_bases 內部一致性：TB 應等於 hits + 2B + 2*3B + 3*HR
    tb_bad = []
    for g in all_games:
        expected_tb = g["hits"] + g["doubles"] + 2 * g["triples"] + 3 * g["home_runs"]
        if expected_tb != g["total_bases"]:
            tb_bad.append(
                f"game_sno {g['game_sno']}({g['game_date']}): "
                f"官方 {g['total_bases']} vs 推算 {expected_tb}"
            )
    checks.append(
        ("total_bases 與安打組成一致（TB = H + 2B + 2*3B + 3*HR）",
         not tb_bad,
         "全部一致" if not tb_bad else "；".join(tb_bad))
    )

    # 10. hits >= 2B + 3B + HR、at_bats <= plate_appearances 等基本合理性
    logic_bad = []
    for g in all_games:
        if g["hits"] < g["doubles"] + g["triples"] + g["home_runs"]:
            logic_bad.append(f"game_sno {g['game_sno']}: hits 少於長打數合計")
        if g["at_bats"] > g["plate_appearances"]:
            logic_bad.append(f"game_sno {g['game_sno']}: at_bats 大於 plate_appearances")
        if g["hits"] > g["at_bats"]:
            logic_bad.append(f"game_sno {g['game_sno']}: hits 大於 at_bats")
    checks.append(
        ("逐場基本合理性（hits/長打/打席關係）", not logic_bad,
         "全部通過" if not logic_bad else "；".join(logic_bad))
    )

    # 11. 交叉核對：我們算出的 season AVG，與最後一場官方累計 Avg 是否相符
    #     官方 batting_average 是「該場結束時的累計季打擊率」，只用來核對，不用來計算
    official_last = all_games[-1]["batting_average"]
    ours = season["batting_average"]
    cross_ok = (
        ours is not None
        and official_last is not None
        and abs(round(ours, 3) - official_last) < 1e-9
    )
    checks.append(
        ("自算 season AVG 與官方最後一場累計 Avg 相符（取 3 位小數）",
         cross_ok,
         f"自算 {fmt_ratio(ours)} vs 官方 {official_last}")
    )

    return checks


def print_ordering_observation(all_games: list) -> None:
    """記錄 game_sno 並非隨日期單調遞增（延賽改期造成），不做修正。"""
    out_of_order = [
        (all_games[i]["game_sno"], all_games[i]["game_date"])
        for i in range(1, len(all_games))
        if all_games[i]["game_sno"] < all_games[i - 1]["game_sno"]
    ]
    print("\n" + "=" * 78)
    print("排序觀察（保留記錄，未做任何修正）")
    print("=" * 78)
    if out_of_order:
        print(f"  依 game_date 升冪排序後，有 {len(out_of_order)} 個位置的 game_sno 比前一筆小：")
        for sno, d in out_of_order:
            print(f"    game_sno {sno}　game_date {d}")
        print("  → game_sno 不是時間順序，排序必須用 game_date，不能用 game_sno。")
        print("  → 這些 game_sno 與 Step 4 記錄的延賽改期場次一致。")
    else:
        print("  game_sno 隨 game_date 單調遞增。")


def main() -> None:
    raw = load_game_logs()
    games = sort_by_date(raw)

    print("=" * 78)
    print(f"Evidence Report：{PLAYER_LABEL}　{SEASON_LABEL}")
    print(f"資料來源：{PLAYER_PATH.relative_to(PLAYER_PATH.parent.parent.parent)}")
    print(f"資料筆數：{len(games)}（每筆 = 一場實際出賽）")
    print("注意：以下所有 batting_average 均由 hits / at_bats 計算，")
    print("　　　未使用官方逐場資料中的 batting_average 欄位。")
    print("=" * 78)

    season = build_window("Season-to-date", games)
    r15 = build_window("Recent 15 Games", games[-15:])
    r10 = build_window("Recent 10 Games", games[-10:])

    print("\n" + "=" * 78)
    print("窗口事實")
    print("=" * 78)
    for w in (season, r15, r10):
        print_window(w)

    print("\n" + "=" * 78)
    print("與 Season-to-date 的差異")
    print("=" * 78)
    print_comparison(season, r15)
    print_comparison(season, r10)

    print_ordering_observation(games)

    print("\n" + "=" * 78)
    print("Data validation")
    print("=" * 78)
    checks = run_validation(games, season, r15, r10)
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/FIRST_EVIDENCE_ANALYSIS.md。")


if __name__ == "__main__":
    main()

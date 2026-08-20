"""張育成 2026 年 10 場滾動基準（Step 6）。

目的：用球員自己整季的 10 場滾動窗口，建立「他自身表現的正常波動範圍」，
之後才有依據判斷近期數字是否真的偏離常態。

本階段**只建立客觀 baseline**：
    - 不設任何門檻，不判斷狀態好壞，不產生自然語言結論。
    - 不使用 LLM、不連網、不用 pandas、不修改 processed data。

窗口定義：依 game_date 升冪排序後的**連續實際出賽場次**，
不是日曆日期。第 1 個窗口是第 1~10 場出賽，第 2 個是第 2~11 場，依此類推。

用法：
    python src/rolling_baseline.py
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 從 Step 5 匯入，用來做跨實作交叉核對（兩套獨立算法互相對帳）
from player_form_analysis import build_window as step5_build_window  # noqa: E402
from player_form_analysis import sort_by_date as step5_sort  # noqa: E402

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
PLAYER_PATH = PROCESSED_DIR / "zhang_yucheng_game_logs_2026.json"

WINDOW_SIZE = 10
PLAYER_LABEL = "張育成（Acnt 0000006888）"
SEASON_LABEL = "2026 一軍例行賽"


def load_game_logs() -> list:
    if not PLAYER_PATH.exists():
        raise SystemExit(
            f"找不到 {PLAYER_PATH}\n請先執行：python src/build_processed_data.py"
        )
    return json.loads(PLAYER_PATH.read_text(encoding="utf-8"))


def file_fingerprint(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def ratio(numerator: int, denominator: int) -> float | None:
    """分母為 0 回傳 None，不填 0，不除零。"""
    if denominator == 0:
        return None
    return numerator / denominator


def fmt(value: float | None, digits: int = 3) -> str:
    return "None" if value is None else f"{value:.{digits}f}"


def build_rolling_windows(games: list, size: int = WINDOW_SIZE) -> list:
    """games 必須已依 game_date 升冪排序。"""
    windows = []
    for start in range(len(games) - size + 1):
        chunk = games[start : start + size]
        at_bats = sum(g["at_bats"] for g in chunk)
        hits = sum(g["hits"] for g in chunk)
        total_bases = sum(g["total_bases"] for g in chunk)
        windows.append(
            {
                "index": start + 1,  # 1-based，第 N 個窗口
                "start_game_date": chunk[0]["game_date"],
                "end_game_date": chunk[-1]["game_date"],
                "games": len(chunk),
                "game_snos": [g["game_sno"] for g in chunk],
                "plate_appearances": sum(g["plate_appearances"] for g in chunk),
                "at_bats": at_bats,
                "hits": hits,
                "total_bases": total_bases,
                "batting_average": ratio(hits, at_bats),
                "slugging_percentage": ratio(total_bases, at_bats),
            }
        )
    return windows


def summarise(values: list[float], label: str) -> dict:
    """對一組數值做描述統計。values 必須已排除 None。"""
    return {
        "label": label,
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        # pstdev：把這 68 個觀測值當成「已觀測到的全體」來描述其離散程度。
        # 不用 stdev（樣本標準差）作為主要指標，因為滾動窗口高度重疊、
        # 彼此不獨立，樣本標準差的推論意義並不成立。兩者都列出以便檢視。
        "pstdev": statistics.pstdev(values),
        "stdev_sample": statistics.stdev(values) if len(values) > 1 else None,
    }


def print_summary(s: dict) -> None:
    print(f"\n--- {s['label']} baseline（n = {s['n']} 個窗口）---")
    print(f"  minimum : {fmt(s['min'])}")
    print(f"  maximum : {fmt(s['max'])}")
    print(f"  mean    : {fmt(s['mean'])}")
    print(f"  median  : {fmt(s['median'])}")
    print(f"  母體標準差 pstdev      : {fmt(s['pstdev'], 4)}")
    print(f"  樣本標準差 stdev（參考）: {fmt(s['stdev_sample'], 4)}")


def rank_and_percentile(values: list[float], target: float) -> dict:
    """回傳排名與經驗百分位，計算方式明確寫出，不使用模糊的「異常程度」。

    rank_desc          : 由大到小排名，1 = 最高。同值視為並列（取最佳名次）。
    below / equal / above : 與 target 比較的窗口個數（含 target 自身，計入 equal）。
    percentile_rank    : (below + equal) / n * 100
                         即「有多少比例的窗口 <= target」，含 target 自身。
    percentile_strict  : below / n * 100
                         即「有多少比例的窗口 < target」，不含並列。
    """
    n = len(values)
    below = sum(1 for v in values if v < target)
    equal = sum(1 for v in values if v == target)
    above = sum(1 for v in values if v > target)
    return {
        "n": n,
        "rank_desc": above + 1,
        "below": below,
        "equal": equal,
        "above": above,
        "percentile_rank": (below + equal) / n * 100,
        "percentile_strict": below / n * 100,
    }


def print_position(name: str, value: float | None, pos: dict) -> None:
    print(f"\n  {name} = {fmt(value)}")
    print(f"    排名（由大到小）    : 第 {pos['rank_desc']} / {pos['n']}")
    print(f"    低於它的窗口數      : {pos['below']}")
    print(f"    與它相同的窗口數    : {pos['equal']}（含自己）")
    print(f"    高於它的窗口數      : {pos['above']}")
    print(
        f"    percentile_rank     : {pos['percentile_rank']:.1f}%"
        f"  = ({pos['below']} + {pos['equal']}) / {pos['n']} × 100"
    )
    print(
        f"    percentile_strict   : {pos['percentile_strict']:.1f}%"
        f"  = {pos['below']} / {pos['n']} × 100"
    )


def run_validation(games: list, windows: list, fingerprint_before: tuple) -> list:
    checks: list[tuple[str, bool, str]] = []
    expected_count = len(games) - WINDOW_SIZE + 1

    # 1. rolling window 數量
    checks.append(
        (f"rolling window 數量 == {expected_count}（= {len(games)} - {WINDOW_SIZE} + 1）",
         len(windows) == expected_count == 68,
         f"實際 {len(windows)}，預期 {expected_count}")
    )

    # 2. 每個 window 都是 10 games
    bad_size = [w["index"] for w in windows if w["games"] != WINDOW_SIZE]
    checks.append(
        (f"每個 window 的 games == {WINDOW_SIZE}", not bad_size,
         "全部符合" if not bad_size else f"不符合的窗口 index：{bad_size}")
    )

    # 3. 每個 window 內 game_sno 無重複
    bad_dup = [
        w["index"] for w in windows if len(set(w["game_snos"])) != len(w["game_snos"])
    ]
    checks.append(
        ("每個 window 內 game_sno 無重複", not bad_dup,
         "全部無重複" if not bad_dup else f"有重複的窗口 index：{bad_dup}")
    )

    # 4. window 日期連續且正確
    #    (a) 窗口內日期為升冪
    #    (b) 窗口的起訖日期與排序後原始資料的對應切片一致
    #    (c) 相鄰窗口的起始日期為非遞減
    bad_date = []
    for w in windows:
        chunk = games[w["index"] - 1 : w["index"] - 1 + WINDOW_SIZE]
        dates = [g["game_date"] for g in chunk]
        if any(dates[i] > dates[i + 1] for i in range(len(dates) - 1)):
            bad_date.append(f"窗口 {w['index']} 內部日期非升冪")
        if w["start_game_date"] != dates[0] or w["end_game_date"] != dates[-1]:
            bad_date.append(f"窗口 {w['index']} 起訖日期與原始切片不符")
        if w["game_snos"] != [g["game_sno"] for g in chunk]:
            bad_date.append(f"窗口 {w['index']} game_sno 與原始切片不符")
    for i in range(1, len(windows)):
        if windows[i]["start_game_date"] < windows[i - 1]["start_game_date"]:
            bad_date.append(f"窗口 {windows[i]['index']} 起始日期早於前一個窗口")
    checks.append(
        ("window 日期連續且正確", not bad_date,
         "全部正確" if not bad_date else "；".join(bad_date[:5]))
    )

    # 5. 最新 window == Step 5 的 Recent 10（用 Step 5 的程式碼獨立算一次）
    step5_recent10 = step5_build_window("Recent 10 Games", step5_sort(games)[-10:])
    latest = windows[-1]
    same_snos = latest["game_snos"] == step5_recent10["game_snos"]
    checks.append(
        ("最新 window 的 game_sno 清單 == Step 5 Recent 10", same_snos,
         "完全相同" if same_snos
         else f"本階段 {latest['game_snos']} vs Step 5 {step5_recent10['game_snos']}")
    )

    # 6. 最新 window 的 AVG / SLG 與 Step 5 完全一致
    avg_same = (
        latest["batting_average"] is not None
        and step5_recent10["batting_average"] is not None
        and abs(latest["batting_average"] - step5_recent10["batting_average"]) < 1e-12
    )
    slg_same = (
        latest["slugging_percentage"] is not None
        and step5_recent10["slugging"] is not None
        and abs(latest["slugging_percentage"] - step5_recent10["slugging"]) < 1e-12
    )
    checks.append(
        ("最新 window 的 AVG 與 Step 5 一致", avg_same,
         f"本階段 {fmt(latest['batting_average'])} vs "
         f"Step 5 {fmt(step5_recent10['batting_average'])}")
    )
    checks.append(
        ("最新 window 的 SLG 與 Step 5 一致", slg_same,
         f"本階段 {fmt(latest['slugging_percentage'])} vs "
         f"Step 5 {fmt(step5_recent10['slugging'])}")
    )

    # 7 & 8. AVG = H / AB、SLG = TB / AB（對全部 68 個窗口逐一重算比對）
    bad_avg, bad_slg = [], []
    for w in windows:
        exp_avg = ratio(w["hits"], w["at_bats"])
        exp_slg = ratio(w["total_bases"], w["at_bats"])
        if not (
            (exp_avg is None and w["batting_average"] is None)
            or (exp_avg is not None and abs(exp_avg - w["batting_average"]) < 1e-12)
        ):
            bad_avg.append(w["index"])
        if not (
            (exp_slg is None and w["slugging_percentage"] is None)
            or (exp_slg is not None and abs(exp_slg - w["slugging_percentage"]) < 1e-12)
        ):
            bad_slg.append(w["index"])
    checks.append(
        ("所有窗口 AVG == hits / at_bats", not bad_avg,
         f"68 個窗口全部相符" if not bad_avg else f"不符：{bad_avg}")
    )
    checks.append(
        ("所有窗口 SLG == total_bases / at_bats", not bad_slg,
         f"68 個窗口全部相符" if not bad_slg else f"不符：{bad_slg}")
    )

    # 9. 未修改原始資料（比對執行前後的 sha256 與檔案大小）
    fingerprint_after = file_fingerprint(PLAYER_PATH)
    checks.append(
        ("未修改 processed data（sha256 與檔案大小不變）",
         fingerprint_before == fingerprint_after,
         f"sha256 前 8 碼 {fingerprint_before[0][:8]}，大小 {fingerprint_before[1]} bytes")
    )

    # 附加：at_bats == 0 的窗口（比率為 None）
    invalid = [w["index"] for w in windows if w["batting_average"] is None]
    checks.append(
        ("是否存在 at_bats == 0 的窗口（比率為 None）", True,
         "沒有" if not invalid else f"有，窗口 index：{invalid}")
    )

    return checks


def main() -> None:
    fingerprint_before = file_fingerprint(PLAYER_PATH)
    raw = load_game_logs()
    games = sorted(raw, key=lambda r: (r["game_date"], r["game_sno"]))

    print("=" * 92)
    print(f"Rolling Baseline Report：{PLAYER_LABEL}　{SEASON_LABEL}")
    print(f"資料來源：data/processed/{PLAYER_PATH.name}")
    print(f"實際出賽場次：{len(games)}　窗口大小：{WINDOW_SIZE} 場（實際出賽，非日曆日）")
    print("=" * 92)

    windows = build_rolling_windows(games)
    print(f"\n產生 rolling windows：{len(windows)} 個")

    # ---------- 全部窗口明細 ----------
    print("\n" + "=" * 92)
    print("全部 rolling windows 明細（每個窗口 = 連續 10 場實際出賽）")
    print("=" * 92)
    print(f"{'#':>3}  {'start':<11} {'end':<11} {'PA':>4} {'AB':>4} {'H':>3} "
          f"{'TB':>4} {'AVG':>6} {'SLG':>6}")
    for w in windows:
        print(
            f"{w['index']:>3}  {w['start_game_date']:<11} {w['end_game_date']:<11} "
            f"{w['plate_appearances']:>4} {w['at_bats']:>4} {w['hits']:>3} "
            f"{w['total_bases']:>4} {fmt(w['batting_average']):>6} "
            f"{fmt(w['slugging_percentage']):>6}"
        )

    # ---------- Baseline summary ----------
    avg_values = [w["batting_average"] for w in windows if w["batting_average"] is not None]
    slg_values = [
        w["slugging_percentage"] for w in windows if w["slugging_percentage"] is not None
    ]

    print("\n" + "=" * 92)
    print("Baseline summary")
    print("=" * 92)
    avg_summary = summarise(avg_values, "AVG")
    slg_summary = summarise(slg_values, "SLG")
    print_summary(avg_summary)
    print_summary(slg_summary)

    # 極值出現在哪個窗口，方便追溯
    def locate(values_key: str, target: float) -> list[str]:
        return [
            f"#{w['index']} {w['start_game_date']}~{w['end_game_date']}"
            for w in windows
            if w[values_key] == target
        ]

    print("\n  極值所在窗口（可追溯）：")
    print(f"    AVG min {fmt(avg_summary['min'])} : {', '.join(locate('batting_average', avg_summary['min']))}")
    print(f"    AVG max {fmt(avg_summary['max'])} : {', '.join(locate('batting_average', avg_summary['max']))}")
    print(f"    SLG min {fmt(slg_summary['min'])} : {', '.join(locate('slugging_percentage', slg_summary['min']))}")
    print(f"    SLG max {fmt(slg_summary['max'])} : {', '.join(locate('slugging_percentage', slg_summary['max']))}")

    # ---------- Recent 10 位置 ----------
    latest = windows[-1]
    print("\n" + "=" * 92)
    print("Recent 10 window（最新的 10 場）在整季 rolling windows 中的位置")
    print("=" * 92)
    print(f"  窗口 #{latest['index']}　{latest['start_game_date']} ~ {latest['end_game_date']}")
    print(f"  game_snos: {latest['game_snos']}")
    print(f"  PA {latest['plate_appearances']}　AB {latest['at_bats']}　"
          f"H {latest['hits']}　TB {latest['total_bases']}")
    print_position("AVG", latest["batting_average"],
                   rank_and_percentile(avg_values, latest["batting_average"]))
    print_position("SLG", latest["slugging_percentage"],
                   rank_and_percentile(slg_values, latest["slugging_percentage"]))
    print("\n  註：以上只是位置描述。本階段不定義任何門檻，")
    print("  　　也不判斷這個位置代表狀態好或壞。")

    # ---------- Validation ----------
    print("\n" + "=" * 92)
    print("Validation")
    print("=" * 92)
    checks = run_validation(games, windows, fingerprint_before)
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/ROLLING_BASELINE_ANALYSIS.md。")


if __name__ == "__main__":
    main()

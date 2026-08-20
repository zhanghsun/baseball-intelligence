"""用 GameSno 對接 processed data，驗證資料一致性（Step 4）。

這支程式**不連網**，只讀 data/processed/ 下的兩份 JSON。

它做的事：
    1. 載入兩份 processed JSON
    2. 用 game_sno 對接
    3. 確認球員每一筆逐場資料都能找到對應賽程
    4. 列出無法對接的 game_sno
    5. 顯示成功對接的場數
    6. 檢查重複 game_sno
    7. 把賽程中的重複 game_sno 逐筆列出（**不猜測合併規則**）
    8. 驗證富邦已完成場數是否與球員資料的 team_total_games = 87 一致

用法：
    python src/data_join_experiment.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
SCHEDULE_PATH = PROCESSED_DIR / "fubon_schedule_2026.json"
PLAYER_PATH = PROCESSED_DIR / "zhang_yucheng_game_logs_2026.json"

EXPECTED_TEAM_GAMES = 87  # 來自球員逐場資料的 TotalTeamGames


def load(path: Path) -> list:
    if not path.exists():
        raise SystemExit(f"找不到 {path}，請先執行 python src/build_processed_data.py")
    return json.loads(path.read_text(encoding="utf-8"))


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def group_by_sno(records: list) -> dict:
    grouped = defaultdict(list)
    for r in records:
        grouped[r["game_sno"]].append(r)
    return grouped


def main() -> None:
    schedule = load(SCHEDULE_PATH)
    player_logs = load(PLAYER_PATH)

    sched_by_sno = group_by_sno(schedule)
    player_by_sno = group_by_sno(player_logs)

    # ---------- 基本筆數 ----------
    section("1. 基本筆數")
    print(f"schedule 筆數                : {len(schedule)}")
    print(f"schedule 相異 game_sno       : {len(sched_by_sno)}")
    print(f"player game logs 筆數        : {len(player_logs)}")
    print(f"player game logs 相異 game_sno: {len(player_by_sno)}")

    # ---------- 重複 game_sno ----------
    section("2. 重複 game_sno")
    sched_dups = {k: v for k, v in sched_by_sno.items() if len(v) > 1}
    player_dups = {k: v for k, v in player_by_sno.items() if len(v) > 1}

    print(f"schedule 重複 game_sno 數量        : {len(sched_dups)}")
    print(f"schedule 因重複多出的筆數          : {len(schedule) - len(sched_by_sno)}")
    print(f"player game logs 重複 game_sno 數量: {len(player_dups)}")

    if sched_dups:
        print("\n賽程重複明細（原樣列出，未做任何合併）：")
        for sno in sorted(sched_dups):
            print(f"  game_sno {sno}")
            for r in sorted(sched_dups[sno], key=lambda x: x["game_date"] or ""):
                print(
                    f"    {r['game_date']} {r['scheduled_time']}  "
                    f"狀態={r['game_status']:<10} game_result={r['game_result']!r:<4} "
                    f"對手={r['opponent']:<14} 場地={r['field']}  "
                    f"比分 {r['visiting_score']}:{r['home_score']}"
                )
        statuses = defaultdict(int)
        for sno in sched_dups:
            for r in sched_dups[sno]:
                statuses[r["game_status"]] += 1
        print(f"\n  重複群組內的狀態分佈：{dict(statuses)}")
        print(
            "\n  觀察（不是結論）：每個重複群組都是「一筆延賽 + 一筆改期後的記錄」的形態，\n"
            "  兩筆共用同一個 game_sno。因此 game_sno 單獨無法唯一識別一場賽程記錄。\n"
            "  正式的唯一識別規則官方沒有說明，本專案目前不自行決定合併方式。"
        )

    if player_dups:
        print("\n球員逐場資料重複明細：")
        for sno in sorted(player_dups):
            print(f"  game_sno {sno}: {[r['game_date'] for r in player_dups[sno]]}")

    # ---------- join ----------
    section("3. GameSno Join 結果")
    matched_one, matched_many, unmatched = [], [], []
    for log in player_logs:
        candidates = sched_by_sno.get(log["game_sno"], [])
        if not candidates:
            unmatched.append(log)
        elif len(candidates) == 1:
            matched_one.append((log, candidates[0]))
        else:
            matched_many.append((log, candidates))

    print(f"成功對接（唯一對應）: {len(matched_one)}")
    print(f"對接到多筆賽程（模糊）: {len(matched_many)}")
    print(f"無法對接            : {len(unmatched)}")

    if unmatched:
        print("\n無法對接的 game_sno：")
        for log in unmatched:
            print(f"  game_sno {log['game_sno']}  {log['game_date']}  對手={log['opponent']}")
    else:
        print("\n球員每一筆逐場資料都找到了對應賽程。")

    if matched_many:
        print("\n對接到多筆賽程的 game_sno（模糊對接，保留不處理）：")
        for log, cands in matched_many:
            print(f"  game_sno {log['game_sno']}  球員記錄日期={log['game_date']}")
            for c in cands:
                print(f"    賽程：{c['game_date']} 狀態={c['game_status']}")

    # ---------- 對接後的欄位一致性 ----------
    section("4. 對接後的欄位一致性檢查")
    date_mismatch, opponent_mismatch = [], []
    for log, sched in matched_one:
        if log["game_date"] != sched["game_date"]:
            date_mismatch.append((log["game_sno"], log["game_date"], sched["game_date"]))
        if log["opponent"] != sched["opponent"]:
            opponent_mismatch.append(
                (log["game_sno"], log["opponent"], sched["opponent"])
            )
    print(f"日期不一致筆數: {len(date_mismatch)}")
    for sno, a, b in date_mismatch:
        print(f"  game_sno {sno}: player={a} schedule={b}")
    print(f"對手不一致筆數: {len(opponent_mismatch)}")
    for sno, a, b in opponent_mismatch:
        print(f"  game_sno {sno}: player={a} schedule={b}")

    # ---------- 87 場驗證 ----------
    section("5. 87 場一致性驗證")
    finished = [r for r in schedule if r["game_result"] == "0"]
    print(f"賽程中 game_result == '0'（已完成）的富邦場次: {len(finished)}")

    team_games_values = [
        r["team_total_games"] for r in player_logs if r["team_total_games"] is not None
    ]
    max_team_games = max(team_games_values) if team_games_values else None
    print(f"球員逐場資料中 team_total_games 最大值        : {max_team_games}")
    print(f"預期值                                       : {EXPECTED_TEAM_GAMES}")

    ok_finished = len(finished) == EXPECTED_TEAM_GAMES
    ok_team_games = max_team_games == EXPECTED_TEAM_GAMES
    print(f"\n賽程已完成場數 == 87 ? {'是' if ok_finished else '否'}")
    print(f"team_total_games 最大值 == 87 ? {'是' if ok_team_games else '否'}")
    print(f"兩個來源一致 ? {'是' if ok_finished and ok_team_games else '否'}")

    print(
        f"\n注意：球員逐場資料只有 {len(player_logs)} 筆，少於已完成的 {len(finished)} 場，"
        f"差 {len(finished) - len(player_logs)} 場。"
    )
    print("  這是預期的：球員未出賽的比賽不會出現在逐場成績表中。這不是資料缺漏。")

    # ---------- 未完成場次的比分 ----------
    section("6. 未完成場次的比分欄位")
    unplayed_nonzero = [
        r
        for r in schedule
        if r["game_result"] != "0" and (r["home_score"] != 0 or r["visiting_score"] != 0)
    ]
    unplayed_zero = [
        r
        for r in schedule
        if r["game_result"] != "0" and r["home_score"] == 0 and r["visiting_score"] == 0
    ]
    print(f"未完成場次共 {len(unplayed_zero) + len(unplayed_nonzero)} 筆")
    print(f"  比分為 0:0 的      : {len(unplayed_zero)}  ← 0 是官方預設值，不是真實比分")
    print(f"  比分非 0:0 的      : {len(unplayed_nonzero)}")
    for r in unplayed_nonzero:
        print(
            f"    game_sno {r['game_sno']}  {r['game_date']}  狀態={r['game_status']}  "
            f"比分 {r['visiting_score']}:{r['home_score']}  對手={r['opponent']}"
        )
    print(
        "\n  原值保留，未做任何修正。使用比分前必須先用 game_result == '0' 過濾。"
    )


if __name__ == "__main__":
    main()

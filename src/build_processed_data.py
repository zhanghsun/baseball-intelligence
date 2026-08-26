"""建立第一份 processed data（Step 4）。

把 Step 2 / Step 3 已驗證的官方資料取得方式，落地成兩份乾淨的 JSON：

    data/processed/fubon_schedule_2026.json          富邦悍將 2026 一軍例行賽賽程
    data/processed/zhang_yucheng_game_logs_2026.json 張育成 2026 一軍例行賽逐場打擊

原則：
    - 直接沿用 src/data_source_experiment.py 與 src/schedule_source_experiment.py 的取得邏輯，
      不重新研究 API、不新增抽象層。
    - **只挑選目前專案真正需要的欄位**，不整包複製原始 response。
    - **不修正任何異常值**。發現異常一律保留原值並印出來，讓它進入資料品質報告。
    - 這不是 ETL pipeline，是一支手動執行的落地腳本。

執行成本：共 4 個 HTTP 請求（賽程 2 個、球員逐場 2 個）。

用法：
    python src/build_processed_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_source_experiment import fetch_follow_score  # noqa: E402
from schedule_source_experiment import fetch_year_schedule  # noqa: E402

# 球員身分與資料路徑的唯一來源（Step 29B）
import player_registry as registry  # noqa: E402

# ---- 以下全部由 registry 衍生，本模組不再自己宣告球員身分 ----
_ACTIVE_PLAYER_ID = registry.default_player_id()
_SUBJECT = registry.subject(_ACTIVE_PLAYER_ID)
_DATA_PATHS = registry.data_paths(_ACTIVE_PLAYER_ID)

YEAR = _SUBJECT["season"]
KIND_CODE = _SUBJECT["kind_code"]
FUBON_TEAM_CODE = _SUBJECT["team_code"]
PLAYER_ACNT = _SUBJECT["player_acnt"]

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
SCHEDULE_OUT = _DATA_PATHS["team_schedule"]
PLAYER_OUT = _DATA_PATHS["player_log"]

# GameResult 代碼對照，取自賽程頁 Vue 模板的判斷式
GAME_STATUS = {
    "": "未開打或進行中",
    "0": "已完成",
    "1": "延賽",
    "2": "保留",
    "4": "取消",
}


def iso_date(value: str | None) -> str | None:
    """'2026-08-18T00:00:00' -> '2026-08-18'"""
    if not value:
        return None
    return value[:10]


def iso_time(value: str | None) -> str | None:
    """'2026-08-21T18:35:00' -> '18:35'"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return None


def build_schedule(raw_games: list) -> tuple[list, list]:
    """挑出富邦相關場次，轉成 processed 格式。回傳 (records, anomalies)。"""
    anomalies: list[str] = []
    records = []

    for g in raw_games:
        home_code = g.get("HomeTeamCode")
        visiting_code = g.get("VisitingTeamCode")
        if FUBON_TEAM_CODE not in (home_code, visiting_code):
            continue

        is_home = home_code == FUBON_TEAM_CODE
        game_result = g.get("GameResult", "")

        # 保留但記錄：PreExeDate 的日期與 GameDate 不一致（延賽改期可能造成）
        pre_date = iso_date(g.get("PreExeDate"))
        game_date = iso_date(g.get("GameDate"))
        if pre_date and game_date and pre_date != game_date:
            anomalies.append(
                f"GameSno {g.get('GameSno')}：GameDate={game_date} 與 "
                f"PreExeDate 日期={pre_date} 不一致（狀態={GAME_STATUS.get(game_result)}）"
            )

        records.append(
            {
                "game_sno": g.get("GameSno"),
                "game_date": game_date,
                "scheduled_time": iso_time(g.get("PreExeDate")),
                "home_team": g.get("HomeTeamName"),
                "visiting_team": g.get("VisitingTeamName"),
                "opponent": g.get("VisitingTeamName") if is_home else g.get("HomeTeamName"),
                "is_home": is_home,
                "field": g.get("FieldAbbe"),
                "game_status": GAME_STATUS.get(game_result, f"未知({game_result})"),
                "home_score": g.get("HomeScore"),
                "visiting_score": g.get("VisitingScore"),
                "game_result": game_result,
                "home_pitcher_acnt": g.get("HomePitcherAcnt"),
                "visiting_pitcher_acnt": g.get("VisitingPitcherAcnt"),
            }
        )

    # 保留但記錄：未開打場次的比分是 0，不是 null，不可當成真實比分
    zero_score_unplayed = [
        r["game_sno"]
        for r in records
        if r["game_result"] != "0" and (r["home_score"] != 0 or r["visiting_score"] != 0)
    ]
    if zero_score_unplayed:
        anomalies.append(
            f"未完成場次中出現非 0 比分：GameSno {zero_score_unplayed}"
        )

    records.sort(key=lambda r: (r["game_date"] or "", r["game_sno"] or 0))
    return records, anomalies


def build_player_logs(raw_rows: list) -> list:
    """轉成 processed 格式。

    欄位取捨說明：
      - at_bats 對應官網 HitCnt（打數），hits 對應 HittingCnt（安打）。官網命名容易搞反。
      - batting_average 是官網 Avg，為「該場結束時的累計季打擊率」，不是單場打擊率。
      - team_total_games 對應 TotalTeamGames，保留是因為 Step 4 需要它做 87 場一致性驗證。
      - 官網另有 singles / 盜壘 / 犧短犧飛 / 故意四壞 / 守備欄位，目前用不到，刻意不收。
    """
    records = [
        {
            "game_sno": r.get("GameSno"),
            "game_date": iso_date(r.get("GameDate")),
            "opponent": r.get("FightTeamAbbrName"),
            "plate_appearances": r.get("PlateAppearances"),
            "at_bats": r.get("HitCnt"),
            "hits": r.get("HittingCnt"),
            "doubles": r.get("TwoBaseHitCnt"),
            "triples": r.get("ThreeBaseHitCnt"),
            "home_runs": r.get("HomeRunCnt"),
            "rbi": r.get("RunBattedINCnt"),
            "runs": r.get("ScoreCnt"),
            "walks": r.get("BasesONBallsCnt"),
            "strikeouts": r.get("StrikeOutCnt"),
            "hit_by_pitch": r.get("HitBYPitchCnt"),
            "total_bases": r.get("TotalBases"),
            "batting_average": r.get("Avg"),
            "team_total_games": r.get("TotalTeamGames"),
        }
        for r in raw_rows
    ]
    records.sort(key=lambda r: (r["game_date"] or "", r["game_sno"] or 0))
    return records


def write_json(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  寫出 {path.name}：{len(records)} 筆")


def main() -> None:
    print("=== 取得富邦悍將賽程 ===")
    raw_games = fetch_year_schedule(YEAR, KIND_CODE)
    schedule, anomalies = build_schedule(raw_games)
    print(f"  全league {len(raw_games)} 筆 -> 富邦相關 {len(schedule)} 筆")

    print("\n=== 取得張育成逐場打擊 ===")
    _, raw_rows = fetch_follow_score(PLAYER_ACNT, str(YEAR), KIND_CODE)
    player_logs = build_player_logs(raw_rows)
    print(f"  取得 {len(player_logs)} 筆")

    print("\n=== 寫出 processed data ===")
    write_json(SCHEDULE_OUT, schedule)
    write_json(PLAYER_OUT, player_logs)

    if anomalies:
        print("\n=== 建置過程發現的異常（已原值保留，未做任何修正）===")
        for a in anomalies:
            print("  - " + a)
    else:
        print("\n建置過程未發現異常。")


if __name__ == "__main__":
    main()

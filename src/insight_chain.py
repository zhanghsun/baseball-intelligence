"""Insight Chain Experiment（Step 14）。

它驗證什麼：現有資料能否可靠地組合成一條與下一場比賽有關的 evidence chain？

    球員近期狀態 → 下一場比賽 → 對手 → 預告先發投手 → 投手左右手 → 歷史 matchup

它**不**做什麼：
    - 不產生自然語言建議、不產生 recommendation、不產生 prediction
    - 不建立 ranking、score、weight、threshold、confidence score
    - 不使用 LLM
    - 不新增資料來源、不呼叫 /box/getlive、不發任何 HTTP 請求
    - 不修改 raw / processed data
    - **不為了讓 chain 看起來完整而猜測任何值**

最重要的設計原則：
    node 無法可靠建立時，**保留 node 並標示 blocked / unverified**，
    比填入猜測值重要。因此本 chain 會有 node 明確標示為
    `missing_required_data` 與 `blocked_by_unverified_upcoming_starter`。

決定性：
    「下一場比賽」不使用系統時鐘，而是以資料本身推導的參考日
    （富邦已完成比賽中最晚的 game_date）為基準。
    這讓 chain 在任何時間重跑都得到相同結果。

用法：
    python src/insight_chain.py
"""

from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# import candidate_insights 會安裝 socket guard，封鎖所有對外連線
from candidate_insights import (  # noqa: E402
    APART_CACHE_PATH,
    PLAYER_LOG_PATH,
    SUBJECT,
    build_context_candidates,
    build_context_evidence,
    build_pattern_candidates,
    build_season_baseline,
    build_trend_candidates,
    load_inputs,
    network_guard_active,
    sha256_of,
)
from evidence_sample_context import build_record, build_trend_components  # noqa: E402
from player_form_analysis import build_window, sort_by_date  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_PATH = ROOT / "data" / "processed" / "fubon_schedule_2026.json"

FUBON_TEAM_CODE = "AEO011"
PLAYER_NAME = "張育成"
SEASON = 2026

# ------------------------------------------------------------------ 受控詞彙

VERIFICATION_STATUS_VALUES = (
    "verified_cross_checked_with_prior_steps",
    "verified_against_processed_schedule",
    "unconfirmed_upcoming_starter_identity",
    "missing_required_data",
    "blocked_by_unverified_upcoming_starter",
)

NODE_STATUS_VALUES = ("usable", "unusable_blocked")

DERIVATION_VALUES = (
    "direct_source_value",
    "computed_from_source_counts",
    "selected_by_rule",
    "not_available",
)

EDGE_BASIS_CODES = (
    "current_form_requires_next_game_context",
    "schedule_game_record_contains_pitcher_account_identifier",
    "player_profile_provides_throwing_batting_handedness",
    "official_item_group_3_provides_season_cumulative_vs_hand_split",
)

# Step 7A 已驗證的 5 筆「已完成比賽先發投手 → 手別」對照，原樣記錄作為方法參考。
# 這些**不會**被用來推論下一場的投手手別。
STEP_7A_VERIFIED_REFERENCE = [
    {"game_sno": 261, "game_date": "2026-08-13", "pitcher_acnt": "0000007276",
     "pitcher_name": "伍立辰", "habit": "右投右打", "hand": "R"},
    {"game_sno": 262, "game_date": "2026-08-14", "pitcher_acnt": "0000005731",
     "pitcher_name": "布雷克", "habit": "右投右打", "hand": "R"},
    {"game_sno": 265, "game_date": "2026-08-15", "pitcher_acnt": "0000006848",
     "pitcher_name": "林詔恩", "habit": "左投左打", "hand": "L"},
    {"game_sno": 269, "game_date": "2026-08-16", "pitcher_acnt": "0000007290",
     "pitcher_name": "張宥謙", "habit": "右投右打", "hand": "R"},
    {"game_sno": 272, "game_date": "2026-08-18", "pitcher_acnt": "0000004624",
     "pitcher_name": "陳克羿", "habit": "右投左打", "hand": "R"},
]

# Step 8 文件記錄的 VS 左投 / VS 右投 數字，作為獨立交叉核對的期望值
STEP_8_EXPECTED = {
    "VS_RIGHT": {"plate_appearances": 258, "at_bats": 219, "hits": 68,
                 "total_bases": 122, "official_avg": 0.3105, "official_obp": 0.4031,
                 "official_slg": 0.557},
    "VS_LEFT": {"plate_appearances": 62, "at_bats": 54, "hits": 17,
                "total_bases": 23, "official_avg": 0.3148, "official_obp": 0.4032,
                "official_slg": 0.4259},
}

IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ------------------------------------------------------------------ 工具

def load_schedule() -> list:
    if not SCHEDULE_PATH.exists():
        raise SystemExit(
            f"找不到 {SCHEDULE_PATH}\n請先執行：python src/build_processed_data.py"
        )
    return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))


def prov(step: str, file: str, field: str | None, derivation: str,
         formula: str | None = None, note: str | None = None) -> dict:
    entry = {
        "source_step": step,
        "source_file": file,
        "source_field": field,
        "derivation": derivation,
    }
    if formula:
        entry["formula"] = formula
    if note:
        entry["note"] = note
    return entry


def fmt(v, digits: int = 8) -> str:
    return "null" if v is None else (f"{v:.{digits}f}" if isinstance(v, float) else str(v))


# ------------------------------------------------------------------ Node 1：Current Form

def window_evidence(window: dict, label: str) -> dict:
    """把 Step 5 的 build_window() 結果攤成 chain node 需要的欄位。"""
    return {
        "window": label,
        "games": window["games"],
        "plate_appearances": window["plate_appearances"],
        "at_bats": window["at_bats"],
        "hits": window["hits"],
        "home_runs": window["home_runs"],
        "rbi": window["rbi"],
        "total_bases": window["total_bases"],
        "batting_average": window["batting_average"],
        "slugging_percentage": window["slugging"],
        "on_base_percentage": None,
        "on_base_percentage_missing_reason": (
            "processed data 未收逐場犧牲飛球，OBP 無法按窗口計算（Step 5 / Step 11 已記錄）"
        ),
        "first_game_date": window["first_game_date"],
        "last_game_date": window["last_game_date"],
        "game_snos": list(window["game_snos"]),
    }


def build_current_form_node(logs: list) -> dict:
    games = sort_by_date(logs)
    season = build_window("Season-to-date", games)
    r15 = build_window("Recent 15 Games", games[-15:])
    r10 = build_window("Recent 10 Games", games[-10:])

    return {
        "node_id": "N1_CURRENT_FORM",
        "node_type": "current_form",
        "status": "usable",
        "verification_status": "verified_cross_checked_with_prior_steps",
        "evidence": {
            "player": PLAYER_NAME,
            "player_acnt": SUBJECT["player_acnt"],
            "season": SEASON,
            "kind_code": SUBJECT["kind_code"],
            "recent_10": window_evidence(r10, "RECENT_10"),
            "recent_15": window_evidence(r15, "RECENT_15"),
            "season_cumulative": window_evidence(season, "SEASON_CUMULATIVE"),
            "date_ranges": {
                "recent_10": [r10["first_game_date"], r10["last_game_date"]],
                "recent_15": [r15["first_game_date"], r15["last_game_date"]],
                "season_cumulative": [season["first_game_date"],
                                      season["last_game_date"]],
            },
        },
        "source_steps": ["Step 2", "Step 4", "Step 5", "Step 6", "Step 9"],
        "source_files": ["data/processed/zhang_yucheng_game_logs_2026.json"],
        "provenance": [
            prov("Step 4", "data/processed/zhang_yucheng_game_logs_2026.json",
                 "plate_appearances / at_bats / hits / home_runs / rbi / total_bases",
                 "computed_from_source_counts",
                 formula="窗口內逐場加總",
                 note="逐場原值來自 Step 2 的 POST /team/getfollowscore"),
            prov("Step 5", "src/player_form_analysis.py", "batting_average",
                 "computed_from_source_counts", formula="hits / at_bats",
                 note="直接呼叫 Step 5 的 build_window()，不另建定義"),
            prov("Step 5", "src/player_form_analysis.py", "slugging_percentage",
                 "computed_from_source_counts", formula="total_bases / at_bats"),
            prov("Step 5", "src/player_form_analysis.py", "game_snos",
                 "selected_by_rule",
                 formula="依 (game_date, game_sno) 升冪排序後取最後 N 場"),
            prov("Step 5", "-", "on_base_percentage", "not_available",
                 note="缺逐場犧牲飛球，回傳 null，不估算"),
        ],
    }


# ------------------------------------------------------------------ Node 2：Next Game

def pick_next_game(schedule: list) -> tuple[dict, str]:
    """以資料推導的參考日選出下一場未開打的富邦賽事。不使用系統時鐘。"""
    completed = [r for r in schedule if r["game_result"] == "0"]
    as_of = max(r["game_date"] for r in completed)
    unplayed = [
        r for r in schedule
        if r["game_result"] == "" and r["game_date"] > as_of
    ]
    unplayed.sort(key=lambda r: (r["game_date"], r["scheduled_time"] or "", r["game_sno"]))
    if not unplayed:
        raise SystemExit("processed schedule 中找不到未開打的富邦賽事")
    return unplayed[0], as_of


def build_next_game_node(game: dict, as_of: str) -> dict:
    return {
        "node_id": "N2_NEXT_GAME",
        "node_type": "next_game",
        "status": "usable",
        "verification_status": "verified_against_processed_schedule",
        "evidence": {
            "game_sno": game["game_sno"],
            "game_date": game["game_date"],
            "scheduled_time": game["scheduled_time"],
            "opponent": game["opponent"],
            "home_away": "home" if game["is_home"] else "away",
            "venue": game["field"],
            "game_status": game["game_status"],
            "game_result_code": game["game_result"],
            # 尚未開打，比分一律為 null。原始檔案中是 0，但那是官方預設值。
            "home_score": None,
            "visiting_score": None,
            "score_is_null_reason": (
                "game_result == '' 表示尚未開打。processed schedule 中的 "
                "home_score / visiting_score 為 0，那是官方預設值而非真實比分"
                "（Step 4 已記錄）。因此此處一律為 null。"
            ),
            "source_score_values_for_traceability": {
                "home_score_in_file": game["home_score"],
                "visiting_score_in_file": game["visiting_score"],
            },
        },
        "selection_rule": {
            "reference_date_basis": "富邦已完成比賽（game_result == '0'）中最晚的 game_date",
            "reference_date": as_of,
            "rule": (
                "從 game_result == '' 且 game_date > reference_date 的場次中，"
                "依 (game_date, scheduled_time, game_sno) 取最早的一場"
            ),
            "clock_independent": True,
            "clock_independent_reason": (
                "不使用系統時鐘，因此在任何時間重跑都得到相同結果"
            ),
        },
        "source_steps": ["Step 3", "Step 4"],
        "source_files": ["data/processed/fubon_schedule_2026.json"],
        "provenance": [
            prov("Step 4", "data/processed/fubon_schedule_2026.json",
                 "game_sno / game_date / scheduled_time / opponent / field / game_status",
                 "direct_source_value",
                 note="原值來自 Step 3 的 POST /schedule/getgamedatas"),
            prov("Step 4", "data/processed/fubon_schedule_2026.json", "is_home",
                 "direct_source_value",
                 formula="home_away = 'home' if is_home else 'away'"),
            prov("Step 4", "data/processed/fubon_schedule_2026.json",
                 "home_score / visiting_score", "not_available",
                 note="未開打場次的 0 為官方預設值，不得解讀為 0:0，因此設為 null"),
        ],
    }


# ------------------------------------------------------------------ Node 3：Next Starting Pitcher

def build_next_starting_pitcher_node(game: dict, schedule: list) -> dict:
    is_home = game["is_home"]
    # 對手那一側的先發投手：富邦是主隊 -> 取客隊投手；富邦是客隊 -> 取主隊投手
    side_field = "visiting_pitcher_acnt" if is_home else "home_pitcher_acnt"
    own_field = "home_pitcher_acnt" if is_home else "visiting_pitcher_acnt"
    acnt_raw = game[side_field]
    acnt = acnt_raw if acnt_raw else None

    # 事實觀察：未開打場次中只有最近一場帶有投手 Acnt
    unplayed = [r for r in schedule if r["game_result"] == ""]
    with_acnt = sorted(
        r["game_sno"] for r in unplayed
        if r["home_pitcher_acnt"] or r["visiting_pitcher_acnt"]
    )

    return {
        "node_id": "N3_NEXT_STARTING_PITCHER",
        "node_type": "next_starting_pitcher",
        "status": "usable" if acnt else "unusable_blocked",
        "verification_status": "unconfirmed_upcoming_starter_identity",
        "evidence": {
            "pitcher_acnt": acnt,
            # schedule 中未開打場次的 PitcherName 是空字串；空字串不是姓名，故為 null
            "pitcher_name": None,
            "pitcher_name_missing_reason": (
                "processed schedule 中未開打場次的投手姓名為空字串"
                "（Step 3 已記錄：Acnt 有值但 Name 為空）。空字串不是姓名，因此為 null。"
                "要取得姓名需要查球員頁，而本階段禁止 HTTP 請求。"
            ),
            "team": game["opponent"],
            "team_side": "visiting" if is_home else "home",
            "own_team_pitcher_acnt_for_reference": game[own_field] or None,
        },
        "unconfirmed_reason": (
            "Step 3 與 Step 7A 都已記錄：未開打場次的 PitcherAcnt 有值但 PitcherName 為空，"
            "且官方沒有任何文字說明這個欄位在未開打場次代表預告先發。"
            "Step 7A 只在【已完成】比賽上驗證過 5 筆（5/5 通過），"
            "從未在【未開打】場次上驗證過。因此本 chain 不把它標為 verified。"
        ),
        "supporting_observation": {
            "statement": (
                "未開打的 31 場富邦賽事中，只有下一場帶有投手 Acnt，"
                "其餘場次的投手欄位為空字串"
            ),
            "unplayed_games_with_pitcher_acnt": with_acnt,
            "unplayed_games_total": len(unplayed),
            "interpretation_limit": (
                "這個觀察與「該欄位是預告先發」相容，但不構成證明。"
                "官方沒有說明，本專案不自行認定。"
            ),
        },
        "source_steps": ["Step 3", "Step 4", "Step 7A"],
        "source_files": ["data/processed/fubon_schedule_2026.json"],
        "provenance": [
            prov("Step 4", "data/processed/fubon_schedule_2026.json", side_field,
                 "selected_by_rule",
                 formula="富邦為主隊時取 visiting_pitcher_acnt，為客隊時取 home_pitcher_acnt",
                 note="原始欄位為 Step 3 的 VisitingPitcherAcnt / HomePitcherAcnt"),
            prov("Step 3", "data/processed/fubon_schedule_2026.json",
                 "visiting_pitcher_name / home_pitcher_name", "not_available",
                 note="未開打場次為空字串，設為 null"),
        ],
    }


# ------------------------------------------------------------------ Node 4：Pitcher Hand

def build_pitcher_hand_node(pitcher_node: dict) -> dict:
    acnt = pitcher_node["evidence"]["pitcher_acnt"]
    verified_acnts = [r["pitcher_acnt"] for r in STEP_7A_VERIFIED_REFERENCE]
    in_reference = acnt in verified_acnts

    return {
        "node_id": "N4_NEXT_STARTER_HAND",
        "node_type": "pitcher_hand",
        "status": "unusable_blocked",
        "verification_status": "missing_required_data",
        "evidence": {
            "pitcher_acnt": acnt,
            "pitcher_name": None,
            "hand": None,
            "evidence_basis": None,
            "missing_reason": (
                "取得手別需要 GET /team/person?Acnt=<acnt> 的「投打習慣」欄位，"
                "而本階段禁止任何 HTTP 請求；且該 Acnt 不在 Step 7A 已驗證的 5 筆之中，"
                "本專案沒有任何本地資料記載它的手別。因此 hand 為 null，不猜測。"
            ),
            "required_to_resolve": (
                "GET /team/person?Acnt=" + (acnt or "<acnt>")
                + " 並解析「投打習慣」（右投 -> R，左投 -> L）"
            ),
        },
        "method_reference": {
            "note": (
                "Step 7A 已在【已完成】比賽上驗證過此方法，5/5 通過。"
                "以下原樣記錄作為方法參考，**沒有**被用來推論本場投手的手別。"
            ),
            "acnt_in_verified_reference": in_reference,
            "verified_records": copy.deepcopy(STEP_7A_VERIFIED_REFERENCE),
        },
        "source_steps": ["Step 7A"],
        "source_files": ["docs/PITCHER_HAND_DATA_SOURCE.md"],
        "provenance": [
            prov("Step 7A", "-", "投打習慣", "not_available",
                 note="需要 HTTP 請求球員頁，本階段禁止；不填補任何值"),
        ],
    }


# ------------------------------------------------------------------ Node 5：Historical Matchup

def build_matchup_branch(code: str, ctx: dict, sample: dict) -> dict:
    return {
        "branch": code,
        "official_item_name": ctx["item_name"],
        "plate_appearances": ctx["plate_appearances"],
        "at_bats": ctx["at_bats"],
        "hits": ctx["hits"],
        "total_bases": ctx["total_bases"],
        "batting_average": ctx["batting_average"],
        "on_base_percentage": ctx["on_base_percentage"],
        "slugging_percentage": ctx["slugging_percentage"],
        "official_reference": {
            "avg": ctx["official_avg"],
            "obp": ctx["official_obp"],
            "slg": ctx["official_slg"],
        },
        "sample_context": {
            "at_bats": sample["sample_context"]["at_bats"],
            "plate_appearances": sample["sample_context"]["plate_appearances"],
            "games": sample["sample_context"]["games"],
            "games_missing_reason": sample["sample_context"].get("games_note"),
            "delta_if_one_more_avg":
                sample["sample_sensitivity"]["batting_average"]["delta_if_one_more"],
            "delta_if_one_more_obp":
                sample["sample_sensitivity"]["on_base_percentage"]["delta_if_one_more"],
            "delta_if_one_more_slg":
                sample["sample_sensitivity"]["slugging_percentage"]["delta_if_one_more"],
        },
    }


def build_historical_matchup_node(
    hand_node: dict, contexts: dict, samples_by_context: dict
) -> dict:
    hand = hand_node["evidence"]["hand"]
    branches = {
        code: build_matchup_branch(code, contexts[code], samples_by_context[code])
        for code in ("VS_RIGHT", "VS_LEFT")
    }

    selected = None
    if hand == "R":
        selected = "VS_RIGHT"
    elif hand == "L":
        selected = "VS_LEFT"

    blocked = selected is None
    return {
        "node_id": "N5_HISTORICAL_MATCHUP",
        "node_type": "historical_matchup",
        "status": "unusable_blocked" if blocked else "usable",
        "verification_status": (
            "blocked_by_unverified_upcoming_starter" if blocked
            else "verified_cross_checked_with_prior_steps"
        ),
        "evidence": {
            "historical_matchup_basis": "season_cumulative_vs_pitcher_hand",
            "basis_definition": (
                "官方分項成績 ItemGroupCode = 3 的「VS. 右投」/「VS. 左投」，"
                "涵蓋 2026 一軍例行賽全季所有面對該手別投手的打席。"
            ),
            "basis_is_not": (
                "這**不是**某一場比賽中所有面對投手的 matchup，"
                "也不是逐打席或逐球資料。它是整季依投手手別切分的累計，"
                "與「對手先發投手」是兩件不同的事。"
            ),
            "selected_branch": selected,
            "selection_blocked_reason": (
                "上游 N4_NEXT_STARTER_HAND 的 hand 為 null，"
                "因此無法決定要引用 VS_LEFT 還是 VS_RIGHT。"
                "本階段不自行選一邊。"
                if blocked else None
            ),
            "unselected_branches_available": sorted(branches) if blocked else None,
            "branches": branches,
        },
        "source_steps": ["Step 8", "Step 11"],
        "source_files": ["data/raw/apart_score_0000006888_2026_A_01.json"],
        "provenance": [
            prov("Step 8", "data/raw/apart_score_0000006888_2026_A_01.json",
                 "PlateAppearances / HitCnt / HittingCnt / TotalBases",
                 "direct_source_value",
                 note="官方 POST /team/getapartscore，ItemGroupCode = 3"),
            prov("Step 8", "src/context_splits.py", "batting_average",
                 "computed_from_source_counts", formula="hits / at_bats"),
            prov("Step 8", "src/context_splits.py", "on_base_percentage",
                 "computed_from_source_counts",
                 formula="(hits + walks + hit_by_pitch) / "
                         "(at_bats + walks + hit_by_pitch + sacrifice_flies)",
                 note="walks 已含故意四壞（Step 7B 以打席恆等式實證），不再加 IBB"),
            prov("Step 8", "src/context_splits.py", "slugging_percentage",
                 "computed_from_source_counts", formula="total_bases / at_bats"),
            prov("Step 11", "src/evidence_sample_context.py",
                 "sample_context / delta_if_one_more", "computed_from_source_counts",
                 formula="delta_if_one_more = 1 / denominator"),
        ],
    }


# ------------------------------------------------------------------ Edges

def build_edges(nodes: list) -> list:
    by_type = {n["node_type"]: n for n in nodes}
    edges = [
        {
            "edge_id": "E1_FORM_TO_GAME",
            "from_node": by_type["current_form"]["node_id"],
            "to_node": by_type["next_game"]["node_id"],
            "basis_code": "current_form_requires_next_game_context",
            "basis": (
                "近期表現本身不含對手資訊。要形成與下一場有關的 evidence，"
                "必須接上下一場的比賽記錄（Step 13 的 next_game_dependency = true）。"
            ),
            "verification_status": "verified_against_processed_schedule",
            "blocked_reason": None,
        },
        {
            "edge_id": "E2_GAME_TO_PITCHER",
            "from_node": by_type["next_game"]["node_id"],
            "to_node": by_type["next_starting_pitcher"]["node_id"],
            "basis_code": "schedule_game_record_contains_pitcher_account_identifier",
            "basis": (
                "賽程場次記錄中含 HomePitcherAcnt / VisitingPitcherAcnt，"
                "依富邦的主客身分可取出對手那一側的投手 Acnt。"
            ),
            "verification_status": "unconfirmed_upcoming_starter_identity",
            "blocked_reason": (
                "Acnt 取得成功，但「未開打場次的 Acnt 是否代表預告先發」未經驗證。"
            ),
        },
        {
            "edge_id": "E3_PITCHER_TO_HAND",
            "from_node": by_type["next_starting_pitcher"]["node_id"],
            "to_node": by_type["pitcher_hand"]["node_id"],
            "basis_code": "player_profile_provides_throwing_batting_handedness",
            "basis": (
                "球員個人頁 /team/person?Acnt= 的 HTML 直接含「投打習慣」欄位，"
                "可推導 R / L（Step 7A 在已完成比賽上 5/5 驗證通過）。"
            ),
            "verification_status": "missing_required_data",
            "blocked_reason": (
                "本階段禁止 HTTP 請求，且該 Acnt 不在 Step 7A 已驗證的 5 筆之中，"
                "本地沒有任何資料記載其手別。"
            ),
        },
        {
            "edge_id": "E4_HAND_TO_MATCHUP",
            "from_node": by_type["pitcher_hand"]["node_id"],
            "to_node": by_type["historical_matchup"]["node_id"],
            "basis_code":
                "official_item_group_3_provides_season_cumulative_vs_hand_split",
            "basis": (
                "官方分項成績 ItemGroupCode = 3 提供整季的「VS. 右投」/「VS. 左投」"
                "累計數據，可依手別選擇對應分項。"
            ),
            "verification_status": "blocked_by_unverified_upcoming_starter",
            "blocked_reason": (
                "上游手別為 null，無法決定引用哪一個分項。兩個分項本身都已備妥且已驗證。"
            ),
        },
    ]
    return edges


# ------------------------------------------------------------------ Chain

def build_chain(logs: list, schedule: list, contexts: dict,
                samples_by_context: dict) -> dict:
    game, as_of = pick_next_game(schedule)

    n1 = build_current_form_node(logs)
    n2 = build_next_game_node(game, as_of)
    n3 = build_next_starting_pitcher_node(game, schedule)
    n4 = build_pitcher_hand_node(n3)
    n5 = build_historical_matchup_node(n4, contexts, samples_by_context)
    nodes = [n1, n2, n3, n4, n5]
    edges = build_edges(nodes)

    usable = [n["node_id"] for n in nodes if n["status"] == "usable"]
    blocked = [n["node_id"] for n in nodes if n["status"] == "unusable_blocked"]

    return {
        "chain_id": f"CHAIN-PREGAME-MATCHUP-{SUBJECT['player_acnt']}-{SEASON}-"
                    f"GAMESNO{game['game_sno']}",
        "chain_type": "pre_game_matchup",
        "player": PLAYER_NAME,
        "player_acnt": SUBJECT["player_acnt"],
        "season": SEASON,
        "kind_code": SUBJECT["kind_code"],
        "target_game_sno": game["game_sno"],
        "nodes": nodes,
        "edges": edges,
        "completeness": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "chain_constructed": True,
            "chain_fully_resolved": not blocked,
            "usable_nodes": usable,
            "blocked_nodes": blocked,
            "first_blocking_node": blocked[0] if blocked else None,
            "blocking_summary": (
                "chain 結構完整建立（5 nodes / 4 edges），但在 N4 之後被資料缺口阻斷。"
                "N4 缺手別、N5 因此無法選擇分項。兩個 node 都保留並標示狀態，"
                "沒有填入任何猜測值。"
                if blocked else "chain 全部節點皆可用"
            ),
        },
        "contains_no": [
            "ranking", "score", "weight", "threshold", "confidence_score",
            "prediction", "recommendation", "natural_language_conclusion", "llm",
        ],
    }


# ------------------------------------------------------------------ 輸出

def print_chain(chain: dict) -> None:
    print("=" * 100)
    print("Insight Chain Experiment（Step 14）")
    print("=" * 100)
    print(f"  chain_id       : {chain['chain_id']}")
    print(f"  chain_type     : {chain['chain_type']}")
    print(f"  player         : {chain['player']}（Acnt {chain['player_acnt']}）")
    print(f"  season         : {chain['season']}　kind_code {chain['kind_code']}")
    print(f"  target_game_sno: {chain['target_game_sno']}")

    print("\n" + "=" * 100)
    print("Nodes")
    print("=" * 100)
    for n in chain["nodes"]:
        print(f"\n  [{n['node_id']}] node_type={n['node_type']}")
        print(f"      status              : {n['status']}")
        print(f"      verification_status : {n['verification_status']}")
        print(f"      source_steps        : {', '.join(n['source_steps'])}")
        print(f"      source_files        : {', '.join(n['source_files'])}")
        ev = n["evidence"]
        if n["node_type"] == "current_form":
            for key in ("recent_10", "recent_15", "season_cumulative"):
                w = ev[key]
                print(f"      {key:<18}: games={w['games']}  PA={w['plate_appearances']}"
                      f"  AB={w['at_bats']}  H={w['hits']}  HR={w['home_runs']}"
                      f"  RBI={w['rbi']}  TB={w['total_bases']}")
                print(f"          {'':<14}  AVG={fmt(w['batting_average'])}"
                      f"  SLG={fmt(w['slugging_percentage'])}"
                      f"  OBP={fmt(w['on_base_percentage'])}")
                print(f"          {'':<14}  {w['first_game_date']} ~ {w['last_game_date']}"
                      f"　game_snos({len(w['game_snos'])})={w['game_snos']}")
        elif n["node_type"] == "next_game":
            print(f"      game_sno   : {ev['game_sno']}")
            print(f"      game_date  : {ev['game_date']}  scheduled_time="
                  f"{ev['scheduled_time']}")
            print(f"      opponent   : {ev['opponent']}  home_away={ev['home_away']}"
                  f"  venue={ev['venue']}")
            print(f"      game_status: {ev['game_status']}"
                  f"（game_result_code={ev['game_result_code']!r}）")
            print(f"      score      : home={ev['home_score']}"
                  f"  visiting={ev['visiting_score']}  <-- null，非 0:0")
            print(f"          原始檔案中的值（僅追溯用）："
                  f"{ev['source_score_values_for_traceability']}")
            print(f"      selection  : reference_date={n['selection_rule']['reference_date']}"
                  f"  clock_independent={n['selection_rule']['clock_independent']}")
        elif n["node_type"] == "next_starting_pitcher":
            print(f"      pitcher_acnt: {ev['pitcher_acnt']}")
            print(f"      pitcher_name: {ev['pitcher_name']}  <-- null")
            print(f"      team        : {ev['team']}（{ev['team_side']}）")
            print(f"      未確認原因  : {n['unconfirmed_reason']}")
            print(f"      觀察        : {n['supporting_observation']['statement']}")
            print(f"                    帶 Acnt 的未開打場次："
                  f"{n['supporting_observation']['unplayed_games_with_pitcher_acnt']}"
                  f" / 共 {n['supporting_observation']['unplayed_games_total']} 場")
        elif n["node_type"] == "pitcher_hand":
            print(f"      hand          : {ev['hand']}  <-- null，未填補")
            print(f"      missing_reason: {ev['missing_reason']}")
            print(f"      required      : {ev['required_to_resolve']}")
            print(f"      Step 7A 參考  : acnt_in_verified_reference="
                  f"{n['method_reference']['acnt_in_verified_reference']}"
                  f"（5 筆已驗證記錄原樣保留，未用於推論）")
        else:
            print(f"      historical_matchup_basis: {ev['historical_matchup_basis']}")
            print(f"      selected_branch         : {ev['selected_branch']}  <-- null")
            print(f"      blocked_reason          : {ev['selection_blocked_reason']}")
            print(f"      可用但未選的分項        : {ev['unselected_branches_available']}")
            for code, b in ev["branches"].items():
                print(f"        {code}（官方 {b['official_item_name']}）")
                print(f"          PA={b['plate_appearances']}  AB={b['at_bats']}"
                      f"  H={b['hits']}  TB={b['total_bases']}")
                print(f"          AVG={fmt(b['batting_average'])}"
                      f"  OBP={fmt(b['on_base_percentage'])}"
                      f"  SLG={fmt(b['slugging_percentage'])}")
                sc = b["sample_context"]
                print(f"          sample_context: AB={sc['at_bats']}"
                      f"  PA={sc['plate_appearances']}  games={sc['games']}"
                      f"  delta_avg={fmt(sc['delta_if_one_more_avg'])}")

    print("\n" + "=" * 100)
    print("Edges")
    print("=" * 100)
    for e in chain["edges"]:
        print(f"\n  [{e['edge_id']}] {e['from_node']} -> {e['to_node']}")
        print(f"      basis_code          : {e['basis_code']}")
        print(f"      basis               : {e['basis']}")
        print(f"      verification_status : {e['verification_status']}")
        print(f"      blocked_reason      : {e['blocked_reason']}")

    print("\n" + "=" * 100)
    print("Completeness")
    print("=" * 100)
    c = chain["completeness"]
    print(f"  node_count            : {c['node_count']}")
    print(f"  edge_count            : {c['edge_count']}")
    print(f"  chain_constructed     : {c['chain_constructed']}")
    print(f"  chain_fully_resolved  : {c['chain_fully_resolved']}")
    print(f"  usable_nodes          : {', '.join(c['usable_nodes'])}")
    print(f"  blocked_nodes         : {', '.join(c['blocked_nodes'])}")
    print(f"  first_blocking_node   : {c['first_blocking_node']}")
    print(f"  summary               : {c['blocking_summary']}")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "rank", "confidence", "importance", "priority")
ALLOWED_KEY_EXCEPTIONS = (
    "home_score", "visiting_score", "score_is_null_reason",
    "source_score_values_for_traceability", "home_score_in_file",
    "visiting_score_in_file",
)
FORBIDDEN_WORDS = (
    "應該", "建議", "必須讓", "代打", "打第", "換投", "推薦",
    "should", "must ", "recommend", "advise",
    "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
    "預測", "統計顯著", "顯著性", "最佳", "最好", "最差",
)
DECLARATIVE_KEYS = ("contains_no", "basis_is_not")

# LLM 套件名稱清單，用於 AST import 檢查（不是文字掃描）
LLM_PACKAGE_NAMES = frozenset({
    "openai", "anthropic", "cohere", "google", "vertexai", "transformers",
    "langchain", "llama_index", "llamaindex", "ollama", "litellm", "mistralai",
    "boto3", "botocore", "huggingface_hub", "torch", "tensorflow",
})


def collect_imported_modules(path: Path) -> set[str]:
    """用 AST 取出檔案中實際 import 的頂層模組名稱。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0].lower())
    return names


def scan_keys(obj, path="") -> list:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if k not in DECLARATIVE_KEYS and k not in ALLOWED_KEY_EXCEPTIONS:
                for bad in FORBIDDEN_KEYS:
                    if bad in kl:
                        found.append(f"{path}.{k}")
                found += scan_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += scan_keys(v, f"{path}[{i}]")
    return found


def run_validation(chain: dict, chain_rerun: dict, schedule: list,
                   contexts: dict, samples_by_context: dict,
                   logs: list, fingerprints_before: dict,
                   sched_fingerprint_before: tuple) -> list:
    checks: list[tuple[str, bool, str]] = []
    nodes = {n["node_type"]: n for n in chain["nodes"]}
    n2, n3, n4, n5 = (nodes["next_game"], nodes["next_starting_pitcher"],
                      nodes["pitcher_hand"], nodes["historical_matchup"])

    # 1 / 2
    checks.append(("chain player == 張育成", chain["player"] == PLAYER_NAME,
                   f"player={chain['player']}　acnt={chain['player_acnt']}"))
    checks.append(("chain season == 2026", chain["season"] == 2026,
                   f"season={chain['season']}　kind_code={chain['kind_code']}"))

    # 3. next game 是下一場未完成富邦賽事
    expected_game, as_of = pick_next_game(schedule)
    ev2 = n2["evidence"]
    earlier = [
        r for r in schedule
        if r["game_result"] == "" and r["game_date"] > as_of
        and (r["game_date"], r["scheduled_time"] or "", r["game_sno"])
        < (expected_game["game_date"], expected_game["scheduled_time"] or "",
           expected_game["game_sno"])
    ]
    ok3 = (
        ev2["game_sno"] == expected_game["game_sno"]
        and ev2["game_result_code"] == ""
        and not earlier
    )
    checks.append(
        ("next game 確實是下一場未完成的富邦賽事", ok3,
         f"參考日={as_of}（已完成比賽最晚日期）　選出 game_sno={ev2['game_sno']}"
         f" {ev2['game_date']} {ev2['scheduled_time']}　game_result={ev2['game_result_code']!r}"
         f"　更早的未開打場次數={len(earlier)}")
    )

    # 4. opponent / home_away / venue 與 processed schedule 一致
    ok4 = (
        ev2["opponent"] == expected_game["opponent"]
        and ev2["home_away"] == ("home" if expected_game["is_home"] else "away")
        and ev2["venue"] == expected_game["field"]
        and ev2["game_date"] == expected_game["game_date"]
        and ev2["scheduled_time"] == expected_game["scheduled_time"]
        and ev2["game_status"] == expected_game["game_status"]
    )
    checks.append(
        ("next game 的 opponent / home_away / venue / 日期時間 / 狀態與 "
         "processed schedule 一致", ok4,
         f"opponent={ev2['opponent']}　home_away={ev2['home_away']}"
         f"　venue={ev2['venue']}　{ev2['game_date']} {ev2['scheduled_time']}"
         f"　status={ev2['game_status']}")
    )

    # 5. 未開打比賽的 score 不得被解讀為 0:0
    ok5 = (
        ev2["home_score"] is None and ev2["visiting_score"] is None
        and ev2["source_score_values_for_traceability"]["home_score_in_file"] == 0
        and bool(ev2["score_is_null_reason"])
    )
    checks.append(
        ("尚未開打比賽的 score 為 null，未被解讀為 0:0", ok5,
         f"node 中 home_score={ev2['home_score']}"
         f"　visiting_score={ev2['visiting_score']}"
         f"　原始檔案值={ev2['source_score_values_for_traceability']}"
         "　（原值保留於追溯欄位，並附說明為官方預設值）")
    )

    # 6. pitcher_acnt 必須來自 schedule source
    side_field = ("visiting_pitcher_acnt" if expected_game["is_home"]
                  else "home_pitcher_acnt")
    ok6 = n3["evidence"]["pitcher_acnt"] == (expected_game[side_field] or None)
    prov_fields = [p["source_field"] for p in n3["provenance"]]
    checks.append(
        ("pitcher_acnt 來自 processed schedule 的對應欄位", ok6 and side_field in prov_fields,
         f"acnt={n3['evidence']['pitcher_acnt']}　欄位={side_field}"
         f"　schedule 原值={expected_game[side_field]!r}"
         f"　provenance 已記錄={side_field in prov_fields}")
    )

    # 7. 不得把未確認的 upcoming pitcher identity 標成 verified
    ok7 = (
        n3["verification_status"] == "unconfirmed_upcoming_starter_identity"
        and "verified" not in n3["verification_status"]
        and n3["evidence"]["pitcher_name"] is None
    )
    checks.append(
        ("未確認的 upcoming pitcher identity 沒有被標成 verified", ok7,
         f"verification_status={n3['verification_status']}"
         f"　pitcher_name={n3['evidence']['pitcher_name']}（空字串已轉為 null）")
    )

    # 8. 已驗證的 pitcher hand 必須符合 Step 7A 結果
    ref = n4["method_reference"]["verified_records"]
    ok8_ref = ref == STEP_7A_VERIFIED_REFERENCE and len(ref) == 5
    hands_ok = all(
        (r["habit"].startswith("右投") and r["hand"] == "R")
        or (r["habit"].startswith("左投") and r["hand"] == "L")
        for r in ref
    )
    not_reused = n4["evidence"]["pitcher_acnt"] not in [
        r["pitcher_acnt"] for r in ref
    ]
    ok8 = ok8_ref and hands_ok and n4["evidence"]["hand"] is None and not_reused
    checks.append(
        ("pitcher hand 的處理符合 Step 7A：本 chain 未宣稱任何手別，"
         "Step 7A 的 5 筆驗證結果原樣保留且未被挪用", ok8,
         f"Step 7A 參考筆數={len(ref)}　投打習慣與 R/L 對應一致={hands_ok}"
         f"　本場 hand={n4['evidence']['hand']}"
         f"　本場 Acnt 不在已驗證清單中={not_reused}")
    )

    # 9. historical matchup 只引用 VS_LEFT / VS_RIGHT
    branches = n5["evidence"]["branches"]
    ok9 = set(branches) == {"VS_RIGHT", "VS_LEFT"} and all(
        b["official_item_name"] in ("VS. 右投", "VS. 左投") for b in branches.values()
    )
    checks.append(
        ("historical matchup 只引用官方 VS. 右投 / VS. 左投 分項", ok9,
         f"branches={sorted(branches)}　官方 ItemName="
         + "、".join(b["official_item_name"] for b in branches.values()))
    )

    # 10. 不得被描述成「該場所有投手」
    basis = n5["evidence"]
    ok10 = (
        basis["historical_matchup_basis"] == "season_cumulative_vs_pitcher_hand"
        and "不是" in basis["basis_is_not"]
        and "逐球" in basis["basis_is_not"]
    )
    checks.append(
        ("historical matchup 的定義明確排除「該場所有投手 / 逐打席 / 逐球」的解讀", ok10,
         f"basis={basis['historical_matchup_basis']}　"
         "basis_is_not 已明確聲明它不是單場 matchup、不是逐打席、不是逐球資料")
    )

    # 11. PA / AB / H / TB 與 Step 8 一致
    bad11 = []
    for code, exp in STEP_8_EXPECTED.items():
        b = branches[code]
        for field in ("plate_appearances", "at_bats", "hits", "total_bases"):
            if b[field] != exp[field]:
                bad11.append(f"{code}.{field}={b[field]} 期望 {exp[field]}")
    checks.append(
        ("PA / AB / H / TB 與 Step 8 evidence 完全一致", not bad11,
         "VS_RIGHT 258/219/68/122　VS_LEFT 62/54/17/23　與 Step 8 文件記錄相同"
         if not bad11 else "；".join(bad11))
    )

    # 12. AVG / OBP / SLG 與 Step 8 一致（官方為 4 位截斷，故以截斷值比對）
    def trunc4(v: float) -> float:
        import math
        return math.floor(v * 10**4 + 1e-9) / 10**4

    bad12 = []
    for code, exp in STEP_8_EXPECTED.items():
        b = branches[code]
        for our_key, exp_key in (("batting_average", "official_avg"),
                                 ("on_base_percentage", "official_obp"),
                                 ("slugging_percentage", "official_slg")):
            if abs(trunc4(b[our_key]) - exp[exp_key]) >= 1e-9:
                bad12.append(f"{code}.{our_key} 截斷={trunc4(b[our_key])} "
                             f"期望={exp[exp_key]}")
            if abs(b[our_key] - contexts[code][our_key]) >= 1e-12:
                bad12.append(f"{code}.{our_key} 與 Step 8 計算值不符")
    checks.append(
        ("AVG / OBP / SLG 與 Step 8 evidence 完全一致（含官方 4 位截斷比對）", not bad12,
         "6 個比率（2 分項 × 3 指標）全部相符，且完整精度值與 Step 8 的計算結果相同"
         if not bad12 else "；".join(bad12))
    )

    # 13. sample_context 與 Step 11 一致
    bad13 = []
    for code, b in branches.items():
        s = samples_by_context[code]
        sc = b["sample_context"]
        if sc["at_bats"] != s["sample_context"]["at_bats"]:
            bad13.append(f"{code} at_bats")
        if sc["plate_appearances"] != s["sample_context"]["plate_appearances"]:
            bad13.append(f"{code} PA")
        if sc["games"] is not None:
            bad13.append(f"{code} games 應為 null")
        for metric, key in (("batting_average", "delta_if_one_more_avg"),
                            ("on_base_percentage", "delta_if_one_more_obp"),
                            ("slugging_percentage", "delta_if_one_more_slg")):
            if sc[key] != s["sample_sensitivity"][metric]["delta_if_one_more"]:
                bad13.append(f"{code} {key}")
    checks.append(
        ("sample_context 與 Step 11 完全一致", not bad13,
         "VS_RIGHT AB=219 PA=258　VS_LEFT AB=54 PA=62　games 皆為 null；"
         "三個 delta_if_one_more 皆取自 Step 11 的 sensitivity"
         if not bad13 else "；".join(bad13))
    )

    # 14 / 15. raw / processed data 未修改
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    if sha256_of(SCHEDULE_PATH) != sched_fingerprint_before:
        changed.append(SCHEDULE_PATH.name)
    checks.append(
        ("raw data 未被修改", APART_CACHE_PATH.name not in changed,
         f"{APART_CACHE_PATH.name} {fingerprints_before[APART_CACHE_PATH][0][:8]} / "
         f"{fingerprints_before[APART_CACHE_PATH][1]} bytes")
    )
    checks.append(
        ("processed data 未被修改", PLAYER_LOG_PATH.name not in changed
         and SCHEDULE_PATH.name not in changed,
         f"{PLAYER_LOG_PATH.name} {fingerprints_before[PLAYER_LOG_PATH][0][:8]} / "
         f"{fingerprints_before[PLAYER_LOG_PATH][1]} bytes　"
         f"{SCHEDULE_PATH.name} {sched_fingerprint_before[0][:8]} / "
         f"{sched_fingerprint_before[1]} bytes")
    )

    # 16. 沒有 HTTP request
    checks.append(
        ("沒有產生任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖；"
         "未呼叫 /team/person、未呼叫 /box/getlive")
    )

    # 17. 沒有 LLM
    #     用 AST 解析本檔案實際 import 的模組，再比對已載入的 sys.modules。
    #     不掃描原始碼文字，因為檢查清單本身就寫在原始碼裡，會自我命中。
    imported = collect_imported_modules(Path(__file__))
    loaded = {m.split(".")[0].lower() for m in sys.modules}
    llm_in_imports = sorted(imported & LLM_PACKAGE_NAMES)
    llm_in_loaded = sorted(loaded & LLM_PACKAGE_NAMES)
    checks.append(
        ("沒有使用 LLM", not llm_in_imports and not llm_in_loaded,
         f"AST 解析本檔案 import 的頂層模組 {len(imported)} 個："
         + "、".join(sorted(imported))
         + f"；已載入模組中沒有任何 LLM 套件（比對清單 {len(LLM_PACKAGE_NAMES)} 個）"
         if not llm_in_imports and not llm_in_loaded
         else f"import={llm_in_imports}　loaded={llm_in_loaded}")
    )

    blob = json.dumps(chain, ensure_ascii=False)
    declarative = json.dumps(
        [chain["contains_no"], n5["evidence"]["basis_is_not"]], ensure_ascii=False
    )

    # 18 / 19. 沒有 ranking / score
    bad_keys = scan_keys(chain)
    rank_keys = [k for k in bad_keys if "rank" in k.lower() or "priority" in k.lower()]
    score_keys = [k for k in bad_keys if "score" in k.lower()]
    checks.append(
        ("沒有產生 ranking", not rank_keys,
         "chain 中沒有任何名次或優先度欄位；node 順序是 chain 的邏輯順序，不是排名"
         if not rank_keys else "；".join(rank_keys))
    )
    checks.append(
        ("沒有產生 score", not score_keys,
         "沒有任何分數欄位（home_score / visiting_score 是比賽比分欄位，已列為例外並為 null）"
         if not score_keys else "；".join(score_keys))
    )
    weight_keys = [k for k in bad_keys if "weight" in k.lower()]
    conf_keys = [k for k in bad_keys if "confidence" in k.lower()]
    # threshold 出現在 contains_no 這個「宣告不含這些東西」的清單裡，需扣除
    threshold_count = blob.count("threshold") - declarative.count("threshold")
    ok_wtc = not weight_keys and not conf_keys and threshold_count <= 0
    checks.append(
        ("沒有 weight / threshold / confidence score", ok_wtc,
         "沒有任何權重、門檻或 confidence 欄位"
         f"（contains_no 中的 threshold 是否定宣告，已扣除 "
         f"{declarative.count('threshold')} 次）"
         if ok_wtc else
         f"weight={weight_keys}　confidence={conf_keys}"
         f"　threshold 非宣告性出現 {threshold_count} 次")
    )

    # 20 / 21 / 22. 沒有 recommendation / prediction / 自然語言結論
    hits = []
    for w in FORBIDDEN_WORDS:
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    checks.append(
        ("沒有 recommendation / prediction / 自然語言 insight 結論", not hits,
         "未出現禁用字眼（contains_no、basis_is_not 等否定宣告已扣除）"
         if not hits else "、".join(hits))
    )

    # 23. deterministic
    det = (json.dumps(chain, ensure_ascii=False, sort_keys=True)
           == json.dumps(chain_rerun, ensure_ascii=False, sort_keys=True))
    checks.append(
        ("相同輸入重跑結果完全一致（deterministic）", det,
         "整條 chain 重建一次，序列化結果完全相同；"
         "下一場的選擇以資料推導的參考日為基準，不使用系統時鐘")
    )

    # 24. 所有 node 都有 source / verification_status
    bad24 = []
    for n in chain["nodes"]:
        for key in ("node_id", "node_type", "status", "verification_status",
                    "source_steps", "source_files", "provenance"):
            if key not in n or n[key] in (None, [], ""):
                bad24.append(f"{n.get('node_id')} 缺 {key}")
        if n["verification_status"] not in VERIFICATION_STATUS_VALUES:
            bad24.append(f"{n['node_id']} verification_status 不在受控詞彙中")
        if n["status"] not in NODE_STATUS_VALUES:
            bad24.append(f"{n['node_id']} status 不在受控詞彙中")
        for p in n["provenance"]:
            if p["derivation"] not in DERIVATION_VALUES:
                bad24.append(f"{n['node_id']} derivation={p['derivation']} 不在受控詞彙中")
            if p["derivation"] == "computed_from_source_counts" and "formula" not in p:
                bad24.append(f"{n['node_id']} 計算值缺 formula")
    checks.append(
        ("所有 node 都有 source / verification_status / provenance，且狀態值在受控詞彙中",
         not bad24,
         f"5 個 node 全部具備；provenance 共 "
         f"{sum(len(n['provenance']) for n in chain['nodes'])} 筆，"
         "計算值一律附 formula，直接引用一律標 direct_source_value"
         if not bad24 else "；".join(bad24[:5]))
    )

    # 25. 所有 edge 都有 basis
    bad25 = []
    node_ids = {n["node_id"] for n in chain["nodes"]}
    for e in chain["edges"]:
        for key in ("edge_id", "from_node", "to_node", "basis", "basis_code",
                    "verification_status"):
            if key not in e or e[key] in (None, ""):
                bad25.append(f"{e.get('edge_id')} 缺 {key}")
        if e["basis_code"] not in EDGE_BASIS_CODES:
            bad25.append(f"{e['edge_id']} basis_code 不在受控詞彙中")
        if e["from_node"] not in node_ids or e["to_node"] not in node_ids:
            bad25.append(f"{e['edge_id']} 端點不存在")
    checks.append(
        ("所有 edge 都有 basis 且端點存在", not bad25,
         f"4 條 edge 全部具備 basis 與 basis_code，端點皆為既有 node"
         if not bad25 else "；".join(bad25[:5]))
    )

    # 26. Chain completeness check
    c = chain["completeness"]
    ok26 = (
        c["chain_constructed"] is True
        and c["chain_fully_resolved"] is False
        and n5["verification_status"] == "blocked_by_unverified_upcoming_starter"
        and n5["evidence"]["selected_branch"] is None
        and n4["evidence"]["hand"] is None
        and c["blocked_nodes"] == ["N4_NEXT_STARTER_HAND", "N5_HISTORICAL_MATCHUP"]
    )
    checks.append(
        ("Chain completeness：上游未確認時 chain 仍建立，historical matchup 標示為 "
         "blocked_by_unverified_upcoming_starter 且未自行選 LEFT / RIGHT", ok26,
         f"chain_constructed={c['chain_constructed']}"
         f"　fully_resolved={c['chain_fully_resolved']}"
         f"　blocked={c['blocked_nodes']}"
         f"　N5 status={n5['verification_status']}"
         f"　selected_branch={n5['evidence']['selected_branch']}")
    )

    # 額外：current_form 與 Step 5 / Step 9 的已知數字交叉核對
    n1 = nodes["current_form"]
    expected_form = {
        "recent_10": {"games": 10, "at_bats": 42, "hits": 17, "total_bases": 26,
                      "plate_appearances": 44},
        "recent_15": {"games": 15, "at_bats": 58, "hits": 19, "total_bases": 29,
                      "plate_appearances": 63},
        "season_cumulative": {"games": 77, "at_bats": 273, "hits": 85,
                              "total_bases": 145, "plate_appearances": 320},
    }
    bad_form = []
    for key, exp in expected_form.items():
        w = n1["evidence"][key]
        for field, value in exp.items():
            if w[field] != value:
                bad_form.append(f"{key}.{field}={w[field]} 期望 {value}")
        if abs(w["batting_average"] - exp["hits"] / exp["at_bats"]) > 1e-12:
            bad_form.append(f"{key}.AVG 不符 H/AB")
        if abs(w["slugging_percentage"] - exp["total_bases"] / exp["at_bats"]) > 1e-12:
            bad_form.append(f"{key}.SLG 不符 TB/AB")
    checks.append(
        ("current_form 的數字與 Step 5 / Step 9 記錄完全一致", not bad_form,
         "recent_10 10場/42AB/17H/26TB　recent_15 15場/58AB/19H/29TB　"
         "season 77場/273AB/85H/145TB，AVG 與 SLG 皆可由計數重算"
         if not bad_form else "；".join(bad_form[:5]))
    )

    return checks


# ------------------------------------------------------------------ main

def main() -> None:
    logs, apart_rows = load_inputs()
    schedule = load_schedule()
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }
    sched_fp_before = sha256_of(SCHEDULE_PATH)

    contexts = build_context_evidence(apart_rows)
    season = build_season_baseline(logs, contexts)
    trend, _ = build_trend_candidates(logs, season)
    context_cands = build_context_candidates(contexts, season)
    pattern, _ = build_pattern_candidates(contexts, season)
    candidates = trend + context_cands + pattern

    trend_components = build_trend_components(logs)
    samples_by_candidate = {
        c["candidate_id"]: build_record(c, trend_components, contexts)
        for c in candidates
    }
    # 取每個 context 的 Step 11 sample record（同 context 的三個指標共用同一份樣本脈絡）
    samples_by_context = {}
    for c in candidates:
        if c["type"] != "CONTEXT":
            continue
        code = c["context"]["code"]
        samples_by_context.setdefault(code, samples_by_candidate[c["candidate_id"]])

    chain = build_chain(logs, schedule, contexts, samples_by_context)
    chain_rerun = build_chain(logs, schedule, contexts, samples_by_context)

    print_chain(chain)

    print("\n" + "=" * 100)
    print("Validation")
    print("=" * 100)
    checks = run_validation(
        chain, chain_rerun, schedule, contexts, samples_by_context, logs,
        fingerprints_before, sched_fp_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/INSIGHT_CHAIN_EXPERIMENT.md。")

    print("\n" + "=" * 100)
    print("chain 結構完整建立，但在投手手別處被資料缺口阻斷。")
    print("被阻斷的 node 保留並標示狀態，沒有填入任何猜測值。")
    print("=" * 100)


if __name__ == "__main__":
    main()

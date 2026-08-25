"""MVP Product Output Model（Step 22）。

它建立什麼：一個**穩定、machine-readable 的產品輸出物件**，定義未來
backend / API / frontend 應該收到什麼。全部在記憶體中組裝，不寫入 data/。

它**不**是什麼：
    - 不是 web UI、不是 API、不是 backend，沒有 React / Flask / FastAPI
    - 沒有 score / weight / threshold / ranking / priority / Top-N / confidence
    - 沒有 prediction / recommendation / natural-language interpretation
    - 不使用 LLM、不發 HTTP 請求
    - 不新增 candidate / group / insight、不新增任何數值
    - 不修改 Step 5~21 的任何輸出或 raw / processed data

資料來源全部是既有 Step 的輸出，原樣引用：
    Step 3 / 4  -> processed schedule（next_game）
    Step 5 / 6  -> 逐場計數與滾動分布
    Step 8      -> 官方分項
    Step 9      -> 29 candidates
    Step 11     -> sample context / sensitivity
    Step 13     -> decision descriptor 受控詞彙
    Step 14     -> next_game / next_starting_pitcher / pitcher_hand node
    Step 18     -> 9 groups
    Step 19     -> group decision relevance
    Step 20     -> presentation model（evidence / application data status 分離）
    Step 21     -> 9 個 factual insight（本輸出的唯一數值來源）

兩個刻意分開、不得合併的欄位（Step 20 已建立）：
    evidence_data_status      —— evidence 數值本身是否存在
    application_data_status   —— 能否直接用於下一場決策

用法：
    python src/product_output_model.py
"""

from __future__ import annotations

import ast
import copy
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# import candidate_insights 會安裝 socket guard，封鎖所有對外連線
from candidate_insights import (  # noqa: E402
    APART_CACHE_PATH,
    PLAYER_LOG_PATH,
    ROOT,
    SUBJECT,
    build_context_evidence,
    build_season_baseline,
    load_inputs,
    network_guard_active,
    sha256_of,
)
from decision_relevance import (  # noqa: E402
    ALLOWED_ACTION_LINK_REQUIRES,
    ALLOWED_ACTION_LINKS,
    ALLOWED_DECISION_AREAS,
    CONTEXTUAL_RELEVANCE_VALUES,
    PERSPECTIVES,
    PERSPECTIVE_ORDER,
    TEMPORAL_RELEVANCE_VALUES,
)
from insight_assembly import (  # noqa: E402
    ALL_METRICS,
    DATA_SOURCE_TOKENS,
    EVIDENCE_KIND_VALUES,
    INTERPRETATION_STATUS_VALUES,
    METRIC_LABEL,
    build_all as build_step21,
)
from insight_chain import (  # noqa: E402
    SCHEDULE_PATH,
    build_next_game_node,
    build_next_starting_pitcher_node,
    build_pitcher_hand_node,
    load_schedule,
    pick_next_game,
)
from insight_presentation_model import (  # noqa: E402
    APPLICATION_READINESS_VALUES,
    DATA_STATUS_VALUES,
    EVIDENCE_SELF_CONTAINMENT_VALUES,
    PRESENTATION_PURPOSE_VALUES,
    build_presentation_model,
)
from decision_relevance import build_relevance_record  # noqa: E402
from insight_assembly import build_insights  # noqa: E402
from insight_grouping import build_groups  # noqa: E402
from group_decision_relevance import build_group_relevance  # noqa: E402
from noteworthy_insights import build_all as build_classification  # noqa: E402

PRODUCT_OUTPUT_VERSION = "step22-v1"

STATEMENT_KIND_VALUES = ("numeric_fact", "explicit_null", "direction_summary")

DIRECTION_VALUES = ("ABOVE", "BELOW", "EQUAL")

# next_game 各欄位的資料狀態，沿用 Step 20 的 4 值詞彙，沒有新增任何值。
# 對照完全由 Step 14 node 的 status / verification_status 決定。
NEXT_GAME_STATUS_FROM_NODE = {
    ("usable", "verified_against_processed_schedule"): "available",
    ("usable", "unconfirmed_upcoming_starter_identity"): "partially_available",
    ("unusable_blocked", "unconfirmed_upcoming_starter_identity"): "unavailable",
    ("unusable_blocked", "missing_required_data"): "unavailable",
}

NEXT_GAME_STATUS_MAPPING_NOTE = (
    "next_game 各欄位的狀態完全由 Step 14 node 的 (status, verification_status) "
    "對照而來，使用 Step 20 已建立的 4 值詞彙，沒有新增值也沒有重新評估任何事實。"
    "對照表在 NEXT_GAME_STATUS_FROM_NODE。"
)

# 產品顯示槽位（回答「網站要顯示什麼」）。全部是受控識別字。
DISPLAY_SLOT_VALUES = (
    "next_game",
    "current_form",
    "season_baseline",
    "contextual_splits",
    "factual_evidence",
    "sample_size",
    "single_event_sensitivity",
    "rolling_distribution_position",
    "data_status",
    "missing_information",
    "traceability",
)

# 明確記錄「沒有被用來決定產品輸出」的量
PRODUCT_NOT_INPUTS = [
    "magnitude", "sample_size_at_bats", "plate_appearances",
    "percentile_rank", "consistency_count", "classification",
    "noteworthy_classification", "interpretation_status",
]

STEP_REGISTRY = [
    {"step": "Step 3", "topic": "賽程資料來源",
     "module": "src/schedule_source_experiment.py",
     "doc": "docs/SCHEDULE_DATA_SOURCE_INVESTIGATION.md"},
    {"step": "Step 4", "topic": "processed data 落地",
     "module": "src/build_processed_data.py",
     "doc": "docs/DATA_LAYER_VALIDATION.md"},
    {"step": "Step 5", "topic": "逐場與季累計計數",
     "module": "src/player_form_analysis.py",
     "doc": "docs/FIRST_EVIDENCE_ANALYSIS.md"},
    {"step": "Step 6", "topic": "滾動窗口分布",
     "module": "src/rolling_baseline.py",
     "doc": "docs/ROLLING_BASELINE_ANALYSIS.md"},
    {"step": "Step 7A", "topic": "投手手別資料來源",
     "module": "src/splits_vs_hand.py",
     "doc": "docs/PITCHER_HAND_DATA_SOURCE.md"},
    {"step": "Step 8", "topic": "官方分項 context",
     "module": "src/context_splits.py",
     "doc": "docs/CONTEXT_EVIDENCE.md"},
    {"step": "Step 9", "topic": "29 candidates",
     "module": "src/candidate_insights.py",
     "doc": "docs/CANDIDATE_INSIGHT_DESIGN.md"},
    {"step": "Step 11", "topic": "sample context / sensitivity",
     "module": "src/evidence_sample_context.py",
     "doc": "docs/EVIDENCE_SAMPLE_ANALYSIS.md"},
    {"step": "Step 13", "topic": "decision descriptor 詞彙",
     "module": "src/decision_relevance.py",
     "doc": "docs/DECISION_RELEVANCE_EXPERIMENT.md"},
    {"step": "Step 14", "topic": "insight chain / next game",
     "module": "src/insight_chain.py",
     "doc": "docs/INSIGHT_CHAIN_EXPERIMENT.md"},
    {"step": "Step 18", "topic": "9 個 insight group",
     "module": "src/insight_grouping.py",
     "doc": "docs/INSIGHT_GROUPING_EXPERIMENT.md"},
    {"step": "Step 19", "topic": "group decision relevance",
     "module": "src/group_decision_relevance.py",
     "doc": "docs/GROUP_DECISION_RELEVANCE_EXPERIMENT.md"},
    {"step": "Step 20", "topic": "presentation model",
     "module": "src/insight_presentation_model.py",
     "doc": "docs/INSIGHT_PRESENTATION_MODEL.md"},
    {"step": "Step 21", "topic": "factual insight assembly",
     "module": "src/insight_assembly.py",
     "doc": "docs/INSIGHT_ASSEMBLY_EXPERIMENT.md"},
]


# ------------------------------------------------------------------ 工具

def fmt(v, digits: int = 8) -> str:
    if v is None:
        return "null"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def uniform(values: list):
    """同一組值是否一致；不一致回傳 None（不強行合併，沿用 Step 19 做法）。"""
    distinct = sorted({json.dumps(v, ensure_ascii=False, sort_keys=True)
                       for v in values})
    if len(distinct) == 1:
        return values[0], None
    return None, distinct


# ------------------------------------------------------------------ A. player

def build_player_section(logs: list, season: dict) -> dict:
    return {
        "player_name": SUBJECT["player_name"],
        "player_acnt": SUBJECT["player_acnt"],
        "team": SUBJECT["team"],
        "team_code": SUBJECT["team_code"],
        "season": SUBJECT["season"],
        "kind_code": SUBJECT["kind_code"],
        "kind_name": SUBJECT["kind_name"],
        "games_played": len(logs),
        "plate_appearances": season["plate_appearances"],
        "at_bats": season["at_bats"],
        "source_steps": ["Step 4", "Step 5"],
        "source_files": ["data/processed/zhang_yucheng_game_logs_2026.json"],
    }


# ------------------------------------------------------------------ B. next_game

def field_status(node: dict) -> str:
    return NEXT_GAME_STATUS_FROM_NODE[
        (node["status"], node["verification_status"])
    ]


def build_next_game_section(n2: dict, n3: dict, n4: dict) -> dict:
    e2, e3, e4 = n2["evidence"], n3["evidence"], n4["evidence"]
    return {
        "game": {
            "game_sno": e2["game_sno"],
            "game_date": e2["game_date"],
            "scheduled_time": e2["scheduled_time"],
            "opponent": e2["opponent"],
            "home_away": e2["home_away"],
            "venue": e2["venue"],
            "game_status": e2["game_status"],
            "data_status": field_status(n2),
            "source_step": "Step 14（node N2，資料來自 Step 3 / 4）",
            "source_file": "data/processed/fubon_schedule_2026.json",
        },
        "result_not_available": {
            "home_score": e2["home_score"],
            "visiting_score": e2["visiting_score"],
            "null_reason": e2["score_is_null_reason"],
            "raw_values_for_traceability_only":
                copy.deepcopy(e2["source_score_values_for_traceability"]),
            "data_status": "unavailable",
        },
        "opponent_starting_pitcher": {
            "pitcher_acnt": e3["pitcher_acnt"],
            "pitcher_name": e3["pitcher_name"],
            "pitcher_name_null_reason": e3["pitcher_name_missing_reason"],
            "team": e3["team"],
            "team_side": e3["team_side"],
            "verification_status": n3["verification_status"],
            "unconfirmed_reason": n3["unconfirmed_reason"],
            "data_status": field_status(n3),
            "source_step": "Step 14（node N3，資料來自 Step 3 / 4 / 7A）",
            "source_file": "data/processed/fubon_schedule_2026.json",
        },
        "opponent_starting_pitcher_hand": {
            "hand": e4["hand"],
            "hand_vocabulary": ["L", "R"],
            "null_reason": e4["missing_reason"],
            "required_to_resolve": e4["required_to_resolve"],
            "verification_status": n4["verification_status"],
            "data_status": field_status(n4),
            "source_step": "Step 14（node N4，方法參考 Step 7A）",
            "source_file": "docs/PITCHER_HAND_DATA_SOURCE.md",
        },
        "selection_rule": {
            "reference_date": n2["selection_rule"]["reference_date"],
            "reference_date_basis": n2["selection_rule"]["reference_date_basis"],
            "rule": n2["selection_rule"]["rule"],
            "clock_independent": n2["selection_rule"]["clock_independent"],
            "clock_independent_note": (
                "參考日由已完成比賽推導，不使用系統時鐘，因此輸出 deterministic"
                "（Step 14 已記錄）。"
            ),
        },
        "status_mapping_note": NEXT_GAME_STATUS_MAPPING_NOTE,
        "is_not": (
            "next_game 只提供下一場的既有賽程事實與資料缺口狀態。"
            "沒有任何對比賽結果或球員表現的推估。"
        ),
    }


# ------------------------------------------------------------------ season_baseline

def build_season_baseline_section(logs: list, season: dict,
                                  insights: list) -> dict:
    """全部 25 個 metric 列共用同一組季累計基準，因此提到頂層一次。

    這是**引用副本**，validation 會逐一比對它等於每個 insight 的 baseline_value。
    """
    return {
        "definition": "2026 一軍例行賽季累計（77 場實際出賽）",
        "games": len(logs),
        "plate_appearances": season["plate_appearances"],
        "at_bats": season["at_bats"],
        "hits": season["hits"],
        "total_bases": season["total_bases"],
        "walks": season["walks"],
        "hit_by_pitch": season["hit_by_pitch"],
        "sacrifice_flies": season["sacrifice_flies"],
        "metrics": {
            "batting_average": {
                "value": season["batting_average"],
                "derivation": "hits / at_bats",
                "source_step": "Step 5",
                "source_file": "data/processed/zhang_yucheng_game_logs_2026.json",
            },
            "on_base_percentage": {
                "value": season["on_base_percentage"],
                "derivation": (
                    "(hits + walks + hit_by_pitch) / "
                    "(at_bats + walks + hit_by_pitch + sacrifice_flies)"
                ),
                "source_step": "Step 8",
                "source_file": "data/raw/apart_score_0000006888_2026_A_01.json",
                "note": (
                    "processed data 未收逐場犧牲飛球，因此季 OBP 由官方分項"
                    "「VS. 右投」+「VS. 左投」加總取得（Step 8 已驗證三組加總一致）。"
                ),
            },
            "slugging_percentage": {
                "value": season["slugging_percentage"],
                "derivation": "total_bases / at_bats",
                "source_step": "Step 5",
                "source_file": "data/processed/zhang_yucheng_game_logs_2026.json",
            },
        },
        "hoisting_note": (
            "25 個 metric 列的 baseline_value 完全相同，因此在頂層提供一次，"
            "讓消費端不必掃描全部 insight 才能顯示季基準。"
            "每個 insight 裡的 baseline_value 仍然原樣保留，沒有被移除。"
        ),
    }


# ------------------------------------------------------------------ C / D. section 描述子

def build_section(section_id: str, perspectives: list, insights: list,
                  presentation: dict, display_slots: list) -> dict:
    """section 只放**參照**，不複製 insight 內容（避免 Step 20 已消除的重複）。

    一個 section 可以涵蓋多個 Step 13 perspective。涵蓋多個時，perspective
    的區分以 subgroups_by_perspective 完整保留，不會被合併掉。
    """
    members = [i for i in insights
               if i["identity"]["perspective"] in perspectives]
    members = sorted(members, key=lambda i: i["identity"]["scope"])

    scopes = [i["identity"]["scope"] for i in members]
    cand_ids = [cid for i in members for cid in i["identity"]["candidate_ids"]]

    by_perspective: dict[str, list] = {}
    for i in members:
        by_perspective.setdefault(
            i["identity"]["perspective"], []).append(i["identity"]["scope"])

    ev_status = sorted({
        i["limitations"]["data_availability"]["evidence_data_status"]
        for i in members
    })
    app_status_by_scope = {
        i["identity"]["scope"]:
            i["limitations"]["data_availability"]["application_data_status"]
        for i in members
    }
    temporal, temporal_conflict = uniform(
        [i["context"]["temporal_relevance"] for i in members])

    # 依 Step 19 的 contextual_relevance 再分組（既有詞彙，不新增）
    by_relevance: dict[str, list] = {}
    for i in members:
        by_relevance.setdefault(
            i["context"]["contextual_relevance"], []
        ).append(i["identity"]["scope"])

    return {
        "section_id": section_id,
        "perspectives": list(perspectives),
        "perspective_names": [PERSPECTIVES[p]["name"] for p in perspectives],
        "subgroups_by_perspective": {
            k: sorted(v) for k, v in sorted(by_perspective.items())
        },
        "group_count": len(members),
        "candidate_count": len(cand_ids),
        "scopes": scopes,
        "insight_refs": [
            {
                "insight_id": i["identity"]["insight_id"],
                "group_id": i["identity"]["group_id"],
                "scope": i["identity"]["scope"],
                "candidate_ids": list(i["identity"]["candidate_ids"]),
                "official_item_name": i["context"]["context_official_item_name"],
                "pointer": f"factual_insights.{i['identity']['insight_id']}",
                "presentation_purpose":
                    presentation[i["identity"]["scope"]]["presentation_purpose"][
                        "purpose"],
            }
            for i in members
        ],
        "temporal_relevance": temporal,
        "temporal_relevance_conflict": temporal_conflict,
        "subgroups_by_contextual_relevance": {
            k: sorted(v) for k, v in sorted(by_relevance.items())
        },
        "evidence_data_status_values": ev_status,
        "application_data_status_by_scope": app_status_by_scope,
        "application_data_status_values":
            sorted(set(app_status_by_scope.values())),
        "status_separation_note": (
            "evidence_data_status 與 application_data_status 是兩件不同的事，"
            "本 section 逐 scope 保留 application 狀態，不聚合成單一值。"
        ),
        "display_slots": list(display_slots),
        "member_selection_rule": {
            "rule_id": "P22-S",
            "rule_text": (
                "section 成員完全由 Step 13 / 18 的 perspective 決定，"
                "不依 magnitude、sample size、classification 或 interpretation_status。"
            ),
            "rule_inputs": ["step18_perspective"],
            "rule_not_inputs": list(PRODUCT_NOT_INPUTS),
            "all_groups_included": True,
        },
        "contains_no_duplication_note": (
            "此處只放 insight_id 與 pointer。metric 數值只存在於 "
            "factual_insights 一處，避免 Step 20 已消除的重複再度出現。"
        ),
    }


# ------------------------------------------------------------------ F. data_status

def build_data_status_section(insights: list, next_game: dict) -> dict:
    ev = {}
    app = {}
    for i in insights:
        scope = i["identity"]["scope"]
        da = i["limitations"]["data_availability"]
        ev[scope] = da["evidence_data_status"]
        app[scope] = da["application_data_status"]

    # 缺口登錄簿：以 required item 為鍵，彙整受影響的 scope
    registry: dict[str, dict] = {}
    for i in insights:
        scope = i["identity"]["scope"]
        for item in i["limitations"]["missing_data"]["required_additional_data"]:
            entry = registry.setdefault(item["item"], {
                "item": item["item"],
                "status": item["status"],
                "vocabulary": list(DATA_STATUS_VALUES),
                "availability_source_step": item["availability_source_step"],
                "evidence_steps": list(item["evidence_steps"]),
                "factual_basis": item["factual_basis"],
                "affected_scopes": [],
                "is_gap": item["status"] != "available",
            })
            entry["affected_scopes"].append(scope)
    for entry in registry.values():
        entry["affected_scopes"] = sorted(entry["affected_scopes"])
        entry["affected_scope_count"] = len(entry["affected_scopes"])

    # metric 層缺口（值不存在）
    metric_gaps = []
    for i in insights:
        for s in i["phenomenon"]["statements"]:
            if s["statement_kind"] != "explicit_null":
                continue
            metric_gaps.append({
                "insight_id": i["identity"]["insight_id"],
                "scope": i["identity"]["scope"],
                "metric": s["metric"],
                "value": None,
                "null_reason":
                    i["limitations"]["unavailable_metrics"]["reason"],
                "interpretation_status": s["interpretation_status"],
                "value_policy":
                    i["limitations"]["unavailable_metrics"]["value_policy"],
            })

    cross = {}
    for scope in sorted(ev):
        cross.setdefault(ev[scope], {}).setdefault(app[scope], []).append(scope)

    return {
        "evidence_data_status_by_scope": ev,
        "application_data_status_by_scope": app,
        "vocabulary": list(DATA_STATUS_VALUES),
        "vocabulary_source_step": "Step 20",
        "separation": {
            "fields_are_independent": True,
            "cross_tabulation": cross,
            "distinct_evidence_values": sorted(set(ev.values())),
            "distinct_application_values": sorted(set(app.values())),
            "basis_is_not_a_single_boolean": (
                "evidence 全部 available，但 application 有 4 種值。"
                "把兩者合併成一個欄位或一個 boolean 會遺失這個區分。"
                "Step 20 第 8 節已記錄。"
            ),
        },
        "missing_information_registry": [
            registry[k] for k in sorted(registry)
        ],
        "missing_information_gap_count": sum(
            1 for e in registry.values() if e["is_gap"]),
        "metric_level_gaps": metric_gaps,
        "metric_level_gap_count": len(metric_gaps),
        "next_game_field_status": {
            "game": next_game["game"]["data_status"],
            "result": next_game["result_not_available"]["data_status"],
            "opponent_starting_pitcher":
                next_game["opponent_starting_pitcher"]["data_status"],
            "opponent_starting_pitcher_hand":
                next_game["opponent_starting_pitcher_hand"]["data_status"],
        },
        "null_representation_policy": {
            "rule": "null + 明確原因，永不靜默省略",
            "requirements": [
                "缺失值一律寫成 null，不用 0、空字串或省略欄位表示",
                "每個 null 旁邊必須有一個 *_reason 或 *_null_reason 欄位",
                "缺失原因必須指向既有 Step 的調查結果，不得寫成模糊來源",
                "不估算、不內插、不填補",
            ],
            "verified_by": "validation 第 7 / 13 / 15 項",
        },
    }


# ------------------------------------------------------------------ G. traceability

def build_traceability_section(insights: list) -> dict:
    files = {
        "data/processed/zhang_yucheng_game_logs_2026.json": PLAYER_LOG_PATH,
        "data/raw/apart_score_0000006888_2026_A_01.json": APART_CACHE_PATH,
        "data/processed/fubon_schedule_2026.json": SCHEDULE_PATH,
    }
    file_records = []
    for rel, path in sorted(files.items()):
        digest, size = sha256_of(path)
        file_records.append({
            "path": rel,
            "sha256": digest,
            "bytes": size,
            "exists": path.exists(),
        })

    index = []
    for i in insights:
        iid = i["identity"]["insight_id"]
        for metric in ALL_METRICS:
            entry = i["traceability"]["by_metric"].get(metric)
            if entry is None:
                index.append({
                    "insight_id": iid,
                    "scope": i["identity"]["scope"],
                    "metric": metric,
                    "traceable": False,
                    "pointer": None,
                    "not_traceable_reason":
                        i["limitations"]["unavailable_metrics"]["reason"],
                })
                continue
            index.append({
                "insight_id": iid,
                "scope": i["identity"]["scope"],
                "metric": metric,
                "traceable": True,
                "pointer": f"factual_insights.{iid}.traceability.by_metric.{metric}",
                "source_step_ids": list(entry["source_step_ids"]),
                "source_file": entry["source_file"],
                "has_game_snos": bool(entry["game_snos"]),
            })

    return {
        "source_files": file_records,
        "step_registry": copy.deepcopy(STEP_REGISTRY),
        "metric_index": index,
        "metric_index_count": len(index),
        "traceable_metric_count": sum(1 for e in index if e["traceable"]),
        "pointer_note": (
            "metric_index 只放指標與 pointer，實際的 source_step / source_file / "
            "source_field / derivation / game_snos 存在 factual_insights 裡一處，"
            "不重複。pointer 可直接解析。"
        ),
        "provenance_rule": {
            "rule": "每個事實數值都必須指到 step + file + field + formula",
            "forbidden": "不接受「source = CPBL」這類模糊來源",
            "verified_by": "validation 第 14 項（逐 pointer 解析並檢查 4 個必填欄位）",
        },
    }


# ------------------------------------------------------------------ H. metadata

def build_metadata_section(insights: list, groups: list, candidates: list,
                           sections: dict) -> dict:
    metric_rows = sum(
        i["supporting_evidence"]["primary_metric_count"] for i in insights)
    null_slots = sum(
        1 for i in insights for s in i["phenomenon"]["statements"]
        if s["statement_kind"] == "explicit_null")
    patterns = sum(
        1 for i in insights
        if i["phenomenon"]["cross_metric_statement"] is not None)

    return {
        "product_output_version": PRODUCT_OUTPUT_VERSION,
        "subject_kind": "single_player_pre_game_reference",
        "counts": {
            "groups": len(groups),
            "candidates": len(candidates),
            "insights": len(insights),
            "sections": len(sections),
            "metric_rows": metric_rows,
            "null_metric_slots": null_slots,
            "cross_metric_direction_summaries": patterns,
        },
        "generated_from_steps": [r["step"] for r in STEP_REGISTRY],
        "determinism": {
            "deterministic": True,
            "clock_independent": True,
            "input_order_independent": True,
            "basis": (
                "所有集合一律排序後輸出；next_game 的參考日由已完成比賽推導，"
                "不讀系統時鐘；驗證含重跑比對與輸入順序打亂比對。"
            ),
        },
        "controlled_vocabularies": {
            "data_status": {"values": list(DATA_STATUS_VALUES),
                            "origin_step": "Step 20"},
            "evidence_self_containment": {
                "values": list(EVIDENCE_SELF_CONTAINMENT_VALUES),
                "origin_step": "Step 20"},
            "application_readiness": {
                "values": list(APPLICATION_READINESS_VALUES),
                "origin_step": "Step 20"},
            "presentation_purpose": {"values": list(PRESENTATION_PURPOSE_VALUES),
                                     "origin_step": "Step 20"},
            "interpretation_status": {
                "values": list(INTERPRETATION_STATUS_VALUES),
                "origin_step": "Step 21"},
            "statement_kind": {"values": list(STATEMENT_KIND_VALUES),
                               "origin_step": "Step 21"},
            "evidence_kind": {"values": list(EVIDENCE_KIND_VALUES),
                              "origin_step": "Step 21"},
            "direction": {"values": list(DIRECTION_VALUES),
                          "origin_step": "Step 9"},
            "temporal_relevance": {"values": list(TEMPORAL_RELEVANCE_VALUES),
                                   "origin_step": "Step 13"},
            "contextual_relevance": {"values": list(CONTEXTUAL_RELEVANCE_VALUES),
                                     "origin_step": "Step 13"},
            "possible_action_link": {"values": list(ALLOWED_ACTION_LINKS),
                                     "origin_step": "Step 13"},
            "action_link_requires": {
                "values": list(ALLOWED_ACTION_LINK_REQUIRES),
                "origin_step": "Step 13"},
            "possible_decision_area": {"values": list(ALLOWED_DECISION_AREAS),
                                       "origin_step": "Step 13"},
            "display_slot": {"values": list(DISPLAY_SLOT_VALUES),
                             "origin_step": "Step 22"},
            "new_in_step_22": ["display_slot"],
            "new_vocabulary_justification": (
                "display_slot 是唯一在本階段新增的詞彙，用來回答「網站要顯示什麼」。"
                "它不描述任何資料事實，只是版面槽位的識別字，"
                "因此不可能改變任何既有判定。"
            ),
        },
        "display_contract": build_display_contract(insights),
        "product_rule": {
            "rule_id": "P22-1",
            "version": "first_version",
            "rule_text": (
                "產品輸出完全由既有 Step 的輸出組裝而成。"
                "所有數值原樣引用 Step 21，不重算、不篩選、不排序、不省略。"
            ),
            "rule_inputs": ["step14_next_game_nodes", "step18_groups",
                            "step19_group_relevance", "step20_presentation_model",
                            "step21_factual_insights"],
            "rule_not_inputs": list(PRODUCT_NOT_INPUTS),
            "all_groups_included": True,
        },
        "consumer_contract": {
            "single_source_of_numbers": "factual_insights",
            "sections_hold_references_only": True,
            "safe_to_render_all": (
                "9 個 insight 全部應該顯示。沒有任何欄位指示消費端隱藏、"
                "排序或挑選 insight。"
            ),
            "must_not_do": [
                "不得依 difference 大小排序或挑選",
                "不得依 sample size 隱藏",
                "不得把 application_data_status != available 當成 evidence 有問題",
                "不得把 null 顯示成 0 或省略",
                "不得自行生成文字結論",
            ],
        },
        "contains_no": [
            "score", "weight", "threshold", "ranking", "priority", "importance",
            "confidence_score", "top_n", "prediction", "recommendation",
            "strategy", "natural_language_conclusion", "llm", "ui", "api",
        ],
    }


def build_display_contract(insights: list) -> list:
    """每個顯示槽位對應到輸出中的哪個路徑、目前是否有資料。"""
    has_rolling = sorted({
        i["identity"]["scope"] for i in insights
        for e in i["supporting_evidence"]["primary_metrics"]
        if e["rolling_percentile"] is not None
    })
    return [
        {"slot": "next_game", "source_path": "next_game",
         "source_step": "Step 14",
         "availability": "partial",
         "availability_note": (
             "賽程事實 available；對手先發身分 partially_available；"
             "手別 unavailable。逐欄位狀態見 data_status.next_game_field_status。")},
        {"slot": "current_form", "source_path": "current_form.insight_refs",
         "source_step": "Step 18 / 21",
         "availability": "available",
         "availability_note": "RECENT_10 / RECENT_15，AVG 與 SLG；OBP 為 null。"},
        {"slot": "season_baseline", "source_path": "season_baseline",
         "source_step": "Step 5 / 8",
         "availability": "available",
         "availability_note": "AVG / OBP / SLG 三項齊全。"},
        {"slot": "contextual_splits",
         "source_path": "contextual_evidence.insight_refs",
         "source_step": "Step 8 / 18 / 21",
         "availability": "available",
         "availability_note": "7 個官方分項，每個 3 個 metric。"},
        {"slot": "factual_evidence",
         "source_path": "factual_insights.<insight_id>.supporting_evidence",
         "source_step": "Step 21",
         "availability": "available",
         "availability_note": "25 個 metric 列，全部帶 current / baseline / "
                              "difference / direction。"},
        {"slot": "sample_size",
         "source_path": "factual_insights.<insight_id>"
                        ".supporting_evidence.primary_metrics[].sample_size",
         "source_step": "Step 11",
         "availability": "partial",
         "availability_note": "AB / PA 全部有值；7 個官方分項的 games 為 null + 原因。"},
        {"slot": "single_event_sensitivity",
         "source_path": "factual_insights.<insight_id>"
                        ".supporting_evidence.primary_metrics[].sensitivity",
         "source_step": "Step 11",
         "availability": "available",
         "availability_note": "25 個 metric 列全部有值。"},
        {"slot": "rolling_distribution_position",
         "source_path": "factual_insights.<insight_id>"
                        ".supporting_evidence.primary_metrics[].rolling_percentile",
         "source_step": "Step 6",
         "availability": "partial",
         "availability_note": f"只有 {has_rolling} 有值；"
                              "官方分項沒有時間維度，因此為 null + 原因。"},
        {"slot": "data_status", "source_path": "data_status",
         "source_step": "Step 19 / 20",
         "availability": "available",
         "availability_note": "evidence 與 application 兩個狀態分開保留。"},
        {"slot": "missing_information",
         "source_path": "data_status.missing_information_registry",
         "additional_source_paths": ["data_status.metric_level_gaps"],
         "source_step": "Step 19 / 20 / 21",
         "availability": "available",
         "availability_note": "4 筆應用層 required 項目 + 2 筆 metric 層缺口。"},
        {"slot": "traceability", "source_path": "traceability",
         "source_step": "Step 4 ~ 21",
         "availability": "available",
         "availability_note": "3 個來源檔的 sha256 + 27 筆 metric 索引。"},
    ]


# ------------------------------------------------------------------ 組裝

def assemble_product_output(logs: list, apart_rows: list, schedule: list,
                            candidates: list, groups: list, group_rel: list,
                            presentation: list, insights: list) -> dict:
    """把既有 Step 輸出組裝成產品輸出。所有數值原樣引用，不重算。"""
    contexts = build_context_evidence(apart_rows)
    season = build_season_baseline(logs, contexts)

    game, as_of = pick_next_game(schedule)
    n2 = build_next_game_node(game, as_of)
    n3 = build_next_starting_pitcher_node(game, schedule)
    n4 = build_pitcher_hand_node(n3)

    insights = sorted(copy.deepcopy(insights),
                      key=lambda i: i["identity"]["scope"])
    pres_by_scope = {r["group_identity"]["scope"]: r for r in presentation}

    next_game = build_next_game_section(n2, n3, n4)

    current_form = build_section(
        "current_form", ["A_CURRENT_FORM"], insights, pres_by_scope,
        ["current_form", "factual_evidence", "sample_size",
         "single_event_sensitivity", "rolling_distribution_position",
         "data_status", "missing_information", "traceability"],
    )
    # Perspective B 與 C 都是官方分項（ItemGroupCode = 3）的季累計切分，
    # 因此放在同一個 section；兩者的 perspective 區分以
    # subgroups_by_perspective 完整保留，沒有被合併掉。
    contextual_evidence = build_section(
        "contextual_evidence", ["B_MATCHUP_CONTEXT", "C_STRUCTURAL_CONTEXT"],
        insights, pres_by_scope,
        ["contextual_splits", "factual_evidence", "sample_size",
         "single_event_sensitivity", "data_status", "missing_information",
         "traceability"],
    )

    factual_insights = {i["identity"]["insight_id"]: i for i in insights}

    output = {
        "player": build_player_section(logs, season),
        "next_game": next_game,
        "season_baseline": build_season_baseline_section(logs, season, insights),
        "current_form": current_form,
        "contextual_evidence": contextual_evidence,
        "factual_insights": factual_insights,
        "data_status": build_data_status_section(insights, next_game),
        "traceability": build_traceability_section(insights),
    }
    output["metadata"] = build_metadata_section(
        insights, groups, candidates,
        {"current_form": current_form, "contextual_evidence": contextual_evidence},
    )
    return output


def build_product_output(logs: list, apart_rows: list, schedule: list) -> dict:
    parts = build_step21(logs, apart_rows)
    candidates, groups, group_rel, _samples, presentation, insights = parts
    return assemble_product_output(logs, apart_rows, schedule, candidates,
                                   groups, group_rel, presentation, insights)


# ------------------------------------------------------------------ pointer 解析

def resolve_pointer(output: dict, pointer: str):
    cur = output
    for part in pointer.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


# ------------------------------------------------------------------ 反證

def structural_signature(output: dict) -> str:
    """只含結構、受控詞彙與識別字，不含任何數值。"""
    def key_paths(obj, prefix=""):
        paths = []
        if isinstance(obj, dict):
            for k in sorted(obj):
                paths.append(f"{prefix}.{k}")
                paths += key_paths(obj[k], f"{prefix}.{k}")
        elif isinstance(obj, list):
            for v in obj:
                paths += key_paths(v, f"{prefix}[]")
        return paths

    ds = output["data_status"]
    return json.dumps({
        "keys": sorted(set(key_paths(output))),
        "insight_ids": sorted(output["factual_insights"]),
        "section_scopes": {
            sid: output[sid]["scopes"]
            for sid in ("current_form", "contextual_evidence")
        },
        "section_candidates": {
            sid: sorted(cid for r in output[sid]["insight_refs"]
                        for cid in r["candidate_ids"])
            for sid in ("current_form", "contextual_evidence")
        },
        "evidence_status": ds["evidence_data_status_by_scope"],
        "application_status": ds["application_data_status_by_scope"],
        "registry": [(e["item"], e["status"], e["affected_scopes"])
                     for e in ds["missing_information_registry"]],
        "metric_gaps": [(g["scope"], g["metric"], g["interpretation_status"])
                        for g in ds["metric_level_gaps"]],
        "next_game_status": ds["next_game_field_status"],
        "counts": output["metadata"]["counts"],
        "display_contract": [(d["slot"], d["source_path"], d["availability"])
                             for d in output["metadata"]["display_contract"]],
        "vocabularies": output["metadata"]["controlled_vocabularies"],
        "product_rule": output["metadata"]["product_rule"],
    }, ensure_ascii=False, sort_keys=True)


def full_signature(output: dict) -> str:
    return json.dumps(output, ensure_ascii=False, sort_keys=True)


def rebuild_from_mutated_parts(logs, apart_rows, schedule, candidates,
                               views, samples, nw_records):
    """從變異後的 candidate 層重建 Step 18~22。沿用 Step 21 的做法。"""
    step13 = [
        build_relevance_record(c, views[c["candidate_id"]],
                               samples[c["candidate_id"]])
        for c in candidates
    ]
    nw_by_id = {r["candidate_id"]: r for r in nw_records}
    groups = build_groups(candidates, views, samples, nw_by_id)
    group_rel = build_group_relevance(groups, step13)
    presentation = build_presentation_model(groups, group_rel, candidates, samples)
    insights = build_insights(presentation, candidates)
    return assemble_product_output(logs, apart_rows, schedule, candidates,
                                   groups, group_rel, presentation, insights)


def mutation_test(logs: list, apart_rows: list, schedule: list,
                  baseline: dict) -> dict:
    """七種變異。全部在深拷貝上操作，不動原始輸入。

    數值類變異（magnitude / AB）刻意在 **candidate 層** 操作，與 Step 19 / 21
    的 mutation test 同一層。原因：Step 9 只在三個指標方向一致時才建立
    MULTI_METRIC_PATTERN，所以直接改動 raw 逐場計數會改變 candidate 的**存在
    與否**，那是 Step 9 的既有行為，不是 Step 22 的組裝規則。要反證「產品組裝
    不看數值」，必須固定 candidate 集合再改數值。

    - magnitude / AB：數字會跟著變，但**結構簽章**不得變。
    - 順序類變異不帶任何資料變化：**完整輸出**必須逐位元相同。
    """
    base_struct = structural_signature(baseline)
    base_full = full_signature(baseline)
    diffs = []
    leaks = []
    cases = 0
    mutants = []

    def value_mutant(kind, value):
        candidates, views, samples, _pbc, nw_records = build_classification(
            logs, apart_rows
        )
        candidates = copy.deepcopy(candidates)
        views = copy.deepcopy(views)
        samples = copy.deepcopy(samples)
        nw_records = copy.deepcopy(nw_records)
        if kind == "magnitude":
            for c in candidates:
                if c["type"] == "TREND":
                    c["absolute_difference"] = value
                    c["absolute_difference_magnitude"] = abs(value)
                elif c["type"] == "CONTEXT":
                    c["comparison"]["difference"] = value
                    c["comparison"]["difference_magnitude"] = abs(value)
                else:
                    for mv in c["metric_values"].values():
                        mv["difference"] = value
                views[c["candidate_id"]]["magnitude"] = abs(value)
        else:
            for c in candidates:
                samples[c["candidate_id"]]["sample_context"]["at_bats"] = value
                c["at_bats"] = value
        return rebuild_from_mutated_parts(
            logs, apart_rows, schedule, candidates, views, samples, nw_records)

    for value in (0.0, 999.0):
        mutants.append((f"magnitude={value}", "struct",
                        lambda v=value: value_mutant("magnitude", v)))
    for value in (1, 9999):
        mutants.append((f"at_bats={value}", "struct",
                        lambda v=value: value_mutant("at_bats", v)))

    def order_mutant(mutate_logs=None, mutate_apart=None, mutate_sched=None):
        lg = copy.deepcopy(logs)
        ap = copy.deepcopy(apart_rows)
        sc = copy.deepcopy(schedule)
        if mutate_logs:
            mutate_logs(lg)
        if mutate_apart:
            mutate_apart(ap)
        if mutate_sched:
            sc = mutate_sched(sc)
        return build_product_output(lg, ap, sc)

    mutants.append(("logs_order=shuffled", "full", lambda: order_mutant(
        mutate_logs=lambda lg: random.Random(20260820).shuffle(lg))))
    mutants.append(("apart_rows_order=shuffled", "full", lambda: order_mutant(
        mutate_apart=lambda ap: random.Random(4242).shuffle(ap))))
    mutants.append(("schedule_order=reversed", "full", lambda: order_mutant(
        mutate_sched=lambda sc: list(reversed(sc)))))

    for name, strictness, fn in mutants:
        got = fn()
        cases += 1
        if strictness == "struct":
            if structural_signature(got) != base_struct:
                diffs.append(f"{name} 時結構簽章改變")
        else:
            if full_signature(got) != base_full:
                diffs.append(f"{name} 時完整輸出改變")
        bad = scan_keys(got)
        if bad:
            leaks.append(f"{name}: {sorted(set(bad))[:3]}")

    return {
        "mutants": [f"{n}（{s}）" for n, s, _ in mutants],
        "cases_tested": cases,
        "changes": diffs,
        "forbidden_key_leaks": leaks,
        "structure_independent_of_values": not diffs and not leaks,
    }


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "threshold", "rank", "priority",
                  "importance", "confidence", "top_n", "recommend", "predict")

# 例外說明：
#   percentile_rank / rank_desc  -> Step 6 的分布描述子，不是 candidate 名次
#   home_score / visiting_score 等 -> CPBL 官方比分欄位，值為 null + 原因
ALLOWED_KEY_EXCEPTIONS = (
    "percentile_rank", "rank_desc",
    # CPBL 官方比分欄位（Step 4 落地的 home_score / visiting_score）。
    # 產品輸出中一律為 null + 原因；*_in_file 是 Step 14 原樣保留的檔內原值。
    "home_score", "visiting_score", "score_is_null_reason",
    "source_score_values_for_traceability",
    "home_score_in_file", "visiting_score_in_file",
)
DECLARATIVE_KEYS = ("contains_no", "rule_not_inputs", "contains_no_judgement",
                    "must_not_do", "forbidden", "new_in_step_22")

LLM_PACKAGE_NAMES = frozenset({
    "openai", "anthropic", "cohere", "vertexai", "transformers", "langchain",
    "llama_index", "ollama", "litellm", "mistralai", "torch", "tensorflow",
    "huggingface_hub",
})

UI_PACKAGE_NAMES = frozenset({
    "flask", "fastapi", "django", "streamlit", "dash", "jinja2", "starlette",
    "uvicorn", "tkinter", "aiohttp", "requests", "httpx", "urllib3",
})


def collect_imported_modules(path: Path) -> set[str]:
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


def collect_declarative_text(obj, out: list) -> None:
    markers = ("is_not", "not_a", "not_inputs", "not_do", "contains_no",
               "limitation", "boundary", "exclusion", "guessing", "meaning",
               "note", "justification", "origin", "rationale", "definition",
               "basis", "reason", "rule", "vocabulary", "policy", "forbidden",
               "requirements", "contract", "topic", "doc")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(m in k.lower() for m in markers):
                out.append(json.dumps(v, ensure_ascii=False))
            else:
                collect_declarative_text(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_declarative_text(v, out)


def list_data_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix()
                  for p in (ROOT / "data").rglob("*") if p.is_file())


def run_validation(output: dict, rerun: dict, insights: list, groups: list,
                   candidates: list, group_rel: list, presentation: list,
                   samples: dict, mutation: dict,
                   fingerprints_before: dict,
                   data_files_before: list) -> list:
    checks: list[tuple[str, bool, str]] = []
    fi = output["factual_insights"]
    ins_by_scope = {i["identity"]["scope"]: i for i in insights}
    grp_by_scope = {g["scope"]: g for g in groups}
    rel_by_scope = {r["scope"]: r for r in group_rel}
    pres_by_scope = {r["group_identity"]["scope"]: r for r in presentation}
    sections = ("current_form", "contextual_evidence")

    # 1. 9 個 group 全部被呈現
    scopes_in_sections = sorted(
        s for sid in sections for s in output[sid]["scopes"])
    ok1 = (len(fi) == 9 == len(groups)
           and scopes_in_sections == sorted(grp_by_scope)
           and output["metadata"]["counts"]["groups"] == 9)
    checks.append(
        ("9 個 group 全部被呈現，沒有任何 group 被省略", ok1,
         f"factual_insights {len(fi)} 個；current_form "
         f"{output['current_form']['group_count']} 個 + contextual_evidence "
         f"{output['contextual_evidence']['group_count']} 個 = 9；"
         "section scope 集合與 Step 18 完全相同")
    )

    # 2. 29 個 candidate 全部可經由 group 追溯
    seen: list[str] = []
    for sid in sections:
        for ref in output[sid]["insight_refs"]:
            g = grp_by_scope[ref["scope"]]
            if ref["candidate_ids"] != g["member_candidate_ids"]:
                seen.append(f"{ref['scope']} 成員不符 Step 18")
            seen.extend(ref["candidate_ids"])
    all_ids = [c["candidate_id"] for c in candidates]
    dupes = [x for x in set(seen) if seen.count(x) > 1]
    ok2 = (sorted(x for x in seen if x in all_ids) == sorted(all_ids)
           and not dupes and len(all_ids) == 29)
    checks.append(
        ("29 個 candidate 全部可經由 group 追溯，無遺漏無重複", ok2,
         f"section 的 insight_refs 共列出 {len(all_ids)} 個 candidate_id，"
         "與 Step 9 的 29 個完全相同，且沒有任何 candidate 出現在兩個 section"
         if ok2 else f"問題={dupes[:5] or seen[:3]}")
    )

    # 3. Step 21 factual insights 原樣呈現，數值未改
    step21_by_id = {i["identity"]["insight_id"]: i for i in insights}
    ok3 = (sorted(fi) == sorted(step21_by_id)
           and all(fi[k] == step21_by_id[k] for k in fi))
    checks.append(
        ("Step 21 factual insights 原樣呈現，數值完全未改", ok3,
         f"{len(fi)} 個 insight 物件與 Step 21 輸出做深度比較，逐欄位完全相同"
         if ok3 else "有 insight 被改動")
    )

    # 3b. 每個 metric 的 5 個核心數值都保留
    core_bad = []
    core_rows = 0
    for iid, i in fi.items():
        for e in i["supporting_evidence"]["primary_metrics"]:
            core_rows += 1
            for key in ("current_value", "baseline_value", "difference",
                        "direction", "sample_size", "sensitivity"):
                if key not in e:
                    core_bad.append(f"{iid}/{e['metric']} 缺 {key}")
            if e["difference"] is None or e["direction"] not in DIRECTION_VALUES:
                core_bad.append(f"{iid}/{e['metric']} difference/direction 異常")
            if "rolling_percentile" not in e:
                core_bad.append(f"{iid}/{e['metric']} 缺 rolling_percentile 欄位")
    checks.append(
        ("每個 factual metric 都保留 current / baseline / difference / direction / "
         "sample_size / sensitivity / rolling_distribution_position", not core_bad,
         f"{core_rows} 個 metric 列逐欄位檢查通過；rolling_percentile 欄位一律存在"
         "（無值時為 null 並附原因）"
         if not core_bad else "；".join(core_bad[:5]))
    )

    # 4. Step 19 decision relevance 保留
    dr_bad = []
    dr_cmp = 0
    for scope, i in ins_by_scope.items():
        src = rel_by_scope[scope]
        c = fi[i["identity"]["insight_id"]]["context"]
        pairs = [
            (c["temporal_relevance"], src["temporal_relevance"]),
            (c["contextual_relevance"], src["contextual_relevance"]),
            (c["context_official_item_name"], src["context_official_item_name"]),
            (c["next_game_dependency"]["evidence_depends_on_next_game"],
             src["next_game_dependency"]["evidence_depends_on_next_game"]),
            (c["application_dependency"]["requires_additional_data"],
             src["application_dependency"]["requires_additional_data"]),
            (c["application_dependency"]["additional_data"],
             src["application_dependency"]["additional_data"]),
            (c["possible_action_link"],
             src["action_link"]["possible_action_link"]),
            (c["possible_decision_area"],
             src["action_link"]["possible_decision_area"]),
        ]
        for got, exp in pairs:
            dr_cmp += 1
            if got != exp:
                dr_bad.append(f"{scope} decision relevance 欄位不符 Step 19")
        # section 層的 subgroup 也必須來自 Step 19 的 contextual_relevance
    sub_all = {}
    for sid in sections:
        for rel, sc in output[sid]["subgroups_by_contextual_relevance"].items():
            if rel not in CONTEXTUAL_RELEVANCE_VALUES:
                dr_bad.append(f"{sid} subgroup {rel} 不在 Step 13 詞彙內")
            sub_all[rel] = sc
            for s in sc:
                if rel_by_scope[s]["contextual_relevance"] != rel:
                    dr_bad.append(f"{s} subgroup 分派不符 Step 19")
    checks.append(
        ("Step 19 decision relevance 完全保留", not dr_bad,
         f"9 個 scope × 8 個欄位 = {dr_cmp} 次比對相符；"
         f"section 的 contextual_relevance 分組 {sub_all} 逐一回查 Step 19 相符"
         if not dr_bad else "；".join(dr_bad[:5]))
    )

    # 5. Step 20 presentation 語意保留
    p_bad = []
    for sid in sections:
        for ref in output[sid]["insight_refs"]:
            exp = pres_by_scope[ref["scope"]]["presentation_purpose"]["purpose"]
            if ref["presentation_purpose"] != exp:
                p_bad.append(f"{ref['scope']} presentation_purpose 不符 Step 20")
            if exp not in PRESENTATION_PURPOSE_VALUES:
                p_bad.append(f"{ref['scope']} purpose 不在 Step 20 詞彙內")
        if not output[sid]["member_selection_rule"]["all_groups_included"]:
            p_bad.append(f"{sid} 未宣告全部納入")
    # Step 20 的「一律顯示」語意必須被 consumer_contract 承接
    cc = output["metadata"]["consumer_contract"]
    if not cc["safe_to_render_all"] or not cc["must_not_do"]:
        p_bad.append("consumer_contract 未承接 always_displayed 語意")
    always = all(pres_by_scope[s]["display_rule"]["always_displayed"]
                 for s in grp_by_scope)
    if not always:
        p_bad.append("Step 20 的 always_displayed 不是全 True")
    checks.append(
        ("Step 20 presentation 語意保留（purpose 與『一律顯示』）", not p_bad,
         "9 個 scope 的 presentation_purpose 與 Step 20 相同且在詞彙內；"
         "Step 20 的 always_displayed 全 True，由 consumer_contract."
         "safe_to_render_all 與 must_not_do 承接"
         if not p_bad else "；".join(p_bad[:5]))
    )

    # 6. evidence / application data status 分離
    ds = output["data_status"]
    ev = ds["evidence_data_status_by_scope"]
    app = ds["application_data_status_by_scope"]
    sep_bad = []
    for scope in grp_by_scope:
        src = ins_by_scope[scope]["limitations"]["data_availability"]
        if ev[scope] != src["evidence_data_status"]:
            sep_bad.append(f"{scope} evidence status 不符 Step 21")
        if app[scope] != src["application_data_status"]:
            sep_bad.append(f"{scope} application status 不符 Step 21")
        if app[scope] not in DATA_STATUS_VALUES:
            sep_bad.append(f"{scope} application status 不在詞彙內")
    distinct_ev = sorted(set(ev.values()))
    distinct_app = sorted(set(app.values()))
    ok6 = (not sep_bad and len(distinct_ev) == 1 and len(distinct_app) == 4
           and ds["separation"]["fields_are_independent"] is True)
    checks.append(
        ("evidence_data_status 與 application_data_status 保持分離", ok6,
         f"evidence 只有 1 種值 {distinct_ev}，application 有 "
         f"{len(distinct_app)} 種值 {distinct_app}；"
         f"cross_tabulation={ds['separation']['cross_tabulation']}"
         "——單一欄位或 boolean 無法表達這個組合"
         if ok6 else "；".join(sep_bad[:5]))
    )

    # 7. 缺失資料明確呈現（null + 原因，永不靜默省略）
    m_bad = []
    for entry in ds["missing_information_registry"]:
        if entry["status"] not in DATA_STATUS_VALUES:
            m_bad.append(f"{entry['item']} status 不在詞彙內")
        if not entry["factual_basis"] or not entry["availability_source_step"]:
            m_bad.append(f"{entry['item']} 缺來源")
        if entry["status"] != "not_investigated" and not entry["evidence_steps"]:
            m_bad.append(f"{entry['item']} 缺 evidence_steps")
        if not entry["affected_scopes"]:
            m_bad.append(f"{entry['item']} 沒有受影響 scope")
    for g in ds["metric_level_gaps"]:
        if g["value"] is not None or not g["null_reason"]:
            m_bad.append(f"{g['scope']}/{g['metric']} null 表示不完整")
        if g["interpretation_status"] != "blocked_by_missing_data":
            m_bad.append(f"{g['scope']}/{g['metric']} 狀態不符")
    # next_game 的每個 null 都要有原因
    ng = output["next_game"]
    null_reason_pairs = [
        (ng["result_not_available"]["home_score"],
         ng["result_not_available"]["null_reason"]),
        (ng["result_not_available"]["visiting_score"],
         ng["result_not_available"]["null_reason"]),
        (ng["opponent_starting_pitcher"]["pitcher_name"],
         ng["opponent_starting_pitcher"]["pitcher_name_null_reason"]),
        (ng["opponent_starting_pitcher_hand"]["hand"],
         ng["opponent_starting_pitcher_hand"]["null_reason"]),
    ]
    for value, reason in null_reason_pairs:
        if value is None and not reason:
            m_bad.append("next_game 有 null 但沒有原因")
    # metric 缺口數必須等於 Step 21 的 null slot 數
    exp_gaps = sum(1 for i in insights for s in i["phenomenon"]["statements"]
                   if s["statement_kind"] == "explicit_null")
    if ds["metric_level_gap_count"] != exp_gaps:
        m_bad.append("metric 缺口數不符 Step 21")
    checks.append(
        ("所有缺失資料都以 null + 明確原因呈現，沒有靜默省略", not m_bad,
         f"應用層 {len(ds['missing_information_registry'])} 筆 required 項目"
         f"（其中 {ds['missing_information_gap_count']} 筆為缺口）全部帶 status / "
         f"source_step / factual_basis / affected_scopes；"
         f"metric 層 {ds['metric_level_gap_count']} 筆缺口；"
         f"next_game 的 {len(null_reason_pairs)} 個 null 全部附原因"
         if not m_bad else "；".join(m_bad[:5]))
    )

    # 8. 沒有 score / weight / threshold / ranking / priority
    blob = json.dumps(output, ensure_ascii=False)
    decl: list[str] = []
    collect_declarative_text(output, decl)
    decl.append(json.dumps(output["metadata"]["contains_no"], ensure_ascii=False))
    decl_blob = "\n".join(decl)
    neutral, neutral_decl = blob, decl_blob
    for tok in DATA_SOURCE_TOKENS:
        neutral = neutral.replace(tok, "cpbl_official_endpoint")
        neutral_decl = neutral_decl.replace(tok, "cpbl_official_endpoint")
    # CPBL 官方比分欄位也含 score，中性化後再掃描
    for tok in ("home_score", "visiting_score", "source_score_values",
                "score_is_null_reason"):
        neutral = neutral.replace(tok, "cpbl_official_game_result_field")
        neutral_decl = neutral_decl.replace(tok, "cpbl_official_game_result_field")

    bad_keys = scan_keys(output)
    words = []
    for w in ("threshold", "門檻", "cutoff", "top_n", "Top-N", "score",
              "weight", "加權", "分數", "評分"):
        cnt = neutral.count(w) - neutral_decl.count(w)
        if cnt > 0:
            words.append(f"{w}×{cnt}")
    checks.append(
        ("沒有引入 score / weight / threshold / ranking / priority / importance / "
         "confidence / Top-N", not bad_keys and not words,
         "遞迴掃描所有巢狀欄位名：0 命中"
         "（percentile_rank / rank_desc 為 Step 6 描述子；"
         "home_score / visiting_score 為 CPBL 官方比分欄位，值為 null + 原因）；"
         "10 個字眼掃描扣除宣告性欄位與官方欄位名後為 0"
         if not bad_keys and not words
         else f"欄位={sorted(set(bad_keys))[:6]}　字眼={words}")
    )

    # 9. 沒有 prediction / recommendation / 自然語言結論
    forbidden = ("建議", "應該", "推薦", "預測", "策略", "最佳", "最好", "最差",
                 "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
                 "值得注意", "recommend", "predict", "strategy", "should",
                 "best", "advantage")
    hits = []
    for w in forbidden:
        cnt = neutral.count(w) - neutral_decl.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    # phenomenon 文字另做嚴格掃描（不扣除任何宣告性欄位）
    from insight_assembly import JUDGEMENT_WORDS, all_statement_texts
    texts = all_statement_texts(list(fi.values()))
    strict = [f"{w}" for t in texts for w in JUDGEMENT_WORDS
              if w in t or w in t.lower()]
    checks.append(
        ("沒有引入 prediction / recommendation / 自然語言結論",
         not hits and not strict,
         f"全文 {len(forbidden)} 個字眼掃描（扣除宣告性欄位）0 命中；"
         f"另對 {len(texts)} 段 Step 21 phenomenon 文字做嚴格掃描"
         f"（不扣除宣告性欄位，{len(JUDGEMENT_WORDS)} 個字眼）0 命中"
         if not hits and not strict
         else f"全文={hits}　嚴格={sorted(set(strict))[:5]}")
    )

    # 10. raw / processed data 未被修改
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data 未被修改", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    # 10b. 沒有在 data/ 下新增或刪除任何檔案（與執行前的清單比對）
    after = list_data_files()
    added = sorted(set(after) - set(data_files_before))
    removed = sorted(set(data_files_before) - set(after))
    checks.append(
        ("沒有在 data/ 下新增或刪除任何檔案（產品輸出只存在記憶體）",
         not added and not removed,
         f"執行前後比對 data/ 檔案清單（{len(data_files_before)} 個檔案）完全相同"
         if not added and not removed
         else f"新增={added}　刪除={removed}")
    )

    # 11. 沒有 HTTP request / 沒有 LLM / 沒有 UI 框架
    imported = collect_imported_modules(Path(__file__))
    loaded = {m.split(".")[0].lower() for m in sys.modules}
    llm_hits = sorted((imported | loaded) & LLM_PACKAGE_NAMES)
    ui_hits = sorted(imported & UI_PACKAGE_NAMES)
    checks.append(
        ("不需要任何 HTTP request，也沒有 LLM / UI / HTTP 客戶端套件",
         network_guard_active() and not llm_hits and not ui_hits,
         f"socket.connect / connect_ex / create_connection 已被封鎖；"
         f"AST 解析本檔案 import 的頂層模組 {len(imported)} 個；"
         f"沒有 LLM 套件（{len(LLM_PACKAGE_NAMES)} 個比對）"
         f"也沒有 UI / HTTP 客戶端（{len(UI_PACKAGE_NAMES)} 個比對）"
         if network_guard_active() and not llm_hits and not ui_hits
         else f"guard={network_guard_active()}　LLM={llm_hits}　UI={ui_hits}")
    )

    # 12. deterministic（重跑 + 輸入順序）
    det = full_signature(output) == full_signature(rerun)
    order_ok = not [d for d in mutation["changes"] if "order" in d]
    checks.append(
        ("deterministic：重跑一致，且不依輸入順序", det and order_ok,
         "整條流程重跑一次序列化完全相同；"
         "另把逐場資料、官方分項列、賽程列的順序打亂／反轉共 3 次重跑，"
         "完整輸出逐位元相同"
         if det and order_ok else f"重跑一致={det}　順序不變={order_ok}")
    )

    # 13. 所有受控詞彙值都在宣告範圍內
    vocab = output["metadata"]["controlled_vocabularies"]
    v_bad = []
    for i in fi.values():
        st = i["interpretation_status"]["status"]
        if st is not None and st not in vocab["interpretation_status"]["values"]:
            v_bad.append("interpretation_status")
        for s in i["phenomenon"]["statements"]:
            if s["statement_kind"] not in vocab["statement_kind"]["values"]:
                v_bad.append("statement_kind")
            if s["direction"] is not None and \
                    s["direction"] not in vocab["direction"]["values"]:
                v_bad.append("direction")
        for e in i["supporting_evidence"]["primary_metrics"]:
            for k in e["evidence_kinds"]:
                if k not in vocab["evidence_kind"]["values"]:
                    v_bad.append(f"evidence_kind {k}")
        c = i["context"]
        if c["temporal_relevance"] not in vocab["temporal_relevance"]["values"]:
            v_bad.append("temporal_relevance")
        if c["contextual_relevance"] not in \
                vocab["contextual_relevance"]["values"]:
            v_bad.append("contextual_relevance")
        if c["possible_action_link"] not in vocab["possible_action_link"]["values"]:
            v_bad.append("possible_action_link")
        if c["possible_decision_area"] not in \
                vocab["possible_decision_area"]["values"]:
            v_bad.append("possible_decision_area")
        ad = c["application_dependency"]["additional_data"]
        if ad is not None and ad not in vocab["action_link_requires"]["values"]:
            v_bad.append(f"action_link_requires {ad}")
    for d in output["metadata"]["display_contract"]:
        if d["slot"] not in vocab["display_slot"]["values"]:
            v_bad.append(f"display_slot {d['slot']}")
        if d["availability"] not in ("available", "partial", "unavailable"):
            v_bad.append(f"availability {d['availability']}")
    for k, v in ds["next_game_field_status"].items():
        if v not in DATA_STATUS_VALUES:
            v_bad.append(f"next_game_field_status {k}")
    checks.append(
        ("所有受控詞彙值都在宣告範圍內", not v_bad,
         f"metadata 登錄 {len([k for k, x in vocab.items() if isinstance(x, dict)])}"
         " 組詞彙；逐一回查 9 個 insight、25 個 metric 列、"
         f"{len(output['metadata']['display_contract'])} 個 display slot、"
         "4 個 next_game 欄位狀態，全部在範圍內；"
         "本階段唯一新增詞彙為 display_slot"
         if not v_bad else "；".join(sorted(set(v_bad))[:5]))
    )

    # 14. traceability 完整（逐 pointer 解析）
    t_bad = []
    resolved = 0
    for entry in output["traceability"]["metric_index"]:
        if not entry["traceable"]:
            if not entry["not_traceable_reason"]:
                t_bad.append(f"{entry['scope']}/{entry['metric']} 缺不可追溯原因")
            continue
        target = resolve_pointer(output, entry["pointer"])
        if target is None:
            t_bad.append(f"{entry['pointer']} 無法解析")
            continue
        resolved += 1
        for key in ("source_step", "source_file", "source_field", "derivation"):
            if not target.get(key):
                t_bad.append(f"{entry['pointer']} 缺 {key}")
        if not (ROOT / target["source_file"]).exists():
            t_bad.append(f"{entry['pointer']} source_file 不存在")
        if target["game_snos"] is None and not target["game_snos_missing_reason"]:
            t_bad.append(f"{entry['pointer']} game_snos null 無原因")
    for f in output["traceability"]["source_files"]:
        if not f["exists"] or not f["sha256"]:
            t_bad.append(f"{f['path']} 缺 sha256 或不存在")
    checks.append(
        ("traceability 完整：每個事實值都能解析到 step / file / field / formula",
         not t_bad,
         f"{len(output['traceability']['metric_index'])} 筆 metric 索引，"
         f"其中 {resolved} 筆 pointer 成功解析並帶齊 4 個必填欄位；"
         f"{output['traceability']['metric_index_count'] - resolved} 筆不可追溯者附原因；"
         f"3 個來源檔全部帶 sha256 與 byte 數"
         if not t_bad else "；".join(t_bad[:5]))
    )

    # 15. PATTERN 去重沒有遺失資訊
    pat_bad = []
    pat_cmp = 0
    pat_n = 0
    cand_by_id = {c["candidate_id"]: c for c in candidates}
    for i in fi.values():
        cm = i["phenomenon"]["cross_metric_statement"]
        pattern_ids = [cid for cid in i["identity"]["candidate_ids"]
                       if cid.startswith("PATTERN-")]
        if not pattern_ids:
            if cm is not None:
                pat_bad.append(f"{i['identity']['scope']} 無 PATTERN 卻有摘要")
            continue
        pat_n += 1
        if cm is None:
            pat_bad.append(f"{i['identity']['scope']} 有 PATTERN 卻無摘要")
            continue
        p = cand_by_id[pattern_ids[0]]
        ev = {e["metric"]: e["difference"]
              for e in i["supporting_evidence"]["primary_metrics"]}
        for metric, mv in p["metric_values"].items():
            pat_cmp += 1
            if metric not in ev or ev[metric] != mv["difference"]:
                pat_bad.append(f"{p['candidate_id']} {metric} difference 遺失")
        if cm["direction_per_metric"] != p["direction_per_metric"] or \
                cm["consistency_count"] != p["consistency_count"]:
            pat_bad.append(f"{p['candidate_id']} direction 摘要不符")
        # 產品輸出中不得為 PATTERN 另建 metric 列
        if i["supporting_evidence"]["primary_metric_count"] != 3:
            pat_bad.append(f"{i['identity']['scope']} metric 列數異常")
    checks.append(
        ("PATTERN 去重沒有遺失資訊，也沒有重複的 metric 列", not pat_bad,
         f"{pat_n} 個 PATTERN；{pat_cmp} 次 difference 比對全部等於同 insight 的 "
         "CONTEXT metric 列；跨指標方向另以 cross_metric_statement 單獨呈現；"
         "沒有任何 insight 因 PATTERN 多出 metric 列"
         if not pat_bad else "；".join(pat_bad[:5]))
    )

    # 16. season_baseline 與每個 insight 的 baseline 相同
    b_bad = []
    b_cmp = 0
    sb = output["season_baseline"]["metrics"]
    for i in fi.values():
        for e in i["supporting_evidence"]["primary_metrics"]:
            b_cmp += 1
            if e["baseline_value"] != sb[e["metric"]]["value"]:
                b_bad.append(f"{i['identity']['scope']}/{e['metric']} baseline 不符")
    checks.append(
        ("頂層 season_baseline 與每個 insight 的 baseline_value 完全相同", not b_bad,
         f"{b_cmp} 次比對相符；三個 metric 的 baseline 分別為 "
         f"AVG={fmt(sb['batting_average']['value'])}、"
         f"OBP={fmt(sb['on_base_percentage']['value'])}、"
         f"SLG={fmt(sb['slugging_percentage']['value'])}"
         if not b_bad else "；".join(b_bad[:5]))
    )

    # 17. section 不複製數值（單一數值來源）
    dup_bad = []
    for sid in sections:
        sec_blob = json.dumps(output[sid], ensure_ascii=False)
        for i in fi.values():
            for e in i["supporting_evidence"]["primary_metrics"]:
                if fmt(e["current_value"]) in sec_blob:
                    dup_bad.append(f"{sid} 複製了 {e['metric']} 數值")
    checks.append(
        ("section 只放參照，數值只存在 factual_insights 一處", not dup_bad,
         "掃描兩個 section 的完整序列化內容，25 個 metric 的 current_value "
         "字串都沒有出現；section 只含 insight_id / group_id / scope / "
         "candidate_ids / pointer 與狀態欄位"
         if not dup_bad else "；".join(dup_bad[:5]))
    )

    # 18. next_game 狀態對照只依 Step 14 node
    ng_bad = []
    for key, node_pair in (
        ("game", ("usable", "verified_against_processed_schedule")),
        ("opponent_starting_pitcher",
         ("usable", "unconfirmed_upcoming_starter_identity")),
        ("opponent_starting_pitcher_hand",
         ("unusable_blocked", "missing_required_data")),
    ):
        exp = NEXT_GAME_STATUS_FROM_NODE[node_pair]
        got = (ng[key]["data_status"] if key != "game"
               else ng["game"]["data_status"])
        if got != exp:
            ng_bad.append(f"{key} 狀態不符對照表")
    if ng["selection_rule"]["clock_independent"] is not True:
        ng_bad.append("next_game 選擇規則不是 clock independent")
    if ng["game"]["game_status"] is None:
        ng_bad.append("next_game 缺 game_status")
    checks.append(
        ("next_game 的資料狀態完全由 Step 14 node 對照而來，且不讀系統時鐘",
         not ng_bad,
         f"3 個欄位的狀態與 NEXT_GAME_STATUS_FROM_NODE 對照相符："
         f"game={ng['game']['data_status']}、"
         f"pitcher={ng['opponent_starting_pitcher']['data_status']}、"
         f"hand={ng['opponent_starting_pitcher_hand']['data_status']}；"
         f"reference_date={ng['selection_rule']['reference_date']}"
         "（由已完成比賽推導）"
         if not ng_bad else "；".join(ng_bad[:5]))
    )

    # 19. mutation test
    checks.append(
        ("mutation test：資料值與輸入順序變異後，產品結構與規則不變",
         mutation["structure_independent_of_values"],
         f"變異 {mutation['mutants']}，共 {mutation['cases_tested']} 次完整重建；"
         f"簽章改變 {len(mutation['changes'])} 次、"
         f"禁用欄位洩漏 {len(mutation['forbidden_key_leaks'])} 次。"
         "數值類變異只比對不含數值的結構簽章；順序類變異比對完整輸出"
         if mutation["structure_independent_of_values"]
         else "；".join(mutation["changes"] + mutation["forbidden_key_leaks"]))
    )

    # 20. 8 個頂層區塊齊全，且 display_contract 覆蓋所有槽位
    top = ("player", "next_game", "season_baseline", "current_form",
           "contextual_evidence", "factual_insights", "data_status",
           "traceability", "metadata")
    t2_bad = [k for k in top if k not in output or not output[k]]
    slots = [d["slot"] for d in output["metadata"]["display_contract"]]
    if sorted(slots) != sorted(DISPLAY_SLOT_VALUES):
        t2_bad.append("display_contract 未覆蓋所有 slot")
    for d in output["metadata"]["display_contract"]:
        paths = [d["source_path"]] + d.get("additional_source_paths", [])
        for p in paths:
            root = p.split("[")[0].split(".<")[0]
            if resolve_pointer(output, root) is None:
                t2_bad.append(f"{d['slot']} source_path 無法解析：{p}")
    checks.append(
        ("9 個頂層區塊齊全，display_contract 覆蓋 11 個槽位且路徑可解析",
         not t2_bad,
         f"頂層鍵：{list(top)}；display_contract "
         f"{len(slots)} 個槽位與 DISPLAY_SLOT_VALUES 完全相同，"
         "每個 source_path 的根路徑都能在輸出中解析到"
         if not t2_bad else "；".join(t2_bad[:5]))
    )

    return checks


# ------------------------------------------------------------------ 輸出

def print_structure(output: dict) -> None:
    print("\n" + "=" * 110)
    print("Product Output 結構（頂層 9 個區塊）")
    print("=" * 110)
    md = output["metadata"]
    print(f"  product_output_version : {md['product_output_version']}")
    print(f"  counts                 : {md['counts']}")
    print()
    print("  A. player              : 球員身分 + 季出賽計數")
    print("  B. next_game           : 下一場賽程事實 + 3 個資料狀態欄位")
    print("  -- season_baseline     : 季累計基準（AVG / OBP / SLG）")
    print("  C. current_form        : Perspective A section（2 groups，只放參照）")
    print("  D. contextual_evidence : Perspective B + C section（7 groups，只放參照）")
    print("  E. factual_insights    : Step 21 的 9 個 insight（唯一數值來源）")
    print("  F. data_status         : evidence / application 兩個狀態 + 缺口登錄簿")
    print("  G. traceability        : 來源檔 sha256 + step registry + metric 索引")
    print("  H. metadata            : 詞彙登錄 + display contract + consumer contract")


def print_next_game(output: dict) -> None:
    ng = output["next_game"]
    print("\n" + "=" * 110)
    print("B. next_game")
    print("=" * 110)
    g = ng["game"]
    print(f"  game_sno={g['game_sno']}  game_date={g['game_date']}"
          f"  time={g['scheduled_time']}")
    print(f"  opponent={g['opponent']}  home_away={g['home_away']}"
          f"  venue={g['venue']}  status={g['game_status']}")
    print(f"  data_status={g['data_status']}")
    r = ng["result_not_available"]
    print(f"  比分：home={r['home_score']}  visiting={r['visiting_score']}"
          f"  data_status={r['data_status']}")
    print(f"        原因：{r['null_reason'][:60]}...")
    p = ng["opponent_starting_pitcher"]
    print(f"  對手先發：acnt={p['pitcher_acnt']}  name={p['pitcher_name']}"
          f"  data_status={p['data_status']}")
    print(f"        verification_status={p['verification_status']}")
    h = ng["opponent_starting_pitcher_hand"]
    print(f"  先發手別：hand={h['hand']}  data_status={h['data_status']}")
    print(f"        required_to_resolve={h['required_to_resolve']}")
    s = ng["selection_rule"]
    print(f"  選擇規則：reference_date={s['reference_date']}"
          f"  clock_independent={s['clock_independent']}")


def print_sections(output: dict) -> None:
    print("\n" + "=" * 110)
    print("C / D. section（只放參照，不複製數值）")
    print("=" * 110)
    for sid in ("current_form", "contextual_evidence"):
        s = output[sid]
        print(f"\n  [{s['section_id']}] perspectives={s['perspectives']}")
        print(f"    groups={s['group_count']}  candidates={s['candidate_count']}")
        print(f"    subgroups_by_perspective={s['subgroups_by_perspective']}")
        print(f"    temporal_relevance={s['temporal_relevance']}")
        print(f"    subgroups={s['subgroups_by_contextual_relevance']}")
        print(f"    evidence_data_status={s['evidence_data_status_values']}")
        print(f"    application_data_status={s['application_data_status_values']}")
        print(f"    display_slots={s['display_slots']}")
        for ref in s["insight_refs"]:
            print(f"      {ref['scope']:<14} {ref['insight_id']}")
            print(f"        candidates={len(ref['candidate_ids'])}"
                  f"  official={ref['official_item_name']}")
            print(f"        purpose={ref['presentation_purpose']}")


def print_data_status(output: dict) -> None:
    ds = output["data_status"]
    print("\n" + "=" * 110)
    print("F. data_status（兩個狀態刻意分開）")
    print("=" * 110)
    print(f"  {'scope':<14} {'evidence':<12} {'application':<22} required item")
    app = ds["application_data_status_by_scope"]
    req = {}
    for e in ds["missing_information_registry"]:
        for s in e["affected_scopes"]:
            req[s] = e["item"]
    for scope in sorted(app):
        print(f"  {scope:<14} "
              f"{ds['evidence_data_status_by_scope'][scope]:<12} "
              f"{app[scope]:<22} {req.get(scope, '-')}")
    print(f"\n  cross_tabulation：{ds['separation']['cross_tabulation']}")
    print(f"  evidence 值域={ds['separation']['distinct_evidence_values']}"
          f"　application 值域={ds['separation']['distinct_application_values']}")

    print(f"\n  缺口登錄簿（{len(ds['missing_information_registry'])} 筆，"
          f"其中 {ds['missing_information_gap_count']} 筆為缺口）：")
    for e in ds["missing_information_registry"]:
        print(f"    {e['item']}")
        print(f"      status={e['status']}  is_gap={e['is_gap']}"
              f"  scopes={e['affected_scopes']}")
        print(f"      依據 Step {e['evidence_steps'] or '（未調查）'}")

    print(f"\n  metric 層缺口（{ds['metric_level_gap_count']} 筆）：")
    for g in ds["metric_level_gaps"]:
        print(f"    {g['scope']}/{g['metric']} = {g['value']}"
              f"　status={g['interpretation_status']}")

    print(f"\n  next_game 欄位狀態：{ds['next_game_field_status']}")
    print(f"  null 表示政策：{ds['null_representation_policy']['rule']}")


def print_display_contract(output: dict) -> None:
    print("\n" + "=" * 110)
    print("H. display contract（網站要顯示什麼，各槽位對應到哪個路徑）")
    print("=" * 110)
    for d in output["metadata"]["display_contract"]:
        print(f"  {d['slot']:<32} {d['availability']:<12} {d['source_step']}")
        print(f"      path : {d['source_path']}")
        print(f"      note : {d['availability_note']}")


def print_answers(output: dict) -> None:
    print("\n" + "=" * 110)
    print("回答")
    print("=" * 110)
    md = output["metadata"]
    ds = output["data_status"]

    print("\n  (1) 網站對一個球員需要收到什麼：頂層 9 個區塊，一次請求可全部取得。")
    print(f"      {md['counts']}")

    print("\n  (4) Step 18 的 9 個 group 如何對應產品版面：")
    for sid in ("current_form", "contextual_evidence"):
        s = output[sid]
        print(f"      {sid:<20} perspectives={s['perspectives']} "
              f"groups={s['group_count']}  candidates={s['candidate_count']}")
        print(f"          scopes={s['scopes']}")
        print(f"          by_perspective={s['subgroups_by_perspective']}")
        print(f"          by_contextual_relevance="
              f"{s['subgroups_by_contextual_relevance']}")

    print("\n  (5) Step 19 decision relevance 的呈現位置：")
    print("      factual_insights.<id>.context（原樣引用 8 個欄位）")
    print("      + section 的 subgroups_by_contextual_relevance")
    print("      + data_status.missing_information_registry（action_link_requires）")

    print("\n  (6) Step 21 factual insight 的對應：")
    print("      factual_insights 是唯一數值來源，物件與 Step 21 深度相同。")
    print("      section 只放 insight_id 與 pointer。")

    print("\n  (7) 如何保持 deterministic 與 machine-readable：")
    print(f"      {md['determinism']}")

    print("\n  (3) 缺失資訊的表示法：")
    for k, v in ds["null_representation_policy"].items():
        print(f"      {k} = {v}")


# ------------------------------------------------------------------ main

def main() -> None:
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
        SCHEDULE_PATH: sha256_of(SCHEDULE_PATH),
    }
    data_files_before = list_data_files()
    logs, apart_rows = load_inputs()
    schedule = load_schedule()

    output = build_product_output(logs, apart_rows, schedule)
    rerun = build_product_output(logs, apart_rows, schedule)
    mutation = mutation_test(logs, apart_rows, schedule, output)

    # validation 需要的 Step 18~21 原始輸出
    candidates, groups, group_rel, samples, presentation, insights = build_step21(
        logs, apart_rows
    )

    print("=" * 110)
    print("MVP Product Output Model（Step 22）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print("這不是 UI、不是 API、不是 backend。只定義未來消費端應該收到的穩定結構。")
    print("輸出只存在記憶體，不寫入 data/。")
    print("=" * 110)

    print_structure(output)
    print_next_game(output)
    print_sections(output)
    print_data_status(output)
    print_display_contract(output)
    print_answers(output)

    print("\n" + "=" * 110)
    print("Mutation test")
    print("=" * 110)
    print(f"  變異             : {mutation['mutants']}")
    print(f"  完整重建次數     : {mutation['cases_tested']}")
    print(f"  簽章改變次數     : {len(mutation['changes'])}")
    print(f"  禁用欄位洩漏次數 : {len(mutation['forbidden_key_leaks'])}")
    print(f"  結構與數值無關   : {mutation['structure_independent_of_values']}")
    for d in mutation["changes"] + mutation["forbidden_key_leaks"]:
        print(f"    - {d}")

    print("\n" + "=" * 110)
    print("Validation")
    print("=" * 110)
    checks = run_validation(
        output, rerun, insights, groups, candidates, group_rel, presentation,
        samples, mutation, fingerprints_before, data_files_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/PRODUCT_OUTPUT_MODEL.md。")

    print("\n" + "=" * 110)
    print("本階段只定義產品輸出結構。沒有 UI、沒有 API、沒有 backend，")
    print("沒有 ranking / priority / Top-N，也沒有 prediction 或 recommendation。")
    print("=" * 110)


if __name__ == "__main__":
    main()

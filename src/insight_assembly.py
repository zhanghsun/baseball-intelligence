"""Insight Assembly Experiment（Step 21）。

它建立什麼：把 Step 20 的 9 個 presentation record 組裝成 **可閱讀但仍完全可追溯**
的 insight object。每個 insight 由 6 個區塊構成：identity、phenomenon、
supporting_evidence、context、limitations、traceability，另加一個受控的
interpretation_status。

它**不**是什麼：
    - 不是 UI、不是產品，沒有 React / Flask / FastAPI / dashboard
    - 沒有 score / weight / threshold / ranking / priority / Top-N
    - 沒有 prediction、沒有 recommendation、沒有 strategy
    - 不使用 LLM、不發 HTTP 請求
    - 不新增 candidate、不新增 group、不新增任何數值
    - 不修改 candidate / grouping / raw / processed data

核心原則：**phenomenon 只能是資料現象。**
    「Recent 10 AVG = 0.40476190，season = 0.31135531，difference = +0.09340660」可以；
    「近期打擊狀況很好」「值得注意」「優勢」「弱點」「下一場應該……」一律不可以。
    驗證裡對 phenomenon 文字做**不扣除任何宣告性欄位**的嚴格字眼掃描。

三個刻意保留的區分（沿用 Step 20 的 A / B / C）：
    A. evidence 本身是否完整          -> supporting_evidence + interpretation_status
    B. evidence 是否可直接用於下一場決策 -> context.application_dependency
    C. 要完成應用還缺什麼資料          -> limitations.missing_data

用法：
    python src/insight_assembly.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# import candidate_insights 會安裝 socket guard，封鎖所有對外連線
from candidate_insights import (  # noqa: E402
    APART_CACHE_PATH,
    PLAYER_LOG_PATH,
    ROOT,
    SUBJECT,
    SUBJECT_SLUG,
    load_inputs,
    network_guard_active,
    sha256_of,
)
from decision_relevance import build_relevance_record  # noqa: E402
from group_decision_relevance import build_group_relevance  # noqa: E402
from insight_grouping import build_groups  # noqa: E402
from insight_presentation_model import (  # noqa: E402
    build_all as build_presentation_all,
    build_presentation_model,
)
from noteworthy_insights import build_all as build_classification  # noqa: E402

ALL_METRICS = ("batting_average", "on_base_percentage", "slugging_percentage")

METRIC_LABEL = {
    "batting_average": "AVG",
    "on_base_percentage": "OBP",
    "slugging_percentage": "SLG",
}

# ------------------------------------------------------------------ 受控詞彙

# interpretation_status：本階段新增的最小詞彙（Step 9~20 都沒有同義欄位，
# 已在 docs/INSIGHT_ASSEMBLY_EXPERIMENT.md 第 6 節說明為何必須新增）。
INTERPRETATION_STATUS_VALUES = (
    "factual_only",
    "factual_with_context",
    "blocked_by_missing_data",
)

INTERPRETATION_STATUS_MEANING = {
    "factual_only": (
        "只能陳述數值本身與季累計 baseline 的 difference。"
        "沒有分布位置，也無法追溯到個別比賽。"
    ),
    "factual_with_context": (
        "可以陳述數值與 baseline 的 difference，並附上同尺寸滾動窗口的分布位置"
        "與可追溯的 game_sno 清單。"
    ),
    "blocked_by_missing_data": (
        "來源資料不足以產生這個數值，因此沒有可陳述的現象。值保持 null。"
    ),
}

INTERPRETATION_STATUS_ORIGIN = (
    "new_in_step_21。Step 9~20 的欄位都沒有表達「這個數字可以被陳述到什麼程度」："
    "Step 11 的 sample_context 描述樣本規模、Step 19 的 data_availability 描述"
    "應用所需外部資料、Step 20 的 evidence_data_status 描述 evidence 數值是否存在。"
    "三者都不回答「陳述邊界」。因此建立這個最小詞彙，只有 3 個值，"
    "判定規則純結構性（是否有分布位置 / 是否有場次追溯 / 數值是否存在），"
    "不含 magnitude、sample size 或 classification。"
)

EVIDENCE_KIND_VALUES = (
    "metric_vs_season_baseline",
    "sample_size_counts",
    "single_event_sensitivity",
    "rolling_distribution_position",
    "game_level_traceability",
    "official_split_definition",
    "cross_metric_direction",
)

ASSEMBLY_NOT_INPUTS = [
    "magnitude", "sample_size_at_bats", "plate_appearances",
    "percentile_rank", "consistency_count", "classification",
    "noteworthy_classification",
]

# phenomenon 嚴格禁用字眼。掃描時**不扣除**任何宣告性欄位。
JUDGEMENT_WORDS = (
    "好", "壞", "強", "弱", "優", "劣", "佳", "差", "提升", "下降", "進步",
    "退步", "值得", "應該", "建議", "預測", "推薦", "策略", "最", "擅長",
    "熱", "冷", "改善", "惡化", "厲害", "危險", "問題",
    "good", "bad", "strong", "weak", "better", "worse", "best", "worst",
    "should", "advantage", "disadvantage", "improve", "decline", "hot",
    "cold", "recommend", "predict", "strategy", "notable", "noteworthy",
    "significant", "trend up", "trend down",
)

# ------------------------------------------------------------------ 欄位追溯表

# TREND：來源是 processed 逐場資料。欄位名取自 src/build_processed_data.py。
TREND_FIELDS = {
    "batting_average": {
        "processed_fields": ["hits", "at_bats"],
        "raw_api_fields": ["HittingCnt", "HitCnt"],
    },
    "slugging_percentage": {
        "processed_fields": ["total_bases", "at_bats"],
        "raw_api_fields": ["TotalBases", "HitCnt"],
    },
}

# CONTEXT：來源是官方分項成績快取。欄位名取自 src/context_splits.py 的 FIELD_MAP。
CONTEXT_FIELDS = {
    "batting_average": ["HittingCnt", "HitCnt"],
    "on_base_percentage": [
        "HittingCnt", "BasesONBallsCnt", "HitBYPitchCnt",
        "HitCnt", "SacrificeFlyCnt",
    ],
    "slugging_percentage": ["TotalBases", "HitCnt"],
}


# ------------------------------------------------------------------ 工具

def fmt(v, digits: int = 8) -> str:
    if v is None:
        return "null"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def signed(v, digits: int = 8) -> str:
    if v is None:
        return "null"
    return f"{v:+.{digits}f}"


def collect_declarative_text(obj, out: list) -> None:
    """收集宣告性 / 說明性欄位的文字，供字眼掃描扣除。

    自動比對欄位名，避免漏掉某個否定宣告而讓掃描誤判（Step 19 / 20 已記錄
    這個問題：否定宣告本身會命中禁用字眼清單）。
    """
    markers = ("is_not", "not_a", "not_inputs", "contains_no", "limitation",
               "boundary", "exclusion", "guessing", "meaning", "note",
               "justification", "origin", "rationale", "definition", "basis",
               "reason", "rule_text", "vocabulary")
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if any(m in kl for m in markers):
                out.append(json.dumps(v, ensure_ascii=False))
            else:
                collect_declarative_text(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_declarative_text(v, out)


# ------------------------------------------------------------------ Evidence 與 slot

def slot_interpretation_status(row: dict | None) -> str:
    """純結構性判定，不看 magnitude / sample size / classification。"""
    if row is None:
        return "blocked_by_missing_data"
    has_distribution = row["rolling_distribution_position"] is not None
    has_game_level = bool(row["traceability"]["game_snos"])
    if has_distribution and has_game_level:
        return "factual_with_context"
    return "factual_only"


def build_traceability_entry(row: dict, candidate: dict) -> dict:
    """單一 metric 的追溯記錄。每個主要數字都要能回到 step / file / field / formula。"""
    metric = row["metric"]
    calc = candidate["calculation_reference"]
    tr = row["traceability"]

    if candidate["type"] == "TREND":
        fields = TREND_FIELDS[metric]
        entry = {
            "source_step": "Step 9（candidate）/ Step 5（數值）/ Step 6（分布位置）",
            "source_step_ids": ["Step 5", "Step 6", "Step 9", "Step 11"],
            "source_file": "data/processed/zhang_yucheng_game_logs_2026.json",
            "source_files": list(tr["source_files"]),
            "source_field": {
                "processed_fields": list(fields["processed_fields"]),
                "raw_api_fields": list(fields["raw_api_fields"]),
                "field_map_reference": "src/build_processed_data.py",
            },
            "derivation": calc["formula"],
            "derivation_detail": {
                "window": candidate["window"]["definition"],
                "window_size_games": candidate["window"]["size_games"],
                "sorting": calc["sorting"],
                "baseline": candidate["baseline_definition"],
                "difference": "current_value - baseline_value",
            },
            "game_snos": list(tr["game_snos"]),
            "game_snos_count": len(tr["game_snos"]),
            "game_snos_missing_reason": None,
            "date_range": dict(tr["date_range"]),
            "source_candidate_id": candidate["candidate_id"],
            "docs": list(calc["docs"]),
        }
    else:
        entry = {
            "source_step": "Step 9（candidate）/ Step 8（數值）",
            "source_step_ids": ["Step 8", "Step 9", "Step 11"],
            "source_file": "data/raw/apart_score_0000006888_2026_A_01.json",
            "source_files": list(tr["source_files"]),
            "source_field": {
                "official_item_name": candidate["context"]["official_item_name"],
                "official_query": tr["official_item_name"],
                "raw_api_fields": list(CONTEXT_FIELDS[metric]),
                "field_map_reference": "src/context_splits.py FIELD_MAP",
            },
            "derivation": calc["formula"],
            "derivation_detail": {
                "granularity": candidate["context"]["granularity"],
                "definition_source": candidate["context"]["definition_source"],
                "definition_note": candidate["context"]["definition_note"],
                "walks_semantics": calc["walks_semantics"],
                "official_rounding": calc["official_rounding"],
                "baseline": "2026 一軍例行賽季累計（77 場實際出賽）",
                "difference": "value - baseline_value",
            },
            "game_snos": None,
            "game_snos_count": 0,
            "game_snos_missing_reason": tr["game_snos_missing_reason"],
            "date_range": None,
            "source_candidate_id": candidate["candidate_id"],
            "docs": list(calc["docs"]),
        }
    entry["metric"] = metric
    entry["metric_label"] = METRIC_LABEL[metric]
    return entry


def build_evidence_item(row: dict, candidate: dict) -> dict:
    """單一 metric 的 supporting evidence。數值全部原樣引用 Step 20，不重算。"""
    rd = row["rolling_distribution_position"]
    sv = row["single_event_sensitivity"]
    ss = row["sample_size"]

    kinds = ["metric_vs_season_baseline", "sample_size_counts",
             "single_event_sensitivity"]
    if rd is not None:
        kinds.append("rolling_distribution_position")
    if row["traceability"]["game_snos"]:
        kinds.append("game_level_traceability")
    if candidate["type"] == "CONTEXT":
        kinds.append("official_split_definition")

    return {
        "metric": row["metric"],
        "metric_label": row["metric_label"],
        "primary_metric": True,
        "current_value": row["current_value"],
        "baseline_value": row["baseline_value"],
        "baseline_definition": row["baseline_definition"],
        "difference": row["difference"],
        "direction": row["direction"],
        "direction_vocabulary": ["ABOVE", "BELOW", "EQUAL"],
        "sample_size": {
            "at_bats": ss["at_bats"],
            "plate_appearances": ss["plate_appearances"],
            "games": ss["games"],
            "games_missing_reason": ss["games_missing_reason"],
            "source_step": ss["source_step"],
        },
        "sensitivity": {
            "numerator": sv["numerator"],
            "denominator": sv["denominator"],
            "numerator_label": sv["numerator_label"],
            "denominator_label": sv["denominator_label"],
            "one_more_success": sv["one_more_success"],
            "one_fewer_success": sv["one_fewer_success"],
            "delta_if_one_more": sv["delta_if_one_more"],
            "success_unit": sv["success_unit"],
            "source_step": sv["source_step"],
            "is_not": sv["is_not"],
        },
        "rolling_percentile": None if rd is None else {
            "percentile_rank": rd["percentile_rank"],
            "percentile_strict": rd["percentile_strict"],
            "rank_desc": rd["rank_desc"],
            "distribution_n": rd["distribution_n"],
            "definition": rd["definition"],
            "source_step": rd["source_step"],
        },
        "rolling_percentile_missing_reason": row["rolling_distribution_missing_reason"],
        "evidence_kinds": kinds,
        "source_candidate_id": row["traceability"]["source_candidate_id"],
        "value_source_step": row["traceability"]["value_source_step"],
        "interpretation_status": slot_interpretation_status(row),
    }


# ------------------------------------------------------------------ Phenomenon

def phenomenon_statement(scope: str, row: dict, candidate: dict) -> dict:
    """只描述資料現象。不含任何價值判斷字眼。"""
    ss = row["sample_size"]
    metric = row["metric"]
    if candidate["type"] == "TREND":
        size = candidate["window"]["size_games"]
        text = (
            f"{scope}：{metric} = {fmt(row['current_value'])}；"
            f"2026 季累計 baseline = {fmt(row['baseline_value'])}；"
            f"difference = {signed(row['difference'])}；"
            f"direction = {row['direction']}；"
            f"window = {size} 場實際出賽；"
            f"sample = {ss['at_bats']} AB / {ss['plate_appearances']} PA / "
            f"{ss['games']} 場。"
        )
    else:
        item = candidate["context"]["official_item_name"]
        text = (
            f"{scope}（官方分項「{item}」，季累計）：{metric} = "
            f"{fmt(row['current_value'])}；"
            f"2026 季累計 baseline = {fmt(row['baseline_value'])}；"
            f"difference = {signed(row['difference'])}；"
            f"direction = {row['direction']}；"
            f"sample = {ss['at_bats']} AB / {ss['plate_appearances']} PA；"
            f"games = null。"
        )
    return {
        "metric": metric,
        "metric_label": row["metric_label"],
        "statement": text,
        "statement_kind": "numeric_fact",
        "current_value": row["current_value"],
        "baseline_value": row["baseline_value"],
        "difference": row["difference"],
        "direction": row["direction"],
        "source_candidate_id": row["traceability"]["source_candidate_id"],
        "interpretation_status": slot_interpretation_status(row),
    }


def blocked_statement(scope: str, metric: str, reason: str) -> dict:
    return {
        "metric": metric,
        "metric_label": METRIC_LABEL[metric],
        "statement": (
            f"{scope}：{metric} = null（沒有可陳述的數值）。"
            f"原因：{reason}"
        ),
        "statement_kind": "explicit_null",
        "current_value": None,
        "baseline_value": None,
        "difference": None,
        "direction": None,
        "source_candidate_id": None,
        "interpretation_status": "blocked_by_missing_data",
    }


def cross_metric_statement(scope: str, cross: dict) -> dict | None:
    if not cross["available"]:
        return None
    per = cross["direction_per_metric"]
    parts = "、".join(f"{k} = {v}" for k, v in sorted(per.items()))
    return {
        "statement": (
            f"{scope}：三個指標與 2026 季累計比較的 direction 為 {parts}；"
            f"相同 direction 計數 {cross['consistency_count']}/"
            f"{cross['total_metrics']}。"
        ),
        "statement_kind": "direction_summary",
        "direction": cross["direction"],
        "direction_per_metric": dict(per),
        "consistency_count": cross["consistency_count"],
        "total_metrics": cross["total_metrics"],
        "source_candidate_id": cross["source_candidate_id"],
        "adds_no_new_number": True,
        "adds_no_new_number_basis": (
            "PATTERN candidate 的每個 metric difference 與同 group 的 CONTEXT "
            "evidence 完全相同（Step 20 已逐一比對），因此這裡只保留 direction 摘要，"
            "不建立任何新數值。"
        ),
        "known_limitation": cross["known_limitation"],
    }


# ------------------------------------------------------------------ Insight object

def build_insight(record: dict, cand_by_id: dict) -> dict:
    gi = record["group_identity"]
    scope = gi["scope"]
    es = record["evidence_summary"]
    dr = record["decision_relevance"]
    ds = record["data_status"]
    mi = record["missing_information"]

    rows_by_metric = {r["metric"]: r for r in es["metrics"]}

    statements = []
    evidence_items = []
    traceability_entries = []
    slot_status = {}

    for metric in ALL_METRICS:
        row = rows_by_metric.get(metric)
        if row is None:
            statements.append(
                blocked_statement(scope, metric, es["metrics_unavailable_reason"])
            )
            slot_status[metric] = "blocked_by_missing_data"
            continue
        cand = cand_by_id[row["traceability"]["source_candidate_id"]]
        statements.append(phenomenon_statement(scope, row, cand))
        item = build_evidence_item(row, cand)
        evidence_items.append(item)
        traceability_entries.append(build_traceability_entry(row, cand))
        slot_status[metric] = item["interpretation_status"]

    cross = cross_metric_statement(scope, es["cross_metric_direction"])

    # insight 層級的 interpretation_status：present slot 的狀態聚合。
    # 只在所有 present slot 一致時成立；不一致就記錄衝突並設為 null，不強行合併
    # （沿用 Step 19 aggregate_group 的處理方式）。
    present_status = sorted({v for m, v in slot_status.items()
                             if v != "blocked_by_missing_data"})
    if not present_status:
        insight_status = "blocked_by_missing_data"
        status_conflict = None
    elif len(present_status) == 1:
        insight_status = present_status[0]
        status_conflict = None
    else:
        insight_status = None
        status_conflict = {"distinct_values": present_status,
                           "by_metric": dict(slot_status)}

    kinds = sorted({k for it in evidence_items for k in it["evidence_kinds"]})
    if cross:
        kinds = sorted(set(kinds) | {"cross_metric_direction"})

    return {
        # ---- 1. identity ----
        "identity": {
            "insight_id": f"INSIGHT-{SUBJECT_SLUG}-{scope}",
            "group_id": gi["group_id"],
            "perspective": gi["perspective"],
            "perspective_name": gi["perspective_name"],
            "scope": scope,
            "candidate_ids": list(gi["candidate_ids"]),
            "candidate_count": gi["candidate_count"],
            "subject": dict(gi["subject"]),
        },

        # ---- 2. phenomenon（只有資料現象）----
        "phenomenon": {
            "statements": statements,
            "statement_count": len(statements),
            "cross_metric_statement": cross,
            "statement_rule": {
                "rule_id": "A21-P",
                "rule_text": (
                    "每個 statement 只由 metric 名稱、current_value、baseline_value、"
                    "difference、direction、sample 計數與 window / 官方分項名稱組成。"
                    "所有數字原樣引用 Step 20，不重算、不四捨五入成模糊說法。"
                ),
                "template_fields": [
                    "scope", "metric", "current_value", "baseline_value",
                    "difference", "direction", "sample_size", "window_or_split",
                ],
                "contains_no_judgement": [
                    "好", "壞", "強", "弱", "優勢", "劣勢", "值得注意",
                    "應該", "建議", "預測", "策略",
                ],
                "judgement_exclusion_note": (
                    "驗證對 statement 文字做嚴格字眼掃描，不扣除任何宣告性欄位。"
                ),
            },
        },

        # ---- 3. supporting_evidence ----
        "supporting_evidence": {
            "primary_metrics": evidence_items,
            "primary_metric_count": len(evidence_items),
            "metrics_present": list(es["metrics_present"]),
            "metrics_unavailable": list(es["metrics_unavailable"]),
            "metrics_unavailable_reason": es["metrics_unavailable_reason"],
            "evidence_kinds": kinds,
            "evidence_kind_count": len(kinds),
            "assembly_note": (
                "一個 insight 由多個不同性質的 evidence 組成："
                "metric 與季累計的 difference、樣本計數、單一事件敏感度，"
                "以及（若存在）滾動分布位置、場次追溯、官方分項定義、跨指標方向摘要。"
                "每一項都獨立記錄，不合成任何綜合值。"
            ),
        },

        # ---- 4. context（原樣引用 Step 19 / Step 20）----
        "context": {
            "contextual_relevance": dr["contextual_relevance"],
            "context_official_item_name": dr["context_official_item_name"],
            "temporal_relevance": dr["temporal_relevance"],
            "next_game_dependency": {
                "evidence_depends_on_next_game":
                    dr["next_game_dependency"]["evidence_depends_on_next_game"],
                "basis": dr["next_game_dependency"]["basis"],
                "meaning": "描述 evidence 本身是否需要下一場資訊才完整。",
            },
            "application_dependency": {
                "requires_additional_data":
                    dr["application_dependency"]["requires_additional_data"],
                "additional_data": dr["application_dependency"]["additional_data"],
                "meaning": (
                    "描述把 evidence 應用到下一場決策時是否需要額外資料。"
                    "與 next_game_dependency 是兩件不同的事。"
                ),
            },
            "possible_decision_area": dr["action_link"]["possible_decision_area"],
            "possible_action_link": dr["action_link"]["possible_action_link"],
            "source_step": "Step 19（經 Step 20 原樣傳遞）",
            "is_not": (
                "context 只描述這份資料連到哪一類決策，不是決策本身，"
                "也不是對下一場的任何投射。"
            ),
        },

        # ---- 5. limitations ----
        "limitations": {
            "sample_limitation": {
                "at_bats": (evidence_items[0]["sample_size"]["at_bats"]
                            if evidence_items else None),
                "plate_appearances": (
                    evidence_items[0]["sample_size"]["plate_appearances"]
                    if evidence_items else None),
                "games": (evidence_items[0]["sample_size"]["games"]
                          if evidence_items else None),
                "games_missing_reason": (
                    evidence_items[0]["sample_size"]["games_missing_reason"]
                    if evidence_items else None),
                "single_event_delta": {
                    it["metric"]: it["sensitivity"]["delta_if_one_more"]
                    for it in evidence_items
                },
                "source_step": "Step 11",
                "is_not_a_filter": (
                    "sample size 只描述樣本規模。Step 11 與 Step 17-7 已記錄："
                    "本專案不用 sample size 淘汰或隱藏任何 insight。"
                ),
            },
            "missing_data": {
                "required_additional_data": copy.deepcopy(
                    mi["required_additional_data"]),
                "missing_for_application": copy.deepcopy(
                    mi["missing_for_application"]),
                "missing_count": mi["missing_count"],
                "no_guessing_note": mi["no_guessing_note"],
                "source_step": "Step 19（經 Step 20 對應詞彙）",
            },
            "unavailable_metrics": {
                "metrics": list(es["metrics_unavailable"]),
                "count": len(es["metrics_unavailable"]),
                "reason": es["metrics_unavailable_reason"],
                "value_policy": "值保持 null，不以任何方式估算或填補。",
            },
            "data_availability": {
                "evidence_data_status": ds["evidence_data_status"],
                "application_data_status": ds["application_data_status"],
                "step19_value": ds["mapped_from_step19_value"],
                "vocabulary": list(ds["vocabulary"]),
                "mapping_note": ds["mapping_note"],
            },
            "temporal_limitation": (
                None if dr["temporal_relevance"] == "recent_games" else
                "官方分項成績沒有時間維度，也沒有出賽場次欄位（Step 8 已記錄）。"
                "因此這份 evidence 沒有 game-level 明細、沒有日期範圍、"
                "也沒有滾動分布位置，只有季累計。"
            ),
            "not_a_next_game_projection": (
                "本 insight 的所有數值都是已完成比賽的統計。"
                "沒有任何欄位是對下一場的投射或推估。"
            ),
        },

        # ---- 6. traceability ----
        "traceability": {
            "by_metric": {e["metric"]: e for e in traceability_entries},
            "metric_count": len(traceability_entries),
            "cross_metric_source": (
                None if cross is None else cross["source_candidate_id"]),
            "step_chain": [
                "Step 2/3（來源調查）", "Step 4（processed data）",
                "Step 5（季與窗口計數）", "Step 6（滾動分布）",
                "Step 8（官方分項）", "Step 9（candidate）",
                "Step 11（sample context）", "Step 13（decision descriptor）",
                "Step 18（grouping）", "Step 19（group relevance）",
                "Step 20（presentation model）", "Step 21（assembly）",
            ],
            "source_files": list(record["provenance"]["source_files"]),
            "every_number_traceable": True,
            "every_number_traceable_basis": (
                "每個 metric 的追溯記錄都帶 source_step / source_file / "
                "source_field / derivation；TREND 另帶 game_snos 清單，"
                "CONTEXT 的 game_snos 為 null 並附明確原因。"
            ),
        },

        # ---- interpretation_status ----
        "interpretation_status": {
            "status": insight_status,
            "vocabulary": list(INTERPRETATION_STATUS_VALUES),
            "vocabulary_origin": INTERPRETATION_STATUS_ORIGIN,
            "meaning": (None if insight_status is None
                        else INTERPRETATION_STATUS_MEANING[insight_status]),
            "by_metric": dict(slot_status),
            "aggregation_rule": (
                "取所有 present metric slot 的狀態；一致時成立，"
                "不一致則設為 null 並記錄衝突，不強行合併。"
                "blocked slot 不影響 insight 層級狀態，另記於 limitations。"
            ),
            "conflict": status_conflict,
            "rule_inputs": ["has_rolling_distribution", "has_game_level_traceability",
                            "metric_value_exists"],
            "rule_not_inputs": list(ASSEMBLY_NOT_INPUTS),
        },

        # ---- 組裝規則與來源 ----
        "assembly_rule": {
            "rule_id": "A21-1",
            "version": "first_version",
            "rule_text": (
                "每個 Step 20 presentation record 組裝成恰好一個 insight object。"
                "所有數值原樣引用，不重算、不新增、不篩選。"
            ),
            "rule_inputs": ["step20_presentation_record", "step18_group_membership",
                            "step9_candidate_evidence"],
            "rule_not_inputs": list(ASSEMBLY_NOT_INPUTS),
            "one_insight_per_group": True,
        },

        "provenance": {
            "presentation_source_step": "Step 20",
            "presentation_source_module": "src/insight_presentation_model.py",
            "group_source_step": "Step 18",
            "group_source_module": "src/insight_grouping.py",
            "relevance_source_step": "Step 19",
            "relevance_source_module": "src/group_decision_relevance.py",
            "candidate_source_step": "Step 9",
            "candidate_source_module": "src/candidate_insights.py",
            "sample_source_step": "Step 11",
            "sample_source_module": "src/evidence_sample_context.py",
            "source_files": list(record["provenance"]["source_files"]),
            "sidecar_note": (
                "本記錄為 sidecar，用 group_id 關聯，"
                "不寫回 group、candidate 或 presentation record"
            ),
        },

        "contains_no": [
            "score", "weight", "threshold", "ranking", "priority", "importance",
            "confidence_score", "top_n", "prediction", "recommendation",
            "strategy", "natural_language_conclusion", "llm", "ui",
        ],
    }


def build_insights(records: list, candidates: list) -> list:
    cand_by_id = {c["candidate_id"]: c for c in candidates}
    ordered = sorted(records, key=lambda r: r["group_identity"]["scope"])
    return [build_insight(r, cand_by_id) for r in ordered]


ORDERING_NOTE = {
    "basis": "scope 字母順序",
    "is_not": (
        "輸出順序只為了讓結果 deterministic 且可比對。"
        "這不是 ranking、不是 priority，也不是 Top-N。"
    ),
}


# ------------------------------------------------------------------ 反證

def rule_signature(insights: list) -> str:
    """只含結構與受控詞彙，不含任何數值。四種變異都不得改變這個簽章。"""
    def key_paths(obj, prefix=""):
        paths = []
        if isinstance(obj, dict):
            for k in sorted(obj):
                paths.append(f"{prefix}.{k}")
                paths += key_paths(obj[k], f"{prefix}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                paths += key_paths(v, f"{prefix}[]")
        return paths

    return json.dumps(
        [
            {
                "insight_id": i["identity"]["insight_id"],
                "group_id": i["identity"]["group_id"],
                "scope": i["identity"]["scope"],
                "candidate_ids": i["identity"]["candidate_ids"],
                "keys": sorted(set(key_paths(i))),
                "interpretation_status": i["interpretation_status"]["status"],
                "interpretation_by_metric": i["interpretation_status"]["by_metric"],
                "metrics_present": i["supporting_evidence"]["metrics_present"],
                "metrics_unavailable": i["supporting_evidence"]["metrics_unavailable"],
                "evidence_kinds": i["supporting_evidence"]["evidence_kinds"],
                "statement_kinds": [s["statement_kind"]
                                    for s in i["phenomenon"]["statements"]],
                "has_cross_metric": i["phenomenon"]["cross_metric_statement"]
                is not None,
                "context": {
                    "contextual_relevance": i["context"]["contextual_relevance"],
                    "temporal_relevance": i["context"]["temporal_relevance"],
                    "evidence_depends_on_next_game":
                        i["context"]["next_game_dependency"][
                            "evidence_depends_on_next_game"],
                    "requires_additional_data":
                        i["context"]["application_dependency"][
                            "requires_additional_data"],
                    "additional_data":
                        i["context"]["application_dependency"]["additional_data"],
                    "possible_decision_area": i["context"]["possible_decision_area"],
                },
                "missing_items": [
                    (m["item"], m["status"])
                    for m in i["limitations"]["missing_data"]["missing_for_application"]
                ],
                "required_items": [
                    (m["item"], m["status"])
                    for m in i["limitations"]["missing_data"][
                        "required_additional_data"]
                ],
                "application_data_status":
                    i["limitations"]["data_availability"]["application_data_status"],
                "assembly_rule": i["assembly_rule"],
            }
            for i in insights
        ],
        ensure_ascii=False, sort_keys=True,
    )


def full_signature(insights: list) -> str:
    return json.dumps(insights, ensure_ascii=False, sort_keys=True)


def rebuild_from_parts(candidates, views, samples, nw_records):
    step13 = [
        build_relevance_record(c, views[c["candidate_id"]],
                               samples[c["candidate_id"]])
        for c in candidates
    ]
    nw_by_id = {r["candidate_id"]: r for r in nw_records}
    groups = build_groups(candidates, views, samples, nw_by_id)
    group_rel = build_group_relevance(groups, step13)
    records = build_presentation_model(groups, group_rel, candidates, samples)
    return build_insights(records, candidates)


def mutation_test(logs, apart_rows, baseline: list) -> dict:
    """四種變異：magnitude、AB、classification、candidate 順序。

    - magnitude / AB 是資料值：數字會跟著變（本來就該變，那是資料），
      但**結構與規則簽章**不得改變，也不得因此冒出 priority / ranking。
    - classification / 順序不帶任何資料變化：**完整輸出**必須逐位元相同。
    """
    base_rule = rule_signature(baseline)
    base_full = full_signature(baseline)
    diffs = []
    cases = 0
    key_leaks = []
    status_leaks = []

    mutants = [
        ("magnitude", 0.0, "rule"),
        ("magnitude", 999.0, "rule"),
        ("at_bats", 1, "rule"),
        ("at_bats", 9999, "rule"),
        ("classification", "flip", "full"),
        ("candidate_order", "reversed", "full"),
    ]

    for kind, value, strictness in mutants:
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
        elif kind == "at_bats":
            for c in candidates:
                samples[c["candidate_id"]]["sample_context"]["at_bats"] = value
                c["at_bats"] = value
        elif kind == "classification":
            flip = {"observation": "noteworthy", "noteworthy": "observation"}
            for r in nw_records:
                r["classification"] = flip.get(r["classification"],
                                               r["classification"])
        else:  # candidate_order
            candidates = list(reversed(candidates))

        got = rebuild_from_parts(candidates, views, samples, nw_records)
        cases += 1

        if strictness == "rule":
            if rule_signature(got) != base_rule:
                diffs.append(f"{kind}={value} 時規則簽章改變")
        else:
            if full_signature(got) != base_full:
                diffs.append(f"{kind}={value} 時完整輸出改變")

        leaks = scan_keys({"insights": got})
        if leaks:
            key_leaks.append(f"{kind}={value}: {sorted(set(leaks))[:3]}")
        vals = {i["interpretation_status"]["status"] for i in got}
        if not vals <= set(INTERPRETATION_STATUS_VALUES) | {None}:
            status_leaks.append(f"{kind}={value}: {sorted(vals - set(INTERPRETATION_STATUS_VALUES))}")

    return {
        "mutants": [f"{k}={v}（{s}）" for k, v, s in mutants],
        "cases_tested": cases,
        "changes": diffs,
        "forbidden_key_leaks": key_leaks,
        "status_vocabulary_leaks": status_leaks,
        "structure_independent_of_values": (
            not diffs and not key_leaks and not status_leaks
        ),
    }


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "threshold", "rank", "priority",
                  "importance", "confidence", "top_n", "recommend", "predict")
ALLOWED_KEY_EXCEPTIONS = ("percentile_rank", "rank_desc")
DECLARATIVE_KEYS = ("contains_no", "rule_not_inputs", "contains_no_judgement")

# CPBL 官方 endpoint / 快取檔名，本身含「score」子字串，與本專案的 score 無關
DATA_SOURCE_TOKENS = ("apart_score", "follow_score")

LLM_PACKAGE_NAMES = frozenset({
    "openai", "anthropic", "cohere", "vertexai", "transformers", "langchain",
    "llama_index", "ollama", "litellm", "mistralai", "torch", "tensorflow",
    "huggingface_hub",
})

UI_PACKAGE_NAMES = frozenset({
    "flask", "fastapi", "django", "streamlit", "dash", "jinja2", "starlette",
    "uvicorn", "tkinter", "react",
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


def all_statement_texts(insights: list) -> list[str]:
    texts = []
    for i in insights:
        for s in i["phenomenon"]["statements"]:
            texts.append(s["statement"])
        cm = i["phenomenon"]["cross_metric_statement"]
        if cm:
            texts.append(cm["statement"])
    return texts


def run_validation(
    insights: list, rerun: list, records: list, groups_before: list,
    groups_after: list, candidates_before: list, candidates_after: list,
    candidates: list, group_rel: list, samples: dict, mutation: dict,
    fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    cand_by_id = {c["candidate_id"]: c for c in candidates}
    rec_by_scope = {r["group_identity"]["scope"]: r for r in records}
    rel_by_scope = {r["scope"]: r for r in group_rel}
    grp_by_scope = {g["scope"]: g for g in groups_after}
    scopes = [i["identity"]["scope"] for i in insights]

    # 1. 9 個 group 全部產生 insight
    ok1 = (len(insights) == 9 == len(groups_after)
           and sorted(scopes) == sorted(grp_by_scope)
           and len(set(scopes)) == 9)
    checks.append(
        ("9 個 group 全部產生 insight", ok1,
         f"insight={len(insights)}　group={len(groups_after)}"
         f"　scope 集合相同={sorted(scopes) == sorted(grp_by_scope)}"
         f"　順序依 scope 字母（不是 ranking）")
    )

    # 2. 一個 group 只有一個 assembled insight
    ids = [i["identity"]["insight_id"] for i in insights]
    gids = [i["identity"]["group_id"] for i in insights]
    ok2 = (len(set(ids)) == len(ids) == 9 and len(set(gids)) == 9
           and all(i["assembly_rule"]["one_insight_per_group"] for i in insights))
    checks.append(
        ("一個 group 只有一個 assembled insight", ok2,
         f"insight_id 唯一 {len(set(ids))} 個、group_id 唯一 {len(set(gids))} 個"
         f"，一對一")
    )

    # 3. 每個 metric 都能追溯
    tr_bad = []
    tr_rows = 0
    for i in insights:
        present = i["supporting_evidence"]["metrics_present"]
        by_metric = i["traceability"]["by_metric"]
        if sorted(by_metric) != sorted(present):
            tr_bad.append(f"{i['identity']['scope']} 追溯 metric 集合不符")
        for metric, e in by_metric.items():
            tr_rows += 1
            for key in ("source_step", "source_file", "source_field",
                        "derivation", "source_candidate_id"):
                if not e.get(key):
                    tr_bad.append(f"{i['identity']['scope']}/{metric} 缺 {key}")
            if not (ROOT / e["source_file"]).exists():
                tr_bad.append(f"{metric} source_file 不存在")
            for f in e["source_files"]:
                if not (ROOT / f).exists():
                    tr_bad.append(f"{metric} source_files {f} 不存在")
            if e["game_snos"] is None and not e["game_snos_missing_reason"]:
                tr_bad.append(f"{i['identity']['scope']}/{metric} "
                              "game_snos 為 null 但沒有原因")
            cand = cand_by_id[e["source_candidate_id"]]
            if e["derivation"] != cand["calculation_reference"]["formula"]:
                tr_bad.append(f"{metric} derivation 不符 Step 9 formula")
    checks.append(
        ("每個 metric 都能追溯到 step / file / field / formula", not tr_bad,
         f"{tr_rows} 個 metric 追溯記錄全部帶 source_step / source_file / "
         "source_field / derivation / source_candidate_id；"
         "引用的檔案全部存在；formula 與 Step 9 一致；"
         "game_snos 為 null 者全部附原因"
         if not tr_bad else "；".join(tr_bad[:5]))
    )

    # 4. phenomenon 數值與 Step 20 完全一致
    ph_bad = []
    ph_rows = 0
    for i in insights:
        rec = rec_by_scope[i["identity"]["scope"]]
        rows = {r["metric"]: r for r in rec["evidence_summary"]["metrics"]}
        for s in i["phenomenon"]["statements"]:
            m = s["metric"]
            if m not in rows:
                if s["statement_kind"] != "explicit_null" or s["current_value"] \
                        is not None:
                    ph_bad.append(f"{i['identity']['scope']}/{m} 缺值卻不是 null")
                continue
            ph_rows += 1
            r = rows[m]
            got = (s["current_value"], s["baseline_value"], s["difference"],
                   s["direction"])
            exp = (r["current_value"], r["baseline_value"], r["difference"],
                   r["direction"])
            if got != exp:
                ph_bad.append(f"{i['identity']['scope']}/{m} 數值不符 Step 20")
            # 文字裡的數字必須與欄位一致（8 位小數）
            if fmt(r["current_value"]) not in s["statement"]:
                ph_bad.append(f"{i['identity']['scope']}/{m} 文字缺 current")
            if signed(r["difference"]) not in s["statement"]:
                ph_bad.append(f"{i['identity']['scope']}/{m} 文字缺 difference")
    checks.append(
        ("phenomenon 的數值與文字都與 Step 20 完全一致", not ph_bad,
         f"{ph_rows} 個 statement 的 current / baseline / difference / direction "
         "逐一比對相符，且數字以 8 位小數原樣寫入文字"
         if not ph_bad else "；".join(ph_bad[:5]))
    )

    # 5. sample context 與 Step 11 一致
    sc_bad = []
    sc_rows = 0
    for i in insights:
        for it in i["supporting_evidence"]["primary_metrics"]:
            sc_rows += 1
            s = samples[it["source_candidate_id"]]
            sc = s["sample_context"]
            sens = s["sample_sensitivity"][it["metric"]]
            if (it["sample_size"]["at_bats"] != sc["at_bats"]
                    or it["sample_size"]["plate_appearances"]
                    != sc["plate_appearances"]
                    or it["sample_size"]["games"] != sc["games"]):
                sc_bad.append(f"{it['source_candidate_id']} sample_size 不符")
            sv = it["sensitivity"]
            if (sv["numerator"] != sens["numerator"]
                    or sv["denominator"] != sens["denominator"]
                    or sv["delta_if_one_more"] != sens["delta_if_one_more"]
                    or sv["one_more_success"] != sens["one_more_success"]
                    or sv["one_fewer_success"] != sens["one_fewer_success"]):
                sc_bad.append(f"{it['source_candidate_id']} sensitivity 不符")
    checks.append(
        ("sample context 與 sensitivity 與 Step 11 完全一致", not sc_bad,
         f"{sc_rows} 個 metric 的 sample_size 與 sensitivity 逐欄位比對相符"
         if not sc_bad else "；".join(sc_bad[:5]))
    )

    # 6. decision relevance 與 Step 19 一致
    dr_bad = []
    dr_cmp = 0
    for i in insights:
        src = rel_by_scope[i["identity"]["scope"]]
        c = i["context"]
        pairs = [
            (c["contextual_relevance"], src["contextual_relevance"]),
            (c["context_official_item_name"], src["context_official_item_name"]),
            (c["temporal_relevance"], src["temporal_relevance"]),
            (c["next_game_dependency"]["evidence_depends_on_next_game"],
             src["next_game_dependency"]["evidence_depends_on_next_game"]),
            (c["next_game_dependency"]["basis"],
             src["next_game_dependency"]["basis"]),
            (c["application_dependency"]["requires_additional_data"],
             src["application_dependency"]["requires_additional_data"]),
            (c["application_dependency"]["additional_data"],
             src["application_dependency"]["additional_data"]),
            (c["possible_decision_area"],
             src["action_link"]["possible_decision_area"]),
            (c["possible_action_link"], src["action_link"]["possible_action_link"]),
            (i["limitations"]["data_availability"]["step19_value"],
             src["data_availability"]["status"]),
        ]
        for got, exp in pairs:
            dr_cmp += 1
            if got != exp:
                dr_bad.append(f"{i['identity']['scope']} context 欄位不符 Step 19")
    checks.append(
        ("context / decision relevance 與 Step 19 完全一致", not dr_bad,
         f"9 個 insight × 10 個欄位 = {dr_cmp} 次逐一比對相符"
         if not dr_bad else "；".join(dr_bad[:5]))
    )

    # 7. group membership 與 Step 18 一致
    mem_bad = []
    total_members = 0
    for i in insights:
        g = grp_by_scope[i["identity"]["scope"]]
        if i["identity"]["candidate_ids"] != g["member_candidate_ids"]:
            mem_bad.append(f"{i['identity']['scope']} 成員不符 Step 18")
        if i["identity"]["candidate_count"] != g["member_count"]:
            mem_bad.append(f"{i['identity']['scope']} 成員數不符")
        total_members += i["identity"]["candidate_count"]
    checks.append(
        ("candidate membership 與 Step 18 完全一致", not mem_bad and total_members == 29,
         f"9 個 group 的成員清單與成員數逐一相符，總數 {total_members} = 29"
         if not mem_bad else "；".join(mem_bad[:5]))
    )

    # 8. PATTERN 沒有新增數值
    pat_bad = []
    pat_cmp = 0
    pat_n = 0
    for i in insights:
        cm = i["phenomenon"]["cross_metric_statement"]
        if cm is None:
            continue
        pat_n += 1
        p = cand_by_id[cm["source_candidate_id"]]
        # (a) 摘要文字裡不得出現任何小數數字
        digits = [ch for ch in cm["statement"] if ch == "."]
        if digits:
            pat_bad.append(f"{p['candidate_id']} 摘要文字含小數")
        # (b) direction 與 consistency 原樣沿用
        if (cm["direction_per_metric"] != p["direction_per_metric"]
                or cm["consistency_count"] != p["consistency_count"]
                or cm["total_metrics"] != p["total_metrics"]
                or cm["direction"] != p["direction"]):
            pat_bad.append(f"{p['candidate_id']} direction 摘要不符 Step 9")
        # (c) PATTERN 的每個 metric difference 都等於同 insight 的 evidence
        ev = {e["metric"]: e["difference"]
              for e in i["supporting_evidence"]["primary_metrics"]}
        for metric, mv in p["metric_values"].items():
            pat_cmp += 1
            if metric not in ev:
                pat_bad.append(f"{p['candidate_id']} {metric} 沒有對應 evidence")
            elif ev[metric] != mv["difference"]:
                pat_bad.append(f"{p['candidate_id']} {metric} difference 不符")
        if not cm["adds_no_new_number"]:
            pat_bad.append(f"{p['candidate_id']} 未宣告 adds_no_new_number")
    checks.append(
        ("PATTERN 沒有新增任何數值", not pat_bad,
         f"{pat_n} 個 PATTERN：摘要文字不含任何小數；direction 與 "
         f"consistency 原樣沿用 Step 9；{pat_cmp} 次 difference 比對"
         "全部等於同 insight 既有的 evidence"
         if not pat_bad else "；".join(pat_bad[:5]))
    )

    # 9. 不產生 score / weight / threshold / ranking / priority
    payload = {"insights": insights}
    blob = json.dumps(payload, ensure_ascii=False)
    decl: list[str] = []
    collect_declarative_text(payload, decl)
    for i in insights:
        decl.append(json.dumps(i["contains_no"], ensure_ascii=False))
        decl.append(json.dumps(
            i["phenomenon"]["statement_rule"]["contains_no_judgement"],
            ensure_ascii=False))
    decl_blob = "\n".join(decl)

    bad_keys = scan_keys(payload)
    # CPBL 官方 endpoint 名稱本身含「score」（apart_score / follow_score），
    # 那是資料來源檔名，不是本專案產生的 score。掃描前先中性化，避免誤判。
    neutral = blob
    neutral_decl = decl_blob
    for tok in DATA_SOURCE_TOKENS:
        neutral = neutral.replace(tok, "cpbl_official_endpoint")
        neutral_decl = neutral_decl.replace(tok, "cpbl_official_endpoint")
    thr = []
    for w in ("threshold", "門檻", "cutoff", "top_n", "Top-N", "score", "weight",
              "加權", "分數"):
        cnt = neutral.count(w) - neutral_decl.count(w)
        if cnt > 0:
            thr.append(f"{w}×{cnt}")
    checks.append(
        ("沒有 score / weight / threshold / ranking / priority / importance / "
         "confidence score / Top-N", not bad_keys and not thr,
         "遞迴掃描所有巢狀欄位名：沒有任何相關欄位"
         "（percentile_rank、rank_desc 為 Step 6 既有描述子，已排除）；"
         f"字眼掃描 9 個詞，扣除宣告性欄位並中性化 CPBL endpoint 名稱"
         f"（{'、'.join(DATA_SOURCE_TOKENS)}，官方檔名本身含 score）後為 0"
         if not bad_keys and not thr
         else f"欄位={sorted(set(bad_keys))[:6]}　字眼={thr}")
    )

    # 10. phenomenon 嚴格字眼掃描（不扣除任何宣告性欄位）
    texts = all_statement_texts(insights)
    strict_hits = []
    for t in texts:
        low = t.lower()
        for w in JUDGEMENT_WORDS:
            if (w in t) or (w in low):
                strict_hits.append(f"{w} @ {t[:28]}")
    checks.append(
        ("phenomenon 文字不含任何價值判斷或結論字眼（嚴格掃描，不扣除宣告性欄位）",
         not strict_hits,
         f"{len(texts)} 段 statement × {len(JUDGEMENT_WORDS)} 個禁用字眼 = "
         f"{len(texts) * len(JUDGEMENT_WORDS)} 次比對，命中 0 次"
         if not strict_hits else "；".join(strict_hits[:6]))
    )

    # 11. 不產生 recommendation / prediction（全文，扣除宣告性欄位）
    forbidden = ("建議", "應該", "推薦", "預測", "策略", "最佳", "最好", "最差",
                 "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
                 "值得注意", "recommend", "predict", "strategy", "should", "best")
    hits = []
    for w in forbidden:
        cnt = blob.count(w) - decl_blob.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    checks.append(
        ("不產生 recommendation / prediction / strategy", not hits,
         "全文掃描：未出現禁用字眼（宣告性與說明性欄位已扣除）"
         if not hits else "、".join(hits))
    )

    # 12. 不修改 candidate / grouping / raw / processed
    checks.append(
        ("沒有修改 candidate（深度比較 29 個物件）",
         candidates_before == candidates_after,
         "逐欄位比較完全相同"
         if candidates_before == candidates_after else "有 candidate 被改動")
    )
    checks.append(
        ("沒有修改 Step 18 的 grouping（深度比較 9 個物件）",
         groups_before == groups_after,
         "逐欄位比較完全相同" if groups_before == groups_after else "有 group 被改動")
    )
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data 未被修改", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    # 13. deterministic
    det = full_signature(insights) == full_signature(rerun)
    checks.append(
        ("deterministic：重跑結果完全一致", det,
         "整條流程重跑一次，序列化結果完全相同" if det else "重跑結果不同")
    )

    # 14. 不發 HTTP request
    checks.append(
        ("沒有任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖")
    )

    # 15. 所有 missing data 都被明確保留
    ms_bad = []
    req_n = 0
    miss_n = 0
    blocked_slots = 0
    for i in insights:
        md = i["limitations"]["missing_data"]
        rec = rec_by_scope[i["identity"]["scope"]]
        if md["required_additional_data"] != rec["missing_information"][
                "required_additional_data"]:
            ms_bad.append(f"{i['identity']['scope']} required 與 Step 20 不符")
        if md["missing_for_application"] != rec["missing_information"][
                "missing_for_application"]:
            ms_bad.append(f"{i['identity']['scope']} missing 與 Step 20 不符")
        if md["missing_count"] != len(md["missing_for_application"]):
            ms_bad.append(f"{i['identity']['scope']} missing_count 不符")
        req_n += len(md["required_additional_data"])
        miss_n += len(md["missing_for_application"])
        for item in md["required_additional_data"]:
            if not item.get("factual_basis") or not item.get(
                    "availability_source_step"):
                ms_bad.append(f"{i['identity']['scope']} 缺來源")
        um = i["limitations"]["unavailable_metrics"]
        if um["metrics"] and not um["reason"]:
            ms_bad.append(f"{i['identity']['scope']} unavailable_metrics 缺原因")
        for s in i["phenomenon"]["statements"]:
            if s["statement_kind"] != "explicit_null":
                continue
            blocked_slots += 1
            if s["current_value"] is not None or s["metric"] not in um["metrics"]:
                ms_bad.append(f"{i['identity']['scope']} null slot 不一致")
            if s["interpretation_status"] != "blocked_by_missing_data":
                ms_bad.append(f"{i['identity']['scope']} null slot 狀態不符")
    checks.append(
        ("所有 missing data 都被明確保留，沒有隱藏也沒有填補", not ms_bad,
         f"{req_n} 筆 required_additional_data（其中 {miss_n} 筆列為缺口）"
         f"與 Step 20 逐欄位相同；{blocked_slots} 個 metric slot 明確寫成 "
         "null + 原因 + blocked_by_missing_data，沒有任何估算值"
         if not ms_bad else "；".join(ms_bad[:5]))
    )

    # 16. interpretation_status 受控
    st_bad = []
    for i in insights:
        s = i["interpretation_status"]
        if s["status"] is not None and s["status"] not in INTERPRETATION_STATUS_VALUES:
            st_bad.append(f"{i['identity']['scope']} status 不在詞彙內")
        for metric, v in s["by_metric"].items():
            if v not in INTERPRETATION_STATUS_VALUES:
                st_bad.append(f"{i['identity']['scope']}/{metric} 不在詞彙內")
        if sorted(s["by_metric"]) != sorted(ALL_METRICS):
            st_bad.append(f"{i['identity']['scope']} by_metric 未覆蓋 3 個 metric")
        if s["rule_not_inputs"] != ASSEMBLY_NOT_INPUTS:
            st_bad.append(f"{i['identity']['scope']} rule_not_inputs 被改動")
        # 結構性判定必須與 evidence 結構相符
        for it in i["supporting_evidence"]["primary_metrics"]:
            expect = ("factual_with_context"
                      if it["rolling_percentile"] is not None else "factual_only")
            if s["by_metric"][it["metric"]] != expect:
                st_bad.append(f"{i['identity']['scope']}/{it['metric']} 狀態不符結構")
    slot_vals = sorted({v for i in insights
                        for v in i["interpretation_status"]["by_metric"].values()})
    insight_vals = sorted({i["interpretation_status"]["status"] for i in insights})
    checks.append(
        ("interpretation_status 只使用受控詞彙，且判定純結構性", not st_bad,
         f"metric slot 實際出現 {len(slot_vals)} 種值 {slot_vals}；"
         f"insight 層級出現 {len(insight_vals)} 種值 {insight_vals}；"
         "判定只看「是否有滾動分布位置 / 是否有場次追溯 / 數值是否存在」"
         if not st_bad else "；".join(st_bad[:5]))
    )

    # 17. mutation test
    checks.append(
        ("mutation test：magnitude / AB / classification / candidate 順序改變後，"
         "結構與規則不變，也沒有冒出 priority / ranking",
         mutation["structure_independent_of_values"],
         f"變異 {mutation['mutants']}，共 {mutation['cases_tested']} 次完整重跑；"
         f"簽章改變 {len(mutation['changes'])} 次、禁用欄位洩漏 "
         f"{len(mutation['forbidden_key_leaks'])} 次、"
         f"詞彙外狀態 {len(mutation['status_vocabulary_leaks'])} 次。"
         "magnitude / AB 變異只比對不含數值的規則簽章（數字本來就該跟資料變）；"
         "classification 與順序變異比對完整輸出，要求逐位元相同。"
         if mutation["structure_independent_of_values"]
         else "；".join(mutation["changes"] + mutation["forbidden_key_leaks"]
                        + mutation["status_vocabulary_leaks"]))
    )

    # 18. 沒有 LLM / UI
    imported = collect_imported_modules(Path(__file__))
    loaded = {m.split(".")[0].lower() for m in sys.modules}
    llm_hits = sorted((imported | loaded) & LLM_PACKAGE_NAMES)
    ui_hits = sorted((imported | loaded) & UI_PACKAGE_NAMES)
    checks.append(
        ("沒有使用 LLM，也沒有引入任何 UI / 前端框架",
         not llm_hits and not ui_hits,
         f"AST 解析本檔案 import 的頂層模組 {len(imported)} 個："
         + "、".join(sorted(imported))
         + f"；已載入模組中沒有 LLM 套件（{len(LLM_PACKAGE_NAMES)} 個比對）"
         f"也沒有 UI 框架（{len(UI_PACKAGE_NAMES)} 個比對）"
         if not llm_hits and not ui_hits
         else f"LLM={llm_hits}　UI={ui_hits}")
    )

    # 19. 6 個區塊齊全
    blocks = ("identity", "phenomenon", "supporting_evidence", "context",
              "limitations", "traceability")
    bl_bad = []
    for i in insights:
        for b in blocks:
            if b not in i or not i[b]:
                bl_bad.append(f"{i['identity']['scope']} 缺 {b}")
        if not i["interpretation_status"]["vocabulary"]:
            bl_bad.append(f"{i['identity']['scope']} 缺 interpretation vocabulary")
    checks.append(
        ("每個 insight 都有 6 個指定區塊 + interpretation_status", not bl_bad,
         f"9 個 insight × {len(blocks)} 個區塊全部存在，"
         "另加 interpretation_status / assembly_rule / provenance"
         if not bl_bad else "；".join(bl_bad[:5]))
    )

    # 20. 沒有依 magnitude / sample size / classification 組裝
    rule_ok = all(
        i["assembly_rule"]["rule_not_inputs"] == ASSEMBLY_NOT_INPUTS
        and i["assembly_rule"]["rule_inputs"] == [
            "step20_presentation_record", "step18_group_membership",
            "step9_candidate_evidence"]
        for i in insights
    )
    cls_keys = [k for k in scan_keys(payload) if "classification" in k.lower()]
    cls_text = blob.count("noteworthy") - decl_blob.count("noteworthy")
    checks.append(
        ("組裝沒有依 magnitude / sample size / classification 決定",
         rule_ok and not cls_keys and cls_text <= 0
         and mutation["structure_independent_of_values"],
         f"rule_inputs 只有 3 項；rule_not_inputs 明確列出 "
         f"{len(ASSEMBLY_NOT_INPUTS)} 個未使用的量；輸出中沒有 classification 欄位，"
         "也沒有 noteworthy / observation 字眼；classification 變異後輸出逐位元相同"
         if rule_ok and not cls_keys and cls_text <= 0
         else f"rule_ok={rule_ok}　cls_keys={cls_keys}　noteworthy×{cls_text}")
    )

    return checks


# ------------------------------------------------------------------ 輸出

def print_overview(insights: list) -> None:
    print("\n" + "=" * 110)
    print("9 個 assembled insight 總覽（順序依 scope 字母，這不是 ranking）")
    print("=" * 110)
    print(f"  {'scope':<14} {'insight_status':<24} {'metric':<7} "
          f"{'evidence 種類':<13} {'missing':<8} {'null slot'}")
    for i in insights:
        se = i["supporting_evidence"]
        nulls = [s["metric_label"] for s in i["phenomenon"]["statements"]
                 if s["statement_kind"] == "explicit_null"]
        print(f"  {i['identity']['scope']:<14} "
              f"{str(i['interpretation_status']['status']):<24} "
              f"{se['primary_metric_count']:<7} "
              f"{se['evidence_kind_count']:<13} "
              f"{i['limitations']['missing_data']['missing_count']:<8} "
              f"{','.join(nulls) or '-'}")

    print(f"\n  {'scope':<14} metric slot 的 interpretation_status")
    for i in insights:
        bm = i["interpretation_status"]["by_metric"]
        cells = "　".join(f"{METRIC_LABEL[m]}={bm[m]}" for m in ALL_METRICS)
        print(f"  {i['identity']['scope']:<14} {cells}")


def print_insights(insights: list) -> None:
    print("\n" + "=" * 110)
    print("每個 assembled insight")
    print("=" * 110)
    for i in insights:
        idt = i["identity"]
        se = i["supporting_evidence"]
        ctx = i["context"]
        lim = i["limitations"]
        st = i["interpretation_status"]

        print(f"\n{'-' * 110}")
        print(f"  [{idt['insight_id']}]")
        print(f"  1. identity")
        print(f"     group_id    : {idt['group_id']}")
        print(f"     perspective : {idt['perspective']}（{idt['perspective_name']}）")
        print(f"     scope       : {idt['scope']}")
        print(f"     candidates  : {idt['candidate_count']} 個")
        for cid in idt["candidate_ids"]:
            print(f"         - {cid}")

        print(f"  2. phenomenon（{i['phenomenon']['statement_count']} 段）")
        for s in i["phenomenon"]["statements"]:
            print(f"     [{s['statement_kind']}] {s['statement']}")
        cm = i["phenomenon"]["cross_metric_statement"]
        if cm:
            print(f"     [{cm['statement_kind']}] {cm['statement']}")
            print(f"         adds_no_new_number={cm['adds_no_new_number']}"
                  f"　來源 {cm['source_candidate_id']}")
        else:
            print(f"     cross_metric_statement: null"
                  f"（此 scope 在 Step 9 沒有 3/3 PATTERN）")

        print(f"  3. supporting_evidence（{se['primary_metric_count']} 個主要 metric）")
        for e in se["primary_metrics"]:
            print(f"     {e['metric_label']}: current={fmt(e['current_value'])}"
                  f"  baseline={fmt(e['baseline_value'])}"
                  f"  difference={signed(e['difference'])}"
                  f"  direction={e['direction']}")
            ss = e["sample_size"]
            sv = e["sensitivity"]
            print(f"         sample     : AB={ss['at_bats']}"
                  f"  PA={ss['plate_appearances']}  games={ss['games']}"
                  f"  (Step 11)")
            print(f"         sensitivity: {sv['numerator']}/{sv['denominator']}"
                  f"  one_more={fmt(sv['one_more_success'])}"
                  f"  one_fewer={fmt(sv['one_fewer_success'])}"
                  f"  delta={fmt(sv['delta_if_one_more'])}")
            rp = e["rolling_percentile"]
            if rp:
                print(f"         rolling    : rank={rp['rank_desc']}"
                      f"/{rp['distribution_n']}"
                      f"  percentile_rank={fmt(rp['percentile_rank'], 4)}"
                      f"  (Step 6)")
            else:
                print(f"         rolling    : null　原因："
                      f"{e['rolling_percentile_missing_reason']}")
            print(f"         status     : {e['interpretation_status']}")
            print(f"         kinds      : {e['evidence_kinds']}")
        if se["metrics_unavailable"]:
            print(f"     metrics 缺：{se['metrics_unavailable']}"
                  f"　原因：{se['metrics_unavailable_reason']}")

        print(f"  4. context")
        print(f"     contextual_relevance = {ctx['contextual_relevance']}"
              f"　temporal_relevance = {ctx['temporal_relevance']}")
        print(f"     next_game_dependency.evidence_depends_on_next_game = "
              f"{ctx['next_game_dependency']['evidence_depends_on_next_game']}")
        print(f"     application_dependency.requires_additional_data = "
              f"{ctx['application_dependency']['requires_additional_data']}"
              f"　additional_data = "
              f"{ctx['application_dependency']['additional_data']}")
        print(f"     possible_decision_area = {ctx['possible_decision_area']}")

        print(f"  5. limitations")
        sl = lim["sample_limitation"]
        print(f"     sample     : AB={sl['at_bats']}  PA={sl['plate_appearances']}"
              f"  games={sl['games']}")
        print(f"                  single_event_delta="
              f"{ {METRIC_LABEL[k]: round(v, 6) for k, v in sl['single_event_delta'].items()} }")
        md = lim["missing_data"]
        print(f"     missing    : count={md['missing_count']}")
        for item in md["required_additional_data"]:
            print(f"        required: {item['item']}　status={item['status']}")
        for item in md["missing_for_application"]:
            print(f"        MISSING : {item['item']}（{item['status']}）")
        if not md["missing_for_application"]:
            print(f"        MISSING : （無缺口）")
        um = lim["unavailable_metrics"]
        print(f"     unavailable_metrics: {um['metrics'] or '（無）'}"
              f"　count={um['count']}")
        da = lim["data_availability"]
        print(f"     data_availability  : evidence={da['evidence_data_status']}"
              f"　application={da['application_data_status']}")
        if lim["temporal_limitation"]:
            print(f"     temporal_limitation: {lim['temporal_limitation']}")

        print(f"  6. traceability（{i['traceability']['metric_count']} 個 metric）")
        for metric, e in i["traceability"]["by_metric"].items():
            print(f"     {METRIC_LABEL[metric]}: step={e['source_step_ids']}")
            print(f"         file       = {e['source_file']}")
            print(f"         field      = {e['source_field']}")
            print(f"         derivation = {e['derivation']}")
            if e["game_snos"]:
                print(f"         game_snos  = {e['game_snos_count']} 場 "
                      f"{e['game_snos']}")
                print(f"         date_range = "
                      f"{e['date_range']['first_game_date']} ~ "
                      f"{e['date_range']['last_game_date']}")
            else:
                print(f"         game_snos  = null　原因："
                      f"{e['game_snos_missing_reason']}")

        print(f"  interpretation_status = {st['status']}")
        print(f"     by_metric = {st['by_metric']}")
        print(f"     rule_inputs = {st['rule_inputs']}")


def print_answers(insights: list) -> None:
    print("\n" + "=" * 110)
    print("回答")
    print("=" * 110)

    print("\n  (1) 什麼叫做 factual insight")
    print("      phenomenon 只由這些欄位組成：scope、metric、current_value、")
    print("      baseline_value、difference、direction、sample 計數、window / 官方分項名稱。")
    texts = all_statement_texts(insights)
    print(f"      本次共 {len(texts)} 段 statement，嚴格字眼掃描命中 0 次。")
    print(f"      範例：{insights[0]['phenomenon']['statements'][0]['statement']}")

    print("\n  (2) 一個 insight 如何由多個 evidence 組成")
    for i in insights:
        se = i["supporting_evidence"]
        print(f"      {i['identity']['scope']:<14} "
              f"{se['evidence_kind_count']} 種：{se['evidence_kinds']}")

    print("\n  (3) 如何避免從數字跳到結論")
    print("      (a) phenomenon 用固定 template 生成，沒有形容詞欄位。")
    print("      (b) interpretation_status 明確標出陳述邊界：")
    for v in INTERPRETATION_STATUS_VALUES:
        scopes = [i["identity"]["scope"] for i in insights
                  if i["interpretation_status"]["status"] == v]
        slots = sum(1 for i in insights
                    for x in i["interpretation_status"]["by_metric"].values()
                    if x == v)
        print(f"          {v:<26} insight {len(scopes)} 個{scopes}"
              f"　metric slot {slots} 個")
    print("      (c) context 只說「連到哪一類決策」，不說決策內容。")
    print("      (d) 驗證對 statement 文字做不扣除宣告性欄位的嚴格掃描。")

    print("\n  (4) 如何處理 sample size")
    print("      sample size 記錄在三個地方，但都不用來篩選：")
    for i in insights:
        sl = i["limitations"]["sample_limitation"]
        print(f"      {i['identity']['scope']:<14} AB={str(sl['at_bats']):<5} "
              f"PA={str(sl['plate_appearances']):<5} "
              f"games={str(sl['games']):<5} "
              f"AVG 單一事件 delta="
              f"{fmt(sl['single_event_delta'].get('batting_average'), 6)}")

    print("\n  (5) 如何處理 missing data")
    for i in insights:
        lim = i["limitations"]
        md = lim["missing_data"]
        um = lim["unavailable_metrics"]
        print(f"      {i['identity']['scope']:<14} "
              f"application={lim['data_availability']['application_data_status']:<20} "
              f"missing={md['missing_count']}"
              f"　metric null={um['metrics'] or '（無）'}")

    print("\n  (6) 如何保持完整 traceability")
    n = sum(i["traceability"]["metric_count"] for i in insights)
    with_snos = sum(1 for i in insights
                    for e in i["traceability"]["by_metric"].values()
                    if e["game_snos"])
    print(f"      {n} 個 metric 追溯記錄，其中 {with_snos} 個帶 game_snos 清單，")
    print(f"      {n - with_snos} 個 game_snos = null 並附明確原因。")
    print(f"      step_chain：{insights[0]['traceability']['step_chain']}")


# ------------------------------------------------------------------ main

def build_all(logs, apart_rows):
    candidates, groups, group_rel, samples, records = build_presentation_all(
        logs, apart_rows
    )
    insights = build_insights(records, candidates)
    return candidates, groups, group_rel, samples, records, insights


def main() -> None:
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }
    logs, apart_rows = load_inputs()

    candidates, groups, group_rel, samples, records, insights = build_all(
        logs, apart_rows
    )
    candidates_before = copy.deepcopy(candidates)
    groups_before = copy.deepcopy(groups)
    *_, rerun = build_all(logs, apart_rows)
    mutation = mutation_test(logs, apart_rows, insights)

    print("=" * 110)
    print("Insight Assembly Experiment（Step 21）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print(f"固定輸入：Step 20 的 {len(records)} 個 presentation record")
    print("這不是 UI、不是產品。只把已驗證的資料組裝成可閱讀且完全可追溯的 insight。")
    print("核心原則：phenomenon 只能是資料現象，不得跳到任何結論。")
    print(f"輸出順序：{ORDERING_NOTE['basis']}　{ORDERING_NOTE['is_not']}")
    print("=" * 110)

    print_overview(insights)
    print_answers(insights)
    print_insights(insights)

    print("\n" + "=" * 110)
    print("Mutation test")
    print("=" * 110)
    print(f"  變異                  : {mutation['mutants']}")
    print(f"  完整重跑次數          : {mutation['cases_tested']}")
    print(f"  簽章改變次數          : {len(mutation['changes'])}")
    print(f"  禁用欄位洩漏次數      : {len(mutation['forbidden_key_leaks'])}")
    print(f"  詞彙外狀態次數        : {len(mutation['status_vocabulary_leaks'])}")
    print(f"  結構與數值無關        : {mutation['structure_independent_of_values']}")
    for d in mutation["changes"] + mutation["forbidden_key_leaks"] \
            + mutation["status_vocabulary_leaks"]:
        print(f"    - {d}")

    print("\n" + "=" * 110)
    print("Validation")
    print("=" * 110)
    checks = run_validation(
        insights, rerun, records, groups_before, groups, candidates_before,
        candidates, candidates, group_rel, samples, mutation, fingerprints_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 "
              "docs/INSIGHT_ASSEMBLY_EXPERIMENT.md。")

    print("\n" + "=" * 110)
    print("本階段只做組裝。沒有 UI、沒有 ranking、沒有 priority、沒有 Top-N，")
    print("也沒有任何 prediction 或 recommendation。")
    print("=" * 110)


if __name__ == "__main__":
    main()

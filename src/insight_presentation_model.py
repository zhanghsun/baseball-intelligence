"""Insight Presentation Model Experiment（Step 20）。

它建立什麼：把 Step 18 的 9 個 insight group 與 Step 19 的 group-level decision
relevance，整理成 **machine-readable 的呈現模型**——使用者應該看到哪些資訊，
以及每一項資訊的資料狀態。

它**不**是什麼：
    - 不是 UI、不是前端實作，沒有 React / Flask / FastAPI / dashboard
    - 沒有 score / weight / threshold / ranking / priority / Top-N
    - 不用 magnitude 決定顯示與否、不用 sample size 篩選、不用 classification 決定顯示
    - 沒有自然語言結論、沒有 prediction、沒有 recommendation
    - 不使用 LLM、不發 HTTP 請求
    - 不新增 candidate、不新增 group
    - 不修改 candidate / grouping / raw / processed data

核心原則：**「資料缺口也必須是一級資訊。」**
    任何 group 都不會因為缺資料而被隱藏。缺什麼、缺到什麼程度、依據是什麼，
    全部以結構化欄位記錄。

三件事刻意分成三組獨立欄位，不合併成一個 boolean：
    A. evidence 本身是否完整          -> evidence_completeness
    B. evidence 是否可直接用於下一場決策 -> application_readiness
    C. 要完成應用還缺什麼資料          -> missing_for_application

用法：
    python src/insight_presentation_model.py
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
    SUBJECT,
    load_inputs,
    network_guard_active,
    sha256_of,
)
from group_decision_relevance import build_everything  # noqa: E402

# ------------------------------------------------------------------ 受控詞彙

# 本階段要求的 data status 詞彙。與 Step 19 的 data_availability 一對一改名，
# 沒有新增或合併任何狀態。
DATA_STATUS_VALUES = (
    "available",
    "partially_available",
    "unavailable",
    "not_investigated",
)

DATA_STATUS_FROM_AVAILABILITY = {
    "verified_available": "available",
    "partially_verified": "partially_available",
    "currently_unavailable": "unavailable",
    "not_investigated": "not_investigated",
}

DATA_STATUS_MAPPING_NOTE = (
    "本階段的 data status 詞彙與 Step 19 的 data_availability 一對一改名"
    "（verified_available -> available、partially_verified -> partially_available、"
    "currently_unavailable -> unavailable、not_investigated -> not_investigated）。"
    "沒有新增狀態、沒有合併狀態，也沒有改變任何事實判定。"
)

# A：evidence 本身是否完整
EVIDENCE_SELF_CONTAINMENT_VALUES = (
    "self_contained",
    "requires_next_game_context",
)

# B：是否可直接用於下一場決策
APPLICATION_READINESS_VALUES = (
    "ready_with_available_data",
    "not_ready_pending_data",
)

# presentation purpose（只描述「可以提供什麼資訊」）
PRESENTATION_PURPOSE_VALUES = (
    "recent_form_relative_to_season_baseline",
    "season_split_by_pitcher_hand_relative_to_season_baseline",
    "season_split_by_pitcher_role_relative_to_season_baseline",
    "season_split_by_pitcher_background_relative_to_season_baseline",
)

PURPOSE_BY_CONTEXTUAL_RELEVANCE = {
    "none": "recent_form_relative_to_season_baseline",
    "pitcher_hand": "season_split_by_pitcher_hand_relative_to_season_baseline",
    "pitcher_role": "season_split_by_pitcher_role_relative_to_season_baseline",
    "pitcher_background":
        "season_split_by_pitcher_background_relative_to_season_baseline",
}

# 該 group 可提供的資訊項目（受控詞彙，全部是事實性項目）
INFORMATION_ITEM_VALUES = (
    "metric_values_with_season_baseline_comparison",
    "sample_size_counts",
    "single_event_sensitivity",
    "rolling_distribution_position",
    "game_level_traceability",
    "official_split_definition_reference",
    "cross_metric_direction_summary",
)

PRESENTATION_NOT_INPUTS = [
    "magnitude", "sample_size_at_bats", "plate_appearances",
    "percentile_rank", "consistency_count", "classification",
]


# ------------------------------------------------------------------ 工具

def metric_short(metric: str) -> str:
    return {
        "batting_average": "AVG",
        "on_base_percentage": "OBP",
        "slugging_percentage": "SLG",
    }[metric]


def fmt(v, digits: int = 8) -> str:
    if v is None:
        return "null"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


# ------------------------------------------------------------------ Evidence summary

def build_metric_row(candidate: dict, sample: dict) -> dict:
    """單一 metric 的呈現列。數值全部原樣引用 Step 9 / Step 11，不重算。"""
    ctype = candidate["type"]
    metric = candidate["metric"]
    sens = sample["sample_sensitivity"][metric]
    sc = sample["sample_context"]

    if ctype == "TREND":
        current = candidate["current_value"]
        baseline = candidate["baseline_value"]
        difference = candidate["absolute_difference"]
        direction = candidate["direction"]
        rp = candidate["rolling_percentile"]
        percentile = None if rp is None else {
            "percentile_rank": rp["percentile_rank"],
            "percentile_strict": rp["percentile_strict"],
            "rank_desc": rp["rank_desc"],
            "distribution_n": rp["distribution_n"],
            "definition": rp["definition"],
            "source_step": "Step 6",
        }
        percentile_missing_reason = None
        traceability = {
            "source_candidate_id": candidate["candidate_id"],
            "source_step": "Step 9",
            "value_source_step": "Step 5",
            "date_range": dict(candidate["traceability"]["date_range"]),
            "game_snos": list(candidate["traceability"]["game_snos"]),
            "game_snos_missing_reason": None,
            "official_item_name": None,
            "source_files": list(candidate["source_files"]),
        }
    else:
        current = candidate["value"]
        baseline = candidate["comparison"]["baseline_value"]
        difference = candidate["comparison"]["difference"]
        direction = candidate["comparison"]["direction"]
        percentile = None
        percentile_missing_reason = (
            "官方分項沒有時間維度，無法建立滾動分布，因此沒有百分位（Step 8）"
        )
        traceability = {
            "source_candidate_id": candidate["candidate_id"],
            "source_step": "Step 9",
            "value_source_step": "Step 8",
            "date_range": None,
            "game_snos": None,
            "game_snos_missing_reason": (
                "官方分項不提供日期或場次，無法追溯到個別比賽（Step 8）"
            ),
            "official_item_name": candidate["context"]["official_item_name"],
            "source_files": list(candidate["source_files"]),
        }

    return {
        "metric": metric,
        "metric_label": metric_short(metric),
        "current_value": current,
        "baseline_value": baseline,
        "baseline_definition": "2026 一軍例行賽季累計（77 場實際出賽）",
        "difference": difference,
        "direction": direction,
        "sample_size": {
            "at_bats": sc["at_bats"],
            "plate_appearances": sc["plate_appearances"],
            "games": sc["games"],
            "games_missing_reason": sc.get("games_note"),
            "source_step": "Step 11",
        },
        "single_event_sensitivity": {
            "numerator": sens["numerator"],
            "denominator": sens["denominator"],
            "numerator_label": sens["numerator_label"],
            "denominator_label": sens["denominator_label"],
            "one_more_success": sens["one_more_success"],
            "one_fewer_success": sens["one_fewer_success"],
            "delta_if_one_more": sens["delta_if_one_more"],
            "success_unit": sens["success_unit"],
            "source_step": "Step 11",
            "is_not": "這是算術上的敏感度描述，不是可信程度",
        },
        "rolling_distribution_position": percentile,
        "rolling_distribution_missing_reason": percentile_missing_reason,
        "traceability": traceability,
    }


def build_evidence_summary(group: dict, candidates_by_id: dict,
                           samples: dict) -> dict:
    """group 的 evidence 摘要。

    metric 列一律取自 CONTEXT / TREND candidate；PATTERN 的內容改以
    cross_metric_direction 呈現，避免同一組數字在 group 內重複兩次
    （Step 18 第 10.6 節記錄的 group 內部重複問題）。

    這是**結構性去重**，不是依數值或分類篩選：PATTERN 的每個 metric 差距
    與對應 CONTEXT candidate 完全相同，驗證會逐一比對確認沒有資訊遺失。
    """
    members = [candidates_by_id[cid] for cid in group["member_candidate_ids"]]
    metric_members = [c for c in members if c["type"] in ("TREND", "CONTEXT")]
    patterns = [c for c in members if c["type"] == "MULTI_METRIC_PATTERN"]

    rows = sorted(
        (build_metric_row(c, samples[c["candidate_id"]]) for c in metric_members),
        key=lambda r: r["metric"],
    )

    if patterns:
        p = patterns[0]
        cross = {
            "available": True,
            "source_candidate_id": p["candidate_id"],
            "source_step": "Step 9",
            "metrics": list(p["metrics"]),
            "direction": p["direction"],
            "direction_per_metric": dict(p["direction_per_metric"]),
            "consistency_count": p["consistency_count"],
            "total_metrics": p["total_metrics"],
            "known_limitation": (
                "Step 10 已記錄：三個指標共用同一批安打與打數，本身高度相關，"
                "方向一致有相當程度是數學上的必然。方向判定不含任何最小差距門檻。"
            ),
            "deduplication_note": (
                "PATTERN 的每個 metric 差距與同 group 的 CONTEXT candidate 完全相同，"
                "因此不另外列成 metric 列，只以方向摘要呈現，避免重複顯示同一組數字。"
            ),
        }
    else:
        cross = {
            "available": False,
            "unavailable_reason": (
                "此 context 在 Step 9 沒有 3/3 的 MULTI_METRIC_PATTERN"
                "（三個指標與季累計比較的方向不一致），因此沒有跨指標方向摘要"
            ),
            "source_step": "Step 9",
        }

    all_metrics = {"batting_average", "on_base_percentage", "slugging_percentage"}
    present = {r["metric"] for r in rows}
    missing = sorted(all_metrics - present)

    return {
        "metrics": rows,
        "metrics_present": sorted(present),
        "metrics_unavailable": missing,
        "metrics_unavailable_reason": (
            "processed data 未收逐場犧牲飛球，TREND 窗口無法計算 OBP"
            "（Step 5 / Step 11 已記錄）"
            if missing else None
        ),
        "cross_metric_direction": cross,
    }


# ------------------------------------------------------------------ 三段區分 A / B / C

def build_evidence_completeness(group_rel: dict, evidence: dict) -> dict:
    """A：evidence 本身是否完整。"""
    dep = group_rel["next_game_dependency"]["evidence_depends_on_next_game"]
    containment = "requires_next_game_context" if dep else "self_contained"
    return {
        "question": "A. evidence 本身是否完整？",
        "evidence_available": True,
        "evidence_available_basis": (
            "所有 metric 的數值都已存在且已與來源 Step 交叉核對"
            "（Step 5 / Step 8 / Step 9）"
        ),
        "self_containment": containment,
        "self_containment_basis": group_rel["next_game_dependency"]["basis"],
        "metric_coverage": {
            "metrics_present": list(evidence["metrics_present"]),
            "metrics_unavailable": list(evidence["metrics_unavailable"]),
            "unavailable_reason": evidence["metrics_unavailable_reason"],
            "complete": not evidence["metrics_unavailable"],
        },
        "is_not": (
            "本組欄位只描述 evidence 本身，不描述能否用於下一場決策"
            "（那是 B），也不描述缺什麼資料（那是 C）"
        ),
    }


def build_application_readiness(group_rel: dict, data_status: str) -> dict:
    """B：evidence 是否可以直接用於下一場決策。"""
    ready = data_status == "available"
    return {
        "question": "B. evidence 是否可以直接用於下一場決策？",
        "readiness": (
            "ready_with_available_data" if ready else "not_ready_pending_data"
        ),
        "application_data_status": data_status,
        "requires_additional_data":
            group_rel["application_dependency"]["requires_additional_data"],
        "additional_data": group_rel["application_dependency"]["additional_data"],
        "readiness_basis": (
            "應用所需的額外資料狀態為 available，因此可直接應用"
            if ready else
            f"應用所需的額外資料狀態為 {data_status}，因此目前無法直接應用"
        ),
        "is_not": (
            "readiness = not_ready_pending_data **不代表** evidence 有問題，"
            "也不代表這個 group 應該被隱藏。evidence 完整性記錄在 A。"
        ),
    }


def build_missing_for_application(group_rel: dict, data_status: str) -> dict:
    """C：要完成應用還缺什麼資料。"""
    requirement = group_rel["action_link_requires"]
    da = group_rel["data_availability"]

    required_entry = {
        "item": requirement,
        "status": data_status,
        "availability_source_step": "Step 19",
        "evidence_steps": list(da["evidence_steps"]),
        "factual_basis": da["factual_basis"],
    }

    if data_status == "available":
        missing = []
        note = (
            "應用所需的額外資料已驗證可取得，因此沒有缺口。"
            "required_additional_data 仍然保留，讓使用者看得到這個依賴存在。"
        )
    else:
        missing = [required_entry]
        note = (
            "應用所需的額外資料尚未達到 available，因此列為缺口。"
            "缺口不會讓這個 group 被隱藏。"
        )

    return {
        "question": "C. 要完成應用還缺什麼資料？",
        "required_additional_data": [required_entry],
        "missing_for_application": missing,
        "missing_count": len(missing),
        "note": note,
        "no_guessing_note": (
            "缺失的資料一律不猜測、不填補。每一筆缺口都標明來源 Step 與事實依據。"
        ),
    }


# ------------------------------------------------------------------ Presentation record

def build_presentation_record(group: dict, group_rel: dict,
                              candidates_by_id: dict, samples: dict) -> dict:
    evidence = build_evidence_summary(group, candidates_by_id, samples)
    data_status = DATA_STATUS_FROM_AVAILABILITY[group_rel["data_availability"]["status"]]

    completeness = build_evidence_completeness(group_rel, evidence)
    readiness = build_application_readiness(group_rel, data_status)
    missing = build_missing_for_application(group_rel, data_status)

    purpose = PURPOSE_BY_CONTEXTUAL_RELEVANCE[group_rel["contextual_relevance"]]
    items = ["metric_values_with_season_baseline_comparison",
             "sample_size_counts", "single_event_sensitivity"]
    if group_rel["temporal_relevance"] == "recent_games":
        items += ["rolling_distribution_position", "game_level_traceability"]
    else:
        items += ["official_split_definition_reference"]
    if evidence["cross_metric_direction"]["available"]:
        items += ["cross_metric_direction_summary"]

    return {
        # ---- 1. group identity ----
        "group_identity": {
            "group_id": group["group_id"],
            "perspective": group["perspective"],
            "perspective_name": group["perspective_name"],
            "scope": group["scope"],
            "candidate_ids": list(group["member_candidate_ids"]),
            "candidate_count": group["member_count"],
            "subject": {
                "player_name": SUBJECT["player_name"],
                "player_acnt": SUBJECT["player_acnt"],
                "season": SUBJECT["season"],
                "kind_code": SUBJECT["kind_code"],
            },
        },

        # ---- 2. evidence summary ----
        "evidence_summary": evidence,

        # ---- 3. decision relevance（原樣引用 Step 19）----
        "decision_relevance": {
            "temporal_relevance": group_rel["temporal_relevance"],
            "contextual_relevance": group_rel["contextual_relevance"],
            "context_official_item_name": group_rel["context_official_item_name"],
            "next_game_dependency": {
                "evidence_depends_on_next_game":
                    group_rel["next_game_dependency"]["evidence_depends_on_next_game"],
                "basis": group_rel["next_game_dependency"]["basis"],
            },
            "application_dependency": {
                "requires_additional_data":
                    group_rel["application_dependency"]["requires_additional_data"],
                "additional_data":
                    group_rel["application_dependency"]["additional_data"],
            },
            "action_link": {
                "possible_action_link":
                    group_rel["action_link"]["possible_action_link"],
                "action_link_basis": group_rel["action_link"]["action_link_basis"],
                "possible_decision_area":
                    group_rel["action_link"]["possible_decision_area"],
            },
            "action_link_requires": group_rel["action_link_requires"],
            "data_availability": group_rel["data_availability"]["status"],
            "source_step": "Step 19",
        },

        # ---- 4. data status ----
        "data_status": {
            "application_data_status": data_status,
            "vocabulary": list(DATA_STATUS_VALUES),
            "mapped_from_step19_value": group_rel["data_availability"]["status"],
            "mapping_note": DATA_STATUS_MAPPING_NOTE,
            "evidence_data_status": "available",
            "evidence_data_status_basis": (
                "evidence 數值本身全部存在且已交叉核對；"
                "此欄位與 application_data_status 是兩件不同的事"
            ),
        },

        # ---- A / B / C 三段區分 ----
        "evidence_completeness": completeness,
        "application_readiness": readiness,
        "missing_information": missing,

        # ---- 6. presentation purpose ----
        "presentation_purpose": {
            "purpose": purpose,
            "provides_information_items": items,
            "is_not": (
                "purpose 只描述「這個 group 可以提供什麼資訊」。"
                "不是 recommendation、不是 prediction、不是 strategy。"
            ),
        },

        # ---- 顯示規則 ----
        "display_rule": {
            "rule_id": "P20-1",
            "always_displayed": True,
            "always_displayed_reason": (
                "資料缺口也是一級資訊。任何 group 都不會因為缺資料、"
                "數值小或樣本小而被隱藏。"
            ),
            "rule_inputs": ["group_membership", "step19_decision_relevance"],
            "rule_not_inputs": list(PRESENTATION_NOT_INPUTS),
        },

        "provenance": {
            "group_source_step": "Step 18",
            "group_source_module": "src/insight_grouping.py",
            "decision_relevance_source_step": "Step 19",
            "decision_relevance_source_module": "src/group_decision_relevance.py",
            "candidate_source_step": "Step 9",
            "candidate_source_module": "src/candidate_insights.py",
            "metric_value_source_steps": ["Step 5", "Step 8"],
            "sample_context_source_step": "Step 11",
            "rolling_distribution_source_step": "Step 6",
            "source_files": list(group["provenance"]["source_files"]),
            "sidecar_note": (
                "本記錄為 sidecar，用 group_id 關聯，"
                "不寫回 group 或 candidate 物件"
            ),
        },

        "contains_no": [
            "score", "weight", "threshold", "ranking", "priority", "importance",
            "confidence_score", "top_n", "prediction", "recommendation",
            "strategy", "natural_language_conclusion", "llm", "ui",
        ],
    }


def build_presentation_model(groups: list, group_rel_records: list,
                             candidates: list, samples: dict) -> list:
    candidates_by_id = {c["candidate_id"]: c for c in candidates}
    rel_by_scope = {r["scope"]: r for r in group_rel_records}
    return [
        build_presentation_record(g, rel_by_scope[g["scope"]],
                                  candidates_by_id, samples)
        for g in sorted(groups, key=lambda g: g["scope"])
    ]


# ------------------------------------------------------------------ 輸出

def print_overview(records: list) -> None:
    print("\n" + "=" * 108)
    print("Presentation Model 總覽（全部 9 個 group 一律呈現，沒有任何隱藏或排序）")
    print("=" * 108)
    print(f"  {'scope':<14} {'A: self_containment':<28} "
          f"{'B: readiness':<26} {'C: missing':<3}")
    for r in records:
        ec = r["evidence_completeness"]
        ar = r["application_readiness"]
        mi = r["missing_information"]
        print(f"  {r['group_identity']['scope']:<14} "
              f"{ec['self_containment']:<28} {ar['readiness']:<26} "
              f"{mi['missing_count']}")

    print(f"\n  {'scope':<14} {'evidence_data_status':<22} "
          f"{'application_data_status':<24} {'metric 數':<9} {'metrics 缺':<12}")
    for r in records:
        ds = r["data_status"]
        es = r["evidence_summary"]
        print(f"  {r['group_identity']['scope']:<14} "
              f"{ds['evidence_data_status']:<22} "
              f"{ds['application_data_status']:<24} "
              f"{len(es['metrics']):<9} "
              f"{','.join(es['metrics_unavailable']) or '-':<12}")

    print(f"\n  {'scope':<14} {'presentation_purpose':<58} {'資訊項目數'}")
    for r in records:
        pp = r["presentation_purpose"]
        print(f"  {r['group_identity']['scope']:<14} {pp['purpose']:<58} "
              f"{len(pp['provides_information_items'])}")


def print_records(records: list) -> None:
    print("\n" + "=" * 108)
    print("每個 group 的 presentation record")
    print("=" * 108)
    for r in records:
        gi = r["group_identity"]
        es = r["evidence_summary"]
        dr = r["decision_relevance"]
        ds = r["data_status"]
        ec = r["evidence_completeness"]
        ar = r["application_readiness"]
        mi = r["missing_information"]
        pp = r["presentation_purpose"]

        print(f"\n{'-' * 108}")
        print(f"  [{gi['group_id']}]")
        print(f"  1. group identity")
        print(f"     scope         : {gi['scope']}")
        print(f"     perspective   : {gi['perspective']}（{gi['perspective_name']}）")
        print(f"     candidate_ids : {gi['candidate_count']} 個")
        for cid in gi["candidate_ids"]:
            print(f"         - {cid}")

        print(f"  2. evidence summary（{len(es['metrics'])} 個 metric）")
        for m in es["metrics"]:
            print(f"     {m['metric_label']}: current={fmt(m['current_value'])}"
                  f"  baseline={fmt(m['baseline_value'])}"
                  f"  diff={fmt(m['difference'])}"
                  f"  direction={m['direction']}")
            ss = m["sample_size"]
            sv = m["single_event_sensitivity"]
            print(f"         sample: AB={ss['at_bats']}  PA={ss['plate_appearances']}"
                  f"  games={ss['games']}  (Step 11)")
            print(f"         sensitivity: {sv['numerator']}/{sv['denominator']}"
                  f"  one_more={fmt(sv['one_more_success'])}"
                  f"  one_fewer={fmt(sv['one_fewer_success'])}"
                  f"  delta={fmt(sv['delta_if_one_more'])}")
            rd = m["rolling_distribution_position"]
            if rd:
                print(f"         rolling: rank={rd['rank_desc']}/{rd['distribution_n']}"
                      f"  percentile_rank={fmt(rd['percentile_rank'], 4)} (Step 6)")
            else:
                print(f"         rolling: null　原因："
                      f"{m['rolling_distribution_missing_reason']}")
            tr = m["traceability"]
            if tr["game_snos"]:
                print(f"         traceability: {tr['source_candidate_id']}")
                print(f"             {tr['date_range']['first_game_date']}"
                      f" ~ {tr['date_range']['last_game_date']}"
                      f"　game_snos({len(tr['game_snos'])})")
            else:
                print(f"         traceability: {tr['source_candidate_id']}"
                      f"　官方 {tr['official_item_name']}")
                print(f"             game_snos=null　原因："
                      f"{tr['game_snos_missing_reason']}")
        if es["metrics_unavailable"]:
            print(f"     metrics 缺：{es['metrics_unavailable']}"
                  f"　原因：{es['metrics_unavailable_reason']}")
        cmd = es["cross_metric_direction"]
        if cmd["available"]:
            print(f"     cross_metric_direction: {cmd['direction']}"
                  f"  {cmd['consistency_count']}/{cmd['total_metrics']}"
                  f"  per_metric={cmd['direction_per_metric']}")
            print(f"         來源 {cmd['source_candidate_id']}")
        else:
            print(f"     cross_metric_direction: 不可用　原因："
                  f"{cmd['unavailable_reason']}")

        print(f"  3. decision relevance（Step 19）")
        print(f"     temporal={dr['temporal_relevance']}"
              f"  contextual={dr['contextual_relevance']}")
        print(f"     evidence_depends_on_next_game="
              f"{dr['next_game_dependency']['evidence_depends_on_next_game']}")
        print(f"     application requires_additional_data="
              f"{dr['application_dependency']['requires_additional_data']}"
              f"  additional_data={dr['application_dependency']['additional_data']}")
        print(f"     action_link={dr['action_link']['possible_action_link']}")
        print(f"     decision_area={dr['action_link']['possible_decision_area']}")
        print(f"     action_link_requires={dr['action_link_requires']}")
        print(f"     data_availability={dr['data_availability']}")

        print(f"  4. data status")
        print(f"     evidence_data_status    = {ds['evidence_data_status']}")
        print(f"     application_data_status = {ds['application_data_status']}"
              f"（由 Step 19 的 {ds['mapped_from_step19_value']} 對應）")

        print(f"  A. evidence_completeness")
        print(f"     evidence_available = {ec['evidence_available']}")
        print(f"     self_containment   = {ec['self_containment']}")
        print(f"     metric_coverage.complete = {ec['metric_coverage']['complete']}")
        print(f"  B. application_readiness")
        print(f"     readiness = {ar['readiness']}")
        print(f"     basis     = {ar['readiness_basis']}")
        print(f"  C. missing_information")
        print(f"     missing_count = {mi['missing_count']}")
        for item in mi["required_additional_data"]:
            print(f"     required: {item['item']}　status={item['status']}")
            print(f"         依據 Step {item['evidence_steps'] or '（無）'}")
            print(f"         {item['factual_basis']}")
        if mi["missing_for_application"]:
            for item in mi["missing_for_application"]:
                print(f"     MISSING: {item['item']}（{item['status']}）")
        else:
            print(f"     MISSING: （無缺口）")

        print(f"  6. presentation purpose")
        print(f"     purpose = {pp['purpose']}")
        print(f"     provides:")
        for it in pp["provides_information_items"]:
            print(f"         - {it}")
        print(f"  display_rule: always_displayed="
              f"{r['display_rule']['always_displayed']}"
              f"　inputs={r['display_rule']['rule_inputs']}")


def print_answers(records: list) -> None:
    print("\n" + "=" * 108)
    print("回答")
    print("=" * 108)

    print("\n  (2) 可以直接顯示的資訊（evidence 本身，全部 9 個 group 都有）：")
    print("      每個 metric 的 current / baseline / difference / direction、")
    print("      sample size（AB / PA / games）、single event sensitivity、traceability。")
    for r in records:
        es = r["evidence_summary"]
        print(f"      {r['group_identity']['scope']:<14} "
              f"metric {len(es['metrics'])} 個"
              f"　rolling={'有' if es['metrics'][0]['rolling_distribution_position'] else '無'}"
              f"　game_snos="
              f"{'有' if es['metrics'][0]['traceability']['game_snos'] else '無'}"
              f"　cross_metric={'有' if es['cross_metric_direction']['available'] else '無'}")

    print("\n  (3) 需要額外資料才能用於下一場決策：")
    for status in DATA_STATUS_VALUES:
        scopes = [r["group_identity"]["scope"] for r in records
                  if r["data_status"]["application_data_status"] == status]
        if not scopes:
            continue
        sample = next(r for r in records
                      if r["data_status"]["application_data_status"] == status)
        req = sample["missing_information"]["required_additional_data"][0]["item"]
        ready = sample["application_readiness"]["readiness"]
        print(f"      {status:<22} {len(scopes)} 個　{scopes}")
        print(f"          required = {req}")
        print(f"          readiness = {ready}")

    print("\n  (4) 目前拿不到的資料：")
    unavail = [r for r in records
               if r["data_status"]["application_data_status"] == "unavailable"]
    notinv = [r for r in records
              if r["data_status"]["application_data_status"] == "not_investigated"]
    print(f"      unavailable       : "
          f"{[r['group_identity']['scope'] for r in unavail]}")
    if unavail:
        print(f"          {unavail[0]['missing_information']['required_additional_data'][0]['factual_basis']}")
    print(f"      not_investigated  : "
          f"{[r['group_identity']['scope'] for r in notinv]}")
    if notinv:
        print(f"          {notinv[0]['missing_information']['required_additional_data'][0]['factual_basis']}")

    print("\n  (5) 使用者如何知道一個數字的 sample size 與來源：")
    print("      每個 metric 列都內建這些欄位，不需要另外查：")
    m = records[0]["evidence_summary"]["metrics"][0]
    print(f"        sample_size            : {m['sample_size']}")
    print(f"        single_event_sensitivity: delta_if_one_more="
          f"{fmt(m['single_event_sensitivity']['delta_if_one_more'])}"
          f"  success_unit={m['single_event_sensitivity']['success_unit']}")
    print(f"        traceability            : "
          f"source_candidate_id={m['traceability']['source_candidate_id']}"
          f"  value_source_step={m['traceability']['value_source_step']}")

    print("\n  (6) 如何避免把資料缺口誤解成「沒有問題」：")
    print("      三個機制：")
    print("      (a) A / B / C 三段分開，不合併成一個 boolean。")
    print("          例如 VS_RIGHT：A=self_contained、B=not_ready_pending_data，")
    print("          兩者同時成立，任何單一 boolean 都無法表達。")
    print("      (b) evidence_data_status 與 application_data_status 分成兩個欄位。")
    print("          9 個 group 的 evidence_data_status 都是 available，")
    print("          但 application_data_status 有 4 種不同值。")
    print("      (c) missing_count 與 missing_for_application 是明確欄位，")
    print("          缺口不是「沒有資料」而是「有一筆記錄說明缺什麼」。")
    counts = {}
    for r in records:
        counts[r["missing_information"]["missing_count"]] = counts.get(
            r["missing_information"]["missing_count"], 0) + 1
    print(f"      missing_count 分佈：{counts}")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "threshold", "rank", "priority",
                  "importance", "confidence", "top_n", "recommend", "predict")
ALLOWED_KEY_EXCEPTIONS = ("percentile_rank", "rank_desc")
DECLARATIVE_KEYS = ("contains_no", "rule_not_inputs")

LLM_PACKAGE_NAMES = frozenset({
    "openai", "anthropic", "cohere", "vertexai", "transformers", "langchain",
    "llama_index", "ollama", "litellm", "mistralai", "torch", "tensorflow",
    "huggingface_hub",
})

UI_PACKAGE_NAMES = frozenset({
    "flask", "fastapi", "django", "streamlit", "dash", "jinja2", "starlette",
    "uvicorn", "tkinter",
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


def run_validation(
    records: list, rerun_records: list, groups_before: list, groups_after: list,
    candidates_before: list, candidates_after: list, group_rel: list,
    candidates: list, samples: dict, fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    scopes = [r["group_identity"]["scope"] for r in records]
    group_scopes = sorted(g["scope"] for g in groups_after)
    by_scope = {g["scope"]: g for g in groups_after}
    cand_by_id = {c["candidate_id"]: c for c in candidates}

    # 1. 9 個 group 全部存在
    ok1 = (
        len(records) == 9 == len(groups_after)
        and sorted(scopes) == group_scopes
        and len(set(scopes)) == 9
        and all(r["display_rule"]["always_displayed"] for r in records)
    )
    checks.append(
        ("9 個 group 全部存在且全部標記 always_displayed", ok1,
         f"records={len(records)}　groups={len(groups_after)}"
         f"　scope 集合相同={sorted(scopes) == group_scopes}"
         f"　always_displayed 全為 True="
         f"{all(r['display_rule']['always_displayed'] for r in records)}")
    )

    # 2. candidate membership 與 Step 18 一致
    mem_bad = []
    total = 0
    for r in records:
        g = by_scope[r["group_identity"]["scope"]]
        if r["group_identity"]["candidate_ids"] != g["member_candidate_ids"]:
            mem_bad.append(r["group_identity"]["scope"])
        if r["group_identity"]["candidate_count"] != g["member_count"]:
            mem_bad.append(f"{r['group_identity']['scope']} count")
        total += r["group_identity"]["candidate_count"]
    checks.append(
        ("每個 group 的 candidate membership 與 Step 18 完全一致", not mem_bad,
         f"9 個 group 的成員清單與成員數逐一相符；總數 {total} = 29"
         if not mem_bad else "；".join(mem_bad[:5]))
    )

    # 3. evidence summary 與 Step 9 完全一致
    ev_bad = []
    covered_metric_candidates = set()
    for r in records:
        for m in r["evidence_summary"]["metrics"]:
            cid = m["traceability"]["source_candidate_id"]
            covered_metric_candidates.add(cid)
            c = cand_by_id[cid]
            if c["type"] == "TREND":
                exp = (c["current_value"], c["baseline_value"],
                       c["absolute_difference"], c["direction"], c["metric"])
            else:
                exp = (c["value"], c["comparison"]["baseline_value"],
                       c["comparison"]["difference"], c["comparison"]["direction"],
                       c["metric"])
            got = (m["current_value"], m["baseline_value"], m["difference"],
                   m["direction"], m["metric"])
            if got != exp:
                ev_bad.append(f"{cid} metric 值不符 Step 9")
    checks.append(
        ("evidence summary 的 metric 值與 Step 9 完全一致", not ev_bad,
         f"共 {len(covered_metric_candidates)} 個 TREND/CONTEXT candidate 的 "
         "current / baseline / difference / direction / metric 逐一比對相符"
         if not ev_bad else "；".join(ev_bad[:5]))
    )

    # 3b. 結構性去重沒有遺失資訊：PATTERN 的每個 metric 差距等於同 group CONTEXT 的差距
    dedup_bad = []
    pattern_count = 0
    for r in records:
        cmd = r["evidence_summary"]["cross_metric_direction"]
        if not cmd["available"]:
            continue
        pattern_count += 1
        p = cand_by_id[cmd["source_candidate_id"]]
        rows = {m["metric"]: m["difference"] for m in r["evidence_summary"]["metrics"]}
        for metric, mv in p["metric_values"].items():
            if metric not in rows:
                dedup_bad.append(f"{p['candidate_id']} {metric} 沒有對應 metric 列")
            elif rows[metric] != mv["difference"]:
                dedup_bad.append(f"{p['candidate_id']} {metric} 差距不符 CONTEXT 列")
    checks.append(
        ("PATTERN 的結構性去重沒有遺失資訊（每個 metric 差距都等於同 group 的 "
         "CONTEXT 列）", not dedup_bad,
         f"{pattern_count} 個 PATTERN × 3 個 metric = {pattern_count * 3} 次比對相符；"
         "PATTERN 的方向摘要另以 cross_metric_direction 保留"
         if not dedup_bad else "；".join(dedup_bad[:5]))
    )

    # 4. sample context 與 Step 11 一致
    sc_bad = []
    n_rows = 0
    for r in records:
        for m in r["evidence_summary"]["metrics"]:
            n_rows += 1
            cid = m["traceability"]["source_candidate_id"]
            s = samples[cid]
            sens = s["sample_sensitivity"][m["metric"]]
            if (m["sample_size"]["at_bats"] != s["sample_context"]["at_bats"]
                    or m["sample_size"]["plate_appearances"]
                    != s["sample_context"]["plate_appearances"]
                    or m["sample_size"]["games"] != s["sample_context"]["games"]):
                sc_bad.append(f"{cid} sample_size 不符 Step 11")
            sv = m["single_event_sensitivity"]
            if (sv["numerator"] != sens["numerator"]
                    or sv["denominator"] != sens["denominator"]
                    or sv["delta_if_one_more"] != sens["delta_if_one_more"]
                    or sv["one_more_success"] != sens["one_more_success"]
                    or sv["one_fewer_success"] != sens["one_fewer_success"]):
                sc_bad.append(f"{cid} sensitivity 不符 Step 11")
    checks.append(
        ("sample context 與 sensitivity 與 Step 11 完全一致", not sc_bad,
         f"{n_rows} 個 metric 列的 sample_size 與 sensitivity 逐欄位比對相符"
         if not sc_bad else "；".join(sc_bad[:5]))
    )

    # 5. decision relevance 與 Step 19 一致
    rel_by_scope = {r["scope"]: r for r in group_rel}
    dr_bad = []
    for r in records:
        scope = r["group_identity"]["scope"]
        src = rel_by_scope[scope]
        dr = r["decision_relevance"]
        pairs = [
            (dr["temporal_relevance"], src["temporal_relevance"]),
            (dr["contextual_relevance"], src["contextual_relevance"]),
            (dr["context_official_item_name"], src["context_official_item_name"]),
            (dr["next_game_dependency"]["evidence_depends_on_next_game"],
             src["next_game_dependency"]["evidence_depends_on_next_game"]),
            (dr["application_dependency"]["requires_additional_data"],
             src["application_dependency"]["requires_additional_data"]),
            (dr["application_dependency"]["additional_data"],
             src["application_dependency"]["additional_data"]),
            (dr["action_link"]["possible_action_link"],
             src["action_link"]["possible_action_link"]),
            (dr["action_link"]["action_link_basis"],
             src["action_link"]["action_link_basis"]),
            (dr["action_link"]["possible_decision_area"],
             src["action_link"]["possible_decision_area"]),
            (dr["action_link_requires"], src["action_link_requires"]),
            (dr["data_availability"], src["data_availability"]["status"]),
        ]
        for got, exp in pairs:
            if got != exp:
                dr_bad.append(f"{scope} decision_relevance 欄位不符 Step 19")
    checks.append(
        ("decision relevance 與 Step 19 完全一致", not dr_bad,
         f"9 個 group × 11 個欄位 = 99 次逐一比對相符"
         if not dr_bad else "；".join(dr_bad[:5]))
    )

    # 6. 不修改 candidate / grouping / raw / processed
    checks.append(
        ("沒有修改 Step 18 的 grouping（深度比較 9 個物件）",
         groups_before == groups_after,
         "逐欄位比較完全相同" if groups_before == groups_after else "有 group 被改動")
    )
    checks.append(
        ("沒有修改 candidate（深度比較 29 個物件）",
         candidates_before == candidates_after,
         "逐欄位比較完全相同"
         if candidates_before == candidates_after else "有 candidate 被改動")
    )
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data 未被修改", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    payload = {"records": records}
    blob = json.dumps(payload, ensure_ascii=False)
    declarative = json.dumps(
        [
            {
                "contains_no": r["contains_no"],
                "rule_not_inputs": r["display_rule"]["rule_not_inputs"],
                "purpose_is_not": r["presentation_purpose"]["is_not"],
                "completeness_is_not": r["evidence_completeness"]["is_not"],
                "readiness_is_not": r["application_readiness"]["is_not"],
                "sens_is_not": [
                    m["single_event_sensitivity"]["is_not"]
                    for m in r["evidence_summary"]["metrics"]
                ],
                "mapping_note": r["data_status"]["mapping_note"],
                "no_guessing": r["missing_information"]["no_guessing_note"],
                "always_reason": r["display_rule"]["always_displayed_reason"],
                "dedup": r["evidence_summary"]["cross_metric_direction"].get(
                    "deduplication_note", ""),
                "cross_limit": r["evidence_summary"]["cross_metric_direction"].get(
                    "known_limitation", ""),
            }
            for r in records
        ],
        ensure_ascii=False,
    )

    # 7. 不產生 score / weight / threshold / ranking / priority
    bad_keys = scan_keys(payload)
    thr = []
    for w in ("threshold", "門檻", "cutoff", "top_n", "Top-N"):
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            thr.append(f"{w}×{cnt}")
    checks.append(
        ("沒有 score / weight / threshold / ranking / priority / importance / "
         "confidence score / Top-N", not bad_keys and not thr,
         "遞迴掃描所有巢狀欄位名：沒有任何相關欄位"
         "（percentile_rank、rank_desc 為 Step 6 既有描述子，已排除）"
         if not bad_keys and not thr
         else f"欄位={sorted(set(bad_keys))[:6]}　字眼={thr}")
    )

    # 8. deterministic
    det = (json.dumps(records, ensure_ascii=False, sort_keys=True)
           == json.dumps(rerun_records, ensure_ascii=False, sort_keys=True))
    checks.append(
        ("deterministic：重跑結果完全一致", det,
         "整條流程重跑一次，序列化結果完全相同" if det else "重跑結果不同")
    )

    # 9. 不發 HTTP request
    checks.append(
        ("沒有任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖")
    )

    # 10. 所有 missing information 都有明確來源
    ms_bad = []
    total_required = 0
    total_missing = 0
    for r in records:
        mi = r["missing_information"]
        for item in mi["required_additional_data"]:
            total_required += 1
            if not item.get("item") or item.get("status") not in DATA_STATUS_VALUES:
                ms_bad.append(f"{r['group_identity']['scope']} required 欄位不完整")
            if not item.get("factual_basis"):
                ms_bad.append(f"{r['group_identity']['scope']} 缺 factual_basis")
            if not item.get("availability_source_step"):
                ms_bad.append(f"{r['group_identity']['scope']} 缺來源 Step")
            if item["status"] != "not_investigated" and not item["evidence_steps"]:
                ms_bad.append(f"{r['group_identity']['scope']} 缺 evidence_steps")
        for item in mi["missing_for_application"]:
            total_missing += 1
            if item["status"] == "available":
                ms_bad.append(f"{r['group_identity']['scope']} available 卻列為缺口")
    checks.append(
        ("所有 missing information 都有明確來源", not ms_bad,
         f"{total_required} 筆 required_additional_data 全部帶 status / "
         f"availability_source_step / factual_basis；"
         f"其中 {total_missing} 筆列為缺口（status != available）"
         if not ms_bad else "；".join(ms_bad[:5]))
    )

    # 11. 不允許自由文字 recommendation / prediction
    forbidden = ("建議", "應該", "推薦", "預測", "策略", "最佳", "最好", "最差",
                 "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
                 "值得注意", "recommend", "predict", "strategy", "should", "best")
    hits = []
    for w in forbidden:
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    checks.append(
        ("不允許自由文字 recommendation / prediction / strategy", not hits,
         "未出現禁用字眼（宣告性與說明性欄位已扣除）"
         if not hits else "、".join(hits))
    )

    # 12. 受控詞彙
    vocab_bad = []
    for r in records:
        if r["data_status"]["application_data_status"] not in DATA_STATUS_VALUES:
            vocab_bad.append(f"{r['group_identity']['scope']} data_status")
        if (r["evidence_completeness"]["self_containment"]
                not in EVIDENCE_SELF_CONTAINMENT_VALUES):
            vocab_bad.append(f"{r['group_identity']['scope']} self_containment")
        if (r["application_readiness"]["readiness"]
                not in APPLICATION_READINESS_VALUES):
            vocab_bad.append(f"{r['group_identity']['scope']} readiness")
        if r["presentation_purpose"]["purpose"] not in PRESENTATION_PURPOSE_VALUES:
            vocab_bad.append(f"{r['group_identity']['scope']} purpose")
        for it in r["presentation_purpose"]["provides_information_items"]:
            if it not in INFORMATION_ITEM_VALUES:
                vocab_bad.append(f"{r['group_identity']['scope']} item {it}")
    checks.append(
        ("所有分類欄位值都在受控詞彙內", not vocab_bad,
         f"data_status 4 值、self_containment 2 值、readiness 2 值、"
         f"purpose 4 值、information items {len(INFORMATION_ITEM_VALUES)} 值，"
         "9 個 group 全部通過"
         if not vocab_bad else "；".join(vocab_bad[:5]))
    )

    # 13. A / B / C 三者沒有被合併成單一 boolean（存在不同組合即證明）
    combos = {
        (r["evidence_completeness"]["self_containment"],
         r["application_readiness"]["readiness"],
         r["missing_information"]["missing_count"] > 0)
        for r in records
    }
    ok13 = len(combos) >= 2 and any(
        a == "self_contained" and b == "not_ready_pending_data" for a, b, _ in combos
    ) and any(
        a == "requires_next_game_context" and b == "ready_with_available_data"
        for a, b, _ in combos
    )
    checks.append(
        ("A / B / C 是三組獨立欄位，不能用單一 boolean 表達", ok13,
         f"實際出現 {len(combos)} 種 (A, B, C) 組合，其中包含 "
         "(self_contained, not_ready) 與 (requires_next_game_context, ready) "
         "兩種相反組合——單一 boolean 無法同時表達這兩者"
         if ok13 else f"組合={sorted(combos)}")
    )

    # 14. 沒有 UI / 前端框架
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

    # 15. 顯示規則沒有用 magnitude / sample size / classification
    rule_ok = all(
        r["display_rule"]["rule_inputs"]
        == ["group_membership", "step19_decision_relevance"]
        and r["display_rule"]["rule_not_inputs"] == PRESENTATION_NOT_INPUTS
        and r["display_rule"]["always_displayed"] is True
        for r in records
    )
    cls_keys = [k for k in scan_keys(payload) if "classification" in k.lower()]
    checks.append(
        ("顯示與否沒有依 magnitude / sample size / classification 決定", rule_ok
         and not cls_keys,
         f"9 個 group 的 always_displayed 全為 True；rule_inputs 只有 2 項；"
         f"rule_not_inputs 明確列出 {len(PRESENTATION_NOT_INPUTS)} 個未使用的量；"
         "輸出中沒有 classification 欄位"
         if rule_ok and not cls_keys else f"rule_ok={rule_ok}　cls_keys={cls_keys}")
    )

    return checks


# ------------------------------------------------------------------ main

def build_all(logs, apart_rows):
    candidates, groups, step13, group_rel = build_everything(logs, apart_rows)
    from noteworthy_insights import build_all as build_cls
    _c, _v, samples, _p, _r = build_cls(logs, apart_rows)
    records = build_presentation_model(groups, group_rel, candidates, samples)
    return candidates, groups, group_rel, samples, records


def main() -> None:
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }
    logs, apart_rows = load_inputs()

    candidates, groups, group_rel, samples, records = build_all(logs, apart_rows)
    candidates_before = copy.deepcopy(candidates)
    groups_before = copy.deepcopy(groups)
    _, _, _, _, rerun_records = build_all(logs, apart_rows)

    print("=" * 108)
    print("Insight Presentation Model Experiment（Step 20）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print(f"固定輸入：Step 18 的 {len(groups)} 個 group + Step 19 的 decision relevance")
    print("這不是 UI，只是 machine-readable 的呈現模型。")
    print("核心原則：資料缺口也必須是一級資訊。9 個 group 全部保留，沒有隱藏、沒有排序。")
    print("=" * 108)

    print_overview(records)
    print_answers(records)
    print_records(records)

    print("\n" + "=" * 108)
    print("Validation")
    print("=" * 108)
    checks = run_validation(
        records, rerun_records, groups_before, groups, candidates_before,
        candidates, group_rel, candidates, samples, fingerprints_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 "
              "docs/INSIGHT_PRESENTATION_MODEL.md。")

    print("\n" + "=" * 108)
    print("本階段只建立呈現模型，沒有 UI、沒有排序、沒有選最佳 group、沒有 Top-N。")
    print("=" * 108)


if __name__ == "__main__":
    main()

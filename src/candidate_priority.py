"""Candidate Priority 結構設計實驗（Step 10）。

它做什麼：為 Step 9 的 29 個 candidate 建立**結構性**的優先度描述——
tier 分組、粒度標記、可靠性描述子、幅度描述子。

它**不**做什麼：
    - 不產生 final_score / importance_score / reliability_score
    - 不設定任何 weight
    - 不設定任何 threshold
    - 不在同一個 tier 內排名
    - 不做統計顯著性宣稱
    - 不產生自然語言結論
    - 不使用 LLM
    - 不發任何 HTTP 請求
    - **不修改 Step 9 的 candidate 數字**（以 sidecar 記錄的方式避免碰到原值）

設計上的關鍵選擇：priority 記錄是**獨立的 sidecar**，用 candidate_id 關聯，
不寫回 candidate 物件。這樣「原始 evidence 沒有被改動」可以直接用深度比較驗證。

tier 的性質：
    tier 是 **provisional_product_priority**（暫定的產品假設）。
    它**不是** statistical importance、不是 evidence strength、不是顯著性、不是預測。

用法：
    python src/candidate_priority.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 匯入 Step 9。注意：candidate_insights 在 import 時就會安裝網路封鎖 guard。
from candidate_insights import (  # noqa: E402
    APART_CACHE_PATH,
    PLAYER_LOG_PATH,
    ROOT,
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

# ------------------------------------------------------------------ 設計常數

# Part 1 / Part 5：candidate type -> tier。這是目前的產品假設，不是統計結論。
PROVISIONAL_PRODUCT_PRIORITY = {
    "TREND": 1,
    "MULTI_METRIC_PATTERN": 2,
    "CONTEXT": 3,
}

PRIORITY_BASIS = "provisional_product_priority"

# 明確記錄 tier 不代表什麼，避免下游誤讀
PRIORITY_IS_NOT = [
    "statistical_importance",
    "statistical_significance",
    "evidence_strength",
    "importance",
    "prediction",
    "final_rank",
]

TIER_RATIONALE = {
    1: "TREND 直接對應「球員目前近況」這個 MVP 問題，且具備時間維度與滾動分布。"
       "這是產品層面的假設：分析人員最先想知道的是近況。",
    2: "MULTI_METRIC_PATTERN 由三個指標同方向構成，資訊密度較高，"
       "但沒有時間維度。放在 TREND 之後是產品假設，不是統計判斷。",
    3: "CONTEXT 是單一指標的球季累計切分，數量最多（21 個），"
       "且沒有時間維度與滾動分布。放最後是產品假設，不代表資訊價值低。",
}

# Part 4：粒度標記
GRANULARITY_BY_TYPE = {
    "TREND": "recent_games",
    "MULTI_METRIC_PATTERN": "season_cumulative",
    "CONTEXT": "season_cumulative",
}

GRANULARITY_NOTE = (
    "不同 granularity 的 magnitude 不可直接比較：recent_games 的分母是最近 N 場出賽，"
    "season_cumulative 的分母是整季。兩者的基準範圍不同。"
)


# ------------------------------------------------------------------ 描述子

def build_reliability(candidate: dict) -> dict:
    """Part 2：原始 reliability descriptors。全部為原始值，未加權、無合成分數。"""
    ctype = candidate["type"]

    if ctype == "TREND":
        metric_count = 1
        consistency_count = None
        completeness = {
            "metrics_available": ["batting_average", "slugging_percentage"],
            "metrics_unavailable": ["on_base_percentage"],
            "metrics_unavailable_reason":
                "processed data 未收逐場犧牲飛球，OBP 無法按窗口計算",
            "fields_null": [],
            "has_game_level_traceability": True,
            "has_date_range": True,
            "has_rolling_distribution": True,
        }
    elif ctype == "CONTEXT":
        metric_count = 1
        consistency_count = None
        completeness = {
            "metrics_available": [
                "batting_average", "on_base_percentage", "slugging_percentage",
            ],
            "metrics_unavailable": [],
            "fields_null": ["runs"],
            "fields_null_reason": "官方分項 response 沒有得分欄位",
            "has_game_level_traceability": False,
            "has_date_range": False,
            "has_rolling_distribution": False,
        }
    else:  # MULTI_METRIC_PATTERN
        metric_count = len(candidate["metrics"])
        consistency_count = candidate["consistency_count"]
        completeness = {
            "metrics_available": list(candidate["metrics"]),
            "metrics_unavailable": [],
            "fields_null": [],
            "has_game_level_traceability": False,
            "has_date_range": False,
            "has_rolling_distribution": False,
        }

    return {
        "_note": "原始描述子，未加權，沒有 reliability_score",
        "sample_size_at_bats": candidate["at_bats"],
        "plate_appearances": candidate["plate_appearances"],
        "data_completeness": completeness,
        "metric_count": metric_count,
        "consistency_count": consistency_count,
    }


def build_magnitude(candidate: dict) -> dict:
    """Part 3：幅度描述子。依 candidate 類型保留不同欄位，不建立統一 score。"""
    ctype = candidate["type"]
    out: dict = {
        "_note": "依 candidate 類型各自保留原始幅度欄位，刻意不統一成單一數值",
        "candidate_type": ctype,
    }

    if ctype == "TREND":
        rp = candidate["rolling_percentile"]
        out.update(
            {
                "absolute_difference": candidate["absolute_difference"],
                "absolute_difference_magnitude":
                    candidate["absolute_difference_magnitude"],
                "direction": candidate["direction"],
                "percentile_rank": None if rp is None else rp["percentile_rank"],
                "percentile_strict": None if rp is None else rp["percentile_strict"],
                "percentile_distribution_n": None if rp is None else rp["distribution_n"],
                "percentile_definition":
                    None if rp is None else rp["definition"],
            }
        )
    elif ctype == "CONTEXT":
        cmp_ = candidate["comparison"]
        out.update(
            {
                "difference_from_season": cmp_["difference"],
                "absolute_difference": cmp_["difference_magnitude"],
                "direction": cmp_["direction"],
                "percentile_rank": None,
                "percentile_unavailable_reason":
                    "官方分項沒有時間維度，無法建立滾動分布",
            }
        )
    else:  # MULTI_METRIC_PATTERN
        out.update(
            {
                "difference_from_season": {
                    metric: mv["difference"]
                    for metric, mv in candidate["metric_values"].items()
                },
                "consistency_count": candidate["consistency_count"],
                "total_metrics": candidate["total_metrics"],
                "direction": candidate["direction"],
                "percentile_rank": None,
                "percentile_unavailable_reason":
                    "官方分項沒有時間維度，無法建立滾動分布",
            }
        )
    return out


def build_priority_record(candidate: dict) -> dict:
    """為一個 candidate 產生獨立的 priority sidecar，不修改 candidate 本身。"""
    ctype = candidate["type"]
    tier = PROVISIONAL_PRODUCT_PRIORITY[ctype]
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_type": ctype,
        # Part 5
        "priority_tier": tier,
        "priority_basis": PRIORITY_BASIS,
        "priority_is_not": list(PRIORITY_IS_NOT),
        "priority_rationale": TIER_RATIONALE[tier],
        "tier_assignment_rule": "由 candidate type 直接決定，不看數值、不看樣本量",
        # Part 6
        "intra_tier_rank": None,
        "intra_tier_rank_note":
            "本階段刻意不在同一 tier 內排名。同 tier 內只有分組，沒有先後。",
        # Part 4
        "granularity": GRANULARITY_BY_TYPE[ctype],
        "cross_granularity_comparison_allowed": False,
        "granularity_note": GRANULARITY_NOTE,
        # Part 2 / Part 3
        "reliability_descriptors": build_reliability(candidate),
        "magnitude_descriptors": build_magnitude(candidate),
        # 明確聲明沒有的東西
        "contains_no": [
            "final_score", "importance_score", "reliability_score",
            "magnitude_score", "weight", "threshold",
            "statistical_significance_claim", "natural_language_conclusion",
        ],
    }


# ------------------------------------------------------------------ 輸出

def print_tier_summary(records: list) -> None:
    by_tier: dict[int, list] = {}
    for r in records:
        by_tier.setdefault(r["priority_tier"], []).append(r)

    print("\n" + "=" * 92)
    print("Tier Summary（provisional_product_priority）")
    print("=" * 92)
    print(f"  {'tier':<6} {'candidate_type':<22} {'granularity':<20} {'count':<6}")
    for tier in sorted(by_tier):
        group = by_tier[tier]
        ctypes = sorted({r["candidate_type"] for r in group})
        grans = sorted({r["granularity"] for r in group})
        print(f"  {tier:<6} {', '.join(ctypes):<22} {', '.join(grans):<20} "
              f"{len(group):<6}")
    print(f"\n  總計 {len(records)} 個 candidate")
    print("\n  tier 只是暫定的產品假設。它不是統計重要性、不是證據強度、不是顯著性、")
    print("  不是預測，也不是最終排名。")


def print_tier_detail(records: list) -> None:
    by_tier: dict[int, list] = {}
    for r in records:
        by_tier.setdefault(r["priority_tier"], []).append(r)

    for tier in sorted(by_tier):
        group = sorted(by_tier[tier], key=lambda r: r["candidate_id"])
        print("\n" + "=" * 92)
        print(f"Tier {tier} — {group[0]['candidate_type']}"
              f"（{len(group)} 個，granularity = {group[0]['granularity']}）")
        print("=" * 92)
        print(f"  依據：{group[0]['priority_rationale']}")
        print("  以下排列順序為 candidate_id 字典序，**不代表任何優先高低**"
              "（同 tier 內不排名）。")
        for r in group:
            rel = r["reliability_descriptors"]
            mag = r["magnitude_descriptors"]
            print(f"\n  - {r['candidate_id']}")
            print(f"      tier={r['priority_tier']}  basis={r['priority_basis']}"
                  f"  intra_tier_rank={r['intra_tier_rank']}")
            print(f"      granularity={r['granularity']}"
                  f"  cross_granularity_comparison_allowed="
                  f"{r['cross_granularity_comparison_allowed']}")
            print(f"      reliability: AB={rel['sample_size_at_bats']}"
                  f"  PA={rel['plate_appearances']}"
                  f"  metric_count={rel['metric_count']}"
                  f"  consistency_count={rel['consistency_count']}")
            dc = rel["data_completeness"]
            print(f"      completeness: metrics_available="
                  f"{len(dc['metrics_available'])}"
                  f"  metrics_unavailable={dc['metrics_unavailable']}"
                  f"  fields_null={dc['fields_null']}")
            print(f"                    game_level_traceability="
                  f"{dc['has_game_level_traceability']}"
                  f"  rolling_distribution={dc['has_rolling_distribution']}")
            if r["candidate_type"] == "TREND":
                print(f"      magnitude: abs_diff={mag['absolute_difference']:+.8f}"
                      f"  direction={mag['direction']}"
                      f"  percentile_rank={mag['percentile_rank']:.4f}"
                      f"  (n={mag['percentile_distribution_n']})")
            elif r["candidate_type"] == "CONTEXT":
                print(f"      magnitude: diff_from_season="
                      f"{mag['difference_from_season']:+.8f}"
                      f"  abs_diff={mag['absolute_difference']:.8f}"
                      f"  direction={mag['direction']}"
                      f"  percentile_rank={mag['percentile_rank']}")
            else:
                diffs = "  ".join(
                    f"{m.split('_')[0]}={v:+.8f}"
                    for m, v in mag["difference_from_season"].items()
                )
                print(f"      magnitude: consistency="
                      f"{mag['consistency_count']}/{mag['total_metrics']}"
                      f"  direction={mag['direction']}"
                      f"  percentile_rank={mag['percentile_rank']}")
                print(f"                 diff_from_season: {diffs}")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_SCORE_KEYS = (
    "final_score", "score", "importance", "priority_score", "weight",
    "weighted", "reliability_score", "magnitude_score", "rank_value",
)

FORBIDDEN_SIGNIFICANCE_WORDS = (
    "statistically significant", "statistical significance", "p-value", "p value",
    "confidence interval", "significant", "統計顯著", "顯著性", "顯著", "信賴區間",
    "信心水準",
)

FORBIDDEN_CONCLUSION_WORDS = (
    "strength", "weakness", "advantage", "disadvantage",
    "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
    "建議", "應該", "預測未來", "值得注意", "表現很好", "表現不佳",
)


def run_validation(
    candidates_before: list,
    candidates_after: list,
    records: list,
    fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    n = len(candidates_after)
    rec_by_id = {r["candidate_id"]: r for r in records}

    # 1. 全部 candidate 都有 tier
    missing = [c["candidate_id"] for c in candidates_after
               if c["candidate_id"] not in rec_by_id]
    no_tier = [r["candidate_id"] for r in records
               if r.get("priority_tier") not in (1, 2, 3)]
    checks.append(
        (f"{n} 個 candidate 全部都有 priority_tier",
         not missing and not no_tier and len(records) == n,
         f"records={len(records)}　candidates={n}"
         + ("" if not missing else f"　缺 tier：{missing}")
         + ("" if not no_tier else f"　tier 非法：{no_tier}"))
    )

    # 2 / 3 / 4. 各類型的 tier 正確
    for ctype, expected_tier, expected_count in (
        ("TREND", 1, 4), ("MULTI_METRIC_PATTERN", 2, 4), ("CONTEXT", 3, 21),
    ):
        group = [r for r in records if r["candidate_type"] == ctype]
        ok = (
            len(group) == expected_count
            and all(r["priority_tier"] == expected_tier for r in group)
        )
        checks.append(
            (f"{ctype} 全部為 tier {expected_tier}", ok,
             f"數量 {len(group)}（期望 {expected_count}）"
             f"　tier 值 {sorted({r['priority_tier'] for r in group})}")
        )

    blob = json.dumps(records, ensure_ascii=False)
    # priority_is_not 與 contains_no 是「明確宣告不含這些東西」的清單。
    # 字眼掃描必須把這兩個欄位的內容扣掉，否則會把否定宣告誤判成違規。
    declarative_blob = json.dumps(
        [
            {"priority_is_not": r["priority_is_not"], "contains_no": r["contains_no"]}
            for r in records
        ],
        ensure_ascii=False,
    )

    # 5 / 6. 沒有 final_score、沒有 weight
    def scan_keys(obj, path="") -> list:
        found = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower()
                for bad in FORBIDDEN_SCORE_KEYS:
                    # contains_no / priority_is_not 是「宣告沒有這些東西」的清單，需排除
                    if bad in kl and k not in ("contains_no", "priority_is_not"):
                        found.append(f"{path}.{k}")
                found += scan_keys(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                found += scan_keys(v, f"{path}[{i}]")
        return found

    score_keys = scan_keys(records)
    checks.append(
        ("沒有 final_score / importance_score / 任何 score 欄位", not score_keys,
         "priority 記錄中沒有任何分數欄位" if not score_keys
         else "；".join(sorted(set(score_keys))[:8]))
    )
    weight_keys = [k for k in score_keys if "weight" in k.lower()]
    checks.append(
        ("沒有 weight 欄位", not weight_keys,
         "沒有任何權重欄位" if not weight_keys else "；".join(weight_keys))
    )

    # 7. 沒有 threshold
    #    以「產出數量」證明：全部 29 個 candidate 都被分配 tier，沒有任何被過濾掉。
    #    另外檢查 tier 指派規則不依賴任何數值。
    all_assigned = len(records) == n
    rule_ok = all(
        r["tier_assignment_rule"] == "由 candidate type 直接決定，不看數值、不看樣本量"
        for r in records
    )
    # 字眼掃描同樣扣除 contains_no 中的否定宣告
    threshold_words = []
    for w in ("threshold", "門檻", "cutoff", "minimum_", "min_at_bats"):
        count = blob.count(w) - declarative_blob.count(w)
        if count > 0:
            threshold_words.append(f"{w}×{count}")
    checks.append(
        ("沒有 threshold：全部 candidate 都被分配 tier，沒有任何項目被數值條件篩掉",
         all_assigned and rule_ok and not threshold_words,
         f"{len(records)}/{n} 全部分配　tier 指派僅依 candidate type，不看數值"
         + ("" if not threshold_words else f"　可疑字眼 {threshold_words}"))
    )

    # 8. 沒有統計顯著性宣稱
    sig_hits = []
    lower_blob = blob.lower()
    lower_declarative = declarative_blob.lower()
    for word in FORBIDDEN_SIGNIFICANCE_WORDS:
        w = word.lower()
        count = lower_blob.count(w) - lower_declarative.count(w)
        if count > 0:
            sig_hits.append(f"{word}×{count}")
    checks.append(
        ("沒有統計顯著性宣稱", not sig_hits,
         "未出現顯著性相關字眼（priority_is_not / contains_no 中的否定宣告已扣除）"
         if not sig_hits else "、".join(sig_hits))
    )

    # 9. 沒有自然語言結論
    concl_hits = []
    for word in FORBIDDEN_CONCLUSION_WORDS:
        count = blob.count(word) - declarative_blob.count(word)
        if count > 0:
            concl_hits.append(f"{word}×{count}")
    checks.append(
        ("沒有自然語言結論或價值判斷字眼", not concl_hits,
         "未出現禁用字眼（priority_is_not / contains_no 中的否定宣告已扣除，"
         "例如 evidence_strength 是宣告「不是證據強度」）"
         if not concl_hits else "、".join(concl_hits))
    )

    # 10. 原始 candidate evidence 數字沒有改變（深度比較）
    same = candidates_before == candidates_after
    diff_ids = []
    if not same:
        before_by_id = {c["candidate_id"]: c for c in candidates_before}
        for c in candidates_after:
            if before_by_id.get(c["candidate_id"]) != c:
                diff_ids.append(c["candidate_id"])
    checks.append(
        ("原始 candidate evidence 完全未被改動（深度比較 29 個物件）", same,
         "與 Step 9 產出逐欄位完全相同" if same else f"被改動：{diff_ids}")
    )

    # 額外：priority 記錄中的幅度數值必須與 candidate 原值相同（複製而非重算）
    copy_bad = []
    for c in candidates_after:
        r = rec_by_id[c["candidate_id"]]
        mag = r["magnitude_descriptors"]
        if c["type"] == "TREND":
            if mag["absolute_difference"] != c["absolute_difference"]:
                copy_bad.append(f"{c['candidate_id']} absolute_difference")
            if mag["percentile_rank"] != c["rolling_percentile"]["percentile_rank"]:
                copy_bad.append(f"{c['candidate_id']} percentile_rank")
        elif c["type"] == "CONTEXT":
            if mag["difference_from_season"] != c["comparison"]["difference"]:
                copy_bad.append(f"{c['candidate_id']} difference_from_season")
        else:
            for metric, mv in c["metric_values"].items():
                if mag["difference_from_season"][metric] != mv["difference"]:
                    copy_bad.append(f"{c['candidate_id']} {metric}")
        rel = r["reliability_descriptors"]
        if rel["sample_size_at_bats"] != c["at_bats"]:
            copy_bad.append(f"{c['candidate_id']} at_bats")
        if rel["plate_appearances"] != c["plate_appearances"]:
            copy_bad.append(f"{c['candidate_id']} plate_appearances")
    checks.append(
        ("priority 記錄中的數值為 candidate 原值的複製，未重算或修改", not copy_bad,
         "全部相符" if not copy_bad else "；".join(copy_bad[:8]))
    )

    # 11. granularity 正確
    gran_bad = []
    for c in candidates_after:
        r = rec_by_id[c["candidate_id"]]
        expected = GRANULARITY_BY_TYPE[c["type"]]
        if r["granularity"] != expected:
            gran_bad.append(f"{c['candidate_id']} = {r['granularity']}（期望 {expected}）")
        if r["cross_granularity_comparison_allowed"] is not False:
            gran_bad.append(f"{c['candidate_id']} 未禁止跨粒度比較")
    checks.append(
        ("granularity 標記正確且明確禁止跨粒度比較", not gran_bad,
         "TREND=recent_games（4 個）、PATTERN/CONTEXT=season_cumulative（25 個），"
         "全部 cross_granularity_comparison_allowed=False"
         if not gran_bad else "；".join(gran_bad))
    )

    # 12. 沒有 HTTP request
    checks.append(
        ("沒有任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖，"
         "資料全部來自本地檔案")
    )

    # 13. raw / processed source data 沒有被修改
    changed = []
    for path, before in fingerprints_before.items():
        if sha256_of(path) != before:
            changed.append(path.name)
    checks.append(
        ("raw / processed source data 未被修改", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    # 額外：同 tier 內沒有排名
    ranked = [r["candidate_id"] for r in records if r["intra_tier_rank"] is not None]
    checks.append(
        ("同 tier 內沒有排名（intra_tier_rank 全為 None）", not ranked,
         "29 個全部為 None" if not ranked else f"有排名：{ranked}")
    )

    return checks


# ------------------------------------------------------------------ main

def main() -> None:
    logs, apart_rows = load_inputs()
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }

    contexts = build_context_evidence(apart_rows)
    season = build_season_baseline(logs, contexts)
    trend, _ = build_trend_candidates(logs, season)
    context_cands = build_context_candidates(contexts, season)
    pattern, direction_log = build_pattern_candidates(contexts, season)
    candidates = trend + context_cands + pattern

    # 深拷貝一份原始狀態，最後用來證明 candidate 沒有被改動
    candidates_before = copy.deepcopy(candidates)

    print("=" * 92)
    print("Candidate Priority 結構設計實驗（Step 10）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print("這一步只設計優先度的**結構**，不產生任何分數、權重、門檻或排名。")
    print("=" * 92)
    print(f"\n輸入：Step 9 的 {len(candidates)} 個 candidate")
    print(f"  TREND {len(trend)}　MULTI_METRIC_PATTERN {len(pattern)}"
          f"　CONTEXT {len(context_cands)}")
    print("\ntier 對照（provisional_product_priority，非統計結論）：")
    for ctype, tier in PROVISIONAL_PRODUCT_PRIORITY.items():
        print(f"  tier {tier}  <-  {ctype}"
              f"　granularity = {GRANULARITY_BY_TYPE[ctype]}")

    records = [build_priority_record(c) for c in candidates]

    print_tier_summary(records)
    print_tier_detail(records)

    print("\n" + "=" * 92)
    print("Validation")
    print("=" * 92)
    checks = run_validation(candidates_before, candidates, records, fingerprints_before)
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/INSIGHT_RANKING_DESIGN.md。")

    print("\n" + "=" * 92)
    print("本階段沒有產生 final ranking。tier 只是分組，同 tier 內沒有先後。")
    print("=" * 92)


if __name__ == "__main__":
    main()

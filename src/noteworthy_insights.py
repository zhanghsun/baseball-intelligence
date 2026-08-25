"""Observation → Noteworthy 規則實驗（Step 17-7）。

它做什麼：把第一版「Observation → Noteworthy Insight」規則套用到 Step 9 的 29 個
candidate，觀察實際資料下的分類結果。

規則（第一版，由本次任務指示給定）：
    observation  : candidate 本身有直接 evidence 即可形成
    noteworthy   : 需同時具備三類 evidence
                     (1) 現象 evidence（phenomenon）
                     (2) 第二種**不同性質**的支持 evidence
                     (3) sample context
    not_eligible : 連直接 evidence 都沒有

它**不**做什麼：
    - 不設 AVG 差距門檻、不設 percentile 門檻、不設 AB 門檻
    - **不因樣本小而淘汰任何 candidate**
    - 不新增任何 statistical test
    - 不建立 score / weight / rank / threshold
    - 不使用 LLM、不發 HTTP 請求
    - 不產生最終自然語言結論
    - 不修改 candidate 原始 evidence（sidecar 設計）

「樣本大小不被用作淘汰條件」是可驗證的：
    `mutation_test_sample_independence()` 把每個 candidate 的 at_bats 換成 1 與 9999
    （在複本上），重跑分類，確認結果完全不變。

用法：
    python src/noteworthy_insights.py
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
from ranking_experiment import build_view  # noqa: E402

# ------------------------------------------------------------------ 規則定義

RULE_SET_ID = "R17-1"
RULE_SET_VERSION = "first_version"
RULE_SOURCE = (
    "本次任務指示（Step 17-7 prompt）中給定的第一版規則。"
    "本專案 docs/ 目前沒有 Step 15 / 16 / 17 的文件，"
    "因此規則來源記錄為指示本身，不引用不存在的文件。"
)

RULES = {
    "R17-1-OBS": (
        "candidate 本身有直接 evidence（現象 evidence 存在且值不為 null）"
        "即可形成 observation"
    ),
    "R17-1-NOTE": (
        "observation 成立，且同時具備「第二種不同性質的支持 evidence」"
        "與「sample context」時，標記為 noteworthy"
    ),
    "R17-1-NE": "連直接 evidence 都沒有（現象 evidence 缺失）時為 not_eligible",
}

CLASSIFICATION_VALUES = ("observation", "noteworthy", "not_eligible")

# 三類 evidence 的受控詞彙
EVIDENCE_CLASSES = ("phenomenon", "second_supporting", "sample_context")

PHENOMENON_TYPES = (
    "window_difference_from_season_baseline",
    "context_difference_from_season_baseline",
    "multi_metric_difference_from_season_baseline",
)

# 「第二種不同性質」的來源。只有這兩種，且都必須能追溯到 Step 6 / 9 / 11 的既有資料。
SECOND_EVIDENCE_TYPES = (
    "rolling_window_distribution_position",
    "cross_metric_direction_consistency",
)

SAMPLE_CONTEXT_TYPE = "sample_size_and_count_sensitivity"

ALLOWED_SOURCE_STEPS = ("Step 5", "Step 6", "Step 8", "Step 9", "Step 10", "Step 11")


# ------------------------------------------------------------------ 規則實作

def phenomenon_evidence(candidate: dict, view: dict) -> dict | None:
    """現象 evidence：candidate 自身相對於季累計基準的差距。"""
    ctype = candidate["type"]
    if ctype == "TREND":
        diff = candidate["absolute_difference"]
        if diff is None or candidate["current_value"] is None:
            return None
        return {
            "evidence_class": "phenomenon",
            "evidence_type": "window_difference_from_season_baseline",
            "statement_fields": {
                "metric": candidate["metric"],
                "window": candidate["window"]["name"],
                "current_value": candidate["current_value"],
                "baseline_value": candidate["baseline_value"],
                "difference": diff,
                "direction": candidate["direction"],
            },
            "provenance": {
                "source_step": "Step 9",
                "source_module": "src/candidate_insights.py",
                "source_field": "current_value / baseline_value / absolute_difference",
                "derivation": "direct_candidate_value",
            },
        }
    if ctype == "CONTEXT":
        cmp_ = candidate["comparison"]
        if cmp_["difference"] is None or candidate["value"] is None:
            return None
        return {
            "evidence_class": "phenomenon",
            "evidence_type": "context_difference_from_season_baseline",
            "statement_fields": {
                "metric": candidate["metric"],
                "context": candidate["context"]["code"],
                "official_item_name": candidate["context"]["official_item_name"],
                "current_value": candidate["value"],
                "baseline_value": cmp_["baseline_value"],
                "difference": cmp_["difference"],
                "direction": cmp_["direction"],
            },
            "provenance": {
                "source_step": "Step 9",
                "source_module": "src/candidate_insights.py",
                "source_field": "value / comparison.baseline_value / comparison.difference",
                "derivation": "direct_candidate_value",
            },
        }
    # MULTI_METRIC_PATTERN
    diffs = {m: mv["difference"] for m, mv in candidate["metric_values"].items()}
    if any(v is None for v in diffs.values()):
        return None
    return {
        "evidence_class": "phenomenon",
        "evidence_type": "multi_metric_difference_from_season_baseline",
        "statement_fields": {
            "context": candidate["context"]["code"],
            "official_item_name": candidate["context"]["official_item_name"],
            "metrics": list(candidate["metrics"]),
            "differences": diffs,
            "direction": candidate["direction"],
        },
        "provenance": {
            "source_step": "Step 9",
            "source_module": "src/candidate_insights.py",
            "source_field": "metric_values[].value / .baseline_value / .difference",
            "derivation": "direct_candidate_value",
        },
    }


def second_supporting_evidence(
    candidate: dict, view: dict, pattern_by_context: dict
) -> dict | None:
    """第二種**不同性質**的支持 evidence。

    只有兩種來源，兩者都必須追溯到既有資料：

    1. rolling_window_distribution_position
       該窗口值在同尺寸滾動窗口分布中的位置（Step 6 建立、Step 9 記錄）。
       性質與「差距」不同：它是分布內的相對位置，不是與單一基準的差。
       只有 TREND 有（CONTEXT / PATTERN 的 percentile 為 null，Step 8 已記錄原因）。

    2. cross_metric_direction_consistency
       同一 context 中 AVG / OBP / SLG 三個指標與季累計比較的方向是否一致
       （Step 9 的 MULTI_METRIC_PATTERN）。
       性質與「單一指標的差距」不同：它是跨指標的方向一致性。

    找不到時回傳 None。**不虛構、不補值。**
    """
    ctype = candidate["type"]

    if ctype == "TREND":
        rp = candidate["rolling_percentile"]
        if rp is None or rp.get("percentile_rank") is None:
            return None
        return {
            "evidence_class": "second_supporting",
            "evidence_type": "rolling_window_distribution_position",
            "different_in_kind_from_phenomenon": (
                "現象 evidence 是「與單一季累計基準的差」；"
                "本項是「在同尺寸滾動窗口分布中的相對位置」，性質不同"
            ),
            "statement_fields": {
                "window_size": rp["window_size"],
                "distribution_n": rp["distribution_n"],
                "rank_desc": rp["rank_desc"],
                "count_below": rp["count_below"],
                "count_equal": rp["count_equal"],
                "count_above": rp["count_above"],
                "percentile_rank": rp["percentile_rank"],
                "percentile_strict": rp["percentile_strict"],
                "percentile_definition": rp["definition"],
            },
            "provenance": {
                "source_step": "Step 6",
                "source_module": "src/rolling_baseline.py",
                "source_field": "rolling_percentile（Step 9 candidate 中記錄）",
                "derivation": "direct_candidate_value",
            },
        }

    # CONTEXT / PATTERN：看同一 context 是否存在 Step 9 的 3/3 pattern
    code = candidate["context"]["code"]
    pattern = pattern_by_context.get(code)
    if pattern is None:
        return None
    if pattern["consistency_count"] != pattern["total_metrics"]:
        return None

    return {
        "evidence_class": "second_supporting",
        "evidence_type": "cross_metric_direction_consistency",
        "different_in_kind_from_phenomenon": (
            "現象 evidence 是「單一指標（或三個指標各自）的差距大小」；"
            "本項是「三個指標的方向是否一致」，性質不同"
        ),
        "statement_fields": {
            "context": code,
            "metrics": list(pattern["metrics"]),
            "direction": pattern["direction"],
            "direction_per_metric": dict(pattern["direction_per_metric"]),
            "consistency_count": pattern["consistency_count"],
            "total_metrics": pattern["total_metrics"],
        },
        "provenance": {
            "source_step": "Step 9",
            "source_module": "src/candidate_insights.py",
            "source_field": (
                f"MULTI_METRIC_PATTERN candidate {pattern['candidate_id']} 的 "
                "direction / consistency_count / direction_per_metric"
            ),
            "derivation": "direct_candidate_value",
        },
        "known_limitation": (
            "Step 10 已記錄：3/3 metric consistency 不等於 importance。"
            "AVG / OBP / SLG 共用同一批安打與打數，本身高度相關，"
            "方向一致有相當程度是數學上的必然。方向判定也不含任何最小差距門檻。"
        ),
    }


def sample_context_evidence(candidate: dict, view: dict, sample: dict) -> dict | None:
    """sample context。**只檢查「是否存在」，不比較大小、不設門檻。**"""
    sc = sample["sample_context"]
    if sc["at_bats"] is None or sc["plate_appearances"] is None:
        return None

    # 取該 candidate 主要指標的 sensitivity（PATTERN 用 magnitude 對應的指標）
    metric = view["magnitude_metric"]
    sens = sample["sample_sensitivity"].get(metric)
    if sens is None or not sens.get("available"):
        return None

    return {
        "evidence_class": "sample_context",
        "evidence_type": SAMPLE_CONTEXT_TYPE,
        "presence_only_note": (
            "本項只要求「存在」。程式沒有把 at_bats 或 plate_appearances "
            "與任何數字比較，也沒有因為樣本小而降級或淘汰。"
        ),
        "statement_fields": {
            "at_bats": sc["at_bats"],
            "plate_appearances": sc["plate_appearances"],
            "games": sc["games"],
            "sensitivity_metric": metric,
            "numerator": sens["numerator"],
            "denominator": sens["denominator"],
            "current": sens["current"],
            "one_more_success": sens["one_more_success"],
            "one_fewer_success": sens["one_fewer_success"],
            "delta_if_one_more": sens["delta_if_one_more"],
            "success_unit": sens["success_unit"],
        },
        "provenance": {
            "source_step": "Step 11",
            "source_module": "src/evidence_sample_context.py",
            "source_field": "sample_context / sample_sensitivity",
            "derivation": "direct_sidecar_value",
        },
    }


def classify(candidate: dict, view: dict, sample: dict,
             pattern_by_context: dict) -> dict:
    """套用第一版規則。回傳 sidecar record。"""
    phenomenon = phenomenon_evidence(candidate, view)
    second = second_supporting_evidence(candidate, view, pattern_by_context)
    sample_ctx = sample_context_evidence(candidate, view, sample)

    supporting = [e for e in (phenomenon, second, sample_ctx) if e is not None]
    present = {e["evidence_class"] for e in supporting}

    if phenomenon is None:
        classification = "not_eligible"
        rule_id = "R17-1-NE"
        missing = ["phenomenon"]
    elif present >= {"phenomenon", "second_supporting", "sample_context"}:
        classification = "noteworthy"
        rule_id = "R17-1-NOTE"
        missing = []
    else:
        classification = "observation"
        rule_id = "R17-1-OBS"
        missing = [c for c in EVIDENCE_CLASSES if c not in present]

    missing_reasons = {}
    if "second_supporting" in missing:
        if candidate["type"] == "TREND":
            missing_reasons["second_supporting"] = (
                "TREND 應有 rolling percentile，但本 candidate 的 "
                "rolling_percentile 為 null"
            )
        else:
            code = candidate["context"]["code"]
            missing_reasons["second_supporting"] = (
                f"context {code} 在 Step 9 沒有 3/3 的 MULTI_METRIC_PATTERN"
                "（三個指標與季累計比較的方向不一致），"
                "且官方分項沒有時間維度所以沒有 rolling percentile"
                "（Step 8 已記錄）。因此找不到第二種不同性質的支持 evidence。"
            )
    if "sample_context" in missing:
        missing_reasons["sample_context"] = "sample context 或 sensitivity 不可用"

    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_type": candidate["type"],
        "scope": view["window_or_scope"],
        "metric_or_context": view["metric_or_context"],
        "classification": classification,
        "rule_id": rule_id,
        "rule_set": {
            "rule_set_id": RULE_SET_ID,
            "version": RULE_SET_VERSION,
            "rule_text": RULES[rule_id],
            "rule_source": RULE_SOURCE,
        },
        "evidence_classes_present": sorted(present),
        "evidence_classes_missing": missing,
        "missing_reasons": missing_reasons,
        "supporting_evidence": supporting,
        "sample_context": (
            sample_ctx["statement_fields"] if sample_ctx else None
        ),
        "provenance": {
            "candidate_source_step": "Step 9",
            "candidate_source_module": "src/candidate_insights.py",
            "sample_context_source_step": "Step 11",
            "sample_context_source_module": "src/evidence_sample_context.py",
            "second_evidence_source_step": (
                second["provenance"]["source_step"] if second else None
            ),
            "source_files": list(candidate["source_files"]),
            "sidecar_note": (
                "本記錄為 sidecar，用 candidate_id 關聯，不寫回 candidate 物件"
            ),
        },
        "limitation": build_limitation(candidate, classification, second, sample_ctx),
        "contains_no": [
            "score", "weight", "rank", "threshold", "confidence_score",
            "statistical_test", "prediction", "recommendation",
            "natural_language_conclusion", "llm",
        ],
    }


def build_limitation(candidate: dict, classification: str,
                     second: dict | None, sample_ctx: dict | None) -> dict:
    items = []
    if classification == "noteworthy":
        items.append(
            "noteworthy 只表示「三類 evidence 都存在」，"
            "不表示這個現象在統計上成立，也不表示它對決策重要。"
            "本規則沒有做任何 statistical test。"
        )
    if second and second["evidence_type"] == "cross_metric_direction_consistency":
        items.append(second["known_limitation"])
    if second and second["evidence_type"] == "rolling_window_distribution_position":
        items.append(
            "Step 6 已記錄：滾動窗口高度重疊（相鄰共用 9 場），彼此不獨立，"
            "因此百分位是「在這些重疊窗口中的相對位置」，不是機率陳述。"
        )
    if sample_ctx:
        d = sample_ctx["statement_fields"]
        items.append(
            f"樣本量 {d['at_bats']} 個打數，單一事件影響量 "
            f"{d['delta_if_one_more']:.8f}（Step 11）。"
            "這個資訊被記錄下來供解讀，**沒有**被用來淘汰或降級。"
        )
    if candidate["type"] == "CONTEXT" or candidate["type"] == "MULTI_METRIC_PATTERN":
        items.append(
            "官方分項為球季累計，沒有時間維度，無法切成任何窗口（Step 8）。"
        )
    if candidate["type"] == "TREND":
        items.append(
            "TREND 沒有 OBP（processed data 未收逐場犧牲飛球，Step 5 / Step 11）。"
        )
    return {
        "items": items,
        "rule_version_caveat": (
            "這是規則的第一版。分類結果完全由規則的形狀決定，"
            "換一組 evidence 類別定義，結果就會不同。"
        ),
    }


# ------------------------------------------------------------------ 樣本獨立性反證

def mutation_test_value_independence(
    candidates: list, views: dict, samples: dict, pattern_by_context: dict,
    baseline_records: list,
) -> dict:
    """把「差距大小」與「percentile」換成極端值後重跑分類，確認結果完全不變。

    這是「沒有數值門檻」的反證。若程式任何地方寫了
    `if diff > X` 或 `if percentile > X`，把值換成 0.0 或 100.0 就會改變分類。
    全部在複本上操作，不動原始 candidate。
    """
    base = {r["candidate_id"]: r["classification"] for r in baseline_records}
    diffs = []
    cases = 0

    for c in candidates:
        cid = c["candidate_id"]
        for mutant_diff in (0.0, -10.0, 10.0):
            cc = copy.deepcopy(c)
            if cc["type"] == "TREND":
                cc["absolute_difference"] = mutant_diff
                cc["absolute_difference_magnitude"] = abs(mutant_diff)
            elif cc["type"] == "CONTEXT":
                cc["comparison"]["difference"] = mutant_diff
                cc["comparison"]["difference_magnitude"] = abs(mutant_diff)
            else:
                for mv in cc["metric_values"].values():
                    mv["difference"] = mutant_diff
            cases += 1
            rec = classify(cc, views[cid], samples[cid], pattern_by_context)
            if rec["classification"] != base[cid]:
                diffs.append(
                    f"{cid}: difference={mutant_diff} 時分類由 {base[cid]} "
                    f"變成 {rec['classification']}"
                )

        if c["type"] == "TREND":
            for mutant_pct in (0.0, 50.0, 100.0):
                cc = copy.deepcopy(c)
                cc["rolling_percentile"]["percentile_rank"] = mutant_pct
                cc["rolling_percentile"]["percentile_strict"] = mutant_pct
                cases += 1
                rec = classify(cc, views[cid], samples[cid], pattern_by_context)
                if rec["classification"] != base[cid]:
                    diffs.append(
                        f"{cid}: percentile_rank={mutant_pct} 時分類由 {base[cid]} "
                        f"變成 {rec['classification']}"
                    )

    return {
        "mutant_difference_values": [0.0, -10.0, 10.0],
        "mutant_percentile_values": [0.0, 50.0, 100.0],
        "cases_tested": cases,
        "classification_changes": diffs,
        "value_independent": not diffs,
    }


def mutation_test_sample_independence(
    candidates: list, views: dict, samples: dict, pattern_by_context: dict,
    baseline_records: list,
) -> dict:
    """把 at_bats 換成極端值後重跑分類，確認結果完全不變。

    這是「樣本大小沒有被用作淘汰條件」的反證：
    如果程式任何地方拿 at_bats 與數字比較，改成 1 或 9999 就會改變分類。
    """
    base = {r["candidate_id"]: r["classification"] for r in baseline_records}
    diffs = []
    for mutant_ab in (1, 9999):
        for c in candidates:
            cid = c["candidate_id"]
            sample_copy = copy.deepcopy(samples[cid])
            sample_copy["sample_context"]["at_bats"] = mutant_ab
            sample_copy["sample_context"]["plate_appearances"] = mutant_ab
            for s in sample_copy["sample_sensitivity"].values():
                if s.get("available"):
                    s["denominator"] = mutant_ab
            rec = classify(c, views[cid], sample_copy, pattern_by_context)
            if rec["classification"] != base[cid]:
                diffs.append(
                    f"{cid}: at_bats={mutant_ab} 時分類由 {base[cid]} "
                    f"變成 {rec['classification']}"
                )
    return {
        "mutant_at_bats_values": [1, 9999],
        "candidates_tested": len(candidates),
        "classification_changes": diffs,
        "sample_size_independent": not diffs,
    }


# ------------------------------------------------------------------ 輸出

def print_records(records: list) -> None:
    order = {"noteworthy": 0, "observation": 1, "not_eligible": 2}
    for cls in ("noteworthy", "observation", "not_eligible"):
        group = sorted(
            (r for r in records if r["classification"] == cls),
            key=lambda r: r["candidate_id"],
        )
        print("\n" + "=" * 100)
        print(f"classification = {cls}（{len(group)} 個）")
        print("=" * 100)
        if not group:
            print("  （沒有）")
            continue
        for r in group:
            print(f"\n  {r['candidate_id']}")
            print(f"    rule_id                 : {r['rule_id']}")
            print(f"    evidence_classes_present: "
                  f"{', '.join(r['evidence_classes_present'])}")
            if r["evidence_classes_missing"]:
                print(f"    evidence_classes_missing: "
                      f"{', '.join(r['evidence_classes_missing'])}")
                for k, v in r["missing_reasons"].items():
                    print(f"        缺 {k}：{v}")
            for e in r["supporting_evidence"]:
                print(f"    [{e['evidence_class']}] {e['evidence_type']}"
                      f"　來源 {e['provenance']['source_step']}")
                sf = e["statement_fields"]
                if e["evidence_class"] == "phenomenon":
                    if "differences" in sf:
                        diffs = "  ".join(
                            f"{m.split('_')[0]}={v:+.8f}"
                            for m, v in sf["differences"].items()
                        )
                        print(f"        direction={sf['direction']}  {diffs}")
                    else:
                        print(f"        current={sf['current_value']:.8f}"
                              f"  baseline={sf['baseline_value']:.8f}"
                              f"  diff={sf['difference']:+.8f}"
                              f"  direction={sf['direction']}")
                elif e["evidence_type"] == "rolling_window_distribution_position":
                    print(f"        window_size={sf['window_size']}"
                          f"  n={sf['distribution_n']}  rank={sf['rank_desc']}"
                          f"  below/equal/above="
                          f"{sf['count_below']}/{sf['count_equal']}/{sf['count_above']}")
                    print(f"        percentile_rank={sf['percentile_rank']:.4f}"
                          f"  percentile_strict={sf['percentile_strict']:.4f}")
                elif e["evidence_type"] == "cross_metric_direction_consistency":
                    print(f"        direction={sf['direction']}"
                          f"  consistency={sf['consistency_count']}"
                          f"/{sf['total_metrics']}"
                          f"  per_metric={sf['direction_per_metric']}")
                else:
                    print(f"        AB={sf['at_bats']}  PA={sf['plate_appearances']}"
                          f"  games={sf['games']}")
                    print(f"        {sf['sensitivity_metric']}: "
                          f"{sf['numerator']}/{sf['denominator']}"
                          f" = {sf['current']:.8f}"
                          f"　one_more={sf['one_more_success']:.8f}"
                          f"　one_fewer={sf['one_fewer_success']:.8f}"
                          f"　delta={sf['delta_if_one_more']:.8f}")


def print_summary(records: list) -> None:
    print("\n" + "=" * 100)
    print("分類統計")
    print("=" * 100)
    counts: dict[str, int] = {}
    for r in records:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    for cls in CLASSIFICATION_VALUES:
        print(f"  {cls:<16}: {counts.get(cls, 0):>3} 個")
    print(f"  {'合計':<16}: {len(records):>3} 個")

    print("\n  依 candidate 類型：")
    by = {}
    for r in records:
        by.setdefault(r["candidate_type"], {}).setdefault(r["classification"], 0)
        by[r["candidate_type"]][r["classification"]] += 1
    for ctype in ("TREND", "MULTI_METRIC_PATTERN", "CONTEXT"):
        d = by.get(ctype, {})
        print(f"    {ctype:<22} " + "　".join(
            f"{cls}={d.get(cls, 0)}" for cls in CLASSIFICATION_VALUES
        ))

    print("\n  第二種支持 evidence 的來源：")
    src: dict[str, int] = {}
    for r in records:
        found = [e["evidence_type"] for e in r["supporting_evidence"]
                 if e["evidence_class"] == "second_supporting"]
        key = found[0] if found else "（無）"
        src[key] = src.get(key, 0) + 1
    for k in sorted(src):
        print(f"    {k:<44} {src[k]:>3} 個")

    print("\n  樣本量最小的 candidate 分類（確認小樣本沒有被淘汰）：")
    smallest = sorted(records, key=lambda r: r["sample_context"]["at_bats"])[:4]
    for r in smallest:
        print(f"    AB={r['sample_context']['at_bats']:>4}  "
              f"{r['classification']:<12} {r['candidate_id']}")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "rank", "threshold", "confidence", "importance")
ALLOWED_KEY_EXCEPTIONS = ("percentile_rank", "rank_desc")
DECLARATIVE_KEYS = ("contains_no",)

LLM_PACKAGE_NAMES = frozenset({
    "openai", "anthropic", "cohere", "vertexai", "transformers", "langchain",
    "llama_index", "ollama", "litellm", "mistralai", "torch", "tensorflow",
    "huggingface_hub",
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
    candidates_before: list, candidates_after: list, records: list,
    rerun_records: list, views: dict, samples: dict,
    mutation: dict, value_mutation: dict, fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    n = len(candidates_after)
    by_id = {r["candidate_id"]: r for r in records}
    cand_ids = [c["candidate_id"] for c in candidates_after]

    # 1. 29 個 candidate 全部都有且只有一個 classification
    ids = [r["candidate_id"] for r in records]
    one_each = (
        len(records) == n == 29
        and sorted(ids) == sorted(cand_ids)
        and len(set(ids)) == len(ids)
        and all(r["classification"] in CLASSIFICATION_VALUES for r in records)
    )
    checks.append(
        (f"{n} 個 candidate 全部都有且只對應一個 classification", one_each,
         f"records={len(records)}　id 集合相同={sorted(ids) == sorted(cand_ids)}"
         f"　無重複={len(set(ids)) == len(ids)}"
         f"　classification 皆在受控詞彙中="
         f"{all(r['classification'] in CLASSIFICATION_VALUES for r in records)}")
    )

    # 2. candidate 原始資料完全未修改
    same = candidates_before == candidates_after
    checks.append(
        ("candidate 原始 evidence 完全未修改（深度比較 29 個物件）", same,
         "sidecar 設計，沒有寫回路徑；逐欄位比較完全相同"
         if same else "有物件被改動")
    )

    # 3. 所有 supporting evidence 都能追溯到既有 Step 資料
    trace_bad = []
    for r in records:
        for e in r["supporting_evidence"]:
            p = e.get("provenance", {})
            if p.get("source_step") not in ALLOWED_SOURCE_STEPS:
                trace_bad.append(f"{r['candidate_id']} {e['evidence_type']} "
                                 f"source_step={p.get('source_step')}")
            if not p.get("source_module") or not p.get("derivation"):
                trace_bad.append(f"{r['candidate_id']} {e['evidence_type']} provenance 不完整")
            if e["evidence_class"] not in EVIDENCE_CLASSES:
                trace_bad.append(f"{r['candidate_id']} evidence_class 不在受控詞彙中")
    checks.append(
        ("所有 supporting evidence 都能追溯到既有 Step 5–11 的資料", not trace_bad,
         f"共 {sum(len(r['supporting_evidence']) for r in records)} 筆 evidence，"
         f"source_step 皆在 {list(ALLOWED_SOURCE_STEPS)} 之中，且都有 "
         "source_module 與 derivation"
         if not trace_bad else "；".join(trace_bad[:5]))
    )

    # 4. 不存在虛構的 evidence：逐筆比對回 Step 9 / Step 11 的實際值
    fake = []
    for c in candidates_after:
        r = by_id[c["candidate_id"]]
        for e in r["supporting_evidence"]:
            sf = e["statement_fields"]
            if e["evidence_class"] == "phenomenon":
                if c["type"] == "TREND":
                    if (sf["current_value"] != c["current_value"]
                            or sf["difference"] != c["absolute_difference"]):
                        fake.append(f"{c['candidate_id']} phenomenon 值不符 candidate")
                elif c["type"] == "CONTEXT":
                    if (sf["current_value"] != c["value"]
                            or sf["difference"] != c["comparison"]["difference"]):
                        fake.append(f"{c['candidate_id']} phenomenon 值不符 candidate")
                else:
                    for m, v in sf["differences"].items():
                        if v != c["metric_values"][m]["difference"]:
                            fake.append(f"{c['candidate_id']} phenomenon {m} 值不符")
            elif e["evidence_type"] == "rolling_window_distribution_position":
                rp = c["rolling_percentile"]
                if (sf["percentile_rank"] != rp["percentile_rank"]
                        or sf["distribution_n"] != rp["distribution_n"]
                        or sf["rank_desc"] != rp["rank_desc"]):
                    fake.append(f"{c['candidate_id']} rolling 值不符 candidate")
            elif e["evidence_type"] == "cross_metric_direction_consistency":
                if sf["consistency_count"] != sf["total_metrics"]:
                    fake.append(f"{c['candidate_id']} consistency 非 3/3 卻被採用")
            else:
                s = samples[c["candidate_id"]]
                sens = s["sample_sensitivity"][sf["sensitivity_metric"]]
                if (sf["at_bats"] != s["sample_context"]["at_bats"]
                        or sf["delta_if_one_more"] != sens["delta_if_one_more"]
                        or sf["current"] != sens["current"]):
                    fake.append(f"{c['candidate_id']} sample context 值不符 Step 11")
    checks.append(
        ("不存在虛構的 evidence：每筆 evidence 的數值都與 Step 9 / Step 11 原值相符",
         not fake,
         "全部逐欄位比對相符" if not fake else "；".join(fake[:5]))
    )

    payload = {"records": records, "mutation": mutation}
    blob = json.dumps(payload, ensure_ascii=False)
    # 宣告性欄位：contains_no 是「不含這些東西」的清單；
    # limitation / known_limitation 是解釋性文字，裡面會出現「不含任何最小差距門檻」
    # 這類否定敘述。字眼掃描必須扣除，否則會把否定宣告誤判成違規。
    declarative = json.dumps(
        [
            {
                "contains_no": r["contains_no"],
                "limitation": r["limitation"],
                "known_limitation": [
                    e.get("known_limitation") for e in r["supporting_evidence"]
                ],
                "presence_only_note": [
                    e.get("presence_only_note") for e in r["supporting_evidence"]
                ],
                "different_in_kind": [
                    e.get("different_in_kind_from_phenomenon")
                    for e in r["supporting_evidence"]
                ],
            }
            for r in records
        ],
        ensure_ascii=False,
    )

    # 5. 沒有 threshold
    #    主要證明是 mutation test（結構性反證），字眼掃描只是輔助。
    thr_words = []
    for w in ("threshold", "門檻", "cutoff", "minimum_", "at_least_"):
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            thr_words.append(f"{w}×{cnt}")
    ok_thr = (
        len(records) == n
        and value_mutation["value_independent"]
        and not thr_words
    )
    checks.append(
        ("沒有 threshold：把差距與 percentile 換成極端值後分類不變（結構性反證）",
         ok_thr,
         f"29 個 candidate 全部被分類；mutation test 共 "
         f"{value_mutation['cases_tested']} 次重新分類"
         f"（difference 換成 {value_mutation['mutant_difference_values']}，"
         f"percentile 換成 {value_mutation['mutant_percentile_values']}），"
         "結果全部與原分類相同，證明分類邏輯沒有把任何數值與常數比較"
         if ok_thr else
         f"mutation 改變數={len(value_mutation['classification_changes'])}"
         f"　可疑字眼={thr_words}")
    )

    # 6. 沒有 score / weight / rank
    bad_keys = scan_keys(payload)
    score_keys = [k for k in bad_keys if "score" in k.lower()]
    weight_keys = [k for k in bad_keys if "weight" in k.lower()]
    rank_keys = [k for k in bad_keys if "rank" in k.lower()]
    checks.append(
        ("沒有 score 欄位", not score_keys,
         "沒有任何分數欄位" if not score_keys else "；".join(score_keys))
    )
    checks.append(
        ("沒有 weight 欄位", not weight_keys,
         "沒有任何權重欄位" if not weight_keys else "；".join(weight_keys))
    )
    checks.append(
        ("沒有 rank 欄位（percentile_rank / rank_desc 為 Step 6 既有 evidence 描述子，已排除）",
         not rank_keys,
         "沒有任何 candidate 名次欄位；輸出分組依 classification，組內為 candidate_id 字典序"
         if not rank_keys else "；".join(rank_keys))
    )

    # 7. 沒有 LLM / HTTP request
    imported = collect_imported_modules(Path(__file__))
    loaded = {m.split(".")[0].lower() for m in sys.modules}
    llm_hits = sorted((imported | loaded) & LLM_PACKAGE_NAMES)
    checks.append(
        ("沒有使用 LLM", not llm_hits,
         f"AST 解析本檔案 import 的頂層模組 {len(imported)} 個："
         + "、".join(sorted(imported))
         + "；已載入模組中沒有任何 LLM 套件"
         if not llm_hits else f"發現：{llm_hits}")
    )
    checks.append(
        ("沒有任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖")
    )

    # 8. sample context 不得被用作淘汰條件（mutation 反證）
    checks.append(
        ("sample context 沒有被用作淘汰條件（把 at_bats 換成 1 與 9999 後分類不變）",
         mutation["sample_size_independent"],
         f"對 {mutation['candidates_tested']} 個 candidate 各測 "
         f"{len(mutation['mutant_at_bats_values'])} 種極端值，"
         f"共 {mutation['candidates_tested'] * len(mutation['mutant_at_bats_values'])} 次"
         "重新分類，結果全部與原分類相同"
         if mutation["sample_size_independent"]
         else "；".join(mutation["classification_changes"][:5]))
    )

    # 額外：沒有任何 candidate 被淘汰（not_eligible 應為 0）
    not_elig = [r["candidate_id"] for r in records
                if r["classification"] == "not_eligible"]
    smallest = min(records, key=lambda r: r["sample_context"]["at_bats"])
    checks.append(
        ("沒有任何 candidate 因樣本小而被淘汰", not not_elig,
         f"not_eligible = 0 個；樣本最小的 {smallest['candidate_id']}"
         f"（AB={smallest['sample_context']['at_bats']}）被分類為 "
         f"{smallest['classification']}"
         if not not_elig else f"not_eligible：{not_elig}")
    )

    # 9. RECENT_10-AVG 必須是 noteworthy
    target = "TREND-ZHANGYUCHENG-2026-A-RECENT_10-AVG"
    t = by_id.get(target)
    ok_target = (
        t is not None
        and t["classification"] == "noteworthy"
        and set(t["evidence_classes_present"]) == set(EVIDENCE_CLASSES)
    )
    detail = "找不到該 candidate"
    if t:
        types = [e["evidence_type"] for e in t["supporting_evidence"]]
        detail = (f"classification={t['classification']}"
                  f"　evidence_classes={t['evidence_classes_present']}"
                  f"　evidence_types={types}")
    checks.append(
        ("RECENT_10-AVG 具備三類 evidence，且被分類為 noteworthy", ok_target, detail)
    )

    # 10. deterministic
    det = (json.dumps(records, ensure_ascii=False, sort_keys=True)
           == json.dumps(rerun_records, ensure_ascii=False, sort_keys=True))
    checks.append(
        ("重新執行結果完全一致（deterministic）", det,
         "整個分類流程重跑一次，序列化結果完全相同"
         if det else "重跑結果不同")
    )

    # 11. raw / processed data 未修改
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data 未被修改", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    # 12. 沒有最終自然語言結論
    forbidden = ("擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
                 "建議", "應該", "預測", "統計顯著", "顯著性", "最佳", "最好", "最差",
                 "表現很好", "表現不佳", "recommend", "should", "predict")
    hits = []
    for w in forbidden:
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    checks.append(
        ("沒有產生最終自然語言結論或價值判斷字眼", not hits,
         "未出現禁用字眼（contains_no 中的否定宣告已扣除）"
         if not hits else "、".join(hits))
    )

    # 13. 沒有新增 statistical test
    stat_words = []
    for w in ("p_value", "p-value", "t_test", "chi_square", "binomial",
              "confidence_interval", "z_score", "hypothesis"):
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            stat_words.append(f"{w}×{cnt}")
    checks.append(
        ("沒有新增任何 statistical test", not stat_words,
         "分類只檢查 evidence 是否存在，沒有任何檢定、機率或區間估計"
         if not stat_words else "、".join(stat_words))
    )

    return checks


# ------------------------------------------------------------------ main

def build_all(logs, apart_rows):
    contexts = build_context_evidence(apart_rows)
    season = build_season_baseline(logs, contexts)
    trend, _ = build_trend_candidates(logs, season)
    context_cands = build_context_candidates(contexts, season)
    pattern, _ = build_pattern_candidates(contexts, season)
    candidates = trend + context_cands + pattern

    trend_components = build_trend_components(logs)
    samples = {
        c["candidate_id"]: build_record(c, trend_components, contexts)
        for c in candidates
    }
    views = {
        c["candidate_id"]: build_view(c, samples[c["candidate_id"]])
        for c in candidates
    }
    pattern_by_context = {p["context"]["code"]: p for p in pattern}
    records = [
        classify(c, views[c["candidate_id"]], samples[c["candidate_id"]],
                 pattern_by_context)
        for c in candidates
    ]
    return candidates, views, samples, pattern_by_context, records


def main() -> None:
    logs, apart_rows = load_inputs()
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }

    candidates, views, samples, pattern_by_context, records = build_all(logs, apart_rows)
    candidates_before = copy.deepcopy(candidates)
    _, _, _, _, rerun_records = build_all(logs, apart_rows)

    mutation = mutation_test_sample_independence(
        candidates, views, samples, pattern_by_context, records
    )
    value_mutation = mutation_test_value_independence(
        candidates, views, samples, pattern_by_context, records
    )

    print("=" * 100)
    print("Observation → Noteworthy 規則實驗（Step 17-7）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print(f"輸入：Step 9 的 {len(candidates)} 個 candidate")
    print(f"規則：{RULE_SET_ID}（{RULE_SET_VERSION}）")
    print("沒有 AVG / percentile / AB 門檻，沒有 score / weight / rank，")
    print("沒有新增 statistical test，沒有 LLM，沒有最終自然語言結論。")
    print("=" * 100)
    print("\n規則內容：")
    for rid, text in RULES.items():
        print(f"  {rid}：{text}")
    print(f"\n規則來源：{RULE_SOURCE}")

    print_summary(records)
    print_records(records)

    print("\n" + "=" * 100)
    print("門檻獨立性反證（mutation test）")
    print("=" * 100)
    print("  (1) sample size 獨立性")
    print(f"      測試值            : at_bats = {mutation['mutant_at_bats_values']}")
    print(f"      受測 candidate 數 : {mutation['candidates_tested']}")
    print(f"      分類改變的筆數    : {len(mutation['classification_changes'])}")
    print(f"      sample_size 獨立  : {mutation['sample_size_independent']}")
    print("      說明：若程式把 at_bats 與數字比較，改成 1 或 9999 就會改變分類。")
    print("  (2) 數值門檻獨立性")
    print(f"      difference 測試值 : {value_mutation['mutant_difference_values']}")
    print(f"      percentile 測試值 : {value_mutation['mutant_percentile_values']}")
    print(f"      重新分類次數      : {value_mutation['cases_tested']}")
    print(f"      分類改變的筆數    : "
          f"{len(value_mutation['classification_changes'])}")
    print(f"      數值門檻獨立      : {value_mutation['value_independent']}")
    print("      說明：若程式寫了 if diff > X 或 if percentile > X，")
    print("      　　　把值換成 0.0 或 100.0 就會改變分類。")

    print("\n" + "=" * 100)
    print("Validation")
    print("=" * 100)
    checks = run_validation(
        candidates_before, candidates, records, rerun_records, views, samples,
        mutation, value_mutation, fingerprints_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 "
              "docs/NOTEWORTHY_INSIGHT_EXPERIMENT.md。")

    print("\n" + "=" * 100)
    print("本階段只套用規則並記錄結果，沒有選出任何 insight，也沒有產生自然語言。")
    print("=" * 100)


if __name__ == "__main__":
    main()

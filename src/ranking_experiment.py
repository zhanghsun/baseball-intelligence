"""Ranking Strategy Experiment（Step 12）。

它做什麼：用**完全同一批 29 個 candidate**，實驗三種不同的 ranking philosophy，
觀察它們會把哪些 candidate 排到前面。

它**不**做什麼：
    - 不決定哪個 strategy 是對的（本階段不選最佳）
    - 不建立 final_score / confidence_score / importance_score
    - 不建立任何 weight（沒有 `a*x + b*y` 這種合成）
    - 不設任何 threshold
    - 不做統計顯著性宣稱
    - 不產生自然語言結論、不使用 LLM
    - 不發任何 HTTP 請求
    - 不修改 candidate evidence 或任何來源資料

排序方式：**deterministic lexicographic ordering**（字典序 tuple 比較），
不是加權分數。每個 strategy 的排序鍵完整記錄在 `STRATEGY_RULES` 中並輸出。

null 的處理：percentile_rank 在 CONTEXT / PATTERN 為 null。
排序鍵中先放一個「是否可用」的旗標，再放數值，
因此 null 永遠不會與真實數值做數值比較，也不會被當成 0。
`verify_no_null_coercion()` 用一個會在遇到 None 數值比較時直接拋錯的
comparator 重跑排序，再比對結果是否相同，以此證明這件事。

用法：
    python src/ranking_experiment.py
"""

from __future__ import annotations

import copy
import functools
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
from candidate_priority import GRANULARITY_BY_TYPE, PROVISIONAL_PRODUCT_PRIORITY  # noqa: E402
from evidence_sample_context import build_record, build_trend_components  # noqa: E402

TOP_N = 10

# ------------------------------------------------------------------ 排序規則（完整記錄）

STRATEGY_RULES = {
    "A_PRODUCT_FIRST": {
        "name": "Strategy A — Product-first",
        "philosophy": (
            "先遵守 Step 10 已記錄的產品偏好 tier（TREND → MULTI_METRIC_PATTERN → "
            "CONTEXT），只在同一 tier 內才比較 evidence descriptors。"
        ),
        "lexicographic_key": [
            "1. priority_tier 升冪（1 → 2 → 3）",
            "2. magnitude 降冪（同 tier 內才生效）",
            "3. sample_size_at_bats 降冪",
            "4. candidate_id 字典序升冪（最終決勝，保證全序）",
        ],
        "no_weighting_note": (
            "字典序比較不是加權。第 2 鍵只在第 1 鍵相同時才被讀取，"
            "兩個鍵之間沒有任何係數或換算。"
        ),
        "null_handling": "本 strategy 的排序鍵不使用 percentile_rank，因此沒有 null 問題。",
    },
    "B_MAGNITUDE_FIRST": {
        "name": "Strategy B — Magnitude-first",
        "philosophy": (
            "先看差距大小。percentile_rank 與 consistency_count 只在 magnitude "
            "完全相同時才會被讀取。"
        ),
        "lexicographic_key": [
            "1. magnitude 降冪",
            "2. percentile_rank 是否可用（可用者優先；僅在第 1 鍵相同時生效）",
            "3. percentile_rank 降冪（僅在兩者都可用時比較）",
            "4. consistency_count 是否可用（可用者優先）",
            "5. consistency_count 降冪（僅在兩者都可用時比較）",
            "6. candidate_id 字典序升冪",
        ],
        "no_weighting_note": (
            "magnitude 與 percentile 之間沒有任何係數。percentile 不會「加分」，"
            "它只在 magnitude 打平時被讀取。"
        ),
        "null_handling": (
            "CONTEXT 與 MULTI_METRIC_PATTERN 的 percentile_rank 為 null。"
            "第 2 鍵是「是否可用」的旗標，先把有值與無值分成兩群，"
            "第 3 鍵只在同一群內比較。因此 null 永遠不會與真實數值比大小，"
            "也沒有被當成 0 或任何補值。"
        ),
    },
    "C_SAMPLE_AWARE": {
        "name": "Strategy C — Conservative / Sample-aware",
        "philosophy": (
            "先看 evidence 背後有多少資料。樣本較大的排前面，"
            "但小樣本 candidate 完全保留，只是排在後面。"
        ),
        "lexicographic_key": [
            "1. sample_size_at_bats 降冪",
            "2. plate_appearances 降冪",
            "3. delta_if_one_more 是否可用（可用者優先）",
            "4. delta_if_one_more 升冪（僅在兩者都可用時比較；單一事件影響量較小者優先）",
            "5. magnitude 降冪",
            "6. candidate_id 字典序升冪",
        ],
        "no_weighting_note": (
            "sample size 沒有被轉換成任何分數或折扣係數，它只是第 1 個排序鍵。"
        ),
        "null_handling": (
            "第 3 鍵 delta_if_one_more 在 TREND 的 OBP 為 null，"
            "但 TREND candidate 的主要指標是 AVG 或 SLG，兩者都有值，"
            "因此本 strategy 實際使用的 delta 沒有 null。"
            "若出現 null，同樣以「是否可用」旗標分群處理。"
        ),
    },
}

STRATEGY_ORDER = ["A_PRODUCT_FIRST", "B_MAGNITUDE_FIRST", "C_SAMPLE_AWARE"]


# ------------------------------------------------------------------ 描述子擷取

def magnitude_of(candidate: dict) -> tuple[float, str, str]:
    """回傳 (magnitude, 使用的 metric, 定義說明)。不做任何合成。"""
    ctype = candidate["type"]
    if ctype == "TREND":
        return (
            abs(candidate["absolute_difference"]),
            candidate["metric"],
            "abs(absolute_difference)：窗口值與季累計的差距絕對值",
        )
    if ctype == "CONTEXT":
        return (
            abs(candidate["comparison"]["difference"]),
            candidate["metric"],
            "abs(difference_from_season)：情境值與季累計的差距絕對值",
        )
    # MULTI_METRIC_PATTERN：三個指標中差距絕對值最大的那一個
    best_metric, best_value = None, -1.0
    for metric, mv in candidate["metric_values"].items():
        v = abs(mv["difference"])
        if v > best_value:
            best_metric, best_value = metric, v
    return (
        best_value,
        best_metric,
        "max over 3 metrics of abs(difference_from_season)："
        "三個指標差距絕對值中的最大者（這是一個明確的選擇，見文件）",
    )


def percentile_of(candidate: dict) -> float | None:
    """TREND 有，CONTEXT / PATTERN 為 None。不補值。"""
    if candidate["type"] == "TREND":
        rp = candidate["rolling_percentile"]
        return None if rp is None else rp["percentile_rank"]
    return None


def consistency_of(candidate: dict) -> int | None:
    if candidate["type"] == "MULTI_METRIC_PATTERN":
        return candidate["consistency_count"]
    return None


def build_view(candidate: dict, sample_record: dict) -> dict:
    """把排序需要的描述子集中成一個唯讀的 view。全部是既有值的複製。"""
    magnitude, mag_metric, mag_def = magnitude_of(candidate)
    sens = sample_record["sample_sensitivity"].get(mag_metric, {})
    return {
        "candidate_id": candidate["candidate_id"],
        "type": candidate["type"],
        "tier": PROVISIONAL_PRODUCT_PRIORITY[candidate["type"]],
        "granularity": GRANULARITY_BY_TYPE[candidate["type"]],
        "metric_or_context": (
            candidate["metric"] if candidate["type"] == "TREND"
            else f"{candidate['context']['code']}"
            + (f" / {candidate['metric']}" if candidate["type"] == "CONTEXT"
               else " / AVG+OBP+SLG")
        ),
        "magnitude": magnitude,
        "magnitude_metric": mag_metric,
        "magnitude_definition": mag_def,
        "percentile_rank": percentile_of(candidate),
        "consistency_count": consistency_of(candidate),
        "sample_size_at_bats": sample_record["sample_context"]["at_bats"],
        "plate_appearances": sample_record["sample_context"]["plate_appearances"],
        "delta_if_one_more": sens.get("delta_if_one_more"),
        "window_or_scope": (
            sample_record["sample_context"]["window_name"]
            or (sample_record["sample_context"]["context"]["code"]
                if sample_record["sample_context"]["context"] else None)
        ),
    }


# ------------------------------------------------------------------ 排序鍵

def key_a(v: dict) -> tuple:
    return (v["tier"], -v["magnitude"], -v["sample_size_at_bats"], v["candidate_id"])


def key_b(v: dict) -> tuple:
    pct, cons = v["percentile_rank"], v["consistency_count"]
    return (
        -v["magnitude"],
        0 if pct is not None else 1,
        # 這個位置只會與「同一個可用性群組」的成員比較，因為前一個鍵已經分群。
        # 因此 0.0 從來不會與真實 percentile 做比較，不構成補值。
        -(pct if pct is not None else 0.0),
        0 if cons is not None else 1,
        -(cons if cons is not None else 0),
        v["candidate_id"],
    )


def key_c(v: dict) -> tuple:
    delta = v["delta_if_one_more"]
    return (
        -v["sample_size_at_bats"],
        -v["plate_appearances"],
        0 if delta is not None else 1,
        (delta if delta is not None else 0.0),
        -v["magnitude"],
        v["candidate_id"],
    )


KEY_FUNCS = {
    "A_PRODUCT_FIRST": key_a,
    "B_MAGNITUDE_FIRST": key_b,
    "C_SAMPLE_AWARE": key_c,
}


# ------------------------------------------------------------------ null 不被當成 0 的證明

class NullComparisonError(RuntimeError):
    pass


def _cmp_numeric(a, b, label: str, descending: bool) -> int:
    """比較兩個數值。若其中一個是 None 直接拋錯——這正是我們要證明不會發生的事。"""
    if a is None or b is None:
        raise NullComparisonError(
            f"試圖對 {label} 做數值比較，但其中一方為 None（a={a}, b={b}）"
        )
    if a == b:
        return 0
    if descending:
        return -1 if a > b else 1
    return -1 if a < b else 1


def cmp_b_strict(x: dict, y: dict) -> int:
    """Strategy B 的嚴格 comparator：任何 None 的數值比較都會拋錯。"""
    r = _cmp_numeric(x["magnitude"], y["magnitude"], "magnitude", descending=True)
    if r:
        return r
    xa = x["percentile_rank"] is not None
    ya = y["percentile_rank"] is not None
    if xa != ya:
        return -1 if xa else 1
    if xa and ya:
        r = _cmp_numeric(x["percentile_rank"], y["percentile_rank"],
                         "percentile_rank", descending=True)
        if r:
            return r
    xc = x["consistency_count"] is not None
    yc = y["consistency_count"] is not None
    if xc != yc:
        return -1 if xc else 1
    if xc and yc:
        r = _cmp_numeric(x["consistency_count"], y["consistency_count"],
                         "consistency_count", descending=True)
        if r:
            return r
    return -1 if x["candidate_id"] < y["candidate_id"] else (
        0 if x["candidate_id"] == y["candidate_id"] else 1
    )


def cmp_c_strict(x: dict, y: dict) -> int:
    for label, desc in (("sample_size_at_bats", True), ("plate_appearances", True)):
        r = _cmp_numeric(x[label], y[label], label, descending=desc)
        if r:
            return r
    xa = x["delta_if_one_more"] is not None
    ya = y["delta_if_one_more"] is not None
    if xa != ya:
        return -1 if xa else 1
    if xa and ya:
        r = _cmp_numeric(x["delta_if_one_more"], y["delta_if_one_more"],
                         "delta_if_one_more", descending=False)
        if r:
            return r
    r = _cmp_numeric(x["magnitude"], y["magnitude"], "magnitude", descending=True)
    if r:
        return r
    return -1 if x["candidate_id"] < y["candidate_id"] else (
        0 if x["candidate_id"] == y["candidate_id"] else 1
    )


def cmp_a_strict(x: dict, y: dict) -> int:
    for label, desc in (("tier", False), ("magnitude", True),
                        ("sample_size_at_bats", True)):
        r = _cmp_numeric(x[label], y[label], label, descending=desc)
        if r:
            return r
    return -1 if x["candidate_id"] < y["candidate_id"] else (
        0 if x["candidate_id"] == y["candidate_id"] else 1
    )


CMP_FUNCS = {
    "A_PRODUCT_FIRST": cmp_a_strict,
    "B_MAGNITUDE_FIRST": cmp_b_strict,
    "C_SAMPLE_AWARE": cmp_c_strict,
}


# ------------------------------------------------------------------ 排序

def rank(views: list, strategy: str) -> list:
    ordered = sorted(views, key=KEY_FUNCS[strategy])
    return [
        {"rank": i + 1, **v, "strategy": strategy}
        for i, v in enumerate(ordered)
    ]


def print_ranking(strategy: str, ranking: list, top_n: int = TOP_N) -> None:
    rule = STRATEGY_RULES[strategy]
    print("\n" + "=" * 100)
    print(f"{rule['name']}")
    print("=" * 100)
    print(f"  philosophy: {rule['philosophy']}")
    print("  lexicographic key（字典序，非加權）：")
    for line in rule["lexicographic_key"]:
        print(f"    {line}")
    print(f"  no weighting: {rule['no_weighting_note']}")
    print(f"  null handling: {rule['null_handling']}")
    print(f"\n  Rank 1 ~ {top_n}：")
    print(f"  {'#':>2}  {'candidate_id':<52} {'type':<21} {'metric / context':<34}")
    for row in ranking[:top_n]:
        print(f"  {row['rank']:>2}  {row['candidate_id']:<52} {row['type']:<21} "
              f"{row['metric_or_context']:<34}")
        pct = ("null" if row["percentile_rank"] is None
               else f"{row['percentile_rank']:.4f}")
        cons = "null" if row["consistency_count"] is None else row["consistency_count"]
        delta = ("null" if row["delta_if_one_more"] is None
                 else f"{row['delta_if_one_more']:.8f}")
        print(f"      evidence: tier={row['tier']}"
              f"  magnitude={row['magnitude']:.8f}({row['magnitude_metric']})"
              f"  percentile_rank={pct}")
        print(f"                consistency_count={cons}"
              f"  AB={row['sample_size_at_bats']}"
              f"  PA={row['plate_appearances']}"
              f"  delta_if_one_more={delta}"
              f"  granularity={row['granularity']}")


# ------------------------------------------------------------------ Rank Changes

def deciding_key_report(views: list, strategy: str, ranking: list) -> dict:
    """對每一組相鄰名次，找出是第幾個排序鍵決定了先後。

    用途：檢查排序規則中的每個鍵是否真的有作用。若某個鍵從未決定任何一組，
    代表這個 strategy 的名稱與實際行為有落差，這件事應該被記錄而不是被忽略。
    """
    keyf = KEY_FUNCS[strategy]
    labels = STRATEGY_RULES[strategy]["lexicographic_key"]
    counts = {i: 0 for i in range(len(labels))}
    for i in range(len(ranking) - 1):
        ka, kb = keyf(ranking[i]), keyf(ranking[i + 1])
        for pos in range(len(ka)):
            if ka[pos] != kb[pos]:
                counts[pos] = counts.get(pos, 0) + 1
                break
    return {
        "strategy": strategy,
        "labels": labels,
        "decided_counts": counts,
        "unused_keys": [labels[i] for i, c in counts.items() if c == 0],
        "pairs": len(ranking) - 1,
    }


def print_deciding_keys(reports: list) -> None:
    print("\n" + "=" * 100)
    print("排序鍵作用診斷（每一組相鄰名次是由第幾個鍵決定的）")
    print("=" * 100)
    for rep in reports:
        print(f"\n  {STRATEGY_RULES[rep['strategy']]['name']}"
              f"（{rep['pairs']} 組相鄰名次）")
        for i, label in enumerate(rep["labels"]):
            print(f"    鍵 {i + 1}：決定了 {rep['decided_counts'].get(i, 0)} 組"
                  f"　{label}")
        if rep["unused_keys"]:
            print("    未被使用的鍵（在本次資料下完全沒有影響任何排序）：")
            for label in rep["unused_keys"]:
                print(f"      - {label}")


def analyse_rank_changes(rankings: dict) -> dict:
    rank_by_strategy = {
        s: {row["candidate_id"]: row["rank"] for row in r}
        for s, r in rankings.items()
    }
    tops = {s: {row["candidate_id"] for row in r[:TOP_N]} for s, r in rankings.items()}

    all_three = set.intersection(*tops.values())
    only_one = {}
    for s in STRATEGY_ORDER:
        others = set.union(*[tops[o] for o in STRATEGY_ORDER if o != s])
        only_one[s] = tops[s] - others

    all_ids = sorted(rank_by_strategy[STRATEGY_ORDER[0]])
    spreads = []
    for cid in all_ids:
        ranks = {s: rank_by_strategy[s][cid] for s in STRATEGY_ORDER}
        spreads.append(
            {
                "candidate_id": cid,
                "ranks": ranks,
                "min_rank": min(ranks.values()),
                "max_rank": max(ranks.values()),
                "spread": max(ranks.values()) - min(ranks.values()),
            }
        )
    spreads.sort(key=lambda d: (-d["spread"], d["candidate_id"]))
    return {
        "top_n": TOP_N,
        "tops": {s: sorted(v) for s, v in tops.items()},
        "in_all_three_tops": sorted(all_three),
        "only_in_one_top": {s: sorted(v) for s, v in only_one.items()},
        "rank_spreads": spreads,
        "rank_by_strategy": rank_by_strategy,
    }


def print_rank_changes(changes: dict) -> None:
    print("\n" + "=" * 100)
    print(f"Rank Changes（比較三種 strategy 的 Top {changes['top_n']}）")
    print("=" * 100)

    print(f"\n  三種方法都進 Top {changes['top_n']} 的 candidate"
          f"（{len(changes['in_all_three_tops'])} 個）：")
    if changes["in_all_three_tops"]:
        for cid in changes["in_all_three_tops"]:
            ranks = changes["rank_by_strategy"]
            print(f"    {cid}")
            print(f"        A={ranks['A_PRODUCT_FIRST'][cid]}"
                  f"  B={ranks['B_MAGNITUDE_FIRST'][cid]}"
                  f"  C={ranks['C_SAMPLE_AWARE'][cid]}")
    else:
        print("    （沒有）")

    print(f"\n  只有某一種方法進 Top {changes['top_n']} 的 candidate：")
    for s in STRATEGY_ORDER:
        ids = changes["only_in_one_top"][s]
        print(f"    {s}（{len(ids)} 個）：")
        if not ids:
            print("        （沒有）")
        for cid in ids:
            ranks = changes["rank_by_strategy"]
            print(f"        {cid}")
            print(f"            A={ranks['A_PRODUCT_FIRST'][cid]}"
                  f"  B={ranks['B_MAGNITUDE_FIRST'][cid]}"
                  f"  C={ranks['C_SAMPLE_AWARE'][cid]}")

    print("\n  排名差異最大的 candidate（spread = 最大名次 − 最小名次）：")
    print(f"    {'candidate_id':<52} {'A':>3} {'B':>3} {'C':>3} {'spread':>7}")
    for d in changes["rank_spreads"][:12]:
        print(f"    {d['candidate_id']:<52} "
              f"{d['ranks']['A_PRODUCT_FIRST']:>3} "
              f"{d['ranks']['B_MAGNITUDE_FIRST']:>3} "
              f"{d['ranks']['C_SAMPLE_AWARE']:>3} {d['spread']:>7}")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = (
    "final_score", "score", "confidence", "importance", "weight", "weighted",
    "reliability_score", "p_value",
)
FORBIDDEN_WORDS = (
    "strength", "weakness", "advantage", "disadvantage", "statistically significant",
    "statistical significance", "p-value", "confidence interval",
    "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差", "建議", "應該",
    "統計顯著", "顯著性", "顯著", "最佳", "最好", "最差", "值得注意",
)
DECLARATIVE_FIELDS = ("no_weighting_note", "null_handling", "magnitude_definition",
                      "philosophy")


def scan_keys(obj, path="") -> list:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            for bad in FORBIDDEN_KEYS:
                if bad in kl:
                    found.append(f"{path}.{k}")
            found += scan_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += scan_keys(v, f"{path}[{i}]")
    return found


def run_validation(
    candidates_before: list,
    candidates_after: list,
    views: list,
    rankings: dict,
    changes: dict,
    fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    n = len(candidates_after)
    all_ids = {c["candidate_id"] for c in candidates_after}

    # 1. 三種 strategy 使用完全相同的 29 candidates
    id_sets = {s: {row["candidate_id"] for row in r} for s, r in rankings.items()}
    same_ids = all(v == all_ids for v in id_sets.values())
    checks.append(
        (f"三種 strategy 都使用完全相同的 {n} 個 candidate", same_ids and n == 29,
         f"candidates={n}　" + "　".join(f"{s}={len(v)}" for s, v in id_sets.items())
         + f"　id 集合相同={same_ids}")
    )

    # 2. 每種 strategy 都產生完整 deterministic ordering
    order_bad = []
    for s, r in rankings.items():
        ranks = [row["rank"] for row in r]
        if ranks != list(range(1, n + 1)):
            order_bad.append(f"{s} 名次不連續")
        if len({row["candidate_id"] for row in r}) != n:
            order_bad.append(f"{s} 有重複 candidate")
        # 全序檢查：相鄰兩筆的排序鍵必須嚴格遞增（沒有並列）
        keyf = KEY_FUNCS[s]
        for i in range(n - 1):
            if not keyf(r[i]) < keyf(r[i + 1]):
                order_bad.append(f"{s} 第 {i + 1} 與 {i + 2} 名排序鍵未嚴格遞增")
    checks.append(
        ("每種 strategy 都產生完整且嚴格全序的 ordering", not order_bad,
         f"三種各 1~{n} 名，無並列、無重複"
         if not order_bad else "；".join(order_bad[:5]))
    )

    # 3. Top 10 都存在於原始 29 candidates
    top_bad = []
    for s, r in rankings.items():
        for row in r[:TOP_N]:
            if row["candidate_id"] not in all_ids:
                top_bad.append(f"{s}: {row['candidate_id']}")
    checks.append(
        (f"三種 strategy 的 Top {TOP_N} 全部存在於原始 candidate 清單", not top_bad,
         f"30 筆（3 × {TOP_N}）全部可對應" if not top_bad else "；".join(top_bad))
    )

    # 4. 沒有 candidate evidence 被修改
    same = candidates_before == candidates_after
    checks.append(
        ("candidate evidence 完全未被修改（深度比較 29 個物件）", same,
         "view 是唯讀複製，沒有寫回路徑；逐欄位比較完全相同"
         if same else "有物件被改動")
    )

    # 排序用的描述子必須與 candidate 原值相符
    view_by_id = {v["candidate_id"]: v for v in views}
    copy_bad = []
    for c in candidates_after:
        v = view_by_id[c["candidate_id"]]
        expected_mag, expected_metric, _ = magnitude_of(c)
        if v["magnitude"] != expected_mag or v["magnitude_metric"] != expected_metric:
            copy_bad.append(f"{c['candidate_id']} magnitude")
        if v["percentile_rank"] != percentile_of(c):
            copy_bad.append(f"{c['candidate_id']} percentile")
        if v["consistency_count"] != consistency_of(c):
            copy_bad.append(f"{c['candidate_id']} consistency")
        if v["sample_size_at_bats"] != c["at_bats"]:
            copy_bad.append(f"{c['candidate_id']} at_bats")
    checks.append(
        ("排序使用的描述子皆為 candidate 原值，未重算或修改", not copy_bad,
         "29 個全部相符" if not copy_bad else "；".join(copy_bad[:5]))
    )

    # 5. 沒有 HTTP request
    checks.append(
        ("沒有任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖，"
         "資料全部來自本地檔案")
    )

    # 6. raw / processed hash 不變
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data hash 不變", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    payload = {"rankings": rankings, "changes": changes, "views": views}
    blob = json.dumps(payload, ensure_ascii=False)
    declarative = json.dumps(
        [
            {k: v for k, v in rule.items() if k in DECLARATIVE_FIELDS}
            for rule in STRATEGY_RULES.values()
        ]
        + [v["magnitude_definition"] for v in views],
        ensure_ascii=False,
    )

    # 7 / 8 / 10. 沒有 final score / weight / confidence score
    score_keys = scan_keys(payload)
    checks.append(
        ("沒有 final_score / importance_score / 任何 score 欄位", not score_keys,
         "輸出中沒有任何分數欄位" if not score_keys
         else "；".join(sorted(set(score_keys))[:8]))
    )
    weight_keys = [k for k in score_keys if "weight" in k.lower()]
    checks.append(
        ("沒有 weight 欄位或加權合成", not weight_keys,
         "三種 strategy 全部使用字典序 tuple，鍵之間沒有任何係數"
         if not weight_keys else "；".join(weight_keys))
    )
    conf_keys = [k for k in score_keys if "confidence" in k.lower()]
    checks.append(
        ("沒有 confidence score", not conf_keys,
         "沒有" if not conf_keys else "；".join(conf_keys))
    )

    # 9. 沒有 threshold
    thr = []
    for w in ("threshold", "門檻", "cutoff", "minimum_ab", "min_at_bats"):
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            thr.append(f"{w}×{cnt}")
    all_ranked = all(len(r) == n for r in rankings.values())
    checks.append(
        ("沒有 threshold：三種 strategy 都對全部 29 個 candidate 排序，沒有任何被排除",
         all_ranked and not thr,
         f"三種各排 {n} 個，全部入榜（Top {TOP_N} 只是呈現切點，不是過濾）"
         + ("" if not thr else f"　可疑字眼 {thr}"))
    )

    # 11. 沒有自然語言結論
    concl = []
    for w in FORBIDDEN_WORDS:
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            concl.append(f"{w}×{cnt}")
    checks.append(
        ("沒有自然語言結論或價值判斷字眼", not concl,
         "未出現禁用字眼（strategy 說明欄位已扣除）"
         if not concl else "、".join(concl))
    )

    # 12. null percentile 沒有被當成 0
    #     用會在 None 數值比較時拋錯的嚴格 comparator 重跑排序，比對結果是否相同
    strict_ok, strict_detail = True, []
    for s in STRATEGY_ORDER:
        try:
            strict_order = sorted(views, key=functools.cmp_to_key(CMP_FUNCS[s]))
        except NullComparisonError as exc:
            strict_ok = False
            strict_detail.append(f"{s}: {exc}")
            continue
        tuple_order = [row["candidate_id"] for row in rankings[s]]
        if [v["candidate_id"] for v in strict_order] != tuple_order:
            strict_ok = False
            strict_detail.append(f"{s}: 嚴格 comparator 的順序與 tuple 排序不同")
    null_pct_ids = [v["candidate_id"] for v in views if v["percentile_rank"] is None]
    checks.append(
        ("null percentile 沒有被當成 0（以嚴格 comparator 反證）", strict_ok,
         f"{len(null_pct_ids)} 個 candidate 的 percentile_rank 為 null；"
         "嚴格 comparator（遇到 None 數值比較即拋錯）產生的順序與 tuple 排序完全相同，"
         "證明 null 從未參與數值比較"
         if strict_ok else "；".join(strict_detail))
    )

    # 13. 同一次執行重跑結果完全一致（並用打亂輸入順序驗證排序為全序）
    repeat_bad = []
    rng = random.Random(20261120)
    for s in STRATEGY_ORDER:
        again = [row["candidate_id"] for row in rank(views, s)]
        if again != [row["candidate_id"] for row in rankings[s]]:
            repeat_bad.append(f"{s} 重跑結果不同")
        shuffled = views[:]
        rng.shuffle(shuffled)
        from_shuffled = [row["candidate_id"] for row in rank(shuffled, s)]
        if from_shuffled != [row["candidate_id"] for row in rankings[s]]:
            repeat_bad.append(f"{s} 打亂輸入順序後結果不同")
    checks.append(
        ("重跑與打亂輸入順序後結果完全一致（deterministic 且不依賴輸入順序）",
         not repeat_bad,
         "三種 strategy 各重跑一次 + 各以打亂順序跑一次，六次結果全部相同"
         if not repeat_bad else "；".join(repeat_bad))
    )

    # 額外：文件記錄的排序鍵數量必須與實際 tuple 長度一致
    #      （若不一致，排序鍵作用診斷的位置對照會錯，文件也會與實作不符）
    align_bad = []
    for s in STRATEGY_ORDER:
        labels = STRATEGY_RULES[s]["lexicographic_key"]
        tuple_len = len(KEY_FUNCS[s](views[0]))
        if len(labels) != tuple_len:
            align_bad.append(f"{s}: 文件 {len(labels)} 個鍵 vs 實際 tuple {tuple_len} 位")
    checks.append(
        ("文件記錄的排序鍵數量與實作 tuple 長度一致", not align_bad,
         "　".join(f"{s}={len(KEY_FUNCS[s](views[0]))} 位" for s in STRATEGY_ORDER)
         if not align_bad else "；".join(align_bad))
    )

    # 額外：排序鍵作用診斷的計數總和必須等於相鄰名次組數
    diag_bad = []
    for s in STRATEGY_ORDER:
        rep = deciding_key_report(views, s, rankings[s])
        total = sum(rep["decided_counts"].values())
        if total != rep["pairs"]:
            diag_bad.append(f"{s}: 計數合計 {total} != 相鄰組數 {rep['pairs']}")
    checks.append(
        ("排序鍵作用診斷的計數合計等於相鄰名次組數（證明每組都有鍵決定）",
         not diag_bad,
         f"三種 strategy 各 {n - 1} 組，合計皆相符"
         if not diag_bad else "；".join(diag_bad))
    )

    # 14. 每個 ranking result 都能 trace 回 candidate_id
    trace_bad = []
    for s, r in rankings.items():
        for row in r:
            if "candidate_id" not in row or row["candidate_id"] not in all_ids:
                trace_bad.append(f"{s} 有無法追溯的結果")
            if row.get("strategy") != s:
                trace_bad.append(f"{s} 的 strategy 標記錯誤")
    checks.append(
        ("每個 ranking result 都帶 candidate_id 且可對應回原始 candidate",
         not trace_bad,
         f"3 × {n} = {3 * n} 筆結果全部可追溯，且都標記所屬 strategy"
         if not trace_bad else "；".join(trace_bad[:5]))
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
    pattern, _ = build_pattern_candidates(contexts, season)
    candidates = trend + context_cands + pattern
    candidates_before = copy.deepcopy(candidates)

    trend_components = build_trend_components(logs)
    sample_records = {
        c["candidate_id"]: build_record(c, trend_components, contexts)
        for c in candidates
    }
    views = [build_view(c, sample_records[c["candidate_id"]]) for c in candidates]

    print("=" * 100)
    print("Ranking Strategy Experiment（Step 12）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print(f"輸入：Step 9 的 {len(candidates)} 個 candidate（三種 strategy 共用同一批）")
    print("這一步只實驗不同的排序哲學，不決定哪一種是對的。")
    print("沒有 final score、沒有 weight、沒有 threshold、沒有 confidence score。")
    print("=" * 100)

    rankings = {s: rank(views, s) for s in STRATEGY_ORDER}
    for s in STRATEGY_ORDER:
        print_ranking(s, rankings[s])

    key_reports = [
        deciding_key_report(views, s, rankings[s]) for s in STRATEGY_ORDER
    ]
    print_deciding_keys(key_reports)

    changes = analyse_rank_changes(rankings)
    print_rank_changes(changes)

    print("\n" + "=" * 100)
    print("Validation")
    print("=" * 100)
    checks = run_validation(
        candidates_before, candidates, views, rankings, changes, fingerprints_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/RANKING_STRATEGY_EXPERIMENT.md。")

    print("\n" + "=" * 100)
    print("本階段沒有選出最佳 strategy。三種結果與差異留給下一階段討論。")
    print("=" * 100)


if __name__ == "__main__":
    main()

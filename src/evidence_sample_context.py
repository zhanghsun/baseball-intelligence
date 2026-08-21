"""Evidence Sample Context / Sensitivity 分析（Step 11）。

它做什麼：讓系統知道「一個 candidate 的數字背後有多少資料支撐」，
以及「比率對單一事件有多敏感」。

它**不**做什麼：
    - 不刪除任何 candidate（29 個全部保留）
    - 不設定 minimum AB / minimum PA 門檻
    - 不建立 confidence_score / evidence_score / reliability_score / importance_score
    - 不做統計顯著性宣稱、不算 p-value
    - 不產生自然語言結論、不使用 LLM
    - 不發任何 HTTP 請求
    - 不修改 Step 9 的 candidate 或任何來源資料

方法：**count-based sensitivity**。把比率拆回分子與分母，
再看「分子多 1」與「分子少 1」會讓比率變成多少。
這是純算術，沒有任何機率模型、沒有分布假設。

設計選擇：與 Step 10 相同，產出是獨立的 sidecar，用 candidate_id 關聯，
不寫回 candidate 物件，因此「來源 evidence 未被修改」是結構性成立的。

用法：
    python src/evidence_sample_context.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 匯入 Step 9。import 時就會安裝網路封鎖 guard。
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
from candidate_priority import GRANULARITY_BY_TYPE  # noqa: E402
from player_form_analysis import build_window, sort_by_date  # noqa: E402

WINDOW_SIZES = {"RECENT_10": 10, "RECENT_15": 15}

# 每個 candidate 都會帶這個清單，明確宣告它不是什麼。
# 字眼掃描時會扣除這個欄位的內容（與 Step 10 的處理方式一致）。
NOT_A = [
    "confidence",
    "confidence_score",
    "evidence_score",
    "reliability_score",
    "importance_score",
    "statistical_significance",
    "p_value",
    "probability",
]

SENSITIVITY_NOTE = (
    "sample_sensitivity 是純算術：把比率拆回分子分母，看分子加減 1 的結果。"
    "沒有機率模型、沒有分布假設，也不代表任何可信程度。"
)


# ------------------------------------------------------------------ 工具

def ratio(numerator: int, denominator: int) -> float | None:
    if denominator is None or numerator is None or denominator == 0:
        return None
    return numerator / denominator


def fmt(value: float | None, digits: int = 8) -> str:
    return "null" if value is None else f"{value:.{digits}f}"


# ------------------------------------------------------------------ Part 2 / Part 3

def build_sensitivity(
    metric: str,
    numerator: int | None,
    denominator: int | None,
    numerator_label: str,
    denominator_label: str,
    success_unit: str,
    unavailable_reason: str | None = None,
) -> dict:
    """count-based sensitivity。分子或分母不足時回傳 null，不估算。"""
    base = {
        "metric": metric,
        "numerator_label": numerator_label,
        "denominator_label": denominator_label,
        "numerator": numerator,
        "denominator": denominator,
        "success_unit": success_unit,
        "_note": SENSITIVITY_NOTE,
        "_not_a": list(NOT_A),
    }

    if unavailable_reason is not None or numerator is None or denominator is None:
        base.update(
            {
                "available": False,
                "unavailable_reason": unavailable_reason or "分子或分母資料不足",
                "current": None,
                "one_more_success": None,
                "one_fewer_success": None,
                "delta_if_one_more": None,
                "delta_if_one_fewer": None,
            }
        )
        return base

    if denominator == 0:
        base.update(
            {
                "available": False,
                "unavailable_reason": "分母為 0，比率無定義",
                "current": None,
                "one_more_success": None,
                "one_fewer_success": None,
                "delta_if_one_more": None,
                "delta_if_one_fewer": None,
            }
        )
        return base

    current = numerator / denominator
    one_more = (numerator + 1) / denominator
    # 分子不可為負，因此 numerator == 0 時「少一次」無定義
    one_fewer = (numerator - 1) / denominator if numerator >= 1 else None

    base.update(
        {
            "available": True,
            "unavailable_reason": None,
            "current": current,
            "one_more_success": one_more,
            "one_fewer_success": one_fewer,
            "delta_if_one_more": one_more - current,
            "delta_if_one_fewer": None if one_fewer is None else one_fewer - current,
            "one_fewer_note": (
                None if one_fewer is not None
                else f"{numerator_label} 已為 0，無法再減少，因此 one_fewer 為 null"
            ),
        }
    )
    return base


def sensitivity_for_avg(hits: int, at_bats: int) -> dict:
    return build_sensitivity(
        "batting_average", hits, at_bats, "hits", "at_bats",
        "一支安打（把一個出局換成一支安打，打數不變）",
    )


def sensitivity_for_slg(total_bases: int, at_bats: int) -> dict:
    return build_sensitivity(
        "slugging_percentage", total_bases, at_bats, "total_bases", "at_bats",
        "一個壘打數（不是一支安打；一支安打可能帶 1~4 個壘打數）",
    )


def sensitivity_for_obp(
    hits: int | None, walks: int | None, hbp: int | None,
    at_bats: int | None, sf: int | None,
    unavailable_reason: str | None = None,
) -> dict:
    if unavailable_reason is not None or None in (hits, walks, hbp, at_bats, sf):
        return build_sensitivity(
            "on_base_percentage", None, None,
            "hits + walks + hit_by_pitch",
            "at_bats + walks + hit_by_pitch + sacrifice_flies",
            "一次上壘（把一個出局換成一次上壘，分母不變）",
            unavailable_reason=unavailable_reason or "缺少 walks / hit_by_pitch / sacrifice_flies",
        )
    return build_sensitivity(
        "on_base_percentage",
        hits + walks + hbp,
        at_bats + walks + hbp + sf,
        "hits + walks + hit_by_pitch",
        "at_bats + walks + hit_by_pitch + sacrifice_flies",
        "一次上壘（把一個出局換成一次上壘，分母不變）",
    )


# ------------------------------------------------------------------ Part 1 / Part 4

def build_trend_components(logs: list) -> dict:
    """重建 Recent 10 / 15 窗口，取得 hits / total_bases 等分子分母成分。

    使用與 Step 9 相同的 build_window()，不引入新資料。
    """
    games = sort_by_date(logs)
    out = {}
    for name, size in WINDOW_SIZES.items():
        w = build_window(f"Recent {size} Games", games[-size:])
        out[name] = {
            "games": w["games"],
            "at_bats": w["at_bats"],
            "plate_appearances": w["plate_appearances"],
            "hits": w["hits"],
            "total_bases": w["total_bases"],
            "walks": w["walks"],
            "hit_by_pitch": w["hit_by_pitch"],
            # 逐場 processed data 未收犧牲飛球，因此 OBP 分母無法組出
            "sacrifice_flies": None,
            "first_game_date": w["first_game_date"],
            "last_game_date": w["last_game_date"],
            "game_snos": list(w["game_snos"]),
            "batting_average": w["batting_average"],
            "slugging": w["slugging"],
        }
    return out


def build_record(
    candidate: dict, trend_components: dict, contexts: dict
) -> dict:
    """為一個 candidate 產生 sample context + sensitivity 的 sidecar。"""
    ctype = candidate["type"]
    granularity = GRANULARITY_BY_TYPE[ctype]

    if ctype == "TREND":
        window_name = candidate["window"]["name"]
        comp = trend_components[window_name]
        sample_context = {
            "at_bats": comp["at_bats"],
            "plate_appearances": comp["plate_appearances"],
            "games": comp["games"],
            "metric": candidate["metric"],
            "context": None,
            "context_note": "TREND 沒有情境切分，範圍是最近 N 場實際出賽",
            "granularity": granularity,
            "window_name": window_name,
            "date_range": {
                "first_game_date": comp["first_game_date"],
                "last_game_date": comp["last_game_date"],
            },
            "game_snos": comp["game_snos"],
            "data_source": {
                "files": ["data/processed/zhang_yucheng_game_logs_2026.json"],
                "origin": "CPBL 官方 POST /team/getfollowscore（Step 2 取得，Step 4 整理）",
                "derivation": (
                    f"依 (game_date, game_sno) 升冪排序後取最後 "
                    f"{WINDOW_SIZES[window_name]} 場，逐場加總"
                ),
            },
        }
        sens = {
            "batting_average": sensitivity_for_avg(comp["hits"], comp["at_bats"]),
            "slugging_percentage": sensitivity_for_slg(
                comp["total_bases"], comp["at_bats"]
            ),
            "on_base_percentage": sensitivity_for_obp(
                comp["hits"], comp["walks"], comp["hit_by_pitch"],
                comp["at_bats"], comp["sacrifice_flies"],
                unavailable_reason=(
                    "processed data 未收逐場犧牲飛球，OBP 分母無法組出。"
                    "依規則回傳 null，不估算。"
                ),
            ),
        }
        # 只保留該 candidate 實際使用的指標，另外附上同窗口其他指標供參考
        primary_metric = candidate["metric"]

    else:
        code = candidate["context"]["code"]
        ctx = contexts[code]
        cf = ctx  # build_context 的輸出已含全部計數欄位
        sample_context = {
            "at_bats": ctx["at_bats"],
            "plate_appearances": ctx["plate_appearances"],
            "games": None,
            "games_note": "官方分項成績沒有出賽場次欄位，因此 games 為 null，不推估",
            "metric": candidate.get("metric"),
            "context": {
                "code": code,
                "official_item_name": ctx["item_name"],
                "group": candidate["context"].get("group"),
            },
            "granularity": granularity,
            "window_name": None,
            "date_range": {
                "first_game_date": None,
                "last_game_date": None,
                "note": "官方分項不提供日期",
            },
            "game_snos": None,
            "data_source": {
                "files": ["data/raw/apart_score_0000006888_2026_A_01.json"],
                "origin": (
                    "CPBL 官方 POST /team/getapartscore，ItemGroupCode = 3"
                    "（Step 8 取得並快取）"
                ),
                "derivation": "官方直接提供的球季累計分項，未再加工",
            },
        }
        sens = {
            "batting_average": sensitivity_for_avg(cf["hits"], cf["at_bats"]),
            "slugging_percentage": sensitivity_for_slg(
                cf["total_bases"], cf["at_bats"]
            ),
            "on_base_percentage": sensitivity_for_obp(
                cf["hits"], cf["walks"], cf["hit_by_pitch"],
                cf["at_bats"], cf["sacrifice_flies"],
            ),
        }
        primary_metric = candidate.get("metric")

    if ctype == "MULTI_METRIC_PATTERN":
        primary_metrics = list(candidate["metrics"])
    else:
        primary_metrics = [primary_metric]

    completeness = {
        "metrics_with_sensitivity": [
            m for m, s in sens.items() if s["available"]
        ],
        "metrics_without_sensitivity": [
            m for m, s in sens.items() if not s["available"]
        ],
        "sensitivity_unavailable_reasons": {
            m: s["unavailable_reason"] for m, s in sens.items() if not s["available"]
        },
        "has_game_count": sample_context["games"] is not None,
        "has_date_range": sample_context["date_range"]["first_game_date"] is not None,
        "has_game_snos": sample_context["game_snos"] is not None,
    }

    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_type": ctype,
        "primary_metrics": primary_metrics,
        "sample_context": sample_context,
        "sample_sensitivity": sens,
        "data_completeness": completeness,
        "traceability": {
            "source_files": list(candidate["source_files"]),
            "source_evidence": list(candidate["source_evidence"]),
            "sensitivity_derivation": (
                "分子分母取自同一份來源資料的原始計數，"
                "one_more / one_fewer 為分子 ±1 後重算，分母固定"
            ),
        },
        "retained": True,
        "retention_note": (
            "無論樣本大小，一律保留。本階段沒有 minimum AB / minimum PA 門檻。"
        ),
        "contains_no": [
            "confidence_score", "evidence_score", "reliability_score",
            "importance_score", "statistical_significance", "p_value",
            "threshold", "final_score", "weight",
        ],
    }


# ------------------------------------------------------------------ 輸出

def print_records(records: list) -> None:
    by_type: dict[str, list] = {}
    for r in records:
        by_type.setdefault(r["candidate_type"], []).append(r)

    for ctype in ("TREND", "MULTI_METRIC_PATTERN", "CONTEXT"):
        group = sorted(by_type.get(ctype, []), key=lambda r: r["candidate_id"])
        if not group:
            continue
        print("\n" + "=" * 96)
        print(f"{ctype}（{len(group)} 個，granularity = "
              f"{group[0]['sample_context']['granularity']}）")
        print("=" * 96)
        for r in group:
            sc = r["sample_context"]
            print(f"\n  {r['candidate_id']}")
            print(f"    sample context: AB={sc['at_bats']}  PA={sc['plate_appearances']}"
                  f"  games={sc['games']}"
                  f"  granularity={sc['granularity']}")
            if sc["context"]:
                print(f"                    context={sc['context']['code']}"
                      f"（官方 {sc['context']['official_item_name']}）")
            else:
                print(f"                    context=None  window={sc['window_name']}"
                      f"  日期 {sc['date_range']['first_game_date']}"
                      f" ~ {sc['date_range']['last_game_date']}")
            print(f"    data source   : {sc['data_source']['files'][0]}")
            print(f"    primary metric(s): {', '.join(r['primary_metrics'])}")
            for metric in r["primary_metrics"]:
                s = r["sample_sensitivity"][metric]
                if not s["available"]:
                    print(f"    sensitivity [{metric}]: null"
                          f"　原因：{s['unavailable_reason']}")
                    continue
                print(f"    sensitivity [{metric}]:"
                      f" {s['numerator']} / {s['denominator']}"
                      f" = {fmt(s['current'])}")
                print(f"        one_more_success  = {s['numerator'] + 1}"
                      f" / {s['denominator']} = {fmt(s['one_more_success'])}"
                      f"　delta {fmt(s['delta_if_one_more'])}")
                if s["one_fewer_success"] is None:
                    print(f"        one_fewer_success = null"
                          f"　{s.get('one_fewer_note')}")
                else:
                    print(f"        one_fewer_success = {s['numerator'] - 1}"
                          f" / {s['denominator']} = {fmt(s['one_fewer_success'])}"
                          f"　delta {fmt(s['delta_if_one_fewer'])}")
                print(f"        success_unit      = {s['success_unit']}")
            print(f"    retained={r['retained']}"
                  f"  metrics_without_sensitivity="
                  f"{r['data_completeness']['metrics_without_sensitivity']}")


def print_sample_size_table(records: list) -> None:
    print("\n" + "=" * 96)
    print("Sample size 一覽（依 at_bats 由小到大排列，僅為呈現順序，不是排名）")
    print("=" * 96)
    seen: dict[tuple, dict] = {}
    for r in records:
        sc = r["sample_context"]
        key = (
            r["candidate_type"],
            sc["window_name"] or (sc["context"]["code"] if sc["context"] else None),
        )
        seen.setdefault(key, {"ab": sc["at_bats"], "pa": sc["plate_appearances"],
                              "games": sc["games"], "gran": sc["granularity"],
                              "n": 0})
        seen[key]["n"] += 1
    print(f"  {'type':<22} {'scope':<14} {'AB':>4} {'PA':>4} {'games':>6}"
          f" {'granularity':<20} {'candidates':>10}")
    for (ctype, scope), v in sorted(seen.items(), key=lambda kv: kv[1]["ab"]):
        print(f"  {ctype:<22} {str(scope):<14} {v['ab']:>4} {v['pa']:>4}"
              f" {str(v['games']):>6} {v['gran']:<20} {v['n']:>10}")
    print("\n  一次事件對 AVG 的影響 = 1 / AB：")
    for (ctype, scope), v in sorted(seen.items(), key=lambda kv: kv[1]["ab"]):
        print(f"    {str(scope):<14} AB={v['ab']:>4}"
              f"　1/AB = {1 / v['ab']:.8f}")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_SCORE_KEYS = (
    "confidence", "reliability_score", "importance", "evidence_score",
    "final_score", "score", "weight", "p_value", "pvalue",
)
FORBIDDEN_SIG_WORDS = (
    "statistically significant", "statistical significance", "p-value", "p value",
    "confidence interval", "significant", "統計顯著", "顯著性", "顯著", "信賴區間",
)
FORBIDDEN_CONCLUSION_WORDS = (
    "strength", "weakness", "advantage", "disadvantage",
    "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差", "不可信",
    "建議", "應該", "值得注意", "表現很好", "表現不佳", "可信度",
)
DECLARATIVE_KEYS = ("_not_a", "contains_no")


def scan_keys(obj, path="") -> list:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if k not in DECLARATIVE_KEYS:
                for bad in FORBIDDEN_SCORE_KEYS:
                    if bad in kl:
                        found.append(f"{path}.{k}")
                found += scan_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += scan_keys(v, f"{path}[{i}]")
    return found


def collect_declarative(records: list) -> str:
    items = []
    for r in records:
        items.append(r["contains_no"])
        for s in r["sample_sensitivity"].values():
            items.append(s["_not_a"])
        items.append(r["retention_note"])
    return json.dumps(items, ensure_ascii=False)


def run_validation(
    candidates_before: list,
    candidates_after: list,
    records: list,
    trend_components: dict,
    contexts: dict,
    fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    n = len(candidates_after)
    by_id = {r["candidate_id"]: r for r in records}

    # 1. 29 candidates 全部保留
    ok = len(records) == n == 29 and all(r["retained"] for r in records)
    checks.append(
        (f"{n} 個 candidate 全部保留", ok,
         f"candidates={n}　records={len(records)}　"
         f"retained=True 的數量={sum(1 for r in records if r['retained'])}")
    )

    # 2. 沒有 candidate 被 sample size 過濾
    ab_values = sorted({r["sample_context"]["at_bats"] for r in records})
    missing = [c["candidate_id"] for c in candidates_after
               if c["candidate_id"] not in by_id]
    checks.append(
        ("沒有任何 candidate 因 sample size 被過濾", not missing,
         f"最小 AB = {ab_values[0]}（仍保留）　最大 AB = {ab_values[-1]}　"
         f"全部 {len(records)} 個都有記錄"
         + ("" if not missing else f"　缺：{missing}"))
    )

    # 3. AVG sensitivity 可由 H/AB 重算
    bad_avg = []
    for r in records:
        s = r["sample_sensitivity"]["batting_average"]
        if not s["available"]:
            bad_avg.append(f"{r['candidate_id']} AVG sensitivity 不可用")
            continue
        expected = s["numerator"] / s["denominator"]
        if abs(expected - s["current"]) > 1e-12:
            bad_avg.append(f"{r['candidate_id']} 重算不符")
        if abs((s["numerator"] + 1) / s["denominator"] - s["one_more_success"]) > 1e-12:
            bad_avg.append(f"{r['candidate_id']} one_more 不符")
        if s["one_fewer_success"] is not None and abs(
            (s["numerator"] - 1) / s["denominator"] - s["one_fewer_success"]
        ) > 1e-12:
            bad_avg.append(f"{r['candidate_id']} one_fewer 不符")
    checks.append(
        ("AVG sensitivity 可由 hits / at_bats 重算", not bad_avg,
         f"{len(records)} 個全部可重算" if not bad_avg else "；".join(bad_avg[:5]))
    )

    # 4. SLG sensitivity 可由 TB/AB 重算
    bad_slg = []
    for r in records:
        s = r["sample_sensitivity"]["slugging_percentage"]
        if not s["available"]:
            bad_slg.append(f"{r['candidate_id']} SLG sensitivity 不可用")
            continue
        if abs(s["numerator"] / s["denominator"] - s["current"]) > 1e-12:
            bad_slg.append(f"{r['candidate_id']} 重算不符")
    checks.append(
        ("SLG sensitivity 可由 total_bases / at_bats 重算", not bad_slg,
         f"{len(records)} 個全部可重算" if not bad_slg else "；".join(bad_slg[:5]))
    )

    # 5. OBP sensitivity 僅在資料完整時計算
    obp_trend_null = [
        r["candidate_id"] for r in records if r["candidate_type"] == "TREND"
        and r["sample_sensitivity"]["on_base_percentage"]["available"]
    ]
    obp_ctx_bad = []
    for r in records:
        if r["candidate_type"] == "TREND":
            continue
        s = r["sample_sensitivity"]["on_base_percentage"]
        if not s["available"]:
            obp_ctx_bad.append(f"{r['candidate_id']} 應可計算但為 null")
            continue
        if abs(s["numerator"] / s["denominator"] - s["current"]) > 1e-12:
            obp_ctx_bad.append(f"{r['candidate_id']} 重算不符")
    checks.append(
        ("OBP sensitivity 僅在資料完整時計算（TREND 為 null，CONTEXT/PATTERN 可算）",
         not obp_trend_null and not obp_ctx_bad,
         f"TREND 4 個全部為 null（缺逐場犧牲飛球）；"
         f"CONTEXT/PATTERN {len(records) - 4} 個全部可重算"
         + ("" if not obp_trend_null else f"　TREND 異常：{obp_trend_null}")
         + ("" if not obp_ctx_bad else f"　異常：{obp_ctx_bad[:5]}"))
    )

    # OBP 交叉核對：CONTEXT candidate 的 sensitivity current 應等於 candidate 的 OBP 值
    obp_cross = []
    for c in candidates_after:
        if c["type"] != "CONTEXT" or c["metric"] != "on_base_percentage":
            continue
        s = by_id[c["candidate_id"]]["sample_sensitivity"]["on_base_percentage"]
        if abs(s["current"] - c["value"]) > 1e-12:
            obp_cross.append(c["candidate_id"])
    checks.append(
        ("CONTEXT 的 OBP sensitivity current 與 Step 9 candidate 值相符", not obp_cross,
         "7 個 OBP candidate 全部相符" if not obp_cross else "；".join(obp_cross))
    )

    # AVG / SLG 交叉核對
    metric_cross = []
    for c in candidates_after:
        rec = by_id[c["candidate_id"]]
        if c["type"] == "TREND":
            s = rec["sample_sensitivity"][c["metric"]]
            if abs(s["current"] - c["current_value"]) > 1e-12:
                metric_cross.append(c["candidate_id"])
        elif c["type"] == "CONTEXT":
            s = rec["sample_sensitivity"][c["metric"]]
            if abs(s["current"] - c["value"]) > 1e-12:
                metric_cross.append(c["candidate_id"])
        else:
            for metric, mv in c["metric_values"].items():
                s = rec["sample_sensitivity"][metric]
                if not s["available"] or abs(s["current"] - mv["value"]) > 1e-12:
                    metric_cross.append(f"{c['candidate_id']}/{metric}")
    checks.append(
        ("所有 sensitivity 的 current 與 Step 9 candidate 的值完全相符",
         not metric_cross,
         "29 個 candidate 的全部主要指標皆相符"
         if not metric_cross else "；".join(metric_cross[:5]))
    )

    blob = json.dumps(records, ensure_ascii=False)
    declarative = collect_declarative(records)

    # 6 / 7. 沒有 confidence score、沒有 reliability score
    score_keys = scan_keys(records)
    checks.append(
        ("沒有 confidence_score / evidence_score / 任何 score 欄位", not score_keys,
         "全部欄位名皆為 descriptor，沒有分數欄位"
         if not score_keys else "；".join(sorted(set(score_keys))[:8]))
    )
    rel_keys = [k for k in score_keys if "reliability" in k.lower()]
    checks.append(
        ("沒有 reliability_score 欄位", not rel_keys,
         "沒有" if not rel_keys else "；".join(rel_keys))
    )

    # 8. 沒有 threshold
    thr_hits = []
    for w in ("threshold", "門檻", "cutoff", "minimum_ab", "minimum_pa", "min_at_bats"):
        count = blob.count(w) - declarative.count(w)
        if count > 0:
            thr_hits.append(f"{w}×{count}")
    checks.append(
        ("沒有 threshold（含 minimum AB / minimum PA）", not thr_hits,
         f"29/29 全部保留，最小 AB = {ab_values[0]} 也沒有被降級或標記"
         + ("" if not thr_hits else f"　可疑字眼 {thr_hits}"))
    )

    # 9. 沒有統計顯著性
    lower_blob, lower_dec = blob.lower(), declarative.lower()
    sig_hits = []
    for w in FORBIDDEN_SIG_WORDS:
        wl = w.lower()
        count = lower_blob.count(wl) - lower_dec.count(wl)
        if count > 0:
            sig_hits.append(f"{w}×{count}")
    checks.append(
        ("沒有統計顯著性宣稱或 p-value", not sig_hits,
         "未出現顯著性相關字眼（_not_a / contains_no 中的否定宣告已扣除）"
         if not sig_hits else "、".join(sig_hits))
    )

    # 10. 沒有自然語言結論
    concl_hits = []
    for w in FORBIDDEN_CONCLUSION_WORDS:
        count = blob.count(w) - declarative.count(w)
        if count > 0:
            concl_hits.append(f"{w}×{count}")
    checks.append(
        ("沒有自然語言結論或價值判斷字眼", not concl_hits,
         "未出現禁用字眼" if not concl_hits else "、".join(concl_hits))
    )

    # 11. source evidence 沒有被修改
    same = candidates_before == candidates_after
    checks.append(
        ("Step 9 candidate 完全未被改動（深度比較 29 個物件）", same,
         "sidecar 設計，沒有寫回路徑；逐欄位比較完全相同"
         if same else "有物件被改動")
    )

    # 12. raw / processed hash 不變
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data hash 不變", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    # 13. 沒有 HTTP request
    checks.append(
        ("沒有任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖，"
         "資料全部來自本地檔案")
    )

    # 額外：granularity 沒有混用
    gran_bad = []
    for r in records:
        expected = GRANULARITY_BY_TYPE[r["candidate_type"]]
        if r["sample_context"]["granularity"] != expected:
            gran_bad.append(r["candidate_id"])
        # TREND 必須用窗口資料（有 game_snos），CONTEXT/PATTERN 必須沒有
        if r["candidate_type"] == "TREND":
            if r["sample_context"]["game_snos"] is None:
                gran_bad.append(f"{r['candidate_id']} 缺 game_snos")
        elif r["sample_context"]["game_snos"] is not None:
            gran_bad.append(f"{r['candidate_id']} 不應有 game_snos")
    checks.append(
        ("兩種 granularity 沒有混用", not gran_bad,
         "TREND 用最近窗口資料（含 game_snos），CONTEXT/PATTERN 用官方球季累計"
         "（game_snos 為 null）"
         if not gran_bad else "；".join(gran_bad[:5]))
    )

    # 額外：sensitivity 的分子分母與來源計數一致
    comp_bad = []
    for c in candidates_after:
        rec = by_id[c["candidate_id"]]
        s_avg = rec["sample_sensitivity"]["batting_average"]
        if c["type"] == "TREND":
            src = trend_components[c["window"]["name"]]
        else:
            src = contexts[c["context"]["code"]]
        if s_avg["numerator"] != src["hits"] or s_avg["denominator"] != src["at_bats"]:
            comp_bad.append(f"{c['candidate_id']} AVG 分子分母不符來源")
        s_slg = rec["sample_sensitivity"]["slugging_percentage"]
        if s_slg["numerator"] != src["total_bases"]:
            comp_bad.append(f"{c['candidate_id']} SLG 分子不符來源")
    checks.append(
        ("sensitivity 的分子分母直接取自來源計數，未重新推導", not comp_bad,
         "29 個全部相符" if not comp_bad else "；".join(comp_bad[:5]))
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

    print("=" * 96)
    print("Evidence Sample Context / Sensitivity 分析（Step 11）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print("這一步只描述「數字背後有多少資料」與「比率對單一事件的敏感度」。")
    print("沒有 confidence score、沒有 reliability score、沒有門檻、沒有統計顯著性。")
    print("29 個 candidate 全部保留，小樣本不被過濾也不被降級。")
    print("=" * 96)

    records = [build_record(c, trend_components, contexts) for c in candidates]

    print_sample_size_table(records)
    print_records(records)

    print("\n" + "=" * 96)
    print("Validation")
    print("=" * 96)
    checks = run_validation(
        candidates_before, candidates, records, trend_components, contexts,
        fingerprints_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/EVIDENCE_SAMPLE_ANALYSIS.md。")

    print("\n" + "=" * 96)
    print("本階段沒有產生任何 score。sample_sensitivity 是算術描述，不是可信程度。")
    print("=" * 96)


if __name__ == "__main__":
    main()

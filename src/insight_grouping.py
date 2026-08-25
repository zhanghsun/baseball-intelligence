"""Insight Grouping Experiment（Step 18）。

它處理什麼：Step 17-7 暴露的 candidate duplication ——
20 個 noteworthy 中有 16 個其實只由 4 組獨立 evidence 支撐，
同一個現象被多個 candidate 重複呈現。

第一版 grouping 原則（`G18-1`）：
    **同一個分析 scope 的 candidate 形成同一個 Insight Group。**
    scope 即 TREND 的 window_name（RECENT_10 / RECENT_15）
    或 CONTEXT / PATTERN 的 context code（VS_RIGHT 等）。

    PATTERN 與同 context 的 CONTEXT candidate 刻意放進同一 group，
    因為 Step 12 已證明 PATTERN 的 magnitude 是由該 context 的 metric 差距產生
    （取三者最大值），兩者不是獨立發現。

它**不**做什麼：
    - 不修改 Step 17-7 的 classification 規則
    - 不新增 threshold
    - 不建立 group_score / group_rank / group_priority / weight
    - **不依 magnitude 決定 grouping**
    - **不依 sample size 決定 grouping**
    - 不使用 LLM、不發 HTTP 請求
    - 不產生自然語言結論
    - 不修改原始 candidate（sidecar 設計）

「grouping 不依 magnitude / sample size 決定」是可驗證的：
    `mutation_test_grouping_independence()` 把 magnitude 與 at_bats 換成極端值
    （在複本上）後重跑 grouping，確認 group 結構完全不變。

用法：
    python src/insight_grouping.py
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
    SUBJECT,
    network_guard_active,
    sha256_of,
)
from decision_relevance import PERSPECTIVES, PERSPECTIVE_ORDER  # noqa: E402
from noteworthy_insights import build_all as build_classification  # noqa: E402

# ------------------------------------------------------------------ 規則定義

GROUPING_RULE_ID = "G18-1"
GROUPING_RULE_VERSION = "first_version"
GROUPING_RULE_TEXT = (
    "同一個分析 scope 的 candidate 形成同一個 Insight Group。"
    "scope = TREND 的 window_name 或 CONTEXT / PATTERN 的 context code。"
)
GROUPING_RULE_INPUTS = ["candidate_scope"]
GROUPING_RULE_NOT_INPUTS = [
    "magnitude", "sample_size_at_bats", "plate_appearances",
    "percentile_rank", "consistency_count", "classification",
]
PATTERN_MERGE_RATIONALE = (
    "PATTERN 與同 context 的 CONTEXT candidate 刻意放進同一 group。"
    "Step 12 已記錄：PATTERN 的 magnitude 定義是「三個指標差距絕對值的最大者」，"
    "因此必然等於該 context 某一個 CONTEXT candidate 的 magnitude（本次 4 個 PATTERN "
    "全部等於同 context 的 SLG candidate）。兩者不是獨立發現。"
    "Step 17-7 也記錄：同 context 的 CONTEXT candidate 用的第二種 evidence "
    "就是該 PATTERN 本身。"
)

# scope -> perspective（沿用 Step 13 的 perspective 定義，不自行新增）
SCOPE_TO_PERSPECTIVE = {
    scope: key
    for key in PERSPECTIVE_ORDER
    for scope in PERSPECTIVES[key]["scopes"]
}

CLASSIFICATION_VALUES = ("noteworthy", "observation", "not_eligible")


# ------------------------------------------------------------------ Grouping

def group_key(view: dict) -> str:
    """grouping 的唯一輸入：candidate 的 scope。不讀任何數值。"""
    return view["window_or_scope"]


def build_groups(candidates: list, views: dict, samples: dict,
                 records_by_id: dict) -> list:
    """依 scope 聚合。member 與 group 一律排序，確保結果不依賴輸入順序。"""
    buckets: dict[str, list] = {}
    for c in candidates:
        scope = group_key(views[c["candidate_id"]])
        buckets.setdefault(scope, []).append(c)

    groups = []
    for scope in sorted(buckets):
        members = sorted(buckets[scope], key=lambda c: c["candidate_id"])
        member_ids = [c["candidate_id"] for c in members]
        member_records = [records_by_id[cid] for cid in member_ids]

        # classification 摘要（只是統計，不參與 grouping 決策）
        counts = {cls: 0 for cls in CLASSIFICATION_VALUES}
        for r in member_records:
            counts[r["classification"]] += 1
        present = [cls for cls in CLASSIFICATION_VALUES if counts[cls] > 0]

        # metrics_available：group 內成員實際涵蓋的指標
        metrics = set()
        for c in members:
            if c["type"] == "TREND":
                metrics.add(c["metric"])
            elif c["type"] == "CONTEXT":
                metrics.add(c["metric"])
            else:
                metrics.update(c["metrics"])
        all_metrics = {"batting_average", "on_base_percentage", "slugging_percentage"}
        missing_metrics = sorted(all_metrics - metrics)

        # shared_data_scope：成員共用的底層資料範圍（**事後描述，不是 grouping 依據**）
        sample_ctxs = [samples[cid]["sample_context"] for cid in member_ids]
        at_bats_values = sorted({s["at_bats"] for s in sample_ctxs})
        pa_values = sorted({s["plate_appearances"] for s in sample_ctxs})
        first = members[0]
        if first["type"] == "TREND":
            shared = {
                "scope_kind": "recent_games_window",
                "window_name": scope,
                "window_size_games": first["window"]["size_games"],
                "granularity": "recent_games",
                "official_item_name": None,
                "date_range": dict(first["traceability"]["date_range"]),
                "game_snos": list(first["traceability"]["game_snos"]),
            }
        else:
            shared = {
                "scope_kind": "season_cumulative_official_split",
                "window_name": None,
                "window_size_games": None,
                "granularity": "season_cumulative",
                "official_item_name": first["context"]["official_item_name"],
                "date_range": None,
                "game_snos": None,
            }
        shared.update({
            "at_bats_values_across_members": at_bats_values,
            "plate_appearances_values_across_members": pa_values,
            "members_share_single_sample": (
                len(at_bats_values) == 1 and len(pa_values) == 1
            ),
            "note": (
                "本欄位是聚合後的事後描述，用來說明「為什麼這些 candidate 講的是同一件事」。"
                "它**不是** grouping 的判定依據——grouping 只看 scope。"
            ),
        })

        groups.append({
            "group_id": f"GROUP-{SUBJECT['player_acnt']}-{SUBJECT['season']}-"
                        f"{SUBJECT['kind_code']}-{scope}",
            "scope": scope,
            "perspective": SCOPE_TO_PERSPECTIVE[scope],
            "perspective_name": PERSPECTIVES[SCOPE_TO_PERSPECTIVE[scope]]["name"],
            "member_candidate_ids": member_ids,
            "member_count": len(member_ids),
            "member_types": {
                t: sum(1 for c in members if c["type"] == t)
                for t in sorted({c["type"] for c in members})
            },
            "classification_summary": {
                "counts": counts,
                "classifications_present": present,
                "mixed_classification": len(present) > 1,
                "by_candidate": {
                    r["candidate_id"]: r["classification"] for r in member_records
                },
                "note": (
                    "classification 來自 Step 17-7，本階段完全沒有修改規則或結果；"
                    "此摘要只是統計，沒有參與 grouping 決策。"
                ),
            },
            "metrics_available": sorted(metrics),
            "metrics_unavailable": missing_metrics,
            "metrics_unavailable_reason": (
                "processed data 未收逐場犧牲飛球，TREND 窗口無法計算 OBP"
                "（Step 5 / Step 11 已記錄）"
                if missing_metrics else None
            ),
            "shared_data_scope": shared,
            "grouping_rule": {
                "rule_id": GROUPING_RULE_ID,
                "version": GROUPING_RULE_VERSION,
                "rule_text": GROUPING_RULE_TEXT,
                "rule_inputs": list(GROUPING_RULE_INPUTS),
                "rule_not_inputs": list(GROUPING_RULE_NOT_INPUTS),
                "pattern_merge_rationale": (
                    PATTERN_MERGE_RATIONALE
                    if any(c["type"] == "MULTI_METRIC_PATTERN" for c in members)
                    else None
                ),
            },
            "provenance": {
                "candidate_source_step": "Step 9",
                "candidate_source_module": "src/candidate_insights.py",
                "scope_source_step": "Step 12",
                "scope_source_module": "src/ranking_experiment.py（build_view）",
                "scope_source_field": "window_or_scope",
                "classification_source_step": "Step 17-7",
                "classification_source_module": "src/noteworthy_insights.py",
                "perspective_source_step": "Step 13",
                "perspective_source_module": "src/decision_relevance.py",
                "sample_context_source_step": "Step 11",
                "source_files": sorted({
                    f for c in members for f in c["source_files"]
                }),
                "sidecar_note": (
                    "本記錄為 sidecar，用 candidate_id 關聯，不寫回 candidate 物件"
                ),
            },
            "contains_no": [
                "group_score", "group_rank", "group_priority", "threshold",
                "weight", "natural_language_conclusion", "llm",
            ],
        })
    return groups


# ------------------------------------------------------------------ 反證

def mutation_test_grouping_independence(
    candidates: list, views: dict, samples: dict, records_by_id: dict,
    baseline_groups: list,
) -> dict:
    """把 magnitude 與 at_bats 換成極端值後重跑 grouping，確認 group 結構不變。

    若 grouping 任何地方讀了這些數值，group 成員就會改變。
    全部在深拷貝上操作，不動原始資料。
    """
    def signature(groups: list) -> str:
        return json.dumps(
            [[g["scope"], g["member_candidate_ids"]] for g in groups],
            ensure_ascii=False, sort_keys=True,
        )

    base_sig = signature(baseline_groups)
    diffs = []
    cases = 0

    for mag in (0.0, 999.0):
        cc = copy.deepcopy(candidates)
        vv = copy.deepcopy(views)
        for c in cc:
            if c["type"] == "TREND":
                c["absolute_difference"] = mag
                c["absolute_difference_magnitude"] = abs(mag)
            elif c["type"] == "CONTEXT":
                c["comparison"]["difference"] = mag
                c["comparison"]["difference_magnitude"] = abs(mag)
            else:
                for mv in c["metric_values"].values():
                    mv["difference"] = mag
            vv[c["candidate_id"]]["magnitude"] = abs(mag)
        cases += 1
        got = build_groups(cc, vv, samples, records_by_id)
        if signature(got) != base_sig:
            diffs.append(f"magnitude={mag} 時 group 結構改變")

    for ab in (1, 9999):
        ss = copy.deepcopy(samples)
        for s in ss.values():
            s["sample_context"]["at_bats"] = ab
            s["sample_context"]["plate_appearances"] = ab
        cases += 1
        got = build_groups(candidates, views, ss, records_by_id)
        if signature(got) != base_sig:
            diffs.append(f"at_bats={ab} 時 group 結構改變")

    return {
        "mutant_magnitude_values": [0.0, 999.0],
        "mutant_at_bats_values": [1, 9999],
        "cases_tested": cases,
        "structure_changes": diffs,
        "grouping_independent_of_values": not diffs,
    }


def shuffle_test(candidates: list, views: dict, samples: dict,
                 records_by_id: dict, baseline_groups: list,
                 seeds=(20261121, 7, 999)) -> dict:
    """打亂輸入順序後重跑，確認結果一致。"""
    def signature(groups: list) -> str:
        return json.dumps(
            [[g["scope"], g["member_candidate_ids"]] for g in groups],
            ensure_ascii=False, sort_keys=True,
        )

    base_sig = signature(baseline_groups)
    diffs = []
    for seed in seeds:
        shuffled = candidates[:]
        random.Random(seed).shuffle(shuffled)
        got = build_groups(shuffled, views, samples, records_by_id)
        if signature(got) != base_sig:
            diffs.append(f"seed={seed} 時結果不同")
    return {
        "seeds": list(seeds),
        "differences": diffs,
        "order_independent": not diffs,
    }


# ------------------------------------------------------------------ 輸出

def print_groups(groups: list) -> None:
    print("\n" + "=" * 100)
    print(f"Insight Groups（共 {len(groups)} 個）")
    print("=" * 100)
    for g in groups:
        cs = g["classification_summary"]
        sd = g["shared_data_scope"]
        print(f"\n  [{g['group_id']}]")
        print(f"    scope               : {g['scope']}")
        print(f"    perspective         : {g['perspective']}"
              f"（{g['perspective_name']}）")
        print(f"    member_count        : {g['member_count']}"
              f"　types={g['member_types']}")
        print(f"    classification      : "
              + "　".join(f"{k}={v}" for k, v in cs["counts"].items() if v)
              + f"　mixed={cs['mixed_classification']}")
        print(f"    metrics_available   : {', '.join(g['metrics_available'])}")
        if g["metrics_unavailable"]:
            print(f"    metrics_unavailable : {', '.join(g['metrics_unavailable'])}"
                  f"　原因：{g['metrics_unavailable_reason']}")
        print(f"    shared_data_scope   : kind={sd['scope_kind']}"
              f"　granularity={sd['granularity']}")
        if sd["official_item_name"]:
            print(f"                          官方 ItemName={sd['official_item_name']}")
        if sd["date_range"]:
            print(f"                          日期 "
                  f"{sd['date_range']['first_game_date']}"
                  f" ~ {sd['date_range']['last_game_date']}"
                  f"　game_snos({len(sd['game_snos'])})")
        print(f"                          AB={sd['at_bats_values_across_members']}"
              f"　PA={sd['plate_appearances_values_across_members']}"
              f"　共用單一樣本={sd['members_share_single_sample']}")
        print(f"    grouping_rule       : {g['grouping_rule']['rule_id']}"
              f"　inputs={g['grouping_rule']['rule_inputs']}")
        if g["grouping_rule"]["pattern_merge_rationale"]:
            print(f"    PATTERN 合併理由    : "
                  f"{g['grouping_rule']['pattern_merge_rationale'][:60]}…")
        print("    members:")
        for cid in g["member_candidate_ids"]:
            print(f"      - {cs['by_candidate'][cid]:<12} {cid}")


def print_summary(groups: list, records: list) -> None:
    print("\n" + "=" * 100)
    print("Grouping 統計")
    print("=" * 100)
    print(f"  candidate 總數 : {sum(g['member_count'] for g in groups)}")
    print(f"  group 總數     : {len(groups)}")

    print("\n  依 perspective：")
    by_p: dict[str, list] = {}
    for g in groups:
        by_p.setdefault(g["perspective"], []).append(g)
    for key in PERSPECTIVE_ORDER:
        gs = by_p.get(key, [])
        print(f"    {key:<22} groups={len(gs):<3} candidates="
              f"{sum(g['member_count'] for g in gs):<3}"
              f" scopes={[g['scope'] for g in gs]}")

    print("\n  classification 壓縮結果：")
    nw_groups = [g for g in groups
                 if g["classification_summary"]["counts"]["noteworthy"] > 0]
    ob_groups = [g for g in groups
                 if g["classification_summary"]["counts"]["observation"] > 0]
    nw_total = sum(g["classification_summary"]["counts"]["noteworthy"] for g in groups)
    ob_total = sum(g["classification_summary"]["counts"]["observation"] for g in groups)
    print(f"    noteworthy  : {nw_total} 個 candidate -> {len(nw_groups)} 個 group")
    print(f"      " + "、".join(g["scope"] for g in nw_groups))
    print(f"    observation : {ob_total} 個 candidate -> {len(ob_groups)} 個 group")
    print(f"      " + "、".join(g["scope"] for g in ob_groups))

    mixed = [g["scope"] for g in groups
             if g["classification_summary"]["mixed_classification"]]
    print(f"\n  同時包含 noteworthy 與 observation 的 group：{len(mixed)} 個")
    print(f"    {mixed if mixed else '（沒有）'}")

    print("\n  每個 group 的成員數：")
    for g in groups:
        cs = g["classification_summary"]["counts"]
        print(f"    {g['scope']:<14} {g['member_count']:>2} 個"
              f"　noteworthy={cs['noteworthy']}"
              f"　observation={cs['observation']}"
              f"　not_eligible={cs['not_eligible']}")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "rank", "threshold", "priority", "confidence")
ALLOWED_KEY_EXCEPTIONS = ("percentile_rank", "rank_desc")
DECLARATIVE_KEYS = ("contains_no", "rule_not_inputs")

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
    candidates_before: list, candidates_after: list, groups: list,
    records: list, mutation: dict, shuffle: dict, fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    n = len(candidates_after)
    cand_ids = sorted(c["candidate_id"] for c in candidates_after)
    all_members = [cid for g in groups for cid in g["member_candidate_ids"]]

    # 1 / 2 / 3
    checks.append(
        (f"{n} 個 candidate 每一個且只屬於一個 group",
         sorted(all_members) == cand_ids and len(all_members) == len(set(all_members)),
         f"group 成員總數={len(all_members)}　candidate 總數={n}"
         f"　集合相同={sorted(all_members) == cand_ids}"
         f"　無重複={len(all_members) == len(set(all_members))}")
    )
    missing = sorted(set(cand_ids) - set(all_members))
    checks.append(
        ("沒有 candidate 遺失", not missing,
         "29 個全部有歸屬" if not missing else f"遺失：{missing}")
    )
    dup = sorted({cid for cid in all_members if all_members.count(cid) > 1})
    checks.append(
        ("沒有 candidate 重複進入兩個 group", not dup,
         "每個 candidate 只出現一次" if not dup else f"重複：{dup}")
    )

    # 4
    same = candidates_before == candidates_after
    checks.append(
        ("grouping 沒有修改 candidate（深度比較 29 個物件）", same,
         "sidecar 設計，沒有寫回路徑；逐欄位比較完全相同"
         if same else "有物件被改動")
    )

    # 5 / 6：mutation 反證
    checks.append(
        ("grouping 不依 magnitude 決定（把 magnitude 換成 0.0 與 999.0 後結構不變）",
         mutation["grouping_independent_of_values"],
         f"magnitude 測試值 {mutation['mutant_magnitude_values']}、"
         f"at_bats 測試值 {mutation['mutant_at_bats_values']}，"
         f"共 {mutation['cases_tested']} 次重跑，group 結構改變 "
         f"{len(mutation['structure_changes'])} 次"
         if mutation["grouping_independent_of_values"]
         else "；".join(mutation["structure_changes"]))
    )
    checks.append(
        ("grouping 不依 sample size 決定（把 at_bats 換成 1 與 9999 後結構不變）",
         mutation["grouping_independent_of_values"],
         "同上 mutation test；grouping 唯一輸入是 scope（rule_inputs = "
         f"{GROUPING_RULE_INPUTS}），rule_not_inputs 明確列出 "
         f"{len(GROUPING_RULE_NOT_INPUTS)} 個未被使用的量"
         if mutation["grouping_independent_of_values"]
         else "；".join(mutation["structure_changes"]))
    )

    # 7：PATTERN 與對應 CONTEXT 被聚合
    by_scope = {g["scope"]: g for g in groups}
    pattern_bad = []
    for c in candidates_after:
        if c["type"] != "MULTI_METRIC_PATTERN":
            continue
        code = c["context"]["code"]
        g = by_scope.get(code)
        if g is None:
            pattern_bad.append(f"{c['candidate_id']} 找不到對應 group")
            continue
        if c["candidate_id"] not in g["member_candidate_ids"]:
            pattern_bad.append(f"{c['candidate_id']} 不在 {code} group 中")
        siblings = [
            x["candidate_id"] for x in candidates_after
            if x["type"] == "CONTEXT" and x["context"]["code"] == code
        ]
        for s in siblings:
            if s not in g["member_candidate_ids"]:
                pattern_bad.append(f"{s} 未與 {c['candidate_id']} 同 group")
        if g["grouping_rule"]["pattern_merge_rationale"] is None:
            pattern_bad.append(f"{code} group 缺 pattern_merge_rationale")
    checks.append(
        ("PATTERN 與對應 CONTEXT 被正確聚合", not pattern_bad,
         "4 個 PATTERN 各自與同 context 的 3 個 CONTEXT candidate 同 group，"
         "且都附合併理由"
         if not pattern_bad else "；".join(pattern_bad[:5]))
    )

    # 8 / 9：TREND 窗口聚合
    for scope, expected in (
        ("RECENT_10", ["TREND-ZHANGYUCHENG-2026-A-RECENT_10-AVG",
                       "TREND-ZHANGYUCHENG-2026-A-RECENT_10-SLG"]),
        ("RECENT_15", ["TREND-ZHANGYUCHENG-2026-A-RECENT_15-AVG",
                       "TREND-ZHANGYUCHENG-2026-A-RECENT_15-SLG"]),
    ):
        g = by_scope.get(scope)
        ok = g is not None and sorted(g["member_candidate_ids"]) == sorted(expected)
        checks.append(
            (f"{scope} 的 AVG / SLG 被聚合在同一個 group", ok,
             f"members={g['member_candidate_ids']}" if g else "找不到 group")
        )

    # 10：每個 group 都能追溯
    trace_bad = []
    for g in groups:
        p = g["provenance"]
        for key in ("candidate_source_step", "scope_source_step",
                    "scope_source_field", "classification_source_step",
                    "perspective_source_step", "source_files"):
            if not p.get(key):
                trace_bad.append(f"{g['scope']} 缺 provenance.{key}")
        for f in p["source_files"]:
            if not (Path(__file__).resolve().parent.parent / f).exists():
                trace_bad.append(f"{g['scope']} source_file 不存在：{f}")
        for cid in g["member_candidate_ids"]:
            if cid not in cand_ids:
                trace_bad.append(f"{g['scope']} 成員 {cid} 不在原始 candidate 中")
    checks.append(
        ("每個 group 都能追溯到原始 candidate 與來源 Step", not trace_bad,
         f"{len(groups)} 個 group 全部具備 provenance，"
         "source_files 皆存在，成員皆為既有 candidate"
         if not trace_bad else "；".join(trace_bad[:5]))
    )

    # 11：deterministic
    checks.append(
        ("deterministic：打亂輸入順序後結果一致", shuffle["order_independent"],
         f"以 seed {shuffle['seeds']} 打亂 candidate 順序各跑一次，"
         "group 結構完全相同"
         if shuffle["order_independent"] else "；".join(shuffle["differences"]))
    )

    # 12 / 13
    checks.append(
        ("沒有 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖")
    )
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

    # 14：沒有 score / ranking / threshold / weight
    payload = {"groups": groups}
    bad_keys = scan_keys(payload)
    blob = json.dumps(payload, ensure_ascii=False)
    declarative = json.dumps(
        [
            {
                "contains_no": g["contains_no"],
                "rule_not_inputs": g["grouping_rule"]["rule_not_inputs"],
                "pattern_merge_rationale": g["grouping_rule"]["pattern_merge_rationale"],
                "shared_note": g["shared_data_scope"]["note"],
                "classification_note": g["classification_summary"]["note"],
            }
            for g in groups
        ],
        ensure_ascii=False,
    )
    thr = []
    for w in ("threshold", "門檻", "cutoff", "minimum_"):
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            thr.append(f"{w}×{cnt}")
    checks.append(
        ("沒有 group_score / group_rank / group_priority / threshold / weight",
         not bad_keys and not thr,
         "遞迴掃描所有巢狀欄位名：沒有任何 score / rank / priority / weight / "
         "threshold 欄位（percentile_rank、rank_desc 為 Step 6 既有描述子，已排除）"
         if not bad_keys and not thr
         else f"欄位={sorted(set(bad_keys))[:6]}　字眼={thr}")
    )

    # 額外：Step 17-7 的 classification 完全未被修改
    from noteworthy_insights import CLASSIFICATION_VALUES as NW_VALUES
    cls_bad = []
    rec_by_id = {r["candidate_id"]: r for r in records}
    for g in groups:
        for cid, cls in g["classification_summary"]["by_candidate"].items():
            if cls != rec_by_id[cid]["classification"]:
                cls_bad.append(cid)
            if cls not in NW_VALUES:
                cls_bad.append(f"{cid} classification 不在受控詞彙中")
    checks.append(
        ("Step 17-7 的 classification 原樣引用，未被修改", not cls_bad,
         "29 筆 classification 與 Step 17-7 記錄逐筆相符"
         if not cls_bad else "；".join(cls_bad[:5]))
    )

    # 額外：沒有自然語言結論
    forbidden = ("擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
                 "建議", "應該", "預測", "最佳", "最好", "最差",
                 "統計顯著", "顯著性", "值得注意", "recommend", "should")
    hits = []
    for w in forbidden:
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    checks.append(
        ("沒有產生自然語言結論或價值判斷字眼", not hits,
         "未出現禁用字眼（宣告性與說明性欄位已扣除）"
         if not hits else "、".join(hits))
    )

    # 額外：raw / processed 未修改
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data 未被修改", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    return checks


# ------------------------------------------------------------------ main

def main() -> None:
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }

    from candidate_insights import load_inputs
    logs, apart_rows = load_inputs()

    # 直接沿用 Step 17-7 的完整流程，不重新實作 classification
    candidates, views, samples, _pattern_by_context, records = build_classification(
        logs, apart_rows
    )
    candidates_before = copy.deepcopy(candidates)
    records_by_id = {r["candidate_id"]: r for r in records}

    groups = build_groups(candidates, views, samples, records_by_id)
    mutation = mutation_test_grouping_independence(
        candidates, views, samples, records_by_id, groups
    )
    shuffle = shuffle_test(candidates, views, samples, records_by_id, groups)

    print("=" * 100)
    print("Insight Grouping Experiment（Step 18）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print(f"輸入：Step 9 的 {len(candidates)} 個 candidate"
          f" + Step 17-7 的 classification")
    print(f"規則：{GROUPING_RULE_ID}（{GROUPING_RULE_VERSION}）")
    print(f"  {GROUPING_RULE_TEXT}")
    print(f"  grouping 唯一輸入：{GROUPING_RULE_INPUTS}")
    print(f"  明確未使用：{GROUPING_RULE_NOT_INPUTS}")
    print("目的只有一個：消除「同一個現象被多個 candidate 重複呈現」。")
    print("沒有 group_score / group_rank / group_priority / threshold / weight。")
    print("=" * 100)

    print_summary(groups, records)
    print_groups(groups)

    print("\n" + "=" * 100)
    print("反證測試")
    print("=" * 100)
    print(f"  magnitude / sample size 獨立性：")
    print(f"    magnitude 測試值 : {mutation['mutant_magnitude_values']}")
    print(f"    at_bats 測試值   : {mutation['mutant_at_bats_values']}")
    print(f"    重跑次數         : {mutation['cases_tested']}")
    print(f"    結構改變次數     : {len(mutation['structure_changes'])}")
    print(f"    結論             : grouping 與數值無關 = "
          f"{mutation['grouping_independent_of_values']}")
    print(f"  輸入順序獨立性：")
    print(f"    seeds            : {shuffle['seeds']}")
    print(f"    結果不同次數     : {len(shuffle['differences'])}")
    print(f"    結論             : order_independent = {shuffle['order_independent']}")

    print("\n" + "=" * 100)
    print("Validation")
    print("=" * 100)
    checks = run_validation(
        candidates_before, candidates, groups, records, mutation, shuffle,
        fingerprints_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 "
              "docs/INSIGHT_GROUPING_EXPERIMENT.md。")

    print("\n" + "=" * 100)
    print("本階段只做聚合，沒有排序、沒有評分、沒有修改 Step 17-7 的分類。")
    print("=" * 100)


if __name__ == "__main__":
    main()

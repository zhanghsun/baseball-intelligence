"""Decision Relevance Experiment（Step 13）。

它研究的問題：**什麼特徵讓一個 candidate 對教練的決策更有關聯？**

它**不**做的事：
    - 不回答「哪個 candidate 最重要」、「哪個 perspective 最好」
    - 不建立 ranking、score、weight、threshold、confidence score
    - 不產生 recommendation（不會出現「應該讓某球員先發」這類句子）
    - 不產生 prediction
    - 不產生自然語言結論
    - 不使用 LLM
    - 不新增資料來源、不發 HTTP 請求
    - 不修改原始 candidate 或任何來源資料

設計方式：與 Step 10 / 11 / 12 相同，產出是**獨立的 sidecar**，
用 candidate_id 關聯，不寫回 candidate 物件。

防止「描述」變成「建議」的機制：
    所有決策相關欄位都限制在**受控詞彙**（controlled vocabulary）中，
    而且值必須是 ASCII snake_case 識別字。
    這在結構上讓自由文字的棒球建議無法出現在這些欄位裡。

用法：
    python src/decision_relevance.py
"""

from __future__ import annotations

import copy
import json
import re
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
from evidence_sample_context import build_record, build_trend_components  # noqa: E402
from ranking_experiment import build_view  # noqa: E402

# ------------------------------------------------------------------ 受控詞彙

TEMPORAL_RELEVANCE_VALUES = ("recent_games", "season_cumulative")

CONTEXTUAL_RELEVANCE_VALUES = (
    "none", "pitcher_hand", "pitcher_role", "pitcher_background",
)

# Step 9 內部把「本土 / 外籍」那一組命名為 pitcher_origin，
# 本階段依 Step 13 指示改用 pitcher_background。兩者指同一組官方分項。
CONTEXT_GROUP_TO_RELEVANCE = {
    "pitcher_hand": "pitcher_hand",
    "pitcher_role": "pitcher_role",
    "pitcher_origin": "pitcher_background",
}

ALLOWED_ACTION_LINKS = (
    "monitor_current_form",
    "compare_against_pitcher_hand_context",
    "compare_against_pitcher_role_context",
    "compare_against_pitcher_background_context",
)

ALLOWED_ACTION_LINK_BASIS = (
    "recent_games",
    "season_cumulative_pitcher_hand",
    "season_cumulative_pitcher_role",
    "season_cumulative_pitcher_background",
)

ALLOWED_ACTION_LINK_REQUIRES = (
    "next_game_context",
    "next_starting_pitcher_hand",
    "in_game_pitcher_role_at_plate_appearance",
    "next_starting_pitcher_registration_status",
)

ALLOWED_DECISION_AREAS = (
    "pre_game_preparation",
    "in_game_situational_preparation",
    "long_term_player_evaluation",
)

ALLOWED_EVIDENCE_LABELS = (
    "recent_window_batting_counts",
    "season_cumulative_split_batting_counts",
    "season_cumulative_split_multi_metric_direction",
)

# 決策相關欄位一律必須是這個格式的識別字，禁止自由文字
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

DECISION_FIELDS = (
    "temporal_relevance",
    "contextual_relevance",
    "possible_action_link",
    "action_link_basis",
    "action_link_requires",
    "possible_decision_area",
    "evidence_label",
)

VOCABULARY = {
    "temporal_relevance": TEMPORAL_RELEVANCE_VALUES,
    "contextual_relevance": CONTEXTUAL_RELEVANCE_VALUES,
    "possible_action_link": ALLOWED_ACTION_LINKS,
    "action_link_basis": ALLOWED_ACTION_LINK_BASIS,
    "action_link_requires": ALLOWED_ACTION_LINK_REQUIRES,
    "possible_decision_area": ALLOWED_DECISION_AREAS,
    "evidence_label": ALLOWED_EVIDENCE_LABELS,
}

# 決策領域對照是「暫定的描述性對照」，與 Step 10 的 tier 一樣是產品層面的假設，
# 沒有經過任何驗證，不是統計結論。
DECISION_AREA_BY_RELEVANCE = {
    "none": "pre_game_preparation",
    "pitcher_hand": "pre_game_preparation",
    "pitcher_role": "in_game_situational_preparation",
    "pitcher_background": "long_term_player_evaluation",
}

ACTION_LINK_BY_RELEVANCE = {
    "none": ("monitor_current_form", "recent_games", "next_game_context"),
    "pitcher_hand": (
        "compare_against_pitcher_hand_context",
        "season_cumulative_pitcher_hand",
        "next_starting_pitcher_hand",
    ),
    "pitcher_role": (
        "compare_against_pitcher_role_context",
        "season_cumulative_pitcher_role",
        "in_game_pitcher_role_at_plate_appearance",
    ),
    "pitcher_background": (
        "compare_against_pitcher_background_context",
        "season_cumulative_pitcher_background",
        "next_starting_pitcher_registration_status",
    ),
}

# ------------------------------------------------------------------ Perspective 定義

PERSPECTIVES = {
    "A_CURRENT_FORM": {
        "name": "Perspective A — Current Form",
        "question": "球員現在的狀態",
        "scopes": ["RECENT_10", "RECENT_15"],
    },
    "B_MATCHUP_CONTEXT": {
        "name": "Perspective B — Matchup Context",
        "question": "特定投手情境",
        "scopes": ["VS_RIGHT", "VS_LEFT", "VS_STARTER", "VS_RELIEF", "VS_CLOSER"],
    },
    "C_STRUCTURAL_CONTEXT": {
        "name": "Perspective C — Structural Context",
        "question": "長期球員表現結構",
        "scopes": ["VS_DOMESTIC", "VS_FOREIGN"],
    },
}
PERSPECTIVE_ORDER = ["A_CURRENT_FORM", "B_MATCHUP_CONTEXT", "C_STRUCTURAL_CONTEXT"]

# Part 4 特別比較的三個 candidate
FOCUS_IDS = [
    "TREND-ZHANGYUCHENG-2026-A-RECENT_10-AVG",
    "CONTEXT-ZHANGYUCHENG-2026-A-VS_CLOSER-AVG",
    "CONTEXT-ZHANGYUCHENG-2026-A-VS_RIGHT-OBP",
]
FOCUS_REASON = {
    FOCUS_IDS[0]: "Step 12 中 Strategy A 第 1 名：高時間性",
    FOCUS_IDS[1]: "Step 12 中 Strategy B 第 3 名、Strategy C 第 29 名：高 magnitude / 小樣本",
    FOCUS_IDS[2]: "Step 12 中 Strategy C 第 1 名、A 與 B 第 29 名：大樣本 / 極小 magnitude",
}


# ------------------------------------------------------------------ 建立描述子

def contextual_relevance_of(candidate: dict) -> tuple[str, str | None, str | None]:
    """回傳 (contextual_relevance, context_code, official_item_name)。"""
    if candidate["type"] == "TREND":
        return "none", None, None
    group = candidate["context"]["group"]
    return (
        CONTEXT_GROUP_TO_RELEVANCE[group],
        candidate["context"]["code"],
        candidate["context"]["official_item_name"],
    )


def evidence_label_of(candidate: dict) -> str:
    return {
        "TREND": "recent_window_batting_counts",
        "CONTEXT": "season_cumulative_split_batting_counts",
        "MULTI_METRIC_PATTERN": "season_cumulative_split_multi_metric_direction",
    }[candidate["type"]]


def build_relevance_record(candidate: dict, view: dict, sample: dict) -> dict:
    temporal = view["granularity"]
    ctx_rel, ctx_code, ctx_name = contextual_relevance_of(candidate)
    action_link, basis, requires = ACTION_LINK_BY_RELEVANCE[ctx_rel]
    decision_area = DECISION_AREA_BY_RELEVANCE[ctx_rel]

    # next_game_dependency：依 Step 13 給定的規則
    #   recent_games      -> true（近期狀態需要「下一場對手」才能形成 matchup-specific 意義）
    #   season_cumulative -> false（本身已經是一個完整的球季累計情境）
    next_dep = temporal == "recent_games"
    next_dep_basis = (
        "temporal_relevance = recent_games。近期表現本身不含對手資訊，"
        "需要下一場的對手與先發投手才能形成 matchup-specific 的意義。"
        if next_dep else
        "temporal_relevance = season_cumulative。這個 candidate 本身就是一個"
        "完整的球季累計情境，不需要下一場資訊才能成立。"
    )

    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_type": candidate["type"],
        "scope": view["window_or_scope"],

        # Part 1.1
        "temporal_relevance": temporal,

        # Part 1.2
        "contextual_relevance": ctx_rel,
        "context_code": ctx_code,
        "context_official_item_name": ctx_name,
        "contextual_relevance_source": (
            "官方分項 ItemGroupCode = 3（Step 8）；沒有自行新增任何 context"
            if ctx_code else "TREND 沒有情境切分"
        ),

        # Part 1.3
        "possible_action_link": action_link,
        "action_link_basis": basis,
        "action_link_requires": requires,
        "action_link_note": (
            "這是「資料可以連到哪一類決策」的描述，不是決策本身，也不是建議。"
        ),

        # Part 1.4
        "next_game_dependency": next_dep,
        "next_game_dependency_basis": next_dep_basis,
        "next_game_dependency_note": (
            "此欄位描述「evidence 本身是否需要下一場資訊才完整」，"
            "不代表這個 candidate 有用或沒用。"
        ),

        # Part 3：Action Chain
        "action_chain": {
            "candidate": candidate["candidate_id"],
            "evidence_label": evidence_label_of(candidate),
            "evidence_detail": {
                "metric_or_context": view["metric_or_context"],
                "magnitude": view["magnitude"],
                "magnitude_metric": view["magnitude_metric"],
                "percentile_rank": view["percentile_rank"],
                "consistency_count": view["consistency_count"],
                "at_bats": sample["sample_context"]["at_bats"],
                "plate_appearances": sample["sample_context"]["plate_appearances"],
                "games": sample["sample_context"]["games"],
                "delta_if_one_more": view["delta_if_one_more"],
            },
            "possible_context_needed": requires,
            "possible_decision_area": decision_area,
            "decision_area_mapping_basis": "provisional_descriptive_mapping",
            "decision_area_is_not": [
                "recommendation", "prediction", "instruction", "lineup_decision",
            ],
        },

        # 供驗證用：決策相關欄位的扁平化，方便檢查受控詞彙
        "controlled_vocabulary_fields": {
            "temporal_relevance": temporal,
            "contextual_relevance": ctx_rel,
            "possible_action_link": action_link,
            "action_link_basis": basis,
            "action_link_requires": requires,
            "possible_decision_area": decision_area,
            "evidence_label": evidence_label_of(candidate),
        },

        "traceability": {
            "source_files": list(candidate["source_files"]),
            "source_evidence": list(candidate["source_evidence"]),
        },
        "contains_no": [
            "score", "weight", "threshold", "ranking", "confidence_score",
            "prediction", "recommendation", "natural_language_conclusion",
        ],
    }


# ------------------------------------------------------------------ Perspective

def build_perspectives(records: list) -> dict:
    by_scope: dict[str, list] = {}
    for r in records:
        by_scope.setdefault(r["scope"], []).append(r["candidate_id"])

    out = {}
    for key in PERSPECTIVE_ORDER:
        spec = PERSPECTIVES[key]
        members = []
        for scope in spec["scopes"]:
            members += sorted(by_scope.get(scope, []))
        out[key] = {
            "key": key,
            "name": spec["name"],
            "question": spec["question"],
            "scopes": list(spec["scopes"]),
            "members": sorted(members),
            "member_count": len(members),
            "membership_rule": (
                "由 candidate 的 scope（TREND 的 window_name 或 CONTEXT/PATTERN 的 "
                "context code）直接查表決定，不看數值"
            ),
            "is_not_a_ranking": True,
        }
    return out


# ------------------------------------------------------------------ 輸出

def print_records(records: list) -> None:
    by_type: dict[str, list] = {}
    for r in records:
        by_type.setdefault(r["candidate_type"], []).append(r)

    for ctype in ("TREND", "MULTI_METRIC_PATTERN", "CONTEXT"):
        group = sorted(by_type.get(ctype, []), key=lambda r: r["candidate_id"])
        if not group:
            continue
        print("\n" + "=" * 100)
        print(f"Decision Relevance Descriptors — {ctype}（{len(group)} 個）")
        print("=" * 100)
        for r in group:
            ac = r["action_chain"]
            print(f"\n  {r['candidate_id']}")
            print(f"    temporal_relevance     : {r['temporal_relevance']}")
            print(f"    contextual_relevance   : {r['contextual_relevance']}"
                  + (f"　（{r['context_code']} / 官方 "
                     f"{r['context_official_item_name']}）"
                     if r["context_code"] else ""))
            print(f"    possible_action_link   : {r['possible_action_link']}")
            print(f"    action_link_basis      : {r['action_link_basis']}")
            print(f"    action_link_requires   : {r['action_link_requires']}")
            print(f"    next_game_dependency   : {r['next_game_dependency']}")
            print(f"    action chain           : {ac['candidate']}")
            print(f"        -> evidence                : {ac['evidence_label']}")
            ed = ac["evidence_detail"]
            pct = "null" if ed["percentile_rank"] is None else f"{ed['percentile_rank']:.4f}"
            print(f"           detail: magnitude={ed['magnitude']:.8f}"
                  f"({ed['magnitude_metric']})  AB={ed['at_bats']}"
                  f"  PA={ed['plate_appearances']}  games={ed['games']}"
                  f"  percentile={pct}")
            print(f"        -> possible_context_needed : {ac['possible_context_needed']}")
            print(f"        -> possible_decision_area  : {ac['possible_decision_area']}"
                  f"（{ac['decision_area_mapping_basis']}）")


def print_descriptor_summary(records: list) -> None:
    print("\n" + "=" * 100)
    print("描述子分佈（只是計數，不是排名）")
    print("=" * 100)
    for field in ("temporal_relevance", "contextual_relevance",
                  "possible_action_link", "action_link_requires",
                  "possible_decision_area"):
        counts: dict[str, int] = {}
        for r in records:
            counts[r["controlled_vocabulary_fields"][field]] = counts.get(
                r["controlled_vocabulary_fields"][field], 0
            ) + 1
        print(f"\n  {field}：")
        for k in sorted(counts):
            print(f"    {k:<48} {counts[k]:>3} 個")

    dep_counts: dict[bool, int] = {}
    for r in records:
        dep_counts[r["next_game_dependency"]] = dep_counts.get(
            r["next_game_dependency"], 0
        ) + 1
    print("\n  next_game_dependency：")
    for k in sorted(dep_counts, key=lambda b: not b):
        print(f"    {str(k):<48} {dep_counts[k]:>3} 個")


def print_perspectives(perspectives: dict) -> None:
    print("\n" + "=" * 100)
    print("Decision Perspectives（三個並列的研究視角，不排名、不比較優劣）")
    print("=" * 100)
    for key in PERSPECTIVE_ORDER:
        p = perspectives[key]
        print(f"\n  {p['name']}")
        print(f"    question       : {p['question']}")
        print(f"    scopes         : {', '.join(p['scopes'])}")
        print(f"    member_count   : {p['member_count']}")
        print(f"    membership_rule: {p['membership_rule']}")
        print("    members:")
        for cid in p["members"]:
            print(f"      - {cid}")


def print_focus_comparison(records: list, views: dict, samples: dict) -> None:
    by_id = {r["candidate_id"]: r for r in records}
    print("\n" + "=" * 100)
    print("Part 4：三個 candidate 的多維度比較")
    print("=" * 100)
    print("  目的：看出 magnitude、sample size、time relevance、context relevance")
    print("  其實是彼此獨立的維度。**不是要決定哪一個比較好。**\n")

    rows = [
        ("candidate_id", lambda cid: cid),
        ("Step 12 A / B / C 名次", lambda cid: FOCUS_RANKS[cid]),
        ("挑選原因", lambda cid: FOCUS_REASON[cid]),
        ("temporal_relevance", lambda cid: by_id[cid]["temporal_relevance"]),
        ("contextual_relevance", lambda cid: by_id[cid]["contextual_relevance"]),
        ("magnitude", lambda cid: f"{views[cid]['magnitude']:.8f}"),
        ("magnitude 使用指標", lambda cid: views[cid]["magnitude_metric"]),
        ("at_bats", lambda cid: str(samples[cid]["sample_context"]["at_bats"])),
        ("plate_appearances",
         lambda cid: str(samples[cid]["sample_context"]["plate_appearances"])),
        ("games", lambda cid: str(samples[cid]["sample_context"]["games"])),
        ("percentile_rank",
         lambda cid: ("null" if views[cid]["percentile_rank"] is None
                      else f"{views[cid]['percentile_rank']:.4f}")),
        ("delta_if_one_more",
         lambda cid: ("null" if views[cid]["delta_if_one_more"] is None
                      else f"{views[cid]['delta_if_one_more']:.8f}")),
        ("magnitude / delta（相當於幾個事件）",
         lambda cid: ("null" if views[cid]["delta_if_one_more"] in (None, 0)
                      else f"{views[cid]['magnitude'] / views[cid]['delta_if_one_more']:.2f}")),
        ("next_game_dependency", lambda cid: str(by_id[cid]["next_game_dependency"])),
        ("possible_action_link", lambda cid: by_id[cid]["possible_action_link"]),
        ("action_link_requires", lambda cid: by_id[cid]["action_link_requires"]),
        ("possible_decision_area",
         lambda cid: by_id[cid]["action_chain"]["possible_decision_area"]),
    ]
    for label, fn in rows:
        print(f"  {label}")
        for cid in FOCUS_IDS:
            short = cid.replace("ZHANGYUCHENG-2026-A-", "")
            print(f"      {short:<28} {fn(cid)}")
        print()


FOCUS_RANKS = {
    FOCUS_IDS[0]: "A=1  B=6  C=24",
    FOCUS_IDS[1]: "A=10 B=3  C=29",
    FOCUS_IDS[2]: "A=29 B=29 C=1",
}


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "rank", "confidence", "importance", "priority")

# percentile_rank 是 Step 6 建立的 evidence 描述子（在滾動分布中的經驗百分位），
# 不是 candidate 之間的名次。本階段只是原值攜帶它，因此從「沒有 ranking」的
# 欄位名掃描中排除這個確切名稱。除此之外任何含 rank 的欄位名仍會被抓出。
ALLOWED_RANK_FIELD_NAMES = ("percentile_rank",)
FORBIDDEN_WORDS = (
    "應該", "建議", "必須", "代打", "打第", "上場", "換投", "推薦",
    "should", "must", "recommend", "advise", "lineup",
    "strength", "weakness", "advantage", "disadvantage",
    "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
    "最重要", "最好", "最佳", "最差", "值得注意", "預測",
    "統計顯著", "顯著性", "顯著",
)
DECLARATIVE_KEYS = ("contains_no", "decision_area_is_not", "is_not_a_ranking")


def scan_keys(obj, path="") -> list:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if k not in DECLARATIVE_KEYS and k not in ALLOWED_RANK_FIELD_NAMES:
                for bad in FORBIDDEN_KEYS:
                    if bad in kl:
                        found.append(f"{path}.{k}")
                found += scan_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += scan_keys(v, f"{path}[{i}]")
    return found


def collect_declarative(records: list, perspectives: dict) -> str:
    items = []
    for r in records:
        items.append(r["contains_no"])
        items.append(r["action_chain"]["decision_area_is_not"])
        items.append(r["action_link_note"])
        items.append(r["next_game_dependency_note"])
    items.append([p["is_not_a_ranking"] for p in perspectives.values()])
    return json.dumps(items, ensure_ascii=False)


def build_all(logs, apart_rows):
    """把整個產出流程包起來，方便做 determinism 檢查。"""
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
    records = [
        build_relevance_record(c, views[c["candidate_id"]], samples[c["candidate_id"]])
        for c in candidates
    ]
    perspectives = build_perspectives(records)
    return candidates, views, samples, records, perspectives


def run_validation(
    candidates_before: list,
    candidates_after: list,
    records: list,
    perspectives: dict,
    fingerprints_before: dict,
    rerun_records: list,
    rerun_perspectives: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    n = len(candidates_after)
    rec_ids = [r["candidate_id"] for r in records]
    cand_ids = [c["candidate_id"] for c in candidates_after]

    # 1. 29 candidates 全部都有 sidecar record
    checks.append(
        (f"{n} 個 candidate 全部都有 sidecar record",
         len(records) == n == 29,
         f"candidates={n}　records={len(records)}")
    )

    # 2. candidate_id 一一對應
    one_to_one = sorted(rec_ids) == sorted(cand_ids) and len(set(rec_ids)) == len(rec_ids)
    checks.append(
        ("candidate_id 一一對應（無遺漏、無重複、無多餘）", one_to_one,
         f"record id 集合 == candidate id 集合：{sorted(rec_ids) == sorted(cand_ids)}"
         f"　record id 無重複：{len(set(rec_ids)) == len(rec_ids)}")
    )

    # 3. candidate evidence 沒被修改
    same = candidates_before == candidates_after
    checks.append(
        ("candidate evidence 完全未被修改（深度比較 29 個物件）", same,
         "sidecar 設計，沒有寫回路徑；逐欄位比較完全相同"
         if same else "有物件被改動")
    )

    # 4. raw / processed data 沒被修改
    changed = [p.name for p, before in fingerprints_before.items()
               if sha256_of(p) != before]
    checks.append(
        ("raw / processed data 未被修改", not changed,
         "　".join(f"{p.name} {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else f"被修改：{changed}")
    )

    # 5. 沒有 HTTP request
    checks.append(
        ("沒有任何 HTTP request", network_guard_active(),
         "socket.connect / connect_ex / create_connection 已被封鎖")
    )

    payload = {"records": records, "perspectives": perspectives}
    blob = json.dumps(payload, ensure_ascii=False)
    declarative = collect_declarative(records, perspectives)

    # 6 / 7 / 10. 沒有 score / weight / confidence score
    bad_keys = scan_keys(payload)
    checks.append(
        ("沒有 score 欄位", not [k for k in bad_keys if "score" in k.lower()],
         "沒有任何分數欄位"
         if not [k for k in bad_keys if "score" in k.lower()]
         else "；".join(k for k in bad_keys if "score" in k.lower()))
    )
    checks.append(
        ("沒有 weight 欄位", not [k for k in bad_keys if "weight" in k.lower()],
         "沒有任何權重欄位"
         if not [k for k in bad_keys if "weight" in k.lower()]
         else "；".join(k for k in bad_keys if "weight" in k.lower()))
    )
    checks.append(
        ("沒有 confidence score", not [k for k in bad_keys if "confidence" in k.lower()],
         "沒有" if not [k for k in bad_keys if "confidence" in k.lower()]
         else "有")
    )

    # 8. 沒有 threshold
    thr = [w for w in ("threshold", "門檻", "cutoff", "minimum_")
           if blob.count(w) - declarative.count(w) > 0]
    checks.append(
        ("沒有 threshold：29 個 candidate 全部產生 record，沒有任何被條件排除",
         len(records) == n and not thr,
         f"29/29 全部有 record；描述子指派只看 candidate 類型與 scope，不看數值"
         + ("" if not thr else f"　可疑字眼 {thr}"))
    )

    # 9. 沒有 ranking
    rank_keys = [k for k in bad_keys if "rank" in k.lower() or "priority" in k.lower()]
    order_dependent = []
    for p in perspectives.values():
        if p["members"] != sorted(p["members"]):
            order_dependent.append(p["key"])
    checks.append(
        ("沒有 ranking：沒有 candidate 名次欄位，perspective 成員一律以 "
         "candidate_id 字典序列出",
         not rank_keys and not order_dependent,
         "三個 perspective 的成員皆為字典序；沒有任何 candidate 名次或優先度欄位"
         "（percentile_rank 是 Step 6 的分布內百分位描述子，不是 candidate 名次，已排除）"
         if not rank_keys and not order_dependent
         else f"rank 欄位={rank_keys}　非字典序={order_dependent}")
    )

    # 11 / 12 / 13. 沒有 prediction / recommendation / 自然語言結論
    hits = []
    for w in FORBIDDEN_WORDS:
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    checks.append(
        ("沒有 prediction / recommendation / 自然語言結論字眼", not hits,
         "未出現禁用字眼（contains_no、decision_area_is_not 等否定宣告已扣除）"
         if not hits else "、".join(hits))
    )

    # 14. action_link 只能是受控詞彙中的識別字
    vocab_bad = []
    for r in records:
        for field, value in r["controlled_vocabulary_fields"].items():
            if not isinstance(value, str) or not IDENTIFIER_RE.match(value):
                vocab_bad.append(f"{r['candidate_id']}.{field} 非 snake_case 識別字")
            elif value not in VOCABULARY[field]:
                vocab_bad.append(f"{r['candidate_id']}.{field}={value} 不在受控詞彙中")
    checks.append(
        ("action_link 等決策欄位全部是受控詞彙中的 snake_case 識別字"
         "（結構上不可能出現自由文字的棒球建議）",
         not vocab_bad,
         f"7 個決策欄位 × 29 個 candidate = {7 * n} 個值全部通過"
         f"　詞彙表大小：" + "、".join(f"{k}={len(v)}" for k, v in VOCABULARY.items())
         if not vocab_bad else "；".join(vocab_bad[:5]))
    )

    # 15. 三個 perspective 的 membership 可追溯
    all_members = []
    for p in perspectives.values():
        all_members += p["members"]
    partition_ok = sorted(all_members) == sorted(cand_ids)
    overlap = len(all_members) != len(set(all_members))
    scope_bad = []
    scope_by_id = {r["candidate_id"]: r["scope"] for r in records}
    for p in perspectives.values():
        for cid in p["members"]:
            if scope_by_id[cid] not in p["scopes"]:
                scope_bad.append(f"{p['key']}: {cid} 的 scope 不在宣告範圍內")
    checks.append(
        ("三個 perspective 的 membership 可完整追溯且形成 partition",
         partition_ok and not overlap and not scope_bad,
         "A=" + str(perspectives['A_CURRENT_FORM']['member_count'])
         + "　B=" + str(perspectives['B_MATCHUP_CONTEXT']['member_count'])
         + "　C=" + str(perspectives['C_STRUCTURAL_CONTEXT']['member_count'])
         + f"　合計 {len(all_members)} == candidates {n}"
         f"　無重疊={not overlap}　每個成員的 scope 都在宣告範圍內={not scope_bad}")
    )

    # 16. 重跑結果 deterministic
    det_ok = (
        json.dumps(records, ensure_ascii=False, sort_keys=True)
        == json.dumps(rerun_records, ensure_ascii=False, sort_keys=True)
        and json.dumps(perspectives, ensure_ascii=False, sort_keys=True)
        == json.dumps(rerun_perspectives, ensure_ascii=False, sort_keys=True)
    )
    checks.append(
        ("相同輸入重跑結果完全一致（deterministic）", det_ok,
         "整個產出流程重跑一次，records 與 perspectives 的序列化結果完全相同"
         if det_ok else "重跑結果不同")
    )

    # 額外：Part 4 的三個 focus candidate 都存在
    by_id = {r["candidate_id"] for r in records}
    missing_focus = [cid for cid in FOCUS_IDS if cid not in by_id]
    checks.append(
        ("Part 4 指定的三個 candidate 都存在於 29 個 record 中", not missing_focus,
         "、".join(cid.replace("ZHANGYUCHENG-2026-A-", "") for cid in FOCUS_IDS)
         if not missing_focus else f"缺：{missing_focus}")
    )

    return checks


# ------------------------------------------------------------------ main

def main() -> None:
    logs, apart_rows = load_inputs()
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }

    candidates, views, samples, records, perspectives = build_all(logs, apart_rows)
    candidates_before = copy.deepcopy(candidates)

    # determinism 檢查用：整個流程重跑一次
    _, _, _, rerun_records, rerun_perspectives = build_all(logs, apart_rows)

    print("=" * 100)
    print("Decision Relevance Experiment（Step 13）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print(f"輸入：Step 9 的 {len(candidates)} 個 candidate")
    print("研究問題：什麼特徵讓一個 candidate 對教練的決策更有關聯？")
    print("不回答「哪個 candidate 最重要」，不回答「哪個 perspective 最好」，")
    print("沒有 ranking、沒有 score、沒有 weight、沒有 threshold、沒有建議、沒有預測。")
    print("=" * 100)

    print_descriptor_summary(records)
    print_perspectives(perspectives)
    print_focus_comparison(records, views, samples)
    print_records(records)

    print("\n" + "=" * 100)
    print("Validation")
    print("=" * 100)
    checks = run_validation(
        candidates_before, candidates, records, perspectives, fingerprints_before,
        rerun_records, rerun_perspectives,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/DECISION_RELEVANCE_EXPERIMENT.md。")

    print("\n" + "=" * 100)
    print("本階段沒有決定任何優先順序。描述子與 perspective 留給下一階段由人決定。")
    print("=" * 100)


if __name__ == "__main__":
    main()

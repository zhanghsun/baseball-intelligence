"""Group-level Decision Relevance Experiment（Step 19）。

它研究什麼：Step 18 的 9 個 insight group，哪些與實際決策的關聯比較直接。

它**不**做什麼：
    - 不做 ranking、不選最佳 group、不做 Top-N
    - 不建立 score / weight / threshold / priority / importance / confidence score
    - 不做 prediction / recommendation / 自然語言推薦
    - 不依 magnitude、sample size、classification 決定 relevance
    - 不新增 candidate 或 group
    - 不修改 candidate、不修改 Step 18 的 grouping、不修改 Step 13 的 descriptor
    - 不使用 LLM、不發 HTTP 請求

做法：把 Step 13 已驗證的 candidate 層級 decision descriptor **聚合**到 group 層級。
聚合前先檢查同 group 內的 descriptor 是否一致；不一致就記為矛盾並中止聚合該欄位。

用法：
    python src/group_decision_relevance.py
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
from decision_relevance import (  # noqa: E402
    ALLOWED_ACTION_LINKS,
    ALLOWED_ACTION_LINK_BASIS,
    ALLOWED_ACTION_LINK_REQUIRES,
    ALLOWED_DECISION_AREAS,
    CONTEXTUAL_RELEVANCE_VALUES,
    PERSPECTIVES,
    PERSPECTIVE_ORDER,
    TEMPORAL_RELEVANCE_VALUES,
    build_relevance_record,
)
from insight_grouping import build_groups  # noqa: E402
from noteworthy_insights import build_all as build_classification  # noqa: E402

# ------------------------------------------------------------------ 受控詞彙

# 沿用 Step 13 的詞彙，逐一對應。本階段沒有改動任何一個既有詞彙。
STEP13_VOCABULARY = {
    "temporal_relevance": TEMPORAL_RELEVANCE_VALUES,
    "contextual_relevance": CONTEXTUAL_RELEVANCE_VALUES,
    "possible_action_link": ALLOWED_ACTION_LINKS,
    "action_link_basis": ALLOWED_ACTION_LINK_BASIS,
    "action_link_requires": ALLOWED_ACTION_LINK_REQUIRES,
    "possible_decision_area": ALLOWED_DECISION_AREAS,
}

# ------------------------------------------------------------------
# 新增的最小詞彙：data_availability
#
# 為什麼必須新增：
#   Step 13 的第 7.1 節已經把每個 action_link_requires 的資料可取得性寫成散文
#   （「已驗證可取得」「部分可取得」「目前無法取得」「未驗證」），
#   但 Step 13 **沒有**把它做成受控詞彙欄位，程式輸出中也沒有對應欄位。
#   本階段需要一個可驗證、可機器讀取的欄位，因此新增這一組。
#
# 為什麼是最小的：
#   只有 4 個值，與 Step 13 第 7.1 節的四種散文描述一對一，沒有新增第五種狀態，
#   也沒有為任何 action_link_requires 改變既有的事實判定。
# ------------------------------------------------------------------
DATA_AVAILABILITY_VALUES = (
    "verified_available",
    "partially_verified",
    "not_investigated",
    "currently_unavailable",
)

NEW_VOCABULARY_JUSTIFICATION = (
    "Step 13 第 7.1 節已用散文記錄四種資料可取得性狀態，但沒有做成受控詞彙欄位。"
    "本階段需要機器可讀且可驗證的欄位，因此新增 data_availability。"
    "四個值與 Step 13 的四種散文描述一對一，沒有新增狀態，"
    "也沒有改變任何既有的事實判定。"
)

# action_link_requires -> (data_availability, 依據的 Step, 事實說明)
# 全部沿用 Step 13 第 7.1 節的既有判定，沒有重新評估。
AVAILABILITY_BY_REQUIREMENT = {
    "next_game_context": (
        "verified_available",
        ["Step 3", "Step 4", "Step 14"],
        "Step 3 的賽程 endpoint 已驗證可取得下一場日期、時間、對手、主客、場地；"
        "Step 4 落地為 processed schedule；Step 14 實際用它建出 next_game node"
        "（status = usable）。",
    ),
    "next_starting_pitcher_hand": (
        "partially_verified",
        ["Step 3", "Step 7A", "Step 14"],
        "Step 7A 在【已完成】比賽上驗證「賽程投手 Acnt → 球員頁投打習慣」5/5 通過；"
        "但未開打場次的 Acnt 是否代表預告先發，Step 3 與 Step 7A 都標記為未確認，"
        "Step 14 因此把 pitcher_hand node 標為 blocked。",
    ),
    "in_game_pitcher_role_at_plate_appearance": (
        "currently_unavailable",
        ["Step 2", "Step 7A", "Step 8"],
        "Step 2 已確認逐場成績 41 個欄位沒有任何投手欄位；"
        "Step 8 已確認官方分項沒有逐打席明細；"
        "逐打席投手只存在於 /box/getlive，該 payload 從 Step 2 至今從未驗證過。",
    ),
    "next_starting_pitcher_registration_status": (
        "not_investigated",
        [],
        "本專案從未調查官方是否提供投手的本土／外籍註冊狀態。"
        "Step 13 第 7.1 節已標記為未驗證。",
    ),
}

# 需要聚合的 Step 13 descriptor 欄位（必須同 group 內一致）
AGGREGATED_FIELDS = (
    "temporal_relevance",
    "contextual_relevance",
    "possible_action_link",
    "action_link_basis",
    "action_link_requires",
    "possible_decision_area",
)

# 明確記錄「沒有被用來決定 relevance」的量
RELEVANCE_NOT_INPUTS = [
    "magnitude", "sample_size_at_bats", "plate_appearances",
    "percentile_rank", "consistency_count", "classification",
]


# ------------------------------------------------------------------ 聚合

def step13_field(record: dict, field: str):
    """讀取 Step 13 record 的 descriptor。

    `possible_decision_area` 在 Step 13 中放在 action_chain 內，其餘在頂層。
    這裡只是讀取位置的對應，沒有改動任何值。
    """
    if field == "possible_decision_area":
        return record["action_chain"]["possible_decision_area"]
    return record[field]


def aggregate_group(group: dict, step13_by_id: dict) -> dict:
    """把同 group 成員的 Step 13 descriptor 聚合成 group 層級記錄。"""
    member_ids = list(group["member_candidate_ids"])
    members = [step13_by_id[cid] for cid in member_ids]

    aggregated: dict = {}
    conflicts: dict = {}
    for field in AGGREGATED_FIELDS:
        values = sorted({step13_field(m, field) for m in members},
                        key=lambda v: (v is None, v))
        if len(values) == 1:
            aggregated[field] = values[0]
        else:
            aggregated[field] = None
            conflicts[field] = {
                "distinct_values": values,
                "by_candidate": {
                    m["candidate_id"]: step13_field(m, field) for m in members
                },
            }

    # next_game_dependency 是布林，單獨處理
    dep_values = sorted({m["next_game_dependency"] for m in members})
    if len(dep_values) == 1:
        evidence_dep = dep_values[0]
    else:
        evidence_dep = None
        conflicts["next_game_dependency"] = {
            "distinct_values": dep_values,
            "by_candidate": {
                m["candidate_id"]: m["next_game_dependency"] for m in members
            },
        }

    requirement = aggregated["action_link_requires"]
    availability, avail_steps, avail_note = AVAILABILITY_BY_REQUIREMENT[requirement]

    return {
        "group_id": group["group_id"],
        "scope": group["scope"],
        "perspective": group["perspective"],
        "perspective_name": group["perspective_name"],
        "member_candidate_ids": member_ids,
        "member_count": len(member_ids),

        # ---- 維度 1：時間性 ----
        "temporal_relevance": aggregated["temporal_relevance"],

        # ---- 維度 2：情境 ----
        "contextual_relevance": aggregated["contextual_relevance"],
        "context_official_item_name": (
            members[0]["context_official_item_name"] if members[0]["context_code"]
            else None
        ),

        # ---- 維度 3：next_game_dependency（evidence 本身是否依賴下一場）----
        "next_game_dependency": {
            "evidence_depends_on_next_game": evidence_dep,
            "meaning": (
                "描述 **evidence 本身** 是否需要下一場資訊才完整。"
                "這是 Step 13 的 next_game_dependency，原樣沿用。"
            ),
            "basis": members[0]["next_game_dependency_basis"],
            "is_not": (
                "這**不是**「使用這個 evidence 做下一場決策時是否需要額外資料」。"
                "後者記錄在 application_dependency 中。兩者刻意分開。"
            ),
        },

        # ---- 維度 4 / 5：action_link 與所需資料 ----
        "action_link": {
            "possible_action_link": aggregated["possible_action_link"],
            "action_link_basis": aggregated["action_link_basis"],
            "possible_decision_area": aggregated["possible_decision_area"],
            "is_not": (
                "這是「資料可以連到哪一類決策」的描述，不是決策本身，也不是建議。"
            ),
        },
        "action_link_requires": requirement,

        # ---- 維度 4 與 3 的區分（本階段要求 4）----
        "application_dependency": {
            "requires_additional_data": requirement is not None,
            "additional_data": requirement,
            "meaning": (
                "描述 **把 evidence 應用到下一場決策時** 是否需要額外資料。"
                "與 next_game_dependency 是兩件不同的事。"
            ),
            "distinction_note": (
                "Step 13 第 7.2 節已記錄這個區分：evidence 本身完整"
                "（next_game_dependency = false）不代表應用時不需要額外資料。"
            ),
        },

        # ---- 維度 6：資料可取得性 ----
        "data_availability": {
            "status": availability,
            "applies_to_requirement": requirement,
            "evidence_steps": avail_steps,
            "factual_basis": avail_note,
            "vocabulary_origin": "new_in_step_19",
            "vocabulary_justification": NEW_VOCABULARY_JUSTIFICATION,
        },

        # ---- 一致性檢查結果 ----
        "member_consistency": {
            "all_aggregated_fields_uniform": not conflicts,
            "conflicting_fields": sorted(conflicts),
            "conflicts": conflicts,
            "checked_fields": list(AGGREGATED_FIELDS) + ["next_game_dependency"],
            "note": (
                "聚合前逐欄位檢查同 group 成員的 descriptor 是否一致。"
                "若不一致，該欄位聚合值設為 null 並記錄衝突，不強行合併。"
            ),
        },

        "relevance_rule": {
            "rule_id": "D19-1",
            "version": "first_version",
            "rule_text": (
                "group 層級的 decision relevance 完全由成員的 Step 13 descriptor "
                "聚合而成；聚合只在成員一致時成立。"
            ),
            "rule_inputs": ["step13_candidate_decision_descriptors", "group_membership"],
            "rule_not_inputs": list(RELEVANCE_NOT_INPUTS),
        },

        "provenance": {
            "group_source_step": "Step 18",
            "group_source_module": "src/insight_grouping.py",
            "descriptor_source_step": "Step 13",
            "descriptor_source_module": "src/decision_relevance.py",
            "candidate_source_step": "Step 9",
            "candidate_source_module": "src/candidate_insights.py",
            "availability_source_step": "Step 13 第 7.1 節（散文）+ Step 2 / 3 / 7A / 8 / 14 的調查結果",
            "source_files": list(group["provenance"]["source_files"]),
            "sidecar_note": (
                "本記錄為 sidecar，用 group_id 關聯，不寫回 group 或 candidate 物件"
            ),
        },

        "contains_no": [
            "score", "weight", "threshold", "ranking", "priority", "importance",
            "confidence_score", "prediction", "recommendation",
            "natural_language_conclusion", "top_n", "llm",
        ],
    }


def build_group_relevance(groups: list, step13_records: list) -> list:
    step13_by_id = {r["candidate_id"]: r for r in step13_records}
    return [aggregate_group(g, step13_by_id) for g in
            sorted(groups, key=lambda g: g["scope"])]


# ------------------------------------------------------------------ 反證

def mutation_test(logs, apart_rows, baseline_records: list) -> dict:
    """把 magnitude / AB / PA 換成極端值後重跑整條流程，確認 group 層級結果不變。

    全部在深拷貝上操作。比對的是 group-level relevance 的完整簽章。
    """
    def signature(records: list) -> str:
        return json.dumps(
            [
                {
                    "scope": r["scope"],
                    "members": r["member_candidate_ids"],
                    "temporal_relevance": r["temporal_relevance"],
                    "contextual_relevance": r["contextual_relevance"],
                    "evidence_depends_on_next_game":
                        r["next_game_dependency"]["evidence_depends_on_next_game"],
                    "possible_action_link": r["action_link"]["possible_action_link"],
                    "action_link_requires": r["action_link_requires"],
                    "possible_decision_area":
                        r["action_link"]["possible_decision_area"],
                    "data_availability": r["data_availability"]["status"],
                    "requires_additional_data":
                        r["application_dependency"]["requires_additional_data"],
                }
                for r in records
            ],
            ensure_ascii=False, sort_keys=True,
        )

    base_sig = signature(baseline_records)
    diffs = []
    cases = 0

    mutants = [
        ("magnitude", 0.0), ("magnitude", 999.0),
        ("at_bats", 1), ("at_bats", 9999),
        ("plate_appearances", 1), ("plate_appearances", 9999),
    ]

    for kind, value in mutants:
        candidates, views, samples, _pbc, nw_records = build_classification(
            logs, apart_rows
        )
        candidates = copy.deepcopy(candidates)
        views = copy.deepcopy(views)
        samples = copy.deepcopy(samples)

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
                cid = c["candidate_id"]
                samples[cid]["sample_context"][kind] = value
                if kind == "at_bats":
                    c["at_bats"] = value
                else:
                    c["plate_appearances"] = value

        step13 = [
            build_relevance_record(c, views[c["candidate_id"]],
                                   samples[c["candidate_id"]])
            for c in candidates
        ]
        nw_by_id = {r["candidate_id"]: r for r in nw_records}
        groups = build_groups(candidates, views, samples, nw_by_id)
        got = build_group_relevance(groups, step13)

        cases += 1
        if signature(got) != base_sig:
            diffs.append(f"{kind}={value} 時 group-level relevance 改變")

    return {
        "mutants": [f"{k}={v}" for k, v in mutants],
        "cases_tested": cases,
        "changes": diffs,
        "relevance_independent_of_values": not diffs,
    }


# ------------------------------------------------------------------ 輸出

def print_structure(records: list) -> None:
    print("\n" + "=" * 104)
    print("9 個 group 的 decision relevance 結構")
    print("=" * 104)
    print(f"  {'scope':<14} {'temporal':<19} {'contextual':<21} "
          f"{'evid_dep':<9} {'availability':<23}")
    for r in records:
        print(f"  {r['scope']:<14} {r['temporal_relevance']:<19} "
              f"{r['contextual_relevance']:<21} "
              f"{str(r['next_game_dependency']['evidence_depends_on_next_game']):<9} "
              f"{r['data_availability']['status']:<23}")

    print(f"\n  {'scope':<14} {'possible_action_link':<44} "
          f"{'decision_area':<34}")
    for r in records:
        print(f"  {r['scope']:<14} {r['action_link']['possible_action_link']:<44} "
              f"{r['action_link']['possible_decision_area']:<34}")

    print(f"\n  {'scope':<14} {'action_link_requires':<44} {'requires_extra':<15}")
    for r in records:
        print(f"  {r['scope']:<14} {r['action_link_requires']:<44} "
              f"{str(r['application_dependency']['requires_additional_data']):<15}")


def print_detail(records: list) -> None:
    print("\n" + "=" * 104)
    print("每個 group 的完整記錄")
    print("=" * 104)
    for r in records:
        print(f"\n  [{r['group_id']}]")
        print(f"    scope                     : {r['scope']}")
        print(f"    perspective               : {r['perspective']}"
              f"（{r['perspective_name']}）")
        print(f"    member_count              : {r['member_count']}")
        print(f"    temporal_relevance        : {r['temporal_relevance']}")
        print(f"    contextual_relevance      : {r['contextual_relevance']}"
              + (f"（官方 {r['context_official_item_name']}）"
                 if r["context_official_item_name"] else ""))
        nd = r["next_game_dependency"]
        print(f"    next_game_dependency      : "
              f"evidence_depends_on_next_game = "
              f"{nd['evidence_depends_on_next_game']}")
        print(f"        意義                  : {nd['meaning']}")
        ad = r["application_dependency"]
        print(f"    application_dependency    : "
              f"requires_additional_data = {ad['requires_additional_data']}"
              f"　additional_data = {ad['additional_data']}")
        print(f"        意義                  : {ad['meaning']}")
        al = r["action_link"]
        print(f"    action_link               : {al['possible_action_link']}")
        print(f"        basis                 : {al['action_link_basis']}")
        print(f"        decision_area         : {al['possible_decision_area']}")
        da = r["data_availability"]
        print(f"    data_availability         : {da['status']}")
        print(f"        依據 Step             : "
              f"{da['evidence_steps'] if da['evidence_steps'] else '（無，尚未調查）'}")
        print(f"        事實說明              : {da['factual_basis']}")
        mc = r["member_consistency"]
        print(f"    member_consistency        : all_uniform="
              f"{mc['all_aggregated_fields_uniform']}"
              f"　conflicting_fields={mc['conflicting_fields']}")
        print(f"    relevance_rule            : {r['relevance_rule']['rule_id']}"
              f"　inputs={r['relevance_rule']['rule_inputs']}")
        print(f"    members:")
        for cid in r["member_candidate_ids"]:
            print(f"      - {cid}")


def print_answers(records: list) -> None:
    print("\n" + "=" * 104)
    print("回答")
    print("=" * 104)

    direct = [r["scope"] for r in records
              if r["next_game_dependency"]["evidence_depends_on_next_game"]]
    indirect = [r["scope"] for r in records
                if not r["next_game_dependency"]["evidence_depends_on_next_game"]]
    print(f"\n  (1) evidence 本身直接連到下一場（next_game_dependency = true）："
          f"{len(direct)} 個")
    print(f"      {direct}")
    print(f"      evidence 本身不依賴下一場（self-contained）：{len(indirect)} 個")
    print(f"      {indirect}")

    with_dep = [r["scope"] for r in records
                if r["application_dependency"]["requires_additional_data"]]
    print(f"\n  (2) 有 action dependency（應用時需要額外資料）：{len(with_dep)} 個")
    print(f"      {with_dep}")
    no_dep = [r["scope"] for r in records
              if not r["application_dependency"]["requires_additional_data"]]
    print(f"      沒有 action dependency：{len(no_dep)} 個　{no_dep}")

    print(f"\n  (3) dependency 的資料可取得性：")
    by_avail: dict[str, list] = {}
    for r in records:
        by_avail.setdefault(r["data_availability"]["status"], []).append(r["scope"])
    for status in DATA_AVAILABILITY_VALUES:
        scopes = by_avail.get(status, [])
        print(f"      {status:<24} {len(scopes)} 個　{scopes}")
        if scopes:
            sample = next(r for r in records
                          if r["data_availability"]["status"] == status)
            print(f"          requirement : {sample['action_link_requires']}")
            print(f"          依據 Step   : "
                  f"{sample['data_availability']['evidence_steps'] or '（無）'}")

    print(f"\n  (4) 資訊可以直接使用 vs 需要額外資料（交叉表）：")
    print(f"      {'evidence 自足':<16}{'availability':<24}{'scopes'}")
    combos: dict[tuple, list] = {}
    for r in records:
        key = (
            not r["next_game_dependency"]["evidence_depends_on_next_game"],
            r["data_availability"]["status"],
        )
        combos.setdefault(key, []).append(r["scope"])
    for (self_contained, avail), scopes in sorted(
        combos.items(), key=lambda kv: (not kv[0][0], kv[0][1])
    ):
        print(f"      {str(self_contained):<16}{avail:<24}{scopes}")
    print("\n      註：全部 9 個 group 的 action_link 都需要額外資料，")
    print("      　　其中只有 2 個所需資料已被驗證可取得。")


# ------------------------------------------------------------------ 驗證

FORBIDDEN_KEYS = ("score", "weight", "threshold", "rank", "priority",
                  "importance", "confidence", "top_n")
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
    groups_before: list, groups_after: list, records: list, rerun_records: list,
    step13_records: list, candidates_before: list, candidates_after: list,
    mutation: dict, fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []

    # 1. 9 groups 全部都有且只有一筆 record
    scopes = [r["scope"] for r in records]
    group_scopes = sorted(g["scope"] for g in groups_after)
    ok1 = (
        len(records) == len(groups_after) == 9
        and sorted(scopes) == group_scopes
        and len(set(scopes)) == len(scopes)
    )
    checks.append(
        ("9 個 group 全部都有且只有一筆 record", ok1,
         f"groups={len(groups_after)}　records={len(records)}"
         f"　scope 集合相同={sorted(scopes) == group_scopes}"
         f"　無重複={len(set(scopes)) == len(scopes)}")
    )

    # 2. membership 與 Step 18 完全一致
    by_scope = {g["scope"]: g for g in groups_after}
    mem_bad = []
    total_members = 0
    for r in records:
        g = by_scope[r["scope"]]
        if r["member_candidate_ids"] != g["member_candidate_ids"]:
            mem_bad.append(r["scope"])
        if r["member_count"] != g["member_count"]:
            mem_bad.append(f"{r['scope']} member_count")
        if r["perspective"] != g["perspective"]:
            mem_bad.append(f"{r['scope']} perspective")
        total_members += r["member_count"]
    checks.append(
        ("candidate / group membership 與 Step 18 完全一致", not mem_bad,
         f"9 個 group 的成員清單、成員數、perspective 全部逐一相符；"
         f"成員總數 {total_members} = 29"
         if not mem_bad else "；".join(mem_bad[:5]))
    )

    # 3. Step 13 的 29 個 descriptor 正確聚合到 group
    step13_by_id = {r["candidate_id"]: r for r in step13_records}
    agg_bad = []
    covered = set()
    for r in records:
        for cid in r["member_candidate_ids"]:
            covered.add(cid)
            m = step13_by_id[cid]
            for field in AGGREGATED_FIELDS:
                if field == "action_link_requires":
                    got = r["action_link_requires"]
                elif field in ("possible_action_link", "action_link_basis",
                               "possible_decision_area"):
                    got = r["action_link"][field]
                else:
                    got = r[field]
                if got != step13_field(m, field):
                    agg_bad.append(f"{r['scope']}.{field} 與 {cid} 不符")
            if (r["next_game_dependency"]["evidence_depends_on_next_game"]
                    != m["next_game_dependency"]):
                agg_bad.append(f"{r['scope']}.next_game_dependency 與 {cid} 不符")
    if len(covered) != 29:
        agg_bad.append(f"只覆蓋 {len(covered)} 個 candidate，應為 29")
    checks.append(
        ("Step 13 的 29 個 candidate-level decision descriptor 正確聚合到 group",
         not agg_bad,
         f"29 個 candidate 全部覆蓋；7 個 descriptor 欄位 × 29 = 203 次逐一比對相符"
         if not agg_bad else "；".join(agg_bad[:5]))
    )

    # 4. 同 group 的 candidate 沒有互相矛盾的 descriptor
    conflict_groups = [r["scope"] for r in records
                       if not r["member_consistency"]["all_aggregated_fields_uniform"]]
    checks.append(
        ("同 group 的 candidate 沒有產生互相矛盾的 decision descriptor",
         not conflict_groups,
         f"9 個 group 逐欄位檢查 "
         f"{len(AGGREGATED_FIELDS) + 1} 個 descriptor，全部成員一致"
         if not conflict_groups else f"有衝突：{conflict_groups}")
    )

    # 5. 不修改 Step 18 grouping
    same_groups = groups_before == groups_after
    checks.append(
        ("沒有修改 Step 18 的 grouping（深度比較 9 個 group 物件）", same_groups,
         "sidecar 設計，沒有寫回路徑；逐欄位比較完全相同"
         if same_groups else "有 group 被改動")
    )

    # 額外：也沒有修改 candidate
    same_cand = candidates_before == candidates_after
    checks.append(
        ("沒有修改 candidate（深度比較 29 個物件）", same_cand,
         "逐欄位比較完全相同" if same_cand else "有 candidate 被改動")
    )

    # 6. 不修改 raw / processed data
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
                "rule_not_inputs": r["relevance_rule"]["rule_not_inputs"],
                "next_game_is_not": r["next_game_dependency"]["is_not"],
                "action_link_is_not": r["action_link"]["is_not"],
                "distinction_note": r["application_dependency"]["distinction_note"],
                "vocab_justification":
                    r["data_availability"]["vocabulary_justification"],
            }
            for r in records
        ],
        ensure_ascii=False,
    )

    # 7. 不產生 score / weight / threshold / ranking / priority / importance
    bad_keys = scan_keys(payload)
    thr = []
    for w in ("threshold", "門檻", "cutoff", "top_n", "Top-N"):
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            thr.append(f"{w}×{cnt}")
    checks.append(
        ("沒有 score / weight / threshold / ranking / priority / importance / "
         "confidence score", not bad_keys and not thr,
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

    # 10. mutation test
    checks.append(
        ("mutation test：magnitude / AB / PA 換成極端值後 group-level relevance 不變",
         mutation["relevance_independent_of_values"],
         f"變異 {mutation['mutants']}，共 {mutation['cases_tested']} 次完整重跑，"
         f"結果改變 {len(mutation['changes'])} 次"
         if mutation["relevance_independent_of_values"]
         else "；".join(mutation["changes"]))
    )

    # 11. 受控詞彙檢查
    vocab_bad = []
    for r in records:
        pairs = [
            ("temporal_relevance", r["temporal_relevance"]),
            ("contextual_relevance", r["contextual_relevance"]),
            ("possible_action_link", r["action_link"]["possible_action_link"]),
            ("action_link_basis", r["action_link"]["action_link_basis"]),
            ("action_link_requires", r["action_link_requires"]),
            ("possible_decision_area", r["action_link"]["possible_decision_area"]),
        ]
        for field, value in pairs:
            if value not in STEP13_VOCABULARY[field]:
                vocab_bad.append(f"{r['scope']}.{field}={value} 不在 Step 13 詞彙中")
        if r["data_availability"]["status"] not in DATA_AVAILABILITY_VALUES:
            vocab_bad.append(f"{r['scope']}.data_availability 不在新增詞彙中")
    checks.append(
        ("所有欄位值都在受控詞彙內（6 個沿用 Step 13，1 個為本階段新增）",
         not vocab_bad,
         f"6 × 9 = 54 個值全部在 Step 13 詞彙中；"
         f"9 個 data_availability 全部在新增的 4 值詞彙中"
         if not vocab_bad else "；".join(vocab_bad[:5]))
    )

    # 12. 沒有自然語言推薦
    forbidden = ("擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
                 "建議", "應該", "推薦", "預測", "最佳", "最好", "最差",
                 "值得注意", "統計顯著", "顯著性", "recommend", "should", "best")
    hits = []
    for w in forbidden:
        cnt = blob.count(w) - declarative.count(w)
        if cnt > 0:
            hits.append(f"{w}×{cnt}")
    checks.append(
        ("沒有自然語言推薦或價值判斷字眼", not hits,
         "未出現禁用字眼（宣告性與說明性欄位已扣除）"
         if not hits else "、".join(hits))
    )

    # 13. relevance 未依 magnitude / sample size / classification 決定
    rule_ok = all(
        r["relevance_rule"]["rule_inputs"]
        == ["step13_candidate_decision_descriptors", "group_membership"]
        and r["relevance_rule"]["rule_not_inputs"] == RELEVANCE_NOT_INPUTS
        for r in records
    )
    # 結構性檢查：沒有任何欄位名含 classification
    cls_keys = []

    def scan_cls(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k not in DECLARATIVE_KEYS and "classification" in k.lower():
                    cls_keys.append(f"{path}.{k}")
                scan_cls(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                scan_cls(v, f"{path}[{i}]")

    scan_cls(payload)
    # 字串掃描：扣除 rule_not_inputs 這個「宣告不使用 classification」的清單
    cls_text = blob.count("classification") - declarative.count("classification")
    no_cls = not cls_keys and cls_text <= 0
    checks.append(
        ("relevance 沒有依 magnitude / sample size / classification 決定",
         rule_ok and no_cls and mutation["relevance_independent_of_values"],
         f"rule_inputs 只有 2 項；rule_not_inputs 明確列出 "
         f"{len(RELEVANCE_NOT_INPUTS)} 個未使用的量；"
         "輸出中沒有任何 classification 欄位（rule_not_inputs 中的否定宣告已扣除）；"
         "mutation test 6 次重跑結果不變"
         if rule_ok and no_cls else
         f"rule_ok={rule_ok}　classification 欄位={cls_keys}"
         f"　非宣告性字串出現 {cls_text} 次")
    )

    return checks


# ------------------------------------------------------------------ main

def build_everything(logs, apart_rows):
    candidates, views, samples, _pbc, nw_records = build_classification(
        logs, apart_rows
    )
    step13 = [
        build_relevance_record(c, views[c["candidate_id"]],
                               samples[c["candidate_id"]])
        for c in candidates
    ]
    nw_by_id = {r["candidate_id"]: r for r in nw_records}
    groups = build_groups(candidates, views, samples, nw_by_id)
    records = build_group_relevance(groups, step13)
    return candidates, groups, step13, records


def main() -> None:
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }
    logs, apart_rows = load_inputs()

    candidates, groups, step13, records = build_everything(logs, apart_rows)
    candidates_before = copy.deepcopy(candidates)
    groups_before = copy.deepcopy(groups)
    _, _, _, rerun_records = build_everything(logs, apart_rows)
    mutation = mutation_test(logs, apart_rows, records)

    print("=" * 104)
    print("Group-level Decision Relevance Experiment（Step 19）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print(f"研究對象固定為 Step 18 的 {len(groups)} 個 insight group")
    print("只研究「決策關聯結構」，不研究證據強度。")
    print("沒有 ranking、沒有 Top-N、沒有 score / weight / threshold / priority，")
    print("沒有 prediction / recommendation / 自然語言推薦，沒有 LLM。")
    print("=" * 104)
    print(f"\n沿用 Step 13 的受控詞彙（6 組，未改動）：")
    for field, values in STEP13_VOCABULARY.items():
        print(f"  {field:<24} {len(values)} 個值")
    print(f"\n本階段新增的最小詞彙（1 組）：")
    print(f"  data_availability        {len(DATA_AVAILABILITY_VALUES)} 個值："
          f"{list(DATA_AVAILABILITY_VALUES)}")
    print(f"  新增理由：{NEW_VOCABULARY_JUSTIFICATION}")

    print_structure(records)
    print_answers(records)
    print_detail(records)

    print("\n" + "=" * 104)
    print("Mutation test")
    print("=" * 104)
    print(f"  變異               : {mutation['mutants']}")
    print(f"  完整重跑次數       : {mutation['cases_tested']}")
    print(f"  結果改變次數       : {len(mutation['changes'])}")
    print(f"  relevance 與數值無關: {mutation['relevance_independent_of_values']}")

    print("\n" + "=" * 104)
    print("Validation")
    print("=" * 104)
    checks = run_validation(
        groups_before, groups, records, rerun_records, step13,
        candidates_before, candidates, mutation, fingerprints_before,
    )
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 "
              "docs/GROUP_DECISION_RELEVANCE_EXPERIMENT.md。")

    print("\n" + "=" * 104)
    print("本階段只描述決策關聯結構，沒有選出最佳 group，沒有排序，沒有推薦。")
    print("=" * 104)


if __name__ == "__main__":
    main()

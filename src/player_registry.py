"""Player registry（Step 28）。

**這是本專案唯一的 player mapping 來源。** API 與前端都從這裡取得球員清單，
不允許在別的地方再寫一份 player id → 資料的對照表。

它做什麼：
    - 宣告目前產品支援哪些球員，以及每位球員的識別資訊
    - 記錄每位球員的 product output 由哪一支 builder 產生
    - 提供 registry 順序（`/api/players` 的順序就是這裡的順序，沒有排序）
    - 提供一致性驗證（`validate_registry`），確保 registry 不會與實際 pipeline 漂移

它**不**做什麼：
    - 不做 ranking、priority、score、weight、threshold
    - 不抓資料、不發 HTTP、不讀 data/
    - 不偽造球員。目前 registry 只有一筆，因為目前只有一位球員的真實資料

順序的意義：
    `PLAYERS` 是 tuple，順序就是宣告順序。這個順序只是「registry 順序」，
    **不是**名次、不是重要性、不是 Top-N。API 一律照這個順序輸出，不自行排序。
"""

from __future__ import annotations

# ------------------------------------------------------------------ registry

# 每一筆必須有的欄位
REQUIRED_FIELDS = (
    "player_id",
    "player_name",
    "player_acnt",
    "team",
    "team_code",
    "season",
    "kind_code",
    "kind_name",
    "product_output",
)

# product_output 區塊必須有的欄位
REQUIRED_PRODUCT_OUTPUT_FIELDS = ("module", "function", "source_step")

# 目前產品支援的球員。**只有真實存在資料的球員才可以出現在這裡。**
PLAYERS: tuple[dict, ...] = (
    {
        "player_id": "zhang-yucheng",
        "player_name": "張育成",
        "player_acnt": "0000006888",
        "team": "富邦悍將",
        "team_code": "AEO011",
        "season": 2026,
        "kind_code": "A",
        "kind_name": "一軍例行賽",
        "product_output": {
            "module": "src/product_output_model.py",
            "function": "build_product_output",
            "source_step": "Step 22",
        },
    },
)

# 依 registry 順序的 id 清單。**沒有排序。**
PLAYER_IDS: tuple[str, ...] = tuple(p["player_id"] for p in PLAYERS)

# id -> entry。dict 保留插入順序，因此走訪順序與 PLAYER_IDS 相同。
PLAYER_BY_ID: dict[str, dict] = {p["player_id"]: p for p in PLAYERS}

ORDER_NOTE = {
    "basis": "registry_order",
    "is_not": (
        "這只是 src/player_registry.py 的宣告順序，"
        "不是 ranking、不是 priority、不是 Top-N，也沒有經過任何排序。"
    ),
}

REGISTRY_SOURCE = {
    "module": "src/player_registry.py",
    "note": "本專案唯一的 player mapping 來源；API 與前端都從這裡取得球員清單。",
}

# `/api/players` 對外暴露的欄位（不含內部 builder 細節）
PUBLIC_FIELDS = (
    "player_id",
    "player_name",
    "player_acnt",
    "team",
    "team_code",
    "season",
    "kind_code",
    "kind_name",
)


# ------------------------------------------------------------------ 查詢

def player_ids() -> list[str]:
    """依 registry 順序回傳 id 清單。"""
    return list(PLAYER_IDS)


def get_player(player_id: str) -> dict | None:
    """依 id 查 registry。查不到回 None，絕不猜測、絕不 fallback 到某個預設球員。"""
    return PLAYER_BY_ID.get(player_id)


def default_player_id() -> str:
    """registry 中的第一筆。只用於 CLI 預熱之類的場合，不用於路由。"""
    return PLAYER_IDS[0]


def public_player_view(entry: dict) -> dict:
    """對外的球員摘要。附上該球員的 product output 端點路徑。"""
    view = {field: entry[field] for field in PUBLIC_FIELDS}
    view["player_endpoint"] = f"/api/player/{entry['player_id']}"
    return view


def public_player_list() -> list[dict]:
    """依 registry 順序回傳對外摘要清單。"""
    return [public_player_view(entry) for entry in PLAYERS]


# ------------------------------------------------------------------ 驗證

def validate_registry() -> list[str]:
    """registry 自我檢查。回傳問題清單，空清單代表通過。

    最後一項會與實際 pipeline 的 subject 交叉核對，避免 registry 與
    `candidate_insights.SUBJECT` 漂移成兩份互相矛盾的設定。
    """
    problems: list[str] = []

    if not PLAYERS:
        problems.append("registry 是空的")

    seen: set[str] = set()
    for index, entry in enumerate(PLAYERS):
        label = entry.get("player_id", f"index {index}")
        for field in REQUIRED_FIELDS:
            if field not in entry or entry[field] in (None, "", {}):
                problems.append(f"{label} 缺欄位 {field}")
        po = entry.get("product_output") or {}
        for field in REQUIRED_PRODUCT_OUTPUT_FIELDS:
            if not po.get(field):
                problems.append(f"{label} 的 product_output 缺 {field}")
        pid = entry.get("player_id")
        if pid in seen:
            problems.append(f"重複的 player_id：{pid}")
        seen.add(pid)
        if pid and pid != pid.lower():
            problems.append(f"player_id 必須全小寫：{pid}")
        if pid and (" " in pid or "/" in pid):
            problems.append(f"player_id 不得含空白或斜線：{pid}")

    if len(PLAYER_IDS) != len(PLAYER_BY_ID):
        problems.append("PLAYER_IDS 與 PLAYER_BY_ID 筆數不一致")
    if list(PLAYER_BY_ID) != list(PLAYER_IDS):
        problems.append("PLAYER_BY_ID 的順序與 PLAYER_IDS 不一致")

    # 與實際 pipeline 的 subject 交叉核對（延後 import，避免不必要的副作用）
    try:
        from candidate_insights import SUBJECT
    except Exception as exc:  # noqa: BLE001
        problems.append(f"無法載入 pipeline subject 進行交叉核對：{type(exc).__name__}")
        return problems

    subject_entries = [
        e for e in PLAYERS
        if e["player_acnt"] == SUBJECT["player_acnt"]
        and e["season"] == SUBJECT["season"]
        and e["kind_code"] == SUBJECT["kind_code"]
    ]
    if len(subject_entries) != 1:
        problems.append(
            "registry 中應該恰好有一筆對應目前 pipeline subject "
            f"（Acnt {SUBJECT['player_acnt']} / {SUBJECT['season']} / "
            f"{SUBJECT['kind_code']}），實際 {len(subject_entries)} 筆"
        )
    else:
        entry = subject_entries[0]
        for registry_field, subject_field in (
            ("player_name", "player_name"),
            ("team", "team"),
            ("team_code", "team_code"),
            ("kind_name", "kind_name"),
        ):
            if entry[registry_field] != SUBJECT[subject_field]:
                problems.append(
                    f"{entry['player_id']} 的 {registry_field} 與 pipeline "
                    f"SUBJECT.{subject_field} 不一致："
                    f"{entry[registry_field]!r} vs {SUBJECT[subject_field]!r}"
                )

    # 目前 pipeline 只支援一位球員，registry 不得多於它實際能產出的球員數
    if len(PLAYERS) > 1:
        problems.append(
            "registry 有多於一筆球員，但目前 pipeline 只支援單一 subject。"
            "新增球員前必須先讓 pipeline 能為該球員產出 product output。"
        )

    return problems


def describe() -> dict:
    """給文件與健康檢查用的摘要。"""
    return {
        "registry_source": dict(REGISTRY_SOURCE),
        "order": dict(ORDER_NOTE),
        "player_count": len(PLAYERS),
        "player_ids": player_ids(),
        "multi_player_ready": True,
        "multi_player_ready_note": (
            "API 路由與前端都由 registry 驅動，不再寫死任何 player id。"
            "但目前 registry 只有一位球員，因為只有這一位有真實資料。"
        ),
        "contains_no": [
            "ranking", "priority", "score", "weight", "threshold",
            "top_n", "prediction", "recommendation", "fabricated_player",
        ],
    }


def main() -> None:
    problems = validate_registry()
    info = describe()
    print("=" * 84)
    print("Player Registry（Step 28）")
    print("=" * 84)
    print(f"  來源           : {info['registry_source']['module']}")
    print(f"  球員數         : {info['player_count']}")
    print(f"  順序依據       : {info['order']['basis']}")
    print(f"                   {info['order']['is_not']}")
    print()
    for index, entry in enumerate(PLAYERS, start=1):
        view = public_player_view(entry)
        print(f"  [{index}] {view['player_id']}")
        print(f"      {view['player_name']}（{view['team']}）"
              f"　Acnt {view['player_acnt']}")
        print(f"      {view['season']} {view['kind_name']}"
              f"（kind_code={view['kind_code']}）")
        print(f"      endpoint : {view['player_endpoint']}")
        po = entry["product_output"]
        print(f"      builder  : {po['module']}::{po['function']}"
              f"（{po['source_step']}）")
    print()
    print(f"  [{'PASS' if not problems else 'FAIL'}] registry 一致性檢查")
    if problems:
        for item in problems:
            print(f"         - {item}")
    else:
        print("         必填欄位齊全、player_id 無重複、順序一致，"
              "且與 pipeline SUBJECT 交叉核對相符")
    print()
    print("  目前 registry 只有一位球員。架構已 multi-player ready，")
    print("  但不會為了看起來支援多球員而偽造任何資料。")
    print("=" * 84)


if __name__ == "__main__":
    main()

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

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    "subject_slug",
    "data",
    "product_output",
)

# product_output 區塊必須有的欄位
REQUIRED_PRODUCT_OUTPUT_FIELDS = ("module", "function", "source_step")

# data 區塊必須有的資料集。值為 repo 相對路徑。
REQUIRED_DATA_KEYS = (
    "player_log",
    "apart_raw",
    "follow_raw",
    "candidate_output",
    "team_schedule",
)

# 球員專屬資料集（不含球隊層級的賽程）。這些路徑不得被兩位球員共用。
PLAYER_SCOPED_DATA_KEYS = (
    "player_log",
    "apart_raw",
    "follow_raw",
    "candidate_output",
)

# 每個資料集「怎麼證明它屬於這位球員」。
#   internal_field ：檔案內部有欄位可核對（可驗證）
#   path_based     ：檔案內部沒有任何球員識別欄位，只能靠路徑（不可驗證）
#   team_level     ：球隊層級資料，多位球員共用
IDENTITY_KINDS = ("internal_field", "path_based", "team_level")

# SUBJECT 的欄位組成（供 pipeline 沿用；順序即 candidate_insights.SUBJECT 的順序）
SUBJECT_FIELDS = (
    "player_name",
    "player_acnt",
    "team",
    "team_code",
    "season",
    "kind_code",
    "kind_name",
)

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
        # pipeline 用來組 candidate_id / insight_id 的識別字
        "subject_slug": "ZHANGYUCHENG-2026-A",
        # 這位球員的資料檔（repo 相對路徑）。**唯一的路徑宣告來源。**
        "data": {
            "player_log":
                "data/processed/zhang_yucheng_game_logs_2026.json",
            "apart_raw":
                "data/raw/apart_score_0000006888_2026_A_01.json",
            "follow_raw":
                "data/raw/follow_score_0000006888_2026.json",
            "candidate_output":
                "data/processed/candidate_insights_zhang_yucheng_2026.json",
            # 球隊層級，同隊球員共用
            "team_schedule":
                "data/processed/fubon_schedule_2026.json",
        },
        # 每個資料集的身分依據。Step 29A 審計的事實，不是推測。
        "data_identity": {
            "apart_raw": {
                "kind": "internal_field",
                "internal_field": "HitterAcnt",
                "note": "官方分項每一列都帶 HitterAcnt，可與 registry 的 player_acnt 核對。",
            },
            "follow_raw": {
                "kind": "internal_field",
                "internal_field": "HitterAcnt",
                "note": "官方逐場原始回傳帶 HitterAcnt / HitterName，可核對。",
            },
            "player_log": {
                "kind": "path_based",
                "internal_field": None,
                "note": (
                    "Step 4 的 processed 逐場資料**沒有任何球員識別欄位**"
                    "（17 個欄位都是場次與計數）。因此它的身分目前只能由路徑決定。"
                    "本專案刻意不為了驗證而改寫既有資料檔。"
                ),
                "risk": (
                    "把別位球員的 player_log 放到這個路徑不會有任何錯誤訊息，"
                    "會靜默產出錯誤的 insight。緩解方式："
                    "(a) registry 是唯一路徑來源；"
                    "(b) 同一路徑不得被兩筆 registry 項目宣告（validate_registry 檢查）；"
                    "(c) 同目錄下的 follow_raw 有 HitterAcnt，"
                    "    可用 verify_data_identity 間接佐證這批資料屬於誰。"
                ),
            },
            "candidate_output": {
                "kind": "path_based",
                "internal_field": None,
                "note": (
                    "Step 9 --write 的產物，pipeline 不讀它。"
                    "內容含 candidate 的 subject 區塊，但身分仍以路徑為準。"
                ),
            },
            "team_schedule": {
                "kind": "team_level",
                "internal_field": None,
                "note": "富邦悍將的賽程，同隊球員共用，不屬於任何單一球員。",
            },
        },
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


# ------------------------------------------------------------------ 身分與路徑

def require_player(player_id: str) -> dict:
    """取 registry 項目，查不到直接拋錯。不猜測、不 fallback。"""
    entry = get_player(player_id)
    if entry is None:
        raise KeyError(
            f"registry 中沒有 player_id={player_id!r}；"
            f"目前可用：{player_ids()}"
        )
    return entry


def data_relpaths(player_id: str) -> dict[str, str]:
    """該球員各資料集的 repo 相對路徑。"""
    return dict(require_player(player_id)["data"])


def data_paths(player_id: str) -> dict[str, Path]:
    """該球員各資料集的絕對路徑。**pipeline 唯一該用的路徑來源。**"""
    return {key: ROOT / rel
            for key, rel in require_player(player_id)["data"].items()}


def data_path(player_id: str, key: str) -> Path:
    paths = data_paths(player_id)
    if key not in paths:
        raise KeyError(f"{player_id} 沒有資料集 {key!r}；可用：{sorted(paths)}")
    return paths[key]


def subject(player_id: str) -> dict:
    """pipeline 用的 subject dict（即 candidate_insights.SUBJECT 的內容）。"""
    entry = require_player(player_id)
    return {field: entry[field] for field in SUBJECT_FIELDS}


def subject_slug(player_id: str) -> str:
    return require_player(player_id)["subject_slug"]


def data_identity(player_id: str) -> dict:
    """各資料集的身分依據（含 path_based 的風險說明）。"""
    import copy
    return copy.deepcopy(require_player(player_id)["data_identity"])


def verify_data_identity(player_id: str) -> dict:
    """用資料檔內部欄位核對 registry 宣告的 player_acnt。

    這一支刻意與 `validate_registry()` 分開：它會讀檔，成本較高，
    因此不放在每次 health 檢查的路徑上。

    回傳 dict：
        checked   已核對的資料集 -> 檔內找到的帳號集合
        path_only 無內部識別欄位、只能靠路徑的資料集
        team      球隊層級資料集
        missing   宣告了但檔案不存在
        problems  不一致或無法核對的問題清單（空 = 通過）
    """
    import json

    entry = require_player(player_id)
    expected = entry["player_acnt"]
    identity = entry["data_identity"]
    paths = data_paths(player_id)

    result: dict = {
        "player_id": player_id,
        "expected_player_acnt": expected,
        "checked": {},
        "path_only": [],
        "team": [],
        "missing": [],
        "problems": [],
    }

    for key, path in paths.items():
        spec = identity.get(key)
        if spec is None:
            result["problems"].append(f"{key} 沒有 data_identity 宣告")
            continue
        if spec["kind"] not in IDENTITY_KINDS:
            result["problems"].append(f"{key} 的 identity kind 不在受控詞彙內")
            continue
        if not path.exists():
            result["missing"].append(key)
            continue
        if spec["kind"] == "team_level":
            result["team"].append(key)
            continue
        if spec["kind"] == "path_based":
            result["path_only"].append(key)
            continue

        field = spec["internal_field"]
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            result["problems"].append(f"{key} 不是非空的列表，無法核對身分")
            continue
        found = sorted({str(r.get(field)) for r in rows if field in r})
        result["checked"][key] = found
        if not found:
            result["problems"].append(f"{key} 找不到欄位 {field}")
        elif found != [expected]:
            result["problems"].append(
                f"{key} 的 {field} 與 registry 不符："
                f"檔內 {found} vs registry {expected!r}"
            )

    return result


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
        data = entry.get("data") or {}
        for key in REQUIRED_DATA_KEYS:
            if not data.get(key):
                problems.append(f"{label} 的 data 缺 {key}")
        for key in data:
            if key not in REQUIRED_DATA_KEYS:
                problems.append(f"{label} 的 data 出現未預期的 key：{key}")
            if str(data[key]).startswith("/") or ".." in str(data[key]):
                problems.append(f"{label} 的 data.{key} 不是 repo 相對路徑")
        ident = entry.get("data_identity") or {}
        for key in REQUIRED_DATA_KEYS:
            spec = ident.get(key)
            if not spec or spec.get("kind") not in IDENTITY_KINDS:
                problems.append(f"{label} 的 data_identity 缺或無效：{key}")
            elif spec["kind"] == "internal_field" and not spec.get("internal_field"):
                problems.append(f"{label} 的 data_identity.{key} 缺 internal_field")

        pid = entry.get("player_id")
        if pid in seen:
            problems.append(f"重複的 player_id：{pid}")
        seen.add(pid)
        if pid and pid != pid.lower():
            problems.append(f"player_id 必須全小寫：{pid}")
        if pid and (" " in pid or "/" in pid):
            problems.append(f"player_id 不得含空白或斜線：{pid}")

    # 球員專屬資料路徑不得被兩位球員共用。
    # 這是 player_log「只能靠路徑決定身分」時唯一可行的結構性防護。
    for key in PLAYER_SCOPED_DATA_KEYS:
        owners: dict[str, list[str]] = {}
        for entry in PLAYERS:
            rel = (entry.get("data") or {}).get(key)
            if rel:
                owners.setdefault(rel, []).append(entry["player_id"])
        for rel, ids in owners.items():
            if len(ids) > 1:
                problems.append(
                    f"data.{key} 路徑 {rel} 被多位球員宣告：{ids}。"
                    "球員專屬資料不得共用路徑。"
                )

    if len(PLAYER_IDS) != len(PLAYER_BY_ID):
        problems.append("PLAYER_IDS 與 PLAYER_BY_ID 筆數不一致")
    if list(PLAYER_BY_ID) != list(PLAYER_IDS):
        problems.append("PLAYER_BY_ID 的順序與 PLAYER_IDS 不一致")

    # 與 pipeline 交叉核對：pipeline 匯出的 SUBJECT / SUBJECT_SLUG / 路徑常數
    # 必須**就是**由 registry 衍生出來的值。
    # Step 29B 起 pipeline 不再自己宣告這些，這道檢查用來擋住「有人又寫死一份」。
    # 延後 import：candidate_insights 在 module 層級 import 本模組，
    # 若這裡也在 module 層級反向 import 就會造成循環。
    try:
        import candidate_insights as ci
    except Exception as exc:  # noqa: BLE001
        problems.append(f"無法載入 pipeline 進行交叉核對：{type(exc).__name__}")
        return problems

    if len(PLAYERS) == 1:
        pid = PLAYER_IDS[0]
        if ci.SUBJECT != subject(pid):
            problems.append(
                "candidate_insights.SUBJECT 不等於 registry 衍生的 subject，"
                "表示 pipeline 又出現了獨立的球員宣告"
            )
        if ci.SUBJECT_SLUG != subject_slug(pid):
            problems.append(
                "candidate_insights.SUBJECT_SLUG 不等於 registry 的 subject_slug"
            )
        paths = data_paths(pid)
        for attr, key in (("PLAYER_LOG_PATH", "player_log"),
                          ("APART_CACHE_PATH", "apart_raw"),
                          ("OUTPUT_PATH", "candidate_output")):
            if getattr(ci, attr) != paths[key]:
                problems.append(
                    f"candidate_insights.{attr} 不等於 registry 的 data.{key}"
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
        print(f"      slug     : {entry['subject_slug']}")
        print("      data     :")
        for key, rel in entry["data"].items():
            kind = entry["data_identity"][key]["kind"]
            field = entry["data_identity"][key]["internal_field"] or "-"
            print(f"          {key:<17} {rel}")
            print(f"          {'':<17} identity={kind}　field={field}")
    print()
    print(f"  [{'PASS' if not problems else 'FAIL'}] registry 一致性檢查")
    if problems:
        for item in problems:
            print(f"         - {item}")
    else:
        print("         必填欄位齊全、player_id 與資料路徑無重複、順序一致；")
        print("         pipeline 的 SUBJECT / SUBJECT_SLUG / 路徑常數"
              "確認為 registry 衍生值")

    print()
    for entry in PLAYERS:
        pid = entry["player_id"]
        result = verify_data_identity(pid)
        ok = not result["problems"] and not result["missing"]
        print(f"  [{'PASS' if ok else 'FAIL'}] {pid} 資料檔身分核對")
        for key, found in result["checked"].items():
            field = entry["data_identity"][key]["internal_field"]
            print(f"         {key}：檔內 {field}={found} "
                  f"== registry {result['expected_player_acnt']}")
        if result["path_only"]:
            print(f"         僅路徑可辨識（檔內無識別欄位）：{result['path_only']}")
        if result["team"]:
            print(f"         球隊層級共用：{result['team']}")
        if result["missing"]:
            print(f"         檔案不存在：{result['missing']}")
        for item in result["problems"]:
            print(f"         - {item}")
    print()
    print("  目前 registry 只有一位球員。架構已 multi-player ready，")
    print("  但不會為了看起來支援多球員而偽造任何資料。")
    print("=" * 84)


if __name__ == "__main__":
    main()

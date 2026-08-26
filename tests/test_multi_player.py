"""Step 28 multi-player 架構測試。

只用標準庫 `unittest`，沒有新增任何依賴。需要執行 JS 的測試用 `node`
（僅內建能力，無 npm 套件）；找不到 `node` 時會 skip。

驗證重點：
  - registry 存在、只有真實球員、無重複 id、與 pipeline subject 一致
  - `/api/players` 由 registry 驅動，順序 = registry 順序，沒有排序
  - `/api/player/<player_id>` 由 registry lookup 決定，api.py 沒有寫死 id
  - 張育成的 Step 23 response schema 完全沒被破壞
  - 前端能取得球員清單、依 player_id 呼叫端點，且不自行排序或計算
  - mutation：改 registry 順序 / 改 player_id，API 必須跟著變
  - 沒有第二份 hard-coded player mapping

執行：
    python tests/test_multi_player.py
"""

from __future__ import annotations

import ast
import copy
import io
import contextlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT / "src"))

import api  # noqa: E402
import player_registry as registry  # noqa: E402
from candidate_insights import (  # noqa: E402
    APART_CACHE_PATH,
    PLAYER_LOG_PATH,
    SUBJECT,
    sha256_of,
)
from insight_chain import SCHEDULE_PATH  # noqa: E402

SOURCE_PATHS = (PLAYER_LOG_PATH, APART_CACHE_PATH, SCHEDULE_PATH)
NODE = shutil.which("node")
BRIDGE = WEB / "tests" / "run_render.mjs"

STEP22_TOP_LEVEL = (
    "player", "next_game", "season_baseline", "current_form",
    "contextual_evidence", "factual_insights", "data_status",
    "traceability", "metadata",
)

# 目前唯一有真實資料的球員
KNOWN_PLAYER_ID = "zhang-yucheng"


def run_bridge(*bridge_args: str) -> dict:
    proc = subprocess.run(
        [NODE, str(BRIDGE), *bridge_args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
    )
    if proc.returncode != 0:
        raise AssertionError(f"bridge 執行失敗：{proc.stderr[:500]}")
    return json.loads(proc.stdout)


class MultiPlayerBase(unittest.TestCase):

    digests_before: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.digests_before = {p: sha256_of(p) for p in SOURCE_PATHS}
        api.CACHE.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        for path, before in cls.digests_before.items():
            assert sha256_of(path) == before, f"{path.name} 在測試期間被修改"


class TestRegistry(MultiPlayerBase):
    """1 / 2 / 3. registry 存在、只有真實球員、無重複 id。"""

    def test_registry_module_exists_and_is_ordered(self):
        self.assertTrue((ROOT / "src" / "player_registry.py").exists())
        self.assertIsInstance(registry.PLAYERS, tuple)
        self.assertIsInstance(registry.PLAYER_IDS, tuple)
        self.assertEqual(list(registry.PLAYER_BY_ID), list(registry.PLAYER_IDS))

    def test_registry_contains_only_the_real_supported_player(self):
        self.assertEqual(registry.player_ids(), [KNOWN_PLAYER_ID])
        entry = registry.get_player(KNOWN_PLAYER_ID)
        self.assertEqual(entry["player_acnt"], SUBJECT["player_acnt"])
        self.assertEqual(entry["season"], SUBJECT["season"])
        self.assertEqual(entry["kind_code"], SUBJECT["kind_code"])
        self.assertEqual(entry["player_name"], SUBJECT["player_name"])

    def test_no_duplicate_player_ids(self):
        ids = [p["player_id"] for p in registry.PLAYERS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), len(registry.PLAYER_BY_ID))

    def test_registry_validation_passes(self):
        self.assertEqual(registry.validate_registry(), [])

    def test_every_entry_has_required_fields(self):
        for entry in registry.PLAYERS:
            for field in registry.REQUIRED_FIELDS:
                self.assertIn(field, entry)
                self.assertNotIn(entry[field], (None, "", {}))
            for field in registry.REQUIRED_PRODUCT_OUTPUT_FIELDS:
                self.assertTrue(entry["product_output"][field])

    def test_unknown_player_lookup_returns_none_without_fallback(self):
        self.assertIsNone(registry.get_player("not-found"))
        self.assertIsNone(registry.get_player(""))
        self.assertIsNone(registry.get_player("ZHANG-YUCHENG"))

    def test_registry_declares_no_ranking_constructs(self):
        info = registry.describe()
        for banned in ("ranking", "priority", "score", "weight", "threshold",
                       "top_n", "prediction", "recommendation"):
            self.assertIn(banned, info["contains_no"])
        self.assertEqual(info["order"]["basis"], "registry_order")
        self.assertTrue(info["order"]["is_not"])

    def test_registry_module_runs_standalone(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            registry.main()
        out = buf.getvalue()
        self.assertIn("[PASS]", out)
        self.assertNotIn("[FAIL]", out)
        self.assertIn(KNOWN_PLAYER_ID, out)


class TestPlayersEndpoint(MultiPlayerBase):
    """4 / 5 / 9 / 10. /api/players 由 registry 驅動且不排序。"""

    def setUp(self) -> None:
        self.status, self.body = api.dispatch("GET", "/api/players")

    def test_players_endpoint_returns_200_json(self):
        self.assertEqual(self.status, 200)
        json.loads(api.serialize(self.body))
        self.assertIn("players", self.body)

    def test_players_matches_registry_exactly(self):
        self.assertEqual([p["player_id"] for p in self.body["players"]],
                         registry.player_ids())
        self.assertEqual(self.body["player_count"], len(registry.PLAYERS))
        self.assertEqual(self.body["player_ids"], registry.player_ids())
        for view, entry in zip(self.body["players"], registry.PLAYERS):
            for field in registry.PUBLIC_FIELDS:
                self.assertEqual(view[field], entry[field])
            self.assertEqual(view["player_endpoint"],
                             f"/api/player/{entry['player_id']}")

    def test_players_order_is_registry_order_not_sorted(self):
        self.assertEqual(self.body["order"]["basis"], "registry_order")
        self.assertTrue(self.body["order"]["is_not"])
        self.assertEqual(self.body["registry_source"]["module"],
                         "src/player_registry.py")

    def test_players_does_not_expose_ranking_or_score_fields(self):
        """欄位名不得含禁用字眼；自由文字掃描要扣除宣告性欄位。

        `order.is_not` 與 `scope_note` 本身就是「這不是 ranking」這類否定宣告，
        掃全文會自我命中（Step 19~25 已多次記錄同一類問題）。
        """
        # (a) 欄位名（含巢狀）遞迴掃描
        def scan(node, path=""):
            found = []
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("contains_no", "order", "scope_note"):
                        continue
                    for banned in ("rank", "score", "priority", "weight",
                                   "threshold", "top_n", "recommend",
                                   "predict"):
                        if banned in key.lower():
                            found.append(f"{path}.{key}")
                    found += scan(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    found += scan(value, f"{path}[{i}]")
            return found

        self.assertEqual(scan(self.body), [])

        # (b) 自由文字掃描，扣除宣告性欄位
        blob = json.dumps(self.body, ensure_ascii=False)
        declared = json.dumps({
            "contains_no": self.body["contains_no"],
            "order": self.body["order"],
            "scope_note": self.body["scope_note"],
        }, ensure_ascii=False)
        for word in ("rank", "score", "priority", "weight", "threshold",
                     "top_n", "recommend", "predict"):
            self.assertEqual(blob.count(word) - declared.count(word), 0,
                             f"/api/players 出現 {word}")

    def test_players_is_listed_in_endpoints_and_health(self):
        paths = [e["path"] for e in api.ENDPOINTS]
        self.assertIn("/api/players", paths)
        _, health = api.dispatch("GET", "/api/health")
        self.assertEqual(health["available_player_ids"], registry.player_ids())
        self.assertEqual(health["available_player_slugs"], registry.player_ids())
        self.assertEqual(health["player_count"], len(registry.PLAYERS))
        self.assertTrue(health["checks"]["registry_consistent"])
        self.assertEqual(health["checks"]["registry_problems"], [])

    def test_players_endpoint_is_deterministic(self):
        blobs = {api.serialize(api.dispatch("GET", "/api/players")[1])
                 for _ in range(5)}
        self.assertEqual(len(blobs), 1)

    def test_players_rejects_non_get(self):
        for method in ("POST", "PUT", "DELETE"):
            status, body = api.dispatch(method, "/api/players")
            self.assertEqual(status, 405)
            self.assertEqual(body["error"]["code"], "method_not_allowed")

    def test_players_path_does_not_collide_with_player_path(self):
        # /api/players 不得被當成 player_id = "players"
        self.assertEqual(api.dispatch("GET", "/api/players")[0], 200)
        status, body = api.dispatch("GET", "/api/player/players")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "player_not_found")


class TestPlayerEndpointBackwardCompatible(MultiPlayerBase):
    """6 / 7 / 8. 張育成端點與 Step 23 schema 完全相容。"""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.status, cls.payload = api.dispatch(
            "GET", f"/api/player/{KNOWN_PLAYER_ID}")

    def test_known_player_returns_200(self):
        self.assertEqual(self.status, 200)

    def test_top_level_schema_unchanged(self):
        self.assertEqual(sorted(self.payload),
                         sorted(list(STEP22_TOP_LEVEL) + ["api"]))
        for key in STEP22_TOP_LEVEL:
            self.assertTrue(self.payload[key])

    def test_step23_api_block_fields_are_preserved(self):
        block = self.payload["api"]
        for key in ("api_version", "endpoint", "player_slug", "read_only",
                    "product_output_version", "source_of_truth", "data_as_of",
                    "request_time_included", "request_time_note",
                    "external_network_used", "contains_no"):
            self.assertIn(key, block, f"Step 23 的 api.{key} 不見了")
        self.assertEqual(block["api_version"], api.API_VERSION)
        self.assertFalse(block["request_time_included"])
        self.assertFalse(block["external_network_used"])

    def test_player_slug_remains_an_alias_of_player_id(self):
        block = self.payload["api"]
        self.assertEqual(block["player_id"], KNOWN_PLAYER_ID)
        self.assertEqual(block["player_slug"], block["player_id"])
        self.assertEqual(block["player_slug_is_alias_of"], "player_id")
        self.assertEqual(block["endpoint"], f"/api/player/{KNOWN_PLAYER_ID}")
        self.assertEqual(block["players_endpoint"], "/api/players")

    def test_api_block_identity_comes_from_registry(self):
        entry = registry.get_player(KNOWN_PLAYER_ID)
        block = self.payload["api"]
        self.assertEqual(block["player_name"], entry["player_name"])
        self.assertEqual(block["season"], entry["season"])
        self.assertEqual(block["kind_code"], entry["kind_code"])
        self.assertEqual(block["registry_source"]["module"],
                         "src/player_registry.py")

    def test_product_output_subject_matches_registry(self):
        entry = registry.get_player(KNOWN_PLAYER_ID)
        player = self.payload["player"]
        for field in ("player_acnt", "season", "kind_code", "player_name"):
            self.assertEqual(player[field], entry[field])

    def test_product_output_counts_unchanged(self):
        counts = self.payload["metadata"]["counts"]
        self.assertEqual(counts["groups"], 9)
        self.assertEqual(counts["insights"], 9)
        self.assertEqual(counts["candidates"], 29)
        self.assertEqual(counts["metric_rows"], 25)
        self.assertEqual(self.payload["metadata"]["product_output_version"],
                         "step22-v1")

    def test_head_still_works(self):
        status, body = api.dispatch("HEAD", f"/api/player/{KNOWN_PLAYER_ID}")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(body), sorted(self.payload))

    def test_unknown_player_returns_404_with_registry_list(self):
        status, body = api.dispatch("GET", "/api/player/not-found")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "player_not_found")
        self.assertEqual(body["error"]["requested_player_id"], "not-found")
        self.assertEqual(body["error"]["requested_player_slug"], "not-found")
        self.assertEqual(body["error"]["available_player_ids"],
                         registry.player_ids())
        self.assertEqual(body["error"]["players_endpoint"], "/api/players")

    def test_missing_player_id_returns_400(self):
        for path in ("/api/player", "/api/player/"):
            status, body = api.dispatch("GET", path)
            self.assertEqual(status, 400, path)
            self.assertEqual(body["error"]["code"], "player_slug_required")
            self.assertEqual(body["error"]["available_player_ids"],
                             registry.player_ids())

    def test_all_error_codes_still_controlled(self):
        for method, path in (("GET", "/api/player/nobody"),
                             ("GET", "/api/player"),
                             ("GET", "/api/player/a/b"),
                             ("GET", "/nope"),
                             ("POST", "/api/players")):
            _, body = api.dispatch(method, path)
            self.assertIn(body["error"]["code"], api.ERROR_CODES)


class TestNoSecondPlayerMapping(MultiPlayerBase):
    """mutation 前提：不得存在第二份 hard-coded player mapping。"""

    def test_api_py_has_no_hardcoded_player_id(self):
        source = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
        self.assertNotIn(f'"{KNOWN_PLAYER_ID}"', source)
        self.assertNotIn(f"'{KNOWN_PLAYER_ID}'", source)
        # PLAYER_REGISTRY 只能是 registry 的別名，不能自己宣告內容
        self.assertIn("PLAYER_REGISTRY = PLAYER_BY_ID", source)

    def test_app_js_has_no_hardcoded_player_id(self):
        source = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertNotIn(KNOWN_PLAYER_ID, source)
        self.assertNotIn("PLAYER_SLUG", source)

    def test_render_js_has_no_player_mapping(self):
        source = (WEB / "render.js").read_text(encoding="utf-8")
        self.assertNotIn(KNOWN_PLAYER_ID, source)
        self.assertNotIn("PLAYER_REGISTRY", source)

    def test_index_html_has_no_hardcoded_player_id(self):
        source = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(f"/api/player/{KNOWN_PLAYER_ID}", source)

    def test_only_player_registry_declares_the_mapping(self):
        """全 repo 只有 registry 模組宣告 player_id -> 資料的對照。"""
        declaring = []
        for path in list((ROOT / "src").glob("*.py")) + list(WEB.glob("*.js")):
            text = path.read_text(encoding="utf-8")
            if re.search(r"[\"']player_id[\"']\s*:\s*[\"']", text):
                declaring.append(path.name)
        self.assertEqual(declaring, ["player_registry.py"],
                         f"有多份 player mapping：{declaring}")


@unittest.skipIf(NODE is None, "找不到 node，跳過需要執行 JS 的測試")
class TestRegistryMutation(MultiPlayerBase):
    """mutation：改 registry 順序 / 改 player_id，API 必須跟著改變。"""

    def _with_registry(self, players):
        """暫時替換 registry 內容，結束後完整還原。"""
        saved = (registry.PLAYERS, registry.PLAYER_IDS, registry.PLAYER_BY_ID,
                 api.PLAYER_REGISTRY)
        registry.PLAYERS = tuple(players)
        registry.PLAYER_IDS = tuple(p["player_id"] for p in players)
        registry.PLAYER_BY_ID = {p["player_id"]: p for p in players}
        api.PLAYER_REGISTRY = registry.PLAYER_BY_ID
        api.PLAYER_IDS = registry.PLAYER_IDS
        api.CACHE.clear()
        return saved

    def _restore(self, saved):
        (registry.PLAYERS, registry.PLAYER_IDS, registry.PLAYER_BY_ID,
         api.PLAYER_REGISTRY) = saved
        api.PLAYER_IDS = registry.PLAYER_IDS
        api.CACHE.clear()

    def test_reordering_registry_reorders_players_endpoint(self):
        real = registry.get_player(KNOWN_PLAYER_ID)
        # 加入一個純測試用的第二筆（只存在於這個測試的記憶體中，不寫入 registry）
        second = copy.deepcopy(real)
        second["player_id"] = "test-only-second"
        second["player_name"] = "測試用第二筆"

        for order in ([real, second], [second, real]):
            saved = self._with_registry(order)
            try:
                _, body = api.dispatch("GET", "/api/players")
                self.assertEqual([p["player_id"] for p in body["players"]],
                                 [p["player_id"] for p in order],
                                 "/api/players 沒有跟著 registry 順序改變")
                self.assertEqual(body["player_ids"],
                                 [p["player_id"] for p in order])
                _, health = api.dispatch("GET", "/api/health")
                self.assertEqual(health["available_player_ids"],
                                 [p["player_id"] for p in order])
            finally:
                self._restore(saved)

        # 還原後必須回到真實 registry
        _, body = api.dispatch("GET", "/api/players")
        self.assertEqual([p["player_id"] for p in body["players"]],
                         [KNOWN_PLAYER_ID])

    def test_renaming_player_id_changes_route_lookup(self):
        real = registry.get_player(KNOWN_PLAYER_ID)
        renamed = copy.deepcopy(real)
        renamed["player_id"] = "renamed-player"

        saved = self._with_registry([renamed])
        try:
            # 新 id 可用
            status, payload = api.dispatch("GET", "/api/player/renamed-player")
            self.assertEqual(status, 200)
            self.assertEqual(payload["api"]["player_id"], "renamed-player")
            self.assertEqual(payload["api"]["endpoint"],
                             "/api/player/renamed-player")
            # 舊 id 變成 404 —— 證明 route 是 registry lookup，不是寫死的
            status, body = api.dispatch("GET", f"/api/player/{KNOWN_PLAYER_ID}")
            self.assertEqual(status, 404)
            self.assertEqual(body["error"]["code"], "player_not_found")
            self.assertEqual(body["error"]["available_player_ids"],
                             ["renamed-player"])
        finally:
            self._restore(saved)

        # 還原後舊 id 必須回復
        self.assertEqual(
            api.dispatch("GET", f"/api/player/{KNOWN_PLAYER_ID}")[0], 200)

    def test_registry_entry_not_matching_pipeline_is_rejected_not_faked(self):
        """registry 宣告一位 pipeline 不支援的球員時，不得回傳別人的資料。"""
        fake = copy.deepcopy(registry.get_player(KNOWN_PLAYER_ID))
        fake["player_id"] = "someone-else"
        fake["player_name"] = "不存在的球員"
        fake["player_acnt"] = "0000000000"

        saved = self._with_registry([fake])
        try:
            status, body = api.dispatch("GET", "/api/player/someone-else")
            self.assertEqual(status, 500)
            self.assertEqual(body["error"]["code"],
                             "product_output_generation_failed")
            self.assertFalse(body["error"]["detail_disclosed"])
            blob = json.dumps(body, ensure_ascii=False)
            self.assertNotIn("Traceback", blob)
            self.assertNotIn(SUBJECT["player_name"], blob)
        finally:
            self._restore(saved)


@unittest.skipIf(NODE is None, "找不到 node，跳過需要執行 JS 的測試")
class TestFrontendPlayerSelection(MultiPlayerBase):
    """11 ~ 14. frontend 取得清單、依 player_id 呼叫、不排序、不計算。"""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        _, players = api.dispatch("GET", "/api/players")
        _, payload = api.dispatch("GET", f"/api/player/{KNOWN_PLAYER_ID}")
        cls.players = json.loads(api.serialize(players))
        cls.payload = json.loads(api.serialize(payload))

    def _bridge_players(self, players, requested=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "players.json"
            path.write_text(json.dumps(players, ensure_ascii=False),
                            encoding="utf-8")
            args = ["--players", str(path)]
            if requested:
                args.append(requested)
            return run_bridge(*args)

    def test_frontend_maps_player_list_from_api(self):
        result = self._bridge_players(self.players)
        self.assertEqual([i["playerId"] for i in result["items"]],
                         [p["player_id"] for p in self.players["players"]])
        item = result["items"][0]
        entry = self.players["players"][0]
        self.assertEqual(item["playerName"], entry["player_name"])
        self.assertEqual(item["team"], entry["team"])
        self.assertEqual(item["season"], entry["season"])
        self.assertIn(entry["player_name"], item["label"])

    def test_frontend_resolves_player_id_from_list(self):
        result = self._bridge_players(self.players)
        self.assertEqual(result["resolvedPlayerId"], KNOWN_PLAYER_ID)
        self.assertEqual(result["resolvedWithoutRequest"], KNOWN_PLAYER_ID)
        # 不存在的請求 id 不會被採用，也不會 fallback 到寫死的 id
        self.assertEqual(result["resolvedWithUnknownRequest"], KNOWN_PLAYER_ID)

    def test_frontend_honours_requested_player_id(self):
        result = self._bridge_players(self.players, KNOWN_PLAYER_ID)
        self.assertEqual(result["resolvedPlayerId"], KNOWN_PLAYER_ID)

    def test_frontend_builds_endpoint_url_from_player_id(self):
        result = self._bridge_players(self.players)
        self.assertEqual(result["playersEndpoint"],
                         "http://127.0.0.1:8000/api/players")
        self.assertEqual(
            result["playerEndpoints"],
            [f"http://127.0.0.1:8000/api/player/{p['player_id']}"
             for p in self.players["players"]])

    def test_frontend_does_not_sort_player_list(self):
        """把清單反轉，前端輸出的順序必須跟著反轉。"""
        real = self.players["players"][0]
        second = dict(real, player_id="test-only-second",
                      player_name="測試用第二筆")
        for order in ([real, second], [second, real]):
            mutated = dict(self.players, players=order)
            result = self._bridge_players(mutated)
            self.assertEqual([i["playerId"] for i in result["items"]],
                             [p["player_id"] for p in order])
            # 第一筆就是預設選取的球員
            self.assertEqual(result["resolvedPlayerId"], order[0]["player_id"])

    def test_frontend_returns_null_for_empty_player_list(self):
        result = self._bridge_players({"players": []})
        self.assertEqual(result["items"], [])
        self.assertIsNone(result["resolvedPlayerId"])
        self.assertIsNone(result["resolvedWithoutRequest"])

    def test_bootstrap_requests_players_then_selected_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            plist = Path(tmp) / "players.json"
            payload = Path(tmp) / "payload.json"
            plist.write_text(json.dumps(self.players, ensure_ascii=False),
                             encoding="utf-8")
            payload.write_text(json.dumps(self.payload, ensure_ascii=False),
                               encoding="utf-8")
            result = run_bridge("--bootstrap", str(plist), str(payload))
        self.assertEqual(result["requestedUrls"], [
            "http://127.0.0.1:8000/api/players",
            f"http://127.0.0.1:8000/api/player/{KNOWN_PLAYER_ID}",
        ])
        self.assertEqual(result["activePlayerId"], KNOWN_PLAYER_ID)
        self.assertEqual(result["listStatus"], 200)
        self.assertEqual(result["detailStatus"], 200)
        self.assertEqual(result["viewModelPlayerName"],
                         self.payload["player"]["player_name"])

    def test_frontend_player_helpers_do_no_computation(self):
        """player 選單相關程式不得含排序或算術。"""
        source = (WEB / "app.js").read_text(encoding="utf-8")
        for banned in (".sort(", ".reverse(", "localeCompare"):
            self.assertNotIn(banned, source)
        # 選單只讀 API 欄位，沒有任何 insight 數值計算
        for banned in ("current_value -", "- baseline", "difference =",
                       "Math.max", "Math.min"):
            self.assertNotIn(banned, source, f"app.js 出現 {banned}")

    def test_render_js_is_untouched_by_player_selection(self):
        """render.js 必須逐位元未被修改（用 git 比對，最直接的證明）。"""
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "web/render.js"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[:300])
        self.assertEqual(proc.stdout.strip(), "",
                         "web/render.js 被修改了（Step 28 不得改動它）")
        # 另外確認 UI 層識別字沒有滲進 render.js
        source = (WEB / "render.js").read_text(encoding="utf-8")
        for banned in ("playerListItems", "resolvePlayerId", "playersEndpoint",
                       "playerEndpointUrl", "addEventListener",
                       "createElement", "/api/players"):
            self.assertNotIn(banned, source,
                             f"render.js 被加入了 UI 層邏輯：{banned}")

    def test_frontend_only_calls_registry_driven_endpoints(self):
        """只檢查真正被當成路徑使用的字串常值，不掃使用者訊息。"""
        source = (WEB / "app.js").read_text(encoding="utf-8")
        literals = re.findall(r"[`'\"]([^`'\"\n]*)[`'\"]", source)
        # 只看「含 /api/ 且真的被當成路徑」的常值：
        #   - 以 /api/ 開頭：路徑常數
        #   - 以 ${ 開頭：由 apiBase 組出的 URL 樣板
        # 使用者訊息雖然也提到 /api/players，但不是以這兩種形式開頭，故排除。
        api_paths = [
            lit for lit in literals
            if "/api/" in lit and (lit.startswith("/api/") or lit.startswith("${"))
        ]
        self.assertTrue(api_paths, "找不到任何 API 路徑常值")
        for literal in api_paths:
            self.assertTrue(
                literal == "/api/players"
                or "${playerId}" in literal
                or "${apiBase}" in literal
                or literal == "${apiBase}${PLAYERS_PATH}",
                f"app.js 出現非 registry 驅動的路徑：{literal}")
        # 不得出現任何寫死的完整 player 路徑
        self.assertNotIn("/api/player/zhang", source)


class TestDataIntegrity(MultiPlayerBase):
    """10. data/ 不得被修改；沒有新增 dependency。"""

    def test_source_data_unchanged(self):
        for path, before in self.digests_before.items():
            self.assertEqual(sha256_of(path), before, path.name)

    def test_data_directory_listing_unchanged(self):
        before = sorted(p.name for p in (ROOT / "data").rglob("*")
                        if p.is_file())
        api.CACHE.clear()
        api.dispatch("GET", "/api/players")
        api.dispatch("GET", f"/api/player/{KNOWN_PLAYER_ID}")
        after = sorted(p.name for p in (ROOT / "data").rglob("*")
                       if p.is_file())
        self.assertEqual(before, after)

    def test_requirements_still_empty(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        self.assertEqual(lines, [])

    def test_no_package_manifest_added(self):
        for name in ("package.json", "package-lock.json", "node_modules",
                     "pyproject.toml"):
            self.assertFalse((ROOT / name).exists())
            self.assertFalse((WEB / name).exists())

    def test_registry_module_imports_only_stdlib(self):
        tree = ast.parse(
            (ROOT / "src" / "player_registry.py").read_text(encoding="utf-8"))
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top.add(node.module.split(".")[0])
        # Step 29B：registry 現在也宣告資料路徑，因此需要 pathlib（仍是標準庫）。
        self.assertTrue(top <= {"__future__", "pathlib"},
                        f"未預期的 import：{top}")

    def test_registry_does_not_import_pipeline_at_module_level(self):
        """避免循環 import：pipeline 在 module 層級 import registry，
        registry 對 pipeline 的交叉核對必須是延後 import。"""
        tree = ast.parse(
            (ROOT / "src" / "player_registry.py").read_text(encoding="utf-8"))
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top.add(node.module.split(".")[0])
        self.assertNotIn("candidate_insights", top)


class TestRegistryIsSingleIdentitySource(MultiPlayerBase):
    """Step 29B：registry 是球員身分與資料路徑的唯一宣告來源。"""

    PIPELINE_FILES = ("candidate_insights.py", "context_splits.py",
                      "build_processed_data.py")

    def setUp(self) -> None:
        self.player_id = registry.default_player_id()
        self.subject = registry.subject(self.player_id)
        self.paths = registry.data_paths(self.player_id)

    # ---- 2. candidate_insights 的相容常數等於 registry 衍生值 ----

    def test_candidate_insights_constants_are_registry_derived(self):
        import candidate_insights as ci
        self.assertEqual(ci.SUBJECT, self.subject)
        self.assertEqual(ci.SUBJECT_SLUG,
                         registry.subject_slug(self.player_id))
        self.assertEqual(ci.PLAYER_LOG_PATH, self.paths["player_log"])
        self.assertEqual(ci.APART_CACHE_PATH, self.paths["apart_raw"])
        self.assertEqual(ci.OUTPUT_PATH, self.paths["candidate_output"])

    def test_candidate_insights_subject_field_order_preserved(self):
        import candidate_insights as ci
        self.assertEqual(list(ci.SUBJECT), list(registry.SUBJECT_FIELDS))

    # ---- 3. context_splits.PLAYER_ACNT 等於 registry ----

    def test_context_splits_constants_are_registry_derived(self):
        import context_splits as cs
        self.assertEqual(cs.PLAYER_ACNT, self.subject["player_acnt"])
        self.assertEqual(cs.YEAR, str(self.subject["season"]))
        self.assertEqual(cs.KIND_CODE, self.subject["kind_code"])
        self.assertEqual(cs.PLAYER_LOG_PATH, self.paths["player_log"])
        self.assertEqual(cs.RAW_LOG_PATH, self.paths["follow_raw"])
        self.assertEqual(cs.CACHE_PATH, self.paths["apart_raw"])
        self.assertIn(self.subject["player_name"], cs.PLAYER_LABEL)

    # ---- 4. build_processed_data.PLAYER_ACNT 等於 registry ----

    def test_build_processed_data_constants_are_registry_derived(self):
        import build_processed_data as bpd
        self.assertEqual(bpd.PLAYER_ACNT, self.subject["player_acnt"])
        self.assertEqual(bpd.YEAR, self.subject["season"])
        self.assertEqual(bpd.KIND_CODE, self.subject["kind_code"])
        self.assertEqual(bpd.FUBON_TEAM_CODE, self.subject["team_code"])
        self.assertEqual(bpd.PLAYER_OUT, self.paths["player_log"])
        self.assertEqual(bpd.SCHEDULE_OUT, self.paths["team_schedule"])

    # ---- 1. AST：pipeline 不再有獨立的球員字面值宣告 ----

    def test_pipeline_modules_declare_no_player_literals(self):
        """AST 檢查（不只字串 grep）：三支 pipeline 檔的 module 層級賦值
        不得再出現球員帳號、姓名或資料檔名的字面值。"""
        literals = (
            self.subject["player_acnt"],
            self.subject["player_name"],
            registry.subject_slug(self.player_id),
            "zhang_yucheng",
            "apart_score_",
            "follow_score_",
            "candidate_insights_zhang",
        )
        offenders = []
        for name in self.PIPELINE_FILES:
            tree = ast.parse((ROOT / "src" / name).read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        for bad in literals:
                            if bad in sub.value:
                                offenders.append(
                                    f"{name}:{node.lineno} 出現 {bad!r}")
        self.assertEqual(offenders, [],
                         f"pipeline 仍有獨立的球員宣告：{offenders[:5]}")

    def test_pipeline_modules_import_registry(self):
        """三支檔案都必須在 module 層級 import registry。"""
        for name in self.PIPELINE_FILES:
            tree = ast.parse((ROOT / "src" / name).read_text(encoding="utf-8"))
            imported = set()
            for node in tree.body:
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertIn("player_registry", imported,
                          f"{name} 沒有 import player_registry")

    def test_registry_validation_catches_reintroduced_declaration(self):
        """反證：若有人又在 pipeline 寫死一份 SUBJECT，validate_registry 必須抓到。"""
        import candidate_insights as ci
        original = ci.SUBJECT
        ci.SUBJECT = dict(original, player_acnt="9999999999")
        try:
            problems = registry.validate_registry()
            self.assertTrue(
                any("SUBJECT" in p for p in problems),
                f"沒有抓到重新寫死的 SUBJECT：{problems}")
        finally:
            ci.SUBJECT = original
        self.assertEqual(registry.validate_registry(), [])

    def test_registry_validation_catches_reintroduced_path(self):
        import candidate_insights as ci
        original = ci.PLAYER_LOG_PATH
        ci.PLAYER_LOG_PATH = registry.ROOT / "data" / "processed" / "other.json"
        try:
            problems = registry.validate_registry()
            self.assertTrue(
                any("PLAYER_LOG_PATH" in p for p in problems),
                f"沒有抓到被改掉的路徑常數：{problems}")
        finally:
            ci.PLAYER_LOG_PATH = original
        self.assertEqual(registry.validate_registry(), [])

    # ---- 身分安全 ----

    def test_data_identity_is_verified_against_file_contents(self):
        """apart / follow raw 用檔內 HitterAcnt 核對 registry 的 player_acnt。"""
        result = registry.verify_data_identity(self.player_id)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["expected_player_acnt"],
                         self.subject["player_acnt"])
        self.assertEqual(sorted(result["checked"]), ["apart_raw", "follow_raw"])
        for found in result["checked"].values():
            self.assertEqual(found, [self.subject["player_acnt"]])

    def test_processed_log_identity_is_documented_as_path_based(self):
        """審計已確認 processed 逐場資料沒有內部識別欄位——如實記錄，不發明欄位。"""
        identity = registry.data_identity(self.player_id)
        self.assertEqual(identity["player_log"]["kind"], "path_based")
        self.assertIsNone(identity["player_log"]["internal_field"])
        self.assertTrue(identity["player_log"]["risk"])
        result = registry.verify_data_identity(self.player_id)
        self.assertIn("player_log", result["path_only"])
        # 沒有為了驗證而在資料檔裡新增欄位
        rows = json.loads(
            self.paths["player_log"].read_text(encoding="utf-8"))
        for key in rows[0]:
            self.assertNotIn("acnt", key.lower())
            self.assertNotIn("player", key.lower())

    def test_team_schedule_is_marked_team_level(self):
        identity = registry.data_identity(self.player_id)
        self.assertEqual(identity["team_schedule"]["kind"], "team_level")
        result = registry.verify_data_identity(self.player_id)
        self.assertIn("team_schedule", result["team"])

    def test_player_scoped_paths_cannot_be_shared(self):
        """反證：兩位球員共用球員專屬路徑時，validate_registry 必須擋下。"""
        entry = registry.get_player(self.player_id)
        clone = copy.deepcopy(entry)
        clone["player_id"] = "test-only-clone"
        saved = (registry.PLAYERS, registry.PLAYER_IDS, registry.PLAYER_BY_ID)
        registry.PLAYERS = (entry, clone)
        registry.PLAYER_IDS = (entry["player_id"], clone["player_id"])
        registry.PLAYER_BY_ID = {p["player_id"]: p for p in registry.PLAYERS}
        try:
            problems = registry.validate_registry()
            self.assertTrue(
                any("不得共用路徑" in p for p in problems),
                f"沒有擋下共用的球員專屬路徑：{problems}")
        finally:
            (registry.PLAYERS, registry.PLAYER_IDS,
             registry.PLAYER_BY_ID) = saved
        self.assertEqual(registry.validate_registry(), [])

    def test_unknown_player_path_lookup_raises(self):
        with self.assertRaises(KeyError):
            registry.data_paths("no-such-player")
        with self.assertRaises(KeyError):
            registry.subject("no-such-player")
        with self.assertRaises(KeyError):
            registry.data_path(self.player_id, "no-such-dataset")

    # ---- 6. 沒有引入第二位球員 ----

    def test_still_exactly_one_player(self):
        self.assertEqual(registry.player_ids(), [KNOWN_PLAYER_ID])
        _, body = api.dispatch("GET", "/api/players")
        self.assertEqual(body["player_count"], 1)

    # ---- 5. 既有行為未變 ----

    def test_product_output_unchanged_after_identity_refactor(self):
        _, payload = api.dispatch("GET", f"/api/player/{KNOWN_PLAYER_ID}")
        counts = payload["metadata"]["counts"]
        self.assertEqual(
            (counts["groups"], counts["candidates"], counts["insights"],
             counts["metric_rows"]), (9, 29, 9, 25))
        for field in ("player_acnt", "season", "kind_code", "player_name",
                      "team", "team_code", "kind_name"):
            self.assertEqual(payload["player"][field], self.subject[field])
        # candidate / insight id 仍使用 registry 的 subject_slug
        slug = registry.subject_slug(self.player_id)
        for insight_id in payload["factual_insights"]:
            self.assertIn(slug, insight_id)

    def test_no_external_http_in_request_path(self):
        import socket as socket_module
        calls = []
        original = socket_module.socket.connect

        def spy(self, *args, **kwargs):
            calls.append(args)
            return original(self, *args, **kwargs)

        socket_module.socket.connect = spy
        try:
            api.CACHE.clear()
            api.dispatch("GET", "/api/players")
            api.dispatch("GET", "/api/health")
            api.dispatch("GET", f"/api/player/{KNOWN_PLAYER_ID}")
        finally:
            socket_module.socket.connect = original
        self.assertEqual(calls, [])


def main() -> int:
    if NODE is None:
        print("警告：找不到 node，需要執行 JS 的測試會被跳過。", file=sys.stderr)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    print(f"\n共 {total} 項測試，通過 {total - failed - skipped} 項，"
          f"失敗 {failed} 項，跳過 {skipped} 項。")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

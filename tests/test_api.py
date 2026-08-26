"""Step 23 後端 API 測試。

只用標準庫 `unittest`，沒有新增任何依賴。

執行：
    python tests/test_api.py

測試策略：結構性斷言優先，不靠字眼掃描。
路由邏輯透過 `api.dispatch()` 直接測試，不經過真實 socket——因為本專案的
socket guard（`candidate_insights.install_network_guard`）刻意封鎖所有
`connect` / `create_connection`，那正是「不會有外部請求」的保證。
另有一個測試實際 bind 一個 ThreadingHTTPServer（bind / listen 不受 guard 影響），
確認 HTTP 層能正常掛起來。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import api  # noqa: E402
from candidate_insights import (  # noqa: E402
    APART_CACHE_PATH,
    PLAYER_LOG_PATH,
    load_inputs,
    network_guard_active,
    sha256_of,
)
from insight_chain import SCHEDULE_PATH  # noqa: E402
from insight_assembly import build_all as build_step21  # noqa: E402

STEP22_TOP_LEVEL = (
    "player", "next_game", "season_baseline", "current_form",
    "contextual_evidence", "factual_insights", "data_status",
    "traceability", "metadata",
)

SOURCE_PATHS = (PLAYER_LOG_PATH, APART_CACHE_PATH, SCHEDULE_PATH)

FORBIDDEN_KEY_FRAGMENTS = (
    "score", "weight", "threshold", "rank", "priority", "importance",
    "confidence", "top_n", "recommend", "predict",
)

# 例外說明：
#   percentile_rank / rank_desc            -> Step 6 的分布描述子
#   home_score / visiting_score / *_in_file -> CPBL 官方比分欄位，值為 null + 原因
ALLOWED_KEYS = frozenset({
    "percentile_rank", "rank_desc",
    "home_score", "visiting_score", "score_is_null_reason",
    "source_score_values_for_traceability",
    "home_score_in_file", "visiting_score_in_file",
})

# 宣告性欄位（內容本身就是「不含什麼」的清單），不列入欄位名掃描
DECLARATIVE_KEYS = frozenset({
    "contains_no", "rule_not_inputs", "contains_no_judgement", "must_not_do",
    "forbidden", "new_in_step_22",
})


def scan_forbidden_keys(obj, path="") -> list[str]:
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in DECLARATIVE_KEYS or key in ALLOWED_KEYS:
                continue
            low = key.lower()
            for frag in FORBIDDEN_KEY_FRAGMENTS:
                if frag in low:
                    found.append(f"{path}.{key}")
            found += scan_forbidden_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found += scan_forbidden_keys(value, f"{path}[{i}]")
    return found


class ApiTestBase(unittest.TestCase):
    """整條 pipeline 與 Step 21 基準各建一次，所有測試共用。"""

    hashes_before: dict
    status: int
    payload: dict
    raw: bytes
    step21_insights: list

    @classmethod
    def setUpClass(cls) -> None:
        cls.hashes_before = {p: sha256_of(p) for p in SOURCE_PATHS}
        cls.status, cls.payload = api.dispatch("GET", "/api/player/zhang-yucheng")
        cls.raw = api.serialize(cls.payload)
        logs, apart_rows = load_inputs()
        cls.step21_insights = build_step21(logs, apart_rows)[5]

    @classmethod
    def tearDownClass(cls) -> None:
        for path, before in cls.hashes_before.items():
            assert sha256_of(path) == before, f"{path.name} 在測試期間被修改"


class TestHealthEndpoint(ApiTestBase):

    def test_health_returns_200(self):
        status, body = api.dispatch("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["api_version"], api.API_VERSION)

    def test_health_is_machine_readable(self):
        _, body = api.dispatch("GET", "/api/health")
        json.loads(api.serialize(body))  # 必須可序列化與反序列化
        self.assertIn("checks", body)
        self.assertIn("endpoints", body)
        self.assertEqual(body["available_player_slugs"], ["zhang-yucheng"])

    def test_health_does_not_depend_on_external_network(self):
        _, body = api.dispatch("GET", "/api/health")
        self.assertFalse(body["external_network_used"])
        self.assertTrue(body["checks"]["network_guard_active"])
        for name, present in body["checks"]["local_source_files_present"].items():
            self.assertTrue(present, f"{name} 不存在")

    def test_health_ignores_query_string(self):
        a = api.serialize(api.dispatch("GET", "/api/health")[1])
        b = api.serialize(api.dispatch("GET", "/api/health?x=1&y=2")[1])
        self.assertEqual(a, b)


class TestPlayerEndpoint(ApiTestBase):

    def test_player_returns_200(self):
        self.assertEqual(self.status, 200)

    def test_response_contains_all_nine_step22_sections(self):
        for key in STEP22_TOP_LEVEL:
            self.assertIn(key, self.payload, f"缺少 Step 22 區塊 {key}")
            self.assertTrue(self.payload[key], f"Step 22 區塊 {key} 為空")

    def test_api_block_is_additive_not_a_second_schema(self):
        # Step 22 的 9 個鍵 + 一個命名空間化的 api 區塊，沒有其他頂層鍵
        self.assertEqual(sorted(self.payload),
                         sorted(list(STEP22_TOP_LEVEL) + ["api"]))
        self.assertEqual(self.payload["api"]["product_output_version"],
                         self.payload["metadata"]["product_output_version"])
        self.assertTrue(self.payload["api"]["read_only"])

    def test_all_nine_groups_are_represented(self):
        self.assertEqual(len(self.payload["factual_insights"]), 9)
        self.assertEqual(self.payload["metadata"]["counts"]["groups"], 9)
        scopes = sorted(
            s for sid in ("current_form", "contextual_evidence")
            for s in self.payload[sid]["scopes"]
        )
        self.assertEqual(len(scopes), 9)
        self.assertEqual(scopes, sorted({
            "RECENT_10", "RECENT_15", "VS_CLOSER", "VS_DOMESTIC", "VS_FOREIGN",
            "VS_LEFT", "VS_RELIEF", "VS_RIGHT", "VS_STARTER",
        }))
        self.assertEqual(self.payload["current_form"]["group_count"], 2)
        self.assertEqual(self.payload["contextual_evidence"]["group_count"], 7)

    def test_all_29_candidates_remain_traceable(self):
        ids = [
            cid
            for sid in ("current_form", "contextual_evidence")
            for ref in self.payload[sid]["insight_refs"]
            for cid in ref["candidate_ids"]
        ]
        self.assertEqual(len(ids), 29)
        self.assertEqual(len(set(ids)), 29, "有 candidate 重複出現")
        self.assertEqual(self.payload["metadata"]["counts"]["candidates"], 29)
        # 每個 candidate 都必須能回到它的 insight，且 insight 存在
        for sid in ("current_form", "contextual_evidence"):
            for ref in self.payload[sid]["insight_refs"]:
                insight = self.payload["factual_insights"][ref["insight_id"]]
                self.assertEqual(insight["identity"]["candidate_ids"],
                                 ref["candidate_ids"])
                self.assertEqual(ref["pointer"],
                                 f"factual_insights.{ref['insight_id']}")

    def test_factual_insight_values_match_step21(self):
        by_id = {i["identity"]["insight_id"]: i for i in self.step21_insights}
        self.assertEqual(sorted(by_id), sorted(self.payload["factual_insights"]))
        compared = 0
        for iid, expected in by_id.items():
            got = self.payload["factual_insights"][iid]
            self.assertEqual(got, expected, f"{iid} 與 Step 21 不符")
            for e, x in zip(got["supporting_evidence"]["primary_metrics"],
                            expected["supporting_evidence"]["primary_metrics"]):
                for field in ("current_value", "baseline_value", "difference",
                              "direction"):
                    self.assertEqual(e[field], x[field])
                compared += 1
        self.assertEqual(compared, 25, "應有 25 個 metric 列")

    def test_step19_decision_relevance_is_preserved(self):
        expected = {
            "RECENT_10": ("recent_games", "none", "next_game_context"),
            "RECENT_15": ("recent_games", "none", "next_game_context"),
            "VS_LEFT": ("season_cumulative", "pitcher_hand",
                        "next_starting_pitcher_hand"),
            "VS_RIGHT": ("season_cumulative", "pitcher_hand",
                         "next_starting_pitcher_hand"),
            "VS_STARTER": ("season_cumulative", "pitcher_role",
                           "in_game_pitcher_role_at_plate_appearance"),
            "VS_RELIEF": ("season_cumulative", "pitcher_role",
                          "in_game_pitcher_role_at_plate_appearance"),
            "VS_CLOSER": ("season_cumulative", "pitcher_role",
                          "in_game_pitcher_role_at_plate_appearance"),
            "VS_DOMESTIC": ("season_cumulative", "pitcher_background",
                            "next_starting_pitcher_registration_status"),
            "VS_FOREIGN": ("season_cumulative", "pitcher_background",
                           "next_starting_pitcher_registration_status"),
        }
        for insight in self.payload["factual_insights"].values():
            scope = insight["identity"]["scope"]
            ctx = insight["context"]
            self.assertEqual(
                (ctx["temporal_relevance"], ctx["contextual_relevance"],
                 ctx["application_dependency"]["additional_data"]),
                expected[scope], f"{scope} decision relevance 不符 Step 19")
            self.assertIn("evidence_depends_on_next_game",
                          ctx["next_game_dependency"])
            self.assertTrue(ctx["possible_decision_area"])

    def test_evidence_and_application_status_remain_separate(self):
        ds = self.payload["data_status"]
        ev = ds["evidence_data_status_by_scope"]
        app = ds["application_data_status_by_scope"]
        self.assertEqual(sorted(ev), sorted(app))
        self.assertEqual(sorted(set(ev.values())), ["available"])
        self.assertEqual(
            sorted(set(app.values())),
            ["available", "not_investigated", "partially_available",
             "unavailable"])
        self.assertTrue(ds["separation"]["fields_are_independent"])
        # 交叉表必須顯示 evidence=available 之下有 4 種 application 狀態
        cross = ds["separation"]["cross_tabulation"]
        self.assertEqual(sorted(cross), ["available"])
        self.assertEqual(len(cross["available"]), 4)
        # 每個 insight 內部也必須同時保留兩個欄位
        for insight in self.payload["factual_insights"].values():
            da = insight["limitations"]["data_availability"]
            self.assertIn("evidence_data_status", da)
            self.assertIn("application_data_status", da)

    def test_missing_information_remains_explicit(self):
        ds = self.payload["data_status"]
        registry = {e["item"]: e for e in ds["missing_information_registry"]}
        self.assertEqual(sorted(registry), [
            "in_game_pitcher_role_at_plate_appearance",
            "next_game_context",
            "next_starting_pitcher_hand",
            "next_starting_pitcher_registration_status",
        ])
        gaps = [e for e in registry.values() if e["is_gap"]]
        self.assertEqual(len(gaps), 3)
        self.assertEqual(ds["missing_information_gap_count"], 3)
        for entry in registry.values():
            self.assertIn(entry["status"],
                          ("available", "partially_available", "unavailable",
                           "not_investigated"))
            self.assertTrue(entry["factual_basis"])
            self.assertTrue(entry["availability_source_step"])
            self.assertTrue(entry["affected_scopes"])
        # metric 層缺口
        self.assertEqual(ds["metric_level_gap_count"], 2)
        for gap in ds["metric_level_gaps"]:
            self.assertIsNone(gap["value"])
            self.assertTrue(gap["null_reason"])
            self.assertEqual(gap["interpretation_status"],
                             "blocked_by_missing_data")

    def test_null_values_remain_null(self):
        # (a) RECENT 窗口的 OBP
        for scope in ("RECENT_10", "RECENT_15"):
            insight = next(i for i in self.payload["factual_insights"].values()
                           if i["identity"]["scope"] == scope)
            obp = next(s for s in insight["phenomenon"]["statements"]
                       if s["metric"] == "on_base_percentage")
            self.assertIsNone(obp["current_value"])
            self.assertEqual(obp["statement_kind"], "explicit_null")
            self.assertEqual(
                insight["limitations"]["unavailable_metrics"]["metrics"],
                ["on_base_percentage"])
        # (b) 官方分項沒有時間維度
        for scope in ("VS_LEFT", "VS_CLOSER", "VS_FOREIGN"):
            insight = next(i for i in self.payload["factual_insights"].values()
                           if i["identity"]["scope"] == scope)
            for e in insight["supporting_evidence"]["primary_metrics"]:
                self.assertIsNone(e["rolling_percentile"])
                self.assertTrue(e["rolling_percentile_missing_reason"])
                self.assertIsNone(e["sample_size"]["games"])
                self.assertTrue(e["sample_size"]["games_missing_reason"])
            for entry in insight["traceability"]["by_metric"].values():
                self.assertIsNone(entry["game_snos"])
                self.assertTrue(entry["game_snos_missing_reason"])
        # (c) next_game 的 null 一律附原因
        ng = self.payload["next_game"]
        self.assertIsNone(ng["result_not_available"]["home_score"])
        self.assertIsNone(ng["result_not_available"]["visiting_score"])
        self.assertTrue(ng["result_not_available"]["null_reason"])
        self.assertIsNone(ng["opponent_starting_pitcher"]["pitcher_name"])
        self.assertTrue(
            ng["opponent_starting_pitcher"]["pitcher_name_null_reason"])
        self.assertIsNone(ng["opponent_starting_pitcher_hand"]["hand"])
        self.assertTrue(ng["opponent_starting_pitcher_hand"]["null_reason"])
        # (d) JSON 往返後 null 仍是 null，不會變成 0 或空字串
        roundtrip = json.loads(self.raw)
        self.assertIsNone(
            roundtrip["next_game"]["opponent_starting_pitcher_hand"]["hand"])

    def test_controlled_vocabulary_values_are_within_declared_sets(self):
        vocab = self.payload["metadata"]["controlled_vocabularies"]
        for insight in self.payload["factual_insights"].values():
            status = insight["interpretation_status"]["status"]
            self.assertIn(status, vocab["interpretation_status"]["values"])
            for s in insight["phenomenon"]["statements"]:
                self.assertIn(s["statement_kind"],
                              vocab["statement_kind"]["values"])
                if s["direction"] is not None:
                    self.assertIn(s["direction"], vocab["direction"]["values"])
            for e in insight["supporting_evidence"]["primary_metrics"]:
                for kind in e["evidence_kinds"]:
                    self.assertIn(kind, vocab["evidence_kind"]["values"])
        for slot in self.payload["metadata"]["display_contract"]:
            self.assertIn(slot["slot"], vocab["display_slot"]["values"])
        for value in self.payload["data_status"][
                "next_game_field_status"].values():
            self.assertIn(value, vocab["data_status"]["values"])

    def test_factual_only_interpretation_boundaries_are_preserved(self):
        by_scope = {i["identity"]["scope"]: i
                    for i in self.payload["factual_insights"].values()}
        for scope in ("RECENT_10", "RECENT_15"):
            self.assertEqual(
                by_scope[scope]["interpretation_status"]["status"],
                "factual_with_context")
        for scope in ("VS_LEFT", "VS_RIGHT", "VS_STARTER", "VS_RELIEF",
                      "VS_CLOSER", "VS_DOMESTIC", "VS_FOREIGN"):
            self.assertEqual(
                by_scope[scope]["interpretation_status"]["status"],
                "factual_only")
            self.assertTrue(by_scope[scope]["limitations"]
                            ["temporal_limitation"])
            self.assertTrue(by_scope[scope]["limitations"]
                            ["not_a_next_game_projection"])

    def test_traceability_is_complete(self):
        tr = self.payload["traceability"]
        self.assertEqual(tr["metric_index_count"], 27)
        self.assertEqual(tr["traceable_metric_count"], 25)
        for entry in tr["metric_index"]:
            if not entry["traceable"]:
                self.assertTrue(entry["not_traceable_reason"])
                continue
            target = self.payload
            for part in entry["pointer"].split("."):
                self.assertIn(part, target, f"{entry['pointer']} 無法解析")
                target = target[part]
            for field in ("source_step", "source_file", "source_field",
                          "derivation"):
                self.assertTrue(target[field], f"{entry['pointer']} 缺 {field}")
        for record in tr["source_files"]:
            self.assertTrue(record["exists"])
            self.assertEqual(len(record["sha256"]), 64)
        self.assertEqual(len(tr["step_registry"]), 14)


class TestErrorHandling(ApiTestBase):

    def test_unknown_player_returns_404(self):
        status, body = api.dispatch("GET", "/api/player/nobody")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "player_not_found")
        self.assertEqual(body["error"]["http_status"], 404)
        self.assertEqual(body["error"]["requested_player_slug"], "nobody")
        self.assertEqual(body["error"]["available_player_slugs"],
                         ["zhang-yucheng"])

    def test_missing_slug_returns_400(self):
        for path in ("/api/player", "/api/player/"):
            status, body = api.dispatch("GET", path)
            self.assertEqual(status, 400, path)
            self.assertEqual(body["error"]["code"], "player_slug_required")

    def test_too_many_path_segments_returns_400(self):
        status, body = api.dispatch("GET", "/api/player/zhang-yucheng/extra")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "malformed_path")

    def test_unknown_path_returns_404(self):
        for path in ("/", "/api", "/api/unknown", "/wat"):
            status, body = api.dispatch("GET", path)
            self.assertEqual(status, 404, path)
            self.assertEqual(body["error"]["code"], "not_found")

    def test_non_get_method_returns_405(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            status, body = api.dispatch(method, "/api/player/zhang-yucheng")
            self.assertEqual(status, 405, method)
            self.assertEqual(body["error"]["code"], "method_not_allowed")

    def test_internal_failure_returns_machine_readable_500(self):
        original = api.CACHE.get

        # Step 28：CACHE.get 改成以 player_id 為鍵，簽章要跟著調整，
        # 否則會提前拋 TypeError，就測不到「錯誤細節不外洩」這件事。
        def boom(player_id):
            raise RuntimeError(
                "boom at C:/Users/secret/path/file.py line 42")

        api.CACHE.get = boom
        try:
            status, body = api.dispatch("GET", "/api/player/zhang-yucheng")
        finally:
            api.CACHE.get = original
        self.assertEqual(status, 500)
        self.assertEqual(body["error"]["code"],
                         "product_output_generation_failed")
        self.assertFalse(body["error"]["detail_disclosed"])
        blob = json.dumps(body, ensure_ascii=False)
        self.assertNotIn("Traceback", blob)
        self.assertNotIn("boom", blob)
        self.assertNotIn("C:/Users", blob)
        self.assertNotIn(".py", blob)

    def test_all_error_codes_are_in_controlled_vocabulary(self):
        paths = [("GET", "/api/player/nobody"), ("GET", "/api/player"),
                 ("GET", "/api/player/a/b"), ("GET", "/nope"),
                 ("POST", "/api/health")]
        for method, path in paths:
            _, body = api.dispatch(method, path)
            self.assertIn(body["error"]["code"], api.ERROR_CODES)


class TestDeterminism(ApiTestBase):

    def test_repeated_requests_return_identical_json(self):
        blobs = {api.serialize(api.dispatch(
            "GET", "/api/player/zhang-yucheng")[1]) for _ in range(5)}
        self.assertEqual(len(blobs), 1, "重複請求的 JSON 不一致")

    def test_response_is_independent_of_dict_insertion_order(self):
        payload = json.loads(self.raw)
        shuffled = {k: payload[k] for k in reversed(list(payload))}
        self.assertEqual(api.serialize(shuffled), self.raw)

    def test_request_order_does_not_matter(self):
        api.dispatch("GET", "/api/health")
        api.dispatch("GET", "/api/player/nobody")
        after = api.serialize(
            api.dispatch("GET", "/api/player/zhang-yucheng")[1])
        self.assertEqual(after, self.raw)

    def test_body_contains_no_request_timestamp(self):
        block = self.payload["api"]
        self.assertFalse(block["request_time_included"])
        self.assertTrue(block["request_time_note"])

    def test_data_as_of_is_derived_from_data_not_the_clock(self):
        as_of = self.payload["api"]["data_as_of"]
        self.assertEqual(
            as_of["reference_date"],
            self.payload["next_game"]["selection_rule"]["reference_date"])
        self.assertTrue(as_of["clock_independent"])
        self.assertTrue(as_of["is_not_request_time"])
        digests = {r["path"]: r["sha256"] for r in as_of["source_file_digests"]}
        self.assertEqual(len(digests), 3)
        for path, (digest, _size) in self.hashes_before.items():
            self.assertEqual(digests[path.name], digest)

    def test_metadata_declares_determinism(self):
        det = self.payload["metadata"]["determinism"]
        self.assertTrue(det["deterministic"])
        self.assertTrue(det["clock_independent"])
        self.assertTrue(det["input_order_independent"])


class TestNoExternalAccess(ApiTestBase):

    def test_network_guard_is_active(self):
        self.assertTrue(network_guard_active())

    def test_api_module_imports_no_http_client(self):
        import ast
        tree = ast.parse((ROOT / "src" / "api.py").read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        for banned in ("requests", "httpx", "aiohttp", "urllib3",
                       "http.client", "socket"):
            self.assertNotIn(banned, modules, f"api.py 匯入了 {banned}")

    def test_serving_a_request_makes_no_socket_connection(self):
        import socket as socket_module
        calls = []
        original = socket_module.socket.connect

        def spy(self, *args, **kwargs):
            calls.append(args)
            return original(self, *args, **kwargs)

        socket_module.socket.connect = spy
        try:
            api.dispatch("GET", "/api/player/zhang-yucheng")
            api.dispatch("GET", "/api/health")
        finally:
            socket_module.socket.connect = original
        self.assertEqual(calls, [], "請求路徑上出現了 socket 連線")

    def test_http_server_can_bind_without_any_outbound_call(self):
        server = api.make_server("127.0.0.1", 0)
        try:
            host, port = server.server_address[:2]
            self.assertEqual(host, "127.0.0.1")
            self.assertGreater(port, 0)
            self.assertTrue(issubclass(server.RequestHandlerClass,
                                       api.ApiHandler))
        finally:
            server.server_close()

    def test_cors_is_off_by_default(self):
        self.assertEqual(api.ApiHandler.cors_origins, ())
        server = api.make_server("127.0.0.1", 0)
        try:
            self.assertEqual(server.RequestHandlerClass.cors_origins, ())
        finally:
            server.server_close()
        scoped = api.make_server("127.0.0.1", 0,
                                 ("http://localhost:5173",))
        try:
            self.assertEqual(scoped.RequestHandlerClass.cors_origins,
                             ("http://localhost:5173",))
        finally:
            scoped.server_close()

    def test_server_banner_hides_python_version(self):
        self.assertEqual(api.ApiHandler.sys_version, "")
        self.assertNotIn("Python", api.ApiHandler.server_version)


class TestSourceIntegrityAndNoNewConstructs(ApiTestBase):

    def test_source_files_unchanged_after_serving(self):
        for _ in range(3):
            api.dispatch("GET", "/api/player/zhang-yucheng")
        for path, before in self.hashes_before.items():
            self.assertEqual(sha256_of(path), before,
                             f"{path.name} 在提供服務後被修改")

    def test_api_writes_no_files(self):
        data_dir = ROOT / "data"
        before = sorted(p.relative_to(ROOT).as_posix()
                        for p in data_dir.rglob("*") if p.is_file())
        api.CACHE.clear()
        api.dispatch("GET", "/api/player/zhang-yucheng")
        after = sorted(p.relative_to(ROOT).as_posix()
                       for p in data_dir.rglob("*") if p.is_file())
        self.assertEqual(before, after, "data/ 下的檔案清單改變了")

    def test_api_introduces_no_ranking_or_scoring_fields(self):
        leaks = scan_forbidden_keys(self.payload)
        self.assertEqual(leaks, [], f"出現禁用欄位：{leaks[:5]}")

    def test_api_block_declares_no_forbidden_constructs(self):
        contains_no = self.payload["api"]["contains_no"]
        for item in ("score", "weight", "threshold", "ranking", "priority",
                     "top_n", "prediction", "recommendation", "llm",
                     "database", "authentication", "live_scraping"):
            self.assertIn(item, contains_no)

    def test_insight_order_is_not_a_ranking(self):
        # section 成員一律照 scope 字母排序，且規則明文宣告不看數值
        for sid in ("current_form", "contextual_evidence"):
            section = self.payload[sid]
            self.assertEqual(section["scopes"], sorted(section["scopes"]))
            rule = section["member_selection_rule"]
            self.assertEqual(rule["rule_inputs"], ["step18_perspective"])
            self.assertTrue(rule["all_groups_included"])
            for banned in ("magnitude", "sample_size_at_bats", "classification"):
                self.assertIn(banned, rule["rule_not_inputs"])

    def test_consumer_contract_forbids_client_side_ranking(self):
        contract = self.payload["metadata"]["consumer_contract"]
        self.assertEqual(contract["single_source_of_numbers"],
                         "factual_insights")
        self.assertTrue(contract["sections_hold_references_only"])
        self.assertTrue(contract["safe_to_render_all"])
        self.assertGreaterEqual(len(contract["must_not_do"]), 5)

    def test_no_new_analytical_metric_is_added_by_the_api(self):
        # API 只加一個 api 區塊；Step 22 的 9 個區塊必須逐位元相同
        logs, apart_rows = load_inputs()
        from insight_chain import load_schedule
        from product_output_model import build_product_output
        reference = build_product_output(logs, apart_rows, load_schedule())
        for key in STEP22_TOP_LEVEL:
            self.assertEqual(self.payload[key], reference[key],
                             f"{key} 與 Step 22 產出不同")


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"\n共 {total} 項測試，通過 {total - failed} 項，失敗 {failed} 項。")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())

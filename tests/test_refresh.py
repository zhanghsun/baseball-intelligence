"""Step 25 手動資料更新 regression tests。

只用標準庫 `unittest`，沒有新增任何依賴。

測試一律以 `--no-fetch` 模式執行（零 HTTP），因為：
  - 目前 repository 的資料就是基準，沒有新比賽（本階段禁止偽造比賽）
  - 要證明的是「refresh 可以安全重新執行現有資料」
網路路徑則用結構性檢查驗證接線正確（沿用 Step 2 / 3 / 8 的既有入口），
不在測試中實際呼叫 CPBL。

執行：
    python tests/test_refresh.py
"""

from __future__ import annotations

import ast
import io
import contextlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import refresh_data  # noqa: E402

DATA_DIR = ROOT / "data"

# refresh 允許寫入的資料檔（不得多也不得少）
EXPECTED_DATA_FILES = {
    "fubon_schedule_2026.json",
    "zhang_yucheng_game_logs_2026.json",
    "apart_score_0000006888_2026_A_01.json",
    "follow_score_0000006888_2026.json",
}

STEP22_TOP_LEVEL = (
    "player", "next_game", "season_baseline", "current_form",
    "contextual_evidence", "factual_insights", "data_status",
    "traceability", "metadata",
)

# refresh_data.py 允許 import 的頂層模組：標準庫 + 本專案既有模組
STDLIB_ALLOWED = {
    "__future__", "argparse", "hashlib", "json", "os", "shutil", "sys",
    "tempfile", "traceback", "pathlib",
}
PROJECT_ALLOWED = {
    "build_processed_data", "context_splits", "data_source_experiment",
    "schedule_source_experiment", "candidate_insights", "insight_chain",
    "product_output_model", "api",
}


def run_refresh(argv: list[str]) -> tuple[int, str]:
    """執行 refresh 並回傳 (exit_code, 輸出)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = refresh_data.main(argv)
    return code, buf.getvalue()


def data_file_listing() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix()
                  for p in DATA_DIR.rglob("*") if p.is_file())


def all_digests() -> dict:
    paths = list(refresh_data.DATA_FILES) + refresh_data.MUST_NOT_CHANGE
    return {p.name: refresh_data.digest(p) for p in paths}


def collect_imports(path: Path) -> tuple[set[str], set[str]]:
    """回傳 (module 層級 import, 函式內 import) 的頂層模組名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top: set[str] = set()
    inner: set[str] = set()

    def names(node) -> set[str]:
        out = set()
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
        return out

    for node in tree.body:
        top |= names(node)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            inner |= names(node)
    return top, inner - top


class RefreshTestBase(unittest.TestCase):
    """整個測試類共用一次基準快照。"""

    digests_before: dict
    listing_before: list

    @classmethod
    def setUpClass(cls) -> None:
        cls.digests_before = all_digests()
        cls.listing_before = data_file_listing()

    @classmethod
    def tearDownClass(cls) -> None:
        after = all_digests()
        for name, before in cls.digests_before.items():
            assert after[name] == before, f"{name} 在測試期間被修改"


class TestScriptStarts(RefreshTestBase):
    """1. refresh script 可以啟動。"""

    def test_help_works(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                refresh_data.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        text = buf.getvalue()
        self.assertIn("--dry-run", text)
        self.assertIn("--no-fetch", text)

    def test_no_fetch_run_succeeds(self):
        code, out = run_refresh(["--no-fetch"])
        self.assertEqual(code, 0, out[-1500:])
        self.assertIn("全部驗證通過", out)
        self.assertNotIn("[FAIL]", out)

    def test_all_internal_checks_pass(self):
        _, out = run_refresh(["--no-fetch"])
        self.assertEqual(out.count("[FAIL]"), 0)
        self.assertGreaterEqual(out.count("[PASS]"), 8)

    def test_mutually_exclusive_modes(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as ctx:
                refresh_data.main(["--dry-run", "--no-fetch"])
        self.assertNotEqual(ctx.exception.code, 0)


class TestNoThirdPartyDependency(RefreshTestBase):
    """2. 不需要第三方 dependency。"""

    def test_refresh_imports_only_stdlib_and_project_modules(self):
        top, inner = collect_imports(ROOT / "src" / "refresh_data.py")
        allowed = STDLIB_ALLOWED | PROJECT_ALLOWED
        self.assertTrue(top <= allowed, f"未預期的 module 層級 import：{top - allowed}")
        self.assertTrue(inner <= allowed, f"未預期的函式內 import：{inner - allowed}")

    def test_no_pipeline_import_at_module_level(self):
        """分析 pipeline 必須延後 import，否則 socket guard 會先封鎖網路。"""
        top, inner = collect_imports(ROOT / "src" / "refresh_data.py")
        for module in ("candidate_insights", "product_output_model",
                       "insight_chain", "api"):
            self.assertNotIn(module, top,
                             f"{module} 在 module 層級被 import，會提前封鎖網路")
            self.assertIn(module, inner, f"{module} 應該在函式內延後 import")

    def test_requirements_still_empty(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        self.assertEqual(lines, [], f"requirements.txt 出現依賴：{lines}")

    def test_no_package_manifest_added(self):
        for name in ("package.json", "package-lock.json", "node_modules",
                     "pyproject.toml", "Pipfile", "poetry.lock"):
            self.assertFalse((ROOT / name).exists(), f"{name} 被新增了")

    def test_no_scheduler_or_daemon_constructs(self):
        source = (ROOT / "src" / "refresh_data.py").read_text(encoding="utf-8")
        for banned in ("import sched", "import threading", "crontab",
                       "schedtasks", "schtasks", "while True",
                       "time.sleep", "APScheduler", "celery"):
            self.assertNotIn(banned, source, f"出現 {banned}")


class TestExistingDataRebuilds(RefreshTestBase):
    """3. 現有資料可以重新建立。"""

    def test_serializer_reproduces_existing_files_byte_for_byte(self):
        problems = refresh_data.verify_serializer_matches_existing()
        self.assertEqual(problems, [], f"格式不一致：{problems}")

    def test_no_fetch_run_reports_everything_unchanged(self):
        _, out = run_refresh(["--no-fetch"])
        self.assertIn("新資料與現有資料完全相同，因此不寫入任何檔案。", out)
        for name in EXPECTED_DATA_FILES:
            self.assertIn(f"不變  {name}", out)

    def test_pipeline_and_product_output_rebuild(self):
        output = refresh_data.build_product_output_now()
        counts = output["metadata"]["counts"]
        self.assertEqual(counts["groups"], 9)
        self.assertEqual(counts["candidates"], 29)
        self.assertEqual(counts["insights"], 9)
        self.assertEqual(counts["metric_rows"], 25)
        for key in STEP22_TOP_LEVEL:
            self.assertIn(key, output)

    def test_all_data_files_parse(self):
        for path in refresh_data.DATA_FILES:
            records = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(records, list)
            self.assertGreater(len(records), 0)


class TestSchemaUnchanged(RefreshTestBase):
    """4 / 5. Product Output schema 與 API schema 不變。"""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.before = refresh_data.product_output_schema(
            refresh_data.build_product_output_now())
        run_refresh(["--no-fetch"])
        cls.after_output = refresh_data.build_product_output_now()
        cls.after = refresh_data.product_output_schema(cls.after_output)

    def test_product_output_schema_identical(self):
        self.assertEqual(self.after["top_level"], self.before["top_level"])
        self.assertEqual(self.after["key_paths"], self.before["key_paths"])
        self.assertEqual(self.after["controlled_vocabularies"],
                         self.before["controlled_vocabularies"])
        self.assertEqual(self.after["display_slots"], self.before["display_slots"])
        self.assertEqual(self.after["counts_keys"], self.before["counts_keys"])
        self.assertEqual(self.after["product_output_version"], "step22-v1")

    def test_api_schema_identical(self):
        import api
        api.CACHE.clear()
        status, payload = api.dispatch("GET", "/api/player/zhang-yucheng")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(payload),
                         sorted(list(STEP22_TOP_LEVEL) + ["api"]))
        self.assertEqual(payload["api"]["api_version"], api.API_VERSION)
        for key in STEP22_TOP_LEVEL:
            self.assertEqual(payload[key], self.after_output[key],
                             f"{key} 與 Product Output 不同")

    def test_health_endpoint_still_works(self):
        import api
        status, body = api.dispatch("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_controlled_vocabularies_are_not_extended(self):
        vocab = self.after["controlled_vocabularies"]
        self.assertEqual(vocab["data_status"]["values"],
                         ["available", "partially_available", "unavailable",
                          "not_investigated"])
        self.assertEqual(len(vocab["interpretation_status"]["values"]), 3)
        self.assertEqual(vocab["new_in_step_22"], ["display_slot"])


class TestDoesNotTouchApiOrFrontend(RefreshTestBase):
    """6 / 7 / 8. 不修改 frontend、API、Step 5~22 規則。"""

    def test_program_files_unchanged_after_refresh(self):
        before = {p: refresh_data.digest(p) for p in refresh_data.MUST_NOT_CHANGE}
        run_refresh(["--no-fetch"])
        for path, digest_before in before.items():
            self.assertEqual(refresh_data.digest(path), digest_before,
                             f"{path.name} 被 refresh 修改了")

    def test_must_not_change_list_covers_api_frontend_and_pipeline(self):
        names = {p.name for p in refresh_data.MUST_NOT_CHANGE}
        for required in ("api.py", "product_output_model.py",
                         "insight_assembly.py", "candidate_insights.py",
                         "app.js", "render.js", "serve.py", "index.html"):
            self.assertIn(required, names)

    def test_whole_web_directory_unchanged(self):
        web = ROOT / "web"
        before = {p: refresh_data.digest(p) for p in web.rglob("*")
                  if p.is_file()}
        run_refresh(["--no-fetch"])
        for path, digest_before in before.items():
            self.assertEqual(refresh_data.digest(path), digest_before,
                             f"web/{path.name} 被修改了")

    def test_all_src_modules_except_refresh_unchanged(self):
        src = ROOT / "src"
        before = {p: refresh_data.digest(p) for p in src.glob("*.py")}
        run_refresh(["--no-fetch"])
        for path, digest_before in before.items():
            self.assertEqual(refresh_data.digest(path), digest_before,
                             f"src/{path.name} 被修改了")


class TestDeterminism(RefreshTestBase):
    """9. 重跑兩次結果 deterministic。"""

    def test_two_runs_leave_identical_data(self):
        run_refresh(["--no-fetch"])
        first = {p.name: refresh_data.digest(p) for p in refresh_data.DATA_FILES}
        run_refresh(["--no-fetch"])
        second = {p.name: refresh_data.digest(p) for p in refresh_data.DATA_FILES}
        self.assertEqual(first, second)
        self.assertEqual(first, {p.name: self.digests_before[p.name]
                                 for p in refresh_data.DATA_FILES})

    def test_two_runs_produce_identical_product_output(self):
        run_refresh(["--no-fetch"])
        a = json.dumps(refresh_data.build_product_output_now(),
                       ensure_ascii=False, sort_keys=True)
        run_refresh(["--no-fetch"])
        b = json.dumps(refresh_data.build_product_output_now(),
                       ensure_ascii=False, sort_keys=True)
        self.assertEqual(a, b)

    def test_output_text_is_stable_apart_from_nothing(self):
        _, first = run_refresh(["--no-fetch"])
        _, second = run_refresh(["--no-fetch"])
        # 輸出不含時間戳，因此兩次執行的畫面內容完全相同
        self.assertEqual(first, second)


class TestFailureLeavesNoHalfUpdate(RefreshTestBase):
    """10. refresh 失敗不會留下損壞的正式資料。"""

    def test_validation_failure_triggers_restore_and_exit_1(self):
        before = {p: refresh_data.digest(p) for p in refresh_data.DATA_FILES}
        original = refresh_data.validate_after

        def failing(before_schema):
            return {
                "checks": [("刻意注入的失敗", False, "測試用")],
                "output": None, "api_payload": None,
            }

        refresh_data.validate_after = failing
        try:
            code, out = run_refresh(["--no-fetch"])
        finally:
            refresh_data.validate_after = original
        self.assertEqual(code, 1)
        self.assertIn("還原到 refresh 前的狀態", out)
        for path, digest_before in before.items():
            self.assertEqual(refresh_data.digest(path), digest_before,
                             f"{path.name} 在失敗後沒有被還原")

    def test_exception_triggers_restore_and_exit_1(self):
        before = {p: refresh_data.digest(p) for p in refresh_data.DATA_FILES}
        original = refresh_data.build_product_output_now

        def boom():
            raise RuntimeError("刻意注入的例外")

        refresh_data.build_product_output_now = boom
        try:
            code, out = run_refresh(["--no-fetch"])
        finally:
            refresh_data.build_product_output_now = original
        self.assertEqual(code, 1)
        self.assertIn("發生例外", out)
        for path, digest_before in before.items():
            self.assertEqual(refresh_data.digest(path), digest_before)

    def test_snapshot_restores_modified_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.json"
            target.write_bytes(b'["original"]')
            snapshot = refresh_data.Snapshot([target])
            try:
                target.write_bytes(b'["corrupted"]')
                restored = snapshot.restore()
                self.assertEqual(restored, ["sample.json"])
                self.assertEqual(target.read_bytes(), b'["original"]')
            finally:
                snapshot.close()

    def test_snapshot_deletes_file_that_did_not_exist_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new.json"
            snapshot = refresh_data.Snapshot([target])
            try:
                target.write_bytes(b"[]")
                snapshot.restore()
                self.assertFalse(target.exists())
            finally:
                snapshot.close()

    def test_atomic_write_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.json"
            refresh_data.atomic_write(target, b'["new"]')
            self.assertEqual(target.read_bytes(), b'["new"]')
            leftovers = [p.name for p in Path(tmp).iterdir()
                         if p.name.endswith(refresh_data.TMP_SUFFIX)]
            self.assertEqual(leftovers, [])

    def test_failed_replace_keeps_original_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.json"
            target.write_bytes(b'["original"]')
            original_replace = os.replace

            def failing_replace(*args, **kwargs):
                raise OSError("刻意注入的替換失敗")

            os.replace = failing_replace
            try:
                with self.assertRaises(OSError):
                    refresh_data.atomic_write(target, b'["new"]')
            finally:
                os.replace = original_replace
            # 正式檔完好，只留下暫存檔
            self.assertEqual(target.read_bytes(), b'["original"]')
            tmp_path = target.with_name(target.name + refresh_data.TMP_SUFFIX)
            self.assertTrue(tmp_path.exists())
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_leftover_temp_files_in_data_dir(self):
        run_refresh(["--no-fetch"])
        leftovers = [p.name for p in DATA_DIR.rglob("*")
                     if p.name.endswith(refresh_data.TMP_SUFFIX)]
        self.assertEqual(leftovers, [])


class TestSourceFilesPreserved(RefreshTestBase):
    """11. 現有 source files 可以被保留。"""

    def test_data_directory_listing_unchanged(self):
        run_refresh(["--no-fetch"])
        self.assertEqual(data_file_listing(), self.listing_before)

    def test_all_expected_data_files_still_exist(self):
        run_refresh(["--no-fetch"])
        for path in refresh_data.DATA_FILES:
            self.assertTrue(path.exists(), f"{path.name} 不見了")
            self.assertGreater(path.stat().st_size, 0)

    def test_historical_records_are_not_rewritten(self):
        """`--no-fetch` 前後逐場資料逐筆相同，歷史資料語意沒被改動。

        刻意不寫死筆數（筆數會隨 refresh 增加）。改用資料推導的不變量：
        逐場筆數必須等於 pipeline 算出的季出賽場數，且日期單調不遞減。
        """
        path = DATA_DIR / "processed" / "zhang_yucheng_game_logs_2026.json"
        logs = json.loads(path.read_text(encoding="utf-8"))
        run_refresh(["--no-fetch"])
        after = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(after), len(logs))
        self.assertEqual(after, logs)
        self.assertGreater(len(after), 0)

        # 與 pipeline 交叉核對：processed 筆數 == 季累計出賽場數
        output = refresh_data.build_product_output_now()
        self.assertEqual(len(after), output["season_baseline"]["games"])
        self.assertEqual(len(after), output["player"]["games_played"])

        # 日期單調不遞減、game_sno 唯一（歷史順序沒被打亂）
        dates = [g["game_date"] for g in after]
        self.assertEqual(dates, sorted(dates))
        snos = [g["game_sno"] for g in after]
        self.assertEqual(len(snos), len(set(snos)))


class TestNoSecondCache(RefreshTestBase):
    """12. 不會建立第二套 cache。"""

    def test_apart_cache_path_is_the_step8_one(self):
        import context_splits
        self.assertEqual(refresh_data.APART_CACHE, context_splits.CACHE_PATH)

    def test_refresh_writes_only_the_four_known_files(self):
        names = {p.name for p in refresh_data.DATA_FILES}
        self.assertEqual(names, EXPECTED_DATA_FILES)

    def test_fetch_reuses_existing_step8_cache_function(self):
        source = (ROOT / "src" / "refresh_data.py").read_text(encoding="utf-8")
        self.assertIn("context_splits.fetch_apart_rows(refetch=True)", source)
        self.assertIn("from schedule_source_experiment import fetch_year_schedule",
                      source)
        self.assertIn("from data_source_experiment import fetch_follow_score",
                      source)
        # 沒有自己重寫 HTTP 請求
        for banned in ("urllib.request", "http.cookiejar", "urlopen",
                       "RequestVerificationToken"):
            self.assertNotIn(banned, source, f"refresh 自行實作了 {banned}")

    def test_no_new_cache_directory_created(self):
        run_refresh(["--no-fetch"])
        dirs = sorted(p.relative_to(ROOT).as_posix()
                      for p in DATA_DIR.rglob("*") if p.is_dir())
        self.assertEqual(dirs, ["data/processed", "data/raw"])


class TestNetworkPathIsIsolated(RefreshTestBase):
    """四、HTTP 只能出現在更新流程，網站路徑不得碰 CPBL。"""

    def test_no_fetch_mode_makes_no_socket_connection(self):
        import socket as socket_module
        calls = []
        original = socket_module.socket.connect

        def spy(self, *args, **kwargs):
            calls.append(args)
            return original(self, *args, **kwargs)

        socket_module.socket.connect = spy
        try:
            code, _ = run_refresh(["--no-fetch"])
        finally:
            socket_module.socket.connect = original
        self.assertEqual(code, 0)
        self.assertEqual(calls, [], "--no-fetch 模式出現了 socket 連線")

    def test_api_and_frontend_never_reference_cpbl(self):
        for rel in ("src/api.py", "web/app.js", "web/render.js", "web/serve.py"):
            source = (ROOT / rel).read_text(encoding="utf-8")
            for banned in ("cpbl.com.tw", "getfollowscore", "getapartscore",
                           "getgamedatas"):
                self.assertNotIn(banned, source.lower(), f"{rel} 引用了 {banned}")

    def test_fetch_all_is_the_only_network_entry(self):
        tree = ast.parse((ROOT / "src" / "refresh_data.py").read_text(
            encoding="utf-8"))
        fetch_modules = {"data_source_experiment", "schedule_source_experiment"}
        importing_functions = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module in fetch_modules:
                    importing_functions.add(node.name)
        self.assertEqual(importing_functions, {"fetch_all"},
                         f"抓取層被多個函式 import：{importing_functions}")


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

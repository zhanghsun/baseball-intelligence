"""Step 24 Frontend 測試。

只用標準庫 `unittest`，沒有新增任何 Python 或 npm 依賴。

兩層驗證：

1. **行為驗證（實際執行 JS）**
   payload 來自真實的 Step 23 API（`api.dispatch`），寫到暫存目錄後由
   `node web/tests/run_render.mjs` 匯入真正的 `web/render.js` 建出 view model，
   再把結果拉回 Python 斷言。沒有 fixture 檔案，因此不會與 API 漂移。

   其中包含 **mutation 反證**：把 payload 的某個欄位換成哨兵值，確認畫面上的值
   跟著變（＝前端是讀 API 的值，不是自己算的），以及把順序反轉後 view model
   的順序跟著變（＝前端沒有自己 sort）。

2. **靜態檢查（不需要 node）**
   掃描 `web/` 的原始碼，確認沒有 `.sort(` / `Date.now()` / `data/` 讀取 /
   LLM / 額外資料來源，且 `render.js` 讀到的每個 payload 路徑都真的存在。

執行：
    python tests/test_frontend.py
"""

from __future__ import annotations

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
from candidate_insights import APART_CACHE_PATH, PLAYER_LOG_PATH, sha256_of  # noqa: E402
from insight_chain import SCHEDULE_PATH  # noqa: E402

SOURCE_PATHS = (PLAYER_LOG_PATH, APART_CACHE_PATH, SCHEDULE_PATH)

NODE = shutil.which("node")
BRIDGE = WEB / "tests" / "run_render.mjs"

FRONTEND_FILES = ("render.js", "app.js", "index.html", "styles.css", "serve.py")

EXPECTED_SCOPES = [
    "RECENT_10", "RECENT_15", "VS_CLOSER", "VS_DOMESTIC", "VS_FOREIGN",
    "VS_LEFT", "VS_RELIEF", "VS_RIGHT", "VS_STARTER",
]

NO_DATA = "尚無資料"
NOT_COMPUTABLE = "無法計算"


def run_render(payload: dict) -> dict:
    """把 payload 交給真正的 render.js，取回 view model。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "payload.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            [NODE, str(BRIDGE), str(path)],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        )
    if proc.returncode != 0:
        raise AssertionError(f"render.js 執行失敗：{proc.stderr[:400]}")
    return json.loads(proc.stdout)


def run_error_render(kind: str, detail: dict | None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [NODE, str(BRIDGE), "--error", kind]
        if detail is not None:
            path = Path(tmp) / "detail.json"
            path.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
            cmd.append(str(path))
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", cwd=str(ROOT))
    if proc.returncode != 0:
        raise AssertionError(f"render.js 執行失敗：{proc.stderr[:400]}")
    return json.loads(proc.stdout)


def section_groups(vm: dict, index: int) -> list:
    """section 只放參照，數值只存在 vm["insights"] 一處。

    這個 helper 把 groupRefs 的索引解回 insight，跟 app.js 的做法一樣。
    """
    section = vm["sections"][index]
    return [vm["insights"][ref["insightIndex"]] for ref in section["groupRefs"]]


def iter_cells(node):
    """走訪 view model 裡所有「cell」物件（含 isNull / text 的那些）。"""
    if isinstance(node, dict):
        if "isNull" in node and "text" in node:
            yield node
        for value in node.values():
            yield from iter_cells(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_cells(value)


LITERAL_RE = re.compile(
    r"'(?:[^'\\\n]|\\.)*'"      # 單引號
    r"|\"(?:[^\"\\\n]|\\.)*\""  # 雙引號
    r"|`(?:[^`\\]|\\.)*`"       # 樣板字串
)


def string_literals(source: str) -> list[str]:
    """抽出原始碼中的字串常值。

    刻意只看常值、不看註解：註解裡本來就寫著「不讀 data/processed」這類否定
    宣告，掃全文會自我命中（Step 19 ~ 22 已多次記錄這個問題）。
    """
    return [m.group(0)[1:-1] for m in LITERAL_RE.finditer(source)]


def iter_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from iter_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_strings(value)


@unittest.skipIf(NODE is None, "找不到 node，跳過需要執行 JS 的測試")
class FrontendRenderBase(unittest.TestCase):

    payload: dict
    vm: dict
    hashes_before: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.hashes_before = {p: sha256_of(p) for p in SOURCE_PATHS}
        status, payload = api.dispatch("GET", "/api/player/zhang-yucheng")
        assert status == 200, status
        # 走一次真正的 JSON 序列化 / 反序列化，模擬瀏覽器收到的東西
        cls.payload = json.loads(api.serialize(payload))
        cls.vm = run_render(cls.payload)

    @classmethod
    def tearDownClass(cls) -> None:
        for path, before in cls.hashes_before.items():
            assert sha256_of(path) == before, f"{path.name} 在測試期間被修改"


class TestApiLoads(FrontendRenderBase):
    """1. API response 可以正常載入。"""

    def test_payload_loads_and_has_all_sections(self):
        for key in ("player", "next_game", "season_baseline", "current_form",
                    "contextual_evidence", "factual_insights", "data_status",
                    "traceability", "metadata", "api"):
            self.assertIn(key, self.payload)

    def test_view_model_builds_without_error(self):
        for key in ("header", "nextGame", "seasonBaseline", "sections",
                    "insights", "dataStatus", "traceability", "meta",
                    "frontendGuards"):
            self.assertIn(key, self.vm)


class TestPlayerHeader(FrontendRenderBase):
    """2. player 正確顯示。"""

    def test_player_identity_matches_api(self):
        h = self.vm["header"]
        p = self.payload["player"]
        self.assertEqual(h["playerName"]["text"], p["player_name"])
        self.assertEqual(h["playerName"]["text"], "張育成")
        self.assertEqual(h["season"]["text"], str(p["season"]))
        self.assertEqual(h["season"]["text"], "2026")
        self.assertEqual(h["team"]["text"], p["team"])
        self.assertEqual(h["gamesPlayed"]["text"], str(p["games_played"]))
        self.assertEqual(h["atBats"]["text"], str(p["at_bats"]))

    def test_data_as_of_comes_from_api_not_browser_clock(self):
        as_of = self.vm["header"]["dataAsOf"]
        self.assertEqual(as_of["referenceDate"]["text"],
                         self.payload["api"]["data_as_of"]["reference_date"])
        # 不寫死日期（資料會隨 refresh 前進）。改驗證資料推導出來的不變量：
        #   (a) ISO 日期格式
        #   (b) 參考日 = 已完成比賽中最晚的一天，因此必定早於下一場
        #   (c) 與 next_game.selection_rule 的參考日一致
        self.assertRegex(as_of["referenceDate"]["text"], r"^\d{4}-\d{2}-\d{2}$")
        next_game_date = self.payload["next_game"]["game"]["game_date"]
        self.assertLess(as_of["referenceDate"]["text"], next_game_date)
        self.assertEqual(
            as_of["referenceDate"]["text"],
            self.payload["next_game"]["selection_rule"]["reference_date"])
        self.assertTrue(as_of["clockIndependent"])
        self.assertEqual(len(as_of["sourceFileDigests"]), 3)
        for record in as_of["sourceFileDigests"]:
            self.assertEqual(len(record["sha256"]), 64)


class TestNextGame(FrontendRenderBase):
    """3. next_game 正確顯示。"""

    def test_scheduled_fields_match_api(self):
        cells = {f["key"]: f["cell"] for f in self.vm["nextGame"]["fields"]}
        g = self.payload["next_game"]["game"]
        self.assertEqual(cells["game_date"]["text"], g["game_date"])
        self.assertEqual(cells["scheduled_time"]["text"], g["scheduled_time"])
        self.assertEqual(cells["opponent"]["text"], g["opponent"])
        self.assertEqual(cells["venue"]["text"], g["venue"])
        self.assertEqual(cells["game_status"]["text"], g["game_status"])
        self.assertEqual(cells["home_away"]["text"],
                         "主場" if g["home_away"] == "home" else "客場")

    def test_unplayed_score_is_never_rendered_as_zero(self):
        result = self.vm["nextGame"]["result"]
        self.assertEqual(result["display"], NO_DATA)
        self.assertTrue(result["home"]["isNull"])
        self.assertTrue(result["visiting"]["isNull"])
        self.assertNotIn("0:0", result["display"])
        self.assertNotEqual(result["home"]["text"], "0")
        self.assertNotEqual(result["visiting"]["text"], "0")
        self.assertTrue(result["reason"])
        # 官方檔內的 0 只出現在追溯欄位，沒有進入顯示欄位
        self.assertIsNotNone(result["rawValuesForTraceabilityOnly"])

    def test_starting_pitcher_partial_state_is_explicit(self):
        sp = self.vm["nextGame"]["startingPitcher"]
        self.assertFalse(sp["acnt"]["isNull"])
        self.assertTrue(sp["name"]["isNull"])
        self.assertEqual(sp["name"]["text"], NO_DATA)
        self.assertTrue(sp["name"]["reason"])
        self.assertEqual(sp["dataStatus"]["value"], "partially_available")
        self.assertEqual(sp["dataStatus"]["label"], "尚未確認（部分驗證）")
        self.assertTrue(sp["unconfirmedReason"])

    def test_pitcher_hand_unavailable_state_is_explicit(self):
        hand = self.vm["nextGame"]["startingPitcherHand"]
        self.assertTrue(hand["hand"]["isNull"])
        self.assertTrue(hand["hand"]["reason"])
        self.assertEqual(hand["dataStatus"]["value"], "unavailable")
        self.assertEqual(hand["dataStatus"]["label"], "目前無法取得")
        self.assertTrue(hand["requiredToResolve"])


class TestSeasonBaseline(FrontendRenderBase):
    """4. season_baseline 正確顯示。"""

    def test_three_metrics_with_values_and_sample_size(self):
        metrics = self.vm["seasonBaseline"]["metrics"]
        self.assertEqual([m["metric"] for m in metrics],
                         ["batting_average", "on_base_percentage",
                          "slugging_percentage"])
        src = self.payload["season_baseline"]
        for m in metrics:
            expected = src["metrics"][m["metric"]]["value"]
            self.assertEqual(m["value"]["raw"], expected)
            self.assertEqual(m["value"]["full"], f"{expected:.8f}")
            self.assertFalse(m["value"]["isNull"])
            self.assertTrue(m["derivation"])
            self.assertEqual(m["sampleSize"]["atBats"]["text"],
                             str(src["at_bats"]))
            self.assertEqual(m["sampleSize"]["plateAppearances"]["text"],
                             str(src["plate_appearances"]))

    def test_ratio_formatting_keeps_full_precision_alongside(self):
        """驗證格式化規則本身，不寫死數值（數值會隨 refresh 改變）。

        規則：headline 是棒球慣用的三位小數去前導 0（`.311`），
        旁邊一律並排完整 8 位精度，且兩者都由同一個 payload 值產生。
        """
        for metric in self.vm["seasonBaseline"]["metrics"]:
            raw = self.payload["season_baseline"]["metrics"][
                metric["metric"]]["value"]
            self.assertEqual(metric["value"]["raw"], raw)
            self.assertEqual(metric["value"]["full"], f"{raw:.8f}")
            expected_text = f"{raw:.3f}"
            if expected_text.startswith("0."):
                expected_text = expected_text[1:]
            self.assertEqual(metric["value"]["text"], expected_text)
            self.assertRegex(metric["value"]["text"], r"^\.\d{3}$")
            # 完整精度沒有被藏起來，且與 headline 是同一個數
            self.assertTrue(metric["value"]["full"].startswith("0."))
            self.assertEqual(round(raw, 3), float(metric["value"]["text"]))


class TestCurrentForm(FrontendRenderBase):
    """5. current_form 正確顯示。"""

    def test_section_has_two_groups_in_api_order(self):
        section = self.vm["sections"][0]
        self.assertEqual(section["sectionId"], "current_form")
        self.assertEqual(section["groupCount"], 2)
        self.assertEqual(section["candidateCount"], 4)
        self.assertEqual([g["scope"] for g in section_groups(self.vm, 0)],
                         [r["scope"] for r in
                          self.payload["current_form"]["insight_refs"]])
        self.assertTrue(section["holdsReferencesOnly"])

    def test_recent10_metrics_are_read_from_api(self):
        group = next(g for g in section_groups(self.vm, 0)
                     if g["scope"] == "RECENT_10")
        insight = self.payload["factual_insights"][group["insightId"]]
        by_metric = {e["metric"]: e
                     for e in insight["supporting_evidence"]["primary_metrics"]}
        for row in group["metrics"]:
            if not row["available"]:
                continue
            src = by_metric[row["metric"]]
            self.assertEqual(row["current"]["raw"], src["current_value"])
            self.assertEqual(row["baseline"]["raw"], src["baseline_value"])
            self.assertEqual(row["difference"]["raw"], src["difference"])
            self.assertEqual(row["direction"]["value"], src["direction"])
            self.assertEqual(row["sampleSize"]["atBats"]["raw"],
                             src["sample_size"]["at_bats"])
            self.assertEqual(row["sensitivity"]["delta"]["raw"],
                             src["sensitivity"]["delta_if_one_more"])
            self.assertEqual(row["rolling"]["rankDesc"],
                             src["rolling_percentile"]["rank_desc"])

    def test_recent_obp_is_not_computable_not_zero(self):
        for scope in ("RECENT_10", "RECENT_15"):
            group = next(g for g in section_groups(self.vm, 0)
                         if g["scope"] == scope)
            obp = next(r for r in group["metrics"]
                       if r["metric"] == "on_base_percentage")
            self.assertFalse(obp["available"])
            self.assertEqual(obp["current"]["text"], NOT_COMPUTABLE)
            self.assertIsNone(obp["current"]["raw"])
            self.assertTrue(obp["current"]["reason"])
            self.assertEqual(obp["interpretationStatus"]["value"],
                             "blocked_by_missing_data")
            # 這一列沒有被省略：三個 metric 都在
            self.assertEqual(len(group["metrics"]), 3)

    def test_rolling_distribution_is_present_for_recent_windows(self):
        for scope in ("RECENT_10", "RECENT_15"):
            group = next(g for g in section_groups(self.vm, 0)
                         if g["scope"] == scope)
            insight = self.payload["factual_insights"][group["insightId"]]
            by_metric = {e["metric"]: e for e
                         in insight["supporting_evidence"]["primary_metrics"]}
            for row in group["metrics"]:
                if not row["available"]:
                    continue
                self.assertIsNotNone(row["rolling"])
                src = by_metric[row["metric"]]["rolling_percentile"]
                # rank_desc 與 distribution_n 原樣引用，沒有重算
                self.assertEqual(row["rolling"]["rankDesc"], src["rank_desc"])
                self.assertEqual(row["rolling"]["distributionN"],
                                 src["distribution_n"])
                self.assertEqual(row["rolling"]["percentileRank"],
                                 src["percentile_rank"])


class TestContextualEvidence(FrontendRenderBase):
    """6. contextual_evidence 的 group 全部可呈現（合計 9 個 group）。"""

    def test_section_has_seven_groups(self):
        section = self.vm["sections"][1]
        self.assertEqual(section["sectionId"], "contextual_evidence")
        self.assertEqual(section["groupCount"], 7)
        self.assertEqual(section["candidateCount"], 25)
        self.assertEqual(sorted(section["scopes"]), sorted([
            "VS_CLOSER", "VS_DOMESTIC", "VS_FOREIGN", "VS_LEFT",
            "VS_RELIEF", "VS_RIGHT", "VS_STARTER",
        ]))

    def test_all_nine_groups_across_sections(self):
        scopes = [g["scope"] for i in (0, 1) for g in section_groups(self.vm, i)]
        self.assertEqual(len(scopes), 9)
        self.assertEqual(sorted(scopes), sorted(EXPECTED_SCOPES))

    def test_each_context_group_shows_three_metrics_with_all_fields(self):
        for group in section_groups(self.vm, 1):
            self.assertEqual(len(group["metrics"]), 3)
            for row in group["metrics"]:
                self.assertTrue(row["available"], f"{group['scope']} {row['metric']}")
                self.assertFalse(row["current"]["isNull"])
                self.assertFalse(row["baseline"]["isNull"])
                self.assertFalse(row["difference"]["isNull"])
                self.assertIn(row["direction"]["value"],
                              ("ABOVE", "BELOW", "EQUAL"))
                self.assertIsNotNone(row["sampleSize"])
                self.assertIsNotNone(row["sensitivity"])
                # 官方分項沒有時間維度：滾動分布為 null 並附原因
                self.assertIsNone(row["rolling"])
                self.assertTrue(row["rollingReason"])
                # 場次為 null 並附原因，不顯示 0
                self.assertTrue(row["sampleSize"]["games"]["isNull"])
                self.assertEqual(row["sampleSize"]["games"]["text"], NO_DATA)
                self.assertTrue(row["sampleSize"]["games"]["reason"])
            self.assertIsNotNone(group["dataStatus"]["application"]["value"])

    def test_pattern_is_summarised_not_duplicated_as_extra_metric_rows(self):
        with_pattern = 0
        for group in section_groups(self.vm, 1):
            insight = self.payload["factual_insights"][group["insightId"]]
            has_pattern = any(c.startswith("PATTERN-")
                              for c in insight["identity"]["candidate_ids"])
            # 無論有沒有 PATTERN，metric 列都只有 3 列
            self.assertEqual(len(group["metrics"]), 3, group["scope"])
            if has_pattern:
                with_pattern += 1
                cm = group["crossMetric"]
                self.assertTrue(cm["available"])
                self.assertTrue(cm["addsNoNewNumber"])
                self.assertEqual(len(cm["perMetric"]), 3)
                # 摘要文字裡沒有小數點，代表沒有新數值
                self.assertNotIn(".", cm["statement"].replace("。", ""))
            else:
                self.assertFalse(group["crossMetric"]["available"])
                self.assertTrue(group["crossMetric"]["reason"])
        self.assertEqual(with_pattern, 4)


class TestFactualInsights(FrontendRenderBase):
    """7. factual_insights 9 個全部可呈現。"""

    def test_nine_insights_in_api_order(self):
        self.assertEqual(len(self.vm["insights"]), 9)
        self.assertEqual([i["insightId"] for i in self.vm["insights"]],
                         list(self.payload["factual_insights"].keys()))

    def test_every_insight_exposes_required_fields(self):
        for insight in self.vm["insights"]:
            self.assertTrue(insight["scope"])
            self.assertTrue(insight["metrics"])
            self.assertIsNotNone(insight["dataStatus"]["evidence"]["value"])
            self.assertIsNotNone(insight["dataStatus"]["application"]["value"])
            self.assertTrue(insight["limitations"]["required"])
            self.assertTrue(insight["traceability"]["entries"])
            self.assertTrue(insight["interpretationStatus"]["label"])
            for row in insight["metrics"]:
                self.assertIn("current", row)
                self.assertIn("baseline", row)
                self.assertIn("difference", row)
                self.assertIn("direction", row)

    def test_no_insight_is_hidden_regardless_of_sample_size(self):
        with_ab = [i for i in self.vm["insights"]
                   if i["limitations"]["sample"]["atBats"]["raw"] is not None]
        smallest = min(with_ab,
                       key=lambda i: i["limitations"]["sample"]["atBats"]["raw"])
        # VS_CLOSER 只有 27 AB，仍然完整呈現
        self.assertEqual(smallest["scope"], "VS_CLOSER")
        self.assertEqual(len(smallest["metrics"]), 3)
        self.assertTrue(all(r["available"] for r in smallest["metrics"]))


class TestNullHandling(FrontendRenderBase):
    """8. null 不會顯示成 0。"""

    def test_no_cell_renders_null_as_zero_or_undefined(self):
        checked = 0
        for cell in iter_cells(self.vm):
            checked += 1
            if cell["isNull"]:
                self.assertIn(cell["text"], (NO_DATA, NOT_COMPUTABLE),
                              f"缺值顯示成 {cell['text']!r}")
                self.assertIsNone(cell["raw"])
            else:
                self.assertNotIn(cell["text"], ("undefined", "null", "NaN", ""))
        self.assertGreater(checked, 100)

    def test_no_undefined_or_nan_strings_anywhere(self):
        for text in iter_strings(self.vm):
            self.assertNotEqual(text, "undefined")
            self.assertNotEqual(text, "NaN")
            self.assertNotIn("NaN", text)

    def test_every_null_cell_that_has_a_reason_keeps_it(self):
        # 至少這些已知缺口必須帶原因
        hand = self.vm["nextGame"]["startingPitcherHand"]["hand"]
        self.assertTrue(hand["isNull"] and hand["reason"])
        for group in section_groups(self.vm, 1):
            for row in group["metrics"]:
                self.assertTrue(row["sampleSize"]["games"]["reason"])
                self.assertTrue(row["rollingReason"])


class TestDataStatusSeparation(FrontendRenderBase):
    """9. application_data_status 與 evidence_data_status 沒有混合。"""

    def test_two_statuses_are_separate_fields_in_every_group(self):
        for insight in self.vm["insights"]:
            ds = insight["dataStatus"]
            self.assertIn("evidence", ds)
            self.assertIn("application", ds)
            self.assertFalse(ds["merged"])
            self.assertTrue(ds["separationNote"])
            src = self.payload["factual_insights"][insight["insightId"]][
                "limitations"]["data_availability"]
            self.assertEqual(ds["evidence"]["value"],
                             src["evidence_data_status"])
            self.assertEqual(ds["application"]["value"],
                             src["application_data_status"])

    def test_evidence_stays_available_even_when_application_is_not(self):
        combos = {(i["dataStatus"]["evidence"]["value"],
                   i["dataStatus"]["application"]["value"])
                  for i in self.vm["insights"]}
        self.assertEqual(sorted({e for e, _ in combos}), ["available"])
        self.assertEqual(
            sorted({a for _, a in combos}),
            ["available", "not_investigated", "partially_available",
             "unavailable"])
        # 存在 evidence=available 但 application!=available 的組合
        self.assertIn(("available", "unavailable"), combos)
        self.assertIn(("available", "partially_available"), combos)
        self.assertIn(("available", "not_investigated"), combos)

    def test_status_table_keeps_two_columns(self):
        rows = self.vm["dataStatus"]["rows"]
        self.assertEqual(len(rows), 9)
        for row in rows:
            self.assertIn("evidence", row)
            self.assertIn("application", row)
        self.assertEqual(self.vm["dataStatus"]["distinctEvidenceValues"],
                         ["available"])
        self.assertEqual(len(self.vm["dataStatus"]["distinctApplicationValues"]),
                         4)
        self.assertTrue(self.vm["dataStatus"]["fieldsAreIndependent"])

    def test_missing_information_registry_is_explicit(self):
        ds = self.vm["dataStatus"]
        items = {e["item"]: e for e in ds["registry"]}
        self.assertEqual(sorted(items), [
            "in_game_pitcher_role_at_plate_appearance",
            "next_game_context",
            "next_starting_pitcher_hand",
            "next_starting_pitcher_registration_status",
        ])
        self.assertEqual(ds["gapCount"], 3)
        self.assertEqual(
            items["next_starting_pitcher_hand"]["statusLabel"],
            "尚未確認（部分驗證）")
        self.assertEqual(
            items["in_game_pitcher_role_at_plate_appearance"]["statusLabel"],
            "目前無法取得")
        self.assertEqual(
            items["next_starting_pitcher_registration_status"]["statusLabel"],
            "尚未調查")
        for entry in items.values():
            self.assertTrue(entry["factualBasis"])
            self.assertTrue(entry["affectedScopes"])
        self.assertEqual(ds["metricGapCount"], 2)
        for gap in ds["metricGaps"]:
            self.assertEqual(gap["display"], NOT_COMPUTABLE)
            self.assertTrue(gap["reason"])


class TestNoFrontendSorting(FrontendRenderBase):
    """10. frontend 沒有自行排序（用順序反轉的 mutation 反證）。"""

    def test_section_group_order_follows_payload_order(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        mutated["contextual_evidence"]["insight_refs"] = list(
            reversed(mutated["contextual_evidence"]["insight_refs"]))
        vm = run_render(mutated)
        expected = [r["scope"] for r in
                    mutated["contextual_evidence"]["insight_refs"]]
        self.assertEqual([g["scope"] for g in section_groups(vm, 1)],
                         expected)
        # 反轉後不等於字母序，證明前端沒有重新排序
        self.assertNotEqual(expected, sorted(expected))

    def test_insight_list_order_follows_payload_key_order(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        keys = list(mutated["factual_insights"].keys())
        mutated["factual_insights"] = {
            k: mutated["factual_insights"][k] for k in reversed(keys)
        }
        vm = run_render(mutated)
        self.assertEqual([i["insightId"] for i in vm["insights"]],
                         list(reversed(keys)))

    def test_metric_row_order_follows_payload_statement_order(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        insight_id = "INSIGHT-ZHANGYUCHENG-2026-A-VS_LEFT"
        statements = mutated["factual_insights"][insight_id]["phenomenon"][
            "statements"]
        mutated["factual_insights"][insight_id]["phenomenon"]["statements"] = \
            list(reversed(statements))
        vm = run_render(mutated)
        group = next(g for g in vm["insights"] if g["insightId"] == insight_id)
        self.assertEqual([r["metric"] for r in group["metrics"]],
                         ["slugging_percentage", "on_base_percentage",
                          "batting_average"])

    def test_source_contains_no_sort_call(self):
        for name in ("render.js", "app.js"):
            source = (WEB / name).read_text(encoding="utf-8")
            self.assertNotIn(".sort(", source, f"{name} 出現 .sort(")
            self.assertNotIn(".reverse(", source, f"{name} 出現 .reverse(")
            self.assertNotIn("localeCompare", source)


class TestNoFrontendComputation(FrontendRenderBase):
    """11. frontend 沒有自行計算 difference（用哨兵值 mutation 反證）。"""

    def test_difference_is_read_from_payload_not_recomputed(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        insight_id = "INSIGHT-ZHANGYUCHENG-2026-A-VS_LEFT"
        target = mutated["factual_insights"][insight_id][
            "supporting_evidence"]["primary_metrics"][0]
        sentinel = 0.12345678
        target["difference"] = sentinel
        vm = run_render(mutated)
        group = next(g for g in vm["insights"] if g["insightId"] == insight_id)
        row = next(r for r in group["metrics"] if r["metric"] == target["metric"])
        # 畫面上的差距等於哨兵值：證明是讀 payload，不是用 current - baseline 算的
        self.assertEqual(row["difference"]["raw"], sentinel)
        self.assertEqual(row["difference"]["text"], "+.123")

    def test_changing_current_value_does_not_change_difference(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        insight_id = "INSIGHT-ZHANGYUCHENG-2026-A-VS_RIGHT"
        target = mutated["factual_insights"][insight_id][
            "supporting_evidence"]["primary_metrics"][0]
        original_difference = target["difference"]
        target["current_value"] = 0.99999999
        vm = run_render(mutated)
        group = next(g for g in vm["insights"] if g["insightId"] == insight_id)
        row = next(r for r in group["metrics"] if r["metric"] == target["metric"])
        self.assertEqual(row["current"]["raw"], 0.99999999)
        # difference 沒有跟著變 -> 前端沒有重算
        self.assertEqual(row["difference"]["raw"], original_difference)

    def test_direction_is_read_from_payload_not_derived_from_sign(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        insight_id = "INSIGHT-ZHANGYUCHENG-2026-A-VS_STARTER"
        target = mutated["factual_insights"][insight_id][
            "supporting_evidence"]["primary_metrics"][0]
        target["difference"] = 0.5          # 正數
        target["direction"] = "BELOW"       # 但 payload 說 BELOW
        vm = run_render(mutated)
        group = next(g for g in vm["insights"] if g["insightId"] == insight_id)
        row = next(r for r in group["metrics"] if r["metric"] == target["metric"])
        self.assertEqual(row["direction"]["value"], "BELOW")
        self.assertEqual(row["direction"]["label"], "低於季累計")

    def test_sample_size_and_sensitivity_are_read_not_derived(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        insight_id = "INSIGHT-ZHANGYUCHENG-2026-A-VS_CLOSER"
        target = mutated["factual_insights"][insight_id][
            "supporting_evidence"]["primary_metrics"][0]
        target["sample_size"]["at_bats"] = 4242
        target["sensitivity"]["delta_if_one_more"] = 0.87654321
        vm = run_render(mutated)
        group = next(g for g in vm["insights"] if g["insightId"] == insight_id)
        row = next(r for r in group["metrics"] if r["metric"] == target["metric"])
        self.assertEqual(row["sampleSize"]["atBats"]["raw"], 4242)
        self.assertEqual(row["sensitivity"]["delta"]["raw"], 0.87654321)

    def test_baseline_is_read_from_payload(self):
        mutated = json.loads(json.dumps(self.payload, ensure_ascii=False))
        mutated["season_baseline"]["metrics"]["batting_average"]["value"] = 0.5
        vm = run_render(mutated)
        avg = next(m for m in vm["seasonBaseline"]["metrics"]
                   if m["metric"] == "batting_average")
        self.assertEqual(avg["value"]["raw"], 0.5)


class TestNoScoreRankingThreshold(FrontendRenderBase):
    """12. frontend 沒有建立 score / ranking / threshold。"""

    FORBIDDEN_FRAGMENTS = ("score", "weight", "threshold", "rank", "priority",
                           "importance", "confidence", "topn", "top_n",
                           "recommend", "predict")
    ALLOWED_KEYS = frozenset({
        "percentileRank", "percentileRankText", "percentileStrictText",
        "rankDesc", "percentile_rank", "rank_desc",
        "home_score", "visiting_score", "score_is_null_reason",
        "home_score_in_file", "visiting_score_in_file",
    })
    DECLARATIVE_KEYS = frozenset({
        "containsNo", "contains_no", "rule_not_inputs", "must_not_do",
        "forbidden", "createsScore", "createsRanking", "createsThreshold",
        "createsPriority", "createsTopN", "createsRecommendation",
        "createsPrediction",
    })

    def _scan(self, node, path=""):
        found = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key in self.ALLOWED_KEYS or key in self.DECLARATIVE_KEYS:
                    continue
                low = key.lower()
                for frag in self.FORBIDDEN_FRAGMENTS:
                    if frag in low:
                        found.append(f"{path}.{key}")
                found += self._scan(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                found += self._scan(value, f"{path}[{i}]")
        return found

    def test_view_model_has_no_score_or_ranking_fields(self):
        leaks = self._scan(self.vm)
        self.assertEqual(leaks, [], f"view model 出現禁用欄位：{leaks[:5]}")

    def test_frontend_guards_declare_nothing_is_created(self):
        guards = self.vm["frontendGuards"]
        for key in ("sorted", "filtered", "recomputed", "createsScore",
                    "createsRanking", "createsThreshold", "createsPriority",
                    "createsTopN", "createsRecommendation", "createsPrediction",
                    "mergesDataStatus", "treatsNullAsZero",
                    "usesBrowserClockForDataDate", "usesLlm",
                    "readsLocalDataDirectory"):
            self.assertFalse(guards[key], key)
        self.assertEqual(guards["orderSource"], "api_payload_order")
        self.assertEqual(guards["numberHandling"], "display_formatting_only")

    def test_sections_hold_references_only_no_duplicated_numbers(self):
        """section 不得複製數值，否則同一組數字在 view model 出現兩次。

        這正是第一次執行時被判斷性字眼掃描抓到的問題：API 原文被計數兩次。
        """
        for index in (0, 1):
            section = self.vm["sections"][index]
            self.assertIn("groupRefs", section)
            self.assertNotIn("groups", section)
            self.assertTrue(section["holdsReferencesOnly"])
            blob = json.dumps(section, ensure_ascii=False)
            for insight in self.vm["insights"]:
                for row in insight["metrics"]:
                    if row["current"]["full"]:
                        self.assertNotIn(row["current"]["full"], blob)
            for ref in section["groupRefs"]:
                target = self.vm["insights"][ref["insightIndex"]]
                self.assertEqual(target["insightId"], ref["insightId"])
                self.assertEqual(target["scope"], ref["scope"])
        self.assertFalse(self.vm["frontendGuards"]["duplicatesNumbers"])
        self.assertEqual(self.vm["frontendGuards"]["singleSourceOfNumbers"],
                         "insights")

    def test_no_group_is_filtered_out(self):
        rendered = {g["scope"] for i in (0, 1)
                    for g in section_groups(self.vm, i)}
        self.assertEqual(rendered, set(EXPECTED_SCOPES))
        listed = {i["scope"] for i in self.vm["insights"]}
        self.assertEqual(listed, set(EXPECTED_SCOPES))

    def test_frontend_introduces_no_judgement_words(self):
        """任何判斷性字眼都必須是 API 原文，前端不得自己新增。

        API 的說明文字本身就含否定宣告（例如 Step 10 的
        「方向判定不含任何最小差距門檻」），所以掃描時要扣掉 payload 裡本來就有
        的出現次數。剩下的正數才是前端自己加的。
        """
        judgement = ("優勢", "劣勢", "強項", "弱點", "很好", "很差", "值得注意",
                     "建議", "推薦", "應該", "預測", "最佳", "最好", "最差",
                     "擅長", "排名", "評分", "分數", "門檻", "厲害", "危險")
        declared = json.dumps({
            "guards": self.vm["frontendGuards"],
            "containsNo": self.vm["meta"]["containsNo"],
            "consumerContract": self.vm["meta"]["consumerContract"],
            "nullPolicy": self.vm["dataStatus"]["nullPolicy"],
        }, ensure_ascii=False)
        rendered = json.dumps(self.vm, ensure_ascii=False)
        from_api = json.dumps(self.payload, ensure_ascii=False)
        hits = []
        for word in judgement:
            introduced = (rendered.count(word)
                          - from_api.count(word)
                          - declared.count(word))
            if introduced > 0:
                hits.append(f"{word}×{introduced}")
        self.assertEqual(hits, [], f"前端自行新增了判斷性字眼：{hits}")

    def test_direction_labels_are_neutral_restatements(self):
        """方向標籤只能是「高於／低於／相同」，不能變成強弱好壞。"""
        allowed = {"高於季累計", "低於季累計", "與季累計相同", NO_DATA}
        seen = set()
        for insight in self.vm["insights"]:
            for row in insight["metrics"]:
                seen.add(row["direction"]["label"])
        self.assertTrue(seen.issubset(allowed), f"出現非中性方向標籤：{seen - allowed}")
        self.assertIn("高於季累計", seen)
        self.assertIn("低於季累計", seen)


class TestErrorStates(FrontendRenderBase):
    """13. API error state 可以呈現。"""

    def test_404_error_view_model(self):
        _, body = api.dispatch("GET", "/api/player/nobody")
        vm = run_error_render("not_found", body)
        self.assertEqual(vm["code"], "player_not_found")
        self.assertEqual(vm["httpStatus"], 404)
        self.assertTrue(vm["title"])
        self.assertTrue(vm["message"])
        self.assertEqual(vm["requestedPlayerSlug"], "nobody")
        self.assertEqual(vm["availablePlayerSlugs"], ["zhang-yucheng"])

    def test_400_error_view_model(self):
        _, body = api.dispatch("GET", "/api/player")
        vm = run_error_render("bad_request", body)
        self.assertEqual(vm["code"], "player_slug_required")
        self.assertEqual(vm["httpStatus"], 400)

    def test_500_error_view_model_hides_internals(self):
        body = {
            "error": {
                "code": "product_output_generation_failed",
                "http_status": 500,
                "message": "產生產品輸出時發生內部錯誤。",
                "player_slug": "zhang-yucheng",
                "detail_disclosed": False,
                "detail_note": "錯誤細節只記錄在伺服器端日誌，不隨回應輸出。",
            }
        }
        vm = run_error_render("server_error", body)
        self.assertEqual(vm["code"], "product_output_generation_failed")
        self.assertEqual(vm["httpStatus"], 500)
        self.assertFalse(vm["detailDisclosed"])
        blob = json.dumps(vm, ensure_ascii=False)
        self.assertNotIn("Traceback", blob)
        self.assertNotIn(".py", blob)

    def test_network_error_view_model_has_actionable_hint(self):
        vm = run_error_render("network", None)
        self.assertEqual(vm["kind"], "network")
        self.assertTrue(vm["title"])
        self.assertIn("src/api.py", vm["hint"])
        self.assertIsNone(vm["code"])

    def test_error_view_model_never_contains_undefined(self):
        for kind in ("network", "not_found", "bad_request", "server_error",
                     "unexpected"):
            vm = run_error_render(kind, None)
            for text in iter_strings(vm):
                self.assertNotEqual(text, "undefined")
                self.assertNotIn("NaN", text)


class TestFrontendStaticInspection(unittest.TestCase):
    """14 / 15. 不直接讀 data/、不修改 Step 5~23。這些檢查不需要 node。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {
            name: (WEB / name).read_text(encoding="utf-8")
            for name in FRONTEND_FILES
        }
        cls.literals = {
            name: string_literals(source)
            for name, source in cls.sources.items()
        }
        cls.hashes_before = {p: sha256_of(p) for p in SOURCE_PATHS}

    def test_all_frontend_files_exist(self):
        for name in FRONTEND_FILES:
            self.assertTrue((WEB / name).exists(), name)
        self.assertTrue(BRIDGE.exists())

    def test_frontend_never_references_local_data_directories(self):
        """只掃字串常值與 HTML 屬性，不掃註解。

        註解裡本來就寫著「不讀 data/processed」這種否定宣告，掃全文會自我命中。
        真正要檢查的是程式**實際使用**的路徑，也就是字串常值。
        """
        banned = ("data/processed", "data/raw", "../data/",
                  "candidate_insights", "product_output_model",
                  "insight_assembly", "insight_chain")
        for name in ("render.js", "app.js"):
            for literal in self.literals[name]:
                for token in banned:
                    self.assertNotIn(token, literal,
                                     f"{name} 的字串常值引用了 {token}")
        html = self.sources["index.html"]
        for token in banned:
            self.assertNotIn(f'"{token}', html)
            self.assertNotIn(f"./{token}", html)

    def test_frontend_only_talks_to_the_api_endpoint(self):
        urls = []
        for name in ("render.js", "app.js"):
            for literal in self.literals[name]:
                urls.extend(re.findall(r"https?://[^\s'\"`]+", literal))
        self.assertTrue(urls, "找不到任何 URL 字串常值")
        # 只允許本機 API base，其餘 URL 一律不得出現
        for url in urls:
            self.assertTrue(url.startswith("http://127.0.0.1"),
                            f"出現非本機 URL：{url}")
        # 只呼叫 /api/player/{slug} 這一條路徑
        paths = set()
        for literal in self.literals["app.js"]:
            paths.update(re.findall(r"/api/[a-zA-Z0-9/_${}\-]+", literal))
        self.assertEqual(paths, {"/api/player/${PLAYER_SLUG}"})

    def test_frontend_does_not_use_browser_clock_for_data_date(self):
        for name in ("render.js", "app.js"):
            source = self.sources[name]
            for banned in ("Date.now(", "new Date(", "toLocaleDateString",
                           "Date.parse(", "performance.now("):
                self.assertNotIn(banned, source, f"{name} 使用了 {banned}")

    def test_frontend_has_no_llm_or_extra_dependency(self):
        for name in self.sources:
            for literal in self.literals[name]:
                low = literal.lower()
                for banned in ("openai", "anthropic", "cdn.jsdelivr",
                               "unpkg.com", "cdnjs", "googleapis",
                               "esm.sh", "skypack"):
                    self.assertNotIn(banned, low, f"{name} 引用了 {banned}")
        html = self.sources["index.html"].lower()
        for banned in ("openai", "cdn.", "unpkg", "googleapis"):
            self.assertNotIn(banned, html)
        # 只從相對路徑 import，沒有任何套件名
        imports = re.findall(r"^import[^;]*from\s+'([^']+)'",
                             self.sources["app.js"], re.M)
        self.assertTrue(imports)
        for spec in imports:
            self.assertTrue(spec.startswith("./") or spec.startswith("../"),
                            f"app.js 匯入了非相對路徑：{spec}")

    def test_no_package_manifest_was_added(self):
        for name in ("package.json", "package-lock.json", "yarn.lock",
                     "pnpm-lock.yaml", "node_modules"):
            self.assertFalse((ROOT / name).exists(), f"{name} 被新增了")
            self.assertFalse((WEB / name).exists(), f"web/{name} 被新增了")

    def test_requirements_txt_has_no_dependency(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        self.assertEqual(lines, [], f"requirements.txt 出現依賴：{lines}")

    def test_static_server_is_rooted_at_web_only(self):
        source = self.sources["serve.py"]
        self.assertIn("WEB_ROOT = Path(__file__).resolve().parent", source)
        self.assertIn("relative_to(WEB_ROOT)", source)
        self.assertIn("directory=str(WEB_ROOT)", source)
        # 靜態伺服器不 import 任何後端模組，也不碰 data/
        self.assertNotIn("import api", source)
        for literal in self.literals["serve.py"]:
            for token in ("data/raw", "data/processed", ".."):
                self.assertNotIn(token, literal,
                                 f"serve.py 的字串常值出現 {token}")

    def test_step_5_to_23_python_sources_are_untouched_by_frontend(self):
        # 前端目錄不含任何 .py 以外的後端邏輯，也不 import backend 模組
        py_files = sorted(p.name for p in WEB.rglob("*.py"))
        self.assertEqual(py_files, ["serve.py"])
        self.assertNotIn("sys.path", self.sources["serve.py"])

    def test_source_data_unchanged(self):
        for path, before in self.hashes_before.items():
            self.assertEqual(sha256_of(path), before, path.name)


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

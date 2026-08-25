# Insight Assembly Experiment（Step 21）

程式：`src/insight_assembly.py`
執行：`python src/insight_assembly.py`
Validation：**22 / 22 PASS，0 FAIL**
Mutation test：6 次完整重跑，簽章改變 0 次

---

## 0. 這一步做什麼、不做什麼

把 Step 20 的 9 個 presentation record 組裝成 **可閱讀但仍完全可追溯** 的
insight object。輸入固定，不新增 candidate、不新增 group、不新增任何數值。

**不做**：UI、React / Flask / FastAPI / dashboard、score、weight、threshold、
ranking、priority、Top-N、prediction、recommendation、strategy、LLM、HTTP request。

輸出只印在螢幕，不寫入 `data/`。所有記錄都是 sidecar，用 `group_id` 關聯，
不寫回 group、candidate 或 presentation record。

輸出順序依 `scope` 字母排列，只為了 deterministic 與可比對。
物件裡明確記錄 `ordering.is_not`：這不是 ranking、不是 priority、不是 Top-N。

---

## 1. 什麼叫做 factual insight

`phenomenon` 只允許由這 8 個欄位組成，沒有任何形容詞欄位：

`scope`、`metric`、`current_value`、`baseline_value`、`difference`、
`direction`、`sample_size`、`window_or_split`

`direction` 只能是 Step 9 已定義的三個值 `ABOVE` / `BELOW` / `EQUAL`
（`src/candidate_insights.py` 的 `direction_of`），不是「好 / 壞」。

實際產出的第一段 statement：

```
RECENT_10：batting_average = 0.40476190；2026 季累計 baseline = 0.31135531；
difference = +0.09340659；direction = ABOVE；window = 10 場實際出賽；
sample = 42 AB / 44 PA / 10 場。
```

本次共 **31 段 statement**（25 段 `numeric_fact`、2 段 `explicit_null`、
4 段 `direction_summary`）。

驗證對這 31 段文字做 **嚴格字眼掃描**：50 個禁用字眼、**不扣除任何宣告性欄位**，
共 1550 次比對，**命中 0 次**。

禁用字眼包含 好 / 壞 / 強 / 弱 / 優 / 劣 / 佳 / 差 / 提升 / 下降 / 進步 /
退步 / 值得 / 應該 / 建議 / 預測 / 推薦 / 策略 / 最 / 擅長 / 熱 / 冷 /
改善 / 惡化 / 厲害 / 危險 / 問題，以及 good / bad / strong / weak / better /
worse / best / worst / should / advantage / disadvantage / improve / decline /
hot / cold / recommend / predict / strategy / notable / noteworthy / significant。

> 為什麼要「不扣除宣告性欄位」：Step 19 與 Step 20 的全文掃描必須扣除
> `contains_no`、`is_not` 這類否定宣告，否則否定宣告本身會命中禁用清單。
> 但 phenomenon 文字裡本來就不該有任何宣告性內容，所以這裡刻意用最嚴格的版本。
> 全文（含所有說明欄位）另有一道扣除宣告性欄位的掃描，是第 11 項檢查。

---

## 2. 9 個 assembled insight 總覽

| scope | interpretation_status | 主要 metric | evidence 種類 | missing_count | null slot |
| --- | --- | ---: | ---: | ---: | --- |
| `RECENT_10` | `factual_with_context` | 2 | 5 | 0 | OBP |
| `RECENT_15` | `factual_with_context` | 2 | 5 | 0 | OBP |
| `VS_CLOSER` | `factual_only` | 3 | 5 | 1 | — |
| `VS_DOMESTIC` | `factual_only` | 3 | 5 | 1 | — |
| `VS_FOREIGN` | `factual_only` | 3 | 5 | 1 | — |
| `VS_LEFT` | `factual_only` | 3 | 4 | 1 | — |
| `VS_RELIEF` | `factual_only` | 3 | 4 | 1 | — |
| `VS_RIGHT` | `factual_only` | 3 | 4 | 1 | — |
| `VS_STARTER` | `factual_only` | 3 | 5 | 1 | — |

9 個 insight × 6 個指定區塊全部存在，`insight_id` 與 `group_id` 一對一，
29 個 candidate 的 membership 與 Step 18 完全相同。

---

## 3. 一個 insight 如何由多個 evidence 組成

`supporting_evidence.evidence_kinds` 使用受控詞彙，7 個值：

| kind | 來源 | 出現在 |
| --- | --- | --- |
| `metric_vs_season_baseline` | Step 9 | 9 個 |
| `sample_size_counts` | Step 11 | 9 個 |
| `single_event_sensitivity` | Step 11 | 9 個 |
| `rolling_distribution_position` | Step 6 | 2 個（RECENT_10 / 15） |
| `game_level_traceability` | Step 4 / 5 | 2 個（RECENT_10 / 15） |
| `official_split_definition` | Step 8 | 7 個（VS_*） |
| `cross_metric_direction` | Step 9 PATTERN | 4 個（CLOSER / DOMESTIC / FOREIGN / STARTER） |

每一項獨立記錄，**不合成任何綜合值**。沒有把「5 種 evidence」變成
「evidence 強度 5 分」這種東西。

`VS_LEFT` / `VS_RIGHT` / `VS_RELIEF` 只有 4 種，因為 Step 9 沒有為這三個
context 建立 3/3 的 `MULTI_METRIC_PATTERN`（三個指標方向不一致）。
這是既有事實，不是本階段的篩選。

### RECENT_10 的組成範例

| evidence | 內容 |
| --- | --- |
| metric vs baseline | AVG `0.40476190` vs `0.31135531`，difference `+0.09340659`，ABOVE |
| | SLG `0.61904762` vs `0.53113553`，difference `+0.08791209`，ABOVE |
| sample counts | 42 AB / 44 PA / 10 場（Step 11） |
| single event sensitivity | AVG 17/42，加一支 `0.42857143`、少一支 `0.38095238`，delta `0.02380952` |
| rolling distribution | AVG rank 5 / 68，percentile_rank 94.1176；SLG rank 20 / 68，72.0588（Step 6） |
| game level traceability | game_snos 10 場 `[240, 242, 244, 249, 260, 261, 262, 265, 269, 272]`，2026-08-02 ~ 2026-08-18 |

---

## 4. 如何避免從數字跳到結論

四道機制，全部有對應驗證：

**(a) phenomenon 用固定 template 生成。** 沒有形容詞欄位可填，
`statement_rule.template_fields` 明確列出 8 個允許欄位。

**(b) `interpretation_status` 標出陳述邊界。** 這是本階段新增的受控欄位（見第 6 節）。

**(c) `context` 只說「連到哪一類決策」。** `possible_decision_area` 與
`possible_action_link` 原樣引用 Step 19，不說決策內容。物件裡有
`context.is_not`：「不是決策本身，也不是對下一場的任何投射。」

**(d) 嚴格字眼掃描。** 見第 1 節。

### 特別處理（對應本次指示 A ~ E）

| 指示 | 處理方式 | 實際結果 |
| --- | --- | --- |
| **A. RECENT_10 / 15 的 OBP 保持 null** | OBP slot 產生 `explicit_null` statement，值為 `null`，附原因 | 2 個 slot，`interpretation_status = blocked_by_missing_data` |
| **B. VS_CLOSER / STARTER / RELIEF 不假裝有 game-level 或 recent 資訊** | `rolling_percentile = null` + 原因；`game_snos = null` + 原因；`limitations.temporal_limitation` 明文記錄；`interpretation_status = factual_only` | 7 個 VS_* group 全部如此 |
| **C. VS_LEFT / RIGHT 不能變成對下一場的預測** | `limitations.not_a_next_game_projection` 明文宣告；缺口 `next_starting_pitcher_hand` 保留為 `partially_available` | statement 只有季累計數字，無任何投射欄位 |
| **D. VS_DOMESTIC / FOREIGN 的本土／外籍 dependency 未調查，不填補** | `application_data_status = not_investigated`，`missing_for_application` 列出 `next_starting_pitcher_registration_status` | 2 個 group |
| **E. PATTERN 不建立新數值** | 只保留 `direction_per_metric` 與 `consistency_count`，摘要文字**不含任何小數點** | 4 個 PATTERN，12 次 difference 比對全部等於同 insight 既有 evidence |

`VS_CLOSER` 的 PATTERN 摘要實際長這樣，沒有任何新數字：

```
VS_CLOSER：三個指標與 2026 季累計比較的 direction 為
AVG = BELOW、OBP = BELOW、SLG = BELOW；相同 direction 計數 3/3。
```

---

## 5. 9 個 insight 的 phenomenon 數值

### Perspective A — Current Form

| scope | metric | current | baseline | difference | direction | rolling |
| --- | --- | ---: | ---: | ---: | --- | --- |
| RECENT_10 | AVG | 0.40476190 | 0.31135531 | +0.09340659 | ABOVE | 5 / 68（94.1176） |
| RECENT_10 | OBP | **null** | — | — | — | — |
| RECENT_10 | SLG | 0.61904762 | 0.53113553 | +0.08791209 | ABOVE | 20 / 68（72.0588） |
| RECENT_15 | AVG | 0.32758621 | 0.31135531 | +0.01623090 | ABOVE | 25 / 63（61.9048） |
| RECENT_15 | OBP | **null** | — | — | — | — |
| RECENT_15 | SLG | 0.50000000 | 0.53113553 | -0.03113553 | BELOW | 35 / 63（46.0317） |

### Perspective B — Matchup Context（全部季累計，全部無 rolling、無 game_snos）

| scope | 官方分項 | AVG | OBP | SLG | AB / PA | PATTERN |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| VS_LEFT | VS. 左投 | 0.31481481 | 0.40322581 | 0.42592593 | 54 / 62 | — |
| VS_RIGHT | VS. 右投 | 0.31050228 | 0.40310078 | 0.55707763 | 219 / 258 | — |
| VS_STARTER | VS. 先發 | 0.33888889 | 0.42583732 | 0.56666667 | 180 / 209 | 3/3 ABOVE |
| VS_RELIEF | VS. 中繼 | 0.30303030 | 0.40000000 | 0.59090909 | 66 / 80 | — |
| VS_CLOSER | VS. 救援 | 0.14814815 | 0.25806452 | 0.14814815 | 27 / 31 | 3/3 BELOW |
| VS_DOMESTIC | VS. 本土投手 | 0.28901734 | 0.37623762 | 0.49710983 | 173 / 202 | 3/3 BELOW |
| VS_FOREIGN | VS. 外籍投手 | 0.35000000 | 0.44915254 | 0.59000000 | 100 / 118 | 3/3 ABOVE |

baseline 一律是同一組季累計值：AVG `0.31135531`、OBP `0.40312500`、
SLG `0.53113553`（77 場 / 320 PA / 273 AB）。

---

## 6. `interpretation_status`：本階段新增的最小詞彙

指示說「如果 vocabulary 已存在就沿用」。全專案（Step 9 ~ 20）grep
`interpretation_status`、`factual_only`、`factual_with_context`、
`blocked_by_missing_data`，**全部 0 命中**。三個既有欄位都不回答同一個問題：

| 既有欄位 | 回答的問題 |
| --- | --- |
| Step 11 `sample_context` | 樣本規模多大 |
| Step 19 `data_availability` | 應用所需的外部資料拿不拿得到 |
| Step 20 `evidence_data_status` | evidence 數值是否存在 |

都不回答「**這個數字可以被陳述到什麼程度**」。因此新增這個欄位，
只有指示給的 3 個值，沒有擴充。

### 判定規則（純結構性）

```
metric 值不存在                                  -> blocked_by_missing_data
有 rolling distribution 且有 game_snos           -> factual_with_context
其餘                                             -> factual_only
```

`rule_inputs` 只有 3 項：`has_rolling_distribution`、
`has_game_level_traceability`、`metric_value_exists`。

`rule_not_inputs` 明確列出 7 個**未使用**的量：`magnitude`、
`sample_size_at_bats`、`plate_appearances`、`percentile_rank`、
`consistency_count`、`classification`、`noteworthy_classification`。

insight 層級取所有 present slot 的狀態聚合，**一致才成立**；不一致就設為
`null` 並記錄 `conflict`，不強行合併（沿用 Step 19 `aggregate_group` 的做法）。
blocked slot 不影響 insight 層級狀態，另記於 `limitations`。

### 實際分佈

| 值 | insight 層級 | metric slot 層級 |
| --- | ---: | ---: |
| `factual_only` | 7（7 個 VS_*） | 21 |
| `factual_with_context` | 2（RECENT_10 / 15） | 4 |
| `blocked_by_missing_data` | 0 | 2（RECENT_10 / 15 的 OBP） |

三個值都真的用到（slot 層級），沒有一個是空詞彙。這個欄位也直接編碼了
指示 B：7 個 VS_* insight 的 `factual_only` 就是「不假裝具有 game-level
或 recent temporal information」的機器可讀形式。

---

## 7. 如何處理 sample size

sample size 出現在三個地方，**都不用來篩選、淘汰或隱藏**：

1. `phenomenon.statements` 的文字裡（`sample = 42 AB / 44 PA / 10 場`）
2. `supporting_evidence.primary_metrics[].sample_size`
3. `limitations.sample_limitation`

| scope | AB | PA | games | AVG 單一事件 delta |
| --- | ---: | ---: | ---: | ---: |
| RECENT_10 | 42 | 44 | 10 | 0.023810 |
| RECENT_15 | 58 | 63 | 15 | 0.017241 |
| VS_CLOSER | 27 | 31 | **null** | 0.037037 |
| VS_DOMESTIC | 173 | 202 | **null** | 0.005780 |
| VS_FOREIGN | 100 | 118 | **null** | 0.010000 |
| VS_LEFT | 54 | 62 | **null** | 0.018519 |
| VS_RELIEF | 66 | 80 | **null** | 0.015152 |
| VS_RIGHT | 219 | 258 | **null** | 0.004566 |
| VS_STARTER | 180 | 209 | **null** | 0.005556 |

`games = null` 的 7 個 group 都附原因：官方分項成績沒有出賽場次欄位，不推估。

`sample_limitation.is_not_a_filter` 明文記錄：sample size 只描述樣本規模，
本專案不用它淘汰或隱藏任何 insight。

`single_event_delta` 讓使用者自己看得到樣本的算術脆弱度：VS_CLOSER 27 AB
時多一支安打 AVG 移動 0.037，VS_RIGHT 219 AB 時只移動 0.0046。
`sensitivity.is_not` 同時宣告：「這是算術上的敏感度描述，不是可信程度。」

Mutation test 把 AB 改成 1 與 9999，規則簽章不變——證明 sample size 沒有
參與任何結構決定。

---

## 8. 如何處理 missing data

缺口分兩層，都是一級資訊。

### 8.1 metric 層：值不存在

RECENT_10 / RECENT_15 的 OBP 沒有值。做法是產生一段
`explicit_null` statement，而不是省略這個 metric：

```
RECENT_10：on_base_percentage = null（沒有可陳述的數值）。
原因：processed data 未收逐場犧牲飛球，TREND 窗口無法計算 OBP（Step 5 / Step 11 已記錄）
```

同時 `limitations.unavailable_metrics` 記錄 metric 名稱、count、reason，
以及 `value_policy`：「值保持 null，不以任何方式估算或填補。」
`interpretation_status.by_metric` 對應 `blocked_by_missing_data`。

### 8.2 應用層：要用於下一場還缺什麼

原樣引用 Step 20 的 `missing_information`，逐欄位相同：

| scope | application_data_status | required_additional_data | missing_count |
| --- | --- | --- | ---: |
| RECENT_10 / RECENT_15 | `available` | `next_game_context` | **0** |
| VS_LEFT / VS_RIGHT | `partially_available` | `next_starting_pitcher_hand` | 1 |
| VS_STARTER / VS_RELIEF / VS_CLOSER | `unavailable` | `in_game_pitcher_role_at_plate_appearance` | 1 |
| VS_DOMESTIC / VS_FOREIGN | `not_investigated` | `next_starting_pitcher_registration_status` | 1 |

9 筆 `required_additional_data` 全部保留（含 RECENT_* 那 2 筆已解決的），
其中 7 筆列為缺口。每一筆都帶 `status`、`availability_source_step`、
`evidence_steps`、`factual_basis`。

`no_guessing_note` 原樣沿用：缺失的資料一律不猜測、不填補。

### 8.3 為什麼缺口不會被誤讀成「沒問題」

Step 20 的三段區分完整保留在 insight object 裡，沒有被壓成 boolean：

| 區分 | 在 insight 裡的位置 |
| --- | --- |
| A. evidence 本身是否完整 | `supporting_evidence` + `interpretation_status` |
| B. 是否可直接用於下一場決策 | `context.application_dependency` |
| C. 還缺什麼資料 | `limitations.missing_data` |

`limitations.data_availability` 也同時保留兩個狀態：9 個 insight 的
`evidence_data_status` 全是 `available`，`application_data_status` 有 4 種值。

---

## 9. 如何保持完整 traceability

每個主要數字都有一筆 `traceability.by_metric[metric]` 記錄，共 **25 筆**：

| 欄位 | TREND（4 筆） | CONTEXT（21 筆） |
| --- | --- | --- |
| `source_step_ids` | Step 5 / 6 / 9 / 11 | Step 8 / 9 / 11 |
| `source_file` | `data/processed/zhang_yucheng_game_logs_2026.json` | `data/raw/apart_score_0000006888_2026_A_01.json` |
| `source_field` | `processed_fields` + `raw_api_fields` + `field_map_reference` | `official_item_name` + `raw_api_fields` + `field_map_reference` |
| `derivation` | `hits / at_bats`、`total_bases / at_bats` | 同上 + OBP 公式 |
| `game_snos` | 10 / 15 場清單 + date_range | **null** + 明確原因 |

實際內容範例（RECENT_15 AVG 與 VS_CLOSER OBP）：

```
AVG: step=['Step 5', 'Step 6', 'Step 9', 'Step 11']
     file       = data/processed/zhang_yucheng_game_logs_2026.json
     field      = {'processed_fields': ['hits', 'at_bats'],
                   'raw_api_fields': ['HittingCnt', 'HitCnt'],
                   'field_map_reference': 'src/build_processed_data.py'}
     derivation = hits / at_bats
     game_snos  = 15 場 [225, 226, 228, 232, 236, 240, 242, 244, 249,
                         260, 261, 262, 265, 269, 272]
     date_range = 2026-07-26 ~ 2026-08-18

OBP: step=['Step 8', 'Step 9', 'Step 11']
     file       = data/raw/apart_score_0000006888_2026_A_01.json
     field      = {'official_item_name': 'VS. 救援',
                   'raw_api_fields': ['HittingCnt', 'BasesONBallsCnt',
                                      'HitBYPitchCnt', 'HitCnt', 'SacrificeFlyCnt'],
                   'field_map_reference': 'src/context_splits.py FIELD_MAP'}
     derivation = (hits + walks + hit_by_pitch)
                  / (at_bats + walks + hit_by_pitch + sacrifice_flies)
     game_snos  = null　原因：官方分項不提供日期或場次，無法追溯到個別比賽（Step 8）
```

驗證逐筆確認：5 個必填欄位都非空、引用的檔案在 repo 裡真的存在、
`derivation` 與 Step 9 `calculation_reference.formula` 逐字相同、
21 筆 `game_snos = null` 全部附原因。

`traceability.step_chain` 另記完整 12 段鏈路：
Step 2/3 → 4 → 5 → 6 → 8 → 9 → 11 → 13 → 18 → 19 → 20 → 21。

---

## 10. Insight object 結構

| 區塊 | 主要欄位 |
| --- | --- |
| 1. `identity` | `insight_id`、`group_id`、`perspective`、`perspective_name`、`scope`、`candidate_ids`、`candidate_count`、`subject` |
| 2. `phenomenon` | `statements[]`（`statement`、`statement_kind`、4 個數值欄位、`interpretation_status`）、`cross_metric_statement`、`statement_rule` |
| 3. `supporting_evidence` | `primary_metrics[]`（current / baseline / difference / direction / `sample_size` / `sensitivity` / `rolling_percentile` / `evidence_kinds`）、`metrics_present`、`metrics_unavailable` |
| 4. `context` | `contextual_relevance`、`temporal_relevance`、`next_game_dependency`、`application_dependency`、`possible_decision_area`、`possible_action_link` |
| 5. `limitations` | `sample_limitation`、`missing_data`、`unavailable_metrics`、`data_availability`、`temporal_limitation`、`not_a_next_game_projection` |
| 6. `traceability` | `by_metric{}`、`cross_metric_source`、`step_chain`、`source_files` |
| — | `interpretation_status`、`assembly_rule`、`provenance`、`contains_no` |

`statement_kind` 受控 3 值：`numeric_fact`、`explicit_null`、`direction_summary`。

---

## 11. Mutation test

6 次完整重跑，**簽章改變 0 次、禁用欄位洩漏 0 次、詞彙外狀態 0 次**。

比對用兩種簽章，因為兩類變異的期望不同：

| 變異 | 比對對象 | 期望 | 結果 |
| --- | --- | --- | --- |
| `magnitude = 0.0` | 規則簽章（不含數值） | 不變 | 不變 |
| `magnitude = 999.0` | 規則簽章 | 不變 | 不變 |
| `at_bats = 1` | 規則簽章 | 不變 | 不變 |
| `at_bats = 9999` | 規則簽章 | 不變 | 不變 |
| `classification` 全部翻轉 | **完整輸出** | 逐位元相同 | 相同 |
| candidate 順序反轉 | **完整輸出** | 逐位元相同 | 相同 |

**為什麼 magnitude / AB 只比對規則簽章**：那兩個是資料值，
phenomenon 裡的數字本來就該跟著資料變——那正是「數字來自資料」的意思。
不該變的是**結構與規則**。規則簽章包含：`insight_id`、`group_id`、
`candidate_ids`、完整巢狀欄位路徑集合、`interpretation_status`（含 by_metric）、
`metrics_present` / `metrics_unavailable`、`evidence_kinds`、
`statement_kinds`、是否有 cross_metric、整個 `context` 區塊、
`missing_items` / `required_items`、`application_data_status`、`assembly_rule`。

**為什麼 classification / 順序要求逐位元相同**：這兩個變異不帶任何資料變化，
所以輸出必須完全一樣。這正面反證了組裝與 Step 17-7 的
noteworthy / observation 分類無關，也與輸入順序無關。

每個 mutant 另外重跑禁用欄位掃描與詞彙檢查，確認變異後沒有冒出
`score` / `weight` / `priority` / `rank` 欄位，也沒有跑出詞彙外的
`interpretation_status`。

---

## 12. Validation：22 / 22 PASS

| # | 檢查 | 結果 | 依據 |
| ---: | --- | --- | --- |
| 1 | 9 個 group 全部產生 insight | PASS | insight 9 = group 9，scope 集合相同 |
| 2 | 一個 group 只有一個 assembled insight | PASS | `insight_id` 唯一 9、`group_id` 唯一 9，一對一 |
| 3 | 每個 metric 都能追溯到 step / file / field / formula | PASS | 25 筆追溯記錄；檔案存在；formula 與 Step 9 逐字相同 |
| 4 | phenomenon 數值與文字都與 Step 20 一致 | PASS | 25 段 statement × 4 欄位；數字以 8 位小數原樣寫入文字 |
| 5 | sample context 與 sensitivity 與 Step 11 一致 | PASS | 25 個 metric 逐欄位相符 |
| 6 | context / decision relevance 與 Step 19 一致 | PASS | 9 × 10 = 90 次比對 |
| 7 | candidate membership 與 Step 18 一致 | PASS | 總數 29 = 29 |
| 8 | PATTERN 沒有新增任何數值 | PASS | 4 個 PATTERN；摘要文字無小數；12 次 difference 比對 |
| 9 | 沒有 score / weight / threshold / ranking / priority / importance / confidence / Top-N | PASS | 遞迴欄位名掃描 + 9 個字眼掃描 |
| 10 | phenomenon 文字無價值判斷（嚴格掃描） | PASS | 31 × 50 = 1550 次比對，命中 0 |
| 11 | 不產生 recommendation / prediction / strategy | PASS | 全文 20 字眼，扣除宣告性欄位後 0 |
| 12 | 沒有修改 candidate | PASS | 深度比較 29 個物件 |
| 13 | 沒有修改 Step 18 grouping | PASS | 深度比較 9 個物件 |
| 14 | raw / processed data 未被修改 | PASS | `e3712d87` / 30547 bytes、`8565cc8c` / 56826 bytes |
| 15 | deterministic | PASS | 整條流程重跑，序列化完全相同 |
| 16 | 沒有 HTTP request | PASS | socket guard 生效 |
| 17 | 所有 missing data 都被明確保留 | PASS | 9 筆 required（7 筆缺口）+ 2 個 null slot |
| 18 | `interpretation_status` 受控且判定純結構性 | PASS | slot 3 值、insight 2 值；逐 metric 反查結構 |
| 19 | mutation test | PASS | 6 次重跑，0 改變 |
| 20 | 沒有 LLM，也沒有 UI / 前端框架 | PASS | AST 解析 12 個 import + `sys.modules` 比對 23 個套件 |
| 21 | 每個 insight 都有 6 個指定區塊 | PASS | 9 × 6 全部存在 |
| 22 | 組裝沒有依 magnitude / sample size / classification | PASS | `rule_inputs` 3 項；無 classification 欄位與字眼；classification 變異後逐位元相同 |

### 第 9 項曾經 FAIL 一次，原因與處理

第一次執行時第 9 項 FAIL，訊息是 `字眼=['score×38']`。

真正原因：CPBL 官方 endpoint 與快取檔名本身含 `score` 子字串
（`apart_score_0000006888_2026_A_01.json`、`follow_score_...json`），
被我加進去的字眼掃描命中 38 次。那是資料來源檔名，不是本專案產生的 score。

處理方式：掃描前先把 `apart_score` / `follow_score` 中性化成
`cpbl_official_endpoint`，再計數。這是把誤判排除，**不是放寬檢查**——
遞迴欄位名掃描與其他 8 個字眼完全沒動，另外還把 `加權`、`分數` 兩個中文詞
加進掃描清單。修正後 22/22 PASS。

`DATA_SOURCE_TOKENS` 常數與註解都留在程式裡，說明為什麼要中性化。

---

## 13. 已知限制（保留不修）

1. **`interpretation_status` 在 insight 層級只用到 2 個值。**
   `blocked_by_missing_data` 只出現在 metric slot 層級。因為 9 個 group 的
   evidence 數值全部存在，沒有整個 group 都拿不到值的情況。

2. **`factual_only` 與 `factual_with_context` 完全由 candidate type 決定。**
   TREND 一定有 rolling distribution 與 game_snos，CONTEXT 一定都沒有。
   所以這個欄位目前的資訊量等於「這是逐場窗口還是官方分項」。
   Step 19 第 11.4 節已記錄類似的「維度完全由 scope 決定」問題。

3. **phenomenon 是 template 拼出來的，不是自然語言。** 可讀性有限。
   本階段刻意如此：只要引入語言生成，就無法用字眼掃描證明沒有結論。

4. **沒有處理 group 之間的關係。** VS_LEFT 與 VS_RIGHT 是互補的兩半、
   VS_STARTER / RELIEF / CLOSER 是同一批打席的三段切分、RECENT_10 是
   RECENT_15 的子集（Step 8 / 18 已記錄）。這些關係在 insight 之間沒有
   任何連結欄位，使用者若同時讀多個 insight 會看到重疊的打席。

5. **`possible_decision_area` 仍然只有 Step 19 的粒度。**
   本階段沒有細化，也沒有新增值。

6. **`explicit_null` 只涵蓋 metric 不存在的情況。**
   「metric 存在但樣本極小」不會產生任何 null 或警示欄位——那會等於引入
   sample size 門檻。使用者要自己看 `sample_limitation` 與
   `single_event_delta`。

---

## 14. 本階段結論

- 9 個 presentation record 組裝成 9 個 insight object，一對一
- 31 段 phenomenon statement，全部只含資料現象，嚴格字眼掃描命中 0
- 25 筆 metric 追溯記錄，全部能回到 step / file / field / formula
- 2 個 metric slot、7 個應用層缺口，全部明確保留，沒有填補
- 新增 1 個受控欄位 `interpretation_status`（3 值），已說明為何必須新增
- 22 / 22 validation PASS，6 次 mutation 重跑無變化
- 沒有 UI、沒有 ranking、沒有 priority、沒有 Top-N、沒有 prediction、沒有 recommendation
- raw / processed data 未被修改（sha256 與 Step 4 落地時相同）

停在 Step 21。

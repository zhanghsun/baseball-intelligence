# MVP Product Output Model（Step 22）

程式：`src/product_output_model.py`
執行：`python src/product_output_model.py`
Validation：**22 / 22 PASS，0 FAIL**
Mutation test：7 次完整重建，簽章改變 0 次
產品輸出**只存在記憶體**，沒有寫入 `data/`（驗證第 11 項以執行前後檔案清單比對確認）

---

## 0. 這一步做什麼、不做什麼

定義一個**穩定、machine-readable 的產品輸出物件**：未來的 backend / API /
frontend 對一個球員應該收到什麼。這不是分析實驗，沒有新的計算。

**不做**：web UI、API、backend、React / Flask / FastAPI、ranking strategy、
score、weight、threshold、priority、Top-N、confidence score、prediction、
recommendation、natural-language interpretation、LLM、HTTP request。

**不改**：Step 5~21 的任何程式與輸出、raw / processed data。過程中沒有發現
Step 5~21 的阻斷性 bug，因此沒有修改任何既有模組。

唯一在本階段新增的受控詞彙是 `display_slot`（11 個值）。它只是版面槽位的識別
字，不描述任何資料事實，因此不可能改變任何既有判定。

---

## 1. 結構：與建議結構的差異及理由

建議結構是 A. player / B. next_game / C. current_form / D. contextual_evidence /
E. factual_insights / F. data_status / G. traceability / H. metadata。

檢查 Step 20 / 21 後做了兩處調整，兩處都是既有工作直接要求的。

### 調整一：新增頂層 `season_baseline`

25 個 metric 列的 `baseline_value` 完全相同（AVG `0.31135531`、
OBP `0.40312500`、SLG `0.53113553`），Step 9 的 `baseline_definition` 也逐字相同。
建議清單把「season baseline」列為必須顯示的項目，但 A~H 裡沒有它的位置。
埋在 25 個 metric 列裡會迫使消費端掃描全部 insight 才能顯示季基準。

因此提到頂層一次，並保留每個 insight 裡原本的 `baseline_value` 不動。
驗證第 16 項逐一比對 25 次，確認頂層值等於每個 insight 的 `baseline_value`。

### 調整二：`current_form` / `contextual_evidence` 只放參照，不複製數值

Step 20 第 10.6 節建立了**結構性去重**原則（PATTERN 不另建 metric 列）。
如果 C 與 D 各自複製一份 metric 數值、E 再放一份完整 insight，同一組數字會在
輸出裡出現兩次，直接違反那個原則。

因此：

- `factual_insights` 是**唯一數值來源**，以 `insight_id` 為鍵，物件與 Step 21
  深度相同（驗證第 3 項）
- `current_form` / `contextual_evidence` 是 **section 描述子**，只放
  `insight_id`、`group_id`、`scope`、`candidate_ids`、`pointer` 與狀態欄位

驗證第 17 項掃描兩個 section 的完整序列化內容，確認 25 個
`current_value` 字串一次都沒出現。

### 調整三：`contextual_evidence` 涵蓋 Perspective B + C

Step 13 定義了 **3 個** perspective，不是 2 個：

| perspective | scopes | possible_decision_area |
| --- | --- | --- |
| `A_CURRENT_FORM` | RECENT_10、RECENT_15 | `pre_game_preparation` |
| `B_MATCHUP_CONTEXT` | VS_RIGHT、VS_LEFT、VS_STARTER、VS_RELIEF、VS_CLOSER | `pre_game_preparation` / `in_game_situational_preparation` |
| `C_STRUCTURAL_CONTEXT` | VS_DOMESTIC、VS_FOREIGN | `long_term_player_evaluation` |

第一次實作只建 A 與 B 兩個 section，結果 9 個 group 只呈現 7 個
（VS_DOMESTIC / VS_FOREIGN 落在 C，被漏掉）。驗證第 1 / 2 項因此 FAIL。

修正方式是讓 `contextual_evidence` 涵蓋 B + C——這 7 個 scope 都是同一份官方
分項（`ItemGroupCode = 3`）的季累計切分，放在同一個版面區塊符合資料本身的結構。
perspective 的區分沒有被合併掉，以 `subgroups_by_perspective` 完整保留：

```
contextual_evidence.subgroups_by_perspective = {
  "B_MATCHUP_CONTEXT":    ["VS_CLOSER", "VS_LEFT", "VS_RELIEF", "VS_RIGHT", "VS_STARTER"],
  "C_STRUCTURAL_CONTEXT": ["VS_DOMESTIC", "VS_FOREIGN"]
}
```

---

## 2. 完整產品輸出結構

頂層 9 個鍵：

```
{
  "player":              { ... },   # A
  "next_game":           { ... },   # B
  "season_baseline":     { ... },   # 新增，理由見第 1 節
  "current_form":        { ... },   # C  section 描述子（只放參照）
  "contextual_evidence": { ... },   # D  section 描述子（只放參照）
  "factual_insights":    { insight_id: <Step 21 insight 物件> },  # E
  "data_status":         { ... },   # F
  "traceability":        { ... },   # G
  "metadata":            { ... }    # H
}
```

### A. `player`

`player_name`、`player_acnt`、`team`、`team_code`、`season`、`kind_code`、
`kind_name`、`games_played` = 77、`plate_appearances` = 320、`at_bats` = 273、
`source_steps`、`source_files`。

### B. `next_game`

全部來自 Step 14 的 node N2 / N3 / N4，原樣引用。

| 子區塊 | 內容 | `data_status` |
| --- | --- | --- |
| `game` | game_sno 279、2026-08-21 18:35、對味全龍、home、新莊 | `available` |
| `result_not_available` | `home_score` / `visiting_score` = **null** + 原因；檔內原值另存 `raw_values_for_traceability_only` | `unavailable` |
| `opponent_starting_pitcher` | acnt `0000006497`；`pitcher_name` = **null** + 原因 | `partially_available` |
| `opponent_starting_pitcher_hand` | `hand` = **null** + 原因 + `required_to_resolve` | `unavailable` |
| `selection_rule` | `reference_date` = 2026-08-18（由已完成比賽推導）、`clock_independent` = true | — |

`data_status` 完全由 Step 14 node 的 `(status, verification_status)` 對照而來，
使用 Step 20 的 4 值詞彙，沒有新增值也沒有重新評估任何事實：

```
("usable",           "verified_against_processed_schedule")     -> available
("usable",           "unconfirmed_upcoming_starter_identity")   -> partially_available
("unusable_blocked", "unconfirmed_upcoming_starter_identity")   -> unavailable
("unusable_blocked", "missing_required_data")                   -> unavailable
```

驗證第 18 項逐一比對這個對照，並確認 `clock_independent` 為 true。

### `season_baseline`

`definition`、`games` 77、PA / AB / hits / total_bases / walks / hit_by_pitch /
sacrifice_flies，以及三個 metric 各自的 `value` + `derivation` + `source_step`
+ `source_file`。OBP 另附說明：processed data 未收逐場犧牲飛球，因此季 OBP 由
官方分項「VS. 右投」+「VS. 左投」加總取得（Step 8 已驗證三組加總一致）。

### C / D. section 描述子

| 欄位 | current_form | contextual_evidence |
| --- | --- | --- |
| `perspectives` | `["A_CURRENT_FORM"]` | `["B_MATCHUP_CONTEXT", "C_STRUCTURAL_CONTEXT"]` |
| `group_count` | 2 | 7 |
| `candidate_count` | 4 | 25 |
| `temporal_relevance` | `recent_games` | `season_cumulative` |
| `subgroups_by_contextual_relevance` | `none` | `pitcher_hand` 2 / `pitcher_role` 3 / `pitcher_background` 2 |
| `evidence_data_status_values` | `[available]` | `[available]` |
| `application_data_status_values` | `[available]` | `[not_investigated, partially_available, unavailable]` |
| `display_slots` | 8 個 | 7 個（無 rolling） |

每個 `insight_refs[]` 項目：`insight_id`、`group_id`、`scope`、
`candidate_ids`、`official_item_name`、`pointer`、`presentation_purpose`。

`member_selection_rule` 宣告成員完全由 perspective 決定，`rule_not_inputs`
列出 8 個未使用的量，`all_groups_included = true`。

### E. `factual_insights`

以 `insight_id` 為鍵的 9 個 Step 21 insight 物件，深度相同。每個 insight 的
6 個區塊（identity / phenomenon / supporting_evidence / context / limitations /
traceability）與 `interpretation_status` 全部原樣保留。

25 個 metric 列，每列都有 `current_value`、`baseline_value`、`difference`、
`direction`、`sample_size`、`sensitivity`、`rolling_percentile`（無值時為 null
+ 原因）、traceability。

### F. `data_status`

| 欄位 | 內容 |
| --- | --- |
| `evidence_data_status_by_scope` | 9 個 scope，全部 `available` |
| `application_data_status_by_scope` | 9 個 scope，4 種值 |
| `separation.cross_tabulation` | evidence × application 交叉表 |
| `missing_information_registry` | 4 筆（以 required item 為鍵，彙整受影響 scope） |
| `metric_level_gaps` | 2 筆（RECENT_10 / 15 的 OBP） |
| `next_game_field_status` | 4 個欄位的狀態 |
| `null_representation_policy` | 4 條規則 |

### G. `traceability`

`source_files`（3 個檔的 sha256 + byte 數 + 存在性）、`step_registry`
（14 個 step 各自的 module 與 doc）、`metric_index`（27 筆 pointer）。

`metric_index` 只放 pointer，實際的 `source_step` / `source_file` /
`source_field` / `derivation` / `game_snos` 只存在 `factual_insights` 一處。
驗證第 14 項逐 pointer 解析，確認 25 筆可解析且 4 個必填欄位齊全，
2 筆不可追溯者附原因。

`provenance_rule.forbidden` 明文寫著：不接受「source = CPBL」這類模糊來源。

### H. `metadata`

`product_output_version` = `step22-v1`、`counts`、`generated_from_steps`、
`determinism`、`controlled_vocabularies`（14 組）、`display_contract`（11 個
槽位）、`product_rule`、`consumer_contract`、`contains_no`。

---

## 3. 網站要顯示什麼：display contract

`metadata.display_contract` 是機器可讀的版面契約，11 個槽位各自對應輸出中的
路徑。驗證第 20 項確認每個 `source_path` 的根路徑都能在輸出中解析到。

| slot | source_path | availability | 說明 |
| --- | --- | --- | --- |
| `next_game` | `next_game` | partial | 賽程 available；先發身分 partially；手別 unavailable |
| `current_form` | `current_form.insight_refs` | available | RECENT_10 / 15，AVG 與 SLG；OBP null |
| `season_baseline` | `season_baseline` | available | AVG / OBP / SLG 齊全 |
| `contextual_splits` | `contextual_evidence.insight_refs` | available | 7 個官方分項 × 3 metric |
| `factual_evidence` | `factual_insights.<id>.supporting_evidence` | available | 25 個 metric 列 |
| `sample_size` | `...primary_metrics[].sample_size` | partial | AB / PA 全有；7 個分項 games 為 null + 原因 |
| `single_event_sensitivity` | `...primary_metrics[].sensitivity` | available | 25 列全有 |
| `rolling_distribution_position` | `...primary_metrics[].rolling_percentile` | partial | 只有 RECENT_10 / 15 有值 |
| `data_status` | `data_status` | available | 兩個狀態分開 |
| `missing_information` | `data_status.missing_information_registry`（+ `metric_level_gaps`） | available | 4 筆應用層 + 2 筆 metric 層 |
| `traceability` | `traceability` | available | 3 檔 sha256 + 27 筆索引 |

`metadata.consumer_contract` 另訂消費端不得做的事：

- 不得依 `difference` 大小排序或挑選
- 不得依 sample size 隱藏
- 不得把 `application_data_status != available` 當成 evidence 有問題
- 不得把 null 顯示成 0 或省略
- 不得自行生成文字結論

`safe_to_render_all` 承接 Step 20 的 `always_displayed`：9 個 insight 全部應該
顯示，輸出中沒有任何欄位指示消費端隱藏、排序或挑選。

---

## 4. 缺失資訊的表示法

`data_status.null_representation_policy`：

```
rule: null + 明確原因，永不靜默省略
requirements:
  1. 缺失值一律寫成 null，不用 0、空字串或省略欄位表示
  2. 每個 null 旁邊必須有一個 *_reason 或 *_null_reason 欄位
  3. 缺失原因必須指向既有 Step 的調查結果，不得寫成模糊來源
  4. 不估算、不內插、不填補
```

### 4.1 應用層缺口登錄簿（4 筆）

以 required item 為鍵，彙整受影響的 scope。每筆帶 `status`、`vocabulary`、
`availability_source_step`、`evidence_steps`、`factual_basis`、
`affected_scopes`、`is_gap`。

| item | status | is_gap | affected_scopes | 依據 |
| --- | --- | --- | --- | --- |
| `next_game_context` | `available` | false | RECENT_10、RECENT_15 | Step 3 / 4 / 14 |
| `next_starting_pitcher_hand` | `partially_available` | **true** | VS_LEFT、VS_RIGHT | Step 3 / 7A / 14 |
| `in_game_pitcher_role_at_plate_appearance` | `unavailable` | **true** | VS_CLOSER、VS_RELIEF、VS_STARTER | Step 2 / 7A / 8 |
| `next_starting_pitcher_registration_status` | `not_investigated` | **true** | VS_DOMESTIC、VS_FOREIGN | （未調查） |

> **本次指示中的欄位名修正**：指示把 VS_DOMESTIC / VS_FOREIGN 的缺口寫成
> `next_opponent_pitcher_nationality`。Step 13 的受控詞彙
> `ALLOWED_ACTION_LINK_REQUIRES` 裡實際的值是
> `next_starting_pitcher_registration_status`
> （`src/decision_relevance.py`）。事實判定完全一致——本專案從未調查官方是否
> 提供投手的本土／外籍註冊狀態，狀態是 `not_investigated`——但欄位名沿用既有
> 詞彙，不新增同義值。
> 我在 Step 20 / 21 的回報與 `docs/INSIGHT_ASSEMBLY_EXPERIMENT.md` 也曾寫成
> `next_opponent_pitcher_nationality`，該文件已一併修正。

`next_game_context` 的 `is_gap = false`，但仍然留在登錄簿裡，讓消費端看得到
這個依賴存在（沿用 Step 20 的做法）。

### 4.2 metric 層缺口（2 筆）

```
RECENT_10 / on_base_percentage = null   status = blocked_by_missing_data
RECENT_15 / on_base_percentage = null   status = blocked_by_missing_data
reason: processed data 未收逐場犧牲飛球，TREND 窗口無法計算 OBP（Step 5 / Step 11）
value_policy: 值保持 null，不以任何方式估算或填補
```

在 Step 21 的 phenomenon 裡這兩個 slot 是一段 `explicit_null` statement，
不是省略。驗證第 7 項確認 metric 缺口數等於 Step 21 的 `explicit_null` 數。

### 4.3 next_game 的 4 個 null

`home_score`、`visiting_score`、`pitcher_name`、`hand`，全部 null + 原因。
`home_score` / `visiting_score` 在來源檔裡是 `0`，那是官方對未開打場次的預設值
（Step 4 已記錄），因此產品輸出設為 null，檔內原值另存
`raw_values_for_traceability_only` 供追溯。

### 4.4 官方分項沒有時間維度

7 個 VS_* scope 的 `games` = null、`game_snos` = null、`rolling_percentile`
= null，三者都附原因。`limitations.temporal_limitation` 明文記錄
「沒有 game-level 明細、沒有日期範圍、也沒有滾動分布位置，只有季累計」。
產品輸出沒有為這些 scope 發明任何時間欄位。

---

## 5. evidence 與 application 兩個狀態的分離

`data_status.separation` 用交叉表正面證明兩者不能合併：

```
evidence_data_status = available 的 9 個 scope，application 分成 4 種：
  available            : RECENT_10, RECENT_15
  partially_available  : VS_LEFT, VS_RIGHT
  unavailable          : VS_CLOSER, VS_RELIEF, VS_STARTER
  not_investigated     : VS_DOMESTIC, VS_FOREIGN
```

`evidence` 值域只有 1 種值，`application` 值域有 4 種值。任何單一欄位或
boolean 都會把「數字是真的，但還不能用於下一場」說成「數字有問題」。

驗證第 6 項確認：兩個欄位逐 scope 與 Step 21 相同、`application` 全在 Step 20
詞彙內、`evidence` 值域 1 種、`application` 值域 4 種、
`fields_are_independent = true`。

section 層也逐 scope 保留 `application_data_status_by_scope`，不聚合成單一值。

---

## 6. Step 19 / 20 / 21 的對應位置

| 既有工作 | 在產品輸出裡的位置 |
| --- | --- |
| Step 18 的 9 個 group | `current_form` + `contextual_evidence` 的 `insight_refs`（2 + 7 = 9） |
| Step 18 的 29 個 candidate | `insight_refs[].candidate_ids`（4 + 25 = 29） |
| Step 19 decision relevance | `factual_insights.<id>.context`（8 個欄位原樣） + section 的 `subgroups_by_contextual_relevance` + `missing_information_registry`（`action_link_requires`） |
| Step 20 `presentation_purpose` | `insight_refs[].presentation_purpose` |
| Step 20 `always_displayed` | `consumer_contract.safe_to_render_all` + `must_not_do` |
| Step 20 兩個 data status | `data_status` + `factual_insights.<id>.limitations.data_availability` |
| Step 20 PATTERN 結構性去重 | `factual_insights.<id>.phenomenon.cross_metric_statement`（4 個），沒有多出 metric 列 |
| Step 21 factual insight | `factual_insights`（唯一數值來源，深度相同） |
| Step 14 next game chain | `next_game`（node N2 / N3 / N4） |

驗證第 4 項做 9 × 8 = 72 次 Step 19 欄位比對，並把 section 的
`contextual_relevance` 分組逐一回查 Step 19。

---

## 7. deterministic 與 machine-readable

`metadata.determinism`：

```
deterministic            : true
clock_independent        : true
input_order_independent  : true
basis: 所有集合一律排序後輸出；next_game 的參考日由已完成比賽推導，
       不讀系統時鐘；驗證含重跑比對與輸入順序打亂比對。
```

三個機制：

1. **排序**：insight 依 `scope`、section 成員依 `scope`、缺口登錄簿依 item、
   來源檔依路徑、metric 列依 metric 名稱。全部字典序，明文宣告不是 ranking。
2. **不讀時鐘**：`next_game` 的參考日 = 已完成比賽中最晚的 `game_date`
   （2026-08-18），Step 14 已建立。
3. **受控詞彙**：14 組詞彙全部登錄在 `metadata.controlled_vocabularies`，
   每組附 `origin_step`。驗證第 13 項逐一回查 9 個 insight、25 個 metric 列、
   11 個 display slot、4 個 next_game 欄位狀態。

---

## 8. Mutation test

7 次完整重建，**簽章改變 0 次、禁用欄位洩漏 0 次**。

| 變異 | 比對對象 | 期望 | 結果 |
| --- | --- | --- | --- |
| `magnitude = 0.0` | 結構簽章（不含數值） | 不變 | 不變 |
| `magnitude = 999.0` | 結構簽章 | 不變 | 不變 |
| `at_bats = 1` | 結構簽章 | 不變 | 不變 |
| `at_bats = 9999` | 結構簽章 | 不變 | 不變 |
| 逐場資料順序打亂 | **完整輸出** | 逐位元相同 | 相同 |
| 官方分項列順序打亂 | **完整輸出** | 逐位元相同 | 相同 |
| 賽程列順序反轉 | **完整輸出** | 逐位元相同 | 相同 |

結構簽章包含：完整巢狀欄位路徑集合、`insight_ids`、section 的 scope 與
candidate 集合、兩個 data status 對照、缺口登錄簿的
`(item, status, affected_scopes)`、metric 缺口、`next_game_field_status`、
`counts`、`display_contract`、14 組詞彙、`product_rule`。

### 為什麼數值變異要在 candidate 層做

第一版把 magnitude 變異寫在 raw 逐場計數上（`total_bases = 0`），結果結構簽章
改變、驗證 FAIL。診斷後發現這是 Step 9 的既有行為：Step 9 只在三個指標方向
一致時才建立 `MULTI_METRIC_PATTERN`，所以把 `total_bases` 全設為 0 會讓 SLG
方向從 ABOVE / BELOW 變成 EQUAL，進而改變 PATTERN candidate 的**存在與否**，
29 個 candidate 的集合就變了。

那不是 Step 22 的組裝規則出問題。要反證「產品組裝不看數值」，必須固定
candidate 集合再改數值——也就是 Step 19 / 21 用的同一層。修正後改在
candidate 層操作（`rebuild_from_mutated_parts`），4 次數值變異全部通過。

---

## 9. Validation：22 / 22 PASS

| # | 檢查 | 結果 | 依據 |
| ---: | --- | --- | --- |
| 1 | 9 個 group 全部被呈現 | PASS | 2 + 7 = 9，scope 集合與 Step 18 相同 |
| 2 | 29 個 candidate 可經 group 追溯，無遺漏無重複 | PASS | `insight_refs` 列出 29 個，無跨 section 重複 |
| 3 | Step 21 factual insights 數值完全未改 | PASS | 9 個物件深度比較相同 |
| 4 | 每個 metric 保留 7 個核心欄位 | PASS | 25 個 metric 列逐欄位檢查 |
| 5 | Step 19 decision relevance 完全保留 | PASS | 9 × 8 = 72 次比對 + 分組回查 |
| 6 | Step 20 presentation 語意保留 | PASS | purpose 相符；`always_displayed` 由 consumer_contract 承接 |
| 7 | 兩個 data status 保持分離 | PASS | evidence 1 種值、application 4 種值 + 交叉表 |
| 8 | 缺失資料以 null + 明確原因呈現 | PASS | 4 筆應用層 + 2 筆 metric 層 + 4 個 next_game null |
| 9 | 沒有引入 score / weight / threshold / ranking / priority | PASS | 遞迴欄位名掃描 + 10 字眼掃描 |
| 10 | 沒有引入 prediction / recommendation / 自然語言結論 | PASS | 全文 22 字眼 + phenomenon 嚴格 50 字眼 |
| 11 | raw / processed data 未被修改 | PASS | 3 檔 sha256 相符 |
| 12 | 沒有在 data/ 下新增或刪除檔案 | PASS | 執行前後 7 個檔案清單相同 |
| 13 | 不需要 HTTP request，無 LLM / UI / HTTP 客戶端 | PASS | socket guard + AST 解析 15 個 import |
| 14 | deterministic：重跑一致且不依輸入順序 | PASS | 重跑相同 + 3 次順序變異相同 |
| 15 | 所有受控詞彙值都在宣告範圍內 | PASS | 14 組詞彙逐一回查 |
| 16 | traceability 完整（逐 pointer 解析） | PASS | 27 筆索引，25 筆解析成功 |
| 17 | PATTERN 去重沒有遺失資訊，也無重複 metric 列 | PASS | 4 個 PATTERN，12 次 difference 比對 |
| 18 | 頂層 season_baseline 等於每個 insight 的 baseline | PASS | 25 次比對 |
| 19 | section 只放參照，數值只存在一處 | PASS | 掃描 section 序列化，25 個 current_value 均未出現 |
| 20 | next_game 狀態由 Step 14 node 對照，不讀時鐘 | PASS | 3 個欄位對照相符 |
| 21 | mutation test | PASS | 7 次重建，0 改變 |
| 22 | 9 個頂層區塊齊全，display_contract 覆蓋 11 槽位且可解析 | PASS | 路徑全部可解析 |

### 六個曾經 FAIL 的項目與根因

第一次執行 16 PASS / 6 FAIL。六個 FAIL 只有三個獨立根因：

**根因一（FAIL 第 1、2 項）：漏了 Perspective C。** Step 13 有 3 個
perspective，第一版只建 A、B 兩個 section，VS_DOMESTIC / VS_FOREIGN 落在 C
被漏掉，只呈現 7 個 group。修正見第 1 節調整三。

**根因二（FAIL 第 9、21 項的欄位洩漏）：CPBL 官方比分欄位的巢狀鍵。**
Step 14 的 `source_score_values_for_traceability` 內層鍵是
`home_score_in_file` / `visiting_score_in_file`，含 `score` 子字串被遞迴掃描
命中。那是 CPBL 官方比分欄位的檔內原值，不是本專案產生的 score。修正是把這兩
個鍵加入 `ALLOWED_KEY_EXCEPTIONS` 並在程式註解說明，其他 8 個禁用詞完全沒動。

**根因三（FAIL 第 12 項）：檢查方式錯誤。** 第一版拿一份硬編碼的檔案清單比對，
結果被 `data/processed/candidate_insights_zhang_yucheng_2026.json` 命中——那是
Step 9 `--write` 的既有產物，不是 Step 22 建立的。修正是改成執行前後的 data/
檔案清單比對，這才是真正要驗的事。

**根因四（FAIL 第 21 項的簽章改變）：mutation 層次錯誤。** 見第 8 節。

**根因五（FAIL 第 22 項）：display_contract 的 source_path 塞了兩條路徑。**
`missing_information` 的 `source_path` 原本寫成 `A / B` 兩條路徑用斜線併排，
無法解析。改成單一 `source_path` + `additional_source_paths` 陣列。

修正後 22/22 PASS。沒有任何檢查被放寬，第 9 項還多加了 `加權`、`分數`、`評分`
三個中文詞進掃描清單。

---

## 10. 已知限制（保留不修）

1. **只涵蓋一個球員。** 所有 ID 都帶 `0000006888` / `ZHANGYUCHENG-2026-A`。
   多球員需要一層 collection wrapper，本階段沒有做。

2. **只涵蓋一場「下一場」。** `next_game` 是單一場次。多場預覽需要
   `next_games[]`，本階段沒有做。

3. **`interpretation_status` 在 insight 層級只有 2 種值。** Step 21 第 13 節
   已記錄。產品輸出原樣傳遞，沒有補強。

4. **section 之間的重疊沒有連結欄位。** VS_LEFT 與 VS_RIGHT 是互補的兩半、
   VS_STARTER / RELIEF / CLOSER 是同一批打席的三段切分、RECENT_10 ⊂
   RECENT_15（Step 8 / 18 已記錄）。消費端同時顯示多個 insight 會看到重疊的
   打席，輸出裡沒有任何欄位提醒這件事。

5. **`display_contract` 的 `availability` 是三值粗粒度**（available /
   partial / unavailable），比 `data_status` 的 4 值詞彙粗。細節在
   `data_status`，`display_contract` 只是版面層的概覽。

6. **沒有版本協商機制。** 只有一個 `product_output_version` 字串
   （`step22-v1`），沒有 schema 檔、沒有向後相容規則。

7. **`next_game` 的 `game_status` 是官方原字串**（「未開打或進行中」），
   不是受控詞彙。Step 4 原樣落地，本階段沒有另建對照。

8. **產品輸出沒有落地。** 只存在記憶體，每次執行重新組裝。這是本次指示要求
   的（「Prefer returning the product output in memory」），代價是消費端目前
   沒有可直接讀的檔案或 endpoint。

---

## 11. 本階段結論

- 定義了頂層 9 個區塊的產品輸出，`factual_insights` 是唯一數值來源
- 9 個 group、29 個 candidate、9 個 insight、25 個 metric 列全部呈現
- 2 筆 metric 層缺口 + 4 筆應用層 required 項目（3 筆為缺口）全部以
  null + 明確原因保留
- evidence 與 application 兩個 data status 完整分離，附交叉表反證
- 11 個 display slot 的機器可讀版面契約，路徑全部可解析
- 27 筆 metric 追溯索引，pointer 可解析到 step / file / field / formula
- 22 / 22 validation PASS，7 次 mutation 重建無變化
- 沒有 UI、沒有 API、沒有 backend、沒有 ranking / priority / Top-N、
  沒有 prediction / recommendation
- 沒有修改任何既有資料或 Step 5~21 的程式；`data/` 檔案清單執行前後相同
- 唯一新增詞彙：`display_slot`（11 值，純版面識別字）
- 修正了一處文件錯誤：`next_opponent_pitcher_nationality` →
  `next_starting_pitcher_registration_status`

停在 Step 22。不進入 backend / frontend。

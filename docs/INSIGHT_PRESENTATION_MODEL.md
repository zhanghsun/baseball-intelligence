# Insight Presentation Model（Step 20）

建立日期：2026-08-20
產出腳本：`src/insight_presentation_model.py`
沿用文件：`docs/INSIGHT_GROUPING_EXPERIMENT.md`（Step 18）、
`docs/GROUP_DECISION_RELEVANCE_EXPERIMENT.md`（Step 19）、
`docs/DECISION_RELEVANCE_EXPERIMENT.md`（Step 13）、
`docs/CANDIDATE_INSIGHT_DESIGN.md`（Step 9）、
`docs/EVIDENCE_SAMPLE_ANALYSIS.md`（Step 11）、
`docs/INSIGHT_CHAIN_EXPERIMENT.md`（Step 14）

> ## 這是什麼、不是什麼
>
> **是：** machine-readable 的呈現模型——研究使用者應該看到哪些資訊與每一項的資料狀態。
>
> **不是：** 不是 UI、不是前端實作。沒有 React / Flask / FastAPI / dashboard
> （驗證有檢查沒有引入任何 UI 框架）。
>
> **不含：** score、weight、threshold、ranking、priority、importance、
> confidence score、Top-N、prediction、recommendation、strategy、
> 自然語言結論、LLM。
>
> **9 個 group 全部保留**，`always_displayed = true`。

> ## 核心原則
>
> ### 「資料缺口也必須是一級資訊。」
>
> 任何 group 都不會因為缺資料、數值小或樣本小而被隱藏。
> 缺什麼、缺到什麼程度、依據是什麼，全部以結構化欄位記錄。

---

## 1. 三段區分（A / B / C）

指示要求這三件事不能合併成一個 boolean。實作上是**三組獨立欄位**：

| | 問題 | 欄位 | 值域 |
| --- | --- | --- | --- |
| **A** | evidence 本身是否完整？ | `evidence_completeness` | `evidence_available`（bool）+ `self_containment`（2 值）+ `metric_coverage` |
| **B** | evidence 是否可直接用於下一場決策？ | `application_readiness` | `readiness`（2 值）+ `application_data_status` + `readiness_basis` |
| **C** | 要完成應用還缺什麼資料？ | `missing_information` | `required_additional_data`（永遠保留）+ `missing_for_application`（缺口清單）+ `missing_count` |

### 為什麼不能合併成一個 boolean

實測結果出現**兩種相反組合**：

| group | A（self_containment） | B（readiness） |
| --- | --- | --- |
| `RECENT_10` / `RECENT_15` | **`requires_next_game_context`**（不自足） | **`ready_with_available_data`**（可直接應用） |
| 7 個 `VS_*` | **`self_contained`**（自足） | **`not_ready_pending_data`**（無法直接應用） |

**A 與 B 的方向剛好相反。** 任何單一 boolean 都無法同時表達
「evidence 不自足但可以應用」與「evidence 自足但無法應用」這兩件事。
驗證第 16 項就是檢查這兩種組合都確實存在。

每組欄位另外帶 `is_not` 聲明它不是另外兩件事。

---

## 2. 總覽：9 個 group 的呈現狀態

| scope | A: self_containment | B: readiness | C: missing_count |
| --- | --- | --- | ---: |
| `RECENT_10` | `requires_next_game_context` | **`ready_with_available_data`** | **0** |
| `RECENT_15` | `requires_next_game_context` | **`ready_with_available_data`** | **0** |
| `VS_LEFT` | `self_contained` | `not_ready_pending_data` | 1 |
| `VS_RIGHT` | `self_contained` | `not_ready_pending_data` | 1 |
| `VS_STARTER` | `self_contained` | `not_ready_pending_data` | 1 |
| `VS_RELIEF` | `self_contained` | `not_ready_pending_data` | 1 |
| `VS_CLOSER` | `self_contained` | `not_ready_pending_data` | 1 |
| `VS_DOMESTIC` | `self_contained` | `not_ready_pending_data` | 1 |
| `VS_FOREIGN` | `self_contained` | `not_ready_pending_data` | 1 |

### 兩種 data status 分開記錄

| scope | `evidence_data_status` | `application_data_status` | metric 數 | metric 缺 |
| --- | --- | --- | ---: | --- |
| `RECENT_10` | `available` | **`available`** | 2 | OBP |
| `RECENT_15` | `available` | **`available`** | 2 | OBP |
| `VS_LEFT` | `available` | **`partially_available`** | 3 | — |
| `VS_RIGHT` | `available` | **`partially_available`** | 3 | — |
| `VS_STARTER` | `available` | **`unavailable`** | 3 | — |
| `VS_RELIEF` | `available` | **`unavailable`** | 3 | — |
| `VS_CLOSER` | `available` | **`unavailable`** | 3 | — |
| `VS_DOMESTIC` | `available` | **`not_investigated`** | 3 | — |
| `VS_FOREIGN` | `available` | **`not_investigated`** | 3 | — |

**9 個 group 的 `evidence_data_status` 全部是 `available`，
但 `application_data_status` 有 4 種不同值。**
把這兩件事放在同一個欄位就會遺失這個區分。

### data status 詞彙的來源

與 Step 19 的 `data_availability` **一對一改名**，沒有新增或合併任何狀態：

| Step 19 | Step 20 |
| --- | --- |
| `verified_available` | `available` |
| `partially_verified` | `partially_available` |
| `currently_unavailable` | `unavailable` |
| `not_investigated` | `not_investigated` |

每筆記錄都帶 `mapped_from_step19_value` 與 `mapping_note`，可回溯。

---

## 3. 回答：9 個 group 各自會呈現什麼資訊

### presentation purpose（受控詞彙，只描述「可以提供什麼資訊」）

| purpose | groups |
| --- | --- |
| `recent_form_relative_to_season_baseline` | RECENT_10、RECENT_15 |
| `season_split_by_pitcher_hand_relative_to_season_baseline` | VS_LEFT、VS_RIGHT |
| `season_split_by_pitcher_role_relative_to_season_baseline` | VS_STARTER、VS_RELIEF、VS_CLOSER |
| `season_split_by_pitcher_background_relative_to_season_baseline` | VS_DOMESTIC、VS_FOREIGN |

每個 purpose 都帶 `is_not`：「只描述這個 group 可以提供什麼資訊，
不是 recommendation、不是 prediction、不是 strategy。」

### 可提供的資訊項目（受控詞彙，7 個值）

| group | metric 列 | rolling 位置 | game_snos | 跨指標方向 | 項目數 |
| --- | ---: | --- | --- | --- | ---: |
| RECENT_10 / RECENT_15 | 2 | **有** | **有** | 無 | 5 |
| VS_STARTER / VS_CLOSER / VS_DOMESTIC / VS_FOREIGN | 3 | 無 | 無 | **有** | 5 |
| VS_LEFT / VS_RIGHT / VS_RELIEF | 3 | 無 | 無 | 無 | 4 |

TREND group 提供 `rolling_distribution_position` 與 `game_level_traceability`；
VS_* group 提供 `official_split_definition_reference`；
有 3/3 pattern 的 4 個 group 另外提供 `cross_metric_direction_summary`。

### group 內部的結構性去重

metric 列一律取自 CONTEXT / TREND candidate。PATTERN 的內容改以
`cross_metric_direction` 呈現，避免同一組數字在 group 內重複兩次
（Step 18 第 10.6 節記錄的 group 內部重複問題）。

**這是結構性去重，不是依數值或分類篩選。**
驗證第 4 項逐一比對確認：4 個 PATTERN × 3 個 metric = **12 次比對**，
PATTERN 的每個 metric 差距都等於同 group CONTEXT 列的差距，**沒有資訊遺失**。
PATTERN 的方向摘要以 `cross_metric_direction` 完整保留，含 Step 10 的已知限制。

---

## 4. 回答：哪些資訊可以直接顯示

**全部 9 個 group 的 evidence 都可以直接顯示。** 每個 metric 列包含：

| 欄位 | 內容 | 來源 |
| --- | --- | --- |
| `current_value` / `baseline_value` / `difference` / `direction` | 完整精度 | Step 9（值來自 Step 5 或 Step 8） |
| `baseline_definition` | 「2026 一軍例行賽季累計（77 場實際出賽）」 | Step 5 |
| `sample_size` | `at_bats` / `plate_appearances` / `games`（+ 缺失原因） | Step 11 |
| `single_event_sensitivity` | 分子分母、`one_more_success`、`one_fewer_success`、`delta_if_one_more`、`success_unit` | Step 11 |
| `rolling_distribution_position` | rank / n / percentile（或 `null` + 原因） | Step 6 |
| `traceability` | `source_candidate_id`、`value_source_step`、日期範圍、`game_snos`（或 `null` + 原因）、`official_item_name`、`source_files` | Step 5 / 8 / 9 |

**沒有任何 metric 列被隱藏。** 缺的東西（TREND 的 OBP、VS_* 的 rolling 與 game_snos）
一律以 `null` + 明確原因呈現，不是省略。

### 完整範例：`VS_RIGHT`（正好對應指示中的例子）

```
group_identity
  scope         : VS_RIGHT
  perspective   : B_MATCHUP_CONTEXT
  candidate_ids : 3 個（VS_RIGHT-AVG / OBP / SLG）

evidence_summary（3 個 metric）
  AVG: current=0.31050228  baseline=0.31135531  diff=-0.00085303  direction=BELOW
       sample: AB=219  PA=258  games=null（官方分項無場次欄位）
       sensitivity: 68/219  one_more=0.31506849  one_fewer=0.30593607  delta=0.00456621
       rolling: null（官方分項沒有時間維度，無法建立滾動分布，Step 8）
       traceability: CONTEXT-…-VS_RIGHT-AVG　官方 VS. 右投
                     game_snos=null（官方分項不提供日期或場次，Step 8）
  OBP: current=0.40310078  baseline=0.40312500  diff=-0.00002422  direction=BELOW
       sensitivity: 104/258  delta=0.00387597
  SLG: current=0.55707763  baseline=0.53113553  diff=+0.02594209  direction=ABOVE
       sensitivity: 122/219  delta=0.00456621
  cross_metric_direction: 不可用（此 context 沒有 3/3 pattern）

data_status
  evidence_data_status    = available
  application_data_status = partially_available（由 Step 19 的 partially_verified 對應）

A. evidence_completeness
  evidence_available       = true
  self_containment         = self_contained
  metric_coverage.complete = true

B. application_readiness
  readiness = not_ready_pending_data
  basis     = 應用所需的額外資料狀態為 partially_available，因此目前無法直接應用

C. missing_information
  missing_count = 1
  required: next_starting_pitcher_hand　status=partially_available
            依據 Step 3、7A、14
  MISSING : next_starting_pitcher_hand（partially_available）

display_rule: always_displayed = true
```

這與指示中的預期完全一致：
`evidence_available = true`、`application_data_status = partially_available`、
`missing_for_application = next_starting_pitcher_hand`，
而且 **group 沒有被隱藏**。

---

## 5. 回答：哪些資訊需要額外資料

**9 個 group 全部都需要額外資料才能應用**（`requires_additional_data = true`）。

| `application_data_status` | groups | `required_additional_data` | `readiness` |
| --- | --- | --- | --- |
| **`available`** | RECENT_10、RECENT_15 | `next_game_context` | **`ready_with_available_data`** |
| `partially_available` | VS_LEFT、VS_RIGHT | `next_starting_pitcher_hand` | `not_ready_pending_data` |
| `unavailable` | VS_STARTER、VS_RELIEF、VS_CLOSER | `in_game_pitcher_role_at_plate_appearance` | `not_ready_pending_data` |
| `not_investigated` | VS_DOMESTIC、VS_FOREIGN | `next_starting_pitcher_registration_status` | `not_ready_pending_data` |

### `required_additional_data` 永遠保留，即使已可取得

RECENT_10 / RECENT_15 的 `missing_count = 0`（沒有缺口），
但 `required_additional_data` 仍然列出 `next_game_context` 與其 `available` 狀態。

理由寫在 `note` 中：讓使用者看得到這個依賴存在。
「可以取得」不等於「不存在依賴」。

---

## 6. 回答：哪些資料目前拿不到

### `unavailable`（3 個 group）

`in_game_pitcher_role_at_plate_appearance`

> Step 2 已確認逐場成績 41 個欄位沒有任何投手欄位；
> Step 8 已確認官方分項沒有逐打席明細；
> 逐打席投手只存在於 `/box/getlive`，該 payload 從 Step 2 至今從未驗證過。

### `not_investigated`（2 個 group）

`next_starting_pitcher_registration_status`

> 本專案從未調查官方是否提供投手的本土／外籍註冊狀態。
> Step 13 第 7.1 節已標記為未驗證。

### `partially_available`（2 個 group）

`next_starting_pitcher_hand`

> Step 7A 在【已完成】比賽上驗證「賽程投手 Acnt → 球員頁投打習慣」5/5 通過；
> 但未開打場次的 Acnt 是否代表預告先發，Step 3 與 Step 7A 都標記為未確認，
> Step 14 因此把 `pitcher_hand` node 標為 blocked。

**`unavailable` 與 `not_investigated` 是兩件不同的事**，
所以用兩個不同的值：前者是已經查過確認拿不到，後者是從未查過。
把它們合併會讓「沒查過」被誤讀成「查過了但沒有」。

每一筆都帶 `evidence_steps` 與 `factual_basis`，
`not_investigated` 的 `evidence_steps` 是空陣列（因為真的沒有調查依據）。
驗證第 13 項確認 9 筆 `required_additional_data` 全部帶完整來源。

---

## 7. 回答：使用者如何知道一個數字的 sample size 與來源

**每個 metric 列都內建這些欄位，不需要另外查詢或跳頁。**

以 `RECENT_10` 的 AVG 為例：

```json
"sample_size": {
  "at_bats": 42,
  "plate_appearances": 44,
  "games": 10,
  "games_missing_reason": null,
  "source_step": "Step 11"
},
"single_event_sensitivity": {
  "numerator": 17, "denominator": 42,
  "numerator_label": "hits", "denominator_label": "at_bats",
  "one_more_success": 0.42857143,
  "one_fewer_success": 0.38095238,
  "delta_if_one_more": 0.02380952,
  "success_unit": "一支安打（把一個出局換成一支安打，打數不變）",
  "source_step": "Step 11",
  "is_not": "這是算術上的敏感度描述，不是可信程度"
},
"traceability": {
  "source_candidate_id": "TREND-ZHANGYUCHENG-2026-A-RECENT_10-AVG",
  "source_step": "Step 9",
  "value_source_step": "Step 5",
  "date_range": {"first_game_date": "2026-08-02", "last_game_date": "2026-08-18"},
  "game_snos": [240, 242, 244, 249, 260, 261, 262, 265, 269, 272],
  "official_item_name": null,
  "source_files": ["data/processed/zhang_yucheng_game_logs_2026.json"]
}
```

### 三種來源資訊都在同一列

1. **樣本量**：`at_bats` / `plate_appearances` / `games`，缺的附 `games_missing_reason`
2. **單一事件的影響量**：`delta_if_one_more` 與 `success_unit`
   （讓使用者知道 42 個打數下一支安打會讓 AVG 動 0.0238）
3. **來源**：`source_candidate_id`、`value_source_step`、`source_files`，
   TREND 有完整 `game_snos` 可回推到具體比賽，VS_* 則有 `official_item_name`
   與 `game_snos_missing_reason`

---

## 8. 回答：如何避免把資料缺口誤解成「沒有問題」

三個機制，每一個都是結構性的，不依賴使用者自己記得：

### (a) A / B / C 三段分開，不合併成一個 boolean

`VS_RIGHT` 同時是 `self_contained`（A）與 `not_ready_pending_data`（B）。
如果只給一個「這個 insight 可用嗎」的 boolean，
無論給 true 或 false 都會誤導：
給 true 會讓人以為可以直接用於下一場，給 false 會讓人以為 evidence 有問題。

### (b) `evidence_data_status` 與 `application_data_status` 分成兩個欄位

9 個 group 的 `evidence_data_status` 都是 `available`，
`application_data_status` 卻有 4 種值。
合併成一個「資料狀態」欄位就會遺失這個區分。

### (c) 缺口是「一筆記錄」，不是「沒有資料」

`missing_count` 分佈：`{0: 2, 1: 7}`。

7 個 group 的缺口不是欄位空白或省略，而是
`missing_for_application` 陣列中一筆帶 `item` / `status` /
`availability_source_step` / `evidence_steps` / `factual_basis` 的完整記錄。

另外 `no_guessing_note` 明確聲明：
「缺失的資料一律不猜測、不填補。每一筆缺口都標明來源 Step 與事實依據。」

### 額外：`always_displayed` 是明文規則

`display_rule.always_displayed = true`（9 個全部），
`always_displayed_reason` 寫明：「資料缺口也是一級資訊。任何 group 都不會因為缺資料、
數值小或樣本小而被隱藏。」

`rule_inputs` 只有 `["group_membership", "step19_decision_relevance"]`，
`rule_not_inputs` 明確列出 6 個**沒有**被用來決定顯示與否的量：
`magnitude`、`sample_size_at_bats`、`plate_appearances`、`percentile_rank`、
`consistency_count`、`classification`。

---

## 9. Presentation record schema

| 區塊 | 欄位 |
| --- | --- |
| 1. `group_identity` | `group_id`、`perspective`、`perspective_name`、`scope`、`candidate_ids`、`candidate_count`、`subject` |
| 2. `evidence_summary` | `metrics[]`（每列含 current / baseline / difference / direction / sample_size / single_event_sensitivity / rolling_distribution_position / traceability）、`metrics_present`、`metrics_unavailable` + 原因、`cross_metric_direction` |
| 3. `decision_relevance` | 原樣引用 Step 19 的 7 個維度 + `source_step` |
| 4. `data_status` | `application_data_status`、`vocabulary`、`mapped_from_step19_value`、`mapping_note`、`evidence_data_status` + basis |
| A | `evidence_completeness` |
| B | `application_readiness` |
| C | `missing_information` |
| 6. `presentation_purpose` | `purpose`、`provides_information_items`、`is_not` |
| — | `display_rule`、`provenance`、`contains_no` |

`provenance` 記錄 8 個來源指向：group（Step 18）、decision relevance（Step 19）、
candidate（Step 9）、metric 值（Step 5 / Step 8）、sample context（Step 11）、
rolling distribution（Step 6）、`source_files`、sidecar 說明。

---

## 10. Validation

程式執行 **18 項檢查，全部通過（18 / 18）**。本次執行沒有 FAIL。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 9 個 group 全部存在 | 9 個 group 且全部 `always_displayed` | PASS |
| 2 | membership 與 Step 18 一致 | 成員清單與成員數逐一相符，總數 29 | PASS |
| 3 | evidence summary 與 Step 9 一致 | 25 個 candidate × 5 個欄位逐一比對 | PASS |
| 4 | — | PATTERN 結構性去重沒有遺失資訊 | PASS　4 × 3 = 12 次比對 |
| 5 | sample context 與 Step 11 一致 | 25 個 metric 列的 sample_size 與 sensitivity | PASS |
| 6 | decision relevance 與 Step 19 一致 | 9 × 11 = 99 次逐一比對 | PASS |
| 7 | 不修改 grouping | 深度比較 9 個 group 物件 | PASS |
| 8 | 不修改 candidate | 深度比較 29 個物件 | PASS |
| 9 | 不修改 raw / processed data | sha256 前後不變 | PASS |
| 10 | 不產生 score / weight / threshold / ranking / priority | 遞迴掃描所有巢狀欄位名 | PASS |
| 11 | deterministic | 整條流程重跑一次，序列化結果相同 | PASS |
| 12 | 不發 HTTP request | socket guard 生效 | PASS |
| 13 | 所有 missing information 都有明確來源 | 9 筆 required 全部帶 status / source_step / factual_basis，其中 7 筆為缺口 | PASS |
| 14 | 不允許自由文字 recommendation / prediction | 字眼掃描（宣告性欄位已扣除） | PASS |
| 15 | — | 所有分類欄位值都在受控詞彙內 | PASS |
| 16 | — | **A / B / C 不能用單一 boolean 表達** | PASS　出現兩種相反組合 |
| 17 | — | **沒有 LLM，也沒有引入任何 UI / 前端框架** | PASS　AST import 檢查 |
| 18 | — | 顯示與否沒有依 magnitude / sample size / classification 決定 | PASS |

### 幾項檢查的實作方式

**第 4 項** 是這一步新增的檢查，用來確保結構性去重是安全的：
逐一比對每個 PATTERN 的三個 metric 差距是否等於同 group 的 CONTEXT 列。
若不相等就代表去重遺失了資訊。

**第 16 項** 收集全部 9 個 group 的 `(A, B, C)` 組合，
確認同時存在 `(self_contained, not_ready)` 與
`(requires_next_game_context, ready)` 這兩種相反組合。
這在結構上證明三者無法用單一 boolean 表達。

**第 17 項** 用 AST 解析實際 import 的頂層模組（9 個，全部標準函式庫或本專案模組），
再比對 13 個 LLM 套件名與 **9 個 UI / 前端框架名**
（`flask`、`fastapi`、`django`、`streamlit`、`dash`、`jinja2`、`starlette`、
`uvicorn`、`tkinter`）。

**第 13 項** 除了檢查欄位完整，還檢查**沒有把 `available` 的項目誤列為缺口**。

### hash 記錄

| 檔案 | sha256 前 8 碼 | bytes |
| --- | --- | --- |
| `data/processed/zhang_yucheng_game_logs_2026.json` | `e3712d87` | 30,547 |
| `data/raw/apart_score_0000006888_2026_A_01.json` | `8565cc8c` | 56,826 |

執行前後完全一致。沒有寫出任何檔案到 `data/`。

---

## 11. 已知限制

1. **這只是模型，不是 UI。** 呈現順序、版面、視覺層級完全沒有決定。
   輸出依 scope 字典序，那不是排名。
2. **`presentation_purpose` 的 4 個值只描述資料類型**，
   沒有描述「這個資訊在什麼情境下有用」。後者需要球隊實務輸入。
3. **`readiness` 只有 2 個值。** `not_ready_pending_data` 涵蓋了三種很不同的狀況
   （partially / unavailable / not_investigated）。細節在
   `application_data_status` 與 `missing_information` 中，
   但 `readiness` 本身無法區分。Step 19 第 11.2 節已記錄類似的粒度問題。
4. **9 個 group 的 A / B / C 組合只有 2 種。** 因為 decision relevance
   完全由 scope 決定（Step 19 第 11.4 節），所以呈現狀態也只有兩類。
   `missing_count` 只有 0 與 1 兩個值。
5. **沒有處理 group 之間的關係。** 例如 VS_LEFT 與 VS_RIGHT 是互補的兩半，
   VS_STARTER / RELIEF / CLOSER 是同一批打席的三段切分（Step 8 已記錄），
   呈現模型目前把它們當成 9 個獨立項目。
6. **沒有寫出檔案。** sidecar 只在程式輸出中，與 Step 10 ~ 19 一致。
7. **只有一名球員、一個球季。** 9 個 group 的組成與狀態分佈不具一般性。

---

## 12. 本階段刻意沒有做的事

- 沒有做 UI、沒有前端實作、沒有引入任何 UI 框架（AST import 檢查驗證）
- 沒有做 ranking、沒有選最佳 group、沒有決定 Top-N
- 沒有建立 score / weight / threshold / priority / importance / confidence score
- 沒有用 magnitude 決定顯示與否、沒有用 sample size 篩選、
  沒有用 classification 決定是否顯示（`rule_not_inputs` 明列 + 驗證第 18 項）
- 沒有隱藏任何 group（9 個全部 `always_displayed = true`）
- 沒有隱藏任何 metric 列（缺的以 `null` + 原因呈現）
- 沒有 prediction / recommendation / strategy / 自然語言結論
- 沒有猜測或填補任何缺失資料
- 沒有把 A / B / C 合併成單一 boolean
- 沒有把 `unavailable` 與 `not_investigated` 合併
- 沒有新增 candidate、沒有新增 group
- 沒有修改 candidate（深度比較驗證）、沒有修改 Step 18 grouping（深度比較驗證）
- 沒有修改 Step 19 的 decision relevance 值（99 次逐一比對驗證）
- 沒有修改 `data/raw/` 或 `data/processed/`（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有 HTTP request（socket guard 強制保證）
- 沒有使用 LLM
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

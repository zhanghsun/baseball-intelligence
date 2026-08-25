# Observation → Noteworthy 規則實驗（Step 17-7）

建立日期：2026-08-20
產出腳本：`src/noteworthy_insights.py`
輸入：Step 9 的 29 個 candidate、Step 6 的滾動分布、Step 11 的 sample context

> ## 關於 Step 編號的說明（請先讀）
>
> 本專案 `docs/` 目前只有到 **Step 14**（`INSIGHT_CHAIN_EXPERIMENT.md`）。
> **沒有 Step 15 / 16 / 17 的文件。**
>
> 本階段使用的「Observation → Noteworthy」規則來自**本次任務指示中直接給定的第一版規則**，
> 而不是某份既有文件。程式中的 `RULE_SOURCE` 欄位如實記錄這一點，
> 沒有引用不存在的文件當來源。
>
> 這件事會影響一項驗證的解讀：「所有 supporting evidence 都能追溯到既有 Step 9～13 資料」——
> 實際可追溯的範圍是 **Step 5、6、8、9、10、11**（Step 12 / 13 是實驗性 sidecar，
> 本階段沒有引用它們的產出）。驗證中使用的允許清單就是這 6 個。

> ## 這一步是什麼、不是什麼
>
> **是：** 把第一版規則套用到 29 個 candidate，觀察實際資料下會分出什麼結果。
>
> **不是：** 不設 AVG 差距門檻、不設 percentile 門檻、不設 AB 門檻、
> 不因樣本小而淘汰、不新增 statistical test、不建立 score / weight / rank、
> 不使用 LLM、不產生最終自然語言結論。

---

## 1. 規則定義（第一版，`R17-1`）

| rule_id | 內容 |
| --- | --- |
| `R17-1-OBS` | candidate 本身有直接 evidence（現象 evidence 存在且值不為 null）即可形成 **observation** |
| `R17-1-NOTE` | observation 成立，且同時具備「第二種不同性質的支持 evidence」與「sample context」時，標記為 **noteworthy** |
| `R17-1-NE` | 連直接 evidence 都沒有時為 **not_eligible** |

### 三類 evidence 的定義

| evidence_class | evidence_type | 來源 | 誰有 |
| --- | --- | --- | --- |
| `phenomenon` | `window_difference_from_season_baseline` | Step 9 | TREND（4） |
| `phenomenon` | `context_difference_from_season_baseline` | Step 9 | CONTEXT（21） |
| `phenomenon` | `multi_metric_difference_from_season_baseline` | Step 9 | PATTERN（4） |
| `second_supporting` | `rolling_window_distribution_position` | Step 6 | TREND（4） |
| `second_supporting` | `cross_metric_direction_consistency` | Step 9 | 有 3/3 pattern 的 context（16） |
| `sample_context` | `sample_size_and_count_sensitivity` | Step 11 | 全部 29 個 |

### 「第二種不同性質」怎麼判定

只採用兩種來源，兩者都必須能追溯到既有資料。**不虛構、不新增。**

**1. `rolling_window_distribution_position`（只有 TREND 有）**

該窗口值在**同尺寸滾動窗口分布**中的位置（Step 6 建立，Step 9 記錄）。

性質與現象 evidence 不同：現象是「與單一季累計基準的差」，
本項是「在 68 個（或 63 個）重疊窗口中的相對位置」。

**2. `cross_metric_direction_consistency`（CONTEXT / PATTERN 可能有）**

同一 context 中 AVG / OBP / SLG 三個指標與季累計比較的方向是否全部一致
（Step 9 的 `MULTI_METRIC_PATTERN`，`consistency_count == total_metrics`）。

性質與現象 evidence 不同：現象是「單一指標的差距大小」，
本項是「跨指標的方向一致性」。

CONTEXT / PATTERN 沒有 `rolling_window_distribution_position`，
因為官方分項沒有時間維度，建不出滾動分布（Step 8 已記錄）。

---

## 2. 29 個 candidate 的分類

| classification | 數量 |
| --- | ---: |
| **noteworthy** | **20** |
| **observation** | **9** |
| **not_eligible** | **0** |
| 合計 | 29 |

### 依 candidate 類型

| candidate_type | noteworthy | observation | not_eligible |
| --- | ---: | ---: | ---: |
| TREND | **4** | 0 | 0 |
| MULTI_METRIC_PATTERN | **4** | 0 | 0 |
| CONTEXT | **12** | **9** | 0 |

### 完整清單

**noteworthy（20 個）**

| candidate_id | 第二種 evidence |
| --- | --- |
| `TREND-…-RECENT_10-AVG` | rolling position（rank 5/68，pct 94.1176） |
| `TREND-…-RECENT_10-SLG` | rolling position（rank 20/68，pct 72.0588） |
| `TREND-…-RECENT_15-AVG` | rolling position（rank 25/63，pct 61.9048） |
| `TREND-…-RECENT_15-SLG` | rolling position（rank 35/63，pct 46.0317） |
| `PATTERN-…-VS_CLOSER-AVG_OBP_SLG` | cross-metric 3/3 BELOW |
| `PATTERN-…-VS_DOMESTIC-AVG_OBP_SLG` | cross-metric 3/3 BELOW |
| `PATTERN-…-VS_FOREIGN-AVG_OBP_SLG` | cross-metric 3/3 ABOVE |
| `PATTERN-…-VS_STARTER-AVG_OBP_SLG` | cross-metric 3/3 ABOVE |
| `CONTEXT-…-VS_CLOSER-AVG / OBP / SLG` | cross-metric 3/3 BELOW |
| `CONTEXT-…-VS_DOMESTIC-AVG / OBP / SLG` | cross-metric 3/3 BELOW |
| `CONTEXT-…-VS_FOREIGN-AVG / OBP / SLG` | cross-metric 3/3 ABOVE |
| `CONTEXT-…-VS_STARTER-AVG / OBP / SLG` | cross-metric 3/3 ABOVE |

**observation（9 個）** — 全部是 CONTEXT，全部缺 `second_supporting`

```
CONTEXT-…-VS_LEFT-AVG / OBP / SLG      （VS_LEFT   方向 ABOVE / ABOVE / BELOW → 2/3）
CONTEXT-…-VS_RELIEF-AVG / OBP / SLG    （VS_RELIEF 方向 BELOW / BELOW / ABOVE → 2/3）
CONTEXT-…-VS_RIGHT-AVG / OBP / SLG     （VS_RIGHT  方向 BELOW / BELOW / ABOVE → 2/3）
```

**not_eligible（0 個）**

沒有任何 candidate 落入這一類。這條規則分支因此**沒有被實際資料驗證過**。
它成立的條件是「現象 evidence 缺失」（差距為 null），而 29 個 candidate 都有值。

---

## 3. 每個 noteworthy 是由哪些不同 evidence 支持

全部 29 個 record 共 **78 筆** supporting evidence
（20 個 noteworthy × 3 + 9 個 observation × 2 = 60 + 18 = 78）。

### 範例一：`TREND-…-RECENT_10-AVG`（本階段指定要檢查的 candidate）

| evidence_class | evidence_type | 內容 | 來源 |
| --- | --- | --- | --- |
| `phenomenon` | `window_difference_from_season_baseline` | current 0.40476190、baseline 0.31135531、**diff +0.09340659**、direction ABOVE | Step 9 |
| `second_supporting` | `rolling_window_distribution_position` | window_size 10、**n=68**、**rank 5**、below/equal/above = 63/1/4、**percentile_rank 94.1176**、percentile_strict 92.6471 | Step 6 |
| `sample_context` | `sample_size_and_count_sensitivity` | **AB 42**、PA 44、games 10、17/42 = 0.40476190、one_more 0.42857143、one_fewer 0.38095238、**delta 0.02380952** | Step 11 |

三類齊備 → **noteworthy**（`R17-1-NOTE`）。這與任務指示的預期一致。

### 範例二：`CONTEXT-…-VS_CLOSER-AVG`（樣本最小，AB 27）

| evidence_class | evidence_type | 內容 | 來源 |
| --- | --- | --- | --- |
| `phenomenon` | `context_difference_from_season_baseline` | current 0.14814815、baseline 0.31135531、**diff −0.16320716**、direction BELOW | Step 9 |
| `second_supporting` | `cross_metric_direction_consistency` | direction BELOW、**3/3**、per_metric {AVG: BELOW, OBP: BELOW, SLG: BELOW} | Step 9（PATTERN candidate） |
| `sample_context` | `sample_size_and_count_sensitivity` | **AB 27**、PA 31、4/27 = 0.14814815、one_more 0.18518519、one_fewer 0.11111111、**delta 0.03703704** | Step 11 |

三類齊備 → **noteworthy**。**樣本 27 個打數沒有讓它被淘汰或降級。**

### 第二種 evidence 的來源分佈

| evidence_type | 數量 |
| --- | ---: |
| `cross_metric_direction_consistency` | 16 |
| `rolling_window_distribution_position` | 4 |
| （無） | 9 |

---

## 4. 哪些 candidate 無法形成 noteworthy，缺什麼

**9 個 CONTEXT candidate，全部缺 `second_supporting`。**

缺的原因對這 9 個完全相同，記錄在 `missing_reasons.second_supporting`：

> context `VS_LEFT` / `VS_RELIEF` / `VS_RIGHT` 在 Step 9 沒有 3/3 的
> `MULTI_METRIC_PATTERN`（三個指標與季累計比較的方向不一致），
> 且官方分項沒有時間維度所以沒有 rolling percentile（Step 8 已記錄）。
> 因此找不到第二種不同性質的支持 evidence。

三個 context 的方向組合（Step 9 的 `context_direction_log`）：

| context | AVG | OBP | SLG | consistency |
| --- | --- | --- | --- | --- |
| VS_LEFT | ABOVE | ABOVE | BELOW | 2/3 |
| VS_RELIEF | BELOW | BELOW | ABOVE | 2/3 |
| VS_RIGHT | BELOW | BELOW | ABOVE | 2/3 |

它們**都有** `phenomenon` 與 `sample_context`，只差第三塊。

### 要讓它們變成 noteworthy 需要什麼

需要一個「不同性質的第二種 evidence」，而目前資料拿不出來：

- rolling percentile → 需要官方分項有時間維度（Step 8 確認沒有）
- 其他維度的一致性 → 需要交叉分項（例如「面對左投的先發」），
  Step 8 已記錄官方只提供單維度切分，無法交叉

也就是說**這 9 個的 blocked 原因是資料結構，不是數值不夠大**。

---

## 5. 是否有 candidate 因為樣本小而被淘汰

**沒有。**

| 證據 | 內容 |
| --- | --- |
| `not_eligible` 數量 | **0** |
| 樣本最小的 candidate | `CONTEXT-…-VS_CLOSER-AVG`，**AB = 27** |
| 它的分類 | **noteworthy** |
| VS_CLOSER 的 4 個 candidate（3 CONTEXT + 1 PATTERN，全部 AB 27） | **全部 noteworthy** |

### 這件事用 mutation test 反證，不只是宣稱

`mutation_test_sample_independence()` 把每個 candidate 的 `at_bats` 與
`plate_appearances` 換成 **1** 與 **9999**（在深拷貝上，不動原始資料），
重跑分類，比對結果。

```
受測 candidate 數 : 29
測試值            : at_bats = [1, 9999]
重新分類次數      : 58
分類改變的筆數    : 0
sample_size 獨立  : True
```

**若程式任何地方把 `at_bats` 與數字比較，改成 1 或 9999 就會改變分類。**
0 次改變證明樣本大小完全沒有進入分類邏輯。

`sample_context` evidence 中另有 `presence_only_note` 欄位明確記錄：
「本項只要求存在。程式沒有把 at_bats 或 plate_appearances 與任何數字比較，
也沒有因為樣本小而降級或淘汰。」

---

## 6. 是否有 threshold / score / ranking 被引入

**沒有。**

### threshold — 用 mutation test 結構性反證

第一版檢查用字眼掃描，結果誤判（見第 9 節）。改成 mutation test：

`mutation_test_value_independence()` 把現象 evidence 的差距換成
**0.0 / −10.0 / +10.0**，把 TREND 的 `percentile_rank` 換成
**0.0 / 50.0 / 100.0**（都在深拷貝上），重跑分類。

```
重新分類次數      : 99
分類改變的筆數    : 0
數值門檻獨立      : True
```

**若程式寫了 `if diff > X` 或 `if percentile > X`，
把差距換成 0.0 或把 percentile 換成 0.0 就會改變分類。**
0 次改變證明分類邏輯沒有把任何數值與常數比較。

加上第 5 節的 sample size mutation test，三個被明確禁止設門檻的量
（AVG 差距、percentile、AB）**全部**通過反證。

### score / weight / rank

遞迴掃描 sidecar 的所有巢狀欄位名：沒有任何 `score`、`weight` 欄位。

`rank` 的處理：`percentile_rank` 與 `rank_desc` 是 **Step 6 建立的 evidence 描述子**
（分布內的經驗百分位與名次），不是 candidate 之間的排名，因此列入白名單。
除此之外沒有任何 rank 欄位。

輸出的分組依 `classification`，組內一律 `candidate_id` 字典序，**不是排名**。

---

## 7. Sidecar schema

每個 record 的欄位：

| 欄位 | 說明 |
| --- | --- |
| `candidate_id` | 關聯用；不寫回 candidate |
| `candidate_type` / `scope` / `metric_or_context` | 識別資訊 |
| `classification` | `observation` / `noteworthy` / `not_eligible`（受控詞彙） |
| `rule_id` | `R17-1-OBS` / `R17-1-NOTE` / `R17-1-NE` |
| `rule_set` | rule_set_id、version、rule_text、**rule_source** |
| `evidence_classes_present` / `evidence_classes_missing` | 三類 evidence 的齊備狀況 |
| `missing_reasons` | 缺什麼、為什麼缺 |
| `supporting_evidence` | 每筆含 evidence_class、evidence_type、statement_fields、provenance |
| `sample_context` | AB / PA / games / sensitivity 的完整內容 |
| `provenance` | 各段 evidence 的來源 Step 與模組、source_files、sidecar 說明 |
| `limitation` | 逐項限制 + rule_version_caveat |
| `contains_no` | 明確宣告不含 score / weight / rank / threshold / statistical_test 等 |

---

## 8. Validation

程式執行 **17 項檢查，全部通過（17 / 17）**。

| # | 檢查 | 結果 |
| --- | --- | --- |
| 1 | 29 個 candidate 全部都有且只對應一個 classification | PASS |
| 2 | candidate 原始 evidence 完全未修改 | PASS　深度比較 29 個物件 |
| 3 | 所有 supporting evidence 都能追溯到既有 Step 資料 | PASS　78 筆，source_step 皆在 Step 5/6/8/9/10/11 |
| 4 | 不存在虛構的 evidence | PASS　逐筆比對回 Step 9 / Step 11 原值 |
| 5 | **沒有 threshold** | PASS　99 次 mutation test 分類不變 |
| 6 | 沒有 score 欄位 | PASS |
| 7 | 沒有 weight 欄位 | PASS |
| 8 | 沒有 rank 欄位 | PASS |
| 9 | 沒有使用 LLM | PASS　AST import 檢查 + `sys.modules` |
| 10 | 沒有任何 HTTP request | PASS　socket guard 生效 |
| 11 | **sample context 沒有被用作淘汰條件** | PASS　58 次 mutation test 分類不變 |
| 12 | 沒有任何 candidate 因樣本小而被淘汰 | PASS　not_eligible = 0；AB 27 的仍是 noteworthy |
| 13 | **RECENT_10-AVG 被分類為 noteworthy** | PASS　三類 evidence 齊備 |
| 14 | 重新執行結果完全一致 | PASS |
| 15 | raw / processed data 未被修改 | PASS |
| 16 | 沒有最終自然語言結論或價值判斷字眼 | PASS |
| 17 | 沒有新增任何 statistical test | PASS |

### 第 4 項的實作方式

不是只檢查欄位存在，而是**逐筆把 evidence 的數值比對回原始物件**：

- `phenomenon` 的 `current_value` / `difference` 必須等於 Step 9 candidate 的對應欄位
- `rolling_window_distribution_position` 的 `percentile_rank` / `distribution_n` /
  `rank_desc` 必須等於 candidate 的 `rolling_percentile`
- `cross_metric_direction_consistency` 必須真的是 3/3（非 3/3 被採用會被抓出）
- `sample_context` 的 `at_bats` / `delta_if_one_more` / `current`
  必須等於 Step 11 sidecar 的值

### hash 記錄

| 檔案 | sha256 前 8 碼 | bytes |
| --- | --- | --- |
| `data/processed/zhang_yucheng_game_logs_2026.json` | `e3712d87` | 30,547 |
| `data/raw/apart_score_0000006888_2026_A_01.json` | `8565cc8c` | 56,826 |

執行前後完全一致。沒有寫出任何檔案到 `data/`。

---

## 9. 開發過程中修正的一個檢查實作錯誤

第一次執行時「沒有 threshold」FAIL，報 `門檻×32`。

**根因：** 檢查用字眼掃描整份序列化字串，而「門檻」這兩個字**只出現在否定敘述中**：

- `known_limitation`：「方向判定也不含任何最小差距門檻。」（16 筆 evidence）
- `limitation.items`：同一段文字被複製進去（16 筆）

16 + 16 = 32，正好對上。也就是說**檢查抓到的是「宣告沒有門檻」這句話本身**。

**修正方式：** 沒有只是把字眼加進白名單放行，而是把主要證明換成**結構性反證**：

1. 新增 `mutation_test_value_independence()`：把差距換成 0.0 / −10.0 / +10.0，
   把 percentile 換成 0.0 / 50.0 / 100.0，共 99 次重新分類，確認分類完全不變。
   這直接證明分類邏輯沒有數值比較，比字眼掃描強得多。
2. 字眼掃描降為輔助，並把 `limitation` / `known_limitation` /
   `presence_only_note` / `different_in_kind_from_phenomenon` 這些**解釋性欄位**
   納入宣告性扣除範圍（與前面幾個 Step 對 `contains_no` 的處理一致）。

**沒有改動任何資料、分類結果或規則。** 修正前後 29 個 candidate 的分類完全相同。

---

## 10. 這次實驗暴露的三個問題

以下是套用規則後才看得到的事實，**不是結論，也不是規則修改建議**。

### 10.1 規則很寬鬆：20 / 29（69%）被標為 noteworthy

第一版規則只要求三類 evidence「存在」，不看大小。
結果超過三分之二的 candidate 都成為 noteworthy。

如果 noteworthy 的用途是「篩選出值得呈現的少數」，
目前這個比例可能不足以達到篩選效果。這是規則形狀的直接後果。

### 10.2 magnitude 與 classification 完全脫鉤，出現反直覺的組合

因為規則刻意不看差距大小，所以會出現這種情況：

| candidate | 差距 | classification |
| --- | --- | --- |
| `CONTEXT-…-VS_LEFT-SLG` | **−0.10520961** | **observation** |
| `CONTEXT-…-VS_DOMESTIC-AVG` | **−0.02233797** | **noteworthy** |

**差距大約 4.7 倍的那一個被分在較低的類別。**

這是規則設計的必然結果（無門檻 + 第二 evidence 是必要條件），不是 bug。
但它意味著 classification 不能被讀成「重要程度」。

### 10.3 16 個 noteworthy 其實只由 4 組獨立 evidence 支撐

20 個 noteworthy 中有 16 個來自 CONTEXT / PATTERN，
而它們只涉及 4 個 context（VS_CLOSER、VS_DOMESTIC、VS_FOREIGN、VS_STARTER）。

以 VS_CLOSER 為例：`PATTERN-VS_CLOSER` 加上 3 個
`CONTEXT-VS_CLOSER-AVG/OBP/SLG`，共 **4 個 noteworthy**，
全部建立在**同一批 27 個打數**上，而且它們的第二種 evidence 是**同一個** 3/3 pattern。

這延續了 Step 10 與 Step 12 已記錄的「PATTERN 與 CONTEXT 數字重複」問題。
若直接呈現 20 個 noteworthy，使用者會看到大量重複。

---

## 11. 已知限制

1. **`not_eligible` 分支未被驗證。** 0 個 candidate 落入該類，程式有處理但沒有真實案例。
2. **第二種 evidence 只有兩種來源。** 這限制了哪些 candidate 有機會成為 noteworthy，
   而限制的原因是資料結構（官方分項無時間維度、無交叉分項），不是規則本身。
3. **`cross_metric_direction_consistency` 的性質有疑慮。**
   Step 10 已記錄：AVG / OBP / SLG 共用同一批安打與打數，高度相關，
   方向一致有相當程度是數學上的必然。這個限制原樣寫進每筆相關 evidence 的
   `known_limitation` 中。
4. **`rolling_window_distribution_position` 不是機率陳述。**
   Step 6 已記錄：滾動窗口高度重疊（相鄰共用 9 場），彼此不獨立。
5. **noteworthy 不等於統計上成立。** 規則沒有做任何 statistical test。
   每個 noteworthy record 的 `limitation` 第一項就寫明這件事。
6. **只有一名球員、一個球季。** 不同球員的 candidate 組成不同，比例不一定具有一般性。
7. **沒有寫出檔案。** sidecar 只在程式輸出中，與 Step 10 ~ 14 的做法一致。

---

## 12. 本階段刻意沒有做的事

- 沒有設 AVG 差距門檻、percentile 門檻、AB 門檻（以 157 次 mutation test 反證）
- 沒有因為樣本小而淘汰或降級任何 candidate
- 沒有新增任何 statistical test
- 沒有建立 score / weight / rank / threshold / confidence score
- 沒有使用 LLM（AST import 檢查 + `sys.modules` 比對）
- 沒有任何 HTTP request（socket guard 強制保證）
- 沒有產生最終自然語言結論
- 沒有修改 candidate 原始 evidence（sidecar 設計 + 深度比較驗證）
- 沒有修改 `data/raw/` 或 `data/processed/`（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有引用不存在的 Step 15 / 16 / 17 文件當作 evidence 來源
- 沒有為第 10 節暴露的問題自行修改規則
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

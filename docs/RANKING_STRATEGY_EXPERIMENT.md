# Ranking Strategy Experiment（Step 12）

建立日期：2026-08-20
產出腳本：`src/ranking_experiment.py`
前置文件：`docs/CANDIDATE_INSIGHT_DESIGN.md`（Step 9）、
`docs/INSIGHT_RANKING_DESIGN.md`（Step 10）、`docs/EVIDENCE_SAMPLE_ANALYSIS.md`（Step 11）

> ## 這一步是什麼、不是什麼
>
> **是：** 用**完全同一批 29 個 candidate**，實驗三種不同的 ranking philosophy，
> 觀察它們會把哪些 candidate 排到前面。
>
> **不是：**
>
> - **不選出最佳 strategy。** 三種結果與差異留給下一階段討論。
> - 不含 `final_score` / `confidence_score` / `importance_score`
> - 不含任何 weight（沒有 `a*x + b*y` 這種合成）
> - 不含任何 threshold
> - 不做統計顯著性宣稱
> - 不產生自然語言結論、不使用 LLM、不做 recommendation、不做預測

---

## 1. 共同輸入與約束

三種 strategy 使用**完全同一批 29 個 candidate**（Step 9 產出），
以及 Step 10 / Step 11 已建立的描述子。

| 約束 | 落實方式 |
| --- | --- |
| 不新增資料 | 只讀兩個既有本地檔案 |
| 不重新抓 CPBL | socket guard 封鎖連線（Step 9 起沿用） |
| 不改 candidate evidence | 排序用的是唯讀 view，`copy.deepcopy` + 深度比較驗證 |
| 不修改 raw / processed data | 執行前後 sha256 比對 |

排序方式一律是 **deterministic lexicographic ordering**（字典序 tuple 比較），
不是加權分數。每個鍵只在前一個鍵完全相同時才被讀取，鍵之間沒有任何係數或換算。

### magnitude 的定義（三種 strategy 共用）

| candidate 類型 | magnitude |
| --- | --- |
| TREND | `abs(absolute_difference)` |
| CONTEXT | `abs(difference_from_season)` |
| MULTI_METRIC_PATTERN | **三個指標中 `abs(difference_from_season)` 最大的那一個** |

PATTERN 取最大值是一個**明確的選擇**，不是唯一的選擇。
它有一個直接的副作用：**PATTERN 的 magnitude 必然與它對應的某一個 CONTEXT candidate
完全相同**（本次 4 個 PATTERN 的 magnitude 都等於同 context 的 SLG candidate）。
這造成了 4 組精確平手，在 Strategy B 中由 `consistency_count` 是否可用來決勝。
這件事延續了 Step 10 記錄的「PATTERN 與 CONTEXT 數字重複」問題。

---

## 2. Strategy A — Product-first

### philosophy

先遵守 Step 10 已記錄的產品偏好 tier（TREND → MULTI_METRIC_PATTERN → CONTEXT），
只在同一 tier 內才比較 evidence descriptors。

### lexicographic key（完整記錄）

```
1. priority_tier            升冪（1 → 2 → 3）
2. magnitude                降冪（同 tier 內才生效）
3. sample_size_at_bats      降冪
4. candidate_id             字典序升冪（最終決勝，保證全序）
```

沒有 percentile_rank，因此本 strategy 沒有 null 問題。

### Rank 1 ~ 10

| # | candidate_id | type | metric / context | tier | magnitude | percentile | AB |
| ---: | --- | --- | --- | ---: | --- | --- | ---: |
| 1 | `TREND-…-RECENT_10-AVG` | TREND | batting_average | 1 | 0.09340659 | 94.1176 | 42 |
| 2 | `TREND-…-RECENT_10-SLG` | TREND | slugging_percentage | 1 | 0.08791209 | 72.0588 | 42 |
| 3 | `TREND-…-RECENT_15-SLG` | TREND | slugging_percentage | 1 | 0.03113553 | 46.0317 | 58 |
| 4 | `TREND-…-RECENT_15-AVG` | TREND | batting_average | 1 | 0.01623090 | 61.9048 | 58 |
| 5 | `PATTERN-…-VS_CLOSER-AVG_OBP_SLG` | PATTERN | VS_CLOSER / AVG+OBP+SLG | 2 | 0.38298738 | null | 27 |
| 6 | `PATTERN-…-VS_FOREIGN-AVG_OBP_SLG` | PATTERN | VS_FOREIGN / AVG+OBP+SLG | 2 | 0.05886447 | null | 100 |
| 7 | `PATTERN-…-VS_STARTER-AVG_OBP_SLG` | PATTERN | VS_STARTER / AVG+OBP+SLG | 2 | 0.03553114 | null | 180 |
| 8 | `PATTERN-…-VS_DOMESTIC-AVG_OBP_SLG` | PATTERN | VS_DOMESTIC / AVG+OBP+SLG | 2 | 0.03402570 | null | 173 |
| 9 | `CONTEXT-…-VS_CLOSER-SLG` | CONTEXT | VS_CLOSER / SLG | 3 | 0.38298738 | null | 27 |
| 10 | `CONTEXT-…-VS_CLOSER-AVG` | CONTEXT | VS_CLOSER / AVG | 3 | 0.16320716 | null | 27 |

（`candidate_id` 前綴 `ZHANGYUCHENG-2026-A-` 省略。）

Top 10 的組成：4 個 TREND（tier 1 全部）+ 4 個 PATTERN（tier 2 全部）+ 2 個 CONTEXT。
也就是 tier 1 與 tier 2 的 8 個 candidate 必然全部進前 8 名，
Top 10 只剩 2 個位置給 21 個 CONTEXT。

---

## 3. Strategy B — Magnitude-first

### philosophy

先看差距大小。`percentile_rank` 與 `consistency_count` 只在 magnitude 完全相同時
才會被讀取。

### lexicographic key（完整記錄）

```
1. magnitude                     降冪
2. percentile_rank 是否可用      可用者優先（僅在第 1 鍵相同時生效）
3. percentile_rank               降冪（僅在兩者都可用時比較）
4. consistency_count 是否可用    可用者優先
5. consistency_count             降冪（僅在兩者都可用時比較）
6. candidate_id                  字典序升冪
```

### null 的處理（重要）

CONTEXT 與 PATTERN 的 `percentile_rank` 為 `null`（25 個 candidate）。

處理方式：**先放一個「是否可用」的旗標，再放數值。**
旗標先把有值與無值分成兩群，數值鍵只在同一群內比較。
因此 `null` 永遠不會與真實 percentile 比大小，**也沒有被當成 0 或任何補值**。

這件事有被實際反證，不只是宣稱。程式另外實作了一個
**嚴格 comparator**：任何時候試圖對 `None` 做數值比較就直接拋 `NullComparisonError`。
用它重跑排序，結果與 tuple 排序**完全相同**（驗證第 13 項）。
若 null 曾被當成數值參與比較，這個 comparator 就會爆掉。

### Rank 1 ~ 10

| # | candidate_id | type | metric / context | magnitude | percentile | consistency | AB |
| ---: | --- | --- | --- | --- | --- | ---: | ---: |
| 1 | `PATTERN-…-VS_CLOSER-AVG_OBP_SLG` | PATTERN | VS_CLOSER / AVG+OBP+SLG | **0.38298738** | null | 3 | 27 |
| 2 | `CONTEXT-…-VS_CLOSER-SLG` | CONTEXT | VS_CLOSER / SLG | **0.38298738** | null | null | 27 |
| 3 | `CONTEXT-…-VS_CLOSER-AVG` | CONTEXT | VS_CLOSER / AVG | 0.16320716 | null | null | 27 |
| 4 | `CONTEXT-…-VS_CLOSER-OBP` | CONTEXT | VS_CLOSER / OBP | 0.14506048 | null | null | 27 |
| 5 | `CONTEXT-…-VS_LEFT-SLG` | CONTEXT | VS_LEFT / SLG | 0.10520961 | null | null | 54 |
| 6 | `TREND-…-RECENT_10-AVG` | TREND | batting_average | 0.09340659 | 94.1176 | null | 42 |
| 7 | `TREND-…-RECENT_10-SLG` | TREND | slugging_percentage | 0.08791209 | 72.0588 | null | 42 |
| 8 | `CONTEXT-…-VS_RELIEF-SLG` | CONTEXT | VS_RELIEF / SLG | 0.05977356 | null | null | 66 |
| 9 | `PATTERN-…-VS_FOREIGN-AVG_OBP_SLG` | PATTERN | VS_FOREIGN / AVG+OBP+SLG | 0.05886447 | null | 3 | 100 |
| 10 | `CONTEXT-…-VS_FOREIGN-SLG` | CONTEXT | VS_FOREIGN / SLG | 0.05886447 | null | null | 100 |

第 1 名與第 2 名的 magnitude 完全相同（0.38298738），由第 4 鍵
（`consistency_count` 是否可用）決勝——PATTERN 有值所以在前。
第 9 名與第 10 名同理（0.05886447）。

**Top 10 中有 4 個是 `VS_CLOSER`（AB = 27，全部 candidate 中最小樣本）。**

---

## 4. Strategy C — Conservative / Sample-aware

### philosophy

先看 evidence 背後有多少資料。樣本較大的排前面。
**小樣本 candidate 完全保留，只是排在後面**——沒有被刪除、沒有被過濾、沒有最低 AB 門檻。

### lexicographic key（完整記錄）

```
1. sample_size_at_bats            降冪
2. plate_appearances              降冪
3. delta_if_one_more 是否可用     可用者優先
4. delta_if_one_more              升冪（僅在兩者都可用時比較；影響量較小者優先）
5. magnitude                      降冪
6. candidate_id                   字典序升冪
```

`sample_size` **沒有**被轉換成任何分數或折扣係數，它只是第 1 個排序鍵。

### Rank 1 ~ 10

| # | candidate_id | type | metric / context | AB | PA | delta_if_one_more | magnitude |
| ---: | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | `CONTEXT-…-VS_RIGHT-OBP` | CONTEXT | VS_RIGHT / OBP | 219 | 258 | 0.00387597 | 0.00002422 |
| 2 | `CONTEXT-…-VS_RIGHT-AVG` | CONTEXT | VS_RIGHT / AVG | 219 | 258 | 0.00456621 | 0.00085303 |
| 3 | `CONTEXT-…-VS_RIGHT-SLG` | CONTEXT | VS_RIGHT / SLG | 219 | 258 | 0.00456621 | 0.02594209 |
| 4 | `CONTEXT-…-VS_STARTER-OBP` | CONTEXT | VS_STARTER / OBP | 180 | 209 | 0.00478469 | 0.02271232 |
| 5 | `CONTEXT-…-VS_STARTER-SLG` | CONTEXT | VS_STARTER / SLG | 180 | 209 | 0.00555556 | 0.03553114 |
| 6 | `PATTERN-…-VS_STARTER-AVG_OBP_SLG` | PATTERN | VS_STARTER / AVG+OBP+SLG | 180 | 209 | 0.00555556 | 0.03553114 |
| 7 | `CONTEXT-…-VS_STARTER-AVG` | CONTEXT | VS_STARTER / AVG | 180 | 209 | 0.00555556 | 0.02753358 |
| 8 | `CONTEXT-…-VS_DOMESTIC-OBP` | CONTEXT | VS_DOMESTIC / OBP | 173 | 202 | 0.00495050 | 0.02688738 |
| 9 | `CONTEXT-…-VS_DOMESTIC-AVG` | CONTEXT | VS_DOMESTIC / AVG | 173 | 202 | 0.00578035 | 0.02233797 |
| 10 | `CONTEXT-…-VS_DOMESTIC-SLG` | CONTEXT | VS_DOMESTIC / SLG | 173 | 202 | 0.00578035 | 0.03402570 |

Top 10 全部是 `season_cumulative` 粒度，且全部來自 3 個最大樣本的 context
（VS_RIGHT 219、VS_STARTER 180、VS_DOMESTIC 173）。

**第 1 名的 magnitude 是 0.00002422，是全部 29 個 candidate 中最小的。**
這是這個排序哲學的直接後果：它按資料量排，不按差距排。

TREND 在這個 strategy 中掉到第 19 ~ 25 名（AB 只有 42 與 58）。

---

## 5. 排序鍵作用診斷

每一組相鄰名次都可以問「是第幾個鍵決定了先後」。
28 組相鄰名次的統計如下（合計必須等於 28，已列為驗證項）：

| Strategy | 鍵 1 | 鍵 2 | 鍵 3 | 鍵 4 | 鍵 5 | 鍵 6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 2 | **26** | 0 | 0 | — | — |
| B | **24** | 0 | 0 | 4 | 0 | 0 |
| C | 8 | 0 | 0 | **10** | 6 | 4 |

### 三個值得記錄的發現

**（1）Strategy B 的 `percentile_rank` 完全沒有影響任何排序（0 組）。**

這個 strategy 名義上考慮 magnitude + percentile + consistency，
但實際上 magnitude 就決定了 24 組，剩下 4 組由 `consistency_count` 是否可用決定。
`percentile_rank` 從頭到尾沒有被讀取來決勝過。

原因是 magnitude 幾乎兩兩不同（唯一的 4 組平手來自 PATTERN 與 CONTEXT 的定義重複，
而那 4 組雙方的 percentile 都是 null）。
**也就是說「Magnitude-first 也考慮百分位」這個描述，在本次資料下並不成立。**

**（2）Strategy A 的 `sample_size_at_bats` 也完全沒有作用（0 組）。**

tier + magnitude 已經決定了全部 28 組。

**（3）Strategy C 中 `delta_if_one_more` 決定了最多組（10 組）。**

因為同一個 context 內的三個指標 AB 相同，`delta` 成為主要的區分鍵。
效果是 OBP 會排在同 context 的 AVG / SLG 之前（OBP 的分母較大，delta 較小）。
這個效果不是刻意設計的，是排序鍵組合的副產物。

### 這個診斷本身抓到了一個實作錯誤

第一次執行時，Strategy C 的計數合計是 24 而不是 28。
原因是文件記錄的排序鍵只列了 5 項，而實際 tuple 有 6 個位置
（少列了「delta 是否可用」的旗標），導致位置對照錯位。

修正方式：把旗標補進文件記錄的鍵清單，並新增兩項驗證——
「文件記錄的鍵數量 == 實作 tuple 長度」與「診斷計數合計 == 相鄰組數」。
**這是修正文件與實作的不一致，沒有改動任何排序行為或資料**
（`key_c` 函式本身從頭到尾沒有改）。

---

## 6. Rank Changes

### 6.1 三種方法都進 Top 10 的 candidate

**0 個。**

29 個 candidate 中，沒有任何一個在三種排序哲學下都進前 10。
這是本階段最重要的觀察：**排序哲學的選擇會完全改變呈現給使用者的內容。**

### 6.2 只有某一種方法進 Top 10

| Strategy | 數量 | candidate（A / B / C 的名次） |
| --- | ---: | --- |
| A_PRODUCT_FIRST | 3 | `TREND-…-RECENT_15-SLG`（3 / 17 / 19）、`TREND-…-RECENT_15-AVG`（4 / 23 / 20）、`PATTERN-…-VS_DOMESTIC`（8 / 15 / 11） |
| B_MAGNITUDE_FIRST | 4 | `CONTEXT-…-VS_CLOSER-OBP`（11 / 4 / 26）、`CONTEXT-…-VS_LEFT-SLG`（12 / 5 / 22）、`CONTEXT-…-VS_RELIEF-SLG`（13 / 8 / 17）、`CONTEXT-…-VS_FOREIGN-SLG`（14 / 10 / 13） |
| C_SAMPLE_AWARE | 9 | `VS_RIGHT` 的 OBP / AVG / SLG（29,27,21 / 29,27,20 / 1,2,3）、`VS_STARTER` 的 AVG / OBP / SLG（19,22,17 / 18,21,14 / 7,4,5）、`VS_DOMESTIC` 的 AVG / OBP / SLG（23,20,18 / 22,19,16 / 9,8,10） |

Strategy C 有 9 個獨占，是三者中最多的——因為它的排序邏輯與另外兩者最不相關。

### 6.3 排名差異最大的 candidate

| candidate_id | A | B | C | spread |
| --- | ---: | ---: | ---: | ---: |
| `CONTEXT-…-VS_RIGHT-OBP` | 29 | 29 | **1** | **28** |
| `PATTERN-…-VS_CLOSER-AVG_OBP_SLG` | 5 | **1** | 28 | **27** |
| `CONTEXT-…-VS_CLOSER-AVG` | 10 | 3 | **29** | **26** |
| `CONTEXT-…-VS_CLOSER-SLG` | 9 | 2 | 27 | 25 |
| `CONTEXT-…-VS_RIGHT-AVG` | 27 | 27 | 2 | 25 |
| `TREND-…-RECENT_10-AVG` | **1** | 6 | 24 | 23 |
| `TREND-…-RECENT_10-SLG` | 2 | 7 | 25 | 23 |
| `CONTEXT-…-VS_CLOSER-OBP` | 11 | 4 | 26 | 22 |
| `TREND-…-RECENT_15-AVG` | 4 | 23 | 20 | 19 |
| `CONTEXT-…-VS_RIGHT-SLG` | 21 | 20 | 3 | 18 |
| `CONTEXT-…-VS_STARTER-OBP` | 22 | 21 | 4 | 18 |
| `CONTEXT-…-VS_LEFT-SLG` | 12 | 5 | 22 | 17 |

最大 spread 是 28，等於名次全距（29 − 1）。

三個最極端的例子（**只描述排序結果，不判斷哪個是對的**）：

- `CONTEXT-VS_RIGHT-OBP`：Strategy C 第 **1** 名，A 與 B 都是第 **29** 名（最後一名）。
  它有最大樣本（AB 219）與最小 magnitude（0.00002422）。
- `PATTERN-VS_CLOSER`：Strategy B 第 **1** 名，Strategy C 第 **28** 名。
  它有最大 magnitude（0.38298738）與最小樣本（AB 27）。
- `TREND-RECENT_10-AVG`：Strategy A 第 **1** 名，Strategy C 第 **24** 名。

這三個 candidate 的排名幾乎完全相反，而它們用的是同一批數字。

### 6.4 Top 10 的類型組成

| Strategy | TREND | PATTERN | CONTEXT |
| --- | ---: | ---: | ---: |
| A | 4 | 4 | 2 |
| B | 2 | 2 | 6 |
| C | 0 | 1 | 9 |

| Strategy | `recent_games` | `season_cumulative` |
| --- | ---: | ---: |
| A | 4 | 6 |
| B | 2 | 8 |
| C | **0** | **10** |

Strategy C 的 Top 10 完全沒有 `recent_games` 粒度的 candidate。
如果 MVP 的第一個問題是「球隊/球員目前近況」，這個結果值得放進下一階段討論。

---

## 7. 觀察與已知問題

以下只記錄問題，**不自行發明替代公式**。

### 7.1 三種 strategy 的 Top 10 沒有交集

這意味著「要呈現哪些 insight」幾乎完全由排序哲學決定，而不是由資料決定。
在選定 philosophy 之前，任何 Top-N 呈現都是任意的。

### 7.2 magnitude 與 sample size 在本次資料中呈反向關係

`VS_CLOSER`（AB 27）有最大的 magnitude，`VS_RIGHT`（AB 219）有最小的 magnitude。
這不是巧合而是結構性的：小樣本的比率本來就更容易偏離整體（Step 11 已量化，
27 個打數的單一事件影響量是 219 個打數的 8 倍）。

因此 Strategy B 與 Strategy C 幾乎必然給出接近相反的順序。
**這是一個結構性衝突，不是可以用權重調和的問題。**

### 7.3 PATTERN 的 magnitude 定義造成人為平手

PATTERN 取三個指標的最大差距，結果必然等於某一個 CONTEXT sibling 的 magnitude。
本次 4 個 PATTERN 全部如此。這讓 Strategy B 的前兩名變成同一個 context 的
PATTERN 與 CONTEXT-SLG 並列，資訊上是重複的。

可能的處理方向（**未實作、未選擇**）：改用三個差距的其他統計量、
或在呈現層對同一 context 去重。兩者都需要你決定。

### 7.4 Strategy B 的名稱與行為不符

如第 5 節（1）所述，`percentile_rank` 完全沒有作用。
若要讓 percentile 真的參與，就必須把它提到 magnitude 之前，
或建立某種合成——而後者正是本階段禁止的加權。
**這個矛盾記錄在此，沒有自行發明解法。**

### 7.5 Strategy C 讓 TREND 全部落榜

TREND 的樣本量（42 / 58）天生小於大 context（173 ~ 219），
所以「按樣本量排序」會系統性地把時間維度的 candidate 推到後面。
這與 Step 10 的產品假設（TREND 為 tier 1）直接衝突。

### 7.6 Top 10 只是呈現切點

三種 strategy 都對全部 29 個 candidate 排序，**沒有任何 candidate 被排除**。
Top 10 是輸出時的切點，不是過濾器。這一點已列為驗證項。

### 7.7 只有一名球員、一個球季

29 個 candidate 全部來自張育成 2026 年。
不同球員、不同球季的 candidate 數量與分布可能完全不同，
因此本次觀察到的 strategy 差異不一定具有一般性。

---

## 8. Validation

程式執行 **17 項檢查，全部通過（17 / 17）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 1 | 三種 strategy 都使用完全相同的 29 個 candidate | PASS　id 集合相同 |
| 2 | 2 | 每種 strategy 都產生完整且**嚴格全序**的 ordering | PASS　1~29 連續、無並列、無重複 |
| 3 | 3 | 三種的 Top 10 全部存在於原始 candidate 清單 | PASS　30 筆全部可對應 |
| 4 | 4 | candidate evidence 完全未被修改 | PASS　深度比較 29 個物件 |
| 5 | 4 | 排序使用的描述子皆為 candidate 原值 | PASS　逐欄位比對 |
| 6 | 5 | 沒有任何 HTTP request | PASS　socket guard 生效 |
| 7 | 6 | raw / processed data hash 不變 | PASS |
| 8 | 7 | 沒有 final_score / 任何 score 欄位 | PASS　遞迴掃描所有巢狀欄位名 |
| 9 | 8 | 沒有 weight 欄位或加權合成 | PASS |
| 10 | 10 | 沒有 confidence score | PASS |
| 11 | 9 | 沒有 threshold | PASS　三種各排 29 個，全部入榜 |
| 12 | 11 | 沒有自然語言結論或價值判斷字眼 | PASS |
| 13 | 12 | **null percentile 沒有被當成 0** | PASS　以嚴格 comparator 反證 |
| 14 | 13 | 重跑與打亂輸入順序後結果完全一致 | PASS　六次結果全部相同 |
| 15 | — | 文件記錄的排序鍵數量與實作 tuple 長度一致 | PASS |
| 16 | — | 排序鍵作用診斷的計數合計 == 相鄰名次組數 | PASS　三種各 28 組 |
| 17 | 14 | 每個 ranking result 都帶 `candidate_id` 且可追溯 | PASS　87 筆全部可追溯 |

### 幾項檢查的實作方式

**第 2 項不只檢查名次連續**，還逐一比對相鄰兩筆的排序 tuple 是否**嚴格遞增**，
確認沒有兩個 candidate 的排序鍵完全相同（否則順序會依賴 `sorted` 的穩定性，
而不是規則本身）。

**第 13 項是反證，不是宣稱。** 另外實作一個嚴格 comparator，
遇到 `None` 的數值比較就拋 `NullComparisonError`。用它重跑三種 strategy 的排序，
結果與 tuple 排序完全相同。25 個 candidate 的 `percentile_rank` 是 null，
它們從未參與任何數值比較。

**第 14 項用兩種方式驗證**：同一批 view 重跑一次，
以及用固定 seed 打亂輸入順序後再跑。六次結果全部相同，
證明排序是全序且不依賴輸入順序。

**第 7 項** sha256：
`zhang_yucheng_game_logs_2026.json` = `e3712d87…`、30,547 bytes；
`apart_score_0000006888_2026_A_01.json` = `8565cc8c…`、56,826 bytes。

---

## 9. 交給下一階段討論的問題

本階段**不選出最佳 strategy**。以下是需要你決定的事：

1. **哪一種排序哲學符合球隊數據分析人員的實際需求？** 三種的 Top 10 沒有交集，
   所以這個選擇會完全決定使用者看到什麼。
2. **magnitude 與 sample size 的結構性反向關係要怎麼處理？**（7.2 節）
   這不是權重可以調和的問題。
3. **PATTERN 與 CONTEXT 的重複要不要去重？**（7.3 節）
4. **percentile 要不要真的參與排序？** 若要，它必須被提到 magnitude 之前，
   或需要某種合成（而合成就是加權）。（7.4 節）
5. **TREND 在 Strategy C 中全部落榜，是否可接受？**（7.5 節）
   這與 Step 10 的 tier 假設直接衝突。
6. **是否需要多個 strategy 並存？** 例如讓使用者切換視角，
   而不是由系統選定一種。

---

## 10. 本階段刻意沒有做的事

- 沒有選出最佳 strategy
- 沒有 `final_score` / `confidence_score` / `importance_score`
- 沒有任何 weight 或加權合成
- 沒有任何 threshold（29 個全部排序，Top 10 只是呈現切點）
- 沒有把 null percentile 當成 0 或任何補值
- 沒有做統計顯著性宣稱
- 沒有產生自然語言結論、沒有 LLM、沒有 recommendation、沒有預測
- 沒有 dashboard
- 沒有 HTTP request（socket guard 強制保證）
- 沒有修改 candidate evidence（唯讀 view + 深度比較驗證）
- 沒有修改 `data/raw/` 或 `data/processed/` 的檔案（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有為第 7 節記錄的問題自行發明替代公式
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

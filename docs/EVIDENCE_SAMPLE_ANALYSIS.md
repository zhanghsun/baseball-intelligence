# Evidence Sample Context / Sensitivity 分析（Step 11）

建立日期：2026-08-20
產出腳本：`src/evidence_sample_context.py`
前置文件：`docs/CANDIDATE_INSIGHT_DESIGN.md`（Step 9）、`docs/INSIGHT_RANKING_DESIGN.md`（Step 10）

> ## 這一步是什麼、不是什麼
>
> **是：** 讓系統知道「一個 candidate 的數字背後有多少資料支撐」，
> 以及「比率對單一事件有多敏感」。
>
> **不是：**
>
> - 不是 confidence score，不是 evidence score，不是 reliability score
> - 不是 importance score
> - 不是統計顯著性，不是 p-value
> - 不是門檻（沒有 minimum AB、沒有 minimum PA）
> - 不是篩選機制（29 個 candidate 全部保留）
> - 不是自然語言結論
>
> **29 個 candidate 全部保留。最小樣本的 `VS_CLOSER`（27 個打數）
> 沒有被刪除、沒有被降級、沒有被標記為不可用。**

---

## 1. Why sample size matters

比率型指標（AVG、OBP、SLG）都是「分子 / 分母」。分母越小，單一事件對比率的影響越大。

這是純算術的必然，不需要任何統計假設就能算出來：**AVG 的單一事件影響量正好是 `1 / AB`。**

實測（29 個 candidate 涵蓋 9 個不同的樣本範圍）：

| scope | AB | `1 / AB`（一支安打對 AVG 的影響量） |
| --- | --- | --- |
| VS_CLOSER | 27 | 0.03703704 |
| RECENT_10 | 42 | 0.02380952 |
| VS_LEFT | 54 | 0.01851852 |
| RECENT_15 | 58 | 0.01724138 |
| VS_RELIEF | 66 | 0.01515152 |
| VS_FOREIGN | 100 | 0.01000000 |
| VS_DOMESTIC | 173 | 0.00578035 |
| VS_STARTER | 180 | 0.00555556 |
| VS_RIGHT | 219 | 0.00456621 |

同一個「多一支安打」的事件，在 `VS_CLOSER` 會讓 AVG 動 0.037，
在 `VS_RIGHT` 只動 0.0046，差了 8 倍。

這件事對前面幾個階段的數字有直接影響。舉一個具體例子（**只描述算術，不做判斷**）：

Step 10 記錄過「最大的 magnitude 是 `CONTEXT-VS_CLOSER-SLG` 的 0.38298738」。
而同一個 candidate 的單一事件影響量是 0.03703704。
也就是說那個 magnitude 大約等於 10 個單一事件的量。
這個換算本身不告訴我們該不該重視它，但它是解讀那個數字時必須一起看的資訊。

---

## 2. Sample context（Part 1）

每個 candidate 都有 `sample_context`，記錄：

| 欄位 | TREND | CONTEXT / PATTERN |
| --- | --- | --- |
| `at_bats` | 42 / 58 | 27 ~ 219 |
| `plate_appearances` | 44 / 63 | 31 ~ 258 |
| `games` | 10 / 15 | **`null`** |
| `metric` | 該 candidate 的指標 | 同 |
| `context` | `null`（TREND 無情境切分） | 代碼 + 官方 `ItemName` + 組別 |
| `granularity` | `recent_games` | `season_cumulative` |
| `window_name` | `RECENT_10` / `RECENT_15` | `null` |
| `date_range` | 起訖日期 | `null` |
| `game_snos` | 完整場次清單 | `null` |
| `data_source` | 見下 | 見下 |

`games` 在 CONTEXT / PATTERN 為 `null`，並附 `games_note`：
「官方分項成績沒有出賽場次欄位，因此 games 為 null，不推估」。

### 資料來源明確記錄

每個 candidate 的 `sample_context.data_source` 記錄三件事：

| candidate 類型 | `files` | `origin` | `derivation` |
| --- | --- | --- | --- |
| TREND | `data/processed/zhang_yucheng_game_logs_2026.json` | CPBL 官方 `POST /team/getfollowscore`（Step 2 取得，Step 4 整理） | 依 `(game_date, game_sno)` 升冪排序後取最後 N 場，逐場加總 |
| CONTEXT / PATTERN | `data/raw/apart_score_0000006888_2026_A_01.json` | CPBL 官方 `POST /team/getapartscore`，`ItemGroupCode = 3`（Step 8 取得並快取） | 官方直接提供的球季累計分項，未再加工 |

### 樣本範圍一覽（Part 4：兩種粒度分開呈現）

| type | scope | AB | PA | games | granularity | candidates |
| --- | --- | --- | --- | --- | --- | --- |
| CONTEXT | VS_CLOSER | 27 | 31 | null | `season_cumulative` | 3 |
| MULTI_METRIC_PATTERN | VS_CLOSER | 27 | 31 | null | `season_cumulative` | 1 |
| **TREND** | **RECENT_10** | **42** | **44** | **10** | **`recent_games`** | **2** |
| CONTEXT | VS_LEFT | 54 | 62 | null | `season_cumulative` | 3 |
| **TREND** | **RECENT_15** | **58** | **63** | **15** | **`recent_games`** | **2** |
| CONTEXT | VS_RELIEF | 66 | 80 | null | `season_cumulative` | 3 |
| CONTEXT | VS_FOREIGN | 100 | 118 | null | `season_cumulative` | 3 |
| MULTI_METRIC_PATTERN | VS_FOREIGN | 100 | 118 | null | `season_cumulative` | 1 |
| CONTEXT | VS_DOMESTIC | 173 | 202 | null | `season_cumulative` | 3 |
| MULTI_METRIC_PATTERN | VS_DOMESTIC | 173 | 202 | null | `season_cumulative` | 1 |
| CONTEXT | VS_STARTER | 180 | 209 | null | `season_cumulative` | 3 |
| MULTI_METRIC_PATTERN | VS_STARTER | 180 | 209 | null | `season_cumulative` | 1 |
| CONTEXT | VS_RIGHT | 219 | 258 | null | `season_cumulative` | 3 |

上表依 AB 由小到大排列，**這只是呈現順序，不是排名**。
兩種 granularity 在表中並列只是為了看樣本量大小，
不代表它們的 magnitude 可以互相比較（Step 10 已記錄 `cross_granularity_comparison_allowed = false`）。

---

## 3. Sensitivity methodology（Part 2 / Part 3）

### 方法

把比率拆回分子與分母，看**分子加 1** 與**分子減 1** 會讓比率變成多少。
分母固定不變。

```
current           = numerator / denominator
one_more_success  = (numerator + 1) / denominator
one_fewer_success = (numerator - 1) / denominator
delta_if_one_more  = one_more_success  - current   （= +1 / denominator）
delta_if_one_fewer = one_fewer_success - current   （= -1 / denominator）
```

**這是純算術。沒有機率模型、沒有分布假設、沒有信賴區間、沒有 p-value。**

### 為什麼分母固定

三個指標的「一次成功」都是把一個出局換成一次成功，而出局本來就已經計入分母：

| metric | 分子 | 分母 | 一次成功的意義 |
| --- | --- | --- | --- |
| AVG | `hits` | `at_bats` | 一支安打（把一個出局換成一支安打，打數不變） |
| SLG | `total_bases` | `at_bats` | **一個壘打數**（不是一支安打） |
| OBP | `hits + walks + hit_by_pitch` | `at_bats + walks + hit_by_pitch + sacrifice_flies` | 一次上壘（把一個出局換成一次上壘，分母不變） |

**SLG 的成功單位要特別注意。** SLG 的分子是壘打數，所以「加 1」代表多一個壘打數，
不是多一支安打。一支安打可能帶來 1 到 4 個壘打數，
因此 SLG 的實際單一事件影響可能是 `1/AB` 的 1 ~ 4 倍。
每個 SLG sensitivity 記錄的 `success_unit` 欄位都寫明了這件事。

### 分子分母不足時回傳 null，不估算（Part 3）

| candidate 類型 | AVG | SLG | OBP |
| --- | --- | --- | --- |
| TREND | 可算 | 可算 | **`null`** |
| CONTEXT | 可算 | 可算 | 可算 |
| MULTI_METRIC_PATTERN | 可算 | 可算 | 可算 |

TREND 的 OBP 為 `null`，`unavailable_reason` 記錄：
「processed data 未收逐場犧牲飛球，OBP 分母無法組出。依規則回傳 null，不估算。」

這是 Step 4 欄位取捨的延續。可以取的做法是回頭把 `SacrificeFlyCnt` 收進 processed data，
但那是資料層的變更，不在本階段範圍。

分子為 0 時 `one_fewer_success` 也回傳 `null`（分子不可為負），
並附 `one_fewer_note`。**本次 29 個 candidate 都沒有觸發這個情況**，
所以這條分支沒有被實際資料驗證到（見第 5 節）。

### 不同粒度不混用（Part 4）

- TREND 的分子分母來自**重建的 Recent 10 / Recent 15 窗口**
  （用 Step 9 同一個 `build_window()`，不引入新資料）
- CONTEXT / PATTERN 的分子分母來自**官方球季累計分項**

驗證有一項專門檢查粒度沒有混用：TREND 必須有 `game_snos`，
CONTEXT / PATTERN 必須沒有。

---

## 4. Examples

### 4.1 VS_CLOSER（最小樣本，27 個打數）

**AVG：4 H / 27 AB**

| | 分子 / 分母 | 值 | delta |
| --- | --- | --- | --- |
| one_fewer_success | 3 / 27 | **0.11111111** | −0.03703704 |
| **current** | **4 / 27** | **0.14814815** | — |
| one_more_success | 5 / 27 | **0.18518519** | +0.03703704 |

**OBP：8 / 31**（= (4 H + 4 BB + 0 HBP) / (27 AB + 4 BB + 0 HBP + 0 SF)）

| | 分子 / 分母 | 值 | delta |
| --- | --- | --- | --- |
| one_fewer_success | 7 / 31 | 0.22580645 | −0.03225806 |
| **current** | **8 / 31** | **0.25806452** | — |
| one_more_success | 9 / 31 | 0.29032258 | +0.03225806 |

**SLG：4 TB / 27 AB**（4 支安打全是一壘安打，所以 TB = H）

| | 分子 / 分母 | 值 | delta |
| --- | --- | --- | --- |
| one_fewer_success | 3 / 27 | 0.11111111 | −0.03703704 |
| **current** | **4 / 27** | **0.14814815** | — |
| one_more_success | 5 / 27 | 0.18518519 | +0.03703704 |

> ### 這段話必須講清楚
>
> 上面的數字**不是在說這個 candidate 不可用、不可靠、或應該被忽略**。
>
> 它在說的是一件算術上的事實：
>
> **在 27 個打數的樣本下，比率對單一事件較敏感。**
>
> 這個 candidate 被完整保留，有完整的 tier（Step 10 的 tier 3）、
> 完整的 magnitude、完整的 traceability。
> sensitivity 資訊的用途是讓使用者在看到 0.1481 這個數字時，
> 同時知道它與 0.1111 和 0.1852 只差一個事件。

### 4.2 VS_RIGHT（最大樣本，219 個打數）作為對照

**AVG：68 H / 219 AB**

| | 分子 / 分母 | 值 | delta |
| --- | --- | --- | --- |
| one_fewer_success | 67 / 219 | 0.30593607 | −0.00456621 |
| **current** | **68 / 219** | **0.31050228** | — |
| one_more_success | 69 / 219 | 0.31506849 | +0.00456621 |

同一個「一支安打」，在這裡的影響量是 0.00456621，
是 `VS_CLOSER` 的 0.03703704 的約 1/8。

### 4.3 RECENT_10（TREND，42 個打數）

**AVG：17 H / 42 AB**

| | 分子 / 分母 | 值 | delta |
| --- | --- | --- | --- |
| one_fewer_success | 16 / 42 | 0.38095238 | −0.02380952 |
| **current** | **17 / 42** | **0.40476190** | — |
| one_more_success | 18 / 42 | 0.42857143 | +0.02380952 |

**SLG：26 TB / 42 AB**

| | 分子 / 分母 | 值 | delta |
| --- | --- | --- | --- |
| one_fewer_success | 25 / 42 | 0.59523810 | −0.02380952 |
| **current** | **26 / 42** | **0.61904762** | — |
| one_more_success | 27 / 42 | 0.64285714 | +0.02380952 |

**OBP：`null`** — processed data 未收逐場犧牲飛球。

一個可以直接對照的算術關係：Step 9 記錄 `RECENT_10-AVG` 的
`absolute_difference` 是 +0.09340659（vs 季累計）。
而單一事件影響量是 0.02380952。兩者的比值約為 3.9。
**這個換算不構成任何結論**，只是把 magnitude 放回它自己的樣本尺度來看。

### 4.4 全部 9 個樣本範圍的單一事件影響量

| scope | AB | AVG / SLG 的 `1/AB` | OBP 分母 | OBP 的 `1/分母` |
| --- | --- | --- | --- | --- |
| VS_CLOSER | 27 | 0.03703704 | 31 | 0.03225806 |
| RECENT_10 | 42 | 0.02380952 | — | `null` |
| VS_LEFT | 54 | 0.01851852 | 62 | 0.01612903 |
| RECENT_15 | 58 | 0.01724138 | — | `null` |
| VS_RELIEF | 66 | 0.01515152 | 80 | 0.01250000 |
| VS_FOREIGN | 100 | 0.01000000 | 118 | 0.00847458 |
| VS_DOMESTIC | 173 | 0.00578035 | 202 | 0.00495050 |
| VS_STARTER | 180 | 0.00555556 | 209 | 0.00478469 |
| VS_RIGHT | 219 | 0.00456621 | 258 | 0.00387597 |

---

## 5. Limitations

### 5.1 sensitivity 不是不確定性的完整描述

「分子 ±1」只回答一個很窄的問題：如果剛好多或少一次成功，數字會變多少。

它**沒有**回答：這個數字有多穩定、重複觀測會落在什麼範圍、
差距是不是隨機波動。那些問題需要樣本量檢定或重抽樣，
本階段沒有做（從 Step 8 標記至今仍未做）。

### 5.2 SLG 的成功單位不對等

AVG 與 OBP 的「一次成功」都是一個離散事件（一支安打、一次上壘）。
SLG 的「一個壘打數」不是一個完整事件——一支安打會帶來 1 ~ 4 個壘打數。

因此 SLG 的 `delta_if_one_more` 是**下界**，實際一支安打的影響可能是它的 1 ~ 4 倍。
這件事寫在每個 SLG sensitivity 的 `success_unit` 中，但沒有另外計算上界。

### 5.3 分母固定的假設

計算時假設分母不變（把一個出局換成一次成功）。
如果情境是「多打一個打席並成功」，分母也會 +1，結果會不同。
本階段只採用分母固定的版本，因為那對應「同樣的機會、不同的結果」，
比較貼近「單一事件的影響」這個問題。這是一個明確的建模選擇，不是唯一的選擇。

### 5.4 TREND 的 OBP 完全缺失

4 個 TREND candidate 都沒有 OBP sensitivity。
這讓 TREND 與 CONTEXT 在指標覆蓋上不對稱，延續了 Step 10 記錄的問題。

### 5.5 `one_fewer = null` 分支未被驗證

29 個 candidate 的分子都 ≥ 1，所以「分子為 0 時回傳 null」這條路徑
沒有被實際資料觸發過。程式有處理，但沒有真實案例驗證。

### 5.6 PATTERN 與 CONTEXT 的 sensitivity 完全重複

`PATTERN-VS_CLOSER` 的三個 sensitivity 與
`CONTEXT-VS_CLOSER-AVG/OBP/SLG` 的完全相同（同一批分子分母）。
這延續了 Step 10 記錄的重複計算問題。

### 5.7 沒有寫出檔案

本階段的產出只在程式輸出中，沒有寫入 `data/`。
理由與 Step 10 相同：它仍屬於設計階段的描述，
在下一階段確定會怎麼用之前先不落地。

---

## 6. Why no confidence score

四個理由：

### 6.1 confidence 這個詞會被讀成機率

「confidence 0.6」會讓人以為是「60% 的機率是真的」。
但我們算的是 `1/27 = 0.037`，那是一個影響量，不是機率。
把它包裝成 confidence 會製造一個資料支撐不了的解讀。

### 6.2 把它壓成單一數字會丟掉方向與單位

`VS_CLOSER` 的 AVG sensitivity 是「±0.037，單位是一支安打」。
壓成一個分數之後，「一支安打」這個單位就消失了，
使用者無法再回頭問「那到底是幾支安打的差別」。
而那個問題正是這份分析最有用的部分。

### 6.3 任何轉換函數都是我們自己編的

要把 AB = 27 轉成一個 0 ~ 1 的分數，得選一個函數
（線性？對數？以某個 AB 為基準正規化？）。
每一種選擇都會改變不同 candidate 的相對位置，而目前沒有任何依據可以選。
Step 10 已經因為同樣的理由拒絕建立 final score。

### 6.4 confidence score 會被當成篩選門檻用

一旦有了分數，下一步幾乎必然是「低於 0.5 就不顯示」。
那正是本階段明確禁止的東西。保留原始描述子而不給分數，
可以讓「要不要篩、怎麼篩」這個決定留在它應該被討論的地方。

### 允許建立的（Part 5）

| 允許 | 本階段是否建立 |
| --- | --- |
| `sample_size`（`at_bats`、`plate_appearances`、`games`） | 是 |
| `sample_sensitivity` | 是 |
| `data_completeness` | 是 |
| `traceability` | 是 |

這些全部是 **descriptors**，不是 scores。
每個 sensitivity 記錄都帶一個 `_not_a` 清單，明確宣告它不是
`confidence` / `confidence_score` / `evidence_score` / `reliability_score` /
`importance_score` / `statistical_significance` / `p_value` / `probability`。

---

## 7. How this will be used by future ranking

以下是**可能的使用方式**，不是決定。決定權在你。

### 7.1 作為呈現層的必要伴隨資訊

最保守也最直接的用法：任何時候顯示一個比率，就把 `at_bats` 與
`delta_if_one_more` 一起顯示。使用者自己判斷。

這個用法不需要任何 ranking 設計，也不需要任何新決策，
而且符合 `PROJECT_DESIGN.md` 的「Insight 必須有實際資料證據支持」。

### 7.2 作為 magnitude 的尺度換算

`magnitude / delta_if_one_more` 得到「這個差距相當於幾個單一事件」。
這是一個無單位的比值，而且**同一個 candidate 內部**的換算是有意義的
（分母來自同一個樣本）。

實測值（僅記錄，不排序、不判斷）：

| candidate | magnitude | delta_if_one_more | 比值 |
| --- | --- | --- | --- |
| `TREND-RECENT_10-AVG` | 0.09340659 | 0.02380952 | 3.92 |
| `CONTEXT-VS_CLOSER-AVG` | 0.16320716 | 0.03703704 | 4.41 |
| `CONTEXT-VS_RIGHT-AVG` | 0.00085303 | 0.00456621 | 0.19 |

**注意：跨 candidate 比較這個比值仍然有 Step 10 記錄的粒度問題。**
比值本身無單位，看起來可比，但分子的意義（時間切片 vs 條件切片）不同。

### 7.3 作為排序的第二鍵，而不是第一鍵

如果最後決定要排序，一種可能是：主鍵用 tier 或 magnitude，
`at_bats` 只在需要打破平手時使用。這樣樣本量會影響順序，
但不會變成一個看不見的折扣係數。

### 7.4 明確**不**建議的用法

- 不要把 `delta_if_one_more` 反過來當成「精確度分數」
- 不要用 `at_bats` 設門檻篩掉 candidate
- 不要把 sensitivity 轉換成信賴區間或機率陳述

---

## 8. Validation

程式執行 **17 項檢查，全部通過（17 / 17）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 1 | 29 個 candidate 全部保留 | PASS　records 29，`retained=True` 29 個 |
| 2 | 2 | 沒有 candidate 因 sample size 被過濾 | PASS　最小 AB 27 仍保留，最大 219 |
| 3 | 3 | AVG sensitivity 可由 `hits / at_bats` 重算 | PASS　29 個全部可重算（含 one_more / one_fewer） |
| 4 | 4 | SLG sensitivity 可由 `total_bases / at_bats` 重算 | PASS　29 個全部可重算 |
| 5 | 5 | OBP sensitivity 僅在資料完整時計算 | PASS　TREND 4 個為 `null`，CONTEXT/PATTERN 25 個可重算 |
| 6 | — | CONTEXT 的 OBP sensitivity 與 Step 9 candidate 值相符 | PASS　7 個全部相符 |
| 7 | — | 所有 sensitivity 的 `current` 與 Step 9 candidate 值相符 | PASS　29 個的全部主要指標 |
| 8 | 6 | 沒有 confidence_score / evidence_score / 任何 score 欄位 | PASS　遞迴掃描所有巢狀欄位名 |
| 9 | 7 | 沒有 reliability_score 欄位 | PASS |
| 10 | 8 | 沒有 threshold（含 minimum AB / minimum PA） | PASS |
| 11 | 9 | 沒有統計顯著性宣稱或 p-value | PASS |
| 12 | 10 | 沒有自然語言結論或價值判斷字眼 | PASS |
| 13 | 11 | Step 9 candidate 完全未被改動 | PASS　深度比較 29 個物件 |
| 14 | 12 | raw / processed data hash 不變 | PASS |
| 15 | 13 | 沒有任何 HTTP request | PASS　socket guard 生效 |
| 16 | Part 4 | 兩種 granularity 沒有混用 | PASS |
| 17 | Part 3 | sensitivity 的分子分母直接取自來源計數 | PASS |

### 幾項檢查的實作方式

**第 3 / 4 / 5 項**不是只檢查值存在，而是**用分子分母獨立重算**
`current`、`one_more_success`、`one_fewer_success` 三個值再比對，
容忍度 `1e-12`。

**第 7 項是跨階段交叉核對**：sensitivity 算出的 `current`
必須等於 Step 9 candidate 記錄的 `current_value` / `value` / `metric_values[].value`。
這確認我們沒有在重建分子分母時算出一組不同的數字。

**第 13 項** 與 Step 10 相同的 sidecar 設計：產出是獨立記錄，用 `candidate_id` 關聯，
沒有寫回 candidate 的路徑。程式先 `copy.deepcopy()` 再深度比較。

**第 14 項** sha256：
`zhang_yucheng_game_logs_2026.json` = `e3712d87…`、30,547 bytes；
`apart_score_0000006888_2026_A_01.json` = `8565cc8c…`、56,826 bytes。

**第 10 / 11 / 12 項的字眼掃描**沿用 Step 10 的做法：
把 `_not_a` 與 `contains_no` 這兩個「宣告不含這些東西」的欄位內容扣除後再掃描。
否則 `"confidence"` 這個宣告詞本身會被誤判成違規。

---

## 9. 本階段刻意沒有做的事

- 沒有刪除或降級任何 candidate（29 個全部保留）
- 沒有 minimum AB / minimum PA 門檻
- 沒有 confidence_score / evidence_score / reliability_score / importance_score
- 沒有統計顯著性宣稱、沒有 p-value、沒有信賴區間
- 沒有建立正式 Insight Ranking
- 沒有產生自然語言、沒有 LLM
- 沒有 HTTP request（socket guard 強制保證）
- 沒有修改 Step 9 的 candidate（sidecar 設計 + 深度比較驗證）
- 沒有修改 `data/raw/` 或 `data/processed/` 的檔案（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有把兩種 granularity 混在同一個計算裡
- 沒有為缺失的欄位估算任何值（TREND 的 OBP 一律 `null`）
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

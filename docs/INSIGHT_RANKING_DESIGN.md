# Insight Ranking 結構設計實驗（Step 10）

建立日期：2026-08-20
產出腳本：`src/candidate_priority.py`
前置文件：`docs/CANDIDATE_INSIGHT_DESIGN.md`（Step 9）

> ## 這一步是什麼、不是什麼
>
> **是：** 設計 candidate priority 的**結構**——tier 分組、粒度標記、可靠性描述子、
> 幅度描述子。
>
> **不是：**
>
> - 不是正式的 numeric ranking score
> - 不含 `final_score` / `importance_score` / `reliability_score` / `magnitude_score`
> - 不含任何 weight
> - 不含任何 threshold
> - 不在同一個 tier 內排名
> - 不做統計顯著性宣稱
> - 不產生自然語言結論、不使用 LLM
>
> **tier 的性質：`provisional_product_priority`（暫定的產品假設）。**
> 它不是 statistical importance、不是 evidence strength、不是顯著性、不是預測、
> 不是最終排名。

---

## 1. Problem

Step 9 產出 29 個 candidate，但它們無法放進同一個排序，因為存在結構性的不對稱：

| 面向 | TREND | MULTI_METRIC_PATTERN | CONTEXT |
| --- | --- | --- | --- |
| 數量 | 4 | 4 | 21 |
| 粒度 | 最近 N 場出賽 | 球季累計 | 球季累計 |
| 指標數 | 1 | 3 | 1 |
| 有滾動分布 | 是 | 否 | 否 |
| 有百分位 | 是 | 否 | 否 |
| 可追溯到場次 | 是 | 否 | 否 |
| 有 `consistency_count` | 否 | 是 | 否 |

問題不是「該給多少權重」，而是**這些 candidate 連可比的共同基準都還沒有**。

---

## 2. Why one numeric score is premature

四個具體理由，每一個都可以從現有資料指出來：

### 2.1 分母範圍不同，magnitude 不可比

TREND 的 magnitude 是「最近 42 或 58 個打數 vs 全季 273 個打數」的差距。
CONTEXT 的 magnitude 是「某個情境的整季 vs 全季」的差距。
這兩種差距的統計性質不同：前者是時間切片，後者是條件切片。

具體例子（**只描述數字，不做判斷**）：

| candidate | granularity | AB | magnitude |
| --- | --- | --- | --- |
| `RECENT_10-AVG` | recent_games | 42 | 0.09340659 |
| `CONTEXT-VS_LEFT-SLG` | season_cumulative | 54 | 0.10520961 |

兩個數字量級接近，但一個是「最近 10 場的打擊率偏離」，
另一個是「整季面對左投的長打率偏離」。把它們放進同一個公式比大小，
等於假設這兩件事的意義可以互換。目前沒有任何依據支持這個假設。

### 2.2 百分位只有 TREND 有，CONTEXT 一律是 null

TREND 有 68 個（10 場）或 63 個（15 場）滾動窗口可以定位，
CONTEXT 沒有時間維度，建不出分布。

任何用到 percentile 的公式，套在 CONTEXT 上時都得填一個預設值。
填什麼都是我們自己編的假設，而不是資料告訴我們的。

### 2.3 樣本量差異達 8 倍，但「小樣本該扣多少分」沒有依據

樣本量從 `VS_CLOSER` 的 27 個打數到 `VS_RIGHT` 的 219 個打數。
Step 6 已記錄：一個 10 場滾動窗口是 28 ~ 42 個打數。
也就是 `VS_CLOSER` 整季的樣本量比一個 10 場窗口還小。

但「27 個打數該打幾折」需要樣本量檢定的結果才能回答。
Step 8 已標記這件事沒做，Step 9 也沒做，本階段同樣沒做。
在沒有檢定之前，任何折扣係數都是憑感覺。

### 2.4 candidate 之間不獨立，會重複計分

三組 context 是同一批 320 個打席的三種切法（Step 8 已驗證完備互斥）。
`VS_FOREIGN` 與 `VS_STARTER` 的打席一定有重疊，但官方只給單維度切分，
**重疊量無法量化**。

同時，PATTERN candidate 完全由 CONTEXT candidate 的同一批數字組成：
`PATTERN-VS_FOREIGN` 的三個 difference 就是
`CONTEXT-VS_FOREIGN-AVG/OBP/SLG` 的 difference。

若把 29 個 candidate 一起丟進加總式的排序，同一批打席會被計入多次。

---

## 3. Candidate granularity

每個 candidate 都有明確的 `granularity` 標記，並附一個明確的禁止旗標：

| candidate type | granularity | 數量 |
| --- | --- | --- |
| TREND | `recent_games` | 4 |
| MULTI_METRIC_PATTERN | `season_cumulative` | 4 |
| CONTEXT | `season_cumulative` | 21 |

每筆 priority 記錄都帶：

```json
{
  "granularity": "recent_games",
  "cross_granularity_comparison_allowed": false,
  "granularity_note": "不同 granularity 的 magnitude 不可直接比較：recent_games 的分母是最近 N 場出賽，season_cumulative 的分母是整季。兩者的基準範圍不同。"
}
```

`cross_granularity_comparison_allowed` 一律為 `false`。
驗證第 11 項會檢查這個旗標沒有被改成 `true`。

---

## 4. Candidate types

### tier 對照（Part 1 / Part 5）

| tier | candidate type | granularity | 數量 |
| --- | --- | --- | --- |
| 1 | TREND | `recent_games` | 4 |
| 2 | MULTI_METRIC_PATTERN | `season_cumulative` | 4 |
| 3 | CONTEXT | `season_cumulative` | 21 |

### tier 指派規則

**由 candidate type 直接決定，不看數值、不看樣本量。**

這一點很重要：tier 不是算出來的，是查表得到的。
因此不存在「因為 magnitude 太小所以掉到 tier 3」這種情況，也就不存在門檻。
驗證第 7 項用「29/29 全部被分配 tier」來證明沒有任何 candidate 被篩掉。

### 每筆記錄都聲明 tier 不代表什麼

```json
{
  "priority_basis": "provisional_product_priority",
  "priority_is_not": [
    "statistical_importance",
    "statistical_significance",
    "evidence_strength",
    "importance",
    "prediction",
    "final_rank"
  ]
}
```

---

## 5. Evidence reliability（Part 2）

每個 candidate 有 `reliability_descriptors`，**全部是原始值，沒有 `reliability_score`**：

| 描述子 | TREND | PATTERN | CONTEXT |
| --- | --- | --- | --- |
| `sample_size_at_bats` | 42 / 58 | 27 ~ 180 | 27 ~ 219 |
| `plate_appearances` | 44 / 63 | 31 ~ 209 | 31 ~ 258 |
| `metric_count` | 1 | 3 | 1 |
| `consistency_count` | `null` | 3 | `null` |
| `data_completeness` | 見下 | 見下 | 見下 |

### `data_completeness` 的內容

這是一個**事實描述**，記錄每個 candidate 缺什麼、有什麼：

| 欄位 | TREND | PATTERN | CONTEXT |
| --- | --- | --- | --- |
| `metrics_available` | AVG、SLG（2 個） | AVG、OBP、SLG（3 個） | AVG、OBP、SLG（3 個） |
| `metrics_unavailable` | `["on_base_percentage"]` | `[]` | `[]` |
| `fields_null` | `[]` | `[]` | `["runs"]` |
| `has_game_level_traceability` | `true` | `false` | `false` |
| `has_date_range` | `true` | `false` | `false` |
| `has_rolling_distribution` | `true` | `false` | `false` |

缺失原因也一併記錄：

- TREND 缺 OBP：processed data 未收逐場犧牲飛球（Step 4 的欄位取捨）
- CONTEXT 的 `runs` 為 null：官方分項 response 沒有得分欄位（Step 8 已確認）

**沒有把這些差異換算成任何分數。** `metric_count = 3` 不代表「比 1 好三倍」；
`has_rolling_distribution = false` 不代表要扣分。它們只是描述資料長什麼樣。

---

## 6. Evidence magnitude（Part 3）

依 candidate 類型各自保留原始欄位，**刻意不統一成單一數值**。

### TREND

| 欄位 | 內容 |
| --- | --- |
| `absolute_difference` | 有號差（current − baseline） |
| `absolute_difference_magnitude` | 絕對值 |
| `direction` | `ABOVE` / `BELOW` / `EQUAL` |
| `percentile_rank` | 同尺寸滾動分布中的百分位 |
| `percentile_strict` | 嚴格定義的百分位 |
| `percentile_distribution_n` | 分布的窗口數（68 或 63） |
| `percentile_definition` | 算式文字 |

實際值：

| candidate | abs_diff | direction | percentile_rank | n |
| --- | --- | --- | --- | --- |
| `RECENT_10-AVG` | +0.09340659 | ABOVE | 94.1176 | 68 |
| `RECENT_10-SLG` | +0.08791209 | ABOVE | 72.0588 | 68 |
| `RECENT_15-AVG` | +0.01623090 | ABOVE | 61.9048 | 63 |
| `RECENT_15-SLG` | −0.03113553 | BELOW | 46.0317 | 63 |

### CONTEXT

| 欄位 | 內容 |
| --- | --- |
| `difference_from_season` | 有號差 |
| `absolute_difference` | 絕對值 |
| `direction` | 方向 |
| `percentile_rank` | 一律 `null` |
| `percentile_unavailable_reason` | 「官方分項沒有時間維度，無法建立滾動分布」 |

21 個 CONTEXT 的 `difference_from_season`（依 candidate_id 字典序，**非排名**）：

| context | AVG | OBP | SLG |
| --- | --- | --- | --- |
| VS_CLOSER | −0.16320716 | −0.14506048 | −0.38298738 |
| VS_DOMESTIC | −0.02233797 | −0.02688738 | −0.03402570 |
| VS_FOREIGN | +0.03864469 | +0.04602754 | +0.05886447 |
| VS_LEFT | +0.00345950 | +0.00010081 | −0.10520961 |
| VS_RELIEF | −0.00832501 | −0.00312500 | +0.05977356 |
| VS_RIGHT | −0.00085303 | −0.00002422 | +0.02594209 |
| VS_STARTER | +0.02753358 | +0.02271232 | +0.03553114 |

### MULTI_METRIC_PATTERN

| 欄位 | 內容 |
| --- | --- |
| `difference_from_season` | 三個指標各自的有號差（dict） |
| `consistency_count` / `total_metrics` | 3 / 3 |
| `direction` | 一致的方向 |
| `percentile_rank` | 一律 `null` |

| pattern | direction | AB | AVG diff | OBP diff | SLG diff |
| --- | --- | --- | --- | --- | --- |
| VS_CLOSER | BELOW | 27 | −0.16320716 | −0.14506048 | −0.38298738 |
| VS_DOMESTIC | BELOW | 173 | −0.02233797 | −0.02688738 | −0.03402570 |
| VS_FOREIGN | ABOVE | 100 | +0.03864469 | +0.04602754 | +0.05886447 |
| VS_STARTER | ABOVE | 180 | +0.02753358 | +0.02271232 | +0.03553114 |

### 這些數值是複製，不是重算

priority 記錄中的所有幅度數值都是從 Step 9 candidate **直接複製**過來的。
驗證有一項專門檢查這件事（逐欄位比對 `absolute_difference`、`percentile_rank`、
`difference_from_season`、`at_bats`、`plate_appearances`），確認沒有被重算或修改。

---

## 7. Provisional product priority

### tier 依據（產品假設，非統計結論）

| tier | 依據 |
| --- | --- |
| 1 — TREND | 直接對應「球員目前近況」這個 MVP 問題，且具備時間維度與滾動分布。這是產品層面的假設：分析人員最先想知道的是近況。 |
| 2 — MULTI_METRIC_PATTERN | 由三個指標同方向構成，資訊密度較高，但沒有時間維度。放在 TREND 之後是產品假設，不是統計判斷。 |
| 3 — CONTEXT | 單一指標的球季累計切分，數量最多（21 個），且沒有時間維度與滾動分布。放最後是產品假設，不代表資訊價值低。 |

### Part 6：同 tier 內不排名

每筆記錄的 `intra_tier_rank` 都是 `null`，並帶說明：

```json
{
  "intra_tier_rank": null,
  "intra_tier_rank_note": "本階段刻意不在同一 tier 內排名。同 tier 內只有分組，沒有先後。"
}
```

輸出時同 tier 內按 `candidate_id` 字典序排列，並在輸出中明確標示
「排列順序為 candidate_id 字典序，不代表任何優先高低」。
驗證有一項檢查 29 個 `intra_tier_rank` 全為 `null`。

### Tier grouping

**Tier 1**（4 個，TREND，`recent_games`）

```
TREND-ZHANGYUCHENG-2026-A-RECENT_10-AVG
TREND-ZHANGYUCHENG-2026-A-RECENT_10-SLG
TREND-ZHANGYUCHENG-2026-A-RECENT_15-AVG
TREND-ZHANGYUCHENG-2026-A-RECENT_15-SLG
```

**Tier 2**（4 個，MULTI_METRIC_PATTERN，`season_cumulative`）

```
PATTERN-ZHANGYUCHENG-2026-A-VS_CLOSER-AVG_OBP_SLG
PATTERN-ZHANGYUCHENG-2026-A-VS_DOMESTIC-AVG_OBP_SLG
PATTERN-ZHANGYUCHENG-2026-A-VS_FOREIGN-AVG_OBP_SLG
PATTERN-ZHANGYUCHENG-2026-A-VS_STARTER-AVG_OBP_SLG
```

**Tier 3**（21 個，CONTEXT，`season_cumulative`）

7 個 context（VS_CLOSER、VS_DOMESTIC、VS_FOREIGN、VS_LEFT、VS_RELIEF、VS_RIGHT、
VS_STARTER）× 3 個指標（AVG、OBP、SLG）。

---

## 8. Limitations

### 8.1 三件必須講清楚的事

**「3/3 metric consistency 不等於 importance。」**

`consistency_count = 3` 只代表三個指標與季累計的比較方向相同。它不代表訊號更強，
理由有兩個：AVG、OBP、SLG 三個指標**共用同一批安打與打數**，本身高度相關，
方向一致有相當程度是數學上的必然，不是獨立證據的疊加；
而且方向判定不含任何最小差距門檻，`VS_RIGHT` 的 OBP 只差 −0.00002422 仍記為 `BELOW`
（它剛好因此沒有形成 pattern，但同樣的微小差距在別的 context 也可能湊成 3/3）。

**「大 magnitude 不等於 high priority。」**

最大的 magnitude 是 `CONTEXT-VS_CLOSER-SLG` 的 0.38298738，
而它的樣本量是全部 candidate 中最小的 27 個打數。
同時它落在 tier 3。這正好說明 tier 與 magnitude 是兩個獨立的維度——
tier 由 candidate type 決定，magnitude 是描述子，兩者沒有換算關係。

**「small sample 不等於 useless，但必須影響 evidence interpretation。」**

`VS_CLOSER` 只有 27 個打數，本階段**沒有**因此把它篩掉或降級
（那會是門檻，而且門檻還沒被設計過）。它一樣被完整保留、一樣有 tier、
一樣有完整的 magnitude 與 traceability。

但 `sample_size_at_bats = 27` 這個事實被明確記錄下來，是為了讓下一階段
**必須**面對它：27 個打數中多一支安打，AVG 就從 0.1481 變 0.1852。
小樣本的問題不在於資料沒用，而在於解讀時必須把不確定性一起呈現。

### 8.2 其他限制

1. **tier 是查表，不是推導。** 換一組產品假設，tier 就會不同。它沒有經過任何驗證，
   目前只是一個待檢驗的假設。
2. **PATTERN 與 CONTEXT 數字重複。** PATTERN 完全由對應 CONTEXT 的同一批數字組成。
   兩者同時存在於 candidate 清單中，任何加總式的處理都會重複計算。
3. **CONTEXT 的 ranking input 少一種。** TREND 有 magnitude + sample size + percentile
   三種，CONTEXT 只有前兩種。這個不對稱在設計權重時無法迴避。
4. **`EQUAL` 方向未被實際資料驗證到。** 29 個 candidate 中沒有出現過 `EQUAL`。
5. **只有一名球員、一個球季。** 沒有聯盟基準，所以 tier 與描述子都無法用外部資料校準。
6. **沒有樣本量檢定。** 從 Step 8 標記至今仍未做。這是設計正式 ranking 前最大的缺口。
7. **本階段完全沒有寫出檔案。** priority 記錄只在程式輸出中，沒有寫入
   `data/processed/`。理由是它比 Step 9 的 candidate 更接近「待討論的設計草案」，
   在 tier 假設被確認之前落地成檔案會給它不該有的權威感。

---

## 9. Open decisions

以下每一項都需要你決定，本階段刻意沒有替你決定：

### 9.1 tier 假設是否成立

tier 1 = TREND、tier 2 = PATTERN、tier 3 = CONTEXT 這個順序，
是我基於「MVP 三個方向的第一項是球員近況」推出的產品假設。

需要決定：這個順序對球隊數據分析人員來說是否正確？
是否應該反過來（情境資訊比近況更有決策價值）？還是根本不該用 tier？

### 9.2 跨粒度要不要比較，如果要，怎麼比

目前 `cross_granularity_comparison_allowed` 一律 `false`，
也就是 tier 1 與 tier 3 的 magnitude 不可放在一起比大小。

需要決定：是永久維持這個限制（tier 之間只做分組不做比較），
還是要找出一個讓兩種粒度可比的方法（例如都轉換成各自分布中的百分位）。
後者需要先解決 CONTEXT 沒有分布的問題。

### 9.3 CONTEXT 的百分位問題怎麼解

三個方向：

- 接受不對稱，永遠不給 CONTEXT 百分位
- 走 Step 7A 的路線 2（用對手先發投手手別建立有時間維度的逐場標記），
  但要接受 65.3% 的打席覆蓋率，且算出的數字會與官方分項不一致
- 走 Step 7A 的路線 3（`/box/getlive` 逐打席），成本最高、尚未驗證

### 9.4 樣本量該怎麼進入 priority

需要決定：是先做樣本量檢定再談 ranking，還是接受不做檢定、
改成把不確定性直接呈現給使用者（例如一律顯示樣本量，讓人自己判斷）。

### 9.5 PATTERN 與 CONTEXT 的重複要怎麼處理

需要決定：PATTERN 出現時是否要抑制對應的 CONTEXT candidate、
或反過來、或兩者都保留但在呈現層去重。

### 9.6 權重（如果最後真的要）

`magnitude × a + sample × b + consistency × c` 這種形式的權重，
以及每個係數的值，全部留給你決定。
本階段已把四種原始素材（magnitude、sample size、percentile、consistency_count）
以未加權的形式保留在 `ranking_inputs` 與 `magnitude_descriptors` / `reliability_descriptors` 中。

### 9.7 priority 記錄要不要落地成檔案

目前只在程式輸出。若下一階段需要穩定輸入，需要決定寫到哪裡，
以及是否沿用 Step 9 的 `_meta` 標記方式。

---

## 10. Validation

程式執行 **15 項檢查，全部通過（15 / 15）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 1 | 29 個 candidate 全部都有 `priority_tier` | PASS　records 29 = candidates 29 |
| 2 | 2 | TREND 全部 tier 1 | PASS　4 個，tier 值集合 `{1}` |
| 3 | 3 | MULTI_METRIC_PATTERN 全部 tier 2 | PASS　4 個，tier 值集合 `{2}` |
| 4 | 4 | CONTEXT 全部 tier 3 | PASS　21 個，tier 值集合 `{3}` |
| 5 | 5 | 沒有 `final_score` 或任何 score 欄位 | PASS　遞迴掃描所有巢狀欄位名 |
| 6 | 6 | 沒有 weight 欄位 | PASS |
| 7 | 7 | 沒有 threshold | PASS　29/29 全部分配，tier 指派僅依 candidate type |
| 8 | 8 | 沒有統計顯著性宣稱 | PASS |
| 9 | 9 | 沒有自然語言結論或價值判斷字眼 | PASS |
| 10 | 10 | 原始 candidate evidence 完全未被改動 | PASS　深度比較 29 個物件 |
| 11 | 10 | priority 記錄中的數值為原值複製 | PASS　逐欄位比對 |
| 12 | 11 | granularity 正確且禁止跨粒度比較 | PASS　29 個 `cross_granularity_comparison_allowed=false` |
| 13 | 12 | 沒有任何 HTTP request | PASS　socket guard 生效 |
| 14 | 13 | raw / processed source data 未被修改 | PASS　sha256 前後不變 |
| 15 | Part 6 | 同 tier 內沒有排名 | PASS　29 個 `intra_tier_rank` 全為 `null` |

### 幾項檢查的實作方式

**第 10 項「原始 evidence 未被改動」的實作方式是設計層面的：**
priority 記錄是**獨立的 sidecar**，用 `candidate_id` 關聯，完全不寫回 candidate 物件。
程式在產生 priority 記錄前先 `copy.deepcopy()` 一份 candidate，
最後用 `==` 做整個 list 的深度比較。因為根本沒有寫入路徑，這項檢查是結構性成立的。

**第 5 項** 用遞迴掃描所有巢狀欄位名，比對
`final_score` / `score` / `importance` / `weight` / `reliability_score` /
`magnitude_score` 等。`contains_no` 與 `priority_is_not` 這兩個「宣告不含這些東西」的
清單會被排除。

**第 13 項** 沿用 Step 9 的 socket guard：`candidate_insights` 在 import 時就把
`socket.socket.connect`、`connect_ex`、`create_connection` 換成會拋 `NetworkBlocked`
的函式。本階段 import 它，因此 guard 自動生效。

**第 14 項** sha256：
`zhang_yucheng_game_logs_2026.json` = `e3712d87…`、30,547 bytes；
`apart_score_0000006888_2026_A_01.json` = `8565cc8c…`、56,826 bytes。

### 開發過程中修正的一個誤判

第 9 項（沒有價值判斷字眼）第一次執行時報 `strength×29` FAIL。
追查後發現來源是 `priority_is_not` 清單中的 `"evidence_strength"`——
那個欄位的用途正是宣告「tier **不是** 證據強度」。

處理方式：把字眼掃描改成統一扣除 `priority_is_not` 與 `contains_no` 的內容，
與顯著性檢查的處理方式一致。**這是修正檢查本身的實作錯誤，不是放寬標準，
也沒有改動任何資料或欄位。** 修正後掃描仍會抓到出現在其他任何欄位的同一個字。

---

## 11. 本階段刻意沒有做的事

- 沒有建立正式 Insight Ranking
- 沒有 `final_score` / `importance_score` / `reliability_score` / `magnitude_score`
- 沒有任何 weight
- 沒有任何 threshold
- 沒有在同一 tier 內排名
- 沒有做統計顯著性宣稱
- 沒有產生自然語言、沒有 LLM
- 沒有 HTTP request（socket guard 強制保證）
- 沒有修改 Step 9 的 candidate 數字（sidecar 設計 + 深度比較驗證）
- 沒有修改 `data/raw/` 或 `data/processed/` 的檔案（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

# Insight Grouping Experiment（Step 18）

建立日期：2026-08-20
產出腳本：`src/insight_grouping.py`
前置文件：`docs/CANDIDATE_INSIGHT_DESIGN.md`（Step 9）、
`docs/RANKING_STRATEGY_EXPERIMENT.md`（Step 12）、
`docs/DECISION_RELEVANCE_EXPERIMENT.md`（Step 13）、
`docs/NOTEWORTHY_INSIGHT_EXPERIMENT.md`（Step 17-7）

> ## 這一步處理什麼
>
> Step 17-7 暴露的 **candidate duplication**：
> 20 個 noteworthy 中有 16 個只由 4 組獨立 evidence 支撐，
> 同一個現象被多個 candidate 重複呈現。
>
> **grouping 的唯一目的就是消除這種重複。**
>
> **不含：** group_score、group_rank、group_priority、threshold、weight、
> 自然語言結論、LLM。
> **沒有修改** Step 17-7 的 classification 規則或結果。
> **沒有修改** 原始 candidate（sidecar 設計）。

---

## 1. Grouping 規則（第一版，`G18-1`）

> **同一個分析 scope 的 candidate 形成同一個 Insight Group。**

`scope` = TREND 的 `window_name`（`RECENT_10` / `RECENT_15`）
或 CONTEXT / PATTERN 的 `context code`（`VS_RIGHT` 等）。
來源是 Step 12 `build_view()` 的 `window_or_scope` 欄位。

| 項目 | 內容 |
| --- | --- |
| `rule_inputs` | **`["candidate_scope"]`** — 只有這一個 |
| `rule_not_inputs` | `magnitude`、`sample_size_at_bats`、`plate_appearances`、`percentile_rank`、`consistency_count`、`classification` |

`rule_not_inputs` 明確列出 6 個**沒有**被用來決定 grouping 的量。
這不只是宣告，第 6 節有 mutation test 反證。

### 為什麼 PATTERN 與同 context 的 CONTEXT 要合併

每個含 PATTERN 的 group 都帶 `pattern_merge_rationale`：

> Step 12 已記錄：PATTERN 的 magnitude 定義是「三個指標差距絕對值的最大者」，
> 因此必然等於該 context 某一個 CONTEXT candidate 的 magnitude
> （本次 4 個 PATTERN 全部等於同 context 的 SLG candidate）。兩者不是獨立發現。
> Step 17-7 也記錄：同 context 的 CONTEXT candidate 用的第二種 evidence
> 就是該 PATTERN 本身。

也就是說 PATTERN 與它的 CONTEXT siblings 在數值上與 evidence 上都互相依賴，
分開呈現就是重複計算同一件事。

---

## 2. 最終共有幾個 group

**9 個 group**，涵蓋全部 29 個 candidate。

| perspective | groups | candidates | scopes |
| --- | ---: | ---: | --- |
| A_CURRENT_FORM | 2 | 4 | `RECENT_10`、`RECENT_15` |
| B_MATCHUP_CONTEXT | 5 | 17 | `VS_CLOSER`、`VS_LEFT`、`VS_RELIEF`、`VS_RIGHT`、`VS_STARTER` |
| C_STRUCTURAL_CONTEXT | 2 | 8 | `VS_DOMESTIC`、`VS_FOREIGN` |
| **合計** | **9** | **29** | |

perspective 沿用 Step 13 的定義，**沒有自行新增或改動**。

壓縮比：**29 個 candidate → 9 個 group**。

---

## 3. 每個 group 有哪些 candidate

| group_id（省略 `GROUP-0000006888-2026-A-`） | scope | perspective | 成員數 | 類型組成 | classification |
| --- | --- | --- | ---: | --- | --- |
| `RECENT_10` | RECENT_10 | A | 2 | TREND 2 | noteworthy 2 |
| `RECENT_15` | RECENT_15 | A | 2 | TREND 2 | noteworthy 2 |
| `VS_CLOSER` | VS_CLOSER | B | 4 | CONTEXT 3 + PATTERN 1 | noteworthy 4 |
| `VS_LEFT` | VS_LEFT | B | 3 | CONTEXT 3 | observation 3 |
| `VS_RELIEF` | VS_RELIEF | B | 3 | CONTEXT 3 | observation 3 |
| `VS_RIGHT` | VS_RIGHT | B | 3 | CONTEXT 3 | observation 3 |
| `VS_STARTER` | VS_STARTER | B | 4 | CONTEXT 3 + PATTERN 1 | noteworthy 4 |
| `VS_DOMESTIC` | VS_DOMESTIC | C | 4 | CONTEXT 3 + PATTERN 1 | noteworthy 4 |
| `VS_FOREIGN` | VS_FOREIGN | C | 4 | CONTEXT 3 + PATTERN 1 | noteworthy 4 |

### 完整成員清單

**`RECENT_10`**（2，noteworthy）
```
TREND-ZHANGYUCHENG-2026-A-RECENT_10-AVG
TREND-ZHANGYUCHENG-2026-A-RECENT_10-SLG
```

**`RECENT_15`**（2，noteworthy）
```
TREND-ZHANGYUCHENG-2026-A-RECENT_15-AVG
TREND-ZHANGYUCHENG-2026-A-RECENT_15-SLG
```

**`VS_CLOSER`**（4，noteworthy）
```
CONTEXT-ZHANGYUCHENG-2026-A-VS_CLOSER-AVG
CONTEXT-ZHANGYUCHENG-2026-A-VS_CLOSER-OBP
CONTEXT-ZHANGYUCHENG-2026-A-VS_CLOSER-SLG
PATTERN-ZHANGYUCHENG-2026-A-VS_CLOSER-AVG_OBP_SLG
```

**`VS_STARTER`**（4，noteworthy）／**`VS_DOMESTIC`**（4，noteworthy）／
**`VS_FOREIGN`**（4，noteworthy）
結構與 `VS_CLOSER` 相同：3 個 CONTEXT（AVG / OBP / SLG）+ 1 個 PATTERN。

**`VS_LEFT`**（3，observation）／**`VS_RELIEF`**（3，observation）／
**`VS_RIGHT`**（3，observation）
各 3 個 CONTEXT（AVG / OBP / SLG），沒有 PATTERN
（因為三個指標方向不一致，Step 9 沒有建立 pattern）。

---

## 4. 20 個 noteworthy 被壓縮成多少 group

| classification | candidate 數 | group 數 | 壓縮比 |
| --- | ---: | ---: | --- |
| **noteworthy** | **20** | **6** | **3.33 ×** |
| **observation** | **9** | **3** | **3.00 ×** |
| not_eligible | 0 | 0 | — |

**noteworthy 的 6 個 group：**
`RECENT_10`、`RECENT_15`、`VS_CLOSER`、`VS_DOMESTIC`、`VS_FOREIGN`、`VS_STARTER`

這正好對應 Step 17-7 記錄的問題：
「16 個 noteworthy 其實只由 4 組獨立 evidence 支撐」——
那 4 組就是 `VS_CLOSER`、`VS_DOMESTIC`、`VS_FOREIGN`、`VS_STARTER`，
加上 2 個 TREND scope，總共 6 個。

**grouping 把重複呈現的問題解掉了。**

---

## 5. 9 個 observation 分布在哪些 group

全部 9 個 observation 集中在 **3 個 group**，每個 group 3 個：

| group | 成員 | 方向組合（Step 9） |
| --- | --- | --- |
| `VS_LEFT` | AVG / OBP / SLG | ABOVE / ABOVE / BELOW → 2/3 |
| `VS_RELIEF` | AVG / OBP / SLG | BELOW / BELOW / ABOVE → 2/3 |
| `VS_RIGHT` | AVG / OBP / SLG | BELOW / BELOW / ABOVE → 2/3 |

三個 group 都缺 `second_supporting`（Step 17-7 已記錄原因：
沒有 3/3 pattern，且官方分項沒有時間維度所以沒有 rolling percentile）。

---

## 6. 是否存在「同一 group 同時包含 noteworthy 與 observation」

**沒有。0 個 group 混合。**

每個 group 內的 classification 完全一致：
6 個 group 全部 noteworthy、3 個 group 全部 observation。

### 這件事有一個結構性原因，值得記錄

不是巧合。Step 17-7 的 `second_supporting` evidence 有兩種來源，
**兩種都是 scope 層級的屬性**：

| 第二種 evidence | 屬於誰 |
| --- | --- |
| `rolling_window_distribution_position` | 每個 TREND candidate 都有（窗口層級） |
| `cross_metric_direction_consistency` | 整個 context 共用同一個 3/3 pattern（context 層級） |

而 `phenomenon` 與 `sample_context` 是所有 29 個 candidate 都有的。
因此 **classification 完全由 scope 決定**，同 scope 內必然一致。

**這意味著 Step 17-7 的 candidate 層級分類，實際上沒有產生任何 candidate 層級的區分。**
29 個分類收斂成 9 個 scope 層級的值，而那 9 個值又只有 2 種結果
（noteworthy / observation）。

這是一個對規則設計有直接意義的事實，記錄在此供你判斷。

---

## 7. Group schema

| 欄位 | 說明 |
| --- | --- |
| `group_id` | `GROUP-<acnt>-<season>-<kind_code>-<scope>` |
| `scope` | grouping 的唯一輸入 |
| `perspective` / `perspective_name` | 沿用 Step 13 的三個 perspective |
| `member_candidate_ids` | 成員清單，一律 `candidate_id` 字典序（**不是排名**） |
| `member_count` / `member_types` | 成員數與類型組成 |
| `classification_summary` | counts、classifications_present、mixed_classification、by_candidate |
| `metrics_available` / `metrics_unavailable` | 該 group 涵蓋與缺少的指標 + 缺少原因 |
| `shared_data_scope` | 成員共用的底層資料範圍（見下） |
| `grouping_rule` | rule_id、version、rule_text、rule_inputs、rule_not_inputs、pattern_merge_rationale |
| `provenance` | 各段資訊的來源 Step 與模組、source_files、sidecar 說明 |
| `contains_no` | 明確宣告不含 group_score / group_rank / group_priority / threshold / weight 等 |

### `shared_data_scope` 是事後描述，不是 grouping 依據

這個欄位記錄「為什麼這些 candidate 講的是同一件事」，
但它**不參與 grouping 判定**（grouping 只看 scope）。欄位中有明確的 `note` 說明這一點。

實測結果：**9 個 group 全部 `members_share_single_sample = true`**，
也就是每個 group 的成員共用完全相同的一組樣本：

| group | scope_kind | AB | PA | 其他 |
| --- | --- | ---: | ---: | --- |
| RECENT_10 | recent_games_window | 42 | 44 | 2026-08-02 ~ 08-18，10 個 game_snos |
| RECENT_15 | recent_games_window | 58 | 63 | 2026-07-26 ~ 08-18，15 個 game_snos |
| VS_CLOSER | season_cumulative_official_split | 27 | 31 | 官方 ItemName `VS. 救援` |
| VS_LEFT | season_cumulative_official_split | 54 | 62 | 官方 ItemName `VS. 左投` |
| VS_RELIEF | season_cumulative_official_split | 66 | 80 | 官方 ItemName `VS. 中繼` |
| VS_FOREIGN | season_cumulative_official_split | 100 | 118 | 官方 ItemName `VS. 外籍投手` |
| VS_DOMESTIC | season_cumulative_official_split | 173 | 202 | 官方 ItemName `VS. 本土投手` |
| VS_STARTER | season_cumulative_official_split | 180 | 209 | 官方 ItemName `VS. 先發` |
| VS_RIGHT | season_cumulative_official_split | 219 | 258 | 官方 ItemName `VS. 右投` |

**每個 group 的 AB 都只有一個值**，這在事實層面確認了 scope-based grouping 是連貫的：
同 group 的 candidate 真的是在描述同一批打席。

（上表依 AB 排列只是為了呈現，不是排名。）

### `metrics_available`

| group | metrics_available | metrics_unavailable |
| --- | --- | --- |
| RECENT_10 / RECENT_15 | AVG、SLG | **OBP**（processed data 未收逐場犧牲飛球，Step 5 / Step 11） |
| 7 個 VS_* | AVG、OBP、SLG | 無 |

---

## 8. Validation

程式執行 **17 項檢查，全部通過（17 / 17）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 1 | 29 個 candidate 每一個且只屬於一個 group | PASS　成員總數 29 = candidate 29，集合相同，無重複 |
| 2 | 2 | 沒有 candidate 遺失 | PASS |
| 3 | 3 | 沒有 candidate 重複進入兩個 group | PASS |
| 4 | 4 | grouping 沒有修改 candidate | PASS　深度比較 29 個物件 |
| 5 | 5 | **grouping 不依 magnitude 決定** | PASS　mutation test |
| 6 | 6 | **grouping 不依 sample size 決定** | PASS　mutation test |
| 7 | 7 | PATTERN 與對應 CONTEXT 被正確聚合 | PASS　4 個 PATTERN 各自與 3 個 sibling 同 group |
| 8 | 8 | RECENT_10 的 AVG / SLG 被聚合 | PASS |
| 9 | 9 | RECENT_15 的 AVG / SLG 被聚合 | PASS |
| 10 | 10 | 每個 group 都能追溯到原始 candidate 與來源 Step | PASS　9 個 group 的 source_files 皆存在 |
| 11 | 11 | **deterministic：打亂輸入順序後結果一致** | PASS　3 個 seed 各跑一次 |
| 12 | 12 | 沒有 HTTP request | PASS　socket guard 生效 |
| 13 | 13 | 沒有使用 LLM | PASS　AST import 檢查 + `sys.modules` |
| 14 | 14 | 沒有 group_score / group_rank / group_priority / threshold / weight | PASS　遞迴掃描所有巢狀欄位名 |
| 15 | — | Step 17-7 的 classification 原樣引用，未被修改 | PASS　29 筆逐筆相符 |
| 16 | — | 沒有產生自然語言結論或價值判斷字眼 | PASS |
| 17 | — | raw / processed data 未被修改 | PASS |

### 第 5 / 6 項的實作方式（mutation 反證）

`mutation_test_grouping_independence()` 在**深拷貝**上做四組變異，
再比對 group 結構的簽章（`[[scope, member_ids], ...]`）：

| 變異 | 值 |
| --- | --- |
| magnitude | `0.0`、`999.0`（同時改 candidate 的 difference 與 view 的 magnitude） |
| at_bats / plate_appearances | `1`、`9999` |

```
重跑次數     : 4
結構改變次數 : 0
```

**若 grouping 任何地方讀了 magnitude 或 at_bats，group 成員就會改變。**
0 次改變證明這兩個量完全沒有進入 grouping 邏輯。

### 第 11 項的實作方式

用 3 個固定 seed（`20261121`、`7`、`999`）打亂 candidate 輸入順序，
各跑一次 grouping，比對結構簽章。3 次全部相同。

group 與 member 都在 `build_groups()` 中明確排序
（group 依 scope、member 依 candidate_id），所以結果不依賴輸入順序。

### 第 14 項的白名單說明

`percentile_rank` 與 `rank_desc` 是 **Step 6 建立的 evidence 描述子**
（分布內的經驗百分位與名次），不是 group 之間的排名，因此列入白名單。
除此之外沒有任何含 `score` / `rank` / `priority` / `weight` / `threshold` 的欄位名。

### hash 記錄

| 檔案 | sha256 前 8 碼 | bytes |
| --- | --- | --- |
| `data/processed/zhang_yucheng_game_logs_2026.json` | `e3712d87` | 30,547 |
| `data/raw/apart_score_0000006888_2026_A_01.json` | `8565cc8c` | 56,826 |

執行前後完全一致。沒有寫出任何檔案到 `data/`。

本次執行**沒有** FAIL，因此沒有需要修正的檢查實作錯誤。

---

## 9. 這次實驗暴露的問題

以下是聚合後才看得到的事實，**不是規則修改建議**。

### 9.1 classification 完全由 scope 決定

見第 6 節。29 個 candidate 層級的分類，收斂成 9 個 scope 層級的值，
而那 9 個值只有 2 種結果。

換句話說：**Step 17-7 的分類規則在 candidate 層級沒有產生任何區分。**
如果分類的目的是在 candidate 之間做區別，目前的規則做不到；
如果目的是在 scope 之間做區別，那它其實應該直接定義在 scope 層級。

### 9.2 grouping 沒有解決「6 個 noteworthy group 之間如何取捨」

grouping 把 20 個壓成 6 個，但 6 個仍然全部是 noteworthy，
彼此之間沒有任何區分依據。Step 12 已證明三種排序哲學的 Top 10 沒有交集，
Step 10 已記錄 magnitude 與 sample size 的結構性反向關係。
**這些問題在 grouping 之後依然存在。**

### 9.3 group 內部的指標不對等

`RECENT_10` / `RECENT_15` group 只有 2 個成員（AVG、SLG），
7 個 `VS_*` group 有 3 個指標。
這讓 group 之間的「資訊量」不對等——但本階段刻意不把它換算成任何數值。

### 9.4 3 個 observation group 的阻斷原因相同

`VS_LEFT`、`VS_RELIEF`、`VS_RIGHT` 都是因為「三個指標方向不一致」而沒有 pattern。
這是資料本身的性質，不是它們的現象比較小
（`VS_LEFT-SLG` 的差距 −0.10520961 比多數 noteworthy 都大，Step 17-7 已記錄）。

---

## 10. 已知限制

1. **grouping 只有一個維度。** scope 是唯一輸入，沒有考慮其他可能的聚合方式
   （例如依 metric 聚合、依 perspective 聚合）。
2. **`not_eligible` 沒有出現。** 因此不存在只含 `not_eligible` 的 group，
   混合情況也無法被真實資料驗證。
3. **group 之間沒有任何順序。** 輸出依 scope 字典序，那不是排名。
   本階段刻意不決定 group 的呈現順序。
4. **只有一名球員、一個球季。** 不同球員的 scope 數量與組成不同，
   9 個 group 這個數字不具一般性。
5. **沒有寫出檔案。** sidecar 只在程式輸出中，與 Step 10 ~ 17-7 一致。
6. **group 內部仍有重複。** 例如 `VS_CLOSER` group 內，
   PATTERN 的 magnitude 等於 CONTEXT-SLG 的 magnitude。
   grouping 消除了「跨 candidate 的重複呈現」，
   但沒有處理「group 內部要呈現哪一個成員」——那是呈現層的問題。

---

## 11. 本階段刻意沒有做的事

- 沒有修改 Step 17-7 的 classification 規則或任何一筆分類結果
- 沒有新增 threshold
- 沒有建立 group_score / group_rank / group_priority / weight
- **沒有依 magnitude 決定 grouping**（4 次 mutation test 反證）
- **沒有依 sample size 決定 grouping**（同一組 mutation test 反證）
- 沒有使用 LLM（AST import 檢查 + `sys.modules` 比對）
- 沒有任何 HTTP request（socket guard 強制保證）
- 沒有產生自然語言結論
- 沒有修改原始 candidate（sidecar 設計 + 深度比較驗證）
- 沒有修改 `data/raw/` 或 `data/processed/`（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有為 group 決定呈現順序或優先度
- 沒有為第 9 節暴露的問題自行修改規則
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

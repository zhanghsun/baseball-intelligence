# Candidate Insight Engine 設計（Step 9）

建立日期：2026-08-20
產出腳本：`src/candidate_insights.py`
輸出檔案：`data/processed/candidate_insights_zhang_yucheng_2026.json`（可選，`--write`）

> ## 這一步是什麼、不是什麼
>
> **是：** 把已經算好、已經驗證過的 evidence，組織成 machine-readable 的「候選」。
>
> **不是：**
>
> - 不是自然語言 Insight
> - 不是 AI / LLM
> - 不是預測
> - 不是 recommendation
> - **不含任何 threshold**（沒有任何 `if diff > X` 之類的判斷）
> - **不含 final ranking score**，不對任何指標加權
> - 不判斷好壞、強弱、擅長與否
>
> Candidate Engine 現階段回答的問題是「有哪些值得我們**之後**評估的候選？」
> 而不是「哪些一定值得注意？」

---

## 1. Input

| 輸入 | 檔案 | 來源階段 |
| --- | --- | --- |
| 逐場打擊資料 | `data/processed/zhang_yucheng_game_logs_2026.json` | Step 4 |
| 官方分項快取 | `data/raw/apart_score_0000006888_2026_A_01.json` | Step 8 |

程式直接沿用既有的 evidence 函式，避免重複實作造成數字分歧：

| 匯入 | 來自 | 用途 |
| --- | --- | --- |
| `sort_by_date`、`build_window` | `src/player_form_analysis.py` | Recent 10 / 15 窗口 |
| `build_rolling_windows`、`rank_and_percentile` | `src/rolling_baseline.py` | 滾動分布與百分位 |
| `build_context`、`trunc4` | `src/context_splits.py` | 7 個官方情境 |

**沒有重新抓 CPBL 資料，沒有任何 HTTP request，沒有修改 processed data。**

### 網路封鎖是執行期保證，不是宣告

程式在 import 完成後立刻把 `socket.socket.connect`、`socket.socket.connect_ex`、
`socket.create_connection` 換成會拋 `NetworkBlocked` 的函式。
任何嘗試連線的程式碼都會直接失敗。驗證第 6 項會檢查這個 guard 仍在生效。

（guard 必須在 import 之後安裝，因為 `ssl` 模組在 import 期間會繼承 `socket.socket`，
在 import 前替換會讓 `ssl` 無法載入。）

---

## 2. 季累計 baseline 的來源

TREND 與 CONTEXT 的比較基準都是同一個「2026 季累計」：

| 項目 | 值 | 推導 |
| --- | --- | --- |
| PA / AB / H / TB | 320 / 273 / 85 / 145 | `processed data` 77 筆逐場加總 |
| BB / HBP / SF | 37 / 7 / 3 | 官方 context evidence 加總（見下） |
| **AVG** | **0.31135531** | 85 / 273 |
| **OBP** | **0.40312500** | 129 / 320 |
| **SLG** | **0.53113553** | 145 / 273 |

OBP 需要犧牲飛球，而 processed data 沒有收 SF（Step 4 的欄位取捨）。
因此 BB / HBP / SF 取自官方 context evidence 的加總——Step 8 已驗證三組 context 在這些
欄位上的加總完全一致，且與逐場資料相符，所以這個推導是可追溯的，不是估算。

`OBP = (85 + 37 + 7) / (273 + 37 + 7 + 3) = 129 / 320`。
`walks` 已含故意四壞（Step 7B 以打席恆等式實證），因此沒有再加 IBB。

---

## 3. Candidate Type 1：TREND

Recent 10 與 Recent 15，各 AVG 與 SLG，共 **4 個** candidate。

### 欄位

| 欄位 | 說明 |
| --- | --- |
| `candidate_id` | `TREND-ZHANGYUCHENG-2026-A-<WINDOW>-<METRIC>`，決定性、可重現 |
| `type` | `"TREND"` |
| `subject` | 球員、球隊、球季、賽制 |
| `metric` | `batting_average` / `slugging_percentage` |
| `window` | 名稱、定義、場數、粒度（`player_games`） |
| `current_value` | 窗口值，完整精度 |
| `baseline_value` | 季累計值 |
| `absolute_difference` | **有號差**（current − baseline） |
| `absolute_difference_magnitude` | 上者的絕對值 |
| `direction` | `ABOVE` / `BELOW` / `EQUAL`（純數值方向，不含好壞） |
| `rolling_percentile` | 同尺寸滾動分布中的位置（見下） |
| `games` / `at_bats` / `plate_appearances` | 樣本量 |

`absolute_difference` 這個名稱有歧義（可讀成「絕對值」或「絕對差距」），
所以同時提供有號差與絕對值兩個欄位，避免下一階段誤用。

### `rolling_percentile` 的定義

`window_size`、`distribution_n`、`rank_desc`、`count_below` / `count_equal` / `count_above`、
`percentile_rank`、`percentile_strict`，並在 `definition` 欄位寫明算式：

```
percentile_rank   = (低於 + 相同) / n × 100
percentile_strict = 低於 / n × 100
```

三個原始個數都保留，讓下一階段可以用任何偏好的百分位定義重算。

**Recent 15 的分布是新建的。** Step 6 只建了 10 場滾動窗口（68 個）；
本階段用同一個 `build_rolling_windows()` 以 `size=15` 建出 63 個（= 77 − 15 + 1）。
方法完全相同，只是窗口大小不同，沒有引入新資料。
驗證第 5 / 6 項確認兩個尺寸的最新滾動窗口都與 `build_window()` 的結果一致。

### 結果

| candidate_id | current | baseline | diff | direction | rolling |
| --- | --- | --- | --- | --- | --- |
| `RECENT_10-AVG` | 0.40476190 | 0.31135531 | +0.09340659 | ABOVE | rank 5/68，pct_rank 94.1% |
| `RECENT_10-SLG` | 0.61904762 | 0.53113553 | +0.08791209 | ABOVE | rank 20/68，pct_rank 72.1% |
| `RECENT_15-AVG` | 0.32758621 | 0.31135531 | +0.01623090 | ABOVE | rank 25/63，pct_rank 61.9% |
| `RECENT_15-SLG` | 0.50000000 | 0.53113553 | −0.03113553 | BELOW | rank 35/63，pct_rank 46.0% |

（`candidate_id` 前綴 `TREND-ZHANGYUCHENG-2026-A-` 省略。）

Recent 10 的 `game_snos` 是 `[240, 242, 244, 249, 260, 261, 262, 265, 269, 272]`
（2026-08-02 ~ 2026-08-18）；Recent 15 多含 `[225, 226, 228, 232, 236]`
（起始 2026-07-26）。

---

## 4. Candidate Type 2：CONTEXT

7 個官方情境 × 3 個指標（AVG / OBP / SLG），共 **21 個** candidate。

### 欄位

| 欄位 | 說明 |
| --- | --- |
| `candidate_id` | `CONTEXT-ZHANGYUCHENG-2026-A-<CONTEXT>-<METRIC>` |
| `type` | `"CONTEXT"` |
| `subject` | 同上 |
| `context` | 代碼、官方 `ItemName`、組別、定義來源、粒度（`season_cumulative`） |
| `metric` / `value` | 指標與完整精度值 |
| `at_bats` / `plate_appearances` | 樣本量 |
| `comparison` | 與**同一球員季累計**的差距與方向 |
| `official_reference_value` | 官方值（截斷 4 位），僅作 reference |
| `own_value_truncated_4dp` | 本專案值截斷後的值，用於與官方對帳 |
| `counting_fields` | 11 個計數欄位原值 |
| `runs` | 一律 `null`（官方分項無此欄位） |

`context.definition_note` 明確記錄：先發/中繼/救援、本土/外籍的判定規則官方沒有文字說明，
本專案不自行定義。英文標籤（`VS_CLOSER` 等）只是標籤。

### comparison 的範圍限制

`comparison_basis` 固定為 `same_player_season_cumulative`。
**刻意不在不同 context 之間排序或選出最高最低**，理由寫在 `comparison._note`：
各 context 樣本量差異很大（27 ~ 219 個打數）且彼此不獨立（例如外籍投手多半是先發）。

### 結果

| context | AB | PA | AVG | OBP | SLG |
| --- | --- | --- | --- | --- | --- |
| VS_RIGHT | 219 | 258 | 0.31050228 | 0.40310078 | 0.55707763 |
| VS_LEFT | 54 | 62 | 0.31481481 | 0.40322581 | 0.42592593 |
| VS_STARTER | 180 | 209 | 0.33888889 | 0.42583732 | 0.56666667 |
| VS_RELIEF | 66 | 80 | 0.30303030 | 0.40000000 | 0.59090909 |
| VS_CLOSER | 27 | 31 | 0.14814815 | 0.25806452 | 0.14814815 |
| VS_DOMESTIC | 173 | 202 | 0.28901734 | 0.37623762 | 0.49710983 |
| VS_FOREIGN | 100 | 118 | 0.35000000 | 0.44915254 | 0.59000000 |

與季累計的差（`comparison.difference`）：

| context | AVG diff | OBP diff | SLG diff |
| --- | --- | --- | --- |
| VS_RIGHT | −0.00085303 | −0.00002422 | +0.02594209 |
| VS_LEFT | +0.00345950 | +0.00010081 | −0.10520961 |
| VS_STARTER | +0.02753358 | +0.02271232 | +0.03553114 |
| VS_RELIEF | −0.00832501 | −0.00312500 | +0.05977356 |
| VS_CLOSER | −0.16320716 | −0.14506048 | −0.38298738 |
| VS_DOMESTIC | −0.02233797 | −0.02688738 | −0.03402570 |
| VS_FOREIGN | +0.03864469 | +0.04602754 | +0.05886447 |

---

## 5. Candidate Type 3：MULTI_METRIC_PATTERN

當同一個 context 的 AVG / OBP / SLG 三個方向一致時建立，共 **4 個** candidate。

### 方向判定規則

逐指標與同一球員的季累計比較：`value > baseline` 記為 `ABOVE`，`<` 記為 `BELOW`，
`=` 記為 `EQUAL`。三個指標方向相同才建立 pattern。

**`no_threshold` 欄位明確記錄：方向判定不含任何最小差距門檻，差距再小也照方向記錄。**
例如 `VS_RIGHT` 的 OBP 只差 −0.00002422，仍然記為 `BELOW`，沒有被當成「等於」。

### 命名

`type` 只叫 `MULTI_METRIC_PATTERN`，欄位只叫 `direction` 與 `consistency_count`。
每個 pattern candidate 都帶一個 `naming_note`，明確聲明**刻意不使用**
`strength` / `weakness` / `advantage` / `disadvantage` 這類帶價值判斷的命名。

### 全部 context 的方向記錄

這張表是輸出的一部分（`_meta.context_direction_log`），
把**沒有**形成 pattern 的也列出來，是為了透明，不是篩選結果：

| context | AVG | OBP | SLG | consistency | pattern_created |
| --- | --- | --- | --- | --- | --- |
| VS_RIGHT | BELOW | BELOW | ABOVE | 2/3 | false |
| VS_LEFT | ABOVE | ABOVE | BELOW | 2/3 | false |
| **VS_STARTER** | ABOVE | ABOVE | ABOVE | **3/3** | **true** |
| VS_RELIEF | BELOW | BELOW | ABOVE | 2/3 | false |
| **VS_CLOSER** | BELOW | BELOW | BELOW | **3/3** | **true** |
| **VS_DOMESTIC** | BELOW | BELOW | BELOW | **3/3** | **true** |
| **VS_FOREIGN** | ABOVE | ABOVE | ABOVE | **3/3** | **true** |

`consistency_count < total_metrics` 的 context 沒有建立 pattern，
是因為「三指標方向一致」在**定義上不成立**，不是被任何門檻篩掉。

### 4 個 pattern

| candidate_id | direction | consistency | at_bats |
| --- | --- | --- | --- |
| `PATTERN-…-VS_STARTER-AVG_OBP_SLG` | ABOVE | 3/3 | 180 |
| `PATTERN-…-VS_CLOSER-AVG_OBP_SLG` | BELOW | 3/3 | 27 |
| `PATTERN-…-VS_DOMESTIC-AVG_OBP_SLG` | BELOW | 3/3 | 173 |
| `PATTERN-…-VS_FOREIGN-AVG_OBP_SLG` | ABOVE | 3/3 | 100 |

### 為什麼 TREND 沒有 pattern candidate

TREND 窗口只有 AVG 與 SLG 兩個指標，沒有 OBP。
原因是 processed data 沒有逐場的犧牲飛球，OBP 無法按窗口計算。
與其用兩個指標湊一個弱化版的 pattern，本階段選擇不做，並把原因記錄在這裡。

---

## 6. Evidence Traceability

每個 candidate 都有這四個欄位（驗證第 4 項會檢查）：

| 欄位 | 內容 |
| --- | --- |
| `source_evidence` | `player_form_analysis` / `rolling_baseline` / `contextual_evidence` |
| `source_files` | 實際檔案路徑（驗證會確認檔案存在） |
| `calculation_reference` | 公式、排序規則、百分位來源、相關文件路徑 |
| `traceability` | `date_range`、`game_snos`、`context_definition` |

追溯精度依資料本身的粒度而定，**沒有補上不存在的資訊**：

| candidate 類型 | `game_snos` | `date_range` |
| --- | --- | --- |
| TREND | 完整場次清單（10 或 15 個） | 起訖日期 |
| CONTEXT / PATTERN | `null` | `null`，附 `_note` 說明官方分項不提供場次 |

驗證第 5 項會檢查 CONTEXT / PATTERN **不可**有 `game_snos`，TREND 的 `game_snos`
數量必須等於 `games`。這是為了防止未來有人不小心把不存在的追溯資訊填進去。

---

## 7. Ranking inputs（未加權）

每個 candidate 有一個 `ranking_inputs` 區塊，只放**原始素材**：

```json
{
  "_note": "原始素材，未加權、未合成任何 score",
  "magnitude": 0.09340659340659341,
  "sample_size_at_bats": 42,
  "percentile_rank": 94.11764705882352,
  "consistency_count": null
}
```

**沒有 `final_score`、沒有權重、沒有任何合成。**
`magnitude × 0.5 + sample × 0.3 + consistency × 0.2` 這種加權留到下一階段由你決定。

`percentile_rank` 在 CONTEXT candidate 中一律為 `null`，並附
`percentile_note` 說明原因：官方分項沒有時間維度，無法建立滾動分布。

驗證第 10 項會掃描所有欄位名，確認沒有 `score` / `rank` / `importance` /
`priority` / `weight` 這類欄位。

---

## 8. 輸出位置的選擇與理由

**選擇：寫到 `data/processed/candidate_insights_zhang_yucheng_2026.json`，
但預設不寫，要加 `--write`。**

理由：

1. **需要 machine-readable 產物。** 下一階段（ranking）需要一個穩定的輸入，
   而且要能驗證「ranking 沒有偷改 candidate 的數字」。只印在螢幕上做不到這件事。
2. **用使用者指定的路徑。** 為此另開 `data/derived/` 會是一個沒被要求的結構變更，
   在這個階段引入會增加混亂。
3. **但它不是來源資料，必須標示清楚。** 檔案是一個物件而不是陣列，
   最上層有 `_meta` 區塊寫明：

   ```json
   {
     "artifact_type": "derived_analysis_output",
     "note": "這不是來源資料，是由 src/candidate_insights.py 從既有 evidence 重新產生的衍生輸出。可隨時重建，不應被當成事實來源。",
     "generator": "src/candidate_insights.py",
     "generated_at_utc": "...",
     "contains_no": ["threshold", "final_ranking_score", "weighting",
                     "natural_language_conclusion", "prediction", "recommendation"]
   }
   ```

4. **預設不寫檔**，避免每次執行驗證都產生一份時間戳不同的檔案。

保留的顧慮：`data/processed/` 現在同時放「來源資料的乾淨投影」與「衍生分析輸出」，
兩者的權威性不同。如果專案之後想要更嚴格的分離，自然的做法是把衍生輸出移到
`data/derived/`。目前沒有這麼做，是因為那是結構決策，應該由你決定。

`data/` 已被 `.gitignore` 排除，所以這個檔案不進版控，需要時重跑腳本重建。

---

## 9. Validation

程式執行 **24 項檢查，全部通過（24 / 24）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 1 | `RECENT_10-AVG` 與 Step 5 / Step 6 一致 | PASS　current 0.40476190（= 17/42）、games 10、AB 42、rolling n 68、rank 5 |
| 2 | 1 | `RECENT_10-SLG` 一致 | PASS　current 0.61904762（= 26/42）、rank 20/68 |
| 3 | 2 | `RECENT_15-AVG` 一致 | PASS　current 0.32758621（= 19/58）、games 15、AB 58、rolling n 63 |
| 4 | 2 | `RECENT_15-SLG` 一致 | PASS　current 0.50000000（= 29/58） |
| 5 | 1 / 2 | RECENT_10 最新滾動窗口 == `build_window()` | PASS　跨實作交叉核對，game_snos / AVG / SLG 全同 |
| 6 | 1 / 2 | RECENT_15 最新滾動窗口 == `build_window()` | PASS　同上 |
| 7–13 | 3 | 7 個 CONTEXT 的 PA/AB/H/TB 與 Step 8 一致 | PASS（7 項） |
| 14 | 3 | 21 個 CONTEXT 比率截斷 4 位後 == 官方值 | PASS |
| 15–17 | 3 | 三組 context 加總 == season totals | PASS（3 項，PA/AB/H/TB 全對） |
| 18 | 4 | 29 個 candidate 都有四個 traceability 欄位 | PASS |
| 19 | 5 | 沒有 candidate 使用不存在的資料 | PASS |
| 20 | 6 | 沒有任何 HTTP request | PASS　socket guard 生效 |
| 21 | 7 | 沒有修改 raw / processed data | PASS　sha256 前後不變 |
| 22 | 8 | 沒有自然語言結論或價值判斷字眼 | PASS |
| 23 | 9 | 沒有 threshold | PASS　TREND 4/4、CONTEXT 21/21 全數產生 |
| 24 | 10 | 沒有 final ranking score 或加權 | PASS |

### 幾項檢查的實作方式

**第 19 項「沒有使用不存在的資料」** 檢查三件事：
`source_files` 指向的檔案真的存在；CONTEXT 的 `runs` 必須是 `null`；
CONTEXT / PATTERN 的 `game_snos` 必須是 `null`，TREND 的 `game_snos` 數量必須等於 `games`。

**第 21 項** 比對執行前後的 sha256：
`zhang_yucheng_game_logs_2026.json` = `e3712d87…`、30,547 bytes；
`apart_score_0000006888_2026_A_01.json` = `8565cc8c…`、56,826 bytes。

**第 22 項** 把全部 candidate 序列化成 JSON 字串後，掃描
`strength` / `weakness` / `advantage` / `disadvantage` / `擅長` / `弱點` / `優勢` /
`建議` / `預測` / `important` 等禁用字眼。`naming_note` 中「刻意不使用這些字」的
宣告性提及會被扣除，其餘一律視為違規。

**第 23 項** 用產出數量證明沒有篩選：TREND 應有 2 窗口 × 2 指標 = 4 個，
CONTEXT 應有 7 情境 × 3 指標 = 21 個，實際都完全相符，
說明沒有任何 candidate 因為差距太小或樣本太少而被丟掉。
`MULTI_METRIC_PATTERN` 只有 4 個，是因為方向一致在定義上只成立於 4 個 context，
不是門檻篩選——`_meta.context_direction_log` 把 7 個全部列出來供核對。

---

## 10. Candidate 總覽

| 類型 | 數量 |
| --- | --- |
| TREND | 4 |
| CONTEXT | 21 |
| MULTI_METRIC_PATTERN | 4 |
| **總計** | **29** |

---

## 11. 已知限制

1. **粒度不能混用。** TREND 是「最近 N 場出賽」，CONTEXT 與 PATTERN 是「球季累計」。
   兩者的 baseline 相同（季累計），但 candidate 本身的範圍不同。
   下一階段若要比較不同 candidate 的「重要性」，必須處理這個粒度差異。
2. **CONTEXT candidate 沒有百分位。** 官方分項沒有時間維度，無法建立滾動分布，
   所以 CONTEXT 只有 magnitude 與 sample size 兩種 ranking input，
   TREND 則有三種。這個不對稱在下一階段設計權重時會是問題。
3. **樣本量差異極大。** `VS_CLOSER` 只有 27 個打數，`VS_RIGHT` 有 219 個。
   本階段刻意不因此篩掉任何 candidate（那會是門檻），但 `sample_size_at_bats`
   已保留供下一階段使用。
4. **context 之間不獨立。** 三組是同一批 320 個打席的三種切法，
   而且無法交叉（官方只給單維度）。同一批打席可能同時支撐多個 candidate，
   例如 `VS_FOREIGN` 與 `VS_STARTER` 的打席一定有重疊，但重疊量無法量化。
5. **只有一名球員、一個球季。** 沒有聯盟基準，沒有其他球員，沒有其他年度。
6. **沒有樣本量檢定。** magnitude 大不代表訊號強。這一點在 Step 8 就已標記，
   本階段沒有處理，也沒有假裝處理。
7. **`EQUAL` 方向未被實際資料驗證到。** 7 個 context 的 21 個方向判定中
   沒有出現過 `EQUAL`，所以那條分支沒有被真實資料觸發。

---

## 12. 本階段刻意沒有做的事

- 沒有 Insight ranking，沒有 final score，沒有加權
- 沒有任何 threshold（包含「AB 太少就忽略」這種）
- 沒有 LLM、沒有 natural language generation
- 沒有 recommendation、沒有預測
- 沒有 next-game analysis
- 沒有 dashboard
- 沒有 HTTP request（以 socket guard 強制保證）
- 沒有修改 `data/raw/` 或 `data/processed/` 的既有檔案（以 sha256 驗證）
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`
- 沒有在不同 context 之間排序或選出最高最低
- 沒有用 strength / weakness / advantage / disadvantage 命名任何欄位

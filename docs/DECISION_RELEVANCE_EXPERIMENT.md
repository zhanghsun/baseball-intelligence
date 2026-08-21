# Decision Relevance Experiment（Step 13）

建立日期：2026-08-20
產出腳本：`src/decision_relevance.py`
前置文件：`docs/CANDIDATE_INSIGHT_DESIGN.md`（Step 9）、`docs/INSIGHT_RANKING_DESIGN.md`（Step 10）、
`docs/EVIDENCE_SAMPLE_ANALYSIS.md`（Step 11）、`docs/RANKING_STRATEGY_EXPERIMENT.md`（Step 12）

> ## 這一步研究什麼
>
> **什麼特徵讓一個 candidate 對教練的決策更有關聯？**
>
> **本階段不回答：**
>
> - 「哪個 candidate 最重要？」
> - 「哪個 perspective 最好？」
>
> **本階段不含：** ranking、score、weight、threshold、confidence score、
> prediction、recommendation、自然語言結論、LLM、新增資料來源。
>
> 產出是 29 個**獨立的 sidecar record**，用 `candidate_id` 關聯，不寫回 candidate。

---

## 1. 為什麼需要這一步

Step 12 用同一批 29 個 candidate 跑了三種 ranking philosophy，
結果三種的 Top 10 **完全沒有交集**。也就是說「要呈現什麼」幾乎完全由排序哲學決定，
而不是由資料決定。

Step 12 也記錄了一個結構性衝突：magnitude 與 sample size 在本次資料中呈反向關係，
不是權重可以調和的問題。

因此本階段不再嘗試排序，改成往回退一步問：
除了 magnitude 與 sample size，還有哪些**維度**可能與決策關聯？

---

## 2. Decision Relevance Descriptors（Part 1）

每個 candidate 有四組描述子。**全部由 candidate 的類型與 scope 查表決定，不看數值。**

### 2.1 `temporal_relevance`

| 值 | 數量 | 對應 |
| --- | ---: | --- |
| `recent_games` | 4 | TREND |
| `season_cumulative` | 25 | CONTEXT（21）+ MULTI_METRIC_PATTERN（4） |

沒有轉成分數。

### 2.2 `contextual_relevance`

| 值 | 數量 | 官方分項來源 |
| --- | ---: | --- |
| `none` | 4 | TREND（沒有情境切分） |
| `pitcher_hand` | 6 | `VS. 右投`、`VS. 左投` |
| `pitcher_role` | 11 | `VS. 先發`、`VS. 中繼`、`VS. 救援`（含 2 個 PATTERN） |
| `pitcher_background` | 8 | `VS. 本土投手`、`VS. 外籍投手`（含 2 個 PATTERN） |

**沒有自行新增任何 context。** 全部來自官方 `ItemGroupCode = 3`（Step 8 已取得的 7 個分項）。

命名對照：Step 9 內部把「本土 / 外籍」那一組命名為 `pitcher_origin`，
本階段依 Step 13 指示改用 `pitcher_background`。兩者指同一組官方分項。

### 2.3 `action_link`

三個欄位，全部限制在受控詞彙中。**這是「資料可以連到哪一類決策」的描述，不是決策本身。**

| `contextual_relevance` | `possible_action_link` | `action_link_basis` | `action_link_requires` | 數量 |
| --- | --- | --- | --- | ---: |
| `none` | `monitor_current_form` | `recent_games` | `next_game_context` | 4 |
| `pitcher_hand` | `compare_against_pitcher_hand_context` | `season_cumulative_pitcher_hand` | `next_starting_pitcher_hand` | 6 |
| `pitcher_role` | `compare_against_pitcher_role_context` | `season_cumulative_pitcher_role` | `in_game_pitcher_role_at_plate_appearance` | 11 |
| `pitcher_background` | `compare_against_pitcher_background_context` | `season_cumulative_pitcher_background` | `next_starting_pitcher_registration_status` | 8 |

### 2.4 `next_game_dependency`

| 值 | 數量 | 依據 |
| --- | ---: | --- |
| `true` | 4 | `temporal_relevance = recent_games`。近期表現本身不含對手資訊，需要下一場的對手與先發投手才能形成 matchup-specific 的意義。 |
| `false` | 25 | `temporal_relevance = season_cumulative`。本身就是一個完整的球季累計情境，不需要下一場資訊才能成立。 |

每筆記錄都附 `next_game_dependency_note`：
「此欄位描述 evidence 本身是否需要下一場資訊才完整，**不代表這個 candidate 有用或沒用**。」

---

## 3. 防止「描述」變成「建議」的機制

這是本階段最容易出錯的地方，所以用結構限制而不是靠自我約束。

所有決策相關欄位（7 個）的值都必須：

1. 是 ASCII **snake_case 識別字**（`^[a-z][a-z0-9_]*$`）
2. 屬於程式中明確宣告的**受控詞彙**

| 欄位 | 詞彙大小 |
| --- | ---: |
| `temporal_relevance` | 2 |
| `contextual_relevance` | 4 |
| `possible_action_link` | 4 |
| `action_link_basis` | 4 |
| `action_link_requires` | 4 |
| `possible_decision_area` | 3 |
| `evidence_label` | 3 |

驗證第 12 項檢查全部 7 × 29 = **203 個值**都通過這兩個條件。

因為值只能是識別字且必須在詞彙表內，
「應該讓張育成先發」這種自由文字**在結構上無法出現**在這些欄位裡。

每個 `action_chain` 另外帶一個 `decision_area_is_not` 清單，
明確宣告它不是 `recommendation` / `prediction` / `instruction` / `lineup_decision`。

---

## 4. Decision Perspectives（Part 2）

三個**並列**的研究視角。**不判斷哪個最重要。**
成員一律以 `candidate_id` 字典序列出，順序不代表優先度。

### Perspective A — Current Form（4 個）

問題：球員現在的狀態　scopes：`RECENT_10`、`RECENT_15`

```
TREND-…-RECENT_10-AVG
TREND-…-RECENT_10-SLG
TREND-…-RECENT_15-AVG
TREND-…-RECENT_15-SLG
```

### Perspective B — Matchup Context（17 個）

問題：特定投手情境　scopes：`VS_RIGHT`、`VS_LEFT`、`VS_STARTER`、`VS_RELIEF`、`VS_CLOSER`

```
CONTEXT-…-VS_CLOSER-AVG / OBP / SLG
CONTEXT-…-VS_LEFT-AVG / OBP / SLG
CONTEXT-…-VS_RELIEF-AVG / OBP / SLG
CONTEXT-…-VS_RIGHT-AVG / OBP / SLG
CONTEXT-…-VS_STARTER-AVG / OBP / SLG
PATTERN-…-VS_CLOSER-AVG_OBP_SLG
PATTERN-…-VS_STARTER-AVG_OBP_SLG
```

### Perspective C — Structural Context（8 個）

問題：長期球員表現結構　scopes：`VS_DOMESTIC`、`VS_FOREIGN`

```
CONTEXT-…-VS_DOMESTIC-AVG / OBP / SLG
CONTEXT-…-VS_FOREIGN-AVG / OBP / SLG
PATTERN-…-VS_DOMESTIC-AVG_OBP_SLG
PATTERN-…-VS_FOREIGN-AVG_OBP_SLG
```

### Membership 是一個 partition

4 + 17 + 8 = **29**，無重疊、無遺漏。
每個成員的 `scope` 都在該 perspective 宣告的 `scopes` 範圍內（驗證第 13 項）。

`membership_rule`：由 candidate 的 scope 直接查表決定，**不看數值**。

---

## 5. Action Chain（Part 3）

每個 candidate 都有完整的四段鏈：

```
candidate
  → evidence（evidence_label + 完整的 evidence_detail）
  → possible_context_needed
  → possible_decision_area
```

`possible_decision_area` 的分佈：

| 值 | 數量 | 對應 |
| --- | ---: | --- |
| `pre_game_preparation` | 10 | TREND（4）+ `pitcher_hand`（6） |
| `in_game_situational_preparation` | 11 | `pitcher_role` |
| `long_term_player_evaluation` | 8 | `pitcher_background` |

每筆都標記 `decision_area_mapping_basis: "provisional_descriptive_mapping"`。

**這個對照與 Step 10 的 tier 一樣是產品層面的暫定假設，沒有經過任何驗證，不是統計結論。**
換一組假設，對照就會不同。

### 範例（實際輸出）

```
TREND-…-RECENT_10-AVG
  → evidence: recent_window_batting_counts
     detail: magnitude=0.09340659(batting_average)  AB=42  PA=44  games=10
             percentile=94.1176  delta_if_one_more=0.02380952
  → possible_context_needed: next_game_context
  → possible_decision_area: pre_game_preparation
```

沒有出現任何具體棒球建議。

---

## 6. Part 4：三個 candidate 的多維度比較

挑這三個是因為它們在 Step 12 中分別代表三種極端。

| 維度 | `TREND-RECENT_10-AVG` | `CONTEXT-VS_CLOSER-AVG` | `CONTEXT-VS_RIGHT-OBP` |
| --- | --- | --- | --- |
| **Step 12 名次 A / B / C** | **1 / 6 / 24** | **10 / 3 / 29** | **29 / 29 / 1** |
| 挑選原因 | 高時間性 | 高 magnitude / 小樣本 | 大樣本 / 極小 magnitude |
| `temporal_relevance` | **`recent_games`** | `season_cumulative` | `season_cumulative` |
| `contextual_relevance` | **`none`** | **`pitcher_role`** | **`pitcher_hand`** |
| magnitude | 0.09340659 | **0.16320716** | **0.00002422** |
| magnitude 使用指標 | batting_average | batting_average | on_base_percentage |
| `at_bats` | 42 | **27** | **219** |
| `plate_appearances` | 44 | 31 | 258 |
| `games` | **10** | `null` | `null` |
| `percentile_rank` | **94.1176** | `null` | `null` |
| `delta_if_one_more` | 0.02380952 | **0.03703704** | **0.00387597** |
| magnitude / delta（相當於幾個事件） | 3.92 | **4.41** | **0.01** |
| `next_game_dependency` | **`true`** | `false` | `false` |
| `possible_action_link` | `monitor_current_form` | `compare_against_pitcher_role_context` | `compare_against_pitcher_hand_context` |
| `action_link_requires` | `next_game_context` | `in_game_pitcher_role_at_plate_appearance` | `next_starting_pitcher_hand` |
| `possible_decision_area` | `pre_game_preparation` | `in_game_situational_preparation` | `pre_game_preparation` |

### 這張表顯示的事情

**四個維度確實彼此獨立，沒有一個可以推導出另一個。**

- 只有 `TREND-RECENT_10-AVG` 有 `recent_games`、有 `games`、有 `percentile_rank`、
  `next_game_dependency = true`——但它的 magnitude 不是三者中最大的。
- `CONTEXT-VS_CLOSER-AVG` magnitude 最大（0.16320716）但樣本最小（27），
  而且 `contextual_relevance` 是 `pitcher_role`，對應的決策領域與另外兩個不同。
- `CONTEXT-VS_RIGHT-OBP` 樣本最大（219）但 magnitude 是全部 29 個中最小的
  （0.00002422）。**它的差距換算下來只相當於 0.01 個單一事件**——
  也就是連一次上壘都不到的差別。

三者的 `possible_decision_area` 落在三種不同組合上，
`action_link_requires` 也各不相同。

**這正是為什麼單一數值排序在 Step 12 會失敗：它把四個不同維度壓成一個維度。**

---

## 7. 觀察

以下只記錄從描述子看到的事實，**不做優先度判斷**。

### 7.1 `action_link_requires` 的資料可取得性差異很大

把 `action_link_requires` 與前面幾個 Step 的資料來源調查對照：

| `action_link_requires` | candidate 數 | 資料可取得性（依既有調查） |
| --- | ---: | --- |
| `next_game_context` | 4 | **已驗證可取得。** Step 3 的賽程 endpoint 提供下一場日期、對手、主客、場地。 |
| `next_starting_pitcher_hand` | 6 | **部分可取得。** Step 7A 驗證了「賽程投手 Acnt + 球員頁投打習慣」5 場全對；但未開打場次的預告先發 Acnt 語意仍未確認（Step 3、Step 7A 都標記為未確認）。 |
| `in_game_pitcher_role_at_plate_appearance` | **11** | **目前無法取得。** Step 7A 已確認逐場資料沒有投手資訊；逐打席投手只存在於 `/box/getlive`，該 payload 從未驗證過。 |
| `next_starting_pitcher_registration_status` | 8 | **未驗證。** 本專案從未調查官方是否提供投手的本土／外籍註冊狀態。 |

換算成 perspective：

| Perspective | 成員數 | action_link 所需資料的狀態 |
| --- | ---: | --- |
| A — Current Form | 4 | 4 個全部已驗證可取得 |
| B — Matchup Context | 17 | 6 個部分可取得、**11 個目前無法取得** |
| C — Structural Context | 8 | 8 個全部未驗證 |

**這是一個純事實的對照，不是優先度建議。** 但它指出一件事：
Perspective B 是成員最多的（17 個），而其中 11 個的 action link 所需資料目前拿不到。

### 7.2 `next_game_dependency` 與 `action_link_requires` 捕捉的是不同的事

25 個 candidate 的 `next_game_dependency = false`，但其中 **14 個**
（`pitcher_hand` 6 + `pitcher_background` 8）的 `action_link_requires`
明確需要下一場的資訊（`next_starting_pitcher_hand` 或
`next_starting_pitcher_registration_status`）。

這不是矛盾，而是兩個欄位描述不同層次：

- `next_game_dependency`：**evidence 本身**是否需要下一場資訊才完整
- `action_link_requires`：**把 evidence 應用到某個決策**時需要什麼額外資訊

`VS_LEFT-SLG` 作為球季累計事實是完整的（不需要下一場），
但要把它連到「下一場的準備」就需要知道下一場先發是不是左投。

**這個區分值得在下一階段被明確處理**，否則很容易把兩件事混為一談。

### 7.3 `pitcher_role` 是成員最多的 contextual_relevance（11 個）

11 個中包含樣本最小的 `VS_CLOSER`（AB 27，3 個 CONTEXT + 1 個 PATTERN）。
Step 12 中 Strategy B 的前 4 名全部來自 `VS_CLOSER`。

同時這 11 個的 `action_link_requires` 是目前唯一**確定拿不到**的資料。

### 7.4 `decision_area` 的對照是假設，不是結論

`pitcher_role → in_game_situational_preparation` 這種對照，
是我依「先發／中繼／救援是比賽進行中才確定的角色」推出的描述性對照。
它沒有經過球隊實務驗證。若實務上這類資訊是賽前準備的一部分，對照就該改。

### 7.5 只有一名球員、一個球季

29 個 candidate 全部來自張育成 2026 年。
不同球員的 candidate 組成可能完全不同（例如投手不會有這些打擊分項），
因此本次的描述子分佈不一定具有一般性。

---

## 8. Validation（Part 5）

程式執行 **15 項檢查，全部通過（15 / 15）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 1 | 29 個 candidate 全部都有 sidecar record | PASS |
| 2 | 2 | `candidate_id` 一一對應（無遺漏、無重複、無多餘） | PASS |
| 3 | 3 | candidate evidence 完全未被修改 | PASS　深度比較 29 個物件 |
| 4 | 4 | raw / processed data 未被修改 | PASS　sha256 前後不變 |
| 5 | 5 | 沒有任何 HTTP request | PASS　socket guard 生效 |
| 6 | 6 | 沒有 score 欄位 | PASS　遞迴掃描所有巢狀欄位名 |
| 7 | 7 | 沒有 weight 欄位 | PASS |
| 8 | 10 | 沒有 confidence score | PASS |
| 9 | 8 | 沒有 threshold | PASS　29/29 全部有 record |
| 10 | 9 | 沒有 ranking | PASS　無 candidate 名次欄位，perspective 成員為字典序 |
| 11 | 11–13 | 沒有 prediction / recommendation / 自然語言結論字眼 | PASS |
| 12 | 14 | 決策欄位全部是受控詞彙中的 snake_case 識別字 | PASS　203 個值全部通過 |
| 13 | 15 | 三個 perspective 的 membership 可追溯且形成 partition | PASS　4+17+8=29，無重疊 |
| 14 | 16 | 相同輸入重跑結果完全一致 | PASS　整個流程重跑後序列化結果相同 |
| 15 | — | Part 4 指定的三個 candidate 都存在 | PASS |

### 幾項檢查的實作方式

**第 12 項是本階段最重要的檢查。** 它不是掃描禁用字眼（那只能抓已知的壞字），
而是**正面限制**：決策欄位的值必須是 snake_case 識別字，且必須在宣告的詞彙表中。
這讓自由文字的棒球建議在結構上無法出現。

**第 13 項** 檢查三件事：三個 perspective 的成員聯集等於全部 29 個 candidate、
成員之間無重疊、每個成員的 `scope` 都在該 perspective 宣告的範圍內。

**第 14 項** 把整個產出流程（讀檔 → 建 candidate → 建 sample → 建 view → 建 record →
建 perspective）完整重跑一次，再比對 `sort_keys=True` 的 JSON 序列化結果。

**第 3 / 4 項** sha256：
`zhang_yucheng_game_logs_2026.json` = `e3712d87…`、30,547 bytes；
`apart_score_0000006888_2026_A_01.json` = `8565cc8c…`、56,826 bytes。

### 開發過程中修正的一個誤判

第 10 項（沒有 ranking）第一次執行時 FAIL，抓到 29 個
`action_chain.evidence_detail.percentile_rank` 欄位——原因是我的掃描比對子字串 `rank`。

但 `percentile_rank` 是 Step 6 建立的 **evidence 描述子**
（該值在滾動分布中的經驗百分位），**不是 candidate 之間的名次**。
本階段只是原值攜帶它。

處理方式：把 `percentile_rank` 這個確切欄位名加入白名單，並在檢查說明中寫明原因。
除此之外任何含 `rank` 的欄位名仍會被抓出。
**這是修正檢查本身的實作精確度，沒有改動任何資料或欄位。**

---

## 9. 交給下一階段（由人決定）的問題

本階段刻意不回答，以下列出需要你決定的事：

1. **`action_link_requires` 的資料可取得性，是否應該影響產品優先順序？**
   Perspective A 的 4 個 candidate 所需資料已驗證可取得；
   Perspective B 有 11/17 目前拿不到；Perspective C 的 8 個從未驗證。
   （7.1 節，純事實對照）

2. **`next_game_dependency` 與 `action_link_requires` 的區分要怎麼呈現？**
   14 個 candidate 的 evidence 本身完整，但應用到決策時仍需要下一場資訊。
   （7.2 節）

3. **`decision_area` 的對照是否符合球隊實務？**
   特別是 `pitcher_role → in_game_situational_preparation` 這一條。（7.4 節）

4. **三個 perspective 要並列呈現，還是選一個作為主視角？**
   Step 12 已顯示不同排序哲學的 Top 10 沒有交集，
   而三個 perspective 是另一種切法（依決策問題切，而非依數值切）。

5. **是否需要為 Perspective B 的 11 個 `pitcher_role` candidate 補資料？**
   若需要，唯一的路是 Step 7A 記錄的路線 3（`/box/getlive` 逐打席），
   成本最高且 payload 尚未驗證。

---

## 10. 本階段刻意沒有做的事

- 沒有回答「哪個 candidate 最重要」
- 沒有回答「哪個 perspective 最好」
- 沒有建立 ranking、score、weight、threshold、confidence score
- 沒有產生 prediction、recommendation、自然語言結論
- 沒有出現任何具體棒球建議（以受控詞彙 + 識別字格式在結構上排除）
- 沒有使用 LLM
- 沒有新增資料來源、沒有新增任何 context
- 沒有 HTTP request（socket guard 強制保證）
- 沒有修改 candidate evidence（sidecar 設計 + 深度比較驗證）
- 沒有修改 `data/raw/` 或 `data/processed/` 的檔案（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

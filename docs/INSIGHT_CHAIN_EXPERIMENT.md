# Insight Chain Experiment（Step 14）

建立日期：2026-08-20
產出腳本：`src/insight_chain.py`
前置文件：Step 2 ~ Step 13 的全部調查與 evidence 文件

> ## 這一步驗證什麼
>
> **現有資料能否可靠地組合成一條與下一場比賽有關的 evidence chain？**
>
> ```
> 球員近期狀態 → 下一場比賽 → 對手 → 預告先發投手 → 投手左右手 → 歷史 matchup
> ```
>
> **不含：** 自然語言建議、recommendation、prediction、ranking、score、weight、
> threshold、confidence score、LLM、新資料來源、`/box/getlive`、dashboard。
>
> **最重要的原則：** node 無法可靠建立時，**保留 node 並標示 blocked / unverified**，
> 比填入猜測值重要。

---

## 1. Chain 的目的

前面 13 個 Step 各自產出了獨立的 evidence，但從來沒有把它們串起來過。
Step 13 記錄了一件事：`TREND` candidate 的 `next_game_dependency = true`，
也就是近期表現要有 matchup-specific 的意義，必須接上下一場的資訊。

本階段第一次實際嘗試這件事，目的不是產生 insight，而是**找出這條鏈在哪裡會斷**。

### 結論先講

| 項目 | 結果 |
| --- | --- |
| chain 是否建立 | **是**（5 nodes / 4 edges，結構完整） |
| chain 是否完全解出 | **否** |
| 可用的 node | N1 current_form、N2 next_game、N3 next_starting_pitcher |
| **被阻斷的 node** | **N4 pitcher_hand、N5 historical_matchup** |
| 第一個阻斷點 | **N4_NEXT_STARTER_HAND** |

`chain_id`：`CHAIN-PREGAME-MATCHUP-0000006888-2026-GAMESNO279`

---

## 2. Node schema

每個 node 的固定結構：

| 欄位 | 說明 |
| --- | --- |
| `node_id` | 唯一識別（`N1_CURRENT_FORM` 等） |
| `node_type` | `current_form` / `next_game` / `next_starting_pitcher` / `pitcher_hand` / `historical_matchup` |
| `status` | `usable` / `unusable_blocked`（受控詞彙） |
| `verification_status` | 受控詞彙，5 個值（見第 5 節） |
| `evidence` | 該 node 的實際資料 |
| `source_steps` | 來自哪些 Step |
| `source_files` | 實際檔案路徑 |
| `provenance` | 逐欄位的來源與推導方式（見第 6 節） |

驗證第 24 項檢查 5 個 node 全部具備這些欄位，且 `status`、`verification_status`、
`provenance[].derivation` 的值都在受控詞彙中。

---

## 3. Edge schema

| 欄位 | 說明 |
| --- | --- |
| `edge_id` | 唯一識別 |
| `from_node` / `to_node` | 端點的 `node_id`（驗證會檢查端點存在） |
| `basis_code` | 受控詞彙，說明「為什麼 A 可以連到 B」 |
| `basis` | 同一件事的完整文字說明 |
| `verification_status` | 這條連接的驗證狀態 |
| `blocked_reason` | 若被阻斷，說明原因；否則 `null` |

### 四條 edge

| edge | basis_code | verification_status |
| --- | --- | --- |
| `E1` N1 → N2 | `current_form_requires_next_game_context` | `verified_against_processed_schedule` |
| `E2` N2 → N3 | `schedule_game_record_contains_pitcher_account_identifier` | `unconfirmed_upcoming_starter_identity` |
| `E3` N3 → N4 | `player_profile_provides_throwing_batting_handedness` | **`missing_required_data`** |
| `E4` N4 → N5 | `official_item_group_3_provides_season_cumulative_vs_hand_split` | **`blocked_by_unverified_upcoming_starter`** |

---

## 4. Evidence definition

### N1 — current_form（`usable`）

全部引用 Step 5 的 `build_window()`，**沒有另建定義**。

| 窗口 | games | PA | AB | H | HR | RBI | TB | AVG | SLG | OBP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| RECENT_10 | 10 | 44 | 42 | 17 | 2 | 9 | 26 | 0.40476190 | 0.61904762 | `null` |
| RECENT_15 | 15 | 63 | 58 | 19 | 2 | 10 | 29 | 0.32758621 | 0.50000000 | `null` |
| SEASON_CUMULATIVE | 77 | 320 | 273 | 85 | 14 | 39 | 145 | 0.31135531 | 0.53113553 | `null` |

日期範圍：RECENT_10 `2026-08-02 ~ 2026-08-18`、RECENT_15 `2026-07-26 ~ 2026-08-18`、
SEASON `2026-03-29 ~ 2026-08-18`。三個窗口的完整 `game_snos` 都在 node 中
（10 / 15 / 77 個）。

OBP 為 `null`，附 `on_base_percentage_missing_reason`：
processed data 未收逐場犧牲飛球（Step 5 / Step 11 已記錄）。**沒有估算。**

### N2 — next_game（`usable`）

| 欄位 | 值 |
| --- | --- |
| `game_sno` | **279** |
| `game_date` | **2026-08-21** |
| `scheduled_time` | **18:35** |
| `opponent` | **味全龍** |
| `home_away` | **home**（富邦主場） |
| `venue` | **新莊** |
| `game_status` | 未開打或進行中（`game_result_code = ''`） |
| `home_score` | **`null`** |
| `visiting_score` | **`null`** |

**比分處理：** processed schedule 中這場的 `home_score` / `visiting_score` 都是 `0`，
但 Step 4 已記錄那是官方預設值而非真實比分。
因此 node 中一律為 `null`，原始值保留在
`source_score_values_for_traceability`（`{home_score_in_file: 0, visiting_score_in_file: 0}`）
供追溯，並附 `score_is_null_reason` 說明。

**「下一場」的選擇規則（決定性設計）：**

```
reference_date = max(game_date where game_result == '0')   → 2026-08-18
next_game      = 從 game_result == '' 且 game_date > reference_date 的場次中，
                 依 (game_date, scheduled_time, game_sno) 取最早的一場
```

**不使用系統時鐘。** 參考日由資料本身推導（富邦已完成比賽中最晚的日期），
因此在任何時間重跑都得到相同結果。這是為了滿足驗證第 23 項（determinism）。

驗證第 3 項另外確認沒有任何更早的未開打場次被跳過（`更早的未開打場次數 = 0`）。

### N3 — next_starting_pitcher（`usable`，但 `unconfirmed_upcoming_starter_identity`）

| 欄位 | 值 |
| --- | --- |
| `pitcher_acnt` | **`0000006497`** |
| `pitcher_name` | **`null`** |
| `team` | 味全龍（`team_side = visiting`） |

富邦是主隊，所以取對手那一側的 `visiting_pitcher_acnt`。
`selected_by_rule` 的規則寫在 provenance 中。

`pitcher_name` 為 `null` 而不是空字串：schedule 中未開打場次的投手姓名是空字串，
**空字串不是姓名**。要取得姓名需查球員頁，而本階段禁止 HTTP 請求。

#### 一個支持性觀察（不構成證明）

未開打的 **31** 場富邦賽事中，**只有下一場（game_sno 279）帶有投手 Acnt**，
其餘 30 場的投手欄位都是空字串。

這個觀察與「該欄位是預告先發」相容，但**不是證明**。
node 中以 `supporting_observation.interpretation_limit` 明確記錄這一點。

### N4 — pitcher_hand（`unusable_blocked`，`missing_required_data`）

| 欄位 | 值 |
| --- | --- |
| `hand` | **`null`** |
| `evidence_basis` | `null` |
| `missing_reason` | 取得手別需要 `GET /team/person?Acnt=0000006497` 的「投打習慣」欄位，而本階段禁止 HTTP 請求；且該 Acnt 不在 Step 7A 已驗證的 5 筆之中，本專案沒有任何本地資料記載它的手別。 |
| `required_to_resolve` | `GET /team/person?Acnt=0000006497` 並解析「投打習慣」（右投 → R，左投 → L） |

Step 7A 的 5 筆已驗證記錄原樣保留在 `method_reference.verified_records`，
並標記 `acnt_in_verified_reference = false`——
**這 5 筆只是方法參考，沒有被用來推論本場投手的手別。**

驗證第 8 項專門檢查這件事：本場 `hand` 為 `null`、Step 7A 的 5 筆記錄未被改動、
5 筆的「投打習慣 → R/L」對應一致、且本場 Acnt 不在那 5 筆之中（避免誤用）。

### N5 — historical_matchup（`unusable_blocked`，`blocked_by_unverified_upcoming_starter`）

| 欄位 | 值 |
| --- | --- |
| `historical_matchup_basis` | **`season_cumulative_vs_pitcher_hand`** |
| `selected_branch` | **`null`** |
| `selection_blocked_reason` | 上游 N4 的 `hand` 為 `null`，無法決定引用 VS_LEFT 還是 VS_RIGHT。**本階段不自行選一邊。** |
| `unselected_branches_available` | `["VS_LEFT", "VS_RIGHT"]` |

兩個分項的資料本身**都已備妥且已驗證**，只是缺少選擇的依據。原樣列在 `branches` 中：

| branch | 官方 ItemName | PA | AB | H | TB | AVG | OBP | SLG |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `VS_RIGHT` | VS. 右投 | 258 | 219 | 68 | 122 | 0.31050228 | 0.40310078 | 0.55707763 |
| `VS_LEFT` | VS. 左投 | 62 | 54 | 17 | 23 | 0.31481481 | 0.40322581 | 0.42592593 |

每個 branch 都帶 Step 11 的 `sample_context`：
`VS_RIGHT` AB 219 / PA 258 / `delta_if_one_more(AVG)` 0.00456621；
`VS_LEFT` AB 54 / PA 62 / `delta_if_one_more(AVG)` 0.01851852。
`games` 皆為 `null`（官方分項無場次欄位）。

---

## 5. Verification status

受控詞彙，5 個值。驗證第 24 項檢查所有 node 的值都在其中。

| 值 | 意義 | 本 chain 中的使用 |
| --- | --- | --- |
| `verified_cross_checked_with_prior_steps` | 數字已與前面 Step 的記錄交叉核對過 | N1 |
| `verified_against_processed_schedule` | 已與 processed schedule 逐欄位核對 | N2、E1 |
| `unconfirmed_upcoming_starter_identity` | 值取得成功，但「未開打場次的 Acnt 代表預告先發」未經驗證 | N3、E2 |
| `missing_required_data` | 所需資料在本階段無法取得，值為 `null` | N4、E3 |
| `blocked_by_unverified_upcoming_starter` | 因上游未確認而無法決定，不自行選擇 | N5、E4 |

**`verified` 這個詞只出現在真的做過交叉核對的 node 上。**
N3 明確不使用 `verified`（驗證第 7 項會檢查）。

---

## 6. Data provenance

每個 node 都有 `provenance` 陣列，**逐欄位**記錄來源。全 chain 共 **16 筆**。

每筆包含：`source_step`、`source_file`、`source_field`、`derivation`，
計算值另外必附 `formula`。

`derivation` 是受控詞彙：

| 值 | 意義 |
| --- | --- |
| `direct_source_value` | 直接引用來源欄位，未加工 |
| `computed_from_source_counts` | 由來源計數計算，**必附 formula** |
| `selected_by_rule` | 依明確規則從多個來源值中選出，**必附 formula** |
| `not_available` | 資料不足，值為 `null`，不估算 |

### 實際範例

```json
{
  "source_step": "Step 4",
  "source_file": "data/processed/fubon_schedule_2026.json",
  "source_field": "visiting_pitcher_acnt",
  "derivation": "selected_by_rule",
  "formula": "富邦為主隊時取 visiting_pitcher_acnt，為客隊時取 home_pitcher_acnt",
  "note": "原始欄位為 Step 3 的 VisitingPitcherAcnt / HomePitcherAcnt"
}
```

```json
{
  "source_step": "Step 8",
  "source_file": "src/context_splits.py",
  "source_field": "on_base_percentage",
  "derivation": "computed_from_source_counts",
  "formula": "(hits + walks + hit_by_pitch) / (at_bats + walks + hit_by_pitch + sacrifice_flies)",
  "note": "walks 已含故意四壞（Step 7B 以打席恆等式實證），不再加 IBB"
}
```

沒有任何 `"source": "CPBL"` 這種模糊記錄。

---

## 7. Known limitations

### 7.1 chain 在 N4 之後完全斷開

`hand` 為 `null` → N5 無法選擇分項。這是本 chain 最實質的限制。
**兩個原因疊加**：

1. 本階段禁止 HTTP 請求，所以無法查球員頁的「投打習慣」
2. 即使查到手別，N3 的身分本身仍未確認（見 7.2）

也就是說**解除第 1 個限制還不足以解出這條 chain**，第 2 個限制才是根本問題。

### 7.2 只有一場、只有一名球員

chain 只針對 game_sno 279 與張育成一人。
未開打場次中也只有這一場帶投手 Acnt，所以無法用多場樣本檢驗一致性。

### 7.3 current_form 缺 OBP

三個窗口的 OBP 都是 `null`。若要補，需回到 Step 4 把 `SacrificeFlyCnt`
收進 processed data——那是資料層變更，不在本階段範圍。

### 7.4 `game_status` 無法區分「未開打」與「進行中」

Step 3 已記錄：進行中的比賽 `GameResult` 也是空字串。
processed schedule 的 `game_status` 因此寫成「未開打或進行中」。
本 chain 沒有嘗試區分，也沒有推測比賽狀態。

### 7.5 沒有寫出檔案

chain 只在程式輸出中，沒有寫入 `data/`。
理由與 Step 10 ~ 13 相同：它仍屬實驗階段的產出。

### 7.6 `historical_matchup` 只有手別一個維度

Step 8 另有 `VS. 先發 / 中繼 / 救援`、`VS. 本土 / 外籍` 兩組分項。
本 chain 依 Step 14 的指示只串手別。Step 13 已記錄
`pitcher_role` 那 11 個 candidate 所需的逐打席角色資料目前拿不到。

---

## 8. 為什麼不能把 upcoming pitcher Acnt 當成已確認先發

三個依據，全部來自既有記錄，不是推測：

1. **官方沒有任何文字說明。** Step 3 調查賽程 endpoint 時，
   `HomePitcherAcnt` / `VisitingPitcherAcnt` 這兩個欄位在官方頁面上沒有文件說明。
   Step 3 已把「未開打場次的 Acnt 是否確為預告先發」列為未確認。

2. **姓名為空是一個異常訊號。** 已完成比賽的 `PitcherName` 有值，
   未開打場次的 `PitcherName` 是空字串而 `PitcherAcnt` 有值。
   這種不一致本身就需要解釋，而官方沒有提供解釋。
   官網的顯示邏輯是「Name 非空才顯示先發」，所以**官網自己也不會顯示這場的先發**。

3. **Step 7A 的驗證範圍不涵蓋這個情況。** Step 7A 的 5/5 通過全部是
   **已完成**比賽。它證明的是「已完成比賽的 Pitcher 欄位是先發投手」
   （另外用 87 場 × 2 側的比對排除了「是勝敗投」的可能，36 次不同）。
   它**沒有**證明未開打場次的 Acnt 代表預告先發。

因此 N3 的 `verification_status` 是 `unconfirmed_upcoming_starter_identity`。

### 支持但不足以證明的觀察

31 場未開打賽事中只有下一場帶 Acnt。這與「預告先發只會提前一場公布」相容，
但也可能有其他解釋（例如資料尚未填入、或該欄位在未開打場次有其他用途）。
在官方說明或多場樣本驗證之前，本專案不認定。

---

## 9. 為什麼不能把 VS_LEFT / VS_RIGHT 解釋成整場逐球 matchup

`historical_matchup_basis` 明確定為 `season_cumulative_vs_pitcher_hand`，
node 中另有 `basis_is_not` 欄位聲明它**不是**什麼。三個理由：

### 9.1 它是整季累計，不是某一場

`VS. 右投` 涵蓋 2026 一軍例行賽全季所有面對右投的 258 個打席，
橫跨 3 月到 8 月。它與 game_sno 279 這一場沒有任何直接關係。

### 9.2 「對手先發投手」與「該場所有投手」是兩件不同的事

Step 7A 用官方分項量化過這件事：

| 分項 | PA | 佔全季 320 PA |
| --- | ---: | ---: |
| VS. 先發 | 209 | 65.3% |
| VS. 中繼 | 80 | 25.0% |
| VS. 救援 | 31 | 9.7% |

**張育成本季有 34.7% 的打席不是面對先發投手。**
若把「對手先發投手的手別」當成整場的 matchup 基礎，
超過三分之一的打席會被錯誤歸類。

### 9.3 它不是逐打席，更不是逐球

官方分項只給彙總，沒有日期、沒有場次、沒有打席明細（Step 8 已記錄）。
逐打席投手資訊只存在於 `/box/getlive`，而該 payload 從 Step 2 至今從未驗證過，
本階段也明確禁止呼叫。

驗證第 10 項檢查 `basis_is_not` 確實包含「不是」與「逐球」的聲明。

---

## 10. 哪些地方目前可以串接

| 連接 | 狀態 | 依據 |
| --- | --- | --- |
| 近期狀態 → 下一場比賽 | **可串** | Step 3 賽程已驗證；日期、時間、對手、主客、場地全部可得 |
| 下一場比賽 → 對手 | **可串** | `opponent` 直接由主客隊代碼推導，Step 4 已驗證 |
| 下一場比賽 → 投手 Acnt | **可取值，但身分未確認** | Acnt 存在（`0000006497`），語意未經驗證 |
| 投手 Acnt → 手別（**已完成**比賽） | **可串且已驗證** | Step 7A 5/5 通過 |
| 手別 → VS_LEFT / VS_RIGHT | **資料已備妥** | Step 8 兩個分項都已驗證，與 Step 5 季累計對帳一致 |

也就是說：**鏈的兩端都是健全的，斷點在中間。**

---

## 11. 哪些地方目前被資料缺口阻斷

| 阻斷點 | 原因 | 解除條件 |
| --- | --- | --- |
| **N3 的身分確認** | 官方未說明未開打場次的 Acnt 語意；Step 7A 未涵蓋此情況 | 需要跨日觀察多場，比對「公布的預告先發」與該 Acnt 是否一致 |
| **N4 的手別** | 本階段禁止 HTTP；且該 Acnt 不在任何本地資料中 | 需要 `GET /team/person?Acnt=0000006497`（單一請求即可） |
| **N5 的分項選擇** | 上游手別為 null | 解除 N4 即自動解除 |

### 兩個阻斷點的性質完全不同

- **N4 是「成本」問題**：一個 HTTP 請求就能解決，方法已在 Step 7A 驗證過 5 次。
- **N3 是「知識」問題**：沒有任何請求可以直接解決它。
  需要跨日累積觀察，或找到官方說明。

**這個區分很重要**：如果只解除 N4（放行一個請求），chain 會變成
「手別已知，但先發身分仍未確認」。那時 N5 是否該解鎖，是一個需要你決定的問題——
本階段不代為決定。

---

## 12. Validation

程式執行 **26 項檢查，全部通過（26 / 26）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 1 | chain player == 張育成 | PASS |
| 2 | 2 | chain season == 2026 | PASS |
| 3 | 3 | next game 確實是下一場未完成富邦賽事 | PASS　參考日 2026-08-18，選出 279，更早的未開打場次 0 個 |
| 4 | 4 | opponent / home_away / venue / 日期時間 / 狀態與 processed schedule 一致 | PASS |
| 5 | 5 | 未開打比賽的 score 為 `null`，未被解讀為 0:0 | PASS　原值 0 保留於追溯欄位並附說明 |
| 6 | 6 | `pitcher_acnt` 來自 schedule 的對應欄位 | PASS　`visiting_pitcher_acnt` = `0000006497` |
| 7 | 7 | 未確認的 upcoming pitcher identity 沒有被標成 verified | PASS |
| 8 | 8 | pitcher hand 的處理符合 Step 7A | PASS　本 chain 未宣稱手別；5 筆參考未被挪用 |
| 9 | 9 | historical matchup 只引用官方 VS. 右投 / VS. 左投 | PASS |
| 10 | 10 | 定義明確排除「該場所有投手 / 逐打席 / 逐球」 | PASS |
| 11 | 11 | PA / AB / H / TB 與 Step 8 完全一致 | PASS　258/219/68/122、62/54/17/23 |
| 12 | 12 | AVG / OBP / SLG 與 Step 8 完全一致 | PASS　6 個比率全符（含官方 4 位截斷比對） |
| 13 | 13 | `sample_context` 與 Step 11 一致 | PASS |
| 14 | 14 | raw data 未被修改 | PASS |
| 15 | 15 | processed data 未被修改 | PASS |
| 16 | 16 | 沒有產生 HTTP request | PASS　socket guard 生效 |
| 17 | 17 | 沒有使用 LLM | PASS　AST 解析 import + `sys.modules` 比對 |
| 18 | 18 | 沒有產生 ranking | PASS |
| 19 | 19 | 沒有產生 score | PASS |
| 20 | — | 沒有 weight / threshold / confidence score | PASS |
| 21 | 20–22 | 沒有 recommendation / prediction / 自然語言結論 | PASS |
| 22 | 23 | 相同輸入重跑結果完全一致 | PASS |
| 23 | 24 | 所有 node 都有 source / verification_status / provenance | PASS　16 筆 provenance，計算值皆附 formula |
| 24 | 25 | 所有 edge 都有 basis 且端點存在 | PASS |
| 25 | 26 | **Chain completeness check** | PASS　見下 |
| 26 | — | current_form 的數字與 Step 5 / Step 9 記錄一致 | PASS |

### 第 25 項（Chain completeness）的實際內容

```
chain_constructed    = True
chain_fully_resolved = False
blocked_nodes        = ["N4_NEXT_STARTER_HAND", "N5_HISTORICAL_MATCHUP"]
N5 verification_status = "blocked_by_unverified_upcoming_starter"
N5 selected_branch     = null
N4 hand                = null
```

chain 在上游未確認的情況下**仍然完整建立**，
而 N5 明確標示為 `blocked_by_unverified_upcoming_starter`，
**沒有自行選 LEFT 或 RIGHT**。

### hash 記錄

| 檔案 | sha256 前 8 碼 | bytes |
| --- | --- | --- |
| `data/processed/zhang_yucheng_game_logs_2026.json` | `e3712d87` | 30,547 |
| `data/processed/fubon_schedule_2026.json` | `c09a5119` | 57,227 |
| `data/raw/apart_score_0000006888_2026_A_01.json` | `8565cc8c` | 56,826 |

執行前後完全一致。

---

## 13. 開發過程中修正的兩個檢查實作錯誤

依 Step 14 的要求（「不要直接放寬檢查，先找出 FAIL 的真正原因」），
第一次執行時的 2 個 FAIL 都追到根因後才修正。
**兩者都是檢查本身的實作錯誤，沒有改動任何資料、chain 內容或標準。**

### 13.1 「沒有使用 LLM」FAIL — 自我命中

**現象：** 檢查報告 `發現：['openai', 'anthropic', 'gpt', 'llm(', 'completion(', 'chat(']`。

**根因：** 檢查的做法是讀自己的原始碼文字，搜尋這幾個字串。
但這幾個字串本身就是寫在同一個檔案裡的比對清單，因此必然命中自己。
這是一個典型的自我參照 bug，與是否真的用了 LLM 完全無關。

**修正：** 改成**結構性檢查**而不是文字掃描：

1. 用 `ast` 解析本檔案，取出所有實際 `import` 的頂層模組名稱
2. 比對 17 個已知 LLM / ML 套件名稱（`openai`、`anthropic`、`transformers`、
   `langchain`、`torch` 等）
3. 另外比對 `sys.modules`，確認執行期也沒有載入任何這些套件

修正後的實際輸出：本檔案 import 的 11 個頂層模組是
`__future__`、`ast`、`candidate_insights`、`copy`、`evidence_sample_context`、
`json`、`math`、`pathlib`、`player_form_analysis`、`re`、`sys`。
全部是標準函式庫或本專案模組。

這個版本比原版**更嚴格**：它會抓到真正的 import，而不是只抓字串。

### 13.2 「沒有 weight / threshold / confidence score」FAIL — 否定宣告被計入

**根因：** chain 頂層有一個 `contains_no` 清單，內容是
`["ranking", "score", "weight", "threshold", "confidence_score", ...]`，
用途正是宣告「本 chain 不含這些東西」。
而檢查用 `"threshold" not in blob` 掃描整份序列化字串，
所以這個否定宣告本身被算成違規。

**修正：** 與 Step 10 ~ 13 的處理方式一致——先算出 `contains_no` 與 `basis_is_not`
這兩個宣告性欄位的出現次數，掃描時扣除。
若 `threshold` 出現在其他任何欄位仍會被抓出。

---

## 14. 本階段刻意沒有做的事

- 沒有產生自然語言 insight、沒有 recommendation、沒有 prediction
- 沒有建立 ranking、score、weight、threshold、confidence score
- 沒有使用 LLM（以 AST import 檢查 + `sys.modules` 比對驗證）
- 沒有新增資料來源、沒有呼叫 `/box/getlive`、沒有呼叫 `/team/person`
- 沒有任何 HTTP request（socket guard 強制保證）
- 沒有 dashboard
- 沒有修改 `data/raw/` 或 `data/processed/` 的檔案（三個檔案 sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- **沒有為了讓 chain 看起來完整而猜測任何值**：
  `pitcher_name`、`hand`、`selected_branch`、比分全部為 `null`
- 沒有把未開打場次的 0 分解讀為 0:0
- 沒有把 Step 7A 的 5 筆已驗證手別挪用到本場
- 沒有自行決定「解除 N4 之後 N5 是否該解鎖」
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

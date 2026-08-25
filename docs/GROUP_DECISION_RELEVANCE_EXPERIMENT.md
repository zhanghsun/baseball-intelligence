# Group-level Decision Relevance Experiment（Step 19）

建立日期：2026-08-20
產出腳本：`src/group_decision_relevance.py`
沿用文件：`docs/INSIGHT_GROUPING_EXPERIMENT.md`（Step 18）、
`docs/DECISION_RELEVANCE_EXPERIMENT.md`（Step 13）、
`docs/CANDIDATE_INSIGHT_DESIGN.md`（Step 9）、
`docs/INSIGHT_RANKING_DESIGN.md`（Step 10）、
`docs/EVIDENCE_SAMPLE_ANALYSIS.md`（Step 11）
沿用程式：`src/insight_grouping.py`、`src/decision_relevance.py`

> ## 這一步研究什麼
>
> Step 18 的 **9 個 insight group**，哪些與實際決策的關聯比較直接。
>
> **只研究「決策關聯結構」，不研究證據強度。**
>
> **不含：** ranking、Top-N、score、weight、threshold、priority、importance、
> confidence score、prediction、recommendation、自然語言推薦、LLM。
>
> 研究對象固定為 Step 18 的 9 個 group，**沒有新增任何 candidate 或 group**。

---

## 1. 受控詞彙

### 沿用 Step 13（6 組，完全未改動）

| 欄位 | 值數 | 值 |
| --- | ---: | --- |
| `temporal_relevance` | 2 | `recent_games`、`season_cumulative` |
| `contextual_relevance` | 4 | `none`、`pitcher_hand`、`pitcher_role`、`pitcher_background` |
| `possible_action_link` | 4 | `monitor_current_form` 等 |
| `action_link_basis` | 4 | `recent_games`、`season_cumulative_*` |
| `action_link_requires` | 4 | `next_game_context` 等 |
| `possible_decision_area` | 3 | `pre_game_preparation`、`in_game_situational_preparation`、`long_term_player_evaluation` |

驗證確認 6 × 9 = **54 個值全部在 Step 13 的詞彙中**，沒有任何自由文字。

### 本階段新增一組最小詞彙：`data_availability`

| 值 |
| --- |
| `verified_available` |
| `partially_verified` |
| `not_investigated` |
| `currently_unavailable` |

**為什麼必須新增：**

Step 13 第 7.1 節**已經**把每個 `action_link_requires` 的資料可取得性寫成散文
（「已驗證可取得」「部分可取得」「目前無法取得」「未驗證」），
但 Step 13 **沒有**把它做成受控詞彙欄位，程式輸出中也沒有對應欄位。
本階段需要一個機器可讀、可驗證的欄位，因此新增。

**為什麼是最小的：**

只有 4 個值，與 Step 13 第 7.1 節的四種散文描述**一對一**。
沒有新增第五種狀態，也沒有為任何 `action_link_requires`
改變既有的事實判定。判定依據全部指回既有 Step。

**先檢查過既有詞彙不足：** Step 13 的 6 組詞彙描述的是
「時間性 / 情境 / 行動連結 / 決策領域」，沒有任何一組表達「資料能不能拿到」。
`action_link_requires` 只說「需要什麼」，不說「拿不拿得到」。因此無法用既有詞彙表達。

---

## 2. 9 個 group 的 decision relevance 結構

| scope | temporal_relevance | contextual_relevance | evidence 依賴下一場 | data_availability |
| --- | --- | --- | --- | --- |
| `RECENT_10` | `recent_games` | `none` | **true** | **`verified_available`** |
| `RECENT_15` | `recent_games` | `none` | **true** | **`verified_available`** |
| `VS_LEFT` | `season_cumulative` | `pitcher_hand` | false | `partially_verified` |
| `VS_RIGHT` | `season_cumulative` | `pitcher_hand` | false | `partially_verified` |
| `VS_STARTER` | `season_cumulative` | `pitcher_role` | false | **`currently_unavailable`** |
| `VS_RELIEF` | `season_cumulative` | `pitcher_role` | false | **`currently_unavailable`** |
| `VS_CLOSER` | `season_cumulative` | `pitcher_role` | false | **`currently_unavailable`** |
| `VS_DOMESTIC` | `season_cumulative` | `pitcher_background` | false | `not_investigated` |
| `VS_FOREIGN` | `season_cumulative` | `pitcher_background` | false | `not_investigated` |

### action_link 與所需資料

| scope | `possible_action_link` | `possible_decision_area` | `action_link_requires` |
| --- | --- | --- | --- |
| `RECENT_10` / `RECENT_15` | `monitor_current_form` | `pre_game_preparation` | `next_game_context` |
| `VS_LEFT` / `VS_RIGHT` | `compare_against_pitcher_hand_context` | `pre_game_preparation` | `next_starting_pitcher_hand` |
| `VS_STARTER` / `VS_RELIEF` / `VS_CLOSER` | `compare_against_pitcher_role_context` | `in_game_situational_preparation` | `in_game_pitcher_role_at_plate_appearance` |
| `VS_DOMESTIC` / `VS_FOREIGN` | `compare_against_pitcher_background_context` | `long_term_player_evaluation` | `next_starting_pitcher_registration_status` |

（表格依 scope 字典序或分組呈現，**不是排名**。）

---

## 3. 兩種 dependency 的區分（設計要求 4）

這兩件事**刻意分成兩個獨立欄位**，不混在一起：

| 欄位 | 描述的是 | 來源 |
| --- | --- | --- |
| `next_game_dependency.evidence_depends_on_next_game` | **evidence 本身**是否需要下一場資訊才完整 | Step 13 的 `next_game_dependency`，原樣沿用 |
| `application_dependency.requires_additional_data` | **把 evidence 應用到下一場決策時**是否需要額外資料 | 由 `action_link_requires` 是否為非 null 導出 |

每個欄位都帶 `is_not` / `distinction_note` 明確聲明它不是另一件事。

### 結果

| | evidence 依賴下一場 | 應用時需要額外資料 |
| --- | ---: | ---: |
| true | **2**（RECENT_10、RECENT_15） | **9**（全部） |
| false | 7 | 0 |

**7 個 group 的 evidence 本身是自足的（`season_cumulative`），
但它們應用到決策時全部需要額外資料。**

這正是 Step 13 第 7.2 節記錄過的張力，本階段把它做成兩個可驗證的欄位。

---

## 4. 回答：哪些 group 直接連到下一場

**evidence 本身直接連到下一場（`next_game_dependency = true`）：2 個**

```
RECENT_10
RECENT_15
```

依據（Step 13 原樣沿用）：`temporal_relevance = recent_games`，
近期表現本身不含對手資訊，需要下一場的對手與先發投手才能形成 matchup-specific 的意義。

**evidence 自足（self-contained）：7 個**

```
VS_CLOSER、VS_DOMESTIC、VS_FOREIGN、VS_LEFT、VS_RELIEF、VS_RIGHT、VS_STARTER
```

依據：`temporal_relevance = season_cumulative`，本身就是一個完整的球季累計情境。

---

## 5. 回答：哪些 group 有 action dependency

**9 個全部都有。0 個沒有。**

也就是說，**沒有任何一個 group 的資訊可以在完全不取得額外資料的情況下連到決策。**

四種 dependency 的分佈：

| `action_link_requires` | group 數 | groups |
| --- | ---: | --- |
| `next_game_context` | 2 | RECENT_10、RECENT_15 |
| `next_starting_pitcher_hand` | 2 | VS_LEFT、VS_RIGHT |
| `in_game_pitcher_role_at_plate_appearance` | 3 | VS_STARTER、VS_RELIEF、VS_CLOSER |
| `next_starting_pitcher_registration_status` | 2 | VS_DOMESTIC、VS_FOREIGN |

---

## 6. 回答：哪些 dependency 已驗證 / 部分驗證 / 尚未調查 / 目前無法取得

| `data_availability` | group 數 | groups | requirement | 依據 Step |
| --- | ---: | --- | --- | --- |
| **`verified_available`** | **2** | RECENT_10、RECENT_15 | `next_game_context` | Step 3、Step 4、Step 14 |
| **`partially_verified`** | **2** | VS_LEFT、VS_RIGHT | `next_starting_pitcher_hand` | Step 3、Step 7A、Step 14 |
| **`currently_unavailable`** | **3** | VS_STARTER、VS_RELIEF、VS_CLOSER | `in_game_pitcher_role_at_plate_appearance` | Step 2、Step 7A、Step 8 |
| **`not_investigated`** | **2** | VS_DOMESTIC、VS_FOREIGN | `next_starting_pitcher_registration_status` | （無，從未調查） |

### 每一項的事實依據（全部指回既有 Step，沒有重新評估）

**`verified_available`（`next_game_context`）**
> Step 3 的賽程 endpoint 已驗證可取得下一場日期、時間、對手、主客、場地；
> Step 4 落地為 processed schedule；Step 14 實際用它建出 `next_game` node
> （status = `usable`）。

**`partially_verified`（`next_starting_pitcher_hand`）**
> Step 7A 在【已完成】比賽上驗證「賽程投手 Acnt → 球員頁投打習慣」5/5 通過；
> 但未開打場次的 Acnt 是否代表預告先發，Step 3 與 Step 7A 都標記為未確認，
> Step 14 因此把 `pitcher_hand` node 標為 blocked。

**`currently_unavailable`（`in_game_pitcher_role_at_plate_appearance`）**
> Step 2 已確認逐場成績 41 個欄位沒有任何投手欄位；
> Step 8 已確認官方分項沒有逐打席明細；
> 逐打席投手只存在於 `/box/getlive`，該 payload 從 Step 2 至今從未驗證過。

**`not_investigated`（`next_starting_pitcher_registration_status`）**
> 本專案從未調查官方是否提供投手的本土／外籍註冊狀態。
> Step 13 第 7.1 節已標記為未驗證。

---

## 7. 回答：哪些資訊可以直接使用、哪些需要額外資料

### 交叉表（evidence 自足 × dependency 可取得性）

| evidence 自足 | `data_availability` | groups |
| --- | --- | --- |
| **false** | `verified_available` | RECENT_10、RECENT_15 |
| true | `partially_verified` | VS_LEFT、VS_RIGHT |
| true | `not_investigated` | VS_DOMESTIC、VS_FOREIGN |
| true | `currently_unavailable` | VS_STARTER、VS_RELIEF、VS_CLOSER |

### 這張表顯示一個結構性的反向關係

**唯一 evidence 不自足的 2 個 group，它們的 dependency 是唯一已驗證可取得的。
而 7 個 evidence 自足的 group，dependency 全部不是 `verified_available`。**

換成事實陳述：

- `RECENT_10` / `RECENT_15`：evidence 本身缺對手資訊，
  但補上這個缺口所需的資料（賽程）**已驗證可取得**，Step 14 也實際串起來過。
- `VS_LEFT` / `VS_RIGHT`：evidence 本身完整，
  但要對到下一場需要知道先發投手的手別——Step 14 的 chain 就是在這裡斷掉的。
- `VS_STARTER` / `VS_RELIEF` / `VS_CLOSER`：evidence 本身完整，
  但要對到具體打席需要逐打席的投手角色，**目前拿不到**。
- `VS_DOMESTIC` / `VS_FOREIGN`：evidence 本身完整，
  但所需資料**從未調查過**，狀態不明。

**沒有任何 group 落在「evidence 自足 + dependency 已驗證」這一格。**

以上只描述結構，**不判斷哪個 group 比較好，也不做任何取捨建議**。

---

## 8. Group-level record schema

| 欄位 | 說明 |
| --- | --- |
| `group_id` / `scope` / `perspective` / `perspective_name` | 沿用 Step 18 |
| `member_candidate_ids` / `member_count` | 沿用 Step 18，順序為 candidate_id 字典序 |
| `temporal_relevance` | 維度 1，聚合自 Step 13 |
| `contextual_relevance` / `context_official_item_name` | 維度 2 |
| `next_game_dependency` | 維度 3：`evidence_depends_on_next_game` + meaning + basis + `is_not` |
| `action_link` | 維度 4：`possible_action_link` / `action_link_basis` / `possible_decision_area` + `is_not` |
| `action_link_requires` | 維度 5 |
| `application_dependency` | 與維度 3 的區分：`requires_additional_data` + `additional_data` + `distinction_note` |
| `data_availability` | 維度 6：`status` + `evidence_steps` + `factual_basis` + `vocabulary_origin` + `vocabulary_justification` |
| `member_consistency` | 聚合前的一致性檢查結果 |
| `relevance_rule` | `rule_id` `D19-1`、`rule_inputs`、`rule_not_inputs` |
| `provenance` | 各段資訊的來源 Step 與模組、source_files、sidecar 說明 |
| `contains_no` | 明確宣告不含 score / weight / threshold / ranking / priority 等 |

### 聚合規則 `D19-1`

```
rule_inputs     : ["step13_candidate_decision_descriptors", "group_membership"]
rule_not_inputs : ["magnitude", "sample_size_at_bats", "plate_appearances",
                   "percentile_rank", "consistency_count", "classification"]
```

聚合只在同 group 成員的 descriptor **完全一致**時成立。
若不一致，該欄位聚合值設為 `null` 並記錄衝突，**不強行合併**。

實測結果：**9 個 group 全部 `all_aggregated_fields_uniform = true`**，
7 個 descriptor 欄位逐一檢查都沒有衝突。

這是可預期的——Step 13 的 descriptor 由 candidate type 與 context 決定，
而 Step 18 的 group 就是依 scope（= window 或 context）切分，兩者對齊。

---

## 9. Validation

程式執行 **15 項檢查，全部通過（15 / 15）**。

| # | 對應要求 | 檢查 | 結果 |
| --- | --- | --- | --- |
| 1 | 8-1 | 9 個 group 全部都有且只有一筆 record | PASS |
| 2 | 8-2 | candidate / group membership 與 Step 18 完全一致 | PASS　成員清單、成員數、perspective 逐一相符，總數 29 |
| 3 | 8-3 | Step 13 的 29 個 descriptor 正確聚合到 group | PASS　7 欄位 × 29 = **203 次**逐一比對相符 |
| 4 | 8-4 | 同 group 的 candidate 沒有互相矛盾的 descriptor | PASS　9 個 group 全部一致 |
| 5 | 8-5 | 沒有修改 Step 18 的 grouping | PASS　深度比較 9 個 group 物件 |
| 6 | — | 沒有修改 candidate | PASS　深度比較 29 個物件 |
| 7 | 8-6 | raw / processed data 未被修改 | PASS　sha256 前後不變 |
| 8 | 8-7 / 6 | 沒有 score / weight / threshold / ranking / priority / importance / confidence score | PASS　遞迴掃描所有巢狀欄位名 |
| 9 | 8-8 | deterministic：重跑結果完全一致 | PASS |
| 10 | 8-9 | 沒有任何 HTTP request | PASS　socket guard 生效 |
| 11 | — | 沒有使用 LLM | PASS　AST import 檢查 + `sys.modules` |
| 12 | **9** | **mutation test：magnitude / AB / PA 換成極端值後結果不變** | PASS　6 次完整重跑，改變 0 次 |
| 13 | 3 | 所有欄位值都在受控詞彙內 | PASS　54 個沿用 Step 13 + 9 個新詞彙 |
| 14 | 6 | 沒有自然語言推薦或價值判斷字眼 | PASS |
| 15 | 7 | relevance 沒有依 magnitude / sample size / classification 決定 | PASS |

### 第 12 項（mutation test，設計要求 9）的實作方式

不是只改一個欄位，而是**每次變異都重跑整條流程**
（candidate → Step 11 sample → Step 13 descriptor → Step 18 grouping → Step 19 聚合），
再比對 group-level relevance 的完整簽章（含 scope、members、6 個維度、data_availability）。

| 變異 | 值 |
| --- | --- |
| magnitude | `0.0`、`999.0` |
| at_bats | `1`、`9999` |
| plate_appearances | `1`、`9999` |

```
完整重跑次數 : 6
結果改變次數 : 0
```

全部在深拷貝上操作，原始 candidate 與 group 未被觸及（第 5 / 6 項驗證）。

### 第 3 項的實作方式

逐一比對 9 個 group × 每個成員 × 7 個 descriptor 欄位，
確認 group 層級的聚合值等於每個成員在 Step 13 的原值。
另外確認 29 個 candidate 全部被覆蓋，沒有遺漏。

### hash 記錄

| 檔案 | sha256 前 8 碼 | bytes |
| --- | --- | --- |
| `data/processed/zhang_yucheng_game_logs_2026.json` | `e3712d87` | 30,547 |
| `data/raw/apart_score_0000006888_2026_A_01.json` | `8565cc8c` | 56,826 |

執行前後完全一致。沒有寫出任何檔案到 `data/`。

---

## 10. 開發過程中修正的兩個問題

### 10.1 `KeyError: 'possible_decision_area'`

Step 13 的 record 把 `possible_decision_area` 放在 `action_chain` 內，
其餘 descriptor 在頂層。第一次執行時直接用頂層存取而失敗。

修正：加一個 `step13_field()` 讀取函式處理位置差異。
**只是讀取位置的對應，沒有改動任何值。**

### 10.2 「relevance 沒有依 classification 決定」FAIL — 否定宣告被計入

檢查用 `"classification" not in blob` 掃描整份序列化字串，
但 `relevance_rule.rule_not_inputs` 這個清單裡**就寫著** `"classification"`，
用途正是宣告「classification 不是輸入」。

修正：改成**結構性檢查**——遞迴掃描所有欄位名，確認沒有任何欄位名含
`classification`；字串掃描則扣除 `rule_not_inputs` 等宣告性欄位的出現次數。
與前面幾個 Step 對 `contains_no` 的處理方式一致。

**兩者都是檢查／讀取的實作問題，沒有改動任何資料、聚合結果或詞彙。**

---

## 11. 已知限制

1. **`data_availability` 是本專案自己的調查狀態，不是官方保證。**
   `not_investigated` 只代表我們沒查過，不代表資料不存在。
2. **`partially_verified` 的粒度很粗。** VS_LEFT / VS_RIGHT 的 dependency 有兩層問題
   （Acnt 語意未確認 + 需要一個 HTTP 請求），Step 14 已記錄這兩層性質不同
   （知識問題 vs 成本問題），但 `data_availability` 只給一個值。
3. **`decision_area` 的對照仍是 Step 13 的暫定假設**，未經球隊實務驗證。
4. **9 個 group 的 relevance 結構完全由 scope 決定。**
   與 Step 18 第 9.1 節記錄的現象一致：所有 candidate 層級的差異都收斂到 scope。
   這意味著 decision relevance 也是 scope 層級的屬性。
5. **只有一名球員、一個球季。** 不同球員的 scope 組成不同，
   9 個 group 這個數字與分佈不具一般性。
6. **沒有寫出檔案。** sidecar 只在程式輸出中，與 Step 10 ~ 18 一致。
7. **`application_dependency.requires_additional_data` 目前 9 個全為 true**，
   因此這個欄位在本次資料下沒有區分力。它的 false 分支未被驗證。

---

## 12. 本階段刻意沒有做的事

- 沒有選出最佳 group、沒有做 Top-N、沒有排序
- 沒有建立 score / weight / threshold / ranking / priority / importance / confidence score
- 沒有 prediction / recommendation / 自然語言推薦
- **沒有依 magnitude、sample size、classification 決定 relevance**（6 次 mutation test 反證）
- 沒有新增 candidate 或 group
- 沒有修改 Step 18 的 grouping（深度比較驗證）
- 沒有修改 Step 13 的任何 descriptor 值（203 次逐一比對驗證）
- 沒有修改 candidate（深度比較驗證）
- 沒有修改 `data/raw/` 或 `data/processed/`（sha256 驗證）
- 沒有寫出任何新檔案到 `data/`
- 沒有擴充 Step 13 的既有詞彙（只新增一組必要的 `data_availability`，並說明理由）
- 沒有任何自由文字值
- 沒有 HTTP request（socket guard 強制保證）
- 沒有使用 LLM（AST import 檢查 + `sys.modules` 比對）
- 沒有使用 pandas，只用 Python 標準函式庫
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`

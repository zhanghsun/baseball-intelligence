# Frontend MVP（Step 24）

程式：`web/index.html`、`web/render.js`、`web/app.js`、`web/styles.css`、`web/serve.py`
測試：`tests/test_frontend.py`（58 / 58 PASS）
新增依賴：**無**（原生 HTML / CSS / Vanilla JS + Python 標準庫）

---

## 0. 這一步做什麼、不做什麼

把 Step 23 的唯讀 API 呈現成可在瀏覽器使用的單頁 MVP。

```
CPBL source → 既有 pipeline → Step 22 Product Output → Step 23 API → Frontend
```

前端的責任只有：**API 給什麼 → 正確呈現什麼。**

**不做**：重算、排序、篩選、score、ranking、threshold、priority、Top-N、
recommendation、prediction、優勢／劣勢／強弱結論、LLM、額外資料來源、
登入、部署、自動資料更新。

**不修改**：`src/api.py`、Step 5~22 的 Python pipeline、`data/raw`、
`data/processed`、任何既有 evidence / candidate / product output 邏輯。
過程中沒有需要動 backend 的地方。

---

## 1. 技術選擇

檢查現況：`package.json` / `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` /
`vite.config.*` / `tsconfig.json` / `node_modules` / `web/` / `frontend/` /
`static/` / `templates/` / `public/` **全部不存在**。`requirements.txt` 是空的。

所以沒有既有框架可沿用，依指示採用原生 HTML + CSS + Vanilla JS（ES modules），
**沒有安裝 React / Vite / Next.js，也沒有建立 `package.json`**。

| 檔案 | 角色 |
| --- | --- |
| `web/index.html` | 單頁殼層，只掛一個 `<main id="app">` 與 module script |
| `web/render.js` | **純函式呈現層**：payload → view model。沒有 DOM、沒有 fetch、沒有時鐘 |
| `web/app.js` | DOM 層：fetch → `render.js` → DOM，以及 loading / 錯誤狀態 |
| `web/styles.css` | 樣式，desktop first + 基本 mobile layout |
| `web/serve.py` | 靜態檔案伺服器（標準庫），只提供 `web/` 內的檔案 |
| `web/tests/run_render.mjs` | 測試橋接器：讓 Python 測試能執行真正的 `render.js` |

### 為什麼把呈現邏輯拆成純函式 `render.js`

因為「前端有沒有自己算、有沒有自己排序」必須可驗證。`render.js` 輸入 payload、
輸出只含字串與布林的 view model，因此可以在完全沒有瀏覽器的情況下用真實 API
payload 驅動並斷言，也能做 mutation 反證（見第 6 節）。

### 為什麼另建 `web/serve.py` 而不是讓 API 提供靜態檔

`src/api.py` 是 Step 23 的成果，本階段禁止修改。所以前端由獨立的靜態伺服器
提供，兩者透過 Step 23 **已經內建**的 `--cors-origin` 選項連接。
Step 23 的檔案一行都沒有動。

---

## 2. 啟動方式

需要兩個終端機。

```
# 終端機 1：後端 API（允許前端來源）
python src/api.py --port 8000 --warm --cors-origin http://127.0.0.1:5173

# 終端機 2：前端靜態檔案
python web/serve.py --port 5173
```

然後開 **http://127.0.0.1:5173/**

如果你習慣用 `localhost` 而不是 `127.0.0.1`，瀏覽器送出的 `Origin` 會是
`http://localhost:5173`，必須一併允許：

```
python src/api.py --cors-origin http://127.0.0.1:5173 --cors-origin http://localhost:5173
```

API 若跑在別的 port，可以用 query string 覆寫，格式經過嚴格驗證
（只接受 `^https?://host(:port)?$`）：

```
http://127.0.0.1:5173/?api=http://127.0.0.1:9000
```

---

## 3. API 怎麼連接

前端只呼叫一個端點：

```js
GET {API_BASE}/api/player/zhang-yucheng
```

`API_BASE` 預設 `http://127.0.0.1:8000`。

前端**不讀**：`data/processed/*`、`data/raw/*`、Step 9 candidate JSON、
Step 20/21/22 的 Python 輸出。測試用字串常值掃描確認 `render.js` / `app.js`
的字串常值裡沒有 `data/processed`、`data/raw`、`../data/`、
`candidate_insights`、`product_output_model` 等字樣，且唯一出現的 URL 是本機
API base、唯一出現的 API 路徑是 `/api/player/${PLAYER_SLUG}`。

---

## 4. 頁面結構

| 區塊 | 資料來源 | 內容 |
| --- | --- | --- |
| A. Player Header | `player` + `api.data_as_of` | 張育成 / 2026 一軍例行賽 / 富邦悍將 / 77 場 320 PA 273 AB；**資料截至 2026-08-18**（來自 `api.data_as_of.reference_date`）＋ 3 個來源檔 sha256 |
| B. 下一場比賽 | `next_game` | 2026-08-21 18:35 對味全龍、主場、新莊、未開打或進行中、場次 279；比分／投手姓名／左右手全部「尚無資料」＋原因；選場規則（參考日、不依賴時鐘） |
| C. 季累計基準 | `season_baseline` | AVG `.311` / OBP `.403` / SLG `.531`，每個都附完整精度、公式、來源 Step、AB 與 PA |
| D. 近期狀態 | `current_form` | RECENT_10 / RECENT_15（Perspective A） |
| E. 情境切分 | `contextual_evidence` | 7 個 VS_*（Perspective B ＋ C） |
| F. 資料狀態 | `data_status` | Evidence / Application 兩欄分開的 9 列表格、交叉值域、缺口登錄簿、無法計算的指標、下一場欄位狀態、null 表示規則 |
| G. 可追溯性 | `traceability` | 3 個來源檔 sha256 + 14 個 step registry（收在 `<details>` 內） |
| H. 中介資料 | `metadata` | counts、11 個 display slot 的版面契約、consumer contract 的「不得做的事」 |

每個 insight group 卡片包含：scope、官方分項名稱、presentation purpose、
時間性／情境標籤、interpretation status、**Evidence / Application 兩個狀態**、
metric 表（3 列：current / baseline / difference / direction / 樣本 /
單一事件敏感度 / 滾動分布位置）、跨指標方向摘要、限制區塊、決策關聯、
可追溯性（`<details>`）。

版面依 `metadata.display_contract` 的 11 個槽位安排，並在 H 區塊直接把契約
本身列出來。

### 資料截至日期

只用 `api.data_as_of.reference_date`。測試靜態檢查確認 `render.js` / `app.js`
裡沒有 `Date.now(`、`new Date(`、`Date.parse(`、`toLocaleDateString`、
`performance.now(`。

---

## 5. 缺資料怎麼呈現

只有兩種顯示文字，都不是 0、不是空白、不是 `undefined`／`NaN`：

| 情況 | 顯示 |
| --- | --- |
| 值不存在 | **尚無資料** |
| 值無法計算（API 有給原因） | **無法計算** |

兩者都用虛線框的警示樣式，並在下方直接印出 API 給的原因。

### 實際的缺口

| 位置 | 顯示 | 狀態 |
| --- | --- | --- |
| 未開打比分 | 尚無資料（**不是 0:0**） | `unavailable` |
| 對手先發投手姓名 | 尚無資料 ＋ 原因 | `partially_available`「尚未確認（部分驗證）」 |
| 先發投手左右手 | 尚無資料 ＋ 原因 ＋ 取得方式 | `unavailable`「目前無法取得」 |
| RECENT_10 / 15 的 OBP | **無法計算** ＋ 原因（該列沒有被省略，3 個 metric 都在） | `blocked_by_missing_data` |
| 7 個 VS_* 的場次數 | 尚無資料 ＋ 原因 | 官方分項沒有場次欄位 |
| 7 個 VS_* 的滾動分布位置 | 尚無資料 ＋ 原因 | 官方分項沒有時間維度 |
| 7 個 VS_* 的 game_snos | 尚無資料 ＋ 原因 | 同上 |
| `next_starting_pitcher_hand` | 尚未確認（部分驗證） | 缺口登錄簿 |
| `in_game_pitcher_role_at_plate_appearance` | 目前無法取得 | 缺口登錄簿 |
| `next_starting_pitcher_registration_status` | 尚未調查 | 缺口登錄簿 |

未開打比分在來源檔裡是 `0`，那個原值只出現在追溯欄位
（`rawValuesForTraceabilityOnly`），沒有進入任何顯示欄位。

顯示文字全部只是 API 已提供的 status / reason / missing information 的**詞彙
翻譯**，沒有新增任何事實判斷。翻譯表在 `render.js` 的
`DATA_STATUS_LABEL` / `DIRECTION_LABEL` / `INTERPRETATION_STATUS_LABEL`，
查不到的代碼一律原樣顯示，絕不編造。

---

## 6. Evidence 與 Application 兩個狀態分開

每個 group 卡片有一個三欄的 status panel：

```
Evidence（數字本身）      │  Application（能否用於下一場）
可取得（已驗證）           │  目前無法取得
                          │  需要 in_game_pitcher_role_at_plate_appearance
```

view model 裡也是兩個獨立欄位，並帶 `merged: false` 與說明文字。
F 區塊另有一張 9 列的表格，兩欄並列。

實際值域：

- `evidence_data_status`：9 個 group 全部 `available`（1 種值）
- `application_data_status`：4 種值

存在的組合包含 `(available, unavailable)`、`(available, partially_available)`、
`(available, not_investigated)` —— 前端沒有把任何一種合併成「evidence 不可靠」。

---

## 7. 數字處理

唯一的數值操作是**顯示格式化**：

- 比率用棒球慣用三位小數（`.405`）
- 有號差顯示 `+.093` / `-.105` / `±.000`
- 完整精度（8 位小數）**一律並排顯示**在旁邊，沒有任何資訊被藏起來

`current_value` / `baseline_value` / `difference` / `direction` /
`sample_size` / `sensitivity` / `rolling_percentile` 全部直接讀 payload。
`view model` 的每個 cell 都保留 `raw`（payload 原值）。

### mutation 反證

測試不只靠靜態掃描，而是改 payload 再看畫面：

| 變異 | 期望 | 結果 |
| --- | --- | --- |
| 把某個 `difference` 換成哨兵值 `0.12345678` | 畫面顯示 `+.123`，`raw` 等於哨兵值 | 通過（證明是讀，不是用 current − baseline 算） |
| 只改 `current_value` 為 `0.99999999`，不動 `difference` | `difference` **不變** | 通過（證明沒有重算） |
| `difference` 設正數但 `direction` 設 `BELOW` | 顯示「低於季累計」 | 通過（證明方向不是從正負號推的） |
| `sample_size.at_bats` 改成 4242、`delta_if_one_more` 改成 `0.87654321` | 原樣顯示 | 通過 |
| `season_baseline.batting_average` 改成 `0.5` | 原樣顯示 | 通過 |
| `insight_refs` 順序反轉 | view model 順序跟著反轉（且不等於字母序） | 通過（證明沒有 sort） |
| `factual_insights` 鍵順序反轉 | insight 列表順序跟著反轉 | 通過 |
| 某 insight 的 `statements` 順序反轉 | metric 列順序變成 SLG / OBP / AVG | 通過 |

`render.js` / `app.js` 原始碼裡沒有 `.sort(`、`.reverse(`、`localeCompare`。

---

## 8. 錯誤處理

| 狀態 | 畫面 |
| --- | --- |
| loading | spinner ＋ 正在請求的 URL |
| 200 | 完整頁面 |
| 400 | 「請求路徑不正確」＋ API 的 `code` / `message` |
| 404 | 「找不到這位球員的資料」＋ `requested` / `available` |
| 500 | 「後端產生資料時發生錯誤」＋ `code`，並顯示 API 的 `detail_note` |
| network error | 「無法連線到後端 API」＋ 啟動指令提示 |
| JSON parse 失敗 | 「收到非預期的回應」 |

錯誤畫面的所有內容都直接來自 API 的 error 物件，並在頁面上明寫
「以上訊息全部來自 API 回應，前端沒有推測錯誤原因」。唯一由前端提供的是
network error 的啟動指令提示（那是操作提示，不是錯誤原因）。

測試確認錯誤 view model 不含 `Traceback`、不含 `.py`、不含 `undefined`／`NaN`。

---

## 9. 視覺設計

深色資料分析風格，desktop first，760px 以下切換 mobile layout
（metric 表改成卡片式列，用 `data-label` 顯示欄位名；status panel 由三欄改單欄）。

沒有動畫（只有 loading spinner，且 `prefers-reduced-motion` 時停用）、
沒有 3D、沒有圖片、沒有圖表、沒有聊天機器人。

冗長的 provenance 一律收在 `<details>` 裡，預設收合，避免頁面過長：
資料版本、下一場選法、成員決定規則、決策關聯、每個 group 的可追溯性、
step registry、缺資料規則。

---

## 10. 測試

`python tests/test_frontend.py` → **Ran 58 tests，OK，0 FAIL**（約 3.8 秒）

兩層驗證：

**(1) 行為驗證（實際執行 JS）**
payload 來自真實的 Step 23 API（`api.dispatch` → `api.serialize` →
`json.loads`，模擬瀏覽器收到的東西），寫到暫存目錄後由
`node web/tests/run_render.mjs` 匯入真正的 `web/render.js` 建出 view model，
再把結果拉回 Python 斷言。**沒有 fixture 檔案**，因此不會與 API 漂移。
Node 只用內建能力，沒有任何 npm 套件。找不到 `node` 時這些測試會 skip 並印出警告。

**(2) 靜態檢查（不需要 node）**
掃描 `web/` 原始碼的**字串常值**（不掃註解，避免自我命中否定宣告）。

| 指示要求 | 對應測試 | 結果 |
| ---: | --- | --- |
| 1 API response 可正常載入 | `TestApiLoads`（2 項） | PASS |
| 2 player 正確顯示 | `TestPlayerHeader`（2 項） | PASS |
| 3 next_game 正確顯示 | `TestNextGame`（4 項） | PASS |
| 4 season_baseline 正確顯示 | `TestSeasonBaseline`（2 項） | PASS |
| 5 current_form 正確顯示 | `TestCurrentForm`（4 項） | PASS |
| 6 9 個 group 全部可呈現 | `TestContextualEvidence`（4 項） | PASS |
| 7 factual_insights 9 個全部可呈現 | `TestFactualInsights`（3 項） | PASS |
| 8 null 不顯示成 0 | `TestNullHandling`（3 項） | PASS |
| 9 兩個 data status 沒有混合 | `TestDataStatusSeparation`（4 項） | PASS |
| 10 沒有自行排序 | `TestNoFrontendSorting`（4 項） | PASS |
| 11 沒有自行計算 difference | `TestNoFrontendComputation`（5 項） | PASS |
| 12 沒有 score / ranking / threshold | `TestNoScoreRankingThreshold`（6 項） | PASS |
| 13 error state 可呈現 | `TestErrorStates`（5 項） | PASS |
| 14 不直接讀 data/ | `TestFrontendStaticInspection` | PASS |
| 15 不修改 Step 5~23 source data | `TestFrontendStaticInspection` ＋ 每個測試類的 `tearDownClass` sha256 比對 | PASS |

其他額外檢查：所有 cell 走訪（>100 個）確認缺值只會是「尚無資料」／
「無法計算」且 `raw` 為 `None`；整個 view model 沒有 `undefined`／`NaN` 字串；
方向標籤只能是「高於／低於／與季累計相同」；沒有新增 `package.json` /
`node_modules`；`requirements.txt` 仍然沒有任何依賴；靜態伺服器 root 限定在
`web/`；`web/` 底下只有 `serve.py` 一個 Python 檔且不 import 任何後端模組。

### 端到端實測（不列入自動化測試，需要 loopback 連線）

兩個伺服器都啟動後，用另一個 process 驗證：

| 檢查 | 結果 |
| --- | --- |
| `GET /`、`/index.html`、`/app.js`、`/render.js`、`/styles.css` | 全部 200；`.js` 的 Content-type 是 `text/javascript; charset=utf-8` |
| `GET /../src/api.py` | **404**（路徑穿越被阻擋） |
| `GET /../data/processed/fubon_schedule_2026.json` | **404**（路徑穿越被阻擋） |
| API 帶 `Origin: http://127.0.0.1:5173` | 200，回 `Access-Control-Allow-Origin: http://127.0.0.1:5173` ＋ `Vary: Origin` |
| API 帶 `Origin: http://evil.example` | 200 但**不回** CORS header |

再用 Node 走完整資料路徑（HTTP fetch API → `render.js`）：

```
httpStatus    200
player        張育成          season 2026      dataAsOf 2026-08-18
nextGame      2026-08-21 | 18:35 | 味全龍 | 主場 | 新莊 | 未開打或進行中 | 279
scoreDisplay  尚無資料        handDisplay 尚無資料
baseline      AVG .311 (0.31135531) | OBP .403 (0.40312500) | SLG .531 (0.53113553)
groupCount    9
scopes        RECENT_10,RECENT_15,VS_CLOSER,VS_DOMESTIC,VS_FOREIGN,VS_LEFT,VS_RELIEF,VS_RIGHT,VS_STARTER
recent10      AVG=.405 diff=+.093 高於季累計 | OBP=無法計算 diff=無法計算 尚無資料 | SLG=.619 diff=+.088 高於季累計
vsCloser      evidence=可取得（已驗證） / application=目前無法取得
metricRows    27      nullRows 2      crossMetrics 4
```

---

## 11. 三個曾經 FAIL 的項目與真正原因

第一次執行 56 項測試時 3 failures + 1 error。四個問題，四個不同根因，
全部找出真正原因後修正，**沒有放寬任何檢查**。

**(a) `rank_desc` 是數字不是字串。** 我的測試假設它是字串並做字串串接，
`TypeError`。修正方式不是改成寬鬆斷言，而是改成與 payload 逐欄位比對
`rank_desc` / `distribution_n` / `percentile_rank`，比原來更嚴格。

**(b) 掃描命中自己的否定宣告。** `app.js` 的檔頭註解寫著
「不讀 data/raw、不讀 data/processed」，全文掃描把這句話當成違規。
另一個測試也把註解裡的 `?api=http://host:port` 當成外部 URL。
根因是掃描範圍錯誤：要檢查的是程式**實際使用**的路徑，也就是字串常值。
修正方式是加一個字串常值抽取器（`string_literals`），只掃常值不掃註解。
這是 Step 19~22 已經反覆記錄過的同一類問題。

**(c) 判斷性字眼掃描抓到「門檻」8 次。** 追查後發現這**不是**前端加的：
那是 API 原文（Step 10 的 `known_limitation` 寫著「方向判定不含任何最小差距
門檻」）。但更重要的是——**payload 裡只有 4 次，view model 裡卻有 8 次**。

根因是 view model 把同 9 個 insight 存了兩份：一份在
`sections[].groups[]`、一份在 `insights[]`。這違反 Step 20~22 建立的
「數值只存在一處」原則（Step 22 第 1 節：section 只放 pointer）。

修正方式是改結構，不是改測試：`insights` 成為唯一數值來源，
`sections[].groupRefs[]` 只放 `insightId` / `scope` / `insightIndex` 指標，
`app.js` 走 ref 查表取得 group。同時新增
`test_sections_hold_references_only_no_duplicated_numbers` 專門守住這件事，
並把字眼掃描改成扣除 payload 本來就有的次數（只有正殘差才算前端新增）。

**(d) `serve.py` 的 log 訊息含 `data/`。** 同 (b) 的問題：
`print("...不讀 data/、不呼叫 CPBL。")` 這句否定宣告被自己的常值掃描抓到。
改成檢查具體目錄 `data/raw` / `data/processed` 與 `..` 路徑穿越，
語意更精確。

---

## 12. 已知限制

1. **只有一位球員、沒有球員切換。** `PLAYER_SLUG` 硬寫成 `zhang-yucheng`，
   因為 Step 22/23 只涵蓋一位球員。

2. **需要兩個 process。** 前端與 API 分開跑，且必須設對 `--cors-origin`。
   忘記設的話畫面會顯示 network error（瀏覽器 console 會顯示 CORS 錯誤）。

3. **沒有前端路由。** 單頁、只有 `#` anchor 目錄。

4. **一次載入全部（約 203 KB JSON）。** 沒有分頁、沒有 lazy load。

5. **沒有真正的瀏覽器自動化測試。** DOM 層（`app.js` 的 `renderPage` 等）
   沒有被自動化測試覆蓋，只有純函式層 `render.js` 有。DOM 層是靠上述端到端
   實測與手動開瀏覽器驗證。要自動測 DOM 需要 jsdom 或 Playwright，
   那會引入大型依賴，依指示不做。

6. **比率顯示成三位小數。** 這是格式化，完整精度一律並排顯示。但如果只掃過
   大字，看到的是四捨五入後的值。

7. **無障礙只做到基本。** 語意化標籤、`prefers-reduced-motion`、可鍵盤操作的
   `<details>`。沒有做完整的 ARIA live region、沒有跳過導覽連結、沒有用
   螢幕閱讀器實測。完整 WCAG 驗證需要輔助科技實測與專家審查。

8. **`README.md` 已與現況不符。** 它仍寫著「沒有 Web API、前端或 dashboard」。
   本階段依指示只動 frontend 相關檔案，因此**沒有修改 README**。
   建議另外處理。

---

## 13. 本階段結論

- 新增 `web/`（5 個檔案 + 1 個測試橋接器）與 `tests/test_frontend.py`、
  本文件
- 技術：原生 HTML / CSS / Vanilla JS（ES modules）＋ Python 標準庫靜態伺服器
- 新增依賴：**無**（沒有 `package.json`、沒有 `node_modules`，
  `requirements.txt` 仍為空）
- 9 個 group、29 個 candidate、27 個 metric 列（含 2 個明確 null）、
  4 個跨指標方向摘要全部呈現
- Evidence / Application 兩個狀態完整分離
- 58 / 58 測試 PASS，含 8 項 mutation 反證
- 沒有修改 Step 5~23 的任何程式；沒有修改 `data/`；來源檔 sha256 前後相同
- 沒有自行排序、沒有 score / ranking / threshold / priority / Top-N、
  沒有 recommendation / prediction、沒有 LLM

停在 Step 24。

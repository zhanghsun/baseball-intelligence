# Baseball Intelligence

> 目前狀態：**MVP 可在本機執行**。後端 API、前端頁面、手動資料更新都已完成。
> API 與前端已改為 registry 驅動，但**分析 pipeline 尚未真正支援第二位球員**。
> 尚未有自動更新，也尚未公開部署。目前 registry 只有一位球員。
>
> 要接手這個專案（尤其是 AI coding agent）請先讀
> [docs/DEVELOPMENT_HANDOFF.md](docs/DEVELOPMENT_HANDOFF.md)。

## 1. Project overview

把 CPBL 官方比賽紀錄，轉換成分析人員看得懂、且每個數字都能追溯來源的
insight，並透過一個唯讀 API 提供給網頁呈現。

核心流程（目前真正存在的架構）：

```
CPBL data
  ↓
raw / processed data
  ↓
candidate generation
  ↓
grouping / decision relevance
  ↓
presentation model
  ↓
factual insight assembly
  ↓
product output
  ↓
read-only API
  ↓
frontend
```

身分與資料路徑則是另一條線，貫穿前半段：

```
registry（src/player_registry.py）
  ↓
player identity / data paths
  ↓
input loading
  ↓
candidate generation
```

- 目標使用者：球隊的數據分析人員
- 案例球隊：富邦悍將
- **目前 registry 只有一位球員：張育成（Acnt `0000006888`）、2026 一軍例行賽**

### Multi-player progress

**API 與 frontend 已經 registry-driven，但分析 pipeline 尚未真正支援第二位球員。**

已完成：registry 是身分與路徑的唯一來源；input loading 與 candidate generation
都接受球員參數；`/api/players` 與前端選單都由 registry 驅動。

尚未完成：grouping / presentation model / factual insight assembly /
product output 這幾層仍讀模組層級的單一 subject。`validate_registry()` 目前
刻意禁止 registry 超過一位球員，等這幾層參數化完成才能解除。

細節見 [docs/DEVELOPMENT_HANDOFF.md](docs/DEVELOPMENT_HANDOFF.md)。

專案最重要的一條原則：

> Insight 必須有實際資料證據支持。事實由 Python 計算，不由模型自行產生。

## 2. Current status

### DONE

| 項目 | 說明 |
| --- | --- |
| Factual evidence pipeline | 逐場計數、季累計、滾動分布、官方分項 |
| Candidate generation | 29 個 candidate（TREND / CONTEXT / MULTI_METRIC_PATTERN） |
| Insight grouping | 依 scope 聚合成 9 個 group |
| Decision relevance | candidate 層與 group 層的決策關聯（受控詞彙） |
| Presentation model | 呈現模型，evidence / application 兩個資料狀態分離 |
| Factual insight assembly | 可閱讀但完全可追溯的 insight object |
| Product output model | machine-readable 產品輸出（頂層 9 個區塊） |
| Read-only backend API | `/api/health`、`/api/players`、`/api/player/{player_id}` |
| Frontend MVP | 單頁，原生 HTML / CSS / JS，含球員選單 |
| Manual data refresh | `src/refresh_data.py`，含原子寫入與失敗還原 |
| Registry-driven player API | 路由與前端清單都由 registry 決定，沒有寫死 player id |
| Player identity single source of truth | `src/player_registry.py` 是身分與資料路徑的唯一來源 |
| Parameterized input loading | `load_inputs(player_id=None)`、`load_schedule(player_id=None)` |
| Parameterized candidate generation | 三個 candidate builder 都接受 `subject=None` |

### CURRENT LIMITATION

- **registry 目前只有張育成一位球員**，因為只有這一位有真實資料
- **真正的多球員 pipeline 尚未完成**：API 與前端已 registry 驅動，
  但 insight / presentation / product output 層仍綁在單一 subject 上

### NOT DONE

| 項目 | 狀態 |
| --- | --- |
| multi-player candidate → insight → product-output pipeline | 尚未完成 |
| multi-player refresh | 尚未完成 |
| 自動資料更新 / scheduler | 尚未完成 |
| 公開部署 | 尚未完成 |
| Production infrastructure（認證、rate limit、監控、CI） | 尚未完成 |
| 資料庫 | 沒有，也沒有計畫在 MVP 階段加入 |
| LLM | 沒有使用 |

## 3. Repository structure

```
baseball-intelligence/
├── README.md
├── .gitignore
├── requirements.txt          Python 依賴（刻意保持為空）
├── src/                      分析 pipeline、API、資料更新入口
│   ├── api.py                    唯讀 Backend API
│   ├── refresh_data.py           手動資料更新入口
│   ├── product_output_model.py   Product Output 組裝
│   ├── insight_assembly.py       factual insight 組裝
│   ├── build_processed_data.py   raw → processed
│   └── …（evidence / candidate / grouping / presentation 等分析模組）
├── web/                      前端（原生 HTML / CSS / JavaScript）
│   ├── index.html
│   ├── render.js                 純函式呈現層（payload → view model）
│   ├── app.js                    DOM 層（fetch → render → DOM）
│   ├── styles.css
│   ├── serve.py                  靜態檔案伺服器
│   └── tests/run_render.mjs      測試橋接器（讓 Python 測試執行真正的 render.js）
├── tests/
│   ├── test_api.py
│   ├── test_frontend.py
│   └── test_refresh.py
├── data/
│   ├── raw/                  官方 response 快取（不進版控）
│   └── processed/            整理後的資料（不進版控）
└── docs/                     各階段設計與驗證文件
```

`src/` 內除了上面列出的幾支之外，還有一系列分析模組（evidence、candidate、
grouping、decision relevance、presentation model 等）。每一支都可以獨立執行
並印出自己的驗證結果，詳細說明在 `docs/` 對應的文件裡。

## 4. Local setup

**沒有任何第三方依賴。** 只需要 Python 3.11+。

- 不需要 `pip install`（`requirements.txt` 刻意保持為空）
- 不需要 `npm install`（前端沒有 `package.json`、沒有建置步驟）
- 沒有資料庫要準備

```
git clone <repo>
cd baseball-intelligence
python --version    # 3.11 以上
```

`data/` 底下的資料檔不進版控（見 `.gitignore`）。新 clone 的環境需要先執行一次
資料更新才會有資料，見第 7 節。

前端測試會用到 `node` 執行真正的 `render.js`。找不到 `node` 時那些測試會自動
skip，其餘測試照常執行。`node` 只用內建能力，不需要安裝任何 npm 套件。

## 5. Start backend

```
python src/api.py
```

預設綁 `127.0.0.1:8000`。可用選項（`python src/api.py --help`）：

| 選項 | 說明 |
| --- | --- |
| `--host HOST` | 綁定位址，預設 `127.0.0.1` |
| `--port PORT` | 綁定 port，預設 `8000` |
| `--cors-origin ORIGIN` | 允許的 CORS 來源，可重複。預設完全不送 CORS header |
| `--warm` | 啟動時先跑一次 pipeline 並快取，讓第一個請求不用等 |

端點：

```
GET http://127.0.0.1:8000/api/health
GET http://127.0.0.1:8000/api/player/zhang-yucheng
```

## 6. Start frontend

前端由獨立的靜態伺服器提供，需要**兩個終端機**。

```
# 終端機 1：後端 API（同時允許前端來源）
python src/api.py --port 8000 --warm --cors-origin http://127.0.0.1:5173

# 終端機 2：前端靜態檔案
python web/serve.py --port 5173
```

然後開 **http://127.0.0.1:5173/**

`python web/serve.py --help` 只有 `--host`（預設 `127.0.0.1`）與 `--port`
（預設 `5173`）。

### CORS：`localhost` 與 `127.0.0.1` 是不同來源

瀏覽器會用你在網址列輸入的主機名稱組出 `Origin` header，`http://localhost:5173`
與 `http://127.0.0.1:5173` 是**兩個不同的來源**。後端只放行精確命中的來源，
所以如果你習慣用 `localhost`，必須一併允許：

```
python src/api.py --cors-origin http://127.0.0.1:5173 --cors-origin http://localhost:5173
```

CORS 預設是關閉的（完全不送 `Access-Control-*` header）。`--cors-origin` 可以
傳 `*` 放行所有來源，但那只適合本機開發。

### API 位址覆寫

前端預設呼叫 `http://127.0.0.1:8000`。API 跑在別的 port 時可以用 query string
覆寫（格式會被嚴格驗證）：

```
http://127.0.0.1:5173/?api=http://127.0.0.1:9000
```

## 7. Data refresh

資料更新是**手動執行**的獨立流程，與網站請求完全分離。

```
python src/refresh_data.py               # 正式更新
python src/refresh_data.py --dry-run     # 取得最新資料並完整預檢，但不寫入
python src/refresh_data.py --no-fetch    # 零 HTTP，用現有本地資料重建並驗證
```

三個模式的差別：

| 模式 | 對 CPBL 發 HTTP | 是否寫入 `data/` | 用途 |
| --- | :---: | :---: | --- |
| 正式（無參數） | 是 | **有變動才寫** | 真正把最新資料寫進 `data/` |
| `--dry-run` | 是 | **從不寫入** | 先看會變什麼、先確認新資料能不能通過 pipeline |
| `--no-fetch` | **零** | **從不寫入**（內容不變） | 確認現有資料仍能安全重跑；也是回歸測試用的模式 |

安全機制（依序）：

1. 序列化格式反證 —— 現有檔案讀出後重寫必須逐位元相同，否則中止
2. 動手前先快照資料檔與程式檔
3. **記憶體預檢** —— 新資料先在記憶體跑完整條 pipeline 並比對 schema，
   壞資料不會被寫進正式檔案
4. 原子替換（同目錄暫存檔 + `os.replace`）
5. 任何驗證失敗或例外 → 從快照完整還原，回傳非零 exit code

新資料與現有資料完全相同時不寫入任何檔案。詳細說明見
[docs/DATA_REFRESH.md](docs/DATA_REFRESH.md)。

> `data/` 不進版控（見 `.gitignore`），所以 refresh 更新的資料檔不會被 commit。

## 8. Testing

三個測試套件，全部用 Python 標準庫 `unittest`，沒有引入 pytest 或任何測試框架：

```
python tests/test_multi_player.py
python tests/test_api.py
python tests/test_frontend.py
python tests/test_refresh.py
```

**Latest verified regression result：88 + 43 + 58 + 41 = 230 / 230 PASS。**

這是**目前 checkpoint 的驗證結果，不是永久保證**。程式或資料變動後請重新執行。

測試涵蓋的重點：

- API 回應包含 Product Output 的 9 個頂層區塊，且數值與分析 pipeline 逐欄位相同
- 缺失資料仍是 `null` + 明確原因，沒有變成 `0`
- `evidence_data_status` 與 `application_data_status` 保持分開
- 前端沒有自行排序、沒有自行計算 difference（用 mutation 反證）
- 沒有引入 score / ranking / threshold / priority / recommendation / prediction
- refresh 失敗會完整還原，不留下半更新狀態
- 重複執行 deterministic
- 來源資料檔在測試前後 sha256 相同

## 9. API

目前只有兩個唯讀端點：

| Method | Path | 說明 |
| --- | --- | --- |
| `GET` | `/api/health` | 存活檢查。不觸發分析 pipeline、不碰任何外部網路 |
| `GET` | `/api/player/zhang-yucheng` | 回傳 Product Output |

**目前沒有 `/api/players`，也沒有任何多球員 API。** `zhang-yucheng` 是唯一支援
的 player slug；其他 slug 會回 `404` 並附受控的錯誤代碼。可用的 slug 清單可以從
`/api/health` 的 `available_player_slugs` 取得。

`GET /api/player/zhang-yucheng` 的回應是 Product Output 的 9 個區塊原樣輸出，
外加一個命名空間化的 `api` 區塊：

```
player, next_game, season_baseline, current_form, contextual_evidence,
factual_insights, data_status, traceability, metadata, api
```

其他特性：

- 唯讀。沒有任何寫入端點，也沒有 `/api/refresh`
- 回應主體**不含請求時間**，因此重複請求的 bytes 完全相同
- 序列化一律排序鍵，不受 dict 插入順序影響
- 錯誤回應是機器可讀的受控錯誤代碼，不揭露 traceback 或主機檔案系統路徑
- 沒有認證、沒有 rate limit

詳細說明見 [docs/BACKEND_API.md](docs/BACKEND_API.md)。

## 10. Frontend

- **原生 HTML / CSS / JavaScript（ES modules）**
- **沒有 React、沒有 Vite、沒有 Next.js**，沒有 `package.json`、沒有建置步驟
- 單頁，desktop first，同時支援基本 mobile layout
- **前端不直接讀 `data/`**，也不知道後端怎麼算出這些數字
- 所有資料都透過 `GET /api/player/zhang-yucheng` 取得

前端只做呈現：不排序、不篩選、不重算、不建立 score / ranking / threshold，
也不產生任何建議或預測。數值的唯一來源是 API 回應中的 `factual_insights`；
版面依 `metadata.display_contract` 安排。

呈現邏輯拆成純函式模組 `web/render.js`（payload → view model，沒有 DOM、沒有
fetch、沒有時鐘），所以「前端有沒有自己算、有沒有自己排序」可以被測試驗證。

詳細說明見 [docs/FRONTEND_MVP.md](docs/FRONTEND_MVP.md)。

## 11. Data architecture

兩條路徑刻意分離：

```
資料更新路徑（只有這裡會連 CPBL）
  python src/refresh_data.py
    → CPBL 官方 endpoint
    → data/raw       官方 response 快取
    → data/processed 整理後的逐場與賽程資料
    → 分析 pipeline → Product Output

網站請求路徑（完全不連 CPBL）
  Frontend → Backend API → 本地 data/
```

| 層 | 內容 |
| --- | --- |
| `data/raw/` | CPBL 官方 response 快取（官方分項成績、逐場原始回傳） |
| `data/processed/` | 整理後的逐場打擊紀錄與富邦賽程 |
| refresh pipeline | `src/refresh_data.py`，手動執行，唯一會發外部 HTTP 的地方 |
| Backend API | `src/api.py`，只讀本地資料，process 啟動後只算一次並快取 |
| Frontend | `web/`，只透過 API 取得資料 |

**使用者打開網頁不會觸發任何 CPBL 抓取。** API 與前端的程式碼裡沒有任何
HTTP 客戶端，分析模組在 import 時還會安裝 socket guard 封鎖對外連線；
測試會實際掛 spy 驗證請求路徑上沒有 socket 連線。

CPBL 資料更新完全由 refresh pipeline 負責，且必須由人手動執行。

## 12. Data version / freshness

資料新鮮度**不是**由系統時鐘決定，而是由資料本身推導：

- `api.data_as_of.reference_date` = 已完成比賽中最晚的 `game_date`
- `api.data_as_of.source_file_digests` = 三個來源檔的 sha256 與 byte 數

前端顯示的「資料截至」就是這個 `reference_date`，不使用瀏覽器時間，也不使用
HTTP `Date` header。

實際的資料新鮮度取決於**你最後一次執行 refresh 的時間點**，以及當時 CPBL 上
已完成的比賽。要知道目前資料到哪一天，直接看 `/api/player/zhang-yucheng` 回應
中的 `api.data_as_of.reference_date`，或看頁面頂端的「資料截至」。

作為紀錄：**目前本地資料的最後驗證日期是 `2026-08-23`**（即最後一次 refresh 後
的 `reference_date`）。

這是**目前本地資料的最後驗證日期，不代表網站永遠即時**。CPBL 之後的新比賽不會
自動出現在這個 repository 裡 —— 必須有人手動執行一次 refresh。

執行中的 API process 不會自動看到新資料 —— refresh 完要重啟 `src/api.py`。

## 13. Design principles

- **Factual evidence first** —— 每個數字都能追溯到 step / 檔案 / 欄位 / 公式
- **No ranking** —— 不排序 insight、不選「最重要」、不做 Top-N
- **No score / weight / threshold** —— 不合成綜合分數、不設門檻
- **Sample size is displayed, not used as a filter** —— 樣本規模與單一事件敏感度
  都會顯示，但從不用來隱藏或淘汰任何 insight
- **Missing data is explicit** —— 缺值一律是 `null` + 明確原因，永不顯示成 `0`、
  永不靜默省略、不估算、不填補
- **`evidence_data_status` 與 `application_data_status` 分開** ——
  「這個數字本身是否可靠存在」與「能不能直接支援下一場決策」是兩件不同的事，
  不合併成單一狀態
- **Traceability preserved** —— provenance 從 CPBL 來源一路保留到前端，
  不接受「source = CPBL」這類模糊來源
- **No LLM, no generated conclusions** —— 不產生自然語言結論、不做預測、
  不做建議

更完整的設計說明見 [docs/PROJECT_DESIGN.md](docs/PROJECT_DESIGN.md)。

## 14. Current limitations

如實列出目前的限制：

- **目前只有一位真實球員**（張育成）。球員列表端點與前端切換 UI 已存在且由
  registry 驅動，但**分析 pipeline 尚未真正支援第二位球員**，因此
  `validate_registry()` 目前刻意禁止 registry 超過一位
- **只涵蓋一個球季**（2026 一軍例行賽）
- **資料更新是手動的**，沒有 scheduler、沒有 cron、沒有背景服務、
  沒有自動 refresh
- **尚未公開部署**，只能在本機執行
- **沒有認證、沒有 rate limiting**。API 預設只綁 `127.0.0.1`；
  綁到對外位址之前必須自行加上存取控制
- **後端是 prototype 等級**，用 Python 標準庫的 `http.server`，
  不適合正式流量
- **回應是單一大物件**（約 200 KB JSON），沒有分頁、沒有欄位選取、沒有壓縮
- **快取沒有失效機制**，資料更新後必須重啟 API process
- **`data/` 不進 Git**（依現有 `.gitignore`），所以 clone 後需要先跑一次
  refresh 才有資料
- **沒有 production infrastructure** —— 沒有 CI、沒有監控、沒有錯誤追蹤、
  沒有 OpenAPI / JSON Schema
- **前端的 DOM 層沒有自動化測試**，只有純函式呈現層有；DOM 需要手動開瀏覽器
  驗證
- **無障礙只做到基本**。完整 WCAG 驗證需要輔助科技實測與專家審查

## 15. Roadmap

目前合理的下一階段，依序：

1. **完成多球員化** —— registry、input loading、candidate generation 已完成；
   還要把 insight / presentation / product output 層參數化，然後才是
   multi-player pipeline 與 multi-player refresh
2. **自動資料更新** —— 在手動 refresh 已經可靠的基礎上，加上排程與失敗通知
3. **公開部署** —— 正式的 WSGI/ASGI 伺服器或反向代理、環境設定、CORS 政策
4. **Production hardening** —— 認證、rate limiting、監控、CI、schema 文件

ranking、prediction、recommendation **不在** roadmap 上。那些方向與本專案目前的
設計原則衝突，若要重新考慮必須先有明確的設計決定，目前沒有。

## 16. Documentation index

`docs/` 底下與使用者最相關的文件：

| 文件 | 內容 |
| --- | --- |
| [DEVELOPMENT_HANDOFF.md](docs/DEVELOPMENT_HANDOFF.md) | **接手用**：目前 checkpoint、已完成／未完成、殘留耦合、安全規則 |
| [PROJECT_DESIGN.md](docs/PROJECT_DESIGN.md) | 專案目標與設計原則 |
| [BACKEND_API.md](docs/BACKEND_API.md) | API 端點、回應結構、錯誤處理、CORS |
| [FRONTEND_MVP.md](docs/FRONTEND_MVP.md) | 前端結構、啟動方式、缺資料呈現規則 |
| [DATA_REFRESH.md](docs/DATA_REFRESH.md) | 手動資料更新流程與安全機制 |
| [PRODUCT_OUTPUT_MODEL.md](docs/PRODUCT_OUTPUT_MODEL.md) | Product Output 的完整結構與欄位定義 |
| [INSIGHT_ASSEMBLY_EXPERIMENT.md](docs/INSIGHT_ASSEMBLY_EXPERIMENT.md) | factual insight 如何組裝、如何避免從數字跳到結論 |
| [INSIGHT_PRESENTATION_MODEL.md](docs/INSIGHT_PRESENTATION_MODEL.md) | 呈現模型與兩個 data status 的區分 |
| [DATA_SOURCE_INVESTIGATION.md](docs/DATA_SOURCE_INVESTIGATION.md) | 逐場資料來源調查 |
| [SCHEDULE_DATA_SOURCE_INVESTIGATION.md](docs/SCHEDULE_DATA_SOURCE_INVESTIGATION.md) | 賽程資料來源調查 |
| [DATA_LAYER_VALIDATION.md](docs/DATA_LAYER_VALIDATION.md) | processed data 的驗證結果 |

`docs/` 內還有其他各階段的分析與驗證文件（evidence、candidate、grouping、
decision relevance、rolling baseline、官方分項等），檔名對應各自的主題。

# Backend / API（Step 23）

程式：`src/api.py`
測試：`tests/test_api.py`
測試結果：**43 / 43 PASS，0 FAIL**
新增依賴：**無**（只用 Python 標準庫）

---

## 0. 這一步做什麼、不做什麼

把 Step 22 已經建好的 Product Output Model 透過一個唯讀 HTTP 端點暴露出來。

```
Step 22 Product Output Model  ->  serialize  ->  API response
```

**不做**：新的分析指標、新的 evidence、ranking、score / weight / threshold /
priority / Top-N、prediction、recommendation、LLM、資料庫、認證、前端、部署、
自動更新資料。

**不重建**：AVG / OBP / SLG / difference / sample size / percentile / insight
group 全部來自 `src/product_output_model.py`。後端一個都沒有重算。
測試 `test_no_new_analytical_metric_is_added_by_the_api` 重新跑一次 Step 22 並把
9 個區塊逐位元比對，確認完全相同。

**不修改**：raw / processed data、Step 5~22 的任何程式。
測試前後記錄 3 個來源檔的 sha256，`tearDownClass` 逐一比對。

---

## 1. 為什麼用標準庫，不用 Flask / FastAPI

檢查現況：

| 項目 | 現況 |
| --- | --- |
| `requirements.txt` | 空的（只有註解），專案至今零第三方依賴 |
| `pyproject.toml` | 不存在 |
| `tests/` | 只有 `.gitkeep`，沒有 pytest |

需求規模：2 個唯讀 GET 端點、固定 JSON、沒有認證、沒有資料庫、沒有非同步、
沒有表單、沒有檔案上傳、沒有 WebSocket。

`http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler` 完全足夠，
因此**沒有新增任何依賴**。`requirements.txt` 保持不變。

測試同理用標準庫 `unittest`，沒有引入 pytest。

---

## 2. 端點

| method | path | 回應 |
| --- | --- | --- |
| `GET` | `/api/health` | 200，存活檢查 |
| `GET` | `/api/player/zhang-yucheng` | 200，Step 22 產品輸出 |
| `HEAD` | 同上 | 同上狀態碼，無主體 |

啟動：

```
python src/api.py                                   # 127.0.0.1:8000
python src/api.py --port 8123 --warm                # 啟動時先建好快取
python src/api.py --cors-origin http://localhost:5173
```

`--warm` 讓 pipeline 在啟動時跑完，第一個請求不用等。實測建立產品輸出約
**11 ms**，序列化約 **2 ms**，回應主體 **208,270 bytes**。

### 2.1 `GET /api/health`

```json
{
  "status": "ok",
  "api_version": "step23-v1",
  "endpoints": [ { "method": "GET", "path": "/api/health", ... }, ... ],
  "available_player_slugs": ["zhang-yucheng"],
  "checks": {
    "product_output_cache_warm": true,
    "local_source_files_present": {
      "zhang_yucheng_game_logs_2026.json": true,
      "apart_score_0000006888_2026_A_01.json": true,
      "fubon_schedule_2026.json": true
    },
    "network_guard_active": true
  },
  "external_network_used": false,
  "note": "health 只檢查後端自身與本地檔案是否存在，不依賴任何外部網路，也不觸發分析 pipeline。"
}
```

health **不觸發** pipeline，也**不碰網路**。它只回報快取是否已暖、本地檔案是否
存在、socket guard 是否生效。

### 2.2 `GET /api/player/zhang-yucheng`

回應主體 = **Step 22 的 9 個頂層區塊原樣** + 1 個命名空間化的 `api` 區塊：

```
player, next_game, season_baseline, current_form, contextual_evidence,
factual_insights, data_status, traceability, metadata, api
```

`api` 是**新增，不是取代**。Step 22 的 9 個鍵一個都沒有被改名、移除或重新包裝，
沒有建立第二套 schema。測試 `test_api_block_is_additive_not_a_second_schema`
斷言頂層鍵恰好是這 10 個。

`api` 區塊內容：

```json
{
  "api_version": "step23-v1",
  "endpoint": "/api/player/zhang-yucheng",
  "player_slug": "zhang-yucheng",
  "read_only": true,
  "product_output_version": "step22-v1",
  "source_of_truth": {
    "module": "src/product_output_model.py",
    "function": "build_product_output",
    "note": "API 只做序列化。所有數值由 Step 22 產生，後端沒有重算任何指標，也沒有第二套 schema。"
  },
  "data_as_of": {
    "reference_date": "2026-08-18",
    "reference_date_basis": "富邦已完成比賽（game_result == '0'）中最晚的 game_date",
    "clock_independent": true,
    "source_file_digests": [
      { "path": "apart_score_0000006888_2026_A_01.json", "sha256": "8565cc8c...", "bytes": 56826 },
      { "path": "fubon_schedule_2026.json",              "sha256": "c09a5119...", "bytes": 57227 },
      { "path": "zhang_yucheng_game_logs_2026.json",     "sha256": "e3712d87...", "bytes": 30547 }
    ],
    "is_not_request_time": "這是**資料推導出來的時間點**：已完成比賽中最晚的 game_date。它不是 API 收到請求的時間。"
  },
  "request_time_included": false,
  "request_time_note": "回應主體刻意不含請求時間，因此重複請求的 bytes 完全相同。HTTP 的 Date header 由協定層提供，不屬於資料。",
  "external_network_used": false,
  "external_network_note": "請求路徑上沒有任何對 CPBL 或其他外部服務的呼叫。資料收集（Step 2~4）與資料供應（本階段）是分開的責任。",
  "contains_no": ["score", "weight", "threshold", "ranking", "priority", ...]
}
```

---

## 3. 資料的時間 vs 請求的時間

指示明確要求區分兩者。做法：

| | 欄位 | 值 | 來源 |
| --- | --- | --- | --- |
| 資料推導的時間 | `api.data_as_of.reference_date` | `2026-08-18` | 已完成比賽中最晚的 `game_date`（Step 14 建立） |
| 資料版本 | `api.data_as_of.source_file_digests` | 3 個檔的 sha256 + byte 數 | 本地檔案 |
| 請求時間 | **不存在** | — | — |

回應主體**完全不含請求時間**，因此重複請求的 bytes 一模一樣。實測連續兩次請求
的 sha256 相同。

唯一與請求時間有關的是 HTTP 的 `Date` header——那是協定層，`BaseHTTPRequestHandler`
自動送出，不屬於資料，也不在 JSON 主體裡。

---

## 4. determinism

三個機制：

1. **序列化一律 `sort_keys=True`**（`api.serialize`），因此不受 dict 插入順序
   影響。測試把 payload 的鍵順序完全反轉後重新序列化，bytes 相同。
2. **主體不含請求時間**，不讀系統時鐘。Step 22 的參考日本身也是資料推導的
   （`clock_independent = true`）。
3. **快取只算一次**：`ProductOutputCache` 在第一個請求時跑完整條 pipeline，
   之後所有請求共用同一個物件。請求順序不影響結果——測試先打 health、
   再打不存在的球員、再打正式端點，輸出與第一次完全相同。

實測：連續 5 次請求序列化後只有 1 種 bytes。

---

## 5. 錯誤處理

錯誤代碼是**受控詞彙**（`api.ERROR_CODES`），主體結構固定：

```json
{ "error": { "code": "...", "http_status": 404, "message": "...", ...額外欄位 } }
```

| 情況 | status | code | 額外欄位 |
| --- | ---: | --- | --- |
| 不存在的球員 | 404 | `player_not_found` | `requested_player_slug`、`available_player_slugs` |
| `/api/player` 或 `/api/player/` | 400 | `player_slug_required` | `expected_path`、`available_player_slugs` |
| 路徑片段過多 | 400 | `malformed_path` | `expected_path`、`received_segment_count` |
| `/`、`/api`、`/api/unknown`、`/wat` | 404 | `not_found` | `available_endpoints` |
| POST / PUT / PATCH / DELETE | 405 | `method_not_allowed` | `allowed_methods` |
| 產生產品輸出時例外 | 500 | `product_output_generation_failed` | `player_slug`、`detail_disclosed: false` |

**不揭露內部細節**：500 的主體只有受控欄位，traceback 只寫到 stderr。
測試刻意讓 `CACHE.get` 拋出含絕對路徑的例外，然後斷言回應主體裡沒有
`Traceback`、沒有例外訊息、沒有 `C:/Users`、沒有 `.py`。

伺服器 banner 也不揭露 Python 版本：`Server: baseball-intelligence-api`
（`sys_version = ""`）。

---

## 6. CORS

**預設完全關閉**，不送任何 `Access-Control-*` header。實測預設模式下回應中沒有
`Access-Control-Allow-Origin`。

需要時用 `--cors-origin ORIGIN`（可重複）逐一列出允許來源。行為：

- 只有請求的 `Origin` 精確命中清單才回 `Access-Control-Allow-Origin: <origin>`
- 同時送 `Vary: Origin` 與 `Access-Control-Allow-Methods: GET, OPTIONS`
- `OPTIONS` 預檢回 204
- 傳 `*` 會放行所有來源。**這只適合本機開發**，正式環境不應使用，本文件在此
  明確記錄這個假設，程式的 `--help` 也寫了

---

## 7. 沒有外部請求

這是本階段的硬性要求：**使用者打開網站不會觸發 CPBL 抓取。**

四層保證：

1. **架構分離**：資料收集是 Step 2~4 的責任（`build_processed_data.py` 等），
   資料供應是本階段的責任。請求路徑上沒有任何抓取程式。
2. **socket guard**：`api.py` 的 import 鏈會經過 `candidate_insights`，
   它在 import 時安裝 guard，封鎖 `socket.socket.connect` /
   `connect_ex` / `create_connection`。health 端點回報這個狀態。
3. **沒有 HTTP 客戶端**：測試用 AST 解析 `api.py` 的 import，確認沒有匯入
   `requests` / `httpx` / `aiohttp` / `urllib3` / `http.client` / `socket`。
4. **行為測試**：測試在 `socket.socket.connect` 上掛一個 spy，然後服務兩個
   請求，斷言 spy 一次都沒被呼叫。

`ThreadingHTTPServer` 用的是 `bind` / `listen` / `accept`，不是 `connect`，
所以伺服器能正常啟動而 guard 仍然生效。測試實際 bind 一個 port 0 的伺服器
確認這件事。

---

## 8. 測試

`python tests/test_api.py` → **Ran 43 tests，OK，0 FAIL**（約 0.15 秒）。

### 為什麼測試不透過真實 socket

專案的 socket guard 刻意封鎖所有 `connect`，因此 in-process 的 HTTP 客戶端連
loopback 也會被拒。這正是「不會有外部請求」的保證，不應為了測試而拆掉。

因此路由邏輯抽成純函式 `api.dispatch(method, path) -> (status, body)`，
HTTP handler 只是薄薄一層轉接。測試直接呼叫 `dispatch`，完全不開連線。
另有測試實際 bind 伺服器確認 HTTP 層能掛起來。

**另外做了一次跨 process 的端到端實測**（不列入自動化測試，因為它需要
loopback 連線）：伺服器跑在一個 process（guard 生效），客戶端在另一個 process
用 `urllib` 打 `http://127.0.0.1:8123`。結果：

| 請求 | 結果 |
| --- | --- |
| `GET /api/health` | 200，`status = ok` |
| `GET /api/player/zhang-yucheng` | 200，208,270 bytes，10 個頂層鍵 |
| 同上再打一次 | bytes 的 sha256 相同 |
| `GET /api/player/nobody` | 404 `player_not_found` |
| `GET /api/player` | 400 `player_slug_required` |
| `GET /nope` | 404 `not_found` |
| `POST /api/player/zhang-yucheng` | 405 `method_not_allowed` |
| CORS header | 未出現（預設關閉） |
| `Server` header | `baseball-intelligence-api`（無 Python 版本） |

### 43 項測試的覆蓋

| 類別 | 測試 | 覆蓋 |
| --- | ---: | --- |
| `TestHealthEndpoint` | 4 | 200、machine-readable、不依賴外部網路、忽略 query string |
| `TestPlayerEndpoint` | 12 | 200、9 個區塊、`api` 為新增而非取代、9 個 group、29 個 candidate、與 Step 21 逐值相符、Step 19 relevance、兩個 data status 分離、缺失資訊明確、null 仍是 null、受控詞彙、factual-only 邊界、traceability |
| `TestErrorHandling` | 7 | 404 / 400 / 400 / 404 / 405 / 500、錯誤代碼受控 |
| `TestDeterminism` | 6 | 重複請求相同、dict 順序無關、請求順序無關、主體無請求時間、`data_as_of` 來自資料、metadata 宣告 |
| `TestNoExternalAccess` | 6 | guard 生效、無 HTTP 客戶端 import、spy 證明無連線、伺服器可 bind、CORS 預設關閉、banner 不揭露版本 |
| `TestSourceIntegrityAndNoNewConstructs` | 7 | 來源檔未變、未寫入任何檔案、無禁用欄位、`contains_no` 宣告、排序不是 ranking、consumer contract、與 Step 22 逐位元相同 |

**結構性斷言優先**。唯一的字眼類檢查是 `scan_forbidden_keys`，它掃**欄位名**
（不是自由文字），並排除兩類正當名稱：

- `percentile_rank` / `rank_desc`：Step 6 的分布描述子，不是 candidate 名次
- `home_score` / `visiting_score` / `*_in_file` / `score_is_null_reason`：
  CPBL 官方比分欄位，值一律為 null + 原因

以及宣告性欄位 `contains_no` / `rule_not_inputs` / `must_not_do` / `forbidden`
等（內容本身就是「不含什麼」的清單）。

### 關鍵斷言的具體數字

| 斷言 | 值 |
| --- | --- |
| 頂層鍵 | 恰好 10 個（Step 22 的 9 + `api`） |
| `factual_insights` | 9 個 |
| section group 數 | 2 + 7 = 9 |
| candidate 數 | 29，無重複 |
| metric 列 | 25 個，逐值與 Step 21 相同 |
| `evidence_data_status` 值域 | 1 種（`available`） |
| `application_data_status` 值域 | 4 種 |
| 應用層缺口 | 4 筆 required，其中 3 筆 `is_gap` |
| metric 層缺口 | 2 筆（RECENT_10 / 15 的 OBP） |
| traceability 索引 | 27 筆，25 筆可解析 |
| step registry | 14 筆 |

---

## 9. 已知限制

1. **只有一位球員。** `PLAYER_REGISTRY` 只有 `zhang-yucheng`，因為 Step 22 的
   產品輸出本身只涵蓋一位球員。要加球員需要先擴充 Step 22。

2. **沒有球員列表端點。** 沒有 `GET /api/players`。前端目前只能硬寫
   `zhang-yucheng`，或從 `/api/health` 的 `available_player_slugs` 取得。

3. **`http.server` 不適合正式流量。** 它是 MVP prototype 用的。真正上線需要
   WSGI/ASGI 伺服器或反向代理。這是刻意的取捨：目前沒有部署需求。

4. **快取沒有失效機制。** 資料檔更新後必須重啟 process。沒有 TTL、沒有
   `/api/refresh`（那會模糊「資料收集 vs 資料供應」的界線）。

5. **回應是單一大物件（約 203 KB）。** 沒有分頁、沒有 field selection、
   沒有 gzip。前端一次拿全部。

6. **沒有認證、沒有 rate limit。** 指示明確要求不加認證。預設只綁
   `127.0.0.1`。綁到 `0.0.0.0` 之前必須自行加上存取控制。

7. **回應含 repo 相對路徑。** `traceability.source_files[].path` 之類的欄位是
   `data/processed/...` 這種相對路徑。那是 Step 22 traceability 契約的一部分
   （「不接受 source = CPBL 這類模糊來源」），不是絕對路徑，也不揭露主機檔案
   系統結構。錯誤回應則完全不含任何路徑。

8. **`HEAD` 會完整計算主體才丟掉。** 為了讓 `Content-Length` 正確。以目前
   2 ms 的序列化成本可以接受。

9. **沒有 OpenAPI / JSON Schema。** 只有本文件與 `metadata.display_contract`。

---

## 10. 前端未來怎麼消費

### 10.1 取得資料

```js
const res = await fetch("http://127.0.0.1:8000/api/player/zhang-yucheng");
if (!res.ok) {
  const { error } = await res.json();   // error.code 是受控詞彙
  throw new Error(error.code);
}
const data = await res.json();
```

開發時若前端在別的 port，啟動後端時加 `--cors-origin http://localhost:5173`。

### 10.2 版面怎麼組

用 `metadata.display_contract`，它是機器可讀的版面契約，11 個槽位各自附
`source_path` 與 `availability`：

```js
for (const slot of data.metadata.display_contract) {
  // slot.slot          -> "current_form" | "contextual_splits" | ...
  // slot.source_path   -> "current_form.insight_refs"
  // slot.availability  -> "available" | "partial" | "unavailable"
  // slot.availability_note -> 為什麼是 partial
}
```

### 10.3 數值從哪裡拿

`factual_insights` 是**唯一數值來源**。section 只放參照：

```js
const section = data.contextual_evidence;
for (const ref of section.insight_refs) {
  const insight = data.factual_insights[ref.insight_id];   // ref.pointer 指的就是這裡
  for (const m of insight.supporting_evidence.primary_metrics) {
    // m.current_value / m.baseline_value / m.difference / m.direction
    // m.sample_size / m.sensitivity / m.rolling_percentile（可能是 null）
  }
}
```

`current_form` / `contextual_evidence` 裡刻意沒有任何數值，所以前端不會拿到兩份
互相可能不一致的數字。

### 10.4 必須遵守的規則

`metadata.consumer_contract.must_not_do` 是機器可讀的：

- 不得依 `difference` 大小排序或挑選
- 不得依 sample size 隱藏
- 不得把 `application_data_status != available` 當成 evidence 有問題
- 不得把 null 顯示成 0 或省略
- 不得自行生成文字結論

`safe_to_render_all` 為 true：9 個 insight 全部應該顯示。輸出裡沒有任何欄位
指示前端隱藏、排序或挑選。

### 10.5 null 怎麼顯示

每個 null 旁邊都有一個 `*_reason` / `*_null_reason` 欄位。前端應該顯示
「—」或「無資料」**並附上原因**，不要顯示 0、不要留白、不要整列消失。

```js
const rp = metric.rolling_percentile;
render(rp ? `${rp.rank_desc}/${rp.distribution_n}` : "—",
       rp ? null : metric.rolling_percentile_missing_reason);
```

### 10.6 兩個 data status 要分開顯示

```js
const da = insight.limitations.data_availability;
// da.evidence_data_status    -> 數字本身是否存在
// da.application_data_status -> 能否直接用於下一場決策
```

9 個 insight 的 `evidence_data_status` 全是 `available`，
`application_data_status` 有 4 種值。前端不可以把兩者合併成一個燈號，否則
「數字是真的，但還不能用於下一場」會被顯示成「數字有問題」。

### 10.7 資料時間顯示哪一個

用 `api.data_as_of.reference_date`（`2026-08-18`），不要用瀏覽器的
`Date.now()`，也不要用回應的 HTTP `Date` header。那兩者是「看到資料的時間」，
不是「資料本身的時間」。

---

## 11. 本階段結論

- 端點：`GET /api/health`、`GET /api/player/zhang-yucheng`
- 回應：Step 22 的 9 個區塊原樣 + 1 個命名空間化的 `api` 區塊
- 新增依賴：**無**，`requirements.txt` 未變動
- 測試：43 / 43 PASS
- 來源資料：未變動（測試前後 sha256 相同，`data/` 檔案清單相同）
- 外部請求：**零**（架構分離 + socket guard + 無 HTTP 客戶端 import + spy 驗證）
- 沒有前端、沒有部署、沒有自動更新資料、沒有資料庫、沒有認證

停在 Step 23。

# Development Handoff

這份文件是給**下一個接手這個 repository 的 AI coding agent** 看的，不是給一般
使用者看的。使用者導向的說明在 [../README.md](../README.md)。

文件裡所有數值都是在建立這份文件時，從 Git 與 runtime 實際讀取的，不是估計值。
時間往後推移，這些數值會過期 —— 請自己重新驗證，不要假設它們永遠正確。

---

## 1. Project purpose

把 CPBL 官方比賽紀錄，轉換成球隊數據分析人員看得懂、且**每個數字都能追溯回
step / 檔案 / 欄位 / 公式**的 insight，並用一個唯讀 API 提供給網頁呈現。

這個專案刻意**不做**的事情，比它做的事情更能定義它：

- 不排序、不評分、不加權、不設門檻
- 不預測、不建議
- 不讓語言模型產生事實。所有事實都由 Python 計算出來
- 不用資料庫，不用前端框架，`requirements.txt` 刻意保持為空

案例對象是富邦悍將的張育成（Acnt `0000006888`），2026 一軍例行賽。

---

## 2. Current checkpoint

| 項目 | 實際值 |
| --- | --- |
| Current branch | `main` |
| Current HEAD commit | `19543bd31d9c45aff1302bb0bf244c90e7289cb0`（短碼 `19543bd`） |
| HEAD commit message | `refactor: parameterize candidate generation` |
| origin/main status | 與 HEAD 相同 commit，`git rev-list --count HEAD ^origin/main` = 0（已同步） |
| Working tree | clean（建立本文件前） |
| Latest completed step | Step 29D（candidate generation parameterization） |
| Test count | 230 tests，230 PASS（88 + 43 + 58 + 41） |
| Data reference date | `2026-08-23` |

這是**當時 checkpoint 的驗證結果，不是永久保證**。

近期 commit 序列（新→舊）：

```
19543bd  refactor: parameterize candidate generation      (Step 29D)
4b5aabf  refactor: parameterize pipeline input loading    (Step 29C)
4d67be0  refactor: derive pipeline identity from player registry  (Step 29B)
71383b6  feat: add registry-driven multi-player API       (Step 28)
63a5bd7  docs: update README for current MVP              (Step 27)
```

Runtime 實測的產出規模（來自 `/api/player/zhang-yucheng` 的
`metadata.counts`）：

```
groups: 9   candidates: 29   insights: 9   sections: 2
metric_rows: 25   null_metric_slots: 2   cross_metric_direction_summaries: 4
```

Endpoints（實測自 `api.ENDPOINTS`）：

```
GET /api/health
GET /api/players
GET /api/player/{player_id}
```

---

## 3. Completed architecture

以下 Step 編號是這個專案已經正式使用過的編號。**不要杜撰不存在的 Step。**

| Step | 內容 |
| --- | --- |
| Step 1 → 4 | data collection / processed data。CPBL 來源調查、賽程與逐場資料落地 |
| Step 5 → 11 | candidate / evidence / statistical context。逐場計數、季累計、滾動分布、對投手左右手、官方分項 |
| Step 12 → 16 | controlled vocabulary / evidence semantics。受控詞彙、缺值語意、樣本規模作為 context |
| Step 17 → 22 | grouping / relevance / presentation / factual insight / product output |
| Step 23 → 24 | 唯讀 API / frontend MVP |
| Step 25 → 26 | safe refresh pipeline / 實際資料更新 |
| Step 27 | README |
| Step 28 | registry-driven API / frontend selector |
| Step 29B | player identity single source of truth |
| Step 29C | input loading parameterization |
| Step 29D | candidate generation parameterization |

Step 29A 是一份純唯讀的耦合稽核，沒有產生 commit。

---

## 4. Current data flow

### Refresh（唯一的資料更新路徑，必須人工執行）

```
CPBL
  → src/refresh_data.py
  → data/raw/, data/processed/
  → existing pipeline
  → product output
  → API
  → frontend
```

### Website（讀取本地資料，不對外連線）

```
frontend (web/)
  → read-only API (src/api.py)
  → local data (data/)
```

**開啟網站不會觸發任何 CPBL HTTP request。**

這不是慣例，而是有機制保證的：API 與前端程式碼裡沒有任何 HTTP 客戶端；分析模組
在 import 時會安裝 socket guard 封鎖對外連線；測試會實際掛 socket spy，驗證整個
請求路徑上的 socket 連線次數為 0。

另外兩點行為要記得：

- 執行中的 API process 有 in-memory cache，refresh 完**必須重啟** `src/api.py`
  才會看到新資料
- `data/` 不進 Git，所以 clone 之後必須先跑一次 refresh 才有資料

---

## 5. Registry architecture

`src/player_registry.py` 目前是 **player identity 與 player-specific data path 的
single source of truth**。任何需要「這位球員是誰」或「這位球員的資料在哪」的程式
碼，都應該問 registry，不要自己寫死。

目前 registry 裡只有一位球員：`zhang-yucheng`。**不要把球員數量寫死在程式或文件
裡** —— 用 `player_ids()` 去問。

實測的公開函式（`dir(player_registry)`）：

| 函式 | 用途 |
| --- | --- |
| `subject(player_id=None)` | 取得該球員的 subject dict（`player_name` / `player_acnt` / `team` / `team_code` / `season` / `kind_code` / `kind_name`） |
| `subject_slug(player_id=None)` | 取得用於 ID 組字串的 slug |
| `data_paths(player_id=None)` | 取得該球員所有資料檔的絕對 `Path` |
| `data_path(player_id, key)` | 取得單一資料檔的 `Path` |
| `data_relpaths(player_id=None)` | 取得相對路徑字串（給 provenance 用） |
| `data_identity(player_id=None)` | 取得資料檔的身分／digest 資訊 |
| `verify_data_identity(player_id=None)` | 驗證磁碟上的資料檔確實屬於這位球員 |
| `require_player(player_id)` | 取得球員，不存在就丟錯（API 路由用） |
| `get_player(player_id)` | 取得球員 record |
| `player_ids()` | 目前 registry 裡所有 player id |
| `default_player_id()` | 預設球員（legacy 呼叫端的相容退路） |
| `public_player_list()` / `public_player_view(player_id)` | 給 API 用的對外形狀 |
| `describe()` | 人類可讀的 registry 摘要 |
| `validate_registry()` | 回傳問題清單，空 list 表示通過 |

`data_paths()` 目前的 key（實測）：

```
player_log, team_schedule, apart_raw, follow_raw, candidate_output
```

### Single-subject guard

registry 與 pipeline 目前**仍有 single-subject guard**：`validate_registry()` 會
在 registry 超過一位球員時回報問題。目前它回傳空 list（通過），因為只有一位球員。

這個 guard 是**刻意的**，不是疏漏。它存在的原因是第 7 節列的那些層還沒參數化 ——
如果現在硬塞第二位球員進 registry，API 路由會通，但 insight / product output 會
默默產出第一位球員的內容並貼上第二位球員的標籤，也就是**靜默的錯誤資料**。

**在第 7 節的耦合清完之前，不要移除這個 guard。**

---

## 6. Parameterization completed

以下簽章是用 `inspect.signature` 實測的，不是從舊報告抄的。

### Step 29C —— input loading

```python
candidate_insights.load_inputs(player_id: str | None = None) -> tuple[list, list]
candidate_insights.input_paths(player_id: str | None = None) -> tuple[Path, Path]
insight_chain.load_schedule(player_id: str | None = None) -> list
insight_chain.schedule_path(player_id: str | None = None) -> Path
```

### Step 29D —— candidate generation

```python
candidate_insights.resolve_identity(subject: dict | None = None) -> dict
candidate_insights.build_trend_candidates(logs, season, subject: dict | None = None) -> tuple[list, dict]
candidate_insights.build_context_candidates(contexts, season, subject: dict | None = None) -> list
candidate_insights.build_pattern_candidates(contexts, season, subject: dict | None = None) -> tuple[list, list]
```

### Legacy calls 保留

所有新參數都是 `None` default，`None` 時回退到 `default_player_id()` 的 subject。
因此**既有的無參數呼叫全部維持原行為**，不需要修改呼叫端。

沿用這個模式繼續往下做：加 optional 參數、保留 `None` 退路、不要一次性打斷所有
呼叫端。

---

## 7. What is NOT yet parameterized

**這一節是接手工作最重要的輸入。** 以下每一行都是在建立本文件時，重新讀取目前
實際程式碼確認的，並附上當時的行號。行號會隨程式碼變動而位移 —— 請以符號與內容
為準，自己重新 grep 確認。

共同的模式有兩種耦合：

1. **identity coupling** —— 直接讀模組層級的 `SUBJECT` / `SUBJECT_SLUG`，而不是
   接受傳入的 subject
2. **path coupling** —— provenance 裡寫死 `zhang_yucheng` / `0000006888` /
   `fubon` 這些字串，而不是問 `registry.data_relpaths()`

### 這四個 builder 目前都沒有 subject 參數（實測簽章）

```python
insight_grouping.build_groups(candidates, views, samples, records_by_id) -> list
insight_assembly.build_insights(records, candidates) -> list
insight_presentation_model.build_presentation_model(groups, group_rel_records, candidates, samples) -> list
product_output_model.build_product_output(logs, apart_rows, schedule) -> dict
```

它們是這個階段真正的瓶頸。

### `src/insight_grouping.py`

- 行 165-166：`group_id` 由 `SUBJECT['player_acnt']` / `SUBJECT['season']` /
  `SUBJECT['kind_code']` 組成
- 行 694-695：`main()` 的輸出標題讀 `SUBJECT`
- `build_groups()` 沒有 subject 參數

### `src/insight_assembly.py`

- 行 46：module 層級 import `SUBJECT_SLUG`
- 行 215：寫死 `"source_file": "data/processed/zhang_yucheng_game_logs_2026.json"`
- 行 241：寫死 `"source_file": "data/raw/apart_score_0000006888_2026_A_01.json"`
- 行 475：`insight_id` 由 `SUBJECT_SLUG` 組成
- 行 1636-1637：`main()` 的輸出標題讀 `SUBJECT`
- `build_insights()` 沒有 subject 參數

### `src/insight_presentation_model.py`

- 行 415-418：subject 區塊直接讀 `SUBJECT` 的 `player_name` / `player_acnt` /
  `season` / `kind_code`
- 行 1179-1180：`main()` 的輸出標題讀 `SUBJECT`
- `build_presentation_model()` 沒有 subject 參數

### `src/product_output_model.py`

耦合最重的一支。

- 行 208-214：player section 直接讀 `SUBJECT` 的 7 個欄位
- 行 219, 244, 264, 317, 326, 336：六處寫死 source file 字串
  （`zhang_yucheng_game_logs_2026.json` / `fubon_schedule_2026.json` /
  `apart_score_0000006888_2026_A_01.json`）
- 行 543-545：寫死「檔名字串 → `Path` 常數」的對照表
- 行 1824-1825：`main()` 的輸出標題讀 `SUBJECT`
- `build_product_output()` 沒有 subject 參數

### `src/evidence_sample_context.py`

- 行 251：寫死 `"files": ["data/processed/zhang_yucheng_game_logs_2026.json"]`
- 行 300：寫死 `"files": ["data/raw/apart_score_0000006888_2026_A_01.json"]`
- 行 759-760：`main()` 的輸出標題讀 `SUBJECT`

### `src/insight_chain.py`

module 層級常數（行 70-72 的 `FUBON_TEAM_CODE` / `PLAYER_NAME` / `SEASON`）在
Step 29B 已改為從 registry 衍生，這部分沒問題。剩下的是：

- 行 212, 214, 619, 621：node 與 chain 的 metadata 直接讀 `SUBJECT`
- 行 615：`chain_id` 由 `SUBJECT['player_acnt']` 組成
- 行 226, 228, 304, 306, 310, 313, 374, 376, 380, 510, 512：十一處在 provenance
  裡寫死資料檔路徑字串
- 行 815：驗證項目的標題字串寫死 `"chain player == 張育成"`

### 這一節的驗證方式

想重新確認目前狀態，跑這個（PowerShell）：

```powershell
Select-String -Path src/insight_grouping.py,src/insight_assembly.py,src/insight_presentation_model.py,src/product_output_model.py,src/evidence_sample_context.py,src/insight_chain.py -Pattern 'SUBJECT_SLUG|SUBJECT\[|data/processed/zhang|data/raw/apart|data/processed/fubon|zhang_yucheng|0000006888'
```

---

## 8. Recommended next work

**這一節只描述方向，不要當成實作指令。** 也不要自行發明新的 Step 編號 —— 目前
文件正式定義到 Step 30 為止，後續編號由使用者決定。

依序：

1. **Parameterize insight / presentation / product-output layers**

   第 7 節那四個 builder 加上 optional subject 參數，並把寫死的 provenance 路徑
   改成問 `registry.data_relpaths()`。沿用第 6 節的模式：optional 參數 + `None`
   退路 + legacy 呼叫端不變。建議一層一層做，每層一個 commit，每次都跑完整
   regression。

2. **Multi-player pipeline**

   前一項完成後，才有可能讓 candidate → insight → product output 真正端到端跑
   第二位球員。到這一步才可以考慮解除 `validate_registry()` 的 single-subject
   guard，而且必須有真實資料驗證過。

3. **Multi-player refresh**

   最後才處理 `refresh_data.py` 的多球員化。這是風險最高的一項，因為它會寫入
   `data/`。

順序不要顛倒。先做 refresh 或先塞第二位球員，都會產出靜默的錯誤資料。

---

## 9. Safety rules / project invariants

**這些是專案的不變量，不要破壞。** 如果有任何一項看起來需要被打破，那代表方向
判斷需要先跟使用者確認，不是自己決定。

### 分析語意

- **no ranking** —— 不排序 insight、不選「最重要」、不做 Top-N
- **no priority** —— 不給 insight 排優先序
- **no score** —— 不合成綜合分數
- **no weight** —— 不加權
- **no threshold** —— 不設門檻來過濾
- **no prediction** —— 不預測未來表現
- **no recommendation** —— 不產生行動建議
- **no arbitrary natural-language conclusion** —— 語言只能來自受控詞彙，不能從
  數字自由跳到結論

### 資料語意

- **sample size is context, not a filter** —— 樣本規模要顯示，但永不用來隱藏或
  淘汰任何 insight
- **missing data must remain explicit** —— 缺值一律 `null` + 明確原因；永不顯示
  成 `0`、永不靜默省略、不估算、不填補
- **`evidence_data_status` 與 `application_data_status` 必須保持分離** ——
  這兩個是不同語意，不要合併成單一 status
- **factual traceability must remain intact** —— 每個數字都要保留 step / 檔案 /
  欄位 / 公式的追溯鏈

### 系統邊界

- **frontend does not calculate analytics** —— 前端只呈現，不算數
- **frontend does not read `data/`** —— 前端只能走 API
- **API remains read-only** —— 沒有寫入端點、沒有觸發 refresh 的端點
- **refresh is the only update path** —— 資料只能由 `refresh_data.py` 更新
- **no second player identity mapping** —— 不要在 registry 之外再建一份身分對照
- **no second cache system** —— 不要在既有 API cache 之外再加一層

---

## 10. Testing commands

這四個檔案實際存在，可以直接執行：

```
python tests/test_multi_player.py
python tests/test_api.py
python tests/test_frontend.py
python tests/test_refresh.py
```

Latest verified regression result：**88 + 43 + 58 + 41 = 230 / 230 PASS**。

這是當時 checkpoint 的結果，不是永久保證。改任何東西之後都要重新跑。

補充驗證指令（實測可獨立執行）：

```
python src/player_registry.py      印出 registry 摘要與 validate_registry() 結果
```

關於 `web/tests/run_render.mjs`：它**不是**可獨立執行的指令，而是一個需要 payload
檔案路徑作為 argv 的 bridge，由 `tests/test_frontend.py` 內部呼叫（`run_render()`
會把 payload 寫成暫存檔再傳進去）。直接 `node web/tests/run_render.mjs` 會因為缺
參數而失敗。要驗證前端呈現層，跑 `python tests/test_frontend.py`。

`tests/test_frontend.py` 會用 `shutil.which("node")` 找 node；**找不到 node 時，
需要執行 JS 的測試會被 skip**，總數就不會是 230。驗證環境實測為 node v24.18.0。

測試在 Windows PowerShell 下直接執行時，中文輸出可能 mojibake。這只影響顯示，
不影響 pass/fail 判定 —— 看 `Ran N tests` 與 `OK` / `FAILED` 那幾行即可。

**測試失敗時不要改測試讓它通過。先診斷。**

---

## 11. Data / Git rules

- `data/raw/*` 與 `data/processed/*` 目前由 `.gitignore` 排除
- **不要修改 `.gitignore`**
- **不要把目前的本地資料自動 commit**。這些是 CPBL 的原始回應與衍生檔，不屬於
  這個 repository 的版控範圍
- `data/` 底下的 `.gitkeep` 是有意保留的，用來維持目錄結構
- `requirements.txt` 刻意保持為空。不要新增 dependency
- clone 之後 `data/` 是空的，必須先跑一次 refresh

Commit 之前一定要確認 `git status`，只有預期的檔案在清單裡。

---

## 12. Known limitations

只列目前確實存在的限制：

- **one real player only** —— registry 裡只有張育成
- **multi-player pipeline incomplete** —— API / frontend 已 registry 驅動，但
  insight / presentation / product output 層仍綁單一 subject
- **single season only** —— 2026 一軍例行賽
- **manual refresh only** —— 資料更新必須人工執行
- **no automatic scheduler** —— 沒有 cron、沒有背景服務
- **prototype backend** —— 用 Python 標準庫的 `http.server`，不適合正式流量
- **no public deployment** —— 只能本機執行
- **no production infrastructure** —— 沒有 CI、沒有監控、沒有錯誤追蹤
- **no authentication / rate limiting** —— API 預設只綁 `127.0.0.1`；綁對外位址
  之前必須自行加存取控制
- **no schema version negotiation** —— 沒有 OpenAPI / JSON Schema，回應形狀的
  唯一契約是 `docs/` 裡的文件與測試
- **no production observability** —— 沒有結構化日誌、沒有 metrics、沒有 tracing
- **single large response** —— 一個球員一個大 JSON 物件，沒有分頁、沒有欄位選取、
  沒有壓縮
- **cache has no invalidation** —— refresh 完必須重啟 API process
- **frontend DOM layer has no automated tests** —— 只有純函式呈現層有；DOM 需要
  手動開瀏覽器驗證
- **accessibility is basic only** —— 完整 WCAG 驗證需要輔助科技實測與專家審查

---

## 13. Handoff principle

> The next agent should first read this document, inspect the current code, run the
> full regression suite, and only then modify the next pipeline layer.

用具體動作說明就是：

1. 讀完這份文件
2. 自己讀目前的程式碼，重新確認第 7 節的耦合清單（行號會位移）
3. 跑第 10 節的四個測試，確認起點是全綠
4. 才開始改下一層

不要跳過第 3 步。不要在沒有確認起點就全綠的狀態下開始改程式碼 —— 否則無法分辨
問題是你造成的，還是原本就存在的。

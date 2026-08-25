# Manual Data Refresh Pipeline（Step 25）

程式：`src/refresh_data.py`
測試：`tests/test_refresh.py`（41 / 41 PASS）
新增依賴：**無**（只用 Python 標準庫）

---

## 0. 這一步做什麼、不做什麼

提供一個手動執行的最小入口：重新取得 CPBL 資料 → 用**既有規則**重算 →
安全替換本地資料檔，讓 Step 22 / 23 / 24 用到最新資料。

**不做**：database、scheduler、cron、Windows Task Scheduler、GitHub Actions、
daemon、background service、polling、webhook、auto refresh、deployment、
第三方依賴。也沒有重新設計任何一層，沒有偽造比賽。

---

## 1. 位置為什麼放在 `src/`

repository 目前沒有 `scripts/`，所有可執行入口都是 `python src/<name>.py`
（`build_processed_data.py`、`context_splits.py`、`product_output_model.py`、
`api.py` …）。為一個檔案新開一個頂層目錄會破壞既有慣例，所以放
`src/refresh_data.py`。

---

## 2. 沿用的既有入口（沒有重寫任何一支）

| 層 | 既有入口 | 用途 |
| --- | --- | --- |
| Step 3 | `schedule_source_experiment.fetch_year_schedule(year, kind_code)` | 取得全聯盟賽程 raw（2 HTTP） |
| Step 2 | `data_source_experiment.fetch_follow_score(acnt, year, kind_code)` | 取得逐場打擊 raw（2 HTTP） |
| Step 8 | `context_splits.fetch_apart_rows(refetch=True)` | 取得官方分項 raw ＋ **既有 cache 機制**（2 HTTP） |
| Step 4 | `build_processed_data.build_schedule` / `build_player_logs` | raw → processed 轉換 |
| Step 22 | `product_output_model.build_product_output(logs, apart_rows, schedule)` | 建立 Product Output |
| Step 23 | `api.dispatch` | 驗證 API 仍可提供資料 |

測試用 AST 掃描確認 `refresh_data.py` 沒有自己實作 `urllib.request` /
`http.cookiejar` / `urlopen` / `RequestVerificationToken`。

---

## 3. Refresh command

```
python src/refresh_data.py               # 取得最新資料並更新（會發 6 個 HTTP 請求）
python src/refresh_data.py --dry-run     # 取得並完整預檢，但完全不寫入
python src/refresh_data.py --no-fetch    # 零 HTTP，只用現有本地資料重跑並驗證
```

三個模式的差異：

| | HTTP | 寫入 | 用途 |
| --- | :---: | :---: | --- |
| 預設 | 6 | 有變動才寫 | 真正更新資料 |
| `--dry-run` | 6 | **從不** | 先看會變什麼、先驗證新資料能不能用 |
| `--no-fetch` | **0** | **從不**（內容不變） | 確認現有資料仍能安全重跑（regression 用的模式） |

---

## 4. 實際資料流

```
更新路徑（只有這裡碰 CPBL）
  refresh_data.py
    → CPBL（Step 2 / 3 / 8 的既有 fetch）
    → 記憶體預檢（用新資料跑一次 Step 5~22，schema 比對）
    → 原子替換 data/raw + data/processed
    → 既有 pipeline → Step 22 Product Output
    → Step 23 API → Step 24 Frontend

網站路徑（完全不碰 CPBL）
  Frontend → Step 23 API → 本地 data/
```

兩條路徑分離。`src/api.py`、`web/app.js`、`web/render.js`、`web/serve.py`
都不呼叫 CPBL，測試逐檔確認它們的原始碼裡沒有 `cpbl.com.tw`、
`getfollowscore`、`getapartscore`、`getgamedatas`。

### 執行順序很重要

所有網路 I/O 一律在 import 分析 pipeline **之前** 完成。原因：
`candidate_insights` 在 import 時會安裝 socket guard 封鎖所有連線
（Step 9~24 的保護機制）。本腳本**不解除它**，只是把抓取排在前面。

測試用 AST 驗證 `candidate_insights` / `product_output_model` /
`insight_chain` / `api` **不在** module 層級 import、而是在函式內延後 import，
且抓取層只被 `fetch_all` 這一個函式 import。

---

## 5. 更新的檔案

| 檔案 | 種類 | 誰在讀 |
| --- | --- | --- |
| `data/processed/fubon_schedule_2026.json` | processed | Step 14 / 22 |
| `data/processed/zhang_yucheng_game_logs_2026.json` | processed | Step 5~22 |
| `data/raw/apart_score_0000006888_2026_A_01.json` | raw cache（Step 8 那一份） | Step 8~22 |
| `data/raw/follow_score_0000006888_2026.json` | raw dump | 無（保持與 processed 同步） |

只有這 4 個。測試斷言 refresh 的檔案清單恰好等於這 4 個，且 `data/` 底下
只有 `data/processed` 與 `data/raw` 兩個目錄。

### 沒有第二套 cache

apart splits 直接用 Step 8 的 `fetch_apart_rows(refetch=True)`，最終路徑、
格式、機制都是那一份。為了取得原子性，抓取時把 `context_splits.CACHE_PATH`
暫時指向同目錄的 `*.refresh-tmp`，rows 進到記憶體後立刻刪掉那個暫存檔，
之後由統一的 `atomic_write` 寫入正式路徑。測試斷言
`refresh_data.APART_CACHE == context_splits.CACHE_PATH`。

### 內容相同就不寫

每個檔案都先在記憶體序列化，與磁碟現有 bytes 逐位元比對。相同就完全不動
（連 mtime 都不改）。`--no-fetch` 模式下 4 個檔案全部報「不變」。

---

## 6. 安全機制

五道，依序：

**(1) 格式反證（動手前）。** 把 4 個現有檔案讀出來、用本腳本的序列化寫回，
必須逐位元相同。不同就中止，不寫入任何東西。這保證 refresh 不會因為格式差異
造成無意義變動，也保證資料檔格式不被本腳本改寫。

**(2) 快照。** 4 個資料檔 ＋ 10 個程式檔（`api.py`、`product_output_model.py`、
`insight_assembly.py`、`candidate_insights.py`、`build_processed_data.py`、
`context_splits.py`、`web/app.js`、`web/render.js`、`web/serve.py`、
`web/index.html`）複製到暫存目錄並記錄 sha256。

**(3) 記憶體預檢（動磁碟之前）。** Step 22 的
`build_product_output(logs, apart_rows, schedule)` 接受參數，所以新資料**不必
先寫入**就能跑完整條 pipeline 並比對 schema。壞資料因此根本不會被寫進正式檔案。

**(4) 原子替換。** 同目錄暫存檔 ＋ `os.replace`。中途失敗不會留下半寫入的檔案
（測試把 `os.replace` 換成拋例外，確認正式檔完好無損）。

**(5) 失敗還原。** 任何驗證失敗或例外 → 從快照完整還原，回傳 exit code 1。

---

## 7. 是否使用 HTTP

**使用，但只在更新流程。** 預設模式與 `--dry-run` 各發 6 個請求
（賽程 2、逐場 2、分項 2），全部走 Step 2 / 3 / 8 的既有 `request()`。
`--no-fetch` 模式 0 個請求 —— 測試在 `socket.socket.connect` 掛 spy，
確認 `--no-fetch` 執行期間 spy 零呼叫。

---

## 8. 實測結果

### `--no-fetch`（零 HTTP）

```
[PASS] 序列化格式與既有資料檔逐位元相同
[PASS] 新資料可以建出 Product Output 且 schema 不變（記憶體預檢）
[PASS] raw / processed data 都可以解析
       schedule 131 筆 / logs 77 筆 / apart 56 筆 / follow raw 77 筆
[PASS] Step 5~22 pipeline 可以執行且 Product Output 可以建立
       groups=9 candidates=29 insights=9 metric_rows=25
[PASS] Product Output schema 沒有改變（key_paths 2630 條、受控詞彙 16 組、display slots 11 個）
[PASS] 重建兩次結果 deterministic
[PASS] Step 23 API 可以提供更新後的 Product Output（health 200、player 200、208270 bytes）
[PASS] API schema 沒有改變，且 9 個 Step 22 區塊原樣傳遞
[PASS] 沒有修改 API / 前端 / pipeline 程式（10 個檔案逐位元相同）
[PASS] 沒有殘留暫存檔
4 個資料檔全部報「不變」，沒有寫入任何檔案。
```

### `--dry-run`（真實連線 CPBL，不寫入）

抓取路徑實測成功。三個 endpoint 都回應正常（各出現一次 HTTP 308
self-redirect，由 Step 2 既有的重試邏輯處理掉，那是官網已知行為）。

**CPBL 目前已有比 repository 更新的資料：**

| 檔案 | 現有 | 重新取得 |
| --- | ---: | ---: |
| `fubon_schedule_2026.json` | 57,227 | 57,670 bytes |
| `zhang_yucheng_game_logs_2026.json` | 30,547 | 30,941 bytes |
| `apart_score_0000006888_2026_A_01.json` | 56,826 | 56,838 bytes |
| `follow_score_0000006888_2026.json` | 85,677 | 86,787 bytes |

記憶體預檢用**新資料**跑完整條 pipeline：`groups=9`、`candidates=29`、
`insights=9`、`metric_rows=25`，**schema 與現在完全相同**。
也就是說真正執行 refresh 是安全的。

`build_schedule` 的既有異常偵測在新資料上報出
「未完成場次中出現非 0 比分：GameSno [151]」——原值保留，未做任何修正
（沿用 Step 4 的既有行為）。

`--dry-run` 結束後 4 個資料檔的 sha256 與 byte 數與執行前完全相同
（`e3712d87` / `c09a5119` / `8565cc8c` / `b2733796`），沒有殘留暫存檔。

---

## 9. 一個曾經 FAIL 的項目與真正原因

`--dry-run` 第一次執行時「沒有殘留暫存檔」FAIL，訊息是
`['apart_score_0000006888_2026_A_01.json']`。

真正原因：為了重用 Step 8 的 cache 寫入函式，抓取時把 `CACHE_PATH` 重導向到
`*.refresh-tmp`。在**有寫入**的情況下那個暫存檔會被 `atomic_write` 的
`os.replace` 消耗掉；但在 `--dry-run`（不寫入）與「內容不變」的情況下它會殘留
到 `finally` 的 `cleanup_temps()` 才被清掉——而殘留檢查跑在清理**之前**。

修正方式不是放寬檢查，而是修正生命週期：rows 一旦進到記憶體，重導向的暫存檔
就立刻在 `finally` 裡刪掉。之後 `atomic_write` 會建立自己乾淨的暫存檔。

順帶在同一輪修正加上第 6 節的機制 (3)「記憶體預檢」——原本 `--dry-run` 的
schema 檢查是拿舊資料比舊資料，等於沒驗到新資料。改成用記憶體中的新資料實際
跑一次 pipeline，`--dry-run` 才真的是 pre-flight，正常模式也變成「先驗證再寫入」。

---

## 10. Regression tests

`python tests/test_refresh.py` → **Ran 41 tests，OK，0 FAIL**（約 7 秒）

| 指示要求 | 對應測試類 | 項數 | 結果 |
| ---: | --- | ---: | --- |
| 1 refresh script 可以啟動 | `TestScriptStarts` | 4 | PASS |
| 2 不需要第三方 dependency | `TestNoThirdPartyDependency` | 5 | PASS |
| 3 現有資料可以重新建立 | `TestExistingDataRebuilds` | 4 | PASS |
| 4 / 5 Product Output 與 API schema 不變 | `TestSchemaUnchanged` | 4 | PASS |
| 6 / 7 / 8 不修改 frontend / API / Step 5~22 | `TestDoesNotTouchApiOrFrontend` | 4 | PASS |
| 9 重跑兩次 deterministic | `TestDeterminism` | 3 | PASS |
| 10 失敗不留損壞資料 | `TestFailureLeavesNoHalfUpdate` | 7 | PASS |
| 11 現有 source files 可以被保留 | `TestSourceFilesPreserved` | 3 | PASS |
| 12 不會建立第二套 cache | `TestNoSecondCache` | 4 | PASS |
| 四、HTTP 路徑隔離 | `TestNetworkPathIsIsolated` | 3 | PASS |

值得一提的幾項：

- **注入失敗** → 把 `validate_after` 換成回傳 FAIL、把
  `build_product_output_now` 換成拋例外，兩種都確認 exit code 1、輸出含
  「還原到 refresh 前的狀態」、4 個資料檔 sha256 不變。
- **`os.replace` 失敗** → 確認正式檔仍是原內容，只留下暫存檔。
- **Snapshot 行為** → 在暫存目錄驗證「被改動的檔案會被還原」與
  「原本不存在的檔案會被刪除」。
- **每個測試類的 `tearDownClass`** 都比對 14 個檔案的 sha256，任何測試修改到
  資料或程式都會立刻失敗。
- **`web/` 與 `src/*.py` 全目錄掃描** → refresh 前後逐檔 sha256 相同。

其他兩個既有套件同時回歸：
`tests/test_api.py` **43 / 43 PASS**、`tests/test_frontend.py` **58 / 58 PASS**。

---

## 11. 已知限制

1. **`--no-fetch` 模式的賽程維持現狀。** 賽程的原始 response 沒有落地檔
   （只有 processed），所以離線模式無法從 raw 重建賽程，直接沿用現有 processed
   內容。逐場打擊與分項則都有 raw dump / cache，可以真正重建。

2. **schema 檢查是保守的。** 它比對完整 key-path 集合。如果新資料造成**合法的**
   結構差異（例如新比賽讓某個 context 的三指標方向變成一致，因而多出一個
   `MULTI_METRIC_PATTERN`），檢查會判定 FAIL 並還原，而不是默默接受。
   這是刻意的：符合本專案「發現異常優先保留並記錄，不偷偷修正」的原則，
   需要人看過再決定。目前實測的新資料沒有觸發這種差異。

3. **只涵蓋一位球員、一個球季。** 常數沿用 `build_processed_data` 的
   `YEAR=2026` / `KIND_CODE='A'` / `PLAYER_ACNT='0000006888'`。

4. **沒有 rate limit 保護以外的節流。** 沿用既有 `request()` 的 1 秒禮貌間隔與
   重試。連續執行多次會重複打官網。

5. **API 執行中的 process 不會自動看到新資料。** `api.CACHE` 在 process 啟動後
   只建一次。refresh 完要重啟 `python src/api.py`。本階段刻意不加
   `/api/refresh` 端點（那會模糊「資料收集 vs 資料供應」的界線）。

6. **`data/processed/candidate_insights_zhang_yucheng_2026.json` 不在更新範圍。**
   那是 Step 9 `--write` 的既有產物，pipeline 不讀它。refresh 不動它，
   內容因此可能與最新資料不同步。

7. **`README.md` 仍與現況不符。** 前一階段已記錄，本階段同樣沒有修改。

---

## 12. 本階段結論

- 新增 `src/refresh_data.py`、`tests/test_refresh.py`、本文件
- Refresh command：`python src/refresh_data.py`（另有 `--dry-run` / `--no-fetch`）
- 新增依賴：**無**；`requirements.txt` 仍為空
- 沒有建立第二套 cache（重用 Step 8 那一份）
- 41 / 41 regression PASS；既有 43 + 58 也全部 PASS
- refresh 前後 Product Output schema 與 API schema 完全一致
- 沒有修改 Step 5~24 的任何程式（14 個檔案 sha256 前後相同）
- `data/` 未被修改（本次只跑 `--no-fetch` 與 `--dry-run`，兩者都不寫入）
- 沒有 scheduler / cron / daemon / webhook / polling / auto refresh /
  database / deployment

停在 Step 25。

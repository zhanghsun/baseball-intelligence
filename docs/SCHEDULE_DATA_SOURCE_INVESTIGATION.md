# CPBL 賽程資料來源調查（Step 3 可行性實驗）

調查日期：2026-08-20
調查性質：一次性可行性驗證，**不是**正式資料抓取系統。
驗證腳本：`src/schedule_source_experiment.py`
前置調查：`docs/DATA_SOURCE_INVESTIGATION.md`（球員逐場成績）

---

## 1. 結論摘要

**可以**取得，而且比預期的完整。

用純 Python 標準函式庫、2 個 HTTP 請求，就能拿到 CPBL 一整年的賽程 JSON，
每場 37 個欄位，包含比賽日期、預定與實際開賽時間、主客隊、場地、比賽狀態、比分、
勝敗投與 MVP。富邦悍將的下一場比賽可以直接判斷出來。

實測結果（2026 年一軍例行賽）：

- 回傳全league 388 筆場次記錄
- 其中與富邦悍將（`AEO011`）相關 131 筆
- 狀態分佈：已完成 87、未開打 31、延賽 12、保留 1
- **下一場比賽**：2026-08-21 18:35，第 279 場，味全龍(客) vs 富邦悍將(主)，@新莊

已完成 87 場這個數字，與 Step 2 逐場成績中 `TotalTeamGames = 87`（2026-08-18 該場）
完全一致，兩個來源互相驗證通過。

---

## 2. 資料來源

| 項目 | 內容 |
| --- | --- |
| 來源 | CPBL 官方全球資訊網「賽程」頁 |
| 網址 | https://www.cpbl.com.tw/schedule |
| 是否需要登入 / 付費 | 否 |
| robots.txt | 與 Step 2 相同：`www.cpbl.com.tw/robots.txt` 回應 308 自我轉址，無法取得任何規則 |

本次調查未使用 `stats.cpbl.com.tw`（其 robots.txt 明確 `Disallow: /api/`），
也沒有嘗試任何繞過存取限制的做法。

---

## 3. 官方匯出方式（優先確認的項目）

賽程頁上有官方提供的**月份賽程 PDF 下載**，網址規則來自頁面 JS 的 `getDownloadUrl`：

```
https://www.cpbl.com.tw/files/GameDets/{YYYY}/{kindCode}/CPBL{賽制中文名}_{YYYYMM}.pdf
```

實測確認可下載（檔名需 URL encode）：

```
GET /files/GameDets/2026/A/CPBL%E4%B8%80%E8%BB%8D%E4%BE%8B%E8%A1%8C%E8%B3%BD_202608.pdf
→ 200, Content-Type: application/pdf
```

**評估：這是官方正式匯出，但不適合當作我們的資料來源。**
它是給人看的 PDF，不是結構化資料；要取用得先加 PDF 解析套件，而且 PDF 版面隨時可能改，
解析出來的可靠度會低於直接拿 JSON。頁面 JS 也顯示明星賽（`kindCode == 'B'`）沒有 PDF。

沒有找到 CSV / Excel / iCal / RSS 等其他匯出形式。

---

## 4. 實際取得方式

與 Step 2 完全相同的模式：頁面骨架是 server-side HTML，賽程資料由 AJAX 取得。
**賽程資料不在 HTML 裡**，只解析 HTML 拿不到任何比賽。

### 步驟 1：GET 賽程頁取 token

```
GET https://www.cpbl.com.tw/schedule
```

目的只是取出 `/schedule/getgamedatas` 那一段 AJAX 內嵌的 anti-forgery token
（與 Step 2 相同：每個 AJAX 呼叫各自內嵌一份不同的 token，必須取對應段落）。

### 步驟 2：POST 取得賽程 JSON

```
POST https://www.cpbl.com.tw/schedule/getgamedatas
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
RequestVerificationToken: <從步驟 1 取得>

calendar=2026/01/01&location=&kindCode=A
```

必要 header 只有兩個：`RequestVerificationToken`（缺少會失敗）與 `Content-Type`。
需沿用步驟 1 的 cookie。`User-Agent` 用一般瀏覽器字串即可。

參數：

| 參數 | 說明 | 實測值 |
| --- | --- | --- |
| `calendar` | 查詢基準日，官網固定送**該年 1 月 1 日** | `2026/01/01` |
| `location` | 場地過濾，空字串 = 全部場地 | `` |
| `kindCode` | 賽制，`A` = 一軍例行賽 | `A` |

`kindCode` 選項（取自頁面，非猜測）：`A` 一軍例行賽、`B` 一軍明星賽、`C` 一軍總冠軍賽、
`E` 一軍季後挑戰賽、`G` 一軍熱身賽、`D` 二軍例行賽、`F` 二軍總冠軍賽、
`H` 未來之星邀請賽、`X` 國際交流賽。

### 重要：查詢粒度是「一整年」

`calendar` 雖然是日期，但官網送的固定是該年 1/1，而回傳是**整年所有場次**；
月曆與月份切換完全由前端 JavaScript 在本地過濾（`vue_schedule.js` 的 `getGames()`）。

也就是說，**沒有辦法只請求某一天或某一週的賽程**。一次請求就是一整年。
這不是我們主動要抓整季，而是這個 endpoint 只有這種粒度。
`src/schedule_source_experiment.py` 因此只在記憶體中處理資料，預設不寫檔。

---

## 5. Response 格式

外層與 Step 2 一致，**雙層 JSON 編碼**：

```json
{ "Success": true, "GameDatas": "<JSON 字串>" }
```

`GameDatas` 的值是字串，要再 parse 一次才會得到 array。

### 完整原始記錄（未開打場次，2026-08-21）

```json
{
  "Year": "2026",
  "KindCode": "A",
  "GameSno": 279,
  "GameSeasonCode": "2",
  "GameDate": "2026-08-21T00:00:00",
  "PreExeDate": "2026-08-21T18:35:00",
  "GameDateTimeS": "2026-08-21T18:35:00",
  "GameDateTimeE": null,
  "GameDuringTime": "",
  "GameResult": "",
  "PresentStatus": 1,
  "ReserveDate": null,
  "MultyGame": "N",
  "IsPlayBall": "N",
  "IsGameStop": "0",
  "FieldAbbe": "新莊",
  "HomeTeamCode": "AEO011",
  "HomeTeamName": "富邦悍將",
  "HomeScore": 0,
  "HomePitcherAcnt": "0000007804",
  "HomePitcherName": "",
  "VisitingTeamCode": "AAA011",
  "VisitingTeamName": "味全龍",
  "VisitingScore": 0,
  "VisitingPitcherAcnt": "0000006497",
  "VisitingPitcherName": "",
  "WinningPitcherAcnt": "", "WinningPitcherName": "",
  "LoserPitcherAcnt": "", "LoserPitcherName": "",
  "CloserAcnt": "", "CloserName": "",
  "MvpAcnt": "", "MvpName": "", "MvpCount": null
}
```

### 完整原始記錄（已完成場次，2026-08-18）

```json
{
  "Year": "2026",
  "KindCode": "A",
  "GameSno": 272,
  "GameSeasonCode": "2",
  "GameDate": "2026-08-18T00:00:00",
  "PreExeDate": "2026-08-18T18:35:00",
  "GameDateTimeS": "2026-08-18T18:36:00",
  "GameDateTimeE": "2026-08-18T21:53:00",
  "GameDuringTime": "031700",
  "GameResult": "0",
  "PresentStatus": 1,
  "ReserveDate": null,
  "MultyGame": "N",
  "IsPlayBall": "N",
  "IsGameStop": "0",
  "FieldAbbe": "樂天桃園",
  "HomeTeamCode": "AJL011", "HomeTeamName": "樂天桃猿", "HomeScore": 0,
  "HomePitcherAcnt": "0000004624", "HomePitcherName": "陳克羿",
  "VisitingTeamCode": "AEO011", "VisitingTeamName": "富邦悍將", "VisitingScore": 5,
  "VisitingPitcherAcnt": "0000007782", "VisitingPitcherName": "威戈神",
  "WinningPitcherAcnt": "0000007782", "WinningPitcherName": "威戈神",
  "LoserPitcherAcnt": "0000004624", "LoserPitcherName": "陳克羿",
  "CloserAcnt": "", "CloserName": "",
  "MvpAcnt": "0000007782", "MvpName": "威戈神", "MvpCount": 1
}
```

（兩筆均省略 `HomeClubSmallImgPath` / `VisitingClubSmallImgPath` 兩個圖片路徑欄位。）

---

## 6. 可以取得哪些欄位

對照使用者列出的 9 個需求：

| 需求 | 是否取得 | 對應欄位 |
| --- | --- | --- |
| 1. 比賽日期 | 是 | `GameDate`（純日期，時間固定 00:00:00） |
| 2. 比賽時間 | **是，官方有提供** | `PreExeDate` 預定開賽時間；`GameDateTimeS` / `GameDateTimeE` 實際開始／結束 |
| 3. 主隊 | 是 | `HomeTeamCode` / `HomeTeamName` |
| 4. 客隊 | 是 | `VisitingTeamCode` / `VisitingTeamName` |
| 5. 對手 | 是（推導） | 用 `AEO011` 比對主客隊代碼，另一邊就是對手 |
| 6. 比賽場地 | 是 | `FieldAbbe` 場地簡稱，如「新莊」「樂天桃園」「亞太主」 |
| 7. 比賽狀態 | 是 | `GameResult`（見下方對照） |
| 8. 已結束的比分 | 是 | `HomeScore` / `VisitingScore` |
| 9. 判斷下一場 | 是 | 見第 7 節 |

### `GameResult` 狀態對照

代碼含義取自賽程頁 Vue 模板的判斷式（`v-if="game.GameResult == '1'"` → 顯示「延賽」等），
不是推測：

| 值 | 含義 |
| --- | --- |
| `""` | 尚未有結果（未開打或進行中） |
| `"0"` | 已完成 |
| `"1"` | 延賽 |
| `"2"` | 保留 |
| `"4"` | 取消 |

### 額外拿到的欄位（超出原本需求）

- **勝投 / 敗投 / 救援成功 / 單場 MVP**：`WinningPitcher*`、`LoserPitcher*`、`Closer*`、`Mvp*`、`MvpCount`
- **雙方先發投手**：`HomePitcher*` / `VisitingPitcher*`（Step 2 的逐場成績表沒有這個）
- **比賽耗時**：`GameDuringTime`，格式為 `HHMMSS` 字串，`"031700"` = 3 小時 17 分
- **雙重賽標記**：`MultyGame`，`"N"` 為否
- `GameSeasonCode`：實測值 `"2"`

### 這解決了 Step 2 的兩個缺口

Step 2 的逐場成績表沒有主客場、沒有球隊勝負比分、沒有開賽時間、沒有對手先發投手。
賽程資料全部補上了，而且兩邊可以用 **`(Year, KindCode, GameSno)`** 對接：

實例驗證：張育成逐場成績中 `GameSno = 272` / `GameDate = 2026-08-18` / 對手樂天桃猿，
與賽程中 `GameSno = 272` 的那場完全對應（富邦客場 @樂天桃園，5:0）。

---

## 7. 如何判斷富邦悍將的下一場比賽

實測可行的判斷方式：

1. 用 `kindCode='A'`、`calendar='<今年>/01/01'` 取得整年賽程
2. 篩出 `HomeTeamCode == 'AEO011' or VisitingTeamCode == 'AEO011'`
3. 再篩出 `GameResult == ''`（尚未有結果）且 `PreExeDate > 現在時間`
4. 依 `PreExeDate` 升冪排序，第一筆就是下一場
5. 對手 = 主客隊中不是 `AEO011` 的那一邊；主客身分由 `HomeTeamCode == 'AEO011'` 判斷

實測輸出（執行時間 2026-08-20 21:30）：

```
下一場：2026-08-21 18:35  第279場  味全龍(客) vs 富邦悍將(主)  @新莊
→ 對手：味全龍，本隊為主隊
之後兩場：08-22 17:05 味全龍@新莊、08-23 17:05 味全龍@新莊
```

**需要注意的邊界情況**（已知但未逐一驗證）：

- 比賽進行中時 `GameResult` 也是 `""`，只靠 `GameResult` 無法區分「未開打」與「進行中」。
  官網用 `PreExeDate` + `IsPlayBall` + `GameDateTimeE` 組合判斷（見 `vue_schedule.js` 的
  `isPlaying()`）。上面的步驟 3 用 `PreExeDate > now` 已可避開進行中的場次。
- 只查 `kindCode='A'` 會漏掉季後賽與總冠軍賽。球季後段要一併查 `C` / `E`。
- 跨年時（12 月底查隔年）要注意 `calendar` 的年份。

---

## 8. 是否可以取得過去比賽結果

可以。`GameResult == '0'` 的場次帶有完整結果：比分、勝敗投、救援成功、單場 MVP、
實際開始與結束時間、比賽耗時。

實測最近三場富邦悍將已完成比賽：

```
2026-08-15 16:05  第265場  富邦悍將(客) vs 統一7-ELEVEn獅(主) @亞太主   1:12  勝投=林詔恩
2026-08-16 16:05  第269場  富邦悍將(客) vs 統一7-ELEVEn獅(主) @亞太主   8:2   勝投=江國豪
2026-08-18 18:35  第272場  富邦悍將(客) vs 樂天桃猿(主)      @樂天桃園  5:0   勝投=威戈神
```

歷史深度：頁面月曆的上一頁按鈕限制在 `new Date(1990, 0, 1)` 之後，
暗示可查到 1990 年，但**本次只實測 2026 年一年**，更早年份是否真的有資料未驗證。

---

## 9. 資料品質觀察（重要）

富邦悍將 131 筆記錄的狀態分佈：

| 狀態 | 筆數 |
| --- | --- |
| 已完成 | 87 |
| 未開打 | 31 |
| 延賽 | 12 |
| 保留 | 1 |
| 合計 | 131 |

**`GameSno` 在同一隊內有 11 筆重複。** 一場例行賽正常是 120 場，131 筆明顯偏多。
合理的解讀是：延賽的比賽會保留一筆「延賽」記錄，改期後再新增一筆同 `GameSno` 的記錄。

→ **`GameSno` 不能單獨當唯一鍵**，做任何聚合前必須先處理延賽／保留造成的重複，
否則場次數會算錯。這一點只有觀察，尚未逐筆確認重複的成因。

另一個佐證：已完成 87 場與 Step 2 逐場成績的 `TotalTeamGames = 87` 一致，
說明「已完成」的篩選條件是對的。

---

## 10. 目前仍未知的部分

| 項目 | 狀況 |
| --- | --- |
| **預告先發投手的姓名** | 未開打場次的 `HomePitcherAcnt` / `VisitingPitcherAcnt` **有值**（8/21 該場為 `0000007804` 與 `0000006497`），但 `*PitcherName` 是空字串。官網模板因為判斷 Name 非空才顯示，所以網頁上看不到。要拿到姓名得用 Acnt 對照球隊名單（Step 2 已能取得 Acnt→姓名對照）。**只有 1 筆樣本，尚未確認這個 Acnt 一定代表預告先發。** |
| `GameSeasonCode` | 實測值 `"2"`。語意未確認（可能是上／下半季，但沒有證據） |
| `PresentStatus` | 實測值 `1`。官網用它決定 box 網址是否加 `presentStatus=0`，語意未確認 |
| `IsPlayBall` | 已完成的場次也是 `"N"`，不是可靠的「已開打」旗標，實際語意未確認 |
| `ReserveDate` | 兩筆樣本都是 `null`，推測與保留賽有關，未驗證 |
| `MvpCount` | 已完成場次為 `1`，未開打為 `null`。模板顯示為「本季已得 MVP 次數」 |
| 延賽重複記錄的規則 | 只知道有 11 筆重複，沒有確認判別與去重規則 |
| 場地全名與代碼 | 只有簡稱 `FieldAbbe`（「亞太主」這種縮寫），沒有場地代碼或全名。與 Step 2 逐場成績的 `FieldNo`（`F08` 等）如何對應**未確認** |
| 1990~2023 年是否有資料 | 未實測 |
| 二軍（`kindCode='D'`）欄位是否相同 | 未實測 |
| `/schedule/getoptsaction` | 只知道用來取場地下拉選單，本次未呼叫 |

---

## 11. 可能的限制

1. **官網 CDN 偶發 308 自我轉址**（與 Step 2 相同）
   本次三次執行中，`GET /schedule` 兩次、`POST /schedule/getgamedatas` 一次遇到 308，
   `Location` 指向完全相同的網址。重試即成功。
   → 任何取用程式都必須有重試機制。

2. **非公開 API，隨時可能改變**
   endpoint、參數、欄位名、token 位置都是從頁面 JS 觀察得來，官方沒有承諾穩定性。

3. **一次請求即整年資料**
   無法縮小查詢範圍。若要每日更新「下一場對手」，每次都會拉回整年 388 筆。
   → 應該做本地快取，不要為了拿一場比賽而反覆請求。

4. **需要兩次請求才能拿一次資料**
   每次都要「GET 頁面拿 token → POST endpoint」。

5. **雙層 JSON 編碼**，忘記第二次 parse 會拿到字串。

6. **`GameSno` 有重複**，見第 9 節。

7. **沒有明確的資料授權說明**
   資料公開可瀏覽，但官網未提供 API 條款。目前僅小量探索性使用；
   若要常態化取用或對外呈現，應先確認授權範圍。

8. **時區**
   所有時間都是不帶時區的字串，推定為台灣時間，但回應中沒有任何時區標記。

---

## 12. 對 MVP 的適用性

對照 `PROJECT_DESIGN.md` 的三個 MVP 方向，加上 Step 2 的逐場成績，覆蓋狀況更新如下：

| MVP 方向 | 現在的狀況 |
| --- | --- |
| 球隊目前近況 | **可以做了**。賽程提供每場勝負與比分，逐場成績提供球員層級表現，兩者用 `GameSno` 對接 |
| 特別需要注意的球員 | **可以做**（Step 2 已確認），現在還能加上主客場與對手先發投手作為情境 |
| 下一場對手 | **可以做了**。日期、時間、主客、場地、對手都有 |

對 Insight 三要素的意義：

- **數據佐證**：所有欄位都是官網原始值，沒有推估。
- **與下一場比賽的關聯**：這是本次最關鍵的補強。有了下一場的對手、主客場與場地，
  才能把球員近況連結到「下一場會發生什麼」。
- **決策支援**：預告先發投手（目前只有 Acnt）若能確認，會是很強的決策輸入。

與已定原則的對照：

- 「MVP 以 Game / Plate Appearance 層級為主要粒度」→ 相符，這是 Game 層級資料。
- 「不假設可以取得逐球資料」→ 相符，本次沒有碰任何逐球來源。
- 「事實由程式計算」→ 相符，腳本只做篩選與排序，沒有任何補值或推估。

---

## 13. 本次請求量

對 `www.cpbl.com.tw` 的請求總量在 10 次量級以內（含重試、賽程頁 JS、PDF 檢查）。
未做任何批次或迴圈抓取。`src/schedule_source_experiment.py` 每執行一次只發出 2 個請求。

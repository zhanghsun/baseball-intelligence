# CPBL 資料來源調查（Step 2 可行性實驗）

調查日期：2026-08-20
調查性質：一次性可行性驗證，**不是**正式資料抓取系統。
驗證腳本：`src/data_source_experiment.py`

---

## 1. 結論摘要

**可以**用純 Python 標準函式庫，從 CPBL 官網取得富邦悍將單一球員的**逐場（game-by-game）打擊成績**，
資料為官方公開頁面內容，不需登入、不需付費、不需 API key。

實測案例：富邦悍將 張育成，2026 年一軍例行賽，取得 **77 場**逐場記錄，
每場 **41 個欄位**，日期範圍 2026-03-29 ~ 2026-08-18。

---

## 2. 資料來源

| 項目 | 內容 |
| --- | --- |
| 來源 | CPBL 官方全球資訊網 |
| 網址 | https://www.cpbl.com.tw/ |
| 目標頁面 | 球員「逐場成績表」`/team/follow?Acnt=<球員代碼>` |
| 是否需要登入 | 否 |
| 是否需要付費 | 否 |
| robots.txt | `https://www.cpbl.com.tw/robots.txt` 回應 308 自我轉址（無法取得內容），因此**沒有**取得到任何 robots 規則 |

另一個候選來源（本次**未**取用，原因見第 8 節）：

| 項目 | 內容 |
| --- | --- |
| 來源 | CPBL 官方進階數據平台 |
| 網址 | https://stats.cpbl.com.tw/ |
| 技術 | Next.js App Router（頁面 HTML 內以 `self.__next_f` 內嵌 RSC payload，無 `__NEXT_DATA__`） |
| robots.txt | 明確 `Disallow: /api/` 與 `Disallow: /_next/` |

---

## 3. 實際取得方式

官網為 ASP.NET MVC + Vue 混合架構：頁面骨架是伺服器端輸出的 HTML，
**表格資料則由頁面載入後的 AJAX 請求取得**，所以不能只靠解析 HTML 表格。

取得逐場成績需要兩個步驟：

### 步驟 1：GET 逐場成績表頁面

```
GET https://www.cpbl.com.tw/team/follow?Acnt=0000006888
```

這一步的作用不是拿資料，而是拿三樣東西：

1. 該球員的預設查詢參數（`acnt` / `defendStation` / `kindCode` / `year`），內嵌在頁面的 Vue `data` 區塊
2. 可選年度清單 `yearOpts`、賽制清單 `kindCodeOpts`
3. 呼叫內部 endpoint 所需的 **anti-forgery token**

頁面中的相關片段（實際觀察到的內容）：

```js
acnt: '0000006888',
defendStation: '游擊手',
kindCode: 'A',
year: '2026',
options: {
  kindCodeOpts: [{"Text":"一軍例行賽","Value":"A"}, ...],
  yearOpts: [{"Text":"2026","Value":"2026"}, ...]
}
```

### 步驟 2：POST 內部 endpoint 取得 JSON

```
POST https://www.cpbl.com.tw/team/getfollowscore
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
RequestVerificationToken: <從步驟 1 頁面取得>

acnt=0000006888&defendStation=游擊手&year=2026&kindCode=A
```

**注意：** token 是「每個 AJAX 呼叫各自內嵌一份」，`/team/getfollowscore` 與
`/team/getbattingscore` 的 token 值不同，必須取對應那一段的。同時要沿用步驟 1 的 cookie。

---

## 4. 是否存在 API

**存在，但不是公開文件化的 API**，而是網站自己前端在用的內部 endpoint。
沒有找到任何官方 API 文件、版本號或使用條款說明。

在球員相關頁面上觀察到的 endpoint（全部為 POST，全部需要 `RequestVerificationToken`）：

| Endpoint | 用途 | 參數 |
| --- | --- | --- |
| `/team/getfollowscore` | **逐場成績（本次採用）** | `acnt`, `defendStation`, `year`, `kindCode` |
| `/team/getfollowoptsaction` | 逐場成績的年度選項 | 同上 |
| `/team/getbattingscore` | 逐年打擊成績 | `acnt`, `kindCode` |
| `/team/getbattingcareerscore` | 生涯打擊成績 | `acnt`, `kindCode` |
| `/team/getpitchscore` | 逐年投球成績 | `acnt`, `kindCode` |
| `/team/getpitchcareerscore` | 生涯投球成績 | `acnt`, `kindCode` |
| `/team/getdefencescore` | 守備成績 | `acnt`, `kindCode` |
| `/team/getfighterscore` | 投打對決成績 | `acnt`, `year`, `defendStation` |
| `/box/getlive` | 單場文字轉播（逐打席／逐球） | 由表單序列化，**本次未呼叫** |
| `/home/getdetaillist` | 首頁當日賽事列表 | 由表單序列化，**本次未呼叫** |

賽制代碼 `kindCode`（取自頁面選單，非猜測）：

`A` 一軍例行賽、`B` 一軍明星賽、`C` 一軍總冠軍賽、`E` 一軍季後挑戰賽、`G` 一軍熱身賽、
`D` 二軍例行賽、`F` 二軍總冠軍賽、`H` 未來之星邀請賽、`X` 國際交流賽

---

## 5. Request / Response 基本結構

### Response 外層

```json
{ "Success": true, "FollowScore": "<JSON 字串>" }
```

**回傳是雙層編碼**：`FollowScore` 的值是一個「字串」，內容才是 JSON array，需要再 parse 一次。

### Response 內層（單場記錄實例，未加工）

```json
{
  "FightTeamAbbrName": "樂天桃猿",
  "SId": { "Value": "0Q230799136142838994" },
  "Year": "2026",
  "KindCode": "A",
  "GameSno": 272,
  "GameDate": "2026-08-18T00:00:00",
  "HitterAcnt": "0000006888",
  "HitterName": "張育成",
  "FieldNo": "F23",
  "FightTeamCode": "AJL011",
  "TeamNo": "AEO011",
  "TotalTeamGames": 87,
  "PlateAppearances": 5,
  "HitCnt": 3,
  "RunBattedINCnt": 1,
  "ScoreCnt": 0,
  "HittingCnt": 1,
  "OneBaseHitCnt": 1,
  "TwoBaseHitCnt": 0,
  "ThreeBaseHitCnt": 0,
  "HomeRunCnt": 0,
  "TotalBases": 1,
  "StrikeOutCnt": 1,
  "StealBaseOKCnt": 0,
  "StealBaseFailCnt": 0,
  "Avg": 0.311,
  "SacrificeHitCnt": 0,
  "SacrificeFlyCnt": 0,
  "BasesONBallsCnt": 2,
  "IntentionalBasesONBallsCnt": 0,
  "HitBYPitchCnt": 0,
  "DoublePlayBatCnt": 1,
  "TripplePlayBatCnt": 0,
  "Lobs": 3,
  "PutoutCnt": 0,
  "AssistCnt": 0,
  "JoinDoublePlayCnt": 0,
  "JoinTripplePlayCnt": 0,
  "ErrorCnt": 0,
  "CaughtStealingCnt": 0,
  "PassedBallCnt": 0
}
```

排序：**日期由新到舊**（index 0 是最近一場）。

---

## 6. 可以取得哪些欄位

野手逐場成績表共 41 欄。以下欄位名稱與中文對照，是從官網表格 `<th>` 與 Vue 綁定逐一對應出來的，
不是推測：

### 比賽識別

| 欄位 | 說明 | 備註 |
| --- | --- | --- |
| `GameDate` | 比賽日期 | ISO 字串，時間固定為 `T00:00:00`（無實際開賽時間） |
| `GameSno` | 場次編號 | 該年度該賽制的流水號 |
| `Year` / `KindCode` | 年度 / 賽制 | |
| `SId` | 記錄唯一鍵 | 巢狀物件 `{"Value": "..."}` |
| `FightTeamAbbrName` / `FightTeamCode` | 對手隊名 / 對手代碼 | 例：`AJL011` = 樂天桃猿 |
| `TeamNo` | 球員所屬球隊代碼 | 富邦悍將 = `AEO011` |
| `FieldNo` | 球場代碼 | 例：`F08`、`F23`。**代碼對照表未知** |
| `TotalTeamGames` | 球隊累計出賽數 | |
| `HitterAcnt` / `HitterName` | 球員代碼 / 姓名 | |

### 打擊（Plate Appearance 層級的彙總）

`PlateAppearances`（打席）、`HitCnt`（打數）、`HittingCnt`（安打）、
`OneBaseHitCnt` / `TwoBaseHitCnt` / `ThreeBaseHitCnt` / `HomeRunCnt`（一二三安、全壘打）、
`TotalBases`（壘打數）、`RunBattedINCnt`（打點）、`ScoreCnt`（得分）、
`StrikeOutCnt`（三振）、`BasesONBallsCnt`（四壞）、`IntentionalBasesONBallsCnt`（故意四壞）、
`HitBYPitchCnt`（死球）、`SacrificeHitCnt`（犧短）、`SacrificeFlyCnt`（犧飛）、
`DoublePlayBatCnt` / `TripplePlayBatCnt`（雙殺打／三殺打）、`Lobs`（殘壘）、
`StealBaseOKCnt` / `StealBaseFailCnt`（盜壘成功／失敗）、`Avg`（打擊率）

`Avg` 是**該場結束時的累計季打擊率**，不是單場打擊率（從數列走勢可確認）。

### 守備（同一張表附帶）

`PutoutCnt`（刺殺）、`AssistCnt`（助殺）、`JoinDoublePlayCnt` / `JoinTripplePlayCnt`（參與雙殺／三殺）、
`ErrorCnt`（失誤）、`CaughtStealingCnt`（盜壘阻殺）、`PassedBallCnt`（捕逸）

### 投手版本

同一個 endpoint，當 `defendStation == '投手'` 時回傳投球逐場欄位。
從頁面表格可確認包含：投球身份、勝敗結果、投球局數、面對打席、**總投球數**、被安打、被全壘打、
奪三振、失分、自責分、四壞、故四、死球、滾地出局、飛球出局、防禦率、完投、完封、好球數、
被盜壘、暴投、犯規、牽制出局等。

**投手版本本次未實際呼叫驗證**，欄位名稱來自頁面 Vue 綁定，尚未看過真實回傳。

---

## 7. 目前無法確認 / 取不到的欄位

| 項目 | 狀況 |
| --- | --- |
| 主客場 | 逐場成績表**沒有**主客場欄位。只能透過 `FieldNo` 間接推論，但球場代碼對照表未知 |
| 比賽勝負與比分 | 逐場成績表**沒有**球隊層級的勝負與得分 |
| 開賽時間 | `GameDate` 只有日期，時間欄位固定為 00:00:00 |
| 對手先發投手 | 逐場成績表沒有 |
| 打序 / 守備位置（當場） | 逐場成績表沒有；`defendStation` 是球員的登錄守位，非當場守位 |
| 打席層級明細 | 逐場成績是「每場一列的彙總」，**不是**逐打席資料 |
| 逐球資料 | 見下方說明 |
| 球速 / 進壘點 / 擊球初速等 tracking 數據 | 官網未見；本次未在任何頁面找到 |
| 資料更新時間 / 資料版本 | 回傳中沒有 timestamp，無法判斷資料何時更新 |
| 歷史資料深度 | 逐場成績表的年度選單只列出 2026 / 2025 / 2024 三年 |

### 關於逐打席與逐球

官網存在「文字轉播」頁面 `/box/live?year=&kindCode=&gameSno=`（頁面條件顯示僅 2017 年後場次有），
其 Vue 模板中可見**逐打席與逐球層級的欄位結構**：每個打席有 `PitcherAcnt` / `PitcherName`、
`Details` 陣列，每個 detail 含 `Index`（第幾球）、`IsBall` / `IsStrike`、`BallCnt` / `StrikeCnt`、
`Content`（文字描述）、`IsSpecialEvent`。

**但這只是頁面模板，實際資料由 `POST /box/getlive` 取得，本次刻意沒有呼叫驗證。**
因此目前只能說：「逐打席／逐球的**文字層級**資料看起來存在」，
不能說「已確認可以取得」，也沒有任何證據顯示有 tracking 型的逐球數據。

---

## 8. 為什麼沒有使用 stats.cpbl.com.tw

該站 `robots.txt` 明確寫著 `Disallow: /api/`。
進階數據平台是 Next.js App Router 應用，資料主要透過 `/api/` 取得，
頁面 HTML 內則是 RSC streaming payload（`self.__next_f`）。

- 直接呼叫 `/api/` 違反該站 robots.txt，**因此不做**。
- 解析 RSC payload 技術上可行且不違反 robots.txt，但格式屬於框架內部實作、極易變動，
  不適合作為 MVP 的資料基礎。

結論：**本階段先不使用進階數據平台**，若之後確實需要進階指標，
應先確認是否有正式的資料使用管道，而不是自行想辦法繞過。

---

## 9. 這份資料適合我們的 MVP 嗎

適合，但只覆蓋一部分。

| MVP 方向 | 這份資料能支援嗎 |
| --- | --- |
| 球隊目前近況 | **部分**。可以把球員逐場成績聚合出球隊近況，但沒有比賽勝負／比分，需要另一個來源 |
| 特別需要注意的球員 | **可以**。逐場打席／安打／四壞／三振足以做近期表現變化的偵測 |
| 下一場對手 | **不行**。逐場成績表只有已完成的比賽，賽程資料要另外查（`/schedule` 尚未調查） |

與 `PROJECT_DESIGN.md` 已定原則的對照：

- 「MVP 以 Game / Plate Appearance 層級為主要粒度」 → 相符。這份資料正是 **Game 層級、
  每場含打席數的球員成績**。
- 「不假設可以取得逐球資料」 → 相符。本次確實沒有驗證到可用的逐球資料。
- 「事實由程式計算」 → 相符。所有數值都是官網原始欄位，沒有任何推估或補值。

---

## 10. 可能遇到的限制

1. **官網 CDN 偶發 308 自我轉址**
   `www.cpbl.com.tw` 由 HiNetCDN 前置。當請求未命中 CDN 快取（`X-Cache: EXPIRED`）時，
   會回傳 `308 Permanent Redirect` 且 `Location` 指向**完全相同的網址**，造成無限轉址。
   同一個網址重試通常就會成功。實測 `/schedule` 連續三次為 200 / 200 / 308。
   → 任何取用程式都必須有重試機制，不能把單次失敗當成「沒有資料」。

2. **非公開 API，隨時可能改變**
   endpoint、參數名、欄位名、anti-forgery token 的取得位置都是從頁面 JS 觀察出來的，
   官方沒有承諾穩定性。網站改版就會壞掉。

3. **需要先載入頁面才能呼叫 endpoint**
   每次查詢都要「GET 頁面拿 token → POST endpoint」兩次請求，成本是單純 API 的兩倍。

4. **雙層 JSON 編碼**
   外層 `FollowScore` 是字串，忘記第二次 parse 會直接拿到字串。

5. **查詢粒度是「一名球員一個年度」**
   要拿整隊就得逐一球員查詢。以 28 人名單計，一次全隊更新約 56 次請求。
   → 必須自己控制頻率，並考慮快取，避免對官網造成負擔。

6. **沒有使用條款上的明確授權**
   資料是公開可瀏覽的，但官網並未提供 API 條款或資料授權說明。
   目前只做小量查詢的探索性使用。若之後要常態化取用或對外呈現，
   應先確認授權範圍，不應假設可以任意使用。

7. **球員代碼（Acnt）需要另外取得**
   `Acnt` 不是公開的固定編號表，要從球隊頁面 `/team?ClubNo=AEO` 解析。
   球員異動（升降二軍、交易、退役）時名單會變。

8. **編碼**
   回應為 UTF-8，中文隊名如「統一7-ELEVEn獅」含半形英數與符號，處理時不要假設純中文。

---

## 11. 實驗過程中確認的具體識別碼

以下皆從官網頁面直接讀取，非推測：

- 富邦悍將：`ClubNo=AEO`、`TeamNo=AEO011`
- 其他球隊 `ClubNo`：中信兄弟 `ACN`、統一7-ELEVEn獅 `ADD`、樂天桃猿 `AJL`、
  味全龍 `AAA`、台鋼雄鷹 `AKP`
- 富邦悍將球員頁面：`/team?ClubNo=AEO` 可解析出 28 名球員的姓名、背號、登錄守位與 `Acnt`
- 本次測試球員：張育成 `Acnt=0000006888`，登錄守位「游擊手」

---

## 12. 本次總共發出的請求量

探索期間對 `www.cpbl.com.tw` 的請求量在 20 次量級以內（含重試與失敗），
未做任何批次或迴圈抓取。`src/data_source_experiment.py` 每執行一次只發出 2 個請求。

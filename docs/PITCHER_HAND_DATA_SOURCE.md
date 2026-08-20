# 投手左右手（pitcher_hand）資料來源調查（Step 7A）

調查日期：2026-08-20
調查性質：一次性可行性驗證。**沒有**修改 processed data、沒有建立 pipeline、沒有做任何 matchup 計算。
前置文件：`docs/DATA_SOURCE_INVESTIGATION.md`、`docs/SCHEDULE_DATA_SOURCE_INVESTIGATION.md`、
`docs/FIRST_EVIDENCE_ANALYSIS.md`

---

## 0. 結論摘要（先講重點）

問題：「是否能可靠取得張育成每場逐場資料所面對的投手左右手？」

答案分三層，必須分開講，因為它們的可靠性不同：

| 層級 | 能不能取得 | 說明 |
| --- | --- | --- |
| **每場「面對的投手」的左右手**（字面上的要求） | **無法可靠取得** | 概念上就不成立：一場比賽打者會面對多位投手，game 層級不存在單一 pitcher_hand。官方資料本身也證實了這點（見第 4.3 節） |
| **每場「對手先發投手」的左右手** | **可以可靠取得，已驗證 5 場全對** | 需要組合兩個官方來源，覆蓋張育成本季約 65% 的打席 |
| **整季 VS. 左投 / VS. 右投 的彙總成績** | **官方直接提供，已交叉對帳成功** | 但只有季累計，無法切成 recent 10 之類的窗口 |

張育成逐場成績的原始 API response **完全沒有任何投手欄位**（41 欄逐一確認過）。

沒有使用任何第三方資料，沒有根據球員姓名或任何間接資訊推測左右手。

---

## 1. 資料來源

### 1.1 已排除：Step 2 的逐場成績 API

檢查對象：`data/raw/follow_score_0000006888_2026.json`
（Step 2 存下的 `POST /team/getfollowscore` 原始回傳，本次沒有重新抓取）

41 個欄位逐一檢查，**沒有任何投手相關欄位**：

```
AssistCnt, Avg, BasesONBallsCnt, CaughtStealingCnt, DoublePlayBatCnt, ErrorCnt,
FieldNo, FightTeamAbbrName, FightTeamCode, GameDate, GameSno, HitBYPitchCnt,
HitCnt, HitterAcnt, HitterName, HittingCnt, HomeRunCnt,
IntentionalBasesONBallsCnt, JoinDoublePlayCnt, JoinTripplePlayCnt, KindCode,
Lobs, OneBaseHitCnt, PassedBallCnt, PlateAppearances, PutoutCnt,
RunBattedINCnt, SId, SacrificeFlyCnt, SacrificeHitCnt, ScoreCnt,
StealBaseFailCnt, StealBaseOKCnt, StrikeOutCnt, TeamNo, ThreeBaseHitCnt,
TotalBases, TotalTeamGames, TripplePlayBatCnt, TwoBaseHitCnt, Year
```

用 `pitch|hand|throw` 做關鍵字比對，只命中 `HitBYPitchCnt`（死球），與投手手別無關。

**結論：逐場成績 API 這條路走不通。**

### 1.2 來源 A：賽程 endpoint（提供每場的先發投手 Acnt）

| 項目 | 內容 |
| --- | --- |
| 網址 | `POST https://www.cpbl.com.tw/schedule/getgamedatas` |
| 取得方式 | Step 3 已驗證，本次沿用，沒有新研究 |
| 相關欄位 | `HomePitcherAcnt` / `HomePitcherName` / `VisitingPitcherAcnt` / `VisitingPitcherName` |

### 1.3 來源 B：球員個人頁（提供投打習慣）

| 項目 | 內容 |
| --- | --- |
| 網址 | `GET https://www.cpbl.com.tw/team/person?Acnt=<投手Acnt>` |
| 方法 | HTML 直接內含，**不需要 AJAX，不需要 token** |
| 相關欄位 | `投打習慣` |

HTML 結構（實際觀察到的內容）：

```html
<dd class="b_t">
    <div class="label">投打習慣</div>
    <div class="desc">右投左打</div>
</dd>
```

### 1.4 來源 C：分項成績 endpoint（官方直接提供 VS. 左投 / VS. 右投）

| 項目 | 內容 |
| --- | --- |
| 頁面 | `https://www.cpbl.com.tw/team/apart?Acnt=0000006888`（球員選單的「分項成績」） |
| endpoint | `POST https://www.cpbl.com.tw/team/getapartscore` |
| 參數 | `acnt`、`kindCode`、`position`（`01` 野手 / `02` 投手）、`year`（`9999` 為年度累計） |
| header | `RequestVerificationToken`（從 `/team/apart` 頁面取，與 Step 2/3 同一機制） |
| 回傳 | 雙層 JSON：`{"Success": true, "ApartScore": "<JSON 字串>"}` |

這是本次調查的意外發現，也是對 matchup 分析最直接相關的官方資料。

---

## 2. 取得方式

### 2.1 每場對手先發投手的左右手（來源 A + B）

```
1. POST /schedule/getgamedatas          取得整年賽程（Step 3 已驗證方式）
2. 篩出富邦相關場次，判斷富邦是主隊還是客隊
3. 取對手那一側的投手 Acnt：
       富邦是主隊 → VisitingPitcherAcnt
       富邦是客隊 → HomePitcherAcnt
4. GET /team/person?Acnt=<該 Acnt>      解析「投打習慣」
5. 投打習慣開頭「右投」→ R，「左投」→ L
```

請求成本：賽程 2 個請求（整年一次拿完），加上每位不同投手 1 個請求。
一整季富邦約 120 場，對手先發投手去重後大約數十人，屬於可控範圍。

本次驗證只發了 2（賽程）+ 5（投手頁）= 7 個請求。

### 2.2 整季 VS. 左投 / VS. 右投（來源 C）

```
1. GET  /team/apart?Acnt=0000006888     取 token
2. POST /team/getapartscore             data: acnt / kindCode=A / position=01 / year=2026
```

2 個請求就能拿到全部分項，不需要逐場處理。

---

## 3. 欄位

### 3.1 `投打習慣` 的取值與轉換

實際觀察到的值都是「X投Y打」四字格式。轉換規則：

| 投打習慣開頭 | `pitcher_hand` |
| --- | --- |
| `右投` | `R` |
| `左投` | `L` |
| 其他 / 缺值 | `None`（不猜） |

本次 5 個樣本觀察到三種組合：`右投右打`、`右投左打`、`左投左打`。
**沒有**觀察到雙手投球（switch pitcher）的案例，所以 `L` / `R` 以外的值目前無法確認官方會怎麼標。

### 3.2 分項成績中的手別欄位

`/team/getapartscore` 回傳每列有 `ItemGroupCode` 與 `ItemName`，
`ItemGroupCode = 3` 那一組就是投手屬性分項：

| ItemName | 意義 |
| --- | --- |
| `VS. 右投` | 面對右投的彙總 |
| `VS. 左投` | 面對左投的彙總 |
| `VS. 本土投手` | 面對本土投手 |
| `VS. 外籍投手` | 面對外籍投手 |
| `VS. 先發` | 面對先發投手 |
| `VS. 中繼` | 面對中繼投手 |
| `VS. 救援` | 面對救援投手 |

每列都帶完整打擊數據，包含 `PlateAppearances`、`HitCnt`（打數）、`HittingCnt`（安打）、
`Avg`、`Obp`、`Slg`、`Ops`，以及 Step 5 缺的 `SacrificeFlyCnt` 與 `IntentionalBasesONBallsCnt`。

---

## 4. 驗證結果

### 4.1 先確認賽程的 Pitcher 欄位到底是什麼

在把 `HomePitcherAcnt` / `VisitingPitcherAcnt` 當成「先發投手」之前，
必須先排除它其實是「勝敗投」的可能。

作法：對富邦 87 場已完成比賽，比對 Pitcher 欄位與 `WinningPitcherAcnt` / `LoserPitcherAcnt`。

| 結果 | 次數 |
| --- | --- |
| Pitcher 欄位 == 勝投或敗投 | 138 |
| Pitcher 欄位與勝敗投都不同 | **36** |

有 36 次不同，證明這個欄位**不是**勝敗投。實例：

```
GameSno 7  2026-03-31  Home Pitcher=布雷克  Visiting Pitcher=魔力藍  W=張奕  L=髙塩將樹
GameSno 12 2026-04-03  Home Pitcher=李東洺  Visiting Pitcher=曾家輝  W=張奕  L=莊昕諺
GameSno 22 2026-04-06  Home Pitcher=江國豪  Visiting Pitcher=鄭浩均  W=廖任磊 L=李振昌
GameSno 35 2026-04-14  Home Pitcher=陳品宏  Visiting Pitcher=伍鐸    W=曾峻岳 L=林凱威
```

加上賽程頁 Vue 模板本身就用「先發({隊名})：」這個標籤來顯示這兩個欄位（Step 3 已記錄），
綜合判斷：**`Home/VisitingPitcher*` 是先發投手。**

保留說明：這是「排除勝敗投 + 官方頁面標籤」兩個依據推出的結論，
沒有用官方文件或第三方來源做第三次確認。

### 4.2 五場樣本驗證

取富邦最近 5 場已完成比賽，抓對手先發投手 Acnt，再查其球員頁：

| game_sno | game_date | opponent | 賽程投手名 | 球員頁姓名 | 球員頁守位 | 投打習慣 | **pitcher_hand** | 姓名一致 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 261 | 2026-08-13 | 中信兄弟 | 伍立辰 | 伍立辰 | 投手 | 右投右打 | **R** | 是 |
| 262 | 2026-08-14 | 統一7-ELEVEn獅 | 布雷克 | 布雷克 | 投手 | 右投右打 | **R** | 是 |
| 265 | 2026-08-15 | 統一7-ELEVEn獅 | 林詔恩 | 林詔恩 | 投手 | 左投左打 | **L** | 是 |
| 269 | 2026-08-16 | 統一7-ELEVEn獅 | 張宥謙 | 張宥謙 | 投手 | 右投右打 | **R** | 是 |
| 272 | 2026-08-18 | 樂天桃猿 | 陳克羿 | 陳克羿 | 投手 | 右投左打 | **R** | 是 |

檢查項目全部通過：

- 5 場的投手 Acnt 都有值，且都能查到球員頁
- 賽程給的投手姓名與球員頁姓名 **5/5 完全一致**（確認 Acnt 對應正確）
- 球員頁守位 5/5 都是「投手」
- 投打習慣 5/5 都解析成功，`pitcher_hand` 5/5 都能推導出 `L` 或 `R`
- 這 5 個 `game_sno` 都存在於張育成的逐場資料中（Step 5 Recent 10 的最後 5 場）

附帶交叉驗證：`game_sno 265`（08-15）的先發是林詔恩，Step 3 記錄該場富邦 1:12 落敗、
**勝投也是林詔恩**，兩處一致。

### 4.3 官方分項成績的交叉對帳（重要）

`ItemGroupCode = 3` 的手別分項，與 Step 5 算出的季累計完全對帳：

| 項目 | VS. 右投 | VS. 左投 | 合計 | Step 5 season | 是否一致 |
| --- | --- | --- | --- | --- | --- |
| 打席 PA | 258 | 62 | **320** | **320** | 一致 |
| 打數 AB | 219 | 54 | **273** | **273** | 一致 |
| 安打 H | 68 | 17 | **85** | **85** | 一致 |

官方分項的比率（僅記錄，不解讀）：

| 分項 | PA | AB | H | AVG | OBP |
| --- | --- | --- | --- | --- | --- |
| VS. 右投 | 258 | 219 | 68 | 0.3105 | 0.4031 |
| VS. 左投 | 62 | 54 | 17 | 0.3148 | 0.4032 |

**這同時證明了「每場單一 pitcher_hand」不成立**，因為同一組分項顯示：

| 分項 | PA | 佔全季 320 PA |
| --- | --- | --- |
| VS. 先發 | 209 | 65.3% |
| VS. 中繼 | 80 | 25.0% |
| VS. 救援 | 31 | 9.7% |

也就是說，張育成本季有 **34.7% 的打席不是面對先發投手**。
若把「對手先發投手的手別」當成整場的 `pitcher_hand`，就會有超過三分之一的打席被錯誤標記。

---

## 5. 限制

### 5.1 game 層級的 `pitcher_hand` 在概念上不成立

一場比賽打者面對多位投手，手別可能不同。
Step 2 的逐場資料是「每場一列的彙總」，無法拆到打席層級，
所以無法在不失真的情況下給每一場一個 `pitcher_hand`。

這不是資料抓不到的問題，是**粒度不匹配**的問題。

### 5.2 「對手先發投手手別」只覆蓋約 65% 的打席

見第 4.3 節。可以取得、可以驗證，但它是一個**代理變數（proxy）**，不是「該場面對的投手」。
使用時必須明講它代表的是先發投手，而不是整場。

### 5.3 真正的逐打席投手資料需要另一條路，本次沒有做

Step 2 文件已記錄：`/box/live` 文字轉播的頁面模板中有逐打席與逐球結構，
每個打席帶 `PitcherAcnt`。理論上這是唯一能給出「每個打席面對誰」的官方來源。

但：

- 需要**每場一個請求**（張育成 77 場出賽 → 至少 77 個請求），本次刻意沒有做
- `POST /box/getlive` 的實際 payload 從 Step 2 到現在都還沒驗證過
- 只有 2017 年後的場次有

### 5.4 球員頁是「當前狀態」快照

球員頁顯示的球隊是查詢當下的登錄狀態，不是比賽當時的狀態。
本次 5 個樣本中，`伍立辰`、`林詔恩`、`張宥謙` 的球員頁球隊都顯示「二軍」，
但他們是在一軍例行賽先發。

投打習慣本身不會改變，所以對 `pitcher_hand` 沒有影響。
但若未來要用球員頁的其他欄位（球隊、背號、守位），必須注意這個時間點問題。

### 5.5 沒有觀察到的取值

5 個樣本只看到 `右投右打` / `右投左打` / `左投左打`。
沒有遇到雙手投球或缺值的案例，所以：

- 不確定官方對 switch pitcher 怎麼標
- 不確定缺值時 `投打習慣` 是空字串還是整個欄位不存在

程式若要處理，必須把非 `右投` / `左投` 開頭的情況一律當 `None`，不要硬套。

### 5.6 未開打場次的投手姓名為空

Step 3 已記錄：未開打場次的 `PitcherAcnt` 有值但 `PitcherName` 是空字串。
本次 5 場都是已完成比賽，姓名都有值，所以**沒有驗證到未開打場次**的情況。

要做「下一場對手先發投手是左投還是右投」時，必須靠 Acnt 查球員頁拿姓名與手別，
而那個 Acnt 是否確為預告先發，Step 3 就已標記為未確認，本次也沒有進一步驗證。

### 5.7 樣本量

只驗證 5 場、5 位投手，都集中在 8 月中旬。沒有驗證整季，也沒有跨年度驗證。

### 5.8 沒有動 processed data

依指示，本次沒有把 `pitcher_hand` 寫進任何 processed 檔案，
`data/processed/` 下的兩份 JSON 未被修改。

---

## 6. 是否適合下一步 matchup analysis

分開回答，因為三條路的適用性差很多。

### 路線 1：官方分項成績（`VS. 左投` / `VS. 右投`）— **最適合，但只有季累計**

優點：

- 官方直接算好的，不需要我們自己配對投手，沒有 proxy 誤差
- 與我們的 season totals 完全對帳（320 PA / 273 AB / 85 H 三項全中），可信度高
- 只要 2 個請求
- 附帶提供 `Obp`、`Slg`、`Ops`、`SacrificeFlyCnt`、`IntentionalBasesONBallsCnt`，
  正好補上 Step 5 因缺欄位而無法算 OBP 的問題

限制：

- **只有季累計，沒有時間維度**。無法回答「最近 10 場面對左投的表現」，
  因此無法接上 Step 6 建立的 rolling baseline
- VS. 左投只有 62 個打席、54 個打數，樣本很小
- 沒有逐場明細，無法自己重算或切窗口，只能接受官方給的彙總數字

### 路線 2：每場對手先發投手手別（賽程 + 球員頁）— **可行，但要接受它是 proxy**

優點：

- 可靠、可驗證（5/5 通過）
- 有逐場粒度，可以切窗口、可以接 rolling baseline
- 請求量可控

限制：

- 只覆蓋 65.3% 的打席，34.7% 打席會被錯誤歸類
- 用它做出的「面對左投表現」與官方分項的數字**必然不一致**，
  因為兩者的分母定義不同。這件事必須事先講清楚，否則會出現兩個互相矛盾的數字

### 路線 3：逐打席文字轉播（`/box/getlive`）— **理論上最正確，成本最高，尚未驗證**

這是唯一能同時滿足「正確」與「有時間維度」的路。
但需要每場一個請求，而且 payload 從未驗證過。目前不建議在沒有明確需求前投入。

### 建議（僅供參考，決定權在你）

如果下一步的目標是**驗證 matchup 訊號是否存在**，路線 1 成本最低、可信度最高，
可以先看官方分項的 VS. 左投 / VS. 右投 差距大不大，再決定值不值得投入路線 2 或 3。

如果下一步的目標是**做「下一場對手先發是左投，張育成近期面對左投表現如何」這種 insight**，
那路線 1 不夠（沒有時間維度），必須走路線 2，並且在輸出時明確標示分母是「面對先發投手」。

無論走哪一條，都必須明講 `pitcher_hand` 的定義是什麼，
因為「面對的投手」與「對手先發投手」是兩件不同的事。

---

## 7. 本次刻意沒有做的事

- 沒有修改 `data/processed/` 下的任何檔案
- 沒有建立正式 scraper 或 pipeline（驗證用腳本為臨時檔，已刪除，方法已記錄於第 2 節）
- 沒有做任何 matchup 計算
- 沒有建立 Insight
- 沒有加入 AI / LLM
- 沒有加入 pandas
- 沒有使用第三方資料來源
- 沒有根據球員姓名、國籍或任何間接資訊推測左右手
- 沒有呼叫 `/box/getlive`，也沒有大量抓取
- 沒有繞過任何存取限制

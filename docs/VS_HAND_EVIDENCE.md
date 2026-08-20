# VS. 右投 / VS. 左投 Evidence（Step 7B）

建立日期：2026-08-20
產出腳本：`src/splits_vs_hand.py`
前置文件：`docs/PITCHER_HAND_DATA_SOURCE.md`（Step 7A）、`docs/FIRST_EVIDENCE_ANALYSIS.md`（Step 5）

> ## 重要範圍聲明
>
> **這是「整季累計」的 VS. 左投 / VS. 右投 資料，不是最近 10 場，也不是最近 15 場。**
>
> 本文件的數字涵蓋 2026 一軍例行賽全季（張育成 77 場出賽、320 個打席）。
> 官方分項成績**沒有時間維度**，無法切成任何窗口。
>
> 請不要把本文件的數字與 `docs/ROLLING_BASELINE_ANALYSIS.md`（Step 6 的 10 場滾動基準）
> 混在一起看。兩者的分母範圍完全不同，混用會得到錯誤的結論。

本文件只記錄事實與驗證，不含門檻、不判斷強弱、不含自然語言結論。

---

## 1. Objective

建立張育成 2026 一軍例行賽在「面對右投」與「面對左投」兩個情境下的事實基礎，
作為之後 matchup 分析的第一份 context evidence。

Step 7A 已確認：逐場資料沒有投手資訊，用「對手先發投手」當 proxy 只覆蓋 65.3% 的打席。
因此本階段改用官方已算好的分項成績，避開 proxy 誤差。

---

## 2. Official source

| 項目 | 內容 |
| --- | --- |
| 來源 | CPBL 官方網站「分項成績」 |
| 頁面 | `https://www.cpbl.com.tw/team/apart?Acnt=0000006888` |
| endpoint | `POST https://www.cpbl.com.tw/team/getapartscore` |
| 參數 | `acnt=0000006888`、`kindCode=A`（一軍例行賽）、`position=01`（野手）、`year=2026` |
| 必要 header | `RequestVerificationToken`（從分項頁 HTML 取），`Content-Type: application/x-www-form-urlencoded` |
| 回傳 | 雙層 JSON：`{"Success": true, "ApartScore": "<JSON 字串>"}` |
| 請求量 | **2 個**（取 token + 取資料） |
| 取得日期 | 2026-08-20 |

沒有使用第三方資料。沒有使用「對手先發投手」proxy。

回傳共 56 列分項，本階段只取 `ItemGroupCode == 3` 的 7 列：

```
VS. 右投、VS. 左投、VS. 本土投手、VS. 外籍投手、VS. 先發、VS. 中繼、VS. 救援
```

其中只使用 `VS. 右投` 與 `VS. 左投`。

---

## 3. Definition of VS Right / VS Left

| 本專案標籤 | 官方 `ItemName` | 定義 |
| --- | --- | --- |
| VS RIGHT | `VS. 右投` | 面對右投手的所有打席（整季累計） |
| VS LEFT | `VS. 左投` | 面對左投手的所有打席（整季累計） |

定義來自官方，**不是我們自己配對投手算出來的**。
這是本階段選用這個來源的主要理由：不需要自己判斷每個打席面對誰，因此沒有 proxy 誤差。

兩者是互斥且完備的切分：`258 + 62 = 320`，與 Step 5 的季累計打席數完全相同（見第 7 節）。

**這兩個分項沒有日期、沒有場次資訊**，所以無法回答「最近幾場面對左投的表現」。

---

## 4. Raw official fields

官方回傳的每一列有 35 個欄位。本階段使用的對應關係：

| 本專案欄位 | 官方欄位 | 備註 |
| --- | --- | --- |
| `plate_appearances` | `PlateAppearances` | |
| `at_bats` | `HitCnt` | 官網 `HitCnt` 是**打數**，不是安打 |
| `hits` | `HittingCnt` | 官網 `HittingCnt` 是**安打** |
| `doubles` | `TwoBaseHitCnt` | |
| `triples` | `ThreeBaseHitCnt` | |
| `home_runs` | `HomeRunCnt` | |
| `walks` | `BasesONBallsCnt` | **已包含故意四壞**，見第 5.1 節 |
| `intentional_walks` | `IntentionalBasesONBallsCnt` | 是 `walks` 的細項拆解，不可再相加 |
| `sacrifice_flies` | `SacrificeFlyCnt` | |
| `sacrifice_hits` | `SacrificeHitCnt` | 用於打席恆等式驗證 |
| `hit_by_pitch` | `HitBYPitchCnt` | |
| `strikeouts` | `StrikeOutCnt` | |
| `rbi` | `RunBattedINCnt` | |
| `total_bases` | `TotalBases` | |
| `runs` | **不存在** | 官方分項成績**沒有得分欄位**，見第 8.1 節 |

官方另外提供 `Avg`、`Obp`、`Slg`、`Ops` 四個比率。
**這四個只用來對帳，沒有當成任何計算結果。**

未使用的官方欄位：`OneBaseHitCnt`、`GroundOuts`、`FlyOuts`、`Goao`、`ItemIndex`、
`ItemNote`、`SId`、`CSId`、`MSId`、`Cdt`、`Mdt`、`Enabled`、`MDeled`、`KindCode`、
`Year`、`HitterAcnt`。

---

## 5. Calculated metrics

### 5.1 先確認 BB 語意（OBP 的前提）

指示要求：若 `BasesONBallsCnt` 是否包含故意四壞有疑義，必須先明確確認，不可猜測。

**判定方法：打席恆等式。** 一個打席一定會落入以下之一：

```
PA = AB + BB + HBP + SF + SH
```

若 `BB` 不含 `IBB`，等式必須寫成 `PA = AB + BB + IBB + HBP + SF + SH`。
兩式相差正好是 `IBB`，因此只要 `IBB > 0` 就能分辨。這是實證，不是推測。

實測結果（兩個分項的 `IBB` 都是 1，所以兩者都具備分辨力）：

| 分項 | PA | IBB | `AB+BB+HBP+SF+SH` | `AB+BB+IBB+HBP+SF+SH` |
| --- | --- | --- | --- | --- |
| VS. 右投 | 258 | 1 | **258（符合 PA）** | 259（不符） |
| VS. 左投 | 62 | 1 | **62（符合 PA）** | 63（不符） |

季累計層級也做了同樣檢查（用 Step 2 存下的逐場原始資料，77 場加總）：

```
PA                  = 320
AB+BB+HBP+SF+SH     = 273 + 37 + 7 + 3 + 0 = 320   符合
AB+BB+IBB+HBP+SF+SH = 273 + 37 + 2 + 7 + 3 + 0 = 322   不符（多出 2，正好是 IBB）
```

**結論：`BasesONBallsCnt` 已包含故意四壞。`IntentionalBasesONBallsCnt` 是其中的細項拆解。**

補充說明：官網頁面上的 OBP 公式提示文字寫成
「(安打 + 四壞球 + 故意四壞球 + 觸身球) / (打數 + 四壞球 + 故意四壞球 + 觸身球 + 犧牲飛球)」，
字面上會讓人以為要把故意四壞另外加。實測證明**不是**——那段文字是在說明「四壞球（含故意四壞）」，
若照字面另外加一次，算出來的 OBP 會與官方值不符。

### 5.2 公式

```
AVG = hits / at_bats
SLG = total_bases / at_bats
OBP = (hits + walks + hit_by_pitch) / (at_bats + walks + hit_by_pitch + sacrifice_flies)
```

OBP 沒有另外加 `intentional_walks`，理由見 5.1。
三個比率全部由程式自行計算，官方的 `Avg` / `Obp` / `Slg` 只用來對帳。

`at_bats == 0` 時比率為 `None`（不填 0、不除零）。本次兩個分項的 `at_bats` 都不為 0。

---

## 6. Right vs Left comparison

### VS RIGHT（官方 `ItemName`: `VS. 右投`）

| 欄位 | 值 |
| --- | --- |
| plate_appearances | 258 |
| at_bats | 219 |
| hits | 68 |
| doubles | 12 |
| triples | 0 |
| home_runs | 14 |
| walks | 30 |
| intentional_walks | 1 |
| sacrifice_flies | 3 |
| sacrifice_hits | 0 |
| hit_by_pitch | 6 |
| strikeouts | 40 |
| runs | **None**（官方分項無此欄位） |
| rbi | 37 |
| total_bases | 122 |
| **batting_average** | **0.3105** = 68 / 219 |
| **on_base_percentage** | **0.4031** = 104 / 258 |
| **slugging_percentage** | **0.5571** = 122 / 219 |

官方比率（僅對帳）：`Avg=0.3105`、`Obp=0.4031`、`Slg=0.557`、`Ops=0.96`

### VS LEFT（官方 `ItemName`: `VS. 左投`）

| 欄位 | 值 |
| --- | --- |
| plate_appearances | 62 |
| at_bats | 54 |
| hits | 17 |
| doubles | 6 |
| triples | 0 |
| home_runs | 0 |
| walks | 7 |
| intentional_walks | 1 |
| sacrifice_flies | 0 |
| sacrifice_hits | 0 |
| hit_by_pitch | 1 |
| strikeouts | 15 |
| runs | **None**（官方分項無此欄位） |
| rbi | 2 |
| total_bases | 23 |
| **batting_average** | **0.3148** = 17 / 54 |
| **on_base_percentage** | **0.4032** = 25 / 62 |
| **slugging_percentage** | **0.4259** = 23 / 54 |

官方比率（僅對帳）：`Avg=0.3148`、`Obp=0.4032`、`Slg=0.4259`、`Ops=0.829`

### DIFFERENCE（VS LEFT 減 VS RIGHT）

僅記錄數值差。**不判斷哪一邊比較強或比較弱，不做任何解讀。**

| 欄位 | VS RIGHT | VS LEFT | 差（左 − 右） |
| --- | --- | --- | --- |
| plate_appearances | 258 | 62 | −196 |
| at_bats | 219 | 54 | −165 |
| hits | 68 | 17 | −51 |
| doubles | 12 | 6 | −6 |
| triples | 0 | 0 | ±0 |
| home_runs | 14 | 0 | −14 |
| walks | 30 | 7 | −23 |
| intentional_walks | 1 | 1 | ±0 |
| sacrifice_flies | 3 | 0 | −3 |
| hit_by_pitch | 6 | 1 | −5 |
| strikeouts | 40 | 15 | −25 |
| rbi | 37 | 2 | −35 |
| total_bases | 122 | 23 | −99 |
| **batting_average** | 0.3105 | 0.3148 | **+0.0043** |
| **on_base_percentage** | 0.4031 | 0.4032 | **+0.0001** |
| **slugging_percentage** | 0.5571 | 0.4259 | **−0.1312** |

三個比率的方向不一致：AVG 與 OBP 幾乎相同（差 0.0043 與 0.0001），SLG 差 0.1312。
從計數欄位可以直接看到 SLG 差距的來源：**VS. 左投的 54 個打數中沒有全壘打**
（VS. 右投 219 打數有 14 支）。

這只是指出數字之間的關係，**不構成任何結論**。VS. 左投只有 54 個打數，樣本很小。

---

## 7. Validation

程式執行 22 項檢查，**通過 21 項，失敗 1 項**。失敗項目未做任何修正，說明見 7.2。

Season totals 是從 `data/processed/zhang_yucheng_game_logs_2026.json`
的 77 筆逐場資料**獨立加總**得出，不使用任何官方彙總值。

### 7.1 通過的檢查

| # | 檢查 | 結果 | 說明 |
| --- | --- | --- | --- |
| 1 | VS Right PA + VS Left PA == Season PA | PASS | 258 + 62 = **320** = 320 |
| 2 | VS Right AB + VS Left AB == Season AB | PASS | 219 + 54 = **273** = 273 |
| 3 | VS Right H + VS Left H == Season H | PASS | 68 + 17 = **85** = 85 |
| 4 | VS Right TB + VS Left TB == Season TB | PASS | 122 + 23 = **145** = 145 |
| 5a | VS RIGHT 自算 AVG == 官方 AVG | PASS | 0.3105 vs 0.3105 |
| 5b | VS LEFT 自算 AVG == 官方 AVG | PASS | 0.3148 vs 0.3148 |
| 6a | VS RIGHT 自算 OBP == 官方 OBP | PASS | 0.4031 vs 0.4031 |
| 6b | VS LEFT 自算 OBP == 官方 OBP | PASS | 0.4032 vs 0.4032 |
| 7b | VS LEFT 自算 SLG == 官方 SLG | PASS | 0.4259 vs 0.4259 |
| 7c | VS RIGHT SLG 截斷 4 位後 == 官方 | PASS | 0.5570 vs 0.557 |
| 7d | VS LEFT SLG 截斷 4 位後 == 官方 | PASS | 0.4259 vs 0.4259 |
| 8 | processed data 未被修改 | PASS | sha256 `e3712d87…`、30,547 bytes 前後不變 |

**第 6 項是本階段最重要的驗證：** 自算 OBP 與官方 OBP 在兩個分項上都完全相符。
這同時證實了 5.1 節對 BB 語意的判定是正確的——若 BB 不含 IBB 而我們少加了，
OBP 就不可能對得上。

補充對帳（超出指示要求，用來加強信心），全部 PASS：

| 欄位 | VS Right + VS Left | processed data 加總 |
| --- | --- | --- |
| doubles | 12 + 6 = 18 | 18 |
| triples | 0 + 0 = 0 | 0 |
| home_runs | 14 + 0 = 14 | 14 |
| walks | 30 + 7 = 37 | 37 |
| strikeouts | 40 + 15 = 55 | 55 |
| rbi | 37 + 2 = 39 | 39 |
| hit_by_pitch | 6 + 1 = 7 | 7 |
| sacrifice_flies | 3 + 0 = 3 | 3 |
| intentional_walks | 1 + 1 = 2 | 2 |

（`sacrifice_flies` 與 `intentional_walks` 不在 processed data 中，
是用 Step 2 存下的 `data/raw/follow_score_0000006888_2026.json` 逐場加總對帳。）

### 7.2 失敗的 1 項：VS RIGHT SLG 尾數

```
[FAIL] VS RIGHT：自算 SLG 與官方 SLG 一致
       自算 0.5571 vs 官方 0.557
```

精確值是 `122 / 219 = 0.55707763…`。四捨五入到 4 位小數是 `0.5571`，
但官方給的是 `0.557`（即 `0.5570`）。

**這是官方的數值呈現慣例，不是資料不一致。** 為了確認，我用
`ItemGroupCode == 3` 全部 7 個分項的 AVG 與 SLG（共 14 個數值）逐一比對：

| 判定假設 | 相符數 / 總數 |
| --- | --- |
| 官方 = 四捨五入到 4 位小數 | 11 / 14 |
| 官方 = **截斷到 4 位小數** | **14 / 14** |

三個造成差異的案例：

| 分項 | 指標 | 精確值 | 官方值 | 四捨五入 | 截斷 |
| --- | --- | --- | --- | --- | --- |
| VS. 右投 | Slg | 0.55707763 | 0.557 | 0.5571 | **0.5570** |
| VS. 先發 | Avg | 0.33888889 | 0.3388 | 0.3389 | **0.3388** |
| VS. 先發 | Slg | 0.56666667 | 0.5666 | 0.5667 | **0.5666** |

三個案例官方值都與「截斷」相符、與「四捨五入」不符，14/14 全部支持截斷。

**處理方式：沒有修改任何數值，也沒有把嚴格比對的容忍度放寬讓它通過。**
原本的嚴格檢查保留為 FAIL，另外新增一項定義明確的「截斷到 4 位小數後比對」檢查（7c、7d），
兩項都 PASS。本專案的計算值一律保留完整精度，不採用官方的截斷慣例。

---

## 8. Limitations

### 8.1 `runs`（得分）無法取得

指示要求的 16 個欄位中，`runs` **官方分項成績沒有提供**。
35 個回傳欄位中沒有任何得分欄位（逐場成績有 `ScoreCnt`，分項成績沒有）。

已記錄為 `None`，**沒有用任何方式推估或填補**。

### 8.2 這是整季累計，沒有時間維度

再次強調：本文件的數字是全季 320 個打席的累計。
官方分項不提供日期或場次，因此：

- 無法算「最近 10 場面對左投」
- 無法接上 Step 6 的 10 場滾動基準
- 無法看出這個左右投差距在球季中如何變化

### 8.3 VS. 左投樣本很小

`54` 個打數、`62` 個打席。作為對照，Step 6 單一個 10 場滾動窗口的打數是 28 ~ 42，
也就是 VS. 左投整季的樣本量只相當於一個多的滾動窗口。

比率指標在這個樣本量下波動很大。0.0043 的 AVG 差距，換算成安打只是 0.2 支的差別
（54 個打數中多或少一支安打，AVG 就會變動約 0.019）。

### 8.4 無法自行重算或切分

官方只給彙總，沒有逐場或逐打席明細。因此：

- 我們無法驗證官方是怎麼把打席分到左投/右投的（例如換投中間的打席怎麼歸類）
- 無法自行重新切分（例如只看某段時間、只看主場）
- 只能接受官方給的分母

唯一的間接保證是第 7 節的加總對帳：兩個分項的 PA / AB / H / TB 以及 9 個補充計數欄位
全部與逐場資料加總一致，說明切分本身沒有遺漏或重複。

### 8.5 沒有比較基準

只有張育成自己的左右投數字。沒有聯盟平均、沒有同守位平均、沒有其他年度。
所以無法判斷「AVG 差 0.0043、SLG 差 0.1312」這樣的差距在一般打者身上算大還是算小。

### 8.6 官方比率的截斷慣例

如 7.2 所述，官方比率是截斷到 4 位小數。若未來要與官方數字逐位比對，
必須知道這件事，否則會誤判為資料錯誤。

### 8.7 未驗證的範圍

- 只驗證 2026 年、只驗證 `kindCode=A`、只驗證張育成一人
- 沒有驗證 `position=02`（投手分項）的欄位結構
- 沒有使用 `VS. 本土/外籍投手`、`VS. 先發/中繼/救援` 這 5 個分項（除了拿來做截斷慣例診斷）
- 沒有驗證 `year=9999`（年度累計）的行為

---

## 9. 本階段刻意沒有做的事

- 沒有建立任何 Insight 或 threshold
- 沒有判斷哪一邊「比較弱」，沒有判斷球員「擅長 / 不擅長」
- 沒有加入最近 10 / 15 場
- 沒有加入對手、沒有加入下一場比賽
- 沒有加入 AI / LLM
- 沒有 dashboard
- 沒有加入 pandas，只用 Python 標準函式庫
- 沒有修改 `data/processed/` 下的檔案（已用 sha256 驗證）
- 沒有修改 `README.md` 與 `PROJECT_DESIGN.md`
- 沒有使用第三方資料，沒有使用「對手先發投手」proxy
- 沒有修正那 1 項 FAIL，也沒有放寬容忍度讓它通過

"""CPBL 賽程資料來源可行性實驗（Step 3，一次性驗證用，不是正式 scraper）。

目的：驗證能否用程式從 CPBL 官網賽程頁取得比賽日期、時間、主客隊、場地、比賽狀態、
比分，並判斷「富邦悍將的下一場比賽」。

作法（共 2 次 HTTP 請求）：
    1. GET  https://www.cpbl.com.tw/schedule
       取得賽程頁，讀出呼叫內部 endpoint 所需的 anti-forgery token。
    2. POST https://www.cpbl.com.tw/schedule/getgamedatas
       取得賽程 JSON。

重要限制：這個 endpoint 的查詢粒度是「一整年」——參數 calendar 固定送該年 1/1，
官網自己也是一次拿整年再由前端切月份顯示。**沒有辦法只要求少數幾場**，
所以這支程式一次請求就會拿到整年賽程。它只在記憶體中處理，預設不寫檔。

刻意的限制：
    - 只用 Python 標準函式庫，不安裝任何套件。
    - 只發 2 個請求，不做批次、不寫資料庫、不建立資料模型。
    - 只印出少量結果（下一場 + 最近幾場已完成比賽）。

用法：
    python src/schedule_source_experiment.py
    python src/schedule_source_experiment.py --team AEO011 --recent 3
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

BASE = "https://www.cpbl.com.tw"
SCHEDULE_PAGE = BASE + "/schedule"
SCHEDULE_API = BASE + "/schedule/getgamedatas"

# 富邦悍將一軍球隊代碼（取自官網頁面連結）
DEFAULT_TEAM_CODE = "AEO011"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# GameResult 代碼對照（取自賽程頁 Vue 模板的判斷式）
GAME_RESULT_TEXT = {
    "": "未開打／尚未有結果",
    "0": "已完成",
    "1": "延賽",
    "2": "保留",
    "4": "取消",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """關掉自動轉址，方便觀察官網偶發的 308 self-redirect。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(
    jar: http.cookiejar.CookieJar,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    tries: int = 4,
    pause: float = 3.0,
) -> str:
    body = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-TW,zh;q=0.9",
        "Referer": BASE + "/",
    }
    if data:
        req_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        req_headers["X-Requested-With"] = "XMLHttpRequest"
    if headers:
        req_headers.update(headers)

    last = ""
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, data=body, headers=req_headers)
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar), _NoRedirect
        )
        try:
            with opener.open(req, timeout=30) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8", "replace")
                last = f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code} (Location={exc.headers.get('Location')})"
        except urllib.error.URLError as exc:
            last = f"URLError {exc.reason}"
        print(f"    第 {attempt} 次失敗：{last}")
        if attempt < tries:
            time.sleep(pause)
    raise RuntimeError(f"請求失敗：{url} -> {last}")


def extract_token(html: str) -> str | None:
    """取出 /schedule/getgamedatas 那一段 ajax 內嵌的 anti-forgery token。"""
    m = re.search(
        r"url:\s*'/schedule/getgamedatas'.*?RequestVerificationToken:\s*'([^']+)'",
        html,
        re.S,
    )
    return m.group(1) if m else None


def fetch_year_schedule(year: int, kind_code: str) -> list:
    jar = http.cookiejar.CookieJar()

    print(f"[1/2] GET {SCHEDULE_PAGE}")
    html = request(jar, SCHEDULE_PAGE)
    token = extract_token(html)
    print(f"      token 取得：{'是' if token else '否'}")
    if not token:
        raise RuntimeError("找不到 RequestVerificationToken，頁面結構可能已改變")

    payload = {
        "calendar": f"{year}/01/01",  # 官網固定送該年 1/1，回傳整年
        "location": "",  # 空字串 = 全部場地
        "kindCode": kind_code,
    }
    print(f"[2/2] POST {SCHEDULE_API}  data={payload}")
    time.sleep(1)  # 禮貌性間隔
    raw = request(
        jar, SCHEDULE_API, data=payload, headers={"RequestVerificationToken": token}
    )

    outer = json.loads(raw)
    print(f"      回傳最外層鍵值：{sorted(outer.keys())}")
    # 與 Step 2 相同：雙層 JSON，GameDatas 是字串
    return json.loads(outer.get("GameDatas") or "[]")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def describe(game: dict) -> str:
    pre = parse_dt(game.get("PreExeDate"))
    time_str = pre.strftime("%H:%M") if pre else "??:??"
    gd = parse_dt(game.get("GameDate"))
    date_str = gd.strftime("%Y-%m-%d") if gd else "?"
    result = GAME_RESULT_TEXT.get(game.get("GameResult", ""), game.get("GameResult"))
    line = (
        f"{date_str} {time_str}  第{game.get('GameSno')}場  "
        f"{game.get('VisitingTeamName')}(客) vs {game.get('HomeTeamName')}(主)  "
        f"@{game.get('FieldAbbe')}  狀態={result}"
    )
    if game.get("GameResult") == "0":
        line += f"  比分 {game.get('VisitingScore')}:{game.get('HomeScore')}"
        if game.get("WinningPitcherName"):
            line += f"  勝投={game.get('WinningPitcherName')}"
    else:
        vp, hp = game.get("VisitingPitcherName"), game.get("HomePitcherName")
        if vp or hp:
            line += f"  預告先發 客={vp or '未定'} / 主={hp or '未定'}"
    return line


def main() -> None:
    today = date.today()
    parser = argparse.ArgumentParser(description="CPBL 賽程取得可行性實驗")
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument("--kind-code", default="A", help="A=一軍例行賽")
    parser.add_argument("--team", default=DEFAULT_TEAM_CODE, help="球隊代碼，富邦悍將=AEO011")
    parser.add_argument("--recent", type=int, default=3, help="印出最近幾場已完成比賽")
    parser.add_argument(
        "--show-raw", action="store_true", help="額外印出兩筆完整原始記錄，供欄位語意檢視"
    )
    args = parser.parse_args()

    games = fetch_year_schedule(args.year, args.kind_code)

    print()
    print("=" * 90)
    print(f"{args.year} 年賽制 {args.kind_code} 回傳場次總數：{len(games)}")
    if not games:
        print("（沒有資料）")
        return

    print(f"\n單場記錄實際欄位共 {len(games[0])} 個：")
    print("  " + ", ".join(sorted(games[0].keys())))

    team_games = [
        g
        for g in games
        if args.team in (g.get("HomeTeamCode"), g.get("VisitingTeamCode"))
    ]
    print(f"\n球隊 {args.team} 相關場次：{len(team_games)}")
    breakdown: dict[str, int] = {}
    for g in team_games:
        key = GAME_RESULT_TEXT.get(g.get("GameResult", ""), str(g.get("GameResult")))
        breakdown[key] = breakdown.get(key, 0) + 1
    print(f"  GameResult 分佈：{breakdown}")
    dup = len(team_games) - len({(g.get("GameSno")) for g in team_games})
    print(f"  GameSno 重複筆數：{dup}")

    # 判斷「下一場」：GameResult 為空（尚未有結果）且預定開賽時間在現在之後，取最早的一場
    now = datetime.now()
    upcoming = sorted(
        (
            g
            for g in team_games
            if g.get("GameResult") == ""
            and (parse_dt(g.get("PreExeDate")) or datetime.max) > now
        ),
        key=lambda g: parse_dt(g.get("PreExeDate")) or datetime.max,
    )
    finished = sorted(
        (g for g in team_games if g.get("GameResult") == "0"),
        key=lambda g: parse_dt(g.get("GameDate")) or datetime.min,
    )

    print(f"\n【下一場比賽】（現在時間 {now:%Y-%m-%d %H:%M}）")
    if upcoming:
        print("  " + describe(upcoming[0]))
        nxt = upcoming[0]
        opponent = (
            nxt.get("VisitingTeamName")
            if nxt.get("HomeTeamCode") == args.team
            else nxt.get("HomeTeamName")
        )
        is_home = nxt.get("HomeTeamCode") == args.team
        print(f"  → 對手：{opponent}，本隊為{'主隊' if is_home else '客隊'}")
        if len(upcoming) > 1:
            print("  之後兩場：")
            for g in upcoming[1:3]:
                print("    " + describe(g))
    else:
        print("  找不到未來場次（可能球季已結束或賽程尚未公布）")

    print(f"\n【最近 {args.recent} 場已完成比賽】")
    for g in finished[-args.recent :]:
        print("  " + describe(g))
    print("=" * 90)

    if args.show_raw:
        for label, sample in (("未開打場次", upcoming[0] if upcoming else None),
                              ("已完成場次", finished[-1] if finished else None)):
            if sample is None:
                continue
            print(f"\n--- 完整原始記錄（{label}）---")
            for key in sorted(sample):
                if key.endswith("ImgPath"):
                    continue  # 圖片路徑對我們沒用，略過
                print(f"  {key:<28} {sample[key]!r}")


if __name__ == "__main__":
    main()

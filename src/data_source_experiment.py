"""CPBL 資料來源可行性實驗（Step 2，一次性驗證用，不是正式 scraper）。

目的：驗證能否用程式從 CPBL 官網取得「單一球員的逐場成績」，並觀察實際欄位。

作法（共 2 次 HTTP 請求）：
    1. GET  https://www.cpbl.com.tw/team/follow?Acnt=<acnt>
       取得逐場成績表頁面，從 HTML 中讀出呼叫內部 endpoint 所需的參數與 anti-forgery token。
    2. POST https://www.cpbl.com.tw/team/getfollowscore
       取得該球員該年度的逐場成績 JSON。

刻意的限制：
    - 只用 Python 標準函式庫，不安裝任何套件。
    - 一次只查一名球員、一個年度，預設只印出最近 5 場。
    - 不做批次抓取、不寫資料庫、不建立資料模型。
    - 遇到官網偶發的 308 self-redirect 時最多重試 4 次，每次間隔 3 秒。

用法：
    python src/data_source_experiment.py
    python src/data_source_experiment.py --acnt 0000002352 --year 2026 --games 5

注意：這支程式會對 CPBL 官網發出少量真實請求，請不要放進迴圈重複執行。
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
from pathlib import Path

BASE = "https://www.cpbl.com.tw"
FOLLOW_PAGE = BASE + "/team/follow"
FOLLOW_API = BASE + "/team/getfollowscore"

# 預設測試案例：富邦悍將 張育成（Acnt 取自官網富邦悍將球員頁面）
DEFAULT_ACNT = "0000006888"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# 逐場成績表中我們最關心的欄位（官網欄位名 -> 中文說明）
FIELDS_OF_INTEREST = [
    ("GameDate", "比賽日期"),
    ("GameSno", "場次"),
    ("FightTeamAbbrName", "對手"),
    ("PlateAppearances", "打席"),
    ("HitCnt", "打數"),
    ("HittingCnt", "安打"),
    ("HomeRunCnt", "全壘打"),
    ("RunBattedINCnt", "打點"),
    ("BasesONBallsCnt", "四壞"),
    ("StrikeOutCnt", "三振"),
    ("Avg", "打擊率"),
]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """關掉自動轉址，方便觀察官網偶發的 308 self-redirect。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_opener(jar: http.cookiejar.CookieJar):
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _NoRedirect
    )


def request(
    jar: http.cookiejar.CookieJar,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    tries: int = 4,
    pause: float = 3.0,
) -> str:
    """發送請求並回傳文字內容；遇到非 200 會重試（官網 CDN 偶發 308）。"""
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
        try:
            with _build_opener(jar).open(req, timeout=30) as resp:
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


def extract_page_context(html: str) -> dict:
    """從逐場成績表頁面抽出呼叫 /team/getfollowscore 所需的參數。"""
    ctx: dict = {}
    for key, pattern in (
        ("acnt", r"acnt:\s*'([^']*)'"),
        ("defendStation", r"defendStation:\s*'([^']*)'"),
        ("kindCode", r"kindCode:\s*'([^']*)'"),
        ("year", r"year:\s*'([^']*)'"),
    ):
        m = re.search(pattern, html)
        ctx[key] = m.group(1) if m else None

    # token 是逐個 ajax 呼叫各自內嵌的，要取 getfollowscore 這一段的
    m = re.search(
        r'url:\s*"/team/getfollowscore".*?RequestVerificationToken:\s*\'([^\']+)\'',
        html,
        re.S,
    )
    ctx["token"] = m.group(1) if m else None

    m = re.search(r'yearOpts:\s*JSON\.parse\(\'(\[.*?\])\'', html, re.S)
    ctx["year_options"] = json.loads(m.group(1)) if m else []
    m = re.search(r'kindCodeOpts:\s*JSON\.parse\(\'(\[.*?\])\'', html, re.S)
    ctx["kind_options"] = json.loads(m.group(1)) if m else []
    m = re.search(r"<h1>\s*([^<\s][^<]*?)\s*</h1>", html)
    ctx["player_name"] = m.group(1) if m else None
    return ctx


def fetch_follow_score(acnt: str, year: str | None, kind_code: str | None) -> tuple[dict, list]:
    jar = http.cookiejar.CookieJar()

    print(f"[1/2] GET {FOLLOW_PAGE}?Acnt={acnt}")
    html = request(jar, f"{FOLLOW_PAGE}?Acnt={acnt}")
    ctx = extract_page_context(html)
    print(f"      頁面預設值：{ {k: ctx[k] for k in ('acnt', 'defendStation', 'kindCode', 'year')} }")
    print(f"      token 取得：{'是' if ctx['token'] else '否'}")
    print(f"      可選年度：{[o['Value'] for o in ctx['year_options']]}")

    if not ctx["token"]:
        raise RuntimeError("找不到 RequestVerificationToken，頁面結構可能已改變")

    payload = {
        "acnt": ctx["acnt"] or acnt,
        "defendStation": ctx["defendStation"] or "",
        "year": year or ctx["year"],
        "kindCode": kind_code or ctx["kindCode"],
    }
    print(f"[2/2] POST {FOLLOW_API}  data={payload}")
    time.sleep(1)  # 禮貌性間隔
    raw = request(
        jar, FOLLOW_API, data=payload, headers={"RequestVerificationToken": ctx["token"]}
    )

    outer = json.loads(raw)
    # 回傳格式為雙層 JSON：外層 {"Success": true, "FollowScore": "<JSON 字串>"}
    rows = json.loads(outer.get("FollowScore") or "[]")
    ctx["response_top_level_keys"] = sorted(outer.keys())
    ctx["payload"] = payload
    return ctx, rows


def report(ctx: dict, rows: list, games: int) -> None:
    print()
    print("=" * 78)
    print(f"球員 Acnt {ctx['payload']['acnt']}（守位：{ctx['defendStation']}）"
          f" / {ctx['payload']['year']} 年 / 賽制代碼 {ctx['payload']['kindCode']}")
    print(f"回傳最外層鍵值：{ctx['response_top_level_keys']}")
    print(f"取得場次數：{len(rows)}")
    if not rows:
        print("（沒有資料）")
        return

    print(f"\n單場記錄實際欄位共 {len(rows[0])} 個：")
    print("  " + ", ".join(sorted(rows[0].keys())))

    # 實測結果：回傳的 list 是「日期由新到舊」排序，因此最近幾場取開頭
    print(f"日期範圍：{rows[-1].get('GameDate', '')[:10]} ~ {rows[0].get('GameDate', '')[:10]}"
          f"（回傳順序為日期由新到舊）")

    print(f"\n最近 {min(games, len(rows))} 場（欄位為官網原始值，未經任何加工）：")
    header = "  ".join(label for _, label in FIELDS_OF_INTEREST)
    print("  " + header)
    for row in rows[:games]:
        cells = []
        for key, label in FIELDS_OF_INTEREST:
            value = row.get(key)
            if key == "GameDate" and isinstance(value, str):
                value = value[:10]
            cells.append(f"{value}".ljust(max(len(label) * 2, 6)))
        print("  " + " ".join(cells))
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description="CPBL 逐場成績取得可行性實驗")
    parser.add_argument("--acnt", default=DEFAULT_ACNT, help="官網球員代碼 Acnt")
    parser.add_argument("--year", default=None, help="年度，預設用頁面預設值")
    parser.add_argument("--kind-code", default=None, help="賽制代碼，A=一軍例行賽")
    parser.add_argument("--games", type=int, default=5, help="印出最近幾場")
    parser.add_argument(
        "--save", action="store_true", help="把原始回傳存到 data/raw/ 供人工檢視"
    )
    args = parser.parse_args()

    ctx, rows = fetch_follow_score(args.acnt, args.year, args.kind_code)
    report(ctx, rows, args.games)

    if args.save:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        out = RAW_DIR / f"follow_score_{ctx['payload']['acnt']}_{ctx['payload']['year']}.json"
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n原始回傳已存到：{out}（data/ 已被 .gitignore 排除）")


if __name__ == "__main__":
    main()

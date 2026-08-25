"""MVP Backend / API（Step 23）。

它做什麼：把 Step 22 的 Product Output Model 透過一個唯讀 HTTP 端點暴露出來。

    Step 22 Product Output Model  ->  serialize  ->  API response

它**不**做什麼：
    - 不重算任何分析。AVG / OBP / SLG / difference / sample size / percentile /
      grouping 全部由 src/product_output_model.py 產生，這裡一個都不重建
    - 不呼叫 CPBL。使用者打開網站**不會**觸發任何抓取
    - 沒有 score / weight / threshold / priority / Top-N / prediction /
      recommendation / LLM
    - 沒有資料庫、沒有 ORM、沒有認證
    - 不修改 raw / processed data，也不寫入任何檔案
    - 沒有新增任何第三方依賴（只用 Python 標準庫）

為什麼用標準庫而不是 Flask / FastAPI：
    `requirements.txt` 目前是空的，專案至今沒有任何第三方依賴。這個 MVP 只需要
    2 個唯讀 GET 端點、固定 JSON、沒有認證、沒有資料庫、沒有非同步需求。
    `http.server` 完全足夠，因此不引入框架。

determinism：
    - 回應主體**不含任何請求時間**。重複請求的 bytes 完全相同
    - 序列化一律 `sort_keys=True`，不受 dict 插入順序影響
    - 「資料的時間」用 `api.data_as_of`，來自已完成比賽推導的參考日與來源檔
      sha256，與請求時間是兩件事

用法：
    python src/api.py                          # 127.0.0.1:8000
    python src/api.py --host 0.0.0.0 --port 9000
    python src/api.py --cors-origin http://localhost:5173
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

# import 這條鏈會安裝 socket guard，封鎖所有對外連線
from candidate_insights import (  # noqa: E402
    APART_CACHE_PATH,
    PLAYER_LOG_PATH,
    load_inputs,
    network_guard_active,
    sha256_of,
)
from insight_chain import SCHEDULE_PATH, load_schedule  # noqa: E402
from product_output_model import build_product_output  # noqa: E402

API_VERSION = "step23-v1"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# slug -> 目前唯一支援的球員。Step 22 的產品輸出只涵蓋一位球員。
PLAYER_REGISTRY = {
    "zhang-yucheng": {
        "player_acnt": "0000006888",
        "season": 2026,
        "kind_code": "A",
    },
}

# 受控的錯誤代碼詞彙。回應主體只會出現這些值。
ERROR_CODES = (
    "player_not_found",
    "player_slug_required",
    "malformed_path",
    "not_found",
    "method_not_allowed",
    "product_output_generation_failed",
)

SOURCE_FILES = (PLAYER_LOG_PATH, APART_CACHE_PATH, SCHEDULE_PATH)

ENDPOINTS = (
    {"method": "GET", "path": "/api/health",
     "description": "後端存活檢查，不依賴任何外部網路"},
    {"method": "GET", "path": "/api/player/{player_slug}",
     "description": "回傳 Step 22 Product Output（唯讀）",
     "available_player_slugs": sorted(PLAYER_REGISTRY)},
)

API_CONTAINS_NO = [
    "score", "weight", "threshold", "ranking", "priority", "importance",
    "confidence_score", "top_n", "prediction", "recommendation", "strategy",
    "natural_language_conclusion", "llm", "database", "authentication",
    "live_scraping", "request_timestamp_in_body",
]


# ------------------------------------------------------------------ 快取

class ProductOutputCache:
    """整條 pipeline 只跑一次，之後所有請求共用同一個結果。

    這是「資料收集」與「資料供應」分離的關鍵：HTTP 請求路徑上沒有任何抓取，
    也沒有重算。快取內容只依賴本地檔案，不依賴時鐘。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._output: dict | None = None

    @property
    def warm(self) -> bool:
        return self._output is not None

    def get(self) -> dict:
        with self._lock:
            if self._output is None:
                logs, apart_rows = load_inputs()
                schedule = load_schedule()
                self._output = build_product_output(logs, apart_rows, schedule)
            return self._output

    def clear(self) -> None:
        with self._lock:
            self._output = None


CACHE = ProductOutputCache()


# ------------------------------------------------------------------ 回應組裝

def source_file_digests() -> list[dict]:
    """來源檔的 sha256。這是「資料版本」的事實依據，與請求時間無關。"""
    out = []
    for path in SOURCE_FILES:
        digest, size = sha256_of(path)
        out.append({
            "path": path.name,
            "sha256": digest,
            "bytes": size,
        })
    return sorted(out, key=lambda r: r["path"])


def build_api_block(slug: str, output: dict) -> dict:
    md = output["metadata"]
    sel = output["next_game"]["selection_rule"]
    return {
        "api_version": API_VERSION,
        "endpoint": f"/api/player/{slug}",
        "player_slug": slug,
        "read_only": True,
        "product_output_version": md["product_output_version"],
        "source_of_truth": {
            "module": "src/product_output_model.py",
            "function": "build_product_output",
            "note": (
                "API 只做序列化。所有數值由 Step 22 產生，"
                "後端沒有重算任何指標，也沒有第二套 schema。"
            ),
        },
        "data_as_of": {
            "reference_date": sel["reference_date"],
            "reference_date_basis": sel["reference_date_basis"],
            "clock_independent": sel["clock_independent"],
            "source_file_digests": source_file_digests(),
            "is_not_request_time": (
                "這是**資料推導出來的時間點**：已完成比賽中最晚的 game_date。"
                "它不是 API 收到請求的時間。"
            ),
        },
        "request_time_included": False,
        "request_time_note": (
            "回應主體刻意不含請求時間，因此重複請求的 bytes 完全相同。"
            "HTTP 的 Date header 由協定層提供，不屬於資料。"
        ),
        "external_network_used": False,
        "external_network_note": (
            "請求路徑上沒有任何對 CPBL 或其他外部服務的呼叫。"
            "資料收集（Step 2~4）與資料供應（本階段）是分開的責任。"
        ),
        "contains_no": list(API_CONTAINS_NO),
    }


def build_player_payload(slug: str) -> dict:
    """Step 22 的 9 個頂層區塊原樣輸出，另加一個命名空間化的 `api` 區塊。

    `api` 是新增，不是取代：Step 22 的 9 個鍵一個都沒有被改名、移除或重新包裝。
    """
    output = CACHE.get()
    payload = dict(output)  # 淺拷貝，避免把 api 區塊寫回快取物件
    payload["api"] = build_api_block(slug, output)
    return payload


def build_health_payload() -> dict:
    """存活檢查。刻意不觸發 pipeline，也不碰任何網路。"""
    return {
        "status": "ok",
        "api_version": API_VERSION,
        "endpoints": [dict(e) for e in ENDPOINTS],
        "available_player_slugs": sorted(PLAYER_REGISTRY),
        "checks": {
            "product_output_cache_warm": CACHE.warm,
            "local_source_files_present": {
                path.name: path.exists() for path in SOURCE_FILES
            },
            "network_guard_active": network_guard_active(),
        },
        "external_network_used": False,
        "note": (
            "health 只檢查後端自身與本地檔案是否存在，"
            "不依賴任何外部網路，也不觸發分析 pipeline。"
        ),
    }


def error_payload(code: str, http_status: int, message: str,
                  **extra) -> dict:
    assert code in ERROR_CODES, code
    body = {
        "error": {
            "code": code,
            "http_status": http_status,
            "message": message,
        }
    }
    body["error"].update(extra)
    return body


# ------------------------------------------------------------------ 路由

def normalize_path(raw_path: str) -> list[str]:
    """去掉 query / fragment 與前後斜線，回傳路徑片段。"""
    path = urlsplit(raw_path).path
    return [seg for seg in path.split("/") if seg]


def dispatch(method: str, raw_path: str) -> tuple[int, dict]:
    """純函式路由。回傳 (http_status, body)。

    刻意與 socket 層分離：
      - 邏輯可以在完全不開任何連線的情況下測試
      - 本專案的 socket guard 封鎖所有 connect，因此測試不透過真實 socket
    """
    if method not in ("GET", "HEAD"):
        return 405, error_payload(
            "method_not_allowed", 405,
            "此端點為唯讀，只接受 GET。",
            allowed_methods=["GET", "HEAD"],
        )

    segments = normalize_path(raw_path)

    if not segments or segments[0] != "api":
        return 404, error_payload(
            "not_found", 404, "找不到這個路徑。",
            available_endpoints=[f"{e['method']} {e['path']}" for e in ENDPOINTS],
        )

    if segments == ["api", "health"]:
        return 200, build_health_payload()

    if segments[:2] == ["api", "player"]:
        if len(segments) == 2:
            return 400, error_payload(
                "player_slug_required", 400,
                "路徑缺少 player slug。",
                expected_path="/api/player/{player_slug}",
                available_player_slugs=sorted(PLAYER_REGISTRY),
            )
        if len(segments) > 3:
            return 400, error_payload(
                "malformed_path", 400,
                "路徑片段過多。",
                expected_path="/api/player/{player_slug}",
                received_segment_count=len(segments),
            )
        slug = segments[2]
        if slug not in PLAYER_REGISTRY:
            return 404, error_payload(
                "player_not_found", 404,
                "沒有這位球員的產品輸出。",
                requested_player_slug=slug,
                available_player_slugs=sorted(PLAYER_REGISTRY),
            )
        try:
            return 200, build_player_payload(slug)
        except Exception:
            # 只把細節寫到 stderr；回應主體不含 traceback 或檔案系統路徑
            traceback.print_exc(file=sys.stderr)
            return 500, error_payload(
                "product_output_generation_failed", 500,
                "產生產品輸出時發生內部錯誤。",
                player_slug=slug,
                detail_disclosed=False,
                detail_note="錯誤細節只記錄在伺服器端日誌，不隨回應輸出。",
            )

    return 404, error_payload(
        "not_found", 404, "找不到這個路徑。",
        available_endpoints=[f"{e['method']} {e['path']}" for e in ENDPOINTS],
    )


def serialize(body: dict) -> bytes:
    """deterministic 序列化：鍵一律排序，因此不受 dict 插入順序影響。"""
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------ HTTP 層

class ApiHandler(BaseHTTPRequestHandler):
    """薄薄一層 socket 轉接。所有路由邏輯都在 dispatch()。"""

    protocol_version = "HTTP/1.1"
    # 不揭露 Python / 伺服器版本
    server_version = "baseball-intelligence-api"
    sys_version = ""

    cors_origins: tuple[str, ...] = ()

    def _write(self, status: int, body: bytes, *, include_body: bool = True):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._write_cors_headers()
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _write_cors_headers(self) -> None:
        if not self.cors_origins:
            return
        origin = self.headers.get("Origin")
        allow = None
        if "*" in self.cors_origins:
            allow = "*"
        elif origin and origin in self.cors_origins:
            allow = origin
        if allow:
            self.send_header("Access-Control-Allow-Origin", allow)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Vary", "Origin")

    def do_GET(self) -> None:  # noqa: N802
        status, body = dispatch("GET", self.path)
        self._write(status, serialize(body))

    def do_HEAD(self) -> None:  # noqa: N802
        status, body = dispatch("HEAD", self.path)
        self._write(status, serialize(body), include_body=False)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self.cors_origins:
            status, body = dispatch("OPTIONS", self.path)
            self._write(status, serialize(body))
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._write_cors_headers()
        self.end_headers()

    def _unsupported(self) -> None:
        status, body = dispatch(self.command, self.path)
        self._write(status, serialize(body))

    do_POST = _unsupported
    do_PUT = _unsupported
    do_PATCH = _unsupported
    do_DELETE = _unsupported

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[api] %s - %s\n" % (self.address_string(), fmt % args))


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                cors_origins: tuple[str, ...] = ()) -> ThreadingHTTPServer:
    handler = type("BoundApiHandler", (ApiHandler,),
                   {"cors_origins": tuple(cors_origins)})
    return ThreadingHTTPServer((host, port), handler)


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Baseball Intelligence 唯讀 MVP API（Step 23）"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--cors-origin", action="append", default=[], metavar="ORIGIN",
        help="允許的 CORS 來源，可重複。預設完全不送 CORS header。"
             "傳入 '*' 會放行所有來源，僅適合本機開發。",
    )
    parser.add_argument(
        "--warm", action="store_true",
        help="啟動時先跑一次 pipeline 並快取，讓第一個請求不用等。",
    )
    args = parser.parse_args(argv)

    if args.warm:
        print("[api] 預先建立產品輸出……", file=sys.stderr)
        CACHE.get()
        print("[api] 產品輸出已快取。", file=sys.stderr)

    server = make_server(args.host, args.port, tuple(args.cors_origin))
    host, port = server.server_address[:2]
    print(f"[api] listening on http://{host}:{port}", file=sys.stderr)
    for e in ENDPOINTS:
        print(f"[api]   {e['method']} {e['path']}", file=sys.stderr)
    if args.cors_origin:
        print(f"[api] CORS allowed origins: {args.cors_origin}", file=sys.stderr)
    else:
        print("[api] CORS: 未啟用（不送任何 Access-Control header）",
              file=sys.stderr)
    print("[api] 請求路徑上沒有任何外部呼叫；資料只來自本地檔案。",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[api] 收到中斷，關閉伺服器。", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

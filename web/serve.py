"""Step 24 Frontend — 靜態檔案伺服器（標準庫，零依賴）。

為什麼要另外一支：
    `src/api.py` 是 Step 23 的成果，本階段**不修改它**。所以前端不由 API 伺服器
    提供，而是用這支獨立的靜態伺服器，兩者透過 Step 23 已經內建的 CORS 選項
    連接。這樣 Step 23 的檔案一行都不用動。

它只提供 `web/` 底下的檔案。`data/`、`src/`、`docs/` 都在 root 之外，
`SimpleHTTPRequestHandler` 會把路徑限制在 directory 參數內，
另外再做一次 realpath 檢查。

用法（兩個終端機）：
    1) python src/api.py --cors-origin http://127.0.0.1:5173
    2) python web/serve.py
    然後開 http://127.0.0.1:5173/
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5173


class FrontendHandler(SimpleHTTPRequestHandler):
    """只讀、只提供 web/ 內的檔案，不列出目錄以外的東西。"""

    server_version = "baseball-intelligence-frontend"
    sys_version = ""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }

    def translate_path(self, path: str) -> str:
        resolved = Path(super().translate_path(path)).resolve()
        try:
            resolved.relative_to(WEB_ROOT)
        except ValueError:
            # 任何試圖跳出 web/ 的路徑一律導回 web/ 根目錄
            return str(WEB_ROOT)
        return str(resolved)

    def end_headers(self) -> None:
        # 開發用：避免瀏覽器快取舊的 js / css
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[web] %s\n" % (fmt % args))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Baseball Intelligence 前端靜態伺服器（Step 24）"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    handler = partial(FrontendHandler, directory=str(WEB_ROOT))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    host, port = server.server_address[:2]
    print(f"[web] serving {WEB_ROOT} at http://{host}:{port}", file=sys.stderr)
    print(f"[web] 記得先啟動後端並允許此來源：", file=sys.stderr)
    print(f"[web]   python src/api.py --cors-origin http://{host}:{port}",
          file=sys.stderr)
    print("[web] 這支伺服器只提供 web/ 內的靜態檔案，不讀 data/、不呼叫 CPBL。",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[web] 收到中斷，關閉伺服器。", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

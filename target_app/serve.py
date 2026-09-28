"""零依赖靶场：给机制层提供一个稳定、离线、可开关的被测目标。

机制层不知道本文件存在（依赖方向：core/ 不 import target_app）。
三态验收靠这里的两个开关制造：copy-mode 改文案（→ FAIL_PRODUCT/anchor_drift），
strip-testids 摘掉稳定钩子（→ FAIL_ANCHOR）。
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGES = Path(__file__).resolve().parent / "pages"
BUILD = "demo-build-1"

SPEC_COPY = "登 录"
DRIFTED_COPY = "立即登录"

_state = {"copy_mode": "spec", "strip_testids": False, "shift_dy": 0}


def _render(name: str) -> str:
    html = (PAGES / name).read_text(encoding="utf-8")
    label = SPEC_COPY if _state["copy_mode"] == "spec" else DRIFTED_COPY
    html = html.replace("{{LOGIN_LABEL}}", label)
    # strip 开关必须同时告诉页面脚本：列表行是 JS 运行时创建的，
    # 服务端正则只扫得到服务端渲染出来的那部分 —— 不告诉脚本，
    # strip 就只是"半生效"，而半生效的开关会让验收为错的原因通过。
    html = html.replace("{{STRIP_TESTIDS}}", "true" if _state["strip_testids"] else "false")
    html = html.replace("{{SHIFT_STYLE}}", f"body {{ transform: translateY({_state['shift_dy']}px); }}")
    if _state["strip_testids"]:
        html = re.sub(r'\sdata-testid="[^"]*"', "", html)
    return html


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音，避免污染测试输出
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._json({"build": BUILD, "ready": True})
        if path in ("/", "/login"):
            return self._send(200, _render("login.html").encode())
        if path == "/list":
            return self._send(200, _render("list.html").encode())
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        path = self.path.split("?", 1)[0]
        if path == "/__demo__/copy-mode":
            _state["copy_mode"] = payload.get("mode", "spec")
            return self._json({"ok": True, "state": _state})
        if path == "/__demo__/strip-testids":
            _state["strip_testids"] = bool(payload.get("strip"))
            return self._json({"ok": True, "state": _state})
        if path == "/__demo__/shift-layout":
            _state["shift_dy"] = int(payload.get("dy") or 0)
            return self._json({"ok": True, "state": _state})
        return self._json({"error": "unknown"}, 404)


class ServerHandle:
    def __init__(self, httpd: ThreadingHTTPServer, thread: threading.Thread):
        self._httpd, self._thread = httpd, thread
        self.port: int = httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> "ServerHandle":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


def serve(port: int = 0, ttl_seconds: float | None = None) -> ServerHandle:
    """起靶场。返回的 handle **本身就是上下文管理器**，所以两种用法都对：

        with serve() as srv: ...        # 退出时自动停
        srv = serve(); ...; srv.stop()  # 手动停

    不要写成 @contextmanager 的生成器：那样 serve() 返回的是上下文管理器对象，
    不是 handle，`srv = serve(); srv.base_url` 会 AttributeError —— 接口声明的是
    返回 ServerHandle，就真的返回它。（ServerHandle 已经有 __enter__/__exit__。）
    """
    _state.update({"copy_mode": "spec", "strip_testids": False, "shift_dy": 0})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    handle = ServerHandle(httpd, thread)
    if ttl_seconds:
        timer = threading.Timer(ttl_seconds, handle.stop)
        timer.daemon = True
        timer.start()
    return handle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8712)
    ap.add_argument("--ttl", type=float, default=None, help="秒；到点自动退出，防挂死")
    args = ap.parse_args()
    start = time.time()
    with serve(port=args.port, ttl_seconds=args.ttl) as srv:
        print(f"target-app on {srv.base_url}", flush=True)
        while True:
            time.sleep(0.5)
            if args.ttl and time.time() - start > args.ttl:
                break


if __name__ == "__main__":
    main()

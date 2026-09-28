"""Regression for 修 1: a control named from `title` must drift as FAIL_PRODUCT.

Constructs a control whose accessible name comes ONLY from its `title` attribute,
drifts that title, and asserts that replaying against a `role` anchor yields
`FAIL_PRODUCT` / `anchor_drift` — not `FAIL_ANCHOR` / `missing`. The old
`__tttAllLabels` chain (aria-label || textContent || placeholder) has no `title`,
so it left this control with no drift candidate and mis-reported `missing`.

Needs a real browser; skipped by default like test_demo_three_states.py.
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core.compile.schema import Anchor, Checks, Step, Workflow
from core.primitives.session import Session
from core.replay.engine import run
from core.replay.result import FAIL_PRODUCT, PASS

pytestmark = pytest.mark.skipif(
    os.environ.get("TTT_E2E") != "1",
    reason="needs a real browser; set TTT_E2E=1",
)

SPEC = "Title Button"
DRIFTED = "Title Button Renamed"

PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
  <button id="ctl" type="button" title="__LABEL__"
          style="min-width:120px;min-height:28px;display:inline-block"></button>
  <div id="target"></div>
  <script>
    document.getElementById('ctl').addEventListener('click', function () {
      document.getElementById('target').textContent = 'done';
    });
  </script>
</body></html>"""


def _page(label: str) -> str:
    return PAGE.replace("__LABEL__", label)


@pytest.fixture()
def app(tmp_path):
    page_path = tmp_path / "index.html"

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = page_path.read_text(encoding="utf-8").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"

    def set_label(label):
        page_path.write_text(_page(label), encoding="utf-8")

    set_label(SPEC)
    yield base, set_label
    httpd.shutdown()
    httpd.server_close()


def _anchor():
    return Anchor(by="role", role="button", name=SPEC, copy_sensitive=True)


def _workflow():
    return Workflow(
        id="w-title-drift",
        title="title drift",
        target="demo",
        steps=(
            Step(n=1, action="goto", path="/"),
            Step(n=2, action="click", anchor=_anchor()),
        ),
    )


def test_title_named_control_drifts_to_fail_product(app):
    base, set_label = app

    with Session(base) as locator:
        # Sanity: with the spec title in place the anchor resolves and clicks clean.
        clean = run(_workflow(), locator, Checks(workflow="w-title-drift"))
        assert clean.status == PASS, clean.summary()

    set_label(DRIFTED)
    with Session(base) as locator:
        drifted = run(_workflow(), locator, Checks(workflow="w-title-drift"))

    assert drifted.status == FAIL_PRODUCT, (
        f"expected FAIL_PRODUCT/anchor_drift, got {drifted.status}/{drifted.reason}"
    )
    assert drifted.reason == "anchor_drift"
    assert drifted.steps[-1].drift, "drift candidate text should be recorded"

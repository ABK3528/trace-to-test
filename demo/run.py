"""End-to-end demo: record, compile, finalize, and replay.

This is the framework's real usage: record a browser flow, compile it into a
regression, then distinguish product drift from missing anchors without an LLM.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from core.compile.compiler import compile_recording
from core.compile.schema import Checks, Workflow
from core.lint.checks_lint import lint
from core.primitives.session import Session
from core.replay.engine import run
from core.replay.preflight import fetch_health, preflight, run_with_retry, stamp_build
from core.replay.result import FAIL_ANCHOR, FAIL_PRODUCT, PASS
from core.transcript.recording import load_recording
from demo.finalize import finalize, write_final
from target_app.serve import serve

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "demo" / "build"
PORT = 8712
BUILD_ID = "demo-build-1"
SHIFT_DY = 120


def _fresh_recording_name() -> str:
    """每次运行一个唯一目录名。

    browser-harness 的 start_recording(name) 是幂等追加：同名目录已存在时
    meta.json 被覆盖、events.jsonl 被截断重写，但旧帧不删 —— 第二次运行读到的是
    截断后的事件与叠加的旧帧，坐标反解就落在错误的元素上。demo 是用户会连跑
    好几遍的东西，所以这里必须保证每次起点干净，而不是靠"先手动删目录"。
    """
    return f"demo-smoke-{os.getpid()}-{time.time_ns()}"


def _explore(base_url: str) -> Path:
    """Drive the target once and record the actual browser session."""
    with Session(base_url) as s:
        rec = s.start_recording(_fresh_recording_name(), "Login and open create dialog")
        s.goto("/login")
        s.fill("#username", os.environ["DEMO_USERNAME"])
        s.fill("#password", os.environ["DEMO_PASSWORD"])
        s.click_text("登 录")
        s.wait_for('[data-loaded="true"]')
        s.click_text("新建")
        # 🔴 无头 Chrome 下合成点击偶发不触发 `<dialog>.showModal()`（约一成概率，
        #    负载高时更频），弹窗没弹出来，"确定" 就不可见。这里做一次**非记账**的
        #    重试：裸 click_at_xy 不经过 _act，录制里仍只有一次"新建"点击，
        #    编译产物不会被多塞一步。等 __tttFindByText('确定') 命中（= 弹窗已打开
        #    且按钮可见、已布局）再继续。
        from core.primitives.session import LOCATE_HELPERS
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not s.js(LOCATE_HELPERS + "(__tttFindByText('确定') !== null)"):
            box = s.js(
                "(()=>{const el=document.getElementById('open-create'); if(!el)return null;"
                "const r=el.getBoundingClientRect();"
                "return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()"
            )
            if box:
                s._bh.click_at_xy(int(box["x"]), int(box["y"]))
            time.sleep(0.1)
        s.click_text("确定")
        s.stop_recording()
    return rec


def _compile(rec_dir: Path, base_url: str):
    with Session(base_url) as locator:
        result = compile_recording(load_recording(rec_dir), target="demo", locator=locator)
    result.write(BUILD_DIR / "compiled")
    return result


def _expect(label: str, result, want_status: str, want_reason: str) -> bool:
    ok = result.status == want_status and (not want_reason or result.reason == want_reason)
    mark = "✅" if ok else "🔴"
    print(f"{mark} {label:<28} {result.status:<14} reason={result.reason or '-'}")
    return ok


def _replay(workflow: Workflow, checks: Checks, base_url: str, *, allow_hosts=()):
    def once():
        with Session(base_url, allow_hosts=allow_hosts) as locator:
            return run(workflow, locator, checks)
    return once


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["compile", "replay"], default=None,
                    help="compile = 只跑到编译+补全；replay = 从零重跑全流程（会重新探索与编译，不是跳过编译）")
    args = ap.parse_args(argv)

    os.environ.setdefault("DEMO_USERNAME", "demo")
    os.environ.setdefault("DEMO_PASSWORD", "secret")

    with serve(port=PORT) as srv:
        base_url = srv.base_url
        rec_dir = _explore(base_url)
        print(f"recorded → {rec_dir}")

        compiled = _compile(rec_dir, base_url)
        print(f"compiled → {BUILD_DIR / 'compiled'}  "
              f"({len(compiled.workflow.steps)} steps, {len(compiled.unresolved)} unresolved)")
        for item in compiled.unresolved:
            print(f"  unresolved: seq {item.seq} {item.helper} — {item.reason}")

        answers = json.loads((ROOT / "demo" / "answers.json").read_text(encoding="utf-8"))
        workflow, checks = finalize(BUILD_DIR / "compiled", answers)
        workflow = stamp_build(workflow, BUILD_ID)
        write_final(workflow, checks, BUILD_DIR / "final")

        violations = [v for v in lint(checks, workflow) if v.startswith("REJECT")]
        if violations:
            for violation in violations:
                print(f"🔴 lint: {violation}", file=sys.stderr)
            return 1

        if args.only == "compile":
            print("✅ compile-only run finished")
            return 0

        verdict = preflight(workflow, fetch_health(base_url))
        print(f"preflight: {verdict.status or 'ok'} ({verdict.reason or '-'})")
        if not verdict.proceed:
            return 1

        results = []
        result, note = run_with_retry(_replay(workflow, checks, base_url))
        results.append(_expect("baseline", result, PASS, ""))
        if note:
            print(f"   note: {note}")

        def _switch(path: str, payload: dict) -> None:
            req = urllib.request.Request(
                base_url + path, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()

        _switch("/__demo__/copy-mode", {"mode": "drifted"})
        result, _ = run_with_retry(_replay(workflow, checks, base_url), attempts=1)
        results.append(_expect("copy drifted", result, FAIL_PRODUCT, "anchor_drift"))
        _switch("/__demo__/copy-mode", {"mode": "spec"})

        _switch("/__demo__/strip-testids", {"strip": True})
        result, _ = run_with_retry(_replay(workflow, checks, base_url), attempts=1)
        results.append(_expect("testids stripped", result, FAIL_ANCHOR, "missing"))
        _switch("/__demo__/strip-testids", {"strip": False})

        click_steps = [st for st in workflow.steps if st.action == "click"]
        no_coords = bool(click_steps) and all(st.xy is None for st in click_steps)
        print(f"{'✅' if no_coords else '🔴'} {'artifact carries no coordinates':<28} "
              f"{len(click_steps)} click step(s), xy={[st.xy for st in click_steps]}")
        results.append(no_coords)

        first_click = next(e for e in load_recording(rec_dir).events if e.helper == "click_at_xy")
        cx, cy = first_click.xy()

        def _at(x: int, y: int) -> str:
            with Session(base_url) as probe:
                probe.goto("/login")
                return str(probe.js(
                    f"(()=>{{const e=document.elementFromPoint({x},{y});"
                    "return e ? e.tagName+'|'+(e.textContent||'').trim().slice(0,20) : null})()"
                ))

        _switch("/__demo__/shift-layout", {"dy": SHIFT_DY})
        with_shift = _at(cx, cy)
        _switch("/__demo__/shift-layout", {"dy": 0})
        without_shift = _at(cx, cy)
        stale = with_shift != without_shift
        print(f"{'✅' if stale else '🔴'} {'recorded coords are stale now':<28} "
              f"with={with_shift!r} without={without_shift!r}")
        results.append(stale)

        _switch("/__demo__/shift-layout", {"dy": SHIFT_DY})
        result, _ = run_with_retry(_replay(workflow, checks, base_url), attempts=1)
        results.append(_expect(f"layout shifted ({SHIFT_DY}px)", result, PASS, ""))
        _switch("/__demo__/shift-layout", {"dy": 0})

        print()
        if all(results):
            print("🎉 三态可证：改文案 → FAIL_PRODUCT，摘锚点 → FAIL_ANCHOR，原样 → PASS")
            print("🎉 回放走锚点：产物不带坐标，且位移 120px 后仍 PASS（坐标已失效）")
            return 0
        print("🔴 demo 结果与预期不符", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

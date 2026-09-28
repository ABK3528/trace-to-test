"""End-to-end: record, compile, finalize, and replay in a real browser.

The test is skipped by default because it needs browser-harness and Chrome.
Set TTT_E2E=1 to run it locally or in an opt-in CI job.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.primitives.session import Session
from target_app.serve import serve

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("TTT_E2E") != "1",
    reason="needs a real browser; set TTT_E2E=1",
)


def run_demo(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "demo.run", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )


def test_two_consecutive_sessions_both_reach_the_live_target():
    with serve() as srv:
        for _ in range(2):
            with Session(srv.base_url) as session:
                session.goto("/login")
                assert session.js("location.pathname") == "/login"


def test_three_states_are_distinguishable_end_to_end():
    done = run_demo()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS" in done.stdout
    assert "FAIL_PRODUCT" in done.stdout and "anchor_drift" in done.stdout
    assert "FAIL_ANCHOR" in done.stdout and "missing" in done.stdout
    assert "layout shifted (120px)" in done.stdout


def test_the_compiled_workflow_never_carries_recorded_plaintext():
    done = run_demo("--only", "compile")
    assert done.returncode == 0, done.stdout + done.stderr
    compiled = (ROOT / "demo" / "build" / "final" / "workflow.json").read_text(encoding="utf-8")
    assert "secret" not in compiled


def test_lint_rejects_the_compiled_checks_until_expectations_are_authored():
    done = run_demo("--only", "compile")
    assert done.returncode == 0, done.stdout + done.stderr
    lint = subprocess.run(
        [sys.executable, "-m", "core.lint.checks_lint",
         str(ROOT / "demo" / "build" / "compiled" / "checks.json"),
         "--workflow", str(ROOT / "demo" / "build" / "compiled" / "workflow.json")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert lint.returncode == 1
    assert "REJECT:no_assertions" in lint.stderr

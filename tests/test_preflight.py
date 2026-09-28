from core.compile.schema import Workflow
from core.replay.preflight import (
    PreflightVerdict, preflight, run_with_retry, stamp_build,
)
from core.replay.result import FAIL_ANCHOR, PASS, STALE_TARGET, RunResult


def wf(build: str = "") -> Workflow:
    w = Workflow(id="w", title="t", target="demo", steps=())
    return stamp_build(w, build) if build else w


def test_a_healthy_target_on_the_expected_build_proceeds():
    verdict = preflight(wf("demo-build-1"), {"build": "demo-build-1", "ready": True})
    assert verdict.proceed
    # `build_unknown` also proceeds; distinguish checked-and-matching from unchecked.
    assert verdict.reason == ""


def test_a_verified_match_and_an_unchecked_build_are_distinguishable():
    """Both proceed, but the reason distinguishes unchecked from verified."""
    verified = preflight(wf("demo-build-1"), {"build": "demo-build-1", "ready": True})
    unchecked = preflight(wf(), {"build": "whatever", "ready": True})
    assert verified.proceed and unchecked.proceed
    assert unchecked.reason == "build_unknown"
    assert verified.reason != unchecked.reason


def test_a_different_build_is_stale_target_not_a_product_verdict():
    verdict = preflight(wf("demo-build-1"), {"build": "demo-build-2", "ready": True})
    assert not verdict.proceed
    assert verdict.status == STALE_TARGET
    assert verdict.reason == "build_drift"
    assert "demo-build-1" in verdict.detail and "demo-build-2" in verdict.detail


def test_an_unreachable_target_is_an_environment_problem():
    verdict = preflight(wf("demo-build-1"), ConnectionError("refused"))
    assert not verdict.proceed
    assert verdict.status == "FAIL_ENV"
    assert verdict.reason == "environment"


def test_a_target_that_is_up_but_not_ready_is_an_environment_problem():
    verdict = preflight(wf("demo-build-1"), {"build": "demo-build-1", "ready": False})
    assert not verdict.proceed
    assert verdict.status == "FAIL_ENV"
    assert verdict.reason == "not_ready"


def test_an_unknown_expected_build_skips_the_staleness_check_but_says_so():
    verdict = preflight(wf(), {"build": "whatever", "ready": True})
    assert verdict.proceed
    assert verdict.reason == "build_unknown"


def test_stamp_build_puts_the_id_into_provenance():
    assert stamp_build(wf(), "b7").source["build"] == "b7"


def test_retry_reports_a_cold_start_flake_when_the_second_run_passes():
    calls = {"n": 0}

    def run_once() -> RunResult:
        calls["n"] += 1
        return RunResult("w", PASS if calls["n"] == 2 else FAIL_ANCHOR, reason="missing")

    result, note = run_with_retry(run_once)
    assert result.ok
    assert note == "COLD_START_FLAKE"
    assert calls["n"] == 2


def test_retry_does_not_annotate_when_the_first_run_passes():
    result, note = run_with_retry(lambda: RunResult("w", PASS))
    assert result.ok and note == ""


def test_retry_reports_the_final_verdict_when_both_runs_fail():
    """The second failure is the stable result and must be returned."""
    seen: list[int] = []

    def run_once() -> RunResult:
        n = len(seen) + 1
        seen.append(n)
        return RunResult("w", FAIL_ANCHOR, reason=f"missing-attempt-{n}")

    result, note = run_with_retry(run_once)
    assert len(seen) == 2
    assert result.reason == "missing-attempt-2"
    assert note == ""


def test_verdict_proceed_is_the_only_thing_that_licenses_a_product_verdict():
    assert PreflightVerdict(status="").proceed is True
    assert PreflightVerdict(status=STALE_TARGET, reason="build_drift").proceed is False

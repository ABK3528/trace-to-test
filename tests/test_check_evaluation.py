from core.compile.anchors import ElementSnapshot
from core.compile.schema import Anchor, Check, Checks, Step, Workflow
from core.replay.engine import run
from core.replay.result import FAIL_ENV, FAIL_PRODUCT, PASS

from tests.test_replay_three_states import FakeLocator

A = Anchor(by="testid", value="item-list")


def _wf():
    return Workflow(id="w", title="t", target="demo",
                    steps=(Step(n=1, action="wait_for", anchor=A, selector="#items"),))


def _snap(text):
    return ElementSnapshot(tag="ul", role="", name="", text=text, testid="item-list")


def test_text_present_passes_when_expected_text_is_there():
    loc = FakeLocator(resolve_script={"item-list": {"count": 1, "snap": _snap("Alpha Beta Gamma")}})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="Beta", source="manual:note")])
    assert run(_wf(), loc, checks).status == PASS


def test_text_present_fails_with_the_actual_text_recorded():
    loc = FakeLocator(resolve_script={"item-list": {"count": 1, "snap": _snap("Alpha")}})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="Beta", source="manual:note")])
    result = run(_wf(), loc, checks)
    assert result.status == FAIL_PRODUCT
    assert result.checks[0].actual == "Alpha"


def test_count_check_compares_the_number_of_matches():
    loc = FakeLocator(resolve_script={"item-list": {"count": 3, "snap": None}})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=A, expect="3", source="fixture:seed")])
    assert run(_wf(), loc, checks).status == PASS


def test_checks_at_a_later_step_do_not_run_when_an_earlier_step_fails():
    wf = Workflow(id="w", title="t", target="demo", steps=(
        Step(n=1, action="click", anchor=Anchor(by="testid", value="gone")),
        Step(n=2, action="wait_for", anchor=A, selector="#items"),
    ))
    loc = FakeLocator(resolve_script={"gone": {"count": 0, "snap": None, "drift": ""}})
    checks = Checks(workflow="w", checks=[Check(id="c2", after_step=2, kind="count",
                                                anchor=A, expect="3", source="fixture:seed")])
    result = run(wf, loc, checks)
    assert result.checks == ()
    assert loc.resolved == ["gone"]


def test_check_resolution_error_is_reported_as_environment_failure():
    loc = FakeLocator(raise_on={"resolve"})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=A, expect="1", source="fixture:seed")])
    result = run(_wf(), loc, checks)
    assert result.status == FAIL_ENV
    assert result.reason == "environment"
    assert result.checks == ()
    assert result.steps[0].status == "ok"
    assert loc.calls == ["wait:#items"]  # step completed before the check's resolve failed
    assert loc.resolved == []


def test_fill_rejects_plaintext_value_ref():
    wf = Workflow(id="w", title="t", target="demo", steps=(
        Step(n=1, action="fill", selector="#password", text="recorded-secret"),
    ))
    result = run(wf, FakeLocator())
    assert result.status == FAIL_ENV
    assert result.reason == "environment"


def test_fill_rejects_missing_environment_variable(monkeypatch):
    monkeypatch.delenv("TRACE_TO_TEST_MISSING", raising=False)
    wf = Workflow(id="w", title="t", target="demo", steps=(
        Step(n=1, action="fill", selector="#username", value_ref="env:TRACE_TO_TEST_MISSING"),
    ))
    result = run(wf, FakeLocator())
    assert result.status == FAIL_ENV
    assert result.reason == "environment"


def test_fill_uses_value_from_environment(monkeypatch):
    monkeypatch.setenv("TRACE_TO_TEST_USERNAME", "configured-user")
    wf = Workflow(id="w", title="t", target="demo", steps=(
        Step(n=1, action="fill", selector="#username", value_ref="env:TRACE_TO_TEST_USERNAME"),
    ))
    loc = FakeLocator()
    result = run(wf, loc)
    assert result.status == PASS
    assert loc.calls == ["fill:#username=configured-user"]

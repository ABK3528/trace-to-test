from core.compile.anchors import ElementSnapshot
from core.compile.schema import Anchor, Check, Checks, Step, Workflow
from core.replay.engine import run
from core.replay.result import FAIL_PRODUCT, PASS

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

from core.compile.schema import Anchor, Check, Checks, Step, Workflow
from core.lint.checks_lint import (
    REJECT_MISSING_SOURCE, REJECT_NO_ASSERTIONS, REJECT_OBSERVED_SOURCE, WARN_XY_FALLBACK, lint,
)

A = Anchor(by="testid", value="item-list")
WF = Workflow(id="w", title="t", target="demo",
              steps=(Step(n=1, action="click", anchor=A),))


def test_a_workflow_with_no_assertions_is_rejected():
    violations = lint(Checks(workflow="w", checks=()), WF)
    assert REJECT_NO_ASSERTIONS in violations[0]


def test_a_check_without_a_source_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="x", source="")])
    assert any(REJECT_MISSING_SOURCE in v for v in lint(checks, WF))


def test_a_check_whose_source_is_the_compile_time_observation_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="x", source="observed:whatever")])
    assert any(REJECT_OBSERVED_SOURCE in v for v in lint(checks, WF))


def test_a_well_sourced_check_passes():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="x", source="prd:demo#items")])
    assert lint(checks, WF) == ()


def test_fixture_and_manual_sources_are_accepted():
    for source in ("fixture:seed", "manual:reviewed-by-human"):
        checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                    anchor=A, expect="3", source=source)])
        assert lint(checks, WF) == ()


def test_an_xy_fallback_anchor_is_a_warning_not_a_rejection():
    wf = Workflow(id="w", title="t", target="demo",
                  steps=(Step(n=1, action="click", anchor=Anchor(by="xy", value="1,2", fallback=True)),))
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=A, expect="3", source="prd:x")])
    warnings = [v for v in lint(checks, wf) if WARN_XY_FALLBACK in v]
    assert warnings and all(v.startswith("WARN") for v in warnings)


def test_a_check_referring_to_a_step_that_does_not_exist_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=99, kind="count",
                                                anchor=A, expect="3", source="prd:x")])
    assert any("after_step" in v for v in lint(checks, WF))


def test_a_check_anchored_nowhere_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=None, expect="3", source="prd:x")])
    assert any("anchor" in v for v in lint(checks, WF))

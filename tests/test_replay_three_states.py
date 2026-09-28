from core.compile.anchors import ElementSnapshot
from core.compile.schema import Anchor, Step, Workflow
from core.replay.engine import run
from core.replay.result import FAIL_ANCHOR, FAIL_ENV, FAIL_PRODUCT, PASS


class FakeLocator:
    """按脚本演戏的定位器：resolve_script[anchor.value] 决定这次解析结果。"""

    def __init__(self, resolve_script=None, raise_on=None):
        self.resolve_script = resolve_script or {}
        self.raise_on = raise_on or set()
        self.calls: list[str] = []
        self.resolved: list[str] = []

    def _maybe_raise(self, name):
        if name in self.raise_on:
            raise RuntimeError(f"boom: {name}")

    def goto(self, path):
        self._maybe_raise("goto")
        self.calls.append(f"goto:{path}")

    def click_xy(self, x, y):
        self.calls.append(f"click:{x},{y}")

    def click_at_anchor(self, anchor):
        """Record the protocol path; without this stub every anchor click becomes FAIL_ENV."""
        self.calls.append(f"click@{anchor.by}:{anchor.value or anchor.name}")

    def fill(self, selector, text):
        # Record the actual value so tests can pin that env data, not recorded plaintext, was used.
        self.calls.append(f"fill:{selector}={text}")

    def press(self, key):
        self.calls.append(f"press:{key}")

    def wait_for(self, selector, state="visible"):
        self._maybe_raise("wait_for")
        self.calls.append(f"wait:{selector}")

    def js(self, expr):
        return None

    def resolve(self, anchor):
        self._maybe_raise("resolve")
        key = anchor.value or anchor.name
        self.resolved.append(key)
        return self.resolve_script.get(key, {"count": 1, "snap": None, "drift": ""})

    def snapshot_at(self, x, y):
        return None

    def snapshot_focused(self):
        return None


def _wf(*steps) -> Workflow:
    return Workflow(id="wf-test", title="t", target="demo", steps=steps)


A_TEXT = Anchor(by="text", value="新建", copy_sensitive=True)
A_TESTID = Anchor(by="testid", value="create-dialog")


def test_all_steps_resolve_means_pass():
    wf = _wf(Step(n=1, action="goto", path="/list"),
             Step(n=2, action="click", anchor=A_TESTID))
    locator = FakeLocator()
    result = run(wf, locator)
    assert result.status == PASS
    assert result.ok
    assert locator.calls == ["goto:/list", "click@testid:create-dialog"]


def test_anchor_found_but_check_fails_is_a_product_failure():
    wf = _wf(Step(n=1, action="wait_for", anchor=A_TESTID, selector="#x"))
    from core.compile.schema import Check, Checks
    checks = Checks(workflow="wf-test", checks=[
        Check(id="c1", after_step=1, kind="text_present", anchor=A_TESTID,
              expect="Create a new item?", source="prd:demo#1"),
    ])
    locator = FakeLocator(resolve_script={
        "create-dialog": {"count": 1, "snap": ElementSnapshot(tag="dialog", role="", name="", text="已改文案", testid="create-dialog"), "drift": ""},
    })
    result = run(wf, locator, checks)
    assert result.status == FAIL_PRODUCT
    assert result.reason == "assertion"


def test_anchor_missing_with_a_drift_candidate_is_a_product_failure():
    wf = _wf(Step(n=1, action="click", anchor=A_TEXT))
    locator = FakeLocator(resolve_script={
        "新建": {"count": 0, "snap": None, "drift": "立即新建"},
    })
    result = run(wf, locator)
    assert result.status == FAIL_PRODUCT
    assert result.reason == "anchor_drift"
    assert result.steps[-1].drift == "立即新建"


def test_anchor_missing_with_no_drift_candidate_is_a_script_problem():
    wf = _wf(Step(n=1, action="click", anchor=A_TESTID))
    locator = FakeLocator(resolve_script={"create-dialog": {"count": 0, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert result.status == FAIL_ANCHOR
    assert result.reason == "missing"


def test_an_ambiguous_anchor_is_a_script_problem():
    wf = _wf(Step(n=1, action="click", anchor=A_TEXT))
    locator = FakeLocator(resolve_script={"新建": {"count": 3, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert result.status == FAIL_ANCHOR
    assert result.reason == "ambiguous"


def test_an_environment_error_that_blocks_the_wait_is_not_a_product_verdict():
    wf = _wf(Step(n=1, action="wait_for", anchor=A_TESTID, selector="#items"))
    locator = FakeLocator(raise_on={"wait_for"})
    result = run(wf, locator)
    assert result.status == FAIL_ENV
    assert result.reason == "environment"


def test_execution_stops_at_the_first_failing_step():
    wf = _wf(Step(n=1, action="click", anchor=Anchor(by="testid", value="gone")),
             Step(n=2, action="click", anchor=Anchor(by="testid", value="never")))
    locator = FakeLocator(resolve_script={"gone": {"count": 0, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert len(result.steps) == 1
    assert result.steps[0].status == "anchor_missing"
    assert locator.calls == []
    assert locator.resolved == ["gone"]



def test_a_click_with_both_an_anchor_and_coordinates_dispatches_through_the_anchor():
    wf = _wf(Step(n=1, action="click", anchor=A_TESTID, xy=(10, 20)))
    locator = FakeLocator()
    result = run(wf, locator)
    assert result.status == PASS
    assert locator.calls == ["click@testid:create-dialog"]
    assert "click:10,20" not in locator.calls


def test_a_coordinate_only_click_still_uses_coordinates():
    wf = _wf(Step(n=1, action="click", xy=(10, 20)))
    locator = FakeLocator()
    result = run(wf, locator)
    assert result.status == PASS
    assert locator.calls == ["click:10,20"]


def test_a_click_with_neither_anchor_nor_coordinates_is_an_environment_failure():
    wf = _wf(Step(n=1, action="click"))
    locator = FakeLocator()
    result = run(wf, locator)
    assert result.status == FAIL_ENV
    assert result.reason == "environment"
    assert locator.calls == []


def test_xy_fallback_targets_are_reported_as_warnings_not_failures():
    wf = _wf(Step(n=1, action="click", anchor=Anchor(by="xy", value="10,20", fallback=True)))
    locator = FakeLocator(resolve_script={"10,20": {"count": 1, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert result.status == PASS
    assert result.steps[0].status == "ok"

    wf = _wf(Step(n=1, action="click", anchor=Anchor(by="xy", value="10,20", fallback=True)))
    locator = FakeLocator(resolve_script={"10,20": {"count": 1, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert result.status == PASS
    assert result.steps[0].status == "ok"

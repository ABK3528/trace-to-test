"""步骤执行引擎 —— 两种模式共用一套动作派发。

assert 模式：按锚点定位，跑断言，产出三态。
probe  模式：动作执行**之前**抓一份元素快照，供编译器反解锚点（spec §4.2 鸿沟一）。

两种模式共用 _perform()，保证"编译时怎么走"和"回放时怎么走"是同一条路 ——
否则编译出来的步骤在回放时可能根本走不通。
"""
from __future__ import annotations

import os
from typing import Mapping, Protocol

from ..compile.anchors import ElementSnapshot
from ..compile.schema import Checks, Step, Workflow
from .result import FAIL_ANCHOR, FAIL_ENV, FAIL_PRODUCT, PASS, CheckOutcome, RunResult, StepOutcome


class Locator(Protocol):
    def goto(self, path: str) -> None: ...
    def click_xy(self, x: int, y: int) -> None: ...
    def click_at_anchor(self, anchor) -> None: ...
    def fill(self, selector: str, text: str) -> None: ...
    def press(self, key: str) -> None: ...
    def wait_for(self, selector: str, state: str = "visible") -> None: ...
    def js(self, expression: str): ...
    def resolve(self, anchor) -> dict: ...
    def snapshot_at(self, x: int, y: int) -> ElementSnapshot | None: ...
    def snapshot_focused(self) -> ElementSnapshot | None: ...


def _perform(step: Step, locator: Locator, *, replay_value: str | None = None) -> None:
    """把一步变成对 locator 的调用。两种模式共用。"""
    if step.action == "goto":
        locator.goto(step.path)
    elif step.action == "click":
        if step.anchor is not None:
            locator.click_at_anchor(step.anchor)
        elif step.xy is not None:
            locator.click_xy(*step.xy)
        else:
            raise ValueError(f"step {step.n}: click needs either an anchor or coordinates")
    elif step.action == "fill":
        value = replay_value if replay_value is not None else _value_of(step)
        locator.fill(step.selector, value)
    elif step.action == "press":
        locator.press(step.key)
    elif step.action == "wait_for":
        locator.wait_for(step.selector, step.state)
    elif step.action == "wait_network_idle":
        locator.js("void 0")
    else:
        raise ValueError(f"unknown action {step.action!r}")


def _value_of(step: Step) -> str:
    """只有 value_ref 是 env:<VAR> 时才取环境变量；明文值一律拒绝。

    录制的 fill_input 带的是当时的明文（可能是密码），绝不能进 workflow。
    """
    if not step.value_ref.startswith("env:"):
        raise ValueError(f"step {step.n}: fill requires value_ref=env:<VAR>, got {step.value_ref!r}")

    name = step.value_ref[4:]
    if name not in os.environ:
        raise KeyError(f"step {step.n}: environment variable {name!r} is not set")
    return os.environ[name]


def run(workflow: Workflow, locator: Locator, checks: Checks | None = None) -> RunResult:
    """回放一条 workflow。遇到第一个非 ok 的步骤就停 —— 后面的步骤结果不可信。"""
    outcomes: list[StepOutcome] = []
    check_outcomes: list[CheckOutcome] = []
    by_step: dict[int, list] = {}
    for check in (checks.checks if checks else ()):
        by_step.setdefault(check.after_step, []).append(check)

    for step in workflow.steps:
        try:
            outcome = _assert_step(step, locator)
        except Exception as exc:  # 环境级问题：不是产品结论
            outcomes.append(StepOutcome(step=step, status="error", message=str(exc)))
            return RunResult(workflow.id, FAIL_ENV, reason="environment", steps=tuple(outcomes))

        outcomes.append(outcome)
        if outcome.status != "ok":
            status, reason = _classify(outcome)
            return RunResult(workflow.id, status, reason=reason, steps=tuple(outcomes))

        for check in by_step.get(step.n, []):
            try:
                check_outcome = _evaluate(check, locator)
            except Exception:
                # Check evaluation can fail because the environment or page is not ready.
                return RunResult(workflow.id, FAIL_ENV, reason="environment",
                                 steps=tuple(outcomes), checks=tuple(check_outcomes))
            check_outcomes.append(check_outcome)
            if not check_outcome.ok:
                return RunResult(workflow.id, FAIL_PRODUCT, reason="assertion",
                                 steps=tuple(outcomes), checks=tuple(check_outcomes))

    return RunResult(workflow.id, PASS, steps=tuple(outcomes), checks=tuple(check_outcomes))


def _assert_step(step: Step, locator: Locator) -> StepOutcome:
    if step.action in ("goto", "wait_for", "wait_network_idle"):
        _perform(step, locator)
        return StepOutcome(step=step, status="ok")

    if step.anchor is None:
        _perform(step, locator)
        return StepOutcome(step=step, status="ok")

    got = locator.resolve(step.anchor)
    count, snapshot, drift = got.get("count", 0), got.get("snap"), got.get("drift", "")
    if count == 1:
        _perform(step, locator)
        return StepOutcome(step=step, status="ok", snapshot=snapshot)
    if count > 1:
        return StepOutcome(step=step, status="anchor_ambiguous",
                           message=f"anchor matched {count} elements")
    if drift:
        return StepOutcome(step=step, status="anchor_drift", drift=drift,
                           message=f"{step.anchor.by} anchor not found; nearest is {drift!r}")
    return StepOutcome(step=step, status="anchor_missing",
                       message=f"{step.anchor.by} anchor {step.anchor.value or step.anchor.name!r} not found")


def _classify(outcome: StepOutcome) -> tuple[str, str]:
    if outcome.status == "anchor_drift":
        return FAIL_PRODUCT, "anchor_drift"
    if outcome.status == "anchor_ambiguous":
        return FAIL_ANCHOR, "ambiguous"
    return FAIL_ANCHOR, "missing"


def _evaluate(check, locator: Locator) -> CheckOutcome:
    got = locator.resolve(check.anchor) if check.anchor else {"count": 0, "snap": None}
    snapshot = got.get("snap")
    if check.kind == "count":
        actual = str(got.get("count", 0))
        ok = actual == str(check.expect)
        return CheckOutcome(check=check, ok=ok, actual=actual,
                            message="" if ok else f"expected count {check.expect}, got {actual}")
    if check.kind == "text_present":
        text = (snapshot.text if snapshot else "") or ""
        ok = check.expect in text
        return CheckOutcome(check=check, ok=ok, actual=text[:200],
                            message="" if ok else f"expected text {check.expect!r} not in {text[:80]!r}")
    raise ValueError(f"unknown check kind {check.kind!r}")


def probe(
    workflow: Workflow,
    locator: Locator,
    *,
    replay_values: Mapping[int, str] | None = None,
) -> tuple[tuple[Step, ElementSnapshot | None], ...]:
    """编译期模式：走一遍步骤，在每个需要锚点的动作**之前**抓元素快照。

    返回 ((step, snapshot|None), ...)，顺序与 workflow.steps 一致。
    """
    replay_values = replay_values or {}
    outcomes: list[tuple[Step, ElementSnapshot | None]] = []
    for step in workflow.steps:
        snapshot = None
        if step.action == "click" and step.xy:
            snapshot = locator.snapshot_at(*step.xy)
        elif step.action == "press":
            snapshot = locator.snapshot_focused()
        outcomes.append((step, snapshot))
        _perform(step, locator, replay_value=replay_values.get(step.n))
    return tuple(outcomes)

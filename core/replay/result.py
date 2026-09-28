"""回放结果模型：三态 + reason，以及"本次未得出结论"的标注。

三态只有 PASS / FAIL_PRODUCT / FAIL_ANCHOR（spec §4.2）。
FAIL_ENV 与 STALE_TARGET 是"本次未得出结论"，由 preflight 产生，
不构成第四态 —— 它们表示"现在还不能下判"。
"""
from __future__ import annotations

from dataclasses import dataclass

PASS = "PASS"
FAIL_PRODUCT = "FAIL_PRODUCT"
FAIL_ANCHOR = "FAIL_ANCHOR"
FAIL_ENV = "FAIL_ENV"
STALE_TARGET = "STALE_TARGET"

# 产品结论只可能是这两个之一；其余都不是结论。
PRODUCT_VERDICTS = (PASS, FAIL_PRODUCT, FAIL_ANCHOR)


@dataclass(frozen=True)
class StepOutcome:
    step: object                    # core.compile.schema.Step
    status: str                     # ok | anchor_missing | anchor_ambiguous | anchor_drift | error
    snapshot: object | None = None  # core.compile.anchors.ElementSnapshot
    drift: str = ""
    message: str = ""


@dataclass(frozen=True)
class CheckOutcome:
    check: object                   # core.compile.schema.Check
    ok: bool
    actual: str = ""
    message: str = ""


@dataclass(frozen=True)
class RunResult:
    workflow_id: str
    status: str
    reason: str = ""
    steps: tuple[StepOutcome, ...] = ()
    checks: tuple[CheckOutcome, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def summary(self) -> str:
        head = f"{self.status}" + (f" ({self.reason})" if self.reason else "")
        return f"{self.workflow_id}: {head} [steps={len(self.steps)} checks={len(self.checks)}]"

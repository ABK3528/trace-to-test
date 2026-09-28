"""Turn a compiled draft into a replayable workflow and authored checks.

Only two human-supplied pieces are added here: environment references for input
values and sources for assertions. Expected values belong in answers.json from
an external requirement source, never inferred from compiler observations.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from core.compile.schema import Anchor, Check, Checks, Step, Workflow

SPEC_REF = "spec:demo/spec.md"


def finalize(compiled_dir: Path, answers: dict) -> tuple[Workflow, Checks]:
    compiled_dir = Path(compiled_dir)
    workflow = Workflow.from_json(json.loads((compiled_dir / "workflow.json").read_text(encoding="utf-8")))

    value_refs: dict[str, str] = answers.get("value_refs", {})
    steps: list[Step] = []
    for step in workflow.steps:
        if step.action == "fill" and not step.value_ref:
            ref = value_refs.get(step.selector)
            if not ref:
                raise ValueError(f"answers.json 缺 {step.selector!r} 的 value_ref")
            step = replace(step, value_ref=ref)
        steps.append(step)
    workflow = replace(workflow, steps=tuple(steps))

    checks = Checks(
        workflow=workflow.id,
        checks=tuple(
            Check(
                id=c["id"], after_step=c["after_step"], kind=c["kind"],
                # Each assertion owns its anchor; it must not borrow a step's locator.
                anchor=Anchor.from_json(c["anchor"]),
                expect=c["expect"], source=c["source"],
            )
            for c in answers["checks"]
        ),
    )
    return workflow, checks


def write_final(workflow: Workflow, checks: Checks, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "workflow.json").write_text(
        json.dumps(workflow.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "checks.json").write_text(
        json.dumps(checks.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")

"""Reject assertions whose expected values lack an external source."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..compile.schema import Checks, Workflow

REJECT_NO_ASSERTIONS = "REJECT:no_assertions"
REJECT_MISSING_SOURCE = "REJECT:missing_source"
REJECT_OBSERVED_SOURCE = "REJECT:observed_source"
WARN_XY_FALLBACK = "WARN:xy_fallback"

_ACCEPTED_SOURCE_PREFIXES = ("prd:", "fixture:", "manual:", "issue:", "spec:")


def lint(checks: Checks, workflow: Workflow | None = None) -> tuple[str, ...]:
    violations: list[str] = []

    if not checks.checks:
        violations.append(
            f"{REJECT_NO_ASSERTIONS} — workflow {checks.workflow!r} has no assertions; "
            "compiled output must be given expectations by a person before use"
        )

    valid_steps = {step.n for step in workflow.steps} if workflow else None
    for check in checks.checks:
        where = f"check {check.id!r}"

        if not check.source:
            violations.append(
                f"{REJECT_MISSING_SOURCE} — {where} has no source; "
                "expected values must come from an external document, fixture, or manual entry"
            )
        elif check.source.startswith("observed:"):
            violations.append(
                f"{REJECT_OBSERVED_SOURCE} — {where} uses a compile-time observation as its source; "
                "this would lock the observed state as the expectation"
            )
        elif not check.source.startswith(_ACCEPTED_SOURCE_PREFIXES):
            violations.append(
                f"{REJECT_MISSING_SOURCE} — {where} source {check.source!r} does not use an accepted prefix "
                f"{_ACCEPTED_SOURCE_PREFIXES}"
            )

        if check.anchor is None:
            violations.append(f"{REJECT_MISSING_SOURCE} — {where} has no anchor to locate")
        elif check.anchor.by == "xy":
            violations.append(
                f"{WARN_XY_FALLBACK} — {where} uses coordinate-based location, which is resolution-dependent"
            )

        if valid_steps is not None and check.after_step not in valid_steps:
            violations.append(
                f"{REJECT_MISSING_SOURCE} — {where} after_step={check.after_step} "
                f"is not in workflow steps {sorted(valid_steps)}"
            )

    if workflow:
        for step in workflow.steps:
            if step.anchor and step.anchor.by == "xy":
                violations.append(
                    f"{WARN_XY_FALLBACK} — step {step.n} uses coordinate-based fallback location"
                )
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="checks_lint")
    parser.add_argument("checks", type=Path)
    parser.add_argument("--workflow", type=Path, default=None)
    args = parser.parse_args(argv)

    checks = Checks.from_json(json.loads(args.checks.read_text(encoding="utf-8")))
    workflow = (
        Workflow.from_json(json.loads(args.workflow.read_text(encoding="utf-8")))
        if args.workflow
        else None
    )

    violations = lint(checks, workflow)
    rejects = [violation for violation in violations if violation.startswith("REJECT")]
    warnings = [violation for violation in violations if violation.startswith("WARN")]

    for warning in warnings:
        print(warning)
    for rejection in rejects:
        print(rejection, file=sys.stderr)
    if rejects:
        return 1
    print("checks lint passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

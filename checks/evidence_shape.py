"""Mechanically check the shape of recorded evidence without judging meaning."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Approximate a concrete value with a digit, assignment, quoted value, or parenthesized value.
_CONCRETE = re.compile(r"\d|=\s*\S|\"[^\"]+\"|'[^']+'|`[^`]+`")
# This detects a negative-control note; a person must still judge whether it is meaningful.
_NEGATIVE_CONTROL = re.compile(r"负控|negative control|would fail|必红")
_EMBEDDED_IMAGE = re.compile(r"!\[[^\]]*\]\(https?://[^)]+\)")
_VAGUE = ("符合预期", "一切正常", "无异常", "pass", "ok", "as expected")


def _is_concrete(actual: str) -> bool:
    text = (actual or "").strip()
    if not text:
        return False
    if text.lower() in _VAGUE:
        return False
    return bool(_CONCRETE.search(text))


def lint_results(records: list[dict]) -> tuple[str, ...]:
    violations: list[str] = []
    for record in records:
        tc = record.get("tc") or "<unnamed>"
        status = record.get("status") or ""
        actual = record.get("actual_result") or ""
        screenshots = record.get("screenshots") or []
        lane = record.get("lane") or "api"

        if status == "pending":
            violations.append(f"{tc}: still pending — the run did not finish")
            continue

        if status == "passed":
            if not _is_concrete(actual):
                violations.append(f"{tc}: passed but actual_result carries no concrete value")
            if not _NEGATIVE_CONTROL.search(actual):
                violations.append(f"{tc}: passed but states no negative control")
            if lane == "ui" and not screenshots:
                violations.append(f"{tc}: ui pass without a screenshot")

        if status == "failed":
            if not record.get("bug"):
                violations.append(f"{tc}: failed without a bug id")
            if lane == "ui":
                body = " ".join(str(path) for path in screenshots) + " " + str(record.get("bug_body") or "")
                if not _EMBEDDED_IMAGE.search(body):
                    violations.append(
                        f"{tc}: ui failure needs a screenshot embedded in the bug, "
                        "not just a local path"
                    )

        if status == "blocked":
            if not re.search(r"解除|unblock|需要|missing|blocked by", actual):
                violations.append(f"{tc}: blocked without saying what would unblock it")
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_shape")
    parser.add_argument("results", type=Path, help="JSONL, one result per line")
    args = parser.parse_args(argv)

    records = [
        json.loads(line)
        for line in args.results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    violations = lint_results(records)
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        return 1
    print(f"evidence shape passed ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

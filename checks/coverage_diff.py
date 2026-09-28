"""Gate 1: bidirectional case-list vs results diff, plus six-count self-consistency.

Use the **case list written down before execution** as the baseline and diff it
against the results read back, in both directions:

  - in the case list but not written back → missed (the run skipped it)
  - written back but absent from the case list → the baseline and the results are
    out of step (did the snapshot change?), so stop and reconcile before writing on
  - `pending` must be zero; when it is not, name each offending case individually
  - the six counts must sum to `total`

The six counts are passed, failed, blocked, skipped, pending, missed. Every case in
the baseline is either written back under one of the five statuses or missed, so the
six sum to `total` (= number of baseline cases) by construction — unless an extra
result or an unknown status slips in. The check is belt-and-suspenders, not the
primary diagnostic.

🔴 This script does **counting and set arithmetic only**; it cannot judge meaning,
   which is exactly why it is mechanizable. "Is the evidence good enough" lives in
   `evidence_shape`; the heaviest part of the review belongs to a person.

Input:
  --cases    case-list JSONL, one {"tc": str, ...} per line
  --results  results JSONL, one {"tc": str, "status": "passed"|"failed"|"blocked"|"skipped"|"pending", ...} per line
Output: violations go to stderr; exit 0 = clean / 1 = any violation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STATUSES = ("passed", "failed", "blocked", "skipped", "pending")


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def lint_coverage(cases: list[dict], results: list[dict]) -> tuple[str, ...]:
    """Return violations; an empty tuple means the gate passed."""
    violations: list[str] = []

    if not cases:
        violations.append("the case list is empty — nothing ran; refusing to pass vacuously")
    if not results:
        violations.append("the results list is empty — nothing ran; refusing to pass vacuously")

    baseline = {str(c.get("tc") or "") for c in cases}
    wrote = {str(r.get("tc") or "") for r in results}

    missed = sorted(tc for tc in baseline - wrote if tc)
    extra = sorted(tc for tc in wrote - baseline if tc)
    for tc in missed:
        violations.append(f"{tc}: in the case list but never written back — missed")
    for tc in extra:
        violations.append(
            f"{tc}: written back but absent from the case list — "
            "baseline and results are out of step; stop and reconcile before writing on"
        )

    counts = {status: 0 for status in STATUSES}
    for r in results:
        tc = str(r.get("tc") or "<unnamed>")
        status = str(r.get("status") or "")
        if status in counts:
            counts[status] += 1
        else:
            violations.append(f"{tc}: unknown status {status!r}")

    for r in results:
        if str(r.get("status") or "") == "pending":
            tc = str(r.get("tc") or "<unnamed>")
            violations.append(f"{tc}: still pending — the run did not finish")

    total = len(cases)
    six = sum(counts.values()) + len(missed)
    if six != total:
        violations.append(
            f"counts do not sum to total: passed={counts['passed']} failed={counts['failed']} "
            f"blocked={counts['blocked']} skipped={counts['skipped']} pending={counts['pending']} "
            f"missed={len(missed)} → six sum {six} != total {total}"
        )
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coverage_diff")
    parser.add_argument("--cases", type=Path, required=True, help="case-list JSONL (baseline)")
    parser.add_argument("--results", type=Path, required=True, help="results JSONL (read back)")
    args = parser.parse_args(argv)

    cases = _load(args.cases)
    results = _load(args.results)
    violations = lint_coverage(cases, results)
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        return 1
    print(f"coverage diff passed ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

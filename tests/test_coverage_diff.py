"""Gate 1 tests: each violation class must be able to fail on its own.

The non-vacuity guard (empty inputs are an error, not a pass) is a separate test
because "nothing ran" must never read as green.
"""
from checks.coverage_diff import lint_coverage


def _case(tc: str) -> dict:
    return {"tc": tc}


def _result(tc: str, status: str) -> dict:
    return {"tc": tc, "status": status}


def _six(tc: str, status: str) -> list[dict]:
    """A full set of results with exactly one case under `status`, no misses, no extras."""
    cases = [_case(f"TC-{i}") for i in range(1, 7)]
    results = []
    for c in cases:
        s = status if c["tc"] == tc else "passed"
        results.append(_result(c["tc"], s))
    return cases, results


def test_clean_pass_produces_no_violations():
    cases, results = _six("TC-3", "passed")
    assert lint_coverage(cases, results) == ()


def test_a_case_in_the_list_but_not_in_the_results_is_a_missed_case():
    cases, results = _six("TC-3", "passed")
    cases.append(_case("TC-7"))
    violations = lint_coverage(cases, results)
    assert any("TC-7" in v and "missed" in v for v in violations)


def test_a_result_without_a_case_in_the_list_is_an_extra_result():
    cases, results = _six("TC-3", "passed")
    results.append(_result("TC-99", "passed"))
    violations = lint_coverage(cases, results)
    assert any("TC-99" in v and "out of step" in v for v in violations)


def test_a_pending_case_is_a_violation():
    cases, results = _six("TC-3", "passed")
    results.append(_result("TC-4", "pending"))
    violations = lint_coverage(cases, results)
    assert any("TC-4" in v and "pending" in v for v in violations)


def test_counts_that_do_not_sum_to_total_are_a_violation():
    # Two baseline cases; an extra written result with a recognized status pushes
    # six past total. (This also flags the extra result separately.)
    cases = [_case("TC-1"), _case("TC-2")]
    results = [
        _result("TC-1", "passed"),
        _result("TC-2", "passed"),
        _result("TC-99", "failed"),
    ]
    violations = lint_coverage(cases, results)
    assert any("do not sum to total" in v for v in violations)


def test_an_unknown_status_is_a_violation():
    cases, results = _six("TC-3", "passed")
    results.append(_result("TC-3", "in_progress"))
    violations = lint_coverage(cases, results)
    assert any("unknown status" in v for v in violations)


def test_empty_inputs_are_an_error_not_a_pass():
    violations = lint_coverage([], [])
    assert any("case list is empty" in v for v in violations)
    assert any("results list is empty" in v for v in violations)


def test_empty_results_with_cases_is_still_an_error():
    violations = lint_coverage([_case("TC-1")], [])
    assert any("results list is empty" in v for v in violations)
    assert any("TC-1" in v and "missed" in v for v in violations)

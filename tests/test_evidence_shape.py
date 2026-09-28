from checks.evidence_shape import lint_results


def rec(**over) -> dict:
    base = dict(tc="TC-1", status="passed", actual_result="", screenshots=[],
                bug=None, bug_body="", lane="api")
    base.update(over)
    return base


def test_a_passed_case_with_a_concrete_value_is_not_flagged_for_a_missing_value():
    violations = lint_results([rec(actual_result="HTTP 200, balance=12.34")])
    assert not any("no concrete value" in v for v in violations)
    assert any("negative control" in v for v in violations)


def test_a_passed_case_that_only_says_it_matched_expectations_is_rejected():
    violations = lint_results([rec(actual_result="符合预期")])
    assert any("no concrete value" in v for v in violations)


def test_a_passed_case_with_no_negative_control_note_is_rejected():
    violations = lint_results([rec(actual_result="HTTP 200")])
    assert any("negative control" in v for v in violations)


def test_a_passed_case_with_a_negative_control_note_is_accepted():
    assert lint_results([
        rec(actual_result="HTTP 200, balance=12.34；负控：把 amount 换 0 本条必红")
    ]) == ()


def test_a_ui_pass_without_a_screenshot_is_rejected():
    violations = lint_results([
        rec(lane="ui", actual_result="见表头 3 列；负控：删掉该列必红")
    ])
    assert any("screenshot" in v for v in violations)


def test_a_ui_pass_with_a_screenshot_is_accepted():
    assert lint_results([
        rec(lane="ui", actual_result="见表头 3 列；负控：删掉该列必红",
            screenshots=["/tmp/shots/tc1.png"])
    ]) == ()


def test_a_failed_case_without_a_bug_id_is_rejected():
    violations = lint_results([rec(status="failed", actual_result="余额少 1")])
    assert any("without a bug id" in v for v in violations)


def test_a_ui_failure_must_have_an_embedded_screenshot_not_just_a_path():
    violations = lint_results([
        rec(status="failed", lane="ui", actual_result="按钮不见了",
            bug="BUG-7", screenshots=["/tmp/shots/tc1.png"])
    ])
    assert any("embedded" in v for v in violations)


def test_a_ui_failure_with_an_embedded_image_in_the_bug_body_is_accepted():
    assert lint_results([
        rec(status="failed", lane="ui", actual_result="按钮不见了", bug="BUG-7",
            screenshots=[], bug_body="见下图：![](https://example.com/uploads/abc.png)")
    ]) == ()


def test_a_ui_failure_with_the_image_only_in_the_screenshots_field_is_rejected():
    violations = lint_results([
        rec(status="failed", lane="ui", actual_result="按钮不见了", bug="BUG-7",
            screenshots=["![](https://example.com/uploads/abc.png)"], bug_body="")
    ])
    assert any("embedded" in v for v in violations)


def test_a_blocked_case_must_say_what_unblocks_it():
    violations = lint_results([rec(status="blocked", actual_result="缺账号")])
    assert any("unblock" in v for v in violations)


def test_a_pending_case_is_always_a_violation_because_the_run_is_incomplete():
    violations = lint_results([rec(status="pending")])
    assert any("pending" in v for v in violations)

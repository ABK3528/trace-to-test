from core.compile.schema import Anchor, Check, Checks


def test_check_round_trips_and_keeps_source():
    check = Check(id="c1", after_step=1, kind="count", anchor=Anchor(by="testid", value="x"),
                  expect="3", source="spec:demo/spec.md#2", observed_at_compile="3")
    restored = Check.from_json(check.to_json())
    assert restored == check
    assert restored.source == "spec:demo/spec.md#2"
    assert restored.observed_at_compile == "3"


def test_checks_container_round_trips():
    container = Checks(workflow="w", checks=(Check(id="c1", after_step=1, kind="count",
                                                   anchor=Anchor(by="testid", value="x"),
                                                   expect="3", source="manual:n"),))
    assert Checks.from_json(container.to_json()) == container


def test_checks_with_no_assertions_round_trips():
    assert Checks.from_json(Checks(workflow="w").to_json()) == Checks(workflow="w")

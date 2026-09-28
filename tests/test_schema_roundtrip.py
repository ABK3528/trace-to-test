import pytest

from core.compile.schema import Anchor, Step, Unresolved, Workflow


def test_anchor_round_trips_including_the_flags():
    anchor = Anchor(by="text", value="新建", copy_sensitive=True)
    assert Anchor.from_json(anchor.to_json()) == anchor


def test_xy_fallback_flag_survives_the_round_trip():
    anchor = Anchor(by="xy", value="10,20", fallback=True)
    assert Anchor.from_json(anchor.to_json()).fallback is True


def test_step_round_trips_including_xy():
    step = Step(n=2, action="click", xy=(120, 168), anchor=Anchor(by="testid", value="b"))
    restored = Step.from_json(step.to_json())
    assert restored.xy == (120, 168)
    assert restored.anchor == step.anchor
    assert restored == step


def test_step_without_xy_round_trips():
    assert Step.from_json(Step(n=1, action="goto", path="/login").to_json()).xy is None


def test_workflow_round_trips():
    wf = Workflow(id="w", title="t", target="demo",
                  source={"recording": "r"},
                  steps=(Step(n=1, action="goto", path="/login"),))
    assert Workflow.from_json(wf.to_json()) == wf


def test_workflow_rejects_an_unknown_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        Workflow.from_json({"schema_version": 99, "id": "w", "title": "", "target": ""})


def test_unresolved_round_trips_with_its_candidates():
    item = Unresolved(seq=3, helper="click_at_xy", event={"x": 120, "y": 168},
                      candidates=(Anchor(by="text", value="新建", copy_sensitive=True),),
                      reason="no_semantic_hook")
    restored = Unresolved.from_json(item.to_json())
    assert restored == item
    assert restored.candidates[0].copy_sensitive is True


def test_unresolved_round_trips_with_no_candidates():
    item = Unresolved(seq=1, helper="type_text", event={"text": "x"},
                      reason="type_text_unsupported")
    restored = Unresolved.from_json(item.to_json())
    assert restored == item
    assert restored.candidates == ()

import json
from pathlib import Path

from core.compile.compiler import compile_recording
from core.compile.anchors import ElementSnapshot
from core.transcript.recording import load_recording

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "smoke-login"


class ScriptedLocator:
    """按坐标返回预设快照，并按步骤记录动作。"""

    def __init__(self, snaps: dict[tuple[int, int], ElementSnapshot]):
        self.snaps = snaps
        self.calls: list[str] = []

    def goto(self, path): self.calls.append(f"goto:{path}")
    def click_xy(self, x, y): self.calls.append(f"click:{x},{y}")
    def click_at_anchor(self, anchor): self.calls.append(f"click@{anchor.by}")
    def fill(self, selector, text): self.calls.append(f"fill:{selector}={text}")
    def press(self, key): self.calls.append(f"press:{key}")
    def wait_for(self, selector, state="visible"): self.calls.append(f"wait:{selector}")
    def js(self, expr): return None
    def resolve(self, anchor): return {"count": 1, "snap": None, "drift": ""}
    def snapshot_at(self, x, y): return self.snaps.get((x, y))
    def snapshot_focused(self): return None


BUTTON = ElementSnapshot(tag="button", role="button", name="新建", text="新建", testid="open-create",
                         attrs={}, path="body > button:nth-of-type(1)", rect={"x": 60, "y": 60, "w": 56, "h": 24})
DIALOG_BTN = ElementSnapshot(tag="button", role="button", name="确定", text="确定", testid="confirm-create",
                             attrs={}, path="dialog > form > button", rect={"x": 180, "y": 240, "w": 120, "h": 40})


def test_goto_steps_come_straight_from_the_url():
    result = compile_recording(load_recording(FIXTURE), target="demo",
                              locator=ScriptedLocator({}))
    first = result.workflow.steps[0]
    assert first.action == "goto"
    assert first.path == "/login"


def test_fill_steps_keep_the_selector_but_never_the_recorded_plaintext():
    result = compile_recording(load_recording(FIXTURE), target="test-target", locator=ScriptedLocator({}))
    fills = [s for s in result.workflow.steps if s.action == "fill"]
    assert fills and fills[0].selector == "#username"
    assert fills[0].value_ref == ""
    steps_json = json.dumps(result.workflow.to_json()["steps"], ensure_ascii=False)
    assert "demo" not in steps_json


def test_click_steps_get_anchors_resolved_from_the_probe():
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    clicks = [s for s in result.workflow.steps if s.action == "click"]
    assert [s.anchor.by for s in clicks] == ["testid", "testid", "testid"]
    assert clicks[0].anchor.value == "open-create"


def test_compiled_steps_keep_the_original_coordinates_for_probe_only():
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    clicks = [s for s in result.workflow.steps if s.action == "click"]
    assert all(s.xy for s in clicks)


def test_the_probe_replays_the_whole_recording_in_order():
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    assert loc.calls[0] == "goto:/login"
    assert "click:120,168" in loc.calls


def test_workflow_carries_its_provenance():
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    assert result.workflow.source["recording"] == "smoke-login"
    assert result.workflow.source["compiler"]


def test_todo_asserts_suggest_where_assertions_are_needed():
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    assert any("open-create" in line for line in result.todo_asserts)
    assert any("confirm-create" in line for line in result.todo_asserts)
    assert any("#items" in line for line in result.todo_asserts)


def test_the_probe_replays_recorded_fill_values_in_memory_only():
    """Probe must reproduce state without persisting captured plaintext."""
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="test-target", locator=loc)

    assert any(c == "fill:#username=demo" for c in loc.calls), loc.calls
    steps_json = json.dumps(result.workflow.to_json()["steps"], ensure_ascii=False)
    assert "demo" not in steps_json


def test_compiled_checks_start_empty_because_expectations_must_come_from_outside():
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    assert result.checks.checks == ()

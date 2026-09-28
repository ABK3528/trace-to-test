import json
from pathlib import Path

from core.compile.anchors import ElementSnapshot
from core.compile.compiler import compile_recording
from core.transcript.recording import TraceEvent, load_recording

from tests.test_compiler_mapping import ScriptedLocator

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "smoke-login"


def _snap(**over):
    base = dict(tag="div", role="", name="", text="", testid="", attrs={},
                path="", rect={"x": 1, "y": 2, "w": 3, "h": 4})
    base.update(over)
    return ElementSnapshot(**base)


def test_an_element_with_no_semantic_hook_becomes_unresolved_not_an_xy_anchor():
    loc = ScriptedLocator({(120, 168): _snap(), (88, 72): _snap(), (210, 260): _snap()})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    click_unresolved = [u for u in result.unresolved if u.helper == "click_at_xy"]
    assert click_unresolved
    assert all(u.reason == "no_semantic_hook" for u in click_unresolved)
    assert any(u.reason == "value_ref_required" for u in result.unresolved)
    assert all(
        any(anchor.by == "xy" and anchor.fallback for anchor in unresolved.candidates)
        for unresolved in click_unresolved
    )
    assert all(s.anchor.by != "xy" for s in result.workflow.steps if s.action == "click")


def test_unresolved_entries_carry_the_original_event_and_the_candidates():
    loc = ScriptedLocator({(120, 168): _snap(), (88, 72): _snap(), (210, 260): _snap()})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    entry = [u for u in result.unresolved if u.event.get("x") == 120][0]
    assert entry.helper == "click_at_xy"
    assert entry.event["y"] == 168
    assert any(a.by == "xy" and a.fallback for a in entry.candidates)


def test_a_path_only_element_does_get_a_path_anchor():
    only_path = _snap(path="body > div:nth-of-type(3)")
    loc = ScriptedLocator({(120, 168): only_path, (88, 72): only_path, (210, 260): only_path})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    anchors = [s.anchor.by for s in result.workflow.steps if s.action == "click"]
    assert anchors and all(by == "path" for by in anchors)
    assert not [u for u in result.unresolved if u.helper == "click_at_xy"]
    assert any(u.reason == "value_ref_required" for u in result.unresolved)


def test_a_click_that_probes_to_nothing_is_unresolved():
    loc = ScriptedLocator({})   # 任何坐标都探不到元素
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    assert any(u.reason == "probe_returned_nothing" for u in result.unresolved)


def test_type_text_is_reported_unsupported_with_a_remedy(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "meta.json").write_text('{"name":"r","title":"","started":0.0}', encoding="utf-8")
    (d / "events.jsonl").write_text(
        json.dumps({"helper": "type_text", "text": "hello", "w": 800, "h": 600}) + "\n",
        encoding="utf-8",
    )
    result = compile_recording(load_recording(d), target="demo", locator=ScriptedLocator({}))
    assert any(u.reason == "type_text_unsupported" for u in result.unresolved)
    assert not any(s.action == "type" for s in result.workflow.steps)


def test_fill_without_a_value_ref_is_listed_for_a_human():
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    assert any(u.reason == "value_ref_required" for u in result.unresolved)


def test_unresolved_never_carries_the_recorded_fill_value():
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    blob = "\n".join(json.dumps(unresolved.to_json(), ensure_ascii=False) for unresolved in result.unresolved)
    assert "demo" not in blob
    assert any(unresolved.event.get("selector") == "#username" for unresolved in result.unresolved)


def test_the_written_unresolved_file_carries_no_recorded_value(tmp_path):
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    out = tmp_path / "compiled"
    result.write(out)
    assert "demo" not in (out / "unresolved.jsonl").read_text(encoding="utf-8")


def test_write_emits_the_four_artifacts(tmp_path):
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    out = tmp_path / "compiled"
    result.write(out)
    assert (out / "workflow.json").is_file()
    assert (out / "checks.json").is_file()
    assert (out / "unresolved.jsonl").is_file()
    assert (out / "checks.todo.md").is_file()
    assert json.loads((out / "workflow.json").read_text())["id"] == result.workflow.id

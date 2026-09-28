from pathlib import Path

import pytest

from core.transcript.recording import ACTION_EVENTS, load_recording

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "smoke-login"


def test_loads_meta_and_all_events():
    rec = load_recording(FIXTURE)
    assert rec.name == "smoke-login"
    assert rec.title == "登录并打开新建弹窗"
    assert len(rec.events) == 7


def test_events_are_sequenced_in_file_order():
    rec = load_recording(FIXTURE)
    assert [e.seq for e in rec.events] == list(range(7))
    assert rec.events[0].helper == "new_tab"
    assert rec.events[-1].helper == "click_at_xy"


def test_viewport_and_box_are_parsed():
    rec = load_recording(FIXTURE)
    first = rec.events[0]
    assert first.viewport == (1440, 900)
    assert rec.events[2].box == {"x": 40, "y": 60, "w": 240, "h": 28}


def test_helper_specific_details_land_in_detail():
    rec = load_recording(FIXTURE)
    assert rec.events[0].detail == {"to": "http://127.0.0.1:8712/login"}
    assert rec.events[2].detail == {"selector": "#username", "text": "demo"}
    assert rec.events[3].detail == {"x": 120, "y": 168}


def test_actionable_keeps_every_upstream_action_helper():
    """actionable() keeps browser-harness ACTIONS, including wait helpers."""
    rec = load_recording(FIXTURE)
    helpers = [e.helper for e in rec.actionable()]
    assert len(helpers) == 7
    assert "wait_for_load" in helpers
    assert helpers.count("click_at_xy") == 3


def test_probe_targets_are_the_events_that_need_a_browser_probe():
    rec = load_recording(FIXTURE)
    assert [e.helper for e in rec.probe_targets()] == ["click_at_xy"] * 3


def test_action_events_matches_browser_harness_contract():
    # 这份集合必须与 browser-harness 0.1.8 recorder.ACTIONS 一致；
    # 上游升级改动它时，这里先红，逼人去看 changelog。
    assert ACTION_EVENTS == {
        "goto_url", "click_at_xy", "type_text", "fill_input", "press_key",
        "scroll", "dispatch_key", "upload_file", "new_tab", "switch_tab",
        "close_tab", "ensure_real_tab",
        "wait", "wait_for_load", "wait_for_element", "wait_for_network_idle",
    }


def test_missing_recording_raises_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="events.jsonl"):
        load_recording(tmp_path / "nope")


def test_blank_lines_are_skipped(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "meta.json").write_text('{"name": "r", "title": "", "started": 0.0}', encoding="utf-8")
    (d / "events.jsonl").write_text(
        '{"helper": "wait_for_load", "w": 800, "h": 600}\n\n{"helper": "scroll", "x": 1, "y": 2}\n',
        encoding="utf-8",
    )
    rec = load_recording(d)
    assert [e.helper for e in rec.events] == ["wait_for_load", "scroll"]

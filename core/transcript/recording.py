"""Read browser-harness recordings and normalize them into an event stream.

A recording directory has this shape (browser-harness 0.1.8)::

    meta.json     {name, title, started}
    events.jsonl  one action per line; fields are described by DETAIL_KEYS
    0001.jpg ...  screenshot frames after each action

This module only reads and normalizes; it does not infer anchors (that is
handled by core/compile).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Aligned with browser-harness 0.1.8 recorder.ACTIONS. The test contains a
# literal assertion so upstream changes fail before this set is updated.
ACTION_EVENTS: frozenset[str] = frozenset({
    "goto_url", "click_at_xy", "type_text", "fill_input", "press_key",
    "scroll", "dispatch_key", "upload_file", "new_tab", "switch_tab",
    "close_tab", "ensure_real_tab",
    "wait", "wait_for_load", "wait_for_element", "wait_for_network_idle",
})

# Detail fields extracted from each helper's raw event into TraceEvent.detail.
DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    "click_at_xy": ("x", "y"),
    "scroll": ("x", "y", "dy", "dx"),
    "goto_url": ("to",),
    "new_tab": ("to",),
    "type_text": ("text",),
    "fill_input": ("selector", "text"),
    "press_key": ("key",),
    "dispatch_key": ("selector", "key"),
    "wait_for_element": ("selector",),
}


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    ts: float
    helper: str
    url: str = ""
    title: str = ""
    viewport: tuple[int, int] | None = None
    box: dict | None = None
    input_type: str = ""
    frame: str = ""
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def is_action(self) -> bool:
        return self.helper in ACTION_EVENTS

    def xy(self) -> tuple[int, int] | None:
        """Return click/scroll coordinates, or None if they are absent."""
        x, y = self.detail.get("x"), self.detail.get("y")
        return (int(x), int(y)) if x is not None and y is not None else None

    def needs_probe(self) -> bool:
        """Whether compilation requires a probe to identify the target."""
        return self.helper in ("click_at_xy", "type_text", "press_key")


@dataclass(frozen=True)
class Recording:
    name: str
    title: str
    started: float
    path: Path
    events: tuple[TraceEvent, ...]

    def actionable(self) -> tuple[TraceEvent, ...]:
        """Return browser-harness ACTIONS events, including wait helpers.

        Filtering events that can yield compiler steps belongs in core/compile,
        not this layer. Use probe_targets() for events that need a browser probe.
        """
        return tuple(event for event in self.events if event.is_action)

    def probe_targets(self) -> tuple[TraceEvent, ...]:
        return tuple(event for event in self.events if event.needs_probe())

    @property
    def viewport(self) -> tuple[int, int] | None:
        for event in self.events:
            if event.viewport:
                return event.viewport
        return None


def _parse_event(seq: int, raw: dict) -> TraceEvent:
    w, h = raw.get("w"), raw.get("h")
    viewport = (int(w), int(h)) if w and h else None
    detail = {
        key: raw[key]
        for key in DETAIL_KEYS.get(str(raw.get("helper")), ())
        if raw.get(key) is not None
    }
    return TraceEvent(
        seq=seq,
        ts=float(raw.get("ts") or 0.0),
        helper=str(raw.get("helper") or ""),
        url=str(raw.get("url") or ""),
        title=str(raw.get("title") or ""),
        viewport=viewport,
        box=raw.get("box"),
        input_type=str(raw.get("input") or ""),
        frame=str(raw.get("frame") or ""),
        detail=detail,
    )


def load_recording(path: Path | str) -> Recording:
    """Read a recording directory, raising a clear error without events.jsonl."""
    root = Path(path)
    events_file = root / "events.jsonl"
    if not events_file.is_file():
        raise FileNotFoundError(f"{events_file} (events.jsonl does not exist in {root})")

    meta: dict = {}
    meta_file = root / "meta.json"
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    events: list[TraceEvent] = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(_parse_event(len(events), json.loads(line)))

    return Recording(
        name=str(meta.get("name") or root.name),
        title=str(meta.get("title") or ""),
        started=float(meta.get("started") or 0.0),
        path=root,
        events=tuple(events),
    )

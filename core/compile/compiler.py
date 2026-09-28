"""Compile recordings into declarative workflows using probe replay.

Compilation replays actions in recording order. Before actions that need a target,
the replay engine asks the browser which element is actually under the pointer or
focus, then semantic anchors are ranked from that snapshot.

A missing semantic anchor is unresolved rather than a coordinate fallback, and
recorded input text is never copied into a workflow.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

from ..replay.engine import probe
from ..transcript.recording import Recording, TraceEvent
from .anchors import ElementSnapshot, candidates
from .schema import Checks, Step, Unresolved, Workflow

COMPILER_VERSION = "0.1.0"

# Recorded helper -> workflow action. Helpers not listed here do not produce steps.
EVENT_TO_ACTION: dict[str, str] = {
    "new_tab": "goto",
    "goto_url": "goto",
    "wait_for_element": "wait_for",
    "fill_input": "fill",
    "click_at_xy": "click",
    "press_key": "press",
}

SUPPORTED_HELPERS: frozenset[str] = frozenset(EVENT_TO_ACTION)


@dataclass(frozen=True)
class CompileResult:
    workflow: Workflow
    checks: Checks
    unresolved: tuple[Unresolved, ...] = ()
    todo_asserts: tuple[str, ...] = ()

    def write(self, directory: Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "workflow.json").write_text(
            json.dumps(self.workflow.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (directory / "checks.json").write_text(
            json.dumps(self.checks.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (directory / "unresolved.jsonl").open("w", encoding="utf-8") as f:
            for item in self.unresolved:
                f.write(json.dumps(item.to_json(), ensure_ascii=False) + "\n")
        (directory / "checks.todo.md").write_text(self._todo_md(), encoding="utf-8")

    def _todo_md(self) -> str:
        lines = [
            f"# 待补断言：{self.workflow.id}",
            "",
            "编译器只给路径与观测点，**期望值必须来自外部**（需求文档 / 夹具 / 手写）。",
            "把下面每一条翻成 checks.json 里的一条 Check，并填上 `source`。",
            "不要直接抄编译时看到的内容——那会把现状固化成基线。",
            "",
        ]
        lines += [f"- [ ] {line}" for line in self.todo_asserts] or ["- （无可建议的断言点）"]
        if self.unresolved:
            lines += ["", "## 需要人工处理的未解项", ""]
            lines += [f"- seq {u.seq} `{u.helper}` — {u.reason}" for u in self.unresolved]
        return "\n".join(lines) + "\n"


def _path_of(url: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _draft_steps(recording: Recording, unresolved: list[Unresolved]) -> tuple[list[Step], list[TraceEvent]]:
    """Build draft steps and their exact source events as a pair.

    Probe results correspond to steps, not all actionable events. Keeping these
    origins alongside the drafts prevents skipped events from shifting anchors.
    """
    steps: list[Step] = []
    origins: list[TraceEvent] = []
    for event in recording.actionable():
        action = EVENT_TO_ACTION.get(event.helper)
        if action is None:
            if event.helper == "type_text":
                unresolved.append(Unresolved(
                    seq=event.seq,
                    helper=event.helper,
                    event=_raw(event),
                    reason="type_text_unsupported",
                ))
            continue

        n = len(steps) + 1
        if action == "goto":
            steps.append(Step(n=n, action="goto", path=_path_of(str(event.detail.get("to") or ""))))
        elif action == "wait_for":
            steps.append(Step(n=n, action="wait_for", selector=str(event.detail.get("selector") or "")))
        elif action == "fill":
            # Never copy the recorded input text. A human must supply env:<VAR>.
            steps.append(Step(n=n, action="fill", selector=str(event.detail.get("selector") or "")))
            unresolved.append(Unresolved(
                seq=event.seq,
                helper=event.helper,
                event=_raw(event),
                reason="value_ref_required",
            ))
        elif action == "click":
            xy = event.xy()
            if xy is None:
                unresolved.append(Unresolved(
                    seq=event.seq,
                    helper=event.helper,
                    event=_raw(event),
                    reason="click_without_coordinates",
                ))
                continue
            steps.append(Step(n=n, action="click", xy=xy))
        elif action == "press":
            steps.append(Step(n=n, action="press", key=str(event.detail.get("key") or "")))

        origins.append(event)
    return steps, origins


_REDACTED_DETAIL_KEYS = frozenset({"text"})


def _raw(event: TraceEvent) -> dict:
    """Return event context without persisting text typed into the page."""
    raw = {"seq": event.seq, "helper": event.helper, "url": event.url}
    raw.update({key: value for key, value in event.detail.items() if key not in _REDACTED_DETAIL_KEYS})
    if event.box:
        raw["box"] = event.box
    return raw


def compile_recording(
    recording: Recording,
    target: str,
    locator,
    *,
    workflow_id: str | None = None,
) -> CompileResult:
    unresolved: list[Unresolved] = []
    draft, origins = _draft_steps(recording, unresolved)

    workflow = Workflow(
        id=workflow_id or f"wf-{recording.name}",
        title=recording.title or recording.name,
        target=target,
        source={
            "recording": recording.name,
            "compiled_at": _now(),
            "compiler": COMPILER_VERSION,
            "viewport": list(recording.viewport) if recording.viewport else None,
        },
        steps=tuple(draft),
    )

    # The recorded fill is transient probe input only; the workflow keeps an empty value_ref.
    replay_values = {
        step.n: str(event.detail.get("text") or "")
        for step, event in zip(draft, origins)
        if step.action == "fill"
    }

    observed = probe(workflow, locator, replay_values=replay_values)
    assert len(observed) == len(origins), "probe() must return one entry per step"
    steps: list[Step] = []
    todo: list[str] = []

    for (step, snap), event in zip(observed, origins):
        if step.action in ("click", "press"):
            if snap is None:
                unresolved.append(Unresolved(
                    seq=event.seq,
                    helper=event.helper,
                    event=_raw(event),
                    reason="probe_returned_nothing",
                ))
                continue
            ranked = candidates(snap)
            semantic = [anchor for anchor in ranked if anchor.by != "xy"]
            if not semantic:
                unresolved.append(Unresolved(
                    seq=event.seq,
                    helper=event.helper,
                    event=_raw(event),
                    candidates=ranked,
                    reason="no_semantic_hook",
                ))
                continue
            step = replace(step, anchor=semantic[0])
        steps.append(step)
        if snap is not None:
            todo.append(_suggest(step, snap))
        elif step.action == "wait_for":
            todo.append(f"step {step.n}: 断言 `{step.selector}` 的内容/条数（期望值待外部来源）")

    # Renumber after dropping unresolved steps so after_step references stay contiguous.
    steps = [replace(step, n=i + 1) for i, step in enumerate(steps)]
    compiled = Workflow(
        id=workflow.id,
        title=workflow.title,
        target=target,
        source=workflow.source,
        steps=tuple(steps),
    )
    return CompileResult(
        workflow=compiled,
        checks=Checks(workflow=compiled.id, checks=()),
        unresolved=tuple(unresolved),
        todo_asserts=tuple(todo),
    )


def _suggest(step: Step, snap: ElementSnapshot) -> str:
    where = snap.testid or snap.name or snap.text or snap.path
    return f"step {step.n} ({step.action} `{where}`): 断言语义 —— 期望值请从需求文档/夹具取"


def _now() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).isoformat(timespec="seconds")

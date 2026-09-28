"""workflow / step / anchor / unresolved 的数据契约（spec §4.3）。

都是纯数据 + JSON 往返，不含任何浏览器或业务逻辑。
断言的 sidecar（Check / Checks）由 Task 6 追加到本模块 —— 本 Task 不定义它们。
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Anchor:
    by: str                                   # testid | role | text | path | xy
    value: str = ""
    role: str = ""
    name: str = ""
    fallback: bool = False                    # xy 兜底必须为 True
    copy_sensitive: bool = False              # 文案会变 → 允许近似匹配

    def to_json(self) -> dict:
        out = {"by": self.by}
        for key in ("value", "role", "name"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.fallback:
            out["fallback"] = True
        if self.copy_sensitive:
            out["copy_sensitive"] = True
        return out

    @staticmethod
    def from_json(d: dict) -> "Anchor":
        return Anchor(
            by=str(d.get("by") or ""),
            value=str(d.get("value") or ""),
            role=str(d.get("role") or ""),
            name=str(d.get("name") or ""),
            fallback=bool(d.get("fallback")),
            copy_sensitive=bool(d.get("copy_sensitive")),
        )


@dataclass(frozen=True)
class Step:
    n: int
    action: str                               # goto|click|fill|press|wait_for|scroll|wait_network_idle
    anchor: Anchor | None = None
    path: str = ""                            # goto 用
    selector: str = ""                        # fill/wait_for 用
    value_ref: str = ""                       # 只允许 env:<VAR> 或 cred:<name>
    text: str = ""                            # press 用不到；填给 fill 的明文一律拒绝
    key: str = ""                             # press 用
    state: str = "visible"                    # wait_for 用
    # 录制的原始落点。**只服务编译期探针**：回放一律按 anchor 定位，
    # 除非 anchor 本身就是那个打了 fallback 标的 xy 兜底。
    xy: tuple[int, int] | None = None

    def to_json(self) -> dict:
        out: dict = {"n": self.n, "action": self.action}
        if self.anchor:
            out["anchor"] = self.anchor.to_json()
        for key in ("path", "selector", "value_ref", "text", "key"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        # A click at the top-left corner is a valid (but falsy) (0, 0) tuple.
        if self.xy is not None:
            out["xy"] = list(self.xy)
        if self.action == "wait_for":
            out["state"] = self.state
        return out

    @staticmethod
    def from_json(d: dict) -> "Step":
        return Step(
            n=int(d.get("n") or 0),
            action=str(d.get("action") or ""),
            anchor=Anchor.from_json(d["anchor"]) if d.get("anchor") else None,
            path=str(d.get("path") or ""),
            selector=str(d.get("selector") or ""),
            value_ref=str(d.get("value_ref") or ""),
            text=str(d.get("text") or ""),
            key=str(d.get("key") or ""),
            state=str(d.get("state") or "visible"),
            xy=tuple(d["xy"]) if d.get("xy") is not None else None,
        )


@dataclass(frozen=True)
class Workflow:
    id: str
    title: str
    target: str
    source: dict = field(default_factory=dict)
    steps: tuple[Step, ...] = ()

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "target": self.target,
            "source": self.source,
            "steps": [s.to_json() for s in self.steps],
        }

    @staticmethod
    def from_json(d: dict) -> "Workflow":
        version = d.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"workflow schema_version {version!r} != {SCHEMA_VERSION}")
        return Workflow(
            id=str(d["id"]),
            title=str(d.get("title") or ""),
            target=str(d.get("target") or ""),
            source=dict(d.get("source") or {}),
            steps=tuple(Step.from_json(s) for s in d.get("steps") or []),
        )


@dataclass(frozen=True)
class Unresolved:
    seq: int
    helper: str
    event: dict
    candidates: tuple[Anchor, ...] = ()
    reason: str = ""

    def to_json(self) -> dict:
        return {
            "seq": self.seq,
            "helper": self.helper,
            "event": self.event,
            "candidates": [a.to_json() for a in self.candidates],
            "reason": self.reason,
        }

    @staticmethod
    def from_json(d: dict) -> "Unresolved":
        return Unresolved(
            seq=int(d.get("seq") or 0),
            helper=str(d.get("helper") or ""),
            event=dict(d.get("event") or {}),
            candidates=tuple(Anchor.from_json(a) for a in d.get("candidates") or []),
            reason=str(d.get("reason") or ""),
        )

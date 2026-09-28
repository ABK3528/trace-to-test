"""期望值来源的接口。**这是防 oracle 锁错的最后一道边界**。

`expectation()` 的合法实现只能读外部真源（需求文档、夹具、人工评审结论）。
它**不许**读编译期产物（`checks.todo.md`、`observed_at_compile`）——
读了就等于把"探索时看到什么"变成基线，正是 spec §鸿沟二 要堵的洞。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Oracle(Protocol):
    source_tag: str

    def expectation(self, key: str) -> str:
        """返回 key 对应的期望值。key 找不到时必须抛 KeyError，不许返回空串。"""
        ...

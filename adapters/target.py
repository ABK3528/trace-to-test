"""被测目标的接口。**项目相关的第一处落点**。

机制层只认这个协议，不认任何具体项目：base_url 从哪来、哪些主机被允许、
凭据叫什么名字、构建标识怎么取，全都由项目自己实现。
"""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class Target(Protocol):
    name: str
    base_url: str
    allow_hosts: tuple[str, ...]
    # 环境变量名 → 用途说明。**值是空的** —— 凭据永远不落进代码或配置。
    credentials: Mapping[str, str]

    def build_id(self) -> str:
        """取当前部署的构建标识（用于判断 workflow 是否对着一份旧构建）。"""
        ...

"""靶场这一份实例实现 —— 仓内唯一的 adapters/instance 内容。

新项目落地时照这份写自己的：换 base_url、换 allow_hosts、
把 credentials 换成本项目要用的环境变量名、把 oracle 接到本项目自己的真源上。
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

_CREDENTIALS = {
    "DEMO_USERNAME": "靶场登录用户名（值来自环境变量，不落代码）",
    "DEMO_PASSWORD": "靶场登录密码（值来自环境变量，不落代码）",
}


class DemoTarget:
    name = "demo"
    base_url = "http://127.0.0.1:8712"
    allow_hosts: tuple[str, ...] = ()
    credentials = _CREDENTIALS

    def build_id(self) -> str:
        with urllib.request.urlopen(f"{self.base_url}/healthz", timeout=5) as r:
            return json.loads(r.read())["build"]


class SpecOracle:
    """从一份 markdown 需求文档里取期望值。

    key 的形状是 `<anchor>#<段落标题>`；找不到就抛 KeyError ——
    静默返回空串会让断言变成"和空串比较"，那是另一种假绿。
    """

    def __init__(self, spec_path: Path):
        self._path = Path(spec_path)
        self.source_tag = f"spec:{self._path}"

    def expectation(self, key: str) -> str:
        heading, _, _ = key.partition("#")
        body = self._path.read_text(encoding="utf-8")
        wanted = re.escape(heading)
        for block in re.split(r"^##\s+", body, flags=re.MULTILINE):
            if re.match(rf"^{wanted}\b", block):
                return block.strip()
        raise KeyError(f"{key!r} is not in the spec document {self._path}")


def demo_oracle_from_spec(spec_path: Path) -> SpecOracle:
    return SpecOracle(spec_path)

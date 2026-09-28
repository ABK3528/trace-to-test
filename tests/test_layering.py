"""分层守卫：机制层不许依赖项目层。

这条测试把 spec §4.1 的那句承诺变成可执行的东西 ——
光写在文档里的边界，第一次赶工时就会被越过去。
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MECHANISM = ("core", "checks")
FORBIDDEN = ("adapters", "target_app", "demo")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module is None:
                continue
            if node.level:                       # 相对导入，跳出本包才算越界
                continue
            if node.module:
                found.add(node.module.split(".")[0])
    return found


def _mechanism_files() -> list[Path]:
    files: list[Path] = []
    for pkg in MECHANISM:
        files += [p for p in (ROOT / pkg).rglob("*.py") if "__pycache__" not in p.parts]
    return files


def test_the_mechanism_layer_exists_so_this_test_is_not_vacuous():
    assert _mechanism_files(), "no mechanism files found — the layering guard would pass vacuously"


@pytest.mark.parametrize("path", _mechanism_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_mechanism_never_imports_the_project_layer(path: Path):
    broken = _imported_modules(path) & set(FORBIDDEN)
    assert not broken, f"{path.relative_to(ROOT)} imports {sorted(broken)} — 机制层不许依赖项目层"


def test_the_mechanism_layer_has_no_llm_client_dependency():
    """回放与编译必须零 LLM。"""
    banned = {"openai", "anthropic", "litellm", "langchain", "ollama", "requests"}
    for path in _mechanism_files():
        assert not (_imported_modules(path) & banned), f"{path.relative_to(ROOT)} 引入了 LLM/网络客户端"

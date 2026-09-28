"""分层守卫：机制层不许依赖项目层。

这条测试把 spec §4.1 的那句承诺变成可执行的东西 ——
光写在文档里的边界，第一次赶工时就会被越过去。
"""
import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MECHANISM = ("core", "checks")
FORBIDDEN = ("adapters", "target_app", "demo")


ESCAPES_TOP_LEVEL = "<escapes-top-level>"
FORBIDDEN_IMPORTS = frozenset({"adapters", "target_app", "demo", ESCAPES_TOP_LEVEL})


def _package_of(path: Path) -> str:
    """core/compile/x.py → 'core.compile'；core/x.py → 'core'。"""
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    parts.pop()                                   # 去掉模块名（或 __init__）
    return ".".join(parts)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _package_of(path)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.add(node.module.split(".")[0])
                continue
            # Resolve relative names against their package context. An ImportError
            # means the import climbs above the top-level package and is forbidden.
            try:
                resolved = importlib.util.resolve_name(
                    "." * node.level + (node.module or ""), package
                )
            except ImportError:
                found.add(ESCAPES_TOP_LEVEL)
                continue
            found.add(resolved.split(".")[0])
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
    broken = _imported_modules(path) & FORBIDDEN_IMPORTS
    assert not broken, f"{path.relative_to(ROOT)} imports {sorted(broken)} — 机制层不许依赖项目层"


def test_a_relative_import_that_escapes_the_top_level_package_is_caught():
    """Regression for relative imports escaping core; probe real resolver behavior."""
    probe = ROOT / "core" / "_probe_escape.py"
    probe.write_text("from ..adapters import target\n", encoding="utf-8")
    try:
        assert ESCAPES_TOP_LEVEL in _imported_modules(probe)
    finally:
        probe.unlink()


ALLOWED_THIRD_PARTY = frozenset({"browser_harness"})


def test_the_mechanism_layer_imports_nothing_unexpected():
    """Allow only stdlib, project packages, and explicitly permitted third-party."""
    allowed = set(sys.stdlib_module_names) | {"core", "checks"}
    for path in _mechanism_files():
        extra = _imported_modules(path) - allowed - ALLOWED_THIRD_PARTY
        assert not extra, f"{path.relative_to(ROOT)} 引入了未许可的依赖 {sorted(extra)}"


def test_only_the_browser_layer_may_touch_the_browser_driver():
    """browser_harness is confined to core/primitives; replay and compile stay browser-independent."""
    scanned = 0
    for path in _mechanism_files():
        scanned += 1
        if "browser_harness" not in _imported_modules(path):
            continue
        assert path.relative_to(ROOT).parts[:2] == ("core", "primitives"), (
            f"{path.relative_to(ROOT)} 引入了 browser_harness，但它不在 core/primitives/"
        )
    assert scanned > 0, "没扫到任何机制层文件 —— 这条守卫会空过"


def test_the_replay_and_compile_layers_use_nothing_but_stdlib_and_core():
    """Replay and compile are the zero-LLM boundary; no third-party deps are allowed."""
    allowed = set(sys.stdlib_module_names) | {"core"}
    seen = {"core.replay": 0, "core.compile": 0}
    for path in _mechanism_files():
        parts = path.relative_to(ROOT).parts[:2]
        if parts not in (("core", "replay"), ("core", "compile")):
            continue
        seen[".".join(parts)] += 1
        residual = _imported_modules(path) - allowed
        assert not residual, f"{path.relative_to(ROOT)} 在零 LLM 层引入了非标准库依赖 {sorted(residual)}"
    for layer, count in seen.items():
        assert count > 0, f"{layer}/ 下一个文件都没扫到 —— 这一层的守卫会空过"

import os
import shutil
import subprocess
import pytest
import sys
import types
from pathlib import Path

from core.compile.schema import Anchor
from core.primitives import session as session_mod
from core.primitives.session import (
    Session,
    TargetNotAllowed,
    assert_target_allowed,
    chrome_launch_args,
    find_chrome,
    harness_env,
    read_devtools_port,
    reap_leaked_browsers,
)


class _StubSession(Session):
    """Construct a session-shaped object without launching a browser."""

    def __init__(self, resolve_result):
        self.timeout = 15.0
        self._resolve_result = resolve_result

    def resolve(self, anchor):
        return self._resolve_result


def test_loopback_is_allowed_by_default():
    assert_target_allowed("http://127.0.0.1:8712", allow_hosts=())
    assert_target_allowed("http://localhost:8712", allow_hosts=())


def test_remote_host_is_refused_by_default():
    with pytest.raises(TargetNotAllowed, match="not in the allow-list"):
        assert_target_allowed("https://example.com", allow_hosts=())


def test_remote_host_is_allowed_when_explicitly_listed():
    assert_target_allowed("https://example.com", allow_hosts=("example.com",))


def test_subdomain_of_a_listed_host_is_allowed():
    assert_target_allowed("https://a.example.com", allow_hosts=("example.com",))


def test_www_prefix_does_not_bypass_the_gate():
    with pytest.raises(TargetNotAllowed):
        assert_target_allowed("https://www.evil.com", allow_hosts=("evil.com",))


def test_a_lookalike_domain_does_not_pass():
    with pytest.raises(TargetNotAllowed):
        assert_target_allowed("https://notexample.com", allow_hosts=("example.com",))


def test_goto_rechecks_gate_for_absolute_urls(monkeypatch):
    session = Session("http://127.0.0.1:8712")
    calls = []
    monkeypatch.setattr(session, "_act", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(TargetNotAllowed, match="not in the allow-list"):
        session.goto("https://elsewhere.example")
    assert calls == []


def test_goto_allows_configured_host_and_resolves_relative_paths(monkeypatch):
    session = Session("http://127.0.0.1:8712", allow_hosts=("example.com",))
    calls = []
    monkeypatch.setattr(session, "_act", lambda *args, **kwargs: calls.append(args))
    session.goto("https://example.com/page")
    session.goto("/login")
    assert calls[0] == ("new_tab", "https://example.com/page")
    assert calls[2] == ("new_tab", "http://127.0.0.1:8712/login")


def test_default_profile_is_unique_per_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    first = Session("http://127.0.0.1:8712")
    second = Session("http://127.0.0.1:8712")
    assert first.profile_dir != second.profile_dir
    assert first.profile_dir.name.startswith(f"ttt-profile-{os.getpid()}-")


def test_sessions_share_a_stable_daemon_name_but_not_a_chrome_profile():
    first = Session("http://127.0.0.1:8712")
    second = Session("http://127.0.0.1:8712")
    assert first._daemon_name == second._daemon_name == f"ttt-{os.getpid()}"
    assert first.profile_dir != second.profile_dir


# —— 隔离：这是我们自起 Chrome 的全部依据，不能只写在注释里 ——


def test_chrome_launch_args_isolate_profile_and_debug_port(tmp_path):
    args = chrome_launch_args(tmp_path, headed=False)
    assert f"--user-data-dir={tmp_path}" in args
    # 端口交给 Chrome 自己挑（=0），避免"我们先要一个再交给它"的竞态
    assert "--remote-debugging-port=0" in args


def test_headless_is_default_and_headed_drops_it(tmp_path):
    assert "--headless=new" in chrome_launch_args(tmp_path, headed=False)
    assert "--headless=new" not in chrome_launch_args(tmp_path, headed=True)


class _AliveProc:
    returncode = None

    def poll(self):
        return None


def test_read_devtools_port_reads_what_chrome_wrote(tmp_path):
    (tmp_path / "DevToolsActivePort").write_text(
        "9333\n/devtools/browser/abc\n", encoding="utf-8")
    assert read_devtools_port(tmp_path, _AliveProc(), timeout=1.0) == 9333


def test_read_devtools_port_gives_up_loudly_instead_of_falling_back(tmp_path):
    """回归：Chrome 没写出 marker 时必须报错退出 —— 绝不退化成用默认浏览器。"""
    with pytest.raises(RuntimeError, match="refusing to fall back"):
        read_devtools_port(tmp_path, _AliveProc(), timeout=0.5)


def test_read_devtools_port_surfaces_an_early_chrome_exit(tmp_path):
    class _DeadProc:
        returncode = 1

        def poll(self):
            return 1

    with pytest.raises(RuntimeError, match="exited early"):
        read_devtools_port(tmp_path, _DeadProc(), timeout=1.0)


def test_harness_env_points_the_daemon_at_our_own_chrome():
    """BU_CDP_URL 一设，browser-harness 就不再走本地 Chrome 发现 ——
    这就是"绝不 attach 用户主浏览器"的机制，不是注释。"""
    env = harness_env("ttt-test", 9333)
    assert env == {"BU_NAME": "ttt-test", "BU_CDP_URL": "http://127.0.0.1:9333"}


def test_session_structurally_satisfies_the_locator_protocol():
    """Guard the structural contract, including a non-vacuity check."""
    import inspect

    from core.replay import engine

    protocol_members = {
        name for name, member in inspect.getmembers(engine.Locator, inspect.isfunction)
        if not name.startswith("_")
    }
    assert protocol_members, "没读到 Locator 的任何成员 —— 这条守卫会空过"
    missing = sorted(n for n in protocol_members if not callable(getattr(Session, n, None)))
    assert not missing, f"Session 未实现 Locator 的成员：{missing}"


def test_reap_matches_the_key_name_not_the_bare_path(tmp_path):
    """🔴 回归：匹配串必须带键名 user-data-dir=。裸路径会命中"命令行里恰好
    提到这个路径"的无关进程（包括正在跑的这条 shell），是事故不是清理。"""
    src = Path(session_mod.__file__).read_text(encoding="utf-8")
    assert 'f"user-data-dir={profile_dir}"' in src


# —— resolve() 拼 JS：四种定位表达式都必须是对浏览器合法的 JS ——
# 这些测试不碰浏览器，只验证 resolve() 生成的字符串能被 node 解析 ——
# 历史缺陷：resolve() 生成的 count IIFE 少一个右花括号（`}})()` 而非 `})()`），
# testid 定位串把 CSS 选择器当 JS 布尔拼（`'x' and '...'`），path/text/role 三
# 种定位都用 `querySelector` 而它不返回数组 —— 全都只在"真的对着浏览器 resolve"
# 时才暴露，单测里的 FakeLocator 永远替身掉 resolve 本身。


def _resolve_count_js(anchor: Anchor) -> str:
    """复刻 resolve() 里 count 分支拼出的完整 JS，供 node 语法检查。"""
    import core.primitives.session as sm

    locate = {
        "testid": f"[...document.querySelectorAll('[data-testid=\"{anchor.value}\"]')]",
        "path": f"[...document.querySelectorAll({anchor.value!r})]",
        "text": f"__tttFindByText({anchor.value!r})",
        "role": f"__tttFindByRole({anchor.role!r}, {anchor.name!r})",
        "xy": None,
    }[anchor.by]
    return (sm.LOCATE_HELPERS
            + f"(()=>{{ const r={locate}; "
              "return Array.isArray(r) ? r.length : (r ? 1 : 0); })()")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_resolve_locators_are_valid_js(tmp_path):
    anchors = [
        Anchor(by="role", role="button", name="登 录", copy_sensitive=True),
        Anchor(by="text", value="新建", copy_sensitive=True),
        Anchor(by="path", value="body > form > button"),
        Anchor(by="testid", value="item-row"),
    ]
    for anchor in anchors:
        js_file = tmp_path / "resolve.js"
        js_file.write_text(_resolve_count_js(anchor), encoding="utf-8")
        result = subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True)
        assert result.returncode == 0, f"{anchor.by} locate is not valid JS: {result.stderr}"


# —— 录制形状：_act 必须按位置传参，否则录制里的坐标落成 None ——


class _FakeRecorder:
    def __init__(self):
        self.calls = []

    def observe(self, helper, args, kwargs, duration=None):
        self.calls.append((helper, args, kwargs))


def test_act_reports_coordinates_positionally_for_the_recorder():
    """recorder._details() 按位置下标取坐标（arg(0,'x'), arg(1,'y')）。
    放进关键字参数 ⇒ 录制里 x/y 是 None ⇒ 编译器没有坐标可反解。"""
    s = _StubSession({"count": 1, "snap": None, "drift": ""})
    s._bh = types.SimpleNamespace(click_at_xy=lambda x, y: None)
    s._recorder = _FakeRecorder()
    s.click_xy(120, 168)
    helper, args, kwargs = s._recorder.calls[0]
    assert helper == "click_at_xy"
    assert args[:2] == (120, 168)


def test_act_reports_wait_for_element_with_the_timeout_positionally():
    """wait_for_element(selector, timeout, visible=) —— 中间那个 timeout
    是位置参数，跳不过去；visible 用关键字传。形状错了录制就缺字段。"""
    s = _StubSession({"count": 1, "snap": None, "drift": ""})
    s._bh = types.SimpleNamespace(wait_for_element=lambda sel, t, visible=False: None)
    s._recorder = _FakeRecorder()
    s.wait_for("#items")
    helper, args, kwargs = s._recorder.calls[0]
    assert helper == "wait_for_element"
    assert args == ("#items", s.timeout)
    assert kwargs == {"visible": True}


def test_click_at_anchor_clicks_the_centre_of_the_resolved_element():
    from core.compile.anchors import ElementSnapshot

    snap = ElementSnapshot(tag="button", role="", name="", text="", testid="b",
                           attrs={}, path="", rect={"x": 100, "y": 50, "w": 40, "h": 20})
    s = _StubSession({"count": 1, "snap": snap, "drift": ""})
    s.clicks = []
    s.click_xy = lambda x, y: s.clicks.append((x, y))
    s.click_at_anchor(Anchor(by="testid", value="b"))
    assert s.clicks == [(120, 60)]


def test_click_at_anchor_refuses_when_the_anchor_did_not_resolve():
    s = _StubSession({"count": 0, "snap": None, "drift": ""})
    s.clicks = []
    s.click_xy = lambda x, y: s.clicks.append((x, y))
    with pytest.raises(AssertionError, match="did not resolve"):
        s.click_at_anchor(Anchor(by="testid", value="b"))
    assert s.clicks == []


def test_session_applies_the_requested_viewport():
    calls = []
    s = object.__new__(Session)
    s.viewport = (1280, 720)
    s._bh = types.SimpleNamespace(cdp=lambda *args, **kwargs: calls.append((args, kwargs)))
    s._apply_viewport()
    assert calls == [(
        ("Emulation.setDeviceMetricsOverride",),
        {"width": 1280, "height": 720, "deviceScaleFactor": 1, "mobile": False},
    )]


def test_find_chrome_respects_explicit_executable(monkeypatch, tmp_path):
    chrome = tmp_path / "chrome"
    chrome.touch()
    monkeypatch.setenv("TTT_CHROME", str(chrome))
    assert find_chrome() == str(chrome)


def test_shutdown_terminates_owned_process_then_reaps_its_profile(monkeypatch, tmp_path):
    calls = []

    class _ChromeProc:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))

    s = object.__new__(Session)
    s.profile_dir = tmp_path
    s._chrome = _ChromeProc()
    monkeypatch.setattr(session_mod, "reap_leaked_browsers", lambda profile: calls.append(("reap", profile)) or 0)
    s._shutdown()
    assert calls == ["terminate", ("wait", 10), ("reap", tmp_path)]
    assert s._chrome is None


def test_enter_sets_isolated_harness_environment_before_admin_import(monkeypatch, tmp_path):
    calls = []

    class _ChromeProc:
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append(("wait", timeout))

    monkeypatch.setattr(session_mod.subprocess, "Popen", lambda *args, **kwargs: _ChromeProc())
    monkeypatch.setattr(session_mod, "find_chrome", lambda: "/fake/chrome")
    monkeypatch.setattr(session_mod, "read_devtools_port", lambda profile, proc, timeout: 9555)
    monkeypatch.setattr(session_mod, "reap_leaked_browsers", lambda profile: 0)

    def ensure_daemon(name):
        assert os.environ["BU_NAME"] == name
        assert os.environ["BU_CDP_URL"] == "http://127.0.0.1:9555"
        calls.append(("ensure_daemon", name))

    def restart_daemon(name):
        calls.append(("restart_daemon", name))

    monkeypatch.setattr(session_mod, "_load_harness", lambda: (
        types.SimpleNamespace(cdp=lambda *args, **kwargs: None),
        object(),
        ensure_daemon,
        restart_daemon,
    ))

    monkeypatch.setitem(sys.modules, "browser_harness.admin", types.SimpleNamespace(
        ensure_daemon=ensure_daemon, restart_daemon=restart_daemon))
    s = Session("http://127.0.0.1:8712", profile_dir=tmp_path)
    try:
        assert s.__enter__() is s
        assert calls == [("restart_daemon", s._daemon_name), ("ensure_daemon", s._daemon_name)]
    finally:
        s._shutdown()

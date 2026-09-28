import os
import pytest
import sys
import types
from pathlib import Path

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


def test_reap_matches_the_key_name_not_the_bare_path(tmp_path):
    """🔴 回归：匹配串必须带键名 user-data-dir=。裸路径会命中"命令行里恰好
    提到这个路径"的无关进程（包括正在跑的这条 shell），是事故不是清理。"""
    src = Path(session_mod.__file__).read_text(encoding="utf-8")
    assert 'f"user-data-dir={profile_dir}"' in src


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
    monkeypatch.setattr(session_mod, "_load_harness", lambda: (
        types.SimpleNamespace(cdp=lambda *args, **kwargs: None),
        object(),
    ))

    def ensure_daemon(name):
        assert os.environ["BU_NAME"] == name
        assert os.environ["BU_CDP_URL"] == "http://127.0.0.1:9555"
        calls.append(("ensure_daemon", name))

    monkeypatch.setitem(sys.modules, "browser_harness.admin", types.SimpleNamespace(ensure_daemon=ensure_daemon))
    s = Session("http://127.0.0.1:8712", profile_dir=tmp_path)
    try:
        assert s.__enter__() is s
        assert calls == [("ensure_daemon", s._daemon_name)]
    finally:
        s._shutdown()

import json
import urllib.request

from target_app.serve import serve


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_serves_login_page():
    with serve() as srv:
        with urllib.request.urlopen(f"{srv.base_url}/login", timeout=5) as r:
            body = r.read().decode()
        assert r.status == 200
        assert 'data-testid="login-form"' in body


def test_healthz_exposes_build_id():
    with serve() as srv:
        assert _get(f"{srv.base_url}/healthz")["build"]


def test_copy_mode_switches_button_label():
    with serve() as srv:
        _post(f"{srv.base_url}/__demo__/copy-mode", {"mode": "drifted"})
        with urllib.request.urlopen(f"{srv.base_url}/login", timeout=5) as r:
            assert "登 录" not in r.read().decode()
        _post(f"{srv.base_url}/__demo__/copy-mode", {"mode": "spec"})
        with urllib.request.urlopen(f"{srv.base_url}/login", timeout=5) as r:
            assert "登 录" in r.read().decode()


def test_strip_testids_also_reaches_hooks_the_page_script_would_create():
    """动态钩子也归开关管：否则 strip 只半生效，验收会为错的原因通过。"""
    with serve() as srv:
        _post(f"{srv.base_url}/__demo__/strip-testids", {"strip": True})
        with urllib.request.urlopen(f"{srv.base_url}/list", timeout=5) as r:
            stripped = r.read().decode()
        assert 'data-strip-testids="true"' in stripped
        script = stripped.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "if (!STRIP) li.dataset.testid = 'item-row';" in script
        assert "const STRIP = document.documentElement.dataset.stripTestids === 'true';" in script

        _post(f"{srv.base_url}/__demo__/strip-testids", {"strip": False})
        with urllib.request.urlopen(f"{srv.base_url}/list", timeout=5) as r:
            plain = r.read().decode()
        assert 'data-strip-testids="false"' in plain
        assert 'data-testid="item-list"' in plain


def test_serve_returns_a_usable_handle_not_just_a_context_manager():
    """接口声明返回 ServerHandle，就直接可用 —— 不要求调用方必须包在 with 里。"""
    srv = serve()
    try:
        assert srv.port > 0
        assert srv.base_url.startswith("http://127.0.0.1:")
    finally:
        srv.stop()


def test_strip_testids_removes_the_hook():
    with serve() as srv:
        _post(f"{srv.base_url}/__demo__/strip-testids", {"strip": True})
        with urllib.request.urlopen(f"{srv.base_url}/login", timeout=5) as r:
            assert 'data-testid="login-form"' not in r.read().decode()


def test_shift_layout_pushes_the_content_down():
    with serve() as srv:
        _post(f"{srv.base_url}/__demo__/shift-layout", {"dy": 120})
        for page in ("/login", "/list"):
            with urllib.request.urlopen(f"{srv.base_url}{page}", timeout=5) as r:
                assert "translateY(120px)" in r.read().decode()

        _post(f"{srv.base_url}/__demo__/shift-layout", {"dy": 0})
        with urllib.request.urlopen(f"{srv.base_url}/login", timeout=5) as r:
            assert "translateY(120px)" not in r.read().decode()

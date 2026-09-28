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


def test_strip_testids_removes_the_hook():
    with serve() as srv:
        _post(f"{srv.base_url}/__demo__/strip-testids", {"strip": True})
        with urllib.request.urlopen(f"{srv.base_url}/login", timeout=5) as r:
            assert 'data-testid="login-form"' not in r.read().decode()

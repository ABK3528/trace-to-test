"""浏览器会话原语：起自己的一次性 Chrome、驱动它、退出时收拾干净。

两条硬规矩：
1. 只打 loopback（除非显式 allow_hosts）——默认安全，不靠自觉。
2. 只关自己 profile 的实例，绝不碰用户主浏览器。browser-harness 实例泄漏是
   已知问题（实测攒到过 15 个挂同一 profile 的实例拖垮后续 run），所以
   __exit__ 里必须回收，且匹配串要带键名 user-data-dir=<profile> ——
   裸路径会命中"命令行里恰好提到这个路径"的无关进程，包括正在跑的 shell 自己。
"""
from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from ..compile.anchors import SNAP_JS, ElementSnapshot

DEFAULT_VIEWPORT = (1440, 900)

# Keep automatically assigned profile names unique within this process.
_PROFILE_SEQ = itertools.count()


class TargetNotAllowed(Exception):
    """目标不在允许清单里。默认只允许 loopback。"""


class BrowserHarnessMissing(Exception):
    """没装 browser-harness（可选依赖）。"""


def _host_of(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def assert_target_allowed(base_url: str, allow_hosts: tuple[str, ...] = ()) -> None:
    """放行 loopback 与显式列出的主机（含其子域，但 www. 前缀不算同域）。"""
    host = _host_of(base_url)
    if host in ("127.0.0.1", "localhost", "::1"):
        return
    for allowed in allow_hosts:
        allowed = allowed.lower().lstrip(".")
        if host == allowed:
            return
        if host.endswith("." + allowed) and host != "www." + allowed:
            return
    raise TargetNotAllowed(
        f"{host!r} is not in the allow-list {allow_hosts!r}; "
        "pass allow_hosts=... explicitly if this is intended"
    )


def read_devtools_port(profile_dir: Path, proc, timeout: float = 20.0) -> int:
    """读 Chrome 自己写下的 DevToolsActivePort。

    🔴 为什么不是"我们先 free_port() 再把端口交给 Chrome"：那是 TOCTOU ——
    从我们放掉端口到 Chrome 绑上之间，别人可能抢走。让 Chrome 自己挑
    （`--remote-debugging-port=0`）并把结果写进 profile 下的 DevToolsActivePort
    文件，是唯一没有竞态的取法。文件首行是端口，次行是 ws 路径。
    超时就报错，**绝不退化成用默认浏览器**。
    """
    marker = profile_dir / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"our Chrome exited early with code {proc.returncode}")
        try:
            first = marker.read_text(encoding="utf-8").splitlines()[0].strip()
            if first.isdigit():
                return int(first)
        except (FileNotFoundError, IndexError, OSError):
            pass
        time.sleep(0.15)
    raise RuntimeError(
        f"our Chrome never wrote {marker} — refusing to fall back to the default browser"
    )


def chrome_launch_args(profile_dir: Path, headed: bool = False) -> list[str]:
    """自起 Chrome 的参数 —— **"绝不 attach 用户主浏览器"就落在这一行**。

    `--user-data-dir` 把 profile 和用户的分开，`--remote-debugging-port=0` 让
    Chrome 自己挑一个空闲调试端口（我们随后从 DevToolsActivePort 读回来）。
    少任何一个，都可能连到用户正在用的那个浏览器。
    后面两个开关是防无人值守时被首启向导卡住。
    """
    args = [
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    if not headed:
        args.insert(0, "--headless=new")
    return args


def harness_env(name: str, port: int) -> dict[str, str]:
    """让 browser-harness 只连我们自起的 Chrome。

    🔴 必须在 **import browser_harness 之前**写进 `os.environ`：
       `admin.NAME` / `daemon.NAME` 都是 import 时从 `BU_NAME` 读一次的，
       daemon 子进程也从自己的环境读 `BU_CDP_URL`。写晚了就静默落回
       默认 daemon + 本地 Chrome 发现 ⇒ 挂到用户主浏览器上。
    """
    return {"BU_NAME": name, "BU_CDP_URL": f"http://127.0.0.1:{port}"}


def find_chrome() -> str:
    """找 Chrome/Chromium。找不到就报可操作的错，**绝不退化成"用默认浏览器凑合"**。"""
    override = os.environ.get("TTT_CHROME")
    if override and Path(override).exists():
        return override
    for candidate in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ):
        if Path(candidate).exists():
            return candidate
    found = shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    raise RuntimeError("no Chrome/Chromium found; set TTT_CHROME to the executable path")


def _load_harness():
    """导入 browser-harness。

    🔴 调用前必须已经把 `harness_env(...)` 写进 `os.environ`。
    拿到的是**裸 helpers**，不带 run.py 的 tracing —— 所以录制要靠我们自己调
    `recorder.observe`（见 Session._act 的说明）。
    """
    try:
        from browser_harness import helpers, recorder  # noqa: PLC0415
        from browser_harness.admin import ensure_daemon, restart_daemon  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment problem
        raise BrowserHarnessMissing(
            "browser-harness is not installed. Run: uv sync --extra browser"
        ) from exc
    return helpers, recorder, ensure_daemon, restart_daemon


def reap_leaked_browsers(profile_dir: Path) -> int:
    """回收挂在本 profile 上的浏览器实例。返回杀掉的进程数。

    🔴 匹配串必须带键名 user-data-dir= —— 裸 profile 路径会误伤无关进程。
    """
    pattern = f"user-data-dir={profile_dir}"
    try:
        found = subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5
        )
        pids = [p for p in found.stdout.split() if p.isdigit()]
        if pids:
            subprocess.run(["kill", *pids], capture_output=True, timeout=5)
        return len(pids)
    except (subprocess.SubprocessError, OSError):
        return 0


class Session:
    """一次探查/回放单元。用 with 包起来，退出时自己收拾。"""

    def __init__(
        self,
        base_url: str,
        *,
        viewport: tuple[int, int] = DEFAULT_VIEWPORT,
        headed: bool = False,
        allow_hosts: tuple[str, ...] = (),
        profile_dir: Path | None = None,
        timeout: float = 15.0,
    ):
        assert_target_allowed(base_url, allow_hosts)
        self.base_url = base_url.rstrip("/")
        self.viewport = viewport
        self.headed = headed
        self.timeout = timeout
        self._allow_hosts = allow_hosts
        if profile_dir is None:
            profile_dir = (
                Path(tempfile.gettempdir())
                / f"ttt-profile-{os.getpid()}-{next(_PROFILE_SEQ)}"
            )
        self.profile_dir = Path(profile_dir)
        self._daemon_name = f"ttt-{os.getpid()}"
        self._bh = None
        self._restart_daemon = None

    def __enter__(self) -> "Session":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._chrome = subprocess.Popen(          # noqa: S603 - 路径来自我们自己找的
            [find_chrome(), *chrome_launch_args(self.profile_dir, self.headed)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Chrome 自己挑的端口，从它写的 DevToolsActivePort 读回来（没有竞态）。
        # 读不到就直接抛 —— 绝不下沉到"用默认浏览器凑合"。
        try:
            self._port = read_devtools_port(
                self.profile_dir, self._chrome, timeout=self.timeout + 10
            )
        except RuntimeError:
            self._shutdown()
            raise

        # 🔴 顺序不能变：把 BU_NAME/BU_CDP_URL 写进 os.environ **之后**才 import
        #    browser_harness。NAME 是 import 时读一次的，写晚了就挂到用户浏览器上。
        self._daemon_name = f"ttt-{os.getpid()}"
        os.environ.update(harness_env(self._daemon_name, self._port))

        try:
            self._bh, self._recorder, ensure_daemon, restart_daemon = _load_harness()
            self._restart_daemon = restart_daemon
            restart_daemon(name=self._daemon_name)
            ensure_daemon(name=self._daemon_name)
            self._apply_viewport()
        except BaseException:
            self._shutdown()
            raise
        return self

    def _apply_viewport(self) -> None:
        """把视口钉死。

        🔴 这不是"顺手设一下"：编译期的锚点探针按**录制时的坐标**去
        elementFromPoint，两次视口不一致 ⇒ 探针点到的是另一个元素，
        锚点会安在错的元素上，而且看起来一切正常。
        """
        width, height = self.viewport
        self._bh.cdp(
            "Emulation.setDeviceMetricsOverride",
            width=width, height=height, deviceScaleFactor=1, mobile=False,
        )

    def _shutdown(self) -> None:
        """关掉**我们自己起的** Chrome，再回收同 profile 的残留实例。

        🔴 只碰我们自己的：识别串是 `--user-data-dir=<我们的 profile>`。
        用户主 Chrome / 用户正在用的窗口没有这个参数，一个都不许动。
        """
        chrome = getattr(self, "_chrome", None)
        restart_daemon = getattr(self, "_restart_daemon", None)
        if restart_daemon is not None and self._daemon_name:
            restart_daemon(name=self._daemon_name)
            self._restart_daemon = None
        if chrome is not None and chrome.poll() is None:
            chrome.terminate()
            try:
                chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                chrome.kill()
        self._chrome = None
        reap_leaked_browsers(self.profile_dir)

    def __exit__(self, *exc) -> None:
        self._shutdown()

    # —— 录制开关（薄封装，供探索期用）——

    def start_recording(self, name: str, title: str | None = None) -> Path:
        return Path(self._recorder.start_recording(name, title))

    def stop_recording(self) -> Path | None:
        stopped = self._recorder.stop_recording()
        return Path(stopped) if stopped else None

    # —— 导航与交互 ——
    #
    # 🔴 每次动作后必须自己调 recorder.observe：我们导入的是裸 helpers，
    #    没有 run.py 的 _traced 包装，不补这一刀 events.jsonl 永远是空的。
    #    参数形状要照 _traced 的样子（位置参数进 args），因为 recorder._details()
    #    按位置下标取值 —— 写错坐标就会落成 None。
    #    只读调用（js / capture_screenshot / page_info）不调 observe：
    #    recorder.ACTIONS 里也没有它们，调了也只是空转。

    def _act(self, helper: str, *args, **kwargs):
        fn = getattr(self._bh, helper)
        started = time.monotonic()
        result = fn(*args, **kwargs)
        self._recorder.observe(helper, args, kwargs, time.monotonic() - started)
        return result

    def goto(self, path: str) -> None:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        assert_target_allowed(url, self._allow_hosts)
        self._act("new_tab", url)
        self._act("wait_for_load", self.timeout)

    def click_xy(self, x: int, y: int) -> None:
        self._act("click_at_xy", int(x), int(y))

    def click_at_anchor(self, anchor) -> None:
        """Click the center of the element resolved by an anchor."""
        got = self.resolve(anchor)
        snap = got.get("snap")
        if not snap:
            raise AssertionError(
                f"anchor {anchor.by}={anchor.value or anchor.name!r} did not resolve"
            )
        rect = snap.rect or {}
        x = int(rect.get("x", 0)) + int(rect.get("w", 0)) // 2
        y = int(rect.get("y", 0)) + int(rect.get("h", 0)) // 2
        self.click_xy(x, y)

    def click_text(self, text: str) -> None:
        """Click the center of the visible element with this exact text."""
        self.js(LOCATE_HELPERS)
        box = self.js(
            "(()=>{const el=__tttFindByText(" + repr(text) + ");"
            "if(!el)return null;const r=el.getBoundingClientRect();"
            "return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()"
        )
        if not box:
            raise AssertionError(f"no visible element with text {text!r}")
        self.click_xy(int(box["x"]), int(box["y"]))

    def fill(self, selector: str, text: str) -> None:
        self._act("fill_input", selector, text, self.timeout)

    def press(self, key: str) -> None:
        self._act("press_key", key)

    def wait_for(self, selector: str, state: str = "visible") -> None:
        # 🔴 wait_for_element(selector, timeout, visible)：中间那个 timeout 是
        #    位置参数，跳不过去；visible 用关键字传，避免把 True 放到 timeout 位上。
        self._act("wait_for_element", selector, self.timeout, visible=(state == "visible"))

    def js(self, expression: str):
        # 只读，不记账
        return self._bh.js(expression)

    def screenshot(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._bh.capture_screenshot(str(path))
        return path

    # —— 锚点探针（编译期用）——

    def _snapshot_js(self, locate_js: str) -> ElementSnapshot | None:
        """把 __ttt_target 指向某元素，再取快照。"""
        probe = (
            f"(()=>{{ const el = {locate_js}; "
            "window.__ttt_target = el || null; return !!el; })()"
        )
        if not self.js(probe):
            return None
        return ElementSnapshot.from_json(self.js(SNAP_JS))

    def snapshot_at(self, x: int, y: int) -> ElementSnapshot | None:
        """点 (x, y) 会打到哪个元素 —— click_at_xy 的锚点来源。"""
        return self._snapshot_js(
            f"document.elementFromPoint({int(x)}, {int(y)})"
        )

    def snapshot_focused(self) -> ElementSnapshot | None:
        """当前获焦元素 —— type_text / press_key 的锚点来源。"""
        return self._snapshot_js(
            "document.activeElement && document.activeElement !== document.body "
            "? document.activeElement : null"
        )

    # —— 断言期定位（按锚点找元素）——

    def resolve(self, anchor) -> dict:
        """按锚点找元素。返回 {'count': int, 'snap': ElementSnapshot | None, 'drift': str}。

        count > 1 = 判据不唯一（FAIL_ANCHOR）；count == 0 时，copy_sensitive 锚点
        再做一次归一化近似匹配找 drift 候选（→ FAIL_PRODUCT/anchor_drift）。
        """
        from ..compile.anchors import candidates, normalize, similarity  # 避免循环导入

        locate = {
            "testid": f"[...document.querySelectorAll('[data-testid=\"{anchor.value}\"]')]",
            "path": f"[...document.querySelectorAll({anchor.value!r})]",
            "text": f"__tttFindByText({anchor.value!r})",
            "role": f"__tttFindByRole({anchor.role!r}, {anchor.name!r})",
            "xy": None,
        }[anchor.by]

        if anchor.by == "xy":
            x, y = (int(v) for v in anchor.value.split(","))
            snap = self.snapshot_at(x, y)
            return {"count": 1 if snap else 0, "snap": snap, "drift": ""}

        count = int(self.js(LOCATE_HELPERS + f"(()=>{{ const r={locate}; "
                         "return Array.isArray(r) ? r.length : (r ? 1 : 0); })()") or 0)
        if count == 1:
            # Helpers 已在上面那条 count 调用里装好；这里不再拼 LOCATE_HELPERS。
            # 否则 `_snapshot_js` 会把 helpers 的 IIFE 当成 locate 表达式的值
            # （helpers 返回 undefined ⇒ 快照永远为空）。
            return {"count": 1, "snap": self._snapshot_js(
                f"(()=>{{const r={locate}; return Array.isArray(r)?r[0]:r;}})()"), "drift": ""}
        if count > 1:
            return {"count": count, "snap": None, "drift": ""}

        if anchor.copy_sensitive:
            target = anchor.value or anchor.name
            nearby = self.js(LOCATE_HELPERS + "__tttAllLabels()") or []
            best, best_score = "", 0.0
            for label in nearby:
                score = similarity(target, str(label))
                if score > best_score:
                    best, best_score = str(label), score
            if best_score >= 0.7:
                return {"count": 0, "snap": None, "drift": best}
        return {"count": 0, "snap": None, "drift": ""}


# 注入页面的定位辅助函数：文本匹配（归一化后精确）与 role+name 匹配。
LOCATE_HELPERS = r"""
(() => {
  if (window.__tttHelpersInstalled) return;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const IMPLICIT_ROLE = {
    a: 'link', button: 'button', select: 'combobox', textarea: 'textbox',
    nav: 'navigation', main: 'main', header: 'banner', footer: 'contentinfo',
    h1: 'heading', h2: 'heading', h3: 'heading', ul: 'list', li: 'listitem',
    table: 'table', dialog: 'dialog', form: 'form',
  };
  const INPUT_ROLE = { submit: 'button', button: 'button', checkbox: 'checkbox',
                       radio: 'radio', search: 'searchbox' };
  const __tttRoleOf = el => el.getAttribute('role')
    || IMPLICIT_ROLE[el.tagName.toLowerCase()]
    || (el.tagName.toLowerCase() === 'input'
        ? INPUT_ROLE[(el.getAttribute('type') || 'text').toLowerCase()] || ''
        : '');
  window.__tttVisible = el => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  window.__tttFindByText = t => [...document.querySelectorAll('*')]
      .filter(el => window.__tttVisible(el) && norm(el.textContent) === norm(t)
                    && ![...el.children].some(c => norm(c.textContent) === norm(t)))[0] || null;
  window.__tttFindByRole = (role, name) => [...document.querySelectorAll('*')]
      .filter(el => window.__tttVisible(el) && (__tttRoleOf(el) === role)
                    && norm(el.getAttribute('aria-label') || el.textContent) === norm(name));
  window.__tttAllLabels = () => [...document.querySelectorAll('button,a,[role],label,input')]
      .filter(window.__tttVisible)
      .map(el => (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || '').trim())
      .filter(Boolean);
  window.__tttHelpersInstalled = true;
})();
"""

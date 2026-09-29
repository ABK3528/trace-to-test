# trace-to-test 机制组 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在一个全新的私有仓 `trace-to-test` 里跑通「browser-harness 录制 → 编译成声明式回归 → 零 LLM 确定性回放」这条竖切，机制层零业务词，用仓内极简靶场做端到端验收。

**Architecture:** `core/` 分三层：`transcript`（读录制）→ `compile`（带探针回放，把坐标反解成语义锚点）→ `replay`（同一引擎的断言模式，产出三态）。`compile` 与 `replay` **共用同一个步骤执行引擎**，区别只是每个动作执行前是「采集元素快照」还是「按锚点定位并断言」。业务只准活在 `adapters/`。

**Tech Stack:** Python 3.12+（`uv` 管理）、pytest、`browser-harness` 0.1.8（作为依赖，不 fork）、零依赖 `http.server` 靶场。

**Spec:** `docs/trace-to-test-design.md`（在 modelgo 仓；本计划实现其中的「机制组」）

## Global Constraints

- **仓内路径**：本计划所有文件路径都相对**新仓 `trace-to-test/` 的根**，不是 modelgo 仓。modelgo 仓只用来放这份计划与 spec。
- **零业务词**：`core/` `checks/` `skills/` 下不得出现任何具体项目/平台/真源名（服务名、URL、租户概念、模型名、具体仓库 ID）。`scripts/portability_check.sh` 扫这三处，零命中才算过。
- **依赖方向**：`core/` 不得 import `target_app/`、不得 import `adapters/`。靶场只能被 `tests/` 与 `make demo` 使用。
- **回放零 LLM**：`core/replay/` 与 `core/compile/` 里不得出现任何模型调用或网络 LLM 请求。
- **浏览器依赖**：只用 `browser_harness`（`from browser_harness import helpers as bh`、`from browser_harness.admin import ensure_daemon`），版本锁 `0.1.8`。不直接调 playwright/selenium。
- **不新增常驻服务**：唯一允许的长驻进程是本地的靶场 `http.server`（仅 tests/demo 用，随跑随停）。
- **Python 版本**：`>=3.12`（`uv` 默认；本机 3.14 也可）。
- **提交粒度**：每个 Task 末尾提交一次。这是全新的空仓，前几个 Task 直接提交到 `main`；从 Task 5 起如无特殊说明仍提交 `main`（尚无 PR 流程）。

---

## 文件结构（先定边界，再排任务）

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 包元数据、依赖（`browser-harness==0.1.8` 可选、pytest dev） |
| `Makefile` | `demo` / `test` / `lint` / `portability` 四个入口 |
| `scripts/portability_check.sh` | 扫 `core/ checks/ skills/`，读 `scripts/business_words.txt` + `scripts/portability_whitelist.txt` |
| `scripts/business_words.txt` | 禁用词表（数据，一行一条，`#` 注释） |
| `target_app/serve.py` | 零依赖 `http.server`，带三态试验开关 |
| `target_app/pages/*.html` | 靶场页面（登录 / 异步列表 / 弹窗 / 暗色） |
| `core/transcript/recording.py` | 读 `meta.json` + `events.jsonl` → `Recording` / `TraceEvent` |
| `core/compile/anchors.py` | **纯函数**：元素快照 → 候选锚点排序；锚点归一化近似匹配 |
| `core/compile/compiler.py` | 编排「带探针回放」，产出 `workflow.json` + `unresolved.jsonl` |
| `core/compile/schema.py` | `Workflow` / `Step` / `Anchor` / `Unresolved` 的 dataclass + JSON 往返 |
| `core/replay/engine.py` | 步骤执行引擎（两种模式：probe / assert） |
| `core/replay/result.py` | 三态 + `reason` 的结果模型 |
| `core/replay/preflight.py` | 假红自查：STALE_TARGET / COLD_START_FLAKE / FAIL_ENV |
| `core/primitives/session.py` | 浏览器会话：`ensure_daemon`、专用 profile、环境闸、泄漏回收 |
| `core/primitives/probe.py` | 注入页面取元素快照的 JS + 解析 |
| `core/lint/checks_lint.py` | `checks.json` 校验：拒无断言、拒 `source` 缺失或 `observed:*` |
| `checks/evidence_shape.py` | 五道闸里可机械化的字段存在性检查（闸②④） |
| `tests/fixtures/recordings/` | 进仓的固定录制样本（不依赖现场录制） |

---

## Task 1: 仓骨架 + 可移植性闸

**Files:**
- Create: `pyproject.toml`, `Makefile`, `README.md`, `.gitignore`, `conftest.py`
- Create: `scripts/portability_check.sh`, `scripts/business_words.txt`, `scripts/portability_whitelist.txt`
- Create: `core/__init__.py`（及 `core/{transcript,compile,replay,primitives,lint}/__init__.py` 空文件）
- Test: `tests/test_portability_check.py`

**Interfaces:**
- Consumes: 无（第一个 Task）
- Produces: `scripts/portability_check.sh`（退出码 0 = 零命中，1 = 有命中，2 = 配置错误或"扫了个寂寞"——空词表 / 零扫描目录 / grep 出错）、`make portability`

- [ ] **Step 1: 建私有仓**

🔴 **在 `~/code` 下建，不要在 modelgo 仓里建** —— 否则新仓会嵌进 modelgo 仓的目录树里：

```bash
cd ~/code
gh repo create trace-to-test --private --description "Business-agnostic AI testing framework: record a browser session, compile it into a declarative regression, replay it deterministically with zero LLM." --clone
cd ~/code/trace-to-test
git commit --allow-empty -m "chore: init"
```

**从这一步起，本计划里的所有相对路径都以 `~/code/trace-to-test` 为根。**

- [ ] **Step 2: 写禁用词表**

`scripts/business_words.txt` —— 数据文件，一行一条，`#` 开头是注释。**这是唯一允许出现业务词的地方**（因此它不在扫描面内）：

```
# 一行一个禁用词（大小写不敏感，按整词匹配）。
# 新项目落地时把这里换成你自己的业务词表。
modelgo
model-gateway
fakellm
observer
# 概念词：这些概念在机制层必须用中性名（例如「租户池」→「资源租约池」）
tenant
租户
```

- [ ] **Step 3: 写白名单**

`scripts/portability_whitelist.txt` —— 每行 `<路径正则>\t<词正则>\t<理由>`（`#` 开头是注释）。
豁免的是**某个文件里的某个词**这个二元组，**不是整行**。

🔴 **为什么不豁免整行**：整行豁免会连同行的其它禁用词一起放过 ——
一行 `# <target> 相关的 modelgo 迁移说明` 就会带着 `modelgo` 一起溜过去。
豁免粒度必须是 (文件, 词)，新增一条等于放宽约束，必须在 MR 里说明理由。

```
# 路径正则<TAB>词正则<TAB>理由（制表符分隔，三列都要有）
core/primitives/host_gate\.py<TAB>tenant<TAB>该文件专门讨论"租户"这个概念的中性化命名，词只出现在注释里
```

初始可以是**空表**（只有注释行）—— 空的含义是"什么都不豁免"，不是"闸没在守"。

- [ ] **Step 4: 写自检脚本**

`scripts/portability_check.sh`：

```bash
#!/usr/bin/env bash
# 扫机制层（core/ checks/ skills/），出现禁用词即失败。
# 退出码：0 = 零命中；1 = 有命中；2 = 配置/用法错误（含"扫了个寂寞"）。
#
# 🔴 四条 fail-open 路径必须堵死，否则这个闸会安静地绿：
#   ① 词表为空            → 闸没在守任何东西
#   ② 一个扫描目录都没有   → 脚本指错了地方（不是"干净"）
#   ③ grep 出错被 || true 吞 → 把"搜失败"当成"没搜到"
#   ④ 白名单列错位         → 空正则匹配一切，静默豁免整个文件
# 还有一条：白名单只豁免 (文件, 词) 二元组，绝不豁免整行。
set -euo pipefail
cd "$(dirname "$0")/.."

WORDS="scripts/business_words.txt"
WHITELIST="scripts/portability_whitelist.txt"
SCAN_DIRS=(core checks skills)

[[ -f "$WORDS" ]] || { echo "missing $WORDS" >&2; exit 2; }
[[ -f "$WHITELIST" ]] || { echo "missing $WHITELIST" >&2; exit 2; }

existing=()
for d in "${SCAN_DIRS[@]}"; do [[ -d "$d" ]] && existing+=("$d"); done
[[ ${#existing[@]} -gt 0 ]] || {
  echo "none of ${SCAN_DIRS[*]} exist — wrong tree?" >&2; exit 2; }

pattern=$(grep -vE '^[[:space:]]*(#|$)' "$WORDS" | paste -sd'|' -)
[[ -n "$pattern" ]] || {
  echo "$WORDS has no terms — the gate would pass vacuously" >&2; exit 2; }

HITS=$(mktemp); WINPUT=$(mktemp); KEPT=$(mktemp)
trap 'rm -f "$HITS" "$WINPUT" "$KEPT"' EXIT

# ——— 白名单：严格校验 + 归一化 ———
# 🔴 不能用 `read` + IFS=$'\t' 做列校验：tab 属于 IFS 的"空白类"，bash 会把
#    **连续的 tab 折叠成一个**，空列被静默吞掉、后面的列整体左移。实测
#    `core/a.py<TAB><TAB>.*<TAB>reason` 读成 path=core/a.py term=.* reason=reason
#    —— term 成了 `.*` 匹配一切 ⇒ 静默豁免该文件的所有命中。
#    awk 的单字符 FS 按字面切、不折叠，看得见空字段，所以校验交给 awk。
awk -F'\t' -v out="$WINPUT" '
  /^[[:space:]]*(#|$)/ { next }
  NF != 3 {
    printf "whitelist line %d: need exactly 3 tab-separated columns (path<TAB>term<TAB>reason), got %d\n", NR, NF > "/dev/stderr"
    bad = 1; next
  }
  $1 == "" || $2 == "" || $3 == "" {
    printf "whitelist line %d: empty column\n", NR > "/dev/stderr"
    bad = 1; next
  }
  { print > out }
  END { exit bad ? 1 : 0 }
' "$WHITELIST" || exit 2

# 正则合法性 + "不许匹配一切"。
# bash 的 =~ 遇到非法正则只静默不匹配、不报错，所以借 grep 的退出码判：
# 对**空输入**跑一次，1 = 合法且不匹配空串（我们要的）；0 = 匹配空串；
# 2 = 非法正则。0 这种也要拒 —— 能匹配空串的正则（`.*`、`a*`）会豁免一切，
# 和空列是同一类漏法。
check_re() {
  local re="$1" label="$2" rc
  set +e
  printf '' | grep -qE -- "$re" 2>/dev/null
  rc=$?
  set -e
  case $rc in
    1) return 0 ;;
    0) echo "whitelist $label matches the empty string ($re) — it would exempt everything" >&2; exit 2 ;;
    *) echo "whitelist $label is not a valid regex ($re)" >&2; exit 2 ;;
  esac
}

while IFS=$'\t' read -r path_re term_re _reason; do
  [[ -z "$path_re" ]] && continue
  check_re "$path_re" "path regex"
  check_re "$term_re" "term regex"
done < "$WINPUT"

# ——— 扫描 ———
set +e
grep -rHoEn -i "\b(${pattern})\b" "${existing[@]}" > "$HITS" 2>/dev/null
rc=$?
set -e
[[ $rc -le 1 ]] || { echo "grep failed with exit $rc" >&2; exit 2; }

if [[ ! -s "$HITS" ]]; then
  echo "✅ portability check passed (${existing[*]})"
  exit 0
fi

# ——— 逐条套白名单（只豁免 (文件, 词) 二元组）———
while IFS= read -r hit; do
  [[ -z "$hit" ]] && continue
  file=${hit%%:*}; rest=${hit#*:}; term=${rest#*:}
  exempt=0
  while IFS=$'\t' read -r path_re term_re _reason; do
    [[ -z "$path_re" ]] && continue
    if [[ "$file" =~ $path_re ]] && [[ "$term" =~ $term_re ]]; then exempt=1; break; fi
  done < "$WINPUT"
  [[ $exempt -eq 1 ]] || printf '%s\n' "$hit" >> "$KEPT"
done < "$HITS"

if [[ -s "$KEPT" ]]; then
  echo "🔴 portability check FAILED — 机制层出现业务词：" >&2
  cat "$KEPT" >&2
  exit 1
fi
echo "✅ portability check passed (${existing[*]})"
```

- [ ] **Step 5: 写失败测试（先红）**

`tests/test_portability_check.py`：

```python
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "portability_check.sh"


def run_check() -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)


def _fake_repo(tmp_path: Path, *, words: str, dirs: list[str]) -> Path:
    """在临时目录里搭一个最小"仓"，用来测脚本自身的配置错误分支。"""
    (tmp_path / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "scripts" / "portability_check.sh")
    (tmp_path / "scripts" / "business_words.txt").write_text(words, encoding="utf-8")
    (tmp_path / "scripts" / "portability_whitelist.txt").write_text(
        "# path-regex\tterm-regex\treason\n", encoding="utf-8")
    for d in dirs:
        (tmp_path / d).mkdir()
    return tmp_path


def _run_in(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "portability_check.sh")],
        cwd=repo, capture_output=True, text=True,
    )


# —— 主路径 ——

def test_passes_on_clean_tree():
    assert run_check().returncode == 0


def test_fails_when_a_business_word_is_injected():
    planted = ROOT / "core" / "_planted_business_word.py"
    planted.write_text("SERVICE = 'modelgo'\n", encoding="utf-8")
    try:
        result = run_check()
        assert result.returncode == 1
        assert "portability check FAILED" in result.stderr
        assert "_planted_business_word.py" in result.stderr
    finally:
        planted.unlink()


def test_whitelisted_placeholder_is_allowed():
    planted = ROOT / "core" / "_planted_placeholder.py"
    planted.write_text("TARGET = '<target>'\n", encoding="utf-8")
    try:
        assert run_check().returncode == 0
    finally:
        planted.unlink()


# —— 🔴 白名单不许退化成"整行豁免" ——

def test_a_line_carrying_both_a_placeholder_and_a_business_word_is_still_a_hit():
    """整行豁免的经典漏法：占位符把同行的业务词一起带过去。"""
    planted = ROOT / "core" / "_planted_mixed.py"
    planted.write_text("TARGET = '<target>'  # never say modelgo here\n", encoding="utf-8")
    try:
        result = run_check()
        assert result.returncode == 1
        assert "modelgo" in result.stderr
    finally:
        planted.unlink()


def test_a_whitelisted_file_and_term_pair_is_exempt(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "allowed.py").write_text("# modelgo, discussed here on purpose\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/allowed\\.py\tmodelgo\tthis file discusses the neutral rename\n", encoding="utf-8")
    assert _run_in(repo).returncode == 0


def test_the_whitelist_does_not_exempt_the_same_term_in_a_different_file(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "allowed.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "core" / "other.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/allowed\\.py\tmodelgo\texempt only this file\n", encoding="utf-8")
    result = _run_in(repo)
    assert result.returncode == 1
    assert "other.py" in result.stderr


# —— 🔴 三条 fail-open 路径 ——

def test_no_scan_directory_at_all_is_a_configuration_error(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=[])
    result = _run_in(repo)
    assert result.returncode == 2
    assert "wrong tree" in result.stderr


def test_an_empty_word_list_is_a_configuration_error(tmp_path):
    repo = _fake_repo(tmp_path, words="# nothing but comments\n", dirs=["core"])
    result = _run_in(repo)
    assert result.returncode == 2
    assert "vacuous" in result.stderr


def test_a_two_column_whitelist_row_is_a_configuration_error(tmp_path):
    """空词正则匹配一切 —— 少一列就是静默豁免整文件，必须报错。"""
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "a.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/a\\.py\tmodelgo\n", encoding="utf-8")           # 只有两列
    result = _run_in(repo)
    assert result.returncode == 2
    assert "3 tab-separated columns" in result.stderr


def test_an_invalid_whitelist_regex_is_a_configuration_error(tmp_path):
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "a.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/a\\.py\t[unclosed\tbroken regex\n", encoding="utf-8")
    result = _run_in(repo)
    assert result.returncode == 2
    assert "not a valid regex" in result.stderr


def test_a_whitelist_row_with_an_empty_middle_column_is_a_configuration_error(tmp_path):
    """回归：bash 的 read + IFS=$'\t' 会折叠连续 tab（tab 属空白类），
    空列被静默吞掉、后面的列整体左移 —— 实测 term 会变成 `.*` 从而豁免一切。
    所以列校验必须交给 awk（单字符 FS 按字面切），这条测试就是钉死这一点。"""
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "a.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/a\\.py\t\t.*\treason\n", encoding="utf-8")     # 中间列是空的
    result = _run_in(repo)
    assert result.returncode == 2
    assert "empty column" in result.stderr


def test_a_term_regex_that_matches_the_empty_string_is_rejected(tmp_path):
    """能匹配空串的正则（.* / a*）会豁免一切，和空列是同一类漏法。"""
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    (repo / "core" / "a.py").write_text("# modelgo\n", encoding="utf-8")
    (repo / "scripts" / "portability_whitelist.txt").write_text(
        "core/a\\.py\t.*\texempts everything\n", encoding="utf-8")
    result = _run_in(repo)
    assert result.returncode == 2
    assert "matches the empty string" in result.stderr


def test_a_partial_set_of_scan_dirs_is_fine(tmp_path):
    """分阶段落地：只存在 core/ 是合法的，不该报错。"""
    repo = _fake_repo(tmp_path, words="modelgo\n", dirs=["core"])
    assert _run_in(repo).returncode == 0
```

- [ ] **Step 6: 跑测试确认当前状态**

Run: `uv run pytest tests/test_portability_check.py -v`
Expected: `test_passes_on_clean_tree` PASS（此时 core/ 是空的）；其余两条要等实现齐全后才有意义 —— 先确认整文件能跑起来、无 collection error。

- [ ] **Step 7: 补齐包结构与构建文件**

`pyproject.toml`：

```toml
[project]
name = "trace-to-test"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
browser = ["browser-harness==0.1.8"]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["core", "checks", "target_app", "demo"]
```

`conftest.py`（仓库根，**空文件**）：让 pytest 把仓库根放进 `sys.path`，这样
`uv run pytest` 与直接 `python -m demo.run` 都能 import 到 `core` / `checks` / `target_app` / `demo`。
同时 `pyproject.toml` 的 `packages` 已把四个包都列进 wheel，`uv sync` 后也可正常 import。

`Makefile`（🔴 制表符缩进，不是空格）：

```make
.PHONY: test portability lint demo

test:
	uv run pytest tests/ -v

portability:
	bash scripts/portability_check.sh

lint: portability
	uv run python -m core.lint.checks_lint --help >/dev/null

demo:
	uv run python -m demo.run
```

`core/` 下建 5 个子包，每个放一个空的 `__init__.py`：`transcript` / `compile` / `replay` / `primitives` / `lint`。注意 `core/compile` 与内置 `compile()` 同名，**只能作为包路径使用，不要在模块里 `import compile`**。

- [ ] **Step 8: 跑全部测试确认通过**

Run: `bash scripts/portability_check.sh && uv run pytest tests/test_portability_check.py -v`
Expected: 三条全 PASS，脚本输出 `✅ portability check passed (core)`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore: repo skeleton + portability gate (mechanism layer must stay business-free)"
```

---

## Task 2: 靶场 target-app

> ⚠️ **后来追加的差量，由 Task 10 携带，不在本 Task 的实现范围内。**
> `/__demo__/shift-layout` 位移开关（`_state["shift_dy"]`、`{{SHIFT_STYLE}}` 占位符、端点，
> 以及 `test_shift_layout_pushes_the_content_down`）是本 Task **合并之后**才为 Task 10 的
> V2b 验收加上的。本 Task 的代码已进 main、不含它；那段改动落在 Task 10。

**Files:**
- Create: `target_app/__init__.py`, `target_app/serve.py`
- Create: `target_app/pages/login.html`, `target_app/pages/list.html`
- Test: `tests/test_target_app.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `target_app.serve.serve(port: int = 0, ttl_seconds: float | None = None) -> ServerHandle`，`ServerHandle` 有 `.base_url: str`、`.port: int`、`.stop() -> None`
  - `serve()` 支持 `--ttl` 秒后自动退出（防测试挂死）
  - 三态试验开关（**只在靶场里，机制层不知道它存在**）：
    - `POST /__demo__/copy-mode` body `{"mode": "spec"|"drifted"}` —— 切文案
    - `POST /__demo__/strip-testids` body `{"strip": true|false}` —— 摘掉 testid
  - `GET /healthz` → `{"build": "<hash>", "ready": true}`（给假红自查用）

- [ ] **Step 1: 写失败测试**

`tests/test_target_app.py`：

```python
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

        _post(f"{srv.base_url}/__demo__/strip-testids", {"strip": False})
        with urllib.request.urlopen(f"{srv.base_url}/list", timeout=5) as r:
            plain = r.read().decode()
        assert 'data-strip-testids="false"' in plain
        assert 'data-testid="item-list"' in plain


def test_shift_layout_pushes_the_content_down():
    """位移开关本身要能验：它是"回放走锚点"那条验收的载体。"""
    with serve() as srv:
        _post(f"{srv.base_url}/__demo__/shift-layout", {"dy": 120})
        with urllib.request.urlopen(f"{srv.base_url}/login", timeout=5) as r:
            assert "margin-top:120px" in r.read().decode()


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_target_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'target_app'`

- [ ] **Step 3: 实现靶场**

`target_app/serve.py`（零依赖；页面放 `target_app/pages/`）：

```python
"""零依赖靶场：给机制层提供一个稳定、离线、可开关的被测目标。

机制层不知道本文件存在（依赖方向：core/ 不 import target_app）。
三态验收靠这里的两个开关制造：copy-mode 改文案（→ FAIL_PRODUCT/anchor_drift），
strip-testids 摘掉稳定钩子（→ FAIL_ANCHOR）。
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGES = Path(__file__).resolve().parent / "pages"
BUILD = "demo-build-1"

SPEC_COPY = "登 录"
DRIFTED_COPY = "立即登录"

_state = {"copy_mode": "spec", "strip_testids": False, "shift_dy": 0}


def _render(name: str) -> str:
    html = (PAGES / name).read_text(encoding="utf-8")
    label = SPEC_COPY if _state["copy_mode"] == "spec" else DRIFTED_COPY
    html = html.replace("{{LOGIN_LABEL}}", label)
    # 🔴 strip 开关必须同时告诉页面脚本：列表行是 JS 运行时创建的，
    #    服务端正则只扫得到服务端渲染出来的那部分 —— 不告诉脚本，
    #    strip 就只是"半生效"，而半生效的开关会让验收为错的原因通过。
    html = html.replace("{{STRIP_TESTIDS}}", "true" if _state["strip_testids"] else "false")
    # 🔴 布局位移：把整页内容往下推 dy 像素，录制里的坐标随即全部失效。
    #    这个开关存在的唯一理由，是让"回放走的是锚点还是坐标"变成可观测的 ——
    #    若回放按坐标走，位移后必然点在空处、回放失败。
    html = html.replace("{{SHIFT_STYLE}}", f"body{{margin-top:{int(_state['shift_dy'])}px}}")
    if _state["strip_testids"]:
        html = re.sub(r'\sdata-testid="[^"]*"', "", html)
    return html


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音，避免污染测试输出
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._json({"build": BUILD, "ready": True})
        if path in ("/", "/login"):
            return self._send(200, _render("login.html").encode())
        if path == "/list":
            return self._send(200, _render("list.html").encode())
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        path = self.path.split("?", 1)[0]
        if path == "/__demo__/copy-mode":
            _state["copy_mode"] = payload.get("mode", "spec")
            return self._json({"ok": True, "state": _state})
        if path == "/__demo__/strip-testids":
            _state["strip_testids"] = bool(payload.get("strip"))
            return self._json({"ok": True, "state": _state})
        if path == "/__demo__/shift-layout":
            _state["shift_dy"] = int(payload.get("dy") or 0)
            return self._json({"ok": True, "state": _state})
        return self._json({"error": "unknown"}, 404)


class ServerHandle:
    def __init__(self, httpd: ThreadingHTTPServer, thread: threading.Thread):
        self._httpd, self._thread = httpd, thread
        self.port: int = httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> "ServerHandle":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


def serve(port: int = 0, ttl_seconds: float | None = None) -> ServerHandle:
    """起靶场。返回的 handle **本身就是上下文管理器**，所以两种用法都对：

        with serve() as srv: ...        # 退出时自动停
        srv = serve(); ...; srv.stop()  # 手动停

    🔴 不要写成 @contextmanager 的生成器：那样 serve() 返回的是上下文管理器对象，
    不是 handle，`srv = serve(); srv.base_url` 会 AttributeError —— 接口声明的是
    返回 ServerHandle，就真的返回它。（ServerHandle 已经有 __enter__/__exit__。）
    """
    _state.update({"copy_mode": "spec", "strip_testids": False, "shift_dy": 0})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    handle = ServerHandle(httpd, thread)
    if ttl_seconds:
        timer = threading.Timer(ttl_seconds, handle.stop)
        timer.daemon = True
        timer.start()
    return handle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8712)
    ap.add_argument("--ttl", type=float, default=None, help="秒；到点自动退出，防挂死")
    args = ap.parse_args()
    start = time.time()
    with serve(port=args.port, ttl_seconds=args.ttl) as srv:
        print(f"target-app on {srv.base_url}", flush=True)
        while True:
            time.sleep(0.5)
            if args.ttl and time.time() - start > args.ttl:
                break


if __name__ == "__main__":
    main()
```

`target_app/pages/login.html`：

```html
<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>Sign in</title>
<style>{{SHIFT_STYLE}}</style></head>
<body>
  <form data-testid="login-form">
    <label for="username">Username</label>
    <input id="username" name="username" type="text">
    <label for="password">Password</label>
    <input id="password" name="password" type="password">
    <button type="button" id="submit-login" onclick="location.href='/list'">{{LOGIN_LABEL}}</button>
  </form>
  <p id="error" hidden>Invalid credentials</p>
</body></html>
```

`target_app/pages/list.html`：一个**异步加载**的列表 + 一个弹窗触发按钮 + 暗色模式跟随（`prefers-color-scheme`）。

```html
<!doctype html>
<html lang="zh" data-strip-testids="{{STRIP_TESTIDS}}"><head><meta charset="utf-8"><title>Items</title>
<style>{{SHIFT_STYLE}}</style>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui; }
  #items li { padding: 4px 0; }
  dialog::backdrop { background: rgba(0,0,0,.4); }
</style></head>
<body>
  <h1>Items</h1>
  <button id="open-create" onclick="document.getElementById('dlg').showModal()">新建</button>
  <dialog id="dlg" data-testid="create-dialog">
    <form method="dialog"><p>Create a new item?</p>
      <button id="confirm-create" data-testid="confirm-create">确定</button></form>
  </dialog>
  <ul id="items" data-testid="item-list"></ul>
  <script>
    // 异步加载：给回放引擎的 settle 留出真实的"数据还没到"窗口。
    // 🔴 加载完成时打一个 data-loaded 哨兵：`#items` 这个容器一开始就在 DOM 里，
    //    wait_for 它等于没等 —— 行还没到就往下走，count 断言必然随机红。
    //    探索脚本必须等 [data-loaded="true"]，它才真的代表"数据到了"。
    // 🔴 行钩子（item-row）也受 strip 开关管：这些 li 是运行时创建的，
    //    服务端的正则扫不到，必须在这里读同一个开关。
    const STRIP = document.documentElement.dataset.stripTestids === 'true';
    setTimeout(() => {
      const ul = document.getElementById('items');
      ['Alpha', 'Beta', 'Gamma'].forEach(name => {
        const li = document.createElement('li');
        li.textContent = name;
        if (!STRIP) li.dataset.testid = 'item-row';
        ul.appendChild(li);
      });
      ul.dataset.loaded = 'true';
    }, 600);
  </script>
</body></html>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_target_app.py -v`
Expected: 6 passed

- [ ] **Step 5: 人工看一眼靶场**

Run: `uv run python -m target_app.serve --ttl 10`
Expected: 打印 `target-app on http://127.0.0.1:8712`，10 秒后自己退出

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(target-app): zero-dep demo target with copy/strip-testid switches for three-state acceptance"
```

---

## Task 3: transcript 层 —— 读录制

**Files:**
- Create: `core/transcript/__init__.py`, `core/transcript/recording.py`
- Create: `tests/fixtures/recordings/smoke-login/meta.json`, `tests/fixtures/recordings/smoke-login/events.jsonl`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `core.transcript.recording.TraceEvent`（frozen dataclass）：`seq: int`、`ts: float`、`helper: str`、`url: str`、`title: str`、`viewport: tuple[int, int] | None`、`box: dict | None`、`input_type: str`、`frame: str`、`detail: dict[str, object]`
  - `core.transcript.recording.Recording`（frozen dataclass）：`name: str`、`title: str`、`started: float`、`events: tuple[TraceEvent, ...]`，方法 `actionable() -> tuple[TraceEvent, ...]`（只留 `ACTIONS` 里的）
  - `core.transcript.recording.load_recording(path: Path | str) -> Recording`
  - `core.transcript.recording.ACTION_EVENTS: frozenset[str]`

**Schema 事实（来自 browser-harness 0.1.8 `recorder.py`，禁止凭记忆改）**：每行一个 JSON 对象，`helper` 字段是动作名，另有 `ts`、`url`、`title`、`w`/`h`（viewport）、`box`（**activeElement** 的框，不是被点中的元素）、`input`（activeElement 的 `type`/`tagName`，小写）、`frame`（截图文名），以及按 helper 不同而不同的明细字段：`click_at_xy`→`x`,`y`；`scroll`→`x`,`y`,`dy`,`dx`；`goto_url`/`new_tab`→`to`；`type_text`→`text`；`fill_input`→`selector`,`text`；`press_key`→`key`；`dispatch_key`→`selector`,`key`；`wait_for_element`→`selector`。URL 里的凭据已被上游 scrub 成 `REDACTED`。密码框的 `text` 已被上游替换成 `•`。

- [ ] **Step 1: 造进仓的固定录制样本**

`tests/fixtures/recordings/smoke-login/meta.json`：

```json
{"name": "smoke-login", "title": "登录并打开新建弹窗", "started": 1759000000.0}
```

`tests/fixtures/recordings/smoke-login/events.jsonl`（每行一个对象；这是**唯一**要跟着 browser-harness 版本走的样本，上游升级格式时改这里让测试红）：

```jsonl
{"ts": 1759000000.1, "helper": "new_tab", "to": "http://127.0.0.1:8712/login", "url": "http://127.0.0.1:8712/login", "title": "Sign in", "w": 1440, "h": 900, "sx": 0, "sy": 0, "dpr": 2, "frame": "0001.jpg"}
{"ts": 1759000000.6, "helper": "wait_for_load", "url": "http://127.0.0.1:8712/login", "title": "Sign in", "w": 1440, "h": 900, "sx": 0, "sy": 0, "dpr": 2, "frame": "0002.jpg"}
{"ts": 1759000001.2, "helper": "fill_input", "selector": "#username", "text": "demo", "url": "http://127.0.0.1:8712/login", "title": "Sign in", "w": 1440, "h": 900, "sx": 0, "sy": 0, "dpr": 2, "input": "text", "box": {"x": 40, "y": 60, "w": 240, "h": 28}, "frame": "0003.jpg"}
{"ts": 1759000001.8, "helper": "click_at_xy", "x": 120, "y": 168, "url": "http://127.0.0.1:8712/login", "title": "Sign in", "w": 1440, "h": 900, "sx": 0, "sy": 0, "dpr": 2, "input": "button", "box": {"x": 40, "y": 156, "w": 90, "h": 30}, "frame": "0004.jpg"}
{"ts": 1759000003.0, "helper": "wait_for_element", "selector": "#items", "url": "http://127.0.0.1:8712/list", "title": "Items", "w": 1440, "h": 900, "sx": 0, "sy": 0, "dpr": 2, "frame": "0005.jpg"}
{"ts": 1759000003.6, "helper": "click_at_xy", "x": 88, "y": 72, "url": "http://127.0.0.1:8712/list", "title": "Items", "w": 1440, "h": 900, "sx": 0, "sy": 0, "dpr": 2, "input": "button", "box": {"x": 60, "y": 60, "w": 56, "h": 24}, "frame": "0006.jpg"}
{"ts": 1759000004.0, "helper": "click_at_xy", "x": 210, "y": 260, "url": "http://127.0.0.1:8712/list", "title": "Items", "w": 1440, "h": 900, "sx": 0, "sy": 0, "dpr": 2, "input": "dialog", "box": {"x": 180, "y": 240, "w": 120, "h": 40}, "frame": "0007.jpg"}
```

- [ ] **Step 2: 写失败测试**

`tests/test_transcript.py`：

```python
from pathlib import Path

import pytest

from core.transcript.recording import ACTION_EVENTS, load_recording

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "smoke-login"


def test_loads_meta_and_all_events():
    rec = load_recording(FIXTURE)
    assert rec.name == "smoke-login"
    assert rec.title == "登录并打开新建弹窗"
    assert len(rec.events) == 7


def test_events_are_sequenced_in_file_order():
    rec = load_recording(FIXTURE)
    assert [e.seq for e in rec.events] == list(range(7))
    assert rec.events[0].helper == "new_tab"
    assert rec.events[-1].helper == "click_at_xy"


def test_viewport_and_box_are_parsed():
    rec = load_recording(FIXTURE)
    first = rec.events[0]
    assert first.viewport == (1440, 900)
    assert rec.events[2].box == {"x": 40, "y": 60, "w": 240, "h": 28}


def test_helper_specific_details_land_in_detail():
    rec = load_recording(FIXTURE)
    assert rec.events[0].detail == {"to": "http://127.0.0.1:8712/login"}
    assert rec.events[2].detail == {"selector": "#username", "text": "demo"}
    assert rec.events[3].detail == {"x": 120, "y": 168}


def test_actionable_keeps_every_upstream_action_helper():
    """actionable() 的判据就是 browser-harness 的 ACTIONS —— 连等待类也算"动作"。

    🔴 "哪些事件能产步骤"是**编译器**的事（它有自己的 EVENT_TO_ACTION 映射），
    不在这一层过滤：在这一层过滤会让 transcript 反过来依赖 compile 的映射表，
    层次就反了。fixture 里 7 条事件全部都在 ACTIONS 里，所以这里断言 7。
    """
    rec = load_recording(FIXTURE)
    helpers = [e.helper for e in rec.actionable()]
    assert len(helpers) == 7
    assert "wait_for_load" in helpers
    assert helpers.count("click_at_xy") == 3


def test_probe_targets_are_the_events_that_need_a_browser_probe():
    """真正必须问浏览器"这是哪个元素"的只有三类：点击、输入、按键。"""
    rec = load_recording(FIXTURE)
    assert [e.helper for e in rec.probe_targets()] == ["click_at_xy"] * 3


def test_action_events_matches_browser_harness_contract():
    # 这份集合必须与 browser-harness 0.1.8 recorder.ACTIONS 一致；
    # 上游升级改动它时，这里先红，逼人去看 changelog。
    assert ACTION_EVENTS == {
        "goto_url", "click_at_xy", "type_text", "fill_input", "press_key",
        "scroll", "dispatch_key", "upload_file", "new_tab", "switch_tab",
        "close_tab", "ensure_real_tab",
        "wait", "wait_for_load", "wait_for_element", "wait_for_network_idle",
    }


def test_missing_recording_raises_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="events.jsonl"):
        load_recording(tmp_path / "nope")


def test_blank_lines_are_skipped(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "meta.json").write_text('{"name": "r", "title": "", "started": 0.0}', encoding="utf-8")
    (d / "events.jsonl").write_text(
        '{"helper": "wait_for_load", "w": 800, "h": 600}\n\n{"helper": "scroll", "x": 1, "y": 2}\n',
        encoding="utf-8",
    )
    rec = load_recording(d)
    assert [e.helper for e in rec.events] == ["wait_for_load", "scroll"]
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_transcript.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.transcript.recording'`

- [ ] **Step 4: 实现**

`core/transcript/recording.py`：

```python
"""读 browser-harness 的录制目录，归一化成事件流。

录制目录的形态（browser-harness 0.1.8）：
    meta.json     {name, title, started}
    events.jsonl  每行一个动作；字段见本模块 DETAIL_KEYS
    0001.jpg ...  每个动作之后的一帧截图

本模块只做「读 + 归一化」，不做任何锚点推断（那是 core/compile 的事）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# 与 browser-harness 0.1.8 recorder.ACTIONS 对齐。测试里有一份逐字断言，
# 上游升级改动它时先红再改。
ACTION_EVENTS: frozenset[str] = frozenset({
    "goto_url", "click_at_xy", "type_text", "fill_input", "press_key",
    "scroll", "dispatch_key", "upload_file", "new_tab", "switch_tab",
    "close_tab", "ensure_real_tab",
    "wait", "wait_for_load", "wait_for_element", "wait_for_network_idle",
})

# 每个 helper 的明细字段名 —— 从事件对象里摘出来放进 detail，
# 让上层按动作类型取值时不必在一大坨字段里翻。
DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    "click_at_xy": ("x", "y"),
    "scroll": ("x", "y", "dy", "dx"),
    "goto_url": ("to",),
    "new_tab": ("to",),
    "type_text": ("text",),
    "fill_input": ("selector", "text"),
    "press_key": ("key",),
    "dispatch_key": ("selector", "key"),
    "wait_for_element": ("selector",),
}

_CTX_KEYS = ("url", "title", "box", "frame")


@dataclass(frozen=True)
class TraceEvent:
    seq: int
    ts: float
    helper: str
    url: str = ""
    title: str = ""
    viewport: tuple[int, int] | None = None
    box: dict | None = None
    input_type: str = ""
    frame: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def is_action(self) -> bool:
        return self.helper in ACTION_EVENTS

    def xy(self) -> tuple[int, int] | None:
        """点击/滚动的坐标，没有就 None。"""
        x, y = self.detail.get("x"), self.detail.get("y")
        return (int(x), int(y)) if x is not None and y is not None else None

    def needs_probe(self) -> bool:
        """是否必须靠编译期探针才能拿到目标元素（见 spec §4.2 鸿沟一）。

        click_at_xy / type_text / press_key 的落点元素不在事件里；
        其余动作要么带 URL、要么带 selector，能直接推出步骤。
        """
        return self.helper in ("click_at_xy", "type_text", "press_key")


@dataclass(frozen=True)
class Recording:
    name: str
    title: str
    started: float
    path: Path
    events: tuple[TraceEvent, ...]

    def actionable(self) -> tuple[TraceEvent, ...]:
        """浏览器意义上的"动作"事件（判据 = ACTIONS，等待类也算）。

        ⚠️ 这里**不**过滤"能不能产步骤" —— 那是 core/compile 的 EVENT_TO_ACTION
        的事。在这一层过滤会让 transcript 依赖 compile 的映射表，层次就反了。
        需要"必须问浏览器"的那一批，用 probe_targets()。
        """
        return tuple(e for e in self.events if e.is_action)

    def probe_targets(self) -> tuple[TraceEvent, ...]:
        return tuple(e for e in self.events if e.needs_probe())

    @property
    def viewport(self) -> tuple[int, int] | None:
        for e in self.events:
            if e.viewport:
                return e.viewport
        return None


def _parse_event(seq: int, raw: dict) -> TraceEvent:
    w, h = raw.get("w"), raw.get("h")
    viewport = (int(w), int(h)) if w and h else None
    detail = {
        key: raw[key]
        for key in DETAIL_KEYS.get(str(raw.get("helper")), ())
        if raw.get(key) is not None
    }
    return TraceEvent(
        seq=seq,
        ts=float(raw.get("ts") or 0.0),
        helper=str(raw.get("helper") or ""),
        url=str(raw.get("url") or ""),
        title=str(raw.get("title") or ""),
        viewport=viewport,
        box=raw.get("box"),
        input_type=str(raw.get("input") or ""),
        frame=str(raw.get("frame") or ""),
        detail=detail,
    )


def load_recording(path: Path | str) -> Recording:
    """读一个录制目录。缺 events.jsonl 时报带路径的 FileNotFoundError。"""
    root = Path(path)
    events_file = root / "events.jsonl"
    if not events_file.is_file():
        raise FileNotFoundError(f"{events_file} (events.jsonl 不存在：{root})")

    meta: dict = {}
    meta_file = root / "meta.json"
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    events: list[TraceEvent] = []
    for line in events_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(_parse_event(len(events), json.loads(line)))

    return Recording(
        name=str(meta.get("name") or root.name),
        title=str(meta.get("title") or ""),
        started=float(meta.get("started") or 0.0),
        path=root,
        events=tuple(events),
    )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_transcript.py -v`
Expected: 9 passed

- [ ] **Step 6: 让可移植性闸也覆盖它**

Run: `make portability`
Expected: `✅ portability check passed (core)`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(transcript): normalize browser-harness recordings into a typed event stream"
```

---

## Task 4: 锚点纯函数层 + schema

**Files:**
- Create: `core/compile/__init__.py`, `core/compile/schema.py`, `core/compile/anchors.py`
- Test: `tests/test_anchor_candidates.py`, `tests/test_anchor_match.py`, `tests/test_schema_roundtrip.py`

**Interfaces:**
- Consumes: `core.transcript.recording.TraceEvent`
- Produces:
  - `core.compile.schema.Anchor`（frozen dataclass）：`by: str`、`value: str = ""`、`role: str = ""`、`name: str = ""`、`fallback: bool = False`、`copy_sensitive: bool = False`；`to_json() -> dict`、`Anchor.from_json(d) -> Anchor`
  - `core.compile.schema.Step`：`n: int`、`action: str`、`anchor: Anchor | None`、`path: str = ""`、`selector: str = ""`、`value_ref: str = ""`、`text: str = ""`、`key: str = ""`、`state: str = "visible"`、`xy: tuple[int, int] | None = None`
  - `core.compile.schema.Workflow`：`id`、`title`、`target`、`source: dict`、`steps: tuple[Step, ...]`；`to_json()`、`Workflow.from_json(d)`
  - `core.compile.schema.Unresolved`：`seq: int`、`helper: str`、`event: dict`、`candidates: tuple[Anchor, ...]`、`reason: str`
  - `core.compile.anchors.ElementSnapshot`（frozen）：`tag`、`role`、`name`、`text`、`testid`、`attrs: dict`、`path`、`rect: dict`
  - `core.compile.anchors.candidates(snap: ElementSnapshot) -> tuple[Anchor, ...]`（按优先级排序）
  - `core.compile.anchors.normalize(s: str) -> str`
  - `core.compile.anchors.similarity(a: str, b: str) -> float`
  - `core.compile.anchors.SNAP_JS: str`（在页面里取快照的 JS）
  - `core.compile.anchors.ANCHOR_PRIORITY: tuple[str, ...] == ("testid", "role", "text", "path", "xy")`
  - `core.compile.anchors.DRIFT_THRESHOLD: float == 0.7`

- [ ] **Step 1: 写失败测试 — 候选排序**

`tests/test_anchor_candidates.py`：

```python
from core.compile.anchors import ANCHOR_PRIORITY, ElementSnapshot, candidates


def snap(**over) -> ElementSnapshot:
    base = dict(
        tag="button", role="button", name="新建", text="新建", testid="",
        attrs={}, path="body > div > button:nth-of-type(1)", rect={"x": 0, "y": 0, "w": 1, "h": 1},
    )
    base.update(over)
    return ElementSnapshot(**base)


def test_priority_order_is_the_declared_one():
    assert ANCHOR_PRIORITY == ("testid", "role", "text", "path", "xy")


def test_testid_wins_when_present():
    got = candidates(snap(testid="create-btn"))
    assert got[0].by == "testid"
    assert got[0].value == "create-btn"
    assert got[0].fallback is False


def test_role_anchor_carries_role_and_name():
    got = candidates(snap())
    top = got[0]
    assert top.by == "role" and top.role == "button" and top.name == "新建"


def test_text_anchor_is_marked_copy_sensitive():
    got = candidates(snap(role="", name="", testid=""))
    top = got[0]
    assert top.by == "text" and top.value == "新建"
    assert top.copy_sensitive is True


def test_role_anchor_is_marked_copy_sensitive():
    assert candidates(snap())[0].copy_sensitive is True


def test_testid_anchor_is_not_copy_sensitive():
    assert candidates(snap(testid="create-btn"))[0].copy_sensitive is False


def test_path_is_offered_when_no_semantic_hook_exists():
    got = [a for a in candidates(snap(role="", name="", testid="")) if a.by == "path"]
    assert got and got[0].copy_sensitive is False


def test_always_ends_with_an_xy_fallback():
    got = candidates(snap())
    assert got[-1].by == "xy"
    assert got[-1].fallback is True


def test_blank_hooks_are_not_emitted_as_candidates():
    got = candidates(snap(role="", name="", testid="", text=""))
    assert all(a.value or a.by in ("xy", "path") for a in got)
    assert not any(a.by in ("testid", "text") for a in got)


def test_long_text_is_truncated_to_keep_anchors_readable():
    got = candidates(snap(role="", name="", testid="", text="x" * 200))
    assert len(got[0].value) <= 80
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_anchor_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.compile.anchors'`

- [ ] **Step 3: 写失败测试 — 归一化与近似匹配**

`tests/test_anchor_match.py`：

```python
from core.compile.anchors import DRIFT_THRESHOLD, normalize, similarity


def test_normalize_folds_whitespace_case_and_punctuation():
    assert normalize("登  录") == normalize("登录")
    assert normalize("Sign In") == normalize("sign in")
    assert normalize("登 录！") == normalize("登录")


def test_normalize_keeps_cjk_intact():
    assert normalize("新建") == "新建"


def test_identical_strings_are_maximally_similar():
    assert similarity("新建", "新建") == 1.0


def test_a_copy_edit_still_scores_above_threshold():
    # 「登 录」→「立即登录」：同一颗按钮，文案改了
    assert similarity("登 录", "立即登录") >= DRIFT_THRESHOLD


def test_unrelated_labels_score_below_threshold():
    assert similarity("新建", "删除") < DRIFT_THRESHOLD


def test_a_short_label_contained_in_a_longer_unrelated_one_is_not_a_match():
    """回归：不设最短公共段下限时，"A" 完整包含在 "Archive" 里会得 1.0，
    阈值就失去鉴别力，任何带 A 的标签都会被当成同一颗按钮。"""
    assert similarity("A", "Archive") < DRIFT_THRESHOLD
    assert similarity("编辑", "编辑器偏好设置") >= DRIFT_THRESHOLD   # 真·文案扩展仍要认


def test_threshold_is_the_documented_value():
    assert DRIFT_THRESHOLD == 0.7
```

- [ ] **Step 4: 实现 schema**

`core/compile/schema.py`：

```python
"""workflow / step / anchor / unresolved 的数据契约（spec §4.3）。

都是纯数据 + JSON 往返，不含任何浏览器或业务逻辑。
断言的 sidecar（Check / Checks）由 Task 6 追加到本模块 —— 本 Task 不定义它们。
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Anchor:
    by: str                                   # testid | role | text | path | xy
    value: str = ""
    role: str = ""
    name: str = ""
    fallback: bool = False                    # xy 兜底必须为 True
    copy_sensitive: bool = False              # 文案会变 → 允许近似匹配

    def to_json(self) -> dict:
        out = {"by": self.by}
        for key in ("value", "role", "name"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.fallback:
            out["fallback"] = True
        if self.copy_sensitive:
            out["copy_sensitive"] = True
        return out

    @staticmethod
    def from_json(d: dict) -> "Anchor":
        return Anchor(
            by=str(d.get("by") or ""),
            value=str(d.get("value") or ""),
            role=str(d.get("role") or ""),
            name=str(d.get("name") or ""),
            fallback=bool(d.get("fallback")),
            copy_sensitive=bool(d.get("copy_sensitive")),
        )


@dataclass(frozen=True)
class Step:
    n: int
    action: str                               # goto|click|fill|press|wait_for|scroll|wait_network_idle
    anchor: Anchor | None = None
    path: str = ""                            # goto 用
    selector: str = ""                        # fill/wait_for 用
    value_ref: str = ""                       # 只允许 env:<VAR> 或 cred:<name>
    text: str = ""                            # press 用不到；填给 fill 的明文一律拒绝
    key: str = ""                             # press 用
    state: str = "visible"                    # wait_for 用
    # 录制的原始落点。**只服务编译期探针**：探针跑的是草稿步（有 xy、还没挂锚点），
    # 那时只能用坐标；编译产物里的 click 一律**清掉 xy**、只留语义锚点。
    xy: tuple[int, int] | None = None

    def to_json(self) -> dict:
        out: dict = {"n": self.n, "action": self.action}
        if self.anchor:
            out["anchor"] = self.anchor.to_json()
        for key in ("path", "selector", "value_ref", "text", "key"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        # 🔴 必须判 is not None，不能判真假：坐标 (0, 0) 是合法的（左上角），
        #    而 (0, 0) 是真假意义上的 False ⇒ 会被漏写、往返后丢失。
        if self.xy is not None:
            out["xy"] = list(self.xy)
        if self.action == "wait_for":
            out["state"] = self.state
        return out

    @staticmethod
    def from_json(d: dict) -> "Step":
        return Step(
            n=int(d.get("n") or 0),
            action=str(d.get("action") or ""),
            anchor=Anchor.from_json(d["anchor"]) if d.get("anchor") else None,
            path=str(d.get("path") or ""),
            selector=str(d.get("selector") or ""),
            value_ref=str(d.get("value_ref") or ""),
            text=str(d.get("text") or ""),
            key=str(d.get("key") or ""),
            state=str(d.get("state") or "visible"),
            xy=tuple(d["xy"]) if d.get("xy") is not None else None,
        )


@dataclass(frozen=True)
class Workflow:
    id: str
    title: str
    target: str
    source: dict = field(default_factory=dict)
    steps: tuple[Step, ...] = ()

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "target": self.target,
            "source": self.source,
            "steps": [s.to_json() for s in self.steps],
        }

    @staticmethod
    def from_json(d: dict) -> "Workflow":
        version = d.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"workflow schema_version {version!r} != {SCHEMA_VERSION}")
        return Workflow(
            id=str(d["id"]),
            title=str(d.get("title") or ""),
            target=str(d.get("target") or ""),
            source=dict(d.get("source") or {}),
            steps=tuple(Step.from_json(s) for s in d.get("steps") or []),
        )


@dataclass(frozen=True)
class Unresolved:
    seq: int
    helper: str
    event: dict
    candidates: tuple[Anchor, ...] = ()
    reason: str = ""

    def to_json(self) -> dict:
        return {
            "seq": self.seq,
            "helper": self.helper,
            "event": self.event,
            "candidates": [a.to_json() for a in self.candidates],
            "reason": self.reason,
        }
```

- [ ] **Step 5: 实现 anchors**

`core/compile/anchors.py`：

```python
"""元素快照 → 候选锚点（纯函数），以及锚点失效时的近似匹配。

为什么 testid 排第一而不是文案（spec §4.2）：文案会随发布变化，
拿文案定位会把「按钮没了」和「按钮改叫别的了」混成一件事。
role/text 类锚点因此标 copy_sensitive，失效时走近似匹配 → 归 FAIL_PRODUCT。

本模块不碰浏览器：SNAP_JS 只是发给页面的字符串，取回来的 dict 由这里解释。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .schema import Anchor

ANCHOR_PRIORITY: tuple[str, ...] = ("testid", "role", "text", "path", "xy")
DRIFT_THRESHOLD = 0.7
_MAX_TEXT = 80
# 公共段短于这个长度就不算"文案改写"——否则短标签被包含即得满分
_MIN_PARTIAL_CHARS = 2

# 在页面里取「这个元素是什么」。返回结构必须与 ElementSnapshot 的字段对齐。
SNAP_JS = r"""
(() => {
  const el = window.__ttt_target;
  if (!el || el.nodeType !== 1) return null;
  const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
  const r = el.getBoundingClientRect();
  const path = (() => {
    const parts = [];
    let n = el;
    while (n && n.nodeType === 1 && parts.length < 8) {
      let sel = n.tagName.toLowerCase();
      if (n.parentElement) {
        const sibs = [...n.parentElement.children].filter(c => c.tagName === n.tagName);
        if (sibs.length > 1) sel += `:nth-of-type(${sibs.indexOf(n) + 1})`;
      }
      parts.unshift(sel);
      n = n.parentElement;
    }
    return parts.join(' > ');
  })();
  const aria = el.getAttribute('aria-label') || '';
  const labelled = el.getAttribute('aria-labelledby');
  const labelText = labelled
    ? (document.getElementById(labelled)?.textContent || '')
    : (el.labels && el.labels[0] ? el.labels[0].textContent : '');
  const name = (aria || labelText || t || el.getAttribute('placeholder')
                || el.getAttribute('title') || el.getAttribute('alt') || '').trim();
  // 隐式角色：真实页面里绝大多数元素没有显式 role 属性，
  // 只读 getAttribute('role') 会让 role 锚点几乎永远缺席。
  const IMPLICIT = {
    a: 'link', button: 'button', select: 'combobox', textarea: 'textbox',
    nav: 'navigation', main: 'main', header: 'banner', footer: 'contentinfo',
    h1: 'heading', h2: 'heading', h3: 'heading', ul: 'list', li: 'listitem',
    table: 'table', dialog: 'dialog', form: 'form',
  };
  const input = el.tagName.toLowerCase() === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '';
  const INPUT_ROLE = { submit: 'button', button: 'button', checkbox: 'checkbox', radio: 'radio', search: 'searchbox' };
  const role = el.getAttribute('role') || IMPLICIT[el.tagName.toLowerCase()] || INPUT_ROLE[input] || '';
  return {
    tag: el.tagName.toLowerCase(),
    role: role,
    name: name.slice(0, 200),
    text: t.slice(0, 200),
    testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
    attrs: { id: el.id || '', name: el.getAttribute('name') || '', type: el.getAttribute('type') || '' },
    path,
    rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
  };
})()
"""


@dataclass(frozen=True)
class ElementSnapshot:
    tag: str
    role: str
    name: str
    text: str
    testid: str
    attrs: dict = field(default_factory=dict)
    path: str = ""
    rect: dict = field(default_factory=dict)

    @staticmethod
    def from_json(d: dict | None) -> "ElementSnapshot | None":
        if not isinstance(d, dict) or not d.get("tag"):
            return None
        return ElementSnapshot(
            tag=str(d.get("tag") or ""),
            role=str(d.get("role") or ""),
            name=str(d.get("name") or ""),
            text=str(d.get("text") or ""),
            testid=str(d.get("testid") or ""),
            attrs=dict(d.get("attrs") or {}),
            path=str(d.get("path") or ""),
            rect=dict(d.get("rect") or {}),
        )


def _clip(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:_MAX_TEXT]


def candidates(snap: ElementSnapshot) -> tuple[Anchor, ...]:
    """按 ANCHOR_PRIORITY 产出候选锚点，最后一颗永远是 xy 兜底。

    语义钩子为空的一律不产出——宁可少一个候选，也不要一个空值锚点
    在回放时"匹配到所有人"。
    """
    out: list[Anchor] = []

    if snap.testid:
        out.append(Anchor(by="testid", value=snap.testid))

    role_name = _clip(snap.name)
    if snap.role and role_name:
        out.append(Anchor(by="role", role=snap.role, name=role_name, copy_sensitive=True))

    text = _clip(snap.text)
    if text:
        out.append(Anchor(by="text", value=text, copy_sensitive=True))

    if snap.path:
        out.append(Anchor(by="path", value=snap.path))

    rect = snap.rect or {}
    out.append(Anchor(
        by="xy",
        value=f"{int(rect.get('x', 0))},{int(rect.get('y', 0))}",
        fallback=True,
    ))
    return tuple(out)


def normalize(text: str) -> str:
    """折叠空白、大小写与标点，用于近似匹配。CJK 原样保留。"""
    text = (text or "").strip().lower()
    text = re.sub(r"[\s　]+", "", text)
    return re.sub(r"[!-/:-@\[-`{-~！-／：-＠［-｀｛-～、-〜。，．・：；？！…—－（）「」『』【】]", "", text)


def similarity(a: str, b: str) -> float:
    """归一化之后的序列相似度 ∈ [0, 1]，对"前后加字的文案改写"也认。

    ⚠️ 为什么不是纯 SequenceMatcher.ratio()：`ratio()` 的分母是两个串的长度和，
    所以短标签被加长时会被稀释 —— "登录" vs "立即登录" 只有 4/6 ≈ 0.667，
    **低于 0.7 的 DRIFT_THRESHOLD**，本 Task 的 test_a_copy_edit_still_scores_above_threshold
    就永远绿不了。（原 spec 写的是纯 ratio()，它与自己那条测试互相矛盾。）

    所以补一项 partial = 最长公共连续段 / 较短串长度，取二者较大值。
    🔴 但 partial 必须设**最短公共段下限**：不设的话，任何一个短标签只要被
    完整包含在别的标签里就得 1.0（"A" ⊂ "Archive"），阈值就失去鉴别力了。
    """
    na, nb = normalize(a), normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0

    matcher = SequenceMatcher(None, na, nb)
    ratio = matcher.ratio()
    longest = matcher.find_longest_match().size
    if longest < _MIN_PARTIAL_CHARS:
        return ratio
    return max(ratio, longest / min(len(na), len(nb)))
```

- [ ] **Step 6: 写 schema 往返测试**

`tests/test_schema_roundtrip.py`：

```python
import pytest

from core.compile.schema import Anchor, Step, Unresolved, Workflow


def test_anchor_round_trips_including_the_flags():
    anchor = Anchor(by="text", value="新建", copy_sensitive=True)
    assert Anchor.from_json(anchor.to_json()) == anchor


def test_xy_fallback_flag_survives_the_round_trip():
    anchor = Anchor(by="xy", value="10,20", fallback=True)
    assert Anchor.from_json(anchor.to_json()).fallback is True


def test_step_round_trips_including_xy():
    step = Step(n=2, action="click", xy=(120, 168), anchor=Anchor(by="testid", value="b"))
    restored = Step.from_json(step.to_json())
    assert restored.xy == (120, 168)
    assert restored.anchor == step.anchor
    assert restored == step


def test_step_without_xy_round_trips():
    assert Step.from_json(Step(n=1, action="goto", path="/login").to_json()).xy is None


def test_workflow_round_trips():
    wf = Workflow(id="w", title="t", target="demo",
                  source={"recording": "r"},
                  steps=(Step(n=1, action="goto", path="/login"),))
    assert Workflow.from_json(wf.to_json()) == wf


def test_workflow_rejects_an_unknown_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        Workflow.from_json({"schema_version": 99, "id": "w", "title": "", "target": ""})


def test_unresolved_round_trips_with_its_candidates():
    item = Unresolved(seq=3, helper="click_at_xy", event={"x": 120, "y": 168},
                      candidates=(Anchor(by="text", value="新建", copy_sensitive=True),),
                      reason="no_semantic_hook")
    restored = Unresolved.from_json(item.to_json())
    assert restored == item
    assert restored.candidates[0].copy_sensitive is True


def test_unresolved_round_trips_with_no_candidates():
    item = Unresolved(seq=1, helper="type_text", event={"text": "x"},
                      reason="type_text_unsupported")
    restored = Unresolved.from_json(item.to_json())
    assert restored == item
    assert restored.candidates == ()
```

Run: `uv run pytest tests/test_schema_roundtrip.py -v`
Expected: 10 passed

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_anchor_candidates.py tests/test_anchor_match.py tests/test_schema_roundtrip.py -v`
Expected: 25 passed

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(compile): anchor schema + pure candidate ranking and drift matching"
```

---

## Task 5: 浏览器会话原语

> ⚠️ **后来追加的差量，由 Task 10 携带，不在本 Task 的实现范围内。**
> daemon 名必须**进程内稳定**（`ttt-<pid>`，不是每会话一个），且 `__enter__` 要先
> `restart_daemon` 再 `ensure_daemon`、`_shutdown` 要连 daemon 一起停。原因是
> `admin.NAME`/`daemon.NAME` 都是 **import 时**读一次 `BU_NAME`，之后改 `os.environ`
> 对已导入的模块无效 —— 按会话换名字会让第二个会话的 CDP 调用打到第一个已关闭的
> 浏览器上（实测 `no close frame received or sent`）。本 Task 的代码已进 main、
> 是旧行为；该修订落在 Task 10。

**Files:**
- Create: `core/primitives/__init__.py`, `core/primitives/session.py`
- Test: `tests/test_session_gate.py`

**Interfaces:**
- Consumes: `browser_harness`（可选依赖；导入失败时给出可操作的报错）
- Produces:
  - `core.primitives.session.Session(base_url: str, *, viewport=(1440, 900), headed=False, allow_hosts: tuple[str, ...] = (), profile_dir: Path | None = None, timeout=15.0)`
  - `Session.__enter__/.__exit__`：**自起一个只属于本次会话的 Chrome**（绝不 attach 用户主浏览器），退出时关掉它并回收残留
  - 🔴 `core.primitives.session.harness_env(name, port) -> dict[str, str]` —— 让 browser-harness 只连我们自起的 Chrome 的环境变量
  - `core.primitives.session.chrome_launch_args(profile_dir, headed=False) -> list[str]`
  - `core.primitives.session.read_devtools_port(profile_dir, proc, timeout=20.0) -> int`、`find_chrome() -> str`
  - 🔴 `Session.start_recording(name, title=None) -> Path`、`Session.stop_recording() -> Path | None`
  - 🔴 **每个动作方法内部都要显式调 `recorder.observe(...)`** —— 见下方「录制为什么必须自己调」
  - `Session.goto(path) -> None`、`Session.click_xy(x, y) -> None`、`Session.fill(selector, text) -> None`、`Session.press(key) -> None`、`Session.wait_for(selector, state="visible") -> None`、`Session.js(expr) -> object`、`Session.snapshot_at(x, y) -> ElementSnapshot | None`、`Session.snapshot_focused() -> ElementSnapshot | None`、`Session.screenshot(path) -> Path`
  - `core.primitives.session.assert_target_allowed(base_url, allow_hosts) -> None`（**默认只允许 loopback**；非 loopback 且不在 allow_hosts 里就抛 `TargetNotAllowed`）
  - `core.primitives.session.TargetNotAllowed(Exception)`
  - `core.primitives.session.reap_leaked_browsers(profile_dir: Path) -> int`

**为什么必须自起 Chrome，以及怎么做**：`browser-harness` 的默认行为是**连本机正在跑的 Chrome**（`admin._is_local_chrome_mode()` 为真时走本地发现：读 profile 的 `DevToolsActivePort`）。直接用默认参数调 `ensure_daemon()`，就会挂到**用户自己的浏览器**上——这会和用户抢标签页，而且录制里混进别人的页面。要真正做到"只属于本次会话"，三件事缺一不可：

1. **自己拉一个 Chrome**：`--user-data-dir=<我们的 profile>`（与用户 profile 分开）+ `--remote-debugging-port=<我们挑的空闲端口>`；无人值守默认 `--headless=new`。
2. **把 `BU_CDP_URL` 指过去**：这个变量一设，`_is_local_chrome_mode()` 立即返回 False，daemon 不再做本地发现，只连我们给的端点。这是机制的落点，不是注释。
3. 🔴 **`BU_NAME` / `BU_CDP_URL` 必须在 `import browser_harness` 之前写进 `os.environ`**：`admin.NAME` 与 `daemon.NAME` 都是 **import 时读一次**的（`os.environ.get("BU_NAME", "default")`），daemon 子进程也从自己的环境里读 `BU_CDP_URL`。写晚了就静默落回默认 daemon + 本地发现 —— 又挂到用户浏览器上。

**为什么有环境闸**：这条轨会真的点、真的填。默认只允许 loopback，等于「不配就永远打不到线上」。这是把「测试轨误打生产」的结构性风险变成默认安全的机制，不是自觉。

**录制为什么必须自己调 `recorder.observe`**：`events.jsonl` 只在 `browser_harness/run.py` 的 `_traced()` 包装里产生——`run.py` 把 `helpers` 的每个函数包一层，成功后调 `recorder.observe(name, args, kwargs, duration)`。我们从 Python 里 `import helpers` 直接调，**绕过那层包装，一条事件都不会落盘**（已核对 `run.py:148-169` 与 `helpers` 无自埋点）。所以 `Session` 的每个动作方法在调完 helper 后必须自己调一次 `recorder.observe`，参数形状与 `_traced` 一致（位置参数放 `args`，其余放 `kwargs`）——`recorder._details()` 是按位置下标取值的，形状错了录制里的坐标就是 `None`。这个陷阱由 **Task 10 写进 README**（本 Task 只需用测试把参数形状钉死，见 Step 4b），否则下一个人会以为「调了 browser-harness 就有录制」。

- [ ] **Step 1: 写失败测试**

`tests/test_session_gate.py`：

```python
import pytest

from core.primitives.session import TargetNotAllowed, assert_target_allowed


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_session_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.primitives.session'`

- [ ] **Step 3: 实现**

`core/primitives/session.py`：

```python
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
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ..compile.anchors import SNAP_JS, ElementSnapshot

DEFAULT_VIEWPORT = (1440, 900)

# 每个会话的 profile 目录后缀，保证同一进程内两次构造不会撞
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
        if host == allowed or host.endswith("." + allowed):
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

    🔴 必须在 **import browser_harness 之前**写进 os.environ：
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
    except ImportError as exc:  # pragma: no cover - 环境问题
        # 🔴 两个 import 都要在 try 里：`browser_harness.admin` 原来在
        #    __enter__ 里单独 import，缺可选依赖时抛的是裸 ImportError，
        #    而不是带安装指引的 BrowserHarnessMissing。
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
        self._allow_hosts = allow_hosts          # 每次导航都要重查闸，得留着
        # 🔴 每个会话一个**独占**的 profile 目录。原来默认是共享的
        #    `tempdir/ttt-profile` ⇒ 并发会话会互相踩，甚至 attach 到上一个会话
        #    起的那个 Chrome 上 —— 与"每会话隔离"直接矛盾。
        if profile_dir is None:
            profile_dir = (Path(tempfile.gettempdir())
                           / f"ttt-profile-{os.getpid()}-{next(_PROFILE_SEQ)}")
        self.profile_dir = Path(profile_dir)
        self._bh = None

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
        #
        # 🔴 daemon 名**进程内稳定**，不是一个会话一个名字。
        #    `admin.NAME` / `daemon.NAME` 都是 import 时读一次 BU_NAME 的，之后改
        #    os.environ 对**已导入**的模块无效 —— 按会话换名字的话，第二个会话的
        #    `helpers._send()` 仍然用第一个名字，打到第一个**已关闭**的浏览器上
        #    （实测报 `no close frame received or sent`）。
        #    会话之间要隔离的是 **profile 与调试端口**，不是 daemon 名。
        self._daemon_name = f"ttt-{os.getpid()}"
        os.environ.update(harness_env(self._daemon_name, self._port))

        self._bh, self._recorder, ensure_daemon, restart_daemon = _load_harness()
        # 先停掉上一个会话的 daemon（它指向那个已经关掉的 Chrome），
        # 再拉起新的 —— `ensure_daemon` 用**当前** os.environ 起子进程，
        # 所以新 daemon 会连到我们这一发的 Chrome 上。
        restart_daemon(self._daemon_name)
        ensure_daemon(name=self._daemon_name)
        self._apply_viewport()
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
        if chrome is not None and chrome.poll() is None:
            chrome.terminate()
            try:
                chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                chrome.kill()
        self._chrome = None
        reap_leaked_browsers(self.profile_dir)
        # 🔴 daemon 也要停：留着它就会一直指向一个已关闭的浏览器，
        #    下一个会话的 CDP 调用会打到死连接上。
        if getattr(self, "_daemon_name", ""):
            try:
                from browser_harness.admin import restart_daemon  # noqa: PLC0415
                restart_daemon(self._daemon_name)
            except Exception:      # 收尾不许因为清理失败而炸
                pass

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
        # 🔴 闸必须在**每一次导航**时重查，不能只在构造时查一次。
        #    否则 `goto("https://elsewhere.example")` 一次调用就整个绕过去 ——
        #    "默认只允许 loopback"这条保证会被推翻，而它的全部价值就在于
        #    "不配就永远打不到线上"。这是个结构性保证，不能靠调用方自觉。
        assert_target_allowed(url, self._allow_hosts)
        self._act("new_tab", url)
        self._act("wait_for_load", self.timeout)

    def click_xy(self, x: int, y: int) -> None:
        self._act("click_at_xy", int(x), int(y))

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

        locate = locate_js(anchor)

        if anchor.by == "xy":
            x, y = (int(v) for v in anchor.value.split(","))
            snap = self.snapshot_at(x, y)
            return {"count": 1 if snap else 0, "snap": snap, "drift": ""}

        count = int(self.js(LOCATE_HELPERS + f"(()=>{{ const r={locate}; "
                         "return Array.isArray(r) ? r.length : (r ? 1 : 0); }})()") or 0)
        if count == 1:
            return {"count": 1, "snap": self._snapshot_js(LOCATE_HELPERS + f"(()=>{{const r={locate}; return Array.isArray(r)?r[0]:r;}})()"), "drift": ""}
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
def locate_js(anchor) -> str | None:
    """把锚点编译成一段 JS 表达式：返回**元素或元素数组**；`xy` 返回 None。

    🔴 这必须是**唯一一份**构造。原来测试里的 `node --check` 守卫**复制**了一份
    locate 字典 —— 于是 `resolve()` 回归、副本没跟进时守卫照样绿。那正是当初
    五个 JS bug 得以存活的机制：同一个东西有两份，只有一份被测。
    `resolve()` 与守卫都调这里。

    值一律经 `json.dumps` 转义再拼进 JS：锚点可能来自被手改过的 workflow 文件，
    直接 f-string 拼等于把 JS 注入面留给数据。

    同时认 `data-testid` 与 `data-test`（SNAP_JS 两个都会采），
    只搜一个会让"只有 data-test 的元素"编译出的锚点永远解不开。
    """
    value = json.dumps(anchor.value)
    if anchor.by == "testid":
        return ("[...document.querySelectorAll("
                "'[data-testid=\"' + " + value + " + '\"],[data-test=\"' + " + value + " + '\"]')]")
    if anchor.by == "path":
        return f"[...document.querySelectorAll({value})]"
    if anchor.by == "text":
        return f"__tttFindByText({value})"
    if anchor.by == "role":
        return f"__tttFindByRole({json.dumps(anchor.role)}, {json.dumps(anchor.name)})"
    return None      # xy：走 snapshot_at，不在这里编表达式


LOCATE_HELPERS = r"""
(() => {
  if (window.__tttHelpersInstalled) return;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  window.__tttVisible = el => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  const CLIP = 80;   // 与 anchors.candidates() 的 _MAX_TEXT 同一个数
  // 🔴 clip 必须**两侧一致**：candidates() 把 name/text 截到 80 后存进锚点，
  //    查找侧原来拿完整文本去比 —— 超过 80 字的标签编译出的锚点永远匹配不上，
  //    表现为"文案漂移"（FAIL_PRODUCT），而页面根本没变。
  const clip = s => norm((s || '').replace(/\s+/g, ' ').trim().slice(0, CLIP));
  // 🔴 取名链必须与 SNAP_JS **逐字一致**（aria-label → labelText → textContent
  //    → placeholder → title → alt）。原来查找侧只认 aria-label/textContent，
  //    于是"靠 <label> 取名的控件"编译出的 role 锚点永远解不开（假 FAIL_PRODUCT）。
  window.__tttRoleName = el => {
    const labelled = el.getAttribute('aria-labelledby');
    const labelText = labelled
      ? (document.getElementById(labelled)?.textContent || '')
      : (el.labels && el.labels[0] ? el.labels[0].textContent : '');
    return el.getAttribute('aria-label') || labelText || el.textContent
        || el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('alt') || '';
  };
  window.__tttFindByText = t => [...document.querySelectorAll('*')]
      .filter(el => window.__tttVisible(el) && clip(el.textContent) === clip(t)
                    && ![...el.children].some(c => clip(c.textContent) === clip(t)))[0] || null;
  window.__tttFindByRole = (role, name) => [...document.querySelectorAll('*')]
      .filter(el => window.__tttVisible(el)
                    && (el.getAttribute('role') || window.__tttImplicitRole(el)) === role
                    && clip(window.__tttRoleName(el)) === clip(name));
  window.__tttAllLabels = () => [...document.querySelectorAll('button,a,[role],label,input')]
      .filter(window.__tttVisible)
      .map(el => (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || '').trim())
      .filter(Boolean);
  // 与 SNAP_JS 的 IMPLICIT/INPUT_ROLE **逐字同表**：两边不一致会让编译期
  // 采到的隐式角色在查找期匹配不上（role 锚点永远解不开）。
  const IMPLICIT = {
    a: 'link', button: 'button', select: 'combobox', textarea: 'textbox',
    nav: 'navigation', main: 'main', header: 'banner', footer: 'contentinfo',
    h1: 'heading', h2: 'heading', h3: 'heading', ul: 'list', li: 'listitem',
    table: 'table', dialog: 'dialog', form: 'form',
  };
  const INPUT_ROLE = { submit: 'button', button: 'button', checkbox: 'checkbox', radio: 'radio', search: 'searchbox' };
  window.__tttImplicitRole = el => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      return INPUT_ROLE[t] || '';
    }
    return IMPLICIT[tag] || '';
  };
  window.__tttHelpersInstalled = true;
})();
"""
```

> 实现提示：`LOCATE_HELPERS` 是 IIFE。`resolve()` 里把 `LOCATE_HELPERS` 与 `locate_js(anchor)` 的产物**拼成一条** `js()` 调用 —— **拼在 count 那条上**；快照那条**不要**再拼一次 helpers（helpers 返回 undefined，拼上去会让快照永远为空，这是真实踩过的 bug）。`resolve()` 里 `from ..compile.anchors import ...` 的局部导入是为了避免 `primitives → compile` 的模块级循环（`compile/anchors.py` 也 import `schema`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_session_gate.py -v`
Expected: 6 passed（这组测试不碰浏览器，纯闸逻辑）

**还需要给 `Session` 补两个按锚点操作的方法**（断言模式点的是**锚点定位到的元素**，不是坐标）。追加到 Task 5 建的 `core/primitives/session.py`，并加进 `Locator` 协议：

```python
    def click_at_anchor(self, anchor) -> None:
        """点锚点定位到的那个元素：先 resolve 拿 rect，再点它的中心。

        为什么不用坐标：那正是 §鸿沟一 要消灭的东西。锚点是我们唯一信任的定位方式，
        点它的时候也必须走同一条路 —— 否则会出现"锚点断言说找到了 A、手工坐标却点在 B 上"。
        """
        got = self.resolve(anchor)
        snap = got.get("snap")
        if not snap:
            raise AssertionError(f"anchor {anchor.by}={anchor.value or anchor.name!r} did not resolve")
        rect = snap.rect or {}
        x = int(rect.get("x", 0)) + int(rect.get("w", 0)) // 2
        y = int(rect.get("y", 0)) + int(rect.get("h", 0)) // 2
        self.click_xy(x, y)

    def click_text(self, text: str) -> None:
        """按可见文本点击 —— 探索期写脚本时最顺手的一个入口。

        🔴 它**走坐标**（click_xy），所以录制里留下的就是坐标，探针才有东西可反解。
        这也意味着探索脚本里可以放心用它：语义定位是编译期的事，不是探索期的事。
        """
        self.js(LOCATE_HELPERS)
        box = self.js(
            "(()=>{const el=__tttFindByText(" + repr(text) + ");"
            "if(!el)return null;const r=el.getBoundingClientRect();"
            "return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()"
        )
        if not box:
            raise AssertionError(f"no visible element with text {text!r}")
        self.click_xy(int(box["x"]), int(box["y"]))
```

对应的测试追加到 `tests/test_session_gate.py`（不需要浏览器 —— `Session` 的 `resolve`/`js` 用替身注入）：

```python
class _StubSession(Session):
    """把 js/resolve 换成剧本，专门测 click_at_anchor 的取中心逻辑。"""

    def __init__(self, resolve_result):
        self.base_url = "http://127.0.0.1:1"
        self.profile_dir = Path("/tmp/ttt-stub")
        self._resolve_result = resolve_result
        self.clicks: list[tuple[int, int]] = []

    def resolve(self, anchor):
        return self._resolve_result

    def click_xy(self, x, y):
        self.clicks.append((x, y))


def test_click_at_anchor_clicks_the_centre_of_the_resolved_element():
    from core.compile.anchors import ElementSnapshot

    snap = ElementSnapshot(tag="button", role="", name="", text="", testid="b",
                           attrs={}, path="", rect={"x": 100, "y": 50, "w": 40, "h": 20})
    stub = _StubSession({"count": 1, "snap": snap, "drift": ""})
    stub.click_at_anchor(Anchor(by="testid", value="b"))
    assert stub.clicks == [(120, 60)]


def test_click_at_anchor_refuses_when_the_anchor_did_not_resolve():
    stub = _StubSession({"count": 0, "snap": None, "drift": ""})
    with pytest.raises(AssertionError, match="did not resolve"):
        stub.click_at_anchor(Anchor(by="testid", value="b"))
    assert stub.clicks == []
```

（`tests/test_session_gate.py` 顶部补 `from pathlib import Path` 与 `from core.compile.schema import Anchor`。）

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_replay_three_states.py -v`
Expected: 8 passed

- [ ] **Step 6b: 写 Check/Checks 往返测试**

`Check`/`Checks` 是本 Task 新加进 `schema.py` 的，所以它们的往返测试也归本 Task
（Task 4 只定义 Anchor/Step/Workflow/Unresolved，那时还没有这两个类型）。

`tests/test_schema_check_roundtrip.py`：

```python
from core.compile.schema import Anchor, Check, Checks


def test_check_round_trips_and_keeps_source():
    check = Check(id="c1", after_step=1, kind="count", anchor=Anchor(by="testid", value="x"),
                  expect="3", source="spec:demo/spec.md#2", observed_at_compile="3")
    restored = Check.from_json(check.to_json())
    assert restored == check
    assert restored.source == "spec:demo/spec.md#2"
    assert restored.observed_at_compile == "3"


def test_checks_container_round_trips():
    container = Checks(workflow="w", checks=(Check(id="c1", after_step=1, kind="count",
                                                   anchor=Anchor(by="testid", value="x"),
                                                   expect="3", source="manual:n"),))
    assert Checks.from_json(container.to_json()) == container


def test_checks_with_no_assertions_round_trips():
    assert Checks.from_json(Checks(workflow="w").to_json()) == Checks(workflow="w")
```

Run: `uv run pytest tests/test_schema_check_roundtrip.py -v`
Expected: 3 passed

- [ ] **Step 7: 写断言求值测试**

`tests/test_check_evaluation.py`：

```python
from core.compile.anchors import ElementSnapshot
from core.compile.schema import Anchor, Check, Checks, Step, Workflow
from core.replay.engine import run
from core.replay.result import FAIL_PRODUCT, PASS

from tests.test_replay_three_states import FakeLocator

A = Anchor(by="testid", value="item-list")


def _wf():
    return Workflow(id="w", title="t", target="demo",
                    steps=(Step(n=1, action="wait_for", anchor=A, selector="#items"),))


def _snap(text):
    return ElementSnapshot(tag="ul", role="", name="", text=text, testid="item-list")


def test_text_present_passes_when_expected_text_is_there():
    loc = FakeLocator(resolve_script={"item-list": {"count": 1, "snap": _snap("Alpha Beta Gamma")}})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="Beta", source="manual:note")])
    assert run(_wf(), loc, checks).status == PASS


def test_text_present_fails_with_the_actual_text_recorded():
    loc = FakeLocator(resolve_script={"item-list": {"count": 1, "snap": _snap("Alpha")}})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="Beta", source="manual:note")])
    result = run(_wf(), loc, checks)
    assert result.status == FAIL_PRODUCT
    assert result.checks[0].actual == "Alpha"


def test_count_check_compares_the_number_of_matches():
    loc = FakeLocator(resolve_script={"item-list": {"count": 3, "snap": None}})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=A, expect="3", source="fixture:seed")])
    assert run(_wf(), loc, checks).status == PASS


def test_a_locator_failure_while_evaluating_a_check_is_an_environment_failure():
    """回归：`_evaluate` 原本在 try 之外 —— 断言期定位失败会把异常抛给调用方，
    既不返回 RunResult 也不给结论。断言期和步骤期同样是环境问题，归 FAIL_ENV。"""
    loc = FakeLocator(raise_on={"resolve"})
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=A, expect="3", source="manual:n")])
    result = run(_wf(), loc, checks)
    assert result.status == FAIL_ENV
    assert result.reason == "environment"


def test_a_fill_step_with_a_plaintext_value_is_refused():
    """🔴 安全属性：录制里的明文（可能是密码）绝不能进 workflow。
    fill 只认 value_ref="env:<VAR>"，明文一律拒绝。"""
    wf = Workflow(id="w", title="t", target="demo",
                  steps=(Step(n=1, action="fill", selector="#u", text="hunter2"),))
    result = run(wf, FakeLocator())
    assert result.status == FAIL_ENV
    assert "value_ref" in result.steps[0].message


def test_a_fill_step_whose_env_var_is_unset_is_refused(monkeypatch):
    """变量没设时必须报错，**绝不能**退化成空串 —— 空串会让断言变成
    "和空串比较"，那是另一种假绿。"""
    monkeypatch.delenv("TTT_MISSING_VAR", raising=False)
    wf = Workflow(id="w", title="t", target="demo",
                  steps=(Step(n=1, action="fill", selector="#u", value_ref="env:TTT_MISSING_VAR"),))
    result = run(wf, FakeLocator())
    assert result.status == FAIL_ENV
    assert "TTT_MISSING_VAR" in result.steps[0].message


def test_a_fill_step_with_a_set_env_var_types_that_value(monkeypatch):
    """正控：变量设了，且用的是它的值（而不是录制里的明文）。"""
    monkeypatch.setenv("TTT_PRESENT_VAR", "from-env")
    wf = Workflow(id="w", title="t", target="demo",
                  steps=(Step(n=1, action="fill", selector="#u", value_ref="env:TTT_PRESENT_VAR"),))
    loc = FakeLocator()
    assert run(wf, loc).status == PASS
    assert loc.calls == ["fill:#u=from-env"]


def test_checks_at_a_later_step_do_not_run_when_an_earlier_step_fails():
    wf = Workflow(id="w", title="t", target="demo", steps=(
        Step(n=1, action="click", anchor=Anchor(by="testid", value="gone")),
        Step(n=2, action="wait_for", anchor=A, selector="#items"),
    ))
    loc = FakeLocator(resolve_script={"gone": {"count": 0, "snap": None, "drift": ""}})
    checks = Checks(workflow="w", checks=[Check(id="c2", after_step=2, kind="count",
                                                anchor=A, expect="3", source="fixture:seed")])
    result = run(wf, loc, checks)
    assert result.checks == ()
```

- [ ] **Step 8: 跑测试确认通过**

Run: `uv run pytest tests/test_check_evaluation.py -v`
Expected: 8 passed

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(replay): locator-protocol engine with three-state verdicts and check evaluation"
```

- [ ] **Step 4b: 写隔离与录制形状的测试**

追加到 `tests/test_session_gate.py`（这组不需要浏览器，纯函数 + 替身）：

```python
import types

from core.compile.schema import Anchor
from core.primitives import session as session_mod
from core.primitives.session import (
    chrome_launch_args, harness_env, read_devtools_port, reap_leaked_browsers,
)

from tests.test_session_gate import _StubSession   # 见 Step 4a 的替身定义


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
    """🔴 回归：`Session` 必须满足 `core.replay.engine.Locator` 的**每一个**成员。

    这条测试为什么必须存在：`Locator` 是 `typing.Protocol`，结构性的，
    **不会在 import 期报错**。曾经 `Session` 漏了 `click_at_anchor`
    （错误地只写在 Task 6 的区段里，Task 5 的 brief 从没携带），
    而引擎的 `except Exception` 会把随之而来的 AttributeError 吞成 FAIL_ENV ——
    三态逻辑塌成一个值，测试还全绿。协议是鸭子类型，所以必须有一条测试
    真的去数它的成员，而不是指望类型检查器。
    """
    import inspect

    from core.replay import engine

    protocol_members = {
        name for name, member in inspect.getmembers(engine.Locator, inspect.isfunction)
        if not name.startswith("_")
    }
    assert protocol_members, "没读到 Locator 的任何成员 —— 这条守卫会空过"
    missing = sorted(n for n in protocol_members if not callable(getattr(Session, n, None)))
    assert not missing, f"Session 未实现 Locator 的成员：{missing}"


def test_the_generated_locate_js_is_syntactically_valid():
    """🔴 两件事一起钉：

    ① `resolve()` 与这条守卫必须用**同一份**构造（都调 `locate_js`）。
       原来守卫**复制**了一份 locate 字典 —— resolve() 回归而副本没跟进时，
       守卫照样绿。那正是当初五个 JS bug 存活下来的机制：同一个东西有两份，
       只有一份被测。
    ② 生成的 JS 要真能被解析。这些字符串是 Python 里的 JS，Python 工具链
       一个都不会读它 —— 只有把产物交给 node 才看得见语法错误。
       ⚠️ 这条**只查语法**：形状不一致（生产方给数组、消费方当单元素）
       语法上合法，靠形状测试与端到端回放兜。
    """
    import subprocess
    import tempfile

    from core.compile.schema import Anchor
    from core.primitives.session import locate_js

    samples = [
        Anchor(by="testid", value="item-list"),
        Anchor(by="path", value="body > div:nth-child(2)"),
        Anchor(by="text", value="登 录"),
        Anchor(by="role", role="button", name="新建"),
    ]
    body = "".join(
        "void (() => { const r=%s; return Array.isArray(r) ? r.length : (r ? 1 : 0); })();\n" % locate_js(a)
        for a in samples
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(body)
        path = fh.name
    proc = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_every_anchor_kind_has_a_locate_expression_except_xy():
    """守卫不许空过：四种锚点各自都要编得出表达式，xy 明确返回 None。"""
    from core.compile.schema import Anchor
    from core.primitives.session import locate_js

    for by in ("testid", "path", "text", "role"):
        assert locate_js(Anchor(by=by, value="v", role="r", name="n")), by
    assert locate_js(Anchor(by="xy", value="1,2")) is None


def test_the_daemon_name_is_stable_across_sessions_in_one_process():
    """🔴 回归：daemon 名必须**进程内稳定**。

    `admin.NAME` / `daemon.NAME` 都是 import 时读一次 BU_NAME 的，之后改
    os.environ 对已导入的模块无效。所以按会话生成新名字的话，第二个会话的
    CDP 调用仍用第一个名字 ⇒ 打到第一个**已关闭**的浏览器上
    （实测报 `no close frame received or sent`）。
    隔离靠的是 profile 与调试端口，不是 daemon 名。
    """
    a = Session("http://127.0.0.1:8712")
    b = Session("http://127.0.0.1:8712")
    assert a._daemon_name == b._daemon_name        # 名字稳定
    assert a.profile_dir != b.profile_dir          # 隔离在别处


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
```

Run: `uv run pytest tests/test_session_gate.py -v`
Expected: 29 passed（Step 4a 的 6 条 + 隔离与录制形状 14 条 + daemon 名与 locate_js 守卫 9 条）

- [ ] **Step 5: 手工冒烟一次真实浏览器**

```bash
uv run python -m target_app.serve --port 8712 --ttl 60 &
sleep 1
uv run --extra browser python - <<'PY'
from core.primitives.session import Session
with Session("http://127.0.0.1:8712") as s:
    s.goto("/login")
    print("shot:", s.screenshot(__import__("pathlib").Path("/tmp/ttt-login.png")))
    print("snapshot focused:", s.snapshot_focused())
    print("element at 120,168:", s.snapshot_at(120, 168))
PY
```

Expected: 打出截图路径 + 两个快照（至少 `snapshot_at` 能取到那颗按钮的 tag/testid/text）

- [ ] **Step 6: 确认没泄漏浏览器**

Run: `pgrep -fl "user-data-dir=.*ttt-profile" || echo "no leaked browser ✅"`
Expected: `no leaked browser ✅`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(primitives): loopback-gated browser session with self-cleaning profile"
```

---

## Task 6: 回放引擎与三态判定

**Files:**
- Modify: `core/compile/schema.py`（加 `Check`、`Checks`）
- Create: `core/replay/__init__.py`, `core/replay/result.py`, `core/replay/engine.py`
- Test: `tests/test_replay_three_states.py`, `tests/test_check_evaluation.py`, `tests/test_schema_check_roundtrip.py`

**Interfaces:**
- Consumes: `core.compile.schema.{Workflow, Step, Anchor}`、`core.compile.anchors.ElementSnapshot`
- Produces:
  - `core.compile.schema.Check`（frozen）：`id`、`after_step: int`、`kind: str`（`text_present`｜`count`）、`anchor: Anchor | None`、`expect: str`、`source: str`（**必填**）、`observed_at_compile: str = ""`；`to_json()`、`Check.from_json(d)`
  - `core.compile.schema.Checks`（frozen）：`workflow: str`、`checks: tuple[Check, ...]`；`to_json()`、`Checks.from_json(d)`、`Checks.load(path)`
  - `core.replay.result.RunResult`（frozen）：`workflow_id: str`、`status: str`、`reason: str`、`steps: tuple[StepOutcome, ...]`、`checks: tuple[CheckOutcome, ...]`、属性 `ok: bool`
  - `core.replay.result.StepOutcome`（frozen）：`step`、`status`、`snapshot`、`drift: str`、`message: str`
  - `core.replay.result.CheckOutcome`（frozen）：`check`、`ok: bool`、`actual: str`、`message: str`
  - `core.replay.result.PASS / FAIL_PRODUCT / FAIL_ANCHOR / FAIL_ENV`（字符串常量）
  - `core.replay.engine.run(workflow: Workflow, locator, checks: Checks | None = None) -> RunResult`
  - `core.replay.engine.probe(workflow: Workflow, locator) -> tuple[tuple[Step, ElementSnapshot | None], ...]`
  - `core.replay.engine.Locator`（`typing.Protocol`）：`goto(path)`、`click_xy(x, y)`、`fill(selector, text)`、`press(key)`、`wait_for(selector, state)`、`js(expr)`、`resolve(anchor) -> dict`、`snapshot_at(x, y)`、`snapshot_focused()`

**为什么引擎吃 `Locator` 协议而不是 `Session`**：三态判定是整个套件最值钱的逻辑，必须能不开浏览器就单测。`Session` 结构上满足这个协议，测试里用 `FakeLocator` 喂三种失败。

- [ ] **Step 1: 给 schema 补 Check**

追加到 `core/compile/schema.py` 末尾：

```python
@dataclass(frozen=True)
class Check:
    """一条断言。

    `source` 是必填的期望值出处 —— 这是防 oracle 锁错的机制：
    期望值只能来自外部（需求文档 / 夹具 / 手写），
    绝不能是"编译时看到什么就写什么"。core/lint 会拒收 source 缺失
    或形如 observed:* 的断言。
    """
    id: str
    after_step: int
    kind: str                                  # text_present | count
    anchor: Anchor | None
    expect: str
    source: str
    observed_at_compile: str = ""              # 只供人比对，永不参与回放判定

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "after_step": self.after_step,
            "kind": self.kind,
            "anchor": self.anchor.to_json() if self.anchor else None,
            "expect": self.expect,
            "source": self.source,
            "observed_at_compile": self.observed_at_compile,
        }

    @staticmethod
    def from_json(d: dict) -> "Check":
        return Check(
            id=str(d.get("id") or ""),
            after_step=int(d.get("after_step") or 0),
            kind=str(d.get("kind") or ""),
            anchor=Anchor.from_json(d["anchor"]) if d.get("anchor") else None,
            expect=str(d.get("expect") or ""),
            source=str(d.get("source") or ""),
            observed_at_compile=str(d.get("observed_at_compile") or ""),
        )


@dataclass(frozen=True)
class Checks:
    workflow: str
    checks: tuple[Check, ...] = ()

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "workflow": self.workflow,
            "checks": [c.to_json() for c in self.checks],
        }

    @staticmethod
    def from_json(d: dict) -> "Checks":
        version = d.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"checks schema_version {version!r} != {SCHEMA_VERSION}")
        return Checks(
            workflow=str(d.get("workflow") or ""),
            checks=tuple(Check.from_json(c) for c in d.get("checks") or []),
        )

    @staticmethod
    def load(path) -> "Checks":
        import json  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        return Checks.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
```

- [ ] **Step 2: 写失败测试 — 三态**

`tests/test_replay_three_states.py`：

```python
from core.compile.anchors import ElementSnapshot
from core.compile.schema import Anchor, Step, Workflow
from core.replay.engine import run
from core.replay.result import FAIL_ANCHOR, FAIL_ENV, FAIL_PRODUCT, PASS


class FakeLocator:
    """按脚本演戏的定位器：resolve_script[anchor.value] 决定这次解析结果。"""

    def __init__(self, resolve_script=None, raise_on=None):
        self.resolve_script = resolve_script or {}
        self.raise_on = raise_on or set()
        self.calls: list[str] = []
        self.resolved: list[str] = []      # 记录每次 resolve 的锚点，用来断言"没走到那一步"

    def _maybe_raise(self, name):
        if name in self.raise_on:
            raise RuntimeError(f"boom: {name}")

    def goto(self, path):
        self._maybe_raise("goto")
        self.calls.append(f"goto:{path}")

    def click_xy(self, x, y):
        self.calls.append(f"click:{x},{y}")

    def click_at_anchor(self, anchor):
        """🔴 必须实现：_perform 的 click 分支在没有 step.xy 时走这里，
        而绝大多数 click 测试都没给 xy。少了它 ⇒ AttributeError 被引擎的
        `except Exception` 吞成 FAIL_ENV，于是**每个** verdict 测试都返回
        FAIL_ENV，三态逻辑一条也没真的验到。（原 brief 漏了，实测过。）"""
        self.calls.append(f"click@{anchor.by}:{anchor.value or anchor.name}")

    def fill(self, selector, text):
        # 记下实际值：这样测试才能钉住"用的是 env 里的值，不是录制里的明文"
        self.calls.append(f"fill:{selector}={text}")

    def press(self, key):
        self.calls.append(f"press:{key}")

    def wait_for(self, selector, state="visible"):
        self._maybe_raise("wait_for")
        self.calls.append(f"wait:{selector}")

    def js(self, expr):
        return None

    def resolve(self, anchor):
        self._maybe_raise("resolve")
        key = anchor.value or anchor.name
        self.resolved.append(key)
        return self.resolve_script.get(key, {"count": 1, "snap": None, "drift": ""})

    def snapshot_at(self, x, y):
        return None

    def snapshot_focused(self):
        return None


def _wf(*steps) -> Workflow:
    return Workflow(id="wf-test", title="t", target="demo", steps=steps)


A_TEXT = Anchor(by="text", value="新建", copy_sensitive=True)
A_TESTID = Anchor(by="testid", value="create-dialog")


def test_all_steps_resolve_means_pass():
    wf = _wf(Step(n=1, action="goto", path="/list"),
             Step(n=2, action="click", anchor=A_TESTID))
    locator = FakeLocator()
    result = run(wf, locator)
    assert result.status == PASS
    assert result.ok
    # 没有 step.xy ⇒ 走 click_at_anchor（而不是坐标），且点的是锚点定位到的元素
    assert locator.calls == ["goto:/list", "click@testid:create-dialog"]


def test_anchor_found_but_check_fails_is_a_product_failure():
    wf = _wf(Step(n=1, action="wait_for", anchor=A_TESTID, selector="#x"))
    from core.compile.schema import Check, Checks
    checks = Checks(workflow="wf-test", checks=[
        Check(id="c1", after_step=1, kind="text_present", anchor=A_TESTID,
              expect="Create a new item?", source="prd:demo#1"),
    ])
    locator = FakeLocator(resolve_script={
        "create-dialog": {"count": 1, "snap": ElementSnapshot(tag="dialog", role="", name="", text="已改文案", testid="create-dialog"), "drift": ""},
    })
    result = run(wf, locator, checks)
    assert result.status == FAIL_PRODUCT
    assert result.reason == "assertion"


def test_anchor_missing_with_a_drift_candidate_is_a_product_failure():
    wf = _wf(Step(n=1, action="click", anchor=A_TEXT))
    locator = FakeLocator(resolve_script={
        "新建": {"count": 0, "snap": None, "drift": "立即新建"},
    })
    result = run(wf, locator)
    assert result.status == FAIL_PRODUCT
    assert result.reason == "anchor_drift"
    assert result.steps[-1].drift == "立即新建"


def test_anchor_missing_with_no_drift_candidate_is_a_script_problem():
    wf = _wf(Step(n=1, action="click", anchor=A_TESTID))
    locator = FakeLocator(resolve_script={"create-dialog": {"count": 0, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert result.status == FAIL_ANCHOR
    assert result.reason == "missing"


def test_an_ambiguous_anchor_is_a_script_problem():
    wf = _wf(Step(n=1, action="click", anchor=A_TEXT))
    locator = FakeLocator(resolve_script={"新建": {"count": 3, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert result.status == FAIL_ANCHOR
    assert result.reason == "ambiguous"


def test_a_click_with_both_an_anchor_and_coordinates_dispatches_through_the_anchor():
    """🔴 回归（本次评审的 Critical）：`_perform` 曾经**先看 xy**。

    于是编译产物（既有语义锚点、又残留录制坐标）回放时永远点坐标 ——
    锚点反解被整个绕过，而三态验收**照样全绿**：`_assert_step` 里 resolve()
    在点击之前跑完，所以判定正常、只有点击落在错的地方，直到布局一变才
    以"断言莫名其妙失败"的形式炸出来。
    """
    wf = _wf(Step(n=1, action="click", xy=(412, 306), anchor=A_TESTID))
    locator = FakeLocator()
    result = run(wf, locator)
    assert result.status == PASS
    assert locator.calls == ["click@testid:create-dialog"]
    assert not any(c.startswith("click:") for c in locator.calls)


def test_a_click_with_only_coordinates_still_uses_them():
    """探针期跑的是草稿步：有 xy、还没挂锚点 ⇒ 只能用坐标。"""
    wf = _wf(Step(n=1, action="click", xy=(412, 306)))
    locator = FakeLocator()
    run(wf, locator)
    assert locator.calls == ["click:412,306"]


def test_a_click_with_neither_anchor_nor_coordinates_is_an_environment_failure():
    wf = _wf(Step(n=1, action="click"))
    result = run(wf, FakeLocator())
    assert result.status == FAIL_ENV
    assert "anchor or coordinates" in result.steps[0].message


def test_an_environment_error_that_blocks_the_wait_is_not_a_product_verdict():
    wf = _wf(Step(n=1, action="wait_for", anchor=A_TESTID, selector="#items"))
    locator = FakeLocator(raise_on={"wait_for"})
    result = run(wf, locator)
    assert result.status == FAIL_ENV
    assert result.reason == "environment"


def test_execution_stops_at_the_first_failing_step():
    """停在第 1 步：既不该发生任何点击，也不该去 resolve 第 2 步的锚点。"""
    wf = _wf(Step(n=1, action="click", anchor=Anchor(by="testid", value="gone")),
             Step(n=2, action="click", anchor=Anchor(by="testid", value="never")))
    locator = FakeLocator(resolve_script={"gone": {"count": 0, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert len(result.steps) == 1                      # 第 2 步根本不入结果
    assert result.steps[0].status == "anchor_missing"
    assert locator.calls == []                         # 一次点击都没发生
    assert locator.resolved == ["gone"]                # 只 resolve 了第 1 步


def test_xy_fallback_targets_are_reported_as_warnings_not_failures():
    wf = _wf(Step(n=1, action="click", anchor=Anchor(by="xy", value="10,20", fallback=True)))
    locator = FakeLocator(resolve_script={"10,20": {"count": 1, "snap": None, "drift": ""}})
    result = run(wf, locator)
    assert result.status == PASS
    assert result.steps[0].status == "ok"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_replay_three_states.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.replay.engine'`

- [ ] **Step 4: 实现 result**

`core/replay/result.py`：

```python
"""回放结果模型：三态 + reason，以及"本次未得出结论"的标注。

三态只有 PASS / FAIL_PRODUCT / FAIL_ANCHOR（spec §4.2）。
FAIL_ENV 与 STALE_TARGET 是"本次未得出结论"，由 preflight 产生，
不构成第四态 —— 它们表示"现在还不能下判"。
"""
from __future__ import annotations

from dataclasses import dataclass, field

PASS = "PASS"
FAIL_PRODUCT = "FAIL_PRODUCT"
FAIL_ANCHOR = "FAIL_ANCHOR"
FAIL_ENV = "FAIL_ENV"
STALE_TARGET = "STALE_TARGET"

# 产品结论只可能是这两个之一；其余都不是结论。
PRODUCT_VERDICTS = (PASS, FAIL_PRODUCT, FAIL_ANCHOR)


@dataclass(frozen=True)
class StepOutcome:
    step: object                    # core.compile.schema.Step
    status: str                     # ok | anchor_missing | anchor_ambiguous | anchor_drift | error
    snapshot: object | None = None  # core.compile.anchors.ElementSnapshot
    drift: str = ""
    message: str = ""


@dataclass(frozen=True)
class CheckOutcome:
    check: object                   # core.compile.schema.Check
    ok: bool
    actual: str = ""
    message: str = ""


@dataclass(frozen=True)
class RunResult:
    workflow_id: str
    status: str
    reason: str = ""
    steps: tuple[StepOutcome, ...] = ()
    checks: tuple[CheckOutcome, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def summary(self) -> str:
        head = f"{self.status}" + (f" ({self.reason})" if self.reason else "")
        return f"{self.workflow_id}: {head} [steps={len(self.steps)} checks={len(self.checks)}]"
```

- [ ] **Step 5: 实现 engine**

`core/replay/engine.py`：

```python
"""步骤执行引擎 —— 两种模式共用一套动作派发。

assert 模式：按锚点定位，跑断言，产出三态。
probe  模式：动作执行**之前**抓一份元素快照，供编译器反解锚点（spec §4.2 鸿沟一）。

两种模式共用 _perform()，保证"编译时怎么走"和"回放时怎么走"是同一条路 ——
否则编译出来的步骤在回放时可能根本走不通。
"""
from __future__ import annotations

from typing import Mapping, Protocol

from ..compile.anchors import ElementSnapshot
from .result import FAIL_ANCHOR, FAIL_ENV, FAIL_PRODUCT, PASS, CheckOutcome, RunResult, StepOutcome


class Locator(Protocol):
    def goto(self, path: str) -> None: ...
    def click_xy(self, x: int, y: int) -> None: ...
    def click_at_anchor(self, anchor) -> None: ...
    def fill(self, selector: str, text: str) -> None: ...
    def press(self, key: str) -> None: ...
    def wait_for(self, selector: str, state: str = "visible") -> None: ...
    def js(self, expression: str): ...
    def resolve(self, anchor) -> dict: ...
    def snapshot_at(self, x: int, y: int) -> ElementSnapshot | None: ...
    def snapshot_focused(self) -> ElementSnapshot | None: ...


def _perform(step, locator, *, replay_value: str | None = None) -> None:
    """把一步变成对 locator 的调用。两种模式共用。

    `replay_value` 只由**探针模式**传入：编译期要复现录制当时的应用状态，
    就必须真的往输入框里敲当时那个值（否则"下一步才出现的元素"根本不会出现，
    锚点也就没得可解）。它只是这一次重放的内存参数 —— 绝不进 workflow
    （workflow 里 fill 的 value_ref 留空待人工补，见 compiler 的明文测试）。

    断言模式不传它：那时值只认 `env:<VAR>`，`_value_of` 会拒掉明文与未设变量。
    """
    if step.action == "goto":
        locator.goto(step.path)
    elif step.action == "click":
        # 🔴 **锚点优先，坐标只是探针期的退路。**
        #    探针跑的是**草稿步**（有 xy、还没挂锚点）⇒ 走坐标；
        #    回放跑的是**编译产物**（有语义锚点）⇒ 走 click_at_anchor。
        #    反过来写（先看 xy）会让回放永远点坐标 —— 编译器的全部意义就没了，
        #    而且它崩的时候表现为"断言莫名其妙失败"而不是 FAIL_ANCHOR：
        #    `_assert_step` 里 resolve() 在点击**之前**就跑完了，所以三态判定
        #    照样正常、验收照样全绿，只有点击落在错的地方。
        if step.anchor is not None:
            locator.click_at_anchor(step.anchor)
        elif step.xy:
            locator.click_xy(*step.xy)
        else:
            raise ValueError(f"step {step.n}: click needs either an anchor or coordinates")
    elif step.action == "fill":
        value = replay_value if replay_value is not None else _value_of(step)
        locator.fill(step.selector, value)
    elif step.action == "press":
        locator.press(step.key)
    elif step.action == "wait_for":
        locator.wait_for(step.selector, step.state)
    elif step.action == "wait_network_idle":
        locator.js("void 0")
    else:
        raise ValueError(f"unknown action {step.action!r}")


def _value_of(step) -> str:
    """只有 value_ref 是 env:<VAR> 时才取环境变量；明文值一律拒绝。

    录制的 fill_input 带的是当时的明文（可能是密码），绝不能进 workflow。
    """
    if not step.value_ref.startswith("env:"):
        raise ValueError(f"step {step.n}: fill requires value_ref=env:<VAR>, got {step.value_ref!r}")
    import os  # noqa: PLC0415

    name = step.value_ref[4:]
    if name not in os.environ:
        raise KeyError(f"step {step.n}: environment variable {name!r} is not set")
    return os.environ[name]


def run(workflow, locator, checks=None) -> RunResult:
    """回放一条 workflow。遇到第一个非 ok 的步骤就停 —— 后面的步骤结果不可信。"""
    outcomes: list[StepOutcome] = []
    check_outcomes: list[CheckOutcome] = []
    by_step: dict[int, list] = {}
    for check in (checks.checks if checks else ()):
        by_step.setdefault(check.after_step, []).append(check)

    for step in workflow.steps:
        try:
            oc = _assert_step(step, locator)
        except Exception as exc:  # 环境级问题：不是产品结论
            outcomes.append(StepOutcome(step=step, status="error", message=str(exc)))
            return RunResult(workflow.id, FAIL_ENV, reason="environment", steps=tuple(outcomes))

        outcomes.append(oc)
        if oc.status != "ok":
            status, reason = _classify(oc)
            return RunResult(workflow.id, status, reason=reason, steps=tuple(outcomes))

        for check in by_step.get(step.n, []):
            try:
                co = _evaluate(check, locator)
            except Exception as exc:
                # 🔴 断言期同样是环境可能出问题的地方（定位不到、页面还没就绪）。
                #    不接住的话异常会直接抛给调用方 —— 既不返回 RunResult，
                #    也不给任何结论，调用方拿到的是一个 traceback 而不是三态。
                #    与步骤期一致：归 FAIL_ENV。
                return RunResult(workflow.id, FAIL_ENV, reason="environment",
                                 steps=tuple(outcomes), checks=tuple(check_outcomes))
            check_outcomes.append(co)
            if not co.ok:
                return RunResult(workflow.id, FAIL_PRODUCT, reason="assertion",
                                 steps=tuple(outcomes), checks=tuple(check_outcomes))

    return RunResult(workflow.id, PASS, steps=tuple(outcomes), checks=tuple(check_outcomes))


def _assert_step(step, locator) -> StepOutcome:
    if step.action in ("goto", "wait_for", "wait_network_idle"):
        _perform(step, locator)
        return StepOutcome(step=step, status="ok")

    if step.anchor is None:
        _perform(step, locator)
        return StepOutcome(step=step, status="ok")

    got = locator.resolve(step.anchor)
    count, snap, drift = got.get("count", 0), got.get("snap"), got.get("drift", "")
    if count == 1:
        _perform(step, locator)
        return StepOutcome(step=step, status="ok", snapshot=snap)
    if count > 1:
        return StepOutcome(step=step, status="anchor_ambiguous",
                           message=f"anchor matched {count} elements")
    if drift:
        return StepOutcome(step=step, status="anchor_drift", drift=drift,
                           message=f"{step.anchor.by} anchor not found; nearest is {drift!r}")
    return StepOutcome(step=step, status="anchor_missing",
                       message=f"{step.anchor.by} anchor {step.anchor.value or step.anchor.name!r} not found")


def _classify(oc: StepOutcome) -> tuple[str, str]:
    if oc.status == "anchor_drift":
        return FAIL_PRODUCT, "anchor_drift"
    if oc.status == "anchor_ambiguous":
        return FAIL_ANCHOR, "ambiguous"
    return FAIL_ANCHOR, "missing"


def _evaluate(check, locator) -> CheckOutcome:
    got = locator.resolve(check.anchor) if check.anchor else {"count": 0, "snap": None}
    snap = got.get("snap")
    if check.kind == "count":
        actual = str(got.get("count", 0))
        ok = actual == str(check.expect)
        return CheckOutcome(check=check, ok=ok, actual=actual,
                            message="" if ok else f"expected count {check.expect}, got {actual}")
    if check.kind == "text_present":
        text = (snap.text if snap else "") or ""
        ok = check.expect in text
        return CheckOutcome(check=check, ok=ok, actual=text[:200],
                            message="" if ok else f"expected text {check.expect!r} not in {text[:80]!r}")
    raise ValueError(f"unknown check kind {check.kind!r}")


def probe(workflow, locator, *, replay_values: Mapping[int, str] | None = None):
    """编译期模式：走一遍步骤，在每个需要锚点的动作**之前**抓元素快照。

    `replay_values` 是 `{step.n: 当时敲进去的值}`，**只用于这一次重放**，
    用来复现录制的应用状态。它为空的步骤走 `_value_of`（即要求 env:<VAR>），
    所以探针模式也不是无条件放行明文值。

    返回 ((step, snapshot|None), ...)，顺序与 workflow.steps 一致。
    """
    replay_values = replay_values or {}
    out: list[tuple[object, ElementSnapshot | None]] = []
    for step in workflow.steps:
        snap = None
        if step.action == "click" and step.xy:
            snap = locator.snapshot_at(*step.xy)
        elif step.action == "press":
            snap = locator.snapshot_focused()
        out.append((step, snap))
        _perform(step, locator, replay_value=replay_values.get(step.n))
    return tuple(out)
```

---

## Task 7: 编译器 —— 带探针回放，把坐标反解成锚点

**Files:**
- Create: `core/compile/compiler.py`
- **Modify**: `core/replay/engine.py` —— ① 两个**关键字参数**（`_perform(..., *, replay_value=None)`、`probe(..., *, replay_values=None)`），有默认值、向后兼容；② 🔴 **`_perform` 的 click 分支改为锚点优先**（`if step.anchor is not None: click_at_anchor(...) elif step.xy: click_xy(...) else: raise`）。原实现先看 `xy`，于是编译产物回放时永远点坐标、锚点反解被绕过，**而三态验收照样全绿**（`resolve()` 在点击之前跑完）。
- **Modify**: `tests/test_replay_three_states.py` —— 补三条派发优先级测试（有锚点+有坐标 ⇒ 走锚点；只有坐标 ⇒ 走坐标；都没有 ⇒ FAIL_ENV）。
- Test: `tests/test_compiler_mapping.py`, `tests/test_compiler_unresolved.py`

**Interfaces:**
- Consumes: `core.transcript.recording.{Recording, TraceEvent}`、`core.compile.anchors.{candidates, ElementSnapshot}`、`core.compile.schema.{Workflow, Step, Anchor, Checks, Unresolved}`、`core.replay.engine.probe`
- Produces:
  - `core.compile.compiler.CompileResult`（frozen）：`workflow: Workflow`、`checks: Checks`、`unresolved: tuple[Unresolved, ...]`、`todo_asserts: tuple[str, ...]`；`write(dir: Path) -> None`
  - `core.compile.compiler.compile_recording(recording: Recording, target: str, locator, *, workflow_id: str | None = None) -> CompileResult`
  - `core.compile.compiler.EVENT_TO_ACTION: dict[str, str]`（事件 helper → 步骤 action，缺省表示"不产步骤"）
  - `core.compile.compiler.SUPPORTED_HELPERS: frozenset[str]`

**事件 → 步骤的映射表（v1 固定）**：

| 录制事件 | 步骤 action | 锚点从哪来 |
|---|---|---|
| `new_tab` / `goto_url` | `goto`（`path` 取 URL 的 path+query） | 不需要 |
| `wait_for_element` | `wait_for`（`selector`） | 不需要 |
| `fill_input` | `fill`（`selector`，`value_ref` **留空待补**） | 不需要 |
| `click_at_xy` | `click`（`xy` = 录制坐标） | **探针** `elementFromPoint` |
| `press_key` | `press`（`key`） | **探针** `activeElement` |
| `type_text` | ❌ **不编译，报 Unresolved**（理由：没有 selector，v1 不支持；改用 `fill_input`） | — |
| `scroll` / `wait` / `wait_for_load` / `wait_for_network_idle` / 标签页管理 | 不产步骤 | — |

**一条已知边界（必须写进 README，由 Task 10 落地）**：探针重放用的是录制里那个值。但录制器会把**密码框**的内容替换成 `•`，所以如果录制时是靠现场输入密码登录的，探针重放敲进去的是一串圆点，**过不了登录** ⇒ 登录之后的元素锚点解不出来，会如实落进 `Unresolved`。这不是 bug，是"录制里本来就没有那个值"的诚实后果。真正的日常用法是**在一个已登录的会话里录你要的那段流程**（浏览器带着会话 cookie），而不是每次都从登录开始录。

**两条硬规矩**：
1. **`fill_input` 的明文不进 workflow**。录制里带的是当时的明文（密码位被上游替换成 `•`，其余是明文），一律丢弃，`value_ref` 留空并进 `unresolved`——由人补成 `env:<VAR>`。测试里有一条专门断言 workflow 的 JSON 里不出现录制明文。
2. **反解不出就报 Unresolved，绝不降级成坐标**。只有 `xy` 候选（没有 testid/role/text/path 任何一个）= 解不出。

- [ ] **Step 1: 写失败测试 — 映射**

`tests/test_compiler_mapping.py`：

```python
import json
from pathlib import Path

from core.compile.compiler import compile_recording
from core.compile.anchors import ElementSnapshot
from core.transcript.recording import load_recording

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "smoke-login"


class ScriptedLocator:
    """按坐标返回预设快照，并按步骤记录动作。"""

    def __init__(self, snaps: dict[tuple[int, int], ElementSnapshot]):
        self.snaps = snaps
        self.calls: list[str] = []

    def goto(self, path): self.calls.append(f"goto:{path}")
    def click_xy(self, x, y): self.calls.append(f"click:{x},{y}")
    def click_at_anchor(self, anchor): self.calls.append(f"click@{anchor.by}")
    def fill(self, selector, text):
        # 记下值：这样测试才能断言"探针重放的是录制值"，而不是只看到 selector
        self.calls.append(f"fill:{selector}={text}")
    def press(self, key): self.calls.append(f"press:{key}")
    def wait_for(self, selector, state="visible"): self.calls.append(f"wait:{selector}")
    def js(self, expr): return None
    def resolve(self, anchor): return {"count": 1, "snap": None, "drift": ""}
    def snapshot_at(self, x, y): return self.snaps.get((x, y))
    def snapshot_focused(self): return None


BUTTON = ElementSnapshot(tag="button", role="button", name="新建", text="新建", testid="open-create",
                         attrs={}, path="body > button:nth-of-type(1)", rect={"x": 60, "y": 60, "w": 56, "h": 24})
DIALOG_BTN = ElementSnapshot(tag="button", role="button", name="确定", text="确定", testid="confirm-create",
                             attrs={}, path="dialog > form > button", rect={"x": 180, "y": 240, "w": 120, "h": 40})


def test_goto_steps_come_straight_from_the_url():
    result = compile_recording(load_recording(FIXTURE), target="demo",
                              locator=ScriptedLocator({}))
    first = result.workflow.steps[0]
    assert first.action == "goto"
    assert first.path == "/login"


def test_fill_steps_keep_the_selector_but_never_the_recorded_plaintext():
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    fills = [s for s in result.workflow.steps if s.action == "fill"]
    assert fills and fills[0].selector == "#username"
    assert fills[0].value_ref == ""
    # 🔴 断言必须只看 `steps`：顶层还带着 `target="demo"`，而 fixture 里录的
    #    用户名恰好也叫 "demo" —— 对**整个** workflow 序列化做子串匹配会永远为假，
    #    于是这条"明文没泄漏"的守卫永远不会真的在守。
    steps_json = json.dumps(result.workflow.to_json()["steps"], ensure_ascii=False)
    assert "demo" not in steps_json


def test_click_steps_get_anchors_resolved_from_the_probe():
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    clicks = [s for s in result.workflow.steps if s.action == "click"]
    assert [s.anchor.by for s in clicks] == ["testid", "testid", "testid"]
    assert clicks[0].anchor.value == "open-create"


def test_compiled_click_steps_drop_the_recorded_coordinates():
    """🔴 编译产物里的 click **不许**再带录制坐标。

    回放按锚点定位，坐标只有编译期探针用。留着它有两个害处：读代码的人会
    以为回放用坐标；以及万一 `_perform` 的优先级被改回"坐标优先"，
    产物会**静默**退回坐标回放 —— 而三态验收照样全绿，因为 `resolve()`
    在点击之前就跑完了。所以坐标必须在产物里被清掉，作为第二道保险。
    """
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    clicks = [s for s in result.workflow.steps if s.action == "click"]
    assert clicks
    assert all(s.anchor is not None for s in clicks)     # 每个 click 都有语义锚点
    assert all(s.xy is None for s in clicks)             # 且都不带坐标


def test_the_probe_replays_the_whole_recording_in_order():
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    assert loc.calls[0] == "goto:/login"
    assert "click:120,168" in loc.calls


def test_workflow_carries_its_provenance():
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    assert result.workflow.source["recording"] == "smoke-login"
    assert result.workflow.source["compiler"]


def test_todo_asserts_suggest_where_assertions_are_needed():
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    # _suggest 用**我们选中的那个锚点**来指认位置（优先 testid），
    # 所以这里断言的是 testid 名与 wait_for 的 selector，
    # 而不是界面上的人话文案（"确定"/"Items"）—— 后者一个都不会出现。
    assert any("open-create" in line for line in result.todo_asserts)
    assert any("confirm-create" in line for line in result.todo_asserts)
    assert any("#items" in line for line in result.todo_asserts)


def test_the_probe_replays_recorded_fill_values_in_memory_only():
    """🔴 这条测试的**两面**都要断言，缺一面就等于没测：

    探针必须用录制值重放（否则应用状态不复现，锚点解不出来），
    而那个值又绝不能出现在 workflow 里（明文可能是密码）。
    只断言"没进 workflow"会漏掉"根本没重放"这个同样坏的结果。
    """
    loc = ScriptedLocator({(120, 168): BUTTON, (88, 72): BUTTON, (210, 260): DIALOG_BTN})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)

    assert any(c == "fill:#username=demo" for c in loc.calls), loc.calls
    steps_json = json.dumps(result.workflow.to_json()["steps"], ensure_ascii=False)
    assert "demo" not in steps_json


def test_compiled_checks_start_empty_because_expectations_must_come_from_outside():
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    assert result.checks.checks == ()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_compiler_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.compile.compiler'`

- [ ] **Step 3: 写失败测试 — Unresolved**

`tests/test_compiler_unresolved.py`：

```python
import json
from pathlib import Path

from core.compile.anchors import ElementSnapshot
from core.compile.compiler import compile_recording
from core.transcript.recording import TraceEvent, load_recording

from tests.test_compiler_mapping import ScriptedLocator

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "smoke-login"


def _snap(**over):
    # 🔴 `path` 默认必须是**空串**：candidates() 把 path 当**语义**候选（优先级在
    #    xy 之前），留个非空 path 就永远解得出锚点 —— 于是
    #    test_an_element_with_no_semantic_hook_... 那条会变成假绿/假红。
    base = dict(tag="div", role="", name="", text="", testid="", attrs={},
                path="", rect={"x": 1, "y": 2, "w": 3, "h": 4})
    base.update(over)
    return ElementSnapshot(**base)


def test_an_element_with_no_semantic_hook_becomes_unresolved_not_an_xy_anchor():
    loc = ScriptedLocator({(120, 168): _snap(), (88, 72): _snap(), (210, 260): _snap()})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)

    # 🔴 不能用 `all(... for u in result.unresolved)`：fixture 里那个 fill_input
    #    必然产出一条 `value_ref_required`，`all()` 会被它带倒 ——
    #    这条原本就是这么写错的。按 helper 收窄到"点击造成的那些"。
    click_gaps = [u for u in result.unresolved if u.helper == "click_at_xy"]
    assert [u.reason for u in click_gaps] == ["no_semantic_hook"] * 3
    assert any(u.reason == "value_ref_required" for u in result.unresolved)   # 那条也在
    assert all(s.anchor.by != "xy" for s in result.workflow.steps if s.action == "click")


def test_unresolved_entries_carry_the_original_event_and_the_candidates():
    """反解不出的条目必须自带**原始事件**与**我们确实找到的候选**。

    🔴 候选是什么，要说实话：一个"全无钩子"的元素，`candidates()` 只给得出
    xy 兜底。所以能断言的是"带上了候选"且"最后一项是打了 fallback 的 xy"。
    原先这条用 `_snap(text="登录")` —— 有 text 就是**有**语义钩子，那个点击
    会被正常编译、根本不会落进 unresolved，测试自然找不到 x=120 那条。
    """
    loc = ScriptedLocator({(120, 168): _snap(), (88, 72): _snap(), (210, 260): _snap()})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    entry = [u for u in result.unresolved if u.event.get("x") == 120][0]
    assert entry.helper == "click_at_xy"
    assert entry.event["y"] == 168
    assert entry.event["url"].endswith("/login")
    assert "text" not in entry.event                 # 敲进去的值已被抹掉（见下）
    assert entry.candidates, "反解不出的条目也必须带上候选（哪怕只有兜底）"
    assert entry.candidates[-1].by == "xy" and entry.candidates[-1].fallback is True


def test_unresolved_never_carries_the_recorded_fill_value():
    """🔴 隐私回归：`unresolved.jsonl` 是要落盘的。

    `_raw()` 曾经原样带上 `fill_input.text`（明文/圆点），于是"明文不进磁盘"
    被 Unresolved 这条侧路绕过 —— workflow 那边测过了，这条侧路没人看。
    位置信息要留着，人工补锚点靠它。
    """
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    blob = "\n".join(json.dumps(u.to_json(), ensure_ascii=False) for u in result.unresolved)
    assert "demo" not in blob
    assert any(u.event.get("selector") == "#username" for u in result.unresolved)


def test_the_written_unresolved_file_carries_no_recorded_value(tmp_path):
    """在最外层再验一次 —— `write()` 才是真正碰文件的地方。

    只查内存对象的话，将来有人在 write() 里换一种序列化方式就绕过去了。
    """
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    out = tmp_path / "compiled"
    result.write(out)
    assert "demo" not in (out / "unresolved.jsonl").read_text(encoding="utf-8")


def test_a_path_only_element_does_get_a_path_anchor():
    """边界：path 也算**语义**候选（优先级在 xy 之前）。

    所以"反解不出"只发生在 testid/role/text/path **全空**时。这条把边界钉住，
    免得以后有人以为 path 是兜底手段、把它挪到 xy 之后 —— 那会静默改变
    编译器的产出物，而不只是排序。
    """
    only_path = _snap(path="body > div:nth-of-type(3)")
    loc = ScriptedLocator({(120, 168): only_path, (88, 72): only_path, (210, 260): only_path})
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    anchors = [s.anchor.by for s in result.workflow.steps if s.action == "click"]
    assert anchors and all(b == "path" for b in anchors)
    # 同样按 helper 收窄：那个 fill 的 value_ref_required 一直都会在
    assert not [u for u in result.unresolved if u.helper == "click_at_xy"]


def test_a_click_that_probes_to_nothing_is_unresolved():
    loc = ScriptedLocator({})   # 任何坐标都探不到元素
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=loc)
    assert any(u.reason == "probe_returned_nothing" for u in result.unresolved)


def test_type_text_is_reported_unsupported_with_a_remedy(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "meta.json").write_text('{"name":"r","title":"","started":0.0}', encoding="utf-8")
    (d / "events.jsonl").write_text(
        json.dumps({"helper": "type_text", "text": "hello", "w": 800, "h": 600}) + "\n",
        encoding="utf-8",
    )
    result = compile_recording(load_recording(d), target="demo", locator=ScriptedLocator({}))
    assert any(u.reason == "type_text_unsupported" for u in result.unresolved)
    assert not any(s.action == "type" for s in result.workflow.steps)


def test_fill_without_a_value_ref_is_listed_for_a_human(tmp_path):
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    assert any(u.reason == "value_ref_required" for u in result.unresolved)


def test_write_emits_the_four_artifacts(tmp_path):
    result = compile_recording(load_recording(FIXTURE), target="demo", locator=ScriptedLocator({}))
    out = tmp_path / "compiled"
    result.write(out)
    assert (out / "workflow.json").is_file()
    assert (out / "checks.json").is_file()
    assert (out / "unresolved.jsonl").is_file()
    assert (out / "checks.todo.md").is_file()
    assert json.loads((out / "workflow.json").read_text())["id"] == result.workflow.id
```

- [ ] **Step 4: 实现**

`core/compile/compiler.py`：

```python
"""把一次录制编译成声明式回归。

编译 = **一次带探针的回放**：按录制顺序重放，在每个需要锚点的动作执行之前
问一次浏览器"这儿是哪个元素"，再由 anchors.candidates() 排序产出候选锚点。
编译器因此复用回放引擎（core.replay.engine.probe），两者是同一套动作派发。

两条不妥协的规矩（spec §4.2 两个鸿沟）：
1. 反解不出 → Unresolved，**绝不降级成坐标**。
2. 录制里的明文值不进 workflow；期望值一律留空，等外部来源补。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..replay.engine import probe
from ..transcript.recording import Recording, TraceEvent
from .anchors import ElementSnapshot, candidates
from .schema import Anchor, Checks, Step, Unresolved, Workflow

COMPILER_VERSION = "0.1.0"

# 录制事件 → 步骤 action。缺省 = 不产步骤（只读、等待、标签页管理）。
EVENT_TO_ACTION: dict[str, str] = {
    "new_tab": "goto",
    "goto_url": "goto",
    "wait_for_element": "wait_for",
    "fill_input": "fill",
    "click_at_xy": "click",
    "press_key": "press",
}

SUPPORTED_HELPERS: frozenset[str] = frozenset(EVENT_TO_ACTION)


@dataclass(frozen=True)
class CompileResult:
    workflow: Workflow
    checks: Checks
    unresolved: tuple[Unresolved, ...] = ()
    todo_asserts: tuple[str, ...] = ()

    def write(self, directory: Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "workflow.json").write_text(
            json.dumps(self.workflow.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (directory / "checks.json").write_text(
            json.dumps(self.checks.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (directory / "unresolved.jsonl").open("w", encoding="utf-8") as f:
            for item in self.unresolved:
                f.write(json.dumps(item.to_json(), ensure_ascii=False) + "\n")
        (directory / "checks.todo.md").write_text(self._todo_md(), encoding="utf-8")

    def _todo_md(self) -> str:
        lines = [
            f"# 待补断言：{self.workflow.id}",
            "",
            "编译器只给路径与观测点，**期望值必须来自外部**（需求文档 / 夹具 / 手写）。",
            "把下面每一条翻成 checks.json 里的一条 Check，并填上 `source`。",
            "🔴 不要直接抄「编译时看到什么」——那是把现状固化成基线。",
            "",
        ]
        lines += [f"- [ ] {line}" for line in self.todo_asserts] or ["- （无可建议的断言点）"]
        if self.unresolved:
            lines += ["", "## 需要人工处理的未解项", ""]
            lines += [
                f"- seq {u.seq} `{u.helper}` — {u.reason}"
                for u in self.unresolved
            ]
        return "\n".join(lines) + "\n"


def _path_of(url: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _draft_steps(recording: Recording, unresolved: list[Unresolved]) -> tuple[list[Step], list[TraceEvent]]:
    """事件 → 草稿步骤。

    🔴 同时返回「每个步骤对应哪个事件」——探针结果是按步骤顺序回来的，
    必须能一一对回去。不要事后用事件列表重新推一遍：带 `click` 但没有坐标的事件
    不会产步骤，重推就会错位一格，后面所有锚点全安在错的步骤上。
    """
    steps: list[Step] = []
    origins: list[TraceEvent] = []
    for event in recording.actionable():
        action = EVENT_TO_ACTION.get(event.helper)
        if action is None:
            if event.helper == "type_text":
                unresolved.append(Unresolved(
                    seq=event.seq, helper=event.helper, event=_raw(event),
                    reason="type_text_unsupported",
                ))
            continue

        n = len(steps) + 1
        if action == "goto":
            steps.append(Step(n=n, action="goto", path=_path_of(str(event.detail.get("to") or ""))))
        elif action == "wait_for":
            steps.append(Step(n=n, action="wait_for", selector=str(event.detail.get("selector") or "")))
        elif action == "fill":
            steps.append(Step(n=n, action="fill", selector=str(event.detail.get("selector") or "")))
            unresolved.append(Unresolved(
                seq=event.seq, helper=event.helper, event=_raw(event),
                reason="value_ref_required",
            ))
        elif action == "click":
            xy = event.xy()
            if not xy:
                unresolved.append(Unresolved(
                    seq=event.seq, helper=event.helper, event=_raw(event),
                    reason="click_without_coordinates",
                ))
                continue
            steps.append(Step(n=n, action="click", xy=xy))
        elif action == "press":
            steps.append(Step(n=n, action="press", key=str(event.detail.get("key") or "")))
        else:
            continue

        origins.append(event)
    return steps, origins


_REDACTED_DETAIL_KEYS = frozenset({"text"})   # 录制里"敲进去的值"


def _raw(event: TraceEvent) -> dict:
    """Unresolved 里附带的原始事件。

    🔴 必须**抹掉敲进去的值**。`fill_input` 的 `text` 是明文（密码位被上游换成
    圆点，其余是明文），而 `unresolved.jsonl` 是**要落盘**的 —— 不抹的话，
    "明文不进磁盘"这条就被 Unresolved 这条侧路整个绕过（原来就是这样）。
    它在探针重放里用一次就够了（见 compile_recording 的 replay_values），不该留档。

    位置信息（`selector` / `x` / `y` / `box`）**要保留** —— 人工补锚点看的正是这些。
    """
    raw = {"seq": event.seq, "helper": event.helper, "url": event.url}
    raw.update({k: v for k, v in event.detail.items() if k not in _REDACTED_DETAIL_KEYS})
    if event.box:
        raw["box"] = event.box
    return raw


def compile_recording(
    recording: Recording,
    target: str,
    locator,
    *,
    workflow_id: str | None = None,
) -> CompileResult:
    unresolved: list[Unresolved] = []
    draft, origins = _draft_steps(recording, unresolved)

    workflow = Workflow(
        id=workflow_id or f"wf-{recording.name}",
        title=recording.title or recording.name,
        target=target,
        source={
            "recording": recording.name,
            "compiled_at": _now(),
            "compiler": COMPILER_VERSION,
            "viewport": list(recording.viewport) if recording.viewport else None,
        },
        steps=tuple(draft),
    )

    # 🔴 录制里的 fill 明文只在**这一次探针重放**里用：不复现当时的状态，
    #    "点击后才出现的元素"就不会出现，锚点也就无从反解。
    #    而 workflow 里的 fill 一律 value_ref 留空 + 进 Unresolved —— 明文绝不落盘。
    #    两条断言（"探针确实用了录制值" + "它没进 workflow"）合起来才说明这件事做对了。
    replay_values = {
        step.n: str(event.detail.get("text") or "")
        for step, event in zip(draft, origins)
        if step.action == "fill"
    }

    observed = probe(workflow, locator, replay_values=replay_values)
    assert len(observed) == len(origins), "probe() must return one entry per step"
    steps: list[Step] = []
    todo: list[str] = []

    for (step, snap), event in zip(observed, origins):
        if step.action in ("click", "press"):
            if snap is None:
                unresolved.append(Unresolved(
                    seq=event.seq, helper=event.helper, event=_raw(event),
                    reason="probe_returned_nothing",
                ))
                continue
            ranked = candidates(snap)
            semantic = [a for a in ranked if a.by != "xy"]
            if not semantic:
                unresolved.append(Unresolved(
                    seq=event.seq, helper=event.helper, event=_raw(event),
                    candidates=ranked, reason="no_semantic_hook",
                ))
                continue
            # 挂上语义锚点的同时**清掉录制坐标**：回放按锚点走，坐标不该留在产物里。
            # 这是第二道保险 —— 万一 _perform 的优先级被人改回"坐标优先"，
            # 产物里没有坐标就退不回去（而三态验收不会替你发现这件事）。
            step = replace(step, anchor=semantic[0], xy=None)
        steps.append(step)
        if snap is not None:
            todo.append(_suggest(step, snap, event))
        elif step.action == "wait_for":
            todo.append(f"step {step.n}: 断言 `{step.selector}` 的内容/条数（期望值待外部来源）")

    # 步骤被丢弃后编号会留洞，重排一次让 after_step 好写
    steps = [replace(s, n=i + 1) for i, s in enumerate(steps)]
    compiled = Workflow(
        id=workflow.id, title=workflow.title, target=target,
        source=workflow.source, steps=tuple(steps),
    )
    return CompileResult(
        workflow=compiled,
        checks=Checks(workflow=compiled.id, checks=()),
        unresolved=tuple(unresolved),
        todo_asserts=tuple(todo),
    )


def _suggest(step: Step, snap: ElementSnapshot, event: TraceEvent) -> str:
    where = snap.testid or snap.name or snap.text or snap.path
    return f"step {step.n} ({step.action} `{where}`): 断言语义 —— 期望值请从需求文档/夹具取"


def _now() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

导入段改为：

```python
from dataclasses import dataclass, replace
```

（`_as_dict()` 不需要了 —— 改字段用 `dataclasses.replace(step, anchor=...)`。`Step.xy` 已在 Task 4 定义。）

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_compiler_mapping.py tests/test_compiler_unresolved.py -v`
Expected: 18 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(compile): probe-replay compiler — coordinates become semantic anchors, unknowns stay unresolved"
```

---

## Task 8: 断言 lint + 五道闸的可机械化部分

**Files:**
- Create: `core/lint/__init__.py`, `core/lint/checks_lint.py`
- Create: `checks/__init__.py`（空）, `checks/evidence_shape.py`
- Test: `tests/test_checks_lint.py`, `tests/test_evidence_shape.py`

**Interfaces:**
- Consumes: `core.compile.schema.{Workflow, Checks, Check}`
- Produces:
  - `core/lint/checks_lint.py`：`lint(checks: Checks, workflow: Workflow | None = None) -> tuple[str, ...]`（返回违规列表，空 = 通过）；`main(argv) -> int`（0 通过 / 1 违规）；`REJECT_NO_ASSERTIONS`、`REJECT_MISSING_SOURCE`、`REJECT_OBSERVED_SOURCE`、`WARN_XY_FALLBACK` 常量
  - `checks/evidence_shape.py`：`lint_results(records: list[dict]) -> tuple[str, ...]`；`main(argv) -> int`；每条记录形状 `{"tc": str, "status": "passed"|"failed"|"blocked"|"skipped"|"pending", "actual_result": str, "screenshots": list[str], "bug": str|None, "bug_body": str, "lane": "ui"|"api"}`。`screenshots` 只管"有没有留图"；`bug_body` 才是"图有没有嵌进单内"的判断依据 —— 两者不能混。

- [ ] **Step 1: 写失败测试 — 断言 lint**

`tests/test_checks_lint.py`：

```python
import json

from core.compile.schema import Anchor, Check, Checks, Step, Workflow
from core.lint.checks_lint import (
    REJECT_MISSING_SOURCE, REJECT_NO_ASSERTIONS, REJECT_OBSERVED_SOURCE, WARN_XY_FALLBACK,
    lint, main,
)

A = Anchor(by="testid", value="item-list")
WF = Workflow(id="w", title="t", target="demo",
              steps=(Step(n=1, action="click", anchor=A),))


def test_a_workflow_with_no_assertions_is_rejected():
    violations = lint(Checks(workflow="w", checks=()), WF)
    assert REJECT_NO_ASSERTIONS in violations[0]


def test_a_check_without_a_source_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="x", source="")])
    assert any(REJECT_MISSING_SOURCE in v for v in lint(checks, WF))


def test_a_check_whose_source_is_the_compile_time_observation_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="x", source="observed:whatever")])
    assert any(REJECT_OBSERVED_SOURCE in v for v in lint(checks, WF))


def test_a_well_sourced_check_passes():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="text_present",
                                                anchor=A, expect="x", source="prd:demo#items")])
    assert lint(checks, WF) == ()


def test_fixture_and_manual_sources_are_accepted():
    for source in ("fixture:seed", "manual:reviewed-by-human"):
        checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                    anchor=A, expect="3", source=source)])
        assert lint(checks, WF) == ()


def test_an_xy_fallback_anchor_is_a_warning_not_a_rejection():
    wf = Workflow(id="w", title="t", target="demo",
                  steps=(Step(n=1, action="click", anchor=Anchor(by="xy", value="1,2", fallback=True)),))
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=A, expect="3", source="prd:x")])
    warnings = [v for v in lint(checks, wf) if WARN_XY_FALLBACK in v]
    assert warnings and all(v.startswith("WARN") for v in warnings)


def test_a_check_referring_to_a_step_that_does_not_exist_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=99, kind="count",
                                                anchor=A, expect="3", source="prd:x")])
    assert any("after_step" in v for v in lint(checks, WF))


# —— CLI 的退出码：WARN 不挡合并，REJECT 必须挡 ——

def test_the_cli_exits_zero_for_warnings_only(tmp_path, capsys):
    """🔴 WARN 不改退出码。少了这条，把 WARN 当 REJECT 的实现也能全绿 ——
    而那个实现会挡住每一次合并。"""
    wf = tmp_path / "workflow.json"
    wf.write_text(json.dumps(
        Workflow(id="w", title="t", target="demo",
                 steps=(Step(n=1, action="click",
                             anchor=Anchor(by="xy", value="1,2", fallback=True)),)
        ).to_json(), ensure_ascii=False), encoding="utf-8")
    ck = tmp_path / "checks.json"
    ck.write_text(json.dumps(
        Checks(workflow="w", checks=(Check(id="c1", after_step=1, kind="count",
                                           anchor=Anchor(by="testid", value="x"),
                                           expect="3", source="prd:x"),)).to_json(),
        ensure_ascii=False), encoding="utf-8")

    assert main([str(ck), "--workflow", str(wf)]) == 0
    out = capsys.readouterr()
    assert "WARN" in out.out          # 警告走 stdout
    assert "REJECT" not in out.err    # 没有 reject


def test_the_cli_exits_nonzero_for_a_reject(tmp_path, capsys):
    ck = tmp_path / "checks.json"
    ck.write_text(json.dumps(Checks(workflow="w").to_json(), ensure_ascii=False), encoding="utf-8")

    assert main([str(ck)]) == 1
    out = capsys.readouterr()
    assert "REJECT" in out.err        # reject 走 stderr


def test_a_check_anchored_nowhere_is_rejected():
    checks = Checks(workflow="w", checks=[Check(id="c1", after_step=1, kind="count",
                                                anchor=None, expect="3", source="prd:x")])
    assert any("anchor" in v for v in lint(checks, WF))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_checks_lint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.lint.checks_lint'`

- [ ] **Step 3: 实现 checks_lint**

`core/lint/checks_lint.py`：

```python
"""断言侧的反模式检查。

拒收三类（REJECT 前缀 = 退出码 1）：
- 整个 workflow 一条断言都没有
- 断言的 source 缺失
- source 形如 observed:* —— 即"编译时看到什么就写什么"，等于把 bug 固化成基线

另有一类 WARN（不挡退出码，但报告里必须单列）：
- 步骤用了 xy 兜底锚点，等于把回归绑在坐标上

用法：
    python -m core.lint.checks_lint checks.json --workflow workflow.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..compile.schema import Checks, Workflow

REJECT_NO_ASSERTIONS = "REJECT:no_assertions"
REJECT_MISSING_SOURCE = "REJECT:missing_source"
REJECT_OBSERVED_SOURCE = "REJECT:observed_source"
WARN_XY_FALLBACK = "WARN:xy_fallback"

_ACCEPTED_SOURCE_PREFIXES = ("prd:", "fixture:", "manual:", "issue:", "spec:")


def lint(checks: Checks, workflow: Workflow | None = None) -> tuple[str, ...]:
    violations: list[str] = []

    if not checks.checks:
        violations.append(
            f"{REJECT_NO_ASSERTIONS} — workflow {checks.workflow!r} 没有任何断言；"
            "编译产物必须由人补上期望值后才算可用"
        )

    valid_steps = {s.n for s in workflow.steps} if workflow else None
    for check in checks.checks:
        where = f"check {check.id!r}"

        if not check.source:
            violations.append(
                f"{REJECT_MISSING_SOURCE} — {where} 没有 source；"
                "期望值必须来自需求文档/夹具/手写"
            )
        elif check.source.startswith("observed:"):
            violations.append(
                f"{REJECT_OBSERVED_SOURCE} — {where} 的 source 是编译期观测值；"
                "这会把现状固化成基线（oracle 锁错）"
            )
        elif not check.source.startswith(_ACCEPTED_SOURCE_PREFIXES):
            violations.append(
                f"{REJECT_MISSING_SOURCE} — {where} 的 source {check.source!r} 不是已知前缀 "
                f"{_ACCEPTED_SOURCE_PREFIXES}"
            )

        if check.anchor is None:
            violations.append(f"{REJECT_MISSING_SOURCE} — {where} 没有 anchor，无法定位")
        elif check.anchor.by == "xy":
            violations.append(
                f"{WARN_XY_FALLBACK} — {where} 用坐标定位，回归会跟分辨率绑定"
            )

        if valid_steps is not None and check.after_step not in valid_steps:
            violations.append(
                f"{REJECT_MISSING_SOURCE} — {where} 的 after_step={check.after_step} "
                f"不在 workflow 的步骤 {sorted(valid_steps)} 里"
            )

    if workflow:
        for step in workflow.steps:
            if step.anchor and step.anchor.by == "xy":
                violations.append(
                    f"{WARN_XY_FALLBACK} — step {step.n} 用坐标兜底定位"
                )
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="checks_lint")
    ap.add_argument("checks", type=Path)
    ap.add_argument("--workflow", type=Path, default=None)
    args = ap.parse_args(argv)

    checks = Checks.from_json(json.loads(args.checks.read_text(encoding="utf-8")))
    workflow = (
        Workflow.from_json(json.loads(args.workflow.read_text(encoding="utf-8")))
        if args.workflow
        else None
    )

    violations = lint(checks, workflow)
    rejects = [v for v in violations if v.startswith("REJECT")]
    warns = [v for v in violations if v.startswith("WARN")]

    for v in warns:
        print(v)
    for v in rejects:
        print(v, file=sys.stderr)
    if rejects:
        return 1
    print("✅ checks lint passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_checks_lint.py -v`
Expected: 8 passed

- [ ] **Step 5: 写失败测试 — 五道闸的字段检查**

`tests/test_evidence_shape.py`：

```python
from checks.evidence_shape import lint_results


def rec(**over) -> dict:
    base = dict(tc="TC-1", status="passed", actual_result="", screenshots=[],
                bug=None, lane="api")
    base.update(over)
    return base


def test_a_passed_case_with_a_concrete_value_is_not_flagged_for_a_missing_value():
    """只验「具体值」这一个维度。

    🔴 这条原本写的是 `== ()`，与实现自相矛盾：通过态**还**要求一条负控结论，
    而这个 fixture 没有 ⇒ 必然多出一条 "no negative control" 违规（那条违规是
    对的，它另有自己的测试）。所以这里只断言"具体值"这一维没被误报，
    同时把"该报的那条照报"也钉住 —— 两面都断言，才不会被单边期望带偏。
    """
    violations = lint_results([rec(actual_result="HTTP 200, balance=12.34")])
    assert not any("no concrete value" in v for v in violations)
    assert any("negative control" in v for v in violations)


def test_a_passed_case_that_only_says_it_matched_expectations_is_rejected():
    violations = lint_results([rec(actual_result="符合预期")])
    assert any("no concrete value" in v for v in violations)


def test_a_passed_case_with_no_negative_control_note_is_rejected():
    violations = lint_results([rec(actual_result="HTTP 200")])
    assert any("negative control" in v for v in violations)


def test_a_passed_case_with_a_negative_control_note_is_accepted():
    assert lint_results([
        rec(actual_result="HTTP 200, balance=12.34；负控：把 amount 换 0 本条必红")
    ]) == ()


def test_a_ui_pass_without_a_screenshot_is_rejected():
    violations = lint_results([
        rec(lane="ui", actual_result="见表头 3 列；负控：删掉该列必红")
    ])
    assert any("screenshot" in v for v in violations)


def test_a_ui_pass_with_a_screenshot_is_accepted():
    assert lint_results([
        rec(lane="ui", actual_result="见表头 3 列；负控：删掉该列必红",
            screenshots=["/tmp/shots/tc1.png"])
    ]) == ()


def test_a_failed_case_without_a_bug_id_is_rejected():
    violations = lint_results([rec(status="failed", actual_result="余额少 1")])
    # 断言片段必须与实现文案一致（实现是 "failed without a bug id"）。
    # 我把 T8 区段里 9 条文案断言逐条核过，只有这一条对不上。
    assert any("without a bug id" in v for v in violations)


def test_a_ui_failure_must_have_an_embedded_screenshot_not_just_a_path():
    violations = lint_results([
        rec(status="failed", lane="ui", actual_result="按钮不见了",
            bug="BUG-7", screenshots=["/tmp/shots/tc1.png"])
    ])
    assert any("embedded" in v for v in violations)


def test_a_ui_failure_with_an_embedded_image_in_the_bug_body_is_accepted():
    assert lint_results([
        rec(status="failed", lane="ui", actual_result="按钮不见了", bug="BUG-7",
            screenshots=[], bug_body="见下图：![](https://example.com/uploads/abc.png)")
    ]) == ()


def test_a_ui_failure_with_the_image_only_in_the_screenshots_field_is_rejected():
    """回归：把 screenshots 与 bug_body 拼起来一起正则，会让"图只躺在字段里、
    正文一个字没有"也算嵌图 —— 而这条检查的语义就是"必须嵌进单内"。
    原来那条验收测试本身就是用 screenshots 装图，等于在复现这个绕过。"""
    violations = lint_results([
        rec(status="failed", lane="ui", actual_result="按钮不见了", bug="BUG-7",
            screenshots=["![](https://example.com/uploads/abc.png)"], bug_body="")
    ])
    assert any("embedded" in v for v in violations)


def test_a_blocked_case_must_say_what_unblocks_it():
    violations = lint_results([rec(status="blocked", actual_result="缺账号")])
    assert any("unblock" in v for v in violations)


def test_a_pending_case_is_always_a_violation_because_the_run_is_incomplete():
    violations = lint_results([rec(status="pending")])
    assert any("pending" in v for v in violations)
```

- [ ] **Step 6: 实现 evidence_shape**

`checks/evidence_shape.py`：

```python
"""五道闸里**能机械化**的那部分（spec §4.6）。

只做字段存在性与形状检查 —— 它**判不了语义**。"证据够不够"最终要人看，
这里只拦住最容易假的那几类：只写"符合预期"、没有负控结论、UI 条没截图、
失败没有单号、UI 失败只贴本地路径没嵌图、blocked 没说怎么解除。

用法：
    python -m checks.evidence_shape results.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# "有一个具体值"的机械近似：出现数字、等号、引号包裹的值，或括号里的取值。
_CONCRETE = re.compile(r"\d|=\s*\S|\"[^\"]+\"|'[^']+'|`[^`]+`")
# 负控结论：写成"负控：…"即可，内容仍需人看
_NEGATIVE_CONTROL = re.compile(r"负控|negative control|would fail|必红")
_EMBEDDED_IMAGE = re.compile(r"!\[[^\]]*\]\(https?://[^)]+\)")
_VAGUE = ("符合预期", "一切正常", "无异常", "pass", "ok", "as expected")


def _is_concrete(actual: str) -> bool:
    text = (actual or "").strip()
    if not text:
        return False
    if text.lower() in _VAGUE:
        return False
    return bool(_CONCRETE.search(text))


def lint_results(records: list[dict]) -> tuple[str, ...]:
    violations: list[str] = []
    for r in records:
        tc = r.get("tc") or "<unnamed>"
        status = r.get("status") or ""
        actual = r.get("actual_result") or ""
        shots = r.get("screenshots") or []
        lane = r.get("lane") or "api"

        if status == "pending":
            violations.append(f"{tc}: still pending — the run did not finish")
            continue

        if status == "passed":
            if not _is_concrete(actual):
                violations.append(f"{tc}: passed but actual_result carries no concrete value")
            if not _NEGATIVE_CONTROL.search(actual):
                violations.append(f"{tc}: passed but states no negative control")
            if lane == "ui" and not shots:
                violations.append(f"{tc}: ui pass without a screenshot")

        if status == "failed":
            if not r.get("bug"):
                violations.append(f"{tc}: failed without a bug id")
            if lane == "ui":
                # 🔴 只认**嵌在 BUG 正文里**的图。原来把 screenshots 与 bug_body
                #    拼接后一起正则，于是"图贴在 screenshots 字段里、正文里一个字没有"
                #    也能过 —— 而这条检查的语义就是"必须嵌进单内"。
                #    （我原来的验收测试恰好就是用 screenshots 装图，等于在复现这个绕过。）
                body = str(r.get("bug_body") or "")
                if not _EMBEDDED_IMAGE.search(body):
                    violations.append(
                        f"{tc}: ui failure needs a screenshot embedded in the bug body, "
                        "not just a path or a screenshot entry"
                    )

        if status == "blocked":
            if not re.search(r"解除|unblock|需要|missing|blocked by", actual):
                violations.append(f"{tc}: blocked without saying what would unblock it")
    return tuple(violations)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evidence_shape")
    ap.add_argument("results", type=Path, help="JSONL，每行一条结果")
    args = ap.parse_args(argv)

    records = [
        json.loads(line)
        for line in args.results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    violations = lint_results(records)
    for v in violations:
        print(v, file=sys.stderr)
    if violations:
        return 1
    print(f"✅ evidence shape passed ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_evidence_shape.py -v`
Expected: 12 passed

- [ ] **Step 8: 确认 lint 脚本本身不夹带业务词**

Run: `make portability && bash scripts/portability_check.sh`
Expected: `✅ portability check passed (core checks)`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(lint): reject unsourced assertions and shape-check the mechanizable review gates"
```

---

## Task 9: 假红自查（三态的前置标注）

**Files:**
- Create: `core/replay/preflight.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: `core.compile.schema.Workflow`、`core.replay.result.{RunResult, FAIL_ENV, STALE_TARGET}`
- Produces:
  - `core.replay.preflight.PreflightVerdict`（frozen）：`status: str`（`""` = 可以下结论）、`reason: str`、`detail: str`；属性 `proceed: bool`
  - `core.replay.preflight.stamp_build(workflow, build: str) -> Workflow`（把构建标识写进 `source["build"]`）
  - `core.replay.preflight.preflight(workflow, health: dict | Exception) -> PreflightVerdict`
  - `core.replay.preflight.fetch_health(base_url: str, timeout: float = 5.0) -> dict | Exception`（打 `/healthz`；**任何异常都返回而不抛**）
  - `core.replay.preflight.run_with_retry(run_once, *, attempts: int = 2) -> tuple[RunResult, str]`（第二个返回值是标注：`""` 或 `"COLD_START_FLAKE"`）

**语义（必须与 spec §4.2 一致）**：`FAIL_ENV` 与 `STALE_TARGET` **不是第四态**，它们是「本次未得出结论」。
一条 workflow 只有在环境对齐、重跑稳定之后产生的结论才落进三态。`preflight()` 返回 `proceed=False` 时
调用方**不许**把任何结果报成产品结论。

- [ ] **Step 1: 写失败测试**

`tests/test_preflight.py`：

```python
from core.compile.schema import Workflow
from core.replay.preflight import (
    PreflightVerdict, preflight, run_with_retry, stamp_build,
)
from core.replay.result import FAIL_ANCHOR, PASS, STALE_TARGET, RunResult


def wf(build: str = "") -> Workflow:
    w = Workflow(id="w", title="t", target="demo", steps=())
    return stamp_build(w, build) if build else w


def test_a_healthy_target_on_the_expected_build_proceeds():
    verdict = preflight(wf("demo-build-1"), {"build": "demo-build-1", "ready": True})
    assert verdict.proceed
    # 🔴 必须同时断言 reason：`build_unknown` 的 proceed 也是 True，
    #    只断言 proceed 的话「验过且匹配」与「压根没验」分不开 ——
    #    而这是两句完全不同的声明（reviewer 指出，实测确实分不开）。
    assert verdict.reason == ""


def test_a_verified_match_and_an_unchecked_build_are_distinguishable():
    """两者都放行，但必须看得出区别：「没检查」和「检查过、没问题」。"""
    verified = preflight(wf("demo-build-1"), {"build": "demo-build-1", "ready": True})
    unchecked = preflight(wf(), {"build": "whatever", "ready": True})
    assert verified.proceed and unchecked.proceed
    assert unchecked.reason == "build_unknown"
    assert verified.reason != unchecked.reason


def test_a_different_build_is_stale_target_not_a_product_verdict():
    verdict = preflight(wf("demo-build-1"), {"build": "demo-build-2", "ready": True})
    assert not verdict.proceed
    assert verdict.status == STALE_TARGET
    assert verdict.reason == "build_drift"
    assert "demo-build-1" in verdict.detail and "demo-build-2" in verdict.detail


def test_an_unreachable_target_is_an_environment_problem():
    verdict = preflight(wf("demo-build-1"), ConnectionError("refused"))
    assert not verdict.proceed
    assert verdict.status == "FAIL_ENV"
    assert verdict.reason == "environment"


def test_a_target_that_is_up_but_not_ready_is_an_environment_problem():
    verdict = preflight(wf("demo-build-1"), {"build": "demo-build-1", "ready": False})
    assert not verdict.proceed
    assert verdict.status == "FAIL_ENV"
    assert verdict.reason == "not_ready"


def test_an_unknown_expected_build_skips_the_staleness_check_but_says_so():
    verdict = preflight(wf(), {"build": "whatever", "ready": True})
    assert verdict.proceed
    assert verdict.reason == "build_unknown"


def test_stamp_build_puts_the_id_into_provenance():
    assert stamp_build(wf(), "b7").source["build"] == "b7"


def test_retry_reports_a_cold_start_flake_when_the_second_run_passes():
    calls = {"n": 0}

    def run_once() -> RunResult:
        calls["n"] += 1
        return RunResult("w", PASS if calls["n"] == 2 else FAIL_ANCHOR, reason="missing")

    result, note = run_with_retry(run_once)
    assert result.ok
    assert note == "COLD_START_FLAKE"
    assert calls["n"] == 2


def test_retry_does_not_annotate_when_the_first_run_passes():
    result, note = run_with_retry(lambda: RunResult("w", PASS))
    assert result.ok and note == ""


def test_retry_reports_the_final_verdict_when_both_runs_fail():
    """两次都失败时返回**第二次**的结果（稳定那次才是有信息的）。

    🔴 两次必须返回**可区分**的对象。原来两次都返回同一个 RunResult，
    于是"返回第一次"这个错误实现也能过 —— 断言不可区分等于没断言。
    """
    seen: list[int] = []

    def run_once() -> RunResult:
        n = len(seen) + 1
        seen.append(n)
        return RunResult("w", FAIL_ANCHOR, reason=f"missing-attempt-{n}")

    result, note = run_with_retry(run_once)
    assert len(seen) == 2
    assert result.reason == "missing-attempt-2"      # 返回的是第二次那次
    assert note == ""


def test_verdict_proceed_is_the_only_thing_that_licenses_a_product_verdict():
    assert PreflightVerdict(status="").proceed is True
    assert PreflightVerdict(status=STALE_TARGET, reason="build_drift").proceed is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.replay.preflight'`

- [ ] **Step 3: 实现**

`core/replay/preflight.py`：

```python
"""回放前的假红自查（spec §4.2）。

三项自查里，这一层负责两项：
- 构建标识变没变（构建标识取自 workflow.source["build"]，由编译器或调用方盖章）
- 目标起没起、就绪没就绪

第三项「首轮失败次轮通过」由 run_with_retry 负责。

🔴 本模块产出的都**不是**三态结论：FAIL_ENV / STALE_TARGET 表示"现在还不能下判"。
调用方在 proceed=False 时不得把任何结果报成产品缺陷或脚本缺陷。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, replace

from .result import FAIL_ENV, STALE_TARGET, RunResult


@dataclass(frozen=True)
class PreflightVerdict:
    status: str = ""            # "" = 可以下结论
    reason: str = ""
    detail: str = ""

    @property
    def proceed(self) -> bool:
        return self.status == ""


def stamp_build(workflow, build: str):
    """把构建标识写进 workflow 的溯源信息，供下次回放判断是否换了构建。"""
    return replace(workflow, source={**workflow.source, "build": build})


def fetch_health(base_url: str, timeout: float = 5.0) -> dict | Exception:
    """打 /healthz。**任何失败都返回异常对象，不抛** —— 调用方要能把它当证据看。"""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/healthz", timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return exc


def preflight(workflow, health: dict | Exception) -> PreflightVerdict:
    if isinstance(health, BaseException):
        return PreflightVerdict(FAIL_ENV, "environment", f"target unreachable: {health}")
    if not health.get("ready"):
        return PreflightVerdict(FAIL_ENV, "not_ready", "target is up but not ready")

    expected = workflow.source.get("build")
    if not expected:
        return PreflightVerdict("", "build_unknown", "workflow records no build id; staleness unchecked")
    actual = health.get("build")
    if actual != expected:
        return PreflightVerdict(
            STALE_TARGET, "build_drift",
            f"workflow was compiled against {expected!r} but the target serves {actual!r}",
        )
    return PreflightVerdict()


def run_with_retry(run_once, *, attempts: int = 2) -> tuple[RunResult, str]:
    """跑一次；失败且还有余量就再跑一次。

    第二次通过 = 首轮是冷加载造成的假红，标注 COLD_START_FLAKE（spec §4.2）。
    两次都失败 = 保留第二次的结果（它是稳定的那次）。
    """
    result = run_once()
    if result.ok or attempts <= 1:
        return result, ""
    second = run_once()
    if second.ok:
        return second, "COLD_START_FLAKE"
    return second, ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_preflight.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(replay): preflight self-checks — stale build, cold start, not-ready are not verdicts"
```

---

## Task 10: 端到端 demo + 三态可证 + README

**Files:**
- Create: `demo/__init__.py`, `demo/run.py`, `demo/finalize.py`
- Create: `demo/spec.md`（**靶场的需求文档，扮演 PRD 角色 —— 期望值的唯一合法来源**）
- Create: `demo/answers.json`（人工补全：只补 `value_ref`，不补期望值）
- Test: `tests/test_demo_three_states.py`
- Modify: `README.md`
- **Modify**: `target_app/serve.py`、`target_app/pages/login.html`、`target_app/pages/list.html`、`tests/test_target_app.py` —— 加 `/__demo__/shift-layout` 位移开关与它的测试。
- **Modify**: `core/primitives/session.py` + `tests/test_session_gate.py` —— 修 **daemon 名必须进程内稳定**这个核心缺陷（见 Task 5 区段的注记）。
  > ⚠️ **这段差量同样归 Task 10 携带**：`core/primitives/session.py` 是 Task 5 的、已合并，而缺陷只有在"一个进程里连开两个会话"时才暴露 —— 那正是 demo 的日常形态（探索一个、编译一个、每次回放再一个）。**必须在 `Session` 里修，不许做成 demo 侧的绕行**：绕行只能让 demo 看起来对，而任何连开两个会话的真实使用者仍然会踩到。
  > ⚠️ **这段差量归 Task 10 携带。** 它原本写在 Task 2 的区段里，但 Task 2 早已合并进 main，那段计划**没有落到代码上** —— 计划说一套、代码做一套，而没有任何活着的任务拥有这个差量。见 Task 2 区段顶部的注记。

**Interfaces:**
- Consumes: 前面全部
- Produces:
  - `demo.finalize.finalize(compiled_dir: Path, answers: dict) -> tuple[Workflow, Checks]`（把 `value_ref` 补进步骤；把 `source` 补进断言）
  - `demo.run.main(argv) -> int`（0 = 三态全部符合预期）
  - `make demo` 一个入口跑完全程

**demo 的流程（就是用户描述的真实用法）**：

```
1. 起靶场（固定 8712 端口）
2. 真录一遍：Session.start_recording → 驱动靶场走完登录+开弹窗 → stop_recording
3. 编译：新开一个 Session 当 locator，compile_recording → build/compiled/
4. 补全：finalize(compiled, answers.json) → build/final/{workflow,checks}.json
5. 回放三态：
   a. 原样          → 期望 PASS
   b. 改文案         → 期望 FAIL_PRODUCT / anchor_drift
   c. 摘掉 testid    → 期望 FAIL_ANCHOR / missing
   d. 位移布局 120px  → 期望 PASS（**这条独立于三态，证明回放走的是锚点而非坐标**）
6. 打印判定表；任一不符合预期则退出码 1
```

- [ ] **Step 1: 写靶场的需求文档（期望值的外部来源）**

`demo/spec.md`：

```markdown
# 靶场需求（demo spec）

> 这份文档扮演"需求文档"的角色。`demo/checks.json` 里每条断言的 `source`
> 必须指到这里 —— 这是"期望值来自外部、不来自编译期观测"的那条机制在 demo 上的落地。

## 1. 登录页 `/login`

- 有一个用户名输入框（`#username`）与一个密码输入框（`#password`）。
- 有一个按钮，标签**逐字**为 `登 录`（中间一个空格）。
- 点击该按钮后跳转到 `/list`。

## 2. 列表页 `/list`

- 有一个列表容器 `data-testid="item-list"`，异步加载完成后含 3 条记录。
- 三条记录的文本依次为 `Alpha`、`Beta`、`Gamma`。
- 有一个按钮，标签为 `新建`；点击后弹出对话框 `data-testid="create-dialog"`。
- 对话框中有一个标签为 `确定` 的按钮（`data-testid="confirm-create"`）。
```

- [ ] **Step 2: 写失败测试**

`tests/test_demo_three_states.py`：

```python
"""端到端：真录一遍 → 编译 → 补全 → 回放三态。

这条测试需要一个真实浏览器（browser-harness），所以默认跳过；
`TTT_E2E=1` 时才跑。CI 上按需触发。
    TTT_E2E=1 uv run pytest tests/test_demo_three_states.py -v
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("TTT_E2E") != "1",
    reason="needs a real browser; set TTT_E2E=1",
)


def run_demo(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "demo.run", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )


def test_three_states_are_distinguishable_end_to_end():
    done = run_demo()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASS" in done.stdout
    assert "FAIL_PRODUCT" in done.stdout and "anchor_drift" in done.stdout
    assert "FAIL_ANCHOR" in done.stdout and "missing" in done.stdout


def test_the_compiled_workflow_never_carries_recorded_plaintext():
    done = run_demo("--only", "compile")
    assert done.returncode == 0, done.stdout + done.stderr
    compiled = (ROOT / "demo" / "build" / "final" / "workflow.json").read_text(encoding="utf-8")
    assert "secret" not in compiled


def test_lint_rejects_the_compiled_checks_until_expectations_are_authored():
    done = run_demo("--only", "compile")
    assert done.returncode == 0, done.stdout + done.stderr
    lint = subprocess.run(
        [sys.executable, "-m", "core.lint.checks_lint",
         str(ROOT / "demo" / "build" / "compiled" / "checks.json"),
         "--workflow", str(ROOT / "demo" / "build" / "compiled" / "workflow.json")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert lint.returncode == 1
    assert "REJECT:no_assertions" in lint.stderr
```

- [ ] **Step 3: 跑测试确认失败**

Run: `TTT_E2E=1 uv run pytest tests/test_demo_three_states.py -v`
Expected: FAIL — `No module named demo.run`

- [ ] **Step 4: 写补全步骤**

`demo/finalize.py`：

```python
"""把编译产物补成可回放的正式件。

补的只有两样，都不是期望值：
- 步骤的 value_ref（`env:<VAR>`）—— 录制里的明文一律丢弃，由这里按 selector 补回
- 断言的 source —— 指向 demo/spec.md，证明期望值来自外部
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from core.compile.schema import Anchor, Check, Checks, Step, Workflow

SPEC_REF = "spec:demo/spec.md"


def finalize(compiled_dir: Path, answers: dict) -> tuple[Workflow, Checks]:
    compiled_dir = Path(compiled_dir)
    workflow = Workflow.from_json(json.loads((compiled_dir / "workflow.json").read_text(encoding="utf-8")))

    value_refs: dict[str, str] = answers.get("value_refs", {})
    steps: list[Step] = []
    for step in workflow.steps:
        if step.action == "fill" and not step.value_ref:
            ref = value_refs.get(step.selector)
            if not ref:
                raise ValueError(f"answers.json 缺 {step.selector!r} 的 value_ref")
            step = replace(step, value_ref=ref)
        steps.append(step)
    workflow = replace(workflow, steps=tuple(steps))

    checks = Checks(
        workflow=workflow.id,
        checks=tuple(
            Check(
                id=c["id"], after_step=c["after_step"], kind=c["kind"],
                # 🔴 断言自带锚点，**不**从步骤上借。
                # count 类断言尤其不能借：步骤的锚点是"那个容器"（匹配 1 个元素），
                # 要数的是它里面有几行（匹配 N 个）—— 借错了 count 永远是 1。
                anchor=Anchor.from_json(c["anchor"]),
                expect=c["expect"], source=c["source"],
            )
            for c in answers["checks"]
        ),
    )
    return workflow, checks


def write_final(workflow: Workflow, checks: Checks, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "workflow.json").write_text(
        json.dumps(workflow.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "checks.json").write_text(
        json.dumps(checks.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
```

`demo/answers.json`：

```json
{
  "value_refs": {
    "#username": "env:DEMO_USERNAME",
    "#password": "env:DEMO_PASSWORD"
  },
  "checks": [
    {"id": "c1", "after_step": 4, "kind": "count",
     "anchor": {"by": "testid", "value": "item-row"}, "expect": "3",
     "source": "spec:demo/spec.md#2-列表页"},
    {"id": "c2", "after_step": 4, "kind": "text_present",
     "anchor": {"by": "testid", "value": "item-list"}, "expect": "Beta",
     "source": "spec:demo/spec.md#2-列表页"}
  ]
}
```

> `after_step` 必须指向被断言的那个步骤号，**填之前先看 `build/compiled/checks.todo.md`** ——
> 编译器会列出建议的断言点与它们的步骤号。
>
> 两条断言故意挂在**不同**的锚点上，各有用意：
> `count` 挂在 `item-row`（每行一个 testid，匹配 3 个 → 数得出 3）；
> `text_present` 挂在 `item-list`（容器，取它的整体文本去 `in` 判 `Beta`）。
> **`count` 千万不能挂 `item-list`** —— 那是容器，只匹配 1 个元素，`expect="3"` 必红。
> 这就是断言「自带锚点」而不是「从步骤借锚点」的现实理由。

- [ ] **Step 5: 写 demo 主程序**

`demo/run.py`：

```python
"""端到端 demo：真录 → 编译 → 补全 → 回放三态。

这就是本框架的日常用法：先手动走一遍，把过程录下来，
再让编译器把它变成一条不依赖 LLM 的回归，最后验证三种结果分得开。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from core.compile.compiler import compile_recording
from core.compile.schema import Checks, Workflow
from core.lint.checks_lint import lint
from core.primitives.session import Session
from core.replay.engine import run
from core.replay.preflight import fetch_health, preflight, run_with_retry, stamp_build
from core.replay.result import FAIL_ANCHOR, FAIL_PRODUCT, PASS
from core.transcript.recording import load_recording
from demo.finalize import finalize, write_final
from target_app.serve import serve

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "demo" / "build"
PORT = 8712
BUILD_ID = "demo-build-1"
SHIFT_DY = 120        # 位移布局用的像素数：足以让录制坐标彻底失效


def _explore(base_url: str) -> Path:
    """真的走一遍并把过程录下来。"""
    with Session(base_url) as s:
        rec = s.start_recording("demo-smoke", "登录并打开新建弹窗")
        s.goto("/login")
        s.fill("#username", os.environ["DEMO_USERNAME"])
        s.fill("#password", os.environ["DEMO_PASSWORD"])
        s.click_text("登 录")            # Session 已有：按可见文本点击，内部走坐标
        s.wait_for('[data-loaded="true"]')   # 🔴 等哨兵，不是等容器：容器一开始就在
        s.click_text("新建")
        s.click_text("确定")
        s.stop_recording()
    return rec


def _compile(rec_dir: Path, base_url: str):
    with Session(base_url) as locator:
        result = compile_recording(load_recording(rec_dir), target="demo", locator=locator)
    result.write(BUILD_DIR / "compiled")
    return result


def _expect(label: str, result, want_status: str, want_reason: str) -> bool:
    ok = result.status == want_status and (not want_reason or result.reason == want_reason)
    mark = "✅" if ok else "🔴"
    print(f"{mark} {label:<28} {result.status:<14} reason={result.reason or '-'}")
    return ok


def _replay(workflow: Workflow, checks: Checks, base_url: str, *, allow_hosts=()):
    def once():
        with Session(base_url, allow_hosts=allow_hosts) as locator:
            return run(workflow, locator, checks)
    return once


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["compile", "replay"], default=None,
                    help="compile = 只跑到编译+补全；replay = 从零重跑全流程（**它会重新探索与编译**，不是"只回放"）")
    args = ap.parse_args(argv)

    os.environ.setdefault("DEMO_USERNAME", "demo")
    os.environ.setdefault("DEMO_PASSWORD", "secret")

    with serve(port=PORT) as srv:
        base_url = srv.base_url

        rec_dir = _explore(base_url)
        print(f"recorded → {rec_dir}")

        compiled = _compile(rec_dir, base_url)
        print(f"compiled → {BUILD_DIR / 'compiled'}  "
              f"({len(compiled.workflow.steps)} steps, {len(compiled.unresolved)} unresolved)")
        for item in compiled.unresolved:
            print(f"  unresolved: seq {item.seq} {item.helper} — {item.reason}")

        workflow, checks = finalize(BUILD_DIR / "compiled", json.loads((ROOT / "demo" / "answers.json").read_text(encoding="utf-8")))
        workflow = stamp_build(workflow, BUILD_ID)
        write_final(workflow, checks, BUILD_DIR / "final")

        # 补全之后必须先过 lint：没断言的产物不许用
        violations = [v for v in lint(checks, workflow) if v.startswith("REJECT")]
        if violations:
            for v in violations:
                print(f"🔴 lint: {v}", file=sys.stderr)
            return 1

        if args.only == "compile":
            print("✅ compile-only run finished")
            return 0

        verdict = preflight(workflow, fetch_health(base_url))
        print(f"preflight: {verdict.status or 'ok'} ({verdict.reason or '-'})")
        if not verdict.proceed:
            return 1

        import urllib.request  # noqa: PLC0415
        results = []

        # a) 原样
        result, note = run_with_retry(_replay(workflow, checks, base_url))
        results.append(_expect("baseline", result, PASS, ""))
        if note:
            print(f"   note: {note}")

        def _switch(path: str, payload: dict) -> None:
            req = urllib.request.Request(
                base_url + path, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()

        # b) 改文案 → 角色/文案锚点失效但能近似匹配 → FAIL_PRODUCT
        _switch("/__demo__/copy-mode", {"mode": "drifted"})
        result, _ = run_with_retry(_replay(workflow, checks, base_url), attempts=1)
        results.append(_expect("copy drifted", result, FAIL_PRODUCT, "anchor_drift"))
        _switch("/__demo__/copy-mode", {"mode": "spec"})

        # c) 摘掉稳定钩子 → testid 锚点失效且无可近似匹配 → FAIL_ANCHOR
        _switch("/__demo__/strip-testids", {"strip": True})
        result, _ = run_with_retry(_replay(workflow, checks, base_url), attempts=1)
        results.append(_expect("testids stripped", result, FAIL_ANCHOR, "missing"))
        _switch("/__demo__/strip-testids", {"strip": False})

        # 产物里不许残留坐标（回放按锚点走，坐标只有编译期探针用）。
        # 🔴 `bool(click_steps)` 是非空守卫：没有 click 步时这条会空过。
        click_steps = [st for st in workflow.steps if st.action == "click"]
        no_coords = bool(click_steps) and all(st.xy is None for st in click_steps)
        print(f"{'✅' if no_coords else '🔴'} {'artifact carries no coordinates':<28} "
              f"{len(click_steps)} click step(s), xy={[st.xy for st in click_steps]}")
        results.append(no_coords)

        # 🔴 d) 位移布局 → 录制坐标全部失效，锚点仍找得到 → 期望 PASS。
        #    这条是**独立于三态**的验收：它证明回放走的是锚点而不是坐标。
        #    三态单独不够 —— `resolve()` 在点击之前就跑完了，所以"坐标优先"那种
        #    回归能在三态全绿的情况下活下来（T7 那条 Critical 正是如此：
        #    验收会过，而它本该证明的东西是假的）。
        first_click = next(e for e in load_recording(rec_dir).events if e.helper == "click_at_xy")
        cx, cy = first_click.xy()

        def _at(x: int, y: int) -> str:
            with Session(base_url) as probe:
                probe.goto("/login")
                return str(probe.js(
                    f"(()=>{{const e=document.elementFromPoint({x},{y});"
                    "return e ? e.tagName+'|'+(e.textContent||'').trim().slice(0,20) : null})()"
                ))

        _switch("/__demo__/shift-layout", {"dy": SHIFT_DY})
        with_shift = _at(cx, cy)
        _switch("/__demo__/shift-layout", {"dy": 0})
        without_shift = _at(cx, cy)
        # 极性自检：同一个坐标在位移前后必须指到**不同**的东西。
        # 否则这条场景什么也没证明（比如位移太小、元素还落在老坐标上）。
        stale = with_shift != without_shift
        print(f"{'✅' if stale else '🔴'} {'recorded coords are stale now':<28} "
              f"with={with_shift!r} without={without_shift!r}")
        results.append(stale)

        _switch("/__demo__/shift-layout", {"dy": SHIFT_DY})
        result, _ = run_with_retry(_replay(workflow, checks, base_url), attempts=1)
        results.append(_expect("layout shifted (%dpx)" % SHIFT_DY, result, PASS, ""))
        _switch("/__demo__/shift-layout", {"dy": 0})

        print()
        if all(results):
            print("🎉 三态可证：改文案 → FAIL_PRODUCT，摘锚点 → FAIL_ANCHOR，原样 → PASS")
            print("🎉 回放走锚点：产物不带坐标，且位移 120px 后仍 PASS（坐标已失效）")
            return 0
        print("🔴 demo 结果与预期不符", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

> `Session.click_text()` 已在 Task 6 定义 —— 它内部走 `click_xy`，所以录制里留下的是坐标，
> 编译期探针才有东西可反解。探索脚本里放心用它：语义定位是编译期的事。

- [ ] **Step 6: 跑 demo 直到三态全绿**

```bash
uv sync --extra browser --extra dev
make demo
```

Expected:
```
✅ baseline                     PASS           reason=-
✅ copy drifted                 FAIL_PRODUCT   reason=anchor_drift
✅ testids stripped             FAIL_ANCHOR    reason=missing
✅ artifact carries no coordinates 3 click step(s), xy=[None, None, None]
✅ recorded coords are stale now   with='INPUT|' without='BUTTON|登 录'
✅ layout shifted (120px)       PASS           reason=-

🎉 三态可证：改文案 → FAIL_PRODUCT，摘锚点 → FAIL_ANCHOR，原样 → PASS
🎉 回放走锚点：产物不带坐标，且位移 120px 后仍 PASS（坐标已失效）
```

- [ ] **Step 7: 连续跑五次确认不 flaky**

Run: `for i in 1 2 3 4 5; do make demo >/dev/null || echo "run $i FAILED"; done; echo done`
Expected: 只打印 `done`（五次全绿，无 flaky）

- [ ] **Step 8: 确认没有泄漏浏览器**

Run: `pgrep -fl "user-data-dir=.*ttt-profile" || echo "no leaked browser ✅"`
Expected: `no leaked browser ✅`

- [ ] **Step 9: 写 README**

`README.md` 必须包含以下六节（内容按本计划与 spec 写实，**不得出现任何业务词**）：

1. **这是什么** —— 一句话：把一次浏览器录制编译成不依赖 LLM 的确定性回归。
2. **六层映射与业务边界** —— `core/ checks/ skills/` 是机制层（零业务词），`adapters/` 是项目层；`scripts/portability_check.sh` 怎么用。
3. 🔴 **两个必须知道的陷阱**：
   - **录制只发生在 `run.py` 的 tracing 里**：从 Python 直接 import helpers 驱动不会产生 `events.jsonl`，必须自己调 `recorder.observe`。
   - **编译 = 一次带探针的回放**：`events.jsonl` 里没有目标元素，锚点靠 `elementFromPoint`/`activeElement` 现问。所以编译期目标必须可达。
4. **三态怎么读** —— `PASS` / `FAIL_PRODUCT`（含 `anchor_drift`）/ `FAIL_ANCHOR`；以及 `FAIL_ENV`、`STALE_TARGET` **不是结论**。
5. **新项目落地 checklist** —— 换 `scripts/business_words.txt`；写 `adapters/` 的 target/oracle 实现；把 exploration 流程写进 `adapters/instance/`；先跑一条竖切再谈接口。
6. **已知边界** —— 逐条写清，别只写在代码注释里：
   - `type_text` 不编译（改用 `fill_input`）；`xy` 兜底锚点会打 WARN；v1 只做 UI 轨。
   - **录制期点击竞态**：无头 Chrome 下约一成的合成点击不会触发 `dialog.showModal()`（`新建` 这类开弹窗的按钮尤其明显）。**推荐做法是对弹窗状态 `wait_for`**（例如等 `dialog[open]` 出现）而不是点完就假设它开了；demo 里那段重试只是把这个竞态吸收了，它**只覆盖探索期** —— 回放期同样的点击没有任何东西吸收，`attempts=1` 的那些场景会直接红。
   - **一个进程同一时刻只开一个 `Session`**：daemon 名是**进程内稳定**的（那是为了绕开 `NAME` 只在 import 时读一次的限制），所以两个 `Session` 重叠存活会互相把对方的 daemon 停掉。顺序使用（退出一个再进下一个）是安全的，也正是本框架的用法；要并发请用不同进程。

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(demo): end-to-end record -> compile -> replay with a provable three-state split"
```

---

## Task 11: 适配层接口 + 依赖方向守卫

**Files:**
- Create: `adapters/__init__.py`, `adapters/target.py`, `adapters/oracle.py`
- Create: `adapters/instance/__init__.py`, `adapters/instance/demo.py`
- Modify: `pyproject.toml`（`packages` 加 `adapters`）
- Test: `tests/test_layering.py`, `tests/test_adapters.py`

**Interfaces:**
- Consumes: 无（只在接口层用标准库类型）
- Produces:
  - `adapters.target.Target`（`typing.Protocol`）：`name: str`、`base_url: str`、`allow_hosts: tuple[str, ...]`、`credentials: Mapping[str, str]`、`build_id(self) -> str`
  - `adapters.oracle.Oracle`（`typing.Protocol`）：`source_tag: str`、`expectation(self, key: str) -> str`，且 `expectation` 的实现**不得**读编译期观测产物
  - `adapters.instance.demo.DemoTarget()`、`adapters.instance.demo.demo_oracle_from_spec(spec_path: Path) -> Oracle`

**为什么这个 Task 必须存在**：spec §4.1 断言「业务只准活在 `adapters/`」。
没有这个 Task，`adapters/` 只是一句承诺；有了它，**依赖方向可以被机器检查** ——
`core/` 一旦 import `adapters` 或 `target_app`，测试就红。分层才成立。

- [ ] **Step 1: 写失败测试 — 依赖方向**

`tests/test_layering.py`：

```python
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
            # 🔴 相对导入不能一律跳过 —— 这个坑的原始形态就是"注释写着
            #    「跳出本包才算越界」，代码却把所有 node.level 都 continue 掉了"，
            #    于是 `from ..adapters import target` 写在 core/ 下安然过关。
            #    用 resolve_name 真解析一次：爬过顶层包的会抛 ImportError，
            #    那正是我们要抓的越界；解析得到的绝对名再取顶层段比对。
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
    """回归：`_imported_modules` 曾经把所有 node.level 的导入一律跳过，
    于是 `from ..adapters import target` 写在 core/ 下能躲过守卫。
    用探针文件走真实代码路径，别只测 `_package_of` 这种边角。"""
    probe = ROOT / "core" / "_probe_escape.py"
    probe.write_text("from ..adapters import target\n", encoding="utf-8")
    try:
        assert ESCAPES_TOP_LEVEL in _imported_modules(probe)
    finally:
        probe.unlink()


ALLOWED_THIRD_PARTY = frozenset({"browser_harness"})


def test_the_mechanism_layer_imports_nothing_unexpected():
    """用**白名单**而不是黑名单。

    🔴 原设计是一份禁用包名清单（openai / anthropic / ...）—— 那是打地鼠：
    `import google.generativeai`、`from mistralai import Mistral` 都能溜过去，
    清单永远追不上新客户端。反过来写成"只准 import 这些根"，
    清单外一律违规：标准库 + 本项目包 + 显式许可的第三方。
    不需要维护，也抓得住没见过的客户端。
    """
    allowed = set(sys.stdlib_module_names) | {"core", "checks"}
    for path in _mechanism_files():
        extra = _imported_modules(path) - allowed - ALLOWED_THIRD_PARTY
        assert not extra, f"{path.relative_to(ROOT)} 引入了未许可的依赖 {sorted(extra)}"


def test_only_the_browser_layer_may_touch_the_browser_driver():
    """`browser_harness` 只准出现在 `core/primitives/` ——
    回放与编译必须与浏览器无关，否则"零 LLM 确定性回放"就无从谈起。"""
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
    """这两层是"零 LLM 回放"承诺的落点：连第三方 HTTP 客户端都不许有。"""
    allowed = set(sys.stdlib_module_names) | {"core"}
    seen = {"core.replay": 0, "core.compile": 0}
    for path in _mechanism_files():
        parts = path.relative_to(ROOT).parts[:2]
        if parts not in (("core", "replay"), ("core", "compile")):
            continue
        seen[".".join(parts)] += 1
        residual = _imported_modules(path) - allowed
        assert not residual, f"{path.relative_to(ROOT)} 在零 LLM 层引入了非标准库依赖 {sorted(residual)}"
    # 🔴 两个目录**各自**都要有文件被扫到。用一个合并计数器（"总数 > 0"）的话，
    #    只有其中一个目录存在时也会过 —— 另一个就成了没人守的空档，
    #    而它恰好可能是将来新增代码的那一个。
    for layer, count in seen.items():
        assert count > 0, f"{layer}/ 下一个文件都没扫到 —— 这一层的守卫会空过"
```

- [ ] **Step 2: 跑测试确认它现在就是绿的（然后才有资格当守卫）**

Run: `uv run pytest tests/test_layering.py -v`
Expected: 全部 PASS（`test_layering.py` 的用例数随 `core/` 下文件数变化，不必数个数）—— 此时 `core/` 与 `checks/` 还没依赖任何项目层。**这条测试的价值在于以后**：
Step 5 写完 adapters 后重跑，若红了说明接口没设计对（适配层该被注入，不该被 import）。

- [ ] **Step 3: 写失败测试 — 适配层**

`tests/test_adapters.py`：

```python
from pathlib import Path

import pytest

from adapters.instance.demo import DemoTarget, demo_oracle_from_spec


def test_demo_target_declares_loopback_only():
    target = DemoTarget()
    assert target.base_url.startswith("http://127.0.0.1")
    assert target.allow_hosts == ()


def test_demo_target_keeps_credentials_out_of_the_target_itself():
    # 凭据只以"环境变量名"的形式声明，值不落在代码里
    assert set(DemoTarget().credentials) == {"DEMO_USERNAME", "DEMO_PASSWORD"}


def test_demo_oracle_reads_expectations_from_the_spec_document(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("## items\n\n- 三条记录的文本依次为 `Alpha`、`Beta`、`Gamma`。\n", encoding="utf-8")
    oracle = demo_oracle_from_spec(spec)
    assert oracle.source_tag.startswith("spec:")
    assert "spec.md" in oracle.source_tag
    # 🔴 必须真的取一次期望值：只断言 source_tag 的话，一个"永远抛 KeyError"的
    #    实现也能让全部测试变绿 —— 那这条测试等于没测。
    body = oracle.expectation("items#2-列表页")
    assert "Alpha" in body and "Gamma" in body


def test_demo_oracle_refuses_a_key_it_cannot_source(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("## items\n\n- 无\n", encoding="utf-8")
    oracle = demo_oracle_from_spec(spec)
    with pytest.raises(KeyError, match="not in the spec document"):
        oracle.expectation("something/not/documented")


def test_the_demo_target_build_id_comes_from_healthz():
    target = DemoTarget()
    # build_id() 会真打 /healthz，这里只验协议形状、不发网络请求
    assert callable(target.build_id)
```

- [ ] **Step 4: 实现适配层**

`adapters/__init__.py`（空）。

`adapters/target.py`：

```python
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
```

`adapters/oracle.py`：

```python
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
```

`adapters/instance/demo.py`：

```python
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
```

- [ ] **Step 5: 跑全部测试 + 依赖守卫 + 可移植性**

Run: `uv run pytest tests/ -v && make portability`
Expected: 全绿；`✅ portability check passed (core checks)`

若 `tests/test_layering.py` 变红 —— 说明你把适配层 import 进了机制层。
**正确的修法是把 `Target`/`Oracle` 当参数注入 `core/`，不是把 import 加进白名单。**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(adapters): injected target/oracle interfaces + machine-checked layering guard"
```

---

## 验收对照（spec §5 的 V1–V8 落在哪）

| 验收项 | 由哪个 Task 交付 | 怎么验 |
|---|---|---|
| **V1** 编译可用、`unresolved` 为空或已补全 | Task 7 + 10 | `make demo` 打印 `0 unresolved`；未解项逐条列在 `checks.todo.md` |
| **V2** 三态可证（最硬） | Task 10 Step 6 | demo 判定表里 a/b/c 三行全绿 |
| **V2b** 回放走锚点而非坐标（独立于 V2） | Task 10 Step 6 | ④ 产物 click 步 `xy is None`（带非空守卫）；⑤ 位移 120px 后回放仍 PASS；⑥ 极性自检：同一录制坐标在位移前后指到不同元素。**V2 单独推不出 V2b** —— `resolve()` 在点击之前跑完，所以坐标优先回放能让 V2 全绿而核心属性为假（T7 的 Critical 正是如此） |
| **V3** 连续回放 ×5 全绿 | Task 10 Step 7 | 五次 `make demo` 无 FAILED |
| **V4** lint 拒两个反模式 | Task 8 Step 1 | `tests/test_checks_lint.py::test_a_workflow_with_no_assertions_is_rejected` 与 `::test_a_check_whose_source_is_the_compile_time_observation_is_rejected` |
| **V5** 可移植性零命中 | Task 1 + 8 | `make portability` |
| **V6** 新机器一条命令跑绿 | Task 10 | 干净 clone 后 `uv sync --extra browser --extra dev && make demo` |
| **V7** 提示词两段式可走查 | ❌ **不在本计划**（提示词组是第二个 plan） | — |
| **V8** 可机械化的闸已下沉 | Task 8 + 最终修复波 | `checks/evidence_shape.py`（闸②④）与 `checks/coverage_diff.py`（闸①）**两个都要**有自测；`provenance` 那部分并进了 `core/lint/checks_lint.py`，在表里显式记下这个合并，**不许靠事后收窄判据来让它成立** |
| **（附加）分层可机检** | Task 11 | `tests/test_layering.py` 断言 `core/ checks/` 不 import `adapters/ target_app/ demo/`，且无 LLM 客户端 |

**本计划不覆盖**：`skills/` 提示词层（V7）、接口生成轨、流程编排轨、契约轨。
按 spec §7，下一份计划是「提示词组」，它不依赖本计划的代码，可与本计划并行。

---

## 最终修复波（整支评审后的一次性收口）

> 来源：整支评审（spec + plan + 全仓）的 Important 项与一处**规格未覆盖**。按流程只开**一轮**，
> 一轮修完 + 一次限定范围复审即收口。

### 修 1 · `__tttAllLabels` 必须走共享的取名链（Important）

`core/primitives/session.py` 的 `__tttAllLabels` 自己手搓了**第三条**取名链
（`aria-label || textContent || placeholder`），而项目专门引入 `ROLE_NAME_JS` 就是为了让这条链**只有一份**。

后果：名字来自 `title` / `alt` / `aria-labelledby` 的锚点**没有 drift 候选**，于是真实文案漂移
被误判成 `FAIL_ANCHOR/missing` 而不是 `FAIL_PRODUCT/anchor_drift` —— 恰好是三态设计要防的那种误归因。
demo 看不见它，因为它的按钮名字来自 `textContent`。

**修法**：`__tttAllLabels` 改为读 `__tttNameOf(el)`。**判据**：构造一个靠 `title` 取名的控件，
改它的 title 后回放，必须得到 `FAIL_PRODUCT/anchor_drift`（而不是 `FAIL_ANCHOR/missing`）。

### 修 2 · 形状守卫要断言「展开成数组」，不是断言子串（Important）

`test_locate_js_returns_the_constructor_each_branch_needs` 只断言 `"querySelectorAll" in locate_js(...)`。
去掉 `[...]` 展开后，`document.querySelectorAll(...)` 仍含这个子串，但返回 NodeList ⇒
`Array.isArray` 为假 ⇒ count 分支**少数**多匹配锚点、snapshot 分支直接坏。

**修法**：断言 `locate_js(...)` 的产物以 `[...` 开头（或直接断言 `Array.isArray` 会在真页面上成立的行为）。
这条守卫不该是全链最弱的一环。

### 修 3 · 补 `checks/coverage_diff.py`（闸①）—— **规格里点名、此前无人实现**

spec §4.4/§4.6 点名三个 `checks/` 脚本：`provenance.py`（并进 `checks_lint`，已记）、
`evidence_shape.py`（已建）、**`coverage_diff.py`（闸①，缺失）**。
计划此前的验收段把 V8 悄悄收窄成只看 `evidence_shape` —— 这是**事后收窄判据**，
正是本计划一直在防的那个模式，所以补实现而不是补一句 deferral。

```python
"""闸①：清单 ↔ 结果 双向差集 + 六项计数自洽。

用**执行前落盘的清单**当基线，与回读的 results 做双向差集：
  - 清单有、结果没写回 → 漏跑
  - 结果有、清单没有   → 快照与结果错位（基线是不是变过？），停下核对，别继续写
  - pending 必须为 0；不为 0 时**逐条点名**
  - 六项之和必须等于 total

🔴 它只做**计数与集合**，判不了语义 —— 这正是它能机械化的原因。
   "证据够不够"在 evidence_shape；最重的那部分只能靠人。

输入：
  --cases   清单 JSONL，每行 {"tc": str, ...}
  --results 结果 JSONL，每行 {"tc": str, "status": "passed"|"failed"|"blocked"|"skipped"|"pending", ...}
输出：违规进 stderr；退出码 0 = 通过 / 1 = 有违规。
"""
```

**必测**（每条都要能单独红）：漏跑一条、结果里多一条、有 pending、六项和不等于 total、全好。
**非空守卫**：两个输入都为空时必须报错而不是通过（否则"什么都没跑"会判绿）。

### 修 4 · 两条一行修复（同类，顺手）

- `Session.click_text` 用 `repr()` 拼 JS → 改用 `json.dumps`。与已修的锚点转义是同一类；
  探索路径上用户会直接用。
- `resolve()` 里的 drift 阈值硬编码 `0.7` → 改为 `from ..compile.anchors import DRIFT_THRESHOLD`。
  常量将来被调而解析器不跟，是静默分叉。

### 修 5 · README 两处（Important 3 的决定 + 一条边界）

- **在 README 开头显式写明**：`make demo` 是验收入口；`make test` **不覆盖**端到端主张
  （那四个 e2e 默认跳过）。这是本轮"决定"，不是代码修复 —— 现状是"分项披露"，
  要改成"一眼可见"。（不加 CI job：本计划内没有 CI，spec §6 的跳过理由就是 CI 分钟数。）
- 已知边界补一条：`scroll` 事件**不编译**（按设计丢弃且不报 Unresolved），
  所以"滚动后才点到的元素"会编译出一个目标在视口外的点击。

### 不修（如实记录为 acceptable-as-recorded）

`evidence_shape` 的启发式偏松（模块自身已声明不做语义判断）、`_daemon_name` 在两处重复赋值、
`_drift_probe_js` 忽略入参、T2/T3 的若干固定默认值、诊断语言中英不一致。

### 收口

一轮修完 → **一次限定范围复审**（只看这一轮的 diff）→ 处置残余（park 并附裁定或升级）。

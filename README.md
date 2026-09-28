# Trace to Test

把一次真实浏览器录制编译成不依赖 LLM 的确定性回归。

## 验收入口：`make demo`，不是 `make test`

🔴 **`make demo` 是本框架的验收入口** —— 它真录一遍、编译、补全、回放三态，端到端走完整条链。

🔴 **`make test` 不覆盖端到端主张。** `uv run pytest tests/` 跑的是机制层单测，其中四个端到端测试
（`tests/test_demo_three_states.py`，需要真实浏览器）**默认跳过**，只有设置 `TTT_E2E=1` 才跑。
所以看到满屏 `passed` 时，那 4 个 `skipped` 正是本框架的差异化（录制→编译→确定性回放）
没有被执行的证据。要证明框架真能跑通，跑 `make demo`。

```bash
uv sync --extra browser --extra dev
make demo
```

## 六层映射与业务边界

`core/`、`checks/` 与 `skills/` 是机制层，必须保持业务无关；项目的目标、操作方式与断言语义放在 `adapters/`。`scripts/portability_check.sh` 检查机制层是否混入项目专属词汇：

```bash
bash scripts/portability_check.sh
```

它扫描核心层源码，并与 `scripts/business_words.txt` 的项目词汇清单比对。新项目应更新该清单，再让检查保持通过。

## 两个必须知道的陷阱

1. **录制只发生在 browser-harness 的 `run.py` tracing wrapper 里。** 从 Python 直接 import `helpers` 并驱动浏览器不会写出 `events.jsonl`。`Session` 因此显式调用 `recorder.observe`；参数必须按 helper 的原始形状传递，尤其坐标要作为位置参数，因为 `recorder._details()` 按位置索引读取。若把坐标改为关键字参数，录制中的坐标会是 `null`，编译器就没有坐标可供反解。
2. **编译是一次带探针的回放。** 录制事件没有记录实际点击目标：事件里的 `box` 是获焦元素，不是点击目标。编译器会在实时浏览器中按录制坐标调用 `elementFromPoint`，并对输入动作查询 `activeElement`，再据此反解锚点。因此，编译时必须能访问目标并重放该流程。
3. **密码录制是已知边界。** recorder 会把密码字段遮蔽为 `•`。如果录制时现场输入密码，探针回放会键入圆点，登录便无法继续，后续锚点会诚实地成为 `Unresolved`。这是正确行为，不是缺陷。要编译的流程应从已认证会话开始录制，或在 `demo/answers.json` 用 `value_ref`（`env:<VAR>`）在补全阶段把凭证接回，回放时从环境变量取真实值。

## 三态怎么读

- `PASS`：步骤与外部来源编写的断言均通过。
- `FAIL_PRODUCT`：步骤能定位，但产品行为或内容不符合预期；`anchor_drift` 表示原文案锚点失效、页面出现了近似候选。
- `FAIL_ANCHOR`：定位本身不可靠，例如锚点缺失（`missing`）或歧义。

一个回放在第一个失败点即停（后面的步骤结果不可信）。所以如果一条断言放在流程末尾之前，早先的断言失败会挡住本应在更靠后的锚点失效 —— 要证「锚点缺失 → FAIL_ANCHOR」，断言必须挂在最后一个动作（`after_step` = 工作流步数）之后，否则摘掉 testid 时先撞上的是断言自己的 testid，判定会被归成 FAIL_PRODUCT 而不是 FAIL_ANCHOR。

`FAIL_ENV` 与 `STALE_TARGET` 都不是产品或脚本结论：前者表示当前环境无法可靠执行，后者表示目标构建已变化、结果可能过时。先恢复可判定条件，再重跑。

## 新项目落地 checklist

- [ ] 将项目专属词汇加入 `scripts/business_words.txt`，确认机制层仍通过 portability check。
- [ ] 在 `adapters/` 实现该项目的 target 与 oracle。
- [ ] 把真实 exploration 流程放入 `adapters/instance/`。
- [ ] 先跑通一条端到端竖切，再扩展成接口或通用配置。

## 已知边界

- `type_text` 暂不编译；探索流程优先使用 `fill_input`。
- **`scroll` 事件按设计丢弃**：既不产生步骤，也不记 `Unresolved`。所以"滚动之后才点到的元素"会编译出一个点击，其目标可能仍在视口外 —— 回放时可能点空。要稳定的做法是在探索脚本里先把元素滚进视口（或用 `wait_for` 让引擎自己找），而不是依赖录制里的滚动。
- `xy` 仅作为最后兜底锚点，使用时会产生 `WARN`。
- v1 只覆盖 UI 轨。
- **录制期点击竞态**：无头 Chrome 下约一成的合成点击不会触发 `dialog.showModal()`（`新建` 这类开弹窗的按钮尤其明显）。推荐做法是对弹窗状态 `wait_for`（例如等 `dialog[open]` 出现）而不是点完就假设它开了；demo 里那段重试只是把这个竞态吸收了，它只覆盖探索期 —— 回放期同样的点击没有任何东西吸收，`attempts=1` 的那些场景会直接红。
- **一个进程同一时刻只开一个 `Session`**：daemon 名是进程内稳定的（那是为了绕开 `NAME` 只在 import 时读一次的限制），所以两个 `Session` 重叠存活会互相把对方的 daemon 停掉。顺序使用（退出一个再进下一个）是安全的，也正是本框架的用法；要并发请用不同进程。

## 运行

```bash
uv sync --extra browser --extra dev
make demo
uv run pytest tests/ -v
```

完整演示会真实录制、编译、补全并回放；需要安装 Chrome。端到端 pytest 默认跳过，设置 `TTT_E2E=1` 后运行：

```bash
TTT_E2E=1 uv run pytest tests/test_demo_three_states.py -v
```

# trace-to-test

把一次真实的浏览器操作**录制**下来，**编译**成一条声明式回归，再以**零 LLM** 的方式确定性回放。

---

## 背景：它解决什么

UI 回归历来只有两条路，各有各的坏处：

| 做法 | 坏处 |
|---|---|
| 写脚本（Selenium / Playwright） | 锚点靠人挑。写的时候页面长什么样就照着写，页面一改就整片红，而**红的是不是产品坏了**没人能一眼判断 |
| 让 LLM 每次现场驱动浏览器 | 不确定。同一个用例今天过明天不过，**不可 CI**，而且失败原因无法归因 |

`trace-to-test` 的答案是：**让 AI 只在「探索」和「编译」两个阶段介入，把结论固化成一段不依赖模型的确定性代码。**

具体地：

- **人（或 AI）手动走一遍流程**，浏览器把这遍操作录成一串动作（坐标、URL、截图、焦点元素）。
- **编译器把这串动作反解成语义锚点**（「那个标签是『新建』的按钮」），而不是坐标。
- **回放时不需要任何模型**：按锚点定位、跑断言、给出结论。同一条 workflow 在 CI 上可以跑一万次，结果一致。

关键收益是**失败可归因**：回放会告诉你这次红到底是**产品坏了**还是**测试写坏了**——这是它区别于上面两条路的地方。（见 [怎么读结果](#怎么读结果)）

## 它怎么工作

```
① 录制            ② 编译（唯一需要浏览器的后置步骤）        ③ 回放（零 LLM）
Session            compile_recording                        run
  │                  │                                        │
  ├ goto             ├ 按录制顺序重放一遍（探针模式）           ├ 按锚点定位
  ├ fill             │   • 每个坐标问 elementFromPoint        ├ 跑 checks.json 里的断言
  ├ click_at_xy ───▶ │   • 每个输入问 activeElement           ├ 三态判定
  └ press            │                                        └ 停在第一个失败点
                     ├ 用语义锚点替换坐标
  ↓                  ├ 反解不出的 → unresolved.jsonl
events.jsonl         └ 产出四个文件
```

**为什么编译必须回放一遍浏览器**：录制里**没有**「被点中的那个元素」。动作里带的 `box` 是**当前获焦元素**的框，不是点击目标——所以想知道「当时点的是谁」，只能拿着坐标去实时页面上重新问一次。**因此编译期目标必须可达。**

## 安装

需要 **Python ≥ 3.12**、[`uv`](https://docs.astral.sh/uv/)、以及本机装好的 **Chrome / Chromium**。

```bash
git clone https://github.com/ABK3528/trace-to-test.git
cd trace-to-test
uv sync --extra browser --extra dev
```

两个 extra：

| extra | 装什么 | 什么时候要 |
|---|---|---|
| `browser` | `browser-harness==0.1.8`（CDP 直控本机 Chrome） | 要**录制 / 编译 / 回放**时 |
| `dev` | `pytest` | 跑测试时 |

## 快速开始

仓库自带一个**极简靶场**（`target_app/`，零依赖的本地网页），用来自证整条链能跑通：

```bash
make demo
```

它会真录一遍、编译、补全、然后在四种情况下回放，最后打印一张判定表：

```
✅ baseline                     PASS           reason=-
✅ copy drifted                 FAIL_PRODUCT   reason=anchor_drift
✅ testids stripped             FAIL_ANCHOR    reason=missing
✅ artifact carries no coordinates 3 click step(s), xy=[None, None, None]
✅ recorded coords are stale now with='HTML|…' without='BUTTON|登 录'
✅ layout shifted (120px)       PASS           reason=-
```

前两行证明**三态分得开**（改文案 → 产品问题；摘掉稳定钩子 → 测试问题）。后三行证明**回放走的是锚点而不是坐标**：把靶场布局整体下移 120px，录制时的坐标全部失效，回放仍然 PASS——因为锚点在新位置照样找得到。

想看编译产物长什么样：

```bash
make demo          # 先生成
cat demo/build/final/workflow.json    # 路径（纯步骤，无坐标）
cat demo/build/compiled/checks.todo.md # 编译器建议你补断言的位置
```

## 在你自己的项目里用

框架分两层，边界是硬的：

- **机制层**（`core/`、`checks/`、`skills/`）**必须保持业务无关**——任何项目复用这一层。
- **适配层**（`adapters/`）放这个项目的具体东西：被测目标、凭据从哪来、期望值（oracle）从哪来。

落地 checklist：

- [ ] 把项目专属词汇加进 `scripts/business_words.txt`，确认机制层仍通过 `make portability`。
- [ ] 在 `adapters/` 实现本项目的 target 与 oracle 接口。
- [ ] 把真实的 exploration 流程放进 `adapters/instance/`。
- [ ] **先跑通一条端到端竖切**，再谈扩展——不要先定接口。

`make portability` 检查机制层有没有混进项目专属词汇（服务名、URL、租户概念…）。它扫 `core/ checks/ skills/` 并与 `scripts/business_words.txt` 比对；新项目换掉那张词表即可。

## 怎么读结果

回放只有一个结论，取三态之一：

| 结果 | 判据 | 含义 |
|---|---|---|
| `PASS` | 步骤定位成功，且外部来源写的断言全过 | 通过 |
| `FAIL_PRODUCT` | 锚点找得到，但断言值不对；或锚点失效但**存在近似匹配**（`anchor_drift`）| **产品**漂移或缺陷 |
| `FAIL_ANCHOR` | 锚点找不到且无可近似匹配（`missing`），或匹配到多个（`ambiguous`）| **测试**写坏了 |

`anchor_drift` 这条值得单独说：`role`/`text` 类锚点是**对文案敏感**的。文案一变它们就失效——如果直接判 `FAIL_ANCHOR`，真实的文案改动会被误报成「测试写坏了」。所以这类锚点失效时会做一次归一化近似匹配：元素还在、只是标签变了 → 归 `FAIL_PRODUCT`；连近似匹配都没有 → 才归 `FAIL_ANCHOR`。**`testid` 锚点不做近似匹配**（它没有可比较的文本）。

### `FAIL_ENV` 和 `STALE_TARGET` **不是结论**

它们表示**现在还不能下判**：

- `FAIL_ENV`：环境无法可靠执行（目标不可达、没就绪）。
- `STALE_TARGET`：目标构建已经变了，这条 workflow 的记录可能过时。

先恢复可判定条件，再重跑。**不要把这两个当成产品或脚本的问题去改代码。**

### 一个容易踩的次序问题

回放在**第一个失败点即停**（后面的步骤结果不可信）。所以断言挂在哪一步很重要：

> 要证明「锚点缺失 → `FAIL_ANCHOR`」，断言必须挂在**最后一个动作之后**（`after_step` = workflow 的步数）。否则把 testid 摘掉时，先撞上的会是**断言自己**的 testid，判定被归成 `FAIL_PRODUCT`，两种状态就分不开了。

## 三个必须知道的陷阱

**1. 录制只在 browser-harness 的 tracing 包装里产生。**
从 Python 直接 `import helpers` 并驱动浏览器**不会**写出 `events.jsonl`。所以 `Session` 自己调用 `recorder.observe`，且参数必须按原始形状传——尤其**坐标要作为位置参数**，因为 `recorder._details()` 是按位置下标取值的。改成关键字参数，录制里的坐标会变成 `null`，编译器就无坐标可反解。

**2. 编译是一次带探针的回放（见上）。** 因此**编译期目标必须可达**，且**视口要与录制时一致**——探针是按录制坐标去问元素的，视口变了它问到的就是另一个元素，而一切看起来都正常。

**3. 密码是已知边界。** 录制器会把密码框内容遮蔽成 `•`。如果录制时是**现场输密码**，探针回放会键入一串圆点，登录过不去，之后的锚点会**诚实地**落进 `Unresolved`——这是正确行为，不是缺陷。要编译的流程应当**从已登录会话开始录**，或者在补全阶段用 `value_ref`（`env:<VAR>`）把凭证接回，回放时从环境变量取真值。

## 命令与配置

```bash
make demo          # 验收：真录一遍 → 编译 → 补全 → 回放（需要 Chrome）
make test          # 机制层单测（不覆盖端到端，见下）
make portability   # 机制层业务词零命中
make lint          # 可移植性 + 断言 lint 模块可用（真跑断言检查见下）
```

| 环境变量 | 作用 |
|---|---|
| `DEMO_USERNAME` / `DEMO_PASSWORD` | demo 探索期登录靶场用（有默认值） |
| `TTT_E2E=1` | 打开被默认跳过的端到端测试 |
| `TTT_CHROME` | 显式指定 Chrome 可执行文件（自动探测失败时） |

断言检查的真正入口（拒收「无断言」与「`source` 是编译期观测值 `observed:*`」两类反模式）：

```bash
uv run python -m core.lint.checks_lint demo/build/final/checks.json \
    --workflow demo/build/final/workflow.json
# 退出码 0 = 通过，1 = 有 REJECT（WARN 不改退出码）
```

## 测试策略（以及 `make test` 不覆盖什么）

🔴 **`make demo` 是验收入口，`make test` 不是。**

`uv run pytest tests/` 跑的是机制层单测；其中**端到端测试（5 条，都需要真实浏览器）默认跳过**，只有 `TTT_E2E=1` 才跑。所以当你看到满屏 `passed` 时，那 5 个 `skipped` **正是「本框架的差异化没有被执行」的证据**。

```bash
TTT_E2E=1 uv run pytest tests/test_demo_three_states.py -v
```

要证明框架真能端到端跑通，**跑 `make demo`**。

## 已知边界

- **`type_text` 暂不编译**；探索流程请优先使用 `fill_input`。
- **`scroll` 事件按设计丢弃**：既不产生步骤，也不记 `Unresolved`。所以「滚动之后才点到的元素」会编译出一个点击，其目标可能仍在视口外。要稳定的做法是在探索脚本里**先把元素滚进视口**，而不是依赖录制里的滚动。
- **`xy` 只是最后兜底锚点**，用到会打 `WARN`。
- **v1 只覆盖 UI 轨**（接口生成 / 流程编排 / 契约轨留了骨架，未实现）。
- **一个进程同一时刻只开一个 `Session`**：daemon 名是进程内稳定的（为绕开 `NAME` 只在 import 时读一次的限制），两个 `Session` 重叠存活会互相停掉对方的 daemon。顺序使用是安全的，也正是本框架的用法；要并发请用不同进程。
- **录制期点击竞态**：无头 Chrome 下合成点击偶尔不触发 `dialog.showModal()`（开弹窗的按钮尤其明显）。推荐对**弹窗状态** `wait_for`（如 `dialog[open]`）而不是点完就假设它开了。demo 里那段重试只是把它吸收了，**且只覆盖探索/录制期**——回放期同样的点击没有东西吸收。
  **失败率没有被良好刻画**：在一次 14 连跑的背靠背序列里实测**连续失败 10 次**（无头、本机带载），随后又连续成功。这不是「约一成」那种可控数字，**别拿它当稳定概率**。它只发生在探索/录制阶段，回放路径不受影响。

## 仓库结构

```
core/               机制层（业务无关，可被任意项目复用）
  transcript/         读 browser-harness 录制 → 归一化事件流
  compile/            坐标反解成语义锚点；产出 workflow / checks / unresolved
  replay/             确定性回放引擎 + 三态判定 + 回放前自查
  primitives/         浏览器会话（自起 Chrome、环境闸、退出回收）
  lint/               断言侧反模式检查
checks/             可机械化的复核闸（清单↔结果差集、证据形状）
adapters/           项目适配层（被测目标、oracle 来源）← 业务只准活在这里
target_app/         仓内极简靶场（自证用）
demo/               端到端演示：录制 → 编译 → 补全 → 四场景回放
scripts/            可移植性自检等
tests/              机制层单测 + 固定录制样本
docs/               设计文档与实施计划
```

编译器产出四个文件（在 `demo/build/` 下能看到实例）：

| 文件 | 内容 |
|---|---|
| `workflow.json` | 路径：纯步骤 + 语义锚点，**不含坐标** |
| `checks.json` | 断言 sidecar，**每条必须带 `source`**（期望值出处） |
| `unresolved.jsonl` | 反解不出的动作 + 我们确实找到的候选 + 为什么解不出 |
| `checks.todo.md` | 建议你补断言的位置（人从这里开始补） |

## 设计文档

- [`docs/trace-to-test-design.md`](docs/trace-to-test-design.md) —— 设计：两个语义鸿沟、三态定义、分层与业务边界、验收清单
- [`docs/trace-to-test-mechanism-plan.md`](docs/trace-to-test-mechanism-plan.md) —— 11 个任务的实施计划（含每步的 TDD 顺序与验收判据）

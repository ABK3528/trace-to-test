# 靶场需求（demo spec）

> 这份文档扮演“需求文档”的角色。`demo/checks.json` 里每条断言的 `source`
> 必须指到这里 —— 这是“期望值来自外部、不来自编译期观测”的那条机制在 demo 上的落地。

## 1. 登录页 `/login`

- 有一个用户名输入框（`#username`）与一个密码输入框（`#password`）。
- 有一个按钮，标签**逐字**为 `登 录`（中间一个空格）。
- 点击该按钮后跳转到 `/list`。

## 2. 列表页 `/list`

- 有一个列表容器 `data-testid="item-list"`，异步加载完成后含 3 条记录。
- 三条记录的文本依次为 `Alpha`、`Beta`、`Gamma`。
- 有一个按钮，标签为 `新建`；点击后弹出对话框 `data-testid="create-dialog"`。
- 对话框中有一个标签为 `确定` 的按钮（`data-testid="confirm-create"`）。

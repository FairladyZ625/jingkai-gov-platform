# 北京经开区共享智能体工作站

## 从 Issue 到 PR

1. 领取前核对 Issue 的依赖、允许路径和验收项。普通任务从最新 `origin/main` 建 `<类型>/<Issue号>-<英文短描述>` 分支，例如 `chore/3-pr-ci-agents`。HA 派工使用绑定的 worktree、分支和指定基线。
2. 只暂存本任务的文件。新增或修改逻辑要附自动化测试，在 CI 中运行。提交信息与 PR 描述用中文。
3. PR 目标为受保护的 `main`。正文首行写 `Closes #实际编号`，仅关联时写 `Refs #实际编号`。保留「摘要」「验证」「截图」三个二级标题。摘要逐条对照验收项，验证节贴实际命令和输出，列出仍未验证的部分。
4. PR 差异涉及 `prototype/v4/**`、`web/**`、`apps/*/web/**` 时，在截图节分别嵌入 1440px 和 1280px 宽的两张截图，Markdown 图片替代文字注明宽度。其他改动在该节写明原因。
5. 确认依赖已合并、CI 通过后交 CEO 评审，由 Ben 合并。禁止直推 main、强推或自行合并。

## 目录和本地命令

- `prototype/v4/` 是现场演示原型。直接打开 `prototype/v4/index.html`，用演示账号登录，从侧栏启动「一键演示」。保留 file:// 与离线 mock 模式。
- `data/public/` 放可公开的数据及核查说明，`docs/plan/` 放开发计划。`docs/agents/` 有写小应用和提交 PR 的操作说明。
- 运行 `python3 -m pytest -q --ignore=tests/demo` 测试仓库逻辑。PR 正文用例可单独运行 `python3 -m pytest -q tests/pr_body`。前端冒烟由 CI 单独运行。
- #2 提供 `scripts/guard.py` 后，提交前运行 `python3 scripts/guard.py`。此前检查暂存差异，防止私有内容进入公开 Git 历史。

## 公开边界

只使用公开数据和演示数据。禁止提交内部资料、data/private、私有源码、密钥、令牌、.env、商务测算、人员投入及采购成本明细。密钥只从环境变量读取。标签与里程碑脚本只由 Ben 授权后执行。

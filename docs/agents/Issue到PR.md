# 从 Issue 到 GitHub PR

用 gh issue view 核对目标、验收项、依赖与分支名。领取方式见 Issue；若已有 Assignee，先核对负责人。手动开发先 fetch origin，从 origin/main 建 Issue 指定分支；HA 派工沿用绑定 worktree。只 stage 拥有的文件，用 git diff --cached 逐项检查。

按 [AGENTS.md](../../AGENTS.md) 运行本地测试与防泄密检查（Linux/macOS 用 `python3`，Windows 用 `python`：`scripts/guard.py`、`python -m pytest -q --ignore=tests/demo`，改动 `core/`、`jkq/`、`apps/` 时安装 `requirements-dev.txt` 并运行 `scripts/check.py`），在 PR 中贴真实命令及输出。PR 正文格式须符合 [PR 模板](../../.github/PULL_REQUEST_TEMPLATE.md) 与 `scripts/check_pr_body.py`：首行单独一行填 `Closes #实际编号`（仅关联时写 `Refs #实际编号`），并保留 `## 摘要`、`## 验证`、`## 截图` 三个二级标题。摘要逐项说明验收结果；界面 PR（差异涉及 `prototype/v4/**`、`web/**`、`apps/*/web/**`）在截图节写两条独立图片链接的 Markdown 图片，替代文字分别注明 `1440`、`1280`；其余改动在截图节写明无需截图的原因。截图校验对照 PR 的完整差异，包括重命名和删除的路径。

经授权发布时，手动流程使用 gh pr create --base main --body-file 加正文文件路径。HA 流程先写 closeout，再按派工顺序 submit、push。通过 gh pr checks 查看实际交付的检查结果。依赖合并后更新基线、重跑验证，交 CEO 评审和 Ben 合并。

# 从 Issue 到 GitHub PR

用 gh issue view 核对目标、验收项、依赖与分支名。领取方式见 Issue；若已有 Assignee，先核对负责人。手动开发先 fetch origin，从 origin/main 建 Issue 指定分支；HA 派工沿用绑定 worktree。只 stage 拥有的文件，用 git diff --cached 逐项检查。

按 AGENTS.md 运行本地测试，在 PR 中贴命令及输出。第一行填 Closes #实际编号，或用 Refs 做关联。摘要逐项说明验收结果；界面 PR 在截图节写两条 Markdown 图片，分别注明 1440px、1280px。截图对照 PR 的完整差异，包括重命名和删除的路径。

经授权发布时，手动流程使用 gh pr create --base main --body-file 加正文文件路径。HA 流程先写 closeout，再按派工顺序 submit、push。通过 gh pr checks 查看实际交付的检查结果。依赖合并后更新基线、重跑验证，交 CEO 评审和 Ben 合并。

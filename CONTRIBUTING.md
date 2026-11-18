# 合作指南

经开政务平台是面向经开区政务场景的工作站：在 v4 原型之上落地对话、知识库和四个业务应用。欢迎协作，但请先按本指南领取任务，避免和已有 Issue、HA 派工或他人改动冲突。

仓库协议为 [AGPL-3.0](LICENSE)。提交即表示同意按该协议公开代码。

## 任务怎么排

仓库里已经拆好 **50 个 Issue**（[#2](https://github.com/FairladyZ625/jingkai-gov-platform/issues/2)–[#51](https://github.com/FairladyZ625/jingkai-gov-platform/issues/51)）和 **5 个里程碑**（M0 仓库与原型就位、M1 平台底座、M2 对话与知识库、M3 四个业务应用、M4 技能、电脑操作和联调演示）。Issue 号 = 任务号 + 1，例如 T01 对应 #2。

每个 Issue 都写了依赖。按依赖关系一共排成 **12 批**，同一批可以并行，依赖尚未合并的不要开工。完整列表和当前进度见：

- [在线计划页](https://jk.sumerchaser.top/v4/plan)（可用「可开工」筛选）
- [Issues 列表](https://github.com/FairladyZ625/jingkai-gov-platform/issues)

## 怎么领任务

1. 只领 **依赖都已合并** 的 Issue。不确定就先看计划页的「可开工」。
2. 先检查该 Issue 是否已有负责人（assignee），或评论里是否已有「我来」「已由 HA Codex worker 领取」。有则不要再领。
3. 有写权限：把自己设为负责人，并评论「我来，预计 X 完成」（把 X 换成你的预计时间）。
4. 没有写权限：在 Issue 下评论「我来，预计 X 完成」，维护者会帮你 assign。也可以先 fork，再按下面流程提 PR。

HA 每 20 分钟巡检一次。已经 assign 的 Issue 不会再派给 Codex。

## 领了之后怎么做

- **24 小时内要有动静**：推出分支，或开一个 Draft PR。超过 48 小时没有任何进展，任务可能被收回重派；收回前会在 Issue 里留言说明。
- 按 Issue 里写明的分支名开分支，不要另起名字。
- 尽早开 Draft PR，描述里写 `Closes #n`（n 为对应 Issue 号）。
- 做不了或中途没法继续：在 Issue 里评论放弃，并取消 assign，方便别人接手。

## 避免冲突

- 只改 Issue 写明的文件范围。需要超出范围时，先在 Issue 里说明，等确认再改。
- 经常把分支 rebase 到最新的 `origin/main`（`main` 为当前主干基线）。
- 同一文件同一时间只由一人修改。
- 改到公共文件（如 `shell.js`、接口规范、mock 数据）时，必须在 PR 描述里点名列出，方便审阅和协调。

## 怎么提 PR

- 按 [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) 和 [AGENTS.md](AGENTS.md) 填写 PR 正文：首行单独写 `Closes #n`（仅关联时写 `Refs #n`），保留 `## 摘要`、`## 验证`、`## 截图` 三个二级标题（由 `scripts/check_pr_body.py` 在 CI 中校验）。
- 在 `## 摘要` 把 Issue 里的验收标准逐条核对说明，在 `## 验证` 附上本地命令与真实输出。
- 改了界面（`prototype/v4/**`、`web/**`、`apps/*/web/**`）：在 `## 截图` 附 1440 和 1280 宽度的两张截图；未改界面则在该节说明无需截图的原因。
- 提交前按 [AGENTS.md](AGENTS.md) 运行 `guard.py` 和本地 `pytest`（改动 `core/`、`jkq/`、`apps/_template/` 等路径时还需跑 `scripts/check.py`），等 CI / guard 全绿后再请审核。
- CEO 助手按验收标准审代码，由 Ben 合并。`main` 受保护，不能直接推。
- 没有写权限时，从自己的 fork 向本仓库 `main` 分支提 PR，同样写 `Closes #n`。

## 红线（不要提交）

- `00_内部资料`
- 局方或客户的私有样例（放在 `data/private/`，该目录已加入 `.gitignore`）
- 任何 token、密钥、密码、部署凭据
- 内部商务核算类内容（关键词清单见 `scripts/guard_rules.json`，提交前由 guard 自动检查）

## 有问题

在对应 Issue 里说明情况，并 @summerchaserwwz。

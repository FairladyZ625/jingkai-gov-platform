# jingkai-gov-platform
经开政务平台 (Jingkai Government Affairs Platform)

## 目录

- `prototype/v4/`：v4 综合版前端原型（静态 HTML/JS，mock 数据，`JK_CONFIG.api.mode` 切换 mock/http）及《接口规范》v1.3
- `docs/plan/`：里程碑与任务清单（定稿）、`issues.json`（Issue 批量创建源）
- `data/public/`：公开来源抓取的真实数据（经开区政务公开政策、企业、公文样例、规则、会议纪要）及核对报告
- `docs/audit/`：原型流程问题截图

开发流程：Issue → `feat/<issue号>-<slug>` 分支 → PR（`Closes #<issue号>`）→ 审核后合并到 main。参与前请先阅读 [《合作指南》](CONTRIBUTING.md)。

本项目是北京经开区共享智能体工作站的公开演示与开发仓库，演示经办人员如何使用智能体处理政务工作。

## 本地运行

双击 `prototype/v4/index.html`，选择演示账号进入工作台，点击侧栏「一键演示」即可观看 12 段流程。默认 mock 模式可离线运行。

## 开发目录

| 目录 | 用途 |
| --- | --- |
| `core/`、`apps/` | 预留共享能力与业务应用 |
| `jkq/`、`deploy/` | 预留经开区配置与部署文件 |
| `web/` | 规划中的前端迁移目标，当前演示入口在 `prototype/v4/` |
| `scripts/`、`tests/guard/` | 仓库检查及其回归测试 |
| `.github/` | 规划中的 PR 模板与 CI 工作流 |

## 提交前检查

克隆后运行 `git config --local core.hooksPath .githooks` 启用提交钩子。暂存改动后运行下列命令，CI 可在检出代码后运行相同命令。

```sh
python3 -m unittest discover -s tests/guard -v
python3 scripts/guard.py
```

检查读取整个 Git 暂存快照，报告违规路径或文本行号。修正后重新暂存，再提交并创建面向 main 的 PR。

# jingkai-gov-platform
经开政务平台 (Jingkai Government Affairs Platform)

## 目录

- `prototype/v4/`：v4 综合版前端原型（静态 HTML/JS，mock 数据，`JK_CONFIG.api.mode` 切换 mock/http）及《接口规范》v1.3
- `docs/plan/`：里程碑与任务清单（定稿）、`issues.json`（Issue 批量创建源）
- `data/public/`：公开来源抓取的真实数据（经开区政务公开政策、企业、公文样例、规则、会议纪要）及核对报告
- `docs/audit/`：原型流程问题截图
- `docs/agents/`：开发与 Agent 协作指南（[Issue 到 PR](docs/agents/Issue到PR.md)、[写小应用](docs/agents/写小应用.md)）

开发流程：Issue → `<类型>/<issue号>-<slug>` 分支（如 `feat/`、`fix/`、`chore/`、`docs/`）→ PR（首行单独写 `Closes #<issue号>` 或 `Refs #<issue号>`）→ 审核后合并到 `main`。参与前请先阅读 [《合作指南》](CONTRIBUTING.md) 与 [AGENTS.md](AGENTS.md)。

本项目是北京经开区共享智能体工作站的公开演示与开发仓库，演示经办人员如何使用智能体处理政务工作。

## 本地运行

- **纯前端原型（离线 mock）**：双击 `prototype/v4/index.html`，选择演示账号进入工作台，点击侧栏「一键演示」即可观看 12 段流程。
- **经开区实例（FastAPI 后端 + 同源托管前端）**：安装 `requirements-dev.txt` 并配置 `HAIKNOW_SECRET`，运行 `make seed` 与 `make dev` 启动，详见 [jkq/README.md](jkq/README.md)；纯平台底座启动见 [core/README.md](core/README.md)。

## 开发目录

| 目录 | 用途 |
| --- | --- |
| `core/` | 平台底座服务端（`core/server/`）、Python/JS SDK（`core/sdk/`）及测试（`core/tests/`），见 [core/README.md](core/README.md) |
| `apps/` | 小应用目录，当前已提供模板 [apps/_template/README.md](apps/_template/README.md)，新应用由 `scripts/new_app.py` 生成 |
| `jkq/` | 经开区实例入口、路径/错误兼容层与平台业务模块，见 [jkq/README.md](jkq/README.md) |
| `config/`、`data/seed/` | 经开区项目配置（`config/projects.yaml`）与种子数据说明（[REAL_DATA.md](data/seed/REAL_DATA.md)） |
| `deploy/` | 演示环境 Docker Compose、Caddyfile、运维脚本 `deploy/demo`、定时重置与模拟政务站 `deploy/mock-gov/`，见 [部署文档](docs/deploy.md) |
| `web/` | 规划中的前端迁移目标，当前后端托管与演示入口仍在 `prototype/v4/` |
| `scripts/`、`tests/` | 仓库检查与脚手架（`guard.py`、`check_pr_body.py`、`check.py`、`new_app.py`），以及 `tests/guard/`、`tests/pr_body/`、`tests/jkq/`、`tests/demo/`、`tests/p0/` 等自动化测试 |
| `.github/` | [PR 模板](.github/PULL_REQUEST_TEMPLATE.md)、[Issue 模板](.github/ISSUE_TEMPLATE/task.md) 与 CI 工作流（[ci.yml](.github/workflows/ci.yml)、[core.yml](.github/workflows/core.yml)） |

## 提交前检查

克隆后运行 `git config --local core.hooksPath .githooks` 启用提交钩子（`.githooks/pre-commit` 默认调用 `python3`，Windows 若无可用 `python3` 可在提交前手动运行 `python scripts/guard.py`）。Linux/macOS 使用 `python3`，Windows 使用 `python`，暂存改动后运行下列命令：

```sh
python3 scripts/guard.py
python3 -m pytest -q --ignore=tests/demo
python3 -m pytest -q tests/pr_body
```

- `scripts/guard.py` 读取整个 Git 暂存快照，报告违规路径或文本行号（防泄密回归可在 Linux/macOS 运行 `python3 -m unittest discover -s tests/guard -v`）。
- `Makefile` 中的 `make test` 等价于 `python3 -m pytest -q --ignore=tests/demo`；当改动涉及 `core/`、`apps/_template/`、`jkq/`、`tests/jkq/`、`tests/fixtures/`、`conftest.py` 或 `requirements-dev.txt` 时，CI 会触发 [core.yml](.github/workflows/core.yml)，本地需安装 `requirements-dev.txt`（及 Node.js）后执行 `python3 scripts/check.py`。
- 修正检查问题后重新暂存，再提交并创建面向 `main` 的 PR。

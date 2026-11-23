# jingkai-gov-platform
经开政务平台 (Jingkai Government Affairs Platform)

## 目录

- `web/`：v4 综合版前端原型（静态 HTML/JS，mock 数据，`JK_CONFIG.api.mode` 切换 mock/http），应用契约与《接口规范》v1.3 位于 `docs/`
- `docs/plan/`：里程碑与任务清单（定稿）、`issues.json`（Issue 批量创建源）
- `data/public/`：公开来源抓取的真实数据（经开区政务公开政策、企业、公文样例、规则、会议纪要）及核对报告
- `docs/audit/`：原型流程问题截图
- `docs/agents/`：开发与 Agent 协作指南（[Issue 到 PR](docs/agents/Issue到PR.md)、[写小应用](docs/agents/写小应用.md)）

开发流程：Issue → `<类型>/<issue号>-<slug>` 分支（如 `feat/`、`fix/`、`chore/`、`docs/`）→ PR（首行单独写 `Closes #<issue号>` 或 `Refs #<issue号>`）→ 审核后合并到 `main`。参与前请先阅读 [《合作指南》](CONTRIBUTING.md) 与 [AGENTS.md](AGENTS.md)。

本项目是北京经开区共享智能体工作站的公开演示与开发仓库，演示经办人员如何使用智能体处理政务工作。

## 本地运行

- **纯前端原型（离线 mock）**：双击 `web/index.html`，选择演示账号进入工作台，点击侧栏「一键演示」即可观看 12 段流程。
- **经开区实例（FastAPI 后端 + 同源托管前端）**：安装 `requirements-dev.txt` 并配置 `HAIKNOW_SECRET`，运行 `make seed` 与 `make dev` 启动，详见 [jkq/README.md](jkq/README.md)；纯平台底座启动见 [core/README.md](core/README.md)。
- **部署到别人的 Linux 服务器**：见下方「部署到服务器」。补充的运维约定（快照中断恢复、公网验收等）见 [docs/deploy.md](docs/deploy.md)。

## 部署到服务器

下面说明如何在一台全新的 Linux 服务器上，用仓库自带的 Docker Compose 部署演示环境，并通过 Caddy 对外提供 HTTPS。命令与路径均以仓库 `deploy/` 目录为准，不要凭记忆改写。配置里的密钥只写变量名或占位符，不要把真实口令、令牌或 `deploy/.env` 内容提交到 Git 或写进文档。

### 服务器要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Linux。定时重置依赖 systemd；运维脚本还需要 Git、Python 3、GNU Make、`flock`、curl 7.71+（`deploy/demo` 使用 `--retry-all-errors`） |
| 容器 | Docker Engine，以及 Docker Compose V2。`deploy/demo` 需要支持 `docker compose config --no-env-resolution` |
| 端口 | 对外放行 TCP 80、443，供 Caddy 申请证书并提供 HTTPS。应用在容器内监听 `APP_PORT`（默认 8000），官方 compose **不会**把该端口映射到宿主机 |
| 内存与磁盘 | 仓库未写死最低配置。compose 为 app 设置了 `shm_size: 1gb`（镜像内含 Playwright 与 Chromium），建议内存不少于 4 GiB；磁盘需容纳镜像、Caddy 证书卷，以及至少两份数据目录的空闲空间（快照/重置会再复制一份） |
| 域名 | 为服务器配置域名的 A/AAAA 记录，指向该机公网地址，并与 `DEMO_DOMAIN` 一致 |

systemd 单元默认把检出放在 `/opt/jkq-demo`，数据目录默认是 `/var/lib/jkq-demo`。可以改路径，但要同步修改单元文件，并在 `deploy/.env` 里设置绝对路径 `DEMO_STATE_DIR`。

### 获取代码

```sh
sudo install -d -o "$USER" -g "$USER" /opt/jkq-demo /var/lib/jkq-demo
git clone https://github.com/FairladyZ625/jingkai-gov-platform.git /opt/jkq-demo
cd /opt/jkq-demo
```

默认检出 `main`。请使用干净、独立的部署目录，不要在含有未提交改动的开发工作树里执行 `deploy/demo update` 或 `rollback`。若仓库为私有，先在服务器上配置有权限的 Git 凭据。systemd 单元默认工作目录是 `/opt/jkq-demo`，若必须换路径，安装定时任务前先改单元文件。

### 配置环境变量

首次安装时从示例复制配置，文件权限仅限当前用户：

```sh
cd /opt/jkq-demo
install -d -m 0700 /var/lib/jkq-demo/data
(umask 077; set -C; cat deploy/env.example > deploy/.env)
```

然后编辑 `deploy/.env`。Compose 优先使用调用环境里的变量，其次读取 `deploy/.env`；长期设置应写进该文件。仓库已忽略 `.env*`，且提交钩子会拦截密钥入库，仍请不要把该文件加入版本库。

`deploy/env.example` 中的变量如下。密钥类只自行生成并填入 `.env`，文档只用占位说明。

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `DEMO_DOMAIN` | 必填 | 对外域名，须已解析到本机。示例值 `demo.example.invalid` 只是占位，Caddy 与健康检查都使用该值 |
| `APP_PORT` | 否，默认 `8000` | 容器内应用监听端口，不对外映射 |
| `HAIKNOW_SECRET` | 必填 | 会话签名密钥。可用 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成 |
| `HAIKNOW_DEMO_LOGIN` | 保持 `0` | 不要改成 `1`。演示身份由下面的 `JKQ_DEMO_MODE=1` 开启，而不是这个开关 |
| `JKQ_DEMO_MODE` | 演示部署填 `1` | 为 `1` 时必须同时配置下面四个口令，否则入口拒绝启动且不打印口令 |
| `JKQ_FRONTEND_API_MODE` | 否 | 容器内前端接口模式。`deploy/env.example` 默认 `mock`（12 段一键演示的兜底）；compose 在未设置时默认 `http`（同源真实会话）。改完后需重建 app 容器才生效 |
| `JKQ_DEMO_ADMIN_PASSWORD` | `JKQ_DEMO_MODE=1` 时必填 | 管理员口令，长度 6 至 1024 位，自行生成 |
| `JKQ_DEMO_LEADER_PASSWORD` | 同上 | 审签领导口令 |
| `JKQ_DEMO_MEMBER_PASSWORD` | 同上 | 经办人员口令 |
| `JKQ_DEMO_PARTNER_PASSWORD` | 同上 | 外部协作者口令 |
| `HAIKNOW_MODEL_PROVIDER` | 否 | 模型后端类型：`cloud`、`local`、`codex-cli` 或 `mock`。不填时先用管理员已保存的路由，再尝试下面三项；都空则用模拟模型。详见 [core/README.md](core/README.md) |
| `HAIKNOW_MODEL_BASE_URL` | 按提供者 | OpenAI 兼容接口的基础地址（须含 API 前缀，例如 `https://example.invalid/v1`）。`mock` / `codex-cli` 可留空 |
| `HAIKNOW_MODEL_NAME` | 按提供者 | 模型名。`mock` 可留空 |
| `HAIKNOW_MODEL_API_KEY` | 按提供者 | 模型密钥，仅写在环境变量里。`cloud` 必填，`local` 视端点而定，`mock` / `codex-cli` 留空 |
| `HAIKNOW_PROVIDER_EXAMPLE_BASE_URL` | 否 | 管理员在后台添加服务商 `example` 时，由环境注入的基础地址 |
| `HAIKNOW_PROVIDER_EXAMPLE_API_KEY` | 否 | 与上一行配对的密钥。带连字符的服务商 ID 会把连字符换成下划线后再读环境变量 |
| `JKQ_CODEX_SMOKE_MODEL` | 否 | 仅用于本机 Codex CLI 联调测试，演示服务器一般不必填写 |

另外两个常用但不在 `env.example` 里的变量：

- `DEMO_STATE_DIR`：宿主机持久目录的绝对路径，默认 `/var/lib/jkq-demo`。若修改，须先创建其下的 `data` 子目录。
- `JKQ_ENTERPRISE_PRIVATE_DB`：企业原值库的容器内绝对路径。演示容器未设置时默认用数据卷内的 `/state/live/enterprise-private.sqlite`。已有原值库的部署请保留原路径；默认值不会覆盖显式配置，也不迁移旧数据。
- `JKQ_DEPLOY_RUNTIME`：由 compose 自动设为 `1`，不必手写。为 `1` 且前端模式为 `http` 时，入口只会改**容器内**前端配置，仓库里的原型文件保持 mock。

生成口令示例（把输出粘贴进 `.env`，不要提交、不要发到聊天或工单）：

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(16))'
```

### 构建与启动

在仓库根目录执行：

```sh
docker compose -f deploy/docker-compose.yml up -d
```

首次构建会安装 Python 依赖并下载 Playwright 的 Chromium，耗时较长。栈包含两个服务：`app`（`python deploy/entrypoint.py`，随后启动单进程 `uvicorn jkq.app:create_app`）和 `proxy`（`caddy:2-alpine`）。只有 `app` 健康后，Caddy 才会对外发布。

启动前可用下面命令检查 compose 文件能否解析（不会创建或启动容器）：

```sh
docker compose -f deploy/docker-compose.yml config >/dev/null
```

### 健康检查

```sh
curl --fail --show-error --output /dev/null --write-out '%{http_code}\n' https://<演示域名>/api/health
```

预期输出 `200`。`/api/health` 为 200 且本机 `POST /api/auth/bootstrap` 与 `POST /api/v1/auth/bootstrap` 均为 404 后，健康检查才会通过；Caddy 对这两条首管路径直接返回 404，不转发到应用。公网再确认：

```sh
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://<演示域名>/api/v1/auth/bootstrap
```

预期同样是 `404`。然后用浏览器打开 `https://<演示域名>/`，分别用下面四个演示账号登录，核对会话身份。

### 演示账号与初始数据

`JKQ_DEMO_MODE=1` 时，实例在对外发布前会创建以下四个口令身份并关闭首管入口。口令只来自对应环境变量，仓库和文档都不存放真实口令。

| 角色 | 用户名 | 姓名 | 口令环境变量 |
| --- | --- | --- | --- |
| 平台管理员 | `admin` | 张磊 | `JKQ_DEMO_ADMIN_PASSWORD` |
| 审签领导 | `liyang` | 李阳 | `JKQ_DEMO_LEADER_PASSWORD` |
| 经办人员 | `wangmin` | 王敏 | `JKQ_DEMO_MEMBER_PASSWORD` |
| 外部协作者 | `hejun` | 何军 | `JKQ_DEMO_PARTNER_PASSWORD` |

业务数据和任务检查点落在 `HAIKNOW_DATA_DIR`（容器内为 `/state/live`，对应宿主机 `${DEMO_STATE_DIR:-/var/lib/jkq-demo}/data`）。

前端若使用 `JKQ_FRONTEND_API_MODE=mock`，一键演示的业务数据在各浏览器的 `localStorage` 中，头像菜单里的「重置演示数据」只清本机浏览器，不会恢复服务器数据目录。要恢复服务器侧演示数据，使用下面的快照与重置。

### 域名与 HTTPS（Caddy，官方方式）

这是仓库提供的对外发布方式。`deploy/Caddyfile` 使用 `{$DEMO_DOMAIN}`，在 80/443 可达时由 Caddy 自动申请和续期证书。证书与 Caddy 配置分别保存在 Docker 命名卷 `certificates` 和 `caddy_config`（Compose 项目名为 `jkq-demo`，宿主机上通常是 `jkq-demo_certificates`、`jkq-demo_caddy_config`）。

请保证：

1. `DEMO_DOMAIN` 与 DNS 记录完全一致（不要带 `https://`）。
2. 服务器防火墙和安全组放行 TCP 80、443。
3. 本机没有其它进程占用这两个端口。

### 可选：用 Cloudflare Tunnel 发布

仓库**没有** `compose.tunnel.yml`，也不包含 cloudflared 服务定义。若服务器不能开放 80/443，可以在宿主机单独安装并运行 `cloudflared`，把隧道指向本机已经工作的 HTTPS 入口（官方 compose 把 Caddy 发布在 80 和 443）。隧道名称、DNS 和证书在 Cloudflare 控制台配置，不在本仓库范围内。

使用隧道时，Cloudflare 返回 **530 / 错误码 1033** 表示边缘连不上源站隧道，常见原因是 `cloudflared` 未运行、服务器休眠或断网，而不是应用自己报错。应用或 Caddy 故障更常见的是 **502**。

### 快照、重置与定时恢复

先在四个账号可登录、且没有进行中的任务时，把当前数据目录打成基准快照；之后的重置都从这份基准恢复，并丢弃基准之后的业务修改：

```sh
cd /opt/jkq-demo
./deploy/demo snapshot
make -f deploy/Makefile demo-reset
```

`snapshot` 会先停应用再复制整个 `data` 目录；再次执行会替换基准。安装每日定时任务（北京时间 03:00，关机错过会在恢复后补跑）：

```sh
# 若检出不在 /opt/jkq-demo，先编辑单元中的 WorkingDirectory 与 ExecStart
sudo install -m 0644 deploy/jkq-demo-reset.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jkq-demo-reset.timer
systemctl list-timers jkq-demo-reset.timer
```

手工重置也可执行 `./deploy/demo reset`。手工操作遇到占锁会立即失败；定时服务占锁时最多等 30 分钟，获得锁后再最多等 2 分钟让应用起来。查看重置日志：`journalctl -u jkq-demo-reset.service`。

若断电后出现 `data.previous` 或 `snapshot.previous`，先停止应用，保留这两份目录，核对后再恢复目录名并重建 app，步骤见 [docs/deploy.md](docs/deploy.md)。

### 升级与回滚

在专用、干净的部署检出中执行。脚本只允许快进合并 `origin/main`，构建成功并通过本机 HTTPS `/api/health` 检查后，才替换上一版记录；失败则切回旧提交和旧镜像。

```sh
cd /opt/jkq-demo
./deploy/demo update
# 退回最近一次成功更新（保留数据）
./deploy/demo rollback
```

涉及不兼容的数据迁移时，先另做停写备份，并确认与旧版本的兼容性。回滚后检出停在旧提交，下一次 `update` 仍从 `origin/main` 快进。

### 备份数据卷

建议在停写窗口备份：

```sh
cd /opt/jkq-demo
docker compose -f deploy/docker-compose.yml stop app
sudo tar -C /var/lib/jkq-demo -czf "jkq-demo-state-$(date +%F).tar.gz" data snapshot
docker run --rm -v jkq-demo_certificates:/data -v jkq-demo_caddy_config:/config \
  -v "$PWD:/backup" alpine tar -czf /backup/jkq-demo-caddy-$(date +%F).tar.gz /data /config
docker compose -f deploy/docker-compose.yml start app
```

若自定义了 `DEMO_STATE_DIR`，把上面的 `/var/lib/jkq-demo` 换成该目录。备份文件含业务数据，按密钥同样的标准保管，不要提交到仓库。

### 查看日志

```sh
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f --tail=200
docker compose -f deploy/docker-compose.yml logs app
docker compose -f deploy/docker-compose.yml logs proxy
journalctl -u jkq-demo-reset.service
```

### 常见问题

- **Docker 未启动**：`docker info` 失败时，先执行 `sudo systemctl start docker`（或按发行版启动 Docker Desktop / 对应服务）。compose 与 `deploy/demo` 在守护进程未运行时都会失败。
- **容器拒绝启动，或一直不健康**：在 `JKQ_DEMO_MODE=1` 下，四个 `JKQ_DEMO_*_PASSWORD` 未设置或长度不在 6 至 1024 位，入口会直接退出且不打印口令；缺少 `HAIKNOW_SECRET` 时实例也会拒绝启动。请检查 `deploy/.env` 后查看 `logs app`。
- **HTTPS 证书失败或浏览器报证书错误**：核对 `DEMO_DOMAIN`、DNS 是否指向本机、80/443 是否放行、是否被其它进程占用。
- **502**：Caddy 已起来，但后端 app 未通过健康检查（`/api/health` 非 200，或首管入口尚未关闭）。查看 app 日志，等待健康或修复配置后重建容器。
- **Cloudflare 530 / 错误码 1033**：隧道连不上源站。检查服务器是否在线、`cloudflared` 是否在跑，而不是先改应用代码。
- **一键演示有的步骤 404**：截至 2026-11-19，真后端尚未覆盖全部演示接口。可在 `deploy/.env` 设置 `JKQ_FRONTEND_API_MODE=mock` 后执行 `docker compose -f deploy/docker-compose.yml up -d --force-recreate app`，再用 `curl -s https://<演示域名>/config/app.config.js` 确认其中含 `mode: 'mock'`。账号登录、健康检查和首管关闭不受影响。接口补齐后改回 `http`（或删除该行）再重建 app。
- **不要把 8000 端口暴露到公网**：官方 compose 只发布 80/443。若自行改了端口映射，等于绕过 Caddy 的 HTTPS 与首管拦截。


## 开发目录

| 目录 | 用途 |
| --- | --- |
| `core/` | 平台底座服务端（`core/server/`）、Python/JS SDK（`core/sdk/`）及测试（`core/tests/`），见 [core/README.md](core/README.md) |
| `apps/` | 小应用目录，当前已提供模板 [apps/_template/README.md](apps/_template/README.md)，新应用由 `scripts/new_app.py` 生成 |
| `jkq/` | 经开区实例入口、路径/错误兼容层与平台业务模块，见 [jkq/README.md](jkq/README.md) |
| `config/`、`data/seed/` | 经开区项目配置（`config/projects.yaml`）与种子数据说明（[REAL_DATA.md](data/seed/REAL_DATA.md)） |
| `deploy/` | 演示环境 Docker Compose、Caddyfile、运维脚本 `deploy/demo`、定时重置与模拟政务站 `deploy/mock-gov/`，见上方「部署到服务器」与 [docs/deploy.md](docs/deploy.md) |
| `web/` | 迁移完成后的前端目录，后端同源托管与静态离线演示入口 |
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

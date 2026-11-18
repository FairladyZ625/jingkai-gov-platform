# 部署演示环境

本说明供有权限的运维人员在专用 Linux 演示机执行。需要 Git、Python 3、GNU Make、flock、curl 7.71+、支持时区的 systemd 和支持 config --no-env-resolution 的 Docker Compose。约定独立检出位于 /opt/jkq-demo，持久目录位于 /var/lib/jkq-demo。域名 A/AAAA 应指向此机，放行 TCP 80、443，供 Caddy 签发证书并对外提供 HTTPS。

## 首次启动

在仓库根目录执行以下准备命令。仅在首次安装时创建配置。

```sh
cd /opt/jkq-demo
install -d -m 0700 /var/lib/jkq-demo/data
(umask 077; set -C; cat deploy/env.example > deploy/.env)
```

如需自定义持久目录，在 deploy/.env 设置绝对路径 DEMO_STATE_DIR，并在该目录创建 data 子目录。Compose 优先使用调用环境的值，其次读取 deploy/.env；手工与定时脚本从 Compose 解析后的 /state/live 挂载定位锁、快照和回退记录。运维人员应将长期设置写入 deploy/.env。编辑 deploy/.env，填写 DEMO_DOMAIN 和实例要求的环境变量：HAIKNOW_SECRET（会话签名，必填，可用 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成）和四个 JKQ_DEMO_*_PASSWORD（容器内无终端，未填时应用拒绝启动）。HAIKNOW_DEMO_LOGIN 保持 0，演示模式由 JKQ_DEMO_MODE=1 开启。模型凭据按需填写 HAIKNOW_MODEL_* 变量。CEO 指定示例文件名为 deploy/env.example，以兼容仓库对 .env 前缀的守卫。示例域名使用保留后缀 .invalid。容器命令是 `python deploy/entrypoint.py`。演示模式（`JKQ_DEMO_MODE=1`）下四个 `JKQ_DEMO_*_PASSWORD` 未设置或长度不在 6 至 1024 位时，入口直接拒绝启动，不打印口令。入口随后启动 `uvicorn jkq.app:create_app --factory --workers 1`，APP_PORT 默认 8000。实例在对外监听前创建 admin、liyang、wangmin、hejun 四个口令身份并关闭首管入口。健康检查同时要求 `/api/health` 为 200，以及本机 `POST /api/auth/bootstrap` 与 `POST /api/v1/auth/bootstrap` 为 404；未关闭前反代不启动。Caddy 对这两条首管路径直接返回 404，不转发到应用。仅当 `JKQ_DEPLOY_RUNTIME=1`（Compose 已设置）时，入口把容器内前端的 `api.mode` 改为 `http`、`baseUrl` 改为空，页面走同源真实会话；仓库里的原型文件保持 `mock`，file:// 仍可离线打开。镜像额外放入 `apps/jkq-hold`，操作名 `hold`：提交后保持 running，容器重启后同一任务 ID 变为 done，已完成的 `saved` 步骤不重复。镜像包含 core/server、core/sdk、jkq/、apps/、config/、data/public/ 和前端目录（有 web/ 时用 web/，否则用 prototype/v4/）。所有业务数据和 job 检查点须落到 HAIKNOW_DATA_DIR。镜像安装与 Chromium 配套的 Python Playwright。应用和浏览器使用容器内部网络，只有反代发布端口。

```sh
docker compose -f deploy/docker-compose.yml up -d
curl --fail --show-error --output /dev/null --write-out '%{http_code}\n' https://<演示域名>/api/health
```

预期输出 200。公网 `POST /api/v1/auth/bootstrap` 返回 404。通过 HTTPS 页面分别用管理员、审签领导、经办人员和外部协作者登录，核对 `/api/v1/auth/session` 返回的身份。用管理员或审签领导提交 `appId=jkq-hold`、`operation=hold` 的任务，确认状态为 running 后执行下面的重启；同一任务 ID 变为 done，`saved` 步骤只执行一次。单 worker 与持久卷提供恢复条件。

```sh
docker compose -f deploy/docker-compose.yml restart
```

## 快照与重置

首次用公开演示种子初始化实例，在四账号可登录且无活动任务时执行以下命令。snapshot 停应用后复制整个 data 目录（含 SQLite 辅助文件），随后启动；再次执行会替换基准。reset 停应用后从基准复制到同一文件系统的临时目录，交换目录并重建应用容器。重置丢弃基准之后的业务修改。Caddy 证书保存在独立命名卷。保留至少两份数据目录的空闲空间。

```sh
./deploy/demo snapshot
export MAKEFILES="$PWD/deploy/Makefile"
make demo-reset
install -m 0644 deploy/jkq-demo-reset.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jkq-demo-reset.timer
systemctl list-timers jkq-demo-reset.timer
```

每日北京时间 03:00 执行，关机错过后在恢复运行时补跑。查看 journalctl -u jkq-demo-reset.service。手工操作也可执行 make -f deploy/Makefile demo-reset。确认恢复后检查基准记录存在、基准后新建记录消失。手工命令遇到占锁立即返回失败。定时服务在占锁时最多等 30 分钟，获得锁后最多再等 2 分钟让应用启动。超时或重置失败会使该次服务返回失败，需检查日志并补跑。若断电后有 data.previous 或 snapshot.previous，请先停止应用，保留两份目录，核对上一份一致的数据，再恢复目录名并重建 app。#50 可调用同一 reset 入口。

## 更新和回滚

在专用干净检出中执行一条命令更新到 origin/main。脚本保留运行中镜像 ID 和旧 Git 版本，仅允许快进，构建后重建应用和 Caddy，等待应用健康，再通过本机 443 端口按配置域名校验证书和 /api/health 的 HTTP 200。成功后原子替换上一版记录。更新失败时切回旧版本的 Compose 和镜像，先把默认标签指回旧镜像再探测健康，并返回失败；若回退后的探测也失败，脚本提示人工排查，后续常规启动仍使用旧镜像。成功更新后可手动退回上一版。回滚后检出位于旧提交，下一次 update 仍从 origin/main 更新。回滚保留数据；涉及不兼容迁移时先另做停写备份，并验证与旧版本的兼容性。

```sh
./deploy/demo update
# 回退最近一次成功更新
./deploy/demo rollback
```

发布验收仍需从公网核对 HTTPS 和四身份。#50 接用同一 reset 入口。

## 公网验收命令

在授权的验收机设置 JKQ_VERIFY_DOMAIN（仅主机名），并通过其凭据管理器提供 JKQ_VERIFY_ADMIN_USER、JKQ_VERIFY_ADMIN_PASSWORD 以及 LEADER、MEMBER、PARTNER 的同名变量。执行 python3 -m pytest -q deploy/test_live.py 检查 HTTPS 健康、四次独立登录与会话。检查续跑时，在重启前记录运行中的 job ID；重启后设置 JKQ_VERIFY_JOB 和该账号角色 JKQ_VERIFY_JOB_ROLE 再执行相同命令。保留重启前的 running 与重启后的 done 两份证据。离线 CI 自动跳过公网验收。

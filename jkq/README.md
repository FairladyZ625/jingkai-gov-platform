# 经开区实例

使用 Python 3.12，先安装 `requirements-dev.txt` 中的依赖。在启动环境中设置
`HAIKNOW_SECRET` 作为会话签名密钥。本地开发可以使用临时生成的随机值，
共用一套数据库的运行进程应使用同一签名配置。

```sh
python3 -m pip install -r requirements-dev.txt
export HAIKNOW_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
make seed
make dev
```

Windows 原生环境可用 `python` 替换 `python3`，并通过 `$env:HAIKNOW_SECRET` 设置密钥后直接运行 `python -m jkq.seed` 与 `PYTHONPATH=core/server;core/sdk` 下的 `python -m uvicorn jkq.app:create_app --factory --host 127.0.0.1 --port 8000`（`Makefile` 目标适用于 Linux/macOS 或 Git Bash/WSL）。

打开 <http://localhost:8000/> 可看同源托管的原型，访问
`/api/health` 得到 `{"ok":true}`。`make test` 运行 Python 回归测试。
`make seed` 通过实例工厂初始化数据库，新库只有 `jkq` 一个项目，
重复运行保留库内现有数据。
实例在打开数据库前检查 `HAIKNOW_CONFIG_DIR/projects.yaml`，要求一个组织和唯一的
`jkq` 项目。旧版若用错误配置初始化出了空项目库，修正配置后对原数据目录重跑
`make seed`，即可补齐项目并保留库内数据。

| 环境变量 | 默认值 |
| --- | --- |
| `HAIKNOW_SECRET` | 必填 |
| `HAIKNOW_ROOT` | 当前仓库根目录 |
| `HAIKNOW_APPS_DIR` | 根目录下的 `apps/` |
| `HAIKNOW_DATA_DIR` | 根目录下的 `data/private/jkq/` |
| `HAIKNOW_CONFIG_DIR` | 根目录下的 `config/` |
| `JKQ_WEB_DIR` | 优先使用 `web/`，目录缺失时使用 `prototype/v4/` |

静态目录需要包含 `index.html`。原型的 mock 或 HTTP 模式由其自身的前端配置决定。

## 挂载平台业务

按两种方式接入实例，每个模块只占一行：

- 纯新增、不需要回落 core 的路由：模块导出
  `router = APIRouter(prefix="/api/v1/业务前缀")`，登记进 `jkq/routers.py` 的 `ROUTERS`。
- 需要包住或回落 core 路由，或需要平台存储的模块：导出 `install(app, ...)`，
  在 `jkq/app.py` 的 `install_platform` 中调用（实例在 `register_routes(app)` 之后执行它）。
  存储对象挂在 `app.state` 上供下游模块取用，会话存储为 `app.state.conversations`。
  长任务（`jobs_api`）和审签（`reviews_api`）原地替换 core 路由，带 SDK 参数的请求仍交给 core，
  不能改成登记进 `ROUTERS` 的 APIRouter。

登录依赖在 `install_platform` 中统一指定，目前使用 core 的 `current_user`，
换成经开区登录态时只改这一处。

`ROUTERS` 中原生路由优先处理同方法、同路径的请求。
auth、admin、kb 的前缀分别映射到 core 的 `/api/auth`、`/api/admin`、
`/api/v1/knowledge`。别名目标完全匹配时允许转发，其余请求保留原生路由的
尾斜杠重定向和方法限制。会话和权限检查由目标接口执行。
业务路由使用 `request.app.state.platform` 获取实例，并可复用 core 的
`current_user` 鉴权依赖。

`auth/session`、`admin/departments` 及其子项
的占位路由返回 404 `NOT_FOUND`。业务模块在 `ROUTERS` 接管对应路径后可删除占位。

`/api/v1/` 错误使用 `{error: {code, message, details}}`。登录凭据错误使用
`BAD_CREDENTIALS`，缺少有效会话使用 `UNAUTHENTICATED`，拒绝访问使用
`FORBIDDEN`，资源或路由不存在使用 `NOT_FOUND`。其余 core 错误保留原 HTTP
状态和具体错误语义，错误码写作大写。业务路由抛出 4xx `HTTPException` 时保留公开字符串提示，
5xx 使用通用提示。

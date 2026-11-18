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

打开 <http://localhost:8000/> 可看同源托管的原型，访问
`/api/health` 得到 `{"ok":true}`。`make test` 运行 Python 回归测试。
`make seed` 通过实例工厂初始化数据库，新库只有 `jkq` 一个项目，
重复运行保留库内现有数据。

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

业务模块导出 `router = APIRouter(prefix="/api/v1/业务前缀")`，
由 `jkq/routers.py` 的 `ROUTERS` 集中登记。实例业务路由优先处理同方法、同路径的请求。
未被实例业务路由接管时，auth、admin、kb 的前缀分别转给 core 的
`/api/auth`、`/api/admin`、`/api/v1/knowledge`，保留卫华的会话及权限检查。
业务路由使用 `request.app.state.platform` 获取实例，并可复用 core 的
`current_user` 鉴权依赖。

`/api/v1/` 错误使用 `{error: {code, message, details}}`。登录凭据错误使用
`BAD_CREDENTIALS`，缺少有效会话使用 `UNAUTHENTICATED`，拒绝访问使用
`FORBIDDEN`，资源或路由不存在使用 `NOT_FOUND`。其余 core 错误保留原 HTTP
状态和具体错误语义，错误码写作大写。

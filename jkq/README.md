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
状态和具体错误语义，平台错误码使用大写 SNAKE_CASE。公文、企业、会议和政策应用的健康检查同样使用 `UNAUTHENTICATED` 和 `FORBIDDEN`。业务路由抛出 4xx `HTTPException` 时保留公开字符串提示，
5xx 使用通用提示。

## 本机 Codex CLI 对话

在仓库根目录操作。服务进程须与已登录 Codex 的用户相同，并能在其 PATH 中找到
`codex`。CLI 会使用该账号连接模型服务，只传公开、合成文本。请求需显式指定
`"classification":"public"`。内部、机密资料及其摘要均不可发送到此后端。

1. 安装 OpenAI Codex CLI（可用 `npm install -g @openai/codex`），运行
   `codex login` 完成登录。已有登录可用 `codex login status` 确认。
2. 按本文开头的步骤安装 Python 3.12 依赖、配置会话签名并运行 `make seed`。
   在同一终端设置下列变量，填入该账号可使用的模型名，然后启动或重启实例。

   ```sh
   export JKQ_CODEX_MODEL_ENABLED=1
   printf 'Codex 模型名：'
   read -r JKQ_CODEX_MODEL_NAME
   export JKQ_CODEX_MODEL_NAME
   make dev
   ```

   默认关闭。仅设置模型名不会启用 CLI。`JKQ_CODEX_MODEL_TIMEOUT` 配置一次调用的
   超时秒数（默认 30），`JKQ_CODEX_MODEL_MAX_CONCURRENCY` 配置同时执行的上限
   （默认 2）。如需优先自动路由，可在启动前另设 `JKQ_MODEL_PROVIDER=codex-cli`。
3. 在另一终端运行以下脚本，输入本地**实例**的有效账号和密码。若新库尚无账号，先在本机服务的 `/docs` 中调用 `POST /api/auth/bootstrap`，按其请求格式建立首个管理员。
   脚本默认通过请求参数选模，保留账户的模型偏好。使用专用验收账号时，可以输入 `y` 保存当前模型，再验证没有 `model` 参数的请求能用上该偏好。
   若同时验证工具，使用对政策应用有操作权限的账号。

   ```sh
   python3.12 - <<'PY'
   import json
   from getpass import getpass
   import httpx

   user = getpass("实例用户名（输入不回显）：")
   password = getpass("实例密码：")
   save_current = getpass("专用验收账号是否保存当前模型 [y/N]：") == "y"
   check_tool = getpass("同时验证政策工具 SSE [y/N]：") == "y"

   with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60, trust_env=False) as api:
       api.post("/api/v1/auth/login", json={"username": user, "password": password}).raise_for_status()
       catalog = api.get("/api/v1/models").raise_for_status().json()
       cli = next(item for item in catalog["items"] if item["id"] == "codex-cli")
       print(cli["id"], cli["name"], cli["enabled"])
       assert cli["enabled"]
       payload = {"classification": "public"}
       if save_current:
           saved = api.put("/api/v1/models/current", json={"model": "codex-cli"})
           assert saved.raise_for_status().json()["current"] == "codex-cli"
       else:
           payload["model"] = "codex-cli"
       path = "/api/v1/ai/chat"
       reply = api.post(path, json={
           **payload, "messages": [{"role": "user", "content": "请仅回复 JKQ_CODEX_OK"}],
       }).raise_for_status().json()
       print(reply["model"], reply["mock"], reply["content"])
       assert reply["model"] == cli["name"] and reply["mock"] is False
       assert reply["content"].strip() == "JKQ_CODEX_OK"

       if check_tool:
           with api.stream("POST", path, json={
               **payload, "stream": True, "tools": ["policy.match"],
               "messages": [{"role": "user", "content": "请调用政策匹配工具，企业编号为公开演练值 E001"}],
           }) as response:
               response.raise_for_status()
               assert response.headers["content-type"].startswith("text/event-stream")
               event = None
               seen = {}
               for line in response.iter_lines():
                   if line.startswith("event: "):
                       event = line.removeprefix("event: ")
                   elif line.startswith("data: "):
                       seen.setdefault(event, []).append(json.loads(line.removeprefix("data: ")))
               assert seen["meta"][0]["model"] == cli["name"]
               assert {"tool": "policy.match", "args": {"entId": "E001"}} in seen["tool"]
               print("工具事件", seen["tool"], "完成", seen["done"][0]["messageId"])
   PY
   ```

### 工具、流式与故障

上方脚本的工具验收读取 SSE 事件。实例把已注册的工具声明传给 CLI。带工具的模型输出须为单个 JSON 对象，例如

```json
{"content":null,"tool_calls":[{"name":"policy_match","arguments":{"entId":"E001"}}]}
```

`content` 可为文本或 null，`tool_calls` 为数组，无调用时用空数组。工具名必须是本次声明中的函数名，参数必须是 JSON 对象。SSE 的 `tool` 事件将别名映射回应用工具名，例如
`{"tool":"policy.match","args":{"entId":"E001"}}`。此事件表示模型请求调用工具。

非流式是默认行为。`stream:true` 会等 CLI 成功退出再发送 `meta`，将完整文本切成每块最多
128 个 Unicode 字符的 `delta`，随后发送可选的 `tool` 和最终的 `done`。
失败进程写出的半句不会作为回答发送。并发已满即拒绝（429 `QUOTA_EXCEEDED`）。
非零退出或工具输出格式错误对应 502 `PROVIDER_ERROR`，超时对应 504 `TIMEOUT`。
有可用回退时，响应可能由其他模型完成；查看 `model`、`mock` 和 `routeNote` 判断实际来源。

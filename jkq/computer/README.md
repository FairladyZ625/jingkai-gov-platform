# 本地模拟政务站运行器

在经开区实例的应用工厂中，配置模拟站后调用 `jkq.computer.api.install(app, current_user, url=mock_url)`。`current_user` 使用卫华会话依赖。实例的 RBAC 需为 `computer` 授予 `view` 或 `operate`，系统启停需要 `admin`。外部协作者始终拒绝。安装应在进入 FastAPI lifespan 前完成。

开发环境用 `make mock-gov` 启动 `http://127.0.0.1:8090/`。安装 `requirements-ui.txt` 声明的 Playwright 1.57.0 后，运行 `python -m playwright install chromium`。使用现有 Chrome 时可在安装路由时传入 `channel="chrome"`。

## 调用顺序

1. `POST /api/apps/computer/runs` 接收 `{"task":"apply"}`，返回 202 和 `item.id`。可带 `Idempotency-Key` 防重复启动。
2. 轮询 `GET /api/apps/computer/runs/{id}`。每步包含日志和经过遮盖的 PNG。列表返回截图数量。
3. 当 `item.status` 为 `waiting`，以 `item.pending.kind` 向 `POST .../confirm` 提交 `{"decision":"approve","kind":"otp"}`。可提交 `{"decision":"decline"}` 停止。批准只适用于当前步骤。
4. 从 `item.result.no` 读取模拟受理编号。经办人也可用 `PATCH .../runs/{id}` 的 `{"status":"stopped"}` 停止。步骤、截图、日志与回执由进程内运行器直接回报，HTTP 客户端提交这些字段会被拒绝。

浏览器会话使用部署明确配置的回环地址及端口。请求按来源和方法拦截，重定向、WebSocket 和 Service Worker 均受限。申报资料使用站点预设示例。站点提供签章或付款按钮时，分别等候独立批准。原始模拟站提供验证码和提交两个确认点。

## 长任务接入

`Runner` 使用 `Run.capture` 提交步骤与截图，通过 `Run` 的当前确认点暂停。当前 `Runs` 仍是单进程内存适配，限 3 个并发，启动至结束（含人工等待）的上限是 600 秒。运行记录、回执和幂等键按经办人保留，不会因其他经办人新任务被删除；超过 30 条时只清理已结束任务的截图热缓存。实例通过环境变量 `JKQ_MOCK_GOV_URL`（可选 `JKQ_BROWSER_CHANNEL`）在 `register_routes` 中挂载。卫华审计保存开始、步骤、拒绝、批准和结果事件。接入 #18 时，需将运行记录、可见性及超时投影到平台长任务，保留单次确认语义。浏览器重启后无法恢复原页面，已批准的操作应保守终止，防止任务重跑时重复提交。卫华通用审签对版本记录拒绝自审，不能直接替代原经办人确认模拟操作的交互。

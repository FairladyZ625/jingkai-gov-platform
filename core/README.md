# 平台 core

服务端位于 `core/server`，Python 与 JavaScript SDK 位于 `core/sdk`。快照版本和授权记录见 [VERSION](VERSION) 与 [NOTICE](NOTICE)。

## 启动

在仓库根目录用 Python 3.12 执行以下命令。临时数据目录用于本地试跑，每次执行会创建一个空目录。

```sh
python3 -m pip install -r requirements.txt
HAIKNOW_DATA_DIR="$(mktemp -d)" PYTHONPATH=core/server:core/sdk \
  python3 -m uvicorn haiknow_core.main:app --host 127.0.0.1 --port 8000
```

`GET /api/health` 返回启动状态，`GET /openapi.json` 返回路由契约，`/docs` 可交互查看 API。全新目录以空账号集启动，`GET /api/auth/state` 返回 `needsBootstrap: true`。临时目录以外的经开区实例配置见 [jkq/README.md](../jkq/README.md)。

`HAIKNOW_DEMO_LOGIN=1` 启用演示身份。关闭后重启，即使复用原数据库与会话签名配置，演示身份也无法登录或使用已有会话。若库中只有演示管理员，可以引导正式管理员。

服务启动时注册身份、权限、应用清单、数据、模型网关、知识库、长任务、定时任务与 v1 接口。飞书、CAD、LaTeX、数据集、嵌入代理和造应用服务端均停用。SDK 保留对应的预览客户端接口，调用时需要目标启动对应服务。知识库以空语料启动。

## 模型后端

[变量清单](../deploy/env.example) 仅含空占位。请由启动进程、容器或部署平台注入实际环境变量。修改默认后端后重启服务。

| `HAIKNOW_MODEL_PROVIDER` | `HAIKNOW_MODEL_BASE_URL` | `HAIKNOW_MODEL_NAME` | `HAIKNOW_MODEL_API_KEY` |
| --- | --- | --- | --- |
| `cloud` | 云服务的 OpenAI 兼容 HTTPS 基础地址 | 已开通的模型名 | 必填，由进程环境注入 |
| `local` | 内网 OpenAI 兼容 HTTP 或 HTTPS 基础地址 | 内网服务配置的模型名 | 由端点的鉴权要求决定，可留空 |
| `codex-cli` | 留空 | 本机 Codex 登录可使用的模型名 | 留空，由 Codex CLI 使用本机已有登录 |
| `mock` | 留空 | 留空 | 留空，使用离线模拟 |

基础地址应包含服务的 API 前缀，例如 `https://cloud.example.test/v1` 或 `http://127.0.0.1:8080/v1`。网关在该地址后追加 `/chat/completions`。内网后端直连配置地址，避开环境代理。设置 `HAIKNOW_MODEL_PROVIDER` 后，默认对话路由由进程环境接管。配置不全时返回配置错误。省略此变量时优先使用管理员已保存的对话路由，其次使用原有的三项 `HAIKNOW_MODEL_*` 配置。三项均为空且没有保存路由时使用模拟模型。

管理员可通过 `/api/v1/admin/ai/providers/{id}` 保存服务商元数据，通过 `/api/v1/admin/ai/routes/{capability}` 保存能力路由。服务商 ID 使用小写字母、数字和连字符。以 `example` 为例，由运维注入 `HAIKNOW_PROVIDER_EXAMPLE_BASE_URL` 与 `HAIKNOW_PROVIDER_EXAMPLE_API_KEY`。带连字符的 ID 将连字符换成下划线。只有管理员填写的基础地址与环境固定地址一致时，网关才会发出该凭据。管理 API 拒收凭据实值，查询只返回配置状态及掩码。路由配置与模型调用审计使用同一个模型字段。

Codex CLI 仅用于公开合成文本的本机联调。它在独立临时目录以只读、临时会话运行，关闭 shell、hooks 和网页搜索。平台通过标准输入传递文本，CLI 自行管理登录。

升级 SQLite 时，v14 保留服务商元数据、路由和用量，清除旧的模型凭据列与停用的飞书加密字段。升级时生成的新备份保留原 schema 及业务数据，将这两列置空。此前已生成的历史备份与主密钥文件由实例运维按保留策略处置。旧服务商应重新通过环境配置凭据。

## 验证

安装开发依赖后，`pytest -q` 收集仓库、core、应用模板及已生成应用的测试。仅安装 pytest 时，默认收集仓库中无需 core 运行依赖的测试。完整 `check.py` 显式检查所有测试目录，并在 Node 可用时运行 SDK 的 JavaScript 行为测试（Windows 上可将 `python3` 替换为 `python`）。

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 scripts/check.py
```

在已登录 Codex CLI 的本机设置 `JKQ_CODEX_SMOKE_MODEL` 为可用模型，再运行下列命令。CI 缺少 CLI 或未设置模型时跳过实际调用，离线回归仍执行。

```sh
python3 -m pytest -q -s core/tests/test_model_providers.py::test_real_codex_cli_smoke
```

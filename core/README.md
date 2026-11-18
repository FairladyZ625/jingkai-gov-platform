# 平台 core

服务端位于 `core/server`，Python 与 JavaScript SDK 位于 `core/sdk`。快照版本和授权记录见 [VERSION](VERSION) 与 [NOTICE](NOTICE)。

## 启动

在仓库根目录用 Python 3.12 执行以下命令。临时数据目录用于本地试跑，每次执行会创建一个空目录。

```sh
python3 -m pip install -r requirements.txt
HAIKNOW_DATA_DIR="$(mktemp -d)" PYTHONPATH=core/server:core/sdk \
  python3 -m uvicorn haiknow_core.main:app --host 127.0.0.1 --port 8000
```

`GET /api/health` 返回启动状态，`GET /openapi.json` 返回路由契约，`/docs` 可交互查看 API。全新目录以空账号集启动，`GET /api/auth/state` 返回 `needsBootstrap: true`。临时目录以外的实例配置由经开区实例任务提供。

服务启动时注册身份、权限、应用清单、数据、模型网关、知识库、长任务、定时任务与 v1 接口。飞书、CAD、LaTeX、数据集、嵌入代理和造应用服务端均停用。SDK 保留对应的预览客户端接口，调用时需要目标启动对应服务。知识库以空语料启动。

## 验证

安装开发依赖并执行回归。完整 `check.py` 还会在 Node 可用时运行 SDK 的 JavaScript 行为测试。

```sh
python3 -m pip install -r requirements-dev.txt
pytest -q
python3 scripts/check.py
```

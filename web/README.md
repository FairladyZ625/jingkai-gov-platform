# 经开区共享智能体工作站 · v4 综合版原型

双击 `index.html` 即可（file://，无需联网）。登录页有 4 个演示账号一键进入；侧栏底部「一键演示」把所有功能自动走一遍。

一键选身份和重置本机数据仅用于 `file://` 离线 mock。部署的 HTTP 工作台使用服务端返回的身份和授权：合作方没有切换视角、启动内部演示或重置入口；成员、领导、管理员在演示中切号仍须输入目标账号口令。首屏词典只读取获准查看的应用；隐藏按钮不代替服务端鉴权。托管 mock 只适合公开样本，不提供真实业务的数据隔离。

## 如何修改（不用碰业务代码）
| 想改什么 | 改哪里 |
|---|---|
| 颜色（深色/浅色、强调色、标签色槽） | `assets/theme.css` |
| 某个标签用什么颜色 | `config/tags.js` |
| 平台名、首页 3 条建议、演示账号、接口模式 | `config/app.config.js` |
| 启用/排序应用 | `config/apps.js` |
| 账号、部门、角色、授权 | `config/accounts.js`（运行中也可在“管理后台”改） |
| 演示数据 | `config/mock-data.js`、`data/`（真实公开政策） |
| AI 能听懂的平台级说法 | `config/operator-intents.js`；应用级在各应用 manifest.intents |
| 拖入对话框的样例文件 | `config/sample-files.js` |
| 一键演示步骤 | `config/demo-script.js` |
改完刷新；改了数据请点头像菜单 →「重置演示数据」。

## 结构（前后端分离）
界面 `assets/`（外壳）+ `apps/<id>/`（应用）→ 只调 `api/*.js`（接口适配，入参/出参对齐《接口规范》）→ `config/app.config.js` 的 `api.mode`：`mock` 走浏览器内 `mock/`，`http` 走真实后端。详见[应用契约](../docs/APP_CONTRACT.md)和[设计规范](DESIGN.md)。

## 静态部署与回归

从仓库根目录运行 `python3 -m http.server -d web 8080`，打开 <http://localhost:8080/>。部署在子路径时，把 `web/` 的内容放在对应目录下（例如 `/v4/`），按目录网址访问。

```sh
npm --prefix web ci
(cd web && npx --no-install playwright install chromium)
npm --prefix web run test:smoke
npm --prefix web run test:e2e
```

冒烟测试验证根路径、`/v4/`、无效口令和断网直开。演示测试在子路径上按段验证业务结果。两个测试命令都会启动本地测试服务，使用 8080 和 8081 端口。

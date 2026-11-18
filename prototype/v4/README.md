# 经开区共享智能体工作站 · v4 综合版原型

双击 `index.html` 即可（file://，无需联网）。登录页有 4 个演示账号一键进入；侧栏底部「一键演示」把所有功能自动走一遍。

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
界面 `assets/`（外壳）+ `apps/<id>/`（应用）→ 只调 `api/*.js`（接口适配，入参/出参对齐《接口规范》）→ `config/app.config.js` 的 `api.mode`：`mock` 走浏览器内 `mock/`，`http` 走真实后端。详见 `APP_CONTRACT.md`、`DESIGN.md`。

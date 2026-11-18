# Web 接口契约

使用 Node.js 22 或更新版本。在仓库根目录运行。

```sh
npm --prefix web run contract
node --test web/tests/contract/*.test.cjs
npm --prefix web run contract -- --base http://127.0.0.1:8000 --module platform
```

默认在独立的内存状态中运行现有浏览器 mock 和请求层。JSON 清单按《接口规范》§7 的模块划分，`runner.test.cjs` 逐项核对方法和路径。`routes` 各覆盖一条规范路径，`errors` 补充业务错误。成功响应校验必需字段和类型，失败响应校验状态码及 `error.code`、`error.message`、`error.details`。mock 的 JS 业务异常在测试边界转换成接口错误形状。HTTP 模式直接校验收到的 JSON。

每个用例可以用 `save` 保存响应，后续请求用 `{{响应名.字段}}` 引用生成的 ID 或对象。路径模板通过 `params` 填值，模型中 `@名称` 引用 `models.json`，`?` 允许字段值为 null。

HTTP 模式面向可重置的演示实例。用例包括导入、写入、权限配置和平台演示重置。运行前从环境变量提供演示管理员账号 `CONTRACT_USERNAME` 与 `CONTRACT_PASSWORD`，也可用 `CONTRACT_TODO_ID`、`CONTRACT_REVIEW_ID`、`CONTRACT_KB_DOC_ID`、`CONTRACT_KB_URL`、`CONTRACT_MEETING_ID` 和 `CONTRACT_ENTERPRISE_ID` 替换目标实例的种子记录。非平台模块会先登录再运行自身用例。使用 `--module` 省略不相关的契约用例。每次 HTTP 请求的连接与响应读取最多等待八秒，首次连接失败会结束运行。

§7 将知识库撤销删除列为 `POST /api/v1/kb/docs/{id}`，§3.6 列为 `POST /api/v1/kb/docs/{id}/restore`。清单按 §7 请求，mock 在公共请求层把该路径交给已有的撤销删除处理器。HTTP 结果由后端对 §7 路径的实际响应决定。

混合模式通过 `web/config/app.config.js` 的 `api.modules` 设置。知识库兼容别名按 `kb` 传输，技能列表按 `skills` 传输，会议转写轮询按 `meeting` 传输。两个传输各使用自身的会话。

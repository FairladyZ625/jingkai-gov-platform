# Web 接口契约

使用 Node.js 22 或更新版本。在仓库根目录运行。

```sh
npm --prefix web run contract
node --test web/tests/contract/*.test.cjs
npm --prefix web run contract -- --base http://127.0.0.1:8000 --module platform   # 只读
CONTRACT_RESETTABLE_TARGET=127.0.0.1:8000 npm --prefix web run contract -- --base http://127.0.0.1:8000 --allow-writes
```

默认在独立的内存状态中运行现有浏览器 mock 和请求层。JSON 清单按《接口规范》§7 的模块划分，`runner.test.cjs` 逐项核对方法和路径。`routes` 各覆盖一条规范路径，`errors` 补充业务错误。成功响应校验必需字段和类型，失败响应校验状态码及 `error.code`、`error.message`、`error.details`。mock 的 JS 业务异常在测试边界转换成接口错误形状。HTTP 模式直接校验收到的 JSON。

每个用例可以用 `save` 保存响应，后续请求用 `{{响应名.字段}}` 引用生成的 ID 或对象。路径模板通过 `params` 填值，模型中 `@名称` 引用 `models.json`，`?` 允许字段值为 null。

HTTP 模式默认只读：只发 GET、登录/退出，以及规范标明不落库的查询（知识库检索、问答、导入预览，政策匹配、试算，电脑操作意图匹配）。其余写入用例跳过，并在模块结果后注明跳过条数。依赖被跳过写入所生成数据的用例同样跳过。

全量写入只能对明确可重置的隔离演示实例运行：加 `--allow-writes`，并设置 `CONTRACT_RESETTABLE_TARGET` 为目标的 `host[:port]`（与 `--base` 完全一致）。运行结束时，无论成败，都会用新会话请求 `POST /api/v1/demo/reset` 回滚共享状态；重置失败时退出非零并提示手动重置。知识库的修改、删除和恢复只针对本轮导入的资料，恢复走 `/restore` 并回读确认。

远程目标必须使用 HTTPS；明文 `http://` 只允许 `localhost`、`127.0.0.0/8` 和 `::1`，违规地址在发出任何请求前退出。

运行前从环境变量提供演示管理员账号 `CONTRACT_USERNAME` 与 `CONTRACT_PASSWORD`，也可用 `CONTRACT_TODO_ID`、`CONTRACT_REVIEW_ID`、`CONTRACT_KB_DOC_ID`、`CONTRACT_KB_URL`、`CONTRACT_MEETING_ID` 和 `CONTRACT_ENTERPRISE_ID` 替换目标实例的种子记录。每个模块先登录并校验 `{ user, role, grants }`，登录失败立即中止，不发任何业务请求。使用 `--module` 省略不相关的契约用例。每次 HTTP 请求的连接与响应读取最多等待八秒，首次连接失败会结束运行。

混合模式通过 `web/config/app.config.js` 的 `api.modules` 设置。知识库兼容别名按 `kb` 传输，技能列表按 `skills` 传输，会议转写轮询按 `meeting` 传输。平台走 HTTP、部分应用留在 mock 时，HTTP 登录、会话查询或 `/me` 成功后，请求层按远端账号的角色映射一个本地演示账号建立 mock 会话（远端口令不进入本地）；HTTP 退出或平台接口返回 401 时清除该会话。

`safety.test.cjs` 覆盖上述写入保护、明文拒绝、知识库恢复回读、混合会话，以及逐项删除必需字段或替换类型时契约失败。

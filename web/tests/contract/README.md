# Web 接口契约

在仓库根目录用 Node.js 22 或更新版本执行。

```sh
npm --prefix web run contract
node --test web/tests/contract/*.test.cjs
npm --prefix web run contract -- --base http://127.0.0.1:8000 --module platform
```

默认运行仓库的浏览器 mock 和请求层。每个模块的 `routes` 对应《接口规范》§7 的路径，`errors` 补充业务错误。成功响应校验必需字段及嵌套类型，失败响应校验状态码和 `error.code`、`error.message`、`error.details`。知识库恢复遵循 §3.6 的 `/restore`。

用 `save` 保存响应，用 `{{响应名.字段}}` 引用同一轮创建的 ID 或对象。模型使用 `@名称` 引用 `models.json`。字段名末尾的 `?` 表示键可省略，类型开头的 `?` 表示值可为 null。动态对象用 `$values` 校验各键的值。会议列表使用摘要模型，技能草稿可省略旧的 `visibility`，该场景使用 `share.scope`。部分政策条目省略旧字段 `sub`、`action`，政策清单显示的文号、文件标题和状态始终必需。

## 连接 HTTP 实例

凭据通过环境变量 `CONTRACT_USERNAME` 和 `CONTRACT_PASSWORD` 提供。远程目标必须使用 HTTPS。明文 HTTP 仅限 `localhost`、`127.0.0.0/8` 和 `::1`。CLI 不跟随重定向，每个请求最多等待八秒。

默认发送登录和读取。导出、退出、POST 查询及业务写入会跳过，依赖写入结果的读取也会跳过。退出可能使同一账号的其他会话失效。CLI 在内存中保存自己的会话 Cookie，未授权错误用例用独立的空会话发出。每个模块输出执行数和跳过数。

全量写入需要独占且可重置的隔离演示实例。只有确认该实例的数据可清空后，才将 `CONTRACT_RESETTABLE_TARGET` 设为与 `--base` 完全一致的规范化地址，保留路径并省去末尾的斜杠。运行时同时加 `--allow-writes`。例如，已确认的回环测试实例可执行：

```sh
CONTRACT_RESETTABLE_TARGET=http://127.0.0.1:8000 npm --prefix web run contract -- --base http://127.0.0.1:8000 --allow-writes
```

CLI 先验证管理员的登录与 Cookie 会话，再检查 `POST /api/v1/demo/reset` 是否返回 `{ ok: true }`。预检失败会中止业务写入。写入开始后，无论用例成败，均重新登录并重置演示数据。重置失败会返回非零。知识库文档用每次生成的唯一标题导入，修改和删除只引用该次导入返回的资料 ID。测试会回读删除后的 404 及恢复后的原 ID。

带固定演示资料的路径可通过 `CONTRACT_TODO_ID`、`CONTRACT_REVIEW_ID`、`CONTRACT_KB_DOC_ID`、`CONTRACT_KB_URL`、`CONTRACT_MEETING_ID`、`CONTRACT_ENTERPRISE_ID` 配置。KB 的固定资料 ID 只用于读路径。

## 混合模式验证

`web/config/app.config.js` 的 `api.modules` 可单独选择任一模块。平台走 HTTP 时，Web 请求层将已确认的远端角色映射到本地演示账号，为 mock 模块建立独立会话。HTTP 退出时即清理本地会话。

`safety.test.cjs` 覆盖写入边界、连接安全、知识库恢复和缺字段变异。CI 的 `browser.cjs` 在 Chromium 中用空存储打开实际 Web 入口，执行 HTTP 登录、访问 mock 知识库、刷新和退出。

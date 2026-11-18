# __APP_NAME__

> 负责人：__OWNER__ ｜ 关联 Issue：#__ISSUE__ ｜ 场景编号：（填 app.json 的 scenes）

这是一个**能直接跑通的骨架**：保存一条记录 → 提交确认 → 换有 `approve` 的账号确认 → 导出 CSV。七问按这个通用流程写好，接入真实场景时逐节替换成你的业务；`app.json` 的 `status` 现在是 `prototype`，七问不能留空。

## 需求七问

### 1. 触发

需要把一条工作记录留档、交给别人确认时打开。典型场景：现场先记一条，主管确认后才作为正式结果导出。

### 2. 使用者与确认人

- 办理员（`sampleoperator`）：新建、修改、提交，有 `view` + `operate`。
- 审核员（`samplereviewer`）：有 `view` + `operate` + `approve`，在「待我确认」里确认或退回。
- 观察员（`sampleobserver`）：只有 `view`，只看不写。

角色与动作写在 `app.json` 的 `defaultRoles`；平台在服务端再判一次，前端按钮只是提示。

### 3. 输入

标题（必填，最多 80 字）和补充说明（可选，最多 2000 字）。样例是 `samples/示例记录.json`，内容为虚构，接入时替换成脱敏或虚构样例。

### 4. 处理步骤

1. 新建：平台生成记录，`version=1`，状态 `draft`，写入本应用留痕 `create`。
2. 修改：带 `baseVersion` 保存，平台生成新版本；版本落后返回 `409 version_conflict`。
3. 提交：校验版本和状态后创建待办，状态转 `pending`，留痕 `submit`。
4. 确认：有 `approve` 且不是提交人的账号确认后状态转 `confirmed`；退回转 `needs_info`。
5. 导出：只允许导出已确认版本，生成 CSV 并留痕 `export`。

记录、版本、确认和成果都由平台数据底座执行（运行平台后见 `/docs` 的 API 文档），应用不自己维护版本号。

### 5. 确认依据

提交人看标题与补充说明是否完整；确认人看记录正文、提交人和版本号。自动判定与模型输出只作参考，最终由人确认。

### 6. 输出

CSV：标题、内容、状态、提交人、确认人，浏览器直接下载。需要服务端文件或跨应用引用时，改用 `ctx.data_files` 与记录里的 `refs`。

### 7. 验收样本

用 `samples/示例记录.json` 的标题和内容：

1. 办理员登录，新建一条，看到状态「草稿」。
2. 办理员点「提交确认」，状态变「待确认」。
3. 切审核员，在「待我确认」里点「确认」，状态变「已确认」。
4. 在「已确认成果」点「导出 CSV」，文件含标题、提交人和确认人。
5. 管理员在「留痕」页看到 `create`、`submit`、`confirm`、`export`。

自动化覆盖在 `tests/`：正常流程、无权限（403）、输入错误（422/409）、导出与留痕。

## 开发说明

```bash
scripts/dev.sh                                  # 起平台
python scripts/check.py --app __APP_ID__        # 只查本应用
python scripts/check.py                         # 提 MR 前全量
```

- 页面入口 `web/index.js`，后端入口 `api/router.py`，需求七问就是本文件。
- 业务事件需要提醒同事时，先由应用选定收件人和来源版本，再调用 `ctx.preview.messages.send`；不要把页面提示自动改成消息发送。消息仅写入应用内收件箱：

```python
message = ctx.preview.messages.send(
    idempotency_key=f"change-{record['id']}-v{record['version']}",
    recipient_ids=["samplereviewer"],
    record_id=record["id"],
    version=record["version"],
    title="变更待核对",
    body="请查看当前版本并确认是否需要处理。",
    priority="high",
    requires_acknowledgement=True,
)
```

- `record_id/version` 必须指向当前应用记录；平台校验所有收件人的 active 身份和来源权限。查询各人状态用 `ctx.preview.messages.sent()`，回执用 `inbox/get/read/acknowledge`。
- 只改本目录；平台能力只经 `haiknow_sdk`、`/sdk/ui/index.js`（页面组件）和 `/sdk/haiknow.js`（`ctx` 与 `v1`）。
- 启动服务与执行回归的命令见 [core/README.md](../../core/README.md)。

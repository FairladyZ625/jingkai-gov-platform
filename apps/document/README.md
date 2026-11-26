# 公文协作

> 负责人：summerchaserwwz ｜ 关联 Issue：#38、#40 ｜ 场景编号：（后续业务 Issue 补 scenes）

按模板起草公文、保存历史版本，定稿后锁定。现有四步应用保留新建入口，工作台从文稿档案直接进入修改、核查、批注、版本比对和审核。

## 需求七问

### 1. 触发

需要按机关常用模板起草通知、请示或意见，并保留可回看的历史版本时打开。典型场景：根据申报延期要素生成初稿，修改三次后定稿。

### 2. 使用者与确认人

- 经办人（member）：查看模板、起草和保存，需要 `view` + `operate`。
- 审签领导（leader）：查看、审签确认需要 `view` + `approve`；修改正文另需 `operate`。
- 管理员（admin）：全部动作。外部协作者默认无本应用授权，访问返回 403。

角色与动作写在 `app.json` 的 `defaultRoles`；平台在服务端再判一次。

### 3. 输入

模板编号、模板要素（如原文名称、原截止日期、新截止日期）、可选的政策出处引用。缺必填要素时位置标「待补」，不编造内容。样例要素使用虚构申报通知，不含内部资料。

### 4. 处理步骤

1. 读取模板目录，按模板生成初稿，缺项写「待补」。
2. 每次保存生成一个可读版本，任一版本可按号读取。
3. 审签通过后文稿定稿；再保存返回 409 `LOCKED`。
4. 政策出处以角标保留，并链接到知识库原文版本。

记录、版本和审签由平台数据底座执行，应用不另建版本库。

### 5. 确认依据

起草人核对要素、待补位置和出处链接；确认人核对正文、版本和引用。模型或 mock 只作参考，最终由人确认。

### 6. 输出

草稿对象含标题、模板、状态、作者、版本列表和出处角标。出处链接指向 `/api/v1/kb/docs/{id}` 的对应版本。定稿后只能另存新稿。

### 7. 验收样本

1. 办理员调用起草接口，初稿缺项为「待补」。
2. 同一草稿保存 3 次后可读取 3 个版本。
3. 定稿后再保存，返回 409 `LOCKED`。
4. 模板不存在返回 404，缺必填要素返回 400，无 operate 权限返回 403。

自动化覆盖在 `tests/test_drafting.py` 与 `tests/test_document_health.py`。

## 润色、比对与批注（#40）

- `POST /drafts/{id}/polish`：返回 `{preview, parts, changed}`，只预览不落版本；采用时走 `PUT /drafts/{id}`，定稿后返回 409 `LOCKED`。`para` 省略时润色全文。
- `POST /compare`：`a`、`b` 可以是 `{id, v}` 或字符串；版本 0 可参与比较。`stats.add/del` 按 UTF-16 代码单元统计，与原型一致。
- `POST /drafts/{id}/comments`、`PATCH /drafts/{id}/comments/{cid}`：新增、回复、解决批注，记录操作者与北京时间。批注单独存为 `document-comment` 记录，定稿后仍可批注；草稿详情的 `comments` 与文稿列表的未解决数都从这里读取。

自动化覆盖在 `tests/test_collaboration.py`。

## 开发说明

在仓库根目录启动平台后执行：

```bash
python3 scripts/check.py --app document
python3 -m pytest -q apps/document/tests
```


## 公文工作台（#228）

- 工作概览汇总待我修改、待我审核、定稿和档案；档案支持标题/起草人搜索、状态筛选及只看本人。待我修改以真实 `authorId` 判断，待我审核以授权与实际审签分配判断。
- 打开已有文稿即可编辑，保存生成新版本；有未保存修改时阻止页面内切换。核查与规则润色展示当前已保存版本，润色先预览再由经办人采用。
- 批注可新增、回复和解决；版本对比直接调用既有差异接口；审核提供通过定稿与带理由退回。定稿禁止保存和规则修正，仍可保留批注讨论。
- `GET /api/apps/document/workbench` 返回 `{items, reviewers, reviews}`，是同一文稿记录与同一审签单的投影。成员来自项目授权查询，不从演示姓名推断 HTTP 账号。
- `PUT /drafts/{id}` 新增可选 `baseVersion`；`POST /drafts/{id}/submit` 新增可选 `version`，均使用详情中的 `versions[].v`。旧调用兼容；工作台必传，过期返回 409 `STALE_VERSION`。`POST /workbench/reviews/{id}` 接收审签单自身的 `{version, decision: approve|reject, comment}`；审签版本不要与文稿展示版本混用。
- 会议转公文可传 `source={app:"meeting", id, version}` 和 `templateId:"T02", inputs:{}`。服务端读取当前用户可见的固定会议定稿记录，要求 `type=meeting`、`minutesStatus=已定稿`、`finalizedVersion=version`，正文取 `data.minutesEdit`。来源保存在文稿 `data.source`，详情返回 `item.source`。客户端附带的来源标题和额外正文不会冒充会议原文。
- HTTP 导出沿用服务端真实 DOCX；离线导出使用 `web/assets/word-export.js` 生成真实 OOXML ZIP，由 `python-docx` 回读测试。未定稿文件标注“草稿”。原始 mock 导出端点仍保留旧契约，页面适配器不再下载伪 `.doc`。
- 新建文稿沿用原四步应用。工作台未扩展多级 OA、电子签章、发文和归档制度，也不把确定性模板与规则润色称为模型创作。

验证：`python3 -m pytest -q apps/document/tests`；`node --test web/tests/contract/document-workbench.test.cjs web/tests/contract/word-export.test.cjs`；`node --test web/tests/e2e/document-workbench.cjs`（需要安装 `web` 的 Playwright 依赖与 Chromium）。浏览器验收已加入 CI；可用 `DOCUMENT_SCREENSHOTS` 指定 1440/1280 截图目录。

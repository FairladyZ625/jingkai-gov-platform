# 企业管理

> 负责人：summerchaserwwz ｜ 关联 Issue：#29 #32 ｜ 场景编号：（台账已交付，走访与诉求见后续 Issue）

四个业务应用之一：健康检查、公开参考资料种子，以及一企一档台账的查询、修改和导入导出。

## 需求七问

### 1. 触发

走访前查阅企业档案，收到企业资料或批量表格时更新台账；外部协作者查看公开企业信息。健康检查供探活。

### 2. 使用者与确认人

经办人（member）可查看与办理；审签领导（leader）可查看、办理与确认；管理员（admin）全部动作；外部协作者（partner）仅可查看和导出脱敏数据。见 app.json defaultRoles。

### 3. 输入

新建企业必填 name。批量导入接受 rows 数组或带字段名表头的 UTF-8 CSV，复合字段使用 JSON。健康路由无需请求体。

### 4. 处理步骤

1. 平台登记并挂载 /api/apps/enterprise。
2. 有 view 的会话可访问 GET /health，以及台账列表、详情和导出。
3. 匿名访问返回 401；缺 view 返回 403（details.app/need）。
4. 有 operate 且非 partner 的用户可新建、修改和导入。应用检查字段和重名，再保存私库原值及 core 脱敏版本。
5. 部署时将环境变量 `JKQ_ENTERPRISE_PRIVATE_DB` 指向仓库外的 SQLite 绝对路径，父目录仅开放给服务账号。备份时一并保留私库和 core 数据。
6. reset_seed 用 data/seed/real/enterprises.json 覆盖 reference:enterprises，仅作参考名单。

### 5. 确认依据

经办人员在详情中核对版本的修改人、修改时间和前后值。批量导入按错误行号和原因修正后可单独重试。健康检查看会话与 view。

### 6. 输出

健康接口返回 {id:"enterprise",status:"ok"}。台账查询返回匹配企业和筛选项；详情展示走访、诉求、文件、待确认建议及历史。导出支持按企业 ID 选择，敏感值打码，可能触发公式的单元格按文本输出。种子键 reference:enterprises。

### 7. 验收样本

sampleadmin 访问 /api/apps/enterprise/health → 200；未登录 → 401；无 view → 403。台账用例见 `apps/enterprise/tests/test_ledger.py`，覆盖中文与多行 CSV、并发重名、权限、历史及千行导入。

## 目录

- 页面入口 `web/index.js`（脚手架占位，业务 UI 后续交付）
- 后端入口 `api/router.py`（健康检查与公开参考资料；台账路由由 `api/ledger.py` 挂载）
- 需求七问即本文件

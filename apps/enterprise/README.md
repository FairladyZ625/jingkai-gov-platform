# 企业管理

> 负责人：summerchaserwwz ｜ 关联 Issue：#29 ｜ 场景编号：（脚手架，后续业务 Issue 补 scenes）

四个业务应用脚手架之一：后端健康路由 + 公开参考资料种子；业务界面与能力在后续 Issue 实现。

## 需求七问

### 1. 触发

经办人维护一企一档、或外部协作者查看公开企业信息时打开。脚手架仅健康检查与公开企业名单种子；台账导入导出见 #32。

### 2. 使用者与确认人

经办人（member）可查看与办理；审签领导（leader）可查看、办理与确认；管理员（admin）全部动作；外部协作者（partner）仅可查看。见 app.json defaultRoles。

### 3. 输入

脚手架阶段无业务表单。后续 #32 将接收企业档案字段与导入文件；当前健康路由无需请求体。

### 4. 处理步骤

1. 平台登记并挂载 /api/apps/enterprise。
2. 有 view 的会话访问 GET /health。
3. 匿名 401；缺 view 403（details.app/need）。
4. reset_seed 用 data/seed/real/enterprises.json 覆盖 reference:enterprises。

### 5. 确认依据

健康检查看会话与 view；公开企业名单仅作参考，正式台账以 #32 业务数据为准。

### 6. 输出

健康接口返回 {id:"enterprise",status:"ok"}；种子键 reference:enterprises。

### 7. 验收样本

sampleadmin 访问 /api/apps/enterprise/health → 200；未登录 → 401；无 view → 403。见 apps/enterprise/tests。

## 目录

- 页面入口 `web/index.js`（脚手架占位，业务 UI 后续交付）
- 后端入口 `api/router.py`
- 需求七问即本文件

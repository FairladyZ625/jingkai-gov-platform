# 公文协作

> 负责人：summerchaserwwz ｜ 关联 Issue：#29 ｜ 场景编号：（脚手架，后续业务 Issue 补 scenes）

四个业务应用脚手架之一：后端健康路由 + 公开参考资料种子；业务界面与能力在后续 Issue 实现。

## 需求七问

### 1. 触发

经办人起草或领导审签公文时打开。脚手架仅健康检查与公开公文参考种子；模板、版本与定稿见 #38。

### 2. 使用者与确认人

经办人（member）可查看与办理；审签领导（leader）可查看、办理与确认；管理员（admin）全部动作。外部协作者默认无本应用授权。见 app.json defaultRoles。

### 3. 输入

脚手架阶段无业务表单。后续 #38 将接收模板选择、正文与定稿动作；当前健康路由无需请求体。

### 4. 处理步骤

1. 平台登记并挂载 /api/apps/document。
2. 有 view 访问 GET /health。
3. 匿名 401；缺 view 403。
4. reset_seed 用 data/seed/real/gongwen.json 覆盖 reference:gongwen。

### 5. 确认依据

健康检查看会话与 view；公开公文样本仅格式参考，正式文稿由 #38 管理。

### 6. 输出

健康接口返回 {id:"document",status:"ok"}；种子键 reference:gongwen。

### 7. 验收样本

sampleadmin → 200；未登录 → 401；无 view → 403。见 apps/document/tests。

## 目录

- 页面入口 `web/index.js`（脚手架占位，业务 UI 后续交付）
- 后端入口 `api/router.py`
- 需求七问即本文件

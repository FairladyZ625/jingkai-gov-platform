# 政策兑现

> 负责人：summerchaserwwz ｜ 关联 Issue：#29 ｜ 场景编号：（脚手架，后续业务 Issue 补 scenes）

四个业务应用脚手架之一：后端健康路由 + 公开参考资料种子；业务界面与能力在后续 Issue 实现。

## 需求七问

### 1. 触发

经办人需要按企业情况核对兑现事项、或领导审看结论时打开。脚手架阶段仅提供健康检查与公开参考资料种子入口；事项库与额度试算见 #30。

### 2. 使用者与确认人

经办人（member）可查看与办理；审签领导（leader）可查看、办理与确认；管理员（admin）具备全部动作；外部协作者（partner）仅可查看。角色与动作写在 app.json 的 defaultRoles。

### 3. 输入

脚手架阶段无业务表单。后续 #30 将接收企业标识、事项筛选条件与画像字段；当前健康路由无需请求体。

### 4. 处理步骤

1. 平台按 app.json 登记应用并挂载 /api/apps/policy。
2. 登录用户携带 view 访问 GET /health，返回 {id,status}。
3. 匿名访问返回 401；缺少 view 返回 403 并带 app/need。
4. reset_seed 用 data/seed/real/rules.json 覆盖本应用参考资料键，保留其他业务数据。

### 5. 确认依据

健康检查以会话与 view 权限为准；种子数据以公开核实资料为准，业务结论须人工确认（#30）。

### 6. 输出

GET /api/apps/policy/health → {id:"policy",status:"ok"}；权限失败返回平台错误体。参考资料键 reference:rules。

### 7. 验收样本

本地：登录 sampleadmin 后 GET /api/apps/policy/health 返回 200；清空 Cookie 后同路径 401；无 view 角色 403。pytest apps/policy 覆盖上述路径与种子重置。

## 目录

- 页面入口 `web/index.js`（脚手架占位，业务 UI 后续交付）
- 后端入口 `api/router.py`
- 需求七问即本文件

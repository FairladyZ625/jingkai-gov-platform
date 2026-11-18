/* =====================================================================
 * 【可改】标签配色表：同一个标签在任何地方都是同一个颜色。
 * 可用色槽（深浅两套已在 assets/theme.css 调好）：
 *   gray blue indigo violet pink red orange amber green teal cyan
 * 用法：应用里调用 ctx.ui.tag('已完成') 或 ctx.ui.tag('通知', 'docType')，
 *       不在表里的新标签会按文字自动分到一个固定色槽（不会每次变）。
 * ===================================================================== */
window.JK_TAGS = {
  /* 状态（全平台通用，优先级最高） */
  status: {
    '待办': 'gray', '草稿': 'gray', '未开始': 'gray', '已停用': 'gray', '已关闭': 'gray', '不满足': 'gray', '已归档': 'gray',
    '进行中': 'blue', '处理中': 'blue', '跟进中': 'blue', '转写中': 'blue', '执行中': 'blue', '审签中': 'blue',
    '待审': 'amber', '待审签': 'amber', '待确认': 'amber', '待核对': 'amber', '待认领': 'amber', '待上架审核': 'amber', '需人工确认': 'amber',
    '已完成': 'green', '已办结': 'green', '已通过': 'green', '已发布': 'green', '已入库': 'green', '可申报': 'green', '已上架': 'green', '在线': 'green', '已解决': 'green', '已签发': 'green',
    '驳回': 'red', '已驳回': 'red', '风险': 'red', '逾期': 'red', '卡住': 'red', '即将到期': 'red', '失败': 'red', '已过期': 'red',
  },
  /* 优先级 */
  priority: { '紧急': 'red', '高': 'red', '中': 'amber', '低': 'gray' },
  /* 角色 */
  role: { '管理员': 'violet', '审签领导': 'amber', '经办人员': 'blue', '外部协作者': 'gray' },
  /* 政策类别 */
  policyCat: {
    '产业发展': 'indigo', '高精尖产业': 'indigo', '科技创新': 'violet', '人才': 'cyan', '人才支持': 'cyan', '数字经济': 'blue', '人工智能': 'blue', '数据要素': 'blue',
    '文化': 'pink', '文化产业': 'pink', '金融': 'amber', '金融支持': 'amber', '企业服务': 'teal', '营商环境': 'teal', '绿色低碳': 'green', '商贸消费': 'orange', '开放合作': 'orange',
  },
  /* 公文文种 */
  docType: { '通知': 'blue', '请示': 'amber', '报告': 'violet', '函': 'cyan', '纪要': 'teal', '方案': 'indigo', '讲话稿': 'pink', '批复': 'orange', '简报': 'green', '公告': 'red' },
  /* 企业标签 */
  entTag: { '高新技术企业': 'violet', '高新': 'violet', '专精特新': 'cyan', '小巨人': 'cyan', '重点企业': 'indigo', '规上企业': 'teal', '上市企业': 'orange', '独角兽': 'pink', '外资': 'amber', '初创': 'green' },
  /* 知识库空间 */
  kbSpace: { '企业档案': 'green', '政策库': 'indigo', '公文范文': 'orange', '会议纪要': 'violet', '部门制度': 'teal', '政策文件': 'indigo', '公文范本': 'orange', '企业档案': 'teal', '内部制度': 'gray', '培训资料': 'cyan', '统计数据': 'blue', '我的资料': 'pink' },
  kbStatus: { '现行有效': 'green', '即将到期': 'amber', '已失效': 'gray', '已更新': 'violet', '申报中': 'blue', '已截止': 'gray', '未找到依据': 'gray', '示例': 'gray', '解析中': 'blue', '待确认': 'amber', '重复': 'gray', '新版本': 'blue', '已入库': 'green', '模拟解析': 'amber' },
  kbKind: { '企业档案': 'green', '政策文件': 'indigo', '政策解读': 'cyan', '通知范文': 'orange', '信息简报': 'blue', '工作报告': 'violet', '会议纪要': 'violet', '机构职责': 'teal', '内部制度': 'gray', '上传资料': 'pink' },
  /* 技能分类 */
  skillCat: { '政策': 'indigo', '企业': 'teal', '会议': 'violet', '公文': 'orange', '知识': 'cyan', '数据': 'blue', '办公': 'gray', '电脑操作': 'amber' },
  /* 模型厂商（模型切换器里的小圆点） */
  provider: { 'DeepSeek': 'blue', '通义千问': 'violet', '文心': 'indigo', 'Kimi': 'gray', '智谱GLM': 'cyan', '豆包': 'orange', 'GPT': 'green', 'Claude': 'amber' },
  /* 识别出的文件类型（对话框拖入文件） */
  fileKind: { '会议录音': 'violet', '会议纪要': 'violet', '公文草稿': 'orange', '政策文件': 'indigo', '企业资料': 'teal', '表格': 'green', '图片': 'pink', '其他': 'gray' },
  /* —— 四个应用的专用分组（apps worker 10:2x 提交） —— */
  policyLevel:  { '可进一步核对': 'green', '待确认': 'amber', '不满足': 'gray' },
  policyWindow: { '申报中': 'green', '本批已结束': 'gray', '窗口待通知': 'amber' },
  policyObj:    { '企业': 'teal', '个人': 'cyan', '其他组织': 'violet' },
  verify:       { '已核实': 'green', '企业自报': 'amber', '预测': 'violet', '待核': 'gray', '统计报表': 'green' },
  alertKind:    { '资质到期': 'red', '久未走访': 'amber', '诉求临期': 'orange' },
  issueStatus:  { '待分派': 'gray', '办理中': 'blue', '待补材料': 'amber', '已办结': 'green' },
  proposal:     { '待确认': 'amber', '已写入': 'green', '已忽略': 'gray' },
  meetStatus:   { '新录音': 'blue', '整理中': 'blue', '已整理': 'green', '仅局方': 'violet' },
  meetType:     { '企业座谈会': 'teal', '局务会': 'violet', '专题推进会': 'indigo' },
  todoStatus:   { '待认领': 'amber', '待确认': 'amber', '已派发': 'green', '已完成': 'green' },
  checkLevel:   { '必须改': 'red', '建议改': 'amber', '提示': 'blue', '通过': 'green' },
  docStatus:    { '草稿': 'gray', '审签中': 'blue', '已定稿': 'green', '已退回': 'red' },
  docGroup:     { '发布政策与安排': 'indigo', '面向企业组织事项': 'teal', '公开结果与回应': 'orange' },
};
/* 应用身份色（侧栏图标、应用页头），与上面的分类色保持一致 */
window.JK_APP_HUES = { chat: 'blue', policy: 'indigo', enterprise: 'teal', meeting: 'violet', document: 'orange', kb: 'cyan', skills: 'pink', computer: 'amber', inbox: 'blue', admin: 'gray' };

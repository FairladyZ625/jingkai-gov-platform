/* =====================================================================
 * 【可改】政策兑现 · 文案与选项。改完刷新页面即可，不用改 app.js。
 * ===================================================================== */
window.JK_APPCFG = window.JK_APPCFG || {};
window.JK_APPCFG.policy = {
  name: '政策兑现',
  summary: '根据企业信息，查找可能适用的政策支持，查看申请条件和原文依据。',
  steps: ['选对象', '核对条件', '试算额度', '政策参考清单'],
  tabs: [['flow', '查找支持'], ['items', '政策支持目录'], ['docs', '政策文件']],
  /* 第 1 步“常用示例”：点一下直接选中（企业 id 来自台账） */
  samples: ['E001', 'E007', 'E005', 'E017'],
  /* 手动描述：对象类型、身份标签、资质 */
  objects: ['企业', '个人', '其他组织'],
  manualTags: ['实体书店', '人工智能', '大模型', '数据', '机器人', '智能网联汽车', '商业', '首店', '服务机构', 'AI原生创业', 'AI人才', '在读学生'],
  licenses: ['出版物经营许可证', '生成式AI备案', '高新技术企业', '专精特新'],
  /* 金额/数量字段：[显示名, 单位, 换算到接口单位的倍数] */
  fields: {
    rent: ['年房租 / 物业费', '万元', 1e4], dataPurchase: ['数据产品采购额', '万元', 1e4], computePurchase: ['算力采购额', '万元', 1e4],
    datasetInvest: ['数据集建设投入', '万元', 1e4], digitalInvest: ['数字化投入', '万元', 1e4], renovation: ['新建 / 改造投入', '万元', 1e4],
    sceneInvest: ['场景项目投入', '万元', 1e4], firstSale: ['首台套合同额', '万元', 1e4], area: ['经营面积', '㎡', 1],
    insurancePremium: ['出口信用保险保费', '万元', 1e4], financingContractAmount: ['当年相关业务合同金额', '万元', 1e4],
    exportAmount: ['出口额', '万元', 1e4],
    employees: ['参保人数', '人', 1], age: ['年龄', '岁', 1], yearsInZone: ['入区经营年限', '年', 1],
  },
  /* 待确认项“填入示例”时用的值（接口单位） */
  sampleFill: { dataPurchase: 300000, computePurchase: 2000000, datasetInvest: 800000, renovation: 600000, digitalInvest: 500000, sceneInvest: 1500000, firstSale: 3000000, area: 500, employees: 30 },
  levels: { ok: ['可进一步核对', 'green'], check: ['待确认', 'amber'], no: ['不满足', 'gray'] },
  windowText: { open: '申报中', ended: '本批已结束', unknown: '窗口待通知' },
  text: {
    pickQ: '为谁查找政策支持？', pickSub: '选择企业或描述情况；筛选范围是当前已收录的政策目录',
    resultEmpty: '没有适用事项', resultEmptyDesc: '检查企业标签和资质是否完整，或换成手动描述',
    viewOnly: '你的角色可以查阅政策与原文，不能进行企业匹配或生成参考清单',
    demoBadge: '示例（无对应原文）',
  },
};

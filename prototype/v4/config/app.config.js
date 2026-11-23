/* =====================================================================
 * 【可改】平台外观与文案（改完刷新页面即可）
 * ===================================================================== */
window.JK_CONFIG = {
  platformName: '经开智能体工作站',
  orgName: '北京经开区 · AI 工作组',
  showDevPlan: false,              // 显示侧栏「开发计划」入口
  defaultTheme: 'light',            // 'dark' | 'light'
  stateKey: 'jk4-state-r1',        // 改这个值 = 所有浏览器数据重新开始
  /* 首页：问候下面的 3 条建议（点一下就让 AI 去办） */
  homeSuggestions: [
    { icon: 'policy', app: 'policy', requires: 'operate', text: '帮我查一下纸鹿二号智驾能申报哪些政策' },
    { icon: 'meeting', app: 'meeting', requires: 'operate', text: '把昨天文化企业座谈会整理成纪要' },
    { icon: 'book', app: 'kb', text: '数据券补贴最高能拿多少？' },
  ],
  /* 登录页“一键登录”的演示账号（正式环境删除这段即可） */
  demoAccounts: [
    { username: 'wangmin', password: 'jk123456', name: '王敏', role: '经办人员', desc: '日常办事：政策、走访、纪要、公文' },
    { username: 'liyang', password: 'jk123456', name: '李阳', role: '审签领导', desc: '审签公文、确认入库、审核技能' },
    { username: 'admin', password: 'admin123', name: '张磊', role: '管理员', desc: '账号、权限、模型、审计' },
    { username: 'hejun', password: 'jk123456', name: '何军', role: '外部协作者', desc: '只看授权内容，敏感字段打码' },
  ],
  /* 输入框占位语 */
  composerPlaceholder: '说一句要办的事，或把文件拖进来…',
  /* AI 操作速度：正常演示 1，一键演示时用 demoSpeed */
  operatorSpeed: 1,
  demoSpeed: 1.6,
  demoReadMs: 2400,                // 未单独编排的结果页沿用片尾字幕的停留；可调整，播放中可随时暂停阅读
  // mock 模式下只选择展示与审计使用的模型，不发网络请求。
  modelRouting: {
    defaultChannel: 'cloud', // 公开请求的自动路由，可切换为 local
    channels: { cloud: 'deepseek-v4.1-flash', local: 'local-qwen-32b' },
    usageBuckets: [['deepseek-v4.1-flash', 34], ['local-qwen-32b', 27], ['qwen4-max', 18], ['glm-5.3', 9], ['kimi-k3.1-pro', 7]],
    transcriptionModel: 'SenseVoice（本地）',
    taskModels: { writing: 'qwen4-max', rules: 'glm-5.3', longText: 'kimi-k3.1-pro' },
    models: [
      { id: 'auto', name: '自动选择', provider: '模型网关', group: '推荐', kind: 'route', desc: '按任务自动路由：敏感数据走本地，写作走旗舰，问答走高速', tags: ['推荐'], enabled: true },
      { id: 'deepseek-v4-pro', name: 'DeepSeek-V4-Pro', provider: '深度求索', group: '国产云端', kind: 'cloud', desc: '复杂推理、政策条件分析', tags: ['推理'], ctx: '1M', enabled: true },
      { id: 'deepseek-v4.1-flash', name: 'DeepSeek-V4.1-Flash', provider: '深度求索', group: '国产云端', kind: 'cloud', desc: '高频问答、信息提取，速度快', tags: ['高速'], ctx: '1M', enabled: true },
      { id: 'qwen4-max', name: '通义千问 Qwen4-Max', provider: '阿里云百炼', group: '国产云端', kind: 'cloud', desc: '旗舰多模态，长文写作与工具调用', tags: ['旗舰', '写作'], ctx: '1M', enabled: true },
      { id: 'qwen3.8-flash', name: '通义千问 Qwen3.8-Flash', provider: '阿里云百炼', group: '国产云端', kind: 'cloud', desc: '低成本日常任务', tags: ['高速'], ctx: '1M', enabled: true },
      { id: 'glm-5.3', name: '智谱 GLM-5.3', provider: '智谱 AI', group: '国产云端', kind: 'cloud', desc: '规则梳理、方案检查', tags: ['推理'], ctx: '1M', enabled: true },
      { id: 'kimi-k3.1-pro', name: 'Kimi K3.1 Pro', provider: '月之暗面', group: '国产云端', kind: 'cloud', desc: '超长文档阅读，政策原文通读', tags: ['长文'], ctx: '1M', enabled: true },
      { id: 'doubao-seed-2', name: '豆包 Seed-2.0', provider: '字节跳动', group: '国产云端', kind: 'cloud', desc: '口语化改写、通知摘要，响应快', tags: ['快速'], ctx: '256K', enabled: true },
      { id: 'ernie-5.5', name: '文心 5.5', provider: '百度智能云', group: '国产云端', kind: 'cloud', desc: '可经“亦智”平台纳管调用', tags: ['亦智'], ctx: '128K', enabled: true },
      { id: 'hunyuan-hy4', name: '腾讯混元 Hy4', provider: '腾讯云', group: '国产云端', kind: 'cloud', desc: '视觉理解、读图', tags: ['读图'], ctx: '1M', enabled: true },
      { id: 'local-qwen-32b', name: 'Qwen3-32B（本地）', provider: '局内机房', group: '本地部署', kind: 'local', desc: '企业台账、未公开公文等敏感数据只走本地', tags: ['数据不出局'], ctx: '128K', enabled: true },
      { id: 'local-deepseek', name: 'DeepSeek 蒸馏版（本地）', provider: '局内机房', group: '本地部署', kind: 'local', desc: '离线兜底', tags: ['数据不出局'], ctx: '64K', enabled: true },
      { id: 'gpt', name: 'GPT 系列', provider: 'OpenAI', group: '海外模型（默认关闭）', kind: 'overseas', desc: '政务数据不出境，默认关闭；管理员可对公开资料开放', tags: ['需审批'], enabled: false },
      { id: 'claude', name: 'Claude 系列', provider: 'Anthropic', group: '海外模型（默认关闭）', kind: 'overseas', desc: '政务数据不出境，默认关闭；管理员可对公开资料开放', tags: ['需审批'], enabled: false },
    ],
    capabilities: [
      { id: 'chat', name: '对话', route: 'auto' }, { id: 'transcribe', name: '语音转写', route: 'FunASR / SenseVoice（本地）' },
      { id: 'embedding', name: '向量检索', route: 'BGE-M3（本地）' }, { id: 'parse', name: '文档解析', route: 'MinerU（本地）' },
      { id: 'vision', name: '读图 / OCR', route: '混元 Hy4' }, { id: 'search', name: '联网搜索', route: 'DeepSeek 搜索（仅公开资料）' },
    ],
  },
  /* 接口：'mock' = 浏览器内模拟后端（mock/ 目录）；'http' = 真实后端（把 baseUrl 指向服务地址即可，界面代码不用改） */
  api: { mode: 'mock', baseUrl: 'http://127.0.0.1:8080', timeoutMs: 20000 },
};

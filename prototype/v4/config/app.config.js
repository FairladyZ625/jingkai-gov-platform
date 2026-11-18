/* =====================================================================
 * 【可改】平台外观与文案（改完刷新页面即可）
 * ===================================================================== */
window.JK_CONFIG = {
  platformName: '经开智能体工作站',
  orgName: '北京经开区 · AI 工作组',
  defaultTheme: 'light',            // 'dark' | 'light'
  stateKey: 'jk4-state-r1',        // 改这个值 = 所有浏览器数据重新开始
  /* 首页：问候下面的 3 条建议（点一下就让 AI 去办） */
  homeSuggestions: [
    { icon: 'policy', app: 'policy', text: '帮我查一下纸鹿二号智驾能申报哪些政策' },
    { icon: 'meeting', app: 'meeting', text: '把昨天文化企业座谈会整理成纪要' },
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
  /* 接口：'mock' = 浏览器内模拟后端（mock/ 目录）；'http' = 真实后端（把 baseUrl 指向服务地址即可，界面代码不用改） */
  api: { mode: 'mock', baseUrl: 'http://127.0.0.1:8080', timeoutMs: 20000 },
};

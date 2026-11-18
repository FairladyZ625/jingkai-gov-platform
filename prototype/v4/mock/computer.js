/* =====================================================================
 * 电脑操作（Computer Use）· 模拟后端
 * 真实后端：受控浏览器（远程桌面 / 无头浏览器）+ 计划器；每一步回传截图、写审计；
 * 提交 / 签章 / 付款 / 登录验证码 一律停下来等人确认（服务端强制，界面无法绕过）。
 * 这里在浏览器里模拟：返回“操作脚本”（每步要打开的页面、要填的值），界面负责把它“演”出来。
 *
 * 【可改】下面 TASKS 是任务模板：步骤名、要填的字段、停在哪里等确认。
 * 申报通知用 data/ 里经开区官网的真实通知（realNotices，带原文链接）；被操作的系统画面是模拟的。
 * ===================================================================== */
(function () {
  const A = window.JKAPI; if (!A) return; const X = A.ext;
  const S = () => X.state();

  /* ---------- 被操作的系统（模拟画面；名称与真实入口一致，便于演示时对照） ---------- */
  const SYSTEMS = [
    { id: 'sso', name: '北京市统一身份认证平台', url: 'https://bjca.beijing.gov.cn/login', kind: '登录', account: '法人账号 · 经办人 王*', allowed: true, lastUsed: '2026-11-12' },
    { id: 'zcdx', name: '经开区政策兑现综合服务平台', url: 'https://zcdx.kfqgw.beijing.gov.cn', kind: '申报', account: '随统一认证登录', allowed: true, lastUsed: '2026-11-12' },
    { id: 'tjzb', name: '统计联网直报平台', url: 'https://lwzb.stats.gov.cn', kind: '填报', account: '企业统计员账号 · 李*', allowed: true, lastUsed: '2026-10-15' },
    { id: 'kfqgw', name: '经开区官网 · 通知公告', url: 'https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/', kind: '公开网站', account: '无需登录', allowed: true, lastUsed: '2026-11-17' },
  ];

  /* ---------- 任务模板 ---------- */
  const TASKS = [
    { id: 'apply', title: '政策申报填表', icon: 'policy', system: 'zcdx', needsEnt: true, desc: '登录申报平台，用台账数据填好申报表', stop: '提交前停下等你确认', keywords: ['申报表', '申报', '填表', '兑现平台'] },
    { id: 'stats', title: '统计月报填报', icon: 'chart', system: 'tjzb', needsEnt: true, desc: '登录直报平台，按台账填本月报表', stop: '提交前停下等你确认', keywords: ['月报', '统计', '直报', '报表'] },
    { id: 'notice', title: '下载通知入知识库', icon: 'download', system: 'kfqgw', needsEnt: false, desc: '到官网找最新申报通知，下载存进知识库', stop: '入库前问你一声', keywords: ['通知', '下载', '官网', '公告', '入库'] },
    { id: 'status', title: '查询办理进度', icon: 'search', system: 'zcdx', needsEnt: true, desc: '登录申报平台，查这家企业的申报进度', stop: '只读，不改任何东西', keywords: ['进度', '状态', '办到哪', '查询'] },
  ];

  const maskPhone = (p) => String(p || '').replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2');
  const maskCode = (c) => String(c || '').replace(/^(.{4}).+(.{4})$/, '$1**********$2');
  const ent = (id) => S().enterprises.find((e) => e.id === id || e.short === id || e.name === id);
  const notices = () => (S().realNotices || []).slice().sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const money = (n) => (n >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, '') + ' 万元' : n + ' 元');

  function enrich(st) {
    st.cuSystems = st.cuSystems || JSON.parse(JSON.stringify(SYSTEMS));
    st.cuRuns = st.cuRuns || [];
    st.cuApps = st.cuApps || [
      { no: 'ZCDX-2026-118204', entId: 'E002', title: '2026年人工智能产业交流活动支持', submitted: '2026-11-12 10:21', status: '形式审查中', next: '预计 11-25 前出结果', by: '陈浩（代填）' },
      { no: 'ZCDX-2026-097311', entId: 'E002', title: '数据券（数据产品采购）支持', submitted: '2026-10-28 15:02', status: '已受理', next: '等待专家评审', by: '企业自行申报' },
      { no: 'ZCDX-2026-086530', entId: 'E001', title: '实体书店成本奖励', submitted: '2026-09-18 09:40', status: '需补正材料', next: '补交房租发票（截止 11-22）', by: '刘翔（代填）' },
      { no: 'ZCDX-2026-071122', entId: 'E005', title: 'AI 创新创业人才支持', submitted: '2026-11-03 16:30', status: '已通过', next: '拨付中', by: '企业自行申报' },
    ];
  }
  A.onLoad(enrich);

  /* ---------- 生成操作脚本 ---------- */
  function loginSteps(e, sysName) {
    return [
      { title: '打开统一身份认证', page: 'login', url: 'https://bjca.beijing.gov.cn/login', ops: [{ op: 'click', sel: 'tab-corp', note: '选“法人登录”' }, { op: 'type', sel: 'code', value: e ? maskCode(e.creditCode) : '', mask: 'code' }, { op: 'type', sel: 'user', value: 'wangmin_jkq', note: '经办人账号（保管箱）' }, { op: 'type', sel: 'pwd', value: '••••••••', mask: 'pwd' }, { op: 'click', sel: 'getotp' }] },
      { title: '输入短信验证码', page: 'login', human: 'otp', ops: [{ op: 'otp', sel: 'otp', note: `验证码已发到法人手机 ${maskPhone(e && e.contacts[0] ? e.contacts[0].phone : '13900000000')}` }, { op: 'click', sel: 'login' }] },
    ];
  }
  function buildScript(task, e, b) {
    const t = TASKS.find((x) => x.id === task); const now = X.now();
    if (task === 'apply') {
      const n = notices().find((x) => x.status === '申报中' && /人工智能|AI/.test(x.title)) || notices()[0];
      const base = Math.max(0, ...Object.values(e.amounts || {})) || 1000000; const ask = Math.min(Math.round(base * 0.3), 3000000);
      const c = e.contacts.find((x) => x.main) || e.contacts[0];
      const fields = [
        ['name', '企业名称', e.name], ['code', '统一社会信用代码', maskCode(e.creditCode), 'code'], ['addr', '注册地址', e.regAddr], ['contact', '联系人', c.name + '（' + c.title + '）'], ['phone', '联系电话', maskPhone(c.phone), 'phone'],
        ['emp', '从业人数', String(e.employees)], ['rev', '上年营业收入（万元）', String(e.revenue.value)], ['proj', '项目名称', `${e.short}2026年度${/汽车|智驾/.test(e.industry) ? '智能网联技术交流活动' : '人工智能技术交流活动'}`], ['amount', '申请支持金额（元）', String(ask), null, 'AI 估算，请核对'],
      ];
      const open = notices().filter((x) => x.status === '申报中' && x !== n).slice(0, 3);
      return { notice: n, openItems: [n, ...open], fields, steps: [
        ...loginSteps(e),
        { title: '找到申报事项', page: 'portal', url: 'https://zcdx.kfqgw.beijing.gov.cn/portal', ops: [{ op: 'read', note: `“申报中”事项 ${notices().filter((x) => x.status === '申报中').length} 个` }, { op: 'click', sel: 'apply-0', note: n.title.replace(/^.*关于开展/, '').replace(/的通知$/, '') }] },
        { title: '填写企业信息', page: 'form', url: 'https://zcdx.kfqgw.beijing.gov.cn/apply/form', ops: fields.slice(0, 7).map(([k, l, v, m]) => ({ op: 'type', sel: k, value: v, mask: m, note: l })) },
        { title: '填写申报内容', page: 'form', ops: [...fields.slice(7).map(([k, l, v, m, hint]) => ({ op: 'type', sel: k, value: v, mask: m, note: hint || l })), { op: 'upload', sel: 'up-0', value: '营业执照.pdf' }, { op: 'upload', sel: 'up-1', value: '活动方案.docx' }, { op: 'check', sel: 'promise', note: '勾选信用承诺' }] },
        { title: '停在提交前', page: 'form', human: 'gate', ops: [{ op: 'gate', sel: 'submit', kind: '提交', note: '提交申报（电子签章）需要你确认' }] },
        { title: '提交并拿到回执', page: 'receipt', url: 'https://zcdx.kfqgw.beijing.gov.cn/apply/receipt', ops: [{ op: 'read', note: '保存受理回执' }] },
      ] };
    }
    if (task === 'stats') {
      const rev = Math.round(e.revenue.value / 12 * (0.92 + (e.employees % 7) / 50));
      const fields = [['period', '报告期', b.month || '2026 年 10 月'], ['revm', '本月营业收入（万元）', String(rev)], ['revy', '本年累计营业收入（万元）', String(rev * 10)], ['emp', '期末从业人员（人）', String(e.employees)], ['wage', '本月应付职工薪酬（万元）', String(Math.round(e.employees * 1.6))], ['rd', '本月研发费用（万元）', String(Math.round(rev * 0.06))]];
      return { fields, steps: [
        ...loginSteps(e),
        { title: '打开本月报表', page: 'stats', url: 'https://lwzb.stats.gov.cn/report/B204-1', ops: [{ op: 'read', note: '找到待填报表 B204-1' }] },
        { title: '按台账填数', page: 'stats', ops: fields.map(([k, l, v]) => ({ op: 'type', sel: k, value: v, note: l })) },
        { title: '数据审核', page: 'stats', ops: [{ op: 'click', sel: 'verify', note: '运行平台审核：0 错误 1 提示' }] },
        { title: '停在上报前', page: 'stats', human: 'gate', ops: [{ op: 'gate', sel: 'submit', kind: '上报', note: '报表提交后需联系统计局才能修改' }] },
        { title: '提交并截图留档', page: 'stats-ok', ops: [{ op: 'read', note: '已上报' }] },
      ] };
    }
    if (task === 'notice') {
      const list = notices().slice(0, 8); const n = list.find((x) => x.status === '申报中') || list[0];
      return { notices: list, notice: n, steps: [
        { title: '打开官网通知公告', page: 'nlist', url: 'https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/', ops: [{ op: 'read', note: `最新 ${list.length} 条` }] },
        { title: '找到最新申报通知', page: 'nlist', ops: [{ op: 'click', sel: 'n-' + list.indexOf(n), note: n.title.replace(/^.*关于/, '关于').slice(0, 26) }] },
        { title: '读通知要点', page: 'ndetail', url: n.url, ops: [{ op: 'read', note: n.window ? `申报时间 ${n.window.start} 至 ${n.window.end}` : '以通知为准' }] },
        { title: '下载原文', page: 'ndetail', ops: [{ op: 'download', sel: 'att', value: n.title.slice(0, 30) + '.html' }] },
        { title: '存进知识库', page: 'ndetail', human: 'import', ops: [{ op: 'kb', note: '存入知识库「政策库」' }] },
      ] };
    }
    if (task === 'status') {
      const apps = S().cuApps.filter((x) => !e || x.entId === e.id);
      return { apps, steps: [
        ...loginSteps(e),
        { title: '打开“我的申报”', page: 'mine', url: 'https://zcdx.kfqgw.beijing.gov.cn/my/applications', ops: [{ op: 'read', note: `共 ${apps.length} 条` }] },
        { title: '读取办理状态', page: 'mine', ops: apps.map((x, i) => ({ op: 'hl', sel: 'row-' + i, note: `${x.title.slice(0, 12)}：${x.status}` })) },
      ] };
    }
    return null;
  }

  /* ---------- 路由 ---------- */
  const need = (a) => { if (!X.can('computer', a)) X.err(403, 'FORBIDDEN', '当前角色没有“电脑操作”权限'); };
  const run = (id) => { const r = S().cuRuns.find((x) => x.id === id); if (!r) X.err(404, 'NOT_FOUND', '任务不存在'); return r; };
  const brief = (r) => ({ ...r, shots: undefined, shotCount: (r.shots || []).filter(Boolean).length });

  X.on('GET', '/api/apps/computer/tasks', () => { need('view'); return { items: TASKS, systems: S().cuSystems }; });
  X.on('PATCH', '/api/apps/computer/systems/:id', (b, p) => { need('operate'); const s = S().cuSystems.find((x) => x.id === p.id); if (!s) X.err(404, 'NOT_FOUND', '系统不存在'); s.allowed = !!b.allowed; X.audit('电脑操作', `${s.allowed ? '允许' : '停止'} AI 使用 ${s.name} 账号`); return { item: s }; });
  X.on('POST', '/api/apps/computer/match', (b) => { const t = String(b.text || ''); let best = null, sc = 0; TASKS.forEach((x) => { const s = x.keywords.filter((k) => t.includes(k)).length; if (s > sc) { sc = s; best = x; } }); const e = S().enterprises.find((x) => t.includes(x.short) || t.includes(x.name)); return { task: best, entId: e ? e.id : null }; });
  X.on('GET', '/api/apps/computer/runs', () => { need('view'); return { items: S().cuRuns.map(brief) }; });
  X.on('GET', '/api/apps/computer/runs/:id', (b, p) => { need('view'); return { item: run(p.id) }; });
  X.on('POST', '/api/apps/computer/runs', (b) => {
    need('operate');
    const t = TASKS.find((x) => x.id === b.task); if (!t) X.err(404, 'NOT_FOUND', '没有这个任务模板');
    const sys = S().cuSystems.find((x) => x.id === t.system); if (!sys.allowed) X.err(403, 'NOT_ALLOWED', `已停止 AI 使用「${sys.name}」账号，可在“系统授权”里打开`);
    const e = b.ent ? ent(b.ent) : null; if (t.needsEnt && !e) X.err(422, 'NEED_ENT', '先选一家企业');
    const sc = buildScript(t.id, e, b);
    const r = { id: X.nid('CU'), task: t.id, title: t.title + (e ? ' · ' + e.short : ''), ent: e ? { id: e.id, short: e.short } : null, system: { name: sys.name, url: sys.url }, from: b.from || '', status: 'running', step: 0, created: X.now(), by: X.me().name, log: [], shots: [], result: null, ...sc };
    S().cuRuns.unshift(r); if (S().cuRuns.length > 10) S().cuRuns.length = 10;
    X.audit('电脑操作', `开始任务 · ${r.title}（${sys.name}）`);
    return { item: r };
  });
  /* 每完成一步回报一次：写日志 + 审计 + 留存截图（敏感字段界面已打码） */
  X.on('PATCH', '/api/apps/computer/runs/:id', (b, p) => {
    const r = run(p.id);
    if (b.step != null) r.step = b.step;
    if (b.status) r.status = b.status;
    if (b.log) { r.log.push({ at: X.now().slice(11), text: b.log, who: b.who || 'AI' }); X.audit('电脑操作', `${r.title} · ${b.log}`.slice(0, 60)); }
    if (b.shot != null && b.shotIdx != null) { r.shots[b.shotIdx] = b.shot; }
    return { item: brief(r) };
  });
  /* 人工确认点：提交 / 签章 / 付款 / 入库 */
  X.on('POST', '/api/apps/computer/runs/:id/confirm', (b, p) => {
    const r = run(p.id); need('operate');
    if (b.decision !== 'approve') { r.status = 'draft'; r.log.push({ at: X.now().slice(11), text: '你选择先不提交，已在系统里暂存', who: X.me().name }); X.audit('电脑操作', `${r.title} · 人工决定暂存，未提交`); return { item: brief(r) }; }
    if (r.task === 'apply') { const no = 'ZCDX-2026-' + String(120000 + Math.floor(Math.random() * 9000)); r.result = { no, at: X.now() }; S().cuApps.unshift({ no, entId: r.ent.id, title: r.notice.title.replace(/^.*关于开展/, '').replace(/申报的通知$/, '').replace(/的通知$/, ''), submitted: X.now(), status: '已提交', next: '等待形式审查', by: X.me().name + '（AI 代填，人工确认提交）' }); }
    if (r.task === 'stats') r.result = { no: 'B204-1 · ' + ((r.fields || [])[0] || [])[2], at: X.now() };
    r.log.push({ at: X.now().slice(11), text: `你已确认${b.kind || '提交'}`, who: X.me().name });
    X.audit('电脑操作', `${r.title} · ${X.me().name} 人工确认${b.kind || '提交'}`);
    return { item: brief(r) };
  });
})();

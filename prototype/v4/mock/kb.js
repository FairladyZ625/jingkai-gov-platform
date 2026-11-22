/* =====================================================================
 * 知识库 · 模拟后端（mock 模式加载；http 模式由真实后端实现同名接口：haiknow 知识库 + MinerU 解析 + 向量/BM25 混合检索）
 * 本文件是"浏览器里的真后端"：真实切片、真实检索（BM25 + 中文二元切词 + 同义词扩展）、真实问答拼装（只摘原文、带出处）。
 *   种子：window.JK_REAL_KB（官网真实文件 189 份）+ 会议纪要/部门制度示例（标"示例"）
 *   持久化：只把用户新增/修改的部分存进 localStorage（S.kb），种子每次从 data/ 读，避免撑爆存储
 * 【可改】SPACES（空间与可见角色）、SYN（同义词）、TAG_RULES（自动标签）、阈值 ASK_MIN
 * ===================================================================== */
(function () {
  const A = window.JKAPI; if (!A) return;
  const X = A.ext;
  const TODAY = (window.JK_DATA && window.JK_DATA.today) || '2026-11-18';

  /* ---------- 【可改】空间：名称、颜色由 tags.js kbSpace 决定；roles = 哪些角色能看 ---------- */
  const SPACES = [
    { id: 'policy', name: '政策库', icon: 'policy', desc: '经开区现行政策原文与官方解读', roles: ['admin', 'leader', 'member', 'partner'] },
    { id: 'template', name: '申报通知', icon: 'doc', desc: '官网申报通知、工作动态与报告', roles: ['admin', 'leader', 'member'] },
    { id: 'minutes', name: '会议纪要', icon: 'meeting', desc: '局务会、座谈会、推进会纪要', roles: ['admin', 'leader', 'member'] },
    { id: 'rules', name: '机构职责', icon: 'shield', desc: '官网机构职责与示例工作规程', roles: ['admin', 'leader', 'member'] },
    { id: 'enterprise', name: '企业档案', icon: 'building', desc: '一企一档、走访记录、企业诉求（含企业信息，外部协作者不可见）', roles: ['admin', 'leader', 'member'], sensitive: true },
  ];
  /* ---------- 【可改】同义词：任一词出现，检索时自动带上同组其它词 ---------- */
  const SYN = [
    ['补贴', '资助', '奖励', '支持', '补助', '扶持'], ['房租', '租金', '房屋租赁', '物业费'], ['数据券', '数据交易', '采购数据', '数据产品'],
    ['AI', '人工智能', '大模型', '智能体'], ['机器人', '具身智能', '人形机器人'], ['小巨人', '专精特新'], ['书店', '实体书店', '出版物'],
    ['汽车', '智能网联', '自动驾驶', '新能源汽车'], ['人才', '引才', '亦城人才', '人才十条'], ['上市', 'IPO', '群雁计划'], ['贷款', '融资', '信贷', '风险补偿'],
    ['截止', '申报时间', '申报期', '截至', '期限', '时限'], ['最高', '不超过', '封顶', '上限'], ['算力', '智算', '算力券'], ['医药', '生物医药', '创新药', '医疗器械'],
    ['芯片', '集成电路', '半导体'], ['绿色', '低碳', '节能', '碳'], ['外贸', '进出口', '出海', '跨境'], ['孵化器', '孵化', '众创空间'],
    ['电话', '联系方式', '咨询'], ['延期', '延长', '顺延', '调整', '变更'], ['条件', '要求', '申报条件', '适用对象'], ['材料', '申报材料', '附件'], ['职责', '主要职责', '负责'],
  ];
  const TAG_RULES = [
    ['数据要素', /数据(券|产业|要素|交易|集|流通)/], ['人工智能', /人工智能|AI|大模型|智能体|词元/], ['机器人', /机器人|具身/], ['生物医药', /医药|生物|医疗器械|脑机/],
    ['汽车', /汽车|智能网联|自动驾驶/], ['集成电路', /集成电路|芯片|信创/], ['人才', /人才/], ['金融', /金融|上市|融资|贷款|基金/], ['文化', /文化|书店|阅读|电竞|游戏/],
    ['绿色低碳', /绿色|低碳|节能|碳排/], ['开放外贸', /外贸|外商|出海|保税|跨境/], ['科技创新', /科技创新|研发|孵化|揭榜/], ['未来产业', /6G|量子|XR|未来能源|新材料|原子级|空天|航天/],
    ['申报通知', /申报.{0,6}通知|申报时间|申报期/], ['含金额', /\d+(\.\d+)?\s*(万元|亿元)/],
  ];
  const ASK_MIN = 6;
  const SEARCH_MIN = 3, SEARCH_REL = 0.2, SEARCH_COV = 0.45; // 搜索：低于 3 分、或不到第一名 30% 的弱命中不返回   // 问答最低相关分；低于它就如实说"没找到"

  /* ===================== 文本工具 ===================== */
  const norm = (s) => String(s || '').replace(/\r/g, '').replace(/[ \t\u3000\u00a0]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
  const CJK = /[\u4e00-\u9fff]/;
  function tokens(s) {
    const out = []; const t = String(s || '').toLowerCase();
    const re = /[\u4e00-\u9fff]+|[a-z0-9]+(?:\.[0-9]+)?/g; let m;
    while ((m = re.exec(t))) { const w = m[0];
      if (CJK.test(w)) { if (w.length === 1) out.push(w); for (let i = 0; i < w.length - 1; i++) out.push(w.substr(i, 2)); }
      else if (w.length > 1 || /\d/.test(w)) out.push(w); }
    return out;
  }
  const STOP = new Set(['的是', '是什', '什么', '多少', '怎么', '哪些', '有没', '没有', '可以', '能不', '不能', '一下', '我们', '请问', '告诉', '关于', '知识', '识库', '帮我', '查一', '里有', '库里', '有关', '吗', '呢', '的', '了', '有', '是', '在', '和', '与', '及', '能', '拿', '查']);
  const STOP_PHRASE = ['多长时间', '多久', '几天', '几号', '吗', '呢', '知识库里', '知识库', '有没有', '是什么', '什么时候', '什么', '怎么样', '怎么', '多少钱', '多少', '哪些', '最高', '能拿', '可以', '能不能', '是否', '请问', '帮我', '查一下', '一下', '关于', '有关', '相关', '政策', '补贴', '奖励', '支持', '申报', '负责', '规定', '文件', '我们', '告诉我', '的', '了', '吗', '呢', '么', '有', '在', '和', '与', '及', '能', '拿', '是', '里', '对', '给', '要', '？', '?'];
  function qTokens(q) {
    q = String(q || ''); const lq = q.toLowerCase();
    const base = [...new Set(tokens(q).filter((t) => !STOP.has(t)))];
    const extra = []; const groups = SYN.filter((g) => g.some((w) => lq.includes(w.toLowerCase())));
    groups.forEach((g) => g.forEach((w) => tokens(w).forEach((t) => extra.push(t))));
    let core = lq; STOP_PHRASE.forEach((p) => { core = core.split(p).join(' '); });
    const units = [...new Set(tokens(core))].filter((t) => t.length > 1).map((t) => { const alt = new Set([t]); groups.forEach((g) => { if (g.some((w) => w.toLowerCase().includes(t))) g.forEach((w) => tokens(w).forEach((x) => alt.add(x))); }); return [...alt]; });
    return { base, extra: [...new Set(extra.filter((t) => !base.includes(t) && !STOP.has(t)))], units };
  }
  function autoTags(title, text) { const s = title + '\n' + String(text).slice(0, 4000); return TAG_RULES.filter(([, re]) => re.test(s)).map(([t]) => t).slice(0, 5); }
  function statusOf(d) {
    if (d.replacedBy) return '已更新';
    if (d.space === 'enterprise') return '';
    if (d.space === 'template' || d.space === 'minutes') { if (!d.expire) return ''; return d.expire < TODAY ? '已截止' : '申报中'; }
    if (d.status === '已失效') return '已失效';
    if (d.expire && d.expire < TODAY) return '已失效';
    if (d.expire) { const days = (Date.parse(d.expire) - Date.parse(TODAY)) / 864e5; if (days <= 150) return '即将到期'; }
    return d.status && d.status !== '即将到期' ? d.status : (d.expire ? '现行有效' : '现行有效');
  }
  const HEAD = /^\s*((第[一二三四五六七八九十百]+[条章节])|([一二三四五六七八九十]+、)|([（(][一二三四五六七八九十]+[)）])|(\d{1,2}[\.．、](?!\d)))/;
  /* 切片：按段落合并到 120–360 字，记录在原文中的起止位置（点出处可精确高亮） */
  function chunk(text) {
    const out = []; let pos = 0; let cur = null; let head = '';
    text.split('\n').forEach((line) => {
      const start = text.indexOf(line, pos); pos = start + line.length;
      if (!line.trim()) return;
      if (HEAD.test(line) && line.length <= 60) head = line.trim().slice(0, 30);
      if (cur && (cur.end - cur.start + line.length > 360 || (HEAD.test(line) && cur.end - cur.start > 120))) { out.push(cur); cur = null; }
      if (!cur) cur = { start, end: pos, head };
      else cur.end = pos;
    });
    if (cur) out.push(cur);
    return out.map((c, i) => ({ i, start: c.start, end: c.end, head: c.head, text: text.slice(c.start, c.end) }));
  }

  /* ===================== 索引（BM25） ===================== */
  let DOCS = [];        // 全部文档（种子 + 用户）
  let CH = [];          // 全部切片 {doc, i, start, end, text, tf:Map, len}
  let DF = new Map(); let AVG = 1;
  function indexDoc(d) {
    d.text = norm(d.text); d.chunks = chunk(d.text); d.tags = d.tags && d.tags.length ? d.tags : autoTags(d.title, d.text);
    const tt = tokens(d.title + ' ' + (d.docNo || ''));
    d._t = new Set(tt);
    d.chunks.forEach((c) => { const tk = tokens((c.head ? c.head + ' ' : '') + c.text); const tf = new Map(); tk.forEach((t) => tf.set(t, (tf.get(t) || 0) + 1)); CH.push({ doc: d, i: c.i, tf, len: tk.length || 1 }); });
  }
  function rebuild() {
    CH = []; DF = new Map();
    DOCS.forEach(indexDoc);
    CH.forEach((c) => c.tf.forEach((_, t) => DF.set(t, (DF.get(t) || 0) + 1)));
    AVG = CH.reduce((s, c) => s + c.len, 0) / (CH.length || 1);
  }
  function bm25(c, toks, w) {
    const N = CH.length, k1 = 1.4, b = 0.72; let s = 0;
    toks.forEach((t) => { const f = c.tf.get(t); if (!f) return; const df = DF.get(t) || 0; const idf = Math.log(1 + (N - df + 0.5) / (df + 0.5)); s += w * idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * c.len / AVG)); });
    return s;
  }

  /* ===================== 种子 ===================== */
  function seed() {
    const R = (window.JK_REAL_KB && window.JK_REAL_KB.docs) || [];
    const docs = R.map((d) => Object.assign({ source: '官网', version: 1, uploadedBy: '系统（官网同步）', addedAt: '2026-11-18' }, d));
    const D = window.JK_DATA || {};
    (D.meetings || []).forEach((m) => {
      const r = (D.meetingResults || {})[m.id]; if (!r) return;
      const lines = [`会议：${m.title}`, `时间：${m.date}`, `参会：${(m.participants || []).join('、') || '见签到表'}`, '一、议题与结论'];
      (r.topics || []).forEach((t, i) => lines.push(`${i + 1}.${t.t}。背景：${t.bg}。意见：${(t.views || []).join('；')}。结论：${t.decision}。`));
      lines.push('二、待办事项'); (r.todos || []).forEach((t, i) => lines.push(`${i + 1}.${t.task}（责任人：${t.owner}，完成时限：${t.due}，交付：${t.deliverable}）`));
      docs.push({ id: 'KB-M' + m.id, space: 'minutes', kind: '会议纪要', title: m.title + ' 纪要', org: '产业促进局', docNo: '', date: m.date.slice(0, 10), expire: '', status: '现行有效', url: '', example: true, source: '会议记录', version: 1, uploadedBy: '会议记录应用', addedAt: m.date.slice(0, 10), text: lines.join('\n') });
    });
    // 企业档案：由企业管理数据生成（企业均为虚构示例）；手机号中间四位打码
    const mask = (x) => String(x || '').replace(/(1\d{2})\d{4}(\d{4})/g, '$1****$2');
    (D.enterprises || []).forEach((e) => {
      const vs = (D.visits || []).filter((v) => v.entId === e.id); const is = (D.issues || []).filter((x) => x.entId === e.id);
      const L = [`企业名称：${e.name}`, `统一社会信用代码：${e.creditCode || '—'}`, `行业：${e.industry || '—'}；规模：${e.scale || '—'}；标签：${(e.tags || []).join('、')}`,
        `资质：${(e.license || []).join('、') || '无'}；在区年限：${e.yearsInZone || '—'} 年；员工：${e.employees || '—'} 人`,
        e.revenue ? `营业收入：${e.revenue.value}${e.revenue.unit}（${e.revenue.period}，${e.revenue.verify || e.revenue.source || ''}）` : '',
        `主营：${e.products || '—'}`, `注册地址：${e.regAddr || '—'}`, `服务专员：${e.servicer || '—'}；最近走访：${e.lastVisit || '—'}`,
        (e.qualifications || []).length ? '资质有效期：' + e.qualifications.map((q) => `${q.name}至${q.validTo}`).join('；') : '',
        vs.length ? '一、走访记录' : '', ...vs.map((v, i) => `${i + 1}.${v.date} ${v.type}（${v.staff}）：${mask(v.notes)}`),
        is.length ? '二、企业诉求' : '', ...is.map((x, i) => `${i + 1}.${x.title}（${x.status}，责任人${x.owner}，时限${x.due}）。下一步：${x.next || '—'}`)].filter(Boolean);
      docs.push({ id: 'KB-E' + e.id, space: 'enterprise', kind: '企业档案', title: `${e.short || e.name} · 示例企业档案`, org: e.servicer ? '企业服务处' : '', docNo: '', date: e.lastVisit || '2026-11-18', expire: '', status: '', url: '', example: true, source: '企业管理', version: 1, uploadedBy: '企业管理应用', addedAt: '2026-11-18', entId: e.id, text: L.join('\n') });
    });
    (window.JK_KB_EXAMPLES || []).forEach((d) => docs.push(Object.assign({ example: true, source: '示例', version: 1, uploadedBy: '示例', status: '现行有效' }, d)));
    return docs;
  }
  function state() { const S = X.state(); S.kb = S.kb || { added: [], removed: [], edits: {}, log: [] }; return S.kb; }
  function load() {
    const K = state();
    DOCS = seed().filter((d) => !K.removed.includes(d.id)).concat(K.added.map((d) => Object.assign({}, d)));
    DOCS.forEach((d) => { const e = K.edits[d.id]; if (e) Object.assign(d, e); });
    rebuild();
  }

  /* ===================== 权限 ===================== */
  const roleId = () => { const u = X.me(); return u ? u.role : 'member'; };
  const masked = () => { try { return !!((X.roleOf && X.roleOf()) || {}).mask; } catch (e) { return false; } };
  // 含企业信息的空间（sensitive）对打码角色（外部协作者）始终不可见，管理员也不能放开
  const visSpaces = () => { const K = state(); return SPACES.filter((s) => !(s.sensitive && masked()) && ((K.spaceRoles || {})[s.id] || s.roles).includes(roleId())).map((s) => s.id); };
  const canSee = (d) => visSpaces().includes(d.space);
  const spaceName = (id) => (SPACES.find((s) => s.id === id) || {}).name || id;

  /* ===================== 检索 ===================== */
  function snippetOf(d, ci, q) {
    const c = d.chunks[ci]; if (!c) return d.text.slice(0, 90);
    const s = c.text.replace(/\n/g, ' ');
    const { base } = qTokens(q || ''); let at = -1;
    for (const t of base) { const k = s.indexOf(t); if (k >= 0 && (at < 0 || k < at)) at = k; }
    const from = Math.max(0, (at < 0 ? 0 : at) - 30); return (from ? '…' : '') + s.slice(from, from + 110) + (from + 110 < s.length ? '…' : '');
  }
  const pub = (d, extra) => Object.assign({ id: d.id, title: d.title, space: d.space, spaceName: spaceName(d.space), kind: d.kind, status: statusOf(d), tags: d.tags, real: !!d.real, example: !!d.example,
    source: { org: d.org, date: d.date, url: d.url || '', docNo: d.docNo || '' }, expire: d.expire || '', version: d.version || 1, chunks: d.chunks.length, from: d.source }, extra || {});
  function passFilters(d, f) {
    if (!f) return true;
    if (f.space && f.space !== 'all' && d.space !== f.space) return false;
    if (f.kind && d.kind !== f.kind) return false;
    if (f.status && statusOf(d) !== f.status) return false;
    if (f.org && !(d.org || '').includes(f.org)) return false;
    if (f.year && String(d.date || '').slice(0, 4) !== String(f.year)) return false;
    if (f.tag && !(d.tags || []).includes(f.tag)) return false;
    if (f.validOnly && /已失效|已更新/.test(statusOf(d))) return false;
    return true;
  }
  const citationKey = d => d.id + '@v' + (d.version || 1);
  function rankChunks(q, filters, scope) {
    const { base, extra } = qTokens(q);
    if (!base.length && !extra.length) return { list: [], base, extra };
    const list = [];
    CH.forEach((c) => {
      if (!canSee(c.doc) || !passFilters(c.doc, filters) || (scope != null && citationKey(c.doc) !== scope)) return;
      let s = bm25(c, base, 1) + bm25(c, extra, 0.45);
      if (!s) return;
      const th = base.filter((t) => c.doc._t.has(t)).length; s += th * 2.5;      // 标题命中加分
      const st = statusOf(c.doc); if (st === '已失效' || st === '已更新') s *= 0.6;  // 失效/旧版降权，但仍可查到
      list.push({ c, s });
    });
    list.sort((a, b) => b.s - a.s);
    return { list, base, extra, units: qTokens(q).units };
  }
  function search(q, opts) {
    opts = opts || {}; const limit = opts.limit || 8; const f = Object.assign({}, opts.filters || {}, opts.space ? { space: opts.space } : {});
    q = String(q || '').trim();
    if (!q) { // 无关键词：按时间列出（用于"全部资料"列表）
      const all = DOCS.filter((d) => canSee(d) && passFilters(d, f) && (opts.scope == null || citationKey(d) === opts.scope)).sort((a, b) => String(b.date).localeCompare(String(a.date)));
      return { hits: all.slice(0, opts.limit || 200).map((d) => pub(d, { snippet: d.text.slice(0, 90).replace(/\n/g, ' '), score: 0 })), total: all.length, facets: facets(all) };
    }
    const { list, base } = rankChunks(q, f, opts.scope); let units = qTokens(q).units;
    // 按文档聚合：每份资料只出一条（最相关的片段 + 命中片段数）
    const by = new Map();
    list.forEach(({ c, s }) => { const x = by.get(c.doc.id); if (!x) by.set(c.doc.id, { d: c.doc, ci: c.i, s, n: 1, cs: [c] }); else { x.n++; x.cs.push(c); } });
    // 关键词覆盖（按 idf 加权）：只命中“申报/通知”这类常见词、漏掉关键名词的资料降权
    // 两个真实词之间的跨界二元组（如“期限调整”里的“限调”）全库都不存在时不计入覆盖
    const dfu = (alt) => alt.some((t) => DF.get(t)); units = units.filter((alt, i) => dfu(alt) || !(units[i - 1] && units[i + 1] && dfu(units[i - 1]) && dfu(units[i + 1])));
    const N = CH.length; const idf = (t) => Math.log(1 + (N - (DF.get(t) || 0) + 0.5) / ((DF.get(t) || 0) + 0.5));
    const uw = units.map((alt) => Math.max(...[...alt].map(idf), 0)); const W = uw.reduce((a, b) => a + b, 0) || 1;
    const cov = (x) => (units.length ? units.reduce((n, alt, i) => n + (alt.some((t) => x.d._t.has(t) || x.cs.some((c) => c.tf.has(t))) ? uw[i] : 0), 0) / W : 1);
    let docs = [...by.values()].map((x) => { x.cov = cov(x); x.f = x.s * (0.35 + 0.65 * x.cov) * (1 + Math.min(x.n - 1, 4) * 0.04); return x; }).sort((a, b) => b.f - a.f);
    const top = docs.length ? docs[0].f : 0;
    docs = docs.filter((x) => x.f >= SEARCH_MIN && x.f >= top * SEARCH_REL && (!units.length || x.cov >= SEARCH_COV));
    // 搜索已授权后，仅合并有相同来源和完整正文的快照，不能用标题作主键。
    const seen = new Set(); docs = docs.filter(({d}) => {
      const k = d.url ? JSON.stringify([d.url, d.title, d.version, statusOf(d), d.expire, !!d.example, d.space === 'enterprise', d.text]) : citationKey(d);
      if (seen.has(k)) return false; seen.add(k); return true;
    });
    if (opts.sort === 'date') docs.sort((a, b) => String(b.d.date).localeCompare(String(a.d.date)));
    return { hits: docs.slice(0, limit).map((x) => pub(x.d, { chunk: x.ci, snippet: snippetOf(x.d, x.ci, q), score: Math.round(x.f * 10) / 10, hitCount: x.n, coverage: Math.round(x.cov * 100) / 100,
      relatedPassages: x.cs.filter(c => c.i !== x.ci).slice(0, 3).map(c => ({ chunk: c.i, passage: c.i + 1, snippet: x.d.chunks[c.i].text })) })), total: docs.length, terms: base, facets: facets(docs.map((x) => x.d)) };
  }
  function facets(docs) {
    const cnt = (fn) => { const m = {}; docs.forEach((d) => { const k = fn(d); if (k) m[k] = (m[k] || 0) + 1; }); return Object.entries(m).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ k, n })); };
    return { space: cnt((d) => d.space), kind: cnt((d) => d.kind), status: cnt(statusOf), year: cnt((d) => String(d.date || '').slice(0, 4)), org: cnt((d) => (d.org || '').replace(/^北京经济技术开发区|^北京市/, '').slice(0, 12)).slice(0, 8) };
  }

  /* ===================== 问答：只摘原文句子，句末标 [n]，不编造 ===================== */
  const GENERIC = new Set(tokens('政策 支持 企业 申报 措施 办法 规定 文件 有关 相关 关于 补贴 奖励 哪些 什么 最高 时间 多少 怎么 条件 负责 是否 可以 北京 经开区 开发区 经济技术'));
  const durationQuestion = /多久|多长时间|几(?:分钟|小时|天|周|个月)|时长/;
  const upper = '最长|最多|最高|上限|封顶|不(?:得|能)?超过|不多于|以内';
  const lower = '最短|最少|最低|下限|至少|不少于|不低于';
  const timeValue = '(?:\\d+(?:\\.\\d+)?|[零〇一二两三四五六七八九十百千半]+)\\s*(?:分钟|小时|工作日|天|周|个月|年|秒)';
  const topicTerms = s => s.split(/(?:最长|最多|最短|最少|至少)(?:能|可(?:以)?)[\u3400-\u9fff]{0,3}?(?:多久|多长时间)|请问|多长时间|多久|几(?:分钟|小时|天|周|个月)|时长|上限|下限|最长|最多|最短|最少|最高|最低|封顶|补贴|奖励|资助|补助|能拿|是多少钱|多少钱|是多少|多少|(?<=计划)[中里对]|(?<=政策)[中里对]|[的？?，,\s]+/).filter(Boolean);
  // 数值必须和所问的上/下限配对；整句保留“不得续借”等限制。
  function attributeField(q) {
    const time = durationQuestion.test(q);
    const free = q.match(/免费([\u3400-\u9fff]{2,8}?)(?=多久|多长时间|几(?:分钟|小时|天|周|个月)|时长)/);
    if (free) {
      const subject = topicTerms(q.slice(0, free.index).replace(/(?:可以|能够|可)$/, ''));
      const activity = free[1];
      const value = new RegExp('(?:免费' + activity + '|' + activity + '免费)(?:的)?(?:时长|时间|期限)?' +
        '(?:为|是|最长|最多|不超过|不得超过|\\s|[：:])*' + timeValue);
      const accepts = t => {
        const hit = value.exec(t);
        return hit && !/(?:不(?:再|得|可|能|予)?|禁止|取消|非)$/.test(t.slice(0, hit.index));
      };
      return {topics:subject.length ? [...subject, activity] : [], time, accepts, localSubject:true};
    }
    const permission = q.match(/(?:是否可以|是否允许|能否|可不可以|能不能)([\u3400-\u9fff]{2,10})[？?]?$/);
    const bound = new RegExp(upper).test(q) ? upper : new RegExp(lower).test(q) ? lower : '';
    const cost = q.match(/费用(?:怎么|如何)(?:补贴|补助|资助)/);
    const payment = q.match(/(?:缴费|收费)(?:金额|标准)/)?.[0];
    const fee = payment || q.match(/押金|费用|收费/)?.[0];
    if (!permission && !fee && !time && !(bound && /补贴|奖励|补助|资助|金额|多少钱|能拿/.test(q))) return null;
    const value = time ? timeValue : '(?:\\d+(?:\\.\\d+)?|[一二两三四五六七八九十百千]+)\\s*[万亿]?元';
    const amount = new RegExp(bound ? '(?:' + bound + ')(?:为|是|需要|可|支持|补贴|使用|借用|停放|停留|\\s|[：:])*' + value +
      '|' + value + (bound === upper ? '以内' : '以上') : value);
    const subject = permission ? q.slice(0,permission.index) : cost ? q.replace(cost[0],' ') : fee ? q.replace(fee,' ') : q;
    const topics = topicTerms(subject);
    const explicit = permission && new RegExp('(?:允许|可以|可|不得|不能|禁止|不支持|不允许|不可)' + permission[1]);
    const accepts = t => explicit ? explicit.test(t) : cost ?
      t.includes('费用') && /补贴|补助|资助/.test(t) && (amount.test(t) || (!bound && /\d+(?:\.\d+)?\s*[%％]/.test(t))) :
      payment ? /缴费|收费/.test(t) && amount.test(t) :
      fee ? t.includes(fee) && (amount.test(t) || /不收取|免费|免收/.test(t)) :
      amount.test(t) && (time || /奖励|补贴|补助|资助|给予|支持/.test(t));
    return {topics, time, accepts};
  }
  function anchored(terms, title, text, localSubject = false) {
    return terms.every(term => {
      if (text.includes(term) || (!localSubject && title.includes(term))) return true;
      for (let i = Math.max(2,term.length-text.length); i <= Math.min(title.length,term.length-2); i++) {
        if (title.includes(term.slice(0,i)) && text.includes(term.slice(i))) return true;
      }
      return false;
    });
  }
  function attributeAnswer(q, list, notFound) {
    const clauses = q.split(/[，,；;]/);
    const parts = clauses.length <= 6 && clauses.every(s => /多久|多长时间|几(?:分钟|小时|天|周|个月)|多少|什么|哪些/.test(s)) ? clauses : [q];
    const fields = parts.map(attributeField);
    if (!fields[0]) return null;
    const subject = fields[0].topics;
    if (!subject.some(t=>t.length >= 2)) return notFound();
    const byDoc = new Map();
    for (const {c} of list) { // list 已按角色、空间、范围和版本筛选并排序
      const d = c.doc;
      const quotes = byDoc.get(d) || Array(fields.length).fill(null);
      byDoc.set(d, quotes);
      const sentences = d.chunks[c.i].text.split(/(?<=[。！？])|\n/).map(t=>t.trim());
      fields.forEach((field, i) => {
        if (!field || quotes[i]) return;
        const terms = [...new Set([...subject,...field.topics])];
        const text = sentences.find(s => !/\[\d+\]/.test(s) && field.accepts(s) && anchored(terms,d.title,s) &&
          (!field.time || s.split(/[，,；;]/).some(c => field.accepts(c) && (field.localSubject
            ? anchored(terms,d.title,c,true)
            : terms.some(t=>c.includes(t)) || /^(?:每次|单次|一次|时长|时间|期限|借期)?(?:最长|最短|最多|至少|不得超过|不超过)/.test(c.trim())))));
        if (text) quotes[i] = {text,i:c.i};
      });
      if (quotes.every(Boolean)) break;
    }
    const best = [...byDoc].sort((a,b)=>b[1].filter(Boolean).length-a[1].filter(Boolean).length)[0];
    if (!best || !best[1].some(Boolean)) return notFound();
    const [doc, quotes] = best, citations = [];
    const lines = quotes.map((s,i) => {
      if (!s) return parts[i].replace(/是多少|多少|[？?]/g,'').slice(0,40) + '：当前引用原文未找到可核对的说明。';
      const n = citations.length + 1;
      citations.push(pub(doc,{n,snippet:s.text,chunk:s.i,citationId:citationKey(doc)}));
      return '“' + s.text + '”[' + n + ']';
    });
    return {answer:lines.join('\n'),citations,confidence:/已失效|已更新/.test(statusOf(doc))?'low':'mid',source:'extract',routeNote:'本地原文摘录',followups:[]};
  }
  function ask(q, opts) {
    opts = opts || {}; q = String(q || '').trim();
    const f = Object.assign({}, opts.filters || {}, opts.space ? { space: opts.space } : {});
    const { list, base, units } = rankChunks(q, f, opts.scope);
    const top = list[0] ? list[0].s : 0;
    const covered = (c) => { if (!units.length) return 1; return units.filter((alt) => alt.some((t) => c.tf.has(t) || c.doc._t.has(t))).length / units.length; };
    const notFound = () => {
      const near = []; const u = new Set(); list.forEach(({ c }) => { if (!u.has(c.doc.id) && near.length < 3 && covered(c) > 0) { u.add(c.doc.id); near.push(pub(c.doc)); } });
      const msg = `知识库里没有找到能回答“${q.slice(0, 24)}”的原文，我不会凭空编答案。`;
      return { answer: msg + (near.length ? '\n\n可能相关但不足以回答：' + near.map((d) => '《' + d.title.replace(/^《|》$/g, '').slice(0, 24) + '》').join('、') : '') + '\n\n可以把相关资料导入知识库后再问。', confidence: 'none', notFound: true, citations: [],
        message: msg,
        near, suggestions: [{ label: '导入相关资料', action: 'import' }].concat(near.length ? [{ label: `看看《${near[0].title.replace(/^《/, '').slice(0, 14)}…》`, open: near[0].id }] : []) };
    };
    if (opts.scope != null) {
      const doc = DOCS.find(d => canSee(d) && passFilters(d, f) && citationKey(d) === opts.scope);
      if (!doc) return notFound();
      const fields = [
        ['申报期限', /期限|截止|截至|申报时间|受理时间/, t => /申报|申请|受理|提交|报送/.test(t) && /截止|截至|期限为|\d{1,2}月\d{1,2}日.{0,4}(?:前|至)|申报时间为/.test(t) && /\d|工作日|常年|另行通知/.test(t)],
        ['适用对象', /适用对象|适用范围|申报对象|支持对象|谁能申报/, t => /(?:适用于|(?:适用对象|申报对象|支持对象|适用范围)[为是：:])\s*[^\s，。；：:]{2,}/.test(t)],
        ['审签材料', /审签|签章|签批|盖章/, t => /签字|签章|盖章|审签|签批|签署/.test(t) && /材料|申请表|申报表|申请书|承诺书|证明|清单|报告/.test(t) && !/^(?:.{0,5}[、.．])?(?:需要)?审签材料(?:要求|清单)?[：:。]?$/.test(t)],
      ].filter(([, trigger]) => trigger.test(q));
      if (fields.length) {
        const sentences = doc.chunks.flatMap(c => c.text.split(/(?<=[。！？])|\n/).map(t => ({ t: t.trim(), chunk: c.i })));
        const citations = [], numbers = new Map();
        const answer = fields.map(([label, , matches]) => {
          const quotes = new Set();
          for (const s of sentences.filter(({t}) => !/\[\d+\]/.test(t) && matches(t))) {
            if (!numbers.has(s.t)) {
              numbers.set(s.t, citations.length + 1);
              citations.push(pub(doc, { n: numbers.get(s.t), snippet: s.t, chunk: s.chunk, citationId: opts.scope }));
            }
            quotes.add('“' + s.t + '”[' + numbers.get(s.t) + ']');
          }
          return label + '：' + ([...quotes].join('；') || '原文未明确（本次未找到可引用的说明）。');
        }).join('\n');
        return { answer, message: answer, notFound: !citations.length, confidence: !citations.length ? 'none' : /已失效|已更新/.test(statusOf(doc)) ? 'low' : 'mid', citations, followups: [], routeNote: '本地原文摘录' };
      }
    } else if (/(?:这项|这份|上述|该)(?:政策|文件|办法)的|这项[^，。；？的]{1,16}政策的/.test(q)) {
      const msg = '请先选定要追问的政策：搜索政策名称并取得引用后，再问这份原文。';
      return { ...notFound(), answer: msg, message: msg, near: [] };
    }
    const grounded = attributeAnswer(q, list, notFound);
    if (grounded) return grounded;
    const best0 = list.slice(0, 12).reduce((m, x) => Math.max(m, covered(x.c)), 0);
    if (!list.length || top < ASK_MIN || best0 < (units.length >= 3 ? 0.6 : units.length === 2 ? 0.99 : 0.99)) return notFound();
    const wantNum = /多少|最高|金额|比例|几|上限|封顶|补贴|奖励|标准/.test(q), wantDate = /什么时候|截止|几号|时间|期限|哪天|何时|延期/.test(q), wantCond = /条件|要求|谁可以|能不能|是否|符合/.test(q), wantList = /哪些|有什么|都有/.test(q), wantHow = /怎么|如何|支持|扶持/.test(q);
    const uCov = (s) => units.length ? units.filter((alt) => alt.some((t) => s.includes(t))).length / units.length : 0;
    const sScore = (s) => 5 * uCov(s) + base.reduce((n, t) => n + (s.includes(t) ? (GENERIC.has(t) ? 1 : 2.5) : 0), 0)
      + (wantNum ? (/\d+(\.\d+)?\s*(万元|亿元|%|％|元)/.test(s) ? 4 : -2) : 0)
      + (wantDate && /\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日/.test(s) ? 3 + (/至|截止|延长|申报期|前/.test(s) ? 6 : 0) : (wantDate ? -2 : 0))
      + (wantCond && /对|符合|满足|注册|认定|须|应当/.test(s) ? 1.5 : 0) - (s.length > 220 ? 2 : 0) - (/^(为深入|为贯彻|为加快|为进一步|现将|现就|通知如下)/.test(s) ? 4 : 0) + (wantHow && /给予|按照|最高|补贴/.test(s) ? 2.5 : 0);
    // 句子级：在前 14 个切片里挑句子，按文档聚合
    const byDoc = new Map();
    list.slice(0, 14).forEach((x) => {
      if (covered(x.c) < 0.34) return;
      const d = x.c.doc; const ch = d.chunks[x.c.i];
      ch.text.split(/(?<=[。；！？])|\n/).map((t) => t.trim()).filter((t) => t.length > 8).forEach((t) => {
        const sc = sScore(t); if (sc < 2.5) return;
        const e = byDoc.get(d.id) || { d, s: x.s, sents: [] }; e.s = Math.max(e.s, x.s); e.sents.push({ t, sc: sc + x.s / 8, ci: x.c.i }); byDoc.set(d.id, e);
      });
    });
    if (wantDate) byDoc.forEach((e) => { const age = (Date.parse(TODAY) - Date.parse(e.d.date || '2000-01-01')) / 864e5; if (age >= 0 && age < 90) e.s *= 1.35; });
    // 标题里含有问题关键词（非泛词）的文件优先：问“数据券”时《数据产业若干措施》排在《机器人若干措施》前
    byDoc.forEach((e) => { const hit = base.filter((t) => t.length > 1 && !GENERIC.has(t) && String(e.d.title).includes(t)).length; if (hit) e.s *= 1 + Math.min(hit, 3) * 0.12; });
    const applicationDate = wantDate && /申报|受理/.test(q);
    if (applicationDate) {
      // 申报日期常在标题所在片段的下一段；排除只提到“申报”的条文和发文日期。
      for (const [id, e] of byDoc) {
        e.sents = e.d.chunks.flatMap(c => c.text.split(/(?<=[。！？])|\n/).map(t => t.trim())
          .filter(t => /申报|受理|报送|提交/.test(t) && /截止|截至|\d{1,2}月\d{1,2}日.{0,4}(至|前)/.test(t) && /\d/.test(t))
          .map(t => ({ t, ci: c.i, sc: sScore(t) })));
        if (!e.sents.length) byDoc.delete(id);
      }
    }
    const docs = [...byDoc.values()].sort((a, b) =>
      (applicationDate && uCov(b.d.title) - uCov(a.d.title)) ||
      (applicationDate && String(b.d.date || '').localeCompare(String(a.d.date || ''))) || b.s - a.s);
    if (!docs.length) return notFound();
    const topS = docs[0].s; const pick = docs.filter((e, i) => i === 0 || e.s >= topS * 0.55).slice(0, 3);
    const citations = []; const blocks = [];
    const clip = (t) => { if (t.length <= 120) return t; const dm = wantDate && /\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日/.exec(t); const nm = wantNum && /\d+(\.\d+)?\s*(万元|亿元|%|％)/.exec(t);
      const w = base.find((k) => !GENERIC.has(k) && t.includes(k)) || base.find((k) => t.includes(k)); const at = dm ? dm.index : nm ? nm.index : w ? t.indexOf(w) : 0; const i = Math.max(0, at - 40); return (i ? '…' : '') + t.slice(i, i + 115) + '…'; };
    const label = (d) => { const t = d.title.replace(/^《|》$/g, ''); const s = t.length > 24 ? t.slice(0, 24) + '…' : t; return `《${s}》` + (d.docNo ? `（${d.docNo}）` : ''); };
    pick.forEach((e, k) => {
      const seen = new Set(); const srt = e.sents.sort((a, b) => b.sc - a.sc); const bestSc = srt[0].sc;
      const sents = srt.filter((x, j) => { if (seen.has(x.t)) return false; seen.add(x.t); return j === 0 || x.sc >= bestSc * (wantList ? 0.6 : 0.8); }).slice(0, k === 0 ? (wantList ? 3 : 2) : 1);
      const st = statusOf(e.d); const warn = /已失效|已更新/.test(st) ? `（⚠ 该文件${st}）` : '';
      const items = sents.map((x) => { const n = citations.length + 1; const sn = clip(x.t); citations.push({ n, id: e.d.id, citationId: citationKey(e.d), version: e.d.version || 1, title: e.d.title, snippet: x.t.length > 120 ? sn.replace(/^…|…$/g, '') : x.t, chunk: x.ci, space: e.d.space, status: st, source: { org: e.d.org, date: e.d.date, url: e.d.url || '', docNo: e.d.docNo || '' }, real: !!e.d.real, example: !!e.d.example }); return `“${sn}”[${n}]`; });
      blocks.push(k === 0 ? `根据${label(e.d)}${warn}：\n` + items.map((x) => '- ' + x).join('\n') : `- ${label(e.d)}${warn}：${items[0]}`);
    });
    const cov = covered(list[0].c);
    const conf = top > 14 && cov >= 0.75 ? 'high' : top > 9 && cov >= 0.5 ? 'mid' : 'low';
    // 一句话结论（只从首条引用原文里摘数字/日期，不编造）
    let lead = '';
    for (const ct of citations.slice(0, 3)) { const s0 = ct.snippet || ''; const parts = [];
      if (wantNum) { const cap = s0.match(/(单个[^，。；]{0,8})?(年度)?[^，。；]{0,6}(最高|不超过|最多)[^，。；\d]{0,6}\d+(\.\d+)?\s*(万元|亿元|元)/); const ratio = s0.match(/[^，。；]{0,12}\d+(\.\d+)?\s*[%％]/); if (cap) parts.push(cap[0].replace(/^[，。；\s“]+/, '')); if (ratio) parts.push(ratio[0].replace(/^[，。；\s“]+/, '')); }
      else if (wantDate) { const d = s0.match(/\d{4}年\d{1,2}月\d{1,2}日[^，。；]{0,4}(至|—|-|到)[^，。；]{0,4}\d{0,4}年?\d{1,2}月\d{1,2}日|[^，。；]{0,8}(截止|截至)[^，。；]{0,4}\d{1,2}月\d{1,2}日[^，。；]{0,4}/); if (d) { let t = d[0].replace(/^[，。；\s“]+/, ''); const ds = [...t.matchAll(/(\d{4})年(\d{1,2})月(\d{1,2})日/g)].pop(); if (ds) { const iso = ds[1] + '-' + ds[2].padStart(2, '0') + '-' + ds[3].padStart(2, '0'); if (iso < TODAY) t += '（这一批已结束）'; } parts.push(t); } }
      if (parts.length) { lead = '**结论：' + parts.join('；') + '**[' + ct.n + ']\n\n'; break; } }
    const answer = lead + blocks[0] + (blocks.length > 1 ? '\n\n**其他相关**\n' + blocks.slice(1).join('\n') : '') + (conf === 'low' ? '\n\n> 相关度一般，建议点出处核对原文。' : '');
    return { answer, summary: lead ? lead.replace(/\*\*|\[\d+\]|\n/g, '').replace(/^结论：/, '') : '', confidence: conf, citations, followups: suggestFollow(q, citations) };
  }
  function suggestFollow(q, cits) {
    const out = []; const c = cits[0]; if (!c) return out;
    if (!/截止|时间/.test(q)) out.push({ label: '申报什么时候截止？', say: (c.title.slice(0, 12)) + ' 申报时间' });
    if (!/条件/.test(q)) out.push({ label: '申报条件是什么？', say: c.title.slice(0, 12) + ' 申报条件' });
    out.push({ label: '起草一份告知通知', say: `根据《${c.title.slice(0, 20)}》起草一份告知企业的通知` });
    return out.slice(0, 3);
  }

  /* ===================== 导入：预览 → 确认入库 ===================== */
  const hash = (s) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0).toString(36); };
  function jaccard(a, b) { const A1 = new Set(tokens(a)), B1 = new Set(tokens(b)); let i = 0; A1.forEach((t) => { if (B1.has(t)) i++; }); return i / (A1.size + B1.size - i || 1); }
  function guessMeta(name, text) {
    const t = norm(text); const first = t.split('\n').find((l) => l.trim().length >= 6) || name;
    const docNo = (t.match(/[京][^\s，。、]{1,8}〔\d{4}〕\d+号/) || [''])[0];
    let title = name.replace(/\.(txt|md|docx?|pdf|wps|html?)$/i, '').trim();
    if (/^(新建|未命名|粘贴|untitled|网页)/i.test(title) || title.length < 4) title = first.replace(/^#+\s*/, '').slice(0, 40);
    const date = (() => { const m = t.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/); return m ? `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}` : TODAY; })();
    const org = (t.match(/北京经济技术开发区[^\s，。、（]{2,16}(局|委员会|中心|办公室|部)/) || [''])[0];
    const space = /一企一档|企业档案|统一社会信用代码|走访记录/.test(title + t.slice(0, 300)) ? 'enterprise' : /纪要|会议|参会|议题/.test(title + t.slice(0, 300)) ? 'minutes' : /制度|规程|办法（内部）|管理规定|职责|守则/.test(title) ? 'rules' : /通知|简报|报告|请示|函|讲话/.test(title) && !/措施|政策|办法|意见/.test(title) ? 'template' : 'policy';
    const kind = space === 'enterprise' ? '企业档案' : space === 'minutes' ? '会议纪要' : space === 'rules' ? '内部制度' : space === 'template' ? (/简报|动态/.test(title) ? '信息简报' : '通知范文') : (/解读/.test(title) ? '政策解读' : '政策文件');
    const expire = (() => { const m = t.match(/(有效期至|有效期到|自.{0,20}起至)\s*(\d{4})年(\d{1,2})月(\d{1,2})日/); return m ? `${m[2]}-${String(m[3]).padStart(2, '0')}-${String(m[4]).padStart(2, '0')}` : ''; })();
    return { title, docNo, date, org, space, kind, expire };
  }
  function dupCheck(title, docNo, text) {
    const h = hash(norm(text));
    for (const d of DOCS) { if (d._hash === undefined) d._hash = hash(d.text); if (d._hash === h) return { type: 'duplicate', id: d.id, title: d.title }; }
    let best = null;
    for (const d of DOCS) {
      if (d.replacedBy) continue;
      const sameNo = docNo && d.docNo && docNo === d.docNo;
      const sim = jaccard(title, d.title);
      if (sameNo || sim >= 0.62) { const ts = sameNo ? 1 : sim; if (!best || ts > best.sim) best = { type: 'version', id: d.id, title: d.title, sim: Math.round(ts * 100), oldDate: d.date, oldVersion: d.version || 1 }; }
    }
    if (best) {
      const old = DOCS.find((d) => d.id === best.id); best.diffLen = Math.abs((old.text || '').length - norm(text).length);
      if (jaccard(old.text.slice(0, 3000), norm(text).slice(0, 3000)) > 0.97) return { type: 'duplicate', id: old.id, title: old.title };
    }
    return best || { type: 'new' };
  }
  function previewItem(it) {
    const text = norm(it.text || '');
    const base = { key: it.key || X.nid('IMP'), name: it.name, ext: it.ext || '', size: it.size || text.length * 2, from: it.from || '上传', parse: it.parse || (text ? 'real' : 'simulated'), url: it.url || '' };
    if (!text) return Object.assign(base, { ok: false, error: it.error || '没有读到文字内容', stages: { parse: 'fail', chunk: 'wait', tag: 'wait' } });
    const m = Object.assign(guessMeta(it.name || '', text), it.meta || {});
    const ch = chunk(text);
    return Object.assign(base, { ok: true, text, chars: text.length, meta: m, chunks: ch.length, chunkPreview: ch.slice(0, 3).map((c) => ({ head: c.head, text: c.text.slice(0, 120) })),
      tags: autoTags(m.title, text), dup: dupCheck(m.title, m.docNo, text), stages: { parse: 'done', chunk: 'done', tag: 'done' } });
  }
  function commit(items, opts) {
    const K = state(); const me = X.me() || { name: '我' }; const out = [];
    items.forEach((it) => {
      if (!it.ok || it.skip) return;
      if (it.dup && it.dup.type === 'duplicate' && it.decision !== 'new') return;
      const m = it.meta || {}; const id = X.nid('KB-U');
      const d = { id, space: m.space || 'policy', kind: m.kind || '上传资料', title: m.title || it.name, org: m.org || (me.dept || ''), docNo: m.docNo || '', date: m.date || TODAY, expire: m.expire || '', status: '现行有效', url: it.url || '', real: !!it.real, example: !!it.example, source: it.from || '上传', parse: it.parse, version: 1, uploadedBy: me.name, addedAt: X.now(), text: it.text, tags: (it.tags && it.tags.length ? it.tags : null) };
      if (it.dup && it.dup.type === 'version' && it.decision !== 'new') {
        const old = DOCS.find((x) => x.id === it.dup.id);
        if (old) { d.version = (old.version || 1) + 1; d.prev = old.id; d.space = old.space; d.kind = old.kind; d.docNo = d.docNo || old.docNo; d.org = d.org || old.org; d.url = d.url || old.url;
          K.edits[old.id] = Object.assign(K.edits[old.id] || {}, { replacedBy: id, replacedAt: X.now() }); }
      }
      K.added.unshift(d); out.push(d);
    });
    K.log.unshift({ at: X.now(), by: me.name, n: out.length, from: (opts && opts.from) || '上传' }); K.log = K.log.slice(0, 30);
    X.audit('知识库', `导入 ${out.length} 份资料${out.some((d) => d.prev) ? '（含新版本）' : ''}`, 'MinerU（模拟）');
    load();
    return { docs: out.map((d) => pub(DOCS.find((x) => x.id === d.id))), chunks: out.reduce((n, d) => n + (DOCS.find((x) => x.id === d.id).chunks.length), 0) };
  }
  /* 网址导入：原型不联网——命中内置的官网页面快照则"抓取"成功；否则如实告知 */
  function fetchUrl(url) {
    url = String(url || '').trim(); const K = window.JK_REAL_KB || {};
    if (!/^https?:\/\//i.test(url)) X.err(400, 'BAD_URL', '请粘贴以 http 开头的完整网址');
    const inKb = DOCS.find((d) => d.url && d.url === url);
    if (inKb) return { item: Object.assign(previewItem({ name: inKb.title, text: inKb.text, from: '网址', url, meta: { title: inKb.title, docNo: inKb.docNo, org: inKb.org, date: inKb.date, space: inKb.space, kind: inKb.kind, expire: inKb.expire } }), { real: !!inKb.real, example: !!inKb.example }), snapshot: true };
    const s = (K.snapshots || {})[url];
    if (s) return { item: Object.assign(previewItem({ name: s.title, text: s.text, from: '网址', url, meta: { title: s.title, docNo: s.docNo, org: s.org, date: s.date } }), { real: true }), snapshot: true, fetched: K.fetched };
    const host = (url.match(/^https?:\/\/([^/]+)/) || [])[1] || '';
    return { item: { key: X.nid('IMP'), name: host, from: '网址', url, ok: false, error: '原型未联网：这个页面没有内置快照。正式版由后端抓取网页正文；现在可以复制正文，用“粘贴文字”导入。', stages: { parse: 'fail', chunk: 'wait', tag: 'wait' } }, snapshot: false };
  }

  /* ===================== 路由（与 api/kb.js 同名同构） ===================== */
  const on = X.first;   // 覆盖 mock-api.js 中同名旧路由
  on('GET', '/api/v1/kb/spaces', () => {
    const roles = state().spaceRoles || {};
    const vis = visSpaces();
    const spaces = X.can('kb', 'admin') ? SPACES : SPACES.filter(s => vis.includes(s.id));
    return { items: spaces.map(s => {
      const visible = vis.includes(s.id);
      const docs = visible ? DOCS.filter(d => d.space === s.id) : [];
      return { ...s, roles: roles[s.id] || s.roles, visible, count: docs.length,
        expiring: docs.filter(d => statusOf(d) === '即将到期').length };
    }) };
  });
  on('PATCH', '/api/v1/kb/spaces/:id', (b, p) => { if (!X.can('kb', 'admin')) X.err(403, 'FORBIDDEN', '只有管理员可以修改空间可见范围'); const K = state(); K.spaceRoles = K.spaceRoles || {}; K.spaceRoles[p.id] = b.roles; X.audit('知识库', `修改空间可见范围 · ${spaceName(p.id)}`); return { ok: true }; });
  on('POST', '/api/v1/kb/search', (b) => search(b.q, b));
  on('POST', '/api/v1/kb/ask', (b) => { const r = ask(b.q, b); X.audit('知识库', `问答 · ${String(b.q).slice(0, 16)}`, 'DeepSeek（模拟·只摘原文）'); return r; });
  on('GET', '/api/v1/kb/docs', (b, p, q) => search('', { filters: q, limit: +q.limit || 400 }));
  on('GET', '/api/v1/kb/docs/:id', (b, p) => {
    const d = DOCS.find((x) => x.id === p.id); if (!d) X.err(404, 'NOT_FOUND', '资料不存在或已删除'); if (!canSee(d)) X.err(403, 'FORBIDDEN', '你没有查看这个空间的权限');
    const versions = []; let cur = d; while (cur && cur.prev) { const pv = DOCS.find((x) => x.id === cur.prev); if (!pv) break; versions.push({ id: pv.id, version: pv.version || 1, date: pv.date, addedAt: pv.addedAt }); cur = pv; }
    const newer = d.replacedBy ? DOCS.find((x) => x.id === d.replacedBy) : null;
    return { item: pub(d, { text: d.text, chunkList: d.chunks.map((c) => ({ i: c.i, start: c.start, end: c.end, head: c.head })), uploadedBy: d.uploadedBy, addedAt: d.addedAt, parse: d.parse || 'real', versions, newer: newer ? { id: newer.id, version: newer.version, date: newer.date } : null }) };
  });
  on('PATCH', '/api/v1/kb/docs/:id', (b, p) => { const d = DOCS.find((x) => x.id === p.id); if (!d) X.err(404, 'NOT_FOUND', '资料不存在'); if (!X.can('kb', 'operate')) X.err(403, 'FORBIDDEN', '没有修改权限'); const K = state(); const e = {}; ['tags', 'title', 'space', 'expire', 'status'].forEach((k) => { if (b[k] !== undefined) e[k] = b[k]; }); K.edits[d.id] = Object.assign(K.edits[d.id] || {}, e); X.audit('知识库', `修改资料信息 · ${d.title.slice(0, 14)}`); load(); return { item: pub(DOCS.find((x) => x.id === p.id)) }; });
  on('DELETE', '/api/v1/kb/docs/:id', (b, p) => { if (!X.can('kb', 'admin') && !X.can('kb', 'approve')) X.err(403, 'FORBIDDEN', '只有管理员或审签领导可以删除资料'); const K = state(); const d = DOCS.find((x) => x.id === p.id); if (!d) X.err(404, 'NOT_FOUND', '资料不存在'); if (K.added.some((x) => x.id === p.id)) K.added = K.added.filter((x) => x.id !== p.id); else K.removed.push(p.id); X.audit('知识库', `删除资料 · ${d.title.slice(0, 14)}`); load(); return { ok: true, item: { id: d.id, title: d.title } }; });
  on('POST', '/api/v1/kb/docs/:id/restore', (b, p) => { const K = state(); K.removed = K.removed.filter((x) => x !== p.id); load(); return { ok: true }; });
  on('POST', '/api/v1/kb/import/preview', (b) => { if (!X.can('kb', 'operate')) X.err(403, 'FORBIDDEN', '你只有查看权限，不能导入资料'); return { items: (b.items || []).map(previewItem) }; });
  on('POST', '/api/v1/kb/import/url', (b) => { if (!X.can('kb', 'operate')) X.err(403, 'FORBIDDEN', '你只有查看权限，不能导入资料'); return fetchUrl(b.url); });
  on('POST', '/api/v1/kb/import/commit', (b) => { if (!X.can('kb', 'operate')) X.err(403, 'FORBIDDEN', '你只有查看权限，不能导入资料'); return commit(b.items || [], b); });
  on('POST', '/api/v1/kb/import', (b) => { // 一步导入（供其它应用/对话直接调用）：预览后直接入库，重复跳过、同名按新版本
    if (!X.can('kb', 'operate')) X.err(403, 'FORBIDDEN', '你只有查看权限，不能导入资料');
    let items = (b.items || []).map(previewItem); if (b.url) items.push(fetchUrl(b.url).item); if (b.text) items.push(previewItem({ name: b.title || '粘贴的文字', text: b.text, from: b.from || '粘贴' }));
    if (b.space) items.forEach((it) => { if (it.meta) it.meta.space = b.space; });
    const r = commit(items, b); return Object.assign(r, { skipped: items.filter((it) => !it.ok || (it.dup && it.dup.type === 'duplicate')).map((it) => ({ name: it.name, reason: it.ok ? '已在库中' : it.error })) });
  });
  on('GET', '/api/v1/kb/stats', () => {
    const vis = DOCS.filter(canSee);
    const status = {};
    const otherSources = Object.create(null);
    let real = 0, example = 0;
    for (const d of vis) {
      const key = statusOf(d);
      status[key] = (status[key] || 0) + 1;
      if (d.real) real++;
      else if (d.example) example++;
      else {
        const from = d.source || '来源未注明';
        otherSources[from] = (otherSources[from] || 0) + 1;
      }
    }
    return { docs: vis.length, real, example, otherSources, status,
      chunks: vis.reduce((n, d) => n + d.chunks.length, 0), fetched: (window.JK_REAL_KB || {}).fetched,
      recent: vis.slice().sort((a, b) => String(b.addedAt || b.date).localeCompare(String(a.addedAt || a.date))).slice(0, 5).map((d) => pub(d)),
      log: state().log.slice(0, 5), facets: facets(vis) };
  });
  on('GET', '/api/v1/kb/suggest', () => ({ items: SUGGEST }));
  /* 旧接口兼容（mock-api.js 的 libraries/files/search） */
  on('GET', '/api/v1/kb/libraries', () => ({ items: SPACES.filter((s) => visSpaces().includes(s.id)).map((s) => ({ id: s.id, name: s.name, icon: s.name[0], files: DOCS.filter((d) => d.space === s.id).length })) }));
  on('GET', '/api/v1/kb/files/:id', (b, p) => { const d = DOCS.find((x) => x.id === p.id); if (!d) X.err(404, 'NOT_FOUND', '资料不存在'); return { item: { id: d.id, name: d.title, no: d.docNo, text: d.text, state: statusOf(d), url: d.url } }; });

  /* 【可改】首页建议问题（要保证每条都能在库里找到答案） */
  const SUGGEST = ['数据券补贴最高能拿多少？', '实体书店有哪些奖励？', '人形机器人推广应用怎么支持？', '信息技术产业局负责什么？'];

  // 工具：对话/其它应用可直接调（模型工具清单）
  window.JKKB = { search, ask, tokens, chunk, statusOf, reload: load, spaces: () => SPACES, docs: () => DOCS, qTokens };
  A.onLoad(() => load());
})();

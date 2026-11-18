/* 模拟后端：按《接口规范》实现同名路由，前端只通过 JKAPI.request(method, path, body) 访问。
 * 换真实后端时，把 request 改为 fetch(path, …) 即可，页面代码不用改。状态保存在 localStorage，可一键重置。 */
(function () {
  const SEED = window.JK_DATA;
  const KEY = window.JK_STATE_KEY || 'jkq-workstation-state-v3';
  const clone = (o) => JSON.parse(JSON.stringify(o));
  let S;
  function refreshExtensionNoticeSeeds() {
    // 已存状态也包含种子副本。只更新延期通知的模板示例和往期标注。
    const template = S.docTemplates?.find((t) => t.id === 'T06');
    if (template) template.inputs = clone(SEED.docTemplates.find((t) => t.id === 'T06').inputs);
    const notice = S.files?.find((f) => f.id === 'F008');
    if (notice) {
      const { name, snippet } = SEED.files.find((f) => f.id === 'F008');
      Object.assign(notice, { name, snippet });
    }
  }
  function load() {
    let cached;
    try { cached = JSON.parse(localStorage.getItem(KEY)); } catch (e) {}
    if (cached) {
      S = cached;
      refreshExtensionNoticeSeeds();
      return;
    }
    S = clone(SEED); S.messages = {}; S.jobs = {}; S.drafts = {}; S.myTodos = []; S.builder = {}; S.seq = 100; S.modelId = 'auto';
    seedDrafts();
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} }
  const nid = (p) => p + '-' + (++S.seq);
  const now = () => { const d = new Date(); return d.toISOString().slice(0, 10) + ' ' + d.toTimeString().slice(0, 5); };
  const me = () => S.users.find((u) => u.id === S.me);
  /* 权限判定（复用 haiknow rbac.py：角色 × 应用 × 动作 view/operate/approve/admin；授权表在 data/accounts.js） */
  function can(app, action, user) {
    const u = user || me(); if (!u) return false;
    const g = (S.grants || {})[u.role]; if (!g) return u.role === 'admin';
    const ap = (S.apps || []).find((a) => a.id === app); if (ap && ap.status === 'disabled' && !(g['*'] || []).includes('admin')) return false;
    const acts = [...(g['*'] || []), ...(g[app] || [])];
    return acts.includes('admin') || acts.includes(action);
  }
  const roleOf = (u) => (S.roles || []).find((r) => r.id === (u || me()).role) || {};
  function audit(app, action, model) { S.audit.unshift([now(), me().name, app, action, model || '—']); S.audit = S.audit.slice(0, 80); }
  const ent = (id) => S.enterprises.find((e) => e.id === id);
  const pol = (id) => S.policies.find((p) => p.id === id);
  const pdoc = (id) => S.policyDocs.find((d) => d.id === id);
  const fmtMoney = (n) => n >= 10000 ? (n / 10000).toFixed(n % 10000 ? 1 : 0).replace(/\.0$/, '') + ' 万元' : n + ' 元';
  const cnDate = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? `${+m[1]}年${+m[2]}月${+m[3]}日` : iso; };

  /* ================= 政策匹配引擎 ================= */
  function profileOf(e) {
    return { subjectType: e.subjectType, tags: e.tags, license: e.license, yearsInZone: e.yearsInZone, regInZone: e.regInZone, employees: e.employees, ...(e.amounts || {}), _known: Object.keys(e.amounts || {}) };
  }
  function evalCond(c, pf) {
    const val = pf[c.f];
    if (c.op === 'has' || c.op === 'hasAny') {
      const arr = val || []; const want = [].concat(c.v);
      const ok = want.some((w) => arr.includes(w));
      if (ok) return 'ok';
      if (c.f === 'license') return 'unknown';
      return 'no';
    }
    if (val === undefined || val === null || val === '') return 'unknown';
    if (c.op === '==') return val === c.v ? 'ok' : 'no';
    if (c.op === '>=') return val >= c.v ? 'ok' : 'no';
    if (c.op === '<=') return val <= c.v ? 'ok' : 'no';
    if (c.op === '>') return val > c.v ? 'ok' : 'no';
    return 'unknown';
  }
  function calcOf(p, pf) {
    const r = p.rule;
    if (r.fixed !== undefined) return r.fixed ? { amount: r.fixed, text: `定额，最高 ${fmtMoney(r.fixed)}`, capped: false } : null;
    const base = pf[r.base];
    if (!base) return null;
    const raw = Math.round(base * r.ratio), amount = Math.min(raw, r.cap);
    return { amount, base, text: `${fmtMoney(base)} × ${Math.round(r.ratio * 100)}% = ${fmtMoney(raw)}${raw > r.cap ? `，超过封顶，按 ${fmtMoney(r.cap)}` : ''}`, capped: raw > r.cap };
  }
  function matchAll(pf) {
    const out = [];
    S.policies.forEach((p) => {
      const objOk = p.object === pf.subjectType || (p.object === '其他组织' && pf.tags.includes('服务机构'));
      const checks = p.conditions.map((c) => ({ label: c.label, state: evalCond(c, pf) }));
      if (!objOk || checks[0].state !== 'ok') return;
      // trigger=该事项的“触发行为”（如建设数据集、改造门店）。台账里没有这类行为记录时不推荐，避免把不相干的事项列为待确认
      if (p.conditions.some((c, i) => c.trigger && checks[i].state === 'unknown')) return;
      let level = 'ok';
      if (checks.some((c) => c.state === 'no')) level = 'no';
      else if (checks.some((c) => c.state === 'unknown')) level = 'check';
      const ended = p.times.open === false;
      out.push({ id: p.id, title: p.title, level, checks, pending: p.pending, window: p.times.window, open: p.times.open, ended, calc: level === 'no' ? null : calcOf(p, pf), rule: p.rule.text, doc: pdoc(p.doc).no, clause: p.clause });
    });
    const rank = { ok: 0, check: 1, no: 2 };
    out.sort((a, b) => rank[a.level] - rank[b.level] || (a.ended - b.ended));
    return out;
  }
  function findEntInText(t) {
    if (!t) return null;
    return S.enterprises.find((e) => t.includes(e.short) || t.includes(e.name) || t.includes(e.short.slice(0, 3))) || null;
  }

  /* ================= 走访记录 → 台账更新建议 ================= */
  function extractVisit(e, notes) {
    const props = [];
    const add = (field, label, oldv, newv, src) => props.push({ id: nid('PR'), entId: e.id, field, label, old: oldv, new: newv, source: src, status: 'pending' });
    let m;
    if ((m = /房租[^0-9]{0,8}(\d+(?:\.\d+)?)\s*万/.exec(notes)) && +m[1] * 10000 !== e.amounts.rent) add('amounts.rent', '年房租', e.amounts.rent ? fmtMoney(e.amounts.rent) : '未登记', m[1] + ' 万元', m[0]);
    if ((m = /(\d{2,5})\s*(?:㎡|平方米|平米)/.exec(notes))) add('amounts.area', '经营面积', e.amounts.area ? e.amounts.area + '㎡' : '未登记', (e.amounts.area || 0) + +m[1] + '㎡（新增 ' + m[1] + '㎡）', m[0]);
    if ((m = /(?:员工|人数|职工)[^0-9]{0,6}(\d{1,5})\s*人/.exec(notes))) add('employees', '从业人数', e.employees + ' 人', m[1] + ' 人', m[0]);
    if ((m = /(新任)?(行政主管|总经理|财务总监|负责人|经理|主管|联系人)?[是为：:\s]*([\u4e00-\u9fa5]{2,3})[，,（(\s]*(?:电话|手机|联系电话|联系方式)[:：\s]*(1\d{10})/.exec(notes))) add('contacts', '新增联系人', e.contacts.map((c) => c.name).join('、'), `${m[3]}（${m[2] || '联系人'}，${m[4]}）`, m[0]);
    if ((m = /(算力|数据)[^0-9]{0,8}(\d+(?:\.\d+)?)\s*万/.exec(notes))) { const f = m[1] === '算力' ? 'computePurchase' : 'dataPurchase'; add('amounts.' + f, m[1] + '采购额', e.amounts[f] ? fmtMoney(e.amounts[f]) : '未登记', m[2] + ' 万元', m[0]); }
    if (/许可证/.test(notes) && !e.license.includes('出版物经营许可证') && e.tags.includes('实体书店')) add('license', '资质', e.license.join('、') || '无', '出版物经营许可证（企业口述，待核验）', '许可证');
    const issues = notes.split(/[。；;\n]/).filter((s) => /(询问|希望|反映|想了解|想申请|想要|需要|能不能|协调|问什么时候)/.test(s)).map((s) => s.trim()).filter(Boolean);
    return { proposals: props, issues };
  }
  function applyProposal(p) {
    const e = ent(p.entId);
    const num = parseFloat(String(p.new).replace(/[^0-9.]/g, ''));
    if (p.field === 'amounts.rent') e.amounts.rent = num * 10000;
    else if (p.field === 'amounts.area') e.amounts.area = parseInt(p.new);
    else if (p.field === 'employees') e.employees = num;
    else if (p.field.startsWith('amounts.')) e.amounts[p.field.slice(8)] = num * 10000;
    else if (p.field === 'contacts') { const m = /^(.+?)（(.+?)，(\d+)）/.exec(p.new); if (m) e.contacts.push({ name: m[1], title: m[2], phone: m[3] }); }
    else if (p.field === 'license') { e.license.push('出版物经营许可证'); e.qualifications.push({ name: '出版物经营许可证', validTo: '待核', verify: '企业自报' }); }
    e.history = e.history || []; e.history.unshift({ at: now(), by: me().name, field: p.label, old: p.old, new: p.new, source: '走访记录' });
  }

  /* ================= 会议长任务 ================= */
  const JOB_STEPS = ['上传与校验', '语音转写（本地 SenseVoice）', '区分发言人', '热词纠错', '生成纪要与待办'];
  function jobState(j) {
    const speed = S.demoFast ? 0.45 : 1;
    const elapsed = (Date.now() - j.started) / 1000, total = 6 * speed;
    const progress = Math.min(100, Math.round((elapsed / total) * 100));
    const step = Math.min(JOB_STEPS.length - 1, Math.floor((progress / 100) * JOB_STEPS.length));
    if (progress >= 100 && j.status !== 'done') {
      j.status = 'done';
      if (j.kind === 'transcribe') { const m = S.meetings.find((x) => x.id === j.ref); const r = S.meetingResults[m.id] || genericResult(m); Object.assign(m, clone(r), { status: 'done' }); save(); }
      if (j.kind === 'parse') { const f = S.files.find((x) => x.id === j.ref); if (f) { f.status = '已入库'; save(); } }
    }
    return { id: j.id, kind: j.kind, ref: j.ref, status: progress >= 100 ? 'done' : 'running', progress, step, steps: JOB_STEPS, stepName: JOB_STEPS[step] };
  }
  function genericResult(m) {
    const ps = m.participants.length ? m.participants : ['主持人', '参会人'];
    return {
      transcript: [['00:00:10', ps[0], `今天的会议主题是“${m.title}”，请大家围绕主要问题发言。`], ['00:02:30', ps[1] || ps[0], '我先汇报目前进展：前期准备基本完成，还有两项材料没到位。'], ['00:05:12', ps[0], '缺的材料下周三前补齐，由经办同志负责跟进。'], ['00:08:40', ps[2] || ps[0], '建议同步通知相关企业，避免信息不对称。'], ['00:10:05', ps[0], '同意。会后形成纪要，[听不清]……下次会议再听进展。']],
      topics: [{ t: '工作进展', bg: '前期准备基本完成', views: ['两项材料未到位'], decision: '下周三前补齐', refs: ['00:02:30', '00:05:12'] }, { t: '企业沟通', bg: '—', views: ['同步通知相关企业'], decision: '同意', refs: ['00:08:40'] }],
      todos: [{ id: nid('TD'), task: '补齐两项材料', owner: '待确认', due: '下周三', deliverable: '材料', ref: '00:05:12', status: '待认领', certain: false }, { id: nid('TD'), task: '通知相关企业', owner: ps[2] ? ps[2].replace(/（.*/, '') : '待确认', due: '待确认', deliverable: '通知', ref: '00:08:40', status: '待认领', certain: false }],
    };
  }
  function minutesOf(m) {
    const tpl = S.meetingTemplates.find((t) => t.name === m.type) || S.meetingTemplates[0];
    return { title: m.title + '纪要', meta: `时间：${m.date}　地点：${m.place || '—'}　主持：${m.host || '—'}`, attendees: m.participants.join('、'), template: tpl.name,
      body: m.topics.map((t, i) => ({ h: `${'一二三四五六七八九'[i]}、${t.t}`, p: `${t.bg ? t.bg + '。' : ''}${t.views.join('；')}。会议议定：${t.decision}。`, refs: t.refs })),
      todos: m.todos };
  }

  /* ================= 公文生成 / 核查 / 润色 / 比对 ================= */
  function genDoc(t, inp) {
    const v = (k) => (inp[k] !== undefined && String(inp[k]).trim() !== '' ? String(inp[k]) : `【待补：${(t.inputs.find((x) => x[0] === k) || [k, k])[1]}】`);
    const P = [];
    let title = '', to = '各有关单位：', sign = '北京经济技术开发区管理委员会产业促进局';
    switch (t.id) {
      case 'T03': { const p = pol(inp.policy) || pol('PI-03'); title = `关于开展${p.title}申报工作的通知`; to = '各有关企业：';
        P.push(`为贯彻落实《${pdoc(p.doc).title}》（${pdoc(p.doc).no}），支持相关主体高质量发展，现就${p.title}申报工作有关事项通知如下。`);
        P.push(`一、申报对象。${p.conditions.map((c) => c.label).join('；')}。`);
        P.push(`二、支持标准。${p.rule.text}。`);
        P.push(`三、申报时间。${cnDate(v('start'))}至${cnDate(v('end'))}，逾期不予受理。`);
        P.push(`四、申报材料。${p.materials.map((m, i) => `（${'一二三四五六七'[i]}）${m}`).join('；')}。`);
        P.push(`五、其他事项。同一事项不得重复申报，申报主体应对材料真实性负责。咨询电话：${v('contact')}。`); break; }
      case 'T06': title = `关于${v('orig').replace(/^关于/, '').replace(/的通知$/, '')}延期的通知`; to = '各有关企业：';
        P.push(`我局于近日发布《${v('orig')}》。因${v('reason')}，经研究，现将申报截止时间由${cnDate(v('oldEnd'))}延长至${cnDate(v('newEnd'))}。`);
        P.push('除申报截止时间外，原通知中申报对象、支持标准、申报材料、申报方式等其他事项均不变。');
        P.push('请各有关企业合理安排时间，在新的截止时间前完成申报。'); break;
      case 'T10': { const e = ent(inp.ent) || ent('E001'); const p = pol(inp.policy) || pol('PI-03'); title = `关于对${e.name}诉求的答复意见`; to = `${e.name}：`;
        P.push(`你单位反映的“${v('issue')}”已收悉。我局高度重视，经认真研究，现答复如下。`);
        P.push(`一、政策依据。根据《${pdoc(p.doc).title}》（${pdoc(p.doc).no}）${p.clause}，${p.original}`);
        P.push(`二、适用情况。经初步核对，你单位${e.yearsInZone >= 1 ? '在经开区注册经营已满一年' : '经营尚未满一年'}，${e.license.length ? '已登记' + e.license.join('、') : '暂未登记相关资质'}。具体申报资格以正式申报时提交材料的审核结果为准。`);
        { const tw = p.times.window || ''; const pend = tw.includes('未核实') || tw.includes('待') || /见当年|以.*通知为准|另行通知/.test(tw); P.push(`三、申报时间。${p.times.deadlineText ? p.times.deadlineText.replace(/。?$/, '。') : pend ? '当前批次申报通知尚未发布，我局将在通知发布后第一时间告知你单位。' : '申报时间为' + tw + '。'}`); }
        P.push('四、后续安排。请提前准备租赁合同、付款凭证等材料。如有疑问，可联系企业服务处。');
        P.push('感谢你单位对经开区工作的支持。'); break; }
      case 'T08': title = `关于${v('title')}拟推荐名单的公示`; to = '';
        P.push(`根据有关工作安排，经组织评议，拟推荐以下单位为${v('title')}：${v('list')}。`);
        P.push(`现予以公示，公示期为${v('days')}个工作日。公示期间，如有异议，请以书面形式向我局反映，并提供必要的证明材料。`);
        P.push('联系电话：010-6788XXXX。'); break;
      case 'T04': title = `关于征集${v('title')}的通知`; to = '各有关企业、科研机构：';
        P.push(`为加快推进人工智能场景应用落地，现面向社会公开征集${v('title')}。`);
        P.push('一、征集方向。面向政务服务、城市治理、智能制造等领域的人工智能应用场景。');
        P.push(`二、支持方式。${v('support')}。`);
        P.push(`三、截止时间。请于${cnDate(v('end'))}前通过线上平台提交申报材料。`); break;
      default: title = `关于${v(t.inputs[0][0])}的${t.kind}`;
        P.push(`为做好${v(t.inputs[0][0])}相关工作，现将有关事项${t.kind === '公示' ? '公示' : '通知'}如下。`);
        t.inputs.slice(1).forEach((x, i) => P.push(`${'一二三四五六'[i]}、${x[1]}：${v(x[0])}。`));
        P.push('请各单位认真贯彻执行。');
    }
    return { title, to, paragraphs: P, sign, date: cnDate('2026-11-17'), docNo: '京技产促〔2026〕【待补】号' };
  }
  const DOC_DATE_PREFIX = /^\s*(\d{4}(?:\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|-\d{2}-\d{2}(?![\d-])))/;
  const EXTENSION_DATES = /申报截止时间\s*由([^。；]*?)延长至([^。；]+)/;
  function docDateValue(text) {
    // 规则按日历日比较，日期后的时分和时区注记不参与比较。
    const match = DOC_DATE_PREFIX.exec(text || '');
    if (!match) return NaN;
    const [year, month, day] = match[1].match(/\d+/g);
    const iso = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
    const time = Date.parse(iso);
    return Number.isFinite(time) && new Date(time).toISOString().startsWith(iso) ? time : NaN;
  }
  function checkDoc(d) {
    const issues = []; const all = [d.title, d.to, ...d.paragraphs].join('\n');
    if (/【待补/.test(d.docNo)) issues.push({ id: 'c1', level: 'warn', kind: '文号', text: '发文字号未填写', fix: '京技产促〔2026〕58号', target: 'docNo' });
    d.paragraphs.forEach((p, i) => {
      if (/【待补：/.test(p)) issues.push({ id: 'c-m' + i, level: 'error', kind: '缺要素', text: `第 ${i + 1} 段有未填写的要素：${p.match(/【待补：(.+?)】/)[1]}`, para: i });
      if (/\d{4}-\d{2}-\d{2}/.test(p)) issues.push({ id: 'c-d' + i, level: 'warn', kind: '日期格式', text: `第 ${i + 1} 段日期写法不规范（应为“2026年12月1日”）`, para: i, fix: 'date' });
      if (d.templateId === 'T06') {
        const dates = EXTENSION_DATES.exec(p);
        if (dates) {
          const [, oldEnd, newEnd] = dates;
          const end = docDateValue(newEnd);
          const reasons = [];
          if (end <= docDateValue(oldEnd)) reasons.push('原截止日');
          if (end <= docDateValue(d.date)) reasons.push('发文日期');
          if (reasons.length) issues.push({ id: 'c-order' + i, level: 'warn', kind: '日期先后', text: `新截止日须晚于${reasons.join('和')}`, para: i });
        }
      }
      if (/的的|申报申报|载止|截至日期/.test(p)) issues.push({ id: 'c-t' + i, level: 'warn', kind: '错别字', text: `第 ${i + 1} 段疑似错别字：${p.match(/的的|申报申报|载止|截至日期/)[0]}`, para: i, fix: 'typo' });
      if (/咱们|赶紧|搞|弄好|大家/.test(p)) issues.push({ id: 'c-s' + i, level: 'info', kind: '语体', text: `第 ${i + 1} 段有口语化表达：“${p.match(/咱们|赶紧|搞|弄好|大家/)[0]}”`, para: i, fix: 'polish' });
    });
    const nums = all.match(/最高\s*(?:不超过)?\s*(\d+)\s*万元/g) || [];
    if (d.policyId) { const p = pol(d.policyId); const cap = p && p.rule.cap ? p.rule.cap / 10000 : null; nums.forEach((n) => { const x = +n.match(/(\d+)/)[1]; if (cap && x !== cap && x * 10000 !== p.rule.fixed) issues.push({ id: 'c-n' + x, level: 'error', kind: '数字一致', text: `“${n}”与政策原文（最高 ${cap} 万元）不一致` }); }); }
    if (d.templateId === 'T08' && !/拟/.test(d.title)) issues.push({ id: 'c-ni', level: 'error', kind: '公示规范', text: '公示标题须保留“拟”字' });
    if (d.templateId === 'T06' && !/不变/.test(all)) issues.push({ id: 'c-bb', level: 'warn', kind: '口径', text: '期限调整通知应写明“其他事项不变”' });
    if (!issues.length) issues.push({ id: 'c-ok', level: 'ok', kind: '通过', text: '未发现问题：文号、日期、数字、语体均已核对' });
    return issues;
  }
  const POLISH = { formal: [['咱们', '我局'], ['赶紧', '及时'], ['搞', '开展'], ['弄好', '完成'], ['大家', '各单位'], ['马上', '尽快'], ['看看', '研究'], ['问一下', '咨询'], ['很多', '较多'], ['没有', '未'], ['不行', '不符合条件'], ['可以', '可'], ['帮忙', '协助']], concise: [['经认真研究，', ''], ['高度重视，', ''], ['认真', ''], ['相关的', '相关'], ['进行', ''], ['的话', '']] };
  function polishText(t, style) { let out = t; (POLISH[style] || POLISH.formal).forEach(([a, b]) => { out = out.split(a).join(b); }); if (style === 'formal' && out === t) out = t.replace(/。$/, '，特此告知。').replace(/特此告知。，特此告知。/, '特此告知。'); return out; }
  function diff(a, b) {
    const A = [...a], B = [...b]; const n = A.length, m = B.length;
    if (n * m > 600000) return [{ op: 'del', t: a }, { op: 'add', t: b }];
    const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const out = []; let i = 0, j = 0; const push = (op, ch) => { const l = out[out.length - 1]; if (l && l.op === op) l.t += ch; else out.push({ op, t: ch }); };
    while (i < n && j < m) { if (A[i] === B[j]) { push('eq', A[i]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) { push('del', A[i]); i++; } else { push('add', B[j]); j++; } }
    while (i < n) push('del', A[i++]); while (j < m) push('add', B[j++]);
    return out;
  }
  function docText(d) { return [d.title, d.docNo, d.to, ...d.paragraphs, d.sign, d.date].filter(Boolean).join('\n'); }
  function seedDrafts() {
    const t = S.docTemplates.find((x) => x.id === 'T10');
    const c = genDoc(t, { ent: 'E001', issue: '咨询实体书店房租补贴申报时间', policy: 'PI-03' });
    const v1 = clone(c); v1.paragraphs[3] = '三、申报时间。今年的通知还没出来，出来以后咱们马上告诉你们。';
    S.drafts['DOC-1112'] = { id: 'DOC-1112', title: c.title, templateId: 'T10', policyId: 'PI-03', status: '审签中', author: '王敏', versions: [{ v: 1, at: '2026-11-12 16:20', by: '王敏', content: v1 }, { v: 2, at: '2026-11-13 10:05', by: '王敏', content: c }],
      comments: [{ id: 'cm1', para: 1, by: '孙婷', at: '2026-11-13 11:02', text: '政策原文引用建议只保留关键句，太长了。', replies: [{ by: '王敏', text: '好的，审签后统一精简。' }], resolved: false }, { id: 'cm2', para: 3, by: '李阳', at: '2026-11-13 14:30', text: '申报时间表述可以，注意不要承诺具体日期。', replies: [], resolved: true }] };
    S.documents.forEach((d) => {
      if (S.drafts[d.id]) return;
      const tt = S.docTemplates.find((x) => x.id === d.templateId);
      // 往期定稿沿用原批次的要素，新建通知使用当前模板示例。
      const inp = d.id === 'DOC-1108' ? {
        orig: '关于开展 2026 年数据券申报工作的通知',
        oldEnd: '2026-11-02',
        newEnd: '2026-11-06',
        reason: '部分企业交易凭证开具延迟',
      } : Object.fromEntries(tt.inputs.map(([key, , value]) => [key, value]));
      const content = genDoc(tt, inp);
      content.title = d.title;
      if (d.status === '已定稿') content.docNo = '京技产促〔2026〕51号';
      S.drafts[d.id] = { id: d.id, title: d.title, templateId: d.templateId, status: d.status, author: d.author,
        versions: [{ v: 1, at: d.updated + ' 10:00', by: d.author, content }], comments: [] };
    });
  }
  function docSummary(dr) { return { id: dr.id, title: dr.title, templateId: dr.templateId, status: dr.status, author: dr.author, updated: dr.versions[dr.versions.length - 1].at, versions: dr.versions.length, comments: dr.comments.filter((c) => !c.resolved).length }; }

  /* ================= 资料库检索 ================= */
  function kbSearch(q) {
    const words = (q || '').replace(/[？?，,。]/g, ' ').split(/\s+/).filter(Boolean);
    // 长句没有空格时，按两字切分再检索（例如“数据券申报截止时间” → 数据 / 据券 / 申报 …）
    const kw = (words.length ? words : [q]).flatMap((w) => (w.length > 4 ? [...Array(w.length - 1)].map((_, i) => w.slice(i, i + 2)).filter((x) => !/^(时间|的|了|一下)$/.test(x)) : [w]));
    const hits = [];
    S.files.forEach((f) => {
      const hay = f.name + (f.snippet || '') + f.tags.join('');
      const score = kw.reduce((s, w) => s + (hay.includes(w) ? 2 : 0) + [...w].filter((ch) => hay.includes(ch)).length / Math.max(4, w.length * 2), 0);
      if (score > 0.8) hits.push({ fileId: f.id, name: f.name, lib: f.lib, snippet: f.snippet || '（文件已入库，可打开查看全文）', page: 1 + (f.id.charCodeAt(3) % 6), score: +score.toFixed(2), status: f.status });
    });
    S.policies.forEach((p) => { const hay = p.title + p.keywords.join('') + p.original; const sc = kw.reduce((s, w) => s + (hay.includes(w) ? 3 : 0), 0); if (sc) hits.push({ fileId: 'POL:' + p.id, name: `${pdoc(p.doc).no} · ${p.clause}`, lib: 'policy', snippet: p.original, page: 2, score: sc, status: '已入库' }); });
    return hits.sort((a, b) => b.score - a.score).slice(0, 8);
  }

  /* ================= 对话编排（意图识别 → 调用小应用工具 → 卡片） ================= */
  function pickModel(requested, sensitive) {
    const m = S.models.find((x) => x.id === requested) || S.models[0];
    if (sensitive && (m.kind === 'cloud' || m.id === 'auto')) return { used: S.models.find((x) => x.id === 'local-qwen-32b'), note: m.id === 'auto' ? '涉及企业台账，已自动路由到本地模型' : `涉及企业台账（内部数据），已从 ${m.name} 切换到本地模型，数据不出局` };
    if (m.id === 'auto') return { used: S.models.find((x) => x.id === 'deepseek-v4.1-flash'), note: '自动选择：高频问答 → DeepSeek-V4.1-Flash' };
    return { used: m, note: '' };
  }
  function detectIntent(text, forced) {
    if (forced) return forced;
    const t = text;
    if (/(公文|起草|拟稿|通知|函|润色|比对|公示|答复意见|改写)/.test(t)) return 'document';
    if (/(会议|纪要|录音|转写|座谈|局务会|待办)/.test(t)) return 'meeting';
    if (/(政策|补贴|奖励|申报|兑现|能申请|支持|数据券|算力券|房租)/.test(t)) return 'policy';
    if (/(企业|公司|台账|走访|画像|联系人|资质|到期|查一下)/.test(t) || findEntInText(t)) return 'enterprise';
    if (/(资料|原文|文件|出处|NAS|条款)/.test(t)) return 'kb';
    return 'chat';
  }
  function chatReply(text, opts) {
    const intent = detectIntent(text, opts.app);
    const e = findEntInText(text);
    const sensitive = intent === 'enterprise' || (intent === 'policy' && !!e);
    const { used, note } = pickModel(opts.model || S.modelId, sensitive);
    const r = { id: nid('M'), role: 'assistant', model: used.name, routeNote: note, intent, content: '', cards: [], citations: [], toolCalls: [], at: now() };
    if (intent === 'policy') {
      if (e) {
        const res = matchAll(profileOf(e));
        const ok = res.filter((x) => x.level === 'ok'), ck = res.filter((x) => x.level === 'check');
        r.toolCalls.push({ tool: 'policy.match', args: { entId: e.id } });
        r.content = `已按「${e.short}」的台账画像（${e.subjectType} · ${e.industry} · 入区 ${e.yearsInZone} 年）核对了 18 项事项：\n**${ok.length} 项可进一步核对**，**${ck.length} 项缺信息待确认**，其余不满足或不适用。下面是结果，点“打开政策兑现”可以补信息、试算并生成告知单。`;
        r.cards.push({ type: 'policy-match', entId: e.id, results: res.slice(0, 5) });
        const top = ok[0] || ck[0]; if (top) { const p = pol(top.id); r.citations.push({ fileId: 'POL:' + p.id, name: `${pdoc(p.doc).no} ${p.clause}`, snippet: p.original }); }
      } else {
        const q = text.replace(/[？?。]/g, '');
        const items = S.policies.filter((p) => p.keywords.some((k) => q.includes(k)) || q.includes(p.title.slice(0, 4)));
        const list = (items.length ? items : S.policies.filter((p) => p.times.open !== false).slice(0, 4)).slice(0, 4);
        r.toolCalls.push({ tool: 'policy.search', args: { q } });
        if (items.length) { const p = items[0];
          r.content = `「${p.title}」的要点：\n· **对象**：${p.object} → ${p.sub}\n· **条件**：${p.conditions.map((c) => c.label).join('；')}\n· **支持规则**：${p.rule.text}\n· **申报窗口**：${p.times.window}\n· **还需确认**：${p.pending.join('、') || '无'}\n\n如果告诉我是哪家企业，我可以直接按台账核对是否满足。`;
          r.citations.push({ fileId: 'POL:' + p.id, name: `${pdoc(p.doc).no} ${p.clause}`, snippet: p.original });
        } else r.content = '没有找到完全对应的事项。下面是当前可关注的几项，你也可以说出企业名称，我按台账帮你逐项核对。';
        r.cards.push({ type: 'policy-items', ids: list.map((p) => p.id) });
      }
    } else if (intent === 'enterprise') {
      if (/到期/.test(text)) { const list = alerts().filter((a) => a.kind === '资质到期'); r.content = `有 **${list.length} 家**企业的资质在 60 天内到期：`; r.cards.push({ type: 'alerts', items: list }); r.toolCalls.push({ tool: 'enterprise.alerts', args: { kind: 'expiring' } }); }
      else if (/没走访|未走访|久未/.test(text)) { const list = alerts().filter((a) => a.kind === '久未走访'); r.content = `超过 90 天未走访的企业有 **${list.length} 家**：`; r.cards.push({ type: 'alerts', items: list }); r.toolCalls.push({ tool: 'enterprise.alerts', args: { kind: 'no_visit_90d' } }); }
      else if (e) { r.toolCalls.push({ tool: 'enterprise.get', args: { id: e.id } }); const iss = S.issues.filter((i) => i.entId === e.id && i.status !== '已办结');
        r.content = `**${e.name}** 走访前 30 秒摘要：\n· 做什么：${e.products}（${e.industry}，${e.scale}，${e.employees} 人）\n· 资质：${e.license.join('、') || '暂无登记'}\n· 最近走访：${e.lastVisit}（${e.servicer}）\n· 在办诉求：${iss.length ? iss.map((i) => i.title + '（' + i.status + '）').join('；') : '无'}`;
        r.cards.push({ type: 'enterprise-brief', entId: e.id }); }
      else { r.content = '你想查哪家企业？可以说简称，比如“查一下星河智驾”。也可以问“资质快到期的企业”“超过 90 天没走访的企业”。'; r.cards.push({ type: 'enterprise-list', ids: S.enterprises.filter((x) => x.tags.includes('重点服务')).map((x) => x.id) }); }
    } else if (intent === 'meeting') {
      r.toolCalls.push({ tool: 'meeting.list', args: {} });
      const pend = S.meetings.filter((m) => m.status === 'done').flatMap((m) => m.todos.filter((t) => t.status === '待认领').map((t) => ({ ...t, meeting: m.title })));
      if (/待办/.test(text)) { r.content = `近期会议还有 **${pend.length} 条**待办没认领：`; r.cards.push({ type: 'todos', items: pend }); }
      else { r.content = '最近的会议录音如下。已整理的可以直接看纪要；新到的录音点“整理这份”，转写、分发言人、纪要和待办会自动完成（可离开页面，好了会通知你）。'; r.cards.push({ type: 'meeting-list', ids: S.meetings.map((m) => m.id) }); }
    } else if (intent === 'document') {
      if (/润色/.test(text)) { const src = text.split(/[：:]/).slice(1).join('：') || '咱们这个事情要赶紧搞，大家看看有没有问题。'; const out = polishText(src, 'formal'); r.toolCalls.push({ tool: 'document.polish', args: { style: 'formal' } }); r.content = '润色结果（政务语体）：'; r.cards.push({ type: 'diff', a: src, b: out, parts: diff(src, out) }); }
      else { const tid = /延期|期限/.test(text) ? 'T06' : /公示/.test(text) ? 'T08' : /答复/.test(text) ? 'T10' : /征集/.test(text) ? 'T04' : /申报/.test(text) ? 'T03' : null;
        r.toolCalls.push({ tool: 'document.templates', args: {} });
        if (tid) { const t = S.docTemplates.find((x) => x.id === tid); r.content = `这属于「${t.groupName} · ${t.name}」。需要填 ${t.inputs.length} 个要素（已帮你按常见情况预填），确认后一键出初稿：`; r.cards.push({ type: 'doc-start', templateId: tid }); }
        else { r.content = '先选“要办什么事”，我按对应的结构起草：'; r.cards.push({ type: 'doc-templates' }); } }
    } else if (intent === 'kb') {
      const hits = kbSearch(text); r.toolCalls.push({ tool: 'kb.search', args: { q: text } });
      r.content = hits.length ? `在共享资料库找到 ${hits.length} 处相关内容，按相关度排列，点击可看原文：` : '资料库里没有找到相关内容。可以把文件拖进“资料库”，入库后就能检索。';
      r.cards.push({ type: 'kb-hits', hits });
    } else {
      const canned = [
        [/(你好|您好|hi|hello)/i, '你好！我是经开区共享智能体工作站的助手。你可以直接说要办的事，比如“书香里文化能申请哪些支持？”“整理昨天座谈会的纪要”“起草一份申报延期通知”。'],
        [/(能做什么|会什么|怎么用|帮助)/, '我能做四类事：\n1. **政策兑现咨询**：按企业情况匹配 18 项事项、试算、生成告知单\n2. **企业管理维护**：查企业、记走访、更新台账、跟进诉求\n3. **会议记录**：录音转写、纪要、待办\n4. **公文协作**：拟稿、核查、润色、比对、批注、审签\n直接说事就行，不用选功能；也可以输入“/”指定应用。'],
        [/三个时间/, '政策兑现里的“三个时间”要分开看：\n· **政策有效期**：这套规则什么时候有效\n· **事项发生期**：哪段时间发生的支出可以申报\n· **申报窗口**：什么时候可以递交申请\n政策有效不代表现在能报；旧政策到期也可能还有历史年度的兑现批次。'],
        [/(总结|概括|摘要)/, '可以，把要总结的文字粘贴进来，或者在资料库里选中文件后让我总结。'],
      ];
      const hit = canned.find(([re]) => re.test(text));
      r.content = hit ? hit[1] : `收到。关于“${text.slice(0, 40)}”，我的理解和建议如下：\n1. 先明确要办的事项和涉及的企业或文件；\n2. 如果涉及政策、企业、会议或公文，我会调用对应的应用，结果带出处；\n3. 没有依据的内容我会标“待确认”，不替你编。\n\n（演示环境：当前回复由模拟模型生成；正式环境由 ${used.name} 实时生成。）`;
      r.cards.push({ type: 'app-suggest' });
    }
    return r;
  }
  function alerts() {
    const out = [];
    S.enterprises.forEach((e) => {
      e.qualifications.forEach((q) => { const d = (Date.parse(q.validTo) - Date.parse('2026-11-17')) / 864e5; if (d >= 0 && d <= 60) out.push({ entId: e.id, name: e.short, kind: '资质到期', text: `${q.name} ${q.validTo} 到期（剩 ${Math.round(d)} 天）`, level: d < 30 ? 'high' : 'mid' }); });
      if (e.lastVisitDays > 90 && (e.tags.includes('重点服务') || e.scale !== '微型')) out.push({ entId: e.id, name: e.short, kind: '久未走访', text: `已 ${e.lastVisitDays} 天未走访（${e.servicer}）`, level: e.lastVisitDays > 150 ? 'high' : 'mid' });
    });
    S.issues.filter((i) => i.status !== '已办结' && i.due < '2026-11-22').forEach((i) => out.push({ entId: i.entId, name: ent(i.entId).short, kind: '诉求临期', text: `${i.title} · ${i.due} 到期`, level: 'high', issueId: i.id }));
    return out;
  }
  function maskEnt(e) { if (!roleOf().mask) return e; const c = clone(e); c.contacts = c.contacts.map((x) => ({ ...x, phone: x.phone.slice(0, 3) + '****' + x.phone.slice(-4) })); c.revenue = { value: '***', unit: '', period: '受限字段', source: '', verify: '' }; c.masked = true; return c; }

  /* ================= 路由表 ================= */
  const routes = [];
  const on = (method, pattern, fn) => routes.push({ method, re: new RegExp('^' + pattern.replace(/:(\w+)/g, '(?<$1>[^/]+)') + '$'), fn });
  const err = (status, code, message) => { const e = new Error(message); e.status = status; e.code = code; throw e; };

  // 身份与平台
  on('GET', '/api/v1/me', () => ({ user: me(), org: S.org, roles: S.roles }));
  on('PUT', '/api/v1/me/role', (b) => { S.users.find((u) => u.id === S.me).role = b.role; return { user: me() }; });
  on('GET', '/api/v1/users', () => ({ items: S.users }));
  on('GET', '/api/v1/models', () => ({ items: S.models, current: S.modelId, capabilities: S.capabilities }));
  on('PUT', '/api/v1/models/current', (b) => { const m = S.models.find((x) => x.id === b.model); if (!m) err(404, 'MODEL_NOT_FOUND', '模型不存在'); if (!m.enabled) err(403, 'MODEL_DISABLED', `${m.name} 默认关闭：政务数据不出境，需管理员对“公开资料”单独开放`); S.modelId = b.model; return { current: S.modelId }; });
  on('PATCH', '/api/v1/models/:id', (b, p) => { const m = S.models.find((x) => x.id === p.id); Object.assign(m, b); audit('模型网关', `${b.enabled ? '启用' : '停用'} ${m.name}`); return { item: m }; });
  on('POST', '/api/v1/ai/chat', (b) => { const r = chatReply(b.messages[b.messages.length - 1].content, b); return { model: r.model, content: r.content, routeNote: r.routeNote }; });
  on('GET', '/api/v1/apps', () => ({ items: S.apps, skills: S.skills }));
  on('GET', '/api/v1/apps/:id', (b, p) => ({ item: S.apps.find((a) => a.id === p.id) || S.skills.find((s) => s.id === p.id) }));
  // 对话
  on('GET', '/api/v1/conversations', () => ({ items: S.conversations }));
  on('POST', '/api/v1/conversations', (b) => { const c = { id: nid('C'), title: b.title || '新对话', app: b.app || null, updated: '刚刚' }; S.conversations.unshift(c); S.messages[c.id] = []; return { item: c }; });
  on('GET', '/api/v1/conversations/:id', (b, p) => ({ item: S.conversations.find((c) => c.id === p.id), messages: S.messages[p.id] || [] }));
  on('DELETE', '/api/v1/conversations/:id', (b, p) => { S.conversations = S.conversations.filter((c) => c.id !== p.id); delete S.messages[p.id]; return { ok: true }; });
  on('POST', '/api/v1/conversations/:id/messages', (b, p) => {
    let c = S.conversations.find((x) => x.id === p.id); if (!c) { c = { id: p.id, title: b.text.slice(0, 18), app: null, updated: '刚刚' }; S.conversations.unshift(c); }
    S.messages[c.id] = S.messages[c.id] || [];
    const u = { id: nid('M'), role: 'user', content: b.text, at: now(), files: b.files || [] };
    const r = chatReply(b.text, b);
    if (c.title === '新对话') c.title = b.text.slice(0, 18);
    c.updated = '刚刚'; c.app = c.app || (r.intent !== 'chat' && r.intent !== 'kb' ? r.intent : null);
    S.messages[c.id].push(u, r);
    audit('对话', `${r.intent} · ${b.text.slice(0, 16)}`, r.model);
    return { conversation: c, user: u, reply: r };
  });
  // 政策兑现咨询
  on('GET', '/api/apps/policy/items', (b, p, q) => {
    let items = S.policies;
    if (q.q) items = items.filter((x) => (x.title + x.keywords.join('') + x.sub + x.original).includes(q.q));
    if (q.object) items = items.filter((x) => x.object === q.object);
    if (q.window === 'open') items = items.filter((x) => x.times.open === true);
    if (q.window === 'ended') items = items.filter((x) => x.times.open === false);
    if (q.window === 'unknown') items = items.filter((x) => x.times.open === null);
    return { items: items.map((x) => ({ ...x, docNo: pdoc(x.doc).no, docTitle: pdoc(x.doc).title, docState: pdoc(x.doc).state })), total: items.length, docs: S.policyDocs };
  });
  on('GET', '/api/apps/policy/items/:id', (b, p) => { const x = pol(p.id); if (!x) err(404, 'NOT_FOUND', '事项不存在'); return { item: { ...x, docNo: pdoc(x.doc).no, docTitle: pdoc(x.doc).title, docState: pdoc(x.doc).state } }; });
  on('POST', '/api/apps/policy/match', (b) => {
    let pf; if (b.entId) { const e = ent(b.entId); pf = profileOf(e); Object.assign(pf, b.overrides || {}); if (b.overrides && b.overrides.license) pf.license = [...new Set([...(e.license || []), ...b.overrides.license])]; }
    else pf = Object.assign({ subjectType: '企业', tags: [], license: [], regInZone: true }, b.profile);
    const results = matchAll(pf); audit('政策兑现咨询', `匹配 · ${b.entId ? ent(b.entId).short : '手动画像'}`, 'DeepSeek-V4.1-Flash');
    return { profile: pf, results, summary: { ok: results.filter((r) => r.level === 'ok').length, check: results.filter((r) => r.level === 'check').length, no: results.filter((r) => r.level === 'no').length } };
  });
  on('POST', '/api/apps/policy/calc', (b) => { const p = pol(b.itemId); const pf = {}; if (p.rule.base) pf[p.rule.base] = +b.amount; return { item: p.id, rule: p.rule.text, result: calcOf(p, pf), note: '试算按政策原文规则确定性计算，实际金额以评审结果为准' }; });
  on('POST', '/api/apps/policy/notice', (b) => {
    const e = ent(b.entId); const items = b.itemIds.map(pol);
    const lines = [`${e.name}：`, `根据你单位情况，经初步核对，可关注以下政策事项（仅供参考，以正式申报审核为准）：`];
    items.forEach((p, i) => { lines.push(`${i + 1}. ${p.title}（${pdoc(p.doc).no} ${p.clause}）`); lines.push(`   支持标准：${p.rule.text}`); lines.push(`   申报时间：${p.times.window}`); lines.push(`   需准备材料：${p.materials.join('、') || '以申报通知为准'}`); if (p.pending.length) lines.push(`   尚需确认：${p.pending.join('、')}`); });
    lines.push('如有疑问请联系企业服务处，电话 010-6788XXXX。', `北京经济技术开发区产业促进局　${cnDate('2026-11-17')}`);
    audit('政策兑现咨询', `生成一次性告知单 · ${e.short}`, 'Qwen4-Max');
    return { text: lines.join('\n') };
  });
  // 企业管理维护
  on('GET', '/api/apps/enterprise/companies', (b, p, q) => {
    let items = S.enterprises;
    if (q.q) items = items.filter((e) => (e.name + e.short + e.creditCode + e.industry + e.tags.join('') + e.formerNames.join('')).includes(q.q));
    if (q.industry) items = items.filter((e) => e.industry.includes(q.industry));
    if (q.tag) items = items.filter((e) => e.tags.includes(q.tag));
    if (q.scale) items = items.filter((e) => e.scale === q.scale);
    if (q.servicer) items = items.filter((e) => e.servicer === q.servicer);
    if (q.alert) { const ids = new Set(alerts().map((a) => a.entId)); items = items.filter((e) => ids.has(e.id)); }
    const sort = q.sort || 'lastVisit';
    items = items.slice().sort((a, b) => sort === 'revenue' ? b.revenue.value - a.revenue.value : sort === 'name' ? a.short.localeCompare(b.short, 'zh') : b.lastVisitDays - a.lastVisitDays);
    return { items: items.map(maskEnt), total: items.length, facets: { industries: [...new Set(S.enterprises.map((e) => e.industry.split(' · ')[0]))], tags: [...new Set(S.enterprises.flatMap((e) => e.tags))], servicers: [...new Set(S.enterprises.map((e) => e.servicer))] } };
  });
  on('GET', '/api/apps/enterprise/companies/:id', (b, p) => { const e = ent(p.id); if (!e) err(404, 'NOT_FOUND', '企业不存在'); return { item: maskEnt(e), visits: S.visits.filter((v) => v.entId === e.id), issues: S.issues.filter((i) => i.entId === e.id), files: S.files.filter((f) => f.tags.includes(e.id)), proposals: S.proposals.filter((x) => x.entId === e.id && x.status === 'pending'), history: e.history || [] }; });
  on('PATCH', '/api/apps/enterprise/companies/:id', (b, p) => { const e = ent(p.id); if (!can('enterprise', 'operate') || roleOf().mask) err(403, 'FORBIDDEN', '当前角色只能查看台账，不能修改'); Object.entries(b).forEach(([k, v]) => { const old = e[k]; e[k] = v; e.history = e.history || []; e.history.unshift({ at: now(), by: me().name, field: k, old: String(old), new: String(v), source: '手动修改' }); }); audit('企业管理维护', `修改台账 · ${e.short}`); return { item: e }; });
  on('POST', '/api/apps/enterprise/companies', (b) => { const id = 'E' + String(S.enterprises.length + 1).padStart(3, '0'); const e = { id, name: b.name, short: b.short || b.name.replace(/^北京|有限公司$/g, '').slice(0, 6), creditCode: b.creditCode || '待补', industry: b.industry || '待分类', scale: b.scale || '小型', tags: b.tags || [], license: [], subjectType: '企业', established: '待补', yearsInZone: +b.yearsInZone || 0, regInZone: true, employees: +b.employees || 0, revenue: { value: 0, unit: '万元', period: '—', source: '—', verify: '待核' }, amounts: {}, regAddr: b.addr || '待补', opAddr: b.addr || '待补', formerNames: [], contacts: b.contact ? [{ name: b.contact, title: '联系人', phone: b.phone || '待补', main: true }] : [], servicer: me().name, lastVisit: '—', lastVisitDays: 0, qualifications: [], products: b.industry || '待补', fieldStatus: {} }; S.enterprises.unshift(e); audit('企业管理维护', `新建企业档案 · ${e.short}`); return { item: e }; });
  on('POST', '/api/apps/enterprise/companies/:id/visits', (b, p) => {
    const e = ent(p.id); const v = { id: nid('V'), entId: e.id, date: '2026-11-17', staff: me().name, type: b.type || '上门走访', notes: b.notes, followups: [] };
    S.visits.unshift(v); e.lastVisit = '2026-11-17'; e.lastVisitDays = 0;
    const { proposals, issues } = extractVisit(e, b.notes);
    S.proposals.push(...proposals);
    audit('企业管理维护', `记录走访 · ${e.short}`, 'Qwen3-32B（本地）');
    return { visit: v, proposals, issues };
  });
  on('POST', '/api/apps/enterprise/proposals/:id/decision', (b, p) => { const x = S.proposals.find((y) => y.id === p.id); if (!x) err(404, 'NOT_FOUND', '建议不存在'); if (b.value) x.new = b.value; x.status = b.decision === 'accept' ? 'accepted' : 'rejected'; if (x.status === 'accepted') applyProposal(x); audit('企业管理维护', `${x.status === 'accepted' ? '确认写入' : '忽略'} · ${x.label}`); const left = S.proposals.filter((y) => y.entId === x.entId && y.status === 'pending').length; if (!left) S.inbox.forEach((i) => { if (i.type === 'proposal' && i.ref === x.entId) i.status = 'done'; }); return { item: x, pending: left }; });
  on('GET', '/api/apps/enterprise/issues', (b, p, q) => { let items = S.issues; if (q.status) items = items.filter((i) => i.status === q.status); if (q.entId) items = items.filter((i) => i.entId === q.entId); if (q.owner) items = items.filter((i) => i.owner === q.owner); return { items: items.map((i) => ({ ...i, entName: ent(i.entId).short })), statuses: ['待分派', '办理中', '待补材料', '已办结'] }; });
  on('POST', '/api/apps/enterprise/issues', (b) => { const i = { id: nid('IS'), entId: b.entId, title: b.title, from: b.from || '走访', created: '2026-11-17', owner: b.owner || me().name, status: '办理中', due: b.due || '2026-11-30', next: b.next || '待确定', steps: [['2026-11-17', '登记诉求（' + (b.from || '走访') + '）']] }; S.issues.unshift(i); audit('企业管理维护', `登记诉求 · ${ent(b.entId).short}`); return { item: i }; });
  on('PATCH', '/api/apps/enterprise/issues/:id', (b, p) => { const i = S.issues.find((x) => x.id === p.id); if (b.status && b.status !== i.status) i.steps.push(['2026-11-17', `状态：${i.status} → ${b.status}${b.note ? '（' + b.note + '）' : ''}`]); else if (b.note) i.steps.push(['2026-11-17', b.note]); Object.assign(i, { status: b.status || i.status, next: b.next || i.next, owner: b.owner || i.owner }); audit('企业管理维护', `更新诉求 · ${i.title.slice(0, 10)}`); return { item: i }; });
  on('GET', '/api/apps/enterprise/alerts', () => ({ items: alerts() }));
  on('GET', '/api/apps/enterprise/export', (b, p, q) => { const ids = q.ids ? q.ids.split(',') : S.enterprises.map((e) => e.id); const rows = [['企业名称', '统一社会信用代码', '行业', '规模', '从业人数', '2025营收(万元)', '服务专员', '最近走访', '标签']]; ids.map(ent).forEach((e) => { const m = maskEnt(e); rows.push([m.name, m.creditCode, m.industry, m.scale, m.employees, m.revenue.value, m.servicer, m.lastVisit, m.tags.join('/')]); }); audit('企业管理维护', `导出台账 ${ids.length} 家`); return { filename: '企业台账导出.csv', csv: '\ufeff' + rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n') }; });
  on('POST', '/api/apps/enterprise/import', (b) => { const added = (b.rows || []).map((r) => routes.find((x) => x.method === 'POST' && x.re.test('/api/apps/enterprise/companies')).fn(r).item); return { added: added.length, items: added }; });
  // 会议记录
  on('GET', '/api/apps/meeting/meetings', () => ({ items: S.meetings.map((m) => ({ id: m.id, title: m.title, type: m.type, date: m.date, duration: m.duration, status: m.status, file: m.file, size: m.size, source: m.source, scope: m.scope, participants: m.participants, todoCount: (m.todos || []).length })), templates: S.meetingTemplates, hotwords: S.hotwords }));
  on('POST', '/api/apps/meeting/meetings', (b) => { const m = { id: nid('MT'), title: b.title || '未命名会议', type: b.type || '企业座谈会', date: b.date || now(), duration: b.duration || '18:32', place: b.place || '—', host: me().name, participants: b.participants && b.participants.length ? b.participants : [me().name], file: b.file || '现场录音.m4a', size: b.size || '12.4 MB', status: 'new', source: b.source || '网页上传' }; S.meetings.unshift(m); return { item: m }; });
  on('POST', '/api/apps/meeting/meetings/:id/transcribe', (b, p) => { const m = S.meetings.find((x) => x.id === p.id); if (b.type) m.type = b.type; if (b.title) m.title = b.title; m.status = 'running'; const j = { id: nid('JOB'), kind: 'transcribe', ref: m.id, started: Date.now(), status: 'running' }; S.jobs[j.id] = j; m.jobId = j.id; audit('会议记录', `转写 · ${m.title.slice(0, 12)}`, 'SenseVoice（本地）'); return { job: jobState(j) }; });
  on('GET', '/api/v1/jobs/:id', (b, p) => { const j = S.jobs[p.id]; if (!j) err(404, 'NOT_FOUND', '任务不存在'); return { job: jobState(j) }; });
  on('GET', '/api/apps/meeting/meetings/:id', (b, p) => { const m = S.meetings.find((x) => x.id === p.id); if (!m) err(404, 'NOT_FOUND', '会议不存在'); return { item: m, minutes: m.status === 'done' ? (m.minutesEdited || minutesOf(m)) : null }; });
  on('PATCH', '/api/apps/meeting/meetings/:id', (b, p) => { const m = S.meetings.find((x) => x.id === p.id);
    if (b.renameSpeaker) { const { from, to } = b.renameSpeaker; m.transcript.forEach((l) => { if (l[1] === from) l[1] = to; }); }
    if (b.todo) { const t = m.todos.find((x) => x.id === b.todo.id); Object.assign(t, b.todo); if (t.owner !== '待确认' && t.due !== '待确认') t.certain = true; }
    if (b.minutes) m.minutesEdited = b.minutes;
    if (b.line) { m.transcript[b.line.index][2] = b.line.text; }
    return { item: m, minutes: m.minutesEdited || minutesOf(m) }; });
  on('POST', '/api/apps/meeting/meetings/:id/todos/commit', (b, p) => { const m = S.meetings.find((x) => x.id === p.id); const done = [];
    m.todos.forEach((t) => { if (b.ids.includes(t.id)) { if (t.owner === '待确认') return; t.status = '已派发'; S.myTodos.unshift({ id: t.id, task: t.task, owner: t.owner, due: t.due, from: m.title, app: 'meeting', done: false }); done.push(t.id); } });
    S.inbox.forEach((i) => { if (i.type === 'todo' && i.ref === m.id) i.status = 'done'; });
    audit('会议记录', `派发待办 ${done.length} 条`); return { committed: done, skipped: b.ids.filter((x) => !done.includes(x)) }; });
  on('POST', '/api/apps/meeting/meetings/:id/link', (b, p) => { const m = S.meetings.find((x) => x.id === p.id); const e = ent(b.entId); const iss = { id: nid('IS'), entId: e.id, title: b.title || `${m.title}中提出的诉求`, from: '会议', created: '2026-11-17', owner: me().name, status: '办理中', due: '2026-11-30', next: '按纪要跟进', steps: [['2026-11-17', `由会议「${m.title}」纪要关联`]] }; S.issues.unshift(iss); return { issue: iss }; });
  // 公文协作
  on('GET', '/api/apps/document/templates', () => ({ items: S.docTemplates, groups: [['A', '发布政策与安排'], ['B', '面向企业组织事项'], ['C', '公开结果与回应']] }));
  on('GET', '/api/apps/document/documents', () => ({ items: Object.values(S.drafts).map(docSummary).sort((a, b) => b.updated.localeCompare(a.updated)) }));
  on('POST', '/api/apps/document/drafts', (b) => { const t = S.docTemplates.find((x) => x.id === b.templateId); const c = genDoc(t, b.inputs || {}); if (b.extra) c.paragraphs.push(...b.extra); const id = nid('DOC'); S.drafts[id] = { id, title: c.title, templateId: t.id, policyId: (b.inputs || {}).policy, status: '草稿', author: me().name, versions: [{ v: 1, at: now(), by: me().name + '（AI 初稿）', content: c }], comments: [], refs: b.refs || [] }; audit('公文协作', `生成初稿 · ${t.name}`, 'Qwen4-Max'); return { item: S.drafts[id] }; });
  on('GET', '/api/apps/document/drafts/:id', (b, p) => { const d = S.drafts[p.id]; if (!d) err(404, 'NOT_FOUND', '文稿不存在'); return { item: d }; });
  on('PUT', '/api/apps/document/drafts/:id', (b, p) => { const d = S.drafts[p.id]; if (d.status === '已定稿') err(409, 'LOCKED', '已定稿文稿不能修改，请另存新稿'); d.versions.push({ v: d.versions.length + 1, at: now(), by: me().name + (b.note ? '（' + b.note + '）' : ''), content: b.content }); d.title = b.content.title; if (d.status === '审签中' || d.status === '已退回') d.status = '草稿'; return { item: d }; });
  on('POST', '/api/apps/document/drafts/:id/check', (b, p) => { const d = S.drafts[p.id]; const c = d.versions[d.versions.length - 1].content; return { issues: checkDoc({ ...c, templateId: d.templateId, policyId: d.policyId }) }; });
  on('POST', '/api/apps/document/drafts/:id/fix', (b, p) => { const d = S.drafts[p.id]; const c = clone(d.versions[d.versions.length - 1].content);
    (b.ids || []).forEach((id) => { if (id === 'c1') c.docNo = '京技产促〔2026〕58号'; const m = /^c-([dts])(\d+)$/.exec(id); if (m) { const i = +m[2]; if (m[1] === 'd') c.paragraphs[i] = c.paragraphs[i].replace(/(\d{4})-(\d{2})-(\d{2})/g, (s, y, mo, da) => `${+y}年${+mo}月${+da}日`); if (m[1] === 't') c.paragraphs[i] = c.paragraphs[i].replace('的的', '的').replace('申报申报', '申报').replace('载止', '截止').replace('截至日期', '截止日期'); if (m[1] === 's') c.paragraphs[i] = polishText(c.paragraphs[i], 'formal'); } if (id === 'c-ni') c.title = c.title.replace('关于', '关于拟'); if (id === 'c-bb') c.paragraphs.push('除上述调整外，原通知其他事项不变。'); });
    d.versions.push({ v: d.versions.length + 1, at: now(), by: me().name + '（一键修正）', content: c }); return { item: d, issues: checkDoc({ ...c, templateId: d.templateId, policyId: d.policyId }) }; });
  on('POST', '/api/apps/document/drafts/:id/polish', (b, p) => { const d = S.drafts[p.id]; const c = clone(d.versions[d.versions.length - 1].content); const before = c.paragraphs.join('\n'); const idx = b.para == null ? c.paragraphs.map((_, i) => i) : [b.para]; idx.forEach((i) => { c.paragraphs[i] = polishText(c.paragraphs[i], b.style || 'formal'); }); const after = c.paragraphs.join('\n'); return { preview: c, parts: diff(before, after), changed: before !== after }; });
  on('POST', '/api/apps/document/compare', (b) => { const get = (x) => { if (typeof x === 'string') return x; const d = S.drafts[x.id]; const v = d.versions.find((y) => y.v === x.v) || d.versions[d.versions.length - 1]; return docText(v.content); }; const a = get(b.a), c = get(b.b); const parts = diff(a, c); return { parts, stats: { add: parts.filter((x) => x.op === 'add').reduce((s, x) => s + x.t.length, 0), del: parts.filter((x) => x.op === 'del').reduce((s, x) => s + x.t.length, 0) } }; });
  on('POST', '/api/apps/document/drafts/:id/comments', (b, p) => { const d = S.drafts[p.id]; const c = { id: nid('cm'), para: b.para, by: me().name, at: now(), text: b.text, replies: [], resolved: false }; d.comments.push(c); return { item: c }; });
  on('PATCH', '/api/apps/document/drafts/:id/comments/:cid', (b, p) => { const d = S.drafts[p.id]; const c = d.comments.find((x) => x.id === p.cid); if (b.reply) c.replies.push({ by: me().name, text: b.reply }); if (b.resolved !== undefined) c.resolved = b.resolved; return { item: c }; });
  on('POST', '/api/apps/document/drafts/:id/submit', (b, p) => { const d = S.drafts[p.id]; const errs = checkDoc({ ...d.versions[d.versions.length - 1].content, templateId: d.templateId, policyId: d.policyId }).filter((x) => x.level === 'error'); if (errs.length) err(422, 'CHECK_FAILED', `还有 ${errs.length} 处必须修改的问题，先在“核查”里处理`); d.status = '审签中'; const r = { id: nid('R'), type: 'review', app: 'document', title: '审签：' + d.title, meta: `公文协作 · ${me().name}提交 · 第 ${d.versions.length} 版`, ref: d.id, status: 'pending', approver: true, assignee: b.assignee || '李阳' }; S.inbox.unshift(r); audit('公文协作', `送审签 · ${d.title.slice(0, 14)} v${d.versions.length}`); return { item: d, review: r }; });
  on('GET', '/api/apps/document/drafts/:id/export', (b, p) => { const d = S.drafts[p.id]; const c = d.versions[d.versions.length - 1].content; const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>${c.title}</title><style>body{font-family:仿宋_GB2312,FangSong,serif;font-size:16pt;line-height:28pt}h1{font-family:方正小标宋简体,SimSun;font-size:22pt;text-align:center}.no{text-align:center}.sign{text-align:right}</style></head><body>${d.status !== '已定稿' ? '<p style="color:#c00">【未定稿 · 仅供内部讨论】</p>' : ''}<p class="no">${c.docNo}</p><h1>${c.title}</h1><p>${c.to}</p>${c.paragraphs.map((x) => `<p>　　${x}</p>`).join('')}<p class="sign">${c.sign}</p><p class="sign">${c.date}</p></body></html>`; audit('公文协作', `导出 Word · ${c.title.slice(0, 14)}`); return { filename: c.title + '.doc', html, final: d.status === '已定稿' }; });
  // 审签 / 等我确认（复用卫华 reviews）
  on('GET', '/api/v1/reviews', () => ({ items: S.inbox }));
  on('POST', '/api/v1/reviews/:id/decisions', (b, p) => { const r = S.inbox.find((x) => x.id === p.id); if (r.approver && !can(r.app, 'approve')) err(403, 'FORBIDDEN', '需要审签权限：请用审签领导账号（如 李阳）处理'); r.status = b.decision === 'approve' ? 'done' : 'rejected'; r.reason = b.reason;
    if (r.type === 'review') { const d = S.drafts[r.ref]; d.status = b.decision === 'approve' ? '已定稿' : '已退回'; if (b.decision === 'approve') d.versions[d.versions.length - 1].content.docNo = d.versions[d.versions.length - 1].content.docNo.replace('【待补】', '58'); }
    if (r.type === 'skill') { const s = S.skills.find((x) => x.id === r.ref); s.status = b.decision === 'approve' ? 'published' : 'draft'; s.visibility = b.decision === 'approve' ? 'recommended' : 'team'; }
    audit(r.app === 'document' ? '公文协作' : '技能中心', `${b.decision === 'approve' ? '通过' : '退回'} · ${r.title.slice(0, 16)}`); return { item: r }; });
  on('GET', '/api/v1/todos', () => ({ items: S.myTodos }));
  on('PATCH', '/api/v1/todos/:id', (b, p) => { const t = S.myTodos.find((x) => x.id === p.id); Object.assign(t, b); return { item: t }; });
  // 资料库（NAS 归集 + 检索）
  on('GET', '/api/v1/kb/libraries', () => ({ items: S.libraries.map((l) => ({ ...l, files: S.files.filter((f) => f.lib === l.id).length })) }));
  on('GET', '/api/v1/kb/files', (b, p, q) => { let items = S.files; if (q.lib) items = items.filter((f) => f.lib === q.lib); if (q.q) items = items.filter((f) => (f.name + f.tags.join('')).includes(q.q)); if (q.sort === 'cited') items = items.slice().sort((a, c) => c.cited - a.cited); return { items, total: items.length }; });
  on('POST', '/api/v1/kb/files', (b) => { const f = { id: nid('F'), lib: b.lib || 'policy', name: b.name, size: b.size || '—', updated: '2026-11-17', cited: 0, tags: b.tags || ['新上传'], status: '解析中', version: 'v1', snippet: b.snippet || '' }; S.files.unshift(f); const j = { id: nid('JOB'), kind: 'parse', ref: f.id, started: Date.now(), status: 'running' }; S.jobs[j.id] = j; audit('资料库', `上传 · ${b.name.slice(0, 16)}`, 'MinerU（本地）'); return { item: f, job: jobState(j) }; });
  on('POST', '/api/v1/kb/search', (b) => ({ hits: kbSearch(b.q) }));
  on('GET', '/api/v1/kb/files/:id', (b, p) => { if (p.id.startsWith('POL:')) { const x = pol(p.id.slice(4)); return { item: { id: p.id, name: pdoc(x.doc).title, no: pdoc(x.doc).no, clause: x.clause, text: x.original, state: pdoc(x.doc).state, verifiedAt: x.verifiedAt, versionNote: x.versionNote } }; } const f = S.files.find((x) => x.id === p.id); return { item: { ...f, text: f.snippet || '（演示：文件全文在 NAS 中，正式环境可在线预览并定位页码）' } }; });
  // 技能中心 / 造应用（复用卫华 builder：对话 → 需求包 → 试跑 → 发布）
  on('GET', '/api/v1/skills', () => ({ items: S.skills, apps: S.apps }));
  on('POST', '/api/v1/builder/sessions', (b) => {
    const t = b.prompt || ''; const base = detectIntent(t); const baseApp = S.apps.find((a) => a.id === base) || S.apps[0];
    const name = (t.match(/(?:做一个|帮我做|想要一个|创建)(.{2,12}?)(?:的技能|技能|助手|$|，|。)/) || [])[1] || (t.slice(0, 10) + '助手');
    const libs = S.libraries.filter((l) => t.includes(l.name.slice(0, 2)) || l.id === baseApp.id).map((l) => l.name);
    const spec = { id: 'sk-' + Date.now().toString(36), name: name.trim(), icon: name.trim()[0], summary: `当用户${t.slice(0, 30)}时使用。`, base: baseApp.id, steps: ['读懂用户提供的材料或问题', `调用「${baseApp.name}」的工具获取依据`, '按固定格式输出，并标出待确认项', '每个结论附出处'], refs: libs.length ? libs : ['政策法规库'], tools: baseApp.tools.slice(0, 2), starters: [`${t.slice(0, 14)}…`, '给我一个示例'], output: '分点输出：结论 / 依据 / 待确认 / 下一步', visibility: 'private',
      skillMd: `---\nname: ${'skill-' + Date.now().toString(36)}\ndescription: 当用户${t.slice(0, 30)}时使用。\nmetadata:\n  jkq.title: ${name.trim()}\n  jkq.base_app: ${baseApp.id}\n  jkq.allowed_tools: [${baseApp.tools.slice(0, 2).join(', ')}]\n  jkq.citation: required\n  jkq.visibility: private\n---\n# ${name.trim()}\n## 步骤\n1. 读懂用户材料\n2. 调用 ${baseApp.name} 获取依据\n3. 按格式输出，标出待确认项\n` };
    const sid = nid('BS'); S.builder[sid] = { id: sid, spec }; return { session: sid, spec };
  });
  on('POST', '/api/v1/builder/sessions/:id/test', (b, p) => { const s = S.builder[p.id]; const r = chatReply(b.input || s.spec.starters[0], { app: s.spec.base }); return { output: { content: `【${s.spec.name}】\n${r.content}`, cards: r.cards, citations: r.citations }, checks: [{ name: '格式', ok: true }, { name: '敏感信息', ok: true }, { name: '资料权限', ok: true }] }; });
  on('POST', '/api/v1/skills', (b) => { const sp = b.spec; const sk = { id: sp.id, name: sp.name, icon: sp.icon, kind: 'skill', author: me().name, authorId: me().id, visibility: b.visibility || 'private', version: '1.0.0', uses: 0, rating: 0, summary: sp.summary, base: sp.base, status: b.visibility === 'recommended' ? 'in_review' : 'published' }; S.skills.unshift(sk); if (b.visibility === 'recommended') S.inbox.unshift({ id: nid('R'), type: 'skill', app: 'skills', title: '技能上架申请：' + sk.name, meta: `技能中心 · ${me().name}`, ref: sk.id, status: 'pending', approver: true }); audit('技能中心', `发布技能 · ${sk.name}（${b.visibility}）`); return { item: sk }; });
  on('POST', '/api/v1/skills/:id/fork', (b, p) => { const s = S.skills.find((x) => x.id === p.id); const f = { ...clone(s), id: s.id + '-fork' + (++S.seq), name: s.name + '（我的改编）', author: me().name, authorId: me().id, visibility: 'private', version: '1.0.0', uses: 0, rating: 0, source: s.id + '@' + s.version, status: 'published' }; S.skills.unshift(f); s.forks = (s.forks || 0) + 1; return { item: f }; });
  on('PATCH', '/api/v1/skills/:id', (b, p) => { const s = S.skills.find((x) => x.id === p.id); Object.assign(s, b); return { item: s }; });
  on('POST', '/api/v1/skills/:id/rate', (b, p) => { const s = S.skills.find((x) => x.id === p.id); s.myRating = b.useful; return { item: s }; });
  // 管理
  on('GET', '/api/v1/admin/usage', () => ({ usage: S.usage, audit: S.audit.slice(0, 30), seats: S.org }));
  on('GET', '/api/v1/audit', () => ({ items: S.audit }));
  on('GET', '/api/v1/feed', () => ({ items: S.feed }));

  // 小应用工具调用（对话编排 / 自建技能通过它调用官方应用能力；与界面同一套权限和留痕）
  function callSync(method, path, body) { const [pp, q] = parseQuery(path); const r = routes.find((x) => x.method === method && x.re.test(pp)); return r.fn(body || {}, pp.match(r.re).groups || {}, q); }
  const TOOLS = {
    'policy.search': (a) => callSync('GET', '/api/apps/policy/items?q=' + encodeURIComponent(a.q || '')),
    'policy.match': (a) => callSync('POST', '/api/apps/policy/match', a),
    'policy.calc': (a) => callSync('POST', '/api/apps/policy/calc', a),
    'policy.notice': (a) => callSync('POST', '/api/apps/policy/notice', a),
    'enterprise.search': (a) => callSync('GET', '/api/apps/enterprise/companies?q=' + encodeURIComponent(a.q || '')),
    'enterprise.get': (a) => callSync('GET', '/api/apps/enterprise/companies/' + a.id),
    'enterprise.propose_update': (a) => callSync('POST', `/api/apps/enterprise/companies/${a.id}/visits`, a),
    'enterprise.issues': (a) => callSync('GET', '/api/apps/enterprise/issues' + (a.entId ? '?entId=' + a.entId : '')),
    'enterprise.alerts': () => callSync('GET', '/api/apps/enterprise/alerts'),
    'meeting.list': () => callSync('GET', '/api/apps/meeting/meetings'),
    'meeting.transcribe': (a) => callSync('POST', `/api/apps/meeting/meetings/${a.id}/transcribe`, a),
    'meeting.summarize': (a) => callSync('GET', '/api/apps/meeting/meetings/' + a.id),
    'meeting.commit_todos': (a) => callSync('POST', `/api/apps/meeting/meetings/${a.id}/todos/commit`, a),
    'document.templates': () => callSync('GET', '/api/apps/document/templates'),
    'document.draft': (a) => callSync('POST', '/api/apps/document/drafts', a),
    'document.polish': (a) => a.text ? { text: polishText(a.text, a.style) } : callSync('POST', `/api/apps/document/drafts/${a.id}/polish`, a),
    'document.check': (a) => callSync('POST', `/api/apps/document/drafts/${a.id}/check`),
    'document.compare': (a) => callSync('POST', '/api/apps/document/compare', a),
    'kb.search': (a) => callSync('POST', '/api/v1/kb/search', a),
  };
  on('GET', '/api/v1/tools', () => ({ items: Object.keys(TOOLS).map((k) => ({ name: k, app: k.split('.')[0], write: /propose_update|commit_todos|draft|notice|transcribe/.test(k) })) }));
  on('POST', '/api/v1/apps/:id/tools/:tool', (b, p) => { const name = p.tool.includes('.') ? p.tool : p.id + '.' + p.tool; const f = TOOLS[name]; if (!f) err(404, 'TOOL_NOT_FOUND', '工具不存在：' + name); return { tool: name, result: f(b.args || {}) }; });

  function parseQuery(path) { const [p, qs] = path.split('?'); const q = {}; if (qs) new URLSearchParams(qs).forEach((v, k) => (q[k] = v)); return [p, q]; }
  const listeners = []; const loadHooks = [];
  window.JKAPI = {
    latency: 260,
    request(method, path, body) {
      const [p, q] = parseQuery(path);
      return new Promise((resolve, reject) => {
        setTimeout(() => {
          try {
            if (window.JKAPI.guard) window.JKAPI.guard(method, p, body || {});
            const r = routes.find((x) => x.method === method && x.re.test(p));
            if (!r) err(404, 'NO_ROUTE', `未实现的接口 ${method} ${p}`);
            const params = (p.match(r.re).groups) || {};
            const out = r.fn(body || {}, params, q);
            if (method !== 'GET') { save(); listeners.forEach((f) => f(method, p)); }
            resolve(clone(out));
          } catch (e) { reject(e); }
        }, method === 'GET' ? Math.min(120, this.latency) : this.latency);
      });
    },
    get: (p) => window.JKAPI.request('GET', p), post: (p, b) => window.JKAPI.request('POST', p, b), put: (p, b) => window.JKAPI.request('PUT', p, b), patch: (p, b) => window.JKAPI.request('PATCH', p, b), del: (p) => window.JKAPI.request('DELETE', p),
    onChange: (f) => listeners.push(f),
    reset() { localStorage.removeItem(KEY); load(); loadHooks.forEach((f) => f(S)); save(); listeners.forEach((f) => f('RESET', '')); },
    /* 扩展点：账号权限模块（assets/auth.js）通过它注册路由、读写状态，不改本文件 */
    ext: { on, first: (m, pt, fn) => { on(m, pt, fn); routes.unshift(routes.pop()); }, err, state: () => S, me, can, roleOf, audit, save, clone, nid, now },
    onLoad(f) { loadHooks.push(f); f(S); save(); },
    guard: null,
    setFast(v) { S.demoFast = v; window.JKAPI.latency = v ? 90 : 260; },
    state: () => S, util: { fmtMoney, cnDate, diff, docText },
    routes: () => routes.map((r) => r.method + ' ' + r.re.source),
  };
  load();
})();
/* ===== 对外别名与便捷函数（供三版原型统一调用） ===== */
(function () {
  const A = window.JKAPI;
  window.MOCK = window.JK_DATA;            // 初始种子数据（只读参考）
  const M = Object.assign(A, {
    /** 当前运行态（含用户修改，已持久化到 localStorage） */
    db: () => A.state(),
    /** 流式对话：逐段回调 onDelta(textSoFar)，结束 resolve 完整结果 {conversation,user,reply} */
    async chatStream(convId, text, opts = {}, onDelta) {
      const r = await A.post(`/api/v1/conversations/${convId}/messages`, { text, model: opts.model, app: opts.app, files: opts.files });
      const full = r.reply.content; let i = 0;
      await new Promise((res) => { const tick = () => { i += Math.max(2, Math.round(full.length / 25)); onDelta && onDelta(full.slice(0, Math.min(i, full.length)), i >= full.length); if (i >= full.length) return res(); setTimeout(tick, 25); }; tick(); });
      return r;
    },
    /** 轮询长任务直到完成，onProgress(job) */
    async waitJob(jobId, onProgress) { for (;;) { const { job } = await A.get('/api/v1/jobs/' + jobId); onProgress && onProgress(job); if (job.status === 'done') return job; await new Promise((r) => setTimeout(r, 400)); } },
  });
  window.MockAPI = M;
})();

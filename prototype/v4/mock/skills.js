/* 技能中心 · 模拟后端（mock 模式加载；http 模式由真实后端 builder/skills 服务实现同名接口）
 * 第一部分：技能引擎（起草 / 执行 / 匹配 / 生成清单）；第二部分：路由。 */
/* =====================================================================
 * 技能引擎（纯逻辑，不碰界面）：
 *   draft(说法)        → AI 起草技能清单（名称/触发语/输入项/步骤/模型/知识库/输出）
 *   run(skill, 输入)   → 按模板逐步执行：查知识库 → 调应用工具 → 模型生成（模拟）→ 输出
 *   match(一句话)      → 用触发语匹配技能（供对话框直接调用自制技能）
 *   toManifest(skill)  → 生成平台小应用 app.json（“升级为小应用”）
 * 【可改】DRAFT_RULES 决定 AI 起草时怎么猜分类、输入项、模型和知识库。
 * ===================================================================== */
(function () {
  const A = window.JKAPI; if (!A) return;

  /* ---------- 起草规则（关键词 → 推断），从上往下第一条命中为准 ---------- */
  const DRAFT_RULES = {
    cat: [[/电脑|网站|系统|平台|登录|填报|填月报|直报|网页|下载/, '电脑操作'], [/政策|补贴|申报|兑现|奖励|资金/, '政策'], [/会议|纪要|周报|例会|座谈/, '会议'], [/公文|通知|请示|函|起草|讲话|简报/, '公文'], [/企业|走访|台账|诉求|一企一档/, '企业'], [/数据|统计|报表|指标/, '数据']],
    catDefault: '知识',
    model: { 政策: 'deepseek-v4-pro', 企业: 'local-qwen-32b', 会议: 'qwen4-max', 公文: 'qwen4-max', 数据: 'deepseek-v4.1-flash', 电脑操作: 'local-qwen-32b', 知识: 'deepseek-v4.1-flash' },
    kb: { 政策: ['政策库'], 企业: ['政策库'], 会议: ['会议纪要'], 公文: ['公文范文', '政策库'], 数据: ['政策库'], 电脑操作: ['政策库'], 知识: ['政策库'] },
    base: { 政策: 'policy', 企业: 'enterprise', 会议: 'meeting', 公文: 'document', 数据: 'kb', 电脑操作: 'computer', 知识: 'kb' },
    output: [[/对比|比较|表格|列表|汇总表/, '表格'], [/材料|清单|核对|检查|齐不齐|缺/, '清单'], [/公文|通知|周报|报告|函|讲话|简报/, '公文']],
    outputDefault: '要点',
  };
  const ICON_HINT = { 政策: '策', 企业: '企', 会议: '会', 公文: '文', 数据: '数', 电脑操作: '填', 知识: '知' };

  function draft(text) {
    const t = String(text || '').trim();
    const cat = (DRAFT_RULES.cat.find(([re]) => re.test(t)) || [, DRAFT_RULES.catDefault])[1];
    const format = (DRAFT_RULES.output.find(([re]) => re.test(t)) || [, DRAFT_RULES.outputDefault])[1];
    const nm = nameOf(t); let name = nm.name;
    if (name.length < 2) name = cat + '小助手';
    const inputs = [];
    if (/企业|公司|走访|书店|一企一档/.test(t)) inputs.push({ key: 'ent', label: '哪家企业', type: 'enterprise', required: true, sample: /书店/.test(t) ? 'E001' : 'E002' });
    if (/会议|纪要|周报/.test(t)) inputs.push({ key: 'week', label: '时间范围', type: 'text', required: true, sample: '本周（11.16—11.20）' });
    if (/金额|多少钱|房租|投入|采购额/.test(t)) inputs.push({ key: 'amount', label: '金额（元）', type: 'number', required: false, sample: '480000' });
    if (/月报|统计|月份/.test(t)) inputs.push({ key: 'month', label: '填报月份', type: 'text', required: true, sample: '2026 年 10 月' });
    inputs.push({ key: 'notes', label: /走访/.test(t) ? '走访记录' : /材料/.test(t) ? '已有材料（逐行写）' : '补充说明', type: 'textarea', required: !inputs.length, sample: sampleNotes(t, cat) });
    const kb = DRAFT_RULES.kb[cat].slice();
    const steps = [];
    if (cat === '政策' && inputs.find((i) => i.key === 'ent')) steps.push({ type: 'tool', tool: 'policy.match', args: { entId: '{{ent}}' }, label: '匹配兑现事项' });
    else if (inputs.find((i) => i.key === 'ent')) steps.push({ type: 'tool', tool: 'enterprise.get', args: { id: '{{ent}}' }, label: '读取企业档案' });
    if (cat === '会议') steps.push({ type: 'tool', tool: 'meeting.list', args: {}, label: '汇总会议记录' });
    if (cat !== '电脑操作') steps.push({ type: 'kb', query: keyPhrase(t, cat), space: kb[0], label: '查' + kb[0] });
    if (cat === '电脑操作') steps.push({ type: 'computer', task: /通知|下载/.test(t) ? 'notice' : /进度|状态/.test(t) ? 'status' : /申报/.test(t) ? 'apply' : 'stats', label: '打开系统替你操作' });
    steps.push({ type: 'model', label: { 表格: '整理成表格', 清单: '逐项核对', 公文: '写成正式文稿', 要点: '写结论和要点' }[format] });
    const title = name + (inputs.find((i) => i.key === 'ent') ? '：{{ent}}' : '');
    return {
      name, icon: name[0] || ICON_HINT[cat], summary: t.length > 40 ? t.slice(0, 38) + '…' : t, base: DRAFT_RULES.base[cat],
      spec: { cat, triggers: triggersOf(name, nm), inputs, steps, model: DRAFT_RULES.model[cat], kb, output: { format, title },
        prompt: `你是北京经开区的${cat}助手。任务：${t}\n请根据用户填写的信息（${inputs.map((i) => '{{' + i.key + '}}').join('、')}），参考知识库「${kb.join('、')}」，按“${format}”格式输出。先给结论，再给依据；每条依据标出处；信息不全时写“待确认”，不编造。` },
      questions: suggestQuestions(t, cat, format),
    };
  }
  function sampleNotes(t, cat) {
    if (/走访/.test(t)) return '计划扩租二层 400㎡ 做亲子阅读区；房租涨到 48 万/年；问房租补贴什么时候报。';
    if (/材料/.test(t)) return '数据产品采购合同\n发票及付款凭证\n营业执照';
    if (cat === '会议') return '书香里扩租诉求已对接；数据券延期通知已印发。';
    if (cat === '政策') return '企业想了解今年还能申请哪些支持。';
    return '（可不填）';
  }
  function keyPhrase(t, cat) { const m = t.match(/(数据券|房租|实体书店|算力|人才|首台套|备案|纪要|周报|通知|走访|诉求|统计)/g); return m ? [...new Set(m)].join(' ') : cat; }
  /* 名称：把口语需求压成 ≤12 字的名字，并找出“核心名词”做触发语 */
  function nameOf(t) {
    let s = t.replace(/^(帮我|请|我想|我要|能不能)?(做|造|制作|创建|新建)?(一个|个)?(技能|助手)?[：:，,\s]*/, '').replace(/^(去|到)/, '').replace(/一下/g, '');
    s = s.replace(/^(每周[一二三四五六日]?|每天|每月|每次)/, '').replace(/(的技能|技能|助手)$/, '').replace(/(齐不齐|对不对|是不是|吗|呢|[。.!！])$/, '').trim();
    let core = '', verb = '', m;
    const walk = /^走访(后|完企业)?[，,]?/.test(s); s = s.replace(/^走访(后|完企业)?[，,]?/, '');
    if ((m = s.match(/把(.+?)(整理|汇总|转换|转|生成|写)成(.+)$/))) { const src = (walk ? '走访' : '') + m[1].replace(/^(本周的?|今天的?|我随手记的|随手记的)/, ''); core = m[3]; verb = '整理'; s = src + (m[2] === '汇总' ? '汇总成' : '转') + m[3]; }
    else if ((m = s.match(/^(核对|检查|审核|预审|查询|查)(.+)$/))) { core = m[2]; verb = m[1] === '查' ? '查' : m[1]; s = m[2] + (m[1] === '查' ? '查询' : m[1]); }
    else core = s.slice(0, 8);
    if (s.length > 12) s = s.replace('汇总成', '→').replace(/转/, '→');
    if (s.length > 12) s = s.slice(0, 12);
    if (s.length <= 3) s += '助手';
    return { name: s, core: core.slice(0, 10), verb };
  }
  function triggersOf(name, nm) { return [...new Set([name, nm.core, nm.verb ? nm.verb + nm.core : ''].filter((x) => x && x.length >= 2))].slice(0, 3); }
  function triggersOld(name, t) { const a = [name]; const short = t.replace(/^(帮我|请|我想|我要)?(做一个|做个|创建|造一个)?/, '').slice(0, 14); if (short && short !== name) a.push(short); a.push('用' + name); return [...new Set(a)].slice(0, 3); }
  function suggestQuestions(t, cat, format) { const q = []; if (format !== '表格') q.push('改成表格输出'); if (!/企业/.test(t)) q.push('加一个“哪家企业”'); q.push('只用本地模型'); return q.slice(0, 3); }

  /* ---------- 模板 ---------- */
  const fill = (tpl, vars) => String(tpl || '').replace(/\{\{(\w+)\}\}/g, (_, k) => (vars[k] != null && vars[k] !== '' ? vars[k] : '（未填）'));

  /* ---------- 执行 ---------- */
  async function run(skill, inputs, { onStep } = {}) {
    const api = A; const spec = skill.spec; const S = A.state();
    const vars = {}; const raw = inputs || {}; const ent = raw.ent ? S.enterprises.find((e) => e.id === raw.ent || e.name === raw.ent || e.short === raw.ent) : null;
    spec.inputs.forEach((i) => { vars[i.key] = i.type === 'enterprise' ? (ent ? ent.short : raw[i.key] || '') : raw[i.key]; });
    const ctxOut = { hits: [], tool: null, toolName: '', missing: spec.inputs.filter((i) => i.required && !raw[i.key]).map((i) => i.label), computer: null };
    for (let i = 0; i < spec.steps.length; i++) {
      const st = spec.steps[i]; onStep && onStep(i, 'run');
      await new Promise((r) => setTimeout(r, A.latency > 150 ? 420 : 120));
      try {
        if (st.type === 'kb') {
          const q = fill(st.query, vars).replace(/（未填）/g, '') || skill.name;
          const SPACE_ID = { 政策库: 'policy', 政策文件: 'policy', 公文范文: 'template', 公文范本: 'template', 会议纪要: 'minutes', 部门制度: 'rules', 内部制度: 'rules' };
          const r = await api.post('/api/v1/kb/search', Object.assign({ q, limit: 4 }, SPACE_ID[st.space] ? { space: SPACE_ID[st.space] } : {}));
          const hits = (r.hits || r.items || []).slice(0, 4).map((h) => ({ id: h.id || h.fileId, title: h.title || h.name, snippet: h.snippet || '', space: h.space || h.lib, source: h.source || {} }));
          ctxOut.hits.push(...hits.filter((h) => !ctxOut.hits.find((x) => x.id === h.id)));
        } else if (st.type === 'tool') {
          const args = {}; Object.entries(st.args || {}).forEach(([k, v]) => { args[k] = String(v).replace(/\{\{(\w+)\}\}/g, (_, kk) => raw[kk] || ''); });
          if (Object.values(args).some((v) => v === '') ) { ctxOut.toolSkipped = st.tool; }
          else { const [app, tool] = st.tool.split('.'); const r = await api.post(`/api/v1/apps/${app}/tools/${tool}`, { args }); ctxOut.tool = r.result; ctxOut.toolName = st.tool; }
        } else if (st.type === 'computer') {
          ctxOut.computer = { task: st.task, ent: raw.ent };
        }
      } catch (e) { ctxOut.errors = (ctxOut.errors || []).concat(st.label + '：' + (e.message || e)); }
      onStep && onStep(i, 'done');
    }
    if (ent) { const e = ent; vars.ent = e.short; }
    const title = fill(spec.output.title, vars);
    const markdown = compose(skill, vars, ent, ctxOut, title);
    let cits = ctxOut.hits.map((h, n) => ({ n: n + 1, ...h })); const used = cits.filter((c) => markdown.includes(`[${c.n}]`)); if (used.length) cits = used; // 只列正文里真正引用到的出处
    return { title, markdown, citations: cits, missing: ctxOut.missing, model: modelName(spec.model), computer: ctxOut.computer };
  }
  function modelName(id) { const m = (A.state().models || []).find((x) => x.id === id); return m ? m.name : '自动选择'; }

  /* 模拟“模型生成”：按输出格式，用输入 + 工具结果 + 知识库片段确定性地拼出结果（每条依据带 [n]） */
  function compose(skill, vars, ent, o, title) {
    const fmt = skill.spec.output.format; const L = [];
    const cite = (i) => (o.hits[i] ? ` [${i + 1}]` : '');
    const clip = (s, n) => { s = String(s || '').replace(/\s+/g, ' '); return s.length > n ? s.slice(0, n) + '…' : s; };
    let lead = '';
    const tr = o.tool;
    if (o.toolName === 'policy.match' && tr && tr.results) {
      const money = (n) => (n >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, '') + ' 万元' : n + ' 元');
      // 只看与技能主题相关的事项（如“实体书店”），避免把全区上百项都算进去
      const GEN = /政策|预判|助手|核对|申报|企业|支持|补贴|奖励|项目|整理|材料|看看/g;
      const core = String(skill.name + ' ' + (skill.spec.steps || []).filter((x) => x.type === 'kb').map((x) => x.query).join(' ')).replace(GEN, ' ');
      const grams = []; (core.match(/[\u4e00-\u9fa5]{2,}/g) || []).forEach((w) => { for (let i = 0; i + 2 <= w.length; i++) grams.push(w.slice(i, i + 2)); });
      const live = tr.results.filter((r) => r.level !== 'no' && !r.ended);
      let rel = live.filter((r) => grams.some((g) => (r.title + (r.category || '')).includes(g)));
      if (!rel.length) rel = live.slice(0, 5);
      const ok = rel.filter((r) => r.level === 'ok').slice(0, 5), pend = rel.filter((r) => r.level === 'check').slice(0, 3);
      const sum = ok.reduce((t, r) => t + ((r.calc && r.calc.kind !== 'ratio' && r.calc.amount) || 0), 0);
      lead = `**${vars.ent || '该企业'}**：相关事项可申报 **${ok.length} 项**${sum ? '，预计最高 **' + money(sum) + '**' : ''}${pend.length ? `；待确认 **${pend.length} 项**` : ''}。`;
      const items = ok.concat(pend).slice(0, 5);
      if (fmt === '表格') { L.push('| 事项 | 结论 | 依据 |', '|---|---|---|'); items.forEach((r) => L.push(`| ${r.title} | ${r.level === 'ok' ? (r.calc ? '预计 ' + money(r.calc.amount) : '可核对') : '待确认'} | ${r.doc} ${r.clause} |`)); }
      else items.forEach((r) => L.push(`- ${r.level === 'ok' ? '✓' : '?'} **${r.title}**${r.calc ? '：' + r.calc.text : ''}（${r.doc}）`));
    } else if (o.toolName === 'enterprise.get' && tr && tr.item) {
      const e = tr.item; lead = `**${e.short}** · ${e.industry} · ${e.scale} · 从业 ${e.employees} 人`;
      const notes = vars.notes || vars.issue || '';
      const parts = String(notes).split(/[；;。\n]/).map((x) => x.trim()).filter(Boolean);
      if (fmt === '表格') { L.push('| 类别 | 内容 | 原话依据 |', '|---|---|---|'); parts.slice(0, 5).forEach((p) => L.push(`| ${/诉求|需|协调|问/.test(p) ? '诉求' : /万|收入|采购|房租/.test(p) ? '经营变化' : /联系人|电话|经理/.test(p) ? '与台账不一致' : '基本情况'} | ${clip(p, 26)} | “${clip(p, 14)}” |`)); if (!parts.length) L.push('| 基本情况 | 档案已读取 | — |'); }
      else if (fmt === '清单') { L.push(`- [x] 企业名称：${e.name}`, `- [x] 统一社会信用代码：${e.creditCode}`, `- [x] 从业人数：${e.employees} 人`, `- [x] 上年营收：${e.revenue ? e.revenue.value + ' 万元' : '待补'}`, `- [ ] ${vars.month || '本月'}数据：待企业确认后提交`); }
      else parts.forEach((p) => L.push('- ' + clip(p, 40)));
    } else if (o.toolName === 'meeting.list' && tr && tr.items) {
      const ms = tr.items.slice(0, 4);
      lead = `本期共 **${ms.length} 场**会议，待办 **${ms.reduce((s, m) => s + (m.todoCount || 0), 0)} 条**。`;
      L.push('**一、本周完成**'); ms.slice(0, 2).forEach((m, i) => L.push(`${i + 1}. ${m.title}（${m.date}）`));
      L.push('**二、正在推进**'); ms.slice(2, 4).forEach((m, i) => L.push(`${i + 1}. ${m.title}：待办 ${m.todoCount || 0} 条跟进中`));
      if (vars.extra || vars.notes) L.push(`${ms.slice(2, 4).length + 1}. ${clip(vars.extra || vars.notes, 40)}`);
      L.push('**三、下周计划**', '1. 跟进未认领待办，周三前全部派发到人', '2. 汇总企业诉求办理进度');
    }
    if (o.hits.length && (fmt !== '公文' || !L.length)) {
      if (!lead) lead = `已在知识库找到 **${o.hits.length} 条**相关依据。`;
      if (fmt === '表格' && !L.length) { L.push('| 依据 | 要点 |', '|---|---|'); o.hits.slice(0, 4).forEach((h, i) => L.push(`| ${clip(h.title, 18)} [${i + 1}] | ${clip(h.snippet, 34)} |`)); }
      else if (fmt === '清单') { const have = String(vars.files || vars.notes || '').split('\n').map((x) => x.trim()).filter(Boolean); const need = ['数据产品采购合同', '交易平台成交凭证', '发票及付款凭证', '营业执照', '信用承诺书']; if (/材料|券/.test(skill.name + skill.spec.prompt)) { L.length = 0; lead = `材料 **${need.filter((n) => have.some((h) => n.includes(h.slice(0, 4)))).length}/${need.length}** 项已齐。`; need.forEach((n) => L.push(`- [${have.some((h) => n.includes(h.slice(0, 4))) ? 'x' : ' '}] ${n}${cite(0)}`)); } else o.hits.slice(0, 4).forEach((h, i) => L.push(`- [ ] ${clip(h.snippet, 36)} [${i + 1}]`)); }
      else if (fmt !== '表格') { L.push('**依据**'); o.hits.slice(0, 3).forEach((h, i) => L.push(`- ${clip(h.snippet, 44)} [${i + 1}]`)); }
    }
    if (!L.length && !lead) lead = '没有在知识库里找到直接依据，建议补充关键词后重试。';
    if (o.computer) L.push('', `已打开「电脑操作」执行填报，**提交前会停下来等你确认**。`);
    if (o.missing.length) L.push('', `**待确认**：${o.missing.join('、')}（未填写）`);
    if (o.toolSkipped) L.push(`> 未填写企业，已跳过“${o.toolSkipped}”。`);
    return [`### ${title}`, lead, '', ...L].join('\n').replace(/\n{3,}/g, '\n\n');
  }

  /* ---------- 对话匹配：触发语 / 名称 ---------- */
  function match(text, skills) {
    const t = String(text || ''); let best = null;
    (skills || A.state().skills).filter((s) => s.status === 'published' && s.spec).forEach((s) => {
      let sc = 0;
      if (t.includes(s.name)) sc = 1;
      (s.spec.triggers || []).forEach((g) => { if (t.includes(g)) sc = Math.max(sc, 0.9); else { const bi = [...Array(Math.max(0, g.length - 1))].map((_, i) => g.slice(i, i + 2)); const hit = bi.filter((b) => t.includes(b)).length; if (bi.length) sc = Math.max(sc, 0.7 * hit / bi.length); } });
      if (sc > 0.45 && (!best || sc > best.score)) best = { skill: s, score: +sc.toFixed(2) };
    });
    return best;
  }

  /* ---------- 升级为小应用：生成平台 apps/<id>/app.json ---------- */
  function toManifest(s) {
    const id = 'jkq-' + s.id.replace(/^sk-/, '');
    return {
      contract: 1, sdk: '1', id, name: s.name, summary: s.summary, sector: 'gov', kind: 'module', scenes: [], owner: s.authorId,
      actions: ['view', 'operate'], defaultRoles: { member: ['view', 'operate'], leader: ['view', 'operate', 'approve'], partner: s.share.scope === 'zone' ? ['view'] : [] },
      review: 'app', needsExternalData: s.spec.steps.some((x) => x.type === 'computer'), status: 'prototype',
      jkq: { fromSkill: s.id + '@' + s.version, tools: s.spec.steps.filter((x) => x.type === 'tool').map((x) => x.tool), kbSpaces: s.spec.kb, model: s.spec.model, starters: s.spec.triggers, inputs: s.spec.inputs.map((i) => ({ key: i.key, label: i.label, type: i.type, required: i.required })) },
    };
  }
  function toSkillMd(s) {
    return `---\nname: ${s.id}\ndescription: ${s.summary}\nmetadata:\n  jkq.title: ${s.name}\n  jkq.category: ${s.spec.cat}\n  jkq.version: ${s.version}\n  jkq.model: ${s.spec.model}\n  jkq.kb: [${s.spec.kb.join(', ')}]\n  jkq.triggers: [${s.spec.triggers.join(', ')}]\n  jkq.output: ${s.spec.output.format}\n  jkq.citation: required\n---\n# ${s.name}\n\n## 需要填写\n${s.spec.inputs.map((i) => `- ${i.label}（${i.key}，${i.type}${i.required ? '，必填' : ''}）`).join('\n')}\n\n## 步骤\n${s.spec.steps.map((x, i) => `${i + 1}. ${x.label}${x.tool ? '（' + x.tool + '）' : ''}${x.query ? '（检索：' + x.query + '）' : ''}`).join('\n')}\n\n## 提示词\n${s.spec.prompt || ''}\n`;
  }

  window.__JKSkillEngine = { draft, run, match, fill, toManifest, toSkillMd, compose, DRAFT_RULES };
})();

/* =====================================================================
 * 技能中心 · 模拟后端 + 种子技能（【可改】改下面 SEED_SPECS 即可改种子技能的“怎么做”）
 * 对应平台 builder（对话 → 需求包 → 试跑 → 发布）与 reviews（上架审核）。
 * 路由用 JKAPI.ext.first 注册，优先于 mock-api.js 里的旧 /api/v1/skills 路由。
 *
 * 技能清单（skill manifest）字段见 apps/skills/README.md
 * ===================================================================== */
(function () {
  const A = window.JKAPI; if (!A) return;
  const X = A.ext;

  /* ---------- 种子技能的完整定义（mock-data.js 里只有名字和简介，这里补齐“怎么做”） ---------- */
  const F = (key, label, type, o) => Object.assign({ key, label, type, required: true, sample: '' }, o || {});
  const SEED_SPECS = {
    'sk-shudian': { cat: '政策', dept: '企业服务处',
      triggers: ['书店能申请什么', '实体书店政策预判', '书店补贴'],
      inputs: [F('ent', '哪家书店', 'enterprise', { sample: 'E001' }), F('rent', '年房租（元）', 'number', { sample: '480000', required: false })],
      steps: [{ type: 'tool', tool: 'policy.match', args: { entId: '{{ent}}' }, label: '匹配兑现事项' }, { type: 'kb', query: '实体书店 房租 成本奖励', space: '政策库', label: '查政策原文' }, { type: 'model', label: '试算并写结论' }],
      model: 'deepseek-v4.1-flash', kb: ['政策库'], output: { format: '要点', title: '{{ent}} 政策预判' },
      prompt: '你是经开区政策兑现助手。根据企业「{{ent}}」的情况和年房租 {{rent}} 元，对照实体书店扶持政策，先给结论（能报几项、预计多少），再列条件核对，标出待确认项。只引用知识库原文，不编造。' },
    'sk-zoufang': { cat: '企业', dept: '企业服务处',
      triggers: ['走访记录整理', '把走访转成台账', '走访随记'],
      inputs: [F('ent', '走访的企业', 'enterprise', { sample: 'E002' }), F('notes', '走访记录（随手记的就行）', 'textarea', { sample: '计划扩建测试场地，需协调路测牌照；算力采购今年约 680 万；联系人换成孙经理。' })],
      steps: [{ type: 'tool', tool: 'enterprise.get', args: { id: '{{ent}}' }, label: '读取企业档案' }, { type: 'model', label: '整理五块档案' }],
      model: 'local-qwen-32b', kb: ['政策库'], output: { format: '表格', title: '{{ent}} 走访整理' },
      prompt: '把走访记录整理为：基本情况 / 经营变化 / 诉求 / 待办 / 与台账不一致处 五块，每条注明原话依据。敏感数据只走本地模型。' },
    'sk-zhoubao': { cat: '会议', dept: '综合科',
      triggers: ['处室周报', '整理本周周报', '周报'],
      inputs: [F('week', '哪一周', 'text', { sample: '2026 年第 46 周（11.9—11.15）' }), F('extra', '补充事项', 'textarea', { required: false, sample: '书香里扩租诉求已对接；数据券延期通知已印发。' })],
      steps: [{ type: 'tool', tool: 'meeting.list', args: {}, label: '汇总本周会议' }, { type: 'kb', query: '会议纪要 待办', space: '会议纪要', label: '查纪要原文' }, { type: 'model', label: '按三段写周报' }],
      model: 'qwen4-max', kb: ['会议纪要'], output: { format: '公文', title: '产业促进局处室周报（{{week}}）' },
      prompt: '按“本周完成 / 正在推进 / 下周计划”三段输出处室周报，每段不超过 5 条，数字准确，引用会议纪要原文。' },
    'sk-xinbanjiu': { cat: '公文', dept: '综合科',
      triggers: ['政策新旧对比', '两版政策有什么变化', '新旧版本对比'],
      inputs: [F('topic', '哪项政策', 'text', { sample: 'AI 原生产业创新高地政策' })],
      steps: [{ type: 'kb', query: '{{topic}}', space: '政策库', label: '找到两个版本' }, { type: 'model', label: '逐条列出变化' }],
      model: 'kimi-k3.1-pro', kb: ['政策库'], output: { format: '表格', title: '{{topic}} 新旧对比' },
      prompt: '找出同名政策的两个版本，按“条件 / 比例 / 封顶 / 期限”逐项对比，标注哪一版现行有效。' },
    'sk-suqiu': { cat: '政策', dept: '政策兑现科',
      triggers: ['诉求答复口径', '企业诉求怎么答复', '答复口径'],
      inputs: [F('ent', '哪家企业', 'enterprise', { sample: 'E005' }), F('issue', '企业的诉求', 'textarea', { sample: '询问生成式 AI 备案奖励怎么申请，数据券下一批什么时候开。' })],
      steps: [{ type: 'kb', query: '{{issue}}', space: '政策库', label: '查政策依据' }, { type: 'model', label: '写电话口径和书面要点' }],
      model: 'deepseek-v4-pro', kb: ['政策库'], output: { format: '要点', title: '{{ent}} 诉求答复口径' },
      prompt: '先给 3 句电话答复口径（口语、准确），再给书面答复要点，每条带政策依据；不确定的写“需进一步核实”。' },
    'sk-shuju': { cat: '数据', dept: '亦智数科（合作企业）',
      triggers: ['数据券材料预审', '数据券材料齐不齐'],
      inputs: [F('ent', '申报企业', 'enterprise', { sample: 'E003' }), F('files', '已有材料（逐行写）', 'textarea', { sample: '数据产品采购合同\n发票及付款凭证\n营业执照' })],
      steps: [{ type: 'kb', query: '数据券 申报材料', space: '政策库', label: '查材料清单' }, { type: 'model', label: '逐项核对缺什么' }],
      model: 'deepseek-v4.1-flash', kb: ['政策库'], output: { format: '清单', title: '{{ent}} 数据券材料预审' },
      prompt: '对照数据券申报材料清单，逐项标注 已有 / 缺少 / 需补充说明。' },
  };
  /* 额外种子：一个“电脑操作”类技能，演示技能可以调用电脑操作 */
  const EXTRA = [
    { id: 'sk-tongji', name: '统计月报自动填报', icon: '统', kind: 'skill', author: '周静', authorId: 'u-zhoujing', version: '1.1.0', uses: 96, rating: 4.7, status: 'published',
      summary: '登录统计直报平台，按台账数据填好月报，停在“提交”前等你确认。', base: 'computer',
      spec: { cat: '电脑操作', dept: '商务金融局', triggers: ['统计月报', '帮我填月报', '统计填报'],
        inputs: [F('ent', '哪家企业', 'enterprise', { sample: 'E001' }), F('month', '填报月份', 'text', { sample: '2026 年 10 月' })],
        steps: [{ type: 'tool', tool: 'enterprise.get', args: { id: '{{ent}}' }, label: '读取台账数据' }, { type: 'computer', task: 'stats', label: '打开统计平台填报' }],
        model: 'local-qwen-32b', kb: ['部门制度'], output: { format: '清单', title: '{{ent}} {{month}} 统计月报' },
        prompt: '用台账里的营收、从业人数填月报；提交前必须停下来让人确认。' } },
  ];
  const SHARE_DEFAULT = { 'sk-shudian': 'dept', 'sk-zoufang': 'dept', 'sk-zhoubao': 'zone', 'sk-xinbanjiu': 'dept', 'sk-suqiu': 'zone', 'sk-shuju': 'private', 'sk-tongji': 'zone' };

  function enrich(S) {
    S.skills = S.skills || [];
    EXTRA.forEach((x) => { if (!S.skills.find((s) => s.id === x.id)) S.skills.push(JSON.parse(JSON.stringify(x))); });
    S.skills.forEach((s) => {
      if (!s.spec) s.spec = JSON.parse(JSON.stringify(SEED_SPECS[s.id] || { cat: '知识', triggers: [s.name], inputs: [F('q', '要处理的内容', 'textarea')], steps: [{ type: 'kb', query: '{{q}}', label: '查知识库' }, { type: 'model', label: '生成结果' }], model: 'auto', kb: ['政策库'], output: { format: '要点', title: s.name } }));
      if (!s.share) s.share = { scope: SHARE_DEFAULT[s.id] || 'private', people: [], perm: 'use' };
      if (s.status === 'in_review') s.share.scope = 'zone';
      if (!s.versions) s.versions = [{ v: s.version, at: '2026-11-10', by: s.author, note: '首次发布' }].concat(s.version !== '1.0.0' ? [] : []);
      if (s.id === 'sk-zhoubao' && s.versions.length === 1) s.versions = [{ v: '1.0.0', at: '2026-09-02', by: '孙婷', note: '首次发布' }, { v: '2.0.0', at: '2026-10-15', by: '孙婷', note: '改为三段式输出' }, { v: '2.0.1', at: '2026-11-03', by: '孙婷', note: '数字核对更严格' }];
      if (s.ratingN == null) s.ratingN = Math.max(0, Math.round((s.uses || 0) / 9));
      if (!s.dept) s.dept = s.spec.dept;
    });
    /* 授权兜底：accounts.js 里旧名 market → skills；电脑操作只给局内角色 */
    const G = S.grants || {};
    Object.keys(G).forEach((r) => { if (G[r].market && !G[r].skills) G[r].skills = G[r].market.slice(); });
    if (G.member && !G.member.computer) G.member.computer = ['view', 'operate'];
    S.skillRuns = S.skillRuns || [];
  }
  A.onLoad(enrich);

  const S = () => X.state();
  const sk = (id) => { const s = S().skills.find((x) => x.id === id); if (!s) X.err(404, 'NOT_FOUND', '技能不存在'); return s; };
  const bump = (v, major) => { const p = (v || '1.0.0').split('.').map(Number); return major ? `${p[0] + 1}.0.0` : `${p[0]}.${p[1] + 1}.0`; };
  const canEdit = (s) => { const me = X.me(); return s.authorId === me.id || X.can('skills', 'admin') || (s.share.perm === 'edit' && visible(s)); };
  function visible(s) {
    const me = X.me(); if (!me) return false;
    if (s.authorId === me.id || X.can('skills', 'admin')) return true;
    if (s.status === 'in_review') return X.can('skills', 'approve');
    if (s.status !== 'published') return false;
    const sc = s.share.scope;
    if (sc === 'zone') return true;
    if (sc === 'dept') { const au = S().users.find((u) => u.id === s.authorId); return au && au.deptId === me.deptId; }
    if (sc === 'people') return (s.share.people || []).includes(me.id);
    return false;
  }
  const view = (s) => ({ ...s, mine: s.authorId === X.me().id, canEdit: canEdit(s) });

  X.first('GET', '/api/v1/skills', (b, p, q) => {
    let items = S().skills.filter(visible).map(view);
    if (q.mine) items = S().skills.filter((s) => s.authorId === X.me().id).map(view);
    if (q.review) items = S().skills.filter((s) => s.status === 'in_review').map(view);
    return { items, apps: S().apps };
  });
  X.first('GET', '/api/v1/skills/:id', (b, p) => { const s = sk(p.id); if (!visible(s)) X.err(403, 'FORBIDDEN', '这个技能没有分享给你'); return { item: view(s), runs: S().skillRuns.filter((r) => r.skillId === s.id).slice(0, 5) }; });
  /* 新建（草稿） */
  X.first('POST', '/api/v1/skills', (b) => {
    if (!X.can('skills', 'operate')) X.err(403, 'FORBIDDEN', '当前角色不能制作技能');
    const me = X.me(); const sp = b.spec || {};
    const s = { id: 'sk-' + Date.now().toString(36), name: b.name || '未命名技能', icon: (b.name || '技')[0], kind: 'skill', author: me.name, authorId: me.id, dept: (S().departments.find((d) => d.id === me.deptId) || {}).name,
      version: '0.1.0', uses: 0, rating: 0, ratingN: 0, summary: b.summary || '', base: b.base || 'kb', status: 'draft', share: { scope: 'private', people: [], perm: 'use' },
      versions: [{ v: '0.1.0', at: X.now(), by: me.name, note: b.forkOf ? '复制自 ' + b.forkOf : 'AI 起草' }], spec: sp, source: b.forkOf || '' };
    S().skills.unshift(s); X.audit('技能中心', `新建技能草稿 · ${s.name}`); return { item: view(s) };
  });
  /* 保存修改（已发布的技能保存 = 新版本） */
  X.first('PATCH', '/api/v1/skills/:id', (b, p) => {
    const s = sk(p.id); if (!canEdit(s)) X.err(403, 'FORBIDDEN', '你只有使用权限，可以“复制改一改”');
    ['name', 'summary', 'icon', 'base'].forEach((k) => b[k] != null && (s[k] = b[k]));
    if (b.spec) s.spec = b.spec;
    if (s.status === 'published' && b.spec) { s.version = bump(s.version); s.versions.push({ v: s.version, at: X.now(), by: X.me().name, note: b.note || '修改内容', spec: JSON.parse(JSON.stringify(b.spec)) }); }
    X.audit('技能中心', `保存技能 · ${s.name} v${s.version}`); return { item: view(s) };
  });
  /* 发布 + 分享范围（全区需审核） */
  X.first('POST', '/api/v1/skills/:id/publish', (b, p) => {
    const s = sk(p.id); if (!canEdit(s)) X.err(403, 'FORBIDDEN', '没有编辑权限');
    s.share = Object.assign({ scope: 'private', people: [], perm: 'use' }, b.share || s.share);
    if (s.status === 'draft' || s.status === 'rejected') { s.version = s.version.startsWith('0.') ? '1.0.0' : bump(s.version); s.versions.push({ v: s.version, at: X.now(), by: X.me().name, note: '发布', spec: JSON.parse(JSON.stringify(s.spec)) }); }
    let review = null;
    if (s.share.scope === 'zone' && !X.can('skills', 'admin')) {
      s.status = 'in_review';
      review = { id: X.nid('R'), type: 'skill', app: 'skills', title: '技能上架申请：' + s.name, meta: `技能中心 · ${X.me().name} 申请全区公开 · v${s.version}`, ref: s.id, status: 'pending', approver: true, assignee: '张磊' };
      S().inbox.unshift(review);
    } else s.status = 'published';
    const scopeName = { private: '仅自己', people: '指定同事', dept: '本部门', zone: '全区' }[s.share.scope];
    X.audit('技能中心', `${review ? '提交上架审核' : '发布'} · ${s.name}（${scopeName}）`); return { item: view(s), review };
  });
  X.first('POST', '/api/v1/skills/:id/share', (b, p) => {
    const s = sk(p.id); if (!canEdit(s)) X.err(403, 'FORBIDDEN', '没有编辑权限');
    const wasZone = s.share.scope === 'zone'; s.share = Object.assign(s.share, b); let review = null;
    if (s.share.scope === 'zone' && !wasZone && s.status === 'published' && !X.can('skills', 'admin')) {
      s.status = 'in_review'; review = { id: X.nid('R'), type: 'skill', app: 'skills', title: '技能上架申请：' + s.name, meta: `技能中心 · ${X.me().name} 申请全区公开`, ref: s.id, status: 'pending', approver: true, assignee: '张磊' }; S().inbox.unshift(review);
    }
    X.audit('技能中心', `修改分享 · ${s.name} → ${s.share.scope}/${s.share.perm}`); return { item: view(s), review };
  });
  /* 审核（管理员/审签领导）。也可在收件箱里审 —— mock-api 的 reviews decision 分支同样会改 status */
  X.first('POST', '/api/v1/skills/:id/review', (b, p) => {
    const s = sk(p.id); if (!X.can('skills', 'approve')) X.err(403, 'FORBIDDEN', '需要审核权限（管理员 / 审签领导）');
    s.status = b.decision === 'approve' ? 'published' : 'rejected'; s.reviewNote = b.reason || '';
    S().inbox.forEach((r) => { if (r.type === 'skill' && r.ref === s.id && r.status === 'pending') { r.status = b.decision === 'approve' ? 'done' : 'rejected'; r.reason = b.reason; } });
    X.audit('技能中心', `${b.decision === 'approve' ? '审核通过' : '退回'} · ${s.name}${b.reason ? '（' + b.reason + '）' : ''}`); return { item: view(s) };
  });
  X.first('POST', '/api/v1/skills/:id/fork', (b, p) => {
    const s = sk(p.id); s.forks = (s.forks || 0) + 1; const me = X.me();
    const f = { ...JSON.parse(JSON.stringify(s)), id: 'sk-' + Date.now().toString(36), name: s.name + '（我的版本）', author: me.name, authorId: me.id, version: '0.1.0', uses: 0, rating: 0, ratingN: 0, status: 'draft', share: { scope: 'private', people: [], perm: 'use' }, source: `${s.name} v${s.version}`, forks: 0, versions: [{ v: '0.1.0', at: X.now(), by: me.name, note: `复制自「${s.name}」v${s.version}` }] };
    S().skills.unshift(f); X.audit('技能中心', `复制改编 · ${s.name}`); return { item: view(f) };
  });
  X.first('POST', '/api/v1/skills/:id/restore', (b, p) => {
    const s = sk(p.id); if (!canEdit(s)) X.err(403, 'FORBIDDEN', '没有编辑权限'); const v = s.versions.find((x) => x.v === b.v); if (!v || !v.spec) X.err(404, 'NOT_FOUND', '该版本没有保存内容');
    s.spec = JSON.parse(JSON.stringify(v.spec)); s.version = bump(s.version); s.versions.push({ v: s.version, at: X.now(), by: X.me().name, note: '回到 v' + b.v, spec: JSON.parse(JSON.stringify(v.spec)) });
    X.audit('技能中心', `回到版本 · ${s.name} v${b.v}`); return { item: view(s) };
  });
  X.first('DELETE', '/api/v1/skills/:id', (b, p) => { const s = sk(p.id); if (s.authorId !== X.me().id && !X.can('skills', 'admin')) X.err(403, 'FORBIDDEN', '只能删除自己的技能'); S().skills = S().skills.filter((x) => x.id !== s.id); X.audit('技能中心', `删除技能 · ${s.name}`); return { ok: true, item: s }; });
  X.first('POST', '/api/v1/skills/:id/restore-deleted', (b) => { S().skills.unshift(b.item); return { ok: true }; });
  X.first('POST', '/api/v1/skills/:id/rate', (b, p) => { const s = sk(p.id); if (!s.myRating) { s.rating = +(((s.rating || 0) * (s.ratingN || 0) + (b.useful ? 5 : 3)) / ((s.ratingN || 0) + 1)).toFixed(1); s.ratingN = (s.ratingN || 0) + 1; } s.myRating = b.useful ? 'up' : 'down'; return { item: view(s) }; });
  X.first('POST', '/api/v1/skills/:id/runs', (b, p) => { const s = sk(p.id); s.uses = (s.uses || 0) + 1; const r = { id: X.nid('SR'), skillId: s.id, at: X.now(), by: X.me().name, inputs: b.inputs, summary: b.summary || '', trial: !!b.trial }; S().skillRuns.unshift(r); S().skillRuns = S().skillRuns.slice(0, 40); X.audit('技能中心', `${b.trial ? '试运行' : '运行'} · ${s.name}`, b.model); return { item: r }; });
  X.first('POST', '/api/v1/skills/:id/promote', (b, p) => { const s = sk(p.id); s.promote = { status: '待开发组评审', at: X.now(), appId: b.appId }; S().inbox.unshift({ id: X.nid('R'), type: 'todo', app: 'skills', title: '技能升级为小应用：' + s.name, meta: `技能中心 · ${X.me().name} 提交 · 走开发组 MR 门禁`, ref: s.id, status: 'pending' }); X.audit('技能中心', `申请升级为小应用 · ${s.name}`); return { item: view(s) }; });

  /* ---------- 引擎接口：起草 / 试运行 / 运行（长任务，复用平台 jobs 思路：步骤检查点 + 轮询） ---------- */
  const E = window.__JKSkillEngine; const JOBS = {};
  X.first('POST', '/api/v1/skills/draft', (b) => { if (!X.can('skills', 'operate')) X.err(403, 'FORBIDDEN', '当前角色不能制作技能'); if (!String(b.text || '').trim()) X.err(422, 'EMPTY', '先用一句话说说想让它做什么'); X.audit('技能中心', `AI 起草技能 · ${String(b.text).slice(0, 16)}`, 'DeepSeek-V4-Pro'); return { draft: E.draft(b.text) }; });
  function startJob(skill, inputs, trial) {
    const job = { id: X.nid('SJ'), skillId: skill.id || null, status: 'running', steps: skill.spec.steps.map((x) => ({ label: x.label, type: x.type, status: 'todo' })), result: null, trial: !!trial };
    JOBS[job.id] = job;
    E.run(skill, inputs || {}, { onStep: (i, st) => { job.steps[i].status = st; } }).then((res) => {
      job.result = res; job.status = 'done';
      if (skill.id && X.state().skills.find((x) => x.id === skill.id)) A.request('POST', `/api/v1/skills/${skill.id}/runs`, { inputs, trial, summary: res.title, model: res.model }).catch(() => {});
      else X.audit('技能中心', `试运行 · ${skill.name}`, res.model);
    }).catch((e) => { job.status = 'failed'; job.error = String(e.message || e); });
    return { job: { ...job } };
  }
  X.first('POST', '/api/v1/skills/trial', (b) => startJob({ id: null, name: b.skill.name, spec: b.skill.spec }, b.inputs, true));
  X.first('POST', '/api/v1/skills/:id/run', (b, p) => { const s = sk(p.id); if (!visible(s)) X.err(403, 'FORBIDDEN', '这个技能没有分享给你'); return startJob(s, b.inputs, !!b.trial); });
  X.first('GET', '/api/v1/skills/jobs/:id', (b, p) => { const j = JOBS[p.id]; if (!j) X.err(404, 'NOT_FOUND', '任务不存在'); return { job: JSON.parse(JSON.stringify(j)) }; });
  X.first('POST', '/api/v1/skills/match', (b) => { const m = E.match(b.text, X.state().skills.filter(visible)); return m ? { skill: view(m.skill), score: m.score } : { skill: null, score: 0 }; });
  X.first('GET', '/api/v1/skills/:id/manifest', (b, p) => { const s = sk(p.id); return { appJson: E.toManifest(s), skillMd: E.toSkillMd(s) }; });
  X.first('GET', '/api/v1/skills/meta/options', () => ({
    models: (X.state().models || []).filter((m) => m.enabled && m.kind !== 'route').map((m) => ({ id: m.id, name: m.name, local: m.kind === 'local' })),
    spaces: ['政策库', '公文范文', '会议纪要', '部门制度'],
    tools: [{ id: 'policy.match', label: '匹配兑现事项', needs: 'ent' }, { id: 'enterprise.get', label: '读取企业档案', needs: 'ent' }, { id: 'meeting.list', label: '汇总会议记录' }],
    computerTasks: [{ id: 'stats', label: '统计月报填报' }, { id: 'apply', label: '政策申报填表' }, { id: 'notice', label: '下载通知入库' }, { id: 'status', label: '查询办理进度' }],
    users: X.state().users.filter((u) => u.status !== 'disabled' && u.id !== X.me().id).map((u) => ({ id: u.id, name: u.name, dept: (X.state().departments.find((d) => d.id === u.deptId) || {}).name || '' })),
    myDept: (X.state().departments.find((d) => d.id === X.me().deptId) || {}).name || '',
  }));
})();

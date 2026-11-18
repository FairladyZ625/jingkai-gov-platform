/* 模拟后端 · 政策兑现（覆盖 mock-api.js 里的匹配路由，其余路由沿用）。
 * 为什么覆盖：接入 83 条经开区真实政策（data/real-policies.js）后，真实条目的第一个条件是“在区注册”，
 * 旧引擎把它当“对象识别条件”，导致几乎所有企业都匹配到几十条。这里改为：
 *   1) 对象识别 = 身份类条件（tags / license / subjectType）至少一条满足；没有身份条件的通用条目不进匹配结果（仍可在事项库查看）
 *   2) “触发行为”条件（如有数据采购、改造投入）未知时不推荐，避免无关事项堆成“待确认”
 *   3) 定额 / “最高”类奖励单独标出，不计入按比例试算的合计
 * 真实后端对应：policy-service 的 match 接口（同入参同出参）。 */
(function () {
  const X = window.JKAPI.ext;
  const S = () => X.state();
  const ent = (id) => S().enterprises.find((e) => e.id === id);
  const pdoc = (id) => S().policyDocs.find((d) => d.id === id) || {};
  const ID_FIELDS = ['tags', 'license', 'subjectType'];
  function profileOf(e) { return { subjectType: e.subjectType, tags: e.tags, license: e.license, yearsInZone: e.yearsInZone, regInZone: e.regInZone, employees: e.employees, established: e.established, ...(e.amounts || {}) }; }
  function evalCond(c, pf) {
    const val = pf[c.f];
    if (c.op === 'has' || c.op === 'hasAny') { const arr = [].concat(val || []); const ok = [].concat(c.v).some((w) => arr.includes(w)); return ok ? 'ok' : c.f === 'license' ? 'unknown' : 'no'; }
    if (val === undefined || val === null || val === '') return 'unknown';
    if (c.op === '==') return val === c.v ? 'ok' : 'no';
    if (c.op === '>=') return val >= c.v ? 'ok' : 'no';
    if (c.op === '<=') return val <= c.v ? 'ok' : 'no';
    if (c.op === '>') return val > c.v ? 'ok' : 'no';
    return 'unknown';
  }
  const money = (n) => (n >= 10000 ? (n / 10000).toFixed(n % 10000 ? 1 : 0).replace(/\.0$/, '') + ' 万元' : n + ' 元');
  function calcOf(p, pf) {
    const r = p.rule || {};
    if (r.base && r.ratio) { const base = pf[r.base]; if (!base) return null; const raw = Math.round(base * r.ratio), cap = r.cap || Infinity, amount = Math.min(raw, cap); return { amount, base, kind: 'ratio', text: `${money(base)} × ${+(r.ratio * 100).toFixed(2)}% = ${money(raw)}${raw > cap ? `，超过封顶，按 ${money(cap)}` : ''}`, capped: raw > cap }; }
    if (r.fixed) return { amount: r.fixed, kind: 'fixed', text: `${r.upTo ? '最高' : '定额'} ${money(r.fixed)}`, capped: false, upTo: !!r.upTo };
    return null;
  }
  function matchAll(pf) {
    const out = [];
    S().policies.forEach((p) => {
      if (p.status && p.status !== '已发布' && X.roleOf().mask) return;
      const conds = p.conditions || [];
      // 自动抽取的“有相关投入/支出”属于泛化触发条件：有金额也不能断定属于本事项，标为待确认，不自动试算
      const generic = (c) => c.trigger && /有相关投入/.test(c.label || '');
      const checks = conds.map((c) => ({ label: generic(c) ? '确认相关投入属于本事项支持范围' : c.label, state: generic(c) ? (pf[c.f] ? 'unknown' : 'none') : evalCond(c, pf), f: c.f }));
      if (checks.some((c) => c.state === 'none')) return;
      const idIdx = conds.map((c, i) => (ID_FIELDS.includes(c.f) ? i : -1)).filter((i) => i >= 0);
      const objOk = !p.object || p.object === pf.subjectType || (p.object === '其他组织' && (pf.tags || []).includes('服务机构'));
      if (!objOk || !idIdx.length) return;
      const tagIdx = idIdx.filter((i) => conds[i].f === 'tags');
      if (tagIdx.length ? !tagIdx.some((i) => checks[i].state === 'ok') : !idIdx.some((i) => checks[i].state !== 'no')) return;
      if (conds.some((c, i) => c.trigger && checks[i].state === 'unknown')) return;
      let level = checks.some((c) => c.state === 'no') ? 'no' : checks.some((c) => c.state === 'unknown') ? 'check' : 'ok';
      const t = p.times || {};
      const isGeneric = conds.some(generic); const okN = checks.filter((c) => c.state === 'ok').length;
      out.push({ okN, id: p.id, title: p.title, level, checks: checks.map(({ label, state }) => ({ label, state })), pending: p.pending || [], window: t.window, open: t.open, ended: t.open === false, calc: level === 'no' || isGeneric ? null : calcOf(p, pf), rule: (p.rule || {}).text, doc: (p.source && p.source.docNo) || pdoc(p.doc).no || '', clause: p.clause || '', real: !!p.real, category: p.category || '' });
    });
    const rank = { ok: 0, check: 1, no: 2 };
    out.sort((a, b) => rank[a.level] - rank[b.level] || (a.ended - b.ended) || (b.okN - a.okN) || ((b.calc && b.calc.kind === 'ratio') - (a.calc && a.calc.kind === 'ratio')) || (b.real - a.real));
    out.forEach((r) => delete r.okN);
    return out;
  }
  X.first('POST', '/api/apps/policy/match', (b) => {
    let pf;
    if (b.entId) { const e = ent(b.entId); if (!e) X.err(404, 'NOT_FOUND', '企业不存在'); pf = profileOf(e); Object.assign(pf, b.overrides || {}); if (b.overrides && b.overrides.license) pf.license = [...new Set([...(e.license || []), ...b.overrides.license])]; }
    else pf = Object.assign({ subjectType: '企业', tags: [], license: [], regInZone: true }, b.profile);
    const results = matchAll(pf);
    X.audit('政策兑现咨询', `匹配 · ${b.entId ? ent(b.entId).short : '手动画像'}`, 'DeepSeek-V4.1-Flash');
    return { profile: pf, results, summary: { ok: results.filter((r) => r.level === 'ok').length, check: results.filter((r) => r.level === 'check').length, no: results.filter((r) => r.level === 'no').length } };
  });
  X.first('POST', '/api/apps/policy/calc', (b) => {
    const p = S().policies.find((x) => x.id === b.itemId); if (!p) X.err(404, 'NOT_FOUND', '事项不存在');
    const pf = {}; if (p.rule && p.rule.base) pf[p.rule.base] = +b.amount;
    return { item: p.id, rule: (p.rule || {}).text, result: calcOf(p, pf), note: '按政策原文规则确定性计算，实际金额以评审结果为准' };
  });
})();

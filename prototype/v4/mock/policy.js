/* 政策试算沿用匹配结果使用的金额计算。 */
(function () {
  const X = window.JKAPI.ext;
  X.on('POST', '/api/apps/policy/calc', (b) => {
    const p = X.visiblePolicies().find((x) => x.id === b.itemId); if (!p) X.err(404, 'NOT_FOUND', '事项不存在');
    const pf = {}; if (p.rule && p.rule.base) pf[p.rule.base] = +b.amount;
    return { item: p.id, rule: (p.rule || {}).text, result: X.calcOf(p, pf), note: p.example ? '示例（无对应原文）' : p.times?.open === false ? '本批已结束，仅供历史参考' : '按政策规则试算，实际金额以评审结果为准' };
  });
})();

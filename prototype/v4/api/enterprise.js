/* 接口适配 · 企业管理维护（接口规范 §4.2）。外部协作者的脱敏在后端完成（maskEnt），前端只展示。 */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  window.JKApi.enterprise = {
    /** {q?, industry?, tag?, scale?, servicer?, alert?:1, sort?:'lastVisit'|'revenue'|'name'} → {items:Enterprise[], total, facets:{industries,tags,servicers}} */
    list: (q) => H.get('/api/apps/enterprise/companies', q),
    /** id → {item:Enterprise, visits:Visit[], issues:Issue[], files:KbFile[], proposals:Proposal[], history:Change[]} */
    get: (id) => H.get('/api/apps/enterprise/companies/' + id),
    /** {name, short?, creditCode?, industry?, scale?, tags?, yearsInZone?, employees?, addr?, contact?, phone?} → {item} */
    create: (b) => H.post('/api/apps/enterprise/companies', b),
    /** (id, {field:value}) → {item}（写变更历史；外部协作者 403） */
    patch: (id, b) => H.patch('/api/apps/enterprise/companies/' + id, b),
    /** (id, {notes, type?}) → {visit, proposals:Proposal[], issues:string[]}  AI 提取台账更新建议，不直接写台账 */
    visit: (id, b) => H.post(`/api/apps/enterprise/companies/${id}/visits`, b),
    /** (proposalId, {decision:'accept'|'reject', value?}) → {item, pending} 人工确认写入 */
    decide: (pid, b) => H.post(`/api/apps/enterprise/proposals/${pid}/decision`, b),
    /** {status?, entId?, owner?} → {items:Issue[], statuses[]} */
    issues: (q) => H.get('/api/apps/enterprise/issues', q),
    /** {entId, title, from?, owner?, due?, next?} → {item:Issue} */
    createIssue: (b) => H.post('/api/apps/enterprise/issues', b),
    /** (id, {status?, note?, next?, owner?}) → {item:Issue} */
    patchIssue: (id, b) => H.patch('/api/apps/enterprise/issues/' + id, b),
    /** → {items:Alert[]}（资质到期 / 久未走访 / 诉求临期） */
    alerts: () => H.get('/api/apps/enterprise/alerts'),
    /** {ids?:'E001,E002'} → {filename, csv} */
    exportCsv: (q) => H.get('/api/apps/enterprise/export', q),
    /** {rows:[{name,...}]} → {added, items} */
    import: (b) => H.post('/api/apps/enterprise/import', b),
  };
})();

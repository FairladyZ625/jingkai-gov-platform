/* 接口适配 · 公文协作（接口规范 §4.4）。审签走平台 reviews；定稿后 PUT 返回 409 LOCKED。 */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  const isHttp = () => {
    const { mode, modules } = window.JK_CONFIG?.api || {};
    return (modules?.document === 'http' || modules?.document === 'mock' ? modules.document : mode) === 'http';
  };
  window.JKApi.document = {
    isHttp,
    /** → {items:DocTemplate[], groups:[[id,name]]} 10 类“要办什么事” */
    templates: () => H.get('/api/apps/document/templates'),
    /** → {items:DocSummary[]} 我的文稿 */
    list: () => H.get('/api/apps/document/documents'),
    /** {templateId, inputs:{}, extra?:string[], refs?:[]} → {item:Draft} AI 初稿（缺要素写【待补：x】） */
    draft: (b) => H.post('/api/apps/document/drafts', b),
    /** id → {item:Draft(versions[], comments[], status)} */
    get: (id) => H.get('/api/apps/document/drafts/' + id),
    /** (id, {content, note?}) → {item}  保存为新版本；已定稿 409 */
    save: (id, b) => H.put('/api/apps/document/drafts/' + id, b),
    /** id → {issues:CheckIssue[]}（level error/warn/info/ok） */
    check: (id) => H.post(`/api/apps/document/drafts/${id}/check`, {}),
    /** (id, {ids[]}) → {item, issues} 一键修正，生成新版本 */
    fix: (id, b) => H.post(`/api/apps/document/drafts/${id}/fix`, b),
    /** (id, {style:'formal'|'concise', para?}) → {preview:Content, parts:Diff[], changed} 只预览，采用时再 save */
    polish: (id, b) => H.post(`/api/apps/document/drafts/${id}/polish`, b),
    /** {a:{id,v}|string, b:{id,v}|string} → {parts:Diff[], stats:{add,del}} */
    compare: (b) => H.post('/api/apps/document/compare', b),
    /** (id, {para, text}) → {item:Comment} */
    comment: (id, b) => H.post(`/api/apps/document/drafts/${id}/comments`, b),
    /** (id, cid, {reply?, resolved?}) → {item:Comment} */
    patchComment: (id, cid, b) => H.patch(`/api/apps/document/drafts/${id}/comments/${cid}`, b),
    /** (id, {assignee?}) → {item, review}  有“必须改”问题时 422 CHECK_FAILED */
    submit: (id, b) => H.post(`/api/apps/document/drafts/${id}/submit`, b || {}),
    /** HTTP 由浏览器下载 .docx，mock 返回 Word 兼容 HTML。 */
    exportWord: (id) => {
      const path = `/api/apps/document/drafts/${encodeURIComponent(id)}/export`;
      if (!isHttp()) return H.get(path);
      // JKHttp 解析 JSON。二进制附件交浏览器处理会话、文件名和下载状态。
      const configured = window.JK_CONFIG.api.baseUrl || '';
      const base = configured === 'http://127.0.0.1:8080' ? '' : configured.replace(/\/$/, '');
      return { url: base + path };
    },
  };
})();

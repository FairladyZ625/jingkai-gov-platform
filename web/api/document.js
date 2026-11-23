/* 接口适配 · 公文协作（接口规范 §4.4）。审签走平台 reviews；定稿后 PUT 返回 409 LOCKED。 */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  // 界面按姓名选审签人；真后端要账号 ID，按演示账号表换算，模拟后端仍收姓名。
  const toUserId = (b) => { const name = b && b.assignee; const u = name && ((window.JK_DATA || {}).users || []).find((x) => x.name === name); return u ? Object.assign({}, b, { assignee: u.id }) : (b || {}); };
  const wordType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  async function readWord(response) {
    const invalid = { status: 502, code: 'INVALID_WORD_RESPONSE', message: '未收到可用的 Word 文件' };
    if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== wordType) throw invalid;
    const blob = await response.blob();
    const magic = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
    if (magic.join(',') !== '80,75,3,4') throw invalid;
    const disposition = response.headers.get('Content-Disposition') || '';
    const encoded = /(?:^|;)\s*filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
    let filename = '';
    if (encoded) try { filename = decodeURIComponent(encoded.trim()); } catch (e) { /* 回退普通文件名 */ }
    if (!filename) filename = /(?:^|;)\s*filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(disposition)?.slice(1).find(Boolean) || '';
    filename = filename.replace(/[\\/:*?"<>|\x00-\x1f\x7f]/g, '_').trim();
    return { filename: /\.docx$/i.test(filename) ? filename : '公文.docx', blob };
  }
  window.JKApi.document = {
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
    submit: (id, b) => H.post(`/api/apps/document/drafts/${id}/submit`, H.mode('document') === 'http' ? toUserId(b) : (b || {})),
    /** HTTP → {filename, blob} 的 .docx；离线模拟仍返回 {filename, html, final} 的 .doc。 */
    exportWord: (id) => H.getFile(`/api/apps/document/drafts/${encodeURIComponent(id)}/export`, readWord),
  };
})();

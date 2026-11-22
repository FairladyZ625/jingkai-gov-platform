/* =====================================================================
 * 接口适配 · 知识库（界面只调这里）。路径与《接口规范》§知识库 同名同构；mock 模式由 mock/kb.js 实现。
 * 真实后端：haiknow 知识库服务（MinerU 解析 → 切片 → 向量 + BM25 混合检索 → 模型只基于检索片段作答并标注出处）。
 * 实体：
 *   Space = { id, name, icon, desc, roles[], visible, count, expiring }
 *   KbDoc = { id, title, space, spaceName, kind, status: 现行有效|即将到期|已失效|已更新, tags[], real, example,
 *             source:{org, date, url, docNo}, expire, version, chunks, from: 官网|上传|粘贴|网址|对话 }
 *   Hit   = KbDoc + { chunk, snippet, score }
 *   Answer= { answer(markdown，句末 [n]), confidence: high|mid|low|none, citations:[{n,id,title,snippet,chunk,source,status}], followups[], notFound?, message?, near[], suggestions[] }
 *   ImportItem = { key, name, ext, size, from, parse: real|simulated, ok, error?, text, chars, meta:{title,docNo,date,org,space,kind,expire},
 *                  chunks, chunkPreview[], tags[], dup:{type: new|duplicate|version, id?, title?, sim?}, stages:{parse,chunk,tag} }
 * ===================================================================== */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  window.JKApi.kb = Object.assign(window.JKApi.kb || {}, {
    /** → {items: Space[]} */ spaces: () => H.get('/api/v1/kb/spaces'),
    /** (id, {roles}) → {ok}  管理员改空间可见范围 */ setSpaceRoles: (id, roles) => H.patch('/api/v1/kb/spaces/' + id, { roles }),
    /** {q, scope?: citationId, space?, limit?, sort?: 'rel'|'date', filters?:{kind,status,org,year,tag,validOnly}} → {hits: Hit[], total, terms[], facets} */ search: (b) => H.post('/api/v1/kb/search', b),
    /** scope 只选择文档版本，不授予权限。HTTP 的现有超时预算同时约束后端模型等待。 */
    ask: (b) => H.post('/api/v1/kb/ask', H.mode?.() === 'http' && H.timeoutMs ? { ...b, timeoutMs: H.timeoutMs() } : b),
    /** {space?, status?, kind?, limit?} → {hits: KbDoc[], total, facets} */ list: (q) => H.get('/api/v1/kb/docs', q),
    /** id → {item: KbDoc + {text, chunkList[{i,start,end,head}], versions[], newer, uploadedBy, addedAt, parse}} */ get: (id) => H.get('/api/v1/kb/docs/' + encodeURIComponent(id)),
    /** (id, {tags?, title?, space?, expire?}) → {item} */ update: (id, b) => H.patch('/api/v1/kb/docs/' + encodeURIComponent(id), b),
    /** id → {ok, item}（可撤销） */ remove: (id) => H.del('/api/v1/kb/docs/' + encodeURIComponent(id)),
    /** id → {ok} */ restore: (id) => H.post('/api/v1/kb/docs/' + encodeURIComponent(id) + '/restore', {}),
    /** {items:[{name, ext, size, text, parse, from}]} → {items: ImportItem[]}  解析+切片+打标签+查重（不入库） */ preview: (items) => H.post('/api/v1/kb/import/preview', { items }),
    /** {url} → {item: ImportItem, snapshot}  抓取网页正文（原型：官网页面快照） */ fetchUrl: (url) => H.post('/api/v1/kb/import/url', { url }),
    /** {items: ImportItem(编辑后，带 decision: version|new, skip)} → {docs: KbDoc[], chunks} */ commit: (items, from) => H.post('/api/v1/kb/import/commit', { items, from }),
    /** {items?|text?|url?, space?, from?} → {docs, chunks, skipped[]}  一步导入（供对话/其它应用） */ importNow: (b) => H.post('/api/v1/kb/import', b),
    /** → {docs, chunks, status:{}, real, fetched, recent: KbDoc[], log[]} */ stats: () => H.get('/api/v1/kb/stats'),
    /** → {items: string[]} 建议问题 */ suggest: () => H.get('/api/v1/kb/suggest'),
  });
})();

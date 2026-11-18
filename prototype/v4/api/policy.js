/* 接口适配 · 政策兑现（接口规范 §4.1）。界面只调这里；mock 模式路由在 mock/mock-api.js（v1 已有，直接复用）。 */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  window.JKApi.policy = {
    /** {q?, object?, window?:'open'|'ended'|'unknown'} → {items:PolicyItem[], total, docs:PolicyDoc[]} */
    items: (q) => H.get('/api/apps/policy/items', q),
    /** id → {item:PolicyItem}（含 docNo/docTitle/docState） */
    item: (id) => H.get('/api/apps/policy/items/' + encodeURIComponent(id)),
    /** {entId, overrides?} | {profile} → {profile, results:MatchResult[]（level ok/check/no, checks[], calc）, summary:{ok,check,no}} */
    match: (b) => H.post('/api/apps/policy/match', b),
    /** {itemId, amount(元)} → {item, rule, result:{amount,text,capped}|null, note} */
    calc: (b) => H.post('/api/apps/policy/calc', b),
    /** {entId, itemIds[]} → {text} 一次性告知单 */
    notice: (b) => H.post('/api/apps/policy/notice', b),
  };
})();

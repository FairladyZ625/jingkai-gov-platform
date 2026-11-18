/* 模拟后端 · 外壳补充路由（审计写入等）。真实后端对应 haiknow audit 接口。 */
(function () {
  const X = window.JKAPI.ext;
  X.on('POST', '/api/v1/audit', (b) => { X.audit(b.app || '平台', b.action || '操作', b.model); X.save(); return { ok: true }; });
})();

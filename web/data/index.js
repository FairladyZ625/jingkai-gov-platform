/* 真实数据入口（知识库 worker 维护）：按顺序加载真实公开数据，需在 config/*.js 之后、core/mock-api.js 之前。
 * 若 index.html 已直接 <script> 引入 real-policies.js / real-kb.js，这里会自动跳过。 */
(function () {
  var api = (window.JK_CONFIG || {}).api || {};
  // 纯 HTTP 使用服务端数据；只在离线或显式选择模拟模块时读取浏览器快照。
  if (api.mode === 'http' && !Object.values(api.modules || {}).includes('mock')) return;
  var base = (document.currentScript && document.currentScript.src || '').replace(/index\.js(\?.*)?$/, '');
  if (document.readyState === 'loading') {
    if (!window.JK_REAL_SUPPLEMENT) document.write('<script src="' + base + 'real-supplement.js"><\/script>');
    if (!window.JK_REAL) document.write('<script src="' + base + 'real-policies.js"><\/script>');
    if (!window.JK_REAL_KB) document.write('<script src="' + base + 'real-kb.js"><\/script>');
    if (!window.JK_KB_EXAMPLES) document.write('<script src="' + base + 'kb-examples.js"><\/script>');
  }
})();

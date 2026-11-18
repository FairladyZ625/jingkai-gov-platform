/* 真实数据入口（知识库 worker 维护）：按顺序加载真实公开数据，需在 config/*.js 之后、core/mock-api.js 之前。
 * 若 index.html 已直接 <script> 引入 real-policies.js / real-kb.js，这里会自动跳过。 */
(function () {
  if (window.JK_REAL && window.JK_REAL_KB && window.JK_KB_EXAMPLES) return;
  var base = (document.currentScript && document.currentScript.src || '').replace(/index\.js(\?.*)?$/, '');
  if (document.readyState === 'loading') {
    if (!window.JK_REAL) document.write('<script src="' + base + 'real-policies.js"><\/script>');
    if (!window.JK_REAL_KB) document.write('<script src="' + base + 'real-kb.js"><\/script>');
    if (!window.JK_KB_EXAMPLES) document.write('<script src="' + base + 'kb-examples.js"><\/script>');
  }
})();

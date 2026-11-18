/* =====================================================================
 * 【可改】启用哪些应用、在侧栏的顺序。新增应用 = 建 3 处文件 + 在这里加一行：
 *   mock/<id>.js   该应用的模拟后端（mock:true 时加载；api.mode='http' 时不加载）
 *   api/<id>.js    该应用的接口适配（api:true 时加载）——界面只调它
 *   apps/<id>/     界面：files 依次加载，css 样式
 * group: 'work' 业务应用 / 'platform' 平台能力；enabled:false = 暂不加载（侧栏也不显示）
 * ===================================================================== */
window.JK_APP_LIST = [
  { id: 'policy',     group: 'work',     mock: true, api: true, files: ['config.js', 'app.js'], css: ['app.css'] },
  { id: 'enterprise', group: 'work',     mock: false, api: true, files: ['config.js', 'app.js'], css: ['app.css'] },
  { id: 'meeting',    group: 'work',     mock: false, api: true, files: ['config.js', 'app.js'], css: ['app.css'] },
  { id: 'document',   group: 'work',     mock: false, api: true, files: ['config.js', 'app.js'], css: ['app.css'] },
  { id: 'kb',         group: 'platform', mock: true,  api: true,  files: ['files.js', 'config.js', 'app.js'], css: ['app.css'] },
  { id: 'skills',     group: 'platform', mock: true, api: true, files: ['app.js'], css: ['app.css'] },
  { id: 'computer',   group: 'platform', mock: true, api: true, files: ['sites.js', 'app.js'], css: ['app.css'] },
];
/* 集成期开关：lead 根据文件是否就绪维护（全部就绪后删掉这段） */
(function () { var ready = window.JK_APPS_READY || null; if (!ready) return; window.JK_APP_LIST.forEach(function (a) { if (ready.indexOf(a.id) < 0) a.enabled = false; }); })();

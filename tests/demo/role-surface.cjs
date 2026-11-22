// 可在离线 Chromium 或 JSDOM 中执行同一交互。只用内存模拟传输，不登录外部服务。
async function inspectRole({ username, mode }) {
  const w = window, $ = s => document.querySelector(s);
  const seed = w.JKAPI.state();
  seed.me = seed.users.find(u => u.username === username).id;
  seed.session = {userId:seed.me, at:'fixture'};
  w.JKAPI.latency = 0;
  const counts = {}, requests = {}, denied = [];
  const paths = {enterprise:'/api/apps/enterprise/companies', meeting:'/api/apps/meeting/meetings',
    policy:'/api/apps/policy/items', document:'/api/apps/document/documents'};
  const profile = await w.JKAPI.get('/api/v1/me');
  // 先从已登录的离线夹具取得该角色可读的响应。切到 HTTP 后，fetch 替身
  // 只服务这些快照，不能再递归调用浏览器 mock 的平台鉴权接口。
  const snapshots = new Map(), unexpectedMock = [];
  if (mode === 'http') {
    for (const path of ['/api/v1/auth/session','/api/v1/me','/api/v1/models','/api/v1/reviews','/api/v1/todos',
      ...Object.entries(paths).filter(([app])=>profile.grants[app]?.includes('view')).map(([,p])=>p)]) {
      snapshots.set(path, await w.JKAPI.get(path));
    }
    w.JKAPI.request = (_method, path) => { unexpectedMock.push(path); throw Error('HTTP 角色矩阵不允许退回浏览器 mock'); };
  }
  // transport 明确标成 HTTP 替身，不隐藏会被服务端拒绝的尝试。
  w.JK_CONFIG.api.mode = mode;
  function observe(path) {
    requests[path] = (requests[path] || 0) + 1;
    const app = Object.keys(paths).find(key => paths[key] === path);
    if (app) {
      counts[app] = (counts[app] || 0) + 1;
      if (!profile.grants[app]?.includes('view')) { denied.push(app); return false; }
    }
    return true;
  }
  if (mode === 'mock') {
    const request = w.JKAPI.request;
    w.JKAPI.request = (method, path, body) => { observe(path.split('?')[0]); return request(method, path, body); };
  }
  w.fetch = async (url, init) => {
    const path = new URL(url, 'https://fixture.invalid').pathname;
    if (!observe(path)) return {ok:false,status:403,json:async()=>({code:'FORBIDDEN'})};
    if (init.method !== 'GET') throw Error('首屏不应发出写请求');
    if (!snapshots.has(path)) throw Error('未登记的角色夹具请求：' + path);
    return {ok:true,status:200,json:async()=>snapshots.get(path)};
  };
  let preload, todos;
  const load = w.JKOp.loadDict;
  w.JKOp.loadDict = function (...args) { return preload = load.apply(this, args); };
  const list = w.JKApi.todos.list;
  w.JKApi.todos.list = (...args) => todos = list(...args);
  // 从真实启动处理器的 session 检查起计数，而不只测 loadDict 自身。
  document.dispatchEvent(new w.Event('DOMContentLoaded'));
  for (let i = 0; (!preload || !todos) && i < 300; i++) await new Promise(r => setTimeout(r, 10));
  if (!preload || !todos) throw Error('未完成首屏初始化');
  await Promise.all([preload, todos]);
  const startup = {...requests};
  const home = [...document.querySelectorAll('.sug')].map(el => el.dataset.say);
  $('#btn-me').click();
  const menu = Array.from(document.querySelectorAll('.menu [data-v], [data-v^="as:"], [data-v="logout"], [data-v="reset"], [data-v="admin"]'), el => el.dataset.v);
  document.body.click();
  $('[data-op="rail.cmdk"]').click();
  const input = $('.cmdk input'), examples = {};
  for (const id of ['kb.import','kb.ask','skills.review','skills.browse','document.approve','meeting.transcribe','enterprise.visit','enterprise.find','policy.match','policy.items']) {
    const example = w.JKOp.allIntents().find(it => it.id === id).examples[0];
    input.value = example; input.dispatchEvent(new w.Event('input'));
    examples[id] = [...document.querySelectorAll('.cmdk-list .ck-t')].some(el => el.textContent === example);
  }
  $('.cmdk [data-x]').click();
  if (document.activeElement !== $('[data-op="rail.cmdk"]')) throw Error('关闭搜索后未回到原入口');
  if (mode === 'http' && profile.role.id === 'leader') {
    const demo = w.JKDemo.start();
    const prompt = $('[data-op="switch.password"]');
    if (!prompt || prompt.value || w.JKDemo.state.on) throw Error('内部演示未等待目标身份口令');
    prompt.closest('[role=dialog]').querySelector('[data-cancel]').click(); await demo;
    if (w.JKDemo.state.on || w.JKDemo.state.i || w.JKShell.S.me.username !== username) throw Error('取消切号后仍在播放');
  }
  if (mode === 'http' && profile.role.id === 'partner') {
    let prompts = 0, sends = 0;
    const modal = w.JK.modal, send = w.JKShell.send;
    w.JK.modal = () => { prompts++; throw Error('无权入口不应弹出口令框'); };
    try {
      for (const text of ['切到管理员','一键演示','审核技能上架申请']) {
        await send(text);
        const last = [...document.querySelectorAll('#chatcol .msg.ai .txt')].at(-1);
        if (!last?.textContent.includes('当前身份不能执行')) throw Error('受限命令未明确拒绝');
      }
      w.JKShell.send = () => { sends++; };
      if (await w.JKShell.switchUser('admin') !== false) throw Error('无权切换身份');
      await w.JKDemo.start();
      if (w.JKDemo.state.on || prompts || sends || w.JKShell.S.me.username !== username) throw Error('外部身份误启动演示');
    } finally { w.JK.modal = modal; w.JKShell.send = send; }
  }
  return {role:profile.role.id, counts, requests:startup, denied, unexpectedMock, menu, examples, demo:!!$('#btn-demo'), railDemo:!!$('[data-op="rail.demo"]'),
    home, help:w.JKOp.hooks.helpNext().map(x=>x.say)};
}
function checkRole(assert, r, mode, file = true) {
  const partner = r.role === 'partner', reviewer = ['admin','leader'].includes(r.role), offline = mode === 'mock' && file;
  assert.deepEqual(r.denied, []);
  assert.deepEqual(r.unexpectedMock, []);
  assert.equal(r.requests['/api/v1/auth/session'], 1);
  assert.deepEqual(r.counts, partner ? {enterprise:1,policy:1} : {enterprise:1,meeting:1,policy:1,document:1});
  assert.equal(r.menu.some(key=>key.startsWith('as:')), offline || mode === 'http' && !partner);
  assert.equal(r.menu.includes('admin'), r.role === 'admin');
  assert.ok(r.menu.includes('logout')); assert.equal(r.menu.includes('reset'), offline);
  assert.equal(r.demo, offline || mode === 'http' && !partner); assert.equal(r.railDemo, r.demo);
  for (const id of ['kb.ask','skills.browse','enterprise.find','policy.items']) assert.ok(r.examples[id], id);
  for (const id of ['kb.import','meeting.transcribe','enterprise.visit','policy.match']) assert.equal(r.examples[id], !partner, id);
  for (const id of ['skills.review','document.approve']) assert.equal(r.examples[id], reviewer, id);
  assert.deepEqual(r.home, r.help);
  assert.equal(r.home.some(s=>s.includes('申报哪些政策')), !partner);
}
module.exports = {inspectRole, checkRole};

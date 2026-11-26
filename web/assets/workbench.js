/* 独立工作台导航；业务模块通过既有 API 读取同一记录。 */
(function () {
  const names = Object.freeze({ enterprise: '企业服务', meeting: '会议纪要', document: '公文协作' });
  const registry = Object.create(null), remembered = new Map();
  let host, userId, current = null, control = null, generation = 0;
  let allowed = () => false, backToChat = () => {}, openApplication = () => {};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const permitted = id => !!userId && Object.hasOwn(names, id) && allowed(id, 'view');
  const parse = () => {
    const match = /^#\/workbench\/(enterprise|meeting|document)(?:\?(.*))?$/.exec(location.hash);
    return match ? { id: match[1], recordId: new URLSearchParams(match[2] || '').get('record') || '' } : null;
  };
  const url = state => '#/workbench/' + state.id + (state.recordId ? '?record=' + encodeURIComponent(state.recordId) : '');
  const baseUrl = () => location.pathname + location.search;
  function changed() {
    host?.parentElement?.classList.toggle('workbench-open', !!current);
    window.dispatchEvent(new CustomEvent('jk:workbench:changed'));
  }
  function dispose() {
    generation++;
    const previous = control; control = null;
    try { previous?.unmount?.(); } catch (error) { console.error('工作台卸载失败', error); }
  }
  function clearView() {
    dispose(); current = null;
    if (host) { host.classList.remove('active'); host.dataset.record = ''; host.replaceChildren(); }
    changed();
  }
  function render() {
    host.classList.add('active'); host.dataset.record = current.recordId;
    const state = { ...current }, token = generation;
    const live = () => token === generation && current?.id === state.id && permitted(state.id);
    host.innerHTML = `<div class="wb-head"><div><span class="t-3">工作台 / ${esc(names[state.id])}</span><h1 tabindex="-1">${esc(names[state.id])}工作台</h1></div><button class="btn ghost" data-wb-chat>返回对话</button></div><div class="wb-body" data-wb-body></div>`;
    host.querySelector('[data-wb-chat]').onclick = () => { if (live()) backToChat(); };
    const el = host.querySelector('[data-wb-body]'), module = registry[state.id];
    if (!module) {
      el.innerHTML = `<div class="wb-empty"><span class="tag">正在准备</span><h2>从现有应用继续办理</h2><p>${esc(names[state.id])}工作台正在准备，你可以先使用现有应用处理业务。</p><button class="btn primary" data-wb-app>打开${esc(names[state.id])}应用</button></div>`;
      el.querySelector?.('[data-wb-app]')?.addEventListener('click', () => { if (live()) openApplication(state.id); });
    } else {
      try {
        control = module.mount(el, { userId, appId: state.id, recordId: state.recordId,
          api: window.JKApi[state.id], can: action => live() && allowed(state.id, action),
          open: recordId => live() && open(state.id, { recordId }) }) || null;
      } catch (error) { el.innerHTML = `<div class="wb-empty" role="alert"><h2>工作台加载失败</h2><p>${esc(error.message || error)}</p></div>`; }
    }
    changed(); host.querySelector('h1').focus();
  }
  function navigate(state, push) {
    if (!host || !state || !permitted(state.id)) return false;
    if (current?.id === state.id && current.recordId === state.recordId) return true;
    dispose(); current = state; remembered.set(state.id, state.recordId);
    const historyState = { ...history.state, jkWorkbenchUser: userId };
    if (push && location.hash !== url(state)) history.pushState(historyState, '', url(state));
    else history.replaceState(historyState, '', url(state));
    render(); return true;
  }
  function open(id, options = {}) {
    const recordId = Object.hasOwn(options, 'recordId') ? options.recordId : remembered.get(id) || '';
    return navigate({ id, recordId: String(recordId ?? '') }, true);
  }
  function hide() {
    if (parse()) history.pushState(null, '', baseUrl());
    if (current) clearView();
  }
  function reset() {
    clearView(); remembered.clear(); userId = null; allowed = () => false;
  }
  function restore() {
    const target = parse(), owner = history.state?.jkWorkbenchUser;
    if (target && (!owner || owner === userId) && permitted(target.id)) navigate(target, false);
    else {
      clearView();
      if (location.hash.startsWith('#/workbench/')) history.replaceState(null, '', baseUrl());
    }
  }
  function bind(el, id, can, chat, application = () => {}) {
    clearView(); if (userId !== id) remembered.clear();
    host = el; userId = id; allowed = can; backToChat = chat; openApplication = application;
    restore();
  }
  window.addEventListener('popstate', restore);
  window.addEventListener('hashchange', restore);
  window.JKWorkbench = { names, register(id, module) {
    if (!Object.hasOwn(names, id) || typeof module?.mount !== 'function') throw Error('无效工作台注册');
    registry[id] = module;
  }, bind, open, hide, reset, current: () => current && { ...current } };
})();

// 本脚本先于任何应用资源执行；不读取真正的 Storage、Cookie 或会话。
(function () {
  if (location.protocol !== 'file:') return;
  const namespace = 't38-fixture:' + crypto.randomUUID() + ':';
  for (const name of ['localStorage', 'sessionStorage']) {
    const values = new Map(), prefix = namespace + name + ':';
    const store = Object.freeze({
      get length() { return values.size; },
      key(i) { return Array.from(values.keys())[i]?.slice(prefix.length) ?? null; },
      getItem(k) { return values.get(prefix + k) ?? null; },
      setItem(k,v) { values.set(prefix + k, String(v)); },
      removeItem(k) { values.delete(prefix + k); },
      clear() { values.clear(); },
    });
    Object.defineProperty(window, name, {value:store, configurable:false});
    if (window[name] !== store) throw Error('未建立隔离存储');
  }
  const diag = {ready:true, blocked:0};
  const deny = () => { diag.blocked++; throw Error('T38 文件验收不发送网络请求'); };
  // CSP connect-src none 之外的第二层。没有代理，不向任何地址转发。
  Object.defineProperty(window,'fetch',{value:async () => deny(), configurable:false});
  window.open = () => { diag.blocked++; return null; };
  const stopLink = e => {
    const a = e.target.closest?.('a[href]');
    if (!a || a.getAttribute('href').startsWith('#') || (a.hasAttribute('download') && a.protocol === 'blob:')) return;
    e.preventDefault(); e.stopImmediatePropagation(); diag.blocked++;
  };
  document.addEventListener('click', stopLink, true);
  document.addEventListener('auxclick', stopLink, true);
  window.T38 = diag;
})();

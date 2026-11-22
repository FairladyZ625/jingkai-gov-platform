/* 知识库（app id: kb）· v4 综合版 —— 平台一等模块
 * 三件事：① 一个框里搜和问（即时结果 + 带出处的回答，没找到就如实说）② 导入（拖文件 / 粘贴 / 网址 / 对话丢文件，逐份显示解析→切片→标签，查重与新版本识别，确认后入库）③ 读原文（点出处直达高亮段落）
 * 同时 JK.provide('kb', service)：对话与其它应用通过 ctx.kb.search / ask / open / import / spaces 调用。
 * 契约：APP_CONTRACT.md §8；界面只调 api/kb.js；颜色只用 ctx.ui.tag 与主题变量；文案在 config.js */
(function () {
  const C = Object.assign({ name: '知识库', summary: '一问就有出处', placeholder: '搜索或提问', suggestions: [], sampleFiles: [], sampleUrl: '' }, (window.JK_APPCFG || {}).kb || {});
  const API = () => (window.JKApi && window.JKApi.kb) || {};
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const SPACE_ICON = { policy: 'policy', template: 'doc', minutes: 'meeting', rules: 'shield', enterprise: 'building' };
  let current = null;          // 已挂载实例（供 service.open 跳转）
  let pendingOpen = null;      // 未挂载时先记下，挂载后打开

  /* ===================== 对外服务（契约 §8） ===================== */
  const service = {
    async search(q, opts) { opts = opts || {}; return API().search({ q, space: opts.space, limit: opts.limit || 8, filters: opts.filters, sort: opts.sort }); },
    async ask(q, opts) {
      opts = opts || {};
      if (opts.fromChat && current) return current.chatAsk(q);
      return API().ask({ q, space: opts.space, filters: opts.filters, appId: opts.appId, scope: opts.scope });
    },
    followScope(q) { return current && current.followScope(q); },
    async open(id, opts) {
      opts = opts || {};
      const p = { id, highlight: opts.highlight, chunk: opts.chunk };
      if (current) { if (current.nav && current.nav.open) await current.nav.open('kb', 'doc', p); else current.go('doc', p); return { ok: true }; }
      if (window.JKShell && JKShell.openApp) { await JKShell.openApp('kb', 'doc', p); return { ok: true }; }
      pendingOpen = p;
      return { ok: true, pending: true };
    },
    async spaces() { const r = await API().spaces(); return r.items.filter((s) => s.visible).map((s) => ({ id: s.id, name: s.name, count: s.count, hue: (window.JK && JK.hue) ? JK.hue(s.name, 'kbSpace') : 'gray' })); },
    /** import(files | {files, text, url, title}, {space, from}) → {docs, chunks, skipped}；files 可以是浏览器 File 或对话里的 {name, ext, text} */
    async import(input, opts) {
      opts = opts || {}; let files = [], text = null, url = null, title = null;
      if (Array.isArray(input)) files = input; else if (input && typeof input === 'object' && !(input instanceof Blob)) { files = input.files || []; text = input.text || null; url = input.url || null; title = input.title || null; } else if (typeof input === 'string') { if (/^https?:\/\//.test(input.trim())) url = input.trim(); else text = input; }
      const items = [];
      for (const f of files) items.push(f instanceof Blob ? await window.JKKBFiles.read(f) : window.JKKBFiles.fromChat(f));
      const ok = items.filter((x) => x.text); const bad = items.filter((x) => !x.text);
      const r = await API().importNow({ items: ok, text, title, url, space: opts.space, from: opts.from || '对话' });
      r.skipped = (r.skipped || []).concat(bad.map((b) => ({ name: b.name, reason: b.error || '无法读取' })));
      if (window.JK && JK.bus) JK.bus.emit('kb:changed', { added: r.docs.length });
      return r;
    },
  };
  if (window.JK && JK.provide) JK.provide('kb', service);

  JK.registerApp({
    manifest: {
      id: 'kb', name: C.name, short: '知识库', icon: 'book', hue: 'cyan', version: '4.0.0', owner: 'AI 工作组',
      summary: C.summary, routes: ['home', 'library', 'import', 'doc'],
      perms: { view: '搜索、问答、读原文', operate: '导入资料、改标签', approve: '删除资料', admin: '设置空间可见范围' },
      tools: [
        { name: 'kb.search', desc: '在知识库里检索原文片段', params: { q: 'string', space: 'policy|template|minutes|rules|enterprise' } },
        { name: 'kb.ask', desc: '只依据知识库原文回答并标注出处；找不到会如实说', params: { q: 'string' } },
        { name: 'kb.open', desc: '打开原文并高亮段落', params: { id: 'string', highlight: 'string' } },
        { name: 'kb.import', desc: '把文件 / 文字 / 网址导入知识库', params: { files: 'File[]', text: 'string', url: 'string' } },
      ],
      accepts: [{ kind: '资料', ext: ['txt', 'md', 'docx', 'pdf', 'html'], match: /制度|规程|细则|规定|资料|汇编|手册|FAQ|问答|纪要汇编|存入知识库/ }],
      intents: [
        { id: 'kb.import', action: 'import', examples: ['把这个网址导入知识库 https://kfqgw.beijing.gov.cn/…', '把这份文件存进知识库', '收录到知识库'], keywords: ['导入', '存入知识库', '存进知识库', '入库', '收录', '网址导入'], plan: ['打开导入', '读取并解析', '切片、打标签、查重', '确认后入库'] },
        { id: 'kb.expiring', action: 'expiring', examples: ['哪些政策快到期了', '知识库里有哪些已失效的文件'], keywords: ['快到期', '即将到期', '已失效', '过期'], plan: ['打开资料库', '按状态筛选', '列出文件'] },
        { id: 'kb.open', action: 'open', examples: ['打开数据产业若干措施的原文', '看一下实体书店管理办法原文'], keywords: ['打开原文', '看原文', '原文'], plan: ['检索文件', '打开原文', '定位段落'] },
        { id: 'kb.search', action: 'search', examples: ['在知识库搜一下机器人', '找一下关于算力的文件'], keywords: ['搜一下', '找一下', '搜索', '找文件', '有没有文件'], plan: ['打开知识库', '输入关键词', '看结果'] },
        { id: 'kb.ask', action: 'ask', examples: ['数据券补贴最高能拿多少？', '知识库里有没有关于火星基地的政策？', '实体书店有哪些奖励', '信息技术产业局负责什么'], keywords: ['知识库', '出处', '依据', '最高能拿', '规定', '哪个文件', '负责什么', '什么时候截止'], plan: ['打开知识库', '检索相关原文', '摘出原文句子', '标注出处'] },
      ],
      starters: [C.suggestions[0] || '数据券补贴最高能拿多少？', '哪些政策快到期了', '把官网网址导入知识库'],
      demo: [
        { title: '有出处的回答', say: C.suggestions[0] || '数据券补贴最高能拿多少？' },
        { title: '网址导入', say: '把这个网址导入知识库 ' + C.sampleUrl },
        { title: '没找到就说没找到', say: '知识库里有没有关于火星基地的政策？' },
      ],
    },

    mount(el, ctx) {
      const ui = ctx.ui; const icon = ui.icon; const tag = (t, g, v) => ui.tag(t, g, v === 'plain' ? { cls: 'plain' } : v);
      const can = (a) => (ctx.perms && ctx.perms.can ? ctx.perms.can(a) : true);
      const K = () => (ctx.api && ctx.api.kb) || API();
      const S = { tab: 'home', q: '', hits: null, total: 0, terms: [], answer: null, asking: false, filters: {}, showFilters: false, sort: 'rel', space: 'all', spaces: [], stats: null,
        lib: { status: '', space: 'all', list: null, facets: null }, doc: null, docTab: 'text', hl: null, hlChunk: null, back: 'home',
        imp: { step: 0, src: 'file', files: [], text: '', title: '', url: '', items: [], busy: false, result: null } };
      let seq = 0, askSeq = 0, reference = null, timer;
      function followScope(q) {
        if (!reference || /起草|撰写|生成公文|打开原文|导入|发起审签|提交审签/.test(q)) return undefined;
        const title = q.match(/《([^》]+)》/);
        if (title && !reference.title.includes(title[1])) return undefined;
        const named = q.match(/(?:这项|这份|该项|上述)([^，。；？、的]{1,16}?)政策/);
        if (named && !reference.subject.includes(named[1])) return undefined;
        const fieldOnly = /^(?:那|请问)?(?:申报期限|申报条件|适用对象|审签材料|申报时间|什么时候截止)(?:呢|是什么|有哪些|是哪些|到哪天)?[？?。]?$/;
        return named || /(?:这项|这份|该|上述)(?:政策|文件|办法|措施)|上文|上一[份轮]/.test(q) || fieldOnly.test(q) ? reference.key : undefined;
      }
      function renderScope() {
        const box = body.querySelector('#kb-scope');
        if (!box) return;
        box.innerHTML = reference ? `<span>追问范围：《${esc(reference.title)}》 · v${esc(reference.version)}（换题会重新检索）</span> <button class="btn ghost sm" data-op="kb.scope-clear">清除范围</button>` : '';
        if (reference) box.querySelector('button').onclick = () => {
          clearScope(); renderAnswer(); runSearch(); body.querySelector('[data-op="kb.q"]').focus();
        };
      }
      function clearScope() {
        ++askSeq; reference = null; S.asking = false; S.answer = null; renderScope();
      }

      /* ---------- 骨架 ---------- */
      el.innerHTML = `<div class="ap"><div class="ap-h">${ui.appIcon('kb', 'lg')}<div class="grow"><h2>${esc(C.name)}</h2><div class="ap-sum">${esc(C.summary)}</div></div>
        ${can('operate') ? `<button class="btn" data-op="kb.import-open">${icon('upload')}导入资料</button>` : ''}</div>
        <div class="tabs ap-tabs" id="kt"></div><div class="ap-body" id="kb-body"></div></div>`;
      const body = el.querySelector('#kb-body');
      el.querySelector('[data-op="kb.import-open"]') && (el.querySelector('[data-op="kb.import-open"]').onclick = () => go('import'));
      const TABS = [['home', '搜索与问答', 'search'], ['library', '资料库', 'folder']].concat(can('operate') ? [['import', '导入', 'upload']] : []);
      function renderTabs() { el.querySelector('#kt').innerHTML = TABS.map(([k, t, i]) => `<button class="tab ${S.tab === k || (S.tab === 'doc' && S.back === k) ? 'on' : ''}" data-tab="${k}" data-op="kb.tab-${k}">${icon(i)}${t}</button>`).join(''); el.querySelectorAll('[data-tab]').forEach((b) => (b.onclick = () => go(b.dataset.tab))); }

      async function loadMeta() { try { const [sp, st] = await Promise.all([K().spaces(), K().stats()]); S.spaces = sp.items.filter((s) => s.visible); S.stats = st; } catch (e) { S.metaErr = e; } }
      function go(route, params) {
        params = params || {};
        if (route === 'doc') { if (reference && params.id !== reference.id) clearScope(); if (S.tab !== 'doc') S.back = S.tab; S.tab = 'doc'; S.hl = params.highlight || null; S.hlChunk = params.chunk != null ? params.chunk : null; S.docTab = 'text'; openDoc(params.id); return; }
        if (route === 'search') route = 'home';
        S.tab = ['home', 'library', 'import'].includes(route) ? route : 'home';
        if (route === 'search') { route = 'home'; params.ask = params.ask !== false; }
        if (route === 'home' && params.q != null) { S.q = params.q; }
        if (route === 'library' && params.status != null) S.lib.status = params.status;
        if (route === 'import' && params.src) S.imp.src = params.src;
        render();
        if (S.tab === 'library') loadLib();
        if (route === 'home' && params.q) { runSearch(); if (params.ask) runAsk(); }
      }

      /* ===================== 搜索与问答 ===================== */
      const spaceName = (id) => (S.spaces.find((s) => s.id === id) || {}).name || id;
      const isQuestion = (q) => /[?？吗呢]$|多少|什么|怎么|如何|哪些|是否|能否|能不能|几|为什么|谁/.test(q);
      function renderHome() {
        const st = S.stats || {};
        body.innerHTML = `
          <div class="kb-q">
            <div class="kb-box"><span class="kb-ico">${icon('search')}</span><input class="kb-input" data-op="kb.q" placeholder="${esc(C.placeholder)}" value="${esc(S.q)}" autocomplete="off"><button class="btn primary" data-op="kb.ask">${icon('sparkles')}问 AI</button></div>
            <div id="kb-scope" class="meta" aria-live="polite"></div>
            <div class="row wrap kb-chips" id="kb-sp">
              <button class="chip-btn ${S.space === 'all' ? 'on' : ''}" data-sp="all">全部 <span class="n">${st.docs ?? ''}</span></button>
              ${S.spaces.map((s) => `<button class="chip-btn ${S.space === s.id ? 'on' : ''}" data-sp="${s.id}" data-op="kb.space-${s.id}">${esc(s.name)} <span class="n">${s.count}</span></button>`).join('')}
              <span class="sp"></span><button class="btn ghost sm ${S.showFilters || Object.values(S.filters).some(Boolean) ? 'on' : ''}" data-op="kb.filters">${icon('filter')}筛选${Object.values(S.filters).filter(Boolean).length ? ` · ${Object.values(S.filters).filter(Boolean).length}` : ''}</button>
            </div>
            <div class="meta kb-summary">${st.docs ?? 0} 份资料 · ${S.spaces.length} 个可见空间 · 真实公开资料 ${st.real || 0} 份 + 示例资料 ${st.example || 0} 份${Object.entries(st.otherSources || {}).map(([from, n]) => ` + ${esc(from)} ${n} 份`).join('')}</div>
            <div id="kb-filt" class="${S.showFilters ? '' : 'hide'}"></div>
          </div>
          <div id="kb-ans"></div><div id="kb-res"></div>`;
        const inp = body.querySelector('[data-op="kb.q"]');
        renderScope();
        inp.oninput = () => { S.q = inp.value; ++askSeq; ++seq; S.asking = false; S.answer = null; renderAnswer(); clearTimeout(timer); timer = setTimeout(runSearch, 140); };
        inp.onkeydown = (e) => { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); S.q = inp.value; runSearch(); if (S.q.trim()) runAsk(); } };
        body.querySelector('[data-op="kb.ask"]').onclick = () => { S.q = inp.value; runSearch(); runAsk(); };
        body.querySelectorAll('[data-sp]').forEach((b) => (b.onclick = () => { clearScope(); S.space = b.dataset.sp; body.querySelectorAll('[data-sp]').forEach((x) => x.classList.toggle('on', x === b)); renderAnswer(); runSearch(); }));
        body.querySelector('[data-op="kb.filters"]').onclick = () => { S.showFilters = !S.showFilters; body.querySelector('#kb-filt').classList.toggle('hide', !S.showFilters); if (S.showFilters) renderFilters(); };
        if (S.showFilters) renderFilters();
        renderAnswer(); renderResults();
      }
      function renderFilters() {
        const fc = (S.facets || (S.stats && null)) || {}; const box = body.querySelector('#kb-filt'); if (!box) return;
        const opt = (k, list, label) => `<select class="select sm" data-f="${k}" data-op="kb.f-${k}"><option value="">${label}</option>${(list || []).map((x) => `<option value="${esc(x.k)}" ${S.filters[k] === x.k ? 'selected' : ''}>${esc(x.k)}（${x.n}）</option>`).join('')}</select>`;
        const F = (S.stats && S.stats.facets) || fc;
        box.innerHTML = `<div class="kb-filt">${opt('status', F.status, '全部状态')}${opt('kind', F.kind, '全部类型')}${opt('year', F.year, '全部年份')}${opt('org', F.org, '全部发文机关')}
          <label class="check"><input type="checkbox" data-f="validOnly" ${S.filters.validOnly ? 'checked' : ''}>只看现行有效</label><span class="sp"></span>${Object.values(S.filters).some(Boolean) ? '<button class="btn ghost sm" data-op="kb.f-clear">清空</button>' : ''}</div>`;
        box.querySelectorAll('select[data-f]').forEach((s) => (s.onchange = () => { S.filters[s.dataset.f] = s.value; afterFilter(); }));
        box.querySelector('input[data-f]').onchange = (e) => { S.filters.validOnly = e.target.checked; afterFilter(); };
        const cl = box.querySelector('[data-op="kb.f-clear"]'); if (cl) cl.onclick = () => { S.filters = {}; afterFilter(); };
      }
      function afterFilter() { clearScope(); renderAnswer(); runSearch(); renderFilters(); const b = body.querySelector('[data-op="kb.filters"]'); const n = Object.values(S.filters).filter(Boolean).length; if (b) b.innerHTML = `${icon('filter')}筛选${n ? ' · ' + n : ''}`; }
      const curFilters = () => { const f = {}; Object.entries(S.filters).forEach(([k, v]) => { if (v) f[k] = v; }); if (S.space !== 'all') f.space = S.space; return f; };
      async function runSearch() {
        const my = ++seq; const q = S.q.trim();
        if (S.answer && !S.asking && S.answer.q !== q) { S.answer = null; renderAnswer(); }
        if (!q) { S.hits = null; renderResults(); return; }
        try { const r = await K().search({ q, scope: followScope(q), limit: 30, filters: curFilters(), sort: S.sort }); if (my !== seq) return; S.hits = r.hits; S.total = r.total; S.terms = r.terms || []; S.facets = r.facets; renderResults(); } catch (e) { if (my === seq) { S.hits = []; renderResults(e); } }
      }
      async function runAsk() {
        const q = S.q.trim(); if (!q) return;
        clearTimeout(timer);
        const my = ++askSeq, scope = followScope(q);
        if (!scope) { reference = null; renderScope(); }
        S.asking = true; S.answer = null; S.showWeak = false; renderAnswer();
        try {
          const a = await K().ask({ q, filters: curFilters(), scope });
          if (my !== askSeq) return;
          S.answer = { ...a, q };
          const c = a.citations && a.citations[0];
          if (c && !scope) reference = { id: c.id, key: c.citationId || c.id + '@v' + (c.version || 1), version: c.version || 1, title: c.title, subject: q + ' ' + c.title + ' ' + c.snippet };
        } catch (e) { if (my !== askSeq) return; S.answer = { error: e.message || '出错了' }; }
        S.asking = false; renderScope(); renderAnswer(); renderResults();
        return S.answer;
      }
      const mark = (s) => { let out = esc(s); (S.terms || []).filter((t) => t.length > 1).sort((a, b) => b.length - a.length).slice(0, 8).forEach((t) => { out = out.split(esc(t)).join('<mark>' + esc(t) + '</mark>'); }); return out.replace(/<\/mark><mark>/g, ''); };
      const statusTag = (s) => (s ? tag(s, 'kbStatus') : '');
      const srcLine = (h) => [h.source && h.source.docNo, (h.source && h.source.org || '').replace(/^北京经济技术开发区/, '经开区'), h.source && h.source.date].filter(Boolean).map(esc).join(' · ');
      function resultRow(h) {
        const more = (h.relatedPassages || []).map(p => `<button class="btn ghost sm" data-passage="${esc(p.snippet)}" data-index="${esc(p.chunk)}" title="${esc(p.snippet)}">片段 ${esc(p.passage)} · ${esc(p.snippet.slice(0, 32))}</button>`).join('');
        return `<div class="li kb-hit" data-doc="${esc(h.id)}" data-chunk="${h.chunk != null ? h.chunk : ''}" data-op="kb.hit-${esc(h.id)}">
          <span class="kb-sico">${icon(SPACE_ICON[h.space] || 'file')}</span>
          <div class="grow"><div class="ttl clip">${mark(h.title)}</div>${h.snippet ? `<div class="kb-snip">${mark(h.snippet)}</div>` : ''}<div class="meta clip">${srcLine(h)} · ${esc(h.id)}${h.chunk != null ? ' · 片段 ' + (h.passage || h.chunk + 1) : ''}</div>
          ${more ? '<details><summary class="meta">同一资料的其他命中片段</summary><div class="col">' + more + '</div></details>' : ''}</div>
          <div class="kb-tags">${h.example ? tag('示例', 'kbStatus') : ''}${h.status !== '现行有效' ? statusTag(h.status) : ''}</div></div>`;
      }
      function bindHits(root) { root.querySelectorAll('[data-doc]').forEach((r) => (r.onclick = e => {
        const p = e.target.closest('[data-passage]');
        if (p) return go('doc', { id: r.dataset.doc, chunk: +p.dataset.index, highlight: p.dataset.passage });
        if (!e.target.closest('details')) go('doc', { id: r.dataset.doc, chunk: r.dataset.chunk ? +r.dataset.chunk : null,
          highlight: S.hits?.find(h => h.id === r.dataset.doc && h.passage)?.snippet });
      })); }
      function renderResults(err) {
        const box = body.querySelector('#kb-res'); if (!box) return;
        if (err) { box.innerHTML = `<div class="callout h-red">${icon('alert')}<div>${esc(err.message || '搜索出错')}</div></div>`; return; }
        if (S.hits == null) {
          const st = S.stats || {}; const recent = (st.recent || []).slice(0, 5);
          box.innerHTML = `<div class="sect">试试这样问</div><div class="kb-sugg">${C.suggestions.map((s, i) => `<button class="kb-sg" data-sg="${esc(s)}" data-op="kb.sugg-${i}">${icon('sparkles')}<span>${esc(s)}</span></button>`).join('')}</div>
            <div class="sect">最近入库</div><div class="list lined card flat kb-list">${recent.map(resultRow).join('') || '<div class="meta" style="padding:12px">暂无</div>'}</div>
            <div class="kb-foot">${icon('globe')}官网同步 ${esc(st.fetched || '')} · ${st.chunks || 0} 个片段</div>`;
          box.querySelectorAll('[data-sg]').forEach((b) => (b.onclick = () => { S.q = b.dataset.sg; body.querySelector('[data-op="kb.q"]').value = S.q; runSearch(); runAsk(); }));
          bindHits(box); return;
        }
        if (!S.hits.length) { box.innerHTML = S.answer ? '' : ui.empty({ icon: 'search', title: '没有匹配的资料', desc: '换个关键词，或清空筛选；也可以把资料导入进来', action: can('operate') ? '导入资料' : '' }); const b = box.querySelector('.empty .btn'); if (b) b.onclick = () => go('import'); return; }
        if (S.answer && S.answer.notFound && !S.showWeak) { box.innerHTML = `<div class="kb-more"><button class="btn ghost sm" data-op="kb.weak">查看检索返回的 ${S.total} 份候选资料</button></div>`; box.querySelector('[data-op="kb.weak"]').onclick = () => { S.showWeak = true; renderResults(); }; return; }
        box.innerHTML = `<div class="row kb-rh"><span class="meta">找到 <b class="t-2">${S.total}</b> 份相关资料</span><span class="sp"></span><div class="seg" data-op="kb.sort"><button class="${S.sort === 'rel' ? 'on' : ''}" data-s="rel">最相关</button><button class="${S.sort === 'date' ? 'on' : ''}" data-s="date">最新</button></div></div>
          <div class="list lined card flat kb-list">${S.hits.slice(0, 12).map(resultRow).join('')}</div>${S.hits.length > 12 ? `<div class="meta kb-more">还有 ${S.total - 12} 份，换个更具体的说法试试</div>` : ''}`;
        box.querySelectorAll('[data-s]').forEach((b) => (b.onclick = () => { S.sort = b.dataset.s; runSearch(); }));
        bindHits(box);
      }
      /* 回答：只摘原文；[n] 变成可点的出处角标 */
      function mdAnswer(text) {
        const lines = String(text).split('\n'); let html = ''; let inList = false;
        const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\[(\d+)\]/g, '<span class="cite" data-cite="$1" data-op="kb.cite-$1">$1</span>');
        lines.forEach((l) => {
          if (/^- /.test(l)) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${inline(l.slice(2))}</li>`; return; }
          if (inList) { html += '</ul>'; inList = false; }
          if (!l.trim()) return;
          if (/^> /.test(l)) html += `<div class="kb-note">${inline(l.slice(2))}</div>`; else if (/^\*\*.+\*\*$/.test(l)) html += `<div class="kb-sub">${inline(l.replace(/\*\*/g, ''))}</div>`; else html += `<p>${inline(l)}</p>`;
        });
        if (inList) html += '</ul>'; return html;
      }
      const CONF = { high: ['依据充分', 'green'], mid: ['依据较充分', 'blue'], low: ['仅供参考', 'amber'] };
      function renderAnswer() {
        const box = body.querySelector('#kb-ans'); if (!box) return;
        if (S.asking) { box.innerHTML = `<div class="card kb-ans"><div class="row"><span class="kb-ai">${icon('sparkles')}</span><b>正在查找原文…</b></div><div class="skel" style="margin-top:14px;width:86%"></div><div class="skel" style="margin-top:8px;width:64%"></div></div>`; return; }
        const a = S.answer; if (!a) { box.innerHTML = ''; return; }
        if (a.error) { box.innerHTML = `<div class="callout h-red">${icon('alert')}<div>${esc(a.error)}</div></div>`; return; }
        if (a.notFound) {
          box.innerHTML = `<div class="card kb-ans kb-nf" data-op="kb.answer"><div class="row"><span class="kb-ai nf">${icon('info')}</span><b>知识库里没找到</b>${tag('未找到依据', 'kbStatus')}</div>
            <p class="kb-nf-msg">${esc(a.message)}</p>
            ${a.near && a.near.length ? `<div class="meta" style="margin:10px 0 6px">可能相关（但不足以回答）：</div><div class="col">${a.near.map((d) => `<div class="src" data-doc="${esc(d.id)}">${icon('file')}<div class="grow clip">${esc(d.title)}</div></div>`).join('')}</div>` : ''}
            <div class="row wrap" style="margin-top:14px">${can('operate') ? '<button class="btn sm" data-op="kb.nf-import">' + icon('upload') + '导入相关资料</button>' : ''}<button class="btn ghost sm" data-op="kb.nf-rephrase">换个说法</button></div></div>`;
          bindHits(box); renderResults(); const imp = box.querySelector('[data-op="kb.nf-import"]'); if (imp) imp.onclick = () => go('import');
          box.querySelector('[data-op="kb.nf-rephrase"]').onclick = () => { const i = body.querySelector('[data-op="kb.q"]'); i.focus(); i.select(); };
          return;
        }
        const [cl, ch] = CONF[a.confidence] || CONF.mid;
        box.innerHTML = `<div class="card kb-ans" data-op="kb.answer">
          <div class="row"><span class="kb-ai">${icon('sparkles')}</span><b>回答</b>${ui.tag(cl, null, { hue: ch, cls: 'plain' })}<span class="sp"></span><span class="meta">${esc(a.routeNote || '只摘原文，不改写')}</span></div>
          <div class="kb-md">${mdAnswer(a.answer)}</div>
          <div class="sect" style="margin-top:16px">出处</div>
          <div class="col">${a.citations.map((c) => `<div class="src kb-src" data-cite-row="${c.n}" data-op="kb.src-${c.n}"><span class="cite">${c.n}</span><div class="grow"><div class="clip">${esc(c.title)}</div><div class="meta clip">${[c.source.docNo, (c.source.org || '').replace(/^北京经济技术开发区/, '经开区'), c.source.date].filter(Boolean).map(esc).join(' · ')}</div></div>${c.example ? tag('示例', 'kbStatus') : ''}${c.status !== '现行有效' ? statusTag(c.status) : ''}${c.source.url ? `<a class="btn ghost sm kb-ext" href="${esc(c.source.url)}" target="_blank" rel="noopener" title="官网原文">${icon('external')}</a>` : ''}</div>`).join('')}</div>
          <div class="row wrap kb-act">${(a.followups || []).map((f, i) => `<button class="chip-btn" data-fu="${i}">${esc(f.label)}</button>`).join('')}<span class="sp"></span>
            <button class="btn ghost sm" data-op="kb.copy">${icon('copy')}复制</button>${ctx.nav && ctx.nav.open ? `<button class="btn ghost sm" data-op="kb.todoc">${icon('doc')}写进公文</button>` : ''}</div></div>`;
        const openCite = (n) => { const c = a.citations.find((x) => String(x.n) === String(n)); if (c) go('doc', { id: c.id, highlight: c.snippet, chunk: c.chunk }); };
        box.querySelectorAll('[data-cite]').forEach((x) => (x.onclick = () => openCite(x.dataset.cite)));
        box.querySelectorAll('[data-cite-row]').forEach((x) => (x.onclick = (e) => { if (e.target.closest('a')) return; openCite(x.dataset.citeRow); }));
        box.querySelectorAll('[data-fu]').forEach((b) => (b.onclick = () => { const f = a.followups[+b.dataset.fu]; if (/起草/.test(f.label) && ctx.nav && ctx.nav.chat) return ctx.nav.chat(f.say); S.q = f.say; body.querySelector('[data-op="kb.q"]').value = S.q; runSearch(); runAsk(); }));
        box.querySelector('[data-op="kb.copy"]').onclick = () => { const txt = a.answer.replace(/\*\*/g, '') + '\n\n出处：\n' + a.citations.map((c) => `[${c.n}] ${c.title}${c.source.docNo ? '（' + c.source.docNo + '）' : ''} ${c.source.url || ''}`).join('\n'); (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(() => ui.toast('已复制回答和出处'), () => ui.toast('复制失败，请手动选择文字', { type: 'warn' })); };
        const td = box.querySelector('[data-op="kb.todoc"]'); if (td) td.onclick = () => ctx.nav.open('document', 'new', { from: 'kb', question: a.q, quote: a.citations.map((c) => ({ title: c.title, docNo: c.source.docNo, text: c.snippet, url: c.source.url })) });
      }

      /* ===================== 资料库 ===================== */
      async function loadLib() {
        const q = {}; if (S.lib.status) q.status = S.lib.status; if (S.lib.space !== 'all') q.space = S.lib.space;
        try { const r = await K().list(q); S.lib.list = r.hits; S.lib.total = r.total; } catch (e) { S.lib.list = []; S.lib.err = e; }
        if (S.tab === 'library') renderLib();
      }
      function renderLib() {
        const st = (S.stats && S.stats.status) || {}; const all = (S.stats && S.stats.docs) || 0;
        const k = [['', '全部', all, 'gray'], ['现行有效', '现行有效', st['现行有效'] || 0, 'green'], ['即将到期', '即将到期', st['即将到期'] || 0, 'amber'], ['已失效', '已失效', st['已失效'] || 0, 'red']];
        if (st['已更新']) k.push(['已更新', '已更新', st['已更新'], 'gray']);
        body.innerHTML = `<div class="kpis" style="--n:${k.length}">${k.map(([v, l, n, h]) => `<button class="kpi-c ${S.lib.status === v ? 'on h-' + h : ''}" data-st="${v}" data-op="kb.st-${v || 'all'}"><div class="v">${n}</div><div class="l">${l}</div></button>`).join('')}</div>
          <div class="row wrap kb-chips" style="margin-top:16px"><button class="chip-btn ${S.lib.space === 'all' ? 'on' : ''}" data-ls="all">全部空间</button>${S.spaces.map((s) => `<button class="chip-btn ${S.lib.space === s.id ? 'on' : ''}" data-ls="${s.id}">${esc(s.name)} <span class="n">${s.count}</span></button>`).join('')}<span class="sp"></span>${can('admin') ? `<button class="btn ghost sm" data-op="kb.vis">${icon('lock')}可见范围</button>` : ''}</div>
          <div id="kb-lib" style="margin-top:12px"></div>`;
        body.querySelectorAll('[data-st]').forEach((b) => (b.onclick = () => { S.lib.status = b.dataset.st; S.lib.list = null; renderLib(); loadLib(); }));
        body.querySelectorAll('[data-ls]').forEach((b) => (b.onclick = () => { S.lib.space = b.dataset.ls; S.lib.list = null; renderLib(); loadLib(); }));
        const vb = body.querySelector('[data-op="kb.vis"]'); if (vb) vb.onclick = visibilityModal;
        const box = body.querySelector('#kb-lib');
        if (S.lib.list == null) { box.innerHTML = '<div class="card"><div class="skel" style="width:70%"></div><div class="skel" style="width:50%;margin-top:10px"></div></div>'; return; }
        if (!S.lib.list.length) { box.innerHTML = ui.empty({ icon: 'folder', title: '这里还没有资料', desc: '换个筛选，或导入第一份资料', action: can('operate') ? '导入资料' : '' }); const b = box.querySelector('.empty .btn'); if (b) b.onclick = () => go('import'); return; }
        const shown = S.lib.list.slice(0, 60);
        box.innerHTML = `<div class="list lined card flat kb-list">${shown.map((h) => `<div class="li kb-hit" data-doc="${esc(h.id)}" data-op="kb.doc-${esc(h.id)}"><span class="kb-sico">${icon(SPACE_ICON[h.space] || 'file')}</span><div class="grow"><div class="ttl clip">${esc(h.title)}</div><div class="meta clip">${srcLine(h)}${h.expire ? ' · 有效期至 ' + esc(h.expire) : ''}</div></div><div class="kb-tags">${tag(h.kind, 'kbKind', 'plain')}${h.example ? tag('示例', 'kbStatus') : statusTag(h.status)}</div></div>`).join('')}</div>${S.lib.list.length > 60 ? `<div class="meta kb-more">共 ${S.lib.total} 份，已显示 60 份；用上方搜索更快</div>` : ''}`;
        bindHits(box);
      }
      async function visibilityModal() {
        const roles = [['admin', '管理员'], ['leader', '审签领导'], ['member', '经办人员'], ['partner', '外部协作者']];
        const sp = (await K().spaces()).items;
        ui.modal({ title: '空间可见范围', okText: '保存', body: `<div class="meta" style="margin-bottom:12px">勾选哪些角色能看到该空间（看不到的空间不会出现在搜索和问答里）</div><table class="tbl"><thead><tr><th>空间</th>${roles.map((r) => `<th>${r[1]}</th>`).join('')}</tr></thead><tbody>${sp.map((s) => `<tr><td>${esc(s.name)}</td>${roles.map((r) => `<td><input type="checkbox" data-vs="${s.id}" data-vr="${r[0]}" ${s.roles.includes(r[0]) ? 'checked' : ''} ${r[0] === 'admin' ? 'disabled' : ''}></td>`).join('')}</tr>`).join('')}</tbody></table>`,
          ok: async (m) => { const root = m && m.querySelector ? m : document; for (const s of sp) { const rs = ['admin'].concat([...root.querySelectorAll(`[data-vs="${s.id}"]:checked`)].map((x) => x.dataset.vr).filter((x) => x !== 'admin')); await K().setSpaceRoles(s.id, rs); } ui.toast('可见范围已保存'); await loadMeta(); render(); } });
      }

      /* ===================== 原文阅读 ===================== */
      async function openDoc(id) {
        S.doc = null; render();
        try { const r = await K().get(id); S.doc = r.item; } catch (e) { S.doc = { error: e.message || '打不开' }; }
        if (S.tab === 'doc') renderDoc();
      }
      function hlRange(d) {
        const t = d.text; if (S.hl) { const s = S.hl.replace(/^…|…$/g, ''); let i = t.indexOf(s); if (i < 0) { const flat = t.replace(/\n/g, ''); const j = flat.indexOf(s); if (j >= 0) { let c = 0, k = 0; for (; k < t.length && c < j; k++) if (t[k] !== '\n') c++; i = k; } } if (i < 0) i = t.indexOf(s.slice(0, 24)); if (i >= 0) { let end = i, c = 0; while (end < t.length && c < s.length) { if (t[end] !== '\n') c++; end++; } return [i, end]; } }
        if (S.hlChunk != null && d.chunkList[S.hlChunk]) { const c = d.chunkList[S.hlChunk]; return [c.start, c.end]; }
        return null;
      }
      function renderDoc() {
        const d = S.doc;
        if (!d) { body.innerHTML = '<div class="card"><div class="skel" style="width:60%"></div><div class="skel" style="width:90%;margin-top:14px"></div><div class="skel" style="width:80%;margin-top:8px"></div></div>'; return; }
        if (d.error) { body.innerHTML = `<button class="btn ghost sm" data-op="kb.back">${icon('chevron-left')}返回</button>` + ui.empty({ icon: 'lock', title: '打不开这份资料', desc: d.error }); body.querySelector('[data-op="kb.back"]').onclick = () => go(S.back); return; }
        const range = hlRange(d);
        const t = d.text; const parts = range ? [t.slice(0, range[0]), t.slice(range[0], range[1]), t.slice(range[1])] : [t, '', ''];
        const para = (s) => esc(s).replace(/\n/g, '</p><p>');
        const textHtml = `<p>${para(parts[0])}${parts[1] ? `<mark class="kb-hl" data-op="kb.hl">${para(parts[1]).replace(/<\/p><p>/g, '</mark></p><p><mark class="kb-hl">')}</mark>` : ''}${para(parts[2])}</p>`.replace(/<p><\/p>/g, '');
        const canEdit = can('operate'); const canDel = can('approve') || can('admin');
        body.innerHTML = `<div class="row kb-dh"><button class="btn ghost sm" data-op="kb.back">${icon('chevron-left')}返回</button><span class="sp"></span>
            ${d.source.url ? `<a class="btn sm" href="${esc(d.source.url)}" target="_blank" rel="noopener" data-op="kb.ext">${icon('external')}官网原文</a>` : ''}
            ${canEdit || canDel ? `<button class="btn ghost sm icon" data-op="kb.more" title="更多">${icon('more')}</button>` : ''}</div>
          <h3 class="kb-title">${esc(d.title)}</h3>
          <div class="row wrap kb-dmeta">${tag(d.spaceName, 'kbSpace')}${d.example ? tag('示例', 'kbStatus') : statusTag(d.status)}${d.version > 1 ? tag('第 ' + d.version + ' 版', 'kbStatus', 'plain') : ''}<span class="meta">${srcLine(d)}${d.expire ? ' · 有效期至 ' + esc(d.expire) : ''}</span></div>
          ${d.newer ? `<div class="callout h-blue" style="margin-top:12px">${icon('info')}<div class="grow">这份资料已有新版本（第 ${d.newer.version} 版，${esc(d.newer.date)}）。</div><button class="btn sm" data-newer="${esc(d.newer.id)}">看新版</button></div>` : ''}
          ${d.status === '已失效' ? `<div class="callout h-red" style="margin-top:12px">${icon('alert')}<div>该文件已失效，仅供查阅历史，不能作为现行依据。</div></div>` : ''}
          ${d.parse === 'simulated' ? `<div class="callout h-amber" style="margin-top:12px">${icon('alert')}<div>这份文件是“模拟解析”：原型读不出正文，正式版由后端解析全文。</div></div>` : ''}
          <div class="tabs" style="margin:16px 0 0">${[['text', '原文'], ['chunks', `片段 ${d.chunks}`], ['info', '信息']].map(([k, l]) => `<button class="tab ${S.docTab === k ? 'on' : ''}" data-dt="${k}" data-op="kb.dt-${k}">${l}</button>`).join('')}</div>
          <div id="kb-dv"></div>`;
        body.querySelector('[data-op="kb.back"]').onclick = () => go(S.back);
        body.querySelectorAll('[data-dt]').forEach((b) => (b.onclick = () => { S.docTab = b.dataset.dt; renderDoc(); }));
        const nb = body.querySelector('[data-newer]'); if (nb) nb.onclick = () => go('doc', { id: nb.dataset.newer });
        const mb = body.querySelector('[data-op="kb.more"]'); if (mb) mb.onclick = (e) => docMenu(e, d, canEdit, canDel);
        const dv = body.querySelector('#kb-dv');
        if (S.docTab === 'text') {
          dv.innerHTML = `<div class="kb-tagrow">${(d.tags || []).map((x) => tag(x, 'kbTag', 'plain')).join('')}</div><article class="kb-doc">${textHtml}</article>`;
          const m = dv.querySelector('.kb-hl'); if (m) setTimeout(() => m.scrollIntoView({ block: 'center', behavior: 'smooth' }), 60);
        } else if (S.docTab === 'chunks') {
          dv.innerHTML = `<div class="meta" style="margin:12px 0">自动按段落切成 ${d.chunks} 个片段，问答时按片段检索和引用。点一个片段在原文中定位。</div><div class="list lined card flat">${d.chunkList.map((c) => `<div class="li" data-ck="${c.i}"><span class="kb-ckn num">${c.i + 1}</span><div class="grow"><div class="ttl clip">${esc(c.head || '（无小标题）')}</div><div class="meta clip">${esc(d.text.slice(c.start, c.end).replace(/\n/g, ' ').slice(0, 80))}</div></div><span class="meta num">${c.end - c.start} 字</span></div>`).join('')}</div>`;
          dv.querySelectorAll('[data-ck]').forEach((r) => (r.onclick = () => { S.hl = null; S.hlChunk = +r.dataset.ck; S.docTab = 'text'; renderDoc(); }));
        } else {
          const row = (k, v) => v ? `<tr><td class="t-2" style="width:120px">${k}</td><td>${v}</td></tr>` : '';
          dv.innerHTML = `<table class="tbl" style="margin-top:12px"><tbody>${row('所属空间', esc(d.spaceName))}${row('类型', esc(d.kind))}${row('发文字号', esc(d.source.docNo))}${row('发文机关', esc(d.source.org))}${row('日期', esc(d.source.date))}${row('有效期至', esc(d.expire))}${row('来源', esc(d.from) + (d.real ? ' · 真实公开资料' : d.example ? ' · 示例（虚构）' : ''))}${row('原文链接', d.source.url ? `<a href="${esc(d.source.url)}" target="_blank" rel="noopener">${esc(d.source.url)}</a>` : '')}${row('入库', esc([d.uploadedBy, d.addedAt].filter(Boolean).join(' · ')))}${row('解析方式', d.parse === 'simulated' ? '模拟解析' : '浏览器真实解析 / 官网正文')}${row('版本', d.versions && d.versions.length ? `第 ${d.version} 版；历史：` + d.versions.map((v) => `<a href="javascript:void 0" data-ver="${esc(v.id)}">第 ${v.version} 版（${esc(v.date)}）</a>`).join('、') : '第 ' + d.version + ' 版')}</tbody></table>`;
          dv.querySelectorAll('[data-ver]').forEach((a) => (a.onclick = () => go('doc', { id: a.dataset.ver })));
        }
      }
      function docMenu(e, d, canEdit, canDel) {
        const items = []; if (canEdit) items.push({ v: 'tags', label: '编辑标签', icon: 'edit' }); if (canDel) items.push({ v: 'del', label: '删除', icon: 'trash' });
        ui.menu(e.currentTarget, items, (v) => (v === 'tags' ? editTags(d) : delDoc(d)));
      }
      function editTags(d) {
        ui.modal({ title: '编辑标签', okText: '保存', body: `<div class="field"><label>标签（用空格或逗号分隔）</label><input class="input" id="kb-tg" value="${esc((d.tags || []).join(' '))}"></div>`,
          ok: async (m) => { const root = m && m.querySelector ? m : document; const v = root.querySelector('#kb-tg').value.split(/[\s,，]+/).filter(Boolean); await K().update(d.id, { tags: v }); ui.toast('标签已保存'); openDoc(d.id); } });
      }
      async function delDoc(d) {
        if (!(await ui.confirm(`删除《${d.title.slice(0, 20)}》？删除后搜索和问答都不再引用它。`, { danger: true }))) return;
        await K().remove(d.id); await loadMeta(); ui.toast('已删除', { ms: 5000, action: { label: '撤销', fn: async () => { await K().restore(d.id); await loadMeta(); ui.toast('已恢复'); } } }); ctx.bus && ctx.bus.emit('kb:changed', {}); go(S.back);
      }

      /* ===================== 导入（三步：选资料 → 确认 → 完成） ===================== */
      function renderImport() {
        const I = S.imp; const steps = ['选资料', '解析确认', '完成'];
        body.innerHTML = `<div class="wiz-steps">${steps.map((s, i) => `${i ? `<span class="wiz-line ${i <= I.step ? 'done' : ''}"></span>` : ''}<span class="wiz-step ${i === I.step ? 'on' : i < I.step ? 'done' : ''}"><span class="n">${i < I.step ? '✓' : i + 1}</span>${s}</span>`).join('')}</div><div id="kb-iw"></div>`;
        const w = body.querySelector('#kb-iw');
        if (I.step === 0) impPick(w); else if (I.step === 1) impReview(w); else impDone(w);
      }
      function impPick(w) {
        const I = S.imp;
        w.innerHTML = `<div class="q">从哪里导入？</div><div class="q-sub">支持一次多份；入库前可以先看解析结果、改标签</div>
          <div class="seg" style="margin-bottom:16px">${[['file', '文件'], ['text', '粘贴文字'], ['url', '网址']].map(([k, l]) => `<button class="${I.src === k ? 'on' : ''}" data-src="${k}" data-op="kb.src-${k}">${l}</button>`).join('')}</div>
          <div id="kb-srcb"></div>
          <div class="wiz-foot"><span class="meta" id="kb-pick-n"></span><span class="sp"></span><button class="btn primary" data-op="kb.parse" disabled>开始解析</button></div>`;
        w.querySelectorAll('[data-src]').forEach((b) => (b.onclick = () => { I.src = b.dataset.src; impPick(w); }));
        const box = w.querySelector('#kb-srcb'); const goBtn = w.querySelector('[data-op="kb.parse"]'); const nEl = w.querySelector('#kb-pick-n');
        const upd = () => { const n = I.src === 'file' ? I.files.length : I.src === 'text' ? (I.text.trim() ? 1 : 0) : (I.url.trim() ? 1 : 0); goBtn.disabled = !n; goBtn.textContent = n > 1 ? `开始解析（${n} 份）` : '开始解析'; nEl.textContent = I.src === 'file' && n ? `已选 ${n} 份` : ''; };
        if (I.src === 'file') {
          box.innerHTML = `<label class="drop kb-drop" data-op="kb.drop"><input type="file" multiple hidden accept=".txt,.md,.docx,.pdf,.html,.htm,.csv,.doc,.wps"><div class="kb-drop-ico">${icon('upload')}</div><div class="kb-drop-t">把文件拖到这里，或点击选择</div><div class="meta">txt · md · docx 直接读正文；pdf 尽量读，读不出会标“模拟解析”</div></label>
            <div class="col" id="kb-fl" style="margin-top:12px"></div>
            ${C.sampleFiles.length ? `<button class="btn ghost sm" data-op="kb.samples" style="margin-top:8px">${icon('sparkles')}没有文件？用示例文件试试</button>` : ''}`;
          const drop = box.querySelector('.kb-drop'); const fi = box.querySelector('input[type=file]');
          const add = (list) => { [...list].forEach((f) => { if (!I.files.some((x) => x.name === f.name && x.size === f.size)) I.files.push(f); }); listFiles(); upd(); };
          fi.onchange = () => add(fi.files);
          drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); }; drop.ondragleave = () => drop.classList.remove('over');
          drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); };
          const sb = box.querySelector('[data-op="kb.samples"]'); if (sb) sb.onclick = () => add(C.sampleFiles.map((s) => new File([s.text], s.name, { type: 'text/plain' })));
          function listFiles() { box.querySelector('#kb-fl').innerHTML = I.files.map((f, i) => `<div class="file">${icon('file')}<div class="grow clip">${esc(f.name)}</div><span class="meta">${f.size > 1024 ? Math.round(f.size / 1024) + ' KB' : f.size + ' B'}</span><button class="btn ghost sm icon" data-rm="${i}" title="移除">${icon('x')}</button></div>`).join(''); box.querySelectorAll('[data-rm]').forEach((b) => (b.onclick = () => { I.files.splice(+b.dataset.rm, 1); listFiles(); upd(); })); }
          listFiles();
        } else if (I.src === 'text') {
          box.innerHTML = `<div class="col gap3"><input class="input" data-op="kb.ptitle" placeholder="标题（可不填，自动取第一行）" value="${esc(I.title)}"><textarea class="textarea" data-op="kb.ptext" rows="9" placeholder="把文字粘贴到这里，比如一段通知、问答口径、会议要点">${esc(I.text)}</textarea></div>`;
          box.querySelector('[data-op="kb.ptitle"]').oninput = (e) => { I.title = e.target.value; };
          box.querySelector('[data-op="kb.ptext"]').oninput = (e) => { I.text = e.target.value; upd(); };
        } else {
          box.innerHTML = `<div class="kb-box sm"><span class="kb-ico">${icon('link')}</span><input class="kb-input" data-op="kb.url" placeholder="粘贴网页地址，如经开区官网政策页面" value="${esc(I.url)}"></div>
            <div class="meta" style="margin-top:8px">原型内置了经开区官网部分页面的快照（2026-11-18）；正式版由后端实时抓取正文。</div>
            ${C.sampleUrl ? `<button class="chip-btn" data-op="kb.url-sample" style="margin-top:10px">${icon('globe')} 试试：数据券申报延期通知（官网）</button>` : ''}`;
          const ui1 = box.querySelector('[data-op="kb.url"]'); ui1.oninput = () => { I.url = ui1.value; upd(); }; ui1.onkeydown = (e) => { if (e.key === 'Enter' && I.url.trim()) goBtn.click(); };
          const us = box.querySelector('[data-op="kb.url-sample"]'); if (us) us.onclick = () => { I.url = C.sampleUrl; ui1.value = I.url; upd(); };
        }
        upd();
        goBtn.onclick = () => startParse();
      }
      async function startParse() {
        const I = S.imp; I.step = 1; I.items = []; I.busy = true; I.err = null;
        const pend = I.src === 'file' ? I.files.map((f) => ({ key: 'p' + Math.random().toString(36).slice(2, 7), name: f.name, stages: { parse: 'run', chunk: 'wait', tag: 'wait' }, file: f })) : I.src === 'text' ? [{ key: 'pt', name: I.title || '粘贴的文字', stages: { parse: 'run', chunk: 'wait', tag: 'wait' } }] : [{ key: 'pu', name: I.url, stages: { parse: 'run', chunk: 'wait', tag: 'wait' } }];
        I.items = pend; renderImport();
        try {
          let parsed;
          if (I.src === 'url') { const r = await K().fetchUrl(I.url.trim()); parsed = [r.item]; }
          else {
            const raw = I.src === 'file' ? await Promise.all(I.files.map((f) => window.JKKBFiles.read(f))) : [{ name: I.title || '粘贴的文字', text: I.text, parse: 'real', from: '粘贴', meta: I.title ? { title: I.title } : undefined }];
            const ok = raw.map((x, i) => Object.assign({ key: pend[i].key }, x));
            const r = await K().preview(ok.filter((x) => x.text)); const map = {}; r.items.forEach((x) => (map[x.key] = x));
            parsed = ok.map((x) => map[x.key] || { key: x.key, name: x.name, ok: false, error: x.error || '读取失败', stages: { parse: 'fail', chunk: 'wait', tag: 'wait' } });
          }
          // 逐份播放 解析→切片→标签（让人看到每一步）
          for (let i = 0; i < parsed.length; i++) {
            const p = parsed[i]; const slot = I.items[i] || (I.items[i] = { key: p.key, name: p.name, stages: {} });
            if (!p.ok) { Object.assign(slot, p); renderReviewRows(); continue; }
            slot.stages = { parse: 'done', chunk: 'run', tag: 'wait' }; renderReviewRows(); await sleep(260);
            slot.stages = { parse: 'done', chunk: 'done', tag: 'run' }; renderReviewRows(); await sleep(260);
            Object.assign(slot, p, { decision: p.dup && p.dup.type === 'version' ? 'version' : p.dup && p.dup.type === 'duplicate' ? 'skip' : 'new' }); slot.stages = { parse: 'done', chunk: 'done', tag: 'done' }; renderReviewRows();
          }
        } catch (e) { I.err = e.message || '解析失败'; }
        I.busy = false; renderImport();
      }
      const STG = [['parse', '解析'], ['chunk', '切片'], ['tag', '标签']];
      function stageHtml(st) { return `<div class="kb-stg">${STG.map(([k, l]) => `<span class="kb-st ${st[k] || 'wait'}"><i></i>${l}</span>`).join('<span class="kb-st-l"></span>')}</div>`; }
      function impReview(w) {
        const I = S.imp;
        const okN = I.items.filter((x) => x.ok && x.decision !== 'skip').length;
        w.innerHTML = `<div class="q">${I.busy ? '正在解析…' : '看一眼，没问题就入库'}</div><div class="q-sub">${I.busy ? '每份资料依次：读正文 → 按段落切片 → 自动打标签 → 查重' : '标题、空间、标签都可以改；重复的会跳过，同名的可作为新版本'}</div>
          ${I.err ? `<div class="callout h-red">${icon('alert')}<div>${esc(I.err)}</div></div>` : ''}
          <div class="col gap3" id="kb-rv"></div>
          <div class="wiz-foot"><button class="btn ghost" data-op="kb.ibk">上一步</button><span class="sp"></span><span class="meta">${I.busy ? '' : `将入库 ${okN} 份`}</span><button class="btn primary" data-op="kb.commit" ${I.busy || !okN ? 'disabled' : ''}>确认入库</button></div>`;
        w.querySelector('[data-op="kb.ibk"]').onclick = () => { I.step = 0; renderImport(); };
        w.querySelector('[data-op="kb.commit"]').onclick = () => doCommit();
        renderReviewRows();
      }
      function renderReviewRows() {
        const box = body.querySelector('#kb-rv'); if (!box) return; const I = S.imp;
        const spOpts = (cur) => S.spaces.map((s) => `<option value="${s.id}" ${cur === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('');
        box.innerHTML = I.items.map((it, i) => {
          const done = it.stages && it.stages.tag === 'done' && it.ok;
          const head = `<div class="row"><span class="kb-fico">${icon(it.from === '网址' ? 'globe' : 'file')}</span><div class="grow clip"><b>${esc(it.name)}</b></div>${it.parse === 'simulated' ? tag('模拟解析', 'kbStatus') : ''}${stageHtml(it.stages || {})}</div>`;
          if (it.ok === false) return `<div class="card tight kb-ir">${head}<div class="callout h-red" style="margin-top:10px">${icon('alert')}<div>${esc(it.error)}</div></div></div>`;
          if (!done) return `<div class="card tight kb-ir">${head}<div class="skel" style="margin-top:12px;width:60%"></div></div>`;
          const m = it.meta; const dup = it.dup || {};
          const dupHtml = dup.type === 'duplicate' ? `<div class="callout h-gray kb-dup">${icon('copy')}<div class="grow">库里已有同样内容：《${esc(dup.title.slice(0, 28))}》</div><div class="seg"><button class="${it.decision === 'skip' ? 'on' : ''}" data-dec="${i}:skip">跳过</button><button class="${it.decision === 'new' ? 'on' : ''}" data-dec="${i}:new">仍然导入</button></div></div>`
            : dup.type === 'version' ? `<div class="callout h-blue kb-dup">${icon('history')}<div class="grow">像是《${esc(dup.title.slice(0, 26))}》的新版本（相似 ${dup.sim}%）</div><div class="seg"><button class="${it.decision === 'version' ? 'on' : ''}" data-dec="${i}:version" data-op="kb.asver">作为新版本</button><button class="${it.decision === 'new' ? 'on' : ''}" data-dec="${i}:new">另存为新资料</button></div></div>` : '';
          return `<div class="card tight kb-ir ${it.decision === 'skip' ? 'kb-skip' : ''}" data-op="kb.item-${i}">${head}
            <div class="kb-ig">
              <div class="field"><label>标题</label><input class="input sm" data-t="${i}" value="${esc(m.title)}"></div>
              <div class="field"><label>放进</label><select class="select sm" data-s="${i}">${spOpts(m.space)}</select></div>
            </div>
            <div class="row wrap kb-itags" data-tg="${i}">${(it.tags || []).map((t, k) => `<span class="kb-tchip">${esc(t)}<button data-tx="${i}:${k}" title="移除">×</button></span>`).join('')}<button class="kb-tadd" data-ta="${i}">+ 标签</button></div>
            <div class="meta kb-imeta">${it.chunks} 个片段 · ${it.chars} 字${m.docNo ? ' · ' + esc(m.docNo) : ''}${m.date ? ' · ' + esc(m.date) : ''}${it.real || it.url ? ' · 来自官网' : ''} · <a href="javascript:void 0" data-pv="${i}">预览片段</a></div>
            <div class="kb-pv hide" id="kb-pv-${i}">${(it.chunkPreview || []).map((c, k) => `<div class="kb-pvc"><span class="kb-ckn num">${k + 1}</span><div class="grow">${c.head ? `<b>${esc(c.head)}</b> ` : ''}${esc(c.text)}…</div></div>`).join('')}</div>
            ${dupHtml}</div>`;
        }).join('');
        box.querySelectorAll('[data-t]').forEach((x) => (x.oninput = () => { I.items[+x.dataset.t].meta.title = x.value; }));
        box.querySelectorAll('[data-s]').forEach((x) => (x.onchange = () => { I.items[+x.dataset.s].meta.space = x.value; }));
        box.querySelectorAll('[data-tx]').forEach((b) => (b.onclick = () => { const [i, k] = b.dataset.tx.split(':').map(Number); I.items[i].tags.splice(k, 1); renderReviewRows(); }));
        box.querySelectorAll('[data-ta]').forEach((b) => (b.onclick = () => { const i = +b.dataset.ta; const inp = document.createElement('input'); inp.className = 'input sm kb-tin'; inp.placeholder = '回车添加'; b.replaceWith(inp); inp.focus(); const fin = () => { const v = inp.value.trim(); if (v && !I.items[i].tags.includes(v)) I.items[i].tags.push(v); renderReviewRows(); }; inp.onkeydown = (e) => { if (e.key === 'Enter') fin(); if (e.key === 'Escape') renderReviewRows(); }; inp.onblur = fin; }));
        box.querySelectorAll('[data-pv]').forEach((a) => (a.onclick = () => body.querySelector('#kb-pv-' + a.dataset.pv).classList.toggle('hide')));
        box.querySelectorAll('[data-dec]').forEach((b) => (b.onclick = () => { const [i, d] = b.dataset.dec.split(':'); I.items[+i].decision = d; renderImport(); }));
      }
      async function doCommit() {
        const I = S.imp; const items = I.items.filter((x) => x.ok).map((x) => Object.assign({}, x, { skip: x.decision === 'skip', decision: x.decision }));
        const btn = body.querySelector('[data-op="kb.commit"]'); if (btn) { btn.disabled = true; btn.textContent = '入库中…'; }
        try { I.result = await K().commit(items, items[0] && items[0].from); } catch (e) { ui.toast(e.message || '入库失败', { type: 'err' }); if (btn) { btn.disabled = false; btn.textContent = '确认入库'; } return; }
        ctx.audit && ctx.audit('kb.import', `导入 ${I.result.docs.length} 份`);
        ctx.bus && ctx.bus.emit('kb:changed', { added: I.result.docs.length });
        await loadMeta(); I.step = 2; renderImport();
      }
      function impDone(w) {
        const r = S.imp.result || { docs: [], chunks: 0 }; const ver = r.docs.filter((d) => d.version > 1).length;
        w.innerHTML = `<div class="kb-done"><div class="kb-done-ico">${icon('check')}</div><div class="big">已入库 ${r.docs.length} 份</div><div class="meta" style="margin-top:6px">切成 ${r.chunks} 个片段，已可以搜索和提问${ver ? ` · 其中 ${ver} 份作为新版本，旧版已标“已更新”` : ''}</div></div>
          <div class="list lined card flat kb-list" style="margin-top:20px">${r.docs.map((h) => `<div class="li kb-hit" data-doc="${esc(h.id)}" data-op="kb.new-${esc(h.id)}"><span class="kb-sico">${icon(SPACE_ICON[h.space] || 'file')}</span><div class="grow"><div class="ttl clip">${esc(h.title)}</div><div class="meta">${esc(h.spaceName)} · ${h.chunks} 个片段</div></div>${h.version > 1 ? tag('新版本', 'kbStatus') : tag('已入库', 'kbStatus')}</div>`).join('')}</div>
          <div class="wiz-foot"><button class="btn ghost" data-op="kb.again">继续导入</button><span class="sp"></span><button class="btn primary" data-op="kb.tryask">${icon('sparkles')}问一个问题试试</button></div>`;
        bindHits(w);
        w.querySelector('[data-op="kb.again"]').onclick = () => { S.imp = { step: 0, src: S.imp.src, files: [], text: '', title: '', url: '', items: [], busy: false, result: null }; renderImport(); };
        w.querySelector('[data-op="kb.tryask"]').onclick = () => { const d = r.docs[0]; S.imp = { step: 0, src: S.imp.src, files: [], text: '', title: '', url: '', items: [], busy: false, result: null }; go('home', { q: d ? d.title.replace(/^.*?关于/, '').slice(0, 14) : '' }); };
      }

      /* ===================== 渲染入口 ===================== */
      function render() {
        renderTabs(); const ib = el.querySelector('[data-op="kb.import-open"]'); if (ib) ib.classList.toggle('hide', S.tab === 'import');
        if (S.tab === 'home') renderHome(); else if (S.tab === 'library') renderLib(); else if (S.tab === 'import') renderImport(); else renderDoc();
      }
      const offs = [];
      if (ctx.bus) { ctx.bus.on('kb:changed', async () => { await loadMeta(); if (S.tab === 'home') renderHome(); else if (S.tab === 'library') await loadLib(); }); ctx.bus.on('data:reset', async () => { await loadMeta(); render(); }); }

      /* ===================== 操作员动作（AI 替你操作） ===================== */
      const textOf = (s) => (typeof s === 'string' ? s : (s && (s.text || s.q)) || '');
      async function typeAndAsk(q, run) {
        go('home'); await sleep(60);
        if (run) { await run.step(1); await run.fill('[data-op="kb.q"]', q); } else { S.q = q; body.querySelector('[data-op="kb.q"]').value = q; }
        S.q = q; runSearch();
        if (run) await run.click('[data-op="kb.ask"]'); else runAsk();
        if (run && !S.asking && !S.answer) runAsk();
        if (run) { await run.step(2); await run.wait(() => S.answer && !S.asking, 8000); await run.step(3); await run.highlight('[data-op="kb.answer"]'); }
        else { for (let i = 0; i < 80 && (!S.answer || S.asking); i++) await sleep(100); }
        return S.answer;
      }
      const handle = {
        nav: ctx.nav,
        followScope,
        async chatAsk(q) {
          go('home'); S.q = q; body.querySelector('[data-op="kb.q"]').value = q;
          runSearch();
          const answer = await runAsk();
          if (!answer || answer.error) throw Error(answer?.error || '提问范围已改变，请重新提问。');
          return answer;
        },
        go,
        actions: {
          async ask(slots, run) {
            const firstPara = (t) => String(t || '').split(/\n\s*\n/)[0].slice(0, 220);
            let q = textOf(slots).replace(/^(在|去)?知识库(里|中)?(查一下|查查|问一下|搜一下)?[，,：:\s]*/, '').trim() || textOf(slots);
            const a = await typeAndAsk(q, run);
            if (!run) return a;
            if (!a || a.error) return run.fail((a && a.error) || '没有拿到回答');
            if (a.notFound) return run.done('知识库里没有找到能回答这个问题的原文，我没有编答案。可以导入相关资料后再问。', [{ label: '导入资料', say: '打开知识库导入' }]);
            const c = a.citations[0]; await run.step(4);
            if (c) await run.highlight('[data-cite-row="1"]', '点出处可直达原文高亮段落');
            run.done(firstPara(a.answer) || `找到 ${a.citations.length} 处原文依据：${(c && c.snippet || '').slice(0, 60)}…`, [{ label: '看原文', say: `打开${(c && c.title || '').slice(0, 16)}原文` }, { label: '写进公文', say: `根据《${(c && c.title || '').slice(0, 18)}》起草一份告知企业的通知` }], { cites: window.JKShell && JKShell.citesOf ? JKShell.citesOf(a) : [] });
          },
          async search(slots, run) {
            const q = textOf(slots).replace(/^.*?(搜一下|找一下|搜索|查找|找找)/, '').replace(/^(关于)?|(的)?(文件|资料|政策)$/g, '').trim() || textOf(slots);
            go('home'); await sleep(40);
            if (run) { await run.step(1); await run.fill('[data-op="kb.q"]', q); } S.q = q; await runSearch();
            if (run) { await run.step(2); await run.wait(() => S.hits, 4000); if (S.hits && S.hits.length) await run.highlight('.kb-list'); run.done(S.hits && S.hits.length ? `找到 ${S.total} 份相关资料，最相关的是《${S.hits[0].title.slice(0, 24)}》` : '没有找到相关资料'); }
            return { hits: S.hits };
          },
          async open(slots, run) {
            const q = textOf(slots).replace(/打开|看一下|看看|的?原文|知识库里?/g, '').trim();
            const r = await K().search({ q, limit: 1 }); const h = r.hits[0];
            if (!h) return run ? run.done('知识库里没有找到这份文件') : null;
            if (run) await run.step(1); go('doc', { id: h.id, chunk: h.chunk });
            if (run) { await run.wait(() => S.doc && S.doc.id === h.id, 4000); await run.step(2); await run.highlight('.kb-title'); run.done(`已打开《${h.title.slice(0, 30)}》`); }
            return h;
          },
          async expiring(slots, run) {
            const st = /失效/.test(textOf(slots)) ? '已失效' : '即将到期';
            go('library', { status: st }); if (run) { await run.step(1); await run.wait(() => S.lib.list, 4000); await run.step(2); await run.highlight(`[data-op="kb.st-${st}"]`); run.done(`${st}的文件共 ${S.lib.list.length} 份${S.lib.list[0] ? '，如《' + S.lib.list[0].title.slice(0, 20) + '》' : ''}`); }
          },
          async import(slots, run) {
            const t = textOf(slots); const url = (t.match(/https?:\/\/[^\s，。]+/) || [])[0]; const file = slots && slots.file;
            if (file) return handle.actions.intake({ file }, run);
            S.imp = { step: 0, src: url ? 'url' : 'file', files: [], text: '', title: '', url: '', items: [], busy: false, result: null }; go('import');
            if (!url) { if (run) { await run.step(1); await run.highlight('[data-op="kb.drop"]', '把文件拖到这里'); run.done('导入页已打开：把文件拖进来，或切到“粘贴文字 / 网址”'); } return; }
            if (run) { await run.step(1); await run.fill('[data-op="kb.url"]', url); } else { S.imp.url = url; }
            S.imp.url = url; if (run) await run.click('[data-op="kb.parse"]'); else startParse();
            return finishImport(run);
          },
          async intake({ file }, run) {
            S.imp = { step: 0, src: 'file', files: [], text: '', title: '', url: '', items: [], busy: false, result: null }; go('import');
            const raw = window.JKKBFiles.fromChat(file);
            S.imp.step = 1; S.imp.busy = true; S.imp.items = [{ key: 'chat', name: raw.name, stages: { parse: 'run', chunk: 'wait', tag: 'wait' } }]; renderImport();
            if (run) await run.step(1);
            const r = await K().preview([Object.assign({ key: 'chat' }, raw)]); const p = r.items[0]; const slot = S.imp.items[0];
            slot.stages = { parse: 'done', chunk: 'run', tag: 'wait' }; renderReviewRows(); await sleep(260); slot.stages = { parse: 'done', chunk: 'done', tag: 'run' }; renderReviewRows(); await sleep(260);
            Object.assign(slot, p, { decision: p.dup && p.dup.type === 'version' ? 'version' : p.dup && p.dup.type === 'duplicate' ? 'skip' : 'new' }); S.imp.busy = false; renderImport();
            return finishImport(run, true);
          },
        },
        unmount() { clearTimeout(timer); ++askSeq; ++seq; reference = null; if (current === handle) current = null; },
      };
      async function finishImport(run, already) {
        if (run && !already) { await run.step(2); await run.wait(() => S.imp.step === 1 && !S.imp.busy, 8000); }
        if (!run) return S.imp.items;
        await run.step(2); const it = S.imp.items[0];
        if (!it || it.ok === false) return run.done((it && it.error) || '没有读到内容', [{ label: '改用粘贴文字', say: '打开知识库导入' }]);
        await run.highlight('[data-op="kb.item-0"]', `${it.chunks} 个片段 · 标签：${(it.tags || []).join('、')}`);
        if (it.decision === 'skip') return run.done(`库里已经有这份资料了（《${it.dup.title.slice(0, 24)}》），没有重复导入。`);
        await run.step(3);
        const c = await run.ask(it.decision === 'version' ? `这是《${it.dup.title.slice(0, 18)}》的新版本，作为新版本入库吗？` : `解析完成：${it.chunks} 个片段，放进「${(S.spaces.find((s) => s.id === it.meta.space) || {}).name}」。确认入库吗？`, ['确认入库', '先不入库']);
        if (c !== '确认入库') return run.done('好的，先不入库。解析结果还在导入页，随时可以改了再入库。');
        await run.click('[data-op="kb.commit"]'); await run.wait(() => S.imp.step === 2, 6000);
        const d = (S.imp.result && S.imp.result.docs[0]) || {};
        run.done(`已入库：《${(d.title || '').slice(0, 30)}》，${S.imp.result ? S.imp.result.chunks : 0} 个片段，现在就能搜和问。`, [{ label: '问一个问题', say: /数据券/.test(d.title || '') ? '数据券申报延期到什么时候？' : `${(d.title || '').slice(0, 12)}的主要内容` }]);
      }

      current = handle;
      (async () => { await loadMeta(); render(); const p = ctx.params || {}; if (pendingOpen) { const po = pendingOpen; pendingOpen = null; go('doc', po); } else if (p.id) go('doc', p); else if (p.file) handle.actions.intake({ file: p.file }); else if (p.q) go('home', { q: p.q, ask: true }); else if (p.route) go(p.route, p); })();
      render();
      return handle;
    },
  });
})();

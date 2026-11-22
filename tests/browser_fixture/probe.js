// 可选 #probe：所有列表、文稿、搜索、决定默认仍走已加载的产品适配器。
(function () {
  if (!window.T38?.ready || location.hash !== '#probe') return;
  const rows = [], counts = new Map();
  let logEl, holdNext = false, release, showVersion = false, cancelProbe = false;
  const note = s => {
    rows.push(s); if (rows.length > 48) rows.shift();
    if (logEl) logEl.textContent = [...counts].map(([k,n])=>n+' 次 '+k).join('\n')+'\n——最近事件——\n'+rows.join('\n');
  };
  const request = JKAPI.request.bind(JKAPI);
  let seq = 0;
  JKAPI.request = (method, path, ...rest) => {
    // 只记方法和路由，不记问题、表单、身份材料或回复。
    const route = path.split('?')[0];
    if (/^\/api\/(apps\/(meeting|document)\/|v1\/kb\/(ask|search)$)/.test(route)) {
      const key=method+' '+route; counts.set(key,(counts.get(key)||0)+1);
    }
    const id = ++seq, t = performance.now();
    note('#' + id + ' 开始 ' + method + ' ' + route);
    return request(method, path, ...rest).then(result => {
      note('#' + id + ' 返回 ' + route + ' ' + Math.round(performance.now()-t) + 'ms');
      return result;
    }, error => { note('#' + id + ' 拒绝 ' + route + ' ' + (error.status || '未知状态')); throw error; });
  };
  const reviews = JKApi.reviews, list = reviews.list.bind(reviews), decide = reviews.decide.bind(reviews);
  reviews.list = async (...args) => {
    const hold = holdNext; holdNext = false;
    const data = await list(...args); // 真正的离线读取；仅控制返回时机
    let result = data;
    if (showVersion) {
      result = {...data, items:await Promise.all(data.items.map(async r => {
        if (r.app !== 'document' || r.status !== 'pending') return r;
        const d = (await JKApi.document.get(r.ref)).item;
        const version = d.versions.at(-1).v;
        return {...r, version, title:r.title + '【协议探针：v' + version + '】'};
      }))};
    }
    if (hold) {
      note('已截住旧列表：可再次打开收件箱并办理，再放行旧读。');
      await new Promise(resolve => { release = resolve; });
    }
    return result;
  };
  reviews.decide = (id, b) => {
    note('决定 ' + id + ' / ' + b.decision + ' / 画面请求版本=' + (b.version ?? '未提供'));
    if (showVersion) return Promise.reject({status:409, code:'FIXTURE_ONLY', message:'协议观察结束，未执行审批'});
    return decide(id, b);
  };
  document.addEventListener('DOMContentLoaded', () => {
    const box = document.createElement('details');
    box.style.cssText = 'position:fixed;bottom:0;left:50%;transform:translateX(-50%);z-index:9999;background:#fff;color:#18232b;padding:.2rem .5rem;max-width:92vw;font:13px system-ui;max-height:38vh;overflow:auto';
    box.innerHTML = '<summary>隔离探针 · 非产品控件</summary><div></div><pre aria-live="off" style="max-height:16vh;overflow:auto"></pre>';
    const button = (label,fn) => {
      const b = document.createElement('button'); b.type='button'; b.textContent=label;
      b.addEventListener('click',fn); box.querySelector('div').append(b);
    };
    button('清观察记录', () => { rows.length=0; counts.clear(); note('新观察段'); });
    button('截住下一次待审读', () => {
      if (!holdNext && !release) { holdNext=true; note('已布置：点击产品收件箱'); }
    });
    button('放行旧读', () => {
      if (release) { const go = release; release=null; go(); note('旧读已放行'); } else note('没有已截住的读');
    });
    button('仅测画面版本（刷新页面才退出）', () => {
      showVersion=true; note('协议模式：重新打开收件箱，行标题附当前稿版本；决定只观察，不写状态。');
    });
    const identityProbe = async role => {
      if (cancelProbe || JKShell.S.role?.id !== role || JKDemo.state.on || document.querySelector('[role=dialog]')) {
        return note('请用' + (role === 'partner' ? '合作方何军' : '内部成员王敏') + '，在无弹窗且未播放时操作');
      }
      // 合成开场只请求切到李阳，不含任何业务步骤。王敏是正式开场的默认身份，
      // 不更换开场目标就不会弹切号框。仍由产品 start 创建并持有真实的 owner signal。
      const before = JKShell.S.me, old = JK_CONFIG.api.mode, script = window.JK_DEMO_SCRIPT;
      const blocked = T38.blocked;
      cancelProbe=true; JK_CONFIG.api.mode='http';
      window.JK_DEMO_SCRIPT = [{ title:'T38 合成切号开场', steps:[{ login:'liyang' }] }];
      try {
        const started = JKDemo.start(0);
        const prompt = !!document.querySelector('[data-op="switch.password"]');
        await started;
        note((role === 'partner' ? '合作方拒绝检查' : '内部成员取消检查') + '：口令弹窗=' + prompt);
      }
      finally {
        window.JK_DEMO_SCRIPT=script; JK_CONFIG.api.mode=old; cancelProbe=false;
        note('已恢复离线模式；同一身份=' + (before === JKShell.S.me) + '；播放中=' + JKDemo.state.on + '；本次拦截外联=' + (T38.blocked - blocked));
      }
    };
    button('合作方禁止启动（HTTP 协议探针）', () => identityProbe('partner'));
    button('内部成员演示切号取消（HTTP 协议探针）', () => identityProbe('member'));
    logEl=box.querySelector('pre'); document.body.append(box);
    note('T38 进程内观察；收起不会改变页面数据。');
  });
})();

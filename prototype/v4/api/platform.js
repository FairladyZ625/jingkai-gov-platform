/* =====================================================================
 * 接口适配层 · 平台接口（接口规范 §3）。外壳只调这里，不碰模拟数据。
 * 每个函数注明 入参 → 出参（与《接口规范》实体同名）。
 * ===================================================================== */
(function () {
  const H = window.JKHttp;
  window.JKApi = window.JKApi || {};
  Object.assign(window.JKApi, {
    auth: {
      /** {username,password} → {user:User} */ login: (b) => H.post('/api/v1/auth/login', b),
      /** → {ok} */ logout: () => H.post('/api/v1/auth/logout', {}),
      /** → {user:User|null} */ session: () => H.get('/api/v1/auth/session'),
    },
    me: {
      /** → {user, role:Role, org, settings, grants:{appId:actions[]}} */ get: () => H.get('/api/v1/me'),
      /** {old,new} → {ok} */ password: (b) => H.put('/api/v1/me/password', b),
      /** prefs → {prefs} */ prefs: (b) => H.patch('/api/v1/me/prefs', b),
    },
    models: {
      /** → {items:Model[], current, capabilities} */ list: () => H.get('/api/v1/models'),
      /** {model} → {current}（接口规范 v1.2） */ setCurrent: (id) => H.put('/api/v1/models/current', { model: id }),
      /** 管理员 {enabled} → {item} */ patch: (id, b) => H.patch('/api/v1/models/' + id, b),
    },
    chat: {
      /** → {items:Conversation[]} */ list: () => H.get('/api/v1/conversations'),
      /** {title,app} → {item} */ create: (b) => H.post('/api/v1/conversations', b),
      /** → {ok} */ remove: (id) => H.del('/api/v1/conversations/' + id),
      /** {text,model,app,files} → {conversation,user,reply:Message} 模型回复（模拟） */ send: (id, b) => H.post(`/api/v1/conversations/${id}/messages`, b),
    },
    apps: { /** → {items:App[], skills} */ list: () => H.get('/api/v1/apps') },
    reviews: {
      /** → {items:Review[]} */ list: () => H.get('/api/v1/reviews'),
      /** {decision:'approve'|'reject', comment} → {item} */ decide: (id, b) => H.post(`/api/v1/reviews/${id}/decisions`, b),
    },
    todos: { list: () => H.get('/api/v1/todos'), patch: (id, b) => H.patch('/api/v1/todos/' + id, b) },
    feed: { list: () => H.get('/api/v1/feed') },
    audit: { /** → {items:AuditEntry[]} */ list: () => H.get('/api/v1/audit') },
    kb: { /* 知识库适配：知识库模块的 api/kb.js 会扩展/覆盖这里 */
      search: (b) => H.post('/api/v1/kb/search', b), ask: (b) => H.post('/api/v1/kb/ask', b),
      libraries: () => H.get('/api/v1/kb/libraries'), file: (id) => H.get('/api/v1/kb/files/' + encodeURIComponent(id)),
      import: (b) => H.post('/api/v1/kb/import', b),
    },
    admin: {
      users: () => H.get('/api/v1/admin/users'), createUser: (b) => H.post('/api/v1/admin/users', b), patchUser: (id, b) => H.patch('/api/v1/admin/users/' + id, b),
      addDept: (b) => H.post('/api/v1/admin/departments', b), patchDept: (id, b) => H.patch('/api/v1/admin/departments/' + id, b), delDept: (id) => H.del('/api/v1/admin/departments/' + id),
      grants: () => H.get('/api/v1/admin/grants'), setGrant: (role, app, actions) => H.put(`/api/v1/admin/grants/${role}/${encodeURIComponent(app)}`, { actions }),
      patchRole: (id, b) => H.patch('/api/v1/admin/roles/' + id, b), patchApp: (id, b) => H.patch('/api/v1/admin/apps/' + id, b),
      settings: () => H.get('/api/v1/admin/settings'), saveSettings: (b) => H.put('/api/v1/admin/settings', b),
      usage: () => H.get('/api/v1/admin/usage'),
    },
    skills: { list: () => H.get('/api/v1/skills') },
    /** 演示环境：重置模拟数据（http 模式下调用服务端演示重置接口） */
    demo: { reset: () => H.mode() === 'mock' ? Promise.resolve(window.JKAPI.reset()) : H.post('/api/v1/demo/reset', {}) },
  });
})();

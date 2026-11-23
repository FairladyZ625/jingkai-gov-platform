/* 账号与权限（模拟后端 + 前端判定）
 * 对应 haiknow：auth.py（会话登录）、identity*.py（用户/部门）、rbac.py（角色×应用×动作）、admin_identity.py（管理接口）
 * 数据来源：data/accounts.js；运行中修改保存在本机，点“重置演示数据”恢复。 */
(function () {
  const A = window.JKAPI; const X = A.ext; const SEED = window.JK_DATA;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const APPS = ['policy', 'enterprise', 'meeting', 'document', 'kb', 'skills', 'computer'];
  const APP_NAMES = { '*': '全部应用', policy: '政策兑现咨询', enterprise: '企业管理维护', meeting: '会议记录', document: '公文协作', kb: '知识库', skills: '技能中心', computer: '电脑操作' };

  function deptPath(S, id) {
    const out = []; let d = (S.departments || []).find((x) => x.id === id);
    while (d) { if (d.parent) out.unshift(d.name); d = S.departments.find((x) => x.id === d.parent); }
    return out.join(' · ') || '—';
  }
  // 状态初始化（首次 / 重置时）：补齐账号相关字段
  A.onLoad((S) => {
    ['departments', 'roles', 'grants', 'grantActions', 'settings', 'quickLogin'].forEach((k) => { if (!S[k]) S[k] = clone(SEED[k]); });
    if (!S.users[0].username) S.users = clone(SEED.users);
    if (S.session === undefined) S.session = null;
    S.prefs = S.prefs || {};
    S.users.forEach((u) => { u.dept = deptPath(S, u.deptId); });
  });

  const S = () => X.state();
  const me = () => X.me();
  const pub = (u) => { const { password, ...rest } = u; return rest; };
  const validPassword = (value) => typeof value === 'string' && value.length >= 6 && value.length <= 1024;
  const needAdmin = () => { if (!X.can('*', 'admin')) X.err(403, 'FORBIDDEN', '需要管理员权限'); };
  const log = (action) => X.audit('账号与权限', action);

  /* ---------- 会话 ---------- */
  X.first('POST', '/api/v1/auth/login', (b) => {
    const u = S().users.find((x) => x.username === (b.username || '').trim());
    if (!u?.password || u.password !== b.password) X.err(401, 'BAD_CREDENTIALS', '账号或密码不正确');
    if (u.status !== 'active') X.err(403, 'ACCOUNT_DISABLED', '该账号已停用，请联系管理员');
    S().session = { userId: u.id, at: X.now() }; S().me = u.id; u.lastLogin = X.now();
    log('登录'); return { user: pub(u) };
  });
  X.first('POST', '/api/v1/auth/logout', () => { if (S().session) log('退出登录'); S().session = null; return { ok: true }; });
  X.first('GET', '/api/v1/auth/session', () => ({ user: S().session ? pub(me()) : null }));
  X.first('GET', '/api/v1/me', () => { const u = me(); return { user: pub(u), role: X.roleOf(u), org: S().org, settings: S().settings, grants: effective(u) }; });
  X.first('PUT', '/api/v1/me/password', (b) => { const u = me(); if (u.password !== b.old) X.err(400, 'BAD_PASSWORD', '原密码不正确'); if ((b.new || '').length < 6) X.err(400, 'WEAK_PASSWORD', '新密码至少 6 位'); u.password = b.new; log('修改密码'); return { ok: true }; });
  X.first('PATCH', '/api/v1/me/prefs', (b) => { S().prefs[me().id] = Object.assign(S().prefs[me().id] || {}, b); return { prefs: S().prefs[me().id] }; });
  function effective(u) { const out = {}; ['*', ...APPS].forEach((a) => { out[a] = ['view', 'operate', 'approve', 'admin'].filter((x) => X.can(a, x, u)); }); return out; }

  /* ---------- 管理：用户 ---------- */
  X.first('GET', '/api/v1/admin/users', () => { needAdmin(); return { items: S().users.map(pub), roles: S().roles, departments: S().departments }; });
  X.first('POST', '/api/v1/admin/users', (b) => {
    needAdmin(); if (!b.username || !b.name) X.err(400, 'INVALID', '请填写账号和姓名');
    if (S().users.some((u) => u.username === b.username)) X.err(409, 'DUPLICATE', '账号已存在');
    if (b.password !== undefined && !validPassword(b.password)) X.err(400, 'INVALID_REQUEST', '登录口令长度须为 6 至 1024 位');
    if (b.password && S().users.filter((u) => u.status === 'active').length >= S().org.seats) X.err(409, 'SEATS_FULL', `席位已满（${S().org.seats} 个）`);
    const u = { id: 'u-' + b.username, username: b.username, password: b.password || null, name: b.name, deptId: b.deptId || 'd-qyfw', title: b.title || '经办', role: b.role || 'member', status: b.password ? 'active' : 'disabled', lastLogin: '—' };
    u.dept = deptPath(S(), u.deptId); S().users.push(u); S().org.used = S().users.filter((x) => x.status === 'active').length;
    log(`新增账号 · ${u.name}（${X.roleOf(u).name}）`); return { item: pub(u) };
  });
  X.first('PATCH', '/api/v1/admin/users/:id', (b, p) => {
    needAdmin(); const u = S().users.find((x) => x.id === p.id); if (!u) X.err(404, 'NOT_FOUND', '用户不存在');
    if (u.id === me().id && (b.status === 'disabled' || (b.role && b.role !== 'admin'))) X.err(400, 'SELF_LOCK', '不能停用自己或取消自己的管理员角色');
    const rotate = validPassword(b.resetPassword);
    if (b.resetPassword !== undefined && b.resetPassword !== false && !rotate) X.err(400, 'INVALID_REQUEST', '请提供新口令');
    if (b.status === 'active' && !u.password && !rotate) X.err(400, 'INVALID_REQUEST', '启用账号前须设置登录口令');
    const changes = [];
    ['name', 'title', 'deptId', 'role', 'status'].forEach((k) => { if (b[k] !== undefined && b[k] !== u[k]) { changes.push(k === 'role' ? `角色→${(S().roles.find((r) => r.id === b.role) || {}).name}` : k === 'status' ? (b.status === 'active' ? '启用' : '停用') : k === 'deptId' ? '调整部门' : '修改' + k); u[k] = b[k]; } });
    if (rotate) { u.password = b.resetPassword; changes.push('重置密码'); }
    u.dept = deptPath(S(), u.deptId); S().org.used = S().users.filter((x) => x.status === 'active').length;
    if (u.status !== 'active' && S().session && S().session.userId === u.id) S().session = null;
    log(`${u.name}：${changes.join('、') || '无变化'}`); return { item: pub(u) };
  });
  /* ---------- 管理：组织 ---------- */
  X.first('POST', '/api/v1/admin/departments', (b) => { needAdmin(); if (!b.name) X.err(400, 'INVALID', '请填写部门名称'); const d = { id: X.nid('d'), name: b.name, parent: b.parent || 'd-root' }; S().departments.push(d); log('新增部门 · ' + d.name); return { item: d }; });
  X.first('PATCH', '/api/v1/admin/departments/:id', (b, p) => { needAdmin(); const d = S().departments.find((x) => x.id === p.id); d.name = b.name || d.name; S().users.forEach((u) => { u.dept = deptPath(S(), u.deptId); }); log('重命名部门 · ' + d.name); return { item: d }; });
  X.first('DELETE', '/api/v1/admin/departments/:id', (b, p) => {
    needAdmin(); const d = S().departments.find((x) => x.id === p.id);
    if (S().departments.some((x) => x.parent === d.id) || S().users.some((u) => u.deptId === d.id)) X.err(409, 'NOT_EMPTY', `「${d.name}」下还有成员或子部门，不能删除`);
    S().departments = S().departments.filter((x) => x.id !== d.id); log('删除部门 · ' + d.name); return { ok: true };
  });
  /* ---------- 管理：角色与授权 ---------- */
  X.first('GET', '/api/v1/admin/grants', () => { needAdmin(); return { roles: S().roles, apps: ['*', ...APPS].map((id) => ({ id, name: APP_NAMES[id] })), grants: S().grants, actions: S().grantActions }; });
  X.first('PUT', '/api/v1/admin/grants/:role/:app', (b, p) => {
    needAdmin(); if (p.role === 'admin' && p.app === '*' && !(b.actions || []).includes('admin')) X.err(400, 'SELF_LOCK', '不能去掉管理员的“管理”动作，否则没人能再进管理后台');
    const g = S().grants[p.role] = S().grants[p.role] || {}; g[p.app] = b.actions || []; if (!g[p.app].length) delete g[p.app];
    log(`授权 · ${(S().roles.find((r) => r.id === p.role) || {}).name} × ${APP_NAMES[p.app] || p.app} = ${(b.actions || []).join('/') || '无'}`); return { grants: S().grants };
  });
  X.first('PATCH', '/api/v1/admin/roles/:id', (b, p) => { needAdmin(); const r = S().roles.find((x) => x.id === p.id); if (b.mask !== undefined) r.mask = !!b.mask; if (b.desc) r.desc = b.desc; log(`角色 · ${r.name}：${b.mask !== undefined ? (b.mask ? '开启' : '关闭') + '敏感字段打码' : '修改说明'}`); return { item: r }; });
  /* ---------- 管理：应用管理（状态 / 灰度 / 停用原因） ---------- */
  X.first('PATCH', '/api/v1/admin/apps/:id', (b, p) => { needAdmin(); const a = S().apps.find((x) => x.id === p.id); if (!a) X.err(404, 'NOT_FOUND', '应用不存在'); Object.assign(a, { status: b.status || a.status, statusNote: b.statusNote || '' }); log(`应用 · ${a.name} → ${({ published: '已发布', gray: '灰度', disabled: '停用' })[a.status] || a.status}`); return { item: a }; });
  /* ---------- 管理：平台设置 ---------- */
  X.first('GET', '/api/v1/admin/settings', () => { needAdmin(); return { settings: S().settings, org: S().org }; });
  X.first('PUT', '/api/v1/admin/settings', (b) => { needAdmin(); Object.assign(S().settings, b.settings || {}); if (b.seats) S().org.seats = +b.seats; log('修改平台设置'); return { settings: S().settings }; });

  /* ---------- 统一鉴权（每个请求先过这里；与 haiknow 服务端判定一致） ---------- */
  const appOf = (p) => { let m = /^\/api\/apps\/(\w+)\//.exec(p); if (m) return m[1]; if (/^\/api\/v1\/kb\//.test(p)) return 'kb'; if (/^\/api\/v1\/(skills|builder)/.test(p)) return 'skills'; return null; };
  A.guard = (method, p) => {
    if (/^\/api\/v1\/auth\//.test(p)) return;
    if (!S().session) X.err(401, 'UNAUTHENTICATED', '登录已失效，请重新登录');
    if (/^\/api\/v1\/admin\//.test(p) || (method === 'PATCH' && /^\/api\/v1\/models\//.test(p))) { needAdmin(); return; }
    const app = appOf(p); if (!app) return;
    const read = method === 'GET' || /\/(search|match|calc|compare)$/.test(p);
    const act = read ? 'view' : 'operate';
    if (!X.can(app, act)) X.err(403, 'FORBIDDEN', `你的角色没有「${APP_NAMES[app]}」的${act === 'view' ? '查看' : '操作'}权限`);
  };

  /* ---------- 前端判定（界面显示 / 隐藏用；真正拦截在上面 guard） ---------- */
  window.JKAuth = {
    APPS, APP_NAMES,
    user: () => (S().session ? me() : null),
    role: () => X.roleOf(),
    can: (app, action) => !!S().session && X.can(app, action || 'view'),
    isAdmin: () => !!S().session && X.can('*', 'admin'),
    masked: () => !!X.roleOf().mask,
    approvers: () => S().users.filter((u) => u.status === 'active' && X.can('document', 'approve', u) && !X.can('*', 'admin', u)),
  };
})();

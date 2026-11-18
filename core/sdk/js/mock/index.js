// 浏览器端假数据服务：只替换应用的数据接口，登录、应用目录和权限仍走真平台。
//
// 用法一（推荐）：在地址后加 ?mock=normal
//   http://127.0.0.1:8800/?mock=normal#/app/<id>
//   场景：normal（正常）、forbidden（写接口 403）、failure（写接口 500）、
//         slow（每个响应慢 1.2 秒）、conflict（第一次保存返回 409 版本冲突）
// 用法二：import { installMock } from '/sdk/mock/index.js'; const mock = installMock({ scenario: 'conflict' });
//   mock.scenario('normal'); mock.user('samplereviewer'); mock.reset(); mock.restore();
//
// 只拦截 /api/apps/<id>/...；/api/me、/api/auth/*、/api/apps 目录、/api/v1/me 等照常打到真服务。
// 数据只存在当前页面内存里，刷新即清空；不写平台 data/。
// 记录字段不做模板 schema 校验：请求里的 data 或自定义字段原样保存，导出按字段逐行展开。

const SCENARIOS = ['normal', 'forbidden', 'failure', 'slow', 'conflict'];
const DEFAULT_DELAY = 1200;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });
}

function detailError(status, detail, extra = {}) {
  return json({ detail, ...extra }, status);
}

function envelope(status, code, message, extra = {}) {
  return json({ error: { code, message, retryable: false, ...extra } }, status);
}

function text(body) {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/csv; charset=utf-8' },
  });
}

function isMocked(path) {
  return /^\/api\/apps\/[^/]+\/.+/.test(path);
}

function csvCell(value) {
  const s = String(value ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

const ENVELOPE_KEYS = new Set(['project', 'type', 'data', 'files', 'refs', 'baseVersion']);
const FIELD_LABELS = { title: '标题', content: '内容' };

// 记录的业务字段：请求带 data 时原样保留（v1 允许任意 JSON），否则把 data/type 之外的字段收进 data。
function dataOf(body) {
  if (Object.hasOwn(body, 'data')) return body.data;
  return Object.fromEntries(Object.entries(body).filter(([key]) => !ENVELOPE_KEYS.has(key)));
}

export function toCsv(record) {
  const data = record.data && typeof record.data === 'object' && !Array.isArray(record.data) ? record.data : {};
  const rows = [['字段', '内容']];
  for (const [key, value] of Object.entries(data)) rows.push([FIELD_LABELS[key] || key, value]);
  rows.push(['状态', record.status]);
  rows.push(['提交人', record.submitter]);
  rows.push(['确认人', record.confirmedBy || '']);
  return `\ufeff${rows.map((row) => row.map(csvCell).join(',')).join('\n')}\n`;
}

export function installMock({
  scenario = 'normal',
  delay = DEFAULT_DELAY,
  fetch: injectedFetch,
  base = globalThis.location?.href || 'http://localhost/',
} = {}) {
  if (!SCENARIOS.includes(scenario)) {
    throw new Error(`未知假数据场景 ${scenario}，可选：${SCENARIOS.join(' / ')}`);
  }
  const original = injectedFetch || globalThis.fetch.bind(globalThis);
  // 应用在新外壳的 iframe 里运行；切换账号会重建 iframe，数据要存在父窗口才能跨账号。
  const host = globalThis.parent && globalThis.parent !== globalThis ? globalThis.parent : null;
  if (host && !host.__hkMockState) {
    host.__hkMockState = { records: new Map(), reviews: new Map(), conflicted: new Set(), seq: 0 };
  }
  const shared = host ? host.__hkMockState : { records: new Map(), reviews: new Map(), conflicted: new Set(), seq: 0 };
  const records = shared.records;
  const reviews = shared.reviews;
  const conflicted = shared.conflicted;
  let current = scenario;
  let overrideUser = null;

  const nextId = (prefix) => `${prefix}-${++shared.seq}`;
  const now = () => Math.floor(Date.now() / 1000);
  const resolve = (path) => new URL(path, base);

  async function who() {
    if (overrideUser) return overrideUser;
    const response = await original(resolve('/api/me'), { credentials: 'same-origin' });
    if (!response.ok) return null;
    return response.json();
  }

  async function bodyOf(init) {
    if (!init || !init.body) return {};
    if (typeof init.body === 'string') {
      try { return JSON.parse(init.body); } catch { return {}; }
    }
    return {};
  }

  function recordOf(appId, rid) {
    const record = records.get(rid);
    return record && record.appId === appId ? record : null;
  }

  function serialize(record) {
    return { ...record };
  }

  async function handle(appId, rest, method, init, url) {
    const user = await who();
    if (!user) return envelope(401, 'unauthenticated', '请先登录');
    const body = await bodyOf(init);

    if (rest === 'records' && method === 'GET') {
      const project = url.searchParams.get('project');
      const items = [...records.values()]
        .filter((r) => r.appId === appId && (!project || r.project === project))
        .sort((a, b) => b.createdAt - a.createdAt)
        .map(serialize);
      return json({ items });
    }

    if (rest === 'records' && method === 'POST') {
      if (!body.project || typeof body.project !== 'string') {
        return detailError(422, '请求字段缺失或类型不正确');
      }
      const record = {
        id: nextId('r'), appId, project: body.project, type: body.type || 'note',
        data: dataOf(body), files: Array.isArray(body.files) ? body.files : [],
        refs: Array.isArray(body.refs) ? body.refs : [],
        version: 1, status: 'draft', submitter: user.id, confirmedBy: null, createdAt: now(),
      };
      records.set(record.id, record);
      return json(serialize(record), 201);
    }

    const recordMatch = rest.match(/^records\/([^/]+)(?:\/(submit|export))?$/);
    if (recordMatch) {
      const record = recordOf(appId, recordMatch[1]);
      if (!record) return envelope(404, 'not_found', '记录不存在');
      const action = recordMatch[2];

      if (!action && method === 'GET') return json(serialize(record));

      if (!action && method === 'PUT') {
        if (current === 'conflict' && !conflicted.has(record.id)) {
          conflicted.add(record.id);
          record.version += 1;
          record.status = 'draft';
          record.confirmedBy = null;
          return envelope(409, 'version_conflict', '记录已有新版本，请重新读取后保存', {
            currentVersion: record.version,
          });
        }
        if (Number(body.baseVersion) !== record.version) {
          return envelope(409, 'version_conflict', '记录已有新版本，请重新读取后保存', {
            currentVersion: record.version,
          });
        }
        record.version += 1;
        record.status = 'draft';
        record.confirmedBy = null;
        if (body.project) record.project = body.project;
        if (body.type) record.type = body.type;
        if (Object.hasOwn(body, 'data')) {
          record.data = body.data;
        } else {
          const base = record.data && typeof record.data === 'object' && !Array.isArray(record.data) ? record.data : {};
          record.data = { ...base, ...dataOf(body) };
        }
        for (const review of reviews.values()) {
          if (review.recordId === record.id && review.status === 'pending') review.status = 'recheck';
        }
        return json(serialize(record));
      }

      if (action === 'submit' && method === 'POST') {
        if (!['draft', 'needs_info'].includes(record.status)) {
          return envelope(409, 'invalid_state', '只有草稿或待补充记录可以提交确认');
        }
        if (body.version != null && Number(body.version) !== record.version) {
          return envelope(409, 'stale_version', '只能提交当前最新版本', { currentVersion: record.version });
        }
        const review = {
          id: nextId('rv'), appId, recordId: record.id, version: record.version,
          assignee: body.assignee || null, submitter: user.id, status: 'pending',
          createdAt: now(), decisions: [],
        };
        reviews.set(review.id, review);
        record.status = 'pending';
        return json({ ...review }, 201);
      }

      if (action === 'export' && method === 'GET') {
        if (record.status !== 'confirmed') return detailError(409, '记录确认后才能导出');
        return text(toCsv(record));
      }
    }

    if (rest === 'reviews' && method === 'GET') {
      const all = [...reviews.values()].filter((r) => r.appId === appId);
      return json({
        todo: all.filter((r) => r.status === 'pending' && r.submitter !== user.id
          && (!r.assignee || r.assignee === user.id)),
        submitted: all.filter((r) => r.submitter === user.id),
      });
    }

    const reviewMatch = rest.match(/^reviews\/([^/]+)\/decisions$/);
    if (reviewMatch && method === 'POST') {
      const review = reviews.get(reviewMatch[1]);
      if (!review || review.appId !== appId) return envelope(404, 'not_found', '确认待办不存在');
      const record = recordOf(appId, review.recordId);
      if (!record) return envelope(404, 'not_found', '记录不存在');
      if (user.id === record.submitter || user.id === review.submitter) {
        return envelope(403, 'self_review', '提交人不能确认自己的记录');
      }
      if (review.status !== 'pending') {
        return envelope(409, 'invalid_state', '此待办已处理或需重新核对');
      }
      if (Number(body.version) !== review.version) {
        return envelope(409, 'stale_version', '记录已有新版本，不能确认旧版本', {
          currentVersion: record.version,
        });
      }
      if (review.assignee && review.assignee !== user.id) {
        return envelope(403, 'forbidden', '此待办已指定其他确认人');
      }
      if (body.decision === 'confirm') {
        review.status = 'confirmed';
        record.status = 'confirmed';
        record.confirmedBy = user.id;
      } else if (body.decision === 'return') {
        review.status = 'needs_info';
        record.status = 'needs_info';
      } else if (body.decision === 'reassign') {
        if (!body.assignee) return envelope(422, 'invalid_request', '换人时必须指定确认人');
        review.assignee = body.assignee;
      } else {
        return envelope(422, 'invalid_request', '未知确认动作');
      }
      const decision = { ...body, actor: user.id, createdAt: now() };
      review.decisions.push(decision);
      return json({ ...review, decision });
    }

    if (rest === 'artifacts' && method === 'GET') {
      const project = url.searchParams.get('project');
      const items = [...records.values()]
        .filter((r) => r.appId === appId && r.status === 'confirmed' && (!project || r.project === project))
        .map((r) => ({ ...r, recordId: r.id, files: [] }));
      return json({ items });
    }

    return envelope(404, 'not_found', '假数据服务没有这个接口');
  }

  async function mockFetch(input, init = {}) {
    const raw = typeof input === 'string' ? input : input.url || String(input);
    const url = new URL(raw, base);
    if (!isMocked(url.pathname)) return original(input, init);
    if (current === 'slow') await sleep(delay);

    const method = String(init.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    if (method !== 'GET' && current === 'forbidden') {
      const appId = url.pathname.split('/')[3];
      return detailError(403, `无权限：${appId} 的 operate`, { app: appId, action: 'operate' });
    }
    if (method !== 'GET' && current === 'failure') {
      return envelope(500, 'internal_error', '平台处理失败，请联系管理员', { retryable: true });
    }

    const match = url.pathname.match(/^\/api\/apps\/([^/]+)\/(.+)$/);
    if (!match) return original(input, init);
    return handle(decodeURIComponent(match[1]), match[2], method, init, url);
  }

  globalThis.fetch = mockFetch;

  return {
    get scenario() { return current; },
    scenario(name) {
      if (!SCENARIOS.includes(name)) throw new Error(`未知假数据场景 ${name}，可选：${SCENARIOS.join(' / ')}`);
      current = name;
      return this;
    },
    user(user) {
      overrideUser = typeof user === 'string' ? { id: user, name: user, roles: [], isAdmin: false } : user;
      return this;
    },
    reset() {
      records.clear();
      reviews.clear();
      conflicted.clear();
      shared.seq = 0;
    },
    restore() {
      if (globalThis.fetch === mockFetch) globalThis.fetch = original;
    },
    get state() { return shared; },
  };
}

export function installMockFromQuery(search = globalThis.location?.search || '') {
  const name = new URLSearchParams(search).get('mock');
  if (!name) return null;
  if (!SCENARIOS.includes(name)) {
    console.warn(`[假数据] 未知场景 ${name}，可选：${SCENARIOS.join(' / ')}；本次不启用假数据`);
    return null;
  }
  const mock = installMock({ scenario: name });
  globalThis.__hkMock = mock;
  if (globalThis.document) document.title = `[假数据 ${name}] ${document.title}`;
  return mock;
}
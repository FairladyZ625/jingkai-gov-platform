# v4 应用模块契约（APP_CONTRACT）· 冻结版 1.1

## ★ 0. 前后端分离（硬性，Rick 10:06）

```
界面 apps/<id>/*.js ──只调──▶ 接口适配 api/<id>.js（typed：入参→出参，与《接口规范》v1.2 同名同构）
                                  │  JKHttp.request(method, path, body)
                                  ▼
            JK_CONFIG.api.mode = 'mock' ──▶ mock/mock-api.js + mock/auth.js + mock/<id>.js（浏览器内模拟后端，AI 结果为模拟，知识库用 data/ 真实数据）
                               = 'http' ──▶ fetch(baseUrl + path)（真实后端，界面一行不改）
```

1. **界面代码禁止**访问 `window.JK_DATA` / `window.MOCK` / `window.JKAPI` / `JKAPI.state()` / localStorage 里的业务数据。只能调用 `ctx.api.<模块>.<函数>()`（即 `window.JKApi.<模块>`）或兜底的 `ctx.api.get/post/...(path)`（同样走 JKHttp）。
2. 每个模块写一个 `api/<id>.js`：`window.JKApi.<id> = { fn: (入参) => JKHttp.post('/api/apps/<id>/...', 入参), ... }`，每个函数上方用注释写 `入参 → 出参`（实体名对齐《接口规范》）。平台接口已在 `api/platform.js`（auth/me/models/chat/reviews/todos/feed/audit/kb/admin/skills/demo）。
3. 模拟实现写在 `mock/<id>.js`：`JKAPI.ext.on(method, path, handler)` 注册路由（handler 收 `(body, params, query)`，返回 JSON，出错 `JKAPI.ext.err(status, code, message)`）；可用 `JKAPI.ext.state()/save()/audit()/nid()/now()/can()/me()`。v1 已有路由见 `mock/mock-api.js`，可以直接复用，不要复制。
4. 在 `config/apps.js` 把自己那行的 `mock: true` / `api: true` 打开（文件存在后再开，否则 file:// 报 404）。
5. 自检：`grep -n "JK_DATA\|JKAPI\|MOCK" apps/<id>/` 必须为空。


> 对应卫华 haiknow 的 `apps/<id>/app.json` + `mount(el, ctx)` 小应用规范。shell（外壳）负责：登录/权限、对话、模型切换、AI 操作员（光标/高亮/任务清单）、收件箱、审计、演示。应用只负责右侧面板里自己的界面和业务。
> 设计规范见 [DESIGN.md](../web/DESIGN.md)；颜色只能用 `assets/theme.css` 变量与 `config/tags.js` 色槽。

## 1. 目录与加载

```
v4/
  index.html                 外壳入口（file:// 直接打开）
  config/                    【可改】Rick 可直接改的配置
    app.config.js            平台名、默认主题、首页建议语等
    apps.js                  启用哪些应用 + 加载哪些文件（新增应用加一行）
    tags.js                  标签→色槽、应用身份色
    mock-data.js accounts.js 种子数据、账号/角色/授权
    operator-intents.js      平台级意图（应用级意图写在各自 manifest）
    demo-script.js           一键演示脚本
    sample-files.js          演示用“拖进对话框”的样例文件
  data/                      真实公开数据（知识库/政策 worker 产出，见 data/REAL_DATA.md）
  mock/mock-api.js auth.js   模拟后端（JKAPI，路径与《接口规范》一致）
  assets/theme.css ui.css    设计令牌 + 通用组件
  assets/shell.*.js          外壳
  apps/<id>/
    app.js                   必须：调用 JK.registerApp(...)
    app.css                  必须存在（可为空）；所有选择器以 .app-<id> 开头
    mock.js                  可选：本应用的模拟后端路由（JKAPI.ext.on）
    *.js                     其它文件，需在 config/apps.js 的 files 里按顺序列出
```

加载顺序：`theme.css ui.css` → `config/*.js`（数据）→ `data/*.js`（真实数据，可改写 `window.JK_DATA`）→ `mock/mock-api.js auth.js` → `assets/shell.core.js`（提供 `window.JK`）→ 各应用 `files` → 外壳其余部分 → 启动。
**不允许**：CDN、fetch 本地 JSON（file:// 不支持）、ES module import、写全局 CSS（不以 `.app-<id>` 开头）、硬编码颜色。

## 2. 注册

```js
JK.registerApp({
  manifest: {                       // ≈ haiknow app.json
    id: 'policy',                   // 与目录名一致
    name: '政策兑现', short: '政策', // 侧栏 / 标签页用 short
    icon: 'policy',                 // JK.icon 名称（见 §6），或一段 <svg>
    hue: 'indigo',                  // 身份色，默认取 config/tags.js 的 JK_APP_HUES
    version: '2.0.0', owner: 'AI 工作组',
    summary: '一句话（≤24 字）',
    routes: ['home', 'match', 'detail', 'calc', 'notice'],   // 应用内页面；home 为默认
    perms: { view: '查看', operate: '匹配/试算', approve: '—' },  // 动作说明（授权矩阵里显示）
    tools: [ { name: 'policy.match', desc: '为企业匹配政策', params: { entId: 'string' } } ], // 模型可调用的工具（≈ haiknow tools）
    accepts: [ { kind: '政策文件', ext: ['pdf','docx','txt'], match: /政策|办法|细则|通知/ } ], // 对话框丢文件时的识别规则（§5）
    intents: [ /* §4 */ ],
    starters: ['书香里文化能申请哪些支持？'],   // 首页/空对话建议语，最多 3 条
    demo: [ /* §7 */ ],
  },
  mount(el, ctx) {                  // el 为右侧面板容器（已加 class="app-policy"）
    // 渲染；返回控制对象
    return {
      go(route, params) {},         // 外壳/深链/操作员切换页面
      actions: {                    // 操作员可调用的动作，名字与 intents[].action 对应
        async match({ entId, text }, run) { /* 见 §4 */ },
      },
      onTheme(theme) {},            // 可选：主题切换（一般不需要，CSS 变量自动生效）
      unmount() {},
    };
  },
});
```

## 3. ctx（外壳注入）

| 字段 | 说明 |
|---|---|
| `ctx.api` | = `window.JKApi`（各模块 typed 接口，如 `ctx.api.policy.match({entId})`、`ctx.api.kb.ask({q})`）+ 兜底 `get/post/put/patch/del(path, body)`（走 JKHttp）。失败抛 `{status, code, message}` |
| `ctx.user` | 当前用户 `{id, name, role, roleName, dept, title}` |
| `ctx.perms` | `can(action, appId?)`（`view/operate/approve/admin`）、`mask(field, value)`（外部协作者看手机号/营收等自动打码）、`isPartner` |
| `ctx.theme` | `get()` → `'dark'|'light'`，`on(cb)` |
| `ctx.ui` | `tag(label, group?)` 返回 HTML 胶囊；`hue(label, group?)`；`icon(name)`；`appIcon(appId,size)`；`toast(msg, {type, action})`；`modal({title, body, ok, okText, onMount})`；`drawer({title, body, onMount, width})`；`confirm(text, {danger})` → Promise<bool>；`empty({icon,title,desc,action})`；`steps(list, current)`（向导步骤条 HTML）；`esc`、`md`、`download(name, content, mime)`、`fmtMoney`、`fmtDate` |
| `ctx.nav` | `open(appId, route?, params?)`、`go(route, params)`（本应用内）、`back()`、`chat(text)`（把一句话发到对话框，由 AI 接着办） |
| `ctx.kb` | 知识库服务（§8）：`search(q, opts)`、`ask(q, opts)`、`open(docId, {highlight})`、`spaces()`、`import(files, opts)` |
| `ctx.operator` | 操作员钩子（§4）：`isRunning()`、`run` 对象在动作里传入 |
| `ctx.chat` | `post(card)` 往当前对话插入卡片（结果卡、确认卡）；`say(text)` 助手发一句话 |
| `ctx.bus` | `on(evt, fn)` / `emit(evt, data)`，跨应用事件：`kb:changed`、`todo:changed`、`inbox:changed`、`data:reset` |
| `ctx.params` | 打开时的参数（深链 / 操作员 / 拖入文件 `{file}`） |
| `ctx.audit(action, detail)` | 写审计日志（写操作必须调用；mock 路由内已写的不用重复） |

## 4. 意图与操作员（AI 替你操作）

应用在 manifest 里声明意图；外壳负责理解用户的话（关键词 + 模糊 + 实体抽取），展示**任务清单**（v3 逐条打勾），然后调用应用 `actions[action](slots, run)`。

```js
intents: [{
  id: 'policy.match',
  examples: ['帮我查一下星河智驾能申报哪些政策', '书香里能享受什么补贴'],   // 也用于模糊匹配与帮助
  keywords: ['政策', '申报', '补贴', '兑现', '能报'],
  slots: { ent: 'enterprise' },     // 外壳自动从话里抽取：enterprise | meeting | doc | policy | kbdoc | date | amount
  action: 'match',
  plan: ['打开政策兑现', '选择企业', '逐项匹配政策', '汇总可申报事项'],   // 任务清单，≤5 步，每步 ≤12 字
  confirm: false,                   // true = 先问“我理解为…，要这样做吗？”
}]
```

动作函数里用 `run` 驱动界面（外壳负责光标动画、高亮、清单打勾、演示加速、用户随时“停止/我来接手”）：

```js
async match({ ent, text }, run) {
  await run.step(1);                                   // 第 2 步开始（0 基），前一步自动打勾
  await run.fill('[data-op="policy.ent"]', ent.name);  // 光标移过去、逐字输入
  await run.click('[data-op="policy.go"]');            // 光标移过去、点
  await run.wait(() => el.querySelector('.result'));   // 等结果出现
  await run.step(3);
  const ok = await run.ask('有 2 项需要补充营收数据，现在补填吗？', ['补填', '先跳过']); // 人工决策点：暂停等用户选
  run.done('匹配完成：可申报 5 项，待核对 2 项', [{ label: '生成告知书', say: '给星河智驾生成政策告知书' }]);
}
```

`run` API：`step(i)`、`fill(sel, text)`、`click(sel)`、`select(sel, value)`、`highlight(sel, note?)`、`scroll(sel)`、`wait(fnOrSel, timeout)`、`sleep(ms)`、`ask(question, options)` → 选中的选项（**签发、提交、入库、删除、对外发送**前必须 `ask`，演示模式自动选第一个）、`say(text)`、`done(summary, nextActions)`、`fail(msg)`、`stopped`（用户点停止后为 true，动作应尽快 return）。
**约定**：所有操作员要点的元素都加 `data-op="<appId>.<name>"`，不要依赖 class 名。

## 5. 文件投递（拖入 / 粘贴 / 附件）

外壳统一接收文件（拖到对话区、粘贴、回形针按钮、或演示样例 `config/sample-files.js`），读取文件名/类型/前 4KB 文本，按所有应用的 `accepts` 打分，选出最匹配的应用，回复一句“这是一份会议录音，我来转写并整理纪要”，并打开该应用，调用 `actions.intake({ file }, run)`。
`file = { name, ext, size, kind, text, dataUrl?, sample? }`。音频/图片不读文本，只给 `kind`。
声明了 `accepts` 的应用**必须**实现 `actions.intake`。识别不出时外壳给 2–3 个选项让用户点（含“存入知识库”）。

## 6. UI 规则（摘要，详见 DESIGN.md）

- 只用 `assets/ui.css` 组件：`.btn(.primary/.ghost/.soft/.danger/.sm)`、`.tag[data-hue]`、`.card`、`.tbl`、`.list .li`、`.field .input .select .textarea`、`.tabs .tab`、`.seg`、`.wiz-steps`、`.wiz-foot`、`.empty`、`.tl`、`.callout`、`.src .cite`、`.diff`、`.drop`、`.bar`。
- 标签一律 `ctx.ui.tag(text, group)`，不要自己写颜色。
- 面板结构：`应用页头（图标+名称+1 个主按钮）` → `tabs（≤5）` → 内容。每个视图最多 1 个 `.primary`。
- 图标：`ctx.ui.icon(name)`，可用名称：chat search inbox plus send paperclip mic file folder upload download play pause stop check x chevron-right chevron-down more settings user users shield key lock eye eye-off sun moon sparkles bolt policy building meeting doc book skill computer globe clock calendar flag alert info link copy edit trash refresh filter sort table list grid star arrow-right external history logout。

## 7. 演示片段

`manifest.demo = [{ title: '政策匹配', say: '帮我查一下星河智驾能申报哪些政策' }, ...]`。外壳的 `config/demo-script.js` 串联各应用片段，把 `say` 打进对话框并运行对应意图（`ask` 自动选默认项）。片段需在 **25 秒内**跑完（演示加速下）。

## 8. 知识库服务（kb 模块提供，所有应用与对话可用）

kb 应用在 `app.js` 里额外调用 `JK.provide('kb', service)`；外壳把它作为 `ctx.kb` 注入所有应用，并供对话回答引用。未提供时外壳回退到 `/api/v1/kb/*` 模拟路由。

```js
service = {
  async search(q, { space, limit = 8, filters } = {}) → { hits: [{ id, title, space, snippet, score, source: { org, date, url, docNo } }] },
  async ask(q, { space, appId } = {}) → { answer /* markdown，句末用 [1][2] 标注 */, citations: [{ n, id, title, snippet, source }] , confidence: 'high'|'mid'|'low' },
  async open(id, { highlight } = {}) → 打开知识库原文阅读器并高亮,
  async spaces() → [{ id, name, count, hue }],
  async import(files, { space } = {}) → { docs: [...] },   // 解析、切片、入库（模拟）
}
```

对话回答引用：外壳渲染 `[n]` 为 `.cite`，点击调用 `kb.open(id, {highlight: snippet})`；回答下方列出出处 `.src`（标题 · 发文机关 · 日期 · 原文链接）。

## 9. 跨应用约定

- 打开其它应用：`ctx.nav.open('document', 'new', { from: 'meeting', meetingId })`。
- 待办/审签：写入 `/api/v1/todos`、`/api/v1/reviews`（外壳收件箱展示），并 `ctx.bus.emit('inbox:changed')`。
- 不直接读写其它应用的 DOM 或 localStorage。共享数据只通过 `ctx.api` 与 `ctx.kb`。
- 需要外壳新增能力：写到 `v4/CONTRACT_REQUESTS.md`（标注应用 id 与需求），lead 处理后在同文件回复。

## 10. 补充（10:20）
- 身份色 CSS 变量：`--app-<id>` / `--app-<id>-bg`（policy enterprise meeting document kb skills computer），定义在 theme.css。
- 应用可有 `apps/<id>/config.js`（文案/示例/步骤名），在 `config/apps.js` 的 `files` 里放在 `app.js` 前面即可；应用 worker 可以直接改自己那一行。
- 技能中心 `skills`：技能上架走 `/api/v1/reviews`（type:'skill'），审签领导/管理员在收件箱和管理后台「技能审核」里处理；外壳意图“帮我做个技能…”路由到 `skills.actions.create({text})`。
- 电脑操作 `computer`：外壳意图“帮我去…系统填/登录/下载…”路由到 `computer.actions.run({text})`；提交/登录/签字前必须 `run.ask`。
- 真实数据加载：`index.html` 固定加载 `data/index.js`；知识库/数据 worker 在 `data/index.js` 里用 `document.write('<script src="data/xxx.js"><\/script>')` 依次加载自己的数据文件（在 mock-api 之前执行，可改写 `window.JK_DATA`，如替换 `policies/policyDocs/files/libraries`）。
- 应用最小骨架示例：`apps/_template/app.js`（lead 提供）。


> §2 附注（1.1.1）：`mount()` 可选返回 `ready: () => Promise`，外壳打开应用后会先 `await ctl.ready()` 再调用 action，用于异步首屏，避免首屏渲染盖掉 action 打开的界面。`run.done(summary, next, extra)` 的 `extra` 可带 `{ cites }`（格式同 `JKShell.citesOf(kbAskResult)`），对话里会渲染出处。

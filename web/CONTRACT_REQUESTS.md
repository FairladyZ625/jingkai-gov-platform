
## [skills + computer] 来自 技能中心/电脑操作 worker（10:20）
1. **config/apps.js**：我已把自己两行的 files 改成 `skills: ['mock.js','engine.js','app.js']`、`computer: ['sites.js','tasks.js','mock.js','app.js']`（只改这两行；如需回退请告知）。
2. **JK.provide('skills', svc)**：技能中心提供 `svc.match(text) → {skill, score}|null`（按技能的触发语匹配）、`svc.run(skillId, inputs, {onStep}) → {markdown, citations}`、`svc.list()`。请外壳在意图都没命中（或命中分 < 技能分）时先问 `svc.match`，命中则打开 skills 应用并调用 `actions.run({skillId, text}, run)`。这样用户自制技能的触发语在对话里直接生效。
3. **JK.provide('computer', svc)**：电脑操作提供 `svc.start(taskId, params)`、`svc.tasks()`；其它应用/技能可调用。
4. **授权**：accounts.js 的 grants 里是 `market`，v4 应用 id 是 `skills`/`computer`。我在 skills/mock.js 的 onLoad 里兜底补：member/partner 有 market 就复制到 skills；computer 只给 admin/leader/member（view+operate），外部协作者无。建议 lead 在 accounts.js 正式加上。
5. **审核**：技能“全区公开”走 `/api/v1/reviews`（type:'skill', app:'skills', approver:true），沿用 mock-api 现有 decision 分支（批准→published）。请把该分支 audit 文案“技能广场”改为“技能中心”（可选）。
6. **演示**：两个应用的 manifest.demo 已写好（skills 2 段、computer 2 段），请串进 config/demo-script.js。

## [apps worker] 10:2x · policy / enterprise / meeting / document
1. **config/apps.js**：四个应用的 `files` 请改为 `['config.js', 'app.js']`。每个应用把可改文案/选项放在 `apps/<id>/config.js`（`window.JK_APPCFG.<id> = {...}`），方便 Rick 直接改。app.js 在缺少 config.js 时也能用内置默认值跑，不会报错。
2. **ctx.ui.appIcon(id, size)**：size 用 `'lg'`（40px）做应用页头图标。请确认支持 `'sm' | '' | 'lg'` 三档。
3. **run.ask 返回值**：应用会用 `const c = await run.ask(q, ['确认写入', '先不写'])`，并判断 `c === '确认写入'`。请确认返回的是选项文字（不是下标）。
4. **slots 形态**：`slots.ent` 我们按 `{ id, name, short }` 或字符串两种都处理；`slots.amount` 按“元”的数字处理；`slots.meeting` 按 `{id,title}` 或字符串处理；`slots.policy` 按 `{id,title}` 或字符串处理。
5. 应用自己的测试台：`apps/_harness/index.html?app=policy&theme=light&user=u-hejun`（只是开发用，不进正式入口）。
6. **config/tags.js 新增分组**（四个应用要用；请原样粘贴到 `window.JK_TAGS` 里，应用调用 `ctx.ui.tag(label, group)`）：
```js
  policyLevel:  { '可进一步核对': 'green', '待确认': 'amber', '不满足': 'gray' },
  policyWindow: { '申报中': 'green', '本批已结束': 'gray', '窗口待通知': 'amber' },
  policyObj:    { '企业': 'teal', '个人': 'cyan', '其他组织': 'violet' },
  verify:       { '已核实': 'green', '企业自报': 'amber', '预测': 'violet', '待核': 'gray', '统计报表': 'green' },
  alertKind:    { '资质到期': 'red', '久未走访': 'amber', '诉求临期': 'orange' },
  issueStatus:  { '待分派': 'gray', '办理中': 'blue', '待补材料': 'amber', '已办结': 'green' },
  proposal:     { '待确认': 'amber', '已写入': 'green', '已忽略': 'gray' },
  meetStatus:   { '新录音': 'blue', '整理中': 'blue', '已整理': 'green', '仅局方': 'violet' },
  meetType:     { '企业座谈会': 'teal', '局务会': 'violet', '专题推进会': 'indigo' },
  todoStatus:   { '待认领': 'amber', '待确认': 'amber', '已派发': 'green', '已完成': 'green' },
  checkLevel:   { '必须改': 'red', '建议改': 'amber', '提示': 'blue', '通过': 'green' },
  docStatus:    { '草稿': 'gray', '审签中': 'blue', '已定稿': 'green', '已退回': 'red' },
  docGroup:     { '发布政策与安排': 'indigo', '面向企业组织事项': 'teal', '公开结果与回应': 'orange' },
```
（测试台里已临时注入同样的映射，外壳合入后以 tags.js 为准。）

## [lead 回复] 10:3x
- apps.js：已合入（四应用 `['config.js','app.js']`；skills `['mock.js','engine.js','app.js']`；computer `['sites.js','tasks.js','mock.js','app.js']`）。⚠️ 契约 1.1 起前后端分离：模拟路由请逐步移到 `mock/<id>.js`，接口函数放 `api/<id>.js`，并把 apps.js 里该行 `mock:true / api:true` 打开；`apps/<id>/` 只放界面。现有 `apps/skills/mock.js` 等这次先保留可用，集成前请迁移。
- `ctx.ui.appIcon(id, size)` 支持 `'sm' | '' | 'lg'`。✅
- `run.ask(q, options)` 返回**选项文字**。✅ 演示模式自动选第一个选项。
- slots：外壳给对象 `ent:{id,name,short}`、`meeting:{id,title}`、`policy:{id,title}`、`doc:{id,title}`，`amount` 为“元”数字。✅
- tags.js：13 个分组已原样合入。✅
- `JK.provide('skills', svc)` → 外壳在平台/应用意图未命中或分数低于 `svc.match` 时打开 skills 并调用 `actions.run({skillId,text}, run)`。✅ `JK.provide('computer', svc)` 记下。✅
- accounts.js 已正式改成 `skills`/`computer`（member 有 computer view+operate，partner 无 computer；leader/admin 为 `*`）。mock-api 中 '技能广场' 文案已全部改为 '技能中心'，inbox 种子 app:'market'→'skills'。
- **面板容器**：`mount(el)` 的 el 没有内边距和最大宽度，应用自带布局（apps worker 的 `.ap` 框架 OK）。面板最大化时 el 变宽，请用 max-width 居中。
- demo：各应用 manifest.demo 会被 config/demo-script.js 串联。

## [kb + 真实数据] 来自 知识库 worker（10:5x）
1. **data/**：`data/index.js` 已实现，会 document.write 加载 `real-policies.js`（→ `JK_REAL`，并合并进 `JK_DATA.policies/policyDocs` 等，见 `data/REAL_DATA.md`）和 `real-kb.js`（→ `JK_REAL_KB`）。index.html 现在的位置（config 之后、mock 之前）正确，无需改。
2. **config/apps.js 的 kb 行**请改为：`{ id: 'kb', group: 'platform', mock: true, api: true, files: ['app.js'], css: ['app.css'] }`（mock/kb.js、api/kb.js 我来写）。
3. **对话回答走 kb**：mock-api 里的 `kbSearch()`/`intent==='kb'` 是旧逻辑（只搜 18 条示例）。请外壳在 `kb` 意图（或任何"问原文/出处/多少/截止"类问题）时调用 `JK.services.kb.ask(text)`，按契约 §8 渲染 `answer` 里的 `[n]` 与 `citations`；`confidence:'none'` 时是"知识库里没找到"，原样显示即可（含建议按钮 `suggestions[]`，每项 `{label, say}`）。
4. **对话拖入文件**：外壳识别为"存入知识库"或无法识别时，调 `JK.services.kb.import({ files:[file] }, { from:'chat' })` 或打开 kb 应用 `actions.intake({file}, run)`（会走预览→确认入库，入库前有 `run.ask`）。粘贴网址（含 http）+“导入/存入知识库”时路由到 kb 意图 `kb.import`。
5. **tags.js 请加两组**：
```js
  kbSpace:  { '政策库': 'indigo', '公文范文': 'orange', '会议纪要': 'violet', '部门制度': 'teal' /* 原有项保留 */ },
  kbStatus: { '现行有效': 'green', '即将到期': 'amber', '已失效': 'red', '已更新': 'blue', '示例': 'gray', '解析中': 'blue', '待确认': 'amber', '重复': 'gray', '新版本': 'blue', '已入库': 'green', '模拟解析': 'amber' },
  kbKind:   { '政策文件': 'indigo', '政策解读': 'cyan', '通知范文': 'orange', '信息简报': 'blue', '工作报告': 'violet', '会议纪要': 'violet', '机构职责': 'teal', '内部制度': 'gray', '上传资料': 'pink' },
```
6. **演示片段**（kb manifest.demo）：① “数据券补贴最高能拿多少？”（问答+引用跳原文）② “把这个网址导入知识库 https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202611/t20261103_4930870.html”（网址导入→解析→入库前确认）③ “知识库里有没有关于火星基地的政策？”（如实回答没找到）。请串进 config/demo-script.js。

## [lead 回复 kb] 11:0x
- apps.js kb 行已改 `mock:true, api:true`（请尽快放好 mock/kb.js、api/kb.js，否则 file:// 404）。
- 对话：任何问句（？/什么/怎么/多少/条件/政策/补贴/申报…）且未命中操作意图时 → `JK.services.kb.ask(text)`；渲染 `[n]` 为可点引用、`citations` 为出处列表（含官网链接按钮），`confidence:'none'` 时原样显示 answer + `suggestions[]` 按钮。✅
- 文件：classify 无匹配时给“存入知识库”选项 → 打开 kb 调 `actions.intake({file}, run)`。kb manifest 写 `accepts`（如 政策文件 pdf/docx、kind '政策文件'）即可参与自动识别。网址导入请用 kb 意图（manifest.intents，带 pattern 'https?://'）。✅
- tags：kbSpace/kbStatus/kbKind 已合入。✅  demo：kb 段直接跑 kb manifest.demo 全部片段。✅
7. **[给 KB/真实数据 worker] real-policies.js 数据质量**（政策匹配直接受影响）：
   - `RP-001` cap=100000000（原文“最高100万元”，应为 1000000）；`RP-032` fixed=100000000（原文是“按涉外收入 1%/3%/6% 经评审”，不应是定额 1 亿）——会让试算合计出现“11066 万元”这类离谱数字。建议 gen 脚本对 cap/fixed 做“原文最高 X 万元”的回读校验。
   - 自动生成的触发条件 `{f:'rent', trigger:true, label:'有相关投入/支出（按原文比例计算）'}` 把“赛事支出”“平台固定资产投资”等都映射到 rent（如 RP-053 专业化平台、RP-055 电竞赛事），书店会被匹配成“电竞赛事 12.6 万”。我在 `mock/policy.js` 里先把这类泛化触发条件降级为“待确认、不自动试算”，数据修正后可去掉。
8. **appIcon('policy','lg')**：页头 40px 图标块里的线条图标渲染得很小（看起来像 10px），请检查 `.app-ico svg` 与 `icon()` 输出的宽高是否冲突。

## [lead 回复] 11:2x
- #8 appIcon lg 图标过小：已修（`.app-ico .ico{width:58%;height:58%}`），刷新即可。
- 外壳已可用：登录/对话/任务清单/光标/人工决策卡（模态框打开时决策卡浮在最上层）/收件箱/管理后台/⌘K/主题/一键演示引擎。各应用 flags 请文件就绪后自己在 apps.js 打开；lead 集成测试命令：`node /workspace/jk/v4lead/smoke.js`。
- 提醒：run.ask 的第一个选项 = 演示模式默认选择，请把“推进流程”的选项放第一个。

### [kb] 补充（KB worker，11-18）
- 已自行把 `config/apps.js` 第 13 行 kb 的 files 改为 `['files.js','config.js','app.js']`（只动了 kb 这一行，请知悉）。
- `JK.services.kb.open` 在应用未挂载时会调用 `JKShell.openApp('kb','doc',{id,highlight})`；不再需要 `nav:open` 事件。
- `ask()` 未命中时 `answer` 为“没找到”的说明文字、`confidence:'none'`、`citations:[]`——外壳现有逻辑可直接显示，请不要再回退到模型生成。
- tags.js 建议加：`kbStatus`：现行有效 green / 即将到期 amber / 已失效 gray / 已更新 violet / 申报中 blue / 已截止 gray / 示例 gray / 未找到依据 gray；`kbKind`、`kbSpace` 见上一节。没加也能用（哈希色）。
- 对话中 kb.ask 意图的结果卡目前只有文字，若能复用 `cites` 渲染出处角标更好（answer() 路径已支持）。

## apps worker · 第 2 批（会议记录 / 公文协作完成后）
9. **mock-api genDoc T10 申报时间措辞**：真实政策 `times.window` 多为“见当年申报通知”，现在会生成“申报时间为见当年申报通知。”。建议判断条件加上 `/见当年|以.*通知为准/`，命中时走“当前批次申报通知尚未发布……”分支。（mock/mock-api.js 属主控，未改）
10. **S.drafts 不持久化**：公文草稿只在内存里，刷新/换账号后新起草、已送审的稿子消失，领导（李阳）在另一会话看不到刚送审的稿子。建议 drafts 随 state 一起 save()。目前演示“审签通过”用种子稿 DOC-1112。
11. **KB 检索质量（给 KB worker）**：`kb.search(q,{space:'template'})` 对“申报期限调整 …”这类短查询会返回同一文档的多个切片且相关性弱；公文协作已在前端按标题去重，建议后端返回按文档聚合的结果。
12. **空间 id**：应用侧已统一用 KB 的空间 id（policy / template / minutes / rules）。企业管理没有对应空间，拖入企业资料只打开一企一档、不入库；如需“企业档案”空间请 KB worker 增加。
13. 测试台 `apps/_harness/index.html` 已加载 mock/kb.js + api/kb.js + apps/kb，`ctx.kb` 用真实服务。

## skills/computer worker · 第 2 批（11-18 10:55，替代 10:20 那节中过时的文件清单）
14. **config/apps.js 已由我改好这两行**（只动这两行）：
    `skills: mock:true, api:true, files:['app.js']`；`computer: mock:true, api:true, files:['sites.js','app.js']`。
    旧清单里的 `mock.js / engine.js / tasks.js` 已不存在（已按契约 1.1 移到 `mock/skills.js`、`mock/computer.js`、`api/skills.js`、`api/computer.js`），不改会 404。
15. **外壳 bug 已修（assets/shell.js 两行，请知悉）**：对话区重绘后，`run.ask` 的问题卡片写进了已脱离 DOM 的旧节点，聊天里看不到确认按钮、流程卡死。
    修法：`planEl` 里记 `m._el = el`；`postPlan` 的 `askBox` 改为优先用 `m._el`（仍在页面上时）。所有应用的 run.ask 都受益。
16. **外壳打开应用与 action 的竞争**：`Op.start` 先 `openApp(app, intent.route)`，应用的异步 `go()` / 首次挂载渲染有时在 action 打开的界面之后才返回，把它盖回首页（表现为“界面上没找到 [data-op=…]”）。
    skills / computer 已在应用内用导航序号处理；其它应用如遇同样现象可照做（或外壳 `await ctl.go()` 后再调 action）。
17. **演示片段**（manifest.demo，已写好）：
    - 技能中心：①“帮我做一个技能：核对数据券申报材料齐不齐”（起草→试运行→选“发布到本部门”）②“用实体书店政策预判看看书香里”。
    - 电脑操作：①“帮我把星河智驾的申报表填了”（验证码→停在提交前→确认提交→受理编号）②“去官网把最新的申报通知下载下来存到知识库”。
    每段 run.ask 的第一个选项都是推进流程的选项。电脑操作一段在演示速度下约 25–35 秒。
18. **审核**：全区公开的技能进 `/api/v1/reviews`（type:'skill', app:'skills'），收件箱“通过/退回”走 mock-api 已有的 decisions 分支，我这边路由会同步状态。
19. **权限**：accounts.js 没有 skills/computer 授权时，我在 mock 里沿用 `market` 的授权给 skills，并给 member 开 `computer: view/operate`、partner 不开电脑操作。若后台要单独配置，请在 grants 加 `skills`、`computer` 两项。
20. **样式例外**：弹窗挂在 body 上，`.sk-code`、`.modal .sk-scopes`、`.cu-shotbig` 这几个类不在 `.app-*` 作用域内（都带 sk- / cu- 前缀，不会冲突）。

## [lead 回复 apps 第 2 批 + kb 补充] 10:5x
- #10 公文草稿持久化：已核实 v4 的 mock-api 在每次非 GET 请求后整体 save()（含 S.drafts），新起草 → 送审 → 刷新 / 换李阳登录后仍在，收件箱能看到并审签（测试：DOC-101 起草→修正→送审→李阳收件箱出现 R-102）。演示脚本「公文协作」段已改为：拖入草稿 → 起草数据券延期通知 → 送审签 → 书香里版本对比；「审签」段李阳通过的就是刚送审的新稿（实测 DOC-103 → 已定稿）。
  - 顺带修了一个外壳 bug：`run.wait('选择器')` 只在应用容器里找，弹窗在 body 上 → “等待超时”，送审弹窗残留。现在先找应用容器再找 document。演示每段开始时会清掉残留弹窗。
- #9 genDoc 申报时间：`见当年 / 以…通知为准 / 另行通知` 均走“当前批次申报通知尚未发布……”分支。✅ KB worker 若加了干净字段（如 times.windowText），告诉我字段名我再接。
- kb：apps.js kb 行确认 `mock:true, api:true, files:['files.js','config.js','app.js']`。✅
- tags：kbStatus 补 申报中 blue / 已截止 gray / 未找到依据 gray，已失效改 gray、已更新改 violet（按 KB 建议）；kbKind / kbSpace 已在。✅
- 对话卡片出处：`run.done(summary, next, { cites })` 新增第 3 参（外壳统一渲染角标 + 出处列表 + 官网链接）；`JKShell.citesOf(askResult)` 规范化。kb 的 ask 意图已改为用 answer 首段作结论并带出处。✅
- `confidence:'none'` 一律原样显示 KB 的“没找到”文字 + suggestions，不回退模型（answer 为空时也显示固定的“没找到”文案）。✅
21. **[外壳] 停止提示落到别的对话**：一个操作还在跑时用户点“新对话”再说下一句，`Op.start` 停掉旧操作，`markStopped` 的“已停下，右侧保持当前进度…”会作为新对话的第一条消息（还成了对话标题）。建议 postAI 写回旧操作所在的对话，或新对话里不显示这条。

## [lead 回复 skills/computer 14–21] 11:0x
- #14 apps.js 两行：已确认（files 与 mock/ api/ 一致，整体演示 4 种主题×宽度均 0 报错）。✅
- #15 shell.js 两行（`m._el` + askBox 优先用仍在页面上的卡片）：已复核保留。✅
- #16 打开应用与 action 竞争：外壳 openApp 首次挂载后多等 160ms；另新增**可选**契约 `mount() → { ready: () => Promise }`，外壳会 `await ctl.ready()` 后才调用 action（写在 APP_CONTRACT §2 附注）。应用内导航序号做法也保留。✅
- #19 accounts.js：grants 已正式含 skills / computer（member: skills+computer view/operate；partner: skills view/operate、无 computer；leader/admin `*`）。mock 里的 market 兜底可删可留。✅
- #21 停止提示落到新对话：`stop(true)`（新对话 / 新操作顶替 / 演示跳段）不再发“已停下…”；只有用户点“我来接手”才发。✅
- 另：面板标签超过 4 个时，非当前标签只显示图标；最多保留 6 个，超出关闭最久未用的（1280 宽度下“电脑”标签被挤出屏幕的问题）。

## [kb + 真实数据] 回复 apps worker #7 / #9 / #11 / #12（11-18）
- **#7 金额/触发条件已在数据源修正**（`shared/real-data/rules.py` 重写回读规则，已重新生成 `data/real-policies.js`）：RP-001/003 cap=1000000；RP-032 改为 `rule:{manual:true}`（分档 1%/3%/6%，不自动试算）；RP-053/055 不再是 rent 比例，改为 `fixed`（最高 2000 万/1000 万），身份条件分别为 `['文化平台']`、`['游戏','电竞']`——书店不会再匹配到。全量 83 条复核：奖池额（“每年发放1亿元…券”）、门槛额、单价不再当补贴额；可试算比例规则只剩 4 条（基数在原文同句可确认），其触发条件 label 已不含“有相关投入”，**`mock/policy.js` 的泛化降级可以去掉**（留着也无害）。
- **#9（给 lead，mock-api genDoc）**：每条真实政策新增 `times.deadlineText`（可直接写进公文的一句话）、`times.noticePending`、`times.deadline`、`times.notice`/`relatedNotice`。建议 T10 直接用 `p.times.deadlineText`；`window` 仍保留“见当年申报通知”，你建议的正则也继续有效。
- **#11**：`kb.search` 现在按文档聚合（每份资料 1 条：最佳片段 + `hitCount` 命中片段数 + `coverage`），加最低分 3、相对第一名 20%、关键词覆盖 ≥45% 三道门槛，同标题去重。前端去重可以保留也可以去掉。
- **#12 新空间 `enterprise`「企业档案」**：由企业管理数据生成 14 份“一企一档”（示例，手机号打码），admin/leader/member 可见；标了 `sensitive`，打码角色（外部协作者）**始终不可见**，管理员也放不开。导入时含“一企一档/统一社会信用代码/走访记录”的资料自动归入该空间。企业管理拖入企业资料如要入库：`ctx.kb.import([file], { space: 'enterprise', from: '企业管理' })`。
- **给 lead**：tags.js `kbSpace` 请加 `'企业档案': 'green'`，`kbKind` 加 `'企业档案': 'green'`（不加则哈希色）。

## [lead 回复 kb 第 2 批] 11:0x
- genDoc T10：优先用 `p.times.deadlineText`，没有时再走 window 正则分支。✅
- tags：kbSpace / kbKind 加 `企业档案: green`。✅
- 企业管理拖入企业资料（非表格）：除打开一企一档外，`ctx.kb.import([file], {space:'enterprise', from:'企业管理'})` 存入“企业档案”（外部协作者不导入）。✅

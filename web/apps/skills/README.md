# 技能中心（apps/skills）

把常办的事做成“一句话就能用”的技能，分享给同事；用得多了可升级成小应用。

| 文件 | 作用 |
|---|---|
| `apps/skills/app.js` / `app.css` | 界面（只调 `ctx.api.skills`，不碰数据） |
| `api/skills.js` | 接口适配：`JKApi.skills.*`，每个方法注明 入参 → 出参 |
| `mock/skills.js` | 演示后端：技能引擎（起草 / 运行）+ 路由 `/api/v1/skills/*` |

## 能做什么
- **发现**：官方应用 + 同事的技能；按分类筛选（政策 / 企业 / 会议 / 公文 / 知识 / 数据 / 办公 / 电脑操作，标签各有颜色）；显示作者、使用次数、评分。
- **一键用**：卡片“使用”或在对话里说触发语（例：“用实体书店政策预判看看书香里”）。
- **制作（4 步）**：说需求 → 改一改 → 试一试 → 发布。
  - 说一句话，AI 起草名称、触发语、要填的信息、步骤、输出格式；
  - 可视化编辑，不用写代码；模型、知识库、提示词收在“更多设置”；
  - 用示例试运行，结果带知识库出处；
  - 发布范围：仅自己 / 指定同事 / 本部门 / 全区公开（需审核）。
- **分享**：按人、部门、全区；权限 可用 / 可编辑；复制链接 `jkq://skills/<id>`。
- **审核**：全区公开进入管理员 / 审签领导的收件箱，通过或退回（写原因），全程写审计。
- **版本**：已发布技能每次保存升一个小版本，可查看并回到旧版本。
- **复制改一改**：基于别人的技能 fork 一份自己的。
- **升级为小应用**：生成平台小应用 `app.json` + `SKILL.md`，提交开发组走评审门禁。

## 技能定义（Skill / SkillSpec）
```js
Skill = {
  id: 'sk-shudian', name: '实体书店政策预判', icon: '书', summary: '…',
  base: 'policy',                 // 依托的官方应用（policy / enterprise / meeting / document / kb / computer）
  owner: '王敏', dept: '企业服务处', status: 'draft' | 'in_review' | 'published',
  version: '1.0.0', versions: [{ v, at, by, note, spec }],
  share: { scope: 'private' | 'people' | 'dept' | 'zone', people: ['u-xx'], perm: 'use' | 'edit' },
  uses: 214, rating: 4.9, ratingN: 31, forkOf: null,
  spec: SkillSpec,
}
SkillSpec = {
  cat: '政策',                                   // 分类，决定标签颜色（config/tags.js skillCat）
  triggers: ['实体书店政策预判', '书店能拿多少补贴'], // 对话里这样说就会用它
  inputs: [{ key: 'ent', label: '哪家书店', type: 'ent' | 'text' | 'textarea' | 'number' | 'month' | 'select', required: true, sample: 'E005', options: [] }],
  steps: [                                       // ≤ 5 步，按顺序执行
    { type: 'tool', tool: 'policy.match', args: { entId: '{{ent}}' }, label: '匹配兑现事项' },
    { type: 'kb', query: '实体书店 房租', space: '政策库', label: '查政策原文' },
    { type: 'computer', task: 'stats', label: '去直报平台填表' },  // 交给“电脑操作”，停在提交前
    { type: 'model', label: '试算并写结论' },
  ],
  model: 'deepseek-v4.1-flash',                  // 或 local-qwen-32b（涉密 / 内网）
  kb: ['政策库'],
  output: { format: '要点' | '表格' | '清单' | '公文', title: '{{ent}} 政策预判' },
  prompt: '你是经开区政策兑现助手……只引用知识库原文，不编造。',
}
```
- `{{key}}` 会替换成填写的值。
- 运行是长任务：`POST /api/v1/skills/:id/run` 返回 `job`，界面轮询 `GET /api/v1/skills/jobs/:id`，逐步打勾。
- 结果：`{ title, markdown, citations[], missing[], model, computer }`；`missing` 为必填未填项，结论中标“待确认”。

## 接口（api/skills.js）
`list · get · options · draft · create · save · publish · share · review · fork · restore · remove · undoRemove · rate · run · trial · job · match · manifest · promote`
入参 / 出参见 `api/skills.js` 注释。审核同时出现在 `/api/v1/reviews`（type: `skill`）。

## 对话怎么调
| 说法 | 动作 |
|---|---|
| 帮我做一个技能：核对数据券申报材料齐不齐 | `actions.create({text})`：起草 → 试运行 → 问发布范围 → 发布 |
| 用实体书店政策预判看看书香里 | `actions.run`：找到技能、填好信息、运行、回结论 |
| 把处室周报整理分享给王敏 | `actions.share`（需确认） |
| 有哪些技能待审核 | `actions.review` |

其它模块可用 `JK.services.skills.match(text)` 按触发语找技能（挂载后由 `JK.provide` 提供）。

## 与平台小应用的对应
| 技能中心 | 平台 |
|---|---|
| 说需求 → AI 起草 | builder：对话 → 需求包 |
| 试一试 | builder：渲染 / 预检 / 试跑 |
| 全区公开审核 | reviews |
| 运行（步骤打勾） | jobs（步骤检查点） |
| 升级为小应用 | `apps/<id>/app.json`（contract / sdk / id / name / summary / sector / kind / scenes / owner / actions / defaultRoles / review / needsExternalData / status）+ MR 门禁 |

## 如何修改
- 起草规则（分类、默认模型、知识库、输出格式）：`mock/skills.js` 中 `DRAFT_RULES`【可改】。
- 预置技能：`mock/skills.js` 中 `SEED_SPECS`。
- 接真实后端：`api/http.js` 切到 http 模式，按 `api/skills.js` 的出参实现 `/api/v1/skills/*` 即可，界面不用改。

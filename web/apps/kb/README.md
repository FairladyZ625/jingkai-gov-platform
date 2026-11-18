# 知识库（kb）

一句话：**把资料丢进来，一问就有出处。** 只摘原文、不编答案；找不到就直说。

文件：`files.js`（浏览器端解析）· `config.js`（文案/示例）· `app.js`（界面 + 服务 + 操作员动作）· `app.css` · 后端 `mock/kb.js` · 接口 `api/kb.js`

## 知识空间与可见范围
| 空间 | 内容（种子） | 默认可见 |
|---|---|---|
| 政策库 policy | 经开区官网现行/失效政策原文 67 + 政策解读 40（真实） | 全部角色（含外部协作者） |
| 公文范文 template | 申报通知 24、经开区动态 30、2025 年政府工作报告（真实） | 内部角色 |
| 会议纪要 minutes | 由会议记录应用生成（示例） | 内部角色 |
| 部门制度 rules | 27 个部门机构职责（真实）+ 3 份制度（示例） | 内部角色 |

管理员可在「资料库 → 可见范围」调整（`PATCH /api/v1/kb/spaces/:id`）。

## ctx.kb / JK.services.kb
```js
await ctx.kb.search('数据券', { space: 'policy', filters: { status: '现行有效', year: '2026' } }) // → { hits:[{id,title,snippet,score,status,source}], total, facets }
await ctx.kb.ask('数据券补贴最高能拿多少？')   // → { answer(md, 带[n]), citations:[{n,id,title,snippet,chunk,source}], confidence:'high|mid|low|none', followups, notFound, near }
await ctx.kb.open(docId, { highlight: '原文片段' }) // 打开原文并高亮滚动到该段
await ctx.kb.spaces()                           // → 当前角色可见的空间
// 一步入库（自动解析/切片/打标签/查重；内容重复的会跳过，进 skipped）→ { docs, chunks, skipped }
await ctx.kb.import(files, { space: 'rules' })  // 浏览器 File[] 或对话里的 {name, ext, text}
await ctx.kb.import({ text: '……', title: '…' }) // 粘贴文本
await ctx.kb.import('https://kfqgw.beijing.gov.cn/…') // 网址（字符串或 {url}）
// 需要用户逐个确认（改标签、选新版本）时，走界面：ctx.nav.open('kb','import') 或 actions.intake({file}, run)
```
`confidence:'none'` 时 `answer` 是“没找到”的说明，**调用方不要再拿模型补答案**。

## 导入
1. **选资料**：多文件拖拽 / 粘贴文本 / 网址；对话框丢文件 → `actions.intake({file})`。
2. **解析确认**：每个文件显示 解析 → 切片 → 标签 三步状态；可改标题、空间、标签，预览片段。
   - 内容完全相同 → 「已存在，跳过」；同文号或标题高度相似 → 「作为新版本 / 另存为新资料」（新版本会把旧版标记“已更新”并互相链接）。
3. **完成**：入库数、片段数，可直接“去问问”。

解析能力（全部在浏览器本地）：txt / md / html / csv 真实解析（UTF-8，失败回退 GBK）；docx 真实解析；PDF 尝试抽取文字，抽不到则标「模拟解析」；图片/音频提示改用会议记录或电脑操作。
网址导入：原型不能跨域抓取，用 2026-11-18 抓取的官网**快照**（真实内容）；不在快照里的网址会如实提示“无法读取”。

## 检索
BM25（中文二元切词 + 同义词表：补贴/资助/奖励、截止/期限、延期/延长…）+ 标题加权；失效/旧版降权。
问答为**抽取式**：按问题类型（多少/何时/条件/怎么办/哪些）给句子打分，只引用原文句子，每句带 [n]；覆盖不足即「知识库里没找到」并给“可能相关”。

## 路由（mock/kb.js）
`GET spaces` `PATCH spaces/:id` `POST search` `POST ask` `GET docs` `GET|PATCH|DELETE docs/:id` `POST docs/:id/restore` `POST import/preview` `POST import/url` `POST import/commit` `POST import` `GET stats` `GET suggest`（均在 `/api/v1/kb/` 下）。

## 操作员
意图：`kb.ask` `kb.search` `kb.open` `kb.import` `kb.expiring`；动作 `ask/search/open/import/intake/expiring`，入库前一律 `run.ask` 确认。
演示片段（manifest.demo）：问答带出处 → 点出处看原文 → 网址导入后再问（数据券延期）。

## 真实性标注
- 带「官网」链接的均为 kfqgw.beijing.gov.cn 真实公开资料，抓取日 2026-11-18，清单见 `/workspace/jk/shared/real-data/sources.md`。
- 会议纪要、3 份制度、示例文件均标「示例」。
- 用户新增/修改存本机（localStorage），种子每次从 `data/` 重新读取。

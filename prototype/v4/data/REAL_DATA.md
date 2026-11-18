# 真实公开数据（data/）· 给各应用 worker 的说明

来源：**北京经济技术开发区官网 https://kfqgw.beijing.gov.cn/**（政务公开·政策文件 / 政策解读 / 通知公告 / 统计数据解读；要闻动态·工作动态；职权信息·机构设置；2025 年度工作报告）。抓取日期 **2026-11-18**。
原始数据、抓取脚本、逐条 URL 清单：`/workspace/jk/shared/real-data/`（`sources.md`、`raw/kfqgw_articles.json` 580 篇原文）。重新生成：`cd shared/real-data && python3 gen.py && python3 gen_js.py`。

## 加载

`index.html` 已引入 `data/index.js`，它会按顺序 `document.write` 加载：
1. `data/real-policies.js` → `window.JK_REAL`，并**合并进 `window.JK_DATA`**（在 `mock/mock-api.js` 之前执行，所以 mock 后端、政策匹配引擎直接用得到）
2. `data/real-kb.js` → `window.JK_REAL_KB`（知识库种子，只由 `mock/kb.js` 使用）

## 合并后 JK_DATA 的变化

| 字段 | 内容 |
|---|---|
| `policyDocs` | 原 7 条示例文件 + **92 份现行有效真实文件**（`id: rd-<官网文章号>`，含 `no 文号`、`org 制发单位`、`date`、`expire 失效日期`、`url 官网原文`、`category`、`real:true`）。原示例里能在官网核到的（〔2024〕29号、〔2025〕16号、〔2026〕12号）补上了 `url/realNo`；〔2021〕161号 实体书店办法已被 **京技管发〔2025〕21号《促进实体书店发展的管理办法》** 替代（`supersededBy`）；其余 3 条官网列表中未核到，标 `unverified:true`。 |
| `policies` | 原 18 条示例事项（标 `example:true`，金额口径为演示）+ **83 条真实支持条款 `RP-001…RP-083`**，结构与原事项相同（`conditions / rule / times / keywords / materials / original / doc / clause`），另加 `category`、`source:{url, docNo, org, date, fetched, deptResp}`、`real:true`。 |
| `realNotices` | **144 条申报通知**（2025-09 起）：`{id, title, org, date, window:{start,end}|null, status: 申报中|已截止|未开始|以通知为准, basis:[{title,no}], url, excerpt}`。2026-11-18 当天"申报中"5 条（人工智能产业交流活动、AI 创新创业人才、AI 在校实习生、亦城人才备案认定、亦城人才评审认定）。 |
| `realNews` | **260 条**：政策解读 120、工作动态 60、通知公告 40、数据解读 40：`{id, kind, title, date, org, url, excerpt}`。适合会议/公文/简报的背景素材。 |
| `departmentsReal` | **27 个真实机构**（经济发展局、营商环境建设局、科技和产业促进局、信息技术产业局、生物技术和大健康产业局、机器人和智能制造产业局、高端汽车和新能源产业局、商务金融局、行政审批局……）`{name, url, duty}` |
| `districtFacts` | 40 条区情原句（工作报告，含数字），`{text, source, url, date}`，例："工业总产值突破6800亿，年均增长7.2%…" |

## 真实条款的匹配规则怎么来的（务必在界面上如实说明）

- `rule.text` = 原文中含金额/比例的句子（原句，不改写）；`original` = 该条款原文（≤600 字）。
- `conditions` 是**按原文提炼的规则化表达**：`regInZone` + 领域标签 `tags hasAny [...]`（如 数据要素→`数据/软件`，实体书店→`实体书店/文化消费`）+ 原文写明的资质（高新技术企业 / 专精特新 / 小巨人）+ 有比例时的投入字段（`rent dataPurchase computePurchase datasetInvest renovation sceneInvest firstSale digitalInvest`）。
- **金额回读规则（11-18 修订，脚本 `shared/real-data/rules.py`）**：只取“最高/不超过/上限 X 万元”或“给予 X 万元”；奖池/基金总额（“每年发放 1 亿元数据券”）、门槛（“收入达 1 亿元以上的企业”）、单价（“1.5 元/天/平方米”）一律不当补贴额。
- 有比例且**计算基数能在同一句原文里确认**（房租、算力费用、数据交易金额等）→ `rule:{base, ratio, cap, text}` 可试算，对应触发条件的 label 写明原文口径（如“有算力服务采购支出（原文：按租赁算力费用的30%）”）。目前 4 条：RP-001/003（数据券 10%，最高 100 万）、RP-006/014（算力 30%，最高 2000 万）。
- 只有封顶额 → `rule:{fixed, upTo:true, text}`（显示"最高 X 万元"，**不要说成定额**）。74 条。
- 分档比例或无单一金额 → `rule:{manual:true, notes:[…]}`，**不要自动试算**，显示原文 + “需人工测算”。5 条（RP-020/032/081/082/083）。
- 身份条件按条款细分：文化类分 实体书店 / 游戏电竞 / 文化贸易 / 影视演艺 / 文化平台；开放类分 外资企业 / 保税 / 外贸 / 首店 / 商业零售。书店不会再被匹配到电竞、平台类条款。
- **申报时间**：`times.window` 仍为"见当年申报通知"（兼容旧判断），新增干净字段：
  - `times.deadlineText`：可直接写进公文的一句话，如“当前批次申报通知尚未发布，申报时间以届时通知为准”/“最近一批已于 2026.10.12 截止，下一批时间以后续申报通知为准”/“当前批次申报至 2026.11.30（以申报通知为准）”。
  - `times.noticePending`：true = 没有正在进行的批次；`times.deadline`：申报中时为截止日。
  - `times.notice`：与本条款对应的真实申报通知 `{title,url,date,window,status}`（按依据文号 + 标题关键词对上，31 条）；只对上文件、没对上条款的放 `times.relatedNotice`，不改变状态。
  - 申报中时 `window` 改为“YYYY-MM-DD 至 YYYY-MM-DD”、`open:true`；已截止时 `open:false`。
- 申报材料 `materials` 是通用清单（示例），界面请标"以申报通知为准"。

## 建议用法

- **政策兑现**：事项列表默认展示 `real:true` 的条款（按 `category` 分组/筛选），每条有"官网原文"链接；示例企业仍用原 24 家，按上面的 tags/资质/投入字段即可匹配出真实条款（如 书香里/墨香/云栖 → 实体书店 4 条；亦庄数元/数坊 → 数据券 10%；灵犀/知行/众智 → 算力 30%、人工智能+ 场景 等）。"申报中"徽标用 `realNotices`。
- **公文协作**：`realNotices` 是真实"申报通知"范文；`realNews` 可做信息简报素材；知识库 `公文范文` 空间有 24 份通知全文 + 30 篇工作动态 + 2025 年度工作报告全文。
- **会议记录 / 企业管理**：会议背景、部门名称用 `departmentsReal`；区情数字用 `districtFacts`（引用时带出处）。
- **知识库**：别直接读 `JK_REAL_KB`，请用 `ctx.kb.search / ask / open / import`（见 `apps/kb/README.md`）。

## 示例 vs 真实的标注约定

- `real:true` + `url` → 界面可显示"官网原文"链接。
- `example:true` → 界面显示灰色"示例"标签（`ctx.ui.tag('示例')`）。
- 企业、人员、会议录音、内部制度、会议纪要均为**示例**（虚构），不得说成真实。

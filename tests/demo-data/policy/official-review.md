# 政策种子官网复核

## 范围与方法

基线为 `41e9758`。用 Node VM 执行 `prototype/v4/config/mock-data.js`，在真实资料合并前提取 7 份旧文档和 18 条 PI，再执行 `prototype/v4/data/real-policies.js`，读取原始 `window.JK_REAL`。基线合并后有 99 份文档、101 个事项。新 JSON 有 96 份真实文档、94 个可查事项。原 83 个 RP 的 ID 保留，11 个 PI 按官网证据保留为真实事项。两个示例数组为空，未保留无据金额。

- 从 83 个 RP 的 `source.url` 去重得到 35 个官网页面。下载 HTML，用 Python 标准库 `html.parser.HTMLParser` 读取 `TRS_UEDITOR` 或 `TRS_Editor` 正文，按段落划分，统一 NFKC 并去空白后定位摘录。83 条旧 `original` 均在官网正文连续段落内命中。包含截断、分档或附列情形时继续读该条整段及相关子段。
- 核对每条 `rule.fixed`、`rule.ratio` 和 `rule.cap` 所指的金额、主体和期间。区分年度政策发放总额、企业或项目上限、一次性和累计支持、投入比例、外资或营收门槛。简单单一上限继续标最高值，存在不同主体、分档或独立支路时按条款显示规则，转人工分项核对。
- 历史书店交叉核对 `data/public/rules.json` 与官网。商业历史批次交叉核对 `data/public/kb_docs.json`、官方申报通知及其 DOCX 附件。附件从通知页取链接，用 `zipfile` 读取 `word/document.xml` 的段落。
- 另核对 RP-007 错配申报通知的附件。该通知明列京技管发〔2024〕29 号第四条，RP-007 的依据是第八条。将通知移至相关通知字段，窗口回到待正式通知。 [官方办事指南](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202607/W020260731362010075366.docx)

## 18 条 PI 的处置

| 旧 ID | 处置 | 官网依据及金额 |
| --- | --- | --- |
| PI-01 | 并入 RP-003 | 京技管发〔2025〕16 号第 8 项，数据券按年度数据交易额 10%，单主体年度最高 100 万元。延长后的 2026 年批次已于 11 月 6 日截止。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150108.html) [延期通知](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202611/t20261103_4930870.html) |
| PI-02 | 保留 ID，转真实 | 京技管发〔2025〕16 号第 9 项，最高 200 万元，须评审，没有投入比例。会议样本可继续引用此 ID。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150108.html) |
| PI-03 | 保留 ID，标为历史真实条款 | 京技管〔2021〕161 号第十一条第二项，实际房租或物业费最高 50%，每店每年合计不超过 20 万元；当前书店演示文稿默认用现行 RP-024，旧规则可回顾试算。[旧办法](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202404/t20240426_3639277.html) [现行办法](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202510/t20251030_4247865.html) |
| PI-04 | 移除 | 旧办法第九条是特色经营的一次性 5 万元，第八条新店建设按面积分 6 至 30 万元。未找到原样本所称改造投入 30%、最高 50 万元的规则。[旧办法](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202404/t20240426_3639277.html) |
| PI-05 | 保留 ID，引用已截止批次 | 2025 年度官方申报指南第四节，审定实际投资额最高 5%，单项目最高 500 万元，门槛按业态核实。出处标官方通知及附件，通知无文号。[通知](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/t20260826_4837970.html) [附件](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/W020260826566480305346.docx) |
| PI-06 | 保留 ID，引用已截止批次 | 2025 年度官方申报指南第四节，投资额超 200 万元的智慧管理运营大数据平台，按审定投资最高 50%、单项目最高 200 万元，市区合计不超过投资 70%。旧比例为 20%。[通知](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/t20260826_4837975.html) [附件](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/W020260826567991327353.docx) |
| PI-07 | 移除 | 用文号、政策题名和「首店、旗舰店」组合查找区政府原文，并查经开区公开通知与现有种子。未核实旧条目的第五条及 50 万元组合。 |
| PI-08 | 并入 RP-006 | 京技管发〔2024〕29 号第一条，按实际使用算力结算费用 30%，经评审最高 2000 万元，年度券池 1 亿元。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) |
| PI-09 | 保留 ID，转真实 | 京技管发〔2024〕29 号第三条，新增获得国家网信办生成式人工智能模型备案的企业获一次性 100 万元，取消旧「常态化受理」口径。企业诉求历史步骤可继续引用此 ID。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) |
| PI-10 | 并入 RP-007 | 京技管发〔2024〕29 号第五条是数据专区，第八条才是模型券。按符合要求的实际完成合同金额 50%，最高 500 万元，指定硬件部分排除。原样本项目投入 30% 无依据。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) |
| PI-11 | 保留 ID，转真实 | 京技管发〔2026〕12 号第三条，支持轻组织形态且有闭环交付能力的人工智能原生创业者，个人最高 50 万元。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202609/t20260907_4853819.html) |
| PI-12 | 保留 ID，移除无据金额、年龄线和受理频次 | 京技管发〔2026〕12 号第七条只提出面向青年人才的多元化、阶梯式住房保障。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202609/t20260907_4853819.html) |
| PI-13 | 保留 ID，移除无据金额和月数 | 京技管发〔2026〕12 号第五条只规定符合条件的在校实习生给予实习补贴及就业奖励。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202609/t20260907_4853819.html) |
| PI-14 | 保留 ID，标为历史真实条款 | 京技管〔2022〕153 号第 2 项，符合规定资质的重点科技型企业按 2022 年 11 月在亦庄新城实缴社保人数给予 500 元/人，未设旧样本 20 人门槛。第 3 项是保供保畅。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202405/t20240509_3668562.html) |
| PI-15 | 保留 ID，标为历史真实条款 | 京技管〔2022〕153 号第 7 项，2023 年一季度为亦庄新城规上企业提供服务且符合合同、社保及稳定入职要求，按 300 元/人给予人力资源服务或劳务派遣企业。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202405/t20240509_3668562.html) [实施细则](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202405/t20240511_3674208.html) |
| PI-16 | 与 PI-17 合为一条真实依据 | 京技管发〔2024〕29 号第十三条，高新技术企业认定分支一次性最高 30 万元，适用人工智能企业。旧「附件 2」和 20 万元已移除。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) |
| PI-17 | 保留 ID，覆盖第十三条 | 人工智能企业首升规一次性 30 万元，小巨人和北京市专精特新认定分别一次性最高 50 万元、20 万元，晋级补差。高企认定分支一次性最高 30 万元，按分支核对。[政策](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) |
| PI-18 | 移除 | 京技管发〔2024〕29 号第八条为模型券，没有机器人首购首用条款。京技管发〔2025〕17 号第六条的实际销售额 10%、最多支持 1000 台、每家每年最高 1000 万元是独立措施 RP-017。[2024 年文件](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) [2025 年文件](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202508/t20250812_4171688.html) |

## 三条完整金额口径

| 事项 | 正文口径 | 实现 |
| --- | --- | --- |
| RP-010 医药科技服务业，第 10 项 | 医药创新服务券全年发放总额 5000 万元。购买医药科技服务的创新企业单次不超过合同金额的 20%，同企业每自然年度累计申请和兑付不超过 200 万元，每合同仅一次。科技服务业企业按营业收入增量另获支持，年度上限 500 万元。责任单位为生物技术和大健康产业局、科技和产业促进局。[京技管发〔2025〕9 号](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250430_4079409.html) | 展示两类主体的口径，无单一可试算额。 |
| RP-045 量子核心技术攻关，第一条 | 早期创新项目一次性最高 200 万元。企业上年度研发投入按 20%，经评审最高 500 万元。企业承担国家或北京市重大科技攻关任务，经评审给予 1:1 配套，最高 3000 万元。责任单位为信息技术产业局、科技和产业促进局。[京技管发〔2025〕15 号](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150081.html) | 按三个分支说明。3000 万元在截断处之后，限重大攻关任务配套。 |
| RP-074 研发中心开放融合，第四条 | 市级认定外资研发中心认定当年 80 万元，第二年实缴合同外资达到 200 万美元奖励 60 万元，第三年累计达到 500 万美元且取得至少 5 项专利成果奖励 60 万元。经母公司授权的跨国公司全球研发中心在累计研发投入至少 1000 万美元、上一年度研发投入占母公司全球投入至少 10% 时，首年 120 万元；第二年实缴合同外资至少 400 万美元为 90 万元；第三年累计至少 1000 万美元且取得至少 10 项专利成果为 90 万元。条文明确可与第二条叠加，两组分别核对。第四条未单列责任部门。[京技管发〔2025〕19 号](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202509/t20250916_4203106.html) | 显示六档和原文门槛，无单一可试算额。未将发文部门直接用作责任部门。 |

## 其他真实事项的发现

- RP-013 原字段 300 万元只能代表其中一类，完整正文还有特别审查一次性 300 万元、首次取证落地再支持 800 万元及单企业每年 3000 万元上限。RP-029 原字段 300 万元只属于中档，第三档为 4% 且最高 500 万元，另有增资支持。
- RP-005 的单次最高分档 4000 万元和单企业年度上限 1 亿元是两种口径。RP-024/025 以出版物经营面积分档且同年互斥，RP-027 两类特色发展奖励不得同时申请。RP-021 给予个人，RP-023 面向原文列明的人工智能社群举办方，均去掉仅凭企业通用人工智能标签作推荐的条件。
- RP-008 的汽车文件第四条明确援引经开区人工智能政策，保留原文和出处，RP-006 已在匹配结果时隐藏该重复权益。RP-014 对相关模型业务租赁算力按 30% 计算，系另一文号的独立条款。两项可分别核对，试算页不把同一投入加总。
- 83 条既有事项中，36 条改为分项人工核对或独立口径，12 条补足原文，43 条补齐可从正文识别的责任部门。既有 144 条通知、260 条工作动态、27 个部门、40 个区情事实的公开数据逐项与原发布对象相同。

## 83 条原始事项逐项记录

表中「最高参考」指该条款下可展示的单一上限，细则和主体以原文为准。人工核对表示原文有分档、主体或其他计量差异，接口不据此推导预计申领金额。

| ID | 依据 | 金额核对处理 |
| --- | --- | --- |
| RP-001 | [繁荣高质量数据供给生态 · 第四条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/t20260805_4809951.html) | 原文比例 10%，最高 100 万元 |
| RP-002 | [打造高质量数据集 · 第二条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202508/t20250812_4171688.html) | 最高参考 200 万元 |
| RP-003 | [全面激发企业用数活力 · 第 8 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150108.html) | 原文比例 10%，最高 100 万元 |
| RP-004 | [培育数据领航企业强引擎 · 第 14 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150108.html) | 最高参考 10000 万元 |
| RP-005 | [支持创新药品研发 · 第 3 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250430_4079409.html) | 改为人工核对 |
| RP-006 | [强化普惠算力供给 · 第一条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) | 原文比例 30%，最高 2000 万元 |
| RP-007 | [开展“人工智能+”行动 · 第八条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) | 改为人工核对 |
| RP-008 | [提高算力供给能力 · 第四条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241101_3932515.html) | 改为人工核对 |
| RP-009 | [打造词元分发与技能获取中枢 · 第五条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/t20260805_4809951.html) | 最高参考 5000 万元 |
| RP-010 | [鼓励医药科技服务业发展 · 第 10 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250430_4079409.html) | 改为人工核对 |
| RP-011 | [打造机器人二次开发社区 · 第三条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202508/t20250812_4171688.html) | 最高参考 3000 万元 |
| RP-012 | [加大数据关键技术支持力度 · 第 5 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150108.html) | 改为人工核对 |
| RP-013 | [支持高端医疗器械研发 · 第 4 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250430_4079409.html) | 改为人工核对 |
| RP-014 | [支持智能引擎推理效能跃升 · 第三条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/t20260805_4809951.html) | 原文比例 30%，最高 2000 万元 |
| RP-015 | [加强核心技术攻关 · 第十一条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241126_3950424.html) | 最高参考 2000 万元 |
| RP-016 | [支持科技创新平台建设 · 第八条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241101_3932515.html) | 最高参考 2000 万元 |
| RP-017 | [推动机器人高水平制造 · 第六条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202508/t20250812_4171688.html) | 最高参考 1000 万元 |
| RP-018 | [实施关键技术及产品攻关“揭榜挂帅” · 第七条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202411/t20241101_3932515.html) | 最高参考 1000 万元 |
| RP-019 | [支持智改数转 · 第 6 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202407/t20240731_3763400.html) | 最高参考 1000 万元 |
| RP-020 | [加快产业集聚 · 第 4 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202407/t20240731_3763400.html) | 人工核对 |
| RP-021 | [支持产业精英人才创业 · 第二条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202609/t20260907_4853819.html) | 改为人工核对 |
| RP-022 | [开放全域场景 · 第 2 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202407/t20240731_3763400.html) | 最高参考 300 万元 |
| RP-023 | [共建开源开放的人工智能社群网络 · 第八条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202609/t20260907_4853819.html) | 最高参考 100 万元 |
| RP-024 | [“一刻钟”建设奖励 · 第七条第一项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202510/t20251030_4247865.html) | 改为人工核对 |
| RP-025 | [公共文化服务奖励 · 第七条第二项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202510/t20251030_4247865.html) | 改为人工核对 |
| RP-026 | [活动组织奖励 · 第七条第四项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202510/t20251030_4247865.html) | 改为人工核对 |
| RP-027 | [特色发展奖励 · 第七条第三项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202510/t20251030_4247865.html) | 改为人工核对 |
| RP-028 | [支持发展供应链金融 · 第三条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251111_4277763.html) | 最高参考 500 万元 |
| RP-029 | [支持私募投资机构经营发展 · 第十一条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251111_4277763.html) | 改为人工核对 |
| RP-030 | [支持外商投资多元布局 · 第二条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202509/t20250916_4203106.html) | 改为人工核对 |
| RP-031 | [布局“白菜心”工程项目 · 第 一 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250411_4063074.html) | 改为人工核对 |
| RP-032 | [支持发展数字文化贸易 · 第 8 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202412/t20241212_3964275.html) | 人工核对 |
| RP-033 | [强化脑机接口平台体系建设 · 第 5 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202602/t20260209_4503840.html) | 最高参考 5000 万元 |
| RP-034 | [打造全球制造新引擎 · 第 二 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251203_4318798.html) | 改为人工核对 |
| RP-035 | [布局建设“共享工厂” · 第 2 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251128_4309397.html) | 改为人工核对 |
| RP-036 | [提质规模生产引擎 · 第 3 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251128_4309397.html) | 最高参考 5000 万元 |
| RP-037 | [支持各类金融机构提升业务增速 · 第十四条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251111_4277763.html) | 最高参考 200 万元 |
| RP-038 | [夯实金融支撑功能 · 第六条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202509/t20250916_4203105.html) | 最高参考 100 万元 |
| RP-039 | [构筑自主创新策源要地 · 第 二 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202611/t20261104_4932421.html) | 最高参考 3000 万元 |
| RP-040 | [强化北京方案示范引领 · 第 三 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202611/t20261104_4932421.html) | 最高参考 3000 万元 |
| RP-041 | [构建共性能力体系支撑 · 第 四 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202611/t20261104_4932421.html) | 最高参考 3000 万元 |
| RP-042 | [支持企业设备更新改造实施·支持方式及标准 · 第 三 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202605/t20260529_4672417.html) | 最高参考 3000 万元 |
| RP-043 | [加速脑机接口产品转化 · 第 4 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202602/t20260209_4503840.html) | 改为人工核对 |
| RP-044 | [提高工艺放大水平 · 第 5 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251231_4382771.html) | 最高参考 3000 万元 |
| RP-045 | [核心技术攻关突破 · 第一条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150081.html) | 改为人工核对 |
| RP-046 | [异构融合计算加速 · 第五条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250715_4150081.html) | 最高参考 3000 万元 |
| RP-047 | [培育6G核心技术竞争力 · 第一条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250710_4146472.html) | 改为人工核对 |
| RP-048 | [构建全体系产业服务能力 · 第五条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202507/t20250710_4146472.html) | 最高参考 3000 万元 |
| RP-049 | [配套支持科技创新专项 · 第 二 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250411_4063074.html) | 最高参考 3000 万元 |
| RP-050 | [提升科创企业孵化能力 · 第 十 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250411_4063074.html) | 最高参考 3000 万元 |
| RP-051 | [科技和产业促进局关于公开·支持方式与标准 · 第 三 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202610/t20261021_4913172.html) | 改为人工核对 |
| RP-052 | [设立“拨投联动”专项资金 · 第四条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202610/t20261014_4900905.html) | 改为人工核对 |
| RP-053 | [支持专业化平台建设 · 第 17 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202412/t20241212_3964275.html) | 改为人工核对 |
| RP-054 | [加速原创精品游戏创新应用及上线 · 第 4 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202607/t20260709_4753653.html) | 改为人工核对 |
| RP-055 | [支持举办职业电竞赛事 · 第 7 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202607/t20260709_4753653.html) | 最高参考 1000 万元 |
| RP-056 | [打造创新技术培育加速平台 · 第 5 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251210_4332753.html) | 最高参考 1000 万元 |
| RP-057 | [全链条能碳污精细化管控场景 · 第 4 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251128_4310265.html) | 最高参考 1000 万元 |
| RP-058 | [突破关键核心技术 · 第 1 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251128_4309397.html) | 改为人工核对 |
| RP-059 | [亦庄新城科技企业孵化器认·运营支持 · 第十四条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250415_4065250.html) | 改为人工核对 |
| RP-060 | [评价优秀的科技企业孵化器运营支持 · 第十七条第一项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250415_4065250.html) | 改为人工核对 |
| RP-061 | [重点支持建设一批前沿创新主体 · 第 3 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202502/t20250219_4014953.html) | 改为人工核对 |
| RP-062 | [装配式建筑项目财政奖励资·支持 · 第五条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202410/t20241011_3917203.html) | 最高参考 1000 万元 |
| RP-063 | [评价良好的科技企业孵化器运营支持 · 第十八条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202504/t20250415_4065250.html) | 改为人工核对 |
| RP-064 | [支持新材料高能级创新平台建设 · 第 5 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202609/t20260914_4862329.html) | 最高参考 500 万元 |
| RP-065 | [打造标杆示范场景 · 第 7 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251211_4336459.html) | 改为人工核对 |
| RP-066 | [打造保税服务主阵地 · 第 四 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251203_4318798.html) | 改为人工核对 |
| RP-067 | [打造创新交互强枢纽 · 第 五 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251203_4318798.html) | 最高参考 500 万元 |
| RP-068 | [绿色治理技术揭榜挂帅 · 第 1 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251128_4310265.html) | 最高参考 500 万元 |
| RP-069 | [绿色制造科技成果验证 · 第 2 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251128_4310265.html) | 最高参考 500 万元 |
| RP-070 | [人力资源服务支持 · 第 9 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202502/t20250219_4014953.html) | 改为人工核对 |
| RP-071 | [筑牢科技创新安全屏障 · 第六条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/t20260807_4813468.html) | 最高参考 300 万元 |
| RP-072 | [支持上市辅导专业赋能 · 第五条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251114_4280732.html) | 最高参考 200 万元 |
| RP-073 | [提升国际园区服务品质 · 第五条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202509/t20250916_4203106.html) | 最高参考 100 万元 |
| RP-074 | [推进研发中心开放融合 · 第四条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202509/t20250916_4203106.html) | 改为人工核对 |
| RP-075 | [支持高水平交流合作 · 第 9 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202602/t20260209_4503840.html) | 改为人工核对 |
| RP-076 | [加快科技成果转化 · 第 2 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251231_4382771.html) | 最高参考 100 万元 |
| RP-077 | [加快核心技术创新攻坚 · 第 4 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251210_4332753.html) | 改为人工核对 |
| RP-078 | [人才认定方式及专项奖励 · 第 1 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202502/t20250219_4014953.html) | 改为人工核对 |
| RP-079 | [推进三海行动计划 · 第四条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202509/t20250916_4203105.html) | 最高参考 50 万元 |
| RP-080 | [支持外贸企业合规 · 第三条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202509/t20250916_4203105.html) | 改为人工核对 |
| RP-081 | [激发企业创新动力 · 第一条](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202608/t20260807_4813468.html) | 人工核对 |
| RP-082 | [建设合成生物专业产业空间 · 第 8 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202512/t20251231_4382771.html) | 人工核对 |
| RP-083 | [改变土地用途的项目应按新用途补缴土地价款 · 第 二 项](https://kfqgw.beijing.gov.cn/zwgkkfq/2024zcwj/202511/t20251110_4267716.html) | 人工核对 |

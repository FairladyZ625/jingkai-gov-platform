# 真实补充数据

四份 UTF-8 JSON 数组分别对应同名的 `data/public/` 抓取快照。抓取日期取自原记录。记录可跨集合引用同一原文，条数按各文件独立统计。

| 文件 | 记录 | 抓取日期 | 发布来源与用途 |
| --- | ---: | --- | --- |
| real/gongwen.json | 19 | 2026-11-18 | 北京经开区、东城、门头沟、中国政府网和上海浦东政府网站。按文种查范文，3 份上海样本标“格式参考（非北京）”。3 份会议公开稿另标“新闻通稿”。 |
| real/rules.json | 93 | 2026-11-18 | 北京经开区官网、北京市政务服务网。保留原站效力说明，27 份明确失效的记录标“已失效”。“官网未标注失效”的效力仍需查证。 |
| real/minutes.json | 326 | 2026-11-18 | 北京经开区官网领导动态。全部为会议素材，体裁为新闻通稿，独立于会议纪要空间。 |
| real/enterprises.json | 137 | 2026-11-18 | 北京经开区及北京市政府网站名单、附件和报道。24 条名单或称号有原库核实标记，113 条从报道提取的记录标“未核实”。仅供名单参考，独立于企业台账。 |

## 字段与使用

- `source_url` 指向发布页，`fetched` 是快照抓取日期，`date` 等业务日期沿用来源记录。`tags` 列出用途、文种或状态。
- `verified` 为布尔值。企业记录继承原库的 `honor_verified`，仅说明所列名单或称号的核实状态。其余三类原库未提供逐条核实标记，统一为 false。本次链接抽查独立记录于 PR。
- 文档保留标题、原文、类型及来源已有的附件或发布信息。企业只投影公开名称、行业、名单或称号、年份、发布者、报道标题和日期、来源类型及附件链接；未公开字段不补录。
- 在仓库根运行 `python3 scripts/data/build_real_supplement.py` 更新四份种子和原型脚本。`web/data/index.js` 通过本地脚本提供 `window.JK_REAL_SUPPLEMENT`，四个键与文件名同名（去掉扩展名）。页面无需网络。#6 管理主种子格式，#24 可按集合选择资料入库。

## 演示原型种子

- 演示台账、会议、公文模板与对话样本维护在 `demo.json`。24 家示例企业标记 `example: true`。示例信用代码使用正则 `^DEMO-E[0-9]{3}$`，后缀为企业 ID。运行 `python3 scripts/check_names.py` 可与公开企业名单比对。
- 政策事项维护在 `real-policies.json` 与 `policy-examples.json`。真实事项在 `source.url` 保留官网链接。无对应原文的样本单独标注，文号与来源留空。18 条 PI 及金额口径见 [政策种子官网复核](../../tests/demo-data/policy/official-review.md)。
- 知识库直接读取 `real-kb.json` 与 `kb-examples.json`，另从 `demo.json` 派生示例会议纪要和企业档案。
- 在仓库根运行 `python3 web/mock/build_mock.py` 重建 `web/config/mock-data.js`。原型沿用 `JK_DATA`、`JK_REAL`、`JK_REAL_KB`、`JK_KB_EXAMPLES`，可直接用 file:// 加载。

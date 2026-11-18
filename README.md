# jingkai-gov-platform
经开政务平台 (Jingkai Government Affairs Platform)

## 目录

- `prototype/v4/`：v4 综合版前端原型（静态 HTML/JS，mock 数据，`JK_CONFIG.api.mode` 切换 mock/http）及《接口规范》v1.3
- `docs/plan/`：里程碑与任务清单（定稿）、`issues.json`（Issue 批量创建源）
- `data/public/`：公开来源抓取的真实数据（经开区政务公开政策、企业、公文样例、规则、会议纪要）及核对报告
- `docs/audit/`：原型流程问题截图

开发流程：Issue → `feat/<issue号>-<slug>` 分支 → PR（`Closes #<issue号>`）→ 审核后合并到 main。

# 检查规则反例夹具

这里不是可运行的应用，是 `tests/test_check_rules.py` 的输入：通常每个目录只放一种问题（`bad-ui-all` 例外，见下），用来断言 `scripts/check.py` 能拦下并给出 `文件:行 [CHK-XXX-NN] 问题 → 改法`。

- 目录外层模拟仓库根：`apps/` + `CODEOWNERS`，测试把 `check.ROOT` 指到这里。
- `apps/no-manifest/` 只有一个占位文件（git 不跟踪空目录）。
- 界面规范反例是 `bad-ui-import`（入口不导入组件库）、`bad-ui-status`（自造状态词）、`bad-ui-class`（凭空 hk- 类名）；`good-ui` 是同规则正例。`bad-ui-all` 同时违反三条，只用于验证豁免到期后三条一起转红。类名判定需要真实 `core` 样式，相关测试会把样式复制到临时仓库根。
- 大于 2MB 的反例不落库（否则门会拦自己），由测试在临时目录生成。
- 这里的 `CODEOWNERS` 只服务夹具，不参与真实仓库的评审。
# 重设计 2.0 · 给模块 worker 的说明（lead，冻结）
风格：完全参考 multica.ai。先看 `DESIGN.md`（2.0）和 `/workspace/jk/style_ref/multica/`（notes.md + 截图，尤其 hero-2x.png / crop-*.png / scroll-2.png）。
令牌、组件、外壳已改好：`assets/theme.css`、`assets/ui.css`、`assets/shell.css`。**变量名与类名全部兼容 1.x**，你的模块不改也能跑，但要按下面重调到位。

## 变了什么
- **默认浅色**（白底）。存储键 `jk4-theme2`（测试台若写了 `jk4-theme` 请同步）。深色仍需同样好看。
- 外框：侧栏 #F3F3F4，主画布是白色浮起卡片。你的应用在白色画布里（`--bg` = #FFF）。
- **主按钮变黑**：`.btn.primary` = `--primary`（浅色 #18181B / 深色 #E4E4E7）。**不要**再用 `background:var(--accent)` 做按钮或大块填充；`--accent`（品牌蓝 #0070E3）只用于链接、进度条、选中描边、徽标数、焦点。
- **标签默认是“白底 + 细边 + 彩色圆点 + 黑字”**。`JK.tag()/ctx.ui.tag()` 不变；要淡色底用 `cls:'soft'`，只要点 + 灰字用 `cls:'plain'`，不要点用 `cls:'nodot'`。标签里放了 `.ico` 时自动不显示圆点。
- 图标块 `.app-ico`：白底细边，线条是应用身份色（`h-<hue>` 或 `--tf`）。
- 新令牌：`--canvas`（#FBFBFB 次级底：看板列 / 分组）、`--nav-on`、`--border-hover`、`--primary(-hover/-fg)`、`--ring`、`--shadow-menu`、`--fs-3xl`(36)、`--ctl-h-lg`(36)、`--track-tight/-display`、`--serif`。
- 字号：正文 14、控件 13、元信息 12；应用标题 20/500（`.app-head h2` 已处理）；大数字 `.kpi .v` 20/500。字重只用 400/500/600，**大字反而用 400/500**。
- 圆角：6 / 8 / 10 / 12；卡片 10，按钮 / 输入 8，弹窗 12。
- 阴影只有 3 档：`--shadow-1`（卡片 / 按钮 / 输入）、`--shadow-menu`、`--shadow-pop`。
- `.tabs` 选中下划线改黑色；`.seg` 变成浅灰胶囊容器；`.wiz-step.on` 黑色实心圆。
- `.toast` 两种主题都是深色浮条。`.modal/.drawer` 白色浮层；`.ov-b` 现在是 `flex column + gap:16px`（表单字段自动隔开，不用再写 margin）。
- `.select` 自绘箭头（`appearance:none`），高度 32。
- 菜单 `JK.menu(anchor, items)` 支持结构化项：`{v, label, desc, right(html), icon, lead(html 前缀，如 appIcon / 头像), on, disabled}`、`{head}`、`{sep:true}`，自动两行排版；**不要再往 `html` 里塞两行 div**。

## 常用类（ui.css）
`.btn` `.btn.primary|ghost|soft|brand|danger|pill|sm|lg|icon` · `.tag` `.tag.soft|plain|nodot|lg|pill` · `.card` `.card.flat|tight|ghost|hoverable|sel` `.card-h` `.card-f` · `.sect`（12px 灰色小节标题）· `.eyebrow`（等宽大写小标签，如“CHANGELOG”）· `.display`（36px 轻字）· `.kpi` · `.callout`（+ `h-<hue>` 变淡色）· `.list/.li` · `.tbl` · `.field/.input/.select/.textarea/.search/.check/.switch` · `.tabs/.tab` · `.seg` · `.wiz-steps/.wiz-foot` · `.plan` · `.empty` · `.tl/.tl-i(.on)` · `.cite/.src` · `.diff` · `.file/.drop` · `.bar` · `.skel` · `.avatar` · `.kbd` · `.count`

## Do
- 层级用 `--text / --text-2 / --text-3` + 字号字重 + `--border` 发丝线；区块之间留白 24。
- 列表 / 看板列用 `--canvas` 底 + 白卡片；卡片标题 14/500，下方元信息 12 灰。
- 一屏一个黑色主按钮；其余用默认白按钮或 `.ghost`。
- 两种主题、1280×800 与 1440×900 各截图自查：无重叠、无裁切、无溢出、选择框 / 按钮文字不换行。
- 截图放 `v4/screenshots/redesign-<模块>-<序号>-<light|dark>.png`。

## Don't
- 不写死色值（#xxx / rgb）；不用渐变；不用彩色大底块；不用 `--accent` 填充按钮。
- 不要粗体大标题（600 只给 ≤16px 的小标题）。
- 不要给卡片加重阴影或 2px 边框。
- 不改 `assets/*`、`config/tags.js`；需要新令牌 / 组件请写 `CONTRACT_REQUESTS.md`（标 [redesign]）。

## 13:20 补充（lead 审查后）
- 吐司（toast）改为**顶部居中**（top:56px），不再盖住底部输入框 / 面板底栏主按钮。
- 分屏时对话列 `clamp(320px,27vw,420px)`，1280 下右侧面板约 680px 宽：模块内容请按 ≥640px 宽设计，表格外层用 `.card flat` + `overflow:auto`。
- ≤1360px 时 `.tbl` 单元格左右内边距自动收为 8px。
- `.bar-row` 标签列可伸缩（最多 128px），条形最少 60px。

## 13:50 · 2.2 multica 对齐（必读）
- 字重上限 500（`--fw-b` 已改 500）。不要写 `font-weight:600/700`，也不要用 `<b>` 期待粗体。
- 字体已自带（assets/fonts），不要在模块里改 font-family。
- 一串结果/条目请放进 `<div class="stack rows">`：自动变成一张卡里的发丝线行（政策兑现已改）。**kb / skills / computer 的 worker：你们的条目列表请同样加 `rows` 类**（我没动你们的文件）。
- 分组标题用 `.sect`（壳）或 `.APP .sec`（模块）：现在是浅灰圆角条。
- 选中卡片 = `.card.sel`（品牌蓝描边）。
- 14:05：外壳新增左侧图标竖栏 `.rail`（data-op `rail.*`），侧栏 216px；toast 右上角；`.rows` 已移到 ui.css（7 个模块都能用）。

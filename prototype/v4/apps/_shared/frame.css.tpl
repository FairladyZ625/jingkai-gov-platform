/* ==== 应用通用框架 2.0（multica 风格；由 apps/_shared/frame.css.tpl 生成，改模板后运行 node apps/_shared/build-css.js） ==== */
/* .APP 本身不加样式：抽屉/弹窗里也会复用 .app-<id> 前缀。.ap 是容器（container: ap），窄面板（对话分栏）下自动收紧 */
.APP .ap{max-width:880px;margin:0 auto;padding:var(--s6) clamp(16px,4.5%,40px) 0;min-height:100%;display:flex;flex-direction:column;container:ap/inline-size}
.APP .ap-h{display:flex;align-items:center;gap:var(--s3);min-height:40px}
.APP .ap-h h2{font-size:var(--fs-xl);font-weight:var(--fw-m);letter-spacing:var(--track-tight);line-height:1.25}
.APP .ap-sum{font-size:var(--fs-sm);color:var(--text-3);margin-top:2px;line-height:1.4}
.APP .ap-tabs{margin:var(--s4) 0 var(--s6)}
.APP .ap-body{flex:1;display:flex;flex-direction:column;min-width:0}
.APP .wiz-steps{margin-bottom:var(--s6)}
.APP .wiz-step[data-step]{cursor:pointer}
.APP .wiz-step[data-step]:hover{color:var(--text)}
.APP .wiz-body{max-width:none;min-width:0}
.APP .wiz-foot{margin-top:auto;padding-top:var(--s3);padding-bottom:var(--s4)}
.APP .wiz-body{padding-bottom:var(--s6)}
.APP .q{font-size:var(--fs-lg);font-weight:var(--fw-b);letter-spacing:var(--track-tight);line-height:1.35;margin-bottom:4px}
.APP .q-sub{font-size:var(--fs-sm);color:var(--text-3);margin-bottom:var(--s5);line-height:1.5}
.APP .stack{display:flex;flex-direction:column;gap:var(--s4)}
.APP.stack{display:flex;flex-direction:column;gap:var(--s5)}
.APP.stack .sec{margin:0 0 var(--s2)}
.APP.stack>div>.meta:first-child{margin-bottom:2px}
.APP .meta{font-size:var(--fs-xs);color:var(--text-3);line-height:1.5}
.APP .big{font-size:var(--fs-2xl);font-weight:var(--fw-m);letter-spacing:var(--track-tight);font-variant-numeric:tabular-nums;line-height:1.1}
/* 指标卡：数字黑色，颜色只在标签前的小圆点 */
.APP .kpis{display:grid;grid-template-columns:repeat(var(--n,3),minmax(0,1fr));gap:var(--s3)}
.APP .kpi-c{display:flex;flex-direction:column;gap:6px;padding:var(--s4);border:1px solid var(--border-strong);border-radius:var(--r-lg);background:var(--surface);box-shadow:var(--shadow-1);cursor:pointer;text-align:left;font:inherit;color:inherit;transition:border-color var(--dur),background var(--dur)}
.APP .kpi-c:hover{border-color:var(--border-hover)}
.APP .kpi-c .v{font-size:var(--fs-2xl);font-weight:var(--fw-m);letter-spacing:var(--track-tight);color:var(--text);font-variant-numeric:tabular-nums;line-height:1}
.APP .kpi-c .l{display:flex;align-items:center;gap:6px;font-size:var(--fs-xs);color:var(--text-2);line-height:1.3}
.APP .kpi-c .l::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--tf,var(--text-3));flex:none}
.APP .kpi-c.on{border-color:var(--accent-line);box-shadow:0 0 0 1px var(--accent-line)}
.APP .pick{position:relative}
.APP .dd{position:absolute;left:0;right:0;top:calc(100% + 4px);z-index:20;padding:4px;border-radius:var(--r-lg);background:var(--surface-3);border:1px solid var(--border);box-shadow:var(--shadow-menu);max-height:340px;overflow:auto}
.APP .dd .mi{display:flex;align-items:center;gap:10px;min-height:44px;padding:6px 10px;border-radius:6px;cursor:pointer}
.APP .dd .mi:hover,.APP .dd .mi.on{background:var(--hover)}
/* 首字母头像：白底细边，字用类别色 */
.APP .ini{width:32px;height:32px;border-radius:var(--r-md);display:grid;place-items:center;font-weight:var(--fw-b);font-size:var(--fs-sm);flex:none;background:var(--surface);color:var(--tf,var(--text-2));border:1px solid var(--border-strong);box-shadow:var(--shadow-1)}
.APP .ini .ico{width:16px;height:16px}
.APP .ini.lg{width:40px;height:40px;font-size:var(--fs-lg);border-radius:var(--r-lg)}
.APP .ini.sm{width:24px;height:24px;font-size:11px;border-radius:50%;box-shadow:none}
.APP .chips{display:flex;flex-wrap:wrap;gap:var(--s2)}
.APP .chip-btn{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:var(--r-md);border:1px solid var(--border-strong);background:var(--surface);color:var(--text-2);font-size:var(--fs-sm);cursor:pointer;box-shadow:var(--shadow-1);white-space:nowrap;transition:border-color var(--dur),background var(--dur)}
.APP .chip-btn:hover{border-color:var(--border-hover);color:var(--text)}
.APP .chip-btn.on{background:var(--active);border-color:var(--border-hover);color:var(--text);font-weight:var(--fw-m);box-shadow:none}
.APP .ck{width:18px;height:18px;border-radius:50%;display:inline-grid;place-items:center;flex:none;font-size:11px;font-weight:var(--fw-b);background:var(--tg);color:var(--tf);border:1px solid var(--tb)}
.APP .ck-row{display:flex;align-items:flex-start;gap:10px;padding:5px 0;font-size:var(--fs-sm);line-height:1.5}
.APP .ck-row .ck{margin-top:1px}
.APP .times{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--s2)}
.APP .times>div{padding:var(--s2) var(--s3);border-radius:var(--r-md);background:var(--canvas);border:1px solid var(--border);font-size:var(--fs-sm)}
.APP .times b{display:block;font-size:var(--fs-xs);color:var(--text-3);font-weight:var(--fw-m)}
.APP .fold{border-top:1px solid var(--border);margin-top:var(--s3);padding-top:var(--s3)}
.APP .link{color:var(--accent);cursor:pointer;font-size:var(--fs-sm);background:none;border:0;padding:0;display:inline-flex;align-items:center;gap:4px}
.APP .link:hover{text-decoration:underline;text-underline-offset:2px}
.APP .link .ico{width:13px;height:13px}
.APP .quote{padding:var(--s3) var(--s4);border-left:2px solid var(--border-hover);background:var(--canvas);border-radius:0 var(--r-md) var(--r-md) 0;font-size:var(--fs-sm);line-height:1.8;color:var(--text)}
.APP .lock-note{display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);color:var(--text-2)}
.APP .err-box{padding:var(--s6);text-align:center;color:var(--text-2)}
.APP .skel-list{display:flex;flex-direction:column;gap:var(--s3)}
.APP .skel-list .skel{height:60px;border-radius:var(--r-lg)}
.APP .sec{display:flex;align-items:center;gap:var(--s2);font-size:var(--fs-xs);font-weight:var(--fw-m);color:var(--text-3);margin:var(--s6) 0 var(--s2);line-height:20px}
.APP .row-click{cursor:pointer}
.APP .num{font-variant-numeric:tabular-nums}
.APP .muted-tag{color:var(--text-3)}
.APP .cb{width:15px;height:15px;accent-color:var(--primary);flex:none;cursor:pointer}
.APP tr.click{cursor:pointer}
/* 窄面板（对话分栏 ≤ 640px）：向导只显示当前步文字，指标卡收紧 */
@container ap (max-width:640px){
  .APP .wiz-step:not(.on){font-size:0;gap:0}
  .APP .wiz-step:not(.on) .n{font-size:11px}
  .APP .kpis{gap:var(--s2)}
  .APP .kpi-c{padding:var(--s3)}
  .APP .kpi-c .v{font-size:var(--fs-xl)}
  .APP .times{grid-template-columns:1fr}
}

/* 列表两行：标题 .t + 元信息 .s */
.APP .li .t{font-size:var(--fs-md);font-weight:var(--fw-m);color:var(--text);line-height:1.45;min-width:0}
.APP .li .s{font-size:var(--fs-xs);color:var(--text-3);line-height:1.5;margin-top:1px;min-width:0}
.APP .li .s .link{font-size:inherit}

/* ==== 2.2 multica 对齐：分组标题条、卡片列表改发丝线行、字重 ≤500 ==== */
.APP .q{font-weight:var(--fw-m)}
.APP .kpi-c .v{font-weight:var(--fw-n)}
.APP .kpi-c.on{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.APP .ini{font-weight:var(--fw-m)}
.APP .ck{font-weight:var(--fw-m)}
.APP .chip-btn{border-radius:var(--r-pill)}
.APP .sec{height:32px;margin:var(--s5) 0 var(--s1);padding:0 var(--s3);border-radius:var(--r-md);background:var(--fill);color:var(--text-2);font-size:var(--fs-sm)}

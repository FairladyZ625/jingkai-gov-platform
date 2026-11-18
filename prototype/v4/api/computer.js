/* =====================================================================
 * 接口适配 · 电脑操作（Computer Use）。界面只调这里。
 * 实体 CuRun = { id, task, title, ent:{id,short}|null, system:{name,url}, status: running|paused|manual|waiting|done|draft|stopped|failed,
 *               step, created, by, from, steps:[{title, page, url?, human?: 'otp'|'gate'|'import', ops:[{op, sel, value, mask, note, kind}]}],
 *               fields?, notice?, notices?, apps?, log:[{at,text,who}], shots:[html], result }
 * 敏感值（信用代码、手机号、密码）由服务端打码后下发；截图里也只有打码值。
 * ===================================================================== */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  window.JKApi.computer = {
    /** → {items: Task[], systems: System[]} */ tasks: () => H.get('/api/apps/computer/tasks'),
    /** {allowed} → {item: System}  允许/停止 AI 使用某系统账号 */ setSystem: (id, allowed) => H.patch('/api/apps/computer/systems/' + id, { allowed }),
    /** {text} → {task: Task|null, entId}  一句话识别任务 */ match: (text) => H.post('/api/apps/computer/match', { text }),
    /** → {items: CuRun[]}（不含截图） */ runs: () => H.get('/api/apps/computer/runs'),
    /** → {item: CuRun}（含截图与日志） */ run: (id) => H.get('/api/apps/computer/runs/' + id),
    /** {task, ent?, month?, from?} → {item: CuRun}  生成操作计划 */ start: (b) => H.post('/api/apps/computer/runs', b),
    /** {step?, status?, log?, who?, shot?, shotIdx?} → {item}  每步回报（写审计） */ report: (id, b) => H.patch('/api/apps/computer/runs/' + id, b),
    /** {decision:'approve'|'decline', kind} → {item}  人工确认 提交/签章/付款 */ confirm: (id, b) => H.post(`/api/apps/computer/runs/${id}/confirm`, b),
  };
})();

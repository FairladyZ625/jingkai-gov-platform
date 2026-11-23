/* =====================================================================
 * 【可改】平台级“说一句就办”的意图（应用里的意图写在各应用 manifest.intents）。
 * 字段：examples 例句（越像越容易命中）、keywords 关键词、plan 任务清单（≤5 步）、
 *       run(slots, run, hooks) 执行函数；confirm:true 先问“我理解为…，要这样做吗？”
 * ===================================================================== */
window.JK_PLATFORM_INTENTS = [
  { id: 'open-app', title: '打开应用', examples: ['打开政策兑现', '进入会议记录', '去知识库看看', '打开技能中心'], keywords: ['打开', '进入', '切到'], plan: ['找到应用', '打开'],
    run: async (s, run, hk) => {
      const def = Object.values(JK.registry).find((d) => [d.manifest.name, d.manifest.short, d.manifest.id].some((n) => n && s.text.includes(n))) || Object.values(JK.registry).find((d) => s.text.includes(d.manifest.name.slice(0, 2)));
      if (!def) return run.done('没找到这个应用。左侧“应用”里可以直接点开。');
      await run.step(1); await hk.openApp(def.manifest.id); run.done(`已打开「${def.manifest.name}」。`, (def.manifest.starters || []).slice(0, 2).map((t) => ({ label: t, say: t })));
    } },
  { id: 'inbox', title: '打开收件箱', examples: ['看看有什么要我审签的', '打开收件箱', '我有哪些待办'], keywords: ['收件箱', '要我审', '待我', '审签', '待办事项'], plan: ['打开收件箱', '列出待我处理'],
    run: async (s, run, hk) => { await hk.openBuiltin('inbox'); await run.step(1); const n = hk.inboxCount(); run.done(n ? `有 **${n} 件**等你处理，已在右侧列出。` : '收件箱是空的，暂时没有要你处理的事。'); } },
  { id: 'admin-user', title: '新增账号', examples: ['帮我新增一个账号', '给新同事开个账号', '停用许平的账号'], keywords: ['账号', '开户', '新同事', '停用'], plan: ['打开管理后台', '进入账号管理', '填写信息', '等你确认'], needsAdmin: true,
    run: async (s, run, hk) => { await hk.openBuiltin('admin', 'users'); await run.step(1); await run.click('[data-op="admin.add-user"]'); await run.step(2);
      await run.fill('[data-op="admin.u-name"]', '张晓'); await run.fill('[data-op="admin.u-username"]', 'zhangxiao'); await run.select('[data-op="admin.u-role"]', 'member');
      await run.step(3); const a = await run.ask('账号信息已填好（张晓 · 经办人员），确认创建吗？', ['确认创建', '先不建']);
      if (a !== '确认创建') return run.done('好的，没有创建。表单保留在右侧。');
      await run.click('[data-op="admin.u-save"]'); await run.wait('[data-op="admin.u-created"]', 8000);
      run.done('已创建账号 **zhangxiao**。口令请在结果弹窗手动查看，不在对话中显示。'); } },
  { id: 'admin-grant', title: '调整权限', examples: ['外部协作者能看哪些应用', '给外部协作者开放知识库', '调整角色权限'], keywords: ['权限', '授权', '能看哪些'], plan: ['打开管理后台', '进入角色与授权', '定位到对应角色'], needsAdmin: true,
    run: async (s, run, hk) => { await hk.openBuiltin('admin', 'grants'); await run.step(1); await run.step(2); await run.highlight('[data-op="admin.grant-partner"]', '外部协作者这一列'); run.done('这一列是外部协作者的授权：点“查/操”即刻生效，并写入审计。'); } },
  { id: 'audit', title: '查看审计日志', examples: ['看看最近谁改了台账', '打开审计日志', '操作留痕'], keywords: ['审计', '留痕', '谁改了', '操作记录'], plan: ['打开管理后台', '进入审计日志'], needsAdmin: true,
    run: async (s, run, hk) => { await hk.openBuiltin('admin', 'audit'); await run.step(1); run.done('已打开审计日志，可按人/应用筛选并导出 CSV。'); } },
  { id: 'model', title: '切换模型', examples: ['换成 DeepSeek', '用通义千问回答', '切换到本地模型', '用 Kimi'], keywords: ['换成', '切换到', '模型', '用通义', '用豆包', '用Kimi', '用 Kimi', '用DeepSeek', '用文心', '用智谱'], plan: ['识别模型', '切换'],
    run: async (s, run, hk) => { await run.step(1); const m = await hk.setModel(s.text); run.done(m ? `已切换到 **${m.name}**。之后的回答都由它生成（敏感数据仍自动走本地模型）。` : '没找到这个模型。点顶部模型名可以看全部可用模型。'); } },
  { id: 'theme', title: '切换主题', examples: ['换成浅色', '切换深色模式', '亮色主题'], keywords: ['浅色', '亮色', '深色', '暗色', '白色主题', '黑色主题'], plan: ['切换主题'],
    run: async (s, run, hk) => { const t = /浅|亮|白/.test(s.text) ? 'light' : 'dark'; hk.setTheme(t); run.done(`已切换为${t === 'light' ? '浅色' : '深色'}。`); } },
  { id: 'role', title: '切换视角', examples: ['切换到领导视角', '用外部协作者看看', '切到管理员'], keywords: ['视角', '切换到领导', '外部协作者', '切到管理员', '换个账号'], plan: ['切换账号', '刷新权限'],
    run: async (s, run, hk) => { const u = /外部|协作/.test(s.text) ? 'hejun' : /管理员/.test(s.text) ? 'admin' : /领导|审签/.test(s.text) ? 'liyang' : 'wangmin'; await run.step(1); await hk.switchUser(u); } },
  { id: 'help', title: '我能做什么', examples: ['你能做什么', '怎么用', '帮助'], keywords: ['你能做什么', '怎么用', '帮助', '能干什么'], plan: ['整理能力清单'],
    run: async (s, run, hk) => { run.done(hk.helpText(), hk.helpNext()); } },
  { id: 'demo', title: '一键演示', examples: ['演示一遍', '一键演示', '给我演示所有功能'], keywords: ['演示'], plan: ['准备演示'],
    run: async (s, run, hk) => { run.done('好，开始一键演示。'); setTimeout(() => hk.startDemo(), 300); } },
  { id: 'reset', title: '重置演示数据', examples: ['重置演示数据', '恢复初始数据'], keywords: ['重置', '恢复初始'], plan: ['等你确认', '重置数据'],
    run: async (s, run, hk) => { const a = await run.ask('会清空本机所有修改（新增的账号、走访、公文等），确认重置吗？', ['确认重置', '取消']); if (a !== '确认重置') return run.done('已取消。'); await run.step(1); await hk.reset(); } },
];

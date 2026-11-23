/* 最小应用骨架（复制到 apps/<id>/ 后改 id）。遵守 APP_CONTRACT：界面只调 ctx.api，颜色只用变量/色槽。 */
JK.registerApp({
  manifest: {
    id: 'demo', name: '示例应用', short: '示例', icon: 'cube', version: '0.1.0', summary: '一句话说明',
    routes: ['home'], perms: { view: '查看', operate: '操作' },
    intents: [{ id: 'demo.hello', examples: ['打开示例应用打个招呼'], keywords: ['示例', '招呼'], action: 'hello', plan: ['打开示例应用', '填写名字', '提交'] }],
    starters: ['打开示例应用打个招呼'],
  },
  mount(el, ctx) {
    el.innerHTML = `<div class="app-head">${ctx.ui.appIcon('demo', 'lg')}<div><h2>示例应用</h2><div class="sub">一句话说明</div></div><span class="sp"></span><button class="btn primary" data-op="demo.go">提交</button></div>
      <div class="card"><div class="field"><label>名字</label><input class="input" data-op="demo.name" placeholder="输入名字"></div><div class="out t-2" style="margin-top:12px"></div></div>`;
    const go = () => { el.querySelector('.out').innerHTML = '你好，' + ctx.ui.esc(el.querySelector('[data-op="demo.name"]').value) + ' ' + ctx.ui.tag('已完成'); ctx.ui.toast('已提交'); };
    el.querySelector('[data-op="demo.go"]').onclick = go;
    return {
      go() {},
      actions: {
        async hello(slots, run) {
          await run.step(1); await run.fill('[data-op="demo.name"]', ctx.user.name);
          await run.step(2); if (!(await run.ask('确认提交吗？', ['提交', '先不提交'])).startsWith('提交')) return run.done('已取消');
          await run.click('[data-op="demo.go"]'); run.done('已完成打招呼');
        },
      },
    };
  },
});

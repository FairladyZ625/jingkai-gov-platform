// 冻结，勿改；改了说明你破坏了兼容。只调用 SDK 1.0。
import { h, steps, uploadArea, table, button, badge, v1 } from '/sdk/haiknow.js';

export async function mount(el, ctx) {
  const [identity, projects] = await Promise.all([v1.me(), v1.projects()]);
  await Promise.all([v1.reviews(), v1.notifications()]);
  el.append(h('h3', {}, ctx.app.name), badge(identity.name), steps(['录入', '确认'], 0),
    table([{ title: '记录', key: 'id' }], (await ctx.records.list()).items),
    uploadArea({ onFile: (file) => ctx.upload('/legacy', file) }),
    button('保存', async () => {
      const file = await ctx.dataFiles.save(new File(['sdk1'], '兼容.txt'), 'sample-project', '兼容测试');
      await ctx.dataFiles.get(file.fileId);
      ctx.dataFiles.url(file.fileId);
      const record = await ctx.records.save({ project: 'sample-project', type: 'sample', data: {}, files: [file.fileId] });
      await ctx.records.get(record.id, 1);
      await ctx.records.save({ baseVersion: 1, data: {} }, record.id);
      await ctx.reviews.submit(record.id, 2, 'samplereviewer');
      ctx.toast('已保存');
    }, { disabled: !ctx.can('operate') }),
    h('a', { href: ctx.url('/records') }, '应用接口'));
  await ctx.api('/context');
  await ctx.artifacts.find();
  await ctx.reviews.list();
  const notes = await ctx.notifications.list();
  if (notes.items[0]) await ctx.notifications.read(notes.items[0].id);
  // decide 在换人确认后调用，不能自己确认自己；完整行为见 Python 夹具流程。
  el.dataset.projects = JSON.stringify(projects);
}

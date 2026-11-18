import { ensureStyles, h, PageHeader, WorkbenchLayout } from '/sdk/ui/index.js';

export async function mount(el, ctx) {
  ensureStyles();
  el.replaceChildren(
    WorkbenchLayout({
      header: PageHeader({
        title: '公文协作',
        description: '按模板起草、保存版本，定稿后锁定。',
      }),
      main: h('p', {}, '请从对话或接口发起起草。完整编辑界面将在后续任务接入。'),
    }),
  );
}

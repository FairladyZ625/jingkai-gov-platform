// 正例：入口从 /sdk/ui/index.js 导入组件，状态走 StatusTag，类名都在 ui.css 里。
import { h, PageHeader, Card, StatusTag, EmptyState } from '/sdk/ui/index.js';

export async function mount(el) {
  el.append(
    PageHeader({ title: '界面规范正例' }),
    Card({ title: '状态', children: [StatusTag({ status: '待确认' })] }),
    EmptyState({ title: '暂无记录', description: '先新建一条' }),
    h('div', { class: 'hk-panel hk-stack-sm' }, '内容'),
  );
}
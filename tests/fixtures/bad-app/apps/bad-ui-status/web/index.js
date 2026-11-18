// 反例：状态映射表里出现五个固定业务状态之外的词；toast 的“已导出 CSV”不算状态标签。
import { h, badge, StatusTag } from '/sdk/ui/index.js';

const STATUS = { draft: '草稿', pending: '待审核', done: '已完结', returned: '已退回' };

export async function mount(el, ctx) {
  ctx.toast('已导出 CSV');
  el.append(h('div', {}, badge(STATUS[ctx.status] || '草稿'), StatusTag({ status: '已完结' })));
}
// 反例：入口只用 /sdk/haiknow.js 手搓页面，没有从 /sdk/ui/index.js 导入组件。
import { h, table, button, badge } from '/sdk/haiknow.js';

export async function mount(el, ctx) {
  el.append(h('div', {}, table([], []), button('保存'), badge('草稿')));
}
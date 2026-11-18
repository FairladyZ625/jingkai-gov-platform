// 反例：同时违反 CHK-APP-15/16/17，用于验证豁免到期后三条规则都会转红。
import { h, badge } from '/sdk/haiknow.js';

export async function mount(el) {
  el.append(h('div', { class: 'hk-card' }, badge('待审核')));
}
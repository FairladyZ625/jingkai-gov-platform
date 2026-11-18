// 反例：hk-card / hk-row 只在存量 SDK1 兼容块里，新应用不能继续手写；hk-field 在 ui.css 里有定义。
import { Card, h } from '/sdk/ui/index.js';

export async function mount(el) {
  el.append(h('div', { class: 'hk-card hk-row hk-field' }, Card({ title: '示例' })));
}
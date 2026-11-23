// 反例：颜色字面量与内联样式。颜色只能用 var(--hk-*) 设计令牌。
const template = '<div style="color:#fff">卡片</div>';
const tone = 'rgb(0, 0, 0)';
const inline = { style: 'color:red' };

export async function mount(el) {
  el.innerHTML = template + tone + inline.style;
}
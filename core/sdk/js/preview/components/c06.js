// C06 资料汇编前端：只显示后端 Render 的结果，不复制模板填充与版本比对规则。
import { h, badge } from '/sdk/haiknow.js';

export const VERSION = '1.0.0';

// 预览成品。render.html 由 Python 端 C06 生成：模板是应用代码、值已统一转义；
// 应用必须确认传入的是本组件返回的 Render，不能把用户输入直接交给 innerHTML。
export function c06Preview(render, { withCitations = true } = {}) {
  if (!render) return h('p', { class: 'muted' }, '还没有生成资料');
  const body = h('div', { class: 'c06-body' });
  body.innerHTML = render.html || '';
  // 卡片外壳由 WorkbenchLayout/Card 提供；这里再套 hk-card 会形成面板内嵌卡片。
  const box = h('div', { class: 'c06-preview' }, body);
  if (withCitations && render.citation_html) {
    const details = h('details', {},
      h('summary', {}, '引用清单'),
      h('div', { class: 'c06-citations' }));
    details.lastChild.innerHTML = render.citation_html;
    box.append(details);
  }
  return box;
}

// 缺件与引用改版提示；应用据此决定是否允许出正式稿。
export function c06Missing(render) {
  if (!render) return h('p', { class: 'muted' }, '还没有生成资料');
  const missing = render.missing || [];
  const stale = render.stale || [];
  if (missing.length === 0 && stale.length === 0) {
    return h('p', { class: 'hk-note' },
      badge('齐全', 'ok'),
      ' 必填槽位齐全，引用版本一致，可以出正式稿。');
  }
  return h('div', {},
    missing.length
      ? h('p', {}, badge(`缺件 ${missing.length}`, 'bad'), ' ', missing.join('、'))
      : null,
    stale.length
      ? h('p', {}, badge(`改版 ${stale.length}`, 'warn'), ' ',
          stale.map((item) => `${item.key}：引用 v${item.cited} → 当前 v${item.current}`).join('；'))
      : null,
    h('p', { class: 'muted small' }, '存在缺件或引用改版，不能出正式稿；补齐后再生成。'));
}
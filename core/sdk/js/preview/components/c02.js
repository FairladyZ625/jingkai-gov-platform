// C02 文档审查前端：显示后端匹配出的提示、原文定位与人工处理记录，不复制匹配规则。
import { h, badge, table } from '/sdk/haiknow.js';
import { issueMessage } from '/sdk/preview/errors.js';

export const VERSION = '1.0.0';

const STATUS_TONES = { 待审: 'warn', 采纳: 'ok', 改判: 'warn', 驳回: '', 无依据: 'bad' };
const RISK_TONES = { 高: 'bad', 中: 'warn', 低: '' };

function statusTone(status) {
  return STATUS_TONES[status] ?? '';
}

function riskTone(risk) {
  return RISK_TONES[risk] ?? '';
}

function text(value) {
  return value == null || value === '' ? '—' : String(value);
}

// 状态汇总：待审、无依据和已处理各多少条。
export function c02Summary(review) {
  if (!review) return h('p', { class: 'muted' }, '还没有审查结果');
  const counts = review.byStatus || {};
  const hints = review.hints || [];
  const errors = review.errors || [];
  return h('p', {},
    hints.length ? badge(`提示 ${hints.length}`, hints.length ? 'warn' : 'ok') : badge('没有提示', 'ok'), ' ',
    Object.entries(counts)
      .filter(([, count]) => count > 0)
      .map(([status, count]) => badge(`${status} ${count}`, statusTone(status))), ' ',
    errors.length ? badge(`问题 ${errors.length}`, 'bad') : null);
}

// 提示清单：每条都带规则、条款原文与定位、等级、依据、建议、状态和处理记录。
export function c02Hints(review) {
  const hints = (review && review.hints) || [];
  if (hints.length === 0) return h('p', { class: 'muted' }, '本轮没有命中任何规则。');
  return table([
    { title: '规则', render: (row) => h('div', {}, h('strong', {}, row.rule), h('div', { class: 'muted small' }, row.condition)) },
    { title: '条款定位', render: (row) => h('div', {}, text(row.locator), row.page ? h('div', { class: 'muted small' }, `第 ${row.page} 页`) : null) },
    { title: '条款原文', key: 'text' },
    { title: '等级', render: (row) => (row.risk ? badge(row.risk, riskTone(row.risk)) : h('span', { class: 'muted' }, '未定级')) },
    { title: '依据出处', render: (row) => (row.basis ? row.basis : h('span', { class: 'muted' }, '无依据')) },
    { title: '建议', render: (row) => text(row.suggestion) },
    { title: '状态', render: (row) => h('div', {}, badge(row.status, statusTone(row.status)), row.note ? h('div', { class: 'muted small' }, row.note) : null) },
    { title: '处理记录', render: (row) => (row.reviewer ? `${row.reviewer}${row.reason ? `：${row.reason}` : ''}` : '—') },
  ], hints);
}

// 被跳过的规则与问题：模型辅助关掉时，没有确定性条件的规则会在这里说明原因。
export function c02Skipped(review) {
  const skipped = (review && review.skipped) || [];
  const errors = (review && review.errors) || [];
  if (skipped.length === 0 && errors.length === 0) return null;
  return h('details', {},
    h('summary', {}, `未参与匹配的规则 ${skipped.length} 条，问题 ${errors.length} 条`),
    skipped.length
      ? table([
          { title: '规则', key: 'rule' },
          { title: '原因', key: 'reason' },
        ], skipped)
      : null,
    errors.length
      ? h('ul', {}, errors.map((issue) => h('li', {}, badge(issueMessage(issue.code), 'bad'), ' ', issue.message)))
      : null);
}

// 人工处理表单：采纳 / 改判 / 驳回。组件不提交，交给应用传进来的 onSubmit。
export function c02Decide(review, onSubmit) {
  const hints = (review && review.hints) || [];
  const hintSelect = h('select', { name: 'hint' },
    hints.map((hint) => h('option', { value: hint.id }, `${hint.rule} · ${hint.locator || hint.clause}`)));
  const statusSelect = h('select', { name: 'status' },
    h('option', { value: '采纳' }, '采纳'),
    h('option', { value: '改判' }, '改判'),
    h('option', { value: '驳回' }, '驳回'));
  const riskSelect = h('select', { name: 'risk' },
    h('option', { value: '' }, '改判时选新等级'),
    h('option', { value: '高' }, '高'),
    h('option', { value: '中' }, '中'),
    h('option', { value: '低' }, '低'));
  const reviewer = h('input', { name: 'reviewer', placeholder: '处理人' });
  const reason = h('textarea', { name: 'reason', rows: 2, placeholder: '改判或驳回必须写理由' });
  const form = h('form', { class: 'c02-decide' },
    h('div', { class: 'hk-row' },
      h('label', {}, '提示', hintSelect),
      h('label', {}, '处理', statusSelect),
      h('label', {}, '改判等级', riskSelect)),
    h('div', { class: 'hk-row' },
      h('label', {}, '处理人', reviewer),
      h('label', {}, '理由', reason)),
    h('div', { class: 'hk-row' },
      h('button', { class: 'hk-btn primary', type: 'submit', disabled: hints.length === 0 }, '记录处理')));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!onSubmit) return;
    onSubmit({
      hintId: hintSelect.value,
      status: statusSelect.value,
      risk: riskSelect.value,
      reviewer: reviewer.value,
      reason: reason.value,
    });
  });
  return form;
}
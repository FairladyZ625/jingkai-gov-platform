// C07 内容制作和审核前端：显示素材使用权、成果版本、修改意见与审核动作，不重算权限。
import { h, badge, table } from '/sdk/haiknow.js';
import { issueMessage } from '/sdk/preview/errors.js';

export const VERSION = '1.0.0';

const RIGHTS_TONES = { 有: 'ok', 无: 'bad', 待确认: 'warn' };
const STATUS_TONES = { 待审: 'warn', 通过: 'ok', 退回: 'bad' };

function rightsTone(rights) {
  return RIGHTS_TONES[rights] ?? '';
}

function statusTone(status) {
  return STATUS_TONES[status] ?? '';
}

function text(value) {
  return value == null || value === '' ? '—' : String(value);
}

function outputText(output) {
  if (output == null || output === '') return '—';
  if (typeof output === 'string') return output;
  if (Array.isArray(output)) {
    return output.map((item) => (item && (item.url || item.text || item.id)) || JSON.stringify(item)).join('、');
  }
  return JSON.stringify(output);
}

// 素材清单：版本、来源与使用权一眼可见，没有使用权的素材用红色标记。
export function c07Assets(assets) {
  const rows = assets || [];
  if (rows.length === 0) return h('p', { class: 'muted' }, '还没有素材');
  return table([
    { title: '素材', render: (row) => row.name || row.id },
    { title: '版本', key: 'version' },
    { title: '来源', render: (row) => text(row.source) },
    { title: '使用权', render: (row) => badge(row.rights, rightsTone(row.rights)) },
  ], rows);
}

// 制作任务检查：错误阻断生成，待确认只提示“只能出草稿”。
export function c07Checks(prepared) {
  if (!prepared) return null;
  const errors = prepared.errors || [];
  const warnings = prepared.warnings || [];
  return h('div', {},
    h('p', {},
      prepared.ok ? badge('素材检查通过', 'ok') : badge(`问题 ${errors.length}`, 'bad'), ' ',
      warnings.length ? badge(`待确认 ${warnings.length}`, 'warn') : null),
    errors.length
      ? h('ul', {}, errors.map((issue) => h('li', {}, badge(issueMessage(issue.code), 'bad'), ' ', issue.message)))
      : null,
    warnings.length
      ? h('ul', {}, warnings.map((issue) => h('li', {}, badge(issueMessage(issue.code), 'warn'), ' ', issue.message)))
      : null);
}

// 成果版本：版本号、审核状态、引用素材、参数、修改意见数和输出。
export function c07Versions(versions) {
  const rows = versions || [];
  if (rows.length === 0) return h('p', { class: 'muted' }, '还没有成果版本');
  return table([
    { title: '版本', render: (row) => row.id },
    { title: '状态', render: (row) => badge(row.status, statusTone(row.status)) },
    { title: '引用素材', render: (row) => (row.assets || []).map((ref) => `${ref.id} v${ref.version}`).join('、') || '—' },
    { title: '生成参数', render: (row) => JSON.stringify(row.params || {}) },
    { title: '修改意见', render: (row) => (row.comments || []).length },
    { title: '输出', render: (row) => outputText(row.output) },
    { title: '审核记录', render: (row) => (row.reviewer ? `${row.reviewer}${row.reason ? `：${row.reason}` : ''}` : '—') },
  ], rows);
}

// 修改意见列表。
export function c07Comments(version) {
  const items = (version && version.comments) || [];
  if (items.length === 0) return h('p', { class: 'muted' }, '还没有修改意见');
  return table([
    { title: '意见', key: 'id' },
    { title: '提出人', key: 'author' },
    { title: '内容', key: 'text' },
    { title: '时间', render: (row) => text(row.at) },
  ], items);
}

// 追加修改意见；onSubmit 接收 {text}，由应用补当前版本与当前用户。
export function c07CommentForm(version, onSubmit) {
  const input = h('textarea', { name: 'text', rows: 2, placeholder: '写明要改哪里、改成什么' });
  const form = h('form', { class: 'c07-comment' },
    h('div', { class: 'hk-row' }, h('label', {}, '修改意见', input)),
    h('div', { class: 'hk-row' },
      h('button', { class: 'hk-btn', type: 'submit', disabled: !version }, '提交修改意见')));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (onSubmit) onSubmit({ text: input.value });
  });
  return form;
}

// 审核：通过或退回；退回必须写理由。onSubmit 接收 {status, reason}。
export function c07ReviewForm(version, onSubmit) {
  const status = h('select', { name: 'status' },
    h('option', { value: '通过' }, '通过'),
    h('option', { value: '退回' }, '退回'));
  const reason = h('textarea', { name: 'reason', rows: 2, placeholder: '退回必须写理由；通过可留空' });
  const form = h('form', { class: 'c07-review' },
    h('div', { class: 'hk-row' }, h('label', {}, '审核结果', status)),
    h('div', { class: 'hk-row' }, h('label', {}, '理由', reason)),
    h('div', { class: 'hk-row' },
      h('button', {
        class: 'hk-btn primary',
        type: 'submit',
        disabled: !version || (version && version.status !== '待审'),
      }, version && version.status === '待审' ? '提交审核' : '该版本已审核')));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (onSubmit) onSubmit({ status: status.value, reason: reason.value });
  });
  return form;
}
// C03 对表计算前端：只渲染后端返回的 Reconcile / Calc，不复制匹配与公式规则。
import { h, badge, table } from '/sdk/haiknow.js';
import { issueMessage } from '/sdk/preview/errors.js';

export const VERSION = '1.0.0';

const STATUS_TEXT = {
  same: '一致',
  diff: '不一致',
  error: '无法比较',
  only_left: '仅左表',
  only_right: '仅右表',
};

function tone(status) {
  if (status === 'same') return 'ok';
  if (status === 'diff') return 'bad';
  return 'warn';
}

function fmt(value) {
  return value == null || value === '' ? '—' : String(value);
}

function keyOf(row, keyColumn) {
  if (row == null) return '—';
  if (row[keyColumn] != null && row[keyColumn] !== '') return row[keyColumn];
  const first = Object.values(row)[0];
  return first == null || first === '' ? '—' : first;
}

function duplicateCount(result) {
  const duplicates = result.duplicates || {};
  return (duplicates.left || []).length + (duplicates.right || []).length;
}

// 匹配结果表：每个匹配行的每个比较列一行；仅左/仅右也各占一行。
export function c03Table(result, { keyColumn = 'code' } = {}) {
  if (!result) return h('p', { class: 'muted' }, '还没有对表结果');
  const rows = [];
  for (const match of result.matches || []) {
    const diffs = match.diffs || [];
    if (diffs.length === 0) {
      rows.push({ key: match.key, column: '—', left: '', right: '', delta: '', unit: '', status: 'same' });
    }
    for (const diff of diffs) {
      rows.push({
        key: match.key,
        column: diff.column,
        left: fmt(diff.left),
        right: fmt(diff.right),
        delta: fmt(diff.delta),
        unit: diff.unit || '',
        status: diff.status,
      });
    }
  }
  for (const row of result.only_left || []) {
    rows.push({ key: keyOf(row, keyColumn), column: '整行', left: '存在', right: '缺失', delta: '', unit: '', status: 'only_left' });
  }
  for (const row of result.only_right || []) {
    rows.push({ key: keyOf(row, keyColumn), column: '整行', left: '缺失', right: '存在', delta: '', unit: '', status: 'only_right' });
  }

  return h('div', {},
    h('p', {},
      badge(`匹配 ${(result.matches || []).length}`, 'ok'), ' ',
      badge(`仅左 ${(result.only_left || []).length}`, 'warn'), ' ',
      badge(`仅右 ${(result.only_right || []).length}`, 'warn'), ' ',
      badge(`重复 ${duplicateCount(result)}`, 'bad')),
    table([
      { title: '键', key: 'key' },
      { title: '列', key: 'column' },
      { title: '左', key: 'left' },
      { title: '右', key: 'right' },
      { title: '差值', key: 'delta' },
      { title: '单位', key: 'unit' },
      { title: '结论', render: (row) => badge(STATUS_TEXT[row.status] || row.status, tone(row.status)) },
    ], rows));
}

// 问题清单：重复键、空键、错单位、空值、列缺失、公式错误都在这里。
export function c03Diff(result) {
  if (!result) return h('p', { class: 'muted' }, '还没有问题清单');
  const issues = result.errors || [];
  if (issues.length === 0) return h('p', { class: 'hk-note' }, '没有发现问题。');
  return h('div', {},
    h('p', {}, badge(`问题 ${issues.length}`, 'bad')),
    h('ul', {}, issues.map((issue) =>
      h('li', {},
        badge(issueMessage(issue.code), 'bad'),
        ' ',
        issue.message,
        issue.row ? h('span', { class: 'muted' }, `（第 ${issue.row} 行）`) : null,
        issue.column ? h('span', { class: 'muted' }, `（列 ${issue.column}）`) : null))));
}
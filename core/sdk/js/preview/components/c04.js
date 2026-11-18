// C04 进度提醒前端：只显示后端 Plan / 投递历史，不复制逾期、升级与去重规则。
import { h, badge, table } from '/sdk/haiknow.js';
import { issueMessage } from '/sdk/preview/errors.js';

export const VERSION = '1.0.0';

const TONES = {
  按期完成: 'ok',
  逾期完成: 'warn',
  逾期: 'bad',
  受阻: 'warn',
  未到期: '',
};

function tone(status) {
  return TONES[status] ?? '';
}

function fmt(value) {
  return value == null || value === '' ? '—' : String(value);
}

// 节点时间线：状态、逾期天数、依赖阻塞原因都来自后端计算。
export function c04Timeline(plan) {
  if (!plan) return h('p', { class: 'muted' }, '还没有进度计划');
  const counts = plan.byStatus || {};
  return h('div', {},
    h('p', {},
      Object.entries(counts).filter(([, count]) => count > 0).map(([status, count]) =>
        badge(`${status} ${count}`, tone(status)))),
    table([
      { title: '节点', key: 'name' },
      { title: '责任人', key: 'owner' },
      { title: '计划', key: 'planned' },
      { title: '实际', key: 'actual' },
      { title: '状态', render: (row) => badge(row.status, tone(row.status)) },
      { title: '逾期天数', key: 'daysLate' },
      {
        title: '受阻原因',
        render: (row) => (row.blockedBy || []).length ? (row.blockedBy || []).join('、') : '—',
      },
    ], (plan.states || []).map((row) => ({
      ...row,
      name: row.name || row.id,
      owner: fmt(row.owner),
      planned: fmt(row.planned),
      actual: fmt(row.actual),
    }))));
}

// 本轮提醒：只显示组件已经去重后的结果，并列出被跳过的原因。
export function c04Reminders(plan) {
  if (!plan) return h('p', { class: 'muted' }, '还没有提醒计划');
  const reminders = plan.reminders || [];
  const skipped = plan.skipped || [];
  const issues = plan.errors || [];
  return h('div', {},
    h('p', {},
      badge(`待发 ${reminders.length}`, reminders.length ? 'warn' : 'ok'), ' ',
      badge(`已跳过 ${skipped.length}`, ''), ' ',
      issues.length ? badge(`问题 ${issues.length}`, 'bad') : null),
    reminders.length
      ? table([
          { title: '对象', key: 'target' },
          { title: '等级', render: (row) => badge(row.level, row.level === '严重' ? 'bad' : row.level === '升级' ? 'warn' : '') },
          { title: '节点', key: 'name' },
          { title: '逾期天数', key: 'daysLate' },
          { title: '第几次', key: 'attempt' },
          { title: '通道', key: 'channel' },
          { title: '内容', key: 'message' },
        ], reminders)
      : h('p', { class: 'hk-note' }, '本轮没有需要发送的提醒。'),
    skipped.length
      ? h('details', {},
          h('summary', {}, '被去重跳过的提醒'),
          table([
            { title: '事件', key: 'event' },
            { title: '对象', key: 'target' },
            { title: '原因', key: 'reason' },
          ], skipped))
      : null,
    issues.length
      ? h('ul', {}, issues.map((issue) =>
          h('li', {}, badge(issueMessage(issue.code), 'bad'), ' ', issue.message)))
      : null);
}

// 投递历史：失败原因与尝试次数可追踪；应用用 retryable 结果重试。
export function c04Deliveries(history) {
  const rows = history || [];
  if (rows.length === 0) return h('p', { class: 'muted' }, '还没有投递记录');
  return h('div', {},
    table([
      { title: '事件', key: 'event' },
      { title: '对象', key: 'target' },
      { title: '结果', render: (row) => badge(row.status === 'sent' ? '已送达' : '失败', row.status === 'sent' ? 'ok' : 'bad') },
      { title: '尝试次数', key: 'attempts' },
      { title: '失败原因', key: 'lastError' },
      { title: '时间', key: 'at' },
    ], rows));
}
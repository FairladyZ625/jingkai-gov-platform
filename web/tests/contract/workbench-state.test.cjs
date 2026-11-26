const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

function boot(hash = '') {
  const listeners = {};
  const location = { hash, pathname: '/v4/', search: '?demo=1' };
  const history = { state: null,
    pushState(state, _title, url) { this.state = state; location.hash = url.includes('#') ? url.slice(url.indexOf('#')) : ''; },
    replaceState(state, title, url) { this.pushState(state, title, url); },
  };
  const classes = new Set();
  const body = { innerHTML: '', focus() {} };
  const host = { classList: { add(c) { classes.add(c); }, remove(c) { classes.delete(c); }, toggle(c, on) { on ? classes.add(c) : classes.delete(c); } },
    parentElement: { classList: { toggle() {} } }, replaceChildren() {}, dataset: {},
    set innerHTML(value) { this.html = value; }, querySelector() { return body; } };
  const window = { addEventListener(name, cb) { listeners[name] = cb; }, dispatchEvent() {}, JKApi: { meeting: { list: () => [] } } };
  const context = vm.createContext({ window, location, history, URLSearchParams,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } } });
  vm.runInContext(readFileSync(join(__dirname, '../../assets/workbench.js'), 'utf8'), context);
  return { wb: window.JKWorkbench, host, location, history, listeners, classes };
}

test('同一账号切换模块和对话保留各自记录，明确空记录可回列表', () => {
  const { wb, host, location } = boot();
  wb.bind(host, 'a', () => true, () => {});
  wb.open('meeting', { recordId: 'M-1' });
  wb.open('enterprise', { recordId: 'E-2' });
  wb.hide();
  assert.equal(location.hash, '');
  wb.open('meeting');
  assert.equal(host.dataset.record, 'M-1');
  wb.open('enterprise');
  assert.equal(host.dataset.record, 'E-2');
  wb.open('meeting', { recordId: '' });
  assert.equal(host.dataset.record, '');
});

test('隐藏工作台卸载业务模块，旧回调不能在另一个模块或退出后导航', () => {
  const { wb, host } = boot();
  let disposed = 0, oldContext;
  wb.register('meeting', { mount(_el, ctx) { oldContext = ctx; return { unmount() { disposed++; } }; } });
  wb.bind(host, 'a', () => true, () => {});
  wb.open('meeting', { recordId: 'M-1' });
  wb.hide();
  assert.equal(disposed, 1);
  assert.equal(wb.current(), null);
  wb.open('enterprise', { recordId: 'E-2' });
  oldContext.open('M-OLD');
  assert.equal(wb.current().id, 'enterprise');
  assert.equal(host.dataset.record, 'E-2');
  wb.reset();
  assert.equal(wb.open('meeting'), false);
});

test('权限拒绝和账号切换后的历史返回均不泄露上一身份记录', () => {
  const { wb, host, history, location, listeners } = boot();
  wb.bind(host, 'a', id => id === 'meeting', () => {});
  assert.equal(wb.open('enterprise'), false);
  wb.open('meeting', { recordId: 'M-PRIVATE' });
  const previousHistory = history.state, previousHash = location.hash;
  wb.reset();
  wb.bind(host, 'b', () => true, () => {});
  assert.equal(wb.current(), null);
  history.state = previousHistory; location.hash = previousHash;
  listeners.popstate();
  assert.equal(wb.current(), null);
  wb.open('meeting');
  assert.equal(host.dataset.record, '');
  assert.equal(wb.open('constructor'), false);
});

test('直接深链按当前权限恢复，未授权链接清理且不挂载', () => {
  const { wb, host, location } = boot('#/workbench/meeting?record=M%2F1');
  wb.bind(host, 'a', () => true, () => {});
  assert.equal(host.dataset.record, 'M/1');
  wb.bind(host, 'a', () => false, () => {});
  assert.equal(wb.current(), null);
  assert.equal(location.hash, '');
});

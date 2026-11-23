// 真实操作员词典，内存 GET 协议桩；绝不启动浏览器、监听端口或访问模型。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../../web/assets/operator.js', import.meta.url), 'utf8');
test('按有效 view 授权预加载，迟到的前一身份响应不写回', async () => {
  const calls = [];
  let finishOld;
  const ctx = {JK:{}, JKHttp:{get: path => {
    calls.push(path);
    if (path.endsWith('/meetings')) return new Promise(resolve => { finishOld = resolve; });
    return Promise.resolve({items:[]});
  }}};
  ctx.window = ctx; vm.runInNewContext(source, ctx);
  const op = ctx.JKOp;
  const first = op.loadDict(app => app === 'meeting');
  const latest = op.loadDict((app, action) => ['enterprise','policy'].includes(app) && action === 'view');
  await latest;
  finishOld({items:[{id:'fixture',title:'上一身份的会议'}]}); await first;
  assert.deepEqual(calls, ['/api/apps/meeting/meetings','/api/apps/enterprise/companies','/api/apps/policy/items']);
  assert.equal(op.dict.meeting.length, 0);
  await op.loadDict(); assert.equal(calls.length, 3, '未提供权限时不应请求');
});

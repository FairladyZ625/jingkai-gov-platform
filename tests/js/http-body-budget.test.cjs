// 无真实 fetch/计时器/监听：在响应头到达后，由同一个请求定时器中断响应体。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('prototype/v4/api/http.js', 'utf8');
test('HTTP 响应体超时不伪装成成功或发 api:write；getter 使用实际请求配置', async () => {
  const timers = new Map(), writes = [];
  let seq = 0, responseStarted;
  const read = new Promise(resolve => { responseStarted = resolve; });
  const ctx = {AbortController, DOMException, setTimeout(fn, ms) { timers.set(++seq, {fn, ms}); return seq; },
    clearTimeout: id => timers.delete(id),
    JK_CONFIG:{api:{mode:'http', baseUrl:'https://fixture.invalid', timeoutMs:250}},
    JK:{bus:{emit: (...args) => writes.push(args)}},
    fetch: async (_url, {signal}) => ({
      ok:true,
      json() {
        return new Promise((_, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('fixture abort', 'AbortError')), {once:true});
          responseStarted();
        });
      },
    }),
  };
  ctx.window = ctx;
  vm.runInNewContext(src, ctx);
  assert.equal(ctx.JKHttp.timeoutMs(),250);
  ctx.JK_CONFIG.api.timeoutMs = 612;
  assert.equal(ctx.JKHttp.timeoutMs(),612);
  const result = ctx.JKHttp.post('/fixture',{value:1});
  const failed = assert.rejects(result,e=>e.code==='TIMEOUT' && e.status===0);
  await read;
  assert.deepEqual([...timers.values()].map(({ms})=>ms),[612]);
  [...timers.values()][0].fn();
  await failed;
  assert.equal(timers.size,0);
  assert.deepEqual(writes,[]);
});

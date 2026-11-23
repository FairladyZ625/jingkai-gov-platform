// 执行真实 mount/事件/总控服务；替身仅是节点和异步 API，不启动浏览器、不测布局。
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const read = p => readFileSync(new URL('../../web/' + p, import.meta.url), 'utf8');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const deferred = () => { let done; const promise = new Promise(r => { done = r; }); return {promise, done}; };
const win = {}, nodes = new Map();
let app, service;
const JK = {registry:{},services:{},BUILTIN:{},bus:{on(){},emit(){}},registerApp(a){app=a;this.registry.kb=a;}, provide(_, s){service=s;this.services.kb=s;}};
const vmctx = vm.createContext({window: win, JK, setTimeout, clearTimeout, AbortController, document:{addEventListener(){}}});
win.JK=JK;
for (const p of ['apps/kb/config.js','apps/kb/app.js']) vm.runInContext(read(p), vmctx);
function node(selector) {
  if (!nodes.has(selector)) nodes.set(selector, {innerHTML:'', value:'', classList:{toggle(){}},
    querySelector:node, querySelectorAll:()=>[], appendChild(){}, replaceWith(){}, focus(){}, click(){return this.onclick?.();}});
  return nodes.get(selector);
}
const follow = '请列出这项政策的申报期限、适用对象和需要审签的材料';
const suggestions = win.JK_APPCFG.kb.suggestions;
let calls=[], activeSearch, activeAsk, activeMeta, failSearch=false, failAsk=false, unavailable=false;
const start=performance.now();
const state = {};
win.JKAPI = { ext:{state:()=>state,me:()=>({role:'member'}),roleOf:()=>({mask:false}),first(){}},onLoad:fn=>fn() };
for (const p of ['data/real-kb.js','mock/kb.js']) vm.runInContext(read(p),vmctx);
win.JK_CONFIG={api:{mode:'http',baseUrl:'https://fixture.invalid',timeoutMs:20000}};
let lastAnswer;
vmctx.fetch=async (url,options)=>{
  const op = url.split('/').pop();
  const response = j=>({ok:true,json:async()=>j});
  if (op==='spaces' || op==='stats') {await activeMeta?.promise;return response(op==='spaces'?{items:[]}:{});}
  assert.equal(options.method,'POST'); assert.ok(['ask','search'].includes(op));
  const b=JSON.parse(options.body);
  calls.push({op,q:b.q,scope:b.scope,at:performance.now()-start,budget:b.timeoutMs});
  await (op==='ask' ? activeAsk : activeSearch)?.promise;
  if (op==='search' && failSearch) return {ok:false,status:503,statusText:'Service Unavailable',json:async()=>({error:{code:'UNAVAILABLE',message:'检索桩不可用'}})};
  if (op==='ask' && failAsk) throw {name:'AbortError'};
  if (op==='ask' && unavailable) return response({notFound:true,unavailable:true,message:'模型服务暂时不可用',citations:[]});
  if (op==='ask') {lastAnswer=win.JKKB.ask(b.q,b);return response(lastAnswer);}
  return response(win.JKKB.search(b.q,b));
};
for (const p of ['api/http.js','api/kb.js']) vm.runInContext(read(p),vmctx);
const kb=win.JKApi.kb;
const handle = app.mount(node('root'), {api:{kb},ui:{icon:()=>'', tag:()=>'', empty:()=>'', appIcon:()=>''}});
await sleep(5);
const input = node('[data-op="kb.q"]');
const log = label => console.log(label, calls.map(c => c.op + '@' + c.at.toFixed(0)).join(' '));
const submit = () => input.onkeydown({key:'Enter',preventDefault(){}});
function expectOnePair(label, q) {
  log(label);
  assert.equal(calls.filter(c=>c.op==='search' && c.q===q).length,1,label);
  assert.equal(calls.filter(c=>c.op==='ask' && c.q===q).length,1,label);
}
function verifyAnswer(q) {
  assert.ok(lastAnswer.citations.length,q);
  assert.match(lastAnswer.answer,[/100万元/,/奖励/,/11月20日/,/负责/][suggestions.indexOf(q)]);
  return lastAnswer.citations[0].citationId;
}
test('右侧输入预检和提交共用检索；回答不等列表，四示例及追问使用正确范围', async () => {
for (const q of suggestions) {
  calls=[]; activeSearch=deferred(); activeAsk=deferred(); input.value=q; input.oninput();
  await sleep(180); // 输入预检已发出，保持未返回；此时按回车。
  submit(); await sleep(0);
  log('右侧带未完成预检'); activeAsk.done(); await sleep(0);
  const scope=verifyAnswer(q);
  assert.match(node('#kb-ans').innerHTML,/kb-src/); // search 未放行，回答不得被它阻塞
  activeSearch.done(); await sleep(0); activeAsk=activeSearch=null;
  expectOnePair('右侧',q);
  calls=[]; await service.ask(follow,{fromChat:true}); expectOnePair('总控追问',follow);
  assert.ok(calls.every(c=>c.scope===scope));
  assert.ok(lastAnswer.citations.every(c=>c.citationId===scope)); assert.match(lastAnswer.answer,/审签材料/);
  calls=[]; await service.ask(q,{fromChat:true}); expectOnePair('总控不同题',q);
  assert.ok(calls.every(c=>!c.scope));
  calls=[]; input.value=follow; input.oninput(); submit(); await sleep(5);
  expectOnePair('右侧追问',follow); assert.ok(calls.every(c=>c.scope===scope));
}
});
test('请求未完成时回车加点击共享同一轮，明确再次提问可刷新', async () => {
  const q=suggestions[0]; calls=[]; activeAsk=deferred();
  input.value=q; input.oninput(); submit(); node('[data-op="kb.ask"]').click(); await sleep(0);
  try {expectOnePair('同轮再点',q);} finally {activeAsk.done();}
  await sleep(5); calls=[]; activeAsk=null; submit(); await sleep(5);
  expectOnePair('完成后再问',q);
});
// 真实操作员动作也只提交一次；模拟“代填完成至点击”长于输入防抖间隔。
const run={step:async()=>{},fill:async(_,v)=>{input.value=v; input.oninput(); await sleep(170);},
  click:async key=>{node(key).click(); await sleep(0); log('操作员点击后');},
  wait:async (fn,budget)=>{const end=performance.now()+budget; while(!fn() && performance.now()<end) await sleep(5); assert.ok(fn());},
  highlight:async()=>{},done(){},fail(e){throw Error(e);}};
test('总控 send → 注册意图 → KB action；追问走总控对话而非新意图', async () => {
  activeSearch=activeAsk=null;
  Object.assign(JK, { $:node, $$:()=>[node('last-message')], h:()=>node('message'),
    esc:String, md:String, icon:()=>'',tag:()=>'',sleep,appIcon:()=>'' });
  vm.runInContext(read('assets/operator.js'),vmctx);
  const op=win.JKOp;
  vmctx.JKOp=op; vmctx.JKHttp=win.JKHttp;
  vm.runInContext(read('assets/shell.js'),vmctx);
  const shell=vmctx.JKShell=win.JKShell;
  Object.assign(shell.S,{me:{id:'fixture'},grants:{kb:['view']},cur:'c',convs:[{id:'c',msgs:[]}],active:'kb'});
  let skillMatches=0;
  JK.services.skills={async match(){skillMatches++; await sleep(80); return null;}};
  // 只替换操作员的光标/挂载驱动，不改 understand/send/KB动作和两个 API 的业务行为。
  op.start=async ({intent,slots,text})=>{assert.equal(intent.id,'kb.ask');return handle.actions[intent.action]({...slots,text},run);};
  for (const q of suggestions) {
    calls=[]; const begin=performance.now(), before=skillMatches;
    await shell.send(q,{silentUser:true});
    console.log('总控单轮',q,'技能匹配='+ (skillMatches-before),'受控耗时ms='+Math.round(performance.now()-begin));
    expectOnePair('总控操作员',q);
    const scope=verifyAnswer(q);
    calls=[]; await shell.send(follow,{silentUser:true}); expectOnePair('总控 send 追问',follow);
    assert.ok(calls.every(c=>c.scope===scope));
    assert.match(shell.S.convs[0].msgs.at(-1).text,/审签材料/);
    assert.equal(calls.find(c=>c.op==='ask').budget,20000);
  }
  console.log('总控四示例和追问 额外技能匹配='+skillMatches); assert.equal(skillMatches,0);
});
// 失败的预检可以重试；回答成功也不能擦掉同时发生的检索错误。
test('检索失败与回答失败独立，保留重试与错误',async () => {
activeSearch=activeAsk=null;
calls=[]; failSearch=true; input.value='另一问？'; input.oninput(); await sleep(180); submit(); await sleep(5);
assert.equal(calls.filter(c=>c.op==='search').length,2); assert.match(node('#kb-res').innerHTML,/检索桩不可用/);
failSearch=false; failAsk=true; await assert.rejects(service.ask(suggestions[0],{fromChat:true}),/服务器响应超时/);
failAsk=false; unavailable=true;
await assert.rejects(service.ask(suggestions[0],{fromChat:true}),/模型服务暂时不可用/);
assert.doesNotMatch(node('#kb-ans').innerHTML,/未找到依据/);
unavailable=false;
handle.unmount();
});
test('带问题打开知识库无需等空间和统计加载，也不在加载完成后重提',async () => {
  calls=[]; failAsk=false; activeMeta=deferred();
  const q=suggestions[0];
  const fresh=app.mount(node('root'),{params:{q},api:{kb},ui:{icon:()=>'',tag:()=>'',empty:()=>'',appIcon:()=>''}});
  try {
    await sleep(5); expectOnePair('元数据阻塞时',q); verifyAnswer(q);
    activeMeta.done(); await sleep(5); expectOnePair('元数据放行后',q);
  } finally {activeMeta.done(); fresh.unmount();}
});

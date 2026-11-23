// 真适配器、mock 路由和 guard；只有服务端 /me 使用内存响应，不创建监听。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

let profile, expired = false, saved = 0, delayed;
const paths = [], mock = [];
const ctx = vm.createContext({setTimeout, clearTimeout, AbortController, FormData, Blob, URLSearchParams,
  localStorage:{getItem(){return null;}, setItem(){saved++;}}, fetch:async url=>{
    paths.push(url);
    if (url==='/api/v1/auth/logout') return {ok:true,json:async()=>({ok:true})};
    if (url==='/api/v1/jobs/platform-job') return {ok:true,json:async()=>({job:{source:'platform'}})};
    assert.equal(url,'/api/v1/me','业务请求不得悄悄走 HTTP');
    if (delayed) await delayed();
    return {ok:!expired,status:expired?401:200,json:async()=>expired?{error:{code:'UNAUTHENTICATED'}}:profile};
  }});
ctx.window=ctx;
const run=file=>vm.runInContext(readFileSync(new URL('../../web/'+file,import.meta.url),'utf8'),ctx);
run('config/app.config.js'); ctx.JK_CONFIG.api={mode:'http',baseUrl:'',modules:{meeting:'mock'}};
for (const f of ['config/mock-data.js','config/accounts.js','mock/mock-api.js','mock/auth.js',
                 'api/http.js','api/platform.js','api/meeting.js']) run(f);
ctx.JKAPI.latency=0;
const original=ctx.JKAPI.request.bind(ctx.JKAPI);
ctx.JKAPI.request=(...args)=>{mock.push(args[1]);return original(...args);};
function member(grants) {
  return {user:{id:'u-wangmin',username:'wangmin',role:'member',status:'active'},
          role:{id:'member',mask:false},grants:{meeting:grants}};
}
profile=member(['view','operate']);
const k=ctx.JKApi.meeting;
assert.ok(Array.isArray((await k.list()).items));
await ctx.JKApi.me.get();
assert.deepEqual(mock,['/api/apps/meeting/meetings']); assert.deepEqual(paths,['/api/v1/me','/api/v1/me']);
assert.equal((await ctx.JKHttp.get('/api/v1/jobs/platform-job')).job.source,'platform');
await assert.rejects(k.job('absent'), e=>e.status===404 && e.code==='NOT_FOUND');
assert.ok(!paths.includes('/api/v1/jobs/absent'),'会议 job 不应访问平台的 HTTP job');
const created=await k.create({title:'临时会议夹具'});
assert.ok((await k.list()).items.some(x=>x.id===created.item.id));
profile=member(['view']); // 同一身份的撤权立即生效；不继承上一次的写授权或数据。
await assert.rejects(k.create({title:'不应写入'}),e=>e.status===403);
assert.ok(!(await k.list()).items.some(x=>x.title==='临时会议夹具'));
profile=member([]); await assert.rejects(k.list(),e=>e.status===403);
profile={...member(['view']),user:{...member([]).user,id:'unknown'}};
await assert.rejects(k.list(),e=>e.status===403);
expired=true; await assert.rejects(k.list(),e=>e.status===401);
expired=false; profile=member(['view','operate']);
let started, release;
const fetching=new Promise(r=>{started=r;});
delayed=()=>new Promise(r=>{release=r;started();});
const pending=k.create({title:'旧身份操作'});
await fetching; await ctx.JKHttp.post('/api/v1/auth/logout',{}); delayed=null; release();
await assert.rejects(pending,e=>e.code==='SESSION_CHANGED');
assert.ok(!(await k.list()).items.some(x=>x.title==='旧身份操作'));
assert.equal(saved,0,'部署混合态不保存身份或混入 file:// 缓存');
const scripts = [];
ctx.document={write:s=>scripts.push(s)};
run('config/apps.js');
ctx.JK_CONFIG.api.modules={kb:'mock'};
const html=readFileSync(new URL('../../web/index.html',import.meta.url),'utf8');
const loader=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('a.mock'));
vm.runInContext(loader,ctx);
assert.deepEqual(scripts.filter(s=>s.includes('src="mock/')),['<script src="mock/kb.js"></script>']);
run('mock/kb.js');
profile={user:{id:'u-hejun',username:'hejun',role:'partner',status:'active'},
         role:{id:'partner',mask:true},grants:{kb:['view'],policy:['view']}};
const publicAnswer=await ctx.JKHttp.post('/api/v1/kb/ask',{q:'数据券补贴最高能拿多少？'});
assert.ok(publicAnswer.citations.length && publicAnswer.citations.every(c=>c.space==='policy'));
await assert.rejects(ctx.JKHttp.get('/api/v1/kb/files/KB-R3948899'),e=>e.status===404);
ctx.JK_CONFIG.api.modules.policy='mock';run('mock/policy.js');
await assert.rejects(ctx.JKHttp.post('/api/apps/policy/match',{entId:'E001'}),e=>e.status===403);
console.log('模块 mock、平台 HTTP、明确授权、撤权/过期/身份隔离和不落盘通过');

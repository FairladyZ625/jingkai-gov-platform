// 可选：仅使用已有 JSDOM。禁用其默认资源加载器，只读取清单内的本地文件；
// 这不是 box、浏览器、像素验收或真实登录。不可为运行此脚本安装依赖。
const {JSDOM,ResourceLoader,VirtualConsole} = require('jsdom');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {pathToFileURL,fileURLToPath}=require('node:url');
const root=fs.realpathSync(process.argv[2]), manifest=JSON.parse(fs.readFileSync(path.join(root,'MANIFEST.json')));
const html=fs.readFileSync(path.join(root,manifest.entry),'utf8');
const requested=new Set(), errors=[];
class LocalOnly extends ResourceLoader {
  fetch(url) {
    const file=fileURLToPath(url); // 非 file: 不接受，不调用 super.fetch
    const rel=path.relative(root,file);
    assert(Object.hasOwn(manifest.files,rel),rel);requested.add(rel);
    return Promise.resolve(fs.readFileSync(file));
  }
}
const vc=new VirtualConsole();
vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(html,{url:pathToFileURL(path.join(root,manifest.entry)).href+'#probe',
  runScripts:'dangerously',resources:new LocalOnly(),virtualConsole:vc,pretendToBeVisual:true,
  beforeParse(w){w.HTMLElement.prototype.scrollIntoView=()=>{};}}); // JSDOM 无布局，滚动未验
const w=dom.window, q=s=>w.document.querySelector(s);
async function until(read,label) {
  for(let i=0;i<180;i++){if(read())return; await new Promise(r=>setTimeout(r,25));}
  throw Error('未到达 '+label+'。DOM 诊断：'+JSON.stringify({errors:errors.slice(0,5),
    ready:w.document.readyState, resources:requested.size,last:[...requested].slice(-4),
    isolated:!!w.T38?.ready, shell:!!w.JKShell, cards:w.document.querySelectorAll('.ql').length,
    probe:!!q('details summary'), root:!!q('#root')}));
}
(async()=>{
  try {
    await until(()=>q('.ql[data-u="hejun"]') && q('details summary'),'离线角色卡和探针');
    assert(w.JK.registry.kb && w.JK.registry.document && w.T38.ready);
    q('.ql[data-u="hejun"]').click();
    await until(()=>w.JKShell.S.me?.role==='partner' && q('#btn-me'),'实际合作方外壳');
    const probeBtn=s=>[...w.document.querySelectorAll('details button')].find(b=>b.textContent.startsWith(s));
    const trace=()=>q('details pre').textContent;
    const initialScript=w.JK_DEMO_SCRIPT;
    const originalSwitch=w.JKShell.switchUser;
    const auth=w.JKApi.auth, originalLogin=auth.login, originalLogout=auth.logout;
    let authCalls=0, switches=[];
    const unexpectedAuth=()=>{authCalls++;throw Error('协议探针不得发出登录/登出请求');};
    const withAuthSpy=()=>{auth.login=auth.logout=unexpectedAuth;};
    const restoreAuth=()=>{auth.login=originalLogin;auth.logout=originalLogout;};
    w.JKShell.switchUser=function(username, run, signal) {
      switches.push({username, signal, owned:w.JKDemo.ownsSwitch(signal)});
      return originalSwitch.call(this,username,run,signal);
    };
    withAuthSpy();
    const partner=w.JKShell.S.me;
    probeBtn('合作方禁止启动').click();
    assert.equal(q('[role=dialog]'),null);
    await until(()=>trace().includes('合作方拒绝检查：口令弹窗=false') && w.JK_CONFIG.api.mode==='mock','HTTP 合作方明确被拒');
    assert.equal(switches.length,0);assert.equal(authCalls,0);assert.equal(w.T38.blocked,0);
    assert.equal(w.JKShell.S.me,partner);assert.equal(w.JKDemo.state.on,false);assert.equal(q('.demobar'),null);
    assert.equal(w.JK_DEMO_SCRIPT,initialScript);
    restoreAuth();
    console.log('Node DOM：合作方进入 HTTP 协议分支后，不启动演示、不弹窗、不调用切号或登录，身份不变。');

    // file: mock 仍由产品切角流程使用本页虚拟身份；不是部署认证。
    assert.equal(await originalSwitch('wangmin'),true);
    const member=w.JKShell.S.me, conversation=w.JKShell.S.cur;
    const playback=()=>{const {on,i,paused,skip}=w.JKDemo.state;return [on,i,paused,skip,w.JKOp.demo];};
    const state=playback();
    withAuthSpy();
    probeBtn('内部成员演示切号取消').click();
    await until(()=>q('[data-op="switch.password"]'),'内部成员原生 HTTP 切号确认');
    assert.equal(q('[data-op="switch.password"]').value,'');
    assert.equal(w.JK_CONFIG.api.mode,'http');assert.equal(w.JKDemo.state.on,false);
    assert.deepEqual(switches.map(x=>[x.username,x.owned]),[['liyang',true]]);
    assert(w.JKDemo.ownsSwitch(switches[0].signal));
    assert.equal(w.JKDemo.ownsSwitch(new w.AbortController().signal),false);
    assert.equal(authCalls,0);assert.equal(w.T38.blocked,0);
    q('[role=dialog] [data-cancel]').click();
    await until(()=>trace().includes('内部成员取消检查：口令弹窗=true') && w.JK_CONFIG.api.mode==='mock' && !q('[role=dialog]'),'取消并回到 mock');
    assert.equal(w.JK_DEMO_SCRIPT,initialScript);assert.equal(w.JKShell.S.me,member);assert.equal(member.username,'wangmin');
    assert.equal(w.JKShell.S.cur,conversation);assert.deepEqual(playback(),state);
    assert.equal(w.JKDemo.ownsSwitch(switches[0].signal),false);assert(switches[0].signal.aborted);
    assert.equal(authCalls,0);assert.equal(q('.demobar'),null);
    restoreAuth();w.JKShell.switchUser=originalSwitch;
    assert.equal(w.T38.blocked,0);assert.equal(errors.length,0,errors.join(';'));
    console.log('Node DOM：加载 '+requested.size+' 个本地资源；file mock 可切虚拟身份；内部成员原生 HTTP 弹窗取消后身份、会话、播放状态不变，owner signal 释放、登录请求为零。未验像素。');
    // 通过真实 mock 业务入口准备两件，分别用于收件箱逆序回包与版本协议；
    // 不写 pending/approved 状态，不从测试直接给观察列表塞行。
    w.JKAPI.latency=0;
    const D=w.JKApi.document;
    async function sent(label) {
      const doc=(await D.draft({templateId:'T06',inputs:{orig:'【T38虚拟】'+label,reason:'隔离核验',oldEnd:'2026-11-30',newEnd:'2026-12-15'}})).item;
      const saved=(await D.save(doc.id,{content:{...doc.versions.at(-1).content,docNo:'演示〔2026〕2号',sign:'虚拟材料组'}})).item;
      const r=(await D.submit(doc.id,{assignee:'李阳'})).review;
      return {id:doc.id,rid:r.id,v:saved.versions.at(-1).v};
    }
    const one=await sent('旧列表演练'),two=await sent('画面版本演练');
    await w.JKShell.switchUser('liyang');await w.JKShell.refreshInbox();
    probeBtn('截住下一次').click();
    const old=w.JKShell.openBuiltin('inbox');await until(()=>q('details pre').textContent.includes('已截住旧列表'),'旧包保持中');
    await w.JKShell.openBuiltin('inbox');
    const approval=rid=>q('.pview.on [data-dec="approve"][data-id="'+rid+'"]');
    assert(approval(one.rid));approval(one.rid).click();
    await until(()=>!approval(one.rid),'新列表移出已办理件');
    probeBtn('放行旧读').click();await old;assert(!approval(one.rid));
    assert.equal((await D.get(one.id)).item.status,'已定稿');
    probeBtn('仅测画面版本').click();await w.JKShell.openBuiltin('inbox');
    const visible=approval(two.rid);
    assert(visible.closest('.inb-i').textContent.includes('【协议探针：v'+two.v+'】'));visible.click();
    await until(()=>q('details pre').textContent.includes(two.rid+' / approve / 画面请求版本='+two.v) && !visible.disabled,'决定携带画面版本');
    assert.equal((await D.get(two.id)).item.status,'审签中');
    assert.equal(w.T38.blocked,0);assert.deepEqual(errors,[]);
    console.log('Node DOM：实际收件箱两读逆序，已办旧件未恢复；显式版本探针收到画面 v'+two.v+'，拒绝写入后仍为审签中。');
  } finally {dom.window.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

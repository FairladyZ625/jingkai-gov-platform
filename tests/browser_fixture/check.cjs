// 不启动浏览器/监听端口。递归解释包内入口的经典 script/document.write，
// 不触发 DOMContentLoaded、不宣称验证布局。业务检查调用包里的原 JKApi。
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const crypto = require('node:crypto');
const {pathToFileURL,fileURLToPath} = require('node:url');
const root = fs.realpathSync(process.argv[2]);
const manifest = JSON.parse(fs.readFileSync(path.join(root,'MANIFEST.json')));
function walk(dir) {
  return fs.readdirSync(dir,{withFileTypes:true}).flatMap(d => {
    const p = path.join(dir,d.name);
    assert(!d.isSymbolicLink() && !d.name.startsWith('.'), '归档不能含隐藏项/符号链接');
    return d.isDirectory() ? walk(p) : [path.relative(root,p)];
  });
}
assert.deepEqual(walk(root).sort(), [...Object.keys(manifest.files),'MANIFEST.json'].sort());
for (const [rel, info] of Object.entries(manifest.files)) {
  const data = fs.readFileSync(path.join(root,rel));
  assert.equal(crypto.createHash('sha256').update(data).digest('hex'),info.sha256,rel);
}
const start = pathToFileURL(path.join(root,manifest.entry));
function load(entry = start) {
  const loaded = new Set(), document = {readyState:'loading', documentElement:{dataset:{}}, addEventListener(){}};
  const w = {document, location:entry, navigator:{platform:'fixture'}, URL, URLSearchParams, crypto,
    setTimeout, clearTimeout, setInterval, clearInterval, AbortController, performance, console};
  for (const s of ['localStorage','sessionStorage']) Object.defineProperty(w,s,{
    configurable:true, get(){throw Error('不应读取原存储')},
  });
  w.window=w; vm.createContext(w);
  function asset(url) {
    const u = new URL(url,start);
    assert.equal(u.protocol,'file:'); assert.equal(u.host,'');
    const rel = path.relative(root,fileURLToPath(u));
    assert.ok(Object.hasOwn(manifest.files,rel), '未列入本地清单：'+rel);
    loaded.add(rel);return fileURLToPath(u);
  }
  document.write = html => {
    for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>|<link\b([^>]+)>/gi)) {
      if (m[3]) { const href = /href="([^"]+)"/.exec(m[3]); if(href) asset(href[1]); continue; }
      const src = /src="([^"]+)"/.exec(m[1]), prev=document.currentScript;
      const file = src && asset(src[1]);
      document.currentScript={src:file?pathToFileURL(file).href:''};
      try { vm.runInContext(file?fs.readFileSync(file,'utf8'):m[2],w,{filename:file||'packaged-index',timeout:8000}); }
      finally { document.currentScript=prev; }
    }
  };
  const html=fs.readFileSync(path.join(root,manifest.entry),'utf8');
  assert.match(html,/connect-src 'none'/);
  document.write(html);return {w,loaded};
}
async function main() {
  const {w,loaded}=load(), api=w.JKApi;
  assert(w.T38.ready && api && w.JK.registry.document && w.JK.registry.kb);
  assert.equal(w.JKHttp.mode(),'mock');assert.equal(w.JK_CONFIG.api.baseUrl,'');
  assert(w.JK_DATA.users.every(a=>a.password==='') && w.JK_CONFIG.demoAccounts.every(a=>a.password===''));
  // data/index.js 在 config/mock-data 已内联同一快照时主动跳过独立脚本。
  const snapshots={'real-kb':'JK_REAL_KB','kb-examples':'JK_KB_EXAMPLES','real-policies':'JK_REAL','real-supplement':'JK_REAL_SUPPLEMENT'};
  for(const rel of Object.keys(manifest.files).filter(k=>/\.(?:js|css)$/.test(k))) {
    const snapshot=/^prototype\/v4\/data\/([\w-]+)\.js$/.exec(rel);
    assert(loaded.has(rel) || (snapshot && w[snapshots[snapshot[1]]]),rel);
  }
  await assert.rejects(w.fetch('https://t38.example.invalid/never'),/不发送网络/);
  w.localStorage.setItem('jk4-side','sentinel');
  const again=load().w;assert.equal(again.localStorage.getItem('jk4-side'),null);
  assert.throws(()=>load(new URL('https://t38.example.invalid/')),/T38 隔离未建立/);
  console.log('包内文件哈希、全部脚本/样式依赖、file-only 启动、禁 fetch、存储不串页：通过',manifest.revision);

  w.JKAPI.latency=0;
  const role=async username=>{await api.auth.login({username,password:''});assert.equal((await api.me.get()).user.username,username);};
  const kb=api.kb;
  await role('wangmin');
  const probeAnswer=async(q,scope) => {
    const hits=(await kb.search({q})).hits;
    const r=await kb.ask({q,scope});
    for(const c of r.citations||[]) {
      const d=(await kb.get(c.id)).item;
      assert(d.text.includes(c.snippet),'引用片段不是原文');
      if(scope) assert.equal(c.citationId,scope);
    }
    console.log(JSON.stringify({q,scope,top8:hits.slice(0,8).map(h=>h.id),notFound:!!r.notFound,
      source:r.source||null, citations:(r.citations||[]).map(c=>({id:c.citationId,snippet:c.snippet})),answer:r.answer||r.message}));
    return r;
  };
  const questions=w.JK_APPCFG.kb.suggestions;assert.equal(questions.length,4);
  let scope;
  for(const q of questions){const r=await probeAnswer(q);assert(r.citations.length,q);scope ||= r.citations[0].citationId;}
  const follow=await probeAnswer('请列出这项数据券政策的申报期限、适用对象和需要审签的材料；如果原文没有写，请明确说明',scope);
  for(const field of ['申报期限','适用对象','审签材料']) assert(follow.answer.includes(field));
  // 以下为正在修复的 #186 观测，日志保留实际答案，不把“无依据”记作问答通过。
  await probeAnswer('群雁计划上市辅导补贴最高多少？');
  await probeAnswer('群雁计划对境内上市辅导费用怎么补贴？');
  const historical=fs.readFileSync(path.join(root,'parking-original.txt'),'utf8').trim();
  const oldNote=await kb.importNow({items:[{name:'隔离样例园区停车管理通知',text:historical}],space:'rules'});
  assert.equal((await kb.get(oldNote.docs[0].id)).item.text.trim(),historical);
  await probeAnswer('园区停车最长能停多久？');
  const text=fs.readFileSync(path.join(root,'parking.txt'),'utf8');
  const preview=(await kb.preview([{name:'【T38虚拟】鹿桥园区访客停车规程',text,parse:'real',from:'粘贴'}])).items;
  preview[0].meta.space='rules';
  const parking=(await kb.commit(preview,'粘贴')).docs[0];
  assert.equal((await kb.get(parking.id)).item.text.trim(),text.trim());
  await probeAnswer('鹿桥园区普通访客可以免费停车多久？');
  const dup=async()=>Array.from((await kb.search({q:'双桐台帐',limit:50})).hits).filter(h=>h.id.startsWith('T38-DUP-'));
  assert.equal((await dup()).length,3);
  await role('hejun'); assert.equal((await dup()).length,2);
  await assert.rejects(kb.get(parking.id),e=>e.status===403 || e.status===404);
  // 整包的统一鉴权先于 KB 检索执行：只读角色可能直接收到 FORBIDDEN。
  // 无论到哪一层，都不能获得内部来源或正文。
  try {
    const denied=await kb.ask({q:'鹿桥园区访客可以免费停车多久？',scope:parking.id+'@v1'});
    assert(denied.notFound && !denied.citations?.length && !denied.answer?.includes('九十分钟'));
  } catch(e) { assert.equal(e.status,403);assert.equal(e.code,'FORBIDDEN');console.log('合作方 scoped ask：mock 鉴权 403，未进入问答引擎'); }
  console.log('合成资料去重与角色隔离：成员 3 / 合作方 2；合作方不可取内部停车资料');

  await role('wangmin');
  const D=api.document, draft=(await D.draft({templateId:'T06',inputs:{orig:'【T38虚拟】材料核验',oldEnd:'2026-11-30',newEnd:'2026-12-15'}})).item;
  const id=draft.id;
  await assert.rejects(D.submit(id,{assignee:'李阳'}),e=>e.code==='CHECK_FAILED');
  const c={...draft.versions.at(-1).content,to:'虚拟材料组：',sign:'T38虚拟组',date:'2026年11月18日',docNo:'演示〔2026〕1号'};
  c.paragraphs=c.paragraphs.map(p=>p.replace(/【待补：.*?】/g,'测试核验'));
  await D.save(id,{content:c});
  const first=(await D.submit(id,{assignee:'李阳'})).review;
  const pending=async rid=>(await api.reviews.list()).items.some(r=>r.id===rid&&r.status==='pending');
  await role('liyang');assert(await pending(first.id));
  await D.comment(id,{para:0,text:'请补充虚拟材料范围。'});
  await api.reviews.decide(first.id,{decision:'reject',reason:'请限定适用范围'});
  await role('wangmin');
  const returned=(await D.get(id)).item;assert.equal(returned.status,'已退回');assert.equal(returned.returnReason,'请限定适用范围');
  c.paragraphs[0]+='本次仅核验虚拟材料。';await D.save(id,{content:c});
  const second=(await D.submit(id,{assignee:'李阳'})).review;
  assert.notEqual(second.id,first.id);await role('liyang');assert(await pending(second.id));
  await api.reviews.decide(second.id,{decision:'approve',reason:'同意'});
  assert(!(await pending(second.id)));assert.equal((await D.get(id)).item.status,'已定稿');
  await assert.rejects(D.save(id,{content:c}),e=>e.code==='LOCKED');
  console.log('包内离线业务回放：核查拒绝 → 送审 → 批注退回 → 修改重送 → 同意定稿并锁定。非真实 HTTP / 浏览器。');
}
main().catch(e=>{console.error(e);process.exitCode=1;});

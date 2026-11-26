const test = require('node:test');
const assert = require('node:assert/strict');
const {createContext, loadScript} = require('./mock.cjs');
async function setup() {
  const c = createContext({Blob, TextEncoder, Uint8Array, DataView});
  loadScript(c, 'api/document.js');
  const login = name => c.JKHttp.post('/api/v1/auth/login', c.JK_CONFIG.demoAccounts.find(a => a.username === name));
  await login('admin'); return {c, api:c.JKApi.document, login};
}
async function reviewable(api) {
  const template = (await api.templates()).items.find(t => t.id === 'T06');
  return (await api.draft({templateId: template.id,
    inputs: Object.fromEntries(template.inputs.map(([key, , value]) => [key, value]))})).item;
}
for (const assignee of ['李阳', 'u-liyang']) test(`离线送审接受${assignee}，保留姓名协议并绑定成员编号`, async () => {
  const {api, c, login} = await setup();
  await login('wangmin');
  const draft = await reviewable(api);
  const {review} = await api.submit(draft.id, {assignee, version: draft.versions.at(-1).v});
  assert.equal(review.assignee, '李阳');
  assert.equal(review.assigneeId, 'u-liyang');
  const stored = c.JKAPI.state().inbox.find(r => r.id === review.id);
  assert.equal(stored.assignee, '李阳');
  assert.equal(stored.assigneeId, 'u-liyang');
  assert.equal((await api.workspace()).reviews.find(r => r.id === review.id).assignee, 'u-liyang');

  // 展示姓名可以修改或同名，但新审签单的办理身份不能随之改变。
  const users = c.JKAPI.state().users;
  users.find(u => u.username === 'admin').name = '李阳';
  users.find(u => u.id === 'u-liyang').name = '李阳（更新姓名）';
  await login('admin');
  assert.ok(!(await api.workspace()).reviews.some(r => r.id === review.id));
  await assert.rejects(api.review(review.id, {version: review.version, decision: 'approve'}), e => e.status === 403);
  await assert.rejects(c.JKHttp.post(`/api/v1/reviews/${review.id}/decisions`, {version: review.version, decision: 'approve'}), e => e.status === 403);
  await login('liyang');
  assert.equal((await api.workspace()).reviews.find(r => r.id === review.id).assignee, 'u-liyang');
  await api.review(review.id, {version: review.version, decision: 'approve'});
  assert.equal((await api.get(draft.id)).item.status, '已定稿');
});
for (const assignee of ['李阳', 'u-liyang']) test(`兼容既存仅含${assignee}的离线审签单`, async () => {
  const {api, c, login} = await setup();
  await login('wangmin');
  const draft = await reviewable(api);
  const {review} = await api.submit(draft.id, {assignee});
  const stored = c.JKAPI.state().inbox.find(r => r.id === review.id);
  delete stored.assigneeId;
  stored.assignee = assignee;
  await login('liyang');
  assert.equal((await api.workspace()).reviews.find(r => r.id === review.id).assignee, 'u-liyang');
  await api.review(review.id, {version: review.version, decision: 'approve'});
  assert.equal((await api.get(draft.id)).item.status, '已定稿');
});
test('工作台读取同一文稿、真实授权成员并拒绝过期保存', async () => {
  const {api} = await setup();
  const d = (await api.draft({templateId:'T06',inputs:{orig:'公开资料通知',oldEnd:'2026-11-01',newEnd:'2026-11-30'}})).item;
  const w = await api.workspace();
  const row = w.items.find(r => r.id === d.id);
  assert.ok(row.authorId); assert.equal(row.project, 'jkq');
  assert.ok(w.reviewers.length); assert.ok(w.reviewers.every(r => r.id && r.name));
  const v = d.versions.at(-1).v, content = {...d.versions.at(-1).content,title:'已更新'};
  await api.save(d.id,{content,baseVersion:v});
  await assert.rejects(api.save(d.id,{content:{...content,title:'旧页覆盖'},baseVersion:v}), e => e.code === 'STALE_VERSION');
  assert.equal((await api.get(d.id)).item.title,'已更新');
});
test('送审及审批绑定版本，并禁止自审与覆盖定稿', async () => {
  const {api,c,login} = await setup();
  const d = (await api.draft({templateId:'T06',inputs:{orig:'公开资料核验',oldEnd:'2026-11-01',newEnd:'2026-11-30',reason:'资料整理'}})).item;
  const content = {title:'关于开展公开资料核验的通知',docNo:'演示〔2026〕1号',to:'各有关单位：',paragraphs:['请核对已公开的资料。','除上述调整外，原通知其他事项不变。'],sign:'公文演示工作组',date:'2026年11月18日'};
  const saved = (await api.save(d.id,{content,baseVersion:d.versions.at(-1).v})).item;
  const workspace = await api.workspace();
  const authorId = workspace.items.find(r => r.id === d.id).authorId;
  const reviewer = workspace.reviewers.find(r => r.id !== authorId && r.name === '李阳');
  await assert.rejects(api.submit(d.id,{assignee:reviewer.id,version:0}), e => e.code === 'STALE_VERSION');
  await assert.rejects(api.submit(d.id,{assignee:authorId,version:saved.versions.at(-1).v}), e => e.code === 'SELF_REVIEW');
  const review = (await api.submit(d.id,{assignee:reviewer.id,version:saved.versions.at(-1).v})).review;
  const account = c.JK_CONFIG.demoAccounts.find(a => a.name === '李阳') || c.JK_CONFIG.demoAccounts.find(a => a.username === 'liyang');
  assert.ok(account); await login(account.username);
  assert.ok((await api.workspace()).reviews.some(r => r.id === review.id));
  await assert.rejects(api.review(review.id,{version:review.version-1,decision:'approve'}), e => e.code === 'STALE_VERSION');
  await api.review(review.id,{version:review.version,decision:'approve',comment:'同意'});
  assert.equal((await api.get(d.id)).item.status,'已定稿');
  await login('admin');
  await assert.rejects(api.save(d.id,{content}), e => e.code === 'LOCKED');
});
test('离线定稿拒绝规则修正接口绕过锁定，非审批成员不能决策', async()=>{
 const {api,login,c}=await setup();
 const final=(await api.workspace()).items.find(r=>r.status==='已定稿');assert.ok(final);
 await assert.rejects(api.fix(final.id,{ids:['c-bb']}), e=>e.code==='LOCKED');
 await login('wangmin');
 await assert.rejects(api.review('nonexistent',{version:1,decision:'approve'}),e=>e.status===403);
});
test('会议与公文处于不同传输模式时拒绝来源转入',async()=>{
 const {c,api}=await setup();c.JK_CONFIG.api.modules={meeting:'http',document:'mock'};
 await assert.rejects(api.draft({templateId:'T02',inputs:{},source:{app:'meeting',id:'M-remote',version:1}}),e=>e.code==='SOURCE_TRANSPORT_MISMATCH');
});
test('规则修正拒绝核查后已变化的版本',async()=>{
 const {api}=await setup();const d=(await api.draft({templateId:'T06',inputs:{orig:'核验通知',oldEnd:'2026-11-01',newEnd:'2026-11-30'}})).item;
 const version=d.versions.at(-1).v, content={...d.versions.at(-1).content,title:'核查后别人已修改'};
 await api.save(d.id,{content,baseVersion:version});
 await assert.rejects(api.fix(d.id,{ids:['c-bb'],baseVersion:version}),e=>e.code==='STALE_VERSION');
 assert.equal((await api.get(d.id)).item.versions.at(-1).v,version+1);
});

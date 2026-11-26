const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium,expect}=require('@playwright/test');
const {join}=require('node:path');
const {mkdir}=require('node:fs/promises');
const {pathToFileURL}=require('node:url');
async function setup(t,width=1440){
  const browser=await chromium.launch(process.env.PLAYWRIGHT_CHROME_PATH?{executablePath:process.env.PLAYWRIGHT_CHROME_PATH}:{});t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width,height:1000},offline:true});page.setDefaultTimeout(10000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));t.after(()=>assert.deepEqual(errors,[]));
  await page.goto(pathToFileURL(join(__dirname,'../../index.html')).href);await page.locator('[data-u="wangmin"]').click();
  await page.locator('#side-sc [data-workbench="meeting"]').click();return page;
}
test('会议工作台从文字到修订、定稿、幂等派发及收件箱同源完成',{timeout:90000},async t=>{
  const page=await setup(t);
  await page.locator('[data-action="new"]').click();
  await page.locator('[name="title"]').fill('【虚构验收】企业服务协调会');
  await page.locator('[name="text"]').fill('主持人：建议增加线上咨询窗口，尚未形成决定。\n经办人：会议决定先核对重复提交材料问题。\n李经办：整理问题清单，负责人和期限由经办人核对。');
  await page.getByRole('button',{name:'保存会议记录',exact:true}).click();
  await expect(page.locator('.mw-detail-head h2')).toHaveText('【虚构验收】企业服务协调会');
  const id=await page.evaluate(()=>JKWorkbench.current().recordId);
  assert.ok(id.startsWith('M-'));
  await expect(page.locator('[data-section="0"] [name="heading"]')).toHaveValue('讨论要点');
  await expect(page.locator('[data-section="1"] [name="heading"]')).toHaveValue('已明确的决定');
  await page.locator('[data-source="P2"]').click();await expect(page.locator('[data-source-card="P2"]')).toHaveClass(/highlight/);
  await page.locator('[data-tab="todos"]').click();await page.locator('[data-action="add-todo"]').click();
  await page.locator('[name="task"]').fill('核对问题清单');
  const myId=await page.evaluate(()=>JKAPI.ext.me().id);
  await page.locator('[name="owner"]').selectOption(myId);await page.locator('[name="due"]').fill('2026-12-10');await page.locator('[name="ref"]').selectOption('P2');
  await page.locator('[data-action="save-todos"]').click();await expect(page.locator('[data-message]')).toContainText('已保存候选');
  await page.locator('[data-action="dispatch"]').click();await expect(page.locator('[data-message]')).toContainText('请先确认纪要定稿');
  await page.locator('[data-tab="minutes"]').click();await page.locator('[data-checked]').check();await page.locator('[data-action="finalize"]').click();await expect(page.locator('[data-message]')).toContainText('已确认定稿');
  await page.reload();await expect(page.locator('.mw-detail-head')).toContainText('已定稿');
  for(const width of [1440,1280,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));if(process.env.MEETING_SCREENSHOTS){await mkdir(process.env.MEETING_SCREENSHOTS,{recursive:true});await page.screenshot({path:join(process.env.MEETING_SCREENSHOTS,`meeting-${width}.png`),fullPage:false});}}
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-tab="todos"]').click();await page.locator('[data-action="dispatch"]').click();await expect(page.locator('[data-message]')).toContainText('已派发');
  const assignment=await page.evaluate(async id=>(await JKApi.meeting.workbenchGet(id)).item.todos[0].assignment.id,id);
  await page.evaluate(async id=>{const d=await JKApi.meeting.workbenchGet(id);await JKApi.meeting.dispatch(id,d.item.todos.map(t=>t.id));},id);
  assert.equal(await page.evaluate(async assignment=>(await JKApi.todos.list()).items.filter(t=>t.id===assignment).length,assignment),1);
  await page.locator('[data-op="nav.inbox"]').click();await page.locator('[data-t="todo"]').click();
  await page.locator('[data-todo="'+assignment+'"]').check();await expect(page.locator('[data-todo="'+assignment+'"]')).toHaveCount(0);
  await page.locator('#side-sc [data-workbench="meeting"]').click();await page.reload();await expect(page.locator('.mw-todo-row')).toContainText('已完成');
  await page.locator('[data-tab="minutes"]').click();await page.locator('[name="paragraph"]').first().fill('人工核对：咨询窗口仍待评估。');await page.getByRole('button',{name:'保存为修订草稿',exact:true}).click();await expect(page.locator('[data-message]')).toContainText('定稿历史保留');
  await page.locator('[data-version]').selectOption({label:'定稿 v3'});await expect(page.locator('[name="paragraph"]').first()).toHaveValue('主持人：建议增加线上咨询窗口，尚未形成决定。');
  await page.locator('[data-action="restore"]').click();await expect(page.locator('[data-restore]')).toContainText('当前记录');
  await page.locator('[data-action="confirm-restore"]').click();await expect(page.locator('.mw-detail-head')).toContainText('待核对');
  await page.locator('[data-tab="sources"]').click();await page.locator('[data-supplement-text]').fill('会后核实材料不必重复提交');await page.locator('[data-supplement-source]').fill('虚构电话核实记录');await page.locator('[data-action="save-supplement"]').click();await expect(page.locator('[data-message]')).toContainText('会后补充已保存');
  await expect(page.locator('[data-detail]')).toContainText('虚构电话核实记录');
  await page.locator('[data-tab="todos"]').click();await page.locator('[name="progress"]').selectOption('待处理');await page.locator('[name="note"]').fill('补充核实后明确重开原因');await page.locator('[data-action="progress-0"]').click();await expect(page.locator('[data-message]')).toContainText('进展已更新');
  await page.locator('.mw-reassign summary').click();await page.locator('[name="new-due"]').fill('2026-12-15');await page.locator('[name="change-note"]').fill('补充核对后调整完成时间');await page.locator('[data-action="reassign-0"]').click();await expect(page.locator('[data-message]')).toContainText('相关成员已收到通知');await expect(page.locator('[name="due"]')).toHaveValue('2026-12-15');

});

test('离线接口指定负责人可办理，其他可见成员不能代办；模型失败不改写纪要',{timeout:30000},async t=>{
  const page=await setup(t);
  const result=await page.evaluate(async()=>{
    const S=JKAPI.state();S.grants['test-reader']={meeting:['view']};
    S.users.push({id:'test-reader',username:'test-reader',name:'虚构观察员',status:'active',role:'test-reader'});
    let d=await JKApi.meeting.workbenchCreate({title:'虚构权限验收',date:'2026-11-26',text:'会议决定核对材料。'});
    d=await JKApi.meeting.workbenchPatch(d.item.id,{baseVersion:d.item.version,todos:[{id:'t1',task:'核对材料',ownerId:'test-reader',due:'2026-12-01',ref:'P1'}]});
    d=await JKApi.meeting.finalize(d.item.id,{baseVersion:d.item.version,checked:true});
    d=await JKApi.meeting.dispatch(d.item.id,['t1']);
    let forbidden=0,model=0;try{await JKApi.meeting.progress(d.item.id,'t1',{status:'已完成',note:'代办'});}catch(e){forbidden=e.status;}
    try{await JKApi.meeting.candidate(d.item.id);}catch(e){model=e.status;}
    const after=await JKApi.meeting.workbenchGet(d.item.id);
    S.me='test-reader';S.session.userId='test-reader';
    const done=await JKApi.meeting.progress(d.item.id,'t1',{status:'已完成',note:'已逐项核对'});
    return {forbidden,model,preserved:after.item.version===d.item.version,status:done.item.todos[0].progressStatus};
  });
  assert.deepEqual(result,{forbidden:403,model:503,preserved:true,status:'已完成'});
});

const wordPath=process.env.MEETING_WORD_EXPORT || join(__dirname,'../../assets/word-export.js');
test('离线 Word 导出使用公文共享 OOXML 工具，生成真实 ZIP 文档',{timeout:30000,skip:!require('node:fs').existsSync(wordPath)},async t=>{
  const page=await setup(t);await page.addScriptTag({path:wordPath});
  const file=await page.evaluate(async()=>{
    let d=await JKApi.meeting.workbenchCreate({title:'虚构 Word 纪要',date:'2026-11-26',text:'会议决定核对材料。'});
    d=await JKApi.meeting.finalize(d.item.id,{baseVersion:d.item.version,checked:true});
    const file=await JKApi.meeting.exportMinutes(d.item.id,d.item.finalizedVersion);
    return {name:file.filename,magic:Array.from(new Uint8Array(await file.blob.slice(0,4).arrayBuffer())),size:file.blob.size};
  });assert.match(file.name,/\.docx$/);assert.deepEqual(file.magic,[80,75,3,4]);assert.ok(file.size>500);
});

test('未保存编辑阻止定稿和离开页签；否定决定仅列讨论',{timeout:30000},async t=>{
  const page=await setup(t);
  await page.evaluate(async()=>{const d=await JKApi.meeting.workbenchCreate({title:'未保存验收',date:'2026-11-26',text:'主持人：尚未形成会议决定，建议下周再讨论。'});JKWorkbench.open('meeting',{recordId:d.item.id});});
  await expect(page.locator('[name="heading"]')).toHaveValue('讨论要点');
  await page.locator('[name="paragraph"]').fill('人工核对但尚未保存的内容。');
  await page.locator('[data-checked]').check();await page.locator('[data-action="finalize"]').click();
  await expect(page.locator('[data-message]')).toContainText('未保存');await expect(page.locator('[name="paragraph"]')).toHaveValue('人工核对但尚未保存的内容。');
  await page.locator('[data-tab="todos"]').click();await expect(page.locator('[name="paragraph"]')).toHaveValue('人工核对但尚未保存的内容。');
  const recordId=await page.evaluate(()=>JKWorkbench.current().recordId);
  await page.evaluate(()=>JKWorkbench.open('meeting',{recordId:'archive'}));await expect(page.locator('.mw-intro h2')).toHaveText('会议档案');
  await page.evaluate(id=>JKWorkbench.open('meeting',{recordId:id}),recordId);await expect(page.locator('[name="paragraph"]')).toHaveValue('人工核对但尚未保存的内容。');
  await page.evaluate(()=>{window.savedMeetingPatch=JKApi.meeting.workbenchPatch;JKApi.meeting.workbenchPatch=async()=>{throw Error('模拟保存失败');};});
  await page.getByRole('button',{name:'保存核对内容',exact:true}).click();await expect(page.locator('[data-message]')).toContainText('模拟保存失败');
  await page.locator('[data-checked]').check();await page.locator('[data-action="finalize"]').click();await expect(page.locator('[data-message]')).toContainText('未保存');
  await page.evaluate(()=>{JKApi.meeting.workbenchPatch=window.savedMeetingPatch;delete window.savedMeetingPatch;});
  await page.getByRole('button',{name:'保存核对内容',exact:true}).click();await expect(page.locator('[data-message]')).toContainText('已保存');
  await page.locator('[data-checked]').check();await page.locator('[data-action="finalize"]').click();await expect(page.locator('.mw-detail-head')).toContainText('已定稿');
  await page.reload();await expect(page.locator('[name="paragraph"]')).toHaveValue('人工核对但尚未保存的内容。');
});

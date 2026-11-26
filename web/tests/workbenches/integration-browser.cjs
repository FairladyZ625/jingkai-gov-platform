const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium,expect}=require('@playwright/test');
const {pathToFileURL}=require('node:url');
const {join}=require('node:path');
const {mkdir}=require('node:fs/promises');
async function setup(t){
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH||undefined});t.after(()=>browser.close());
 const page=await browser.newPage({viewport:{width:1280,height:900},offline:true});page.setDefaultTimeout(10000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));t.after(()=>assert.deepEqual(errors,[]));
 await page.goto(pathToFileURL(join(__dirname,'../../index.html')).href);await page.locator('[data-u="wangmin"]').click();await expect(page.locator('#rail [data-workbench="enterprise"]')).toBeVisible();return page;
}
test('跨工作台新诉求入口直接打开表单并预选企业',{timeout:30000},async t=>{
 const page=await setup(t);await page.evaluate(()=>JKWorkbench.open('enterprise',{recordId:'issues?action=new&company=E001'}));
 await expect(page.getByLabel('诉求内容',{exact:true})).toBeVisible();
 await expect(page.getByLabel('选择企业',{exact:true})).toHaveValue('E001');
 await page.getByLabel('诉求内容',{exact:true}).fill('会议确认需要后续跟进的事项');
 await page.getByLabel('诉求来源',{exact:true}).selectOption('会议');
 await page.getByRole('button',{name:'保存诉求',exact:true}).click();
 await expect(page.getByRole('heading',{name:'会议确认需要后续跟进的事项'})).toBeVisible();
});

async function meetingFixture(page,finalized=true){
 return page.evaluate(async finalized=>{
  let d=await JKApi.meeting.workbenchCreate({title:'【虚构联验】服务协调会',date:'2026-11-26',text:'会议决定核对企业重复提交材料的诉求。'});
  if(finalized)d=await JKApi.meeting.finalize(d.item.id,{baseVersion:d.item.version,checked:true});
  const issue=await JKApi.enterprise.createIssue({entId:'E001',title:'【虚构联验】重复材料核对',from:'会议',owner:'王敏'});
  return {id:d.item.id,version:d.item.finalizedVersion||d.item.version,issueId:issue.item.id};
 },finalized);
}
test('会议关联企业诉求，企业返回固定定稿并回读最新办理状态',{timeout:45000},async t=>{
 const page=await setup(t),f=await meetingFixture(page);
 await page.evaluate(f=>JKWorkbench.open('meeting',{recordId:f.id+'~links'}),f);
 await page.getByRole('button',{name:'选择企业诉求',exact:true}).click();
 await page.locator('[data-issue]').selectOption(f.issueId);await page.locator('[data-link-source]').selectOption('P1');
 await page.getByRole('button',{name:'确认关联',exact:true}).click();await expect(page.locator('[data-message]')).toContainText('关联已保存');
 await page.locator('[data-link-app="enterprise"]').click();
 await expect(page.locator('[data-meeting-source]')).toContainText('【虚构联验】服务协调会');
 await page.getByLabel('办理状态',{exact:true}).selectOption('待补材料');await page.getByLabel('本次进展与依据',{exact:true}).fill('已联系企业补充材料');
 await page.getByRole('button',{name:'保存办理进展',exact:true}).click();await expect(page.locator('[data-issue-status]')).toHaveText('待补材料');
 if(process.env.INTEGRATION_SCREENSHOTS){await mkdir(process.env.INTEGRATION_SCREENSHOTS,{recursive:true});for(const width of [1440,1280]){await page.setViewportSize({width,height:1100});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:join(process.env.INTEGRATION_SCREENSHOTS,`integration-${width}.png`),fullPage:false,animations:"disabled"});}}
 await page.locator('[data-meeting-source]').click();await expect(page.locator('.mw-banner').first()).toContainText('固定定稿版本 v'+f.version);
 await expect(page.locator('[name="paragraph"]')).toHaveValue('会议决定核对企业重复提交材料的诉求。');
 await page.evaluate(f=>JKWorkbench.open('meeting',{recordId:f.id+'~links'}),f);await expect(page.locator('[data-links]')).toContainText('待补材料');
 await page.getByRole('button',{name:'先登记新诉求，再返回关联',exact:true}).click();await expect(page.getByLabel('诉求内容',{exact:true})).toBeVisible();
});
test('未定稿会议关联保留当时来源；无会议权限不展示回链',{timeout:45000},async t=>{
 const page=await setup(t),f=await meetingFixture(page,false);
 await page.evaluate(async f=>{await JKApi.meeting.linkRecord(f.id,{app:'enterprise',id:f.issueId,sourceRef:'P1'});let d=await JKApi.meeting.workbenchGet(f.id);await JKApi.meeting.workbenchPatch(f.id,{baseVersion:d.item.version,text:'后续补充的另一段资料。'});JKWorkbench.open('enterprise',{recordId:'issue?id='+f.issueId});},f);
 await page.locator('[data-meeting-source]').click();await expect(page.locator('.mw-banner').first()).toContainText('来源记录版本 v'+f.version);
 await expect(page.locator('[data-source-text]')).toHaveValue('会议决定核对企业重复提交材料的诉求。');
 await page.evaluate(async f=>{await JKShell.switchUser('hejun');JKWorkbench.open('enterprise',{recordId:'issue?id='+f.issueId});},f);
 await expect(page.locator('.wb-enterprise [data-view="issue"]')).toBeVisible();await expect(page.locator('[data-meeting-source]')).toHaveCount(0);
 assert.equal(await page.evaluate(async f=>{try{await JKApi.meeting.backlinks({app:'enterprise',id:f.issueId});return 200;}catch(e){return e.status;}},f),403);
});
test('会议定稿转公文使用真实正文，会议后续修订保留公文固定来源',{timeout:45000},async t=>{
 const page=await setup(t),f=await meetingFixture(page);
 await page.evaluate(f=>JKWorkbench.open('meeting',{recordId:f.id+'~links'}),f);
 await page.getByRole('button',{name:'将当前定稿转公文草稿',exact:true}).click();
 await expect(page.locator('.dw-source [data-action="source"]')).toHaveText('【虚构联验】服务协调会');
 const paragraphs=page.locator('[data-editor] textarea[name="para"]');await expect(paragraphs.first()).toBeVisible();assert.match((await paragraphs.allTextContents()).join('\n'),/会议决定核对企业重复提交材料的诉求/);
 await page.evaluate(async f=>{const d=await JKApi.meeting.workbenchGet(f.id);await JKApi.meeting.workbenchPatch(f.id,{baseVersion:d.item.version,text:'后来修改的来源不覆盖旧定稿。'});},f);
 await page.locator('.dw-source [data-action="source"]').click();await expect(page.locator('.mw-banner').first()).toContainText('固定定稿版本 v'+f.version);await expect(page.locator('[name="paragraph"]')).toHaveValue('会议决定核对企业重复提交材料的诉求。');
});

const test=require('node:test'), assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {chromium}=require('@playwright/test');
const root=path.resolve(__dirname,'../..');
test('查看会议来源前保留未保存正文，保存失败不能绕过离开保护',{timeout:60000},async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(12000);
  await page.goto('file://'+root+'/index.html');await page.locator('[data-u="wangmin"]').click();await page.locator('.hello').waitFor();
  const id=await page.evaluate(async()=>{
   const api=JKApi.document,d=(await api.draft({templateId:'T06',inputs:{orig:'会议事项办理通知',oldEnd:'2026-11-01',newEnd:'2026-11-30'}})).item;
   // 本回归覆盖公文离开保护；来源读取与定稿权限由 HTTP/API 用例覆盖。
   JKAPI.state().drafts[d.id].source={app:'meeting',id:'source-fixture',version:2,title:'公开演示会议定稿'};
   JKWorkbench.open('document',{recordId:d.id});return d.id;
  });
  const paragraph=page.locator('[data-editor] textarea[name="para"]').first(),source=page.locator('.dw-source [data-action="source"]');
  await paragraph.fill('经核对新增但尚未保存的公文修改。');
  await source.click();
  assert.equal((await page.evaluate(()=>JKWorkbench.current())).id,'document');
  await page.getByRole('alert').filter({hasText:'请先保存正文修改'}).waitFor();
  assert.equal(await paragraph.inputValue(),'经核对新增但尚未保存的公文修改。');
  await page.evaluate(()=>{window.originalDocumentSave=JKApi.document.save;JKApi.document.save=async()=>{throw new Error('本次保存失败，请重试');};});
  await page.getByRole('button',{name:'保存新版本',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'本次保存失败'}).waitFor();
  await source.click();
  assert.equal((await page.evaluate(()=>JKWorkbench.current())).id,'document');
  assert.equal(await paragraph.inputValue(),'经核对新增但尚未保存的公文修改。');
  await page.evaluate(()=>{JKApi.document.save=window.originalDocumentSave;delete window.originalDocumentSave;});
  await page.getByRole('button',{name:'保存新版本',exact:true}).click();await page.getByText('已保存新版本',{exact:true}).waitFor();
  await source.click();
  assert.deepEqual(await page.evaluate(()=>JKWorkbench.current()),{id:'meeting',recordId:'source-fixture~minutes~2'});
  await page.evaluate(id=>JKWorkbench.open('document',{recordId:id}),id);
  await require('@playwright/test').expect(paragraph).toHaveValue('经核对新增但尚未保存的公文修改。');
 }finally{await browser.close();}
});
test('公文工作台真实页面：档案直达、修改留版、核查、批注、送审、审批与下载',{timeout:90000},async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.setDefaultTimeout(12000);page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file://'+root+'/index.html');
  await page.locator('[data-u="wangmin"]').click();await page.locator('.hello').waitFor();
  const id=await page.evaluate(async()=>{
   const a=JKApi.document,d=(await a.draft({templateId:'T06',inputs:{orig:'公开资料核验',oldEnd:'2026-11-01',newEnd:'2026-11-30',reason:'统一资料'}})).item;
   await a.save(d.id,{content:{title:'公开资料核验办理通知',docNo:'演示〔2026〕1号',to:'各有关单位：',paragraphs:['请于2026年11月30日前完成公开资料核验。','除上述调整外，原通知其他事项不变。'],sign:'公文工作组',date:'2026年11月26日'},baseVersion:d.versions.at(-1).v});JKWorkbench.open('document');return d.id;
  });
  await page.getByRole('button',{name:'文稿档案',exact:true}).click();
  await page.locator('[data-doc-open="'+id+'"]').click();
  await page.getByLabel('文稿标题',{exact:true}).fill('公开资料核验办理通知（修订）');
  await page.getByRole('button',{name:'保存新版本',exact:true}).click();
  await page.getByText('已保存新版本',{exact:true}).waitFor();
  await page.getByRole('button',{name:'批注',exact:true}).click();
  await page.getByLabel('批注内容').fill('请核对主送范围。');await page.getByRole('button',{name:'添加批注',exact:true}).click();await page.getByText('请核对主送范围。',{exact:true}).waitFor();
  await page.getByRole('button',{name:'核查与润色',exact:true}).click();await page.getByRole('button',{name:'重新核查',exact:true}).waitFor();
  await page.getByRole('button',{name:'审签记录',exact:true}).click();
  await page.getByLabel('审核人',{exact:true}).selectOption('u-liyang');
  await page.getByRole('button',{name:'提交当前版本审核',exact:true}).click();await page.getByText('已提交审核',{exact:true}).waitFor();
  const review=await page.evaluate(async id=>(await JKApi.document.workspace()).reviews.find(r=>(r.recordId||r.ref)===id&&r.status==='pending'),id);assert.ok(review.version);
  await page.evaluate(async()=>{await JKShell.switchUser('liyang');JKWorkbench.open('document',{recordId:'view=review'});});
  await page.locator('[data-doc-open="'+id+'"]').click();
  await page.getByRole('button',{name:'审签记录',exact:true}).click();
  await page.getByLabel('审核意见').fill('经核对，同意定稿。');
  await page.getByRole('button',{name:'同意定稿',exact:true}).click();await page.getByText('已确认定稿',{exact:true}).waitFor();
  assert.equal(await page.evaluate(async id=>(await JKApi.document.get(id)).item.status,id),'已定稿');
  const downloadEvent=page.waitForEvent('download');await page.getByRole('button',{name:'下载 Word',exact:true}).click();const download=await downloadEvent;assert.match(download.suggestedFilename(),/\.docx$/);
  const bytes=fs.readFileSync(await download.path());assert.equal(bytes.readUInt32LE(0),0x04034b50);
  await page.getByRole('button',{name:'定稿查询',exact:true}).click();await page.locator('[data-doc-open="'+id+'"]').waitFor();
  await page.reload();await page.locator('[data-doc-open="'+id+'"]').waitFor();
  for(const width of [1440,1280]){await page.setViewportSize({width,height:1000});await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await page.screenshot({path:path.join(process.env.DOCUMENT_SCREENSHOTS || require('node:os').tmpdir(),'document-'+width+'.png'),fullPage:false});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));}
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});

test('公文页面拒绝过期覆盖，核查与比对可用，只读成员无修改入口',{timeout:90000},async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(12000);
  await page.goto('file://'+root+'/index.html');await page.locator('[data-u="admin"]').click();await page.locator('[data-op="shell.me"]').waitFor({state:'attached'});
  const id=await page.evaluate(async()=>{const d=(await JKApi.document.draft({templateId:'T06',inputs:{orig:'版本核验通知',oldEnd:'2026-11-01',newEnd:'2026-11-30'}})).item;JKWorkbench.open('document',{recordId:d.id});return d.id;});
  const title=page.getByLabel('文稿标题',{exact:true});await title.fill('页面上的旧修改');
  await page.evaluate(async id=>{const a=JKApi.document,d=(await a.get(id)).item;await a.save(id,{content:{...d.versions.at(-1).content,title:'其他经办人已保存的版本'},baseVersion:d.versions.at(-1).v});},id);
  await page.getByRole('button',{name:'保存新版本',exact:true}).click();await page.getByRole('alert').filter({hasText:'文稿已有新版本'}).waitFor();
  assert.equal(await title.inputValue(),'页面上的旧修改');
  await page.reload();await page.getByLabel('文稿标题',{exact:true}).waitFor();assert.equal(await page.getByLabel('文稿标题',{exact:true}).inputValue(),'其他经办人已保存的版本');
  await page.getByRole('button',{name:'版本对比',exact:true}).click();await page.getByRole('button',{name:'对比版本',exact:true}).click();await page.locator('.dw-diff').waitFor();
  await page.getByRole('button',{name:'核查与润色',exact:true}).click();await page.getByRole('button',{name:'重新核查',exact:true}).waitFor();
  assert.ok(await page.locator('.dw-check').count());await page.getByRole('button',{name:'预览政务语体',exact:true}).click();await page.locator('.dw-polish .dw-diff').waitFor();
  await page.evaluate(async()=>{await JKHttp.put('/api/v1/admin/grants/partner/document',{actions:['view']});await JKShell.switchUser('hejun');});
  await page.evaluate(id=>JKWorkbench.open('document',{recordId:id}),id);await page.getByLabel('文稿标题',{exact:true}).waitFor();
  assert.ok(await page.getByLabel('文稿标题',{exact:true}).isDisabled());assert.equal(await page.getByRole('button',{name:'保存新版本',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'新建文稿',exact:true}).count(),0);
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 }finally{await browser.close();}
});

test('采用规则润色产生新版本后清除旧核查和预览，同版本重新核查保留预览',{timeout:60000},async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(12000);
  await page.goto('file://'+root+'/index.html');await page.locator('[data-u="wangmin"]').click();await page.locator('[data-op="shell.me"]').waitFor({state:'attached'});
  const saved=await page.evaluate(async()=>{
   const a=JKApi.document,d=(await a.draft({templateId:'T06',inputs:{orig:'公开资料核验通知',oldEnd:'2026-11-01',newEnd:'2026-11-30'}})).item;
   const revised=(await a.save(d.id,{content:{title:'关于调整公开资料核验期限的通知',docNo:'演示〔2026〕1号',to:'各有关单位：',paragraphs:['咱们要赶紧搞资料核验。','除上述调整外，原通知其他事项不变。'],sign:'公文工作组',date:'2026年11月26日'},baseVersion:d.versions.at(-1).v})).item;
   JKWorkbench.open('document',{recordId:new URLSearchParams({id:d.id,tab:'check'}).toString()});return {id:d.id,version:revised.versions.at(-1).v};
  });
  await page.getByRole('button',{name:'重新核查',exact:true}).waitFor();assert.ok(await page.locator('.dw-check').count());
  await page.getByRole('button',{name:'预览政务语体',exact:true}).click();
  const adopt=page.getByRole('button',{name:'采用润色并存为新版本',exact:true});await adopt.waitFor();
  const previewText=await page.locator('.dw-polish .dw-diff').innerText();
  await page.getByRole('button',{name:'重新核查',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.wb-document').hasAttribute('aria-busy'));
  assert.equal(await page.locator('.dw-polish .dw-diff').innerText(),previewText);
  assert.equal(await page.evaluate(async id=>(await JKApi.document.get(id)).item.versions.at(-1).v,saved.id),saved.version);
  await adopt.click();await page.getByText('润色已另存为新版本',{exact:true}).waitFor();
  const changed=await page.evaluate(async id=>(await JKApi.document.get(id)).item.versions.at(-1),saved.id);
  assert.equal(changed.v,saved.version+1);assert.equal(changed.content.paragraphs[0],'我局要及时开展资料核验。');
  assert.equal(await adopt.count(),0,'已采用的旧预览不能继续作为当前版本被重复采用');
  assert.equal(await page.locator('.dw-polish .dw-diff').count(),0,'新版本不保留旧润色差异');
  assert.equal(await page.locator('.dw-check').count(),0,'旧版本的核查结论不能显示为新版本结论');
  await page.getByText('文稿已更新，请重新核查当前版本。',{exact:true}).waitFor();
  await page.getByRole('button',{name:'运行核查',exact:true}).click();await page.getByRole('button',{name:'重新核查',exact:true}).waitFor();
  assert.ok(await page.locator('.dw-check').count());assert.equal(await adopt.count(),0);
 }finally{await browser.close();}
});

async function legacyDraft(page) {
 await page.goto('file://'+root+'/index.html');await page.locator('[data-u="wangmin"]').click();await page.locator('[data-op="shell.me"]').waitFor({state:'attached'});
 const id=await page.evaluate(async()=>{
  const a=JKApi.document,d=(await a.draft({templateId:'T06',inputs:{orig:'跨入口核验通知',oldEnd:'2026-11-01',newEnd:'2026-11-30'}})).item;
  await a.save(d.id,{content:{title:'跨入口核验通知',docNo:'演示〔2026〕1号',to:'各有关单位：',paragraphs:['旧版正文'],sign:'公文工作组',date:'2026年11月26日'},baseVersion:d.versions.at(-1).v});
  await JKShell.openApp('document','detail',{id:d.id});return d.id;
 });
 await page.locator('.pview.on [data-op="document.p-0"]').waitFor();return id;
}
async function changeFromWorkbench(page,id,text) {
 await page.evaluate(id=>JKWorkbench.open('document',{recordId:id}),id);
 await page.locator('.wb-document textarea[name="para"]').first().fill(text);await page.getByRole('button',{name:'保存新版本',exact:true}).click();await page.getByText('已保存新版本',{exact:true}).waitFor();
 await page.locator('[data-wb-chat]').click();await page.locator('.pview.on [data-op="document.paper"]').waitFor();
}
for(const unsaved of [false,true])test(`跨入口${unsaved?'保留未保存编辑并拒绝旧版覆盖':'自动刷新原应用，修改标题不回退正文'}`,{timeout:60000},async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);const id=await legacyDraft(page);
  const legacy=page.locator('.pview[data-view="document"]');
  if(unsaved){await legacy.locator('[data-pe="0"]').click();await legacy.locator('[data-ed="0"]').fill('尚未保存的独立编辑');await legacy.locator('.ap-h h2').click();}
  await changeFromWorkbench(page,id,'工作台保存的新版正文');
  const before=await page.evaluate(async id=>(await JKApi.document.get(id)).item.versions.at(-1),id);
  if(unsaved){
   assert.equal(await legacy.locator('[data-op="document.p-0"]').innerText(),'尚未保存的独立编辑');
   await legacy.locator('[data-op="document.save"]').click();
   await page.getByText(/文稿已有新版本/).first().waitFor();
   const after=await page.evaluate(async id=>(await JKApi.document.get(id)).item.versions.at(-1),id);
   assert.equal(after.v,before.v);assert.equal(after.content.paragraphs[0],'工作台保存的新版正文');
   assert.equal(await legacy.locator('[data-op="document.p-0"]').innerText(),'尚未保存的独立编辑');
   assert.equal(await legacy.locator('[data-op="document.save"]').count(),1);
  }else{
   await require('@playwright/test').expect(legacy.locator('[data-op="document.p-0"]')).toHaveText('工作台保存的新版正文',{timeout:3000});
   await legacy.locator('[data-pe="title"]').click();await legacy.locator('[data-ed="title"]').fill('原应用仅修改标题');await legacy.locator('.ap-h h2').click();await legacy.locator('[data-op="document.save"]').click();
   await page.getByText(/已保存为第/).last().waitFor();
   const after=await page.evaluate(async id=>(await JKApi.document.get(id)).item.versions.at(-1),id);
   assert.equal(after.content.title,'原应用仅修改标题');assert.equal(after.content.paragraphs[0],'工作台保存的新版正文');assert.equal(after.v,before.v+1);
  }
 }finally{await browser.close();}
});

test('已打开原应用文稿后，工作台新建进入模板选择',{timeout:60000},async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);await legacyDraft(page);
  await page.evaluate(()=>JKWorkbench.open('document'));await page.getByRole('button',{name:'新建文稿',exact:true}).click();
  await require('@playwright/test').expect(page.locator('.pview.on [data-tpl]')).toHaveCount(10,{timeout:3000});
  assert.equal(await page.locator('.pview.on .dc-paper').count(),0);
 }finally{await browser.close();}
});

for(const action of ['polish','fix'])test(`原应用${action==='polish'?'润色采用':'规则修正'}绑定产生结果时的版本`,{timeout:60000},async()=>{
 const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROME_PATH || undefined,headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(12000);const id=await legacyDraft(page),legacy=page.locator('.pview[data-view="document"]');
  if(action==='polish'){
   await legacy.locator('[data-pe="0"]').click();await legacy.locator('[data-ed="0"]').fill('咱们要赶紧弄好资料。');await legacy.locator('.ap-h h2').click();await legacy.locator('[data-op="document.save"]').click();await page.getByText(/已保存为第/).last().waitFor();
   await legacy.locator('[data-op="document.panel-polish"]').click();await legacy.locator('[data-op="document.polish"]').click();await legacy.locator('[data-op="document.polish-yes"]').waitFor();
  }else{await legacy.locator('[data-op="document.check"]').click();await legacy.locator('[data-op="document.fix-all"]').waitFor();}
  const external=await page.evaluate(async id=>{const a=JKApi.document,d=(await a.get(id)).item;return (await a.save(id,{content:{...d.versions.at(-1).content,paragraphs:['另一客户端刚保存的正文']},baseVersion:d.versions.at(-1).v})).item.versions.at(-1);},id);
  await legacy.locator(`[data-op="document.${action==='polish'?'polish-yes':'fix-all'}"]`).click();
  await page.getByText(/文稿已有新版本/).first().waitFor();
  const latest=await page.evaluate(async id=>(await JKApi.document.get(id)).item.versions.at(-1),id);
  assert.equal(latest.v,external.v);assert.equal(latest.content.paragraphs[0],'另一客户端刚保存的正文');
  if(action==='polish'){assert.equal(await legacy.locator('[data-op="document.p-0"]').innerText(),'我局要及时完成资料。');assert.equal(await legacy.locator('[data-op="document.save"]').count(),1);}
 }finally{await browser.close();}
});

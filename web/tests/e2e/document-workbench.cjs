const test=require('node:test'), assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {chromium}=require('@playwright/test');
const root=path.resolve(__dirname,'../..');
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

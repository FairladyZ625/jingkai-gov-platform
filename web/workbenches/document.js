/* 公文工作台：同一文稿的档案、修订和审签；仅通过公开适配器读写。 */
(function () {
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const navs = [['overview','工作概览'],['archive','文稿档案'],['edit','待我修改'],['review','待我审核'],['final','定稿查询']];
  const tabs = [['content','正文编辑'],['check','核查与润色'],['comments','批注'],['versions','版本对比'],['reviews','审签记录']];
  const tag = status => `<span class="dw-status dw-status-${status==='已定稿'?'done':status==='已退回'?'return':status==='审签中'?'pending':'draft'}">${esc(status)}</span>`;
  const button = (label,action,primary=false,disabled=false) => `<button type="button" class="btn ${primary?'primary':''}" data-action="${action}" ${disabled?'disabled':''}>${label}</button>`;
  const input = (label,name,value,disabled=false) => `<label class="dw-field">${label}<input class="input" name="${name}" value="${esc(value)}" ${disabled?'disabled':''}></label>`;
  JKWorkbench.register('document',{mount(el,ctx) {
    let alive=true, busy=false, dirty=false, workspace, draft, issues, preview, comparison, loadedVersion, resultsInvalidated=false;
    const api=ctx.api, route=new URLSearchParams(ctx.recordId.includes('=')?ctx.recordId:'');
    const id=route.get('id') || (ctx.recordId && !ctx.recordId.includes('=')?ctx.recordId:''), view=route.get('view') || 'overview', tab=route.get('tab') || 'content';
    const live=()=>alive && ctx.can('view');
    const editable=()=>ctx.can('operate') && draft?.status!=='已定稿';
    const version=()=>draft?.versions.at(-1).v;
    const row=()=>workspace.items.find(r=>r.id===draft?.id);
    const own=r=>r.authorId===ctx.userId;
    const pending=()=>workspace.reviews.filter(r=>r.status==='pending' && r.submitter!==ctx.userId && (!r.assignee||r.assignee===ctx.userId) && ctx.can('approve') && workspace.items.some(d=>d.id===(r.recordId||r.ref)&&d.authorId!==ctx.userId&&d.status==='审签中'));
    const reviews=()=>workspace.reviews.filter(r=>(r.recordId||r.ref)===id);
    const open=(values)=>{ if(live())ctx.open(new URLSearchParams(values).toString()); };
    const notice=(text,error=false)=>{if(live()){const n=el.querySelector('[data-notice]');if(n){n.hidden=false;n.className='dw-notice'+(error?' error':'');n.textContent=text;n.setAttribute('role',error?'alert':'status');}}};
    async function run(fn,message,refresh=true) {
      if(!live()||busy)return;busy=true;el.setAttribute('aria-busy','true');
      el.querySelectorAll('button').forEach(b=>{if(!b.disabled){b.disabled=true;b.dataset.waitDisabled='1';}});
      try { await fn();if(!live())return;if(refresh){ window.dispatchEvent(new CustomEvent('jk:document:changed',{detail:{id,userId:ctx.userId}})); await load(); }if(message)notice(message); }
      catch(error){notice(error.message||'操作未完成，请重试',true);}
      finally {busy=false;if(alive){el.removeAttribute('aria-busy');el.querySelectorAll('[data-wait-disabled]').forEach(b=>{b.disabled=false;delete b.dataset.waitDisabled;});}}
    }
    function frame(body) {
      el.classList.add('wb-document');
      el.innerHTML=`<div class="dw-top"><p>围绕一份文稿，完成起草、修改、核查和审签。</p>${ctx.can('operate')?button('新建文稿','new',true):'<span class="dw-muted">仅查看权限</span>'}</div><nav class="dw-nav" aria-label="公文工作台导航">${navs.map(([key,label])=>`<button data-view="${key}" class="${!id&&view===key?'on':''}" ${!id&&view===key?'aria-current="page"':''}>${label}</button>`).join('')}</nav><div data-notice hidden></div>${body}`;
    }
    function rows(items) {
      return items.length?`<div class="dw-table-wrap"><table class="dw-table"><thead><tr><th>文稿</th><th>状态</th><th>起草人</th><th>最近修改</th><th>版本</th></tr></thead><tbody>${items.map(d=>`<tr><td><button class="dw-link" data-doc-open="${esc(d.id)}">${esc(d.title)}</button>${d.source?'<small>来自会议纪要</small>':''}</td><td>${tag(d.status)}</td><td>${esc(d.author)}</td><td class="dw-muted">${esc(String(d.updated||'').replace('T',' ').slice(0,16))}</td><td>v${d.versions}</td></tr>`).join('')}</tbody></table></div>`:'<div class="dw-empty"><strong>暂无相关文稿</strong><p>文稿创建、修改或送审后，会出现在这里。</p></div>';
    }
    function listing() {
      const modifying=workspace.items.filter(d=>own(d)&&['草稿','已退回'].includes(d.status)), waiting=pending(), finalized=workspace.items.filter(d=>d.status==='已定稿');
      if(view==='overview') {
        frame(`<div class="dw-metrics">${[['edit','待我修改',modifying.length],['review','待我审核',waiting.length],['final','已定稿',finalized.length],['archive','文稿档案',workspace.items.length]].map(([key,label,n])=>`<button data-view="${key}"><span>${label}</span><strong>${n}</strong><small>查看文稿 →</small></button>`).join('')}</div><section class="dw-card"><div class="dw-section-head"><div><h2>继续办理</h2><p>优先处理退回意见，再完善待送审文稿。</p></div><span class="dw-muted">${modifying.length} 份待修改</span></div>${rows(modifying.sort((a,b)=>(b.status==='已退回')-(a.status==='已退回')).slice(0,6))}</section><section class="dw-card"><div class="dw-section-head"><div><h2>最近文稿</h2><p>档案、版本和审签沿用同一份记录。</p></div><button class="btn ghost" data-view="archive">查看全部</button></div>${rows(workspace.items.slice(0,5))}</section>`);return;
      }
      let items=view==='edit'?modifying:view==='review'?workspace.items.filter(d=>waiting.some(r=>(r.recordId||r.ref)===d.id)):view==='final'?finalized:workspace.items;
      const q=route.get('q')||'',status=route.get('status')||'',mine=route.get('mine')==='1';
      items=items.filter(d=>(!q||(d.title+' '+d.author).includes(q))&&(!status||d.status===status)&&(!mine||own(d)));
      frame(`<section class="dw-card"><div class="dw-section-head"><div><h2>${navs.find(n=>n[0]===view)?.[1]||'文稿档案'}</h2><p>${view==='review'?'仅展示分配给你、且你有权审核的待审文稿。':view==='edit'?'由你起草的草稿和已退回文稿。':'查询文稿状态，打开后可查看正文、版本和审签。'}</p></div><span class="dw-muted">${items.length} 份文稿</span></div><form class="dw-filters" data-filter><input class="input" name="q" aria-label="搜索文稿" placeholder="搜索标题或起草人" value="${esc(q)}">${['archive','edit'].includes(view)?`<select class="input" name="status" aria-label="文稿状态"><option value="">全部状态</option>${['草稿','已退回','审签中','已定稿'].map(s=>`<option ${s===status?'selected':''}>${s}</option>`).join('')}</select>`:''}<label><input name="mine" type="checkbox" ${mine?'checked':''}> 只看我起草的</label><button class="btn" type="submit">查询</button></form>${rows(items)}</section>`);
    }
    function contentPanel() {
      const c=draft.versions.at(-1).content,disabled=!editable();
      return `<form data-editor class="dw-editor"><div class="dw-form-grid">${input('文稿标题','title',c.title,disabled)}${input('发文字号','docNo',c.docNo,disabled)}${input('主送机关','to',c.to,disabled)}</div><div class="dw-paragraphs">${c.paragraphs.map((p,i)=>`<label class="dw-field">第 ${i+1} 段<textarea class="input" name="para" rows="${Math.max(3,Math.min(8,Math.ceil(p.length/40)))}" ${disabled?'disabled':''}>${esc(p)}</textarea></label>`).join('')}</div>${editable()?button('增加一段','paragraph'):''}<div class="dw-form-grid">${input('发文机关','sign',c.sign,disabled)}${input('成文日期','date',c.date,disabled)}</div>${editable()?`<div class="dw-save">${input('修改说明（选填）','note','')}<button class="btn primary" type="submit">保存新版本</button></div>`:'<p class="dw-muted">'+(draft.status==='已定稿'?'文稿已定稿，正文与版本已锁定。':'当前账号可查看正文。')+'</p>'}</form>${draft.refs?.length?`<aside class="dw-source"><strong>引用依据</strong>${draft.refs.map(ref=>`<p><button class="dw-link" data-citation="${esc(ref.id)}">${esc(ref.title||ref.id)}</button>${ref.version?` · 版本 ${esc(ref.version)}`:''}</p>`).join('')}</aside>`:''}`;
    }
    const diffHTML=parts=>(parts||[]).map(p=>`<span class="dw-diff-${esc(p.op)}">${esc(p.t??p.text??'')}</span>`).join('');
    function checkPanel() {
      return `<div class="dw-section-head"><div><h3>核查当前已保存版本</h3><p>检查必填要素、文字格式和引用依据；结论仍需经办人核对。</p></div>${ctx.can('operate')?button(issues?'重新核查':'运行核查','check'):''}</div>${issues?`<div class="dw-checks">${issues.length?issues.map(i=>`<div class="dw-check"><span class="dw-status">${({error:'必须修改',warn:'请核对',info:'提示',ok:'通过'})[i.level]||esc(i.level)}</span><div><strong>${esc(i.title||i.message||i.rule||i.id)}</strong><p>${esc(i.detail||i.message||i.desc||i.suggestion||'')}</p></div></div>`).join(''):'<p>未发现规则核查问题，仍需人工核对内容。</p>'}</div>`:`<p class="dw-muted">${resultsInvalidated?'文稿已更新，请重新核查当前版本。':'尚未核查。请先保存修改，再运行核查。'}</p>`}${editable()?`<div class="dw-polish"><h3>规则润色</h3><p>按固定文字规则提供预览，采用后另存新版本。</p><div class="dw-actions">${button('预览政务语体','formal')}${button('预览精简表达','concise')}</div>${preview?`<div class="dw-diff">${diffHTML(preview.parts)}</div><p>${preview.changed?'请核对差异后再采用。':'当前正文没有适用的规则替换。'}</p>${preview.changed?button('采用润色并存为新版本','adopt',true):''}`:''}</div>`:''}`;
    }
    function commentsPanel() {
      const c=draft.versions.at(-1).content;
      return `<h3>逐段批注</h3><p class="dw-muted">批注与回复保留在同一文稿中，修改正文不会删除讨论。</p>${draft.comments.length?draft.comments.map(cm=>`<article class="dw-comment"><header><strong>第 ${cm.para+1} 段 · ${esc(cm.by)}</strong><span class="dw-muted">${cm.resolved?'已解决':'待处理'}</span></header><p>${esc(cm.text)}</p>${(cm.replies||[]).map(r=>`<blockquote>${esc(r.by)}：${esc(r.text)}</blockquote>`).join('')}${ctx.can('operate')?`<form data-comment-reply="${esc(cm.id)}"><input class="input" name="reply" aria-label="回复 ${esc(cm.by)} 的批注" placeholder="补充回复" required><button class="btn">回复</button><button type="button" class="btn ghost" data-resolve="${esc(cm.id)}" data-resolved="${!cm.resolved}">${cm.resolved?'重新打开':'标记已解决'}</button></form>`:''}</article>`).join(''):'<div class="dw-empty">暂无批注</div>'}${ctx.can('operate')&&c.paragraphs.length?`<form data-comment class="dw-new-comment"><label class="dw-field">批注段落<select class="input" name="para" aria-label="批注段落">${c.paragraphs.map((p,i)=>`<option value="${i}">第 ${i+1} 段 · ${esc(p.slice(0,30))}</option>`).join('')}</select></label><label class="dw-field">批注内容<textarea class="input" name="text" required rows="3"></textarea></label><button class="btn primary">添加批注</button></form>`:''}`;
    }
    function versionsPanel() {
      const vs=draft.versions;
      return `<h3>版本对比</h3><p class="dw-muted">每次保存产生一个新版本，不覆盖历史正文。</p><form data-compare class="dw-filters"><label>较早版本 <select class="input" name="a">${vs.map(v=>`<option value="${v.v}">v${v.v} · ${esc(v.by)}</option>`).join('')}</select></label><label>较新版本 <select class="input" name="b">${vs.map((v,i)=>`<option value="${v.v}" ${i===vs.length-1?'selected':''}>v${v.v} · ${esc(v.by)}</option>`).join('')}</select></label><button class="btn" ${vs.length<2?'disabled':''}>对比版本</button></form>${comparison?`<p>新增 ${comparison.stats.add} 字 · 删除 ${comparison.stats.del} 字</p><div class="dw-diff">${diffHTML(comparison.parts)}</div>`:vs.length<2?'<p class="dw-muted">保存第二个版本后即可比较。</p>':''}<ol class="dw-history">${[...vs].reverse().map(v=>`<li><strong>v${v.v}</strong><span>${esc(v.by)}</span><time>${esc(v.at)}</time></li>`).join('')}</ol>`;
    }
    function reviewPanel() {
      const assigned=pending().find(r=>(r.recordId||r.ref)===id),members=workspace.reviewers.filter(u=>u.id!==ctx.userId&&u.id!==row()?.authorId),hist=reviews();
      return `<h3>审核与定稿</h3><p class="dw-muted">审核针对提交的具体版本。正文变更后须重新核查和送审。</p>${editable()&&['草稿','已退回'].includes(draft.status)?`<form data-submit class="dw-review-form"><label class="dw-field">审核人<select class="input" name="assignee" aria-label="审核人" required><option value="">请选择审核人</option>${members.map(u=>`<option value="${esc(u.id)}">${esc(u.name)}</option>`).join('')}</select></label><button class="btn primary" ${members.length?'':'disabled'}>提交当前版本审核</button>${!members.length?'<p>暂无可选审核人，请联系管理员配置项目授权。</p>':''}</form>`:''}${assigned?`<form data-decision="${esc(assigned.id)}" data-version="${assigned.version}" class="dw-review-form"><strong>待你审核：当前已送审版本</strong><label class="dw-field">审核意见<textarea class="input" name="comment" rows="3" placeholder="退回时请写明修改原因"></textarea></label><div class="dw-actions"><button class="btn primary" name="decision" value="approve">同意定稿</button><button class="btn" name="decision" value="reject">退回修改</button></div></form>`:''}${draft.status==='审签中'&&!assigned?'<div class="dw-notice">文稿正在审核中。修改正文后，现有审签单将失效，需要重新送审。</div>':''}${draft.status==='已定稿'?'<div class="dw-notice">该文稿已经确认定稿，可下载定稿 Word。</div>':''}<h3>可见审签记录</h3>${hist.length?hist.map(r=>`<article class="dw-comment"><header><strong>${esc(({recheck:'旧版本已失效',stale:'旧版本已失效',pending:'待审核',confirmed:'已通过',needs_info:'已退回',done:'已通过',rejected:'已退回'})[r.status]||r.status)}</strong><span>${esc(workspace.reviewers.find(u=>u.id===r.assignee)?.name||r.assignee||'未指定')}</span></header>${(r.decisions||[]).map(d=>`<p>${esc(d.comment||'未填写意见')}</p>`).join('')}${r.reason?`<p>${esc(r.reason)}</p>`:''}</article>`).join(''):'<p class="dw-muted">当前账号没有可见的审签记录。</p>'}`;
    }
    function detail() {
      const panels={content:contentPanel,check:checkPanel,comments:commentsPanel,versions:versionsPanel,reviews:reviewPanel};
      frame(`<section class="dw-detail"><button class="dw-link dw-back" data-view="archive">← 返回文稿档案</button><div class="dw-detail-head"><div><h2>${esc(draft.title)}</h2><p>${tag(draft.status)} <span>${esc(draft.author)} 起草 · v${version()}</span></p></div>${button('下载 Word','download')}</div>${draft.returnReason?`<div class="dw-notice error"><strong>退回意见：</strong>${esc(draft.returnReason)}</div>`:''}${draft.source?`<div class="dw-source">来源：<button class="dw-link" data-action="source">${esc(draft.source.title)}</button> · 会议定稿版本 ${draft.source.version}<span>转入后，文稿的修改与会议纪要分别留版。</span></div>`:''}<nav class="dw-tabs" aria-label="文稿处理">${tabs.map(([key,label])=>`<button data-tab="${key}" class="${tab===key?'on':''}" ${tab===key?'aria-current="page"':''}>${label}${key==='comments'&&draft.comments.length?` <small>${draft.comments.length}</small>`:''}</button>`).join('')}</nav><section class="dw-panel">${(panels[tab]||contentPanel)()}</section></section>`);
    }
    async function load() {
      const results=await Promise.all([api.workspace(),id?api.get(id):Promise.resolve(null)]);if(!live())return;
      const nextDraft=results[1]?.item, nextVersion=nextDraft?.versions.at(-1).v;
      if(loadedVersion!==undefined && nextVersion!==loadedVersion) {
        issues=preview=comparison=undefined;resultsInvalidated=true;
      }
      loadedVersion=nextVersion;workspace=results[0];draft=nextDraft;dirty=false;
      if(id)detail();else listing();
    }
    const saved=()=>{if(dirty){notice('请先保存正文修改，再执行此操作。',true);return false;}return true;};
    el.addEventListener('input',onInput);el.addEventListener('click',onClick);el.addEventListener('submit',onSubmit);
    function onInput(e){if(e.target.closest('[data-editor]'))dirty=true;}
    function onClick(e) {
      const b=e.target.closest('button');if(!b||!live()||busy)return;
      if(dirty && (b.dataset.view || b.dataset.docOpen || b.dataset.tab)){notice('正文尚未保存，请先保存新版本再离开。',true);return;}
      if(b.dataset.view){open({view:b.dataset.view});return;}
      if(b.dataset.docOpen){open({id:b.dataset.docOpen});return;}
      if(b.dataset.tab){open({id,tab:b.dataset.tab});return;}
      if(b.dataset.citation){JKShell.openApp('kb','doc',{fileId:b.dataset.citation,version:draft.refs.find(r=>r.id===b.dataset.citation)?.version});return;}
      if(b.dataset.resolve){run(()=>api.patchComment(id,b.dataset.resolve,{resolved:b.dataset.resolved==='true'}),'批注状态已更新');return;}
      const a=b.dataset.action;if(!a)return;
      if(a==='new'){JKWorkbench.hide();JKShell.openApp('document','new');return;}
      if(a==='reload'){run(()=>{},'',true);return;}
      if(a==='source'){if(!saved())return;JKWorkbench.open('meeting',{recordId:`${draft.source.id}~minutes~${draft.source.version}`});return;}
      if(a==='download'){run(async()=>{const r=await api.exportWord(id);if(live())JK.download(r.filename,r.blob);},'',false);return;}
      if(a==='paragraph'&&editable()){const list=el.querySelector('.dw-paragraphs'),n=list.children.length+1;list.insertAdjacentHTML('beforeend',`<label class="dw-field">第 ${n} 段<textarea class="input" name="para" rows="3"></textarea></label>`);list.lastElementChild.querySelector('textarea').focus();dirty=true;return;}
      if(!saved())return;
      if(a==='check'&&ctx.can('operate'))run(async()=>{const r=await api.check(id);if(live()){issues=r.issues;detail();}},'',false);
      if(['formal','concise'].includes(a)&&editable())run(async()=>{const r=await api.polish(id,{style:a});if(live()){preview=r;detail();}},'',false);
      if(a==='adopt'&&editable()&&preview)run(()=>api.save(id,{content:preview.preview,note:'采用规则润色',baseVersion:version()}),'润色已另存为新版本');
    }
    function onSubmit(e) {
      e.preventDefault();if(!live()||busy)return;const f=e.target,fd=new FormData(f);
      if(f.matches('[data-filter]')){open({view,q:fd.get('q')||'',status:fd.get('status')||'',mine:fd.get('mine')?'1':''});return;}
      if(f.matches('[data-editor]')&&editable()){
        const content={};for(const k of ['title','docNo','to','sign','date'])content[k]=String(fd.get(k)||'');content.paragraphs=fd.getAll('para').map(String);
        if(!content.title.trim()){notice('请填写文稿标题。',true);return;}
        run(()=>api.save(id,{content,note:fd.get('note')||'',baseVersion:version()}),'已保存新版本');return;
      }
      if(f.matches('[data-comment]')&&ctx.can('operate')){run(()=>api.comment(id,{para:Number(fd.get('para')),text:String(fd.get('text'))}),'批注已添加');return;}
      if(f.dataset.commentReply&&ctx.can('operate')){run(()=>api.patchComment(id,f.dataset.commentReply,{reply:String(fd.get('reply'))}),'回复已保存');return;}
      if(f.matches('[data-compare]')){run(async()=>{const r=await api.compare({a:{id,v:Number(fd.get('a'))},b:{id,v:Number(fd.get('b'))}});if(live()){comparison=r;detail();}},'',false);return;}
      if(f.matches('[data-submit]')&&editable())run(()=>api.submit(id,{assignee:String(fd.get('assignee')),version:version()}),'已提交审核');
      if(f.dataset.decision&&ctx.can('approve')){
        const decision=e.submitter?.value,comment=String(fd.get('comment')||'');
        if(decision==='reject'&&!comment.trim()){notice('请填写退回原因。',true);return;}
        run(()=>api.review(f.dataset.decision,{version:Number(f.dataset.version),decision,comment}),decision==='approve'?'已确认定稿':'已退回修改');
      }
    }
    el.innerHTML='<div class="dw-empty" role="status">正在读取文稿档案…</div>';
    load().then(()=>{if(live()&&id&&tab==='check'&&ctx.can('operate'))run(async()=>{issues=(await api.check(id)).issues;if(live())detail();},'',false);}).catch(error=>{if(live()){frame(`<div class="dw-empty" role="alert"><strong>文稿暂时无法读取</strong><p>${esc(error.message||'请稍后重试')}</p>${button('重试','reload')}</div>`);}});
    return {unmount(){alive=false;el.removeEventListener('input',onInput);el.removeEventListener('click',onClick);el.removeEventListener('submit',onSubmit);}};
  }});
})();

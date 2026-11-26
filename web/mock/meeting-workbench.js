/* 会议工作台离线适配：和原应用共用 S.meetings / S.myTodos。 */
(function () {
  const X = window.JKAPI.ext, S = X.state, me = X.me, fail = X.err, clone = X.clone;
  const root = '/api/apps/meeting/workbench';
  const previousGuard=window.JKAPI.guard;
  window.JKAPI.guard=(method,path,body)=>{
    previousGuard?.(method,path,body);
    const match=/^\/api\/apps\/meeting\/meetings\/([^/]+)(?:\/todos\/commit)?$/.exec(path);
    if(match && (method==='PATCH'||method==='POST') && S().meetings.some(m=>m.id===match[1]&&m.ownerId)) fail(409,'INVALID_STATE','请在会议工作台核对版本、定稿和派发');
  };
  const need = action => { if (!X.can('meeting', action)) fail(403, 'FORBIDDEN', '没有会议操作权限'); };
  const members = () => S().users.filter(u => u.status === 'active' && X.can('meeting', 'view', u)).map(({ id, name }) => ({ id, name }));
  const get = id => { need('view'); const m = S().meetings.find(m => m.id === id); if (!m) fail(404, 'NOT_FOUND', '会议不存在'); if(!m.recordSnapshots){const before=clone(m);delete before.finalizedSnapshots;m.recordSnapshots={[m.version||1]:before};}return m; };
  const owner = m => { need('operate'); if (m.ownerId && m.ownerId !== me().id && !X.can('meeting', 'admin')) fail(403, 'FORBIDDEN', '仅整理负责人可操作'); };
  const day = value => { if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '') || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0,10) !== value) fail(422, 'INVALID_REQUEST', '请选择明确年月日'); return value; };
  const src = m => (m.transcript || []).map((line, i) => ({ id: m.source === 'text' || /^[PS]/.test(String(line[0])) ? line[0] : `L${i+1}`, ts: line[0], version: m.sourceVersion || 1, speaker: line[1], quote: line[2], index: i }));
  const decisionHeading=words=>{let text=String(words).trim();const heads='(?:会议决定|会议明确|一致同意|会议议定|议定|决定|结论)';if(!new RegExp('^'+heads).test(text))text=text.replace(/^[^：:\n]{1,40}[：:]\s*/,'');const match=new RegExp('^'+heads+'[：:\\s]*(.+)').exec(text);return !match||/[？?]/.test(text)||/^(?:尚未|仍未|还未|未|没有|尚不|不明确|是否|尚待|待确认|拟|可能|建议)/.test(match[1])?'讨论要点':'已明确的决定';};
  const initial = m => ({ title: m.title, body: src(m).map(s => ({ h: decisionHeading(s.quote), p: s.quote, refs: [s.id] })) });
  const minutes = m => { const result = clone(m.minutesEdited || initial(m)); result.body.forEach(p => {p.sources = src(m).filter(s => (p.refs || []).includes(s.id) || (p.refs || []).includes(s.ts));p.refs=p.sources.map(s=>s.id);}); return result; };
  function project(m) {
    const item = clone(m); delete item.finalizedSnapshots;delete item.recordSnapshots;
    Object.assign(item, { version: m.version || 1, ownerId: m.ownerId || '', owner: m.owner || '待认领', sources: src(m), sourceVersion: m.sourceVersion || 1,
      minutesStatus: m.minutesStatus || (m.transcript?.length ? '待核对' : '草稿'), processingStatus: m.transcript?.length ? '已整理' : m.processingError ? '整理失败' : '待整理', links: m.links || [] });
    item.todos = (m.todos || []).map(t => { const task = S().myTodos.find(x => x.id === t.assignment?.id); const state = task?.progressStatus==='已取消' ? '已取消' : task?.done ? '已完成' : task?.progressStatus || (t.assignment ? '待处理' : '待派发');
      return { ...t, sourceChanged:!!t.assignment&&(t.assignment.sourceVersion!==(m.sourceVersion||1)||t.assignment.finalizedVersion!==m.finalizedVersion||m.minutesStatus==='待核对'), progressStatus: state, progress: task?.note || '', history: task?.history || [], overdue: !!t.assignment && /^\d{4}-\d{2}-\d{2}$/.test(t.due) && t.due < new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' }) && !['已完成','已取消'].includes(state) }; });
    return { item, minutes: minutes(m), versions: m.finalizedVersions || [] };
  }
  function save(m) { m.version = (m.version ?? 1) + 1; m.status = m.transcript?.length ? 'done' : 'new';const snapshot=clone(m);delete snapshot.finalizedSnapshots;delete snapshot.recordSnapshots;(m.recordSnapshots||={})[m.version]=snapshot; return project(m); }
  X.on('POST', root + '/meetings/:id/candidate', (b,p) => { owner(get(p.id));fail(503,'MODEL_UNAVAILABLE','离线模式没有真实模型服务；可使用原文摘录候选或人工编辑，原纪要未改变'); });
  X.on('GET', root + '/members', () => { need('view'); return { items: members() }; });
  X.on('GET', root + '/meetings', () => { need('view'); return { items: S().meetings.map(m => project(m).item) }; });
  X.on('POST', root + '/meetings', b => { need('operate'); if (!b.title?.trim()) fail(422, 'INVALID_REQUEST', '请填写会议名称');
    const m = { id: X.nid('M'), title: b.title, date: day(b.date), type: b.type || '专题推进会', ownerId: me().id, owner: me().name, source: 'text', sourceVersion: 1, originalText: b.text || '', text: b.text || '', participants: b.participants || [],
      transcript: (b.text || '').split('\n').map((text, i) => [`P${i + 1}`, '文字记录', text]).filter(l => l[2].trim()), todos: [], links: [], version: 0 };
    m.minutesEdited = initial(m); m.minutesStatus = m.transcript.length ? '待核对' : '草稿'; S().meetings.unshift(m); return save(m); });
  X.on('GET', root + '/meetings/:id', (b, p, q) => { const m = get(p.id); if (!q.version) return project(m); const frozen = q.snapshot ? m.recordSnapshots?.[q.version] : m.finalizedSnapshots?.[q.version]; if (!frozen) fail(404, 'NOT_FOUND', '定稿版本不存在'); return project(frozen); });
  X.on('PATCH', root + '/meetings/:id', (b, p) => { const m = get(p.id); owner(m); if (b.baseVersion !== (m.version || 1)) fail(409, 'VERSION_CONFLICT', '记录已更新，请重新加载并比较');
    const next = clone(m);for(const key of ['place','host','participants'])if(b[key]!==undefined)next[key]=clone(b[key]); if (b.title) next.title = b.title; if (b.date) next.date = day(b.date);
    if (b.text !== undefined) { next.originalText ??= next.text || src(m).map(s => s.quote).join('\n'); next.text = b.text; next.sourceVersion = (next.sourceVersion || 1) + 1;
      next.transcript = b.text.split('\n').map((text,i) => [`P${i+1}`, '文字记录', text]).filter(l => l[2].trim()).concat((m.transcript||[]).filter(l=>String(l[0]).startsWith('S'))); next.minutesEdited ||= initial(m); next.minutesEdited.body.forEach(s => s.needsReview = true); }
    if (b.minutes) { const valid = src(next).map(s => s.id); if (!b.minutes.body.length || b.minutes.body.some(s => !s.p.trim() || !s.refs?.length || s.refs.some(r => !valid.includes(r)))) fail(422, 'INVALID_REFERENCE', '每段纪要须有内容和有效原文依据'); next.minutesEdited = clone(b.minutes); }
    if (b.todos) { const previous = next.todos || []; if (previous.some(t => t.assignment && !b.todos.find(x => x.id === t.id))) fail(409, 'INVALID_STATE', '不能删除已派发任务');
      next.todos = b.todos.map(t => { const old = previous.find(x => x.id === t.id); if (old?.assignment) { if (['task','ownerId','due','ref'].some(k => (t[k] || '') !== (old[k] || ''))) fail(409, 'INVALID_STATE', '已派发内容保留原依据'); return old; } return { ...t, owner: t.ownerId || '待确认', status: '待认领' }; }); }
    next.ownerId ||= me().id; next.owner ||= me().name; next.minutesStatus = next.transcript?.length ? '待核对' : '草稿'; Object.assign(m, next); return save(m); });
  X.on('POST', root + '/meetings/:id/supplements', (b,p) => {const m=get(p.id);owner(m);if(b.baseVersion!==(m.version||1))fail(409,'VERSION_CONFLICT','记录已更新');if(!b.text?.trim()||!b.source?.trim())fail(422,'INVALID_REQUEST','请填写补充内容和核实来源');
    m.minutesEdited ||= initial(m);const added={id:X.nid('S'),text:b.text,source:b.source,by:me().name,at:X.now()};(m.supplements||=[]).push(added);(m.transcript||=[]).push([added.id,'会后补充 · '+me().name,`${b.text}（来源：${b.source}；补充人：${me().name}；时间：${added.at}）`]);m.sourceVersion=(m.sourceVersion||1)+1;m.minutesStatus='待核对';m.minutesEdited.body.forEach(s=>s.needsReview=true);return save(m);});
  X.on('POST', root + '/meetings/:id/restore', (b,p) => {const m=get(p.id);owner(m);if(b.baseVersion!==(m.version||1))fail(409,'VERSION_CONFLICT','记录已更新');const previous=m.finalizedSnapshots?.[b.fromVersion];if(!previous)fail(422,'INVALID_REFERENCE','定稿版本不存在');
    for(const key of ['minutesEdited','text','transcript','source','supplements']){if(previous[key]!==undefined)m[key]=clone(previous[key]);else delete m[key];}m.sourceVersion=(m.sourceVersion||1)+1;m.minutesStatus='待核对';m.restoredFromVersion=b.fromVersion;m.minutesEdited.body.forEach(s=>s.needsReview=true);return save(m);});
  X.on('POST', root + '/meetings/:id/finalize', (b, p) => { const m = get(p.id); owner(m); if (b.baseVersion !== (m.version || 1)) fail(409, 'VERSION_CONFLICT', '请核对最新版本');
    const current = minutes(m), valid = src(m).map(s => s.id); if (!b.checked || !current.body.length || current.body.some(s => s.needsReview || !s.refs?.length || s.refs.some(r => !valid.includes(r)))) fail(409, 'INVALID_STATE', '请先核对并保存待复核内容');
    m.ownerId ||= me().id; m.owner ||= me().name; m.minutesEdited = current; m.minutesStatus = '已定稿'; m.finalizedVersion = (m.version || 1) + 1; m.finalizedBy = me().name; m.finalizedAt = X.now();
    m.finalizedVersions = [...(m.finalizedVersions || []), m.finalizedVersion]; const result = save(m), snapshot = clone(m); delete snapshot.finalizedSnapshots;delete snapshot.recordSnapshots; (m.finalizedSnapshots ||= {})[m.finalizedVersion] = snapshot; return result; });
  X.on('POST', root + '/meetings/:id/dispatch', (b, p) => { const m = get(p.id); owner(m); const selected = [...new Set(b.ids)].map(id => m.todos.find(t => t.id === id)); if (selected.some(t => !t)) fail(404, 'NOT_FOUND', '事项不存在');
    const pending = selected.filter(t => !t.assignment); if (!pending.length) return project(m); if (m.minutesStatus !== '已定稿') fail(409, 'INVALID_STATE', '请先确认纪要定稿');
    pending.forEach(t => { day(t.due); if (!members().some(u => u.id === t.ownerId) || !src(m).some(s => s.id === t.ref)) fail(422, 'INVALID_REQUEST', '请确认在用成员和来源段落'); });
    pending.forEach(t => { const recipient = members().find(u => u.id === t.ownerId); t.owner = recipient.name; t.status = '已派发'; t.assignment = { id: `MT-${m.id}-${t.id}`, recipientId: recipient.id, sender: me().name, at: new Date().toISOString(), finalizedVersion: m.finalizedVersion, sourceVersion: m.sourceVersion || 1 };
      S().myTodos.push({ id: t.assignment.id, title: t.task, task: t.task, owner: t.owner, recipientId: recipient.id, due: t.due, app: 'meeting', from: me().name, at: X.now(), done: false, ref: { meetingId: m.id, todoId: t.id, tab: 'todos' } }); }); return save(m); });
  X.on('PATCH', root + '/meetings/:id/todos/:todo/progress', (b, p) => { const m = get(p.id), t = m.todos.find(t => t.id === p.todo), task = S().myTodos.find(x => x.id === t?.assignment?.id);
    if (!task) fail(404, 'NOT_FOUND', '已派发事项不存在'); const manager = X.can('meeting','operate') && (m.ownerId === me().id || X.can('meeting','admin'));
    if ((b.status === '已取消' ? !manager : task.recipientId !== me().id && !(manager && b.status === '待处理')) || !b.note?.trim()) fail(403, 'FORBIDDEN', '请由负责人填写办理说明');
    if((task.done||task.progressStatus==='已取消')&&!['待处理',task.progressStatus].includes(b.status))fail(409,'INVALID_STATE','请先说明原因并重开为待处理');
    if (!['待处理','办理中','已完成','已取消'].includes(b.status)) fail(422, 'INVALID_REQUEST', '状态无效');
    (task.history ||= []).push({ from: task.progressStatus || '待处理', to: b.status, note: b.note, by: me().name, at: X.now() }); task.progressStatus = b.status; task.note = b.note; task.done = ['已完成','已取消'].includes(b.status); return project(m); });
  X.on('POST', root + '/meetings/:id/todos/:todo/reassign', (b,p) => {
    const m=get(p.id);owner(m);if(b.baseVersion!==(m.version||1))fail(409,'VERSION_CONFLICT','记录已更新');
    const t=m.todos.find(t=>t.id===p.todo),task=S().myTodos.find(x=>x.id===t?.assignment?.id);
    if(!task)fail(404,'NOT_FOUND','已派发事项不存在');
    if(t.assignment.recipientId!==b.previousOwnerId)fail(409,'VERSION_CONFLICT','原负责人已变更');
    if(task.done||task.progressStatus==='已取消')fail(409,'INVALID_STATE','请先说明原因重开已完成或取消的事项');
    const member=members().find(u=>u.id===b.ownerId);day(b.due);if(!member||!b.note?.trim())fail(422,'INVALID_REQUEST','请核对成员和变更原因');
    if(t.ownerId===b.ownerId&&t.due===b.due)fail(422,'INVALID_REQUEST','负责人和期限均未改变');
    const change={from:t.owner+' / '+t.due,to:member.name+' / '+b.due,note:b.note,by:me().name,at:X.now()};
    const recipients=[...new Set([t.assignment.recipientId,member.id])].filter(id=>members().some(u=>u.id===id));
    t.ownerId=member.id;t.owner=member.name;t.due=b.due;t.assignment.recipientId=member.id;
    Object.assign(task,{recipientId:member.id,owner:member.name,due:b.due,note:b.note});(task.history||=[]).push(change);
    for(const recipientId of recipients)S().myTodos.push({id:X.nid('MEETING-CHANGE'),recipientId,title:'会议事项调整',task:'会议事项调整：'+t.task,app:'meeting',kind:'notice',from:me().name,at:X.now(),ref:{meetingId:m.id,todoId:t.id},done:false});
    X.audit('会议记录','调整事项负责人或期限');return save(m);
  });
  X.first('GET', '/api/v1/todos', () => ({ items: S().myTodos.filter(t => !t.recipientId || t.recipientId === me().id) }));
  X.first('PATCH', '/api/v1/todos/:id', (b, p) => { const t = S().myTodos.find(t => t.id === p.id && (!t.recipientId || t.recipientId === me().id)); if (!t) fail(404,'NOT_FOUND','待办不存在'); const done=typeof b.done==='boolean'?b.done:b.status==='已完成'?true:undefined;if(typeof done!=='boolean')fail(422,'INVALID_REQUEST','完成状态无效');if(done===t.done)return {item:t}; if(t.done&&!done&&S().meetings.find(m=>m.id===t.ref?.meetingId)?.todos?.some(x=>x.assignment?.id===t.id&&x.assignment.finalizedVersion))fail(409,'INVALID_STATE','请在会议工作台填写原因后重开事项'); t.done = done; t.progressStatus = done ? '已完成' : '待处理'; return { item: t }; });
  function linkTarget(app, id) {
    if (!['enterprise','document'].includes(app) || !X.can(app,'view')) fail(403,'FORBIDDEN','无权访问目标应用');
    const value = app === 'enterprise' ? S().issues.find(i => i.id === id) : S().drafts[id];
    if (!value) fail(404,'NOT_FOUND','目标记录不存在'); return value;
  }
  X.on('POST', root + '/meetings/:id/links', (b,p) => { const m=get(p.id); owner(m); const value=linkTarget(b.app,b.id);
    if(b.app==='document' && (value.source?.id!==m.id || value.source?.version!==b.version)) fail(422,'INVALID_REFERENCE','文稿须来自当前会议定稿');
    if(b.sourceRef && !src(m).some(s=>s.id===b.sourceRef)) fail(422,'INVALID_REFERENCE','来源段落不存在');
    const links=m.links ||= []; if(links.some(l=>l.app===b.app && l.id===b.id)) return project(m);
    links.push({app:b.app,id:b.id,version:b.app==='document'?b.version:(m.minutesStatus==='已定稿'?m.finalizedVersion:m.version),sourceVersion:m.sourceVersion||1,finalized:b.app==='document'||m.minutesStatus==='已定稿',sourceRef:b.sourceRef||'',by:me().id,at:X.now()}); return save(m);
  });
  X.on('GET', root + '/links', (b,p,q) => { need('view');linkTarget(q.app,q.id);return {items:S().meetings.flatMap(m=>(m.links||[]).filter(l=>l.app===q.app&&l.id===q.id).map(l=>({...l,meetingId:m.id,title:m.title})))}; });
  // 任意上传在离线模式不能伪造转写。明确示例仍沿用原演示任务。
  X.first('POST', '/api/apps/meeting/meetings/:id/transcribe', (b, p) => { const m = get(p.id); owner(m); if (m.source !== 'demo' && !m.sampleId) { m.processingError = '离线模式没有真实转写服务，录音可在真实服务中上传；请粘贴文字继续'; X.save(); fail(503,'TRANSCRIBE_UNAVAILABLE',m.processingError); } m.status='running'; const id=X.nid('J'); S().jobs[id]={ id,kind:'transcribe',ref:m.id,status:'running',progress:0,step:0,steps:['音频预处理','语音识别','说话人分离','纪要整理'],started:Date.now() };m.jobId=id; return {job:S().jobs[id]}; });
})();

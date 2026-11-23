/* 接口适配 · 会议记录（接口规范 §4.3）。转写为长任务：transcribe 返回 job，轮询 job() 直到 done。 */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  // 真后端只收 multipart 表单。带真实文件（blob）时上传该文件；示例录音没有文件内容，
  // 按 source=demo 登记，由后端读取 apps/meeting/samples/demo.webm。模拟后端仍收原对象。
  const toForm = (b, audio) => {
    if (b instanceof FormData) return b;
    const form = new FormData();
    const blob = (audio instanceof Blob && audio) ||
      (typeof Blob !== 'undefined' && ((b.blob instanceof Blob && b.blob) || (b.file instanceof Blob && b.file))) || null;
    const source = b.source === '现场录音' ? 'live' : blob ? 'upload' : ['live', 'nas', 'demo'].includes(b.source) ? b.source : 'demo';
    form.append('title', b.title || '会议录音'); if (b.type) form.append('type', b.type);
    form.append('participants', JSON.stringify(b.participants || []));
    form.append('source', source);
    if (blob && source !== 'demo') form.append('file', blob, (typeof b.file === 'string' && b.file) || blob.name || 'recording.webm');
    else if (b.sampleId) form.append('sampleId', b.sampleId);
    return form;
  };
  window.JKApi.meeting = {
    /** → {items:MeetingSummary[], templates:MeetingTemplate[], hotwords:string[]} */
    list: () => H.get('/api/apps/meeting/meetings'),
    /** {title, type, participants[], file, size, source, duration?} → {item:Meeting}（上传 / 现场录音登记） */
    create: (b, audio) => H.post('/api/apps/meeting/meetings', H.mode('meeting') === 'http' ? toForm(b || {}, audio) : b),
    /** (id, {type?, title?, participants?, hotwords?}) → {job:Job} */
    transcribe: (id, b) => H.post(`/api/apps/meeting/meetings/${id}/transcribe`, b || {}),
    /** jobId → {job:{id,status,progress,step,steps[],stepName}} */
    job: (jid) => H.meetingJob(jid),
    /** id → {item:Meeting(transcript, topics, todos), minutes:Minutes|null} */
    get: (id) => H.get('/api/apps/meeting/meetings/' + id),
    /** (id, {renameSpeaker:{from,to}} | {todo:{id,owner,due}} | {minutes} | {line:{index,text}}) → {item, minutes} */
    patch: (id, b) => H.patch('/api/apps/meeting/meetings/' + id, b),
    /** (id, {ids:[todoId]}) → {committed[], skipped[]} 派发待办到“我的待办” */
    commitTodos: (id, b) => H.post(`/api/apps/meeting/meetings/${id}/todos/commit`, b),
    /** (id, {entId, title}) → {issue:Issue} 会上企业诉求关联到企业台账 */
    link: (id, b) => H.post(`/api/apps/meeting/meetings/${id}/link`, b),
  };
})();

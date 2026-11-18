/* 接口适配 · 会议记录（接口规范 §4.3）。转写为长任务：transcribe 返回 job，轮询 job() 直到 done。 */
(function () {
  const H = window.JKHttp; window.JKApi = window.JKApi || {};
  window.JKApi.meeting = {
    /** → {items:MeetingSummary[], templates:MeetingTemplate[], hotwords:string[]} */
    list: () => H.get('/api/apps/meeting/meetings'),
    /** {title, type, participants[], file, size, source, duration?} → {item:Meeting}（上传 / 现场录音登记） */
    create: (b) => H.post('/api/apps/meeting/meetings', b),
    /** (id, {type?, title?, participants?, hotwords?}) → {job:Job} */
    transcribe: (id, b) => H.post(`/api/apps/meeting/meetings/${id}/transcribe`, b || {}),
    /** jobId → {job:{id,status,progress,step,steps[],stepName}} */
    job: (jid) => H.get('/api/v1/jobs/' + jid),
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

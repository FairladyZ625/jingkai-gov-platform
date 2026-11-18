/* =====================================================================
 * 【可改】会议记录 · 文案与选项。改完刷新即可。
 * ===================================================================== */
window.JK_APPCFG = window.JK_APPCFG || {};
window.JK_APPCFG.meeting = {
  name: '会议记录',
  summary: '录音变纪要，待办直接派发',
  steps: ['选录音', '自动整理', '核对转写', '纪要与待办'],
  tabs: [['flow', '办理'], ['all', '全部会议'], ['todos', '待办总览']],
  sources: [['upload', '上传录音', 'upload'], ['live', '现场录音', 'mic'], ['nas', '会议档案', 'folder']],
  audioExt: ['mp3', 'm4a', 'wav', 'aac', 'amr', 'mp4', 'flac'],
  /* “用示例录音”：演示上传时预填的会议信息 */
  sampleUpload: { title: '数据产业企业座谈会', type: '企业座谈会', participants: ['吴强', '王敏', '星河智驾', '灵犀大模型'], file: '2026-11-18 数据产业座谈.m4a', size: '21.7 MB', duration: '28:40' },
  /* 待办 → 起草公文：按待办内容挑选公文模板（命中第一个） */
  todoToDoc: [
    { match: /征集/, templateId: 'T04', input: 'title' },
    { match: /口径|答复|告知/, templateId: 'T10', input: 'issue' },
    { match: /方案|指南/, templateId: 'T02', input: 'title' },
  ],
  owners: ['待确认'],
  text: {
    pickQ: '整理哪场会？', pickSub: '上传录音、现场录音，或从会议档案里选',
    runQ: '正在整理，可以先去忙别的', runSub: '在本地服务器转写，录音不出内网；好了会通知你',
    checkQ: '核对转写', checkSub: '点时间可回放，黄色是没听清的地方，点一下就能改',
    outQ: '纪要与待办', outSub: '纪要点段落可直接改；待办补齐负责人后再派发',
    noAccess: '你的账号没有会议记录的权限',
    local: '本地转写 · 不出内网',
  },
};

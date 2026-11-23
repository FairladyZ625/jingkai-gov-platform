// 只放测试输入；不提供问答映射、不写审批结果、不扩大空间权限。
(function () {
  if (!window.T38?.ready || JK_CONFIG.api.mode !== 'mock') throw Error('非文件隔离模式');
  JK_CONFIG.api.baseUrl = ''; JK_CONFIG.showDevPlan = false;
  JK_CONFIG.stateKey = window.JK_STATE_KEY = 't38:offline:state';
  // 这些是浏览器内可公开的角色卡片，无外部身份、无秘密；刷新即销毁。
  for (const u of [...JK_DATA.users, ...JK_CONFIG.demoAccounts]) u.password = '';
  const common = {title:'【T38虚拟】双桐台帐说明', kind:'隔离样本', org:'虚拟资料组',
    date:'2026-11-22', status:'现行有效', version:1, example:true, source:'隔离夹具',
    url:'https://t38.example.invalid/double', space:'policy'};
  for (const [id, space, text] of [
    ['A','policy','双桐台帐的公开受理日为每周三。'], ['B','policy','双桐台帐的公开受理日为每周三。'],
    ['C','policy','双桐台帐的公开归档日为每周五。'], ['D','enterprise','双桐台帐的内部复核日为每周四。'],
  ]) JK_KB_EXAMPLES.push({...common, id:'T38-DUP-'+id, space, text});
})();

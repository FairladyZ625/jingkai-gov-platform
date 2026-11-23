/* =====================================================================
 * 【可改】账号 · 组织 · 角色 · 授权（复用 haiknow 的 identity / rbac / admin_identity 模型）
 *  - 改这里的数据后，点右下角头像 →“重置演示数据”即可生效
 *  - 运行中在“管理后台”里改的内容（新增账号、改角色、改授权）也会立即生效，并保存在本机浏览器
 * ===================================================================== */
(function () {
  const D = window.JK_DATA;

  /* 组织：部门树（haiknow org.js：部门 + 岗位；有成员或子部门的部门不能删除） */
  D.departments = [
    { id: 'd-root', name: '北京经开区管委会', parent: null },
    { id: 'd-cyc', name: '产业促进局', parent: 'd-root' },
    { id: 'd-qyfw', name: '企业服务处', parent: 'd-cyc' },
    { id: 'd-zcdx', name: '政策兑现科', parent: 'd-cyc' },
    { id: 'd-zhk', name: '综合科', parent: 'd-cyc' },
    { id: 'd-swjr', name: '商务金融局', parent: 'd-root' },
    { id: 'd-kj', name: '科技和产业促进局', parent: 'd-root' },
    { id: 'd-ai', name: 'AI 工作组', parent: 'd-root' },
    { id: 'd-ext', name: '外部协作单位', parent: null },
    { id: 'd-yzsk', name: '亦智数科（合作企业）', parent: 'd-ext' },
  ];

  /* 角色（至少四类）；mask=true 表示该角色看企业联系人电话、营收等字段时自动打码 */
  D.roles = [
    { id: 'admin', name: '管理员', desc: '管理账号、角色授权、模型接入、留痕；拥有全部动作', mask: false },
    { id: 'leader', name: '审签领导', desc: '使用全部应用，审签公文、确认台账入库、审核技能上架', mask: false },
    { id: 'member', name: '经办人员', desc: '使用四个业务应用、资料库，创建并共享自己的技能', mask: false },
    { id: 'partner', name: '外部协作者', desc: '只能查看被授权的应用与资料；敏感字段自动打码，不能修改台账', mask: true },
  ];

  /* 动作（haiknow GRANT_ACTIONS）：查看 / 操作 / 审签 / 管理 */
  D.grantActions = [['view', '查看'], ['operate', '操作'], ['approve', '审签'], ['admin', '管理']];

  /* 授权矩阵：行=角色，列=应用（* 表示全部应用）。勾选即生效 */
  D.grants = {
    admin: { '*': ['view', 'operate', 'approve', 'admin'] },
    leader: { '*': ['view', 'operate', 'approve'] },  // 含 kb / skills / computer
    member: { policy: ['view', 'operate'], enterprise: ['view', 'operate'], meeting: ['view', 'operate'], document: ['view', 'operate'], kb: ['view', 'operate'], skills: ['view', 'operate'], computer: ['view', 'operate'] },
    partner: { policy: ['view'], enterprise: ['view'], kb: ['view'], skills: ['view', 'operate'] },
  };

  /* 账号：演示环境密码明文写在这里并显示在登录页；正式环境由 haiknow passwords.py 加盐哈希存储 */
  const U = (id, username, password, name, deptId, title, role, extra) => Object.assign({ id, username, password, name, deptId, title, role, status: 'active', lastLogin: '—' }, extra || {});
  D.users = [
    U('u-zhanglei', 'admin', 'admin123', '张磊', 'd-ai', '平台管理员', 'admin'),
    U('u-liyang', 'liyang', 'jk123456', '李阳', 'd-cyc', '处长', 'leader'),
    U('u-zhengli', 'zhengli', 'jk123456', '郑丽', 'd-zcdx', '科长', 'leader'),
    U('u-wangmin', 'wangmin', 'jk123456', '王敏', 'd-qyfw', '经办', 'member'),
    U('u-zhaoqian', 'zhaoqian', 'jk123456', '赵倩', 'd-zcdx', '经办', 'member'),
    U('u-sunting', 'sunting', 'jk123456', '孙婷', 'd-zhk', '文秘', 'member'),
    U('u-liuxiang', 'liuxiang', 'jk123456', '刘翔', 'd-qyfw', '服务专员', 'member'),
    U('u-chenhao', 'chenhao', 'jk123456', '陈浩', 'd-qyfw', '服务专员', 'member'),
    U('u-fengyu', 'fengyu', 'jk123456', '冯宇', 'd-qyfw', '服务专员', 'member'),
    U('u-zhoujing', 'zhoujing', 'jk123456', '周静', 'd-swjr', '经办', 'member'),
    U('u-wuqiang', 'wuqiang', 'jk123456', '吴强', 'd-kj', '经办', 'member'),
    U('u-hejun', 'hejun', 'jk123456', '何军', 'd-yzsk', 'AI 工程师', 'partner'),
    U('u-tangxin', 'tangxin', 'jk123456', '唐鑫', 'd-yzsk', '产品经理', 'partner'),
    U('u-xuping', 'xuping', 'jk123456', '许平', 'd-qyfw', '服务专员（已调岗）', 'member', { status: 'disabled' }),
  ];

  /* 登录页“一键登录”卡片：每个角色一个代表账号 */
  D.quickLogin = ['wangmin', 'liyang', 'admin', 'hejun'];

  /* 平台设置（haiknow settings.js：平台名称、登录后默认首页、会话时长） */
  D.settings = { platformName: '经开区共享智能体工作站', orgName: '北京经开区 · AI 工作组', sessionHours: 8, defaultHome: 'chat', watermark: false };

  D.session = null; // 当前登录会话：{ userId, at }
})();

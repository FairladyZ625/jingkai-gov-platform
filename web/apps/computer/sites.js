/* =====================================================================
 * 电脑操作 · 被操作系统的“模拟画面”（只负责画页面，不含业务逻辑）。
 * 每个可操作元素带 data-vc="名字"，与 mock/computer.js 操作脚本里的 sel 对应。
 * 真实部署时这一层换成远程浏览器的实时画面 / 截图流。
 * ===================================================================== */
(function () {
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const v = (P, k) => esc((P.vals || {})[k] || '');
  const inp = (P, k, label, o = {}) => `<div class="vs-f ${o.wide ? 'wide' : ''}"><label>${esc(label)}${o.req ? '<i>*</i>' : ''}</label><input class="vs-in" data-vc="${k}" ${o.type ? `type="${o.type}"` : ''} value="${v(P, k)}" placeholder="${esc(o.ph || '')}" ${o.mask ? `data-mask="${o.mask}"` : ''}>${o.hint ? `<span class="vs-hint">${esc(o.hint)}</span>` : ''}</div>`;
  const bar = (name, nav, on) => `<div class="vs-top"><span class="vs-logo">${esc(name.slice(0, 1))}</span><b>${esc(name)}</b><span class="vs-sp"></span>${(nav || []).map((n) => `<span class="vs-nav ${n === on ? 'on' : ''}">${esc(n)}</span>`).join('')}</div>`;
  const short = (t) => String(t || '').replace(/^.*关于开展/, '').replace(/申报的通知$/, '').replace(/的通知$/, '');
  const stTag = (s) => `<span class="vs-tag ${/通过|受理|已提交|申报中/.test(s) ? 'ok' : /补正|退回|截止/.test(s) ? 'bad' : 'mid'}">${esc(s)}</span>`;

  const PAGES = {
    login(R, P) {
      return `${bar('北京市统一身份认证平台', ['帮助中心'], '')}<div class="vs-center"><div class="vs-card vs-login">
        <div class="vs-tabs"><span class="${P.corp ? '' : 'on'}" data-vc="tab-person">个人登录</span><span class="${P.corp ? 'on' : ''}" data-vc="tab-corp">法人登录</span></div>
        ${inp(P, 'code', '统一社会信用代码', { mask: 'code', ph: '18 位代码' })}${inp(P, 'user', '经办人账号', { ph: '用户名' })}${inp(P, 'pwd', '密码', { type: 'password', mask: 'pwd' })}
        <div class="vs-f"><label>短信验证码</label><div class="vs-row"><input class="vs-in" data-vc="otp" value="${v(P, 'otp')}" placeholder="6 位验证码" data-mask="otp"><button class="vs-btn ghost" data-vc="getotp">${P.otpSent ? '已发送 58s' : '获取验证码'}</button></div></div>
        <button class="vs-btn pri block" data-vc="login">登 录</button><div class="vs-mini">登录即同意《统一身份认证服务协议》</div></div></div>`;
    },
    portal(R, P) {
      return `${bar('经开区政策兑现综合服务平台', ['首页', '政策申报', '我的申报', '通知公告'], '政策申报')}<div class="vs-pad"><div class="vs-h">正在申报的事项</div>
        ${(R.openItems || []).map((n, i) => `<div class="vs-item"><div class="vs-grow"><div class="vs-it">${esc(short(n.title))}</div><div class="vs-mini">${esc(n.org)} · ${n.window ? esc(n.window.start + ' 至 ' + n.window.end) : '以通知为准'}</div></div>${stTag(n.status)}<button class="vs-btn pri sm" data-vc="apply-${i}">我要申报</button></div>`).join('')}</div>`;
    },
    form(R, P) {
      const f = R.fields || []; const F = (k) => f.find((x) => x[0] === k) || [k, k];
      const fld = (k, o) => { const x = F(k); return inp(P, k, x[1], Object.assign({ mask: x[3], hint: x[4] }, o || {})); };
      return `${bar('经开区政策兑现综合服务平台', ['首页', '政策申报', '我的申报'], '政策申报')}<div class="vs-pad">
        <div class="vs-crumb">政策申报 › ${esc(short(R.notice && R.notice.title))} › 在线填报</div>
        <div class="vs-sec">一、申报主体信息</div><div class="vs-grid">${fld('name', { wide: true, req: 1 })}${fld('code', { req: 1 })}${fld('addr', { req: 1 })}${fld('contact', { req: 1 })}${fld('phone', { req: 1 })}${fld('emp')}${fld('rev')}</div>
        <div class="vs-sec">二、申报内容</div><div class="vs-grid">${fld('proj', { wide: true, req: 1 })}${fld('amount', { req: 1 })}</div>
        <div class="vs-sec">三、申报材料</div>${['营业执照（副本）', '活动方案及预算'].map((l, i) => `<div class="vs-up"><span>${esc(l)}</span><span class="vs-sp"></span>${(P.ups || {})['up-' + i] ? `<span class="vs-file">✓ ${esc(P.ups['up-' + i])}</span>` : '<span class="vs-mini">未上传</span>'}<button class="vs-btn ghost sm" data-vc="up-${i}">上传</button></div>`).join('')}
        <label class="vs-check" data-vc="promise"><span class="vs-box ${(P.checks || {}).promise ? 'on' : ''}"></span>本单位承诺所填信息真实有效，愿承担相应法律责任（信用承诺）</label>
        <div class="vs-actions"><button class="vs-btn" data-vc="save">暂存</button><button class="vs-btn pri" data-vc="submit">电子签章并提交</button></div></div>`;
    },
    receipt(R, P) {
      const r = R.result || {};
      return `${bar('经开区政策兑现综合服务平台', ['首页', '政策申报', '我的申报'], '我的申报')}<div class="vs-center"><div class="vs-card vs-ok"><div class="vs-okc">✓</div><div class="vs-h">申报已提交</div>
        <div class="vs-kv"><span>受理编号</span><b>${esc(r.no || '—')}</b></div><div class="vs-kv"><span>提交时间</span><b>${esc(r.at || '—')}</b></div><div class="vs-kv"><span>当前状态</span>${stTag('已提交')}</div>
        <div class="vs-mini">请在“我的申报”中关注形式审查结果</div></div></div>`;
    },
    stats(R, P) {
      const f = R.fields || [];
      return `${bar('统计联网直报平台', ['待填报表', '已报报表', '通知'], '待填报表')}<div class="vs-pad"><div class="vs-crumb">2026 年 › 月报 › B204-1 服务业财务状况</div>
        <div class="vs-grid">${f.map(([k, l]) => inp(P, k, l, { req: k !== 'rd' })).join('')}</div>
        ${P.verify ? '<div class="vs-verify">平台审核：<b>0</b> 个错误，<b>1</b> 个提示（本月营收环比 +4.2%，在合理范围）</div>' : ''}
        <div class="vs-actions"><button class="vs-btn" data-vc="verify">数据审核</button><button class="vs-btn" data-vc="save">保存</button><button class="vs-btn pri" data-vc="submit">上报</button></div></div>`;
    },
    'stats-ok'(R, P) { return `${bar('统计联网直报平台', ['待填报表', '已报报表'], '已报报表')}<div class="vs-center"><div class="vs-card vs-ok"><div class="vs-okc">✓</div><div class="vs-h">报表已上报</div><div class="vs-kv"><span>报表</span><b>${esc((R.result || {}).no || 'B204-1')}</b></div><div class="vs-kv"><span>上报时间</span><b>${esc((R.result || {}).at || '')}</b></div></div></div>`; },
    nlist(R, P) {
      return `${bar('北京经济技术开发区', ['首页', '政务公开', '通知公告', '政策文件'], '通知公告')}<div class="vs-pad"><div class="vs-h">通知公告</div>
        ${(R.notices || []).map((n, i) => `<div class="vs-item link" data-vc="n-${i}"><div class="vs-grow"><div class="vs-it clip">${esc(n.title)}</div><div class="vs-mini">${esc(n.org)}</div></div>${stTag(n.status)}<span class="vs-mini">${esc(n.date)}</span></div>`).join('')}</div>`;
    },
    ndetail(R, P) {
      const n = R.notice || {};
      return `${bar('北京经济技术开发区', ['首页', '政务公开', '通知公告'], '通知公告')}<div class="vs-pad vs-article"><div class="vs-at">${esc(n.title)}</div><div class="vs-mini vs-c">${esc(n.org)} · ${esc(n.date)}</div>
        <div class="vs-meta">${n.window ? `<span>申报时间：<b>${esc(n.window.start)} 至 ${esc(n.window.end)}</b></span>` : ''}${(n.basis || []).map((b) => `<span>依据：${esc(b.no || b.title)}</span>`).join('')}</div>
        <p>${esc(n.excerpt || '')}……</p>
        <div class="vs-att"><span>附件：</span><a data-vc="att">${esc(n.title.slice(0, 24))}….html</a>${P.downloaded ? '<span class="vs-file">✓ 已下载</span>' : ''}</div>
        <div class="vs-mini">原文：${esc(n.url || '')}</div></div>`;
    },
    mine(R, P) {
      return `${bar('经开区政策兑现综合服务平台', ['首页', '政策申报', '我的申报'], '我的申报')}<div class="vs-pad"><div class="vs-h">我的申报</div>
        <table class="vs-tbl"><thead><tr><th>受理编号</th><th>事项</th><th>提交时间</th><th>状态</th><th>下一步</th></tr></thead><tbody>
        ${(R.apps || []).map((a, i) => `<tr data-vc="row-${i}"><td class="mono">${esc(a.no)}</td><td>${esc(a.title)}</td><td>${esc(a.submitted)}</td><td>${stTag(a.status)}</td><td>${esc(a.next)}</td></tr>`).join('') || '<tr><td colspan="5">暂无申报记录</td></tr>'}</tbody></table></div>`;
    },
  };
  window.JKCuSites = { render: (page, R, P) => (PAGES[page] ? PAGES[page](R, P) : `<div class="vs-pad">空白页</div>`), pages: Object.keys(PAGES) };
})();

const labels = [
  ['开场', '王敏工作台与开场字幕'],
  ['政策兑现', '企业核对、补填再算、告知单'],
  ['企业走访', '一企一档、走访写入、台账筛选'],
  ['会议纪要', '录音转写与纪要、重新派发待办'],
  ['公文协作', '新文稿、核查、同一文稿送审签、版本比对'],
  ['知识库', '带出处回答、网址导入、无依据提示'],
  ['技能中心', '新技能创建与发布、同事技能运行'],
  ['电脑操作', '申报提交前确认、提交回执、通知入库'],
  ['审签', '李阳通过本次送审单、对应文稿已定稿'],
  ['外部协作者', '何军首次打开 E002，响应电话与营收脱敏、可见联系人电话打码'],
  ['管理后台', '授权矩阵、模型与能力路由、审计日志'],
  ['浅色主题', '浅色切换、恢复深色并返回王敏、结束字幕'],
];

// 在页面内观察一次真实一键演示。保留写入回执的 ID，避免把预置数据
// 或其他文稿的通用提示当成本轮操作结果。各标签内的检查独立取证。
function installChecks() {
  const trace = [];
  function observe(target, name, project) {
    const call = target[name];
    target[name] = async function (...args) {
      const by = JKShell.S.me.username;
      const segment = JKDemo.state.i;
      const result = await call.apply(this, args);
      trace.push({ segment, by, name, ...project(result, args) });
      return result;
    };
  }
  const { enterprise, meeting, document: docs, skills, reviews, computer } = JKApi;
  const themes = [];
  const setTheme = JKShell.setTheme;
  JKShell.setTheme = theme => {
    setTheme(theme);
    if (JKDemo.state.on && JKDemo.state.i === 11) themes.push(theme);
  };
  observe(enterprise, 'visit', r => ({
    id: r.visit.id, entId: r.visit.entId, proposals: r.proposals.map(p => p.id),
  }));
  observe(enterprise, 'decide', r => ({ id: r.item.id, status: r.item.status }));
  observe(meeting, 'create', (r, [b]) => ({ id: r.item.id, file: b.file }));
  observe(meeting, 'commitTodos', r => ({ count: r.committed.length }));
  observe(docs, 'draft', r => ({ id: r.item.id, title: r.item.title }));
  observe(docs, 'check', (r, [id]) => ({ id, issueCount: r.issues.length }));
  observe(docs, 'submit', r => ({
    id: r.item.id, reviewId: r.review.id, ref: r.review.ref,
    assignee: r.review.assignee, status: r.review.status,
  }));
  observe(reviews, 'decide', (r, [id, b]) => ({
    id, reviewId: r.item.id, ref: r.item.ref, status: r.item.status, decision: b.decision,
  }));
  observe(skills, 'create', r => ({ id: r.item.id }));
  observe(skills, 'publish', r => ({ id: r.item.id, status: r.item.status }));
  observe(computer, 'confirm', (r, [id, b]) => ({
    id, kind: b.kind, decision: b.decision, receipt: r.item.result?.no,
  }));

  const visible = selector => [...document.querySelectorAll(selector)].filter(el => el.getClientRects().length);
  const contains = (selector, pattern) => visible(selector).some(el => pattern.test(el.innerText));
  const panel = app => '.pview.on[data-view="' + app + '"] ';
  const reply = pattern => contains('#chatcol .msg.ai .txt', pattern);
  const user = username => JKShell.S.me?.username === username;
  const caption = pattern => contains('.demo-caption', pattern);
  const events = (segment, name) => trace.filter(event => event.segment === segment && event.name === name);

  function submittedDraft() {
    const draft = events(4, 'draft').find(d => d.by === 'wangmin' && /数据券.*延期/.test(d.title));
    if (!draft?.id) return;
    const review = events(4, 'submit').find(r => r.by === 'wangmin' && r.id === draft.id &&
      r.ref === draft.id && r.reviewId && r.assignee === '李阳' && r.status === 'pending');
    if (review) return { docId: draft.id, reviewId: review.reviewId };
  }

  const e002 = JK_DATA.enterprises.find(e => e.id === 'E002');
  const e001 = JK_DATA.enterprises.find(e => e.id === 'E001');
  const sampleRecording = JK_SAMPLE_FILES.find(file => file.id === 'rec-1117');
  const phones = e002.contacts.map(contact => contact.phone);
  const expectedPhones = phones.map(phone => phone.slice(0, 3) + '****' + phone.slice(-4));
  const matchesMaskedPhones = actual => phones.length > 0 &&
    phones.every(phone => /^\d{11}$/.test(phone)) &&
    actual.length === expectedPhones.length && actual.every((phone, i) => phone === expectedPhones[i]);

  let partnerProfileRequested = false;
  let firstPartnerProfile;
  const getProfile = enterprise.get;
  enterprise.get = async function (id) {
    const { on, i } = JKDemo.state;
    if (!on || i !== 9 || !user('hejun') || id !== e002.id || partnerProfileRequested) {
      return getProfile.call(this, id);
    }
    partnerProfileRequested = true;
    const response = await getProfile.call(this, id);
    const item = response?.item;
    firstPartnerProfile = {
      correctCompany: item?.id === id,
      maskedPhones: matchesMaskedPhones(item?.contacts?.map(contact => contact.phone) ?? []),
      restrictedRevenue: item?.revenue?.value === '***',
    };
    return response;
  };

  const partnerPanel = panel('enterprise');
  const partnerProfileVisible = () => user('hejun') &&
    visible(partnerPanel + '[data-op="enterprise.profile"]').some(el => el.innerText.includes(e002.name));
  let firstRenderedContacts;
  function renderedContactsMasked() {
    if (firstRenderedContacts !== undefined) return firstRenderedContacts;
    if (!firstPartnerProfile?.correctCompany || !partnerProfileVisible()) return false;
    const contacts = visible(partnerPanel + '#eptab .ent-kv')
      .find(field => field.firstElementChild?.textContent === '联系人');
    if (!contacts) return false;
    firstRenderedContacts = matchesMaskedPhones([...contacts.querySelectorAll('.num')]
      .filter(phone => phone.checkVisibility({ visibilityProperty: true, opacityProperty: true }))
      .map(phone => phone.innerText.trim())) && phones.every(phone => !contacts.innerText.includes(phone));
    return firstRenderedContacts;
  }

  const probes = [
    [
      ['王敏工作台', () => user('wangmin') && contains('.hello', /王敏/)],
      ['开场字幕', () => caption(/这是经办人员王敏的工作台：一个对话框，说一句话 AI 就替你办/)],
    ],
    [
      ['企业核对', () => reply(/项可进一步核对/)],
      ['补填并重新核对', () => reply(/重新核对：\d+ 项可核对/)],
      ['告知单列出事项', () => visible(panel('policy') + '[data-op="policy.notice-text"]')
        .some(el => /^1\. .+/m.test(el.value)) && reply(/告知单已生成/)],
    ],
    [
      ['打开一企一档', () => visible(panel('enterprise') + '[data-op="enterprise.profile"]')
        .some(el => el.innerText.includes(e002.name))],
      ['本次走访及其建议已实际写入', () => events(2, 'visit').some(v => v.entId === e001.id &&
        v.proposals.length && v.proposals.every(id => events(2, 'decide')
          .some(d => d.id === id && d.status === 'accepted')) &&
        JKAPI.state().visits.some(saved => saved.id === v.id && saved.entId === v.entId)) &&
        reply(/已写入 \d+ 条，变更已留痕/)],
      ['高新技术企业筛选', () => reply(/高新技术企业共 \d+ 家/)],
    ],
    [
      ['本次上传的录音已整理并含发言人和纪要', () => events(3, 'create')
        .some(event => event.file === sampleRecording.name && JKAPI.state().meetings
          .some(m => m.id === event.id && m.status === 'done' && m.transcript.some(line => line[1] && line[2]) &&
            m.topics.length > 0)) && reply(/录音「.*」已整理：\d+ 段转写/)],
      ['派发本次选中的待办', () => events(3, 'commitTodos').some(event => event.count > 0) && reply(/已派发 \d+ 条/)],
    ],
    [
      ['创建延期通知', () => events(4, 'draft').some(d => d.by === 'wangmin' && d.id && /数据券.*延期/.test(d.title))],
      ['核查本次文稿', () => events(4, 'check').some(c => c.issueCount > 0 && events(4, 'draft').some(d => d.id === c.id))],
      ['将本次文稿送李阳审签', submittedDraft],
      ['第 1 版与第 2 版比对回执', () => reply(/第 1 版 → 第 2 版：新增/)],
    ],
    [
      ['回答正文和同一回答的出处', () => visible('#chatcol .msg.ai').some(el =>
        el.querySelector('.txt')?.innerText.trim() &&
        [...el.querySelectorAll('.src[data-cid] a[title="官网原文"]')].some(link => link.protocol === 'https:'))],
      ['网址导入有结果', () => reply(/已入库：|库里已经有这份资料了/)],
      ['无依据时说明找不到', () => contains(panel('kb') + '[data-op="kb.answer"]', /未找到依据/)],
    ],
    [
      ['新技能已创建并发布', () => events(6, 'publish').some(p => p.by === 'wangmin' &&
        p.status === 'published' && events(6, 'create').some(c => c.id === p.id)) && reply(/技能「.*」已发布/)],
      ['运行同事的技能', () => reply(/「.*」已运行/)],
    ],
    [
      ['提交前停下并显示确认按钮', () => !events(7, 'confirm').length &&
        contains(panel('computer') + '[data-op="computer.wait"]', /停在「提交」前/) &&
        contains('[data-o="确认提交"]', /确认提交/)],
      ['确认后取得同一次申报回执', () => events(7, 'confirm')
        .some(event => event.kind === '提交' && event.decision === 'approve' && event.receipt) &&
        reply(/已为.*提交申报，受理编号/)],
      ['下载的通知已入知识库', () => reply(/已把《.*》存进知识库/)],
    ],
    [
      ['李阳通过同一审签单且该文稿已定稿', () => {
        const draft = submittedDraft();
        if (!draft || !user('liyang')) return false;
        const { docId, reviewId } = draft;
        return events(8, 'decide').some(r => r.by === 'liyang' && r.id === reviewId &&
          r.reviewId === reviewId && r.ref === docId && r.status === 'done' && r.decision === 'approve') &&
          JKAPI.state().drafts[docId]?.status === '已定稿' && contains('.toast', /已通过/);
      }],
    ],
    [
      ['何军可见正确企业档案和脱敏提示', () => partnerProfileVisible() &&
        contains(partnerPanel + '.ap > .callout', /外部协作者视图：联系人电话、营收已打码/) &&
        contains(partnerPanel + '[data-op="enterprise.brief"]', /30 秒速览/)],
      ['首次档案响应的联系人电话已打码', () => firstPartnerProfile?.correctCompany && firstPartnerProfile.maskedPhones],
      ['同一次档案响应的营业收入为受限值', () => firstPartnerProfile?.correctCompany && firstPartnerProfile.restrictedRevenue],
      ['首次档案实际显示的联系人电话已打码', renderedContactsMasked],
    ],
    [
      ['外部协作者的授权矩阵', () => user('admin') &&
        contains(panel('admin') + '[data-tab="grants"].on', /角色与授权/) &&
        contains(panel('admin') + '[data-op="admin.grant-partner"]', /外部协作者/) &&
        visible(panel('admin') + '.mtx [data-mask="partner"]').length > 0],
      ['可见模型列表和能力路由', () => user('admin') &&
        contains(panel('admin') + '[data-tab="models"].on', /模型/) &&
        contains(panel('admin') + '.adm-body', /能力路由/) && visible(panel('admin') + '[data-m]').length > 0],
      ['审计日志及导出入口', () => user('admin') &&
        contains(panel('admin') + '[data-csv]', /导出 CSV/) && visible(panel('admin') + '.audit-row').length > 0],
    ],
    [
      ['实际切换到浅色', () => themes.includes('light') && document.documentElement.dataset.theme === 'light' && caption(/深色、浅色两套主题/)],
      ['回到王敏工作台和深色主题，显示演示结束', () => themes.includes('dark') && document.documentElement.dataset.theme === 'dark' &&
        user('wangmin') && caption(/演示结束/)],
    ],
  ];

  const seen = probes.map(() => new Set());
  let inspectionError;
  function sample() {
    const { on, i } = JKDemo.state;
    try {
      if (on) {
        for (const [name, check] of probes[i]) {
          if (!seen[i].has(name) && check()) seen[i].add(name);
        }
      }
      requestAnimationFrame(sample);
    } catch (error) {
      inspectionError = error;
    }
  }
  requestAnimationFrame(sample);

  window.demoRegression = {
    inspect(i) {
      if (inspectionError) throw inspectionError;
      const { on, i: active } = JKDemo.state;
      const missing = probes[i].filter(([name]) => !seen[i].has(name)).map(([name]) => name);
      if (!missing.length || !on || active > i) return { missing, active: on && active === i };
      return false;
    },
    submittedDraft,
  };
}

module.exports = { labels, installChecks };

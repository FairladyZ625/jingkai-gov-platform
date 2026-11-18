// 应用模板前端：保存 → 提交确认 → 导出。页面组件统一从 /sdk/ui/index.js 取，接口只走 ctx.api()。
import { v1 } from '/sdk/haiknow.js';
import { installMockFromQuery } from '/sdk/mock/index.js';
import {
  ensureStyles,
  h,
  PageHeader,
  WorkbenchLayout,
  FormField,
  Input,
  Textarea,
  Table,
  StatusTag,
  Button,
  EmptyState,
  ForbiddenState,
  Notice,
  showToast,
} from '/sdk/ui/index.js';

// ?mock= 只替换本应用的数据接口；登录、目录、权限仍走真平台。应用在 iframe 里，读父页面的查询串。
installMockFromQuery(window.parent === window ? location.search : window.parent.location.search);

const STATUS_TEXT = {
  draft: '草稿',
  pending: '待确认',
  needs_info: '待补充',
  confirmed: '已确认',
  recheck: '需重新核对',
};
const STEPS = ['录入草稿', '提交确认', '主管复核', '导出归档'];

export function statusLabel(status) {
  if (status == null || status === '') return '草稿';
  const label = STATUS_TEXT[status];
  if (!label) {
    console.warn(`[模板] 未登记的业务状态：${status}，按「需重新核对」展示`);
    return '需重新核对';
  }
  return label;
}

function statusTag(status) {
  return StatusTag({ status: statusLabel(status) });
}

export async function mount(el, ctx) {
  ensureStyles();
  await ctx.preview.errors.load(); // 读取 web/errors.json 里登记的自定义错误码中文提示

  let me = null;
  let project = null;
  let projectName = '';
  let projectNames = null;
  let records = [];
  let reviews = { todo: [], submitted: [] };
  let artifacts = [];
  let busy = false;
  let editing = null;
  const draft = { title: '', content: '' };

  function notify(message, tone = 'info') {
    showToast(message, tone, { duration: 2600 });
  }

  async function load() {
    me = await v1.me();
    // 外壳在 iframe 查询串里传入当前项目；只接受当前账号可见的项目，看不到就退回第一个可见项目。
    const requested = new URLSearchParams(location.search).get('project');
    project = requested && me.projects.includes(requested) ? requested : me.projects[0] || null;
    if (!project) {
      projectName = '';
      records = [];
      reviews = { todo: [], submitted: [] };
      artifacts = [];
      return;
    }
    if (!projectNames) {
      const tree = await v1.projects();
      projectNames = new Map(
        (tree.companies || []).flatMap((company) => (company.projects || []).map((item) => [item.id, item.name]))
      );
    }
    projectName = projectNames.get(project) || project;
    const [r, q, a] = await Promise.all([
      ctx.api(`/records?project=${encodeURIComponent(project)}`),
      ctx.api('/reviews'),
      ctx.api(`/artifacts?project=${encodeURIComponent(project)}`),
    ]);
    records = r.items || [];
    // 待办接口不认项目参数，按当前项目已加载的记录收窄，避免把其他项目的待办带进来。
    const recordIds = new Set(records.map((record) => record.id));
    const reviewData = q || { todo: [], submitted: [] };
    reviews = {
      todo: (reviewData.todo || []).filter((review) => recordIds.has(review.recordId)),
      submitted: (reviewData.submitted || []).filter((review) => recordIds.has(review.recordId)),
    };
    artifacts = a.items || [];
  }

  async function run(action, message) {
    busy = true;
    render();
    try {
      await action();
      await load();
      notify(message, 'success');
    } catch (e) {
      notify(ctx.preview.errors.message(e), 'error');
    } finally {
      busy = false;
      render();
    }
  }

  const titleOf = (record) => record?.data?.title || '（未命名）';

  async function download(record) {
    const id = record.recordId || record.id;
    const version = record.version ? `?version=${record.version}` : '';
    const text = await ctx.api(`/records/${id}/export${version}`);
    const href = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
    const link = h('a', { href, download: `记录-${id}.csv` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(href), 0);
  }

  const decide = (review, decision) => run(
    () => ctx.api(`/reviews/${review.id}/decisions`, { json: { version: review.version, decision } }),
    decision === 'confirm' ? '已确认' : '已退回',
  );

  function section(title, ...children) {
    return h('section', { class: 'hk-stack-sm' }, h('h3', { class: 'hk-panel-title' }, title), ...children);
  }

  function createCard() {
    const title = Input({
      id: 'record-title',
      name: 'title',
      required: true,
      value: draft.title,
      placeholder: '标题（必填）',
      onInput: (value) => { draft.title = value; },
    });
    const content = Textarea({
      id: 'record-content',
      name: 'content',
      rows: 3,
      value: draft.content,
      placeholder: '补充说明（可选）',
      onInput: (value) => { draft.content = value; },
    });
    return h(
      'form',
      {
        class: 'hk-stack-sm',
        novalidate: true,
        onSubmit: (e) => {
          e.preventDefault();
          if (!draft.title.trim()) return notify('请填写标题', 'error');
          return run(async () => {
            await ctx.api('/records', { json: { project, title: draft.title.trim(), content: draft.content } });
            draft.title = '';
            draft.content = '';
          }, '已保存');
        },
      },
      FormField({ label: '标题', id: 'record-title', required: true, sourceTag: '人工录入', control: title }),
      FormField({ label: '内容', id: 'record-content', sourceTag: '人工录入', control: content }),
      h(
        'div',
        { class: 'hk-btn-row' },
        Button({
          label: '保存',
          variant: 'primary',
          type: 'submit',
          disabled: busy || !ctx.can('operate'),
        })
      )
    );
  }

  function editCard() {
    const title = Input({
      id: 'record-title',
      name: 'title',
      required: true,
      value: editing.title,
      onInput: (value) => { editing.title = value; },
    });
    const content = Textarea({
      id: 'record-content',
      name: 'content',
      rows: 3,
      value: editing.content,
      onInput: (value) => { editing.content = value; },
    });
    const save = () => run(async () => {
      try {
        await ctx.api(`/records/${editing.id}`, {
          method: 'PUT',
          json: { baseVersion: editing.version, title: editing.title.trim(), content: editing.content },
        });
        editing = null;
      } catch (e) {
        if (e.code === 'version_conflict') {
          const latest = await ctx.api(`/records/${editing.id}`);
          editing.version = latest.version;
        }
        throw e;
      }
    }, '已保存');
    return h(
      'form',
      {
        class: 'hk-stack-sm',
        novalidate: true,
        onSubmit: (e) => {
          e.preventDefault();
          if (!editing.title.trim()) return notify('请填写标题', 'error');
          return save();
        },
      },
      FormField({ label: '标题', id: 'record-title', required: true, sourceTag: '已存记录', control: title }),
      FormField({ label: '内容', id: 'record-content', sourceTag: '已存记录', control: content }),
      h(
        'div',
        { class: 'hk-btn-row' },
        Button({ label: '保存修改', variant: 'primary', type: 'submit', disabled: busy }),
        Button('取消', () => { editing = null; render(); }, { variant: 'ghost', disabled: busy })
      )
    );
  }

  function recordActions(record) {
    if (busy) return h('span', {}, '处理中…');
    const actions = [];
    if (['draft', 'needs_info', 'recheck'].includes(record.status) && ctx.can('operate')) {
      actions.push(
        Button('编辑', () => {
          editing = { id: record.id, version: record.version, status: record.status, title: titleOf(record), content: record.data?.content || '' };
          render();
        }, { size: 'sm' })
      );
      if (record.status !== 'recheck') {
        actions.push(
          Button(
            '提交确认',
            () => run(() => ctx.api(`/records/${record.id}/submit`, { json: {} }), '已提交，等待确认'),
            { variant: 'primary', size: 'sm' }
          )
        );
      }
    }
    if (record.status === 'confirmed') {
      actions.push(Button('导出 CSV', () => run(() => download(record), '已导出'), { size: 'sm' }));
    }
    if (actions.length) return h('div', { class: 'hk-btn-row' }, ...actions);
    return h('span', {}, record.status === 'pending' ? '等待确认' : '—');
  }

  function recordsCard() {
    return section(
      `记录（${records.length}）`,
      records.length
        ? Table({
            caption: '记录列表',
            columns: [
              { key: 'title', title: '标题', render: (r) => titleOf(r) },
              { key: 'status', title: '状态', render: (r) => statusTag(r.status) },
              { key: 'version', title: '版本', render: (r) => `v${r.version}` },
              { key: 'submitter', title: '提交人' },
              { key: 'actions', title: '操作', render: recordActions },
            ],
            rows: records,
          })
        : EmptyState({ title: '还没有记录', detail: '在左侧新建一条记录并提交确认。' })
    );
  }

  function todoCard() {
    if (!reviews.todo.length) return null;
    return section(
      `待我确认（${reviews.todo.length}）`,
      Table({
        caption: '待我确认',
        columns: [
          { key: 'title', title: '标题', render: (r) => titleOf(records.find((x) => x.id === r.recordId)) },
          { key: 'submitter', title: '提交人' },
          { key: 'version', title: '版本', render: (r) => `v${r.version}` },
          {
            key: 'actions',
            title: '操作',
            render: (r) =>
              h(
                'div',
                { class: 'hk-btn-row' },
                Button('确认', () => decide(r, 'confirm'), { variant: 'primary', size: 'sm', disabled: busy }),
                Button('退回', () => decide(r, 'return'), { size: 'sm', disabled: busy })
              ),
          },
        ],
        rows: reviews.todo,
      })
    );
  }

  function submittedCard() {
    if (!reviews.submitted.length) return null;
    return section(
      `我提交的（${reviews.submitted.length}）`,
      Table({
        caption: '我提交的',
        columns: [
          { key: 'title', title: '标题', render: (r) => titleOf(records.find((x) => x.id === r.recordId)) },
          { key: 'version', title: '版本', render: (r) => `v${r.version}` },
          { key: 'status', title: '状态', render: (r) => statusTag(r.status) },
        ],
        rows: reviews.submitted,
      })
    );
  }

  function artifactsCard() {
    return section(
      `已确认成果（${artifacts.length}）`,
      artifacts.length
        ? Table({
            caption: '已确认成果',
            columns: [
              { key: 'title', title: '标题', render: (a) => titleOf(a) },
              { key: 'version', title: '版本', render: (a) => `v${a.version}` },
              { key: 'confirmedBy', title: '确认人' },
              {
                key: 'actions',
                title: '操作',
                render: (a) => Button('导出 CSV', () => run(() => download(a), '已导出'), { size: 'sm', disabled: busy }),
              },
            ],
            rows: artifacts,
          })
        : EmptyState({ title: '暂无已确认成果', detail: '记录确认后会出现在这里。' })
    );
  }

  function currentStage() {
    if (artifacts.length) return 3;
    if (reviews.todo.length || records.some((r) => r.status === 'pending')) return 2;
    if (records.length) return 1;
    return 0;
  }

  function render() {
    el.className = 'hk-ui-scope hk-prototype-page hk-stack';
    el.replaceChildren();
    if (!project) {
      const cards = [
        PageHeader({ eyebrow: '业务办理工作台', title: '__APP_NAME__', meta: `用户：${ctx.user.name || ctx.user.id}` }),
        EmptyState({ title: '当前账号没有可见项目', detail: '请联系管理员分配项目范围后再使用本应用。' }),
      ];
      el.append(...cards.filter(Boolean));
      return;
    }

    const current = records[0];
    const roleText = ctx.can('approve') ? '可确认' : ctx.can('operate') ? '可提交' : '只读';
    const cards = [
      PageHeader({
        eyebrow: '业务办理工作台',
        title: '__APP_NAME__',
        meta: `用户：${ctx.user.name || ctx.user.id}（${ctx.user.role || '未分配角色'}） · 项目：${projectName} · 权限：${roleText}`,
        actions: [statusTag(current?.status)],
      }),
      WorkbenchLayout({
        steps: STEPS,
        currentStep: currentStage(),
        leftTitle: editing ? `编辑记录 v${editing.version}` : '新建记录',
        leftBadge: statusTag(editing ? editing.status : 'draft'),
        left: ctx.can('operate')
          ? (editing ? editCard() : createCard())
          : ForbiddenState({
              title: '当前角色为只读',
              detail: '切换到具备「可提交」权限的角色（如办理员）可新建或修改记录。',
              requiredRole: '办理员',
              action: '新建与修改草稿',
            }),
        rightTitle: '记录与确认',
        rightBadge: statusTag(current?.status),
        right: h(
          'div',
          { class: 'hk-stack' },
          recordsCard(),
          todoCard(),
          submittedCard(),
          artifactsCard()
        ),
      }),
    ];
    el.append(...cards.filter(Boolean));
  }

  try {
    await load();
  } catch (e) {
    el.className = 'hk-ui-scope hk-prototype-page hk-stack';
    el.replaceChildren(
      PageHeader({ eyebrow: '业务办理工作台', title: '__APP_NAME__' }),
      Notice(ctx.preview.errors.message(e), 'danger')
    );
    return;
  }
  render();
}
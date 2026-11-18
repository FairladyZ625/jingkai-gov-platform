// HAiKnow 平台统一界面组件库（/sdk/ui/index.js）
// 零构建原生 ES Module：自动挂载 /web/tokens.css 与 /sdk/ui/ui.css，无需构建工具或外部 CDN。

const THEME_STORAGE_KEY = 'haiknow-theme';

// 五个固定业务状态（名称与颜色语义强制固定，见《视觉与界面规范》）
export const BUSINESS_STATUSES = Object.freeze({
  draft: { key: 'draft', label: '草稿', className: 'hk-status-draft' },
  needs_supplement: { key: 'needs_supplement', label: '待补充', className: 'hk-status-supplement' },
  pending_confirm: { key: 'pending_confirm', label: '待确认', className: 'hk-status-pending' },
  confirmed: { key: 'confirmed', label: '已确认', className: 'hk-status-confirmed' },
  needs_recheck: { key: 'needs_recheck', label: '需重新核对', className: 'hk-status-recheck' },
});

const BUSINESS_STATUS_BY_LABEL = Object.freeze(
  Object.fromEntries(Object.values(BUSINESS_STATUSES).map((s) => [s.label, s]))
);

// 四个后台任务状态（与业务确认状态严格区分：“任务跑完”不等于“业务已确认”）
export const TASK_STATUSES = Object.freeze({
  queued: { key: 'queued', label: '排队', className: 'hk-task-queued' },
  running: { key: 'running', label: '运行', className: 'hk-task-running' },
  failed: { key: 'failed', label: '失败', className: 'hk-task-failed' },
  cancelled: { key: 'cancelled', label: '取消', className: 'hk-task-cancelled' },
});

const TASK_STATUS_BY_LABEL = Object.freeze(
  Object.fromEntries(Object.values(TASK_STATUSES).map((s) => [s.label, s]))
);

const SVG_PATHS = Object.freeze({
  folder: 'M3 6h7l2 2h9v12H3z M3 6V4h7l2 2',
  file: 'M5 2h9l5 5v15H5z M14 2v6h5 M8 13h8 M8 17h6',
  upload: 'M12 16V4 m-5 5 5-5 5 5 M4 17v3h16v-3',
  check: 'm5 12 4 4L19 6',
  alert: 'm12 3 10 18H2z M12 9v5 M12 18h.01',
  clock: 'M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0 M12 6v6l4 3',
  lock: 'M5 11h14v10H5z M8 11V7a4 4 0 0 1 8 0v4',
  refresh: 'M21 12a9 9 0 1 1-2.64-6.36 M21 3v6h-6',
  sun: 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z M12 1v2 M12 21v2 M4.22 4.22l1.42 1.42 M18.36 18.36l1.42 1.42 M1 12h2 M21 12h2 M4.22 19.78l1.42-1.42 M18.36 5.64l1.42-1.42',
  moon: 'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z',
});

export function ensureStyles() {
  if (typeof document === 'undefined') return;
  const links = [
    ['hk-tokens-css', '/web/tokens.css'],
    ['hk-ui-css', '/sdk/ui/ui.css'],
  ];
  for (const [id, href] of links) {
    if (!document.getElementById(id)) {
      const link = document.createElement('link');
      link.id = id;
      link.rel = 'stylesheet';
      link.href = href;
      document.head.append(link);
    }
  }
  if (!document.documentElement.dataset.theme) {
    initTheme();
  }
}

export function getTheme() {
  if (typeof document === 'undefined') return 'light';
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

export function setTheme(theme) {
  const next = theme === 'dark' ? 'dark' : 'light';
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // 忽略隐私模式存储限制
    }
  }
  return next;
}

export function initTheme() {
  if (typeof document === 'undefined') return 'light';
  try {
    const params = new URLSearchParams(window.location.search);
    const hashQuery = window.location.hash.includes('?')
      ? new URLSearchParams(window.location.hash.split('?')[1])
      : null;
    const forced = params.get('theme') || (hashQuery && hashQuery.get('theme'));
    if (forced === 'dark' || forced === 'light') {
      return setTheme(forced);
    }
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return setTheme(saved === 'dark' ? 'dark' : 'light');
  } catch {
    return setTheme('light');
  }
}

export function toggleTheme() {
  return setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith('on') && typeof v === 'function') {
      el.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (k === 'class' || k === 'className') {
      el.className = v;
    } else if (k === 'dataset' && typeof v === 'object') {
      for (const [dk, dv] of Object.entries(v)) {
        if (dv != null) el.dataset[dk] = String(dv);
      }
    } else if (k in el && (k === 'value' || k === 'checked' || k === 'disabled' || k === 'readOnly' || k === 'selected')) {
      el[k] = v;
    } else {
      el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  const appendChild = (c) => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) {
      c.forEach(appendChild);
    } else {
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
  };
  children.forEach(appendChild);
  return el;
}

export function svgIcon(name, className = 'hk-state-icon') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', className);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', SVG_PATHS[name] || SVG_PATHS.folder);
  svg.append(path);
  return svg;
}

// 1. 主题切换器组件
export function ThemeSwitch({ onChange } = {}) {
  ensureStyles();
  const wrap = h('div', { class: 'hk-theme-switch', role: 'group', 'aria-label': '切换浅色或深色主题' });
  const render = () => {
    const current = getTheme();
    wrap.replaceChildren(
      ...[['light', '浅色'], ['dark', '深色']].map(([mode, label]) =>
        h(
          'button',
          {
            type: 'button',
            class: `hk-theme-btn ${current === mode ? 'active' : ''}`,
            'aria-pressed': current === mode ? 'true' : 'false',
            dataset: { themeMode: mode },
            onClick: () => {
              setTheme(mode);
              render();
              wrap.querySelector(`[data-theme-mode="${mode}"]`).focus();
              if (onChange) onChange(mode);
            },
          },
          label
        )
      )
    );
  };
  render();
  return wrap;
}

// 2. 按钮组件（主 / 次 / 危险 / 幽灵）
export function Button(labelOrProps, onClickOrOpts, maybeOpts = {}) {
  ensureStyles();
  let props;
  if (typeof labelOrProps === 'object' && labelOrProps !== null && !(labelOrProps instanceof Node)) {
    props = labelOrProps;
  } else {
    const isFn = typeof onClickOrOpts === 'function';
    const opts = isFn ? maybeOpts : (onClickOrOpts || {});
    props = { ...opts, label: labelOrProps, onClick: isFn ? onClickOrOpts : opts.onClick };
  }
  const {
    label = '',
    variant = props.primary ? 'primary' : props.danger ? 'danger' : 'secondary',
    size = 'md',
    disabled = false,
    type = 'button',
    title,
    ariaLabel,
    id,
    dataset,
    onClick,
  } = props;

  const classes = ['hk-ui-btn'];
  if (variant && variant !== 'secondary') classes.push(variant);
  if (size === 'sm') classes.push('sm');

  return h(
    'button',
    {
      id,
      type,
      class: classes.join(' '),
      disabled,
      title,
      'aria-label': ariaLabel,
      dataset,
      onClick,
    },
    label
  );
}

// 3. 五个固定业务状态标签（草稿 / 待补充 / 待确认 / 已确认 / 需重新核对）
export function StatusTag(statusOrProps, opts = {}) {
  ensureStyles();
  const isObj = typeof statusOrProps === 'object' && statusOrProps !== null;
  const status = isObj ? statusOrProps.status : statusOrProps;
  const { id, title } = isObj ? statusOrProps : opts;
  const def = BUSINESS_STATUSES[status] || BUSINESS_STATUS_BY_LABEL[status];
  if (!def) {
    return h(
      'span',
      {
        id,
        class: 'hk-status-tag hk-status-draft',
        dataset: { statusKey: 'unknown', statusInvalid: 'true' },
        title: title || '非标准业务状态词',
      },
      String(status || '草稿')
    );
  }
  return h(
    'span',
    {
      id,
      class: `hk-status-tag ${def.className}`,
      dataset: { statusKey: def.key },
      title: title || `业务状态：${def.label}`,
    },
    def.label
  );
}

// 4. 四个后台任务状态组件（排队 / 运行 / 失败 / 取消，与业务状态区分）
export function TaskStatus(statusOrProps, opts = {}) {
  ensureStyles();
  const isObj = typeof statusOrProps === 'object' && statusOrProps !== null;
  const status = isObj ? statusOrProps.status : statusOrProps;
  const { taskId = '', title = '', detail = '', progress, onCancel, onRetry } = isObj ? statusOrProps : opts;
  const def = TASK_STATUSES[status] || TASK_STATUS_BY_LABEL[status] || TASK_STATUSES.queued;
  const prefixText = title || (taskId ? `任务 #${taskId}` : '任务');
  const progressText = typeof progress === 'number' ? ` ${progress}%` : '';
  const node = h(
    'span',
    {
      class: `hk-task-status ${def.className}`,
      role: 'status',
      dataset: { taskStatus: def.key },
    },
    h('span', { class: 'hk-task-dot', 'aria-hidden': 'true' }),
    h('span', { class: 'hk-task-prefix' }, `${prefixText} ·`),
    h('span', { class: 'hk-task-label' }, `${def.label}${progressText}`),
    detail ? h('span', { class: 'hk-task-detail' }, `（${detail}）`) : null
  );
  if ((def.key === 'queued' || def.key === 'running') && typeof onCancel === 'function') {
    node.append(Button('取消任务', onCancel, { variant: 'ghost', size: 'sm' }));
  }
  if (def.key === 'failed' && typeof onRetry === 'function') {
    node.append(Button('重试', onRetry, { variant: 'ghost', size: 'sm' }));
  }
  return node;
}

// 5. 基础输入控件：Input / Select / DateInput / Textarea / Checkbox / FileUpload
export function Input({
  id,
  name,
  type = 'text',
  value = '',
  placeholder = '',
  unit = '',
  required = false,
  disabled = false,
  readOnly = false,
  min,
  max,
  step = type === 'number' ? 'any' : undefined,
  ariaLabel,
  describedBy,
  onInput,
  onChange,
} = {}) {
  ensureStyles();
  const inputEl = h('input', {
    id,
    name,
    type,
    class: 'hk-input',
    value,
    placeholder,
    required,
    disabled,
    readOnly,
    min,
    max,
    step,
    'aria-label': ariaLabel,
    'aria-required': required ? 'true' : undefined,
    'aria-describedby': describedBy,
    onInput: onInput ? (e) => onInput(e.target.value, e) : undefined,
    onChange: onChange ? (e) => onChange(e.target.value, e) : undefined,
  });
  if (!unit) return inputEl;
  const group = h('div', { class: 'hk-input-group' }, inputEl, h('span', { class: 'hk-input-addon' }, unit));
  group.inputElement = inputEl;
  return group;
}

export function DateInput(props = {}) {
  return Input({ ...props, type: 'date', unit: '' });
}

export function Select({
  id,
  name,
  value = '',
  options = [],
  required = false,
  disabled = false,
  ariaLabel,
  describedBy,
  onChange,
} = {}) {
  ensureStyles();
  return h(
    'select',
    {
      id,
      name,
      class: 'hk-select',
      required,
      disabled,
      'aria-label': ariaLabel,
      'aria-required': required ? 'true' : undefined,
      'aria-describedby': describedBy,
      onChange: onChange ? (e) => onChange(e.target.value, e) : undefined,
    },
    options.map((opt) => {
      const optVal = typeof opt === 'object' ? opt.value : opt;
      const optLabel = typeof opt === 'object' ? opt.label : opt;
      return h('option', { value: optVal, selected: String(value) === String(optVal) }, optLabel);
    })
  );
}

export function Textarea({
  id,
  name,
  value = '',
  placeholder = '',
  rows = 3,
  required = false,
  disabled = false,
  readOnly = false,
  ariaLabel,
  describedBy,
  onInput,
  onChange,
} = {}) {
  ensureStyles();
  return h('textarea', {
    id,
    name,
    class: 'hk-textarea',
    rows,
    value,
    placeholder,
    required,
    disabled,
    readOnly,
    'aria-label': ariaLabel,
    'aria-required': required ? 'true' : undefined,
    'aria-describedby': describedBy,
    onInput: onInput ? (e) => onInput(e.target.value, e) : undefined,
    onChange: onChange ? (e) => onChange(e.target.value, e) : undefined,
  });
}

export function Checkbox({ id, name, checked = false, label = '', required = false, disabled = false, describedBy, onChange } = {}) {
  ensureStyles();
  const input = h('input', {
    id,
    name,
    type: 'checkbox',
    checked,
    required,
    disabled,
    'aria-describedby': describedBy,
    onChange: onChange ? (e) => onChange(e.target.checked, e) : undefined,
  });
  const box = h('label', { class: 'hk-check-row' }, input, h('span', {}, label));
  box.inputElement = input;
  return box;
}

export function FileUpload({
  id,
  name,
  accept = '',
  label = '选择或拖入文件',
  hint = '',
  required = false,
  disabled = false,
  describedBy,
  onFile,
} = {}) {
  ensureStyles();
  const statusEl = h('span', { class: 'hk-upload-meta' }, hint || (accept ? `支持格式：${accept}` : '点击或拖拽文件到此区域'));
  const handleFile = (file) => {
    if (!file || disabled) return;
    statusEl.textContent = `已选择：${file.name}（${Math.max(1, Math.round(file.size / 1024))} KB）`;
    if (onFile) onFile(file);
  };
  const input = h('input', {
    id,
    name,
    type: 'file',
    accept,
    required,
    disabled,
    hidden: true,
    'aria-describedby': describedBy,
    onChange: (e) => e.target.files && e.target.files[0] && handleFile(e.target.files[0]),
  });
  const box = h(
    'label',
    {
      class: 'hk-upload-box',
      tabindex: disabled ? '-1' : '0',
      role: 'button',
      'aria-label': label,
      'aria-required': required ? 'true' : undefined,
      'aria-disabled': disabled ? 'true' : undefined,
      'aria-describedby': describedBy,
      onKeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          input.click();
        }
      },
      onDragover: (e) => {
        e.preventDefault();
        box.classList.add('dragover');
      },
      onDragleave: () => box.classList.remove('dragover'),
      onDrop: (e) => {
        e.preventDefault();
        box.classList.remove('dragover');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
          handleFile(e.dataTransfer.files[0]);
        }
      },
    },
    input,
    h('span', { class: 'hk-upload-title' }, label),
    statusEl
  );
  return box;
}

// 6. 带单位、必填标记、来源说明与逐格错误定位的表单项（FormField & Form）
let fieldCounter = 0;

export function FormField({
  key,
  name,
  id,
  label = '',
  required = false,
  unit = '',
  source = '',
  sourceTag = '',
  error = '',
  wide = false,
  type = 'text',
  value = '',
  options = [],
  placeholder = '',
  accept = '',
  disabled = false,
  readOnly = false,
  control,
  onInput,
  onChange,
  onFile,
} = {}) {
  ensureStyles();
  fieldCounter += 1;
  const fieldKey = key || name || id || `field_${fieldCounter}`;
  const resolvedSource = source || sourceTag;
  const inputId = id || `hk_input_${fieldKey}_${fieldCounter}`;
  const errId = `${inputId}_err`;

  const errNode = h(
    'p',
    {
      id: errId,
      class: 'hk-field-error',
      role: 'alert',
      hidden: !error,
    },
    error
  );

  let controlNode = control;
  if (!controlNode) {
    if (type === 'select') {
      controlNode = Select({ id: inputId, name: fieldKey, value, options, required, disabled, describedBy: errId, onChange: onChange || onInput });
    } else if (type === 'date') {
      controlNode = DateInput({ id: inputId, name: fieldKey, value, required, disabled, readOnly, describedBy: errId, onChange: onChange || onInput });
    } else if (type === 'textarea') {
      controlNode = Textarea({ id: inputId, name: fieldKey, value, placeholder, required, disabled, readOnly, describedBy: errId, onInput, onChange });
    } else if (type === 'file') {
      controlNode = FileUpload({ id: inputId, name: fieldKey, accept, label: placeholder || '选择或拖入文件', required, disabled, describedBy: errId, onFile });
    } else if (type === 'checkbox') {
      controlNode = Checkbox({ id: inputId, name: fieldKey, checked: Boolean(value), label: placeholder || label, required, disabled, describedBy: errId, onChange: onChange || onInput });
    } else {
      controlNode = Input({ id: inputId, name: fieldKey, type, value, placeholder, unit, required, disabled, readOnly, describedBy: errId, onInput, onChange });
    }
  }

  const focusTarget = controlNode.inputElement || controlNode;
  if (error) {
    focusTarget.setAttribute('aria-invalid', 'true');
  }

  const metaParts = [];
  if (unit) metaParts.push(h('span', { class: 'hk-unit-badge', title: '字段单位' }, `单位: ${unit}`));
  if (resolvedSource) metaParts.push(h('span', { class: 'hk-source-tag', title: '字段来源' }, resolvedSource));

  const wrapper = h(
    'div',
    {
      class: `hk-field ${wide ? 'wide' : ''} ${error ? 'has-error' : ''}`.trim(),
      dataset: { fieldKey },
    },
    h(
      'div',
      { class: 'hk-field-head' },
      h(
        'label',
        { class: 'hk-field-label', for: inputId },
        label,
        required ? h('span', { class: 'hk-required', 'aria-hidden': 'true', title: '必填项' }, '*') : null
      ),
      metaParts.length ? h('div', { class: 'hk-field-meta' }, ...metaParts) : null
    ),
    controlNode,
    errNode
  );

  wrapper.setError = (msg = '') => {
    const hasErr = Boolean(msg);
    wrapper.classList.toggle('has-error', hasErr);
    errNode.textContent = msg || '';
    errNode.hidden = !hasErr;
    if (hasErr) {
      focusTarget.setAttribute('aria-invalid', 'true');
    } else {
      focusTarget.removeAttribute('aria-invalid');
    }
  };
  wrapper.focusControl = () => {
    if (typeof focusTarget.focus === 'function') focusTarget.focus();
  };
  wrapper.fieldKey = fieldKey;
  return wrapper;
}

export function Form({ fields = [], values = {}, errors = {}, actions = [], onChange, onSubmit } = {}) {
  ensureStyles();
  const state = { ...values };
  const fieldMap = new Map();

  const grid = h(
    'div',
    { class: 'hk-field-grid' },
    fields.map((f) => {
      const k = f.key || f.name || f.id;
      const node = FormField({
        ...f,
        key: k,
        value: state[k] !== undefined ? state[k] : (f.value ?? ''),
        error: errors[k] || f.error || '',
        onInput: (val) => {
          state[k] = val;
          node.setError('');
          if (onChange) onChange(k, val, { ...state });
        },
        onChange: (val) => {
          state[k] = val;
          node.setError('');
          if (onChange) onChange(k, val, { ...state });
        },
        onFile: (file) => {
          state[k] = file;
          node.setError('');
          if (onChange) onChange(k, file, { ...state });
        },
      });
      if (state[k] === undefined && f.value !== undefined) {
        state[k] = f.value;
      }
      fieldMap.set(k, { def: f, node });
      return node;
    })
  );

  const formEl = h(
    'form',
    {
      class: 'hk-form',
      novalidate: true,
      onSubmit: (e) => {
        e.preventDefault();
        if (onSubmit) onSubmit(formEl.getValues());
      },
    },
    grid,
    actions.length ? h('div', { class: 'hk-btn-row hk-form-actions' }, ...actions) : null
  );

  formEl.getValues = () => ({ ...state });
  formEl.setValues = (nextValues = {}) => {
    for (const [k, v] of Object.entries(nextValues)) {
      state[k] = v;
      const entry = fieldMap.get(k);
      if (entry) {
        const inputEl = entry.node.querySelector('input, select, textarea');
        if (inputEl && inputEl.type !== 'file') {
          if (inputEl.type === 'checkbox') inputEl.checked = Boolean(v);
          else inputEl.value = v ?? '';
        }
        entry.node.setError('');
      }
    }
  };
  formEl.clearErrors = () => formEl.setErrors({});
  formEl.setErrors = (errMap = {}) => {
    let firstInvalid = null;
    for (const [k, { node }] of fieldMap.entries()) {
      const msg = errMap[k] || '';
      node.setError(msg);
      if (msg && !firstInvalid) firstInvalid = node;
    }
    if (firstInvalid) firstInvalid.focusControl();
  };
  formEl.validate = () => {
    const nextErrors = {};
    for (const [k, { def }] of fieldMap.entries()) {
      const v = state[k];
      if (def.disabled) continue;
      if (def.required && (v === '' || v == null || (def.type === 'checkbox' && v === false))) {
        nextErrors[k] = `${def.label}为必填项，请补齐后再提交`;
        continue;
      }
      if (typeof def.validate === 'function') {
        const msg = def.validate(v, state);
        if (msg) nextErrors[k] = msg;
      }
    }
    formEl.setErrors(nextErrors);
    return { valid: Object.keys(nextErrors).length === 0, errors: nextErrors, values: formEl.getValues() };
  };
  return formEl;
}

// 7. 表格组件（窄屏局部横滑，整页不横滑）
export function Table(columnsOrProps, rowsArg, optsArg = {}) {
  ensureStyles();
  const props = Array.isArray(columnsOrProps)
    ? { columns: columnsOrProps, rows: rowsArg || [], ...optsArg }
    : (columnsOrProps || {});
  const { columns = [], rows = [], emptyText = '暂无记录', caption = '数据明细表', onRowClick } = props;

  if (!rows.length) {
    return EmptyState({ title: emptyText });
  }

  return h(
    'div',
    { class: 'hk-table-wrap', role: 'region', 'aria-label': caption, tabindex: '0' },
    h(
      'table',
      { class: 'hk-ui-table' },
      h(
        'thead',
        {},
        h(
          'tr',
          {},
          columns.map((col) =>
            h(
              'th',
              { class: col.align === 'right' || col.numeric ? 'hk-cell-num' : '' },
              col.unit ? `${col.title} (${col.unit})` : col.title
            )
          )
        )
      ),
      h(
        'tbody',
        {},
        rows.map((row, idx) =>
          h(
            'tr',
            {
              class: onRowClick ? 'hk-clickable-row' : '',
              tabindex: onRowClick ? '0' : undefined,
              onClick: onRowClick ? () => onRowClick(row, idx) : undefined,
              onKeydown: onRowClick
                ? (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onRowClick(row, idx);
                    }
                  }
                : undefined,
            },
            columns.map((col) => {
              const content = col.render ? col.render(row, idx) : row[col.key];
              return h('td', { class: col.align === 'right' || col.numeric ? 'hk-cell-num' : '' }, content ?? '—');
            })
          )
        )
      )
    )
  );
}

// 8. 卡片、指标与提示横幅
export function Card({ title = '', badge = null, action = null, actions = null, footer = null, className = '', children } = {}, ...rest) {
  ensureStyles();
  const bodyChildren = children !== undefined ? [children, ...rest] : rest;
  const headerAction = action || (Array.isArray(actions) && actions.length ? h('div', { class: 'hk-btn-row' }, ...actions) : actions);
  return h(
    'section',
    { class: `hk-panel ${className}`.trim() },
    title || badge || headerAction
      ? h(
          'header',
          { class: 'hk-panel-head' },
          h('div', { class: 'hk-panel-heading' }, h('h3', { class: 'hk-panel-title' }, title), badge),
          headerAction
        )
      : null,
    h('div', { class: 'hk-panel-body' }, ...bodyChildren),
    footer ? h('footer', { class: 'hk-panel-foot' }, footer) : null
  );
}

export function MetricGrid(itemsOrProps = []) {
  ensureStyles();
  const items = Array.isArray(itemsOrProps) ? itemsOrProps : (itemsOrProps.items || []);
  return h(
    'div',
    { class: 'hk-metric-grid' },
    items.map((it) =>
      h(
        'div',
        { class: 'hk-metric' },
        h('strong', { class: 'hk-metric-value' }, it.unit ? `${it.value} ${it.unit}` : String(it.value)),
        h('span', { class: 'hk-metric-label' }, it.label)
      )
    )
  );
}

export function Notice(textOrProps, tone = 'info') {
  ensureStyles();
  const isObj = typeof textOrProps === 'object' && textOrProps !== null && !(textOrProps instanceof Node);
  const text = isObj ? (textOrProps.text || textOrProps.children || textOrProps.title || '') : textOrProps;
  const resolvedTone = isObj ? (textOrProps.tone || 'info') : tone;
  const toneMap = { info: '', blue: '', warn: 'amber', warning: 'amber', amber: 'amber', error: 'red', danger: 'red', red: 'red', ok: 'green', success: 'green', green: 'green' };
  const cls = toneMap[resolvedTone] || '';
  return h('div', { class: `hk-notice ${cls}`.trim(), role: cls === 'red' ? 'alert' : 'note' }, text);
}

// 9. 步骤条、标签页、页面头与左右两栏办理页布局
export function StepStrip(names = [], current = 0) {
  ensureStyles();
  return h(
    'ol',
    { class: 'hk-step-strip', 'aria-label': '业务办理步骤' },
    names.map((name, i) => {
      const stateClass = i < current ? 'done' : i === current ? 'current' : '';
      return h(
        'li',
        { class: `hk-step-node ${stateClass}`.trim(), 'aria-current': i === current ? 'step' : undefined },
        h('span', { class: 'hk-step-num' }, i < current ? '✓' : String(i + 1)),
        h('span', {}, name)
      );
    })
  );
}

export function Tabs({ items = [], active, onChange } = {}) {
  ensureStyles();
  const bar = h('div', { class: 'hk-tabs', role: 'tablist' });
  const buttons = items.map((it, idx) => {
    const key = typeof it === 'object' ? it.key : it;
    const label = typeof it === 'object' ? it.label : it;
    const isSelected = key === active;
    return h(
      'button',
      {
        type: 'button',
        role: 'tab',
        class: `hk-tab ${isSelected ? 'active' : ''}`,
        'aria-selected': isSelected ? 'true' : 'false',
        tabindex: isSelected ? '0' : '-1',
        dataset: { tabKey: key },
        onClick: () => onChange && onChange(key),
        onKeydown: (e) => {
          if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            e.preventDefault();
            const dir = e.key === 'ArrowRight' ? 1 : -1;
            const nextIdx = (idx + dir + buttons.length) % buttons.length;
            buttons[nextIdx].focus();
            buttons[nextIdx].click();
          }
        },
      },
      label
    );
  });
  bar.append(...buttons);
  return bar;
}

export function PageHeader({ eyebrow = '', title = '', meta = '', actions = [], showThemeSwitch = true, onThemeChange } = {}) {
  ensureStyles();
  const actionNodes = [...actions];
  if (showThemeSwitch) {
    actionNodes.push(ThemeSwitch({ onChange: onThemeChange }));
  }
  return h(
    'div',
    { class: 'hk-page-head' },
    h(
      'div',
      { class: 'hk-page-head-main' },
      eyebrow ? h('div', { class: 'hk-eyebrow' }, eyebrow) : null,
      h('h1', { class: 'hk-page-title' }, title),
      meta ? h('p', { class: 'hk-page-meta' }, meta) : null
    ),
    h('div', { class: 'hk-page-actions' }, ...actionNodes)
  );
}

export function WorkbenchLayout({
  steps = [],
  currentStep = 0,
  leftTitle = '输入与操作',
  leftBadge = null,
  leftAction = null,
  leftContent = null,
  left = null,
  leftFooter = null,
  rightTitle = '结果与下一步',
  rightBadge = null,
  rightAction = null,
  rightContent = null,
  right = null,
  rightFooter = null,
  asymmetric = false,
} = {}) {
  ensureStyles();
  return h(
    'div',
    { class: 'hk-workbench-wrap' },
    steps.length ? StepStrip(steps, currentStep) : null,
    h(
      'div',
      { class: `hk-workbench ${asymmetric ? 'asymmetric' : ''}`.trim() },
      h(
        'div',
        { class: 'hk-workbench-col' },
        Card({ title: leftTitle, badge: leftBadge, action: leftAction, footer: leftFooter }, leftContent ?? left)
      ),
      h(
        'div',
        { class: 'hk-workbench-col' },
        Card({ title: rightTitle, badge: rightBadge, action: rightAction, footer: rightFooter }, rightContent ?? right)
      )
    )
  );
}

// 10. 空 / 加载 / 失败 / 无权限四类状态视图
export function StateView({
  kind = 'empty',
  title = '',
  detail = '',
  description = '',
  meta = '',
  actions = [],
} = {}) {
  ensureStyles();
  const resolvedDetail = detail || description;
  const iconMap = { empty: 'folder', loading: 'refresh', error: 'alert', forbidden: 'lock' };
  const roleMap = { empty: 'status', loading: 'status', error: 'alert', forbidden: 'alert' };
  const iconEl = svgIcon(iconMap[kind] || 'folder', `hk-state-icon ${kind === 'loading' ? 'spin' : ''}`.trim());

  return h(
    'div',
    {
      class: `hk-state-view ${kind}`,
      role: roleMap[kind] || 'status',
      dataset: { stateKind: kind },
    },
    iconEl,
    h('h4', { class: 'hk-state-title' }, title),
    resolvedDetail ? h('p', { class: 'hk-state-detail' }, resolvedDetail) : null,
    meta ? h('div', { class: 'hk-state-meta' }, meta) : null,
    actions.length ? h('div', { class: 'hk-state-actions' }, ...actions) : null
  );
}

export function EmptyState({ title = '暂无记录', detail = '', description = '', action = null, actionLabel = '', onAction } = {}) {
  const actions = [];
  if (action) actions.push(action);
  if (actionLabel && onAction) actions.push(Button(actionLabel, onAction, { variant: 'secondary', size: 'sm' }));
  return StateView({ kind: 'empty', title, detail: detail || description, actions });
}

export function LoadingState({ title = '正在处理任务', detail = '', description = '', taskId = '', onCancel } = {}) {
  const actions = onCancel ? [Button('取消任务', onCancel, { variant: 'secondary', size: 'sm' })] : [];
  return StateView({
    kind: 'loading',
    title,
    detail: detail || description,
    meta: taskId ? `任务号：${taskId}` : '',
    actions,
  });
}

export function ErrorState({
  title = '处理失败',
  detail = '',
  description = '',
  code = '',
  taskId = '',
  retryLabel = '重试',
  onRetry,
  secondaryLabel = '',
  onSecondary,
} = {}) {
  const actions = [];
  if (onRetry) actions.push(Button(retryLabel, onRetry, { variant: 'primary', size: 'sm' }));
  if (secondaryLabel && onSecondary) actions.push(Button(secondaryLabel, onSecondary, { variant: 'secondary', size: 'sm' }));
  const metaParts = [];
  if (code) metaParts.push(`错误码：${code}`);
  if (taskId) metaParts.push(`任务号：${taskId}`);
  return StateView({
    kind: 'error',
    title,
    detail: detail || description,
    meta: metaParts.join(' · '),
    actions,
  });
}

export function ForbiddenState({
  title = '当前账号无此操作权限',
  detail = '',
  description = '',
  requiredRole = '',
  action = '',
  backLabel = '返回应用目录',
  onBack,
} = {}) {
  const actions = onBack ? [Button(backLabel, onBack, { variant: 'secondary', size: 'sm' })] : [];
  const metaParts = [];
  if (action) metaParts.push(`所需动作：${action}`);
  if (requiredRole) metaParts.push(`授权角色：${requiredRole}`);
  return StateView({
    kind: 'forbidden',
    title,
    detail: detail || description,
    meta: metaParts.join(' · '),
    actions,
  });
}

// 11. Toast 提示组件
let activeToastTimer = null;

export function Toast({ message = '', tone = 'info' } = {}) {
  ensureStyles();
  const toneClass = tone === 'error' || tone === 'danger' ? 'error' : tone === 'success' || tone === 'ok' ? 'success' : tone === 'warning' || tone === 'warn' ? 'warning' : '';
  return h(
    'div',
    {
      class: `hk-ui-toast ${toneClass}`.trim(),
      role: toneClass === 'error' ? 'alert' : 'status',
      'aria-live': 'polite',
    },
    message
  );
}

export function showToast(messageOrProps, tone = 'info', { duration = 2600 } = {}) {
  ensureStyles();
  if (typeof document === 'undefined') return null;
  const isObj = typeof messageOrProps === 'object' && messageOrProps !== null;
  const message = isObj ? messageOrProps.message : messageOrProps;
  const resolvedTone = isObj ? (messageOrProps.tone || 'info') : tone;
  let host = document.getElementById('hk-ui-toast-host');
  if (!host) {
    host = h('div', { id: 'hk-ui-toast-host' });
    document.body.append(host);
  }
  const node = Toast({ message, tone: resolvedTone });
  host.replaceChildren(node);
  clearTimeout(activeToastTimer);
  if (duration > 0) {
    activeToastTimer = setTimeout(() => {
      node.remove();
    }, duration);
  }
  return node;
}

ensureStyles();

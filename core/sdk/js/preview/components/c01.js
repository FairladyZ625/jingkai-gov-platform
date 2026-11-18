// C01 采集填表前端：只收集输入与显示后端校验结果，不复制一套校验规则。
// 校验以后端 /c01/draft 返回的 Draft 为准，避免 Python 与 JS 两边规则漂移。
import { badge } from '/sdk/haiknow.js';
import { issueMessage } from '/sdk/preview/errors.js';
import { ensureStyles, h, Button, FormField, Input, Select } from '/sdk/ui/index.js';

export const VERSION = '1.0.0';

// Draft.errors 是 [{ field, code, message }]；也接受 { field: 文案 } 便于应用直接回填。
function normalizeErrors(errors) {
  if (!errors) return {};
  const list = Array.isArray(errors) ? errors : Array.isArray(errors.errors) ? errors.errors : null;
  if (!list) return typeof errors === 'object' ? { ...errors } : {};
  const out = {};
  for (const issue of list) {
    if (issue && issue.field && out[issue.field] == null) {
      out[issue.field] = issue.message || issueMessage(issue.code);
    }
  }
  return out;
}

function fieldValue(values, key) {
  const value = values[key];
  return value === '' || value == null ? '' : String(value);
}

// 渲染一个字段表单。schema 为后端 Schema.to_dict()，values 为回显值。
// onSubmit(values) 由应用调用后端校验；onChange(values) 可选，用于暂存输入。
export function c01Form(schema, values = {}, { onSubmit, onChange, disabled = false, errors = {} } = {}) {
  ensureStyles();
  const fields = (schema && schema.fields) || [];
  const initialErrors = normalizeErrors(errors);
  const inputs = {};
  const wrappers = {};
  const form = h('form', { class: 'c01-form hk-form hk-stack', novalidate: true });

  function collect() {
    return Object.fromEntries(fields.map((field) => [field.key, inputs[field.key].value]));
  }
  function emit() {
    if (onChange) onChange(collect());
  }
  function clearError(key) {
    if (wrappers[key]) wrappers[key].setError('');
  }

  for (const field of fields) {
    const value = fieldValue(values, field.key);
    const inputId = `c01_input_${field.key}`;
    const errId = `${inputId}_err`;
    const helpId = `${inputId}_help`;
    const describedBy = field.help ? `${helpId} ${errId}` : errId;
    let control;
    let input;

    if (field.type === 'enum') {
      control = Select({
        id: inputId,
        name: field.key,
        value,
        options: [
          { value: '', label: '请选择' },
          ...(field.options || []).map((option) => ({ value: option, label: option })),
        ],
        required: Boolean(field.required),
        disabled,
        describedBy,
        onChange: () => {
          clearError(field.key);
          emit();
        },
      });
      input = control;
    } else {
      const type = field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text';
      const placeholder = field.type === 'file' || field.type === 'photo'
        ? '文件 ID（由应用上传后填入）'
        : '';
      control = Input({
        id: inputId,
        name: field.key,
        type,
        // number 默认 step=1 会拦下 12.5；校验以后端为准，浏览器只负责收集输入。
        step: type === 'number' ? 'any' : undefined,
        value,
        placeholder,
        unit: field.unit || '',
        required: Boolean(field.required),
        disabled,
        describedBy,
        onInput: () => {
          clearError(field.key);
          emit();
        },
      });
      input = control.inputElement || control;
    }

    inputs[field.key] = input;
    const wrapper = FormField({
      key: field.key,
      id: inputId,
      label: field.label || field.key,
      required: Boolean(field.required),
      unit: field.unit || '',
      error: initialErrors[field.key] || '',
      control,
    });
    wrappers[field.key] = wrapper;
    if (field.help) {
      // FormField 没有说明文字入口：把说明放在控件之后、错误之前，沿用次要色样式。
      const [head, , errNode] = wrapper.children;
      wrapper.replaceChildren(
        head,
        control,
        h('span', { id: helpId, class: 'hk-field-meta' }, field.help),
        errNode,
      );
    }
    form.append(wrapper);
  }

  form.setErrors = (nextErrors = {}) => {
    const errorMap = normalizeErrors(nextErrors);
    let firstInvalid = null;
    for (const field of fields) {
      const wrapper = wrappers[field.key];
      const message = errorMap[field.key] || '';
      wrapper.setError(message);
      if (message && !firstInvalid) firstInvalid = wrapper;
    }
    if (firstInvalid) firstInvalid.focusControl();
  };
  form.clearErrors = () => form.setErrors({});

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (onSubmit) onSubmit(collect());
  });
  form.append(
    h(
      'div',
      { class: 'hk-btn-row' },
      Button({ label: '校验', variant: 'primary', type: 'submit', disabled }),
      Button({
        label: '清空',
        type: 'button',
        disabled,
        onClick: () => {
          for (const field of fields) inputs[field.key].value = '';
          form.clearErrors();
          emit();
        },
      }),
    ),
  );
  return form;
}

// 把 Draft.errors 渲染成可读清单；ok 时给一条通过提示。
export function c01Issues(draft) {
  if (!draft) return h('p', { class: 'muted' }, '还没有校验结果');
  if (draft.ok) return h('p', { class: 'hk-note' }, '校验通过，可以保存。');
  const issues = draft.errors || [];
  return h('div', {},
    h('p', {}, badge(`发现 ${issues.length} 个问题`, 'bad')),
    h('ul', { class: 'c01-issues' }, issues.map((issue) =>
      h('li', {},
        badge(issueMessage(issue.code), 'bad'),
        ' ',
        issue.message,
        issue.field ? h('span', { class: 'muted' }, `（字段 ${issue.field}）`) : null))));
}
// 错误展示的唯一入口：错误对象 → 中文提示，界面不出现原始错误码。
// 码表每条占一行（`  code: '中文',`），scripts/check.py 的 CHK-ERR-04 按这个格式解析并与
// prototype/v4/接口规范.md 和服务端实际发出的码逐条比对，新增码必须同时补这里。

export const PLATFORM_ERROR_MESSAGES = {
  unauthenticated: '登录已失效，请重新登录',
  bad_credentials: '账号或口令不正确',
  account_disabled: '账号已停用，请联系管理员',
  bad_password: '原密码不正确',
  weak_password: '新密码至少需要 6 位',
  invalid_query: '检索词缺少有效字符',
  self_lock: '请保留管理员的管理权限',
  skill_tool_not_allowed: '技能配置包含目录外的工具',
  url_not_allowed: '请输入允许导入的公开网址',
  tool_not_allowed: '技能未声明该工具',
  already_decided: '该版本已有审签结果',
  not_empty: '部门仍有成员、下级部门或岗位',
  file_too_large: '附件总大小超出限制',
  request_too_large: '导入请求过大，请减少导入内容',
  payload_too_large: '录音文件超出上传限制',
  unsupported_media_type: '不支持该导入格式',
  transcribe_provider_error: '转写服务调用失败，请稍后重试',
  url_fetch_failed: '读取网页失败，请检查网址',
  transcribe_not_configured: '转写服务尚未就绪，请联系管理员',
  url_fetch_timeout: '读取网页超时，请稍后重试',
  transcribe_timeout: '转写超时，请稍后重试',
  invalid_credentials: '用户名或口令不正确',
  invalid_box: '收件箱分类无效',
  unsupported_type: '文件类型不受支持',
  model_disabled: '该模型已停用',
  tool_not_found: '工具不存在',
  duplicate: '名称已存在，请换一个',
  check_failed: '送审前核查未通过',
  locked: '登录失败次数过多，请稍后再试',
  forbidden: '没有执行此操作的权限',
  self_review: '提交人不能确认自己的记录',
  not_found: '内容不存在，或你没有查看权限',
  version_conflict: '记录已有新版本，请重新读取后再保存',
  stale_version: '记录已有新版本，请刷新后再操作',
  invalid_state: '当前状态不能执行此操作，请刷新后重试',
  invalid_reference: '引用的内容不可用，请重新核对来源',
  invalid_request: '填写的内容不完整或格式不正确，请检查后重试',
  method_not_allowed: '不支持此操作',
  internal_error: '平台处理失败，请联系管理员',
  conflict: '名称或编号已存在，请换一个',
  in_use: '仍有关联内容，请先调整关联后再操作',
  last_admin: '必须保留至少一个启用的管理员',
  write_confirmation_required: '请先确认写入操作，再提交执行结果',
  org_cycle: '部门不能属于自身或下级部门',
  builtin_role: '内置角色不可删除',
  already_bootstrapped: '已存在管理员，请直接登录',
  not_configured: '该能力尚未配置，请联系管理员',
  signature_invalid: '飞书事件签名或令牌校验失败',
  quota_exceeded: '应用调用次数已达到限额',
  provider_error: '服务商暂时不可用，请检查服务商配置或稍后重试',
  outbound_denied: '该服务商不允许外发这类资料',
  timeout: '服务商响应超时，请稍后重试',
  bad_input: '输入内容无效，请检查后重试',
  compile_failed: '文档编译失败，请检查模板与填写内容后重试',
  too_large: '文档内容或生成的文件过大',
  unsupported_format: '不支持这种文件格式，请改用 DXF 或 STEP 文件',
  parse_failed: '文件解析失败，请确认文件完整或换用其他格式',
  busy: '系统繁忙，请稍后重试',
  gate_failed: '应用没有通过门禁检查，不能预览或上线，请让助手按报错继续修改',
  insecure_transport: '接入地址使用 http，密钥将以明文传输',
  app_unavailable: '该应用暂不可用，请联系管理员',
  submitter_unavailable: '调度启用人已不可用，请由其他有权限用户重新启用',
  app_error: '该应用处理失败，请稍后重试或联系管理员',
  http_error: '请求失败，请稍后重试',
  network_error: '网络异常，请检查网络后重试',
  media_permission_denied: '摄像头或麦克风权限被拒绝，请在浏览器设置中允许访问，或改用本地文件上传',
  media_device_not_found: '未检测到可用的摄像头或麦克风设备，请连接设备后重试，或改用本地文件上传',
  media_device_in_use: '摄像头或麦克风正被其他程序占用或不可读，请关闭占用程序后重试，或改用本地文件上传',
  media_capture_interrupted: '媒体采集已中断，请重新采集或改用本地文件上传',
  media_not_supported: '当前浏览器环境不支持直接调用摄像头或麦克风，请改用本地文件上传',
  media_invalid_type: '媒体文件格式不在允许范围内，请选择规定格式的图片或音频',
  media_too_large: '媒体文件大小超出限制，请压缩或缩短时长后重试',
  media_duration_exceeded: '录音时长超出上限，请缩短录音时间后重试',
  media_empty: '采集到的媒体内容为空，请重新拍摄、录音或选择有效文件',
  media_upload_failed: '媒体原件上传失败，请重试或改用本地文件上传',
};

// 共用组件校验问题的中文类别：界面徽标只显示类别，原始码不上屏。
// 码来自 core/sdk/haiknow_sdk/preview/components/*.py 的 Issue / _Stop；
// scripts/check.py 的 CHK-ERR-04 按这个格式解析，并比对组件后端实际使用的码。
export const ISSUE_MESSAGES = {
  required: '必填项缺失',
  type: '格式不正确',
  pattern: '格式不正确',
  range: '超出允许范围',
  option: '选项不在范围内',
  unknown_field: '未声明的字段',
  unknown_name: '引用了不存在的变量',
  formula_error: '公式有误',
  divide_by_zero: '公式除以零',
  empty_table: '表格没有内容',
  bad_header: '表头有误',
  row_columns: '列数与表头不一致',
  empty_key: '匹配键为空',
  duplicate_key: '匹配键重复',
  no_column: '缺少列',
  unit_unknown: '单位无法换算',
  not_number: '不是有效数字',
  empty_value: '数值为空',
  csv_error: '文件解析失败',
  duplicate_rule: '规则重复',
  hint_not_found: '提示不存在',
  reviewer_required: '缺少处理人',
  reason_required: '缺少理由',
  risk_required: '缺少风险等级',
  unknown_risk: '风险等级无效',
  no_basis: '没有依据',
  duplicate_node: '节点重复',
  unknown_dependency: '依赖不存在',
  no_planned: '缺少计划时间',
  no_owner: '缺少责任人',
  bad_date: '日期无效',
  unknown_asset: '素材不存在',
  unknown_asset_version: '素材版本不存在',
  rights_denied: '没有使用权',
  rights_pending: '使用权待确认',
  version_not_found: '版本不存在',
  author_required: '缺少提出人',
  comment_required: '修改意见为空',
  already_decided: '已经审核过',
};

const STATUS_FALLBACK = {
  401: PLATFORM_ERROR_MESSAGES.unauthenticated,
  403: PLATFORM_ERROR_MESSAGES.forbidden,
  404: PLATFORM_ERROR_MESSAGES.not_found,
  405: PLATFORM_ERROR_MESSAGES.method_not_allowed,
  409: PLATFORM_ERROR_MESSAGES.invalid_state,
  422: PLATFORM_ERROR_MESSAGES.invalid_request,
};
export const GENERIC_ERROR_MESSAGE = '操作失败，请稍后重试';
const HAN = /[一-鿿]/;

function ownKey(table, code) {
  return table && typeof code === 'string' && Object.prototype.hasOwnProperty.call(table, code) ? table[code] : '';
}

// 组件校验问题 → 中文类别；未登记的码也只回中文类别，界面不出现原始码。
export function issueMessage(code) {
  return ownKey(ISSUE_MESSAGES, code) || '校验问题';
}

// extra：应用自己登记的 { code: 中文 }（见 apps/<id>/web/errors.json）。
// 取值顺序：服务端给的中文说明（不含原始码）→ 应用登记 → 平台码表 → 按 HTTP 状态兜底 → 通用兜底。
export function errorMessage(error, extra = null) {
  const code = error && error.code;
  const raw = error && typeof error.message === 'string' ? error.message.trim() : '';
  const lowerCode = typeof code === 'string' ? code.toLowerCase() : '';
  if (raw && HAN.test(raw) && !(lowerCode && raw.toLowerCase().includes(lowerCode))) return raw;
  const mapped = ownKey(extra, code) || ownKey(extra, lowerCode) || ownKey(PLATFORM_ERROR_MESSAGES, lowerCode);
  if (mapped) return mapped;
  if (code && typeof console !== 'undefined') console.debug('[haiknow] 未登记的错误码：', code);
  if (error && !error.status && !code && /fetch|network|failed to load/i.test(raw)) return PLATFORM_ERROR_MESSAGES.network_error;
  return (error && STATUS_FALLBACK[error.status]) || (error && error.status >= 500 ? PLATFORM_ERROR_MESSAGES.internal_error : GENERIC_ERROR_MESSAGE);
}

// 应用登记表：每个应用一份，避免 A 应用的码解释 B 应用的错误。
const appTables = new Map();

export function defineErrors(appId, table) {
  const clean = {};
  for (const [code, text] of Object.entries(table || {})) if (typeof text === 'string' && text) clean[code] = text;
  appTables.set(appId, { ...(appTables.get(appId) || {}), ...clean });
}

// 读取 /apps/<id>/web/errors.json 并登记；文件不存在或损坏时静默跳过。
export async function loadAppErrors(appId, fetchImpl = globalThis.fetch) {
  try {
    const response = await fetchImpl(`/apps/${encodeURIComponent(appId)}/web/errors.json`, { credentials: 'same-origin' });
    if (response.ok) defineErrors(appId, await response.json());
  } catch {
    /* 没有登记文件按无自定义码处理 */
  }
}

export function appErrorMessage(appId, error) {
  return errorMessage(error, appTables.get(appId));
}

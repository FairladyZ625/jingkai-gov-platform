// 实验能力：受管模板 + 字段生成 PDF 并登记知识库；应用 ID 由调用上下文提供。
export function templates(http) {
  return http('/api/v1/latex/templates');
}

// body: { project, template, fields, title, category?, version?, entryId?, note?, tags? }
export function render(http, appId, body) {
  return http('/api/v1/latex/render', { json: { ...body, appId } });
}

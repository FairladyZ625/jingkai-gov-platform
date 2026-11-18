"""技能编辑器与保存接口共用的工具目录、内容字段和结构校验。"""

TOOLS = (
    {"id": "policy.match", "label": "匹配兑现事项", "needs": "ent"},
    {"id": "enterprise.get", "label": "读取企业档案", "needs": "ent"},
    {"id": "meeting.list", "label": "汇总会议记录"},
)
CONTENT = ("name", "summary", "icon", "base", "spec")


class SkillError(ValueError):
    def __init__(self, status, code, message, **details):
        super().__init__(message)
        self.status = status
        self.error = {"code": code, "message": message, "details": details}


def invalid(message):
    raise SkillError(400, "INVALID_REQUEST", message)


def validate_spec(spec):
    if not isinstance(spec, dict):
        invalid("技能规格应为对象")
    for key, kind in (("triggers", str), ("inputs", dict), ("steps", dict)):
        values = spec.get(key, [])
        if not isinstance(values, list) or not all(isinstance(i, kind) for i in values):
            invalid(f"{key} 列表格式有误")
    steps = spec.get("steps", [])
    if len(steps) > 5:
        invalid("技能最多允许五个步骤")
    allowed = {t["id"] for t in TOOLS}
    declarations = spec.get("tools", [])
    if not isinstance(declarations, list):
        invalid("工具声明应为列表")
    tools = list(declarations)
    for step in steps:
        if step.get("type") not in ("tool", "kb", "computer", "model"):
            invalid("未知的步骤类型")
        if step["type"] == "tool" or "tool" in step:
            tools.append(step.get("tool"))
    for tool in tools:
        if not isinstance(tool, str) or tool not in allowed:
            raise SkillError(400, "SKILL_TOOL_NOT_ALLOWED", "工具不在技能白名单内")
    return {"triggers": [], "inputs": [], "steps": [], **spec}


def content_fields(body):
    content = {key: body[key] for key in CONTENT if key in body}
    if "spec" in content:
        content["spec"] = validate_spec(content["spec"])
    if any(not isinstance(value, str) for key, value in content.items() if key != "spec"):
        invalid("技能基本信息应为文本")
    if "name" in content and not content["name"].strip():
        invalid("技能名称不能为空")
    return content


def next_version(version):
    major, minor, _ = version.split(".")
    return f"{major}.{int(minor) + 1}.0"

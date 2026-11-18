"""技能执行与 provider 约定，由 core JobService 持久化每一步。"""

import json
import re

from .spec import TOOLS, SkillError, invalid, validate_spec

TOOL_IDS = frozenset(tool["id"] for tool in TOOLS)
STEP_LABELS = {"kb": "检索知识库", "model": "生成结论", "tool": "调用工具", "computer": "准备电脑操作"}
COMPUTER_TASKS = frozenset(("stats", "apply", "notice", "status"))
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
PENDING = "待确认"


def prepare_skill(skill):
    if not isinstance(skill, dict):
        invalid("技能应为对象")
    name = skill.get("name")
    if not isinstance(name, str) or not name.strip():
        invalid("技能名称不能为空")
    spec = skill.get("spec")
    if not isinstance(spec, dict):
        invalid("技能规格应为对象")
    steps = spec.get("steps", [])
    if not isinstance(steps, list):
        invalid("steps 列表格式有误")
    # 原编辑器以 tool 步骤声明工具。提供 tools 时，以显式名单为准。
    declared = spec.get("tools", [step.get("tool") for step in steps
                                  if isinstance(step, dict) and step.get("type") == "tool"])
    if not isinstance(declared, list):
        invalid("工具声明应为列表")
    permitted = {tool for tool in declared if isinstance(tool, str) and tool in TOOL_IDS}
    for step in steps:
        if not isinstance(step, dict):
            invalid("步骤应为对象")
        if step.get("type") == "tool" or "tool" in step:
            tool = step.get("tool")
            if not isinstance(tool, str) or tool not in permitted:
                raise SkillError(403, "TOOL_NOT_ALLOWED", "步骤只能调用技能已声明的工具")
        if step.get("type") == "tool" and not isinstance(step.get("args", {}), dict):
            invalid("工具参数应为对象")
        if step.get("type") == "kb" and any(
            key in step and not isinstance(step[key], str) for key in ("query", "space")
        ):
            invalid("知识库查询和空间应为文本")
        if step.get("type") == "computer":
            task = step.get("task")
            if not isinstance(task, str) or task not in COMPUTER_TASKS:
                invalid("电脑操作任务无效")
    return {"name": name.strip(), "spec": validate_spec(spec)}


def is_blank(value):
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == [] or value == {}


def render(value, inputs, unresolved=None):
    """保留完整占位符对应的 JSON 类型。记录无法绑定的参数以跳过下游调用。"""
    if isinstance(value, dict):
        return {key: render(item, inputs, unresolved) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, inputs, unresolved) for item in value]
    if not isinstance(value, str):
        return value

    def lookup(key):
        item = inputs.get(key)
        if not is_blank(item):
            return item
        if unresolved is not None:
            unresolved.add(key)
        return PENDING

    whole = PLACEHOLDER.fullmatch(value)
    if whole:
        return lookup(whole[1])
    return PLACEHOLDER.sub(lambda match: str(lookup(match[1])), value)


def step_label(step):
    label = step.get("label")
    return label if isinstance(label, str) and label.strip() else STEP_LABELS[step["type"]]


def run_step(provider, user, step, spec, inputs, prior, name, key):
    kind = step["type"]
    unresolved = set()
    if kind == "kb":
        query = render(step.get("query", name), inputs, unresolved)
        if unresolved or is_blank(query):
            return {"note": "知识库查询条件待确认，已跳过。"}
        params = {"q": str(query), "limit": 4}
        if step.get("space"):
            params["space"] = step["space"]
        return {"hits": provider.search(user, params)["hits"]}
    if kind == "tool":
        args = render(step.get("args", {}), inputs, unresolved)
        if unresolved:
            return {"note": f"{step['tool']} 的参数待确认，已跳过。"}
        # 稳定步骤键可供工具桥去重。同一技能的多次运行各有自己的键。
        return provider.tool(user, step["tool"], args, key)
    if kind == "computer":
        return {"computer": {"task": step["task"], "ent": inputs.get("ent")}}
    return provider.generate(user, spec["model"], {
        "title": str(render(spec["output"]["title"] or name, inputs)),
        "prompt": str(render(spec["prompt"], inputs)),
        "format": spec["output"]["format"],
        "inputs": inputs,
        "prior": list(prior),
    })


def execute(execution, skill, raw_inputs, user, provider, authorize):
    spec = skill["spec"]
    fields = spec["inputs"]
    inputs = {field["key"]: raw_inputs[field["key"]] for field in fields
              if not is_blank(raw_inputs.get(field["key"]))}
    missing = [field["key"] for field in fields if field.get("required") and field["key"] not in inputs]
    title = str(render(spec["output"]["title"] or skill["name"], inputs))
    lines = [f"### {title}"]
    if missing:
        lines.extend(f"- {field.get('label') or field['key']}：**待确认**"
                     for field in fields if field["key"] in missing)
    prior = []
    citations = []
    seen = set()
    model = None
    computer = None
    if not spec["steps"]:
        authorize()
    for index, step in enumerate(spec["steps"]):
        kind = step["type"]
        authorize()
        result = execution.step(
            f"{index + 1}:{kind}",
            lambda key: run_step(provider, user, step, spec, inputs, prior, skill["name"], key),
        )
        prior.append({"type": kind, "result": result})
        for hit in result.get("hits", []):
            identity = (hit["id"], hit["snippet"])
            if identity not in seen:
                seen.add(identity)
                citations.append({**hit, "n": len(citations) + 1})
        if kind == "model":
            model = result["model"]
            lines.append(result["markdown"])
        if kind == "computer":
            computer = result["computer"]
        if "note" in result:
            lines.append(f"> {result['note']}")
        if kind == "tool" and "result" in result:
            value = result["result"]
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            lines.append(f"- {step_label(step)}：{rendered}")

    if citations:
        lines.extend(("", "### 知识库出处"))
        lines.extend(f"- [{cite['n']}] {cite['title']}：{cite['snippet']}" for cite in citations)
    return {"title": title, "markdown": "\n".join(lines), "citations": citations,
            "missing": missing, "model": model, "computer": computer}

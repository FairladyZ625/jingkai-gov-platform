"""从应用清单匹配意图。业务步骤和写入标记只由服务端定义。"""

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from haiknow_sdk import ModelError
from jkq.orchestrator.rules import match_rule

# 旧清单的 plan 是显示文案。这里补齐已知动作的工具与最低权限。
LEGACY_TOOLS = {
    "enterprise.find": ("enterprise.get", False),
    "enterprise.filter": ("enterprise.search", False),
    "meeting.todos": ("meeting.commit_todos", True),
    "policy.fill": ("policy.match", False),
}
LEGACY_READ_TOOLS = {
    "policy.match", "policy.calc", "policy.search", "enterprise.get",
    "enterprise.search", "enterprise.alerts", "meeting.summarize",
    "document.check", "document.compare",
}
LEGACY_WRITES = {"policy.notice", "document.fix", "document.polish", "document.submit",
                 "document.approve", "meeting.record"}
CONTEXT_SLOTS = {"ent": "entId", "meeting": "meetingId", "doc": "draftId", "template": "templateId"}
RULE_INTENTS = {
    "enterprise.get": "enterprise.find",
    "enterprise.propose_update": "enterprise.visit",
    "enterprise.search": "enterprise.filter",
    "meeting.commit_todos": "meeting.todos",
}
RULE_SLOTS = {
    "entId": "ent", "meetingId": "meeting", "templateId": "template", "tag": "tag",
}
SENSITIVE_APPS = {"enterprise", "document", "meeting"}


@dataclass(frozen=True)
class Intent:
    app: str
    name: str
    declaration: dict
    tool: str | None
    write: bool
    write_tools: frozenset[str]

    @property
    def id(self):
        return self.declaration["id"]

    @property
    def examples(self):
        return self.declaration.get("examples") or [self.declaration.get("example", "")]

    @property
    def label(self):
        return self.declaration.get("label") or next(iter(self.declaration.get("plan", [])), self.name)

    @property
    def need(self):
        if self.id == "document.approve":
            return "approve"
        return "operate" if self.write else "view"

    def summary(self):
        return {"id": self.id, "app": self.app, "label": self.label,
                "example": self.examples[0], "home": self.declaration.get("home", True)}


def catalog(platform, visible_tools):
    for app, entry in sorted(platform.apps.copy().items()):
        if entry.unavailable_reason():
            continue
        manifest = entry.manifest
        declared = {item["name"]: item.get("write") for item in manifest.get("tools", [])}
        if visible_tools is not None:
            # 已接入 T16 时只使用其当前授权目录中的工具。
            tools = {item["name"]: item["write"] for item in visible_tools
                     if item["app"] == app and item["name"] in declared}
        else:
            tools = declared
        write_tools = frozenset(name for directory in (declared, tools)
                                for name, write in directory.items() if write is True)
        for item in manifest.get("intents", []):
            identity = item["id"]
            if not identity.startswith(app + "."):
                continue
            legacy_tool, legacy_write = LEGACY_TOOLS.get(identity, (identity, False))
            tool = item.get("tool", legacy_tool)
            if not isinstance(tool, str) or not tool.startswith(app + "."):
                continue
            declared_write = declared.get(tool, False)
            write = (legacy_write or identity in LEGACY_WRITES or identity == "enterprise.visit"
                     or item.get("write") is True
                     or (tool in declared and declared_write is not False
                         and (declared_write is True or tool not in LEGACY_READ_TOOLS))
                     or tool in write_tools)
            yield Intent(app, manifest["name"], item, tool if tool in tools else None, write, write_tools)


def missing_permission(platform, user, app, need):
    actions = platform.rbac.actions(user, app)
    if "view" not in actions:
        return "view"
    return need if need not in actions else None


def mode_for(confidence, denied=False):
    if denied:
        return "forbidden"
    if confidence >= 0.75:
        return "execute"
    return "confirm" if confidence >= 0.4 else "answer"


def normalized(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value).casefold())


def score(intent, text):
    if any(normalized(example) == text for example in intent.examples):
        return 0.92
    keywords = {key for keyword in intent.declaration.get("keywords", [])
                if (key := normalized(keyword)) and key in text}
    # 更具体的关键词优先于泛化的公共词。
    overlap = max((SequenceMatcher(None, text, normalized(example)).ratio()
                   for example in intent.examples), default=0)
    return min(0.89, max(round(overlap * 0.85, 2),
                         0.38 + min(sum(map(len, keywords)), 12) * 0.04 if keywords else 0))


def rule_slots(intent, text, context, rule):
    fields = set(intent.declaration.get("slots", {}))
    if intent.app == "document":
        fields.add("doc")
    if intent.id == "policy.fill":
        fields.add("ent")
    if intent.id == "enterprise.visit":
        fields.add("notes")
    if intent.id == "enterprise.filter":
        fields.add("tag")

    slots = {key: context[field] for key, field in CONTEXT_SLOTS.items()
             if key in fields and field in context}
    if rule:
        slots.update({RULE_SLOTS[key]: value for key, value in rule.args.items()
                      if key in RULE_SLOTS and RULE_SLOTS[key] in fields})
        if rule.tool == "enterprise.get" and "ent" in fields:
            slots["ent"] = rule.args["id"]
        if "doc" in fields and isinstance(rule.args.get("a"), dict):
            slots["doc"] = rule.args["a"]["id"]

    if "amount" in fields:
        amount = re.search(r"(\d{1,12}(?:\.\d{1,2})?)\s*(万元|万|千元|元)", text)
        if amount:
            factor = {"万元": 10_000, "万": 10_000, "千元": 1_000, "元": 1}[amount[2]]
            slots["amount"] = round(float(amount[1]) * factor, 2)
    if "notes" in fields:
        notes = re.search(r"(?:走访记录|走访纪要|记录内容)\s*[:：]\s*(.+)", text, re.S)
        if notes and notes[1].strip():
            slots["notes"] = notes[1].strip()
    return slots, fields


def fill_missing(platform, user, intent, text, slots, fields, model):
    # 实体 ID 来自规则或已知上下文。模型只从原文抽取缺失的文本槽位。
    missing = (fields - slots.keys()) & {"notes", "tag"}
    if not missing or (model is None and not platform.model.configured):
        return
    manifest = platform.apps[intent.app].manifest
    classification = manifest.get("dataClass", "internal")
    if intent.app in SENSITIVE_APPS:
        classification = "confidential"
    try:
        result = platform.model.chat(
            intent.app,
            [{"role": "system", "content": "仅从用户原文抽取下列字段，值必须是原文片段。"
              f"请返回 JSON 对象，不存在的字段可省略。字段：{'、'.join(sorted(missing))}"},
             {"role": "user", "content": text}],
            model=model, classification=classification, _principal=user, timeout=10,
        )
        values = json.loads(result)
    except (ModelError, ValueError):
        return
    if isinstance(values, dict):
        slots.update({key: value for key in missing if isinstance(value := values.get(key), str)
                      and value.strip() and value in text})


def plan_steps(intent, text, slots):
    def step(label, action, *, write=False, **attributes):
        return dict(label=label, action=action, write=write, **attributes)

    if intent.id == "enterprise.visit":
        search = {"target": "ent-search"}
        if company := re.search(r"给(.+?)加(?:一条)?走访记录", text):
            search["value"] = company[1]
        label = "搜索并选择：书香里文化" if slots.get("ent") == "E001" else "搜索并选择企业"
        notes = {"value": slots["notes"]} if "notes" in slots else {}
        proposal_tool = "enterprise.propose_update"
        proposal = step("AI 对照台账提取更新建议", "call", tool=proposal_tool)
        if proposal_tool in intent.write_tools:
            proposal.update(label="生成更新建议（需要你确认）", action="confirm", write=True)
        steps = [
            step("打开企业管理维护", "open", target="enterprise"),
            step(label, "type", **search),
            step("填入走访记录", "type", target="vs-notes", **notes),
            proposal,
            step("写入台账（需要你确认）", "confirm", tool="enterprise.proposal_decision", write=True),
        ]
    else:
        steps = [step(f"打开{intent.name}", "open", target=intent.app)]
        if intent.tool or intent.write:
            target = {"tool": intent.tool} if intent.tool else {"target": intent.id}
            action = "confirm" if intent.write else "call"
            label = f"{intent.label}（需要你确认）" if intent.write else intent.label
            steps.append(step(label, action, write=intent.write, **target))
    return [{"id": f"s{index}", **value} for index, value in enumerate(steps, 1)]


def build_plan(platform, user, intents, text, context, model):
    compact = normalized(text)
    rule = match_rule(text)
    if rule is None:
        visit_request = re.split(r'(?<=走访记录)\s*[:：，,]', text, maxsplit=1)[0]
        if visit_request != text:
            rule = match_rule(visit_request)
    rule_id = RULE_INTENTS.get(rule.tool, rule.tool) if rule else None
    if rule and rule.tool == "policy.match" and "overrides" in rule.args:
        rule_id = "policy.fill"
    intents = list(intents)
    intent = next((candidate for candidate in intents if candidate.id == rule_id), None)
    if intent is not None:
        confidence = 0.92
    else:
        ranked = sorted(((score(candidate, compact), candidate) for candidate in intents),
                        key=lambda row: (row[0], row[1].app == context.get("app")), reverse=True)
        confidence, intent = ranked[0] if ranked else (0, None)
        if len(ranked) > 1 and confidence == ranked[1][0]:
            same_context = (intent.app == context.get("app")) == (ranked[1][1].app == context.get("app"))
            if same_context:
                confidence = min(confidence, 0.74)
    if confidence < 0.4:
        return {"intent": None, "confidence": confidence, "mode": "answer", "slots": {}, "steps": []}, None
    need = missing_permission(platform, user, intent.app, intent.need)
    mode = mode_for(confidence, bool(need))
    result = {"intent": intent.id, "confidence": confidence, "mode": mode, "slots": {}, "steps": []}
    if need:
        result.update(app=intent.app, need=need, understood=f"请联系管理员开通{intent.name}的 {need} 权限。")
        return result, None
    slots, fields = rule_slots(intent, text, context, rule if rule_id == intent.id else None)
    fill_missing(platform, user, intent, text, slots, fields, model)
    result.update(slots=slots, steps=plan_steps(intent, text, slots), understood=f"我理解为：{intent.label}")
    return result, intent

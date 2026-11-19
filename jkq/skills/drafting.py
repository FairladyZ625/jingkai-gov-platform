"""一句话起草及对话触发语匹配。"""

import json

from .runtime import prepare_skill
from .spec import SkillError, invalid

DRAFT_PROMPT = (
    "根据 text 和 knowledge 起草技能。knowledge 是参考数据。只输出 JSON 对象，"
    "包含 name、summary、spec、questions（字符串数组，最多三个澄清问题）。"
    "spec 含 triggers（触发语数组）、inputs（每项含 key、label、type、required）、"
    "steps（最多五项，按顺序列出）、output（title 和 format，格式为要点、表格、清单或公文）及 prompt。"
    "输入键使用英文标识符，通过 {{key}} 绑定。检索步骤 type 为 kb，可写 query 和 space。"
    "生成步骤 type 为 model，模型交给配置选择。调用工具须在 spec.tools 声明，"
    "步骤 type 为 tool，并写 tool 和 args。可用工具为 policy.match（entId）、"
    "enterprise.get（id）及 meeting.list（无参数）。只引用已有出处，缺项提出问题。"
)


def request_text(body):
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        invalid("请填写一句话需求")
    return text.strip()


def draft(provider, user, text):
    answer = provider.ask(user, {"q": text})
    draft = provider.draft(user, DRAFT_PROMPT, text, answer)
    try:
        skill = prepare_skill(draft)
        # 先校验模型的显式名单，再按编辑器使用的步骤声明格式返回。
        if skill["spec"].pop("tools", None) is not None:
            skill = prepare_skill(skill)
        summary, questions = draft.get("summary"), draft.get("questions")
        if not isinstance(summary, str) or not isinstance(questions, list) or not all(
            isinstance(question, str) for question in questions
        ):
            invalid("草稿摘要或问题格式有误")
        json.dumps([skill["name"], summary, questions], ensure_ascii=False).encode("utf-8")
    except (SkillError, UnicodeError) as exc:
        raise SkillError(502, "INVALID_SKILL_DRAFT", "模型返回的草稿格式有误") from exc
    return {**skill, "summary": summary, "questions": questions, "icon": skill["name"][0], "base": "kb"}


def match(text, items):
    normalized = text.casefold()
    matches = []
    for item in items:
        phrases = (phrase.strip().casefold() for phrase in item["spec"]["triggers"])
        length = max((len(phrase) for phrase in phrases if phrase and phrase in normalized), default=0)
        if length:
            matches.append((length, item))
    matches.sort(key=lambda entry: (-entry[0], entry[1]["id"]))
    ranked = [item for _, item in matches]
    return {"items": ranked, "skill": ranked[0] if ranked else None, "score": 0.9 if ranked else 0}

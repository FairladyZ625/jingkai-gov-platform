"""一句话起草及对话触发语匹配。"""

from .runtime import prepare_skill
from .spec import SkillError, invalid

DRAFT_PROMPT = (
    "据需求和有出处的知识库答复起草技能。返回 name、summary、spec 和 questions。"
    "spec 要写明触发语、必填输入、顺序步骤和输出格式。信息不足时提出问题，"
    "只引用已有出处，不编造依据。使用已登记的工具，模型由配置选择。"
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
        summary, questions = draft.get("summary"), draft.get("questions")
        if not isinstance(summary, str) or not isinstance(questions, list) or not all(
            isinstance(question, str) for question in questions
        ):
            invalid("草稿摘要或问题格式有误")
    except SkillError as exc:
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

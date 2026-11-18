"""对话规则按具体业务动作、知识问答的顺序匹配。"""

import re
import unicodedata
from dataclasses import dataclass

from .ports import ToolCall


@dataclass(frozen=True)
class Rule:
    pattern: str
    call: ToolCall


# 演示企业简称与种子数据 data/seed/demo.json 一致，规则只认这些固定对象。
ENTERPRISES = {"书香里": "E001", "书香里文化": "E001", "纸鹿二号": "E002", "纸鹿二号智驾": "E002"}
ENT = r"(?P<ent>书香里(?:文化)?|纸鹿二号(?:智驾)?)"

RULES = (
    Rule(rf"(?:帮我)?(?:查(?:一下)?)?{ENT}能(?:申请|申报)哪些(?:政策)?(?:支持|政策)?", ToolCall("policy.match", {})),
    Rule(r"补填数据采购额(?P<amount>[0-9]{1,7})万", ToolCall("policy.match", {})),
    Rule(rf"给{ENT}生成(?:政策)?告知单", ToolCall("policy.notice", {})),
    Rule(rf"查(?:一下)?{ENT}", ToolCall("enterprise.get", {})),
    Rule(rf"给{ENT}加(?:一条)?走访记录", ToolCall("enterprise.propose_update", {})),
    Rule(r"打开企业台账筛选高新(?:技术)?企业", ToolCall("enterprise.search", {"tag": "高新技术"})),
    Rule(r"把(?:文化企业)?座谈会的待办派发下去", ToolCall("meeting.commit_todos", {"meetingId": "MT-1112"})),
    Rule(r"起草(?:一份)?数据券申报延期通知", ToolCall("document.draft", {"templateId": "T06"})),
    Rule(r"(?:送审签|提交审签)", ToolCall("document.submit", {})),
    Rule(r"打开书香里(?:文化)?的答复意见,?对比(?:一下)?第1版和第2版", ToolCall(
        "document.compare", {"a": {"id": "DOC-1112", "v": 1}, "b": {"id": "DOC-1112", "v": 2}},
    )),
)
# 企业参数名随工具而定。
ENT_ARG = {"enterprise.get": "id"}
KNOWLEDGE = re.compile(
    r"知识库.*(?:有没有|是否|哪些|什么|哪份|查到)|(?:查|找|看|有没有).*(?:知识库|原文)|原文|政策条款|什么政策|政策依据|"
    r"(?:政策|补贴|补助|奖励|申报|办法|规定|通知).*(?:是[什么]|多少|哪些|多久|何时|什么时候|条件|截止|要求|如何|怎么|解读)|"
    r"(?:查找|查询|找|哪些|有没有|关于|解读).*(?:政策|条款|实施方案)|"
    r"(?:数据券|算力券|奖励|补贴).*\?|(?:三[个种]时间)"
)


def match_rule(text: str) -> ToolCall | None:
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).rstrip("。!?")
    for rule in RULES:
        if match := re.fullmatch(rule.pattern, normalized):
            groups = match.groupdict()
            if amount := groups.get("amount"):
                return ToolCall(rule.call.tool, {"overrides": {"dataPurchase": int(amount) * 10_000}})
            args = rule.call.args.copy()
            if ent := groups.get("ent"):
                args[ENT_ARG.get(rule.call.tool, "entId")] = ENTERPRISES[ent]
            return ToolCall(rule.call.tool, args)
    if KNOWLEDGE.search(unicodedata.normalize("NFKC", text)):
        return ToolCall("kb.ask", {"q": text})
    return None

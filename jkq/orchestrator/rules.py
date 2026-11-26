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
    Rule(rf"给{ENT}生成(?:政策参考清单|参考清单|(?:政策)?告知单)", ToolCall("policy.notice", {})),
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
    r"三[个种]时间|"
    r"(?:政策|补贴|补助|奖励|申报|办法|规定|通知|数据券|算力券|资格|认定|适用范围)"
    r".*(?:什么|多少|哪些|多久|何时|条件|截止|要求|如何|怎么|咋|解读|细则|标准|[吗?])|"
    r"(?:查找|查询|查一下|找|哪些|有没有|关于|解读|解释|介绍|说明|怎么|如何|何时|什么时候|多少|什么)"
    r".*(?:政策|条款|实施方案|数据券|算力券|补贴|奖励|申报|办法|规定)"
)
KB_COMMAND = re.compile(
    r"(?:请|麻烦)?(?:帮我)?(?:"
    r"(?:导入|上传|入库|发布|删除|移除|编辑|重命名|创建空间).+|打开知识库|"
    r"(?:把|将).+(?:导入|上传到|存入|加入)知识库)"
)
KB_QUESTION = re.compile(r"怎么|如何|为何|为什么|什么|哪些|是否|能否|有没有|[吗?]$")
KB_FOLLOWUP = re.compile(r"^(?:那|这个|这项|该|它|上述|刚才|还有)")
SMALL_TALK = re.compile(r"你好(?:呀|啊)?|您好|早上好|下午好|晚上好|谢谢(?:你|您)?|多谢|再见|辛苦了|聊聊天|讲(?:个|一个)笑话")


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def kb_command(text: str) -> bool:
    """知识库应用默认检索，明确的应用命令交给其注册工具。"""
    normalized = _normalized(text).rstrip("。!")
    return KB_COMMAND.fullmatch(normalized) is not None and not KB_QUESTION.search(normalized)


def follows_knowledge_question(text: str) -> bool:
    return KB_FOLLOWUP.match(_normalized(text)) is not None


def is_small_talk(text: str) -> bool:
    return SMALL_TALK.fullmatch(_normalized(text).rstrip("。!?")) is not None


def match_rule(text: str) -> ToolCall | None:
    normalized = _normalized(text)
    action = normalized.rstrip("。!?")
    for rule in RULES:
        if match := re.fullmatch(rule.pattern, action):
            groups = match.groupdict()
            if amount := groups.get("amount"):
                return ToolCall(rule.call.tool, {"overrides": {"dataPurchase": int(amount) * 10_000}})
            args = rule.call.args.copy()
            if ent := groups.get("ent"):
                args[ENT_ARG.get(rule.call.tool, "entId")] = ENTERPRISES[ent]
            return ToolCall(rule.call.tool, args)
    return ToolCall("kb.ask", {"q": text}) if KNOWLEDGE.search(normalized) and not kb_command(text) else None

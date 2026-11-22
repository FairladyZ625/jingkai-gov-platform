"""从查询识别主题与所问属性；只给能同时定位主题和属性的原句加权。"""
import re
from collections import namedtuple


DEADLINE = re.compile(r"(?:申报|申请|受理|提交|报送).{0,24}(?:截止|截至|期限为|限期|时间为)|(?:截至|截止|自).{0,20}\d{1,4}[年月日/-]|\d{1,2}月\d{1,2}日.{0,4}(?:至|前)")
AUDIENCE = re.compile(r"(?:适用于|(?:适用对象|申报对象|支持对象|适用范围)[为是：:])\s*[^\s，。；：:]{2,}")
SIGNOFF = re.compile(r"(?:签字|签章|盖章|审签|签批|签署)")
MATERIAL = re.compile(r"材料|申请表|申报表|申请书|承诺书|证明|清单|报告")


def deadline(s):
    # 发文日和政策有效期都不等于申报截止日。
    return bool(DEADLINE.search(s) and re.search(r"\d+[年月日天个/-]|工作日|另行通知|常年|随时", s)
                and re.search(r"申报|申请|受理|提交|报送|征集", s))


FIELDS = (
    ("申报期限", re.compile(r"期限|截止|截至|申报时间|受理时间"), deadline),
    ("适用对象", re.compile(r"适用对象|适用范围|申报对象|支持对象|谁能申报"), AUDIENCE.search),
    ("审签材料", re.compile(r"审签|签章|签批|盖章"), lambda s: SIGNOFF.search(s) and MATERIAL.search(s)
     and not re.fullmatch(r"(?:.{0,5}[、.．])?(?:需要)?审签材料(?:要求|清单)?[：:。]?", s)),
)

# 问法与原文的语言不同（如“负责什么”对应“主要职责”）；这里没有政策名、答案或金额。
NUMBER = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千半][零〇一二两三四五六七八九十百千万半]*)"
DURATION = re.compile(NUMBER + r"\s*(?:分钟|小时|工作日|天|周|个月|年|秒)")
UPPER = r"最长|最多|最高|上限|封顶|不(?:得|能)?超过|不多于|以内"
LOWER = r"最短|最少|最低|下限|至少|不少于|不低于"
TIME_QUESTION = r"多久|多长时间|几(?:分钟|小时|天|周|个月)|时长"
LIMIT = r"(?:最长|最多|最短|最少|至少)"
# “最长能用多久”的动词是问法的一部分；不从“夜间借用”等主题限定词中删字。
TIME_TAIL = rf"{LIMIT}(?:能|可(?:以)?)(?:[\u3400-\u9fff]{{0,3}}?)(?:多久|多长时间)"
MONEY = re.compile(NUMBER + r"\s*(?:[万亿]?元|[%％])")

ATTRIBUTES = (
    (TIME_QUESTION, DURATION.search),
    (r"截止|什么时候|申报期限|何时", deadline),
    (r"奖励|补贴|补助|资助|金额|多少钱|能拿", lambda s: re.search(r"奖励|补贴|补助|资助|给予|支持", s) and MONEY.search(s)),
    (r"负责什么|职责|职能", lambda s: re.search(r"负责|统筹|承担|组织实施", s)
     and not re.search(r"负责解释|解释工作", s)),
)
FILLER = re.compile(rf"{TIME_TAIL}|{TIME_QUESTION}|{UPPER}|{LOWER}|请问|请介绍|请列出|有哪些|有什么|是什么|分别是|能拿|补贴|奖励|补助|资助|"
                    r"(?<=计划)[中里对]|(?<=政策)[中里对]|申报|申请|什么时候|截止|何时|负责什么|职能|职责|是多少钱|多少钱|是多少|多少|是哪里|在哪[里儿]?|"
                    r"怎么|如何|什么|哪些|关于|[的？?，,。\s]+")
Profile = namedtuple("Profile", "topics attribute duration")
PERMISSION = re.compile(r"(?:是否可以|是否允许|能否|可不可以|能不能)([\u3400-\u9fff]{2,10})[？?]?$")
BARE_LIMIT = re.compile(r"(?:每次|单次|一次|时长|时间|期限|使用时长|借期|[（(]?\d+[)）.、])?\s*(?:" + UPPER + "|" + LOWER + ")")


def topic_terms(q):
    return tuple(x.casefold() for x in FILLER.split(q) if x and x not in ("是", "为", "呢", "？"))


def profile(q):
    permission = PERMISSION.search(q)
    if permission:
        action = permission[1]
        # “是否可以”只引用明确写有允许/禁止该动作的条款，不把搜到动作名当作允许。
        explicit = re.compile(r"(?:允许|可以|可|不得|不能|禁止|不支持|不允许|不可)" + re.escape(action))
        subject = topic_terms(q[:permission.start()])
        return Profile((*subject, action) if subject else (), explicit.search, False)
    topics = topic_terms(q)
    attribute = next((test for pattern, test in ATTRIBUTES if re.search(pattern, q)), None)
    duration = bool(re.search(TIME_QUESTION, q))
    fee = re.search(r"押金|费用|收费", q)
    if fee and attribute is None:
        topics = topic_terms(q.replace(fee[0], " "))
        attribute = lambda s: fee[0] in s and (MONEY.search(s) or re.search(r"不收取|免收|免费", s))
    bound = UPPER if re.search(UPPER, q) else LOWER if re.search(LOWER, q) else None
    if bound and attribute:
        check = attribute
        value = DURATION.pattern if duration else MONEY.pattern
        suffix = r"(?:以内|以下)" if bound == UPPER else "以上"
        limit = re.compile(rf"(?:{bound})(?:为|是|可达|可|支持|补贴|使用|借用|停放|停留|需要|须|\s|[：:])*{value}|{value}{suffix}")
        attribute = lambda s: check(s) and limit.search(s)
    return Profile(topics, attribute, duration)


def question_parts(q):
    """只拆已经结束一个问句再问下一项的并列问题，不把条件从问句中剪掉。"""
    parts = [s.strip() for s in re.split(r"[，,；;]|[？?][，,；;]?\s*(?=\S)", q) if s.strip()]
    if 1 < len(parts) <= 6 and all(re.search(rf"{TIME_QUESTION}|多少|什么|哪些|几[天日周]|哪天", s) for s in parts):
        return parts
    return [q]


def evidence_fields(parts):
    """后续省略主题的字段继承首问主题，不能借另一份通知的相似数字作答。"""
    subject = profile(parts[0]).topics
    for part in parts:
        field = profile(part)
        yield field._replace(topics=tuple(dict.fromkeys((*subject, *field.topics))))


def strength(query, title, sentence):
    topics, attribute, duration = query
    if not any(len(t) >= 2 for t in topics) or (attribute and not attribute(sentence)):
        return 0
    title, text = title.casefold(), sentence.casefold()
    # 限定词必须完整覆盖。允许一个连续主题跨“标题前缀 + 条款后缀”，
    # 如计划名在标题、办理事项在正文；不是任意二元词沾边就算有依据。
    for t in topics:
        if t not in title and t not in text and not (
            attribute and any(t[:i] in title and t[i:] in text
                              for i in range(max(2, len(t)-len(text)), min(len(title), len(t)-2)+1))
        ):
            return 0
    if duration:
        # 检查含数值的短句本身。“园区停车不得过夜，摄像记录最长为三天”
        # 虽然同句出现两个锚，后三天也并非允许停车的时长。
        clauses = re.split(r"[，,；;]", text)
        if not any(attribute(c) and (any(t in c for t in topics) or BARE_LIMIT.match(c.strip())) for c in clauses):
            return 0
    # 无明确属性时，标题本身、泛泛提及或只匹配部分短语不足以答复。
    if not attribute and (topics[-1] not in text or text.strip("。 ：:") == title or text.endswith(("？", "?", "：", ":"))
                          or len(text.strip("。 ：:")) <= sum(map(len, topics)) + 1):
        return 0
    return 1 + sum(t in title for t in topics) + sum(t in text for t in topics)

"""从查询识别主题与所问属性；只给能同时定位主题和属性的原句加权。"""
import re


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
ATTRIBUTES = (
    (r"截止|什么时候|申报期限|何时", deadline),
    (r"奖励|补贴|补助|最高|金额|资助", lambda s: re.search(r"奖励|补贴|补助|资助|给予|支持", s)
     and re.search(r"\d+(?:\.\d+)?\s*(?:[万亿]?元|[%％])", s)),
    (r"负责什么|职责|职能", lambda s: re.search(r"负责|统筹|承担|组织实施", s)
     and not re.search(r"负责解释|解释工作", s)),
)
FILLER = re.compile(r"请问|请介绍|请列出|有哪些|有什么|是什么|分别是|能拿|补贴|奖励|资助|最高|"
                    r"申报|申请|什么时候|截止|何时|负责什么|职能|职责|是多少|多少|是哪里|在哪[里儿]?|"
                    r"怎么|如何|什么|哪些|关于|[的？?，,。\s]+")


def profile(q):
    topics = tuple(x.casefold() for x in FILLER.split(q) if len(x) >= 2)
    attribute = next((test for pattern, test in ATTRIBUTES if re.search(pattern, q)), None)
    return topics, attribute


def strength(query, title, sentence):
    topics, attribute = query
    if not topics or (attribute and not attribute(sentence)):
        return 0
    title, text = title.casefold(), sentence.casefold()
    if not all(t in title or t in text for t in topics):
        return 0
    # 无明确属性时，标题本身、泛泛提及或只匹配部分短语不足以答复。
    if not attribute and (topics[-1] not in text or text.strip("。 ：:") == title or text.endswith(("？", "?", "：", ":"))
                          or len(text.strip("。 ：:")) <= sum(map(len, topics)) + 1):
        return 0
    return 1 + sum(t in title for t in topics) + sum(t in text for t in topics)

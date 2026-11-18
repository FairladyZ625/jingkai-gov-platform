"""走访提取的字段约束、引文核验，以及 #16 模型接入前的进程内 provider。"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from haiknow_sdk import DataError
from haiknow_sdk.preview.components.c01 import Field, Schema

AMOUNTS = {
    "amounts.rent": "年房租",
    "amounts.area": "经营面积",
    "amounts.computePurchase": "算力采购额",
    "amounts.dataPurchase": "数据采购额",
    "revenue.value": "营收",
}
CONTACT_PHONE = Field("phone", "联系电话", required=True, pattern=r"[0-9+() -]{7,24}")
CONTACT = Schema((
    Field("name", "联系人姓名", required=True, pattern=r"[\u4e00-\u9fffA-Za-z· ]{2,32}"),
    Field("title", "联系人职务", required=True, pattern=r"[\u4e00-\u9fffA-Za-z· ]{2,32}"),
    CONTACT_PHONE,
))
FIELDS = Schema((
    Field("employees", "从业人数", "number", required=True, min=0),
    Field("yearsInZone", "入区年数", "number", required=True, min=0),
    CONTACT_PHONE,
    Field("contacts", "新增联系人"),
    Field("license", "新增许可证", required=True, pattern=r"[\u4e00-\u9fffA-Za-z（）()· ]{2,48}"),
    Field("scale", "企业规模", "enum", required=True, options=("大型", "中型", "小型", "微型")),
    *(Field(key, label, "number", required=True, min=0) for key, label in AMOUNTS.items()),
))
# 经办人界面延续数字打码。低权限和工具响应在路由层改用结构化摘要。
CHINESE_DIGITS = "零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬億"
NUMBERS = re.compile(
    rf"\d(?:[\d.,，．\-\s]*\d)?|[{CHINESE_DIGITS}]{{7,}}|[{CHINESE_DIGITS}]+(?=[元圆块])"
)
ISSUE = re.compile(r"询问|希望|反映|想了解|想申请|需要|能不能|协调")
SENTENCE = re.compile(r"[^。；;！？!?\n]+")
CLAUSE = re.compile(r"[^。；;，,！？!?\n]+")
NEGATED = re.compile(
    r"尚未|还未|从未|尚无|没有|未取得|未获得|未获|未拿到|未持有|未能|没取得|没能|并未|并非|不是|不确定|正在|计划|拟|希望|预计|申请中"
)
RANGE = r"(?!\s*(?:到|至|[-~～–—－]|[+＋]))"
CONTACT_CLAIM = re.compile(
    r"(?:新任)?(行政主管|总经理|财务总监|负责人|经理|主管|联系人)"
    r"[:：为是\s]*([\u4e00-\u9fff]{2,4})[（(，,\s]*(?:电话|手机)[:：\s]*(1[0-9]{10})(?!\d)"
)
# 模型金额一律以元计，面积以平方米计。识别显式单位后才能确认数值。
CURRENCY = {"元": 1, "万元": 10_000, "亿元": 100_000_000}
NUMERIC_UNITS = {
    **dict.fromkeys(AMOUNTS, CURRENCY),
    "amounts.area": {"㎡": 1, "平方米": 1, "平米": 1},
    "employees": {"人": 1},
    "yearsInZone": {"年": 1},
}
MEASURE = r"\s*(?:现有|已有|有|增至|增加至|降至|达到|达|为|约为|约|是|[:：]){0,2}\s*"
NUMBER = r"[0-9]+(?:\.[0-9]+)?"
MONEY = rf"({NUMBER})\s*(亿元|万元|元)(?:\s*人民币)?(?!\s*(?:美元|美金|欧元|港[元币]|日元|英镑|圆|圓|角|分|多|余|\d)){RANGE}"
REVENUE_INTENT = re.compile(rf"营收{MEASURE}[{CHINESE_DIGITS}\d]")
NUMBER_CLAIMS = {
    "employees": rf"(?:员工|职工|从业人数|员工人数|职工人数|人数){MEASURE}({NUMBER})\s*人(?![次均天月年多余\d]){RANGE}",
    "yearsInZone": rf"入区{MEASURE}(?:已满|满)?\s*({NUMBER})\s*年(?![度多余\d]){RANGE}",
    "amounts.rent": rf"(?:房租|租金){MEASURE}{MONEY}",
    "amounts.area": rf"(?:面积){MEASURE}({NUMBER})\s*(?:㎡|平方米|平米)(?![多余\d]){RANGE}",
    "amounts.computePurchase": rf"算力(?:采购额|采购金额|采购费用){MEASURE}{MONEY}",
    "amounts.dataPurchase": rf"数据(?:采购额|采购金额|采购费用){MEASURE}{MONEY}",
    "revenue.value": rf"营收{MEASURE}{MONEY}",
}
LICENSE = re.compile(r"(?:已获得|已取得|已拿到|已获|获得|取得|拿到)\s*(?:了\s*)?([\u4e00-\u9fffA-Za-z（）()· ]{2,44}?许可证)")
SCALE = re.compile(r"(?:企业规模|规模)\s*(?:为|是|[:：])?\s*(大型|中型|小型|微型)")
PHONE = r"\s*(?:变更为|更换为|更新为|为|是|[:：])?\s*(1[0-9]{10})(?!\d)"



class OutboundDenied(DataError):
    def __init__(self):
        super().__init__("outbound_denied", "企业数据仅可交给本地或白名单模型")
        self.status = 403


@dataclass(frozen=True)
class Destination:
    id: str
    kind: str

    def require_allowed(self, allowlist):
        if self.kind not in ("local", "mock") and self.id not in allowlist:
            raise OutboundDenied()


@dataclass(frozen=True)
class Extractor:
    destination: Destination
    invoke: Callable[[dict, str], dict]
    allowlist: frozenset[str] = frozenset()

    def extract(self, company, notes):
        self.destination.require_allowed(self.allowlist)
        return self.invoke(company, notes)


def visible_text(text):
    return NUMBERS.sub("****", text)


@dataclass(frozen=True)
class Claim:
    field: str
    value: object
    start: int
    end: int


def claims_in(notes):
    """从完整分句识别字段、值、单位和位置，避免模型裁剪掉限定语。"""
    claims = []
    blocked_license = [(s.start(), s.end()) for s in SENTENCE.finditer(notes) if NEGATED.search(s[0])]
    for clause in CLAUSE.finditer(notes):
        text = clause[0]
        if NEGATED.search(text):
            continue

        def collect(field, match, value):
            claims.append(Claim(field, value, clause.start() + match.start(), clause.start() + match.end()))

        for field, pattern in NUMBER_CLAIMS.items():
            for match in re.finditer(pattern, text):
                value = Decimal(match[1])
                if match.lastindex == 2:
                    value *= CURRENCY[match[2]]
                collect(field, match, value)
        if not any(start <= clause.start() < end for start, end in blocked_license):
            for match in LICENSE.finditer(text):
                collect("license", match, match[1])
        for match in SCALE.finditer(text):
            collect("scale", match, match[1])
        contacts = list(CONTACT_CLAIM.finditer(text))
        for match in contacts:
            title, name, phone = match.groups()
            collect("contacts", match, {"title": title, "name": name, "phone": phone})
        labels = "企业电话|联系电话" if contacts else "企业电话|联系电话|联系人电话|手机|电话"
        for match in re.finditer(rf"(?:{labels}){PHONE}", text):
            if not any(contact.start() <= match.start() < contact.end() for contact in contacts):
                collect("phone", match, match[1])
    return claims


def evidence(notes, quote, field, value, claims):
    if not isinstance(quote, str) or not quote.strip():
        return None
    matches = []
    for occurrence in re.finditer(re.escape(quote), notes):
        supported = [
            c for c in claims if c.field == field and occurrence.start() <= c.start and c.end <= occurrence.end()
        ]
        if not supported or any(c.value != value for c in supported):
            return None
        matches.append(supported[0])
    if not matches:
        return None
    match = matches[0]
    source = notes[match.start:match.end]
    if field in AMOUNTS or field in ("phone", "contacts"):
        source = NUMBERS.split(source, maxsplit=1)[0].strip()
    return source or None


def normalize(field, value):
    definition = FIELDS.by_key.get(field)
    if definition is None:
        raise ValueError("不支持该建议字段")
    if field == "contacts":
        if not isinstance(value, dict) or any(not isinstance(v, str) for v in value.values()):
            raise ValueError("联系人须包含姓名、职务和电话")
        draft = CONTACT.draft(value)
        if not draft.ok:
            raise ValueError("联系人字段缺失或格式错误")
        return draft.values
    if definition.type == "text" and not isinstance(value, str):
        raise ValueError("字段必须为文本")
    draft = Schema((definition,)).draft({field: value})
    if not draft.ok:
        raise ValueError(draft.errors[0].message)
    clean = draft.values[field]
    if field in ("employees", "yearsInZone"):
        if isinstance(clean, float) and not clean.is_integer():
            raise ValueError("字段必须为整数")
        return int(clean)
    if field in AMOUNTS:
        try:
            number = float(clean)
        except OverflowError as exc:
            raise ValueError("金额或面积超出可表示范围") from exc
        if not math.isfinite(number):
            raise ValueError("金额或面积超出可表示范围")
        return number
    return clean


def candidates(extractor, company, notes):
    try:
        result = extractor.extract(company, notes)
    except OutboundDenied:
        return [], [], "企业数据仅可交给本地或白名单模型，走访已保存"
    except Exception:
        # 只隔离 provider 调用。上游异常可能携带原文或凭据，回复使用固定文字。
        return [], [], "模型调用失败，走访已保存，可人工核对"
    if (not isinstance(result, dict) or not isinstance(result.get("proposals"), list)
            or not isinstance(result.get("issues"), list)):
        return [], [], "模型返回格式无效，走访已保存，可人工核对"

    claims = claims_in(notes)
    proposed = {}
    for candidate in result["proposals"]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("field"), str):
            continue
        field = candidate["field"]
        if field in proposed:
            continue
        quote = candidate.get("source")
        try:
            new = normalize(field, candidate.get("new"))
        except ValueError:
            continue
        checked_value = new
        if field in NUMERIC_UNITS:
            # 未声明单位的模型候选使用约定基准单位。声明单位时先核对，再换到基准单位。
            units = NUMERIC_UNITS[field]
            unit = candidate.get("unit")
            if "unit" in candidate and (not isinstance(unit, str) or unit not in units):
                continue
            checked_value = Decimal(str(new)) * units.get(unit, 1)
        source = evidence(notes, quote, field, checked_value, claims)
        if source:
            if field in AMOUNTS:
                new = float(checked_value)
                if not math.isfinite(new):
                    continue
            proposed[field] = (field, new, source, quote)

    issues = list(dict.fromkeys(
        text.strip() for text in result["issues"]
        if isinstance(text, str) and text.strip() and text in notes
    ))
    warning = None
    revenue_starts = {claim.start for claim in claims if claim.field == "revenue.value"}
    if (len(proposed) < len(result["proposals"])
            or any(match.start() not in revenue_starts for match in REVENUE_INTENT.finditer(notes))):
        warning = "已忽略字段、原文或单位无法核实的建议，请人工核对"
    return list(proposed.values()), issues, warning


def mock_extract(_company, notes):
    """供开发期使用的确定性提取。未来由网关注入已选定且禁止回退的 provider。"""
    return {
        "proposals": [
            {"field": claim.field, "new": float(claim.value) if isinstance(claim.value, Decimal) else claim.value,
             "source": notes[claim.start:claim.end]}
            for claim in claims_in(notes)
        ],
        "issues": [part for part in re.split(r"[。；;\n]", notes) if ISSUE.search(part)],
    }


MOCK_EXTRACTOR = Extractor(Destination("enterprise-in-process", "mock"), mock_extract)

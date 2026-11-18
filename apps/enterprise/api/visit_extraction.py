"""走访提取的字段约束、引文核验，以及 #16 模型接入前的进程内 provider。"""

import re
from collections.abc import Callable
from dataclasses import dataclass

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
# 自由文本无法从台账结构区分数值用途。对外遮盖数字，证据只选仍可显示的原文片段。
CHINESE_DIGITS = "零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬億"
NUMBERS = re.compile(
    rf"\d(?:[\d.,，．\-\s]*\d)?|[{CHINESE_DIGITS}]{{7,}}|[{CHINESE_DIGITS}]+(?=[元圆块])"
)
ISSUE = re.compile(r"询问|希望|反映|想了解|想申请|需要|能不能|协调")


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


def evidence(notes, quote):
    if not isinstance(quote, str) or not quote.strip() or quote not in notes:
        return None
    visible = [part.strip() for part in NUMBERS.split(quote) if any(c.isalpha() for c in part)]
    return max(visible, key=len, default=None)


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
            return float(clean)
        except OverflowError as exc:
            raise ValueError("金额或面积超出可表示范围") from exc
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

    proposed = {}
    for candidate in result["proposals"]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("field"), str):
            continue
        field = candidate["field"]
        quote = candidate.get("source")
        source = evidence(notes, quote)
        if not source or field in proposed:
            continue
        try:
            new = normalize(field, candidate.get("new"))
        except ValueError:
            continue
        proposed[field] = (field, new, source, quote)

    issues = list(dict.fromkeys(
        visible_text(text.strip()) for text in result["issues"]
        if isinstance(text, str) and text.strip() and text in notes
    ))
    warning = None
    if len(proposed) < len(result["proposals"]):
        warning = "已忽略字段无效、重复或原文无法核实的建议"
    return list(proposed.values()), issues, warning


def mock_extract(_company, notes):
    """供开发期使用的确定性提取。未来由网关注入已选定且禁止回退的 provider。"""
    proposals = []
    contact = re.search(
        r"(?:新任)?(行政主管|总经理|财务总监|负责人|经理|主管|联系人)"
        r"[:：为是\s]*([\u4e00-\u9fff]{2,4})[（(，,\s]*(?:电话|手机)[:：\s]*(1\d{10})(?!\d)",
        notes,
    )
    if contact:
        title, name, phone = contact.groups()
        proposals.append({"field": "contacts", "new": {"name": name, "title": title, "phone": phone},
                          "source": contact[0]})
    if "出版物经营许可证" in notes and re.search(r"(?:已获|取得|拿到)[^。；\n]{0,8}出版物经营许可证", notes):
        proposals.append({"field": "license", "new": "出版物经营许可证", "source": "出版物经营许可证"})
    rules = (
        ("employees", r"(?:员工|人数|职工)[^\d。；\n]{0,8}(\d+)\s*人", 1),
        ("phone", r"(?:联系电话|联系人电话|手机|电话)[^\d。；\n]{0,8}(1\d{10})(?!\d)", 1),
        ("amounts.rent", r"(?:房租|租金)[^\d。；\n]{0,8}(\d+(?:\.\d+)?)\s*万", 10_000),
        ("amounts.area", r"(?:面积)[^\d。；\n]{0,8}(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米)", 1),
        ("amounts.computePurchase", r"算力[^\d。；\n]{0,8}(\d+(?:\.\d+)?)\s*万", 10_000),
        ("amounts.dataPurchase", r"数据[^\d。；\n]{0,8}(\d+(?:\.\d+)?)\s*万", 10_000),
        ("revenue.value", r"营收[^\d。；\n]{0,8}(\d+(?:\.\d+)?)\s*万", 10_000),
    )
    for field, pattern, multiplier in rules:
        if field == "phone" and contact:
            pattern = r"(?:企业电话|联系电话)[^\d。；\n]{0,8}(1\d{10})(?!\d)"
        match = re.search(pattern, notes)
        if match:
            value = match[1] if field == "phone" else float(match[1]) * multiplier
            proposals.append({"field": field, "new": value, "source": match[0]})
    return {"proposals": proposals, "issues": [
        part for part in re.split(r"[。；;\n]", notes) if ISSUE.search(part)
    ]}


MOCK_EXTRACTOR = Extractor(Destination("enterprise-in-process", "mock"), mock_extract)

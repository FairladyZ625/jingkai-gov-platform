"""§4.4 模板目录与确定性模拟起草。示例字段仅用于展示。"""
from html import unescape

from haiknow_sdk import DataError
from haiknow_sdk.preview.components.c06 import Book, Slot
from haiknow_sdk.preview.components.common import is_missing

GROUPS = (
    ("A", "发布政策与安排"),
    ("B", "面向企业组织事项"),
    ("C", "公开结果与回应"),
)


def template(group, name, purpose, kind, inputs, title, paragraphs, *, required, to="{{to}}"):
    return {
        "group": group, "name": name, "purpose": purpose, "kind": kind,
        "inputs": inputs, "title": title, "paragraphs": paragraphs,
        "required": required, "to": to,
    }


TEMPLATES = {
    "T01": template("A", "政策措施印发通知", "将已形成的政策措施印发给相关机构", "通知", (
        ("title", "政策名称", "关于支持人工智能原生人才发展的若干措施"),
        ("target", "印发对象", "各部门、各街道、各有关单位"),
        ("effect", "生效日期", "2026-12-01"),
    ), "关于印发《{{title}}》的通知", (
        "现将《{{title}}》印发给你们，请结合实际组织实施。",
        "生效日期为{{effect}}。",
    ), required=("title", "target"), to="{{target}}"),
    "T02": template("A", "工作方案印发通知", "把实施方案发给执行单位", "通知", (
        ("title", "方案名称", "共享智能体工作站试点工作方案"),
        ("target", "印发对象", "局属各处室"),
        ("lead", "牵头部门", "综合科"),
    ), "关于印发《{{title}}》的通知", (
        "现将《{{title}}》印发给你们，请按方案做好组织落实工作。",
        "牵头部门为{{lead}}。",
    ), required=("title", "target"), to="{{target}}"),
    "T03": template("B", "奖励申报通知", "某项政策进入申报期，告知企业如何申报", "通知", (
        ("policy", "政策依据", "RP-023"),
        ("start", "申报开始", "2026-11-11"),
        ("end", "申报截止", "2026-11-30"),
        ("method", "申报渠道及提交方式", ""),
        ("contact", "咨询电话", ""),
    ), "关于开展奖励申报工作的通知", (), required=("policy", "start", "end"), to="各有关单位："),
    "T04": template("B", "项目公开征集通知", "向企业征集项目、课题或方案", "通知", (
        ("title", "征集方向", "AI 场景应用示范项目"),
        ("end", "截止时间", "2026-12-20"),
        ("support", "支持方式", "按投入 30%，最高 500 万元"),
    ), "关于征集{{title}}的通知", (
        "现公开征集{{title}}。",
        "请于{{end}}前提交材料。申报方式为{{method}}。",
        "支持方式为{{support}}。",
    ), required=("title", "end")),
    "T05": template("B", "项目榜单发布通知", "发布可揭榜的项目清单", "通知", (
        ("batch", "榜单批次", "第四批"), ("count", "项目数量", "12"),
    ), "关于发布{{batch}}项目榜单的通知", (
        "现发布{{batch}}项目榜单，共{{count}}项。",
        "项目清单及揭榜方式为{{requirements}}。",
    ), required=("batch",)),
    "T06": template("B", "申报期限调整通知", "已发布事项需要延长或变更时间", "通知", (
        ("orig", "原通知名称", "关于开展 2026 年数据券后续批次申报工作的通知"),
        ("oldEnd", "原截止时间", "2026-11-30"),
        ("newEnd", "新截止时间", "2026-12-15"),
        ("reason", "调整原因", "部分企业交易凭证开具延迟"),
    ), "关于调整《{{orig}}》申报期限的通知", (
        "因{{reason}}，现将《{{orig}}》的申报截止时间由{{oldEnd}}调整至{{newEnd}}。",
        "请按照调整后的期限提交申报。",
    ), required=("orig", "oldEnd", "newEnd")),
    "T07": template("B", "企业经营情况调查通知", "要求企业按口径和期限填报经营数据", "通知", (
        ("period", "统计期间", "2026 年 1—10 月"),
        ("end", "填报截止", "2026-11-28"),
    ), "关于开展{{period}}企业经营情况调查的通知", (
        "本次调查统计期间为{{period}}，请于{{end}}前填报。",
        "统计口径及填报方式为{{requirements}}。",
    ), required=("period", "end")),
    "T08": template("C", "拟推荐结果公示", "最终确定前公开候选名单", "公示", (
        ("title", "公示事项", "2026 年度接诉即办先进单位"),
        ("days", "公示期（工作日）", "5"),
        ("list", "拟推荐名单", "书香里文化、星河智驾、天工机器人"),
    ), "关于{{title}}拟推荐名单的公示", (
        "现对{{title}}拟推荐名单予以公示。拟推荐名单为{{list}}。",
        "公示期为{{days}}个工作日。异议受理方式为{{method}}。",
    ), required=("title",), to=""),
    "T09": template("C", "行政许可事项公示", "许可事项依法公示", "公示", (
        ("item", "许可事项", "互联网上网服务营业场所筹建"),
        ("applicant", "申请主体", "北京亦城网咖有限公司"),
    ), "关于{{item}}的公示", (
        "现将{{item}}相关信息予以公示。",
        "申请主体为{{applicant}}。公示期限为{{period}}，异议受理方式为{{method}}。",
    ), required=("item",), to=""),
    "T10": template("C", "企业诉求答复意见", "回应企业诉求，说明研究、办理和后续安排", "函", (
        ("ent", "企业", "E001"),
        ("issue", "诉求内容", "咨询实体书店房租补贴申报时间"),
        ("policy", "政策依据", "PI-03"),
    ), "关于企业诉求的答复意见", (
        "你单位反映的诉求为{{issue}}。",
        "政策依据为{{policy}}。",
        "办理情况及后续安排为{{requirements}}。",
    ), required=("ent", "issue")),
}

COMMON_SLOTS = {
    "docNo": "发文字号", "to": "主送机关", "sign": "发文机关", "date": "成文日期",
    "requirements": "具体要求", "method": "办理方式", "period": "公示期限",
}
PUBLIC_FIELDS = ("group", "name", "purpose", "inputs", "kind")


def catalogue():
    groups = dict(GROUPS)
    items = [
        {"id": key, "groupName": groups[row["group"]], **{field: row[field] for field in PUBLIC_FIELDS}}
        for key, row in TEMPLATES.items()
    ]
    return {"items": items, "groups": GROUPS}


def draft_template(template_id, inputs):
    spec = TEMPLATES.get(template_id)
    if spec is None:
        raise DataError("not_found", "公文模板不存在")
    missing = [key for key in spec["required"] if is_missing(inputs.get(key))]
    if missing:
        raise DataError("invalid_request", "请填写必填公文要素", fields=missing)
    return spec


def mock_draft(spec, inputs, extra):
    labels = {**COMMON_SLOTS, **{key: label for key, label, _ in spec["inputs"]}}
    book = Book(tuple(Slot(key, label) for key, label in labels.items()))

    def render(value):
        # C06 面向 HTML。这里输出 §2.5 约定的纯文本，由消费端负责显示转义。
        return unescape(book.render(value, inputs).html)

    return {
        "title": render(spec["title"]), "docNo": render("{{docNo}}"),
        "to": render(spec["to"]), "paragraphs": [*(render(p) for p in spec["paragraphs"]), *extra],
        "sign": render("{{sign}}"), "date": render("{{date}}"),
    }

"""按所选政策支持生成参考清单，并准备公文起草参数。"""

from html import unescape

from haiknow_sdk.preview.components.c06 import Book, Slot

from .policy_calc import estimate


_HEADER = Book((Slot("subject"),))
_SECTION = Book((Slot("title"), Slot("guidance", required=False), Slot("department")))
_SECTION_TEMPLATE = "{{title}}\n{{guidance}}落款：{{department}}\n咨询电话：请填写"
_FOOTER = "具体申报条件、材料及受理时间以正式申报通知为准。"
_TEMPLATE_ID = "T10"  # 公文的「企业诉求答复意见」模板


def build_notice(ent_id: str | None, items: list[dict], *, subject_type=None, amounts=None) -> dict:
    subject = f"企业编号：{ent_id}" if ent_id else f"申报对象：{subject_type}（手动描述）"
    heading = _HEADER.render("政策参考清单\n{{subject}}", {"subject": subject})
    sections = [heading.html]
    for index, item in enumerate(items, 1):
        source = item.get("source") or {}
        department = (source.get("deptResp") or "").strip() or "请填写"
        times = item.get("times") or {}
        rule = item.get("rule") or {}
        trial = estimate(rule, (amounts or {}).get(item["id"]))
        fields = (
            ("政策依据", " ".join(value for value in (item.get("docNo"), item.get("clause")) if value)),
            ("支持标准", rule.get("text")),
            ("试算参考", trial["text"] if trial and trial["kind"] == "ratio" else None),
            ("申报时间", times.get("deadlineText") or times.get("window")),
            ("需准备材料", "、".join(item.get("materials") or [])),
            ("尚需确认", "、".join(item.get("pending") or [])),
            ("原文", source.get("url")),
        )
        guidance = "".join(f"{label}：{value}\n" for label, value in fields if value)
        section = _SECTION.render(
            _SECTION_TEMPLATE, {"title": item["title"], "guidance": guidance, "department": department},
        )
        sections.append(f"{index}. {section.html}")

    # C06 转义的是 HTML。§4.1 的 text 供纯文本控件使用。
    text = unescape("\n\n".join([*sections, _FOOTER]))
    item_ids = [item["id"] for item in items]
    issue = "咨询" + "、".join(item["title"] for item in items) + "的申报事宜"
    return {
        "text": text,
        "deepLink": {
            "app": "document",
            "route": "new",
            "params": {
                **({"entId": ent_id} if ent_id else {}),
                "itemIds": item_ids,
                "templateId": _TEMPLATE_ID,
                "from": "policy",
                "inputs": {"ent": ent_id or "", "policy": item_ids[0], "issue": issue},
                "notice": text,
            },
        },
    }

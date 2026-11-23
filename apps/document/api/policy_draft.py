"""奖励申报通知只依据政策应用的公开目录。人工填报与来源确认分开。"""

from haiknow_sdk import DataError

from apps.policy.api.policy_catalog import catalog, item_with_doc

from . import templates
from .checks import read_date


def _cn_date(value):
    return f"{value.year}年{value.month}月{value.day}日"


def _line(value, missing):
    return (value or "").strip().rstrip("。") or f"【待补：{missing}】"


def reward_notice(spec, inputs, extra):
    policy_id = inputs["policy"].strip()
    items, docs = catalog()
    item = items.get(policy_id)
    if not item:
        raise DataError("not_found", "所选政策不在公开目录中，请重新选择")
    policy = item_with_doc(item, docs[item["doc"]])
    times = policy["times"]
    if (policy.get("historical") or times.get("valid", "").startswith("已替代")
            or policy["docState"] in {"已失效", "已废止", "已替代"}):
        raise DataError("invalid_request", "该事项为历史政策，不能作为奖励申报通知的依据")

    start, end = (read_date(inputs[field]) for field in ("start", "end"))
    if not start or not end or end < start:
        raise DataError("invalid_request", "请填写有效的申报起止日期，截止日期不能早于开始日期")
    span = f"{_cn_date(start)}至{_cn_date(end)}"
    notice = times.get("notice") or {}
    window = notice.get("window") or {}
    same_notice = (notice.get("scope") == "与本条款对应的最近一次申报通知"
                   and bool(notice.get("url"))
                   and (start.isoformat(), end.isoformat()) == (window.get("start"), window.get("end")))
    if same_notice and times.get("open") is not False:
        period = f"申报时间为{span}，以对应批次正式申报通知为准。"
    elif same_notice:
        period = f"公开目录所载批次为{span}，该批次已结束。【待补：经确认的申报期限】"
    else:
        period = f"拟于{span}受理，尚未与正式申报通知核对。【待补：经确认的申报期限】"

    basis = f"《{policy['docTitle']}》"
    if policy["docNo"]:
        basis += f"（{policy['docNo']}）"
    conditions = "；".join(dict.fromkeys(c["label"].rstrip("。；") for c in policy["conditions"] if c.get("label")))
    materials = "、".join(policy.get("materials") or ())
    content = templates.mock_draft(spec, inputs, [])
    content["title"] = f"关于开展{policy['title']}申报工作的通知"
    content["paragraphs"] = [
        f"根据{basis}有关规定，现将{policy['title']}申报有关事项通知如下。",
        f"一、申报对象。{_line(conditions, '申报对象及资格条件')}。",
        f"二、支持标准。{_line((policy.get('rule') or {}).get('text'), '支持标准')}。",
        f"三、申报时间。{period}",
        (f"四、申报材料。公开目录列有{materials}，最终清单以正式申报通知为准。"
         if materials else "四、申报材料。【待补：正式申报材料清单】"),
        f"五、申报方式。{_line(inputs.get('method'), '申报渠道及提交方式')}。",
        f"六、咨询电话。{_line(inputs.get('contact'), '咨询电话')}。",
        *extra,
    ]
    return content

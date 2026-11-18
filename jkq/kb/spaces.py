"""接口规范 §2.6 的空间与角色。"""
from collections import Counter

NAMES = {"policy": "政策库", "template": "公文范文", "minutes": "会议纪要",
         "rules": "部门制度", "enterprise": "企业档案"}
INTERNAL = ("admin", "leader", "member")


def visible_spaces(user):
    roles = set(user.roles)
    if "partner" in roles:
        return ("policy",)
    return tuple(NAMES) if roles.intersection(INTERNAL) else ()


def spaces(user, documents):
    counts = Counter(doc["space"] for doc in documents)
    expiring = Counter(doc["space"] for doc in documents if doc["status"] == "即将到期")
    return [
        dict(id=key, name=NAMES[key], icon=NAMES[key][0], desc=NAMES[key],
             roles=[*INTERNAL, "partner"] if key == "policy" else list(INTERNAL),
             visible=True, sensitive=key == "enterprise", count=counts[key], expiring=expiring[key])
        for key in visible_spaces(user)
    ]

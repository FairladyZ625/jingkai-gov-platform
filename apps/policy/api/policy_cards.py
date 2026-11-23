"""政策工具输出的 §4.5 对话卡片。"""


def match_card(ent_id: str, results: list[dict]) -> dict:
    return {
        "type": "policy-match",
        "entId": ent_id,
        "results": results[:5],
        "deepLink": {"app": "policy", "route": "match", "params": {"entId": ent_id}},
    }


def items_card(items: list[dict]) -> dict:
    ids = [item["id"] for item in items]
    return {
        "type": "policy-items",
        "ids": ids,
        "deepLinks": [
            {"app": "policy", "route": "detail", "params": {"tab": "library", "itemId": item_id}}
            for item_id in ids
        ],
    }

"""告知单和卡片的输出契约。"""

import pytest

from apps.policy.api.policy_cards import items_card, match_card
from apps.policy.api.policy_notice import build_notice


def test_notice_keeps_department_per_item_and_fills_document_inputs():
    items = [
        {"id": "P1", "title": "A & B 申报", "source": {"deptResp": "发展部门", "phone": "测试电话"}},
        {"id": "P2", "title": "C < D 申报", "source": {"deptResp": "服务部门"}},
    ]
    result = build_notice("E001", items)

    assert "1. A & B 申报\n落款：发展部门\n咨询电话：请填写" in result["text"]
    assert "2. C < D 申报\n落款：服务部门\n咨询电话：请填写" in result["text"]
    assert "测试电话" not in result["text"]
    assert result["deepLink"] == {
        "app": "document",
        "route": "new",
        "params": {
            "entId": "E001",
            "itemIds": ["P1", "P2"],
            "templateId": "T10",
            "from": "policy",
            "inputs": {"ent": "E001", "policy": "P1", "issue": "咨询A & B 申报、C < D 申报的申报事宜"},
            "notice": result["text"],
        },
    }


@pytest.mark.parametrize("source", [None, {}, {"deptResp": "  "}])
def test_missing_responsible_department_requires_manual_fill(source):
    result = build_notice("E002", [{"id": "P1", "title": "示例事项", "source": source}])
    assert "落款：请填写\n咨询电话：请填写" in result["text"]


@pytest.mark.parametrize("count", [0, 5, 8])
def test_match_card_keeps_upstream_order_and_caps_results(count):
    results = [{"id": f"P{i}"} for i in range(count)]
    assert match_card("E002", results) == {
        "type": "policy-match",
        "entId": "E002",
        "results": results[:5],
        "deepLink": {"app": "policy", "route": "match", "params": {"entId": "E002"}},
    }
    assert len(results) == count


def test_each_policy_result_links_to_its_library_item():
    assert items_card([{"id": "P2"}, {"id": "P1"}]) == {
        "type": "policy-items",
        "ids": ["P2", "P1"],
        "deepLinks": [
            {"app": "policy", "route": "detail", "params": {"tab": "library", "itemId": "P2"}},
            {"app": "policy", "route": "detail", "params": {"tab": "library", "itemId": "P1"}},
        ],
    }
    assert items_card([]) == {"type": "policy-items", "ids": [], "deepLinks": []}

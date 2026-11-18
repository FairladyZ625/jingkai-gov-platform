"""无需运行时依赖的政策事项和核对表回归，随仓库 pytest job 执行。"""

import json
from datetime import date
from pathlib import Path

import pytest

from apps.policy.api.policy_catalog import enterprise_profile, list_items, public_catalog
from apps.policy.api.policy_match import match_items


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/policy_match_case.json"
AS_OF = date(2026, 11, 18)


@pytest.mark.parametrize(
    ("filters", "sample_id", "expected_window"),
    [
        ({"object_type": "个人"}, "RP-021", None),
        ({"window": "open"}, "RP-023", True),
        ({"window": "ended"}, "PI-03", False),
        ({"window": "unknown"}, "RP-006", None),
    ],
)
def test_public_catalog_filters(filters, sample_id, expected_window):
    result = list_items(**({"q": "", "object_type": "", "window": ""} | filters), today=AS_OF)
    assert set(result) == {"items", "total", "docs"}
    assert result["total"] == len(result["items"]) > 0
    sample = next(item for item in result["items"] if item["id"] == sample_id)
    assert sample["times"]["open"] is expected_window
    assert all(item["real"] is True and item["source"]["url"].startswith("https://") for item in result["items"])
    if "object_type" in filters:
        assert {item["object"] for item in result["items"]} == {filters["object_type"]}
    else:
        assert {item["times"]["open"] for item in result["items"]} == {expected_window}


def test_windows_follow_beijing_dates_and_keep_known_cutoff():
    result = list_items("RP-023", "", "", today=date(2026, 11, 10))
    assert result["items"][0]["times"]["open"] is None
    result = list_items("RP-023", "", "", today=date(2026, 11, 30))
    assert result["items"][0]["times"]["open"] is True
    result = list_items("RP-023", "", "", today=date(2026, 12, 1))
    assert result["items"][0]["times"]["open"] is False
    assert result["items"][0]["times"]["notice"]["status"] == "已截止"


def test_only_verified_rows_with_source_and_document_enter_catalog():
    source = {"url": "https://example.org/rule"}
    snapshot = {
        "policyDocs": [{"id": "doc", "real": True, **source}],
        "policies": [
            {"id": "real", "doc": "doc", "real": True, "source": source},
            {"id": "sample", "doc": "doc", "real": False, "source": source},
            {"id": "no-link", "doc": "doc", "real": True},
            {"id": "broken-link", "doc": "doc", "real": True, "source": {"url": "https://[hostname"}},
            {"id": "unsafe-link", "doc": "doc", "real": True, "source": {"url": "javascript:void(0)"}},
            {"id": "missing-doc", "doc": "other", "real": True, "source": source},
        ],
    }
    items, docs = public_catalog(snapshot)
    assert set(items) == {"real"}
    assert set(docs) == {"doc"}


def test_every_demo_match_agrees_with_review_table_and_cites_conditions():
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))
    catalog = list_items("", "", "", today=AS_OF)["items"]
    items = {item["id"]: item for item in catalog}
    report = match_items(enterprise_profile(case["entId"]), catalog, estimate_item=lambda rule, base: None)
    for level, expected_ids in case["expected"].items():
        assert {row["id"] for row in report["results"] if row["level"] == level} == set(expected_ids)
        assert report["summary"][level] == len(expected_ids)
    for row in report["results"]:
        item = items[row["id"]]
        assert row["doc"] == item["docNo"]
        assert row["clause"] == item["clause"]
        assert row["source"] == item["source"]
        assert row["checks"][0]["condition"]["f"] == "subjectType"
        assert [check["condition"] for check in row["checks"][1:]] == item["conditions"]
        assert all(check["label"] in check["reason"] for check in row["checks"])


def test_missing_facts_are_unknown_and_known_scale_and_amount_can_disagree():
    catalog = list_items("", "", "", today=AS_OF)["items"]
    profile = {
        **enterprise_profile("E002"),
        "scale": "大型",
        "computePurchase": 0,
        "majorResearchTask": True,
        "license": None,
    }
    report = match_items(profile, catalog, estimate_item=lambda rule, base: None)
    results = {row["id"]: row for row in report["results"]}
    assert results["RP-006"]["level"] == "no"
    assert results["RP-015"]["level"] == "ok"
    checks = {
        check["condition"]["f"]: check["state"]
        for check in results["rd-3623656-art11-1"]["checks"]
    }
    assert checks == {"subjectType": "ok", "scale": "no", "license": "unknown", "inIntegrationCarrier": "unknown"}

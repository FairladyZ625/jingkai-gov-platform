import json
from pathlib import Path

import pytest

from jkq.orchestrator.cards import render_card
from jkq.orchestrator.ports import ToolCall
from jkq.orchestrator.rules import match_rule

ROOT = Path(__file__).resolve().parents[2]
DEMO = json.loads((ROOT / "tests/fixtures/demo_utterances.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("example", DEMO, ids=[item["text"] for item in DEMO])
def test_demo_intent(example):
    call = match_rule(example["text"])
    assert (call.app, call.tool, call.args) == (example["intent"], example["tool"], example["args"])


def test_demo_fixture_contains_twelve_distinct_script_utterances():
    prototype = ROOT / "prototype/v4"
    scripts = [prototype / "config/demo-script.js", *prototype.glob("apps/*/app.js"),
               prototype / "apps/kb/config.js"]
    source = "\n".join(path.read_text(encoding="utf-8") for path in scripts)
    seed = json.loads((ROOT / "data/seed/demo.json").read_text(encoding="utf-8"))
    for ent in seed["enterprises"]:
        source = source.replace(f"${{seedShort('{ent['id']}')}}", ent["short"])
    texts = {item["text"] for item in DEMO}
    assert len(DEMO) == len(texts) == 12
    missing = [text for text in texts if f"'{text}'" not in source and f"`{text}`" not in source]
    assert not missing


def test_rules_accept_seed_short_and_full_names():
    assert match_rule("书香里文化能申请哪些支持？") == ToolCall("policy.match", {"entId": "E001"})
    assert match_rule("给书香里文化生成政策告知单") == ToolCall("policy.notice", {"entId": "E001"})
    assert match_rule("查一下书香里") == ToolCall("enterprise.get", {"id": "E001"})
    assert match_rule("查一下星河智驾") is None


def test_rules_preserve_original_question_and_leave_general_chat_to_model():
    text = "  请问《数据券管理办法》的申报要求是什么？ "
    assert match_rule(text) == ToolCall("kb.ask", {"q": text})
    assert match_rule("想看看昨天的工作进展") is None
    assert match_rule("把这个网址导入知识库") is None
    assert match_rule("三个时间是什么意思？").tool == "kb.ask"
    assert match_rule("补填数据采购额 0 万").args == {"overrides": {"dataPurchase": 0}}


@pytest.mark.parametrize(("call", "result", "expected"), [
    (
        ToolCall("policy.match", {"entId": "E001"}),
        {"results": [{"id": f"PI-{i}", "title": "演示条款", "level": "check"} for i in range(7)]},
        ("policy-match", {"entId": "E001"}, {"entId", "results"}),
    ),
    (
        ToolCall("policy.match", {"profile": {"yearsInZone": 3}}),
        {"profile": {"yearsInZone": 3}, "results": [{"id": "PI-01", "level": "check"}], "summary": {"check": 1}},
        ("policy-match", {"tab": "match"}, {"entId", "results"}),
    ),
    (
        ToolCall("policy.search"), {"items": [{"id": "PI-01"}]},
        ("policy-items", {"tab": "library", "itemId": "PI-01"}, {"ids"}),
    ),
    (
        ToolCall("enterprise.get"), {"item": {"id": "E002", "contacts": []}},
        ("enterprise-brief", {"entId": "E002"}, {"entId"}),
    ),
    (
        ToolCall("enterprise.search"), {"ids": ["E003", "E001"]},
        ("enterprise-list", {"entId": "E003"}, {"ids"}),
    ),
    (
        ToolCall("enterprise.alerts"), {"items": [{"entId": "E001", "text": "演示预警"}]},
        ("alerts", {"entId": "E001"}, {"items"}),
    ),
    (
        ToolCall("meeting.list"), {"items": [{"id": "MT-1112"}]},
        ("meeting-list", {"meetingId": "MT-1112", "process": False}, {"ids"}),
    ),
    (
        ToolCall("meeting.summarize", {"meetingId": "MT-1112"}), {"todos": [{"id": "TD-1"}]},
        ("todos", {"meetingId": "MT-1112", "tab": "todos"}, {"items"}),
    ),
    (
        ToolCall("meeting.get"), {"item": {"id": "MT-1112"}, "minutes": {"summary": "会议摘要"}},
        ("meeting-list", {"meetingId": "MT-1112", "tab": "minutes"}, {"ids"}),
    ),
    (
        ToolCall("meeting.summarize"),
        {"item": {"id": "MT-1112"}, "minutes": {"todos": [{"id": "TD-1", "title": "回访"}]}},
        ("todos", {"meetingId": "MT-1112", "tab": "todos"}, {"items"}),
    ),
    (
        ToolCall("document.draft"), {"item": {"templateId": "T06"}},
        ("doc-start", {"templateId": "T06", "autogen": True}, {"templateId"}),
    ),
    (
        ToolCall("document.templates"), {"items": []},
        ("doc-templates", {}, set()),
    ),
    (
        ToolCall("document.compare", {"a": {"id": "D-1", "v": 1}, "b": {"id": "D-1", "v": 2}}),
        {"parts": [{"op": "add", "t": "演示说明"}]},
        ("diff", {"draftId": "D-1"}, {"a", "b", "parts"}),
    ),
    (
        ToolCall("document.polish", {"id": "D-1", "style": "formal"}),
        {"preview": {"title": "演示公文", "paras": ["正式表述"]},
         "parts": [{"op": "add", "t": "正式表述"}], "changed": 1},
        ("diff", {"draftId": "D-1"}, {"a", "b", "parts", "changed"}),
    ),
    (
        ToolCall("policy.notice", {"entId": "E001"}), {"text": "演示告知单"},
        ("app-suggest", {}, set()),
    ),
    (
        ToolCall("kb.ask", {"q": "演示问题"}),
        {"citations": [{"id": "KB-1", "title": "演示材料", "snippet": "原文"}]},
        ("kb-hits", {"fileId": "KB-1"}, {"hits"}),
    ),
])
def test_card_fields_and_deep_links(call, result, expected):
    kind, params, fields = expected
    card = render_card(call, result)
    assert set(card) == {"type", "deepLink"} | fields
    assert card["type"] == kind
    assert card["deepLink"] == {"app": call.app, "params": params}
    if kind == "policy-match":
        assert card["results"] == result["results"][:5]
        assert card["entId"] == params.get("entId")
    if call.tool == "meeting.get":
        assert card["ids"] == [result["item"]["id"]]
    if call.tool == "meeting.summarize" and "minutes" in result:
        assert card["items"] == result["minutes"]["todos"]
    if call.tool == "document.polish":
        assert (card["a"], card["b"], card["parts"], card["changed"]) == (
            call.args["id"], result["preview"], result["parts"], result["changed"],
        )
    if kind == "kb-hits":
        assert card["hits"] == result["citations"]


def test_empty_search_links_to_library_without_fake_id():
    assert render_card(ToolCall("policy.search"), {"items": []}) == {
        "type": "policy-items", "ids": [], "deepLink": {"app": "policy", "params": {"tab": "library"}},
    }

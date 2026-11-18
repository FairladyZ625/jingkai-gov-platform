from datetime import date
import json

import pytest
from haiknow_sdk.ai import AIError

from apps.document.api import checks


def draft(*paragraphs, template="T06", citations=(), **fields):
    return {
        "id": "draft-test", "version": 1,
        "data": {
            "templateId": template, "citations": list(citations), "policyId": None,
            "content": {
                "title": "关于调整申报期限的通知", "to": "各单位", "sign": "测试单位",
                "date": "2026年11月1日", "docNo": "测试〔2026〕8号",
                "paragraphs": list(paragraphs), **fields,
            },
        },
    }


def no_policy(identity, version):
    return None


def no_language_issues(messages, **options):
    return {"result": '{"issues":[]}'}


def test_check_and_fix_several_disjoint_changes_in_one_paragraph():
    record = draft("申报申报载止为2026-11-06，生效日期为2026-2-1。", docNo="测试[2026]08号")
    result = checks.inspect(record, "通知", no_policy, no_language_issues)
    assert {issue["kind"] for issue in result.issues} == {"文号", "日期格式", "错别字"}
    assert len(result.issues) == 5
    assert all({"id", "level", "kind", "text", "para", "field", "original"} <= set(row) for row in result.issues)
    for issue in result.issues:
        assert issue["para"] == (0 if issue["field"] == "paragraphs" else None)
        assert issue["original"][issue["start"]:issue["end"]]
    ids = [*result.changes, "不存在", "不存在"]
    content, citations, ignored, unfixable = checks.apply(record["data"], result, ids)
    assert ignored == ["不存在"]
    assert unfixable == []
    assert citations == []
    assert content["docNo"] == "测试〔2026〕8号"
    assert content["paragraphs"] == ["申报截止为2026年11月6日，生效日期为2026年2月1日。"]
    assert "载止" in record["data"]["content"]["paragraphs"][0]

    revised = {**record, "version": 2, "data": {**record["data"], "content": content}}
    recheck = checks.inspect(revised, "通知", no_policy, no_language_issues)
    assert recheck.response() == {"issues": [], "languageCheck": {"status": "completed"}}
    assert checks.apply(revised["data"], recheck, list(result.changes))[2] == list(result.changes)


def test_rule_file_can_add_a_rule_without_python_change(tmp_path, monkeypatch):
    path = tmp_path / "rules.json"
    data = json.loads(checks.RULES.read_text())
    data.append({
        "id": "colloquial", "condition": "请使用正式表述", "basis": "样例措辞规则",
        "kind": "用词", "level": "info", "fields": ["paragraphs"], "pattern": "搞一下", "replacement": "办理",
    })
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(checks, "RULES", path)
    record = draft("请搞一下。")
    only = checks.inspect(record, "通知", no_policy, no_language_issues)
    assert [(row["kind"], row["para"]) for row in only.issues] == [("用词", 0)]
    assert checks.apply(record["data"], only, list(only.changes))[0]["paragraphs"] == ["请办理。"]


def test_required_fields_invalid_calendar_and_order_have_no_invented_values():
    record = draft("申报截止时间由2026年11月6日调整至2026年11月2日。",
                   "2026-02-30的日期待核对。", title="申报安排", docNo="【待补：发文字号】",
                   to="  ", sign="【待补：发文机关】", date="2026年11月2日")
    result = checks.inspect(record, "通知", no_policy, no_language_issues)
    assert {(row["kind"], row["field"], row["para"]) for row in result.issues} == {
        ("文种要素", "title", None), ("文号", "docNo", None), ("缺要素", "to", None),
        ("缺要素", "sign", None), ("日期先后", "paragraphs", 0), ("日期", "paragraphs", 1),
    }
    assert all("fix" not in row for row in result.issues)
    public_notice = draft("  ", template="T08", title="关于示例名单的公示", to="")
    result = checks.inspect(public_notice, "公示", no_policy, no_language_issues)
    assert {(row["kind"], row["field"]) for row in result.issues} == {("缺要素", "body"), ("文种要素", "title")}


def test_expired_citation_can_be_removed_without_editing_other_references():
    refs = [
        {"id": "expired", "version": 1, "title": "旧示例政策", "marker": "〔1〕"},
        {"id": "valid", "version": 1, "title": "现行示例政策", "marker": "〔2〕"},
    ]
    record = draft("政策原文摘录：旧规定〔1〕", "政策原文摘录：现行规定〔2〕", citations=refs)

    def lookup(identity, version):
        return {"space": "policy", "version": 1, "status": "已失效" if identity == "expired" else "现行有效",
                "expire": "2026-11-18"}

    result = checks.inspect(record, "通知", lookup, no_language_issues, today=date(2026, 11, 18))
    expired, = result.issues
    assert (expired["level"], expired["kind"], expired["para"]) == ("error", "政策引用", 0)
    content, citations, ignored, unfixable = checks.apply(record["data"], result, [expired["id"]])
    assert ignored == unfixable == []
    assert citations == refs[1:]
    assert content["paragraphs"] == ["【待补：有效政策依据】", "政策原文摘录：现行规定〔2〕"]

    record["data"]["content"] = content
    record["data"]["citations"] = citations
    result = checks.inspect(record, "通知", lookup, no_language_issues, today=date(2026, 11, 18))
    assert [(row["kind"], row["level"]) for row in result.issues] == [("缺要素", "error")]
    result = checks.inspect(record, "通知", lookup, no_language_issues, today=date(2026, 11, 19))
    assert any(row["kind"] == "政策引用" and row["level"] == "error" for row in result.issues)


def test_expired_policy_in_authored_prose_requires_manual_change():
    refs = [{"id": "expired", "version": 1, "title": "旧示例政策", "marker": "〔1〕"}]
    record = draft("此前曾依据该政策〔1〕办理。", citations=refs)
    result = checks.inspect(record, "通知", lambda *_: {"space": "policy", "status": "已失效"}, no_language_issues)
    warning, = result.issues
    assert warning["level"] == "error" and "fix" not in warning
    assert checks.apply(record["data"], result, [warning["id"]])[3] == [warning["id"]]

    result = checks.inspect(record, "通知", no_policy, no_language_issues)
    assert [row["level"] for row in result.issues] == ["warn"]


def test_model_uses_gateway_and_returns_an_original_span():
    def chat(messages, *, classification, timeout):
        assert classification == "confidential"
        assert timeout > 0
        body = json.loads(messages[-1]["content"])
        paragraph, = (key for key, text in body.items() if "咱们" in text)
        return {"result": json.dumps({"issues": [
            {"clause": paragraph, "original": "咱们", "replacement": "我单位"},
        ]})}

    record = draft("咱们将及时反馈。")
    result = checks.inspect(record, "通知", no_policy, chat)
    issue, = result.issues
    assert issue["level"] == "info" and issue["para"] == 0
    assert issue["original"][issue["start"]:issue["end"]] == "咱们"
    assert checks.apply(record["data"], result, [issue["id"]])[0]["paragraphs"] == ["我单位将及时反馈。"]


@pytest.mark.parametrize("response", ["模型返回的普通文本", '{"issues":[{"clause":"5","original":"正文未出现","replacement":"测试"}]}'])
def test_malformed_language_check_only_returns_rules(response):
    record = draft("载止时间另行通知。")
    rule_only = checks.inspect(record, "通知", no_policy, no_language_issues)
    result = checks.inspect(record, "通知", no_policy, lambda *_a, **_k: {"result": response})
    assert result.issues == rule_only.issues
    assert result.language_check == {"status": "incomplete", "message": "语言检查未完成"}


def test_provider_failure_only_returns_rules():
    def unavailable(*_args, **_kwargs):
        raise AIError("provider_error", "模拟模型不可用")

    record = draft("载止时间另行通知。")
    rule_only = checks.inspect(record, "通知", no_policy, no_language_issues)
    actual = checks.inspect(record, "通知", no_policy, unavailable)
    assert actual.issues == rule_only.issues
    assert actual.language_check["status"] == "incomplete"

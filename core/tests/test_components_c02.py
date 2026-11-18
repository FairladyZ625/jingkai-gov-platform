"""C02 文档审查：规则命中、无依据、模型辅助、人工改判与文本/解析区块来源。"""
import pytest

from haiknow_sdk.preview.components import c02

RULES = (
    c02.Rule("R-01", "出现非标或定制字样，且未附偏离表", "高", "Q/WH-T-001 5.3", "补充偏离表", keywords=("非标", "定制")),
    c02.Rule("R-02", "引用标准未注明年号", "中", "GB/T 1.1-2020 第 9 章", "注明年号", keywords=("未注明年号",)),
    c02.Rule("R-03", "交期短于标准周期", "中", "", "核对产能", keywords=("交期",)),
)

CLAUSES = (
    c02.Clause("c1", "3.1 乙方提供的变频器为非标定制机型，未附偏离表。", "第 3.1 条", page=2),
    c02.Clause("c2", "3.2 引用标准 GB/T 12668-2018，未注明年号。", "第 3.2 条", page=2),
    c02.Clause("c3", "4.1 合同交期为 15 天。", "第 4.1 条", page=3),
)


def ids(review):
    return [hint.id for hint in review.hints]


def rule_ids(review):
    return [hint.rule for hint in review.hints]


def hint(review, hint_id):
    return next(item for item in review.hints if item.id == hint_id)


def test_normal_review_keeps_text_locator_and_basis():
    review = c02.review(RULES, CLAUSES)

    assert review.ok is True
    assert ids(review) == ["R-01@c1", "R-02@c2", "R-03@c3"]
    first = hint(review, "R-01@c1")
    assert first.text.startswith("3.1 乙方提供")
    assert first.locator == "第 3.1 条" and first.page == 2
    assert first.risk == "高" and first.basis == "Q/WH-T-001 5.3"
    assert first.suggestion == "补充偏离表"
    assert first.status == "待审"
    assert review.by_status()["待审"] == 2


def test_rule_without_basis_is_no_basis_and_has_no_conclusion():
    review = c02.review(RULES, CLAUSES)
    item = hint(review, "R-03@c3")

    assert item.status == "无依据"
    assert item.risk == "" and item.suggestion == ""
    assert "依据" in item.note
    assert review.by_status()["无依据"] == 1


def test_model_assist_only_runs_for_rules_without_deterministic_condition():
    calls = []
    assisted = c02.Rule("R-04", "付款条件与公司标准不一致", "低", "财务制度 4.2", "与财务确认")

    def judge(rule, clause):
        calls.append((rule.id, clause.id))
        return {"hit": clause.id == "c3", "suggestion": "请财务确认付款节点"}

    off = c02.review(RULES + (assisted,), CLAUSES)
    assert off.skipped == [{"rule": "R-04", "reason": "规则没有可匹配条件，未启用模型辅助"}]
    assert all(item.rule != "R-04" for item in off.hints)

    on = c02.review(RULES + (assisted,), CLAUSES, judge=judge)
    assert calls == [("R-04", "c1"), ("R-04", "c2"), ("R-04", "c3")]
    item = hint(on, "R-04@c3")
    assert item.status == "待审"
    assert item.suggestion == "请财务确认付款节点"
    assert on.skipped == []


def test_model_judge_output_is_checked():
    assisted = c02.Rule("R-04", "需要模型判断", "低", "依据")

    with pytest.raises(ValueError, match="hit"):
        c02.review((assisted,), CLAUSES, judge=lambda rule, clause: {"suggestion": "x"})
    with pytest.raises(TypeError, match="dict"):
        c02.review((assisted,), CLAUSES, judge=lambda rule, clause: True)
    with pytest.raises(ValueError, match="suggestion"):
        c02.review((assisted,), CLAUSES, judge=lambda rule, clause: {"hit": True, "suggestion": 1})


def test_pattern_and_keywords_are_case_insensitive():
    rule = c02.Rule("R-05", "出现非标", "高", "依据", pattern=r"\bnon[-\s]?standard\b", keywords=("定制",))
    clauses = (
        c02.Clause("a", "The motor is Non Standard."),
        c02.Clause("b", "该机型为定制产品。"),
        c02.Clause("c", "标准机型。"),
    )
    review = c02.review((rule,), clauses)

    assert ids(review) == ["R-05@a", "R-05@b"]


def test_duplicate_rule_id_is_reported_once_and_first_wins():
    review = c02.review((RULES[0], c02.Rule("R-01", "重复", "低", "x", keywords=("交期",))), CLAUSES)

    assert [issue.code for issue in review.errors] == ["duplicate_rule"]
    assert rule_ids(review) == ["R-01"]


def test_decide_accept_keeps_reviewer_and_reason():
    review = c02.review(RULES, CLAUSES)
    result = c02.decide(review.hints, "R-01@c1", "采纳", reviewer="张工", reason="确认需要偏离表")

    assert result.ok is True and result.errors == []
    item = hint(result, "R-01@c1")
    assert item.status == "采纳"
    assert item.reviewer == "张工"
    assert item.reason == "确认需要偏离表"
    # 未处理的提示不变
    assert hint(result, "R-02@c2").status == "待审"


def test_decide_override_requires_new_risk_and_reason():
    review = c02.review(RULES, CLAUSES)

    missing = c02.decide(review.hints, "R-01@c1", "改判", reviewer="张工")
    assert {issue.code for issue in missing.errors} == {"risk_required", "reason_required"}

    bad = c02.decide(review.hints, "R-01@c1", "改判", reviewer="张工", reason="条款已澄清", risk="最高")
    assert [issue.code for issue in bad.errors] == ["unknown_risk"]

    ok = c02.decide(review.hints, "R-01@c1", "改判", reviewer="张工", reason="条款已澄清", risk="低")
    item = hint(ok, "R-01@c1")
    assert item.status == "改判" and item.risk == "低"
    assert item.reviewer == "张工" and item.reason == "条款已澄清"


def test_decide_reject_requires_reason_and_reviewer():
    review = c02.review(RULES, CLAUSES)

    no_reviewer = c02.decide(review.hints, "R-01@c1", "驳回", reviewer="  ", reason="误报")
    assert [issue.code for issue in no_reviewer.errors] == ["reviewer_required"]

    no_reason = c02.decide(review.hints, "R-01@c1", "驳回", reviewer="张工")
    assert [issue.code for issue in no_reason.errors] == ["reason_required"]

    ok = c02.decide(review.hints, "R-01@c1", "驳回", reviewer="张工", reason="误报")
    assert hint(ok, "R-01@c1").status == "驳回"


def test_no_basis_hint_cannot_be_accepted_but_can_be_overridden():
    review = c02.review(RULES, CLAUSES)

    rejected = c02.decide(review.hints, "R-03@c3", "采纳", reviewer="张工")
    assert [issue.code for issue in rejected.errors] == ["no_basis"]

    overridden = c02.decide(review.hints, "R-03@c3", "改判", reviewer="张工", reason="补到财务制度", risk="中")
    item = hint(overridden, "R-03@c3")
    assert item.status == "改判" and item.risk == "中" and item.note == ""


def test_decide_unknown_hint_and_status_contract():
    review = c02.review(RULES, CLAUSES)

    missing = c02.decide(review.hints, "R-09@c9", "采纳", reviewer="张工")
    assert missing.ok is False
    assert [issue.code for issue in missing.errors] == ["hint_not_found"]

    with pytest.raises(ValueError, match="未知处理状态"):
        c02.decide(review.hints, "R-01@c1", "无依据", reviewer="张工")


def test_from_text_splits_paragraphs_and_keeps_locator():
    clauses = c02.from_text("第一条 非标设备。\n\n第二条 交期 15 天。\n\n\n第三条 质保 12 个月。")

    assert [clause.id for clause in clauses] == ["c1", "c2", "c3"]
    assert clauses[0].locator == "第 1 段"
    assert clauses[1].text == "第二条 交期 15 天。"

    with pytest.raises(TypeError, match="字符串"):
        c02.from_text(None)


def test_from_parse_accepts_envelope_and_table_blocks():
    envelope = {
        "capability": "parse",
        "result": {
            "blocks": [
                {"id": "b0", "type": "text", "order": 0, "page": 1, "text": "3.1 非标定制机型。"},
                {"id": "b1", "type": "table", "order": 1, "page": 2, "table": [["项目", "要求"], ["交期", "15 天"]]},
                {"id": "b2", "type": "image", "order": 2, "page": 3},
                {"id": "b3", "type": "text", "order": 3, "page": 4, "text": "4.1 质保 12 个月。", "bbox": [1, 2, 3, 4]},
            ]
        },
    }
    clauses = c02.from_parse(envelope)

    assert [clause.id for clause in clauses] == ["b0", "b1", "b3"]
    assert clauses[1].text == "项目\t要求\n交期\t15 天"
    assert clauses[1].locator == "第 2 页"
    assert clauses[2].page == 4 and clauses[2].bbox == (1.0, 2.0, 3.0, 4.0)


def test_from_parse_requires_dict_blocks():
    with pytest.raises(TypeError, match="dict"):
        c02.from_parse([])
    with pytest.raises(TypeError, match="dict"):
        c02.from_parse({"result": []})
    with pytest.raises(TypeError, match="blocks"):
        c02.from_parse({"blocks": ["x"]})


def test_contract_errors_are_program_errors():
    with pytest.raises(ValueError, match="规则 id"):
        c02.Rule(" ", "条件")
    with pytest.raises(ValueError, match="条件描述"):
        c02.Rule("R", "  ")
    with pytest.raises(ValueError, match="未知风险等级"):
        c02.Rule("R", "条件", "最高")
    with pytest.raises(ValueError, match="正则"):
        c02.Rule("R", "条件", pattern="([")
    with pytest.raises(ValueError, match="条款 id"):
        c02.Clause("", "正文")
    with pytest.raises(ValueError, match="原文"):
        c02.Clause("c1", " ")
    with pytest.raises(ValueError, match="页码"):
        c02.Clause("c1", "正文", page=0)
    with pytest.raises(ValueError, match="bbox"):
        c02.Clause("c1", "正文", bbox=("x",))
    with pytest.raises(TypeError, match="Rule"):
        c02.review(("R",), CLAUSES)
    with pytest.raises(TypeError, match="Clause"):
        c02.review(RULES, ("c",))
    with pytest.raises(TypeError, match="可调用"):
        c02.review(RULES, CLAUSES, judge="model")


def test_to_dict_is_stable_for_frontend():
    data = c02.review(RULES, CLAUSES).to_dict()

    assert data["ok"] is True
    assert data["hints"][0]["locator"] == "第 3.1 条"
    assert data["hints"][2]["status"] == "无依据"
    assert data["byStatus"]["无依据"] == 1
    assert data["skipped"] == []
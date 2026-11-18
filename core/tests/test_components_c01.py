"""C01 采集填表：正常样例、出错样例与边界。"""
import pytest

from haiknow_sdk.preview.components import c01


def make_schema():
    return c01.Schema(fields=(
        c01.Field("batch", "批次", required=True),
        c01.Field("qty", "数量", type="number", required=True, unit="件", min=0, max=100),
        c01.Field("result", "结论", type="enum", required=True, options=("合格", "不合格", "待确认")),
    ))


def codes(draft):
    return [issue.code for issue in draft.errors]


def test_normal_draft_keeps_values_and_sources():
    schema = make_schema()
    draft = schema.draft(
        {"batch": " B-001 ", "qty": "12", "result": "合格"},
        sources={"batch": {"fileId": "f-1", "locator": "第 2 行"}},
    )

    assert draft.ok is True
    assert draft.values == {"batch": " B-001 ", "qty": 12, "result": "合格"}
    assert draft.missing == []
    assert draft.sources == {"batch": {"fileId": "f-1", "locator": "第 2 行"}}
    assert draft.errors == []


def test_missing_required_and_optional_empty():
    schema = c01.Schema(fields=(
        c01.Field("batch", "批次", required=True),
        c01.Field("note", "备注"),
    ))
    draft = schema.draft({"batch": "  ", "note": ""})

    assert draft.ok is False
    assert draft.values == {"batch": "", "note": ""}
    assert draft.missing == ["batch"]
    assert codes(draft) == ["required"]


def test_number_type_and_range_errors():
    schema = c01.Schema(fields=(
        c01.Field("qty", "数量", type="number", min=0, max=10),
        c01.Field("price", "单价", type="number"),
    ))

    bad_type = schema.draft({"qty": "abc"})
    assert codes(bad_type) == ["type"]
    assert bad_type.values["qty"] == ""

    out_of_range = schema.draft({"qty": 12})
    assert codes(out_of_range) == ["range"]
    # 超范围仍保留数字，方便前端回显后修正
    assert out_of_range.values["qty"] == 12


def test_enum_option_and_unknown_field():
    schema = make_schema()
    draft = schema.draft({"batch": "B-1", "qty": 1, "result": "待定", "extra": "x"})

    assert draft.ok is False
    assert codes(draft) == ["unknown_field", "option"]
    # 未声明的键不写进草稿
    assert set(draft.values) == {"batch", "qty", "result"}


def test_date_pattern_and_file_fields():
    schema = c01.Schema(fields=(
        c01.Field("day", "日期", type="date", required=True),
        c01.Field("code", "编号", type="text", pattern=r"[A-Z]{2}-\d{3}"),
        c01.Field("drawing", "图纸", type="file"),
        c01.Field("photo", "照片", type="photo"),
    ))
    draft = schema.draft({
        "day": "2026-11-06",
        "code": "XX-1",
        "drawing": {"fileId": "f-9", "locator": "第 1 页"},
        "photo": "f-10",
    })

    assert draft.values["day"] == "2026-11-06"
    assert draft.values["drawing"] == "f-9"
    assert draft.values["photo"] == "f-10"
    assert codes(draft) == ["pattern"]

    bad_day = schema.draft({"day": "2026/11/06"})
    assert "type" in codes(bad_day)


def test_from_text_passes_extractor_sources_and_errors():
    schema = make_schema()

    def extractor(text):
        return {
            "batch": {"value": text.strip(), "fileId": "f-1", "locator": "第 2 行"},
            "qty": "3",
            "result": "合格",
        }

    draft = schema.from_text("B-002", extractor)
    assert draft.ok is True
    assert draft.values["qty"] == 3
    assert draft.sources["batch"] == {"fileId": "f-1", "locator": "第 2 行"}


def test_from_text_does_not_swallow_extractor_errors():
    schema = make_schema()

    def boom(_):
        raise RuntimeError("抽取失败")

    with pytest.raises(RuntimeError, match="抽取失败"):
        schema.from_text("x", boom)
    with pytest.raises(TypeError, match="必须返回 dict"):
        schema.from_text("x", lambda _: ["not", "a", "dict"])


def test_contract_errors_are_program_errors():
    with pytest.raises(ValueError, match="未知字段类型"):
        c01.Field("x", "X", type="rich-text")
    with pytest.raises(ValueError, match="必须提供 options"):
        c01.Field("x", "X", type="enum")
    with pytest.raises(ValueError, match="key 重复"):
        c01.Schema(fields=(c01.Field("x"), c01.Field("x")))


def test_error_body_is_v1_envelope():
    schema = make_schema()
    body = c01.error_body(schema.draft({}).errors)

    assert body["error"]["code"] == "invalid_request"
    assert body["error"]["retryable"] is False
    assert [item["field"] for item in body["error"]["issues"]] == ["batch", "qty", "result"]


def test_schema_to_dict_shape():
    data = make_schema().to_dict()
    assert data["version"] == 1
    assert [field["key"] for field in data["fields"]] == ["batch", "qty", "result"]
    assert data["fields"][2]["options"] == ["合格", "不合格", "待确认"]

def test_large_integers_are_preserved_exactly():
    schema = c01.Schema(fields=(c01.Field("n", "数值", type="number"),))

    exact = schema.draft({"n": 9007199254740993})
    assert exact.ok is True and exact.values["n"] == 9007199254740993

    exact_text = schema.draft({"n": "9007199254740993"})
    assert exact_text.ok is True and exact_text.values["n"] == 9007199254740993

    huge = schema.draft({"n": 10 ** 400})
    assert huge.ok is True and huge.values["n"] == 10 ** 400

    tiny = schema.draft({"n": "0.00000000001"})
    assert tiny.ok is True and tiny.values["n"] == 1e-11


def test_unsupported_precision_is_a_type_error_not_a_silent_change():
    schema = c01.Schema(fields=(c01.Field("n", "数值", type="number"),))

    for value in ("1e309", "9007199254740993.0"):
        draft = schema.draft({"n": value})
        assert draft.ok is False
        assert [issue.code for issue in draft.errors] == ["type"]
        assert draft.values["n"] == ""


def test_oversized_numeric_string_is_rejected_without_500():
    schema = c01.Schema(fields=(c01.Field("n", "数值", type="number"),))
    draft = schema.draft({"n": "9" * 5000})
    assert draft.ok is False
    assert [issue.code for issue in draft.errors] == ["type"]

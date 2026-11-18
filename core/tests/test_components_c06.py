"""C06 资料汇编：缺件、引用改版、转义、CSV 与模板错误。"""
import pytest

from haiknow_sdk.preview.components import c06

TEMPLATE = """<h1>{{ title }}</h1>
<p>项目：{{  project  }}</p>
<p>数量：{{ qty }}</p>
<p>结论：{{ result }}</p>
<p>签字：{{ sign }}</p>
"""


def make_book():
    return c06.Book(title="出厂资料（演示）", slots=(
        c06.Slot("title", "标题"),
        c06.Slot("project", "项目"),
        c06.Slot("qty", "数量", unit="件"),
        c06.Slot("result", "结论"),
        c06.Slot("sign", "签字", required=False),
    ))


def full_data(**overrides):
    data = {"title": "出厂资料（演示）", "project": "演示项目", "qty": 3, "result": "合格"}
    data.update(overrides)
    return data


def test_normal_render_fills_values_and_optional_missing():
    render = make_book().render(TEMPLATE, full_data())

    assert render.complete is True
    assert render.formal_ready is True
    assert render.missing == [] and render.stale == []
    assert "<h1>出厂资料（演示）</h1>" in render.html
    assert "项目：演示项目" in render.html
    # 可选槽位缺件输出空串，不显示待补
    assert "签字：</p>" in render.html
    assert [row["slot"] for row in render.rows] == ["title", "project", "qty", "result", "sign"]


def test_missing_required_shows_placeholder_and_blocks_formal():
    render = make_book().render(TEMPLATE, full_data(qty=""))

    assert render.complete is False
    assert render.formal_ready is False
    assert render.missing == ["qty"]
    assert "【待补：数量】" in render.html


def test_stale_citation_blocks_formal_but_stays_complete():
    render = make_book().render(
        TEMPLATE,
        full_data(),
        citations={"project": {"appId": "demo", "recordId": "r-1", "version": 2}},
        current_versions={"project": 3},
    )

    assert render.complete is True
    assert render.formal_ready is False
    assert render.stale == [{"key": "project", "cited": 2, "current": 3}]


def test_same_citation_version_is_not_stale():
    render = make_book().render(
        TEMPLATE,
        full_data(),
        citations={"project": c06.Citation("demo", "r-1", 2)},
        current_versions={"project": "2"},
    )
    assert render.stale == [] and render.formal_ready is True


def test_values_are_html_escaped():
    render = make_book().render(TEMPLATE, full_data(project='<script>alert("x")</script>'))

    assert "<script>" not in render.html
    assert "&lt;script&gt;" in render.html
    assert "&quot;x&quot;" in render.html
    # 引用表与 CSV 用原始值，不重复转义
    assert render.rows[1]["value"] == '<script>alert("x")</script>'


def test_list_values_join_with_chinese_comma():
    render = make_book().render(TEMPLATE, full_data(result=["合格", "已复核"]))
    assert "合格、已复核" in render.html


def test_unknown_placeholder_is_a_program_error():
    with pytest.raises(c06.TemplateError) as raised:
        make_book().render("<p>{{ project_name }}</p>", full_data())
    assert raised.value.code == "unknown_placeholder"
    assert raised.value.field == "project_name"


def test_bad_template_type_and_duplicate_slots():
    with pytest.raises(TypeError, match="模板"):
        make_book().render(None, full_data())
    with pytest.raises(ValueError, match="槽位 key 重复"):
        c06.Book(slots=(c06.Slot("x"), c06.Slot("x")))


def test_citation_normalization_keeps_metadata():
    render = make_book().render(
        TEMPLATE,
        full_data(),
        citations={"project": {"app_id": "demo", "record_id": "r-1", "version": "2", "fileId": "f-1", "extra": "x"}},
    )
    citation = render.citations["project"]
    assert citation["appId"] == "demo"
    assert citation["recordId"] == "r-1"
    assert citation["version"] == 2
    assert citation["fileId"] == "f-1"
    assert citation["extra"] == "x"


def test_render_to_dict_and_csv():
    render = make_book().render(
        TEMPLATE,
        full_data(),
        citations={"project": {"appId": "demo", "recordId": "r-1", "version": 2}},
        current_versions={"project": 2},
    )
    data = render.to_dict()
    assert set(data) == {"html", "complete", "formal_ready", "missing", "stale", "citations", "rows", "citation_html"}
    assert "<table>" in data["citation_html"]

    text = render.csv()
    assert text.startswith("\ufeff槽位,值,来源应用,记录号,版本,文件号")
    lines = text.lstrip("\ufeff").splitlines()
    assert lines[1] == "title,出厂资料（演示）,,,,"
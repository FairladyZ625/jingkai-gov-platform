"""C07 内容制作和审核：素材使用权、生成请求、版本号、修改意见与审核状态。"""
import pytest

from haiknow_sdk.preview.components import c07

ASSETS = (
    c07.Asset("logo", 1, "品牌 Logo", "品牌库", "有", "f-logo"),
    c07.Asset("product", 2, "产品图", "产品目录", "有", "f-product"),
    c07.Asset("stock", 1, "图库照片", "外部图库", "待确认", "f-stock"),
    c07.Asset("blocked", 1, "未授权图片", "网络", "无", "f-blocked"),
)


def task(asset_refs, *, kind="image", params=None, task_id="poster"):
    return c07.Task(
        task_id,
        "做一张 A3 活动海报，突出新产品",
        tuple(c07.AssetRef(*ref) for ref in asset_refs),
        params or {"size": "1024x1024"},
        kind,
    )


def codes(result):
    return [issue.code for issue in result.errors]


def version(version_id, task_id="poster", number=1, status="待审", assets=None):
    return c07.Version(
        version_id, task_id, number, {"url": "mock://poster"},
        {"size": "1024x1024"}, tuple(c07.AssetRef(*ref) for ref in (assets or [("logo", 1)])), status,
    )


def test_assets_with_rights_build_a_request_with_asset_versions():
    prepared = c07.build(task([("logo", 1), ("product", 2)]), ASSETS)

    assert prepared.ok is True and prepared.errors == [] and prepared.warnings == []
    assert [item["id"] for item in prepared.assets] == ["logo", "product"]
    request = prepared.request
    assert request["kind"] == "image"
    assert "做一张 A3 活动海报" in request["prompt"]
    assert "品牌 Logo v1" in request["prompt"] and "产品图 v2" in request["prompt"]
    assert request["params"] == {"size": "1024x1024"}


def test_without_rights_cannot_build_result():
    prepared = c07.build(task([("logo", 1), ("blocked", 1)]), ASSETS)

    assert prepared.ok is False
    assert prepared.request is None
    assert codes(prepared) == ["rights_denied"]
    assert prepared.errors[0].field == "blocked"


def test_pending_rights_is_warning_and_can_only_make_a_draft():
    prepared = c07.build(task([("logo", 1), ("stock", 1)]), ASSETS)

    assert prepared.ok is True
    assert [issue.code for issue in prepared.warnings] == ["rights_pending"]
    assert prepared.request is not None


def test_unknown_asset_and_version_are_separate_errors():
    prepared = c07.build(task([("missing", 1), ("product", 9)]), ASSETS)

    assert prepared.ok is False
    assert codes(prepared) == ["unknown_asset", "unknown_asset_version"]


def test_record_numbers_versions_per_task_and_snapshots_assets():
    prepared = c07.build(task([("logo", 1), ("product", 2)]), ASSETS)
    first = c07.record(prepared, {"url": "mock://one"})
    second = c07.record(prepared, {"url": "mock://two"}, versions=(first,))
    other = c07.record(
        c07.build(task([], task_id="copy", kind="chat", params={}), ASSETS),
        "文案",
        versions=(first, second),
    )

    assert first.id == "poster#v1" and first.number == 1
    assert second.id == "poster#v2" and second.number == 2
    assert other.id == "copy#v1" and other.number == 1
    assert first.status == "待审"
    assert [ref.to_dict() for ref in second.assets] == [{"id": "logo", "version": 1}, {"id": "product", "version": 2}]
    assert second.params == {"size": "1024x1024"}


def test_record_rejects_blocked_build_and_empty_output():
    blocked = c07.build(task([("blocked", 1)]), ASSETS)

    with pytest.raises(ValueError, match="素材检查未通过"):
        c07.record(blocked, {"url": "x"})
    with pytest.raises(ValueError, match="生成结果不能为空"):
        c07.record(c07.build(task([("logo", 1)]), ASSETS), "")
    with pytest.raises(TypeError, match="versions"):
        c07.record(c07.build(task([("logo", 1)]), ASSETS), {"url": "x"}, versions=({"id": "x"},))


def test_comment_appends_with_id_and_author():
    versions = [version("poster#v1")]
    result = c07.comment(versions, "poster#v1", author="王设计", text="主标题再大一号", at="2026-11-07")

    assert result.ok is True
    entry = result.versions[0].comments[0]
    assert entry.id == "poster#v1#c1"
    assert entry.author == "王设计" and entry.text == "主标题再大一号" and entry.at == "2026-11-07"
    # 原列表不被修改
    assert versions[0].comments == ()


def test_comment_errors():
    versions = [version("poster#v1")]

    missing = c07.comment(versions, "poster#v9", author="王设计", text="改")
    assert codes(missing) == ["version_not_found"]

    empty = c07.comment(versions, "poster#v1", author=" ", text=" ")
    assert set(codes(empty)) == {"author_required", "comment_required"}


def test_approve_requires_all_assets_have_rights():
    versions = [version("poster#v1", assets=[("logo", 1), ("stock", 1)])]

    pending = c07.decide(versions, "poster#v1", "通过", reviewer="张主管", assets=ASSETS)
    assert codes(pending) == ["rights_pending"]

    ok = c07.decide([version("poster#v2", number=2, assets=[("logo", 1)])], "poster#v2", "通过",
                    reviewer="张主管", assets=ASSETS)
    assert ok.ok is True
    assert ok.versions[-1].status == "通过"
    assert ok.versions[-1].reviewer == "张主管"


def test_approve_shows_denied_and_unknown_asset():
    denied = c07.decide([version("poster#v1", assets=[("blocked", 1), ("product", 9)])], "poster#v1",
                        "通过", reviewer="张主管", assets=ASSETS)
    assert codes(denied) == ["rights_denied", "unknown_asset"]


def test_return_requires_reason_and_only_pending_can_be_reviewed():
    versions = [version("poster#v1"), version("poster#v2", number=2, status="通过")]

    no_reason = c07.decide(versions, "poster#v1", "退回", reviewer="张主管")
    assert codes(no_reason) == ["reason_required"]

    returned = c07.decide(versions, "poster#v1", "退回", reviewer="张主管", reason="产品参数不对")
    assert returned.ok is True
    assert returned.versions[0].status == "退回" and returned.versions[0].reason == "产品参数不对"

    again = c07.decide(returned.versions, "poster#v1", "退回", reviewer="张主管", reason="再改")
    assert codes(again) == ["already_decided"]

    decided = c07.decide(versions, "poster#v2", "通过", reviewer="张主管", assets=ASSETS)
    assert codes(decided) == ["already_decided"]

    missing = c07.decide(versions, "poster#v9", "退回", reviewer="张主管", reason="x")
    assert codes(missing) == ["version_not_found"]


def test_decide_contract_errors():
    versions = [version("poster#v1")]

    with pytest.raises(ValueError, match="未知审核状态"):
        c07.decide(versions, "poster#v1", "待审", reviewer="张主管")
    with pytest.raises(ValueError, match="assets"):
        c07.decide(versions, "poster#v1", "通过", reviewer="张主管")


def test_version_round_trips_through_from_dict():
    result = c07.comment([version("poster#v1")], "poster#v1", author="王设计", text="改标题")
    data = result.versions[0].to_dict()
    restored = c07.Version.from_dict(data)

    assert restored.to_dict() == data
    assert restored.comments[0].text == "改标题"
    with pytest.raises(TypeError, match="dict"):
        c07.Version.from_dict("x")


def test_contract_errors_are_program_errors():
    with pytest.raises(ValueError, match="素材 id"):
        c07.Asset(" ")
    with pytest.raises(ValueError, match="素材版本"):
        c07.Asset("a", 0)
    with pytest.raises(ValueError, match="未知使用权"):
        c07.Asset("a", 1, rights="有版权")
    with pytest.raises(ValueError, match="素材引用 id"):
        c07.AssetRef(" ")
    with pytest.raises(ValueError, match="素材引用版本"):
        c07.AssetRef("a", 0)
    with pytest.raises(ValueError, match="制作任务 id"):
        c07.Task(" ", "要求")
    with pytest.raises(ValueError, match="要求"):
        c07.Task("t", " ")
    with pytest.raises(ValueError, match="未知生成类型"):
        c07.Task("t", "要求", kind="video")
    with pytest.raises(TypeError, match="AssetRef"):
        c07.Task("t", "要求", ("logo",))
    with pytest.raises(TypeError, match="params"):
        c07.Task("t", "要求", params=["x"])
    with pytest.raises(ValueError, match="成果版本 id"):
        c07.Version(" ", "t", 1, "x")
    with pytest.raises(ValueError, match="属于一个制作任务"):
        c07.Version("v", " ", 1, "x")
    with pytest.raises(ValueError, match="版本号"):
        c07.Version("v", "t", 0, "x")
    with pytest.raises(ValueError, match="未知审核状态"):
        c07.Version("v", "t", 1, "x", status="驳回")
    with pytest.raises(TypeError, match="task"):
        c07.check({"id": "t"}, ASSETS)
    with pytest.raises(TypeError, match="assets"):
        c07.check(task([]), ({"id": "logo"},))


def test_to_dict_uses_camel_case():
    data = c07.build(task([("logo", 1)]), ASSETS).to_dict()

    assert data["ok"] is True
    assert data["assets"][0]["fileId"] == "f-logo"
    assert data["request"]["assets"][0] == {"id": "logo", "version": 1, "name": "品牌 Logo",
                                           "source": "品牌库", "rights": "有", "fileId": "f-logo"}
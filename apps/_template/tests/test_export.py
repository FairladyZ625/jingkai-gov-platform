"""导出拼装是纯函数，用手工算好的 CSV 断言，不经过 HTTP。"""
import importlib.util
from pathlib import Path

app_dir = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(f"{app_dir.name}_router", app_dir / "api" / "router.py")
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


def test_to_csv_quotes_comma_and_newline():
    record = {
        "data": {"title": "含,逗号", "content": "第一行\n第二行"},
        "status": "confirmed",
        "submitter": "sampleoperator",
        "confirmedBy": "samplereviewer",
    }
    assert router.to_csv(record) == (
        "字段,内容\r\n"
        '标题,"含,逗号"\r\n'
        '内容,"第一行\n第二行"\r\n'
        "状态,confirmed\r\n"
        "提交人,sampleoperator\r\n"
        "确认人,samplereviewer\r\n"
    )


def test_to_csv_leaves_confirmed_by_blank_for_unconfirmed_record():
    record = {"data": {"title": "草稿"}, "status": "draft", "submitter": "sampleoperator", "confirmedBy": None}
    assert "确认人,\r\n" in router.to_csv(record)

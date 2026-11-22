"""§4.4 公文送审和 Word 下载。"""
import re
from io import BytesIO
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from fastapi import APIRouter, Request, Response
from haiknow_sdk import DataError
from pydantic import BaseModel

from .drafting_router import DocumentRoute, Operator, Text, Viewer, _with_comments, error
from .drafts import _present as present, _record as get_record

# 由 api/router.py 收录，平台统一加 /api/apps/document 前缀。
router = APIRouter(route_class=DocumentRoute)
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Word XML 不能表示的控制字符（保留 \t、\n；\f 单独转为分页符）。
ILLEGAL = re.compile("[\x00-\x08\x0b\x0e-\x1f\x7f]")


def clean(text):
    """统一换行：CRLF、CR 视为一个换行；去掉 Word XML 无法表示的控制字符。"""
    return ILLEGAL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


def add_text(document, text, alignment=None):
    """正文中的换行保留为段内换行，分页符 \f 转为 Word 分页符。"""
    paragraph = document.add_paragraph()
    for index, part in enumerate(clean(text).split("\f")):
        if index:
            paragraph.add_run().add_break(WD_BREAK.PAGE)
        if part:
            paragraph.add_run(part)
    if alignment is not None:
        paragraph.alignment = alignment
    return paragraph


class Submission(BaseModel):
    assignee: Text | None = None


def check_issues(ctx, request, record):
    # #39 提供同版本核查。集成前禁止在无核查结果时创建待办。
    try:
        from .checking_router import inspect
    except ModuleNotFoundError as exc:
        if exc.name != f"{__package__}.checking_router":
            raise
        raise DataError("app_unavailable", "公文核查尚未接入，暂时不能送审") from exc
    return inspect(ctx, request, record).response()["issues"]


@router.post("/drafts/{identity}/submit")
def submit(identity: str, body: Submission, ctx: Operator, request: Request):
    record = get_record(ctx, identity)
    problems = [i["id"] for i in check_issues(ctx, request, record) if i["level"] == "error"]
    if problems:
        return error(422, "CHECK_FAILED", "请先处理核查发现的问题", issueIds=problems)
    try:
        review = ctx.reviews.submit(identity, record["version"], body.assignee)
    except DataError as exc:
        if exc.code == "self_review":
            return error(409, "SELF_REVIEW", str(exc))
        raise
    item = _with_comments(ctx, present(ctx, {**record, "status": "pending"}))
    return {"item": item, "review": {**review, "type": "review", "app": ctx.app_id,
                                    "ref": identity, "title": item["title"]}}


@router.get("/drafts/{identity}/export", response_class=Response)
def export(identity: str, ctx: Viewer):
    record = get_record(ctx, identity)
    content = record["data"]["content"]
    document = Document()
    draft_mark = "（草稿）" if record["status"] != "confirmed" else ""
    title = clean(content["title"]).replace("\f", "").replace("\n", " ") + draft_mark
    document.add_heading(title, level=0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    if content["docNo"]:
        add_text(document, content["docNo"], WD_ALIGN_PARAGRAPH.CENTER)
    if content["to"]:
        add_text(document, content["to"])
    for paragraph in content["paragraphs"]:
        add_text(document, paragraph)
    for key in ("sign", "date"):
        if content[key]:
            add_text(document, content[key], WD_ALIGN_PARAGRAPH.RIGHT)
    stream = BytesIO()
    document.save(stream)
    filename = quote(title.replace("/", "／").replace("\\", "＼") + ".docx", safe="")
    return Response(stream.getvalue(), media_type=DOCX_TYPE,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

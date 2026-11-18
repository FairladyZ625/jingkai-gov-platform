"""§4.4 公文送审和 Word 下载。"""
from io import BytesIO
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fastapi import APIRouter, Request, Response
from haiknow_sdk import DataError
from pydantic import BaseModel

from .drafting_router import DocumentRoute, Operator, Text, Viewer, error
from .drafts import _present as present, _record as get_record

router = APIRouter(prefix="/api/apps/document", route_class=DocumentRoute)
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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
    item = present(ctx, {**record, "status": "pending"})
    return {"item": item, "review": {**review, "type": "review", "app": ctx.app_id,
                                    "ref": identity, "title": item["title"]}}


@router.get("/drafts/{identity}/export", response_class=Response)
def export(identity: str, ctx: Viewer):
    record = get_record(ctx, identity)
    content = record["data"]["content"]
    document = Document()
    draft_mark = "（草稿）" if record["status"] != "confirmed" else ""
    title = content["title"] + draft_mark
    document.add_heading(title, level=0).alignment = WD_ALIGN_PARAGRAPH.CENTER
    if content["docNo"]:
        document.add_paragraph(content["docNo"]).alignment = WD_ALIGN_PARAGRAPH.CENTER
    if content["to"]:
        document.add_paragraph(content["to"])
    for paragraph in content["paragraphs"]:
        document.add_paragraph(paragraph)
    for key in ("sign", "date"):
        if content[key]:
            document.add_paragraph(content[key]).alignment = WD_ALIGN_PARAGRAPH.RIGHT
    stream = BytesIO()
    document.save(stream)
    filename = quote(title.replace("/", "／").replace("\\", "＼") + ".docx", safe="")
    return Response(stream.getvalue(), media_type=DOCX_TYPE,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

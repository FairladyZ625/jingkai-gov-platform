"""由实例装配已认证的用户、会话存储、工具桥及文件存储的应用/项目。"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import FormParser, MultiPartException, MultiPartParser

from .service import MAX_BYTES, InputError, attachments, check_size, fallback_apps, publish


def error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message, "details": {}}},
                        status_code=status)


async def read_form(request):
    # 为 multipart 边界及文件名留出 64 KiB，同时限制无 Content-Length 的上传。
    wire_limit = MAX_BYTES + 64 * 1024

    class RequestTooLarge(MultiPartException):
        pass

    async def bounded_stream():
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > wire_limit:
                raise RequestTooLarge("附件请求过大")
            yield chunk

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "multipart/form-data":
        parser = MultiPartParser(request.headers, bounded_stream(), max_files=16, max_fields=3,
                                 max_part_size=wire_limit)
    elif content_type == "application/x-www-form-urlencoded":
        parser = FormParser(request.headers, bounded_stream())
    else:
        raise InputError(415, "UNSUPPORTED_TYPE", "请使用表单上传附件")
    try:
        return await parser.parse()
    except RequestTooLarge as exc:
        raise InputError(413, "FILE_TOO_LARGE", "单次附件内容合计最多 10 MiB") from exc
    except MultiPartException as exc:
        raise InputError(422, "CHECK_FAILED", "附件表单格式不正确或数量超限") from exc


def install(app, plat, current_user, conversations, *, app_id, project, apps=fallback_apps,
            not_found):
    router = APIRouter(prefix="/api/v1/conversations/{cid}/attachments")

    def owned(cid: str, user=Depends(current_user)):
        try:
            return conversations.detail(user.id, cid)
        except not_found:
            return None

    def missing():
        return error(404, "NOT_FOUND", "对话或附件不存在")

    @router.post("")
    async def upload(cid: str, request: Request, detail=Depends(owned), user=Depends(current_user)):
        if detail is None:
            return missing()
        try:
            form = await read_form(request)
            try:
                parts = []
                size = 0
                for source, value in form.multi_items():
                    if source == "files[]" and isinstance(value, UploadFile):
                        size += value.size or 0
                        check_size(size)
                        parts.append(("file", value.filename or "", await value.read(MAX_BYTES + 1)))
                    elif source in ("url", "text") and isinstance(value, str) and value.strip():
                        size += len(value.encode("utf-8"))
                        check_size(size)
                        parts.append((source, "链接" if source == "url" else "粘贴文本", value))
                if not parts:
                    raise InputError(422, "CHECK_FAILED", "请选择文件或填写链接、文本")
                return await run_in_threadpool(publish, user, cid, parts, conversations, plat.data,
                                               apps, app_id, project, form.get("lib"))
            finally:
                await form.close()
        except InputError as exc:
            return error(exc.status, exc.code, str(exc))
        except not_found:
            return missing()

    @router.get("")
    def listing(detail=Depends(owned)):
        return missing() if detail is None else {"items": attachments(detail)}

    @router.get("/{ident}/content")
    def download(ident: str, detail=Depends(owned), user=Depends(current_user)):
        for item in attachments(detail) if detail is not None else ():
            if item["id"] == ident and item.get("url", "").startswith("/api/v1/conversations/"):
                data = plat.data.read_file(user, ident)
                return Response(data, media_type="application/octet-stream", headers={
                    "Content-Disposition": "attachment; filename*=UTF-8''" + quote(item["name"], safe="")})
        return missing()

    app.include_router(router)

"""由实例装配已认证的用户、会话存储、工具桥及文件存储的应用/项目。"""
from urllib.parse import quote, unquote_to_bytes

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from .service import AttachmentStore, MAX_BYTES, InputError, attachments, check_size, fallback_apps, publish


def error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message, "details": {}}},
                        status_code=status)


def decode_field(raw):
    # unquote_to_bytes 对每个 % 分段；分块可避免大段中文产生数百万个临时对象。
    decoded = bytearray()
    start = 0
    while start < len(raw):
        end = min(start + 64 * 1024, len(raw))
        if end < len(raw):
            partial = raw.rfind(b"%", end - 2, end)
            if partial >= 0:
                end = partial
        decoded.extend(unquote_to_bytes(raw[start:end].replace(b"+", b" ")))
        start = end
    return decoded.decode("utf-8")


def urlencoded_form(body):
    fields = body.split(b"&", 3)
    if len(fields) > 3:
        raise InputError(422, "CHECK_FAILED", "表单最多支持三个字段")
    pairs = []
    try:
        for field in fields:
            key, _, value = field.partition(b"=")
            pairs.append((decode_field(key), decode_field(value)))
    except UnicodeDecodeError as exc:
        raise InputError(422, "CHECK_FAILED", "表单文本需要使用 UTF-8 编码") from exc
    return FormData(pairs)


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
    try:
        if content_type == "application/x-www-form-urlencoded":
            wire_limit = 3 * MAX_BYTES + 64 * 1024
            body = bytearray()
            async for chunk in bounded_stream():
                body.extend(chunk)
            return await run_in_threadpool(urlencoded_form, bytes(body))
        if content_type != "multipart/form-data":
            raise InputError(415, "UNSUPPORTED_TYPE", "请使用表单上传附件")
        parser = MultiPartParser(request.headers, bounded_stream(), max_files=16, max_fields=3)
        # 旧版只限制字段数；新版的字段大小限制与传输上限对齐。
        parser.max_part_size = wire_limit
        return await parser.parse()
    except RequestTooLarge as exc:
        raise InputError(413, "FILE_TOO_LARGE", "单次附件内容合计最多 10 MiB") from exc
    except MultiPartException as exc:
        raise InputError(422, "CHECK_FAILED", "附件表单格式不正确或数量超限") from exc


def install(app, plat, current_user, conversations, *, app_id, project, apps=fallback_apps,
            not_found):
    store = AttachmentStore(conversations)
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
                if any(source == "file" for source, _, _ in parts):
                    plat.data.projects.require(user, project)
                    plat.data.app(user, app_id, "operate")
                return await run_in_threadpool(publish, user, cid, parts, store, apps, form.get("lib"))
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
    def download(cid: str, ident: str, detail=Depends(owned), user=Depends(current_user)):
        for item in attachments(detail) if detail is not None else ():
            if item["id"] == ident and item.get("url", "").startswith("/api/v1/conversations/"):
                data = store.content(user.id, cid, ident)
                if data is None:
                    return missing()
                plat.data.projects.require(user, project)
                plat.data.app(user, app_id)
                return Response(data, media_type="application/octet-stream", headers={
                    "Content-Disposition": "attachment; filename*=UTF-8''" + quote(item["name"], safe="")})
        return missing()

    app.include_router(router)

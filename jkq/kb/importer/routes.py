"""四个知识库导入端点。应用须显式提供认证依赖和导入服务。"""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from .parsing import MAX_FILE
from .public_url import PublicURLError
from .service import ImportFailure, ImportService, Upload, invalid


class _ImportRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def checked(request):
            try:
                return await handle(request)
            except (ImportFailure, PublicURLError) as exc:
                return _error(exc.status, exc.code, str(exc), details=getattr(exc, "details", {}))
            except RequestValidationError:
                return _error(422, "CHECK_FAILED", "导入请求参数无效")
            except HTTPException as exc:
                if exc.status_code == 401:
                    return _error(401, "UNAUTHENTICATED", "请先登录", headers=exc.headers)
                if exc.status_code == 403:
                    return _error(403, "FORBIDDEN", "没有知识库导入权限", headers=exc.headers)
                raise

        return checked


def _error(status, code, message, *, details=None, headers=None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}},
                        status_code=status, headers=headers)


def _decode(value):
    def unique_object(pairs):
        result = {}
        for key, entry in pairs:
            if key in result:
                raise ValueError
            result[key] = entry
        return result

    try:
        return json.loads(value, object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        raise invalid("导入请求须为没有重复字段的有效 JSON") from None


async def _payload(request, *, accept_files=True):
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type == "application/json":
        return _decode(await request.body()), ()
    if content_type != "multipart/form-data" or not accept_files:
        raise ImportFailure(415, "UNSUPPORTED_MEDIA_TYPE", "请求须使用 JSON 或受支持的 multipart 文件上传")

    try:
        async with request.form(max_fields=1) as form:
            parts = form.getlist("file")
            metadata = form.get("payload")
            if (form.keys() - {"payload", "file"} or not isinstance(metadata, str) or not parts
                    or any(not isinstance(part, UploadFile) for part in parts)):
                raise invalid("文件上传须包含 JSON 字段 payload 和一个或多个 file 字段")
            payload = _decode(metadata)
            files = []
            for part in parts:
                content = await part.read(MAX_FILE + 1)
                if len(content) > MAX_FILE:
                    raise ImportFailure(422, "PARSE_FAILED", "文件超过大小上限")
                files.append(Upload(part.filename or "", content))
            return payload, files
    except HTTPException as exc:
        if exc.status_code == 400:
            raise invalid("文件上传格式无效") from None
        raise


def build_router(service: ImportService, current_user):
    """JSON 兼容原型，multipart 的 payload.items[].fileIndex 绑定同序 file 字段。"""
    router = APIRouter(prefix="/api/v1/kb/import", route_class=_ImportRoute)
    session = Depends(current_user)

    @router.post("/preview")
    async def preview(request: Request, user=session):
        payload, files = await _payload(request)
        return await service.preview(user, payload, files=files)

    @router.post("/commit")
    async def commit(request: Request, user=session):
        payload, files = await _payload(request)
        return await service.commit(user, payload, files=files)

    @router.post("")
    async def import_now(request: Request, user=session):
        payload, files = await _payload(request)
        return await service.commit(user, payload, files=files, one_step=True)

    @router.post("/url")
    async def read_url(request: Request, user=session):
        payload, _ = await _payload(request, accept_files=False)
        return await service.preview_url(user, payload)

    return router

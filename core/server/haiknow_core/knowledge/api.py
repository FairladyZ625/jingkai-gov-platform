"""知识库 HTTP 接口；业务检查全部在 Knowledge 服务内。"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from .seed import seed
from .service import CATEGORIES, MAX_TEXT, Knowledge


def _names(value: str) -> list[str]:
    return [item.strip() for item in (value or '').split(',') if item.strip()]


def install(app, platform, current_user):
    service = Knowledge(platform.data)
    platform.data.knowledge = service
    # 可选挂点：v1 旧文件入口对已登记为受限的原件执行知识库权限。
    platform.data.file_guard = service.guard_file
    platform.knowledge = service
    router = APIRouter(prefix='/api/v1/knowledge')

    @router.get('/categories')
    def categories(user=Depends(current_user)):
        return {'items': list(CATEGORIES)}

    @router.get('/entries')
    def search(q: str | None = None, category: str | None = None, status: str | None = None,
               app: str | None = None, updatedAfter: float | None = None,
               updatedBefore: float | None = None, includeUnpublished: bool = False,
               limit: int = 50, offset: int = 0, user=Depends(current_user)):
        return service.search(user, {'q': q, 'category': category, 'status': status, 'app': app,
                                     'updatedAfter': updatedAfter, 'updatedBefore': updatedBefore,
                                     'includeUnpublished': includeUnpublished,
                                     'limit': limit, 'offset': offset})

    @router.post('/entries', status_code=201)
    def create_entry(title: str = Form(), category: str = Form(), sourceApp: str = Form(),
                     project: str | None = Form(default=None), scope: str = Form(default='project'),
                     visibility: str = Form(default='internal'),
                     tags: str = Form(default=''), roles: str = Form(default=''),
                     departments: str = Form(default=''), note: str = Form(default=''),
                     text: str = Form(default=''), purpose: str = Form(default='knowledge'),
                     fileId: str | None = Form(default=None),
                     file: UploadFile | None = File(default=None), user=Depends(current_user)):
        upload = (file.filename or '上传文件', file.file.read()) if file is not None else None
        body = {'title': title, 'category': category, 'tags': _names(tags), 'sourceApp': sourceApp,
                'project': project or None, 'scope': scope, 'visibility': visibility, 'roles': _names(roles),
                'departments': _names(departments), 'purpose': purpose, 'note': note,
                'text': text[:MAX_TEXT]}
        return service.create_entry(user, body, upload=upload, file_id=fileId or None)

    @router.get('/entries/{entry_id}')
    def entry(entry_id: str, user=Depends(current_user)):
        return service.get(user, entry_id)

    @router.patch('/entries/{entry_id}')
    def update_entry(entry_id: str, body: dict, user=Depends(current_user)):
        return service.update(user, entry_id, body)

    @router.post('/entries/{entry_id}/versions', status_code=201)
    def add_version(entry_id: str, note: str = Form(default=''), text: str = Form(default=''),
                    purpose: str = Form(default='knowledge'), project: str | None = Form(default=None),
                    fileId: str | None = Form(default=None),
                    file: UploadFile | None = File(default=None), user=Depends(current_user)):
        upload = (file.filename or '上传文件', file.file.read()) if file is not None else None
        body = {'note': note, 'text': text[:MAX_TEXT], 'purpose': purpose, 'project': project or None}
        return service.add_version(user, entry_id, body, upload=upload, file_id=fileId or None)

    @router.post('/entries/{entry_id}/submit')
    def submit(entry_id: str, body: dict, user=Depends(current_user)):
        return service.submit(user, entry_id, body)

    @router.post('/entries/{entry_id}/publish')
    def publish(entry_id: str, body: dict, user=Depends(current_user)):
        return service.publish(user, entry_id, body)

    @router.get('/entries/{entry_id}/references')
    def references(entry_id: str, user=Depends(current_user)):
        return service.references(user, entry_id)

    @router.get('/entries/{entry_id}/versions/{version}')
    def version(entry_id: str, version: int, user=Depends(current_user)):
        return service.get_version(user, entry_id, version)

    @router.get('/entries/{entry_id}/versions/{version}/content')
    def content(entry_id: str, version: int, user=Depends(current_user)):
        data, _ = service.read(user, entry_id, version)
        return Response(data, media_type='application/octet-stream')

    @router.get('/records/{app_id}/{record_id}/versions/{version}/files')
    def record_files(app_id: str, record_id: str, version: int, user=Depends(current_user)):
        return service.record_files(user, app_id, record_id, version)

    app.include_router(router)
    if os.environ.get('HAIKNOW_KB_SEED', '1') != '0':
        seed(service, platform.root)

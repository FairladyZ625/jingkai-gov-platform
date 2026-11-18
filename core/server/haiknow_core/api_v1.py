"""v1 HTTP 适配；所有业务检查由 DataService 执行。"""
import logging

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from haiknow_sdk import DataError


def data_error_response(error, *, status=None, headers=None):
    payload = {**error.error, 'code': error.code.upper()}
    return JSONResponse({'error': payload}, status_code=status or error.status, headers=headers)


def install(app, platform, current_user):
    service = platform.data
    router = APIRouter(prefix='/api/v1')

    @app.exception_handler(DataError)
    async def data_error(request, e):
        return data_error_response(e)

    @app.exception_handler(Exception)
    async def internal_error(request, e):
        if request.url.path.startswith('/api/v1/'):
            logging.getLogger('haiknow').exception('v1 请求失败')
            error = DataError('internal_error', '平台处理失败，请联系管理员')
            return data_error_response(error, status=500)
        raise e

    @app.exception_handler(HTTPException)
    async def http_error(request, e):
        if request.url.path.startswith('/api/v1/'):
            code = {401: 'unauthenticated', 403: 'forbidden', 404: 'not_found', 405: 'method_not_allowed'}.get(e.status_code, 'invalid_request')
            message = {401: '请先登录', 403: '没有执行此操作的权限', 404: '资源不存在', 405: '此资源不支持该操作'}.get(e.status_code, '请求不正确')
            error = DataError(code, message)
            return data_error_response(error, headers=e.headers)
        return JSONResponse({'detail': e.detail}, status_code=e.status_code, headers=e.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, e):
        if request.url.path.startswith('/api/v1/'):
            error = DataError('invalid_request', '请求字段缺失或类型不正确')
            return data_error_response(error, status=422)
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, e)

    @router.get('/me')
    def me(user=Depends(current_user)):
        return {'id': user.id, 'name': user.name, 'roles': list(user.roles),
                'projects': [p for p in service.projects.by_id if service.projects.visible(user, p)],
                'isAdmin': 'admin' in platform.rbac.actions(user, '*')}

    @router.get('/projects')
    def projects(user=Depends(current_user)):
        return service.projects.tree(user)

    @router.post('/files', status_code=201)
    def upload(file: UploadFile, app: str = Form(), project: str = Form(), purpose: str = Form(), user=Depends(current_user)):
        return service.save_file(user, app, project, purpose, file.filename or '上传文件', file.file.read())

    @router.get('/files/{fid}')
    def file(fid: str, user=Depends(current_user)):
        return service.get_file(user, fid)

    @router.get('/files/{fid}/content')
    def content(fid: str, user=Depends(current_user)):
        return Response(service.read_file(user, fid), media_type='application/octet-stream')

    @router.post('/apps/{app_id}/records', status_code=201)
    def create_record(app_id: str, body: dict, user=Depends(current_user)):
        return service.save_record(user, app_id, body)

    @router.put('/apps/{app_id}/records/{rid}')
    def update_record(app_id: str, rid: str, body: dict, user=Depends(current_user)):
        return service.save_record(user, app_id, body, rid)

    @router.get('/apps/{app_id}/records')
    def records(app_id: str, project: str | None = None, status: str | None = None, type: str | None = None, user=Depends(current_user)):
        return service.list_records(user, app_id, project=project, status=status, type=type)

    @router.get('/apps/{app_id}/records/{rid}')
    def record(app_id: str, rid: str, user=Depends(current_user)):
        return service.get_record(user, app_id, rid)

    @router.get('/apps/{app_id}/records/{rid}/versions/{version}')
    def version(app_id: str, rid: str, version: int, user=Depends(current_user)):
        return service.get_record(user, app_id, rid, version)

    @router.get('/apps/{app_id}/cross-project/records')
    def cross_project_records(app_id: str, subject: str, project: str | None = None,
                              status: str | None = None, type: str | None = None,
                              user=Depends(current_user)):
        return service.list_cross_records(user, app_id, subject, project=project, status=status, type=type)

    @router.get('/apps/{app_id}/cross-project/records/{rid}')
    def cross_project_record(app_id: str, rid: str, version: int | None = None, user=Depends(current_user)):
        return service.get_cross_record(user, app_id, rid, version)

    @router.get('/apps/{app_id}/cross-project/files/{fid}/content')
    def cross_project_file(app_id: str, fid: str, user=Depends(current_user)):
        return Response(service.read_cross_file(user, app_id, fid), media_type='application/octet-stream')

    @router.post('/reviews', status_code=201)
    def submit_review(body: dict, user=Depends(current_user)):
        return service.submit_review(user, body, generic_http=True)

    @router.post('/reviews/{rid}/decisions')
    def decision(rid: str, body: dict, user=Depends(current_user)):
        return service.decide_review(user, rid, body, generic_http=True)

    @router.get('/reviews')
    def reviews(assignee: str | None = None, mine: str | None = None, app: str | None = None, user=Depends(current_user)):
        return service.list_reviews(user, assignee=assignee, mine=mine, app_id=app)

    @router.get('/apps/{app_id}/members')
    def members(app_id: str, project: str, action: str = 'approve', user=Depends(current_user)):
        return service.list_members(user, app_id, project, action)

    @router.get('/artifacts')
    def artifacts(project: str | None = None, product: str | None = None, type: str | None = None,
                  app: str | None = None, history: bool = False, recordId: str | None = None,
                  version: int | None = None, user=Depends(current_user)):
        return service.find_artifacts(user, project=project, product=product, type=type,
                                      app=app, history=history, recordId=recordId, version=version)

    @router.get('/notifications')
    def notifications(app: str | None = None, user=Depends(current_user)):
        return service.list_notifications(user, app=app)

    @router.post('/notifications/{nid}/read')
    def read_notification(nid: str, user=Depends(current_user)):
        return service.read_notification(user, nid)

    @router.post('/apps/{app_id}/messages', status_code=201)
    def send_message(app_id: str, body: dict, response: Response, user=Depends(current_user)):
        result = service.send_message(user, app_id, body)
        if result['replayed']:
            response.status_code = 200
        return result

    @router.get('/apps/{app_id}/messages/sent')
    def sent_messages(app_id: str, user=Depends(current_user)):
        return service.list_sent_messages(user, app_id)

    @router.get('/messages')
    def messages(user=Depends(current_user)):
        return service.list_messages(user)

    @router.get('/messages/{mid}')
    def message(mid: str, user=Depends(current_user)):
        return service.get_message(user, mid)

    @router.post('/messages/{mid}/read')
    def read_message(mid: str, user=Depends(current_user)):
        return service.read_message(user, mid)

    @router.post('/messages/{mid}/acknowledge')
    def acknowledge_message(mid: str, user=Depends(current_user)):
        return service.acknowledge_message(user, mid)

    app.include_router(router)

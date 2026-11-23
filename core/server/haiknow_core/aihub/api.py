"""管理员配置和 AI 错误映射。"""
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..settings import AISettings
from .config import ENVIRONMENT_PROVIDER, valid_base_url
from .errors import AIError
from .gateway import CAPABILITIES, CAPABILITY_SUPPORT, TEST_ORDER, Gateway


def v1_error(status, code, message, **details):
    """v1 错误信封的管理接口拒绝：理由要写清，不能被通用文案盖掉。"""
    return JSONResponse({'error': {'code': code.upper(), 'message': message, 'retryable': False, **details}}, status_code=status)


def transport_warnings(kind, base_url):
    """http 接入地址允许保存（本地/内网网关），但密钥会明文过网，由界面常显警示。"""
    if kind in ('mock', 'builtin', 'codex-cli') or not base_url or not valid_base_url(base_url) or urlsplit(base_url).scheme != 'http':
        return []
    return [{'code': 'insecure_transport', 'message': '接入地址使用 http，密钥将以明文传输。'}]


class ProviderBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['mock', 'ark', 'deepseek', 'openai', 'local', 'mineru', 'builtin']
    base_url: str = ''
    models: list[str] = Field(min_length=1)
    enabled: bool = True
    allow_outbound: Literal['public', 'internal', 'confidential'] | None = None


class ToolBody(BaseModel):
    appId: str = Field(min_length=1)
    classification: Literal['public', 'internal', 'confidential'] = 'internal'


class ParseBody(ToolBody):
    fileId: str = Field(min_length=1)


class SearchBody(ToolBody):
    query: str = Field(min_length=1, max_length=128)
    count: int | None = Field(default=None, ge=1, le=50)


class FetchBody(ToolBody):
    url: str = Field(min_length=1, max_length=8192)
    allowed_hosts: list[str] | None = Field(default=None, min_length=1)


class EmbeddingBody(ToolBody):
    text: str = Field(min_length=1)


class VisionBody(ToolBody):
    fileId: str = Field(min_length=1)
    instruction: str = Field(min_length=1, max_length=2000)


class TranscribeBody(ToolBody):
    fileId: str = Field(min_length=1)


class RouteBody(BaseModel):
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None


class QuotaBody(BaseModel):
    max_calls: int = Field(ge=0)


class TestBody(BaseModel):
    """服务商测试可点名能力；不传时按已配路由或服务商类型挑一个。"""

    capability: str | None = None


def install(app, plat):
    from ..main import current_user
    settings = AISettings(plat.store.data_dir, plat.model.environment)

    class Files:
        """文件可见性由 DataService 判定；这里按调用用户取原件。"""

        def get_file(self, user, file_id):
            return plat.data.get_file(user, file_id)

        def read_file(self, user, file_id):
            return plat.data.read_file(user, file_id)

    gateway = Gateway(settings, files=Files(),
                      audit=lambda app_id, user_id, action, detail: plat.store.audit(app_id, user_id, action, detail))
    plat.model.aihub = gateway
    router = APIRouter(prefix='/api/v1/admin/ai')
    tools = APIRouter(prefix='/api/v1/ai')

    def admin(user=Depends(current_user)):
        if 'admin' not in plat.rbac.actions(user, '*'):
            raise HTTPException(403, '需要管理员权限')
        return user

    @app.exception_handler(AIError)
    async def ai_error(request: Request, error: AIError):
        status = {'not_configured': 503, 'quota_exceeded': 429, 'timeout': 504, 'bad_input': 400,
                  'provider_error': 502, 'outbound_denied': 403, 'not_found': 404}[error.kind]
        envelope = {'code': error.kind.upper(), 'message': str(error), 'retryable': error.retryable}
        if getattr(error, 'task_id', None):
            envelope['taskId'] = error.task_id
        return JSONResponse({'error': envelope}, status_code=status)

    @router.get('/providers')
    def providers(user=Depends(admin)):
        items = settings.providers()
        for item in items:
            item['warnings'] = transport_warnings(item['kind'], item['base_url'])
        return {'items': items}

    @router.put('/providers/{ident}')
    def put_provider(ident: str, body: ProviderBody, user=Depends(admin)):
        if ident == ENVIRONMENT_PROVIDER:
            return v1_error(409, 'invalid_state', '该服务商由进程环境配置。')
        if not all(model.strip() for model in body.models) or (body.kind not in ('mock', 'builtin') and not valid_base_url(body.base_url)):
            raise HTTPException(400, '服务商配置无效')
        # 改类型与改模型列表都会让已有路由静默失效：先校验引用它的路由仍然成立。
        routes = [route for route in settings.stored_routes() if ident in (route['provider'], route['fallback_provider'])]
        lost = sorted({route['capability'] for route in routes if route['capability'] not in CAPABILITY_SUPPORT[body.kind]})
        if lost:
            return v1_error(409, 'invalid_state', f'服务商 {ident} 的新类型 {body.kind} 不支持已被路由使用的能力：{"、".join(lost)}，请先调整这些路由', capabilities=lost)
        missing = [(route['capability'], route['model'] if route['provider'] == ident else route['fallback_model'])
                   for route in routes
                   if (route['model'] if route['provider'] == ident else route['fallback_model']) not in body.models]
        if missing:
            return v1_error(409, 'invalid_state',
                            f'服务商 {ident} 的模型列表缺少路由正在使用的模型：{"、".join(f"{capability}·{model}" for capability, model in missing)}',
                            capabilities=sorted({capability for capability, _ in missing}))
        settings.put_provider(ident, body.kind, body.base_url, body.models, body.enabled, body.allow_outbound)
        plat.store.audit('platform', user.id, 'ai.provider.update', {'provider': ident, 'enabled': body.enabled})
        return {'ok': True, 'warnings': transport_warnings(body.kind, body.base_url)}

    @router.delete('/providers/{ident}')
    def delete_provider(ident: str, user=Depends(admin)):
        if ident == ENVIRONMENT_PROVIDER:
            return v1_error(409, 'invalid_state', '该服务商由进程环境配置。')
        if settings.provider(ident) is None:
            raise HTTPException(404, '服务商不存在')
        # 路由引用时拒绝删除：静默级联会让线上应用突然 not_configured。
        used = sorted({route['capability'] for route in settings.stored_routes()
                       if ident in (route['provider'], route['fallback_provider'])})
        if used:
            return v1_error(409, 'invalid_state', f'服务商 {ident} 仍被能力路由引用：{"、".join(used)}', capabilities=used)
        settings.delete_provider(ident)
        plat.store.audit('platform', user.id, 'ai.provider.delete', {'provider': ident})
        return {'ok': True}

    @router.post('/providers/{ident}/probe')
    def probe_provider(ident: str, user=Depends(admin)):
        return gateway.probe(ident)

    def test_capability(provider):
        """优先测这个服务商当前真正在承载的能力；没有路由时按常见顺序挑第一个支持的。"""
        supported = CAPABILITY_SUPPORT[provider['kind']]
        routed = [route['capability'] for route in settings.routes()
                  if provider['id'] in (route['provider'], route['fallback_provider']) and route['capability'] in supported]
        return (routed or [capability for capability in TEST_ORDER if capability in supported])[0]

    def test_model(provider, capability):
        for route in settings.routes():
            if route['capability'] != capability:
                continue
            if route['provider'] == provider['id']:
                return route['model']
            if route['fallback_provider'] == provider['id']:
                return route['fallback_model']
        return next(iter(provider['models']), None)

    @router.post('/providers/{ident}/test')
    def test_provider(ident: str, body: TestBody | None = None, user=Depends(admin)):
        provider = settings.provider(ident)
        if provider is None:
            raise HTTPException(404, '服务商不存在')
        capability = body.capability if body and body.capability else test_capability(provider)
        if capability not in CAPABILITIES:
            return v1_error(400, 'invalid_request', '能力无效')
        outcome = gateway.test(capability, provider_id=ident, model=test_model(provider, capability))
        plat.store.audit('platform', user.id, 'ai.provider.test', {
            'provider': ident, 'capability': capability, 'model': outcome['model'],
            'ok': outcome['ok'], 'elapsed_ms': outcome['elapsed_ms']})
        return outcome

    @router.get('/routes')
    def routes(user=Depends(admin)):
        return {'items': settings.routes()}

    @router.put('/routes/{capability}')
    def put_route(capability: str, body: RouteBody, user=Depends(admin)):
        if capability == 'chat' and settings.environment.explicit:
            return v1_error(409, 'invalid_state', '对话路由由进程环境配置。')
        if capability not in CAPABILITIES or bool(body.fallback_provider) != bool(body.fallback_model):
            raise HTTPException(400, '能力或兜底配置无效')
        for ident, model in [(body.provider, body.model), (body.fallback_provider, body.fallback_model)]:
            if ident:
                if ident == ENVIRONMENT_PROVIDER:
                    return v1_error(409, 'invalid_state', '环境服务商只能由进程配置为默认对话路由。')
                provider = settings.provider(ident)
                if not provider or model not in provider['models']:
                    raise HTTPException(400, '服务商或模型不存在')
                if capability not in CAPABILITY_SUPPORT[provider['kind']]:
                    return v1_error(400, 'invalid_request', f'服务商 {ident} 不支持能力 {capability}', provider=ident, capability=capability)
        settings.put_route(capability, body.provider, body.model, body.fallback_provider, body.fallback_model)
        plat.store.audit('platform', user.id, 'ai.route.update', {'capability': capability})
        return {'ok': True}

    @router.delete('/routes/{capability}')
    def delete_route(capability: str, user=Depends(admin)):
        if capability == 'chat' and settings.environment.explicit:
            return v1_error(409, 'invalid_state', '对话路由由进程环境配置。')
        settings.delete_route(capability)
        plat.store.audit('platform', user.id, 'ai.route.delete', {'capability': capability})
        return {'ok': True}

    @router.post('/routes/{capability}/test')
    def test_route(capability: str, user=Depends(admin)):
        if capability not in CAPABILITIES:
            return v1_error(400, 'invalid_request', '能力无效')
        outcome = gateway.test(capability)
        plat.store.audit('platform', user.id, 'ai.route.test', {
            'capability': capability, 'provider': outcome['provider'], 'model': outcome['model'],
            'ok': outcome['ok'], 'elapsed_ms': outcome['elapsed_ms']})
        return outcome

    @router.get('/quotas')
    def quotas(user=Depends(admin)):
        return {'items': settings.quotas()}

    @router.put('/quotas/{app_id}')
    def put_quota(app_id: str, body: QuotaBody, user=Depends(admin)):
        if app_id not in plat.apps:
            raise HTTPException(404, '应用不存在')
        settings.put_quota(app_id, body.max_calls)
        plat.store.audit('platform', user.id, 'ai.quota.update', {'app_id': app_id, 'max_calls': body.max_calls})
        return {'ok': True}

    @router.get('/usage')
    def usage(user=Depends(admin)):
        return {'items': settings.usage()}

    def tool_user(user, app_id):
        plat.data.app(user, app_id)
        return user

    @tools.post('/parse')
    def parse(body: ParseBody, user=Depends(current_user)):
        return gateway.call(body.appId, 'parse', {'file_id': body.fileId, 'classification': body.classification}, principal=tool_user(user, body.appId))

    @tools.post('/search')
    def search(body: SearchBody, user=Depends(current_user)):
        payload = {'query': body.query, 'classification': body.classification}
        if body.count is not None:
            payload['count'] = body.count
        return gateway.call(body.appId, 'search', payload, principal=tool_user(user, body.appId))

    @tools.post('/fetch')
    def fetch(body: FetchBody, user=Depends(current_user)):
        payload = {'url': body.url, 'classification': body.classification}
        if body.allowed_hosts is not None:
            payload['allowed_hosts'] = body.allowed_hosts
        return gateway.call(body.appId, 'fetch', payload, principal=tool_user(user, body.appId))

    @tools.post('/embedding')
    def embedding(body: EmbeddingBody, user=Depends(current_user)):
        return gateway.call(body.appId, 'embedding', {'input': body.text, 'classification': body.classification},
                            principal=tool_user(user, body.appId))

    @tools.post('/vision')
    def vision(body: VisionBody, user=Depends(current_user)):
        return gateway.call(body.appId, 'vision', {'file_id': body.fileId, 'instruction': body.instruction,
                                                   'classification': body.classification}, principal=tool_user(user, body.appId))

    @tools.post('/transcribe')
    def transcribe(body: TranscribeBody, user=Depends(current_user)):
        return gateway.call(body.appId, 'transcribe', {'file_id': body.fileId,
                                                        'classification': body.classification},
                            principal=tool_user(user, body.appId))

    app.include_router(router)
    app.include_router(tools)

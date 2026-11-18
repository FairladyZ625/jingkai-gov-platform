"""冻结，勿改；改了说明你破坏了兼容。仅含虚构数据的 SDK 1.0 应用。"""
from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, app_context, require
from haiknow_sdk.ai import AIError

router = APIRouter()


@router.get('/context')
def context(ctx: AppContext = Depends(app_context)):
    return dict(app=ctx.app_id, user=ctx.user.id, name=ctx.user.name,
                roles=ctx.user.roles, projects=ctx.user.projects,
                actions=sorted(ctx.actions), approve=ctx.can('approve'))


@router.post('/legacy')
def legacy(ctx: AppContext = Depends(require('operate'))):
    fid = ctx.files.save('冻结.txt', b'sdk1')
    ctx.kv.put('sdk1-file', fid)
    ctx.audit('sdk1.save', {'file': fid})
    return dict(content=ctx.files.read(fid).decode(), files=ctx.files.list(),
                value=ctx.kv.get('sdk1-file'), missing=ctx.kv.get('missing', 'default'),
                kv=ctx.kv.list('sdk1'), available=ctx.model.available,
                answer=ctx.model.chat([{'role': 'user', 'content': '兼容样例'}]))


@router.post('/upload')
def upload(ctx: AppContext = Depends(require('operate'))):
    f = ctx.data_files.save('凭证.txt', b'sdk1', project='sample-project', purpose='兼容测试')
    assert ctx.data_files.read(f['fileId']) == b'sdk1'
    return ctx.data_files.get(f['fileId'])


@router.post('/save')
def save(body: dict, ctx: AppContext = Depends(require('operate'))):
    return ctx.records.save(**body)


@router.get('/record/{rid}')
def record(rid: str, version: int | None = None, ctx: AppContext = Depends(app_context)):
    return ctx.records.get(rid, version)


@router.get('/records')
def records(ctx: AppContext = Depends(app_context)):
    return ctx.records.list(project='sample-project')


@router.post('/submit')
def submit(body: dict, ctx: AppContext = Depends(require('operate'))):
    return ctx.reviews.submit(**body)


@router.post('/decision/{rid}')
def decide(rid: str, body: dict, ctx: AppContext = Depends(require('approve'))):
    return ctx.reviews.decide(rid, **body)


@router.get('/reviews')
def reviews(ctx: AppContext = Depends(app_context)):
    return ctx.reviews.list(assignee='me')


@router.get('/artifacts')
def artifacts(ctx: AppContext = Depends(app_context)):
    return ctx.artifacts.find(project='sample-project')


@router.get('/notifications')
def notifications(ctx: AppContext = Depends(app_context)):
    return ctx.notifications.list()


@router.post('/read/{nid}')
def read(nid: str, ctx: AppContext = Depends(app_context)):
    return ctx.notifications.read(nid)


@router.post('/ai')
def ai(ctx: AppContext = Depends(require('operate'))):
    results = {}
    calls = dict(chat=lambda: ctx.ai.chat([{'role': 'user', 'content': '测试'}]),
                 image=lambda: ctx.ai.image('虚构图案'),
                 transcribe=lambda: ctx.ai.transcribe('ZGVtbw=='),
                 speech=lambda: ctx.ai.speech('测试'), embedding=lambda: ctx.ai.embedding('测试'))
    for capability, call in calls.items():
        try:
            call()
        except AIError as error:
            results[capability] = dict(kind=error.kind, retryable=error.retryable)
    return results

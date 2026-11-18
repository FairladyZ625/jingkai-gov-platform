"""经开区实例注册入口：install(app, current_user)。"""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from haiknow_sdk import DataError

from .spec import CONTENT, TOOLS, SkillError, invalid
from .storage import Skills


class SkillRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def dispatch(request):
            try:
                return await handle(request)
            except SkillError as exc:
                return JSONResponse({"error": exc.error}, status_code=exc.status)
            except DataError as exc:
                details = {k: v for k, v in exc.error.items() if k not in ("code", "message", "retryable")}
                return JSONResponse({"error": {"code": exc.code.upper(), "message": str(exc),
                                               "details": details}}, status_code=exc.status)
            except HTTPException as exc:
                if exc.status_code not in (401, 403):
                    raise
                code = "UNAUTHENTICATED" if exc.status_code == 401 else "FORBIDDEN"
                return JSONResponse({"error": {"code": code, "message": str(exc.detail), "details": {}}},
                                    status_code=exc.status_code, headers=exc.headers)
        return dispatch


class SkillCatalog(Skills):
    def listed(self, user, doc, *, review):
        item = doc["data"]
        return self.access(user, item)[0] and (not review or item["status"] == "in_review")

    def list_items(self, user, *, mine, review):
        docs = self.records.list_records(user, "skills")["items"]
        items = []
        for doc in docs:
            item = doc["data"]
            if item["deleted"] or (mine and item["authorId"] != user.id) or not self.listed(user, doc, review=review):
                continue
            items.append(self.view(user, doc, history=False))
        return items


def install(app, current_user, *, editor_options=None, runs_for=None):
    platform = app.state.platform
    app.state.skills = SkillCatalog(platform)
    router = APIRouter(prefix="/api/v1/skills", route_class=SkillRoute)

    def get_skills():
        return app.state.skills

    @router.get("")
    def listing(mine: bool = False, review: bool = False, user=Depends(current_user), skills=Depends(get_skills)):
        apps = [{"id": aid, "name": entry.manifest["name"]} for aid, entry in platform.apps.items()
                if "view" in platform.rbac.actions(user, aid)]
        return {"items": skills.list_items(user, mine=mine, review=review), "apps": apps}

    @router.get("/meta/options")
    def options(user=Depends(current_user), skills=Depends(get_skills)):
        skills.records.app(user, "skills")
        departments = platform.directory.profile(user)["departments"]
        opts = {"models": [], "spaces": [], "computerTasks": [
            {"id": key, "label": label} for key, label in
            (("stats", "统计月报填报"), ("apply", "政策申报填表"), ("notice", "下载通知入库"), ("status", "查询办理进度"))
        ]}
        if editor_options:
            opts.update(editor_options(user))
        return {**opts, "tools": TOOLS, "users": [{"id": u.id, "name": u.name}
                for u in platform.rbac.users.values() if u.id != user.id],
                "myDept": "、".join(d["name"] for d in departments)}

    @router.get("/{sid}")
    def detail(sid: str, user=Depends(current_user), skills=Depends(get_skills)):
        doc = skills.load(user, sid)
        return {"item": skills.view(user, doc), "runs": runs_for(user, sid) if runs_for else []}

    @router.post("")
    def create(body: dict, user=Depends(current_user), skills=Depends(get_skills)):
        source = body.get("forkOf")
        if source is not None:
            if not isinstance(source, dict) or not isinstance(source.get("id"), str):
                invalid("复制来源须包含技能标识和版本")
            doc = skills.load(user, source["id"])
            version = source.get("version")
            if not isinstance(version, str) or version not in skills.history(doc):
                raise SkillError(404, "NOT_FOUND", "来源技能版本不存在")
            source = {"id": doc["id"], "version": version}
        return {"item": skills.create(user, body, source)}

    @router.patch("/{sid}")
    def patch(sid: str, body: dict, user=Depends(current_user), skills=Depends(get_skills)):
        return {"item": skills.revise(user, sid, body)}

    @router.post("/{sid}/fork")
    def fork(sid: str, user=Depends(current_user), skills=Depends(get_skills)):
        source = skills.load(user, sid)["data"]
        body = {k: source[k] for k in CONTENT}
        body["name"] += "（我的版本）"
        return {"item": skills.create(user, body, {"id": sid, "version": source["version"]})}

    @router.post("/{sid}/restore")
    def restore(sid: str, body: dict, user=Depends(current_user), skills=Depends(get_skills)):
        return {"item": skills.revise(user, sid, body, restore=True)}

    @router.delete("/{sid}")
    def remove(sid: str, user=Depends(current_user), skills=Depends(get_skills)):
        return {"ok": True, "item": skills.set_deleted(user, sid, True)}

    @router.post("/{sid}/restore-deleted")
    def undo(sid: str, user=Depends(current_user), skills=Depends(get_skills)):
        return {"ok": True, "item": skills.set_deleted(user, sid, False)}

    app.include_router(router)

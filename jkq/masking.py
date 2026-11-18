"""企业响应投影。字段在 CSV 排版、卡片渲染前统一过滤。"""

import re
from copy import deepcopy


class MaskRules:
    """整份配置校验后替换；并发请求使用各自取得的快照。"""

    def __init__(self, path):
        self.path = path
        self.reload()

    def reload(self):
        import yaml

        rules = {}
        for row in yaml.safe_load(self.path.read_text(encoding="utf-8"))["rules"]:
            style = re.fullmatch(r"([0-9]*)(\*+)([0-9]*)", row["show"])
            if not style or not isinstance(row["fields"], list):
                raise ValueError("字段打码规则格式错误")
            prefix, stars, suffix = style.groups()
            fields = rules.setdefault(row["entity"], [])
            for field in row["fields"]:
                parts = field.split(".")
                if not all(re.fullmatch(r"[A-Za-z_]\w*(?:\[\])?", part) for part in parts):
                    raise ValueError("脱敏字段路径格式错误")
                fields.append((parts, len(prefix), stars, len(suffix)))
        if not rules.get("enterprise"):
            raise ValueError("缺少企业脱敏规则")
        self._rules = rules

    def projector(self, entity):
        fields = self._rules[entity]

        def project(record):
            result = deepcopy(record)
            if entity == "enterprise":
                # 变更记录含自由文本来源和展示标签，无法可靠回推字段路径。
                _hide_changes(result)
            for parts, prefix, stars, suffix in fields:
                _apply(result, parts, prefix, stars, suffix)
            return result

        return project


def _hide_changes(document):
    for key in ("history", "proposals"):
        if key in document:
            document[key] = []


def enterprise_card(record, project):
    """供消息编排组装 reply.cards 时调用，project 来自 enterprise_projector 依赖。"""
    return {"type": "enterprise-brief", "entId": record["id"], "item": project(record)}


def _apply(parent, parts, prefix, stars, suffix):
    part = parts[0]
    array = part.endswith("[]")
    key = part[:-2] if array else part
    if parent is None:
        return
    if not isinstance(parent, dict):
        raise ValueError("企业记录与脱敏路径不符")
    if key not in parent:
        return
    value = parent[key]

    def masked(item):
        text = str(item) if isinstance(item, (str, int, float)) else ""
        if len(text) < 4 or len(text) <= prefix + suffix:
            return "****"
        return text[:prefix] + stars + (text[-suffix:] if suffix else "")

    if array and isinstance(value, list):
        for index, item in enumerate(value):
            if len(parts) == 1:
                value[index] = masked(item)
            else:
                _apply(item, parts[1:], prefix, stars, suffix)
    elif len(parts) == 1:
        parent[key] = masked(value)
    elif value is not None:
        if array or not isinstance(value, dict):
            raise ValueError("企业字段结构与脱敏路径不符")
        _apply(value, parts[1:], prefix, stars, suffix)


def install(app, source, *, role_mask=None):
    """在 #11 注册。source 提供业务读取、更新及 CSV 排版；只向排版器传入投影后的记录。

    kb_docs(space, excluded, request) 须在分页、计数前排除 excluded 中的空间。
    role_mask(role) 可接 #13 的即时角色配置。返回的 MaskRules 支持显式 reload()。
    """
    import yaml
    from fastapi import APIRouter, Depends, Request
    from fastapi.responses import JSONResponse

    try:
        from jkq.auth import AuthError, require_action
    except ImportError:
        from haiknow_core.main import current_user

        class AuthError(Exception):
            def __init__(self, status, code, message, **details):
                super().__init__(message)
                self.status = status
                self.error = {"code": code, "message": message, "details": details}

        def require_action(app_id, action):
            def check(request: Request, user=Depends(current_user)):
                platform = request.app.state.platform
                if action not in platform.rbac.actions(user, app_id):
                    details = {"app": app_id, "need": action}
                    platform.store.audit(app_id, user.id, "permission.denied", details)
                    raise AuthError(403, "FORBIDDEN", "当前角色缺少所需权限", **details)
                return user

            return check

    platform = app.state.platform
    rules = MaskRules(platform.config_dir / "mask_rules.yaml")
    if role_mask is None:
        def role_mask(role):
            config = yaml.safe_load((platform.config_dir / "roles.yaml").read_text(encoding="utf-8"))
            return config["roles"][role]["mask"]

    router = APIRouter()
    enterprise = "/api/apps/enterprise"
    kb_view = require_action("kb", "view")

    def mask_enabled(user=Depends(require_action("enterprise", "view"))):
        flags = [role_mask(role) for role in user.roles]
        if not flags or any(type(flag) is not bool for flag in flags):
            raise ValueError("角色缺少有效的脱敏设置")
        return any(flags)

    def projector(mask=Depends(mask_enabled)):
        return rules.projector("enterprise") if mask else (lambda row: row)

    app.state.enterprise_projector = projector

    @router.get(enterprise + "/companies/{company_id}")
    def detail(company_id: str, request: Request, project=Depends(projector), mask=Depends(mask_enabled)):
        document = source.detail(company_id, request)
        result = {**document, "item": project(document["item"])}
        if mask:
            _hide_changes(result)
        return result

    @router.get(enterprise + "/companies")
    def companies(request: Request, project=Depends(projector)):
        page = source.companies(request)
        return {**page, "items": [project(row) for row in page["items"]]}

    @router.get(enterprise + "/export")
    def export(request: Request, project=Depends(projector)):
        return source.format_csv([project(row) for row in source.export_rows(request)])

    @router.get(enterprise + "/companies/{company_id}/card")
    def card(company_id: str, request: Request, project=Depends(projector)):
        return enterprise_card(source.detail(company_id, request)["item"], project)

    def deny(user, app_id, need):
        details = {"app": app_id, "need": need}
        platform.store.audit(app_id, user.id, "permission.denied", details)
        raise AuthError(403, "FORBIDDEN", "外部协作者无权执行此操作", **details)

    @router.patch(enterprise + "/companies/{company_id}")
    def update(company_id: str, changes: dict, request: Request,
               user=Depends(require_action("enterprise", "operate"))):
        if "partner" in user.roles:
            deny(user, "enterprise", "operate")
        return source.update(company_id, changes, request)

    @router.get("/api/v1/kb/spaces")
    def spaces(request: Request, user=Depends(kb_view)):
        page = source.spaces(request)
        if "partner" not in user.roles:
            return page
        return {**page, "items": [row for row in page["items"] if row["id"] != "enterprise"]}

    @router.get("/api/v1/kb/libraries", include_in_schema=False)
    def libraries(page=Depends(spaces)):
        return {"items": [{"id": row["id"], "name": row["name"], "icon": row["icon"],
                           "files": row["count"]} for row in page["items"]]}

    @router.get("/api/v1/kb/docs")
    def docs(request: Request, space: str = None, user=Depends(kb_view)):
        excluded = ("enterprise",) if "partner" in user.roles else ()
        if space in excluded:
            deny(user, "kb", "view")
        return source.kb_docs(space, excluded, request)

    @app.exception_handler(AuthError)
    async def _mask_auth_error(_, exc):
        return JSONResponse({"error": exc.error}, status_code=exc.status)

    # 与 #12 相同，先匹配受保护的经开区路由，再匹配 core 中的同名路径。
    routes = app.router.routes
    offset = len(routes)
    app.include_router(router)
    routes[:] = routes[offset:] + routes[:offset]
    return rules

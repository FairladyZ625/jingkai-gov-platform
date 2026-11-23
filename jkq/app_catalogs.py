"""经开区对外应用目录过滤。"""

from functools import wraps

from fastapi.routing import APIRoute


def internal_app_ids(platform):
    return {app_id for app_id, entry in platform.apps.items() if entry.manifest.get("internal") is True}


def _app_list(body, internal):
    body["apps"] = [app for app in body["apps"] if app["id"] not in internal]
    for grants in body.get("grants", {}).values():
        for app_id in internal:
            grants.pop(app_id, None)


def _filter_endpoint(endpoint, platform):
    @wraps(endpoint)
    def filtered(**kwargs):
        body = endpoint(**kwargs)
        internal = internal_app_ids(platform)
        if internal:
            _app_list(body, internal)
        return body

    return filtered


def install(app):
    paths = {"/api/apps", "/api/admin/apps", "/api/admin/grants"}
    routers = [app.router]
    while routers:
        for route in routers.pop().routes:
            # 新版保留嵌套路由器，旧版把各路由展开到父路由器。
            included = getattr(route, "original_router", None)
            if included is not None:
                routers.append(included)
            if isinstance(route, APIRoute) and route.methods == {"GET"} and route.path in paths:
                filtered = _filter_endpoint(route.endpoint, app.state.platform)
                # 同步端点保留原依赖。嵌套路由匹配时会从 endpoint 重建依赖。
                route.endpoint = route.dependant.call = filtered

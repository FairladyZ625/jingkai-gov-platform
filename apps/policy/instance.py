"""通用工具桥就绪前，把 #22 的对话入口接到政策应用。"""

import json
import re
import unicodedata
from urllib.parse import quote

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient, HTTPError

from jkq.orchestrator.ports import ModelTurn, ToolCall


APP_ID = "policy"
_OPERATE = {"policy.match", "policy.notice"}
_DEMO_ENTERPRISES = {"书香里": "E001", "书香里文化": "E001", "纸鹿二号智驾": "E002"}
_DEMO_NAMES = "|".join(re.escape(name) for name in _DEMO_ENTERPRISES)


class PolicyToolBridge:
    """通过已挂载的应用路由执行工具，沿用同一登录态和 SDK 权限。"""

    def __init__(self, app):
        self.app = app

    def tools(self, user):
        platform = self.app.state.platform
        entry = platform.apps.get(APP_ID)
        actions = platform.rbac.actions(user, APP_ID)
        if entry is None or entry.unavailable_reason() or "view" not in actions:
            return {"items": []}
        return {"items": [
            {"name": tool["name"], "app": APP_ID, "write": tool["write"]}
            for tool in entry.manifest.get("tools", [])
            if type(tool.get("write")) is bool and (tool["name"] not in _OPERATE or "operate" in actions)
        ]}

    async def call_from_chat(self, request, app_id, tool, args):
        if app_id != APP_ID:
            raise HTTPException(404, "工具不存在")
        entry = self.app.state.platform.apps.get(APP_ID)
        specs = entry.manifest.get("tools", []) if entry else []
        spec = next((item for item in specs if item["name"] == tool), None)
        if spec is None or spec.get("write") is not False:
            raise HTTPException(404, "工具不存在")
        method, path = spec["endpoint"].split(" ", 1)
        if method not in {"GET", "POST"} or not re.fullmatch(r"/api/apps/policy/(?:[a-z-]+/)*[a-z-]+", path):
            raise HTTPException(404, "工具未注册到政策应用")

        if tool == "policy.notice" and "itemIds" not in args:
            return {"result": {"text": "请提供要写入政策参考清单的政策支持编号。"}}
        headers = [(name, value) for name, value in request.headers.raw if name == b"cookie"]
        options = {"params": args} if method == "GET" else {"json": args}
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://policy.internal",
                               headers=headers) as client:
            response = await client.request(method, path, **options)
        if not response.is_success:
            raise HTTPException(response.status_code, "政策工具执行失败")
        return {"result": response.json()}


class _NoticeSelectionGuard:
    """包住已安装的通用工具桥：未给出事项编号的告知单先追问，其余调用原样交回。"""

    def __init__(self, bridge):
        self._bridge = bridge

    def __getattr__(self, name):
        return getattr(self._bridge, name)

    def tools(self, user):
        return self._bridge.tools(user)

    async def call_from_chat(self, request, app_id, tool, args):
        if app_id == APP_ID and tool == "policy.notice" and "itemIds" not in args:
            return {"tool": tool, "result": {"text": "请提供要写入政策参考清单的政策支持编号。"}}
        return await self._bridge.call_from_chat(request, app_id, tool, args)


def _policy_call(text: str) -> ToolCall | None:
    text = unicodedata.normalize("NFKC", text).strip().rstrip("。?!")
    if match := re.fullmatch(rf"(?:看看)?({_DEMO_NAMES})能申请(?:什么|哪些(?:政策)?支持)", text):
        return ToolCall("policy.match", {"entId": _DEMO_ENTERPRISES[match[1]]})
    if match := re.fullmatch(r"搜索政策事项\s*:?\s*(\S.*)", text):
        return ToolCall("policy.search", {"q": match[1]})
    if match := re.fullmatch(rf"给({_DEMO_NAMES})生成(?:政策参考清单|参考清单|(?:政策)?告知单)\s*:?\s*"
                             r"([A-Za-z0-9-]+(?:[、,\s]+[A-Za-z0-9-]+)*)", text):
        return ToolCall("policy.notice", {
            "entId": _DEMO_ENTERPRISES[match[1]],
            "itemIds": re.split(r"[、,\s]+", match[2]),
        })
    return None


def policy_gateway(fallback=None):
    """在已安装的对话编排上挂政策话术：其余请求交回原网关，未配置模型时保持原有提示。"""

    async def gateway(request, *, messages, tools, model, classification, on_delta=None):
        last = messages[-1]
        if last["role"] == "tool" and _answers_policy_call(messages):
            result = json.loads(last["content"])
            return ModelTurn(deltas=(result.get("text") or "查询结果见卡片。",))
        if last["role"] == "user" and (call := _policy_call(last["content"])) and call.tool in tools:
            return ModelTurn(calls=(call,))
        if fallback is None:
            raise RuntimeError("未配置对话模型")
        return await fallback(request, messages=messages, tools=tools, model=model,
                              classification=classification, on_delta=on_delta)

    return gateway


def _answers_policy_call(messages):
    calls = next((message.get("tool_calls") for message in reversed(messages)
                  if message["role"] == "assistant" and message.get("tool_calls")), None) or []
    return bool(calls) and all(call["function"]["name"].startswith(APP_ID + ".") for call in calls)


async def selected_enterprise(request, enterprise_id: str) -> dict:
    """沿原企业 HTTP 路由授权；不读取演示画像、原值库或其他企业历史。"""
    unavailable = {'id': enterprise_id, 'status': 'unavailable'}
    headers = [(name, value) for name, value in request.headers.raw if name in {b'cookie', b'authorization'}]
    try:
        async with AsyncClient(transport=ASGITransport(app=request.app, raise_app_exceptions=False),
                               base_url='http://policy.internal', headers=headers) as client:
            response = await client.get('/api/apps/enterprise/companies/' + quote(enterprise_id, safe=''))
        if not response.is_success:
            return unavailable
        item = response.json()['item']
        if not isinstance(item, dict) or item.get('id') != enterprise_id or not item.get('name'):
            return unavailable
        # 只暴露当前岗位所需字段；保留原接口对只读账号的投影，绝不展开私库。
        fields = {key: item[key] for key in ('id', 'name', 'industry', 'scale')
                  if isinstance(item.get(key), str)}
        return {'id': enterprise_id, 'status': 'available', 'item': fields}
    except (KeyError, TypeError, ValueError, RuntimeError, HTTPError, TimeoutError):
        return unavailable


def install(app, current_user):
    """不重复注册会话路由；通用编排按 app.state 读取网关与工具桥。"""
    app.state.policy_enterprise_reader = selected_enterprise
    if getattr(app.state, "apps_bridge", None) is None:
        app.state.apps_bridge = PolicyToolBridge(app)
    else:
        app.state.apps_bridge = _NoticeSelectionGuard(app.state.apps_bridge)
    app.state.chat_gateway = policy_gateway(getattr(app.state, "chat_gateway", None))

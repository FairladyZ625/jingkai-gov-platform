import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest

pytest.importorskip("fastapi", reason="消息路由验证需要 requirements-dev.txt")

from fastapi.testclient import TestClient
from haiknow_core.store import Store
from haiknow_sdk import DataError
from starlette.requests import ClientDisconnect

from jkq.app import create_app
from jkq.conversations.store import ConversationStore
from jkq.orchestrator.persistence import finish_turn, start_turn
from jkq.orchestrator.ports import ModelTurn, ToolCall
from jkq.orchestrator.routes import install
from jkq.settings import REPO_ROOT


BASE = "/api/v1/conversations"
OWNER = "sampleoperator"
PASSWORD = "demo-pass"
POLICY_RESULT = {"results": [{"id": "PI-01", "title": "演示条款", "level": "check"}]}
SOURCES = [{"id": "KB-1", "title": "公开演示政策", "snippet": "该示例用于测试出处。", "n": 1}]
KB_ANSWER = "“该示例用于测试出处。”[1]"
KB_NO_MATCH = {"outcome": "no_match", "confidence": "none", "citations": []}


class ScriptedGateway:
    def __init__(self):
        self.script = []
        self.requests = []

    async def __call__(self, request, **payload):
        self.requests.append(payload)
        assert self.script, "这轮不应继续调用模型"
        return self.script.pop(0)


class BridgeStub:
    def __init__(self, owner):
        self.owner = owner
        self.catalog = {
            "policy.match": False, "policy.search": False, "enterprise.get": False,
            "enterprise.search": False, "meeting.commit_todos": True, "kb.ask": False,
            "kb.search": False, "kb.import": True, "test.publish": True, "document.submit": True,
        }
        self.calls = []
        self.kb_classes = []
        self.preflights = []
        self.reviews = []
        self.write_errors = {}
        self.results = {
            "policy.match": POLICY_RESULT,
            "policy.search": {"items": [{"id": "PI-01"}]},
            "enterprise.get": {"item": {"id": "E002"}},
            "enterprise.search": {"items": [{"id": "E002"}]},
            "kb.ask": {"outcome": "answered", "confidence": "high", "answer": KB_ANSWER, "citations": SOURCES},
        }

    def tools(self, user):
        assert user.id == self.owner
        return {"items": [
            {"name": name, "app": name.partition(".")[0], "write": write}
            for name, write in self.catalog.items()
        ]}

    async def call_from_chat(self, request, app_id, tool, args):
        assert request.session.get("uid") == self.owner
        assert tool != "kb.ask", "密级不能经旧工具接口传递"
        if self.catalog[tool]:
            failure = self.write_errors.get(tool)
            if failure and failure.code == "FORBIDDEN":
                raise failure
            self.preflights.append((app_id, tool, args))
            if failure:
                raise failure
            self.reviews.append((app_id, tool, args))
            return {"tool": tool, "result": {"status": "pending", "reviewId": "TEST-REVIEW"}}
        self.calls.append((app_id, tool, args))
        return {"tool": tool, "result": self._result(tool)}

    async def ask_from_chat(self, request, question, *, classification):
        assert request.session.get("uid") == self.owner
        self.calls.append(("kb", "kb.ask", {"q": question}))
        self.kb_classes.append(classification)
        return self._result("kb.ask")

    def _result(self, tool):
        result = self.results[tool]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def instance_client(isolated_platform, reuse_loaded_routers, cheap_password_hash, monkeypatch):
    monkeypatch.setenv("HAIKNOW_SECRET", "jkq-test-session-signing")
    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    monkeypatch.setenv("JKQ_DEMO_MODE", "0")
    monkeypatch.setenv("HAIKNOW_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(REPO_ROOT / "config"))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(REPO_ROOT / "apps"))

    def create_client():
        client = TestClient(create_app())
        response = client.post("/api/auth/bootstrap", json={
            "username": OWNER, "password": PASSWORD, "name": "测试经办账号",
        })
        assert response.status_code == 200
        return client

    return create_client


def _owner(client):
    return client.get("/api/auth/session").json()["user"]["id"]


@pytest.fixture
def connected(instance_client):
    client = instance_client()
    bridge, gateway = BridgeStub(_owner(client)), ScriptedGateway()
    client.app.state.apps_bridge = bridge
    client.app.state.chat_gateway = gateway
    cid = client.post(BASE, json={}).json()["item"]["id"]
    return client, f"{BASE}/{cid}/messages", bridge, gateway


def test_normal_instance_registers_messages_even_without_upstream_dependencies(instance_client):
    client = instance_client()
    cid = client.post(BASE, json={}).json()["item"]["id"]
    response = client.post(f"{BASE}/{cid}/messages", json={"text": "你好"})
    assert response.status_code == 200
    assert response.json()["reply"]["content"] == "模型暂不可用，无法完成这次对话。"
    assert client.get(f"{BASE}/{cid}").json()["messages"][-1] == response.json()["reply"]


@pytest.mark.parametrize(("data_class", "claim", "files", "expected"), [
    ("public", "public", [], "public"),
    ("internal", "public", [], "internal"),
    ("confidential", "public", [], "confidential"),
    (None, "public", [], "confidential"),
    ("public", "confidential", [], "confidential"),
    ("public", "待核定", [], "confidential"),
    ("public", "public", [{"id": "F-1", "classification": "public"}], "confidential"),
])
def test_first_turn_combines_classification_before_gateway(
    instance_client, monkeypatch, data_class, claim, files, expected,
):
    monkeypatch.setattr("jkq.orchestrator.routes.install", partial(install, classification="public"))
    client = instance_client()
    client.app.state.platform.apps["document"].manifest["dataClass"] = data_class
    gateway = ScriptedGateway()
    client.app.state.chat_gateway = gateway
    gateway.script = [ModelTurn(("测试回复。",))]
    cid = client.post(BASE, json={"app": "document"}).json()["item"]["id"]
    payload = client.post(f"{BASE}/{cid}/messages", json={"text": "请帮我处理", "files": files,
                                                         "classification": claim}).json()
    assert gateway.requests[0]["classification"] == payload["user"]["classification"] == expected


@pytest.mark.parametrize("legacy", [False, True])
def test_classification_inherits_history_without_tool_calls(instance_client, monkeypatch, legacy):
    monkeypatch.setattr("jkq.orchestrator.routes.install", partial(install, classification="public"))
    client = instance_client()
    gateway = ScriptedGateway()
    client.app.state.chat_gateway = gateway
    gateway.script = [ModelTurn(("测试回复。",))] * 2
    cid = client.post(BASE, json={}).json()["item"]["id"]
    url = f"{BASE}/{cid}/messages"
    if legacy:
        client.app.state.conversations.append_message(_owner(client), cid, role="user", content="旧消息")
    else:
        assert client.post(url, json={"text": "一条受限消息",
                                      "classification": "confidential"}).status_code == 200
    reply = client.post(url, json={"text": "继续说", "classification": "public"}).json()["reply"]
    assert gateway.requests[-1]["classification"] == reply["classification"] == "confidential"
    assert gateway.requests[-1]["messages"][1]["content"] == ("旧消息" if legacy else "一条受限消息")


def test_rule_calls_tool_without_gateway_and_uses_previous_match_for_override(connected):
    client, url, bridge, gateway = connected
    first = client.post(url, json={"text": "书香里文化能申请哪些支持？", "files": [{"id": "F1"}]})
    assert first.status_code == 200
    assert first.json()["user"]["files"] == [{"id": "F1"}]
    assert first.json()["reply"]["intent"] == "policy"
    second = client.post(url, json={"text": "补填数据采购额 30 万"}).json()["reply"]
    assert bridge.calls == [
        ("policy", "policy.match", {"entId": "E001"}),
        ("policy", "policy.match", {"entId": "E001", "overrides": {"dataPurchase": 300000}}),
    ]
    assert second["cards"][0]["deepLink"] == {"app": "policy", "params": {"entId": "E001"}}
    assert not gateway.requests
    assert client.get(url.removesuffix("/messages")).json()["messages"][-1] == second


def test_policy_followup_with_unknown_target_requests_clarification(connected):
    client, url, bridge, gateway = connected
    reply = client.post(url, json={"text": "补填数据采购额 30 万"}).json()["reply"]
    assert reply["intent"] == "policy"
    assert "哪家企业" in reply["content"]
    assert not bridge.calls and not gateway.requests


def test_model_tool_name_and_args_sequence_snapshot(connected):
    client, url, bridge, gateway = connected
    gateway.script = [
        ModelTurn(("尚未执行的模型草稿",), (ToolCall("enterprise.search", {"q": "星河"}, "a"),)),
        ModelTurn(calls=(ToolCall("policy.match", {"entId": "E002"}, "b"),)),
        ModelTurn(("找到企业。", "请查看适用政策。"), model="configured-local", route_note="走本地"),
    ]
    response = client.post(url, json={"text": "看看星河的办理情况", "model": "configured-route",
                                      "classification": "public"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert json.dumps(reply["toolCalls"], ensure_ascii=False, sort_keys=True) == (
        '[{"args": {"q": "星河"}, "status": "ok", "tool": "enterprise.search"}, '
        '{"args": {"entId": "E002"}, "status": "ok", "tool": "policy.match"}]'
    )
    assert bridge.calls == [
        ("enterprise", "enterprise.search", {"q": "星河"}),
        ("policy", "policy.match", {"entId": "E002"}),
    ]
    assert reply["content"] == "查询结果见卡片。"
    assert [card["type"] for card in reply["cards"]] == ["enterprise-list", "policy-match"]
    assert (reply["model"], reply["routeNote"]) == ("configured-local", "走本地")
    assert [payload["model"] for payload in gateway.requests] == ["configured-route"] * 3
    assert [payload["classification"] for payload in gateway.requests] == ["confidential"] * 3
    assert not {"kb.search", "admin.export"}.intersection(gateway.requests[0]["tools"])
    assert gateway.requests[1]["messages"][-2]["tool_calls"][0]["id"] == "a"
    last_tools = [item for item in gateway.requests[-1]["messages"] if item["role"] == "tool"]
    assert [(item["tool_call_id"], json.loads(item["content"])) for item in last_tools] == [
        ("a", {"items": [{"id": "E002"}]}), ("b", POLICY_RESULT),
    ]


@pytest.mark.parametrize("confidence", ["high", "none"])
def test_kb_uses_citations_or_reports_no_source_without_model(connected, confidence):
    client, url, bridge, gateway = connected
    if confidence == "none":
        bridge.results["kb.ask"] = KB_NO_MATCH
    text = "知识库里有没有关于火星基地的政策？"
    reply = client.post(url, json={"text": text}).json()["reply"]
    assert bridge.calls == [("kb", "kb.ask", {"q": text})]
    assert not gateway.requests
    if confidence == "none":
        assert (reply["content"], reply["citations"], reply["cards"]) == (
            "知识库里没有找到能回答这个问题的原文。", [], [],
        )
    else:
        assert reply["citations"] == [{"fileId": "KB-1", "name": "公开演示政策", "snippet": SOURCES[0]["snippet"]}]
        assert reply["cards"][0]["deepLink"] == {"app": "kb", "params": {"fileId": "KB-1"}}


def test_model_selected_kb_cannot_substitute_its_answer(instance_client, monkeypatch):
    monkeypatch.setattr("jkq.orchestrator.routes.install", partial(install, classification="public"))
    client = instance_client()
    bridge, gateway = BridgeStub(_owner(client)), ScriptedGateway()
    client.app.state.apps_bridge, client.app.state.chat_gateway = bridge, gateway
    cid = client.post(BASE, json={}).json()["item"]["id"]
    url = f"{BASE}/{cid}/messages"
    args = {"q": "相关背景", "classification": "public", "dataClass": "public"}
    gateway.script = [
        ModelTurn(calls=(ToolCall("enterprise.get", {"id": "E002"}),)),
        ModelTurn(("模型草稿",), (ToolCall("kb.ask", args),)),
    ]
    bridge.results["kb.ask"] = KB_NO_MATCH
    reply = client.post(url, json={"text": "多说一点相关的背景", "classification": "public"}).json()["reply"]
    assert reply["content"].count("知识库里没有找到能回答这个问题的原文。") == 1
    assert "模型草稿" not in reply["content"]
    assert reply["toolCalls"][-1] == {"tool": "kb.ask", "args": {"q": "相关背景"}, "status": "ok"}
    assert bridge.kb_classes == ["confidential"]
    assert [request["classification"] for request in gateway.requests] == ["public", "confidential"]


def test_legacy_bridge_cannot_receive_kb_question_without_classification(connected, monkeypatch):
    client, url, bridge, gateway = connected
    monkeypatch.delattr(BridgeStub, "ask_from_chat")
    reply = client.post(url, json={"text": "数据券申报单位须在经开区注册满一年吗"}).json()["reply"]
    assert reply["content"] == "未能完成请求，知识库暂不可用。"
    assert reply["toolCalls"][0]["status"] == "error"
    assert not bridge.calls and not gateway.requests


@pytest.mark.parametrize("stream", [False, True])
def test_unclassified_input_never_releases_gateway_draft(connected, stream):
    client, url, bridge, _ = connected
    calls = []
    text = "经开区的领券门槛卡户籍还是缴税"

    async def bypass_gateway(request, *, on_delta, **payload):
        calls.append(on_delta)
        if on_delta is not None:
            await on_delta("注册半年就能领券。")
        return ModelTurn(("注册半年就能领券。",))

    client.app.state.chat_gateway = bypass_gateway
    bridge.results["kb.ask"] = KB_NO_MATCH
    response = client.post(url, json={"text": text, "stream": stream})
    assert response.status_code == 200
    assert "注册半年" not in response.text
    reply = list(_events(response.text))[-1][1]["reply"] if stream else response.json()["reply"]
    assert reply["content"] == "知识库里没有找到能回答这个问题的原文。"
    assert calls == [None]
    assert bridge.calls == [("kb", "kb.ask", {"q": text})]


@pytest.mark.parametrize(("text", "app"), [
    ("怎么拿到数据券？", None),
    ("亦庄高企首认补助标准", None),
    ("数据券申报单位须在经开区注册满一年吗", None),
    ("这数据券咋弄啊", None),
    ("这里的申请条件是什么", "kb"),
    ("信息技术产业局职责", "kb"),
    ("导入知识库需要哪些资料", "kb"),
])
def test_knowledge_question_preempts_model_plain_text(connected, text, app):
    client, url, bridge, gateway = connected
    gateway.script = [ModelTurn(("没有出处的模型回答。",))]
    reply = client.post(url, json={"text": text, "app": app}).json()["reply"]
    assert reply["content"] == KB_ANSWER
    assert reply["citations"]
    assert bridge.calls == [("kb", "kb.ask", {"q": text})]
    assert not gateway.requests


def test_knowledge_followup_keeps_trusted_classification(instance_client, monkeypatch):
    monkeypatch.setattr("jkq.orchestrator.routes.install", partial(install, classification="public"))
    client = instance_client()
    bridge, gateway = BridgeStub(_owner(client)), ScriptedGateway()
    client.app.state.apps_bridge = bridge
    client.app.state.chat_gateway = gateway
    cid = client.post(BASE, json={}).json()["item"]["id"]
    url = f"{BASE}/{cid}/messages"
    previous = "数据券申报条件是什么？"
    first = client.post(url, json={"text": previous, "classification": "confidential"}).json()
    text = "那要卡到哪天"
    second = client.post(url, json={"text": text, "classification": "public"}).json()
    assert first["reply"]["citations"] and second["reply"]["citations"]
    assert bridge.kb_classes == [first["user"]["classification"], second["user"]["classification"]] == [
        "confidential", "confidential",
    ]
    assert bridge.calls[-1] == ("kb", "kb.ask", {"q": f"{previous}\n{text}"})
    assert not gateway.requests


@pytest.mark.parametrize("app", [None, "kb"])
def test_kb_import_uses_registered_action(connected, app):
    client, url, bridge, gateway = connected
    args = {"id": "F-1"}
    gateway.script = [ModelTurn(calls=(ToolCall("kb.import", args),))]
    reply = client.post(url, json={"text": "把这份政策原文导入知识库", "app": app}).json()["reply"]
    if app == "kb":
        assert gateway.requests[0]["tools"] == ["kb.import"]
    assert reply["toolCalls"][0]["status"] == "pending"
    assert bridge.reviews == [("kb", "kb.import", args)]
    assert not bridge.calls and not reply["citations"]


def test_explicit_kb_import_cannot_run_a_misdeclared_write_tool(connected):
    client, url, bridge, gateway = connected
    bridge.catalog["kb.import"] = False
    gateway.script = [ModelTurn(calls=(ToolCall("kb.import", {"id": "F-1"}),))]
    reply = client.post(url, json={"text": "导入这份文档", "app": "kb"}).json()["reply"]
    assert reply["toolCalls"][0]["status"] == "error"
    assert not bridge.calls and not bridge.reviews


@pytest.mark.parametrize(("failure", "message"), [
    (DataError("FORBIDDEN", "内部错误详情"), "未能完成请求，当前账号没有权限。"),
    (TimeoutError("内部错误详情"), "未能完成请求，工具响应超时。"),
    (RuntimeError("内部错误详情"), "未能完成请求，工具服务暂不可用。"),
    ({"outcome": "unavailable", "confidence": "none", "citations": []},
     "知识库暂时无法提供有出处的回答，请稍后再试。"),
    ({"confidence": "none", "citations": []}, "未能完成请求，工具返回了无法使用的结果。"),
    ({"outcome": "answered", "confidence": "high", "answer": "无引用答案", "citations": []},
     "未能完成请求，工具返回了无法使用的结果。"),
    ({"outcome": "answered", "confidence": "high", "answer": "无法从原文证明的结论。[1]", "citations": SOURCES},
     "未能完成请求，工具返回了无法使用的结果。"),
    ({"outcome": "answered", "confidence": "high", "answer": KB_ANSWER, "citations": [{**SOURCES[0], "id": ""}]},
     "未能完成请求，工具返回了无法使用的结果。"),
])
def test_tool_failure_is_200_and_never_uses_model_to_recover(connected, failure, message):
    client, url, bridge, gateway = connected
    bridge.results["kb.ask"] = failure
    gateway.script = [ModelTurn(("未经核验的草稿",), (ToolCall("kb.ask", {"q": "背景"}),))]
    response = client.post(url, json={"text": "多说一点相关的背景"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply["content"] == message
    assert reply["toolCalls"] == [{"tool": "kb.ask", "args": {"q": "背景"}, "status": "error"}]
    assert not reply["cards"] and not reply["citations"]
    assert len(gateway.requests) == 1


def test_explicit_app_skips_rule_and_filters_available_tools(connected):
    client, url, bridge, gateway = connected
    gateway.script = [
        ModelTurn(calls=(ToolCall("enterprise.get", {"id": "E002"}),)),
        ModelTurn(("请查看企业档案。",)),
    ]
    response = client.post(url, json={"text": "书香里文化能申请哪些支持？", "app": "enterprise"})
    assert response.status_code == 200
    assert response.json()["reply"]["intent"] == "enterprise"
    assert gateway.requests[0]["tools"] == ["enterprise.get", "enterprise.search"]
    assert bridge.calls == [("enterprise", "enterprise.get", {"id": "E002"})]


def test_explicit_non_kb_app_does_not_fallback_to_kb_or_model_text(connected):
    client, url, bridge, gateway = connected
    gateway.script = [ModelTurn(("注册半年就能领券。",))]
    reply = client.post(url, json={"text": "数据券申报单位须在经开区注册满一年吗", "app": "enterprise"}).json()["reply"]
    assert gateway.requests[0]["tools"] == ["enterprise.get", "enterprise.search"]
    assert reply["content"] == "请说明要在当前应用中查询或办理的事项。"
    assert not reply["toolCalls"] and not bridge.calls


def test_model_cannot_call_tools_outside_the_user_supplied_app(connected):
    client, url, bridge, gateway = connected
    gateway.script = [ModelTurn(calls=(ToolCall("policy.match", {"entId": "E001"}),))]
    reply = client.post(url, json={"text": "帮我看看", "app": "enterprise"}).json()["reply"]
    assert reply["toolCalls"][0]["status"] == "error"
    assert not bridge.calls


@pytest.mark.parametrize(("text", "tool", "args"), [
    ("把座谈会的待办派发下去", "meeting.commit_todos", {"meetingId": "MT-1112"}),
    ("执行这项工作", "test.publish", {"id": "S-1"}),
    ("把刚写的草稿交给审核人", "document.submit", {"id": "D-1"}),
])
def test_write_tools_only_create_pending_intent(connected, text, tool, args):
    client, url, bridge, gateway = connected
    if tool != "meeting.commit_todos":
        gateway.script = [ModelTurn(("已写入",), (ToolCall(tool, args),))]
    reply = client.post(url, json={"text": text}).json()["reply"]
    assert reply["toolCalls"] == [{"tool": tool, "args": args, "status": "pending", "reviewId": "TEST-REVIEW"}]
    assert reply["content"] == "这项操作需要你确认。"
    assert bridge.reviews == bridge.preflights == [(tool.partition(".")[0], tool, args)]
    assert not bridge.calls


@pytest.mark.parametrize(("code", "expected", "preflight_count"), [
    ("FORBIDDEN", "当前账号没有权限", 0),
    ("NOT_FOUND", "没有找到目标资源", 1),
    ("CHECK_FAILED", "工具参数或业务校验未通过", 1),
])
def test_write_tool_does_not_create_review_if_authorization_or_preflight_fails(
    connected, code, expected, preflight_count,
):
    client, url, bridge, gateway = connected
    bridge.write_errors["document.submit"] = DataError(code, "测试错误")
    gateway.script = [ModelTurn(calls=(ToolCall("document.submit", {"id": "D-1"}),))]
    response = client.post(url, json={"text": "把刚写的草稿交给审核人"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply["toolCalls"] == [{"tool": "document.submit", "args": {"id": "D-1"}, "status": "error"}]
    assert expected in reply["content"]
    assert len(bridge.preflights) == preflight_count and not bridge.reviews and not bridge.calls


def test_submit_without_draft_id_requests_clarification(connected):
    client, url, bridge, gateway = connected
    reply = client.post(url, json={"text": "送审签"}).json()["reply"]
    assert reply["toolCalls"] == [{"tool": "document.submit", "args": {}, "status": "skipped"}]
    assert reply["content"] == "请先告诉我需要送审签的草稿编号。"
    assert not bridge.preflights and not bridge.reviews and not bridge.calls and not gateway.requests


def test_misdeclared_submit_tool_cannot_execute(connected):
    client, url, bridge, gateway = connected
    bridge.catalog["document.submit"] = False
    gateway.script = [ModelTurn(calls=(ToolCall("document.submit", {"id": "D-1"}),))]
    reply = client.post(url, json={"text": "把刚写的草稿交给审核人"}).json()["reply"]
    assert reply["toolCalls"][0]["status"] == "error"
    assert not bridge.preflights and not bridge.reviews and not bridge.calls


def test_mixed_tool_batch_records_every_outcome_in_order(connected):
    client, url, bridge, gateway = connected
    bridge.results["policy.search"] = TimeoutError()
    calls = (
        ToolCall("policy.search", {"q": "示例"}),
        ToolCall("enterprise.get", {"id": "E002"}),
        ToolCall("test.publish", {"id": "S-1"}),
        ToolCall("document.submit"),
    )
    gateway.script = [ModelTurn(("已全部完成。",), calls)]
    reply = client.post(url, json={"text": "请依次处理这几项工作"}).json()["reply"]
    assert [(entry["tool"], entry["status"]) for entry in reply["toolCalls"]] == [
        ("policy.search", "error"), ("enterprise.get", "ok"),
        ("test.publish", "pending"), ("document.submit", "skipped"),
    ]
    assert [call[1] for call in bridge.calls] == ["policy.search", "enterprise.get"]
    assert bridge.reviews == [("test", "test.publish", {"id": "S-1"})]
    assert len(gateway.requests) == 1 and "已全部完成" not in reply["content"]
    assert [card["type"] for card in reply["cards"]] == ["enterprise-brief"]


def test_registry_revalidates_read_that_became_write(connected):
    client, url, bridge, gateway = connected
    bridge.results["policy.match"] = {"status": "pending", "reviewId": "TEST-REVIEW"}
    reply = client.post(url, json={"text": "书香里文化能申请哪些支持？"}).json()["reply"]
    assert reply["toolCalls"][0]["status"] == "pending"
    assert reply["toolCalls"][0]["reviewId"] == "TEST-REVIEW"
    assert reply["cards"] == []
    assert not gateway.requests


def test_model_loop_terminates_at_round_limit(connected):
    client, url, bridge, gateway = connected
    gateway.script = [ModelTurn(calls=(ToolCall("enterprise.get", {"id": "E002"}),))] * 5
    reply = client.post(url, json={"text": "继续处理"}).json()["reply"]
    assert len(gateway.requests) == len(bridge.calls) == len(reply["toolCalls"]) == 4
    assert "上限" in reply["content"]


def _events(data):
    for part in data.strip().split("\n\n"):
        kind, payload = part.split("\n", 1)
        yield kind.removeprefix("event: "), json.loads(payload.removeprefix("data: "))


def test_sse_sends_model_deltas_and_cards_and_finishes_persisted_reply(connected):
    client, url, bridge, gateway = connected
    gateway.script = [
        ModelTurn(calls=(ToolCall("enterprise.get", {"id": "E002"}),), model="routing-model"),
        ModelTurn(("模型草稿，不应作为业务结果发布。",), model="configured-local"),
    ]
    with client.stream("POST", url, json={"text": "查一查业务记录", "stream": True}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = list(_events(response.read().decode()))
    assert [name for name, _ in events] == ["meta", "tool", "meta", "delta", "card", "done"]
    assert [data["model"] for name, data in events if name == "meta"] == ["routing-model", "configured-local"]
    assert [data["text"] for name, data in events if name == "delta"] == ["查询结果见卡片。"]
    assert events[-2][1]["deepLink"] == {"app": "enterprise", "params": {"entId": "E002"}}
    done = events[-1][1]
    assert (done["messageId"], done["reply"]["content"], done["reply"]["incomplete"]) == (
        events[0][1]["messageId"], "查询结果见卡片。", False,
    )
    assert client.get(url.removesuffix("/messages")).json()["messages"] == [done["user"], done["reply"]]


async def _drive_stream(client, url, text, send, *, spec="2.4", disconnect=None):
    body = json.dumps({"text": text, "stream": True}).encode()
    disconnect = disconnect if disconnect is not None else asyncio.Event()
    body_read = False

    async def receive():
        nonlocal body_read
        if not body_read:
            body_read = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    prepared = client.build_request("POST", url, content=body, headers={"content-type": "application/json"})
    scope = dict(type="http", asgi={"version": "3.0", "spec_version": spec}, http_version="1.1",
                 method="POST", scheme="http", path=url, root_path="", query_string=b"",
                 headers=[(key.lower(), value) for key, value in prepared.headers.raw],
                 client=("127.0.0.1", 12345), server=("testserver", 80))
    await client.app(scope, receive, send)


def test_first_model_delta_reaches_client_before_gateway_finishes(connected):
    client, url, bridge, gateway = connected

    async def run():
        received = asyncio.Event()
        emitted = []

        async def paused_gateway(request, *, on_delta, on_meta, **payload):
            await on_meta("configured-local", None)
            await on_delta("模型首段")
            await asyncio.wait_for(received.wait(), timeout=1)
            await on_delta("及尾段")
            return ModelTurn(route_note="完成后确认路由")

        async def send(message):
            data = message.get("body", b"")
            if data:
                emitted.extend(_events(data.decode()))
            if b"event: delta" in data:
                received.set()

        client.app.state.chat_gateway = paused_gateway
        await _drive_stream(client, url, "你好", send)
        assert [name for name, _ in emitted] == ["meta", "delta", "delta", "done"]
        assert emitted[0][1]["model"] == "configured-local"
        assert emitted[0][1]["routeNote"] is None
        assert emitted[1][1]["text"] == "模型首段"
        assert emitted[-1][1]["reply"]["content"] == "模型首段及尾段"
        assert emitted[-1][1]["reply"]["model"] == "configured-local"
        assert emitted[-1][1]["reply"]["routeNote"] == "完成后确认路由"

    asyncio.run(run())
    assert client.get(url.removesuffix("/messages")).json()["messages"][-1]["content"] == "模型首段及尾段"


def test_gateway_failure_after_first_delta_leaves_message_incomplete(connected):
    client, url, bridge, gateway = connected

    async def broken_gateway(request, *, on_delta, **payload):
        await on_delta("已收到一段")
        raise TimeoutError()

    client.app.state.chat_gateway = broken_gateway
    response = client.post(url, json={"text": "你好", "stream": True})
    events = list(_events(response.text))
    assert [name for name, _ in events] == ["meta", "delta", "error"]
    assert events[-1][1] == {"code": "PROVIDER_ERROR", "message": "模型回复中断，请重试。"}
    assert client.get(url.removesuffix("/messages")).json()["messages"][-1]["incomplete"] is True


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
@pytest.mark.parametrize("last_frame", ["delta", "done"])
def test_sse_disconnect_preserves_last_committed_assistant(connected, spec, last_frame):
    client, url, bridge, gateway = connected
    sent = []

    async def drive_asgi():
        disconnect = asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.start":
                assert message["status"] == 200
            data = message.get("body", b"")
            if data.startswith(f"event: {last_frame}\n".encode()):
                sent.extend(_events(data.decode()))
                if last_frame == "done":
                    history = await asyncio.to_thread(client.get, url.removesuffix("/messages"))
                    assert history.json()["messages"][-1] == sent[-1][1]["reply"]
                disconnect.set()
                if spec == "2.4":
                    raise OSError("fixture closed the socket")
                await asyncio.Future()
            if data:
                sent.extend(_events(data.decode()))

        args = (client, url, "书香里文化能申请哪些支持？", send)
        if spec == "2.4":
            with pytest.raises(ClientDisconnect):
                await _drive_stream(*args, spec=spec, disconnect=disconnect)
        else:
            await _drive_stream(*args, spec=spec, disconnect=disconnect)

    asyncio.run(drive_asgi())
    expected = ["meta", "tool", "delta"] + (["card", "done"] if last_frame == "done" else [])
    assert [name for name, _ in sent] == expected
    assert sent[0][1] == {"messageId": sent[0][1]["messageId"], "model": None, "routeNote": None}
    history = client.get(url.removesuffix("/messages")).json()["messages"]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assistant = history[1]
    assert assistant["role"] == "assistant"
    assert assistant["id"] == sent[0][1]["messageId"]
    if last_frame == "delta":
        assert assistant["incomplete"] is True
        assert assistant["content"] == ""
    else:
        assert assistant == sent[-1][1]["reply"]
        assert assistant["incomplete"] is False


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
def test_sse_done_is_already_observable_in_history_at_send(connected, spec):
    client, url, bridge, gateway = connected
    events = []

    async def send(message):
        if data := message.get("body"):
            events.extend(_events(data.decode()))
            if events[-1][0] == "done":
                assert message["more_body"] is False
                done = events[-1][1]
                history = await asyncio.to_thread(client.get, url.removesuffix("/messages"))
                assert history.json() == {
                    "item": done["conversation"], "messages": [done["user"], done["reply"]],
                }
                assert done["reply"]["incomplete"] is False

    asyncio.run(_drive_stream(client, url, "数据券申报单位须在经开区注册满一年吗", send, spec=spec))
    assert [kind for kind, _ in events] == ["meta", "tool", "delta", "card", "done"]
    assert not gateway.requests


@pytest.mark.parametrize(("failure", "code"), [("delete", "NOT_FOUND"), ("write", "INTERNAL_ERROR")])
def test_sse_persistence_failure_has_error_and_no_done(connected, monkeypatch, failure, code):
    client, url, bridge, gateway = connected
    conversation_url = url.removesuffix("/messages")
    store = client.app.state.conversations
    audit = store._audit
    events = []

    def fail_audit(owner, cid, action, **details):
        if action == "message.complete":
            raise sqlite3.OperationalError("测试事务写入失败")
        audit(owner, cid, action, **details)

    if failure == "write":
        monkeypatch.setattr(store, "_audit", fail_audit)

    async def send(message):
        if data := message.get("body"):
            events.extend(_events(data.decode()))
            if events[-1][0] == "card" and failure == "delete":
                deleted = await asyncio.to_thread(client.delete, conversation_url)
                assert deleted.status_code == 204
            if events[-1][0] == "error":
                assert message["more_body"] is False

    asyncio.run(_drive_stream(client, url, "书香里文化能申请哪些支持？", send))
    assert [kind for kind, _ in events] == ["meta", "tool", "delta", "card", "error"]
    message = "会话或待完成的消息已不存在。" if failure == "delete" else "回复保存失败，请稍后重试。"
    assert events[-1][1] == {"code": code, "message": message}
    if failure == "delete":
        assert client.get(conversation_url).status_code == 404
        assert client.post(f"{conversation_url}/restore").status_code == 200
    assistant = client.get(conversation_url).json()["messages"][-1]
    assert assistant["incomplete"] is True
    assert assistant["content"] == "" and assistant["cards"] == []
    assert not gateway.requests


def test_invalid_and_unauthorized_requests_do_not_write_or_call_tools(connected):
    client, url, bridge, gateway = connected
    unauthenticated = TestClient(client.app)
    response = unauthenticated.post(url, json={"text": "你好", "stream": True})
    assert (response.status_code, response.json()["error"]["code"]) == (401, "UNAUTHENTICATED")
    other = {"username": "other-fixture", "password": PASSWORD}
    assert client.post("/api/admin/users", json={**other, "name": "另一个测试账号"}).status_code == 201
    assert unauthenticated.post("/api/auth/login", json=other).status_code == 200
    response = unauthenticated.post(url, json={"text": "你好"})
    assert (response.status_code, response.json()["error"]["code"]) == (404, "NOT_FOUND")
    response = client.post(url, json={"text": " "})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "CHECK_FAILED")
    response = client.post(url, content=r'{"text":"你好","files":[{"name":"\ud800"}]}',
                           headers={"content-type": "application/json"})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "CHECK_FAILED")
    assert client.get(url.removesuffix("/messages")).json()["messages"] == []
    assert not bridge.calls and not gateway.requests


def test_concurrent_turns_preserve_pairs_and_finalize_independently(tmp_path):
    store = ConversationStore(Store(tmp_path))
    cid = store.create(OWNER)["id"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(lambda text: start_turn(store, OWNER, cid, text, []), ["甲", "乙"])
    finish_turn(store, OWNER, cid, second, {"content": "乙的回复"})
    finish_turn(store, OWNER, cid, first, {"content": "甲的回复"})
    messages = store.detail(OWNER, cid)["messages"]
    observed = {
        (messages[i]["content"], messages[i + 1]["content"], messages[i + 1]["incomplete"])
        for i in range(0, len(messages), 2)
    }
    assert observed == {("甲", "甲的回复", False), ("乙", "乙的回复", False)}
    assert len(store.platform.audit_list("conversations")) == 7

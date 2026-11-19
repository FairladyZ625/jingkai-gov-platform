"""通过实例入口验证告知单、授权和对话编排。"""

import json
from shutil import copyfile

import pytest
from fastapi.testclient import TestClient

from jkq.app import create_app
from jkq.settings import REPO_ROOT

from apps.policy.api.policy_cards import match_card


PREFIX = "/api/apps/policy"
NOTICE = {"entId": "E001", "itemIds": ["RP-001", "RP-006"]}

@pytest.fixture
def policy_client(isolated_platform, reuse_loaded_routers, cheap_password_hash, monkeypatch):
    config, _ = isolated_platform
    for name in ("projects.yaml", "roles.yaml", "users.yaml"):
        copyfile(REPO_ROOT / "config" / name, config / name)
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(REPO_ROOT / "apps"))
    monkeypatch.setenv("HAIKNOW_SECRET", "test-policy-session")
    monkeypatch.delenv("HAIKNOW_DEMO_LOGIN", raising=False)
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    for role in ("admin", "leader", "member", "partner"):
        monkeypatch.setenv(f"JKQ_DEMO_{role.upper()}_PASSWORD", f"test-{role}")

    def make(role="admin"):
        client = TestClient(create_app())
        username = {"admin": "admin", "partner": "hejun"}[role]
        response = client.post("/api/v1/auth/login", json={"username": username, "password": f"test-{role}"})
        assert response.status_code == 200, response.text
        return client

    return make


def test_notice_returns_source_departments_and_document_prefill(policy_client):
    client = policy_client()
    selected = [client.get(f"{PREFIX}/items/{id_}").json()["item"] for id_ in NOTICE["itemIds"]]
    response = client.post(f"{PREFIX}/notice", json=NOTICE)
    assert response.status_code == 200, response.text
    body = response.json()
    for index, item in enumerate(selected, 1):
        section = body["text"].split("\n\n")[index]
        assert section.startswith(f"{index}. {item['title']}\n")
        assert item["rule"]["text"] in section
        assert f"落款：{item['source']['deptResp']}\n咨询电话：请填写" in section
    assert body["text"].count("咨询电话：请填写") == len(selected)
    link = body["deepLink"]
    assert (link["app"], link["route"]) == ("document", "new")
    assert {key: link["params"][key] for key in NOTICE} == NOTICE
    assert link["params"]["templateId"] == "T10"
    assert link["params"]["inputs"]["ent"] == NOTICE["entId"]
    assert link["params"]["inputs"]["policy"] == NOTICE["itemIds"][0]
    assert all(item["title"] in link["params"]["inputs"]["issue"] for item in selected)


@pytest.mark.parametrize(("overrides", "status", "code"), [
    ({"itemIds": []}, 400, "INVALID_REQUEST"),
    ({"itemIds": ["PI-03", "missing"]}, 404, "NOT_FOUND"),
    ({"itemIds": [" "]}, 400, "INVALID_REQUEST"),
    ({"itemIds": "PI-03"}, 400, "INVALID_REQUEST"),
    ({"entId": "missing"}, 404, "NOT_FOUND"),
])
def test_invalid_notice_requests(policy_client, overrides, status, code):
    response = policy_client().post(f"{PREFIX}/notice", json={**NOTICE, **overrides})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_view_only_role_can_read_items_and_cannot_generate_notice(policy_client):
    client = policy_client("partner")
    assert client.get(f"{PREFIX}/items").status_code == 200
    assert client.post(f"{PREFIX}/tools/match", json={"entId": "E001"}).status_code == 403
    for item_ids in (NOTICE["itemIds"], []):
        response = client.post(f"{PREFIX}/notice", json={**NOTICE, "itemIds": item_ids})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert response.json()["error"]["details"] == {"app": "policy", "need": "operate"}


def test_notice_deduplicates_selected_items_in_input_order(policy_client):
    client = policy_client()
    response = client.post(f"{PREFIX}/notice", json={
        "entId": NOTICE["entId"], "itemIds": ["RP-006", "PI-03", "RP-006"],
    })
    assert response.status_code == 200
    result = response.json()
    assert result["deepLink"]["params"]["itemIds"] == ["RP-006", "PI-03"]
    assert result["text"].count("咨询电话：请填写") == 2


def test_tools_emit_cards_from_actual_catalog_and_matcher(policy_client):
    client = policy_client()
    args = {"entId": "E001"}
    full = client.post(f"{PREFIX}/match", json=args).json()["results"]
    assert len(full) > 5
    result = client.post(f"{PREFIX}/tools/match", json=args)
    assert result.status_code == 200
    assert result.json()["cards"] == [match_card("E001", full)]

    response = client.get(f"{PREFIX}/tools/search", params={"q": "PI-03"})
    assert response.status_code == 200
    card, = response.json()["cards"]
    assert card["type"] == "policy-items"
    assert "PI-03" in card["ids"]
    assert {
        "app": "policy", "route": "detail", "params": {"tab": "library", "itemId": "PI-03"},
    } in card["deepLinks"]


def _send(client, text):
    conversation = client.post("/api/v1/conversations", json={"title": "政策验收"})
    assert conversation.status_code == 200, conversation.text
    cid = conversation.json()["item"]["id"]
    result = client.post(f"/api/v1/conversations/{cid}/messages", json={"text": text})
    assert result.status_code == 200, result.text
    return result.json()["reply"]


@pytest.mark.parametrize(("utterance", "ent_id"), [
    ("看看书香里文化能申请什么", "E001"),
    ("看看纸鹿二号智驾能申请什么？", "E002"),
    ("书香里文化能申请哪些支持？", "E001"),
])
def test_real_conversation_returns_policy_match_card(policy_client, utterance, ent_id):
    client = policy_client()
    reply = _send(client, utterance)
    assert reply["toolCalls"] == [{"tool": "policy.match", "args": {"entId": ent_id}, "status": "ok"}]
    card, = reply["cards"]
    assert card["type"] == "policy-match"
    assert card["entId"] == ent_id
    assert card["deepLink"] == {"app": "policy", "params": {"entId": ent_id}}
    assert len(card["results"]) == 5


def test_real_conversation_search_returns_items_card_link(policy_client):
    reply = _send(policy_client(), "搜索政策事项 RP-006")
    card, = reply["cards"]
    assert card["type"] == "policy-items"
    assert card["ids"] == ["RP-006"]
    assert card["deepLink"] == {"app": "policy", "params": {"tab": "library", "itemId": "RP-006"}}


def test_real_conversation_generates_notice_for_explicit_selection(policy_client):
    reply = _send(policy_client(), "给书香里生成告知单 RP-001、RP-006")
    assert reply["toolCalls"] == [{"tool": "policy.notice", "args": NOTICE, "status": "ok"}]
    assert reply["content"].count("咨询电话：请填写") == 2
    assert "政策兑现一次性告知单" in reply["content"]


def test_real_conversation_needs_selection_before_generating_notice(policy_client):
    reply = _send(policy_client(), "给书香里生成告知单")
    assert reply["content"] == "请提供要写入告知单的政策事项编号。"


def test_view_only_role_does_not_receive_company_match_card(policy_client):
    reply = _send(policy_client("partner"), "书香里文化能申请哪些支持")
    assert reply["cards"] == []
    assert reply["toolCalls"][0]["status"] == "error"


def test_policy_wiring_registers_one_messages_route(policy_client):
    client = policy_client()

    def message_routes(router):
        for route in router.routes:
            if nested := getattr(route, "original_router", None):
                yield from message_routes(nested)
            elif (getattr(route, "path", None) == "/api/v1/conversations/{cid}/messages"
                  and "POST" in route.methods):
                yield route

    assert len(list(message_routes(client.app.router))) == 1


def test_policy_gateway_preserves_other_gateway_and_stream_contract():
    import asyncio
    from apps.policy.instance import policy_gateway
    from jkq.orchestrator.ports import ModelTurn

    received = []
    marker = ModelTurn(deltas=("原网关回复",))

    async def fallback(request, **kwargs):
        received.append((request, kwargs))
        return marker

    gateway = policy_gateway(fallback)
    common = dict(tools=["policy.match"], model="offline-model", classification="internal", on_delta=None)
    turn = asyncio.run(gateway(None, messages=[{"role": "user", "content": "看看纸鹿二号智驾能申请什么？"}], **common))
    assert turn.calls[0].args == {"entId": "E002"} and received == []
    turn = asyncio.run(gateway(None, messages=[{"role": "user", "content": "别的应用问题"}], **common))
    assert turn is marker and received[-1][1]["on_delta"] is None
    messages = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "enterprise.get"}}]},
        {"role": "tool", "content": '{"text":"企业结果"}'},
    ]
    assert asyncio.run(gateway(None, messages=messages, **common)) is marker


def test_policy_gateway_handles_streamed_request_via_common_route(policy_client):
    client = policy_client()
    cid = client.post("/api/v1/conversations", json={"title": "政策流式"}).json()["item"]["id"]
    result = client.post(f"/api/v1/conversations/{cid}/messages", json={
        "text": "看看书香里文化能申请什么", "stream": True,
    })
    assert result.status_code == 200
    events = [block.split("\n", 1) for block in result.text.strip().split("\n\n")]
    parsed = [(kind.removeprefix("event: "), json.loads(data.removeprefix("data: "))) for kind, data in events]
    assert [kind for kind, _ in parsed] == ["meta", "tool", "delta", "card", "done"]
    assert parsed[1][1] == {"tool": "policy.match", "args": {"entId": "E001"}, "status": "ok"}
    assert parsed[3][1]["type"] == "policy-match" and len(parsed[3][1]["results"]) == 5

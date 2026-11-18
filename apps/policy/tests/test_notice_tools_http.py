"""在政策脚手架和事项库就绪后验证 HTTP、角色与工具桥。"""

import json
from pathlib import Path

import pytest

from apps.policy.api.policy_cards import match_card


APP_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/apps/policy"
NOTICE = {"entId": "E001", "itemIds": ["RP-001", "RP-006"]}

pytestmark = pytest.mark.skipif(
    not all((APP_DIR / file).is_file() for file in ("app.json", "api/router.py", "api/policy_routes.py")),
    reason="等待 #29 应用脚手架与 #30 政策目录进入主线",
)


@pytest.fixture
def policy_client(make_client, isolated_platform):
    config, _ = isolated_platform
    path = config / "users.yaml"
    users = json.loads(path.read_text())
    users["users"].append({"id": "partner", "name": "测试协作者", "roles": ["partner"], "projects": []})
    path.write_text(json.dumps(users), encoding="utf-8")
    def make(user="sampleadmin", *, configure=None):
        client = make_client(APP_DIR.parent)
        if configure:
            configure(client.app)
        assert client.post("/api/auth/login", json={"user_id": user}).status_code == 200
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


def test_platform_tool_bridge_registers_and_dispatches_policy_tools(policy_client):
    apps_bridge = pytest.importorskip("jkq.apps_bridge")
    from fastapi import Request
    from haiknow_core.main import current_user

    def configure(app):
        bridge = apps_bridge.install(app, current_user)

        # #22 届时在同一登录请求内调用此入口。这里验证工具桥的对话入口。
        @app.post("/tests/policy-tool-from-chat")
        async def call_from_chat(request: Request, body: dict):
            return await bridge.call_from_chat(request, "policy", body["tool"], body["args"])

    client = policy_client(configure=configure)
    tool_list = client.get("/api/v1/tools").json()["items"]
    assert {tool["name"] for tool in tool_list if tool["app"] == "policy"} >= {
        "policy.match", "policy.notice", "policy.search",
    }
    assert client.get("/api/v1/apps/policy").json()["chatCards"] == ["policy-match", "policy-items"]
    match = client.post("/tests/policy-tool-from-chat", json={"tool": "match", "args": {"entId": "E001"}})
    assert match.status_code == 200, match.text
    assert match.json()["result"]["cards"][0]["type"] == "policy-match"
    notice = client.post("/tests/policy-tool-from-chat", json={"tool": "notice", "args": NOTICE})
    assert notice.status_code == 200, notice.text
    assert notice.json()["result"]["deepLink"]["params"]["templateId"] == "T10"

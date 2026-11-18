"""技能运行时的纯逻辑、真实 HTTP 与 core 持久队列回归。"""

import json
import time

import pytest

from jkq.skills.drafting import draft, match
from jkq.skills.runtime import execute, prepare_skill
from jkq.skills.runtime_provider import MockSkillProvider
from jkq.skills.spec import SkillError, validate_spec

ROOT = "/api/v1/skills"
SPEC = {
    "triggers": ["整理资料"],
    "inputs": [
        {"key": "ent", "label": "企业名称", "required": True},
        {"key": "count", "label": "数量", "required": True},
        {"key": "flag", "label": "是否补充", "required": True},
    ],
    "steps": [
        {"type": "kb", "space": "policy", "query": "公开样例"},
        {"type": "model"},
        {"type": "tool", "tool": "enterprise.get", "args": {"id": "{{ent}}", "count": "{{count}}"}},
    ],
    "output": {"title": "{{ent}}资料"},
    "tools": ["enterprise.get"],
}
SKILL = {"name": "资料整理", "spec": SPEC}
INPUTS = {"ent": "示例企业", "count": 0, "flag": False}
HIT = {"id": "doc-1", "title": "公开样例文件", "snippet": "样例条款", "space": "policy"}


class RecordingProvider(MockSkillProvider):
    def __init__(self):
        self.calls = []

    def search(self, user, params):
        self.calls.append(("kb", user.id, params))
        return {"hits": [HIT]}

    def generate(self, user, model, request):
        self.calls.append(("model", user.id, request))
        return {"model": model, "markdown": "结论可查 [1]"}

    def tool(self, user, name, args, idempotency_key):
        self.calls.append(("tool", user.id, name, args, idempotency_key))
        return {"result": "已读取样例"}


@pytest.mark.parametrize("tools,tool", [
    ([], "enterprise.get"), (["policy.match"], "enterprise.get"),
    (["unregistered"], "unregistered"), (["enterprise.get"], "unregistered"),
])
def test_tool_allowlist(tools, tool):
    spec = {"tools": tools, "steps": [{"type": "tool", "tool": tool}]}
    with pytest.raises(SkillError) as error:
        prepare_skill({"name": "校验工具", "spec": spec})
    assert (error.value.status, error.value.error["code"]) == (403, "TOOL_NOT_ALLOWED")


def test_legacy_tool_step_is_a_declaration():
    spec = {"steps": [{"type": "tool", "tool": "meeting.list"}]}
    assert prepare_skill({"name": "旧版技能", "spec": spec})["spec"]["steps"] == spec["steps"]


def test_mock_draft_is_valid_and_match_only_uses_nonempty_triggers():
    provider = MockSkillProvider()
    result = draft(provider, None, "帮我做个技能：整理资料表格")
    assert result["name"] == "整理资料表格"
    assert result["summary"] and result["questions"]
    assert result["spec"] == validate_spec(result["spec"])
    assert result["spec"]["output"]["format"] == "表格"
    candidate = {"id": "one", **result}
    blank = {"id": "two", "spec": {"triggers": [" "]}}
    assert match("请运行整理资料表格", [blank, candidate])["items"] == [candidate]
    assert match("仅有无关内容", [blank, candidate]) == {"items": [], "skill": None, "score": 0}


def test_required_bindings_preserve_zero_and_false_and_skip_missing_tool_argument():
    from types import SimpleNamespace

    class Steps:
        def step(self, name, run):
            return run(name)

    provider = RecordingProvider()
    result = execute(Steps(), prepare_skill(SKILL), {**INPUTS, "ent": "  "},
                     SimpleNamespace(id="operator"), provider, lambda: None)
    assert result["missing"] == ["ent"]
    assert result["title"] == "待确认资料"
    assert "- 企业名称：**待确认**" in result["markdown"]
    assert result["citations"] == [{**HIT, "n": 1}]
    assert [call[0] for call in provider.calls] == ["kb", "model"]
    assert provider.calls[-1][2]["inputs"] == {"count": 0, "flag": False}


@pytest.fixture
def api_factory(request):
    pytest.importorskip("fastapi")
    from haiknow_core.main import current_user
    from jkq.skills.api import install as install_crud
    from jkq.skills.runtime_api import install

    config, _ = request.getfixturevalue("isolated_platform")
    roles = config / "roles.yaml"
    role_doc = json.loads(roles.read_text())
    for role, actions in (("sampleoperator", ["view", "operate"]), ("sampleextra", ["view", "operate"]),
                          ("sampleobserver", ["view"])):
        role_doc["roles"][role] = {"grants": {"skills": actions}}
    roles.write_text(json.dumps(role_doc))
    make_client = request.getfixturevalue("make_client")

    def connect(provider=None):
        client = make_client()
        install_crud(client.app, current_user)
        install(client.app, current_user, provider=provider)
        return client

    return connect


def login(api, user="sampleoperator"):
    assert api.post("/api/auth/login", json={"user_id": user}).status_code == 200


def error(response, status, code):
    assert response.status_code == status, response.text
    payload = response.json()["error"]
    assert payload["code"] == code and payload["message"] and isinstance(payload["details"], dict)


def create(api, skill=SKILL):
    response = api.post(ROOT, json=skill)
    assert response.status_code == 200, response.text
    return response.json()["item"]["id"]


def poll(api, job_id, expected="done"):
    for _ in range(150):
        response = api.get(f"{ROOT}/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()["job"]
        if job["status"] != "running":
            assert job["status"] == expected, job
            return job
        time.sleep(0.02)
    pytest.fail("任务未进入终态")


def test_run_uses_real_queue_checkpoints_for_order_and_idempotency(api_factory):
    provider = RecordingProvider()
    with api_factory(provider) as api:
        login(api)
        path = f"{ROOT}/{create(api)}/run"
        headers = {"Idempotency-Key": "first-run"}
        response = api.post(path, json={"inputs": INPUTS}, headers=headers)
        assert response.status_code == 202, response.text
        submitted = response.json()["job"]
        assert submitted["status"] == "running" and submitted["trial"] is False
        job_id = submitted["id"]
        job = poll(api, job_id)
        again = api.post(path, json={"inputs": INPUTS}, headers=headers).json()["job"]
        assert again["id"] == job_id and again["status"] == "done"
        error(api.post(path, json={"inputs": {}}, headers=headers), 409, "INVALID_STATE")
        assert [step["type"] for step in job["steps"]] == ["kb", "model", "tool"]
        assert all(step["status"] == "done" for step in job["steps"])
        assert [call[0] for call in provider.calls] == ["kb", "model", "tool"]
        assert provider.calls[0] == ("kb", "sampleoperator", {"q": "公开样例", "space": "policy", "limit": 4})
        assert provider.calls[1][2]["prior"] == [{"type": "kb", "result": {"hits": [HIT]}}]
        assert provider.calls[2] == ("tool", "sampleoperator", "enterprise.get",
                                     {"id": "示例企业", "count": 0}, f"{job_id}:3:tool")
        assert job["result"]["citations"] == [{**HIT, "n": 1}]
        assert "已读取样例" in job["result"]["markdown"]
        assert job["result"]["missing"] == []

    with api_factory() as reopened:
        login(reopened)
        assert poll(reopened, job_id) == job
        login(reopened, "sampleextra")
        error(reopened.get(f"{ROOT}/jobs/{job_id}"), 404, "NOT_FOUND")


def test_trial_keeps_skill_count_and_reports_missing_fields(api_factory):
    with api_factory() as api:
        login(api)
        create(api)
        before = api.get(ROOT).json()["items"]
        response = api.post(f"{ROOT}/trial", json={"skill": SKILL, "inputs": {"ent": " "}})
        assert response.status_code == 202, response.text
        job = poll(api, response.json()["job"]["id"])
        assert job["trial"] is True
        assert job["result"]["missing"] == ["ent", "count", "flag"]
        assert job["result"]["title"] == "待确认资料"
        assert "**待确认**" in job["result"]["markdown"] and job["result"]["citations"] == []
        assert api.get(ROOT).json()["items"] == before


def test_run_and_trial_reject_undeclared_tools_before_any_step(api_factory):
    provider = RecordingProvider()
    skill = {**SKILL, "spec": {**SPEC, "tools": []}}
    with api_factory(provider) as api:
        login(api)
        for path, payload in ((f"{ROOT}/{create(api, skill)}/run", {"inputs": INPUTS}),
                              (f"{ROOT}/trial", {"skill": skill, "inputs": INPUTS})):
            error(api.post(path, json=payload), 403, "TOOL_NOT_ALLOWED")
        assert provider.calls == []


def test_draft_contract_and_invalid_model_output(api_factory):
    class InvalidDraft(MockSkillProvider):
        def draft(self, user, prompt, text, knowledge):
            result = super().draft(user, prompt, text, knowledge)
            result["spec"]["steps"] = [{"type": "unknown"}]
            return result

    with api_factory() as api:
        login(api)
        response = api.post(f"{ROOT}/draft", json={"text": "整理事项清单"})
        assert response.status_code == 200, response.text
        result = response.json()["draft"]
        assert result["name"] and result["summary"] and result["questions"]
        assert result["spec"] == validate_spec(result["spec"])
        assert api.get(ROOT).json()["items"] == []
        error(api.post(f"{ROOT}/draft", json={"text": "  "}), 400, "INVALID_REQUEST")
    with api_factory(InvalidDraft()) as api:
        login(api)
        error(api.post(f"{ROOT}/draft", json={"text": "整理事项清单"}), 502, "INVALID_SKILL_DRAFT")


def test_match_respects_published_visibility_and_unavailable_endpoints(api_factory):
    with api_factory() as api:
        error(api.post(f"{ROOT}/match", json={"text": "整理资料"}), 401, "UNAUTHENTICATED")
        login(api)
        sid = create(api)
        create(api)
        assert api.post(f"{ROOT}/match", json={"text": "整理资料"}).json()["items"] == []
        skills = api.app.state.skills
        user = skills.platform.directory.user("sampleoperator")
        skills.save(user, skills.load(user, sid), {"status": "published", "share": {
            "scope": "people", "people": ["sampleextra"], "perm": "use",
        }})
        login(api, "sampleextra")
        response = api.post(f"{ROOT}/match", json={"text": "请帮我整理资料"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [item["id"] for item in payload["items"]] == [sid]
        assert payload["skill"]["id"] == sid
        assert api.post(f"{ROOT}/match", json={"text": "无匹配"}).json()["items"] == []
        assert api.post(f"{ROOT}/match", json={"text": "  "}).json()["items"] == []
        error(api.get(f"{ROOT}/{sid}/manifest"), 501, "NOT_IMPLEMENTED")
        error(api.post(f"{ROOT}/{sid}/promote", json={}), 501, "NOT_IMPLEMENTED")
        login(api, "sampleobserver")
        assert api.post(f"{ROOT}/match", json={"text": "整理资料"}).json()["items"] == []
        error(api.post(f"{ROOT}/{sid}/run", json={"inputs": INPUTS}), 403, "FORBIDDEN")

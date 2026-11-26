"""技能运行时的纯逻辑、真实 HTTP 与 core 持久队列回归。"""

import json
import re
import time

import pytest

from jkq.skills.drafting import draft, match
from jkq.skills.runtime import execute, prepare_skill
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


class SampleSkillProvider:
    def require_sources(self, user, hits, tools=()):
        pass

    def search(self, user, params):
        return {"hits": [], "total": 0, "terms": [], "facets": {}}

    def ask(self, user, params):
        return {"answer": "未找到可以引用的知识库片段。", "confidence": "none", "citations": []}

    def draft(self, user, prompt, text, knowledge):
        name = re.sub(r"^(?:帮我|请)?(?:做|创建|制作)(?:一个|个)?技能[：:，,\s]*", "", text)
        name = name.strip("。！?？ ")[:24] or "知识整理助手"
        format_name = "要点"
        for keyword, output in (("表格", "表格"), ("清单", "清单"), ("公文", "公文")):
            if keyword in text:
                format_name = output
                break
        return {
            "name": name,
            "summary": text,
            "spec": {
                "triggers": [name],
                "inputs": [{"key": "materials", "label": "已有材料", "type": "textarea", "required": True}],
                "steps": [{"type": "kb", "query": name}, {"type": "model"}],
                "output": {"title": name, "format": format_name},
                "prompt": f"{text}\n已有材料：{{{{materials}}}}\n请写结论与出处，缺项标为待确认。",
            },
            "questions": ["可以提供哪些输入材料？", "结果要依据哪个知识库？"],
        }

    def generate(self, user, model, request):
        # 样例 provider 只展示收到的材料，不编造业务判断或知识库依据。
        details = [(field, " ".join(str(value).splitlines())) for field, value in request["inputs"].items()]
        format_name = request["format"]
        if format_name == "表格":
            rows = ["| 字段 | 内容 |", "| --- | --- |"]
            for field, value in details or [("已有材料", "待确认")]:
                cell = value.replace("\\", "\\\\").replace("|", r"\|")
                rows.append(f"| {field} | {cell} |")
            markdown = "\n".join(rows)
        elif format_name == "清单":
            markdown = "\n".join(f"- [ ] {field}：{value}" for field, value in details) or "- [ ] 已有材料：待确认"
        elif format_name == "公文":
            paragraphs = "\n\n".join(f"**{field}**：{value}" for field, value in details) or "已有材料待确认。"
            markdown = f"#### 一、已有材料\n\n{paragraphs}"
        else:
            markdown = "\n".join(f"- {field}：{value}" for field, value in details) or "缺少可用于形成结论的输入。"
        return {"model": model, "markdown": markdown}

    def tool(self, user, name, args, idempotency_key):
        return {"note": f"{name} 尚未接入业务工具桥，未执行实际业务操作。"}


class RecordingProvider(SampleSkillProvider):
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
    provider = SampleSkillProvider()
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
        install(client.app, current_user, provider=provider if provider is not None else SampleSkillProvider())
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


@pytest.mark.parametrize("trial", [False, True], ids=["saved", "trial"])
def test_job_result_is_only_visible_to_submitter(api_factory, trial):
    with api_factory(RecordingProvider()) as api:
        login(api)
        sid = create(api)
        path = f"{ROOT}/trial" if trial else f"{ROOT}/{sid}/run"
        body = {"inputs": INPUTS, "skill": SKILL} if trial else {"inputs": INPUTS}
        response = api.post(path, json=body)
        assert response.status_code == 202, response.text
        job_id = response.json()["job"]["id"]
        result = poll(api, job_id)["result"]
        assert result["citations"] == [{**HIT, "n": 1}]
        assert HIT["snippet"] in result["markdown"]

        login(api, "sampleadmin")
        # 管理员能访问技能本身，但另一个用户的任务应与不存在的任务一致。
        assert api.get(f"{ROOT}/{sid}").status_code == 200
        for reader in ("sampleadmin", "sampleextra", "sampleoutsider"):
            login(api, reader)
            denied = api.get(f"{ROOT}/jobs/{job_id}")
            error(denied, 404, "NOT_FOUND")
            assert denied.json() == api.get(f"{ROOT}/jobs/missing-job").json()


@pytest.mark.parametrize("policy,minutes", [("政策库", "会议纪要"), ("policy", "minutes")])
def test_prototype_kb_steps_send_standard_space_ids(api_factory, policy, minutes):
    provider = RecordingProvider()
    skill = {"name": "检索示例", "spec": {"steps": [
        {"type": "kb", "query": "实体书店 房租 成本奖励", "space": policy, "label": "查政策原文"},
        {"type": "kb", "query": "会议纪要 待办", "space": minutes, "label": "查纪要原文"},
    ]}}
    with api_factory(provider) as api:
        login(api)
        response = api.post(f"{ROOT}/trial", json={"skill": skill})
        assert response.status_code == 202, response.text
        poll(api, response.json()["job"]["id"])
        assert [call[2] for call in provider.calls] == [
            {"q": "实体书店 房租 成本奖励", "space": "policy", "limit": 4},
            {"q": "会议纪要 待办", "space": "minutes", "limit": 4},
        ]


@pytest.mark.parametrize("space", ["未知空间", "unknown", ""])
def test_unknown_kb_space_is_rejected_before_queueing(api_factory, space):
    provider = RecordingProvider()
    skill = {"name": "检索示例", "spec": {"steps": [
        {"type": "kb", "space": space, "query": "{{missing}}"},
    ]}}
    with api_factory(provider) as api:
        login(api)
        sid = create(api, skill)
        error(api.post(f"{ROOT}/{sid}/run", json={}), 400, "INVALID_REQUEST")
        error(api.post(f"{ROOT}/trial", json={"skill": skill}), 400, "INVALID_REQUEST")
        assert provider.calls == []


@pytest.mark.parametrize("keyword,format_name,expected", [
    ("", "要点", "- materials：公开样例 😀"),
    ("表格", "表格", "| 字段 | 内容 |\n| --- | --- |\n| materials | 公开样例 😀 \\| 第二行 |"),
    ("清单", "清单", "- [ ] materials：公开样例 😀"),
    ("公文", "公文", "#### 一、已有材料\n\n**materials**：公开样例 😀"),
], ids=["bullets", "table", "checklist", "document"])
def test_draft_to_trial_renders_requested_markdown(api_factory, keyword, format_name, expected):
    with api_factory() as api:
        login(api)
        text = f"整理资料{keyword} 😀"
        drafted = api.post(f"{ROOT}/draft", json={"text": text})
        assert drafted.status_code == 200, drafted.text
        skill = drafted.json()["draft"]
        assert skill["name"] == text
        assert skill["spec"]["output"]["format"] == format_name
        materials = "公开样例 😀 |\n第二行" if format_name == "表格" else "公开样例 😀"
        response = api.post(f"{ROOT}/trial", json={"skill": skill, "inputs": {"materials": materials}})
        assert response.status_code == 202, response.text
        result = poll(api, response.json()["job"]["id"])["result"]
        assert result["markdown"] == f"### {text}\n\n{expected}"


@pytest.mark.parametrize("path,body", [
    ("trial", {"skill": {**SKILL, "name": "技能\ud800"}}),
    ("{sid}/run", {"inputs": {"ent": [{"材料": "\udfff"}]}}),
    ("trial", {"skill": SKILL, "inputs": {"ent": [{"\ud800": "材料"}]}}),
    ("draft", {"text": "整理资料\udfff"}),
], ids=["skill-name", "nested-value", "nested-key", "draft-text"])
def test_invalid_unicode_in_run_trial_and_draft_returns_400(api_factory, path, body):
    class NoDraftCalls(SampleSkillProvider):
        def ask(self, user, params):
            pytest.fail("不可编码的文本不应进入起草 provider")

    with api_factory(NoDraftCalls()) as api:
        login(api)
        sid = create(api)
        # JSON 允许传入转义序列供服务端解析，构造请求时保留该序列。
        response = api.post(f"{ROOT}/{path.format(sid=sid)}", content=json.dumps(body),
                            headers={"Content-Type": "application/json"})
        error(response, 400, "INVALID_REQUEST")


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
    class InvalidDraft(SampleSkillProvider):
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


PUBLIC_QUERY = "算力券 封顶"
PUBLIC_SOURCE = "KB-P3950424"


@pytest.fixture
def instance(isolated_platform, cheap_password_hash, monkeypatch, request):
    pytest.importorskip("fastapi")
    import os
    import secrets
    from pathlib import Path

    from fastapi.testclient import TestClient

    from jkq.app import create_app

    repo = Path(__file__).resolve().parents[2]
    password = secrets.token_urlsafe(12)
    for name in ("HAIKNOW_ROOT", "JKQ_WEB_DIR", "JKQ_MOCK_GOV_URL", "JKQ_KB_VECTOR_SEARCH"):
        monkeypatch.delenv(name, raising=False)
    for name in tuple(os.environ):
        if name.startswith(("JKQ_CLOUD_MODEL_", "JKQ_DEEPSEEK_MODEL_", "JKQ_LOCAL_BACKUP_MODEL_",
                            "JKQ_LOCAL_MODEL_", "JKQ_OVERSEAS_MODEL_")):
            monkeypatch.delenv(name)
    for name in ("ADMIN", "LEADER", "MEMBER", "PARTNER"):
        monkeypatch.setenv(f"JKQ_DEMO_{name}_PASSWORD", password)
    deployment = getattr(request, "param", "local")
    assert deployment in {"local", "cloud", "local-and-cloud", "unapproved-local-and-cloud"}
    if deployment != "cloud":
        base = "http://127.0.0.1:18000/v1"
        monkeypatch.setenv("JKQ_LOCAL_MODEL_BASE_URL", base)
        if deployment != "unapproved-local-and-cloud":
            monkeypatch.setenv("JKQ_LOCAL_MODEL_CONFIDENTIAL_BASE_URL", base)
        monkeypatch.setenv("JKQ_LOCAL_MODEL_NAME", "acceptance-local")
    if deployment != "local":
        monkeypatch.setenv("JKQ_CLOUD_MODEL_BASE_URL", "https://skill-cloud.example.invalid/v1")
        monkeypatch.setenv("JKQ_CLOUD_MODEL_NAME", "acceptance-cloud")
        monkeypatch.setenv("JKQ_CLOUD_MODEL_API_KEY", "test-only")
    monkeypatch.setenv("JKQ_MODEL_PROVIDER", "cloud" if deployment == "cloud" else "local")
    monkeypatch.setenv("JKQ_DEMO_MODE", "1")
    monkeypatch.setenv("HAIKNOW_DEMO_LOGIN", "0")
    monkeypatch.setenv("HAIKNOW_SECRET", password)
    monkeypatch.setenv("HAIKNOW_CONFIG_DIR", str(repo / "config"))
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(repo / "apps"))
    with TestClient(create_app()) as api:
        def sign_in(username="wangmin"):
            response = api.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert response.status_code == 200, response.text

        yield api, sign_in


def model_transport(api, reply):
    import httpx

    calls = []

    def upstream(request):
        body = json.loads(request.content)
        assert body["model"] == "acceptance-local"
        assert request.url.path == "/v1/chat/completions"
        data = json.loads(body["messages"][-1]["content"])
        calls.append(data)
        content = reply(data)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    api.app.state.jkq_models.transport = httpx.MockTransport(upstream)
    return calls


def test_instance_run_executes_real_kb_then_configured_model_then_business_tool(instance):
    api, sign_in = instance
    error(api.get(ROOT), 401, "UNAUTHENTICATED")
    sign_in()
    meeting = api.post("/api/apps/meeting/workbench/meetings", json={
        "title": "公开演练会议概要", "date": "2026-11-26",
    })
    assert meeting.status_code == 201, meeting.text
    draft_skill = {
        "name": "知识库与会议汇总",
        "spec": {"triggers": ["汇总公开材料"], "tools": ["meeting.list"],
                 "inputs": [{"key": "scope", "label": "核查范围", "required": True}],
                 "steps": [{"type": "kb", "space": "policy", "query": PUBLIC_QUERY},
                           {"type": "model"}, {"type": "tool", "tool": "meeting.list"}]},
    }
    calls = model_transport(api, lambda payload: "可查阅公开政策依据 [1]。")
    sid = create(api, draft_skill)
    accepted = api.post(f"{ROOT}/{sid}/run", json={"inputs": {"unused": "输入隐私标记"}})
    assert accepted.status_code == 202, accepted.text
    job = poll(api, accepted.json()["job"]["id"])
    assert [step["status"] for step in job["steps"]] == ["done", "done", "done"]
    result = job["result"]
    assert result["model"] == "acceptance-local"
    assert result["missing"] == ["scope"]
    assert "核查范围：**待确认**" in result["markdown"]
    for value in ("可查阅公开政策依据", "公开演练会议概要", meeting.json()["item"]["id"]):
        assert value in result["markdown"]
    assert result["citations"][0]["id"] == PUBLIC_SOURCE
    assert [step["type"] for step in calls[0]["prior"]] == ["kb"]
    assert calls[0]["prior"][0]["result"]["hits"][0]["id"] == PUBLIC_SOURCE

    # 管理审计实际读取平台库。普通提交人只有任务详情权限。
    audit_path = "/api/v1/audit?app=skills"
    error(api.get(audit_path), 403, "FORBIDDEN")
    sign_in("admin")
    error(api.get(f"{ROOT}/jobs/{job['id']}"), 404, "NOT_FOUND")
    audit = api.get(audit_path)
    assert audit.status_code == 200, audit.text
    entries = audit.json()["items"]
    recorded = [row for row in reversed(entries) if row["detail"].get("jobId") == job["id"]]
    assert [row["action"] for row in recorded] == [
        "job.submit", "job.running", *["job.step.running", "job.step.done"] * 3, "job.done",
    ]
    assert all(row["userId"] == "u-wangmin" and set(row["detail"]) == {"jobId", "attempt"} for row in recorded)
    assert any(row["action"] == "ai.chat" and row["detail"]["model"] == "acceptance-local" for row in entries)
    assert any(row["action"] == "skill.tool" and row["detail"] == {"tool": "meeting.list"} for row in entries)
    assert all(marker not in audit.text for marker in ("输入隐私标记", "公开演练会议概要", PUBLIC_SOURCE))


def test_instance_tools_preserve_original_permissions_and_masking(instance):
    api, sign_in = instance
    sign_in()
    company = api.post("/api/v1/apps/enterprise/records", json={
        "project": "jkq", "type": "enterprise.company",
        "data": {"item": {"name": "公开演练企业", "contact": "联系人脱敏标记"}},
    })
    assert company.status_code == 201, company.text
    skill = {"name": "企业信息与政策匹配", "spec": {"steps": [
        {"type": "tool", "tool": "enterprise.get", "args": {"id": company.json()["id"]}},
        {"type": "tool", "tool": "policy.match", "args": {"entId": "E002"}},
    ]}}
    body, headers = {"skill": skill}, {"Idempotency-Key": "apps-check"}
    accepted = api.post(f"{ROOT}/trial", json=body, headers=headers)
    assert accepted.status_code == 202, accepted.text
    job = poll(api, accepted.json()["job"]["id"])
    assert [step["status"] for step in job["steps"]] == ["done", "done"]
    assert "公开演练企业" in job["result"]["markdown"]
    assert "联系人脱敏标记" not in job["result"]["markdown"]
    assert "匹配兑现事项" in job["result"]["markdown"] or '"results"' in job["result"]["markdown"]

    assert api.put("/api/v1/me/role", json={"role": "partner"}).status_code == 200
    error(api.get(f"{ROOT}/jobs/{job['id']}"), 403, "FORBIDDEN")
    error(api.post(f"{ROOT}/trial", json=body, headers=headers), 403, "FORBIDDEN")


@pytest.mark.parametrize("mode,revocation", [
    ("run", "grant"), ("trial", "grant"), ("run", "document"), ("trial", "document"),
])
def test_instance_rechecks_source_on_poll_and_idempotent_replay(instance, mode, revocation):
    api, sign_in = instance
    sign_in()
    skill = {"name": "公开资料查找", "spec": {"steps": [
        {"type": "kb", "space": "policy", "query": PUBLIC_QUERY},
    ]}}
    path, body = (f"{ROOT}/{create(api, skill)}/run", {}) if mode == "run" else (
        f"{ROOT}/trial", {"skill": skill},
    )
    before = api.get(ROOT).json()["items"]
    headers = {"Idempotency-Key": "source-check"}
    accepted = api.post(path, json=body, headers=headers)
    assert accepted.status_code == 202, accepted.text
    jid = accepted.json()["job"]["id"]
    result = poll(api, jid)["result"]
    citation = result["citations"][0]
    assert citation["id"] == PUBLIC_SOURCE and citation["snippet"] in result["markdown"]
    assert api.post(path, json=body, headers=headers).json()["job"]["id"] == jid
    assert api.get(ROOT).json()["items"] == before

    if revocation == "document":
        response = api.delete(f"/api/v1/kb/docs/{PUBLIC_SOURCE}")
        assert response.status_code == 200, response.text
    else:
        store = api.app.state.platform.store
        with store._lock, store._db as db:
            db.execute("delete from role_grants where role_id='member' and app_id='kb'")
        drafted = api.post(f"{ROOT}/draft", json={"text": PUBLIC_QUERY})
        error(drafted, 403, "FORBIDDEN")
        assert drafted.json()["error"]["details"] == {"app": "kb", "need": "view"}
    for response in (api.get(f"{ROOT}/jobs/{jid}"), api.post(path, json=body, headers=headers)):
        error(response, 403, "FORBIDDEN")
        assert citation["snippet"] not in response.text and "result" not in response.json()


def test_instance_draft_consumes_verified_knowledge_and_validates_model_json(instance):
    api, sign_in = instance
    sign_in()
    skill = {"name": "整理算力券依据", "summary": "核对公开政策",
             "spec": {"steps": [{"type": "kb", "space": "policy", "query": PUBLIC_QUERY},
                                {"type": "model"}]},
             "questions": ["要核对哪个申报期？"]}

    def reply(payload):
        if "passages" in payload:
            excerpt = next(sentence for sentence in payload["passages"][0]["sentences"] if "2000万元" in sentence)
            return json.dumps([{"passage": 1, "quote": excerpt}])
        return json.dumps(skill)

    calls = model_transport(api, reply)
    response = api.post(f"{ROOT}/draft", json={"text": PUBLIC_QUERY})
    assert response.status_code == 200, response.text
    drafted = response.json()["draft"]
    assert drafted["name"] == skill["name"] and drafted["summary"] == skill["summary"]
    assert drafted["questions"] == skill["questions"]
    assert drafted["spec"] == validate_spec(skill["spec"])
    assert calls[0]["question"] == PUBLIC_QUERY
    [ref] = calls[1]["knowledge"]["citations"]
    assert ref["id"] == PUBLIC_SOURCE and ref["snippet"] in calls[1]["knowledge"]["answer"]
    assert api.get(ROOT).json()["items"] == []

    model_transport(api, lambda payload: "未按约定返回 JSON")
    error(api.post(f"{ROOT}/draft", json={"text": "💡"}), 502, "INVALID_SKILL_DRAFT")


def test_instance_editor_options_follow_kb_permissions(instance):
    api, sign_in = instance
    path = f"{ROOT}/meta/options"
    error(api.get(path), 401, "UNAUTHENTICATED")
    sign_in("hejun")
    options = api.get(path).json()
    assert set(options["spaces"]) == {"政策库", "policy"}
    models = {item["id"]: item for item in options["models"]}
    assert {"auto", "local", "acceptance-local"} <= models.keys()
    assert models["local"]["local"] and not models["auto"]["local"]
    assert "cloud" not in models
    sign_in()
    assert {"政策库", "policy", "会议纪要", "minutes", "企业档案", "enterprise"} <= set(api.get(path).json()["spaces"])
    store = api.app.state.platform.store
    with store._lock, store._db as db:
        db.execute("delete from role_grants where role_id='member' and app_id='kb'")
    assert api.get(path).json()["spaces"] == []


@pytest.mark.parametrize(("space", "model"), [("政策库", "local"), ("policy", "acceptance-local")])
def test_instance_draft_editor_save_and_trial_after_tool_swap(instance, space, model):
    api, sign_in = instance
    sign_in()
    skill = {
        "name": "政策与业务工具", "summary": "整理公开资料", "questions": [],
        "spec": {"kb": [space], "model": model, "tools": ["meeting.list"],
                 "inputs": [{"key": "ent", "label": "企业", "type": "enterprise", "required": True}],
                 "steps": [{"type": "kb", "space": space, "query": PUBLIC_QUERY},
                           {"type": "model"}, {"type": "tool", "tool": "meeting.list", "args": {}}]},
    }
    calls = model_transport(api, lambda payload: "公开政策与业务结果" if "prior" in payload else json.dumps(skill))
    # 无有效检索词时，起草直接使用无知识库答复，试运行仍查公开材料。
    response = api.post(f"{ROOT}/draft", json={"text": "💡"})
    assert response.status_code == 200, response.text
    drafted = response.json()["draft"]
    assert "tools" not in drafted["spec"]
    options = api.get(f"{ROOT}/meta/options").json()
    spec = drafted["spec"]
    # 编辑器以完全相同的 value 选中原值，再按向导的 autosave 和 trial 请求提交。
    spec["steps"][0]["space"] = next(value for value in options["spaces"] if value == spec["steps"][0]["space"])
    spec["kb"] = [value for value in options["spaces"] if value in spec["kb"]]
    spec["model"] = next(option["id"] for option in options["models"] if option["id"] == spec["model"])
    replacement = next(tool for tool in options["tools"] if tool["id"] == "policy.match")
    spec["steps"][-1].update(tool=replacement["id"], label=replacement["label"], args={"entId": "{{ent}}"})
    inputs = {"ent": "E002"}
    sid = create(api, {key: drafted[key] for key in ("name", "summary", "icon", "base", "spec")})
    saved = api.patch(f"{ROOT}/{sid}", json={key: drafted[key] for key in ("name", "summary", "icon", "spec")})
    assert saved.status_code == 200, saved.text
    assert saved.json()["item"]["spec"] == spec
    before = api.get(ROOT).json()["items"]
    for path, body in ((f"{ROOT}/{sid}/run", {"inputs": inputs}),
                       (f"{ROOT}/trial", {"skill": {"name": drafted["name"], "spec": spec}, "inputs": inputs})):
        accepted = api.post(path, json=body)
        assert accepted.status_code == 202, accepted.text
        job = poll(api, accepted.json()["job"]["id"])
        assert [step["status"] for step in job["steps"]] == ["done", "done", "done"]
        assert job["result"]["citations"][0]["id"] == PUBLIC_SOURCE
        assert job["result"]["model"] == "acceptance-local"
        assert replacement["label"] in job["result"]["markdown"]
    assert api.get(ROOT).json()["items"] == before
    assert len(calls) == 3

    # 显式提交不一致名单仍受原约束，模型返回同样的失配也不能成为草稿。
    inconsistent = {"name": drafted["name"], "spec": {**spec, "tools": ["meeting.list"]}}
    error(api.post(f"{ROOT}/trial", json={"skill": inconsistent, "inputs": inputs}), 403, "TOOL_NOT_ALLOWED")
    bad_sid = create(api, inconsistent)
    error(api.post(f"{ROOT}/{bad_sid}/run", json={"inputs": inputs}), 403, "TOOL_NOT_ALLOWED")
    assert len(calls) == 3
    model_transport(api, lambda payload: json.dumps({**skill, "spec": inconsistent["spec"]}))
    error(api.post(f"{ROOT}/draft", json={"text": "💡"}), 502, "INVALID_SKILL_DRAFT")


@pytest.mark.parametrize("model", ["local", "acceptance-local", "auto", "unknown-acceptance"])
def test_instance_resolves_existing_skill_model_for_run_and_trial(instance, model):
    api, sign_in = instance
    sign_in()
    calls = model_transport(api, lambda payload: "模型路由回执")
    skill = {"name": "模型选择", "spec": {"model": model, "steps": [{"type": "model"}]}}
    sid = create(api, skill)
    known = model != "unknown-acceptance"
    for path, body in ((f"{ROOT}/{sid}/run", {}), (f"{ROOT}/trial", {"skill": skill})):
        accepted = api.post(path, json=body)
        assert accepted.status_code == 202, accepted.text
        job = poll(api, accepted.json()["job"]["id"], expected="done" if known else "failed")
        if known:
            assert job["result"]["model"] == "acceptance-local"
        else:
            assert job["errorCode"] == "NOT_FOUND" and job["result"] is None
    assert len(calls) == (2 if known else 0)


@pytest.mark.parametrize("instance", ["local-and-cloud"], indirect=True)
@pytest.mark.parametrize("operation", ["run", "trial"])
@pytest.mark.parametrize("model", ["local", "acceptance-local", "auto"])
def test_instance_skill_local_failure_routes_by_selection(instance, operation, model):
    import httpx

    api, sign_in = instance
    sign_in()
    options = {item["id"]: item for item in api.get(f"{ROOT}/meta/options").json()["models"]}
    assert options["local"]["local"] and options["acceptance-local"]["local"]
    assert not options["auto"]["local"] and not options["cloud"]["local"]
    assert all(not options[value].get("disabled", False)
               for value in ("local", "acceptance-local", "auto", "cloud", "acceptance-cloud"))
    calls = []
    marker = "合成技能输入，仅用于离线验证"

    def upstream(request):
        payload = json.loads(request.content)
        assert json.loads(payload["messages"][-1]["content"])["inputs"] == {"note": marker}
        calls.append((request.url.host, payload["model"]))
        if request.url.host == "127.0.0.1":
            return httpx.Response(503)
        assert request.url.host == "skill-cloud.example.invalid"
        return httpx.Response(200, json={"choices": [{"message": {"content": "离线云端回执"}}]})

    api.app.state.jkq_models.transport = httpx.MockTransport(upstream)
    skill = {"name": "离线路由", "spec": {"model": model, "steps": [{"type": "model"}],
                                      "inputs": [{"key": "note", "required": True}]}}
    body = {"inputs": {"note": marker}}
    if operation == "run":
        path = f"{ROOT}/{create(api, skill)}/run"
    else:
        path = f"{ROOT}/trial"
        body["skill"] = skill
    accepted = api.post(path, json=body)
    assert accepted.status_code == 202, accepted.text
    auto = model == "auto"
    job = poll(api, accepted.json()["job"]["id"], expected="done" if auto else "failed")
    expected_calls = [("127.0.0.1", "acceptance-local")]
    if auto:
        assert job["result"]["model"] == "acceptance-cloud"
        expected_calls.append(("skill-cloud.example.invalid", "acceptance-cloud"))
    else:
        assert job["errorCode"] == "PROVIDER_ERROR" and job["result"] is None
        assert job["steps"][0]["status"] == "failed"
    assert calls == expected_calls


@pytest.mark.parametrize("instance", ["unapproved-local-and-cloud"], indirect=True)
def test_instance_explicit_unapproved_local_skill_has_no_transport(instance):
    import httpx

    api, sign_in = instance
    sign_in()
    options = {item["id"]: item for item in api.get(f"{ROOT}/meta/options").json()["models"]}
    for value in ("local", "acceptance-local"):
        assert options[value]["disabled"] and not options[value]["local"]
        assert "审批" in options[value]["disabledReason"]
    assert all(not options[value].get("disabled", False)
               for value in ("auto", "cloud", "acceptance-cloud"))
    calls = []

    def record(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={"choices": [{"message": {"content": "合成测试回执"}}]})

    api.app.state.jkq_models.transport = httpx.MockTransport(record)
    for model in ("local", "acceptance-local"):
        skill = {"name": "未获准的本地部署", "spec": {"model": model, "steps": [{"type": "model"}]}}
        response = api.post(f"{ROOT}/trial", json={"skill": skill})
        assert response.status_code == 202, response.text
        job = poll(api, response.json()["job"]["id"], expected="failed")
        assert job["errorCode"] == "OUTBOUND_DENIED" and job["result"] is None
    assert calls == []


def test_instance_permissions_skip_and_unavailable_are_distinct(instance):
    api, sign_in = instance
    sign_in("hejun")
    steps = [{"type": "tool", "tool": "meeting.list"}]
    denied = api.post(f"{ROOT}/trial", json={"skill": {"name": "汇总会议", "spec": {"steps": steps}}})
    assert denied.status_code == 202, denied.text
    job = poll(api, denied.json()["job"]["id"], expected="failed")
    assert job["errorCode"] == "FORBIDDEN" and job["result"] is None
    assert job["steps"][0]["status"] == "failed"
    error(api.post(f"{ROOT}/trial", json={
        "skill": {"name": "汇总会议", "spec": {"steps": steps, "tools": []}},
    }), 403, "TOOL_NOT_ALLOWED")

    sign_in()
    skipped = api.post(f"{ROOT}/trial", json={"skill": {"name": "查企业", "spec": {
        "inputs": [{"key": "ent", "required": True}],
        "steps": [{"type": "tool", "tool": "enterprise.get", "args": {"id": "{{ent}}"}}],
    }}})
    job = poll(api, skipped.json()["job"]["id"])
    assert job["steps"][0]["status"] == "skipped" and job["result"]["missing"] == ["ent"]
    assert "待确认" in job["result"]["markdown"]

    unavailable = api.post(f"{ROOT}/trial", json={
        "skill": {"name": "验证模型缺失", "spec": {"model": "mock", "steps": [{"type": "model"}]}},
    })
    assert unavailable.status_code == 202, unavailable.text
    job = poll(api, unavailable.json()["job"]["id"], expected="failed")
    assert job["errorCode"] == "NOT_CONFIGURED" and job["result"] is None


def test_instance_match_and_deferred_routes(instance):
    api, sign_in = instance
    sign_in()
    sid = create(api)
    path = f"{ROOT}/match"
    assert api.post(path, json={"text": "整理资料"}).json()["items"] == []
    skills = api.app.state.skills
    user = skills.platform.directory.user("u-wangmin")
    skills.save(user, skills.load(user, sid), {"status": "published"})
    assert api.post(path, json={"text": "请整理资料"}).json()["skill"]["id"] == sid
    assert api.post(path, json={"text": "无触发词"}).json() == {"items": [], "skill": None, "score": 0}
    error(api.get(f"{ROOT}/{sid}/manifest"), 501, "NOT_IMPLEMENTED")
    error(api.post(f"{ROOT}/{sid}/promote", json={}), 501, "NOT_IMPLEMENTED")


@pytest.mark.parametrize("metadata", [{}, {"classification": ""}, {"classification": "unknown"}])
def test_unclassified_source_requires_confidential_route(instance, monkeypatch, metadata):
    from jkq.skills.runtime_provider import SkillProvider

    api, _ = instance
    provider = SkillProvider(api.app)
    monkeypatch.setattr(provider, "_documents", lambda user: [{"id": "sample", "space": "minutes", **metadata}])
    assert provider._outbound(None, [{"id": "sample", "classification": "internal"}]) == "confidential"


@pytest.mark.parametrize(("saved", "current", "expected"), [
    ("confidential", "public", "confidential"),
    ("public", "confidential", "confidential"),
    ("public", "public", "internal"),
])
def test_outbound_uses_checkpoint_and_current_classification(instance, monkeypatch, saved, current, expected):
    from jkq.skills.runtime_provider import SkillProvider

    api, _ = instance
    provider = SkillProvider(api.app)
    monkeypatch.setattr(provider, "_documents", lambda user: [{"id": "sample", "classification": current}])
    assert provider._outbound(None, [{"id": "sample", "classification": saved}]) == expected


def test_instance_confidential_kb_outside_enterprise_space_stays_confidential(instance):
    """非企业空间但入库为 confidential 的资料，run/trial 与一句话起草都按文档密级出站。"""
    api, sign_in = instance
    sign_in()
    marker = "合成机密纪要 甲乙丙项目 推进节点"
    imported = api.post("/api/v1/kb/import", json={
        "text": f"第一条 {marker}定于下月完成。", "title": "合成机密会议纪要",
        "space": "minutes", "classification": "confidential",
    })
    assert imported.status_code == 200, imported.text
    [doc] = imported.json()["docs"]
    service = api.app.state.jkq_models
    original, levels = service.call, []

    def recording(user, payload, **kwargs):
        levels.append(payload["classification"])
        return original(user, payload, **kwargs)

    service.call = recording

    def reply(payload):
        if "passages" in payload:
            sentence = payload["passages"][0]["sentences"][0]
            return json.dumps([{"passage": 1, "quote": sentence}])
        if "knowledge" in payload:
            return json.dumps({"name": "纪要核对", "summary": "核对节点",
                               "spec": {"steps": [{"type": "kb", "space": "minutes", "query": marker}]},
                               "questions": []})
        return "按纪要推进 [1]。"

    model_transport(api, reply)
    skill = {"name": "纪要汇总", "spec": {"steps": [
        {"type": "kb", "space": "minutes", "query": marker}, {"type": "model"},
    ]}}
    for path, body in ((f"{ROOT}/{create(api, skill)}/run", {}), (f"{ROOT}/trial", {"skill": skill})):
        accepted = api.post(path, json=body)
        assert accepted.status_code == 202, accepted.text
        job = poll(api, accepted.json()["job"]["id"])
        citation = job["result"]["citations"][0]
        assert citation["id"] == doc["id"] and citation["classification"] == "confidential"
    drafted = api.post(f"{ROOT}/draft", json={"text": marker})
    assert drafted.status_code == 200, drafted.text
    assert len(levels) == 4 and set(levels) == {"confidential"}


@pytest.mark.parametrize("instance", ["cloud"], indirect=True)
@pytest.mark.parametrize("model", ["auto", "acceptance-cloud"])
def test_cloud_only_confidential_skill_paths_never_call_transport(instance, model):
    import httpx

    api, sign_in = instance
    sign_in()
    service = api.app.state.jkq_models
    # 内建 mock 没有上游地址；cloud 是唯一配置了传输的模型。
    assert {name for name, config in service.providers.items() if config and config.get("base_url")} == {"cloud"}
    calls = []

    def count_only(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={"choices": [{"message": {"content": "合成测试回执"}}]})

    service.transport = httpx.MockTransport(count_only)
    # 正对照：同一运行实例可以发送普通消息，确保后续零调用不是配置缺失。
    control = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "普通演练"}]})
    assert control.status_code == 200, control.text
    assert calls == ["skill-cloud.example.invalid"]
    calls.clear()

    marker = "合成机密纪要 测试甲项目节点"
    imported = api.post("/api/v1/kb/import", json={
        "title": "仅测试的会议纪要", "text": marker + "定于下月完成。",
        "space": "minutes", "classification": "confidential",
    })
    assert imported.status_code == 200, imported.text
    skill = {"name": "整理合成纪要", "spec": {"model": model, "steps": [
        {"type": "kb", "space": "minutes", "query": marker}, {"type": "model"},
    ]}}
    for path, body in ((f"{ROOT}/{create(api, skill)}/run", {}), (f"{ROOT}/trial", {"skill": skill})):
        accepted = api.post(path, json=body)
        assert accepted.status_code == 202, accepted.text
        job = poll(api, accepted.json()["job"]["id"], expected="failed")
        assert job["errorCode"] == "OUTBOUND_DENIED"
        assert calls == []
    error(api.post(f"{ROOT}/draft", json={"text": marker}), 403, "OUTBOUND_DENIED")
    assert calls == []


def test_instance_mounts_skill_share_and_publication_routes(instance):
    api, sign_in = instance
    paths = api.get("/openapi.json").json()["paths"]
    for action in ("share", "publish", "review", "rate"):
        assert f"/api/v1/skills/{{sid}}/{action}" in paths
    sign_in()
    created = api.post(ROOT, json={"name": "分享挂载核对", "spec": {}, "summary": "示例"})
    assert created.status_code == 200, created.text
    shared = api.post(f"{ROOT}/{created.json()['item']['id']}/share",
                      json={"scope": "people", "people": ["u-liyang"], "perm": "use"})
    assert shared.status_code == 200, shared.text

"""项目成员权限查询 preview 的范围、授权与字段边界。"""

from test_platform import login


def test_members_are_scoped_to_project_app_and_active_users(make_client):
    client = make_client()
    login(client, "sampleoperator")
    response = client.get(
        "/api/v1/apps/sample-app/members",
        params={"project": "sample-project", "action": "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {"id": "sampleextra", "name": "样例协审员"},
            {"id": "samplereviewer", "name": "样例审核员"},
            {"id": "sampleadmin", "name": "样例管理员"},
        ]
    }
    assert all(set(item) == {"id", "name"} for item in response.json()["items"])

    store = client.app.state.platform.store
    with store._lock, store._db:
        store._db.execute("update users set status='disabled' where id='samplereviewer'")
    remaining = client.get(
        "/api/v1/apps/sample-app/members",
        params={"project": "sample-project", "action": "approve"},
    )
    assert remaining.status_code == 200
    assert remaining.json()["items"] == [
        {"id": "sampleextra", "name": "样例协审员"},
        {"id": "sampleadmin", "name": "样例管理员"},
    ]


def test_members_require_caller_scope_and_valid_action(make_client):
    client = make_client()
    login(client, "sampleoutsider")
    hidden_app = client.get(
        "/api/v1/apps/sample-app/members",
        params={"project": "sample-project", "action": "approve"},
    )
    assert hidden_app.status_code == 404
    assert hidden_app.json()["error"]["code"] == "not_found"

    login(client, "sampleoperator")
    hidden_project = client.get(
        "/api/v1/apps/sample-app/members",
        params={"project": "limited-project", "action": "approve"},
    )
    assert hidden_project.status_code == 404
    assert hidden_project.json()["error"]["code"] == "not_found"

    invalid_action = client.get(
        "/api/v1/apps/sample-app/members",
        params={"project": "sample-project", "action": "publish"},
    )
    assert invalid_action.status_code == 422
    assert invalid_action.json()["error"]["code"] == "invalid_request"


def test_python_preview_members_binds_context_app(make_client, tmp_path):
    import json
    from pathlib import Path

    from conftest import ROOT

    apps = tmp_path / "apps"
    app = apps / "members-preview"
    (app / "api").mkdir(parents=True)
    manifest = json.loads((ROOT / "tests/fixtures/platform-app/app.json").read_text(encoding="utf-8"))
    (app / "app.json").write_text(json.dumps({**manifest, "id": "members-preview"}), encoding="utf-8")
    (app / "api/router.py").write_text(
        """from fastapi import APIRouter, Depends
from haiknow_sdk import app_context

router = APIRouter()

@router.get('/members')
def members(ctx=Depends(app_context)):
    return ctx.preview.members.list('sample-project', action='approve')
""",
        encoding="utf-8",
    )
    client = make_client(apps)
    login(client, "sampleoperator")
    response = client.get("/api/apps/members-preview/members")
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == ["samplereviewer", "sampleadmin"]

"""演示种子：E001/E002 企业台账与书香里答复意见两个版本，仅演示配置写入且幂等。"""

from shutil import copyfile

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from jkq.app import create_app  # noqa: E402
from jkq.demo import seed as demo_seed  # noqa: E402
from jkq.settings import REPO_ROOT  # noqa: E402

COMPANIES = "/api/apps/enterprise/companies"
DOCUMENTS = "/api/apps/document/documents"


@pytest.fixture
def make_client(isolated_platform, reuse_loaded_routers, cheap_password_hash, monkeypatch, tmp_path):
    config, _ = isolated_platform
    for name in ("projects.yaml", "roles.yaml", "users.yaml"):
        copyfile(REPO_ROOT / "config" / name, config / name)
    monkeypatch.setenv("HAIKNOW_APPS_DIR", str(REPO_ROOT / "apps"))
    monkeypatch.setenv("HAIKNOW_SECRET", "test-demo-seed")
    monkeypatch.setenv("JKQ_ENTERPRISE_PRIVATE_DB", str(tmp_path / "enterprise.db"))
    monkeypatch.delenv("HAIKNOW_DEMO_LOGIN", raising=False)
    for role in ("admin", "leader", "member", "partner"):
        monkeypatch.setenv(f"JKQ_DEMO_{role.upper()}_PASSWORD", f"test-{role}")

    def make(demo=True):
        monkeypatch.setenv("JKQ_DEMO_MODE", "1")
        if not demo:
            monkeypatch.delenv("JKQ_DEMO_MODE")
            return create_app(), None
        app = create_app()
        client = TestClient(app)
        response = client.post("/api/v1/auth/login", json={"username": "wangmin", "password": "test-member"})
        assert response.status_code == 200, response.text
        return app, client

    return make


def test_demo_seed_writes_fixed_companies_and_two_versions_once(make_client):
    app, client = make_client()
    assert any(entry.cls is demo_seed.DemoSeed for entry in app.user_middleware)
    companies = client.get(COMPANIES).json()["items"]
    assert {item["id"] for item in companies} >= set(demo_seed.DEMO_COMPANY_IDS)
    assert {item["short"] for item in companies} >= {"书香里文化", "纸鹿二号智驾", "知行应用"}
    assert "E020" in {item["id"] for item in companies}
    docs = [item for item in client.get(DOCUMENTS).json()["items"] if item["title"] == demo_seed.DOCUMENT_TITLE]
    assert len(docs) == 1
    draft = client.get("/api/apps/document/drafts/" + docs[0]["id"]).json()["item"]
    assert [version["v"] for version in draft["versions"]] == [1, 2]
    diff = client.post("/api/apps/document/compare", json={"a": {"id": draft["id"], "v": 1},
                                                         "b": {"id": draft["id"], "v": 2}}).json()
    assert diff["stats"]["add"] > 0
    # 再次补种不新增记录（宿主重置后重启也走同一入口）。
    assert demo_seed.seed(app, REPO_ROOT) == {"companies": [], "document": None}
    assert len(client.get(COMPANIES).json()["items"]) == len(companies)


def test_formal_config_has_no_demo_seed(make_client):
    # 正式配置没有演示账号，直接确认种子入口未接线。
    app, _ = make_client(demo=False)
    assert not any(entry.cls is demo_seed.DemoSeed for entry in app.user_middleware)

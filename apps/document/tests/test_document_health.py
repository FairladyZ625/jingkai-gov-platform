def test_document_health(client_for):
    client = client_for("document")
    url = "/api/apps/document/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "document", "status": "ok"}
    client.cookies.clear()
    response = client.get(url)
    assert response.status_code == 401
    assert response.json()["error"] == {"code": "UNAUTHENTICATED", "message": "未登录", "details": {}}


def test_document_requires_view(client_for):
    client = client_for("document", user="sampleoutsider")
    response = client.get("/api/apps/document/health")
    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "FORBIDDEN", "message": "无权查看此应用", "details": {"app": "document", "need": "view"},
    }

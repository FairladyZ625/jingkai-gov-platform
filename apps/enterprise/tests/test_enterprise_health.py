def test_enterprise_health(client_for):
    client = client_for("enterprise")
    url = "/api/apps/enterprise/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "enterprise", "status": "ok"}
    client.cookies.clear()
    response = client.get(url)
    assert response.status_code == 401
    assert response.json()["error"] == {"code": "unauthenticated", "message": "未登录", "details": {}}


def test_enterprise_requires_view(client_for):
    client = client_for("enterprise", user="sampleoutsider")
    response = client.get("/api/apps/enterprise/health")
    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "forbidden", "message": "无权查看此应用", "details": {"app": "enterprise", "need": "view"},
    }

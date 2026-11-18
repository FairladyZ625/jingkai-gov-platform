def test_policy_health(client_for):
    client = client_for("policy")
    url = "/api/apps/policy/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "policy", "status": "ok"}
    client.cookies.clear()
    response = client.get(url)
    assert response.status_code == 401
    assert response.json()["error"] == {"code": "unauthenticated", "message": "未登录", "details": {}}


def test_policy_requires_view(client_for):
    client = client_for("policy", user="sampleoutsider")
    response = client.get("/api/apps/policy/health")
    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "forbidden", "message": "无权查看此应用", "details": {"app": "policy", "need": "view"},
    }

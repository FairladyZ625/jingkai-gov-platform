def test_meeting_health(client_for):
    client = client_for("meeting")
    url = "/api/apps/meeting/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "meeting", "status": "ok"}
    client.cookies.clear()
    response = client.get(url)
    assert response.status_code == 401
    assert response.json()["error"] == {"code": "UNAUTHENTICATED", "message": "未登录", "details": {}}


def test_meeting_requires_view(client_for):
    client = client_for("meeting", user="sampleoutsider")
    response = client.get("/api/apps/meeting/health")
    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "FORBIDDEN", "message": "无权查看此应用", "details": {"app": "meeting", "need": "view"},
    }

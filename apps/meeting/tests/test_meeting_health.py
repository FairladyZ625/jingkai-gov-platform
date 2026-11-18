def test_meeting_health(client_for):
    client = client_for("meeting")
    url = "/api/apps/meeting/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "meeting", "status": "ok"}
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_meeting_requires_view(client_for):
    client = client_for("meeting", user="sampleoutsider")
    assert client.get("/api/apps/meeting/health").status_code == 403

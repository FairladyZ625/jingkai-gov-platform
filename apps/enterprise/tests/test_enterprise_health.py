def test_enterprise_health(client_for):
    client = client_for("enterprise")
    url = "/api/apps/enterprise/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "enterprise", "status": "ok"}
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_enterprise_requires_view(client_for):
    client = client_for("enterprise", user="sampleoutsider")
    assert client.get("/api/apps/enterprise/health").status_code == 403

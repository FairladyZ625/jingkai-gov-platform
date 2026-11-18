def test_policy_health(client_for):
    client = client_for("policy")
    url = "/api/apps/policy/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "policy", "status": "ok"}
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_policy_requires_view(client_for):
    client = client_for("policy", user="sampleoutsider")
    assert client.get("/api/apps/policy/health").status_code == 403

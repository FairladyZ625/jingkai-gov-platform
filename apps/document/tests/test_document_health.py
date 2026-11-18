def test_document_health(client_for):
    client = client_for("document")
    url = "/api/apps/document/health"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == {"id": "document", "status": "ok"}
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_document_requires_view(client_for):
    client = client_for("document", user="sampleoutsider")
    assert client.get("/api/apps/document/health").status_code == 403

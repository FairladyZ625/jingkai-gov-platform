def test_hello(client_for):
    c = client_for("bad-tests", user="sampleadmin")
    assert c.get("/api/apps/bad-tests/hello").status_code == 200
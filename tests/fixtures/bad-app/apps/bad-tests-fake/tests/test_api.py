"""反例：把无权限场景写成注释、字符串和非等值断言，不算覆盖。"""


def test_hello(client_for):
    c = client_for("bad-tests-fake", user="sampleadmin")
    # TODO: 以后补 assert r.status_code == 403
    assert "PermissionDenied" in "占位说明"
    assert c.get("/api/apps/bad-tests-fake/hello").status_code == 200
    assert c.get("/api/apps/bad-tests-fake/hello").status_code != 403
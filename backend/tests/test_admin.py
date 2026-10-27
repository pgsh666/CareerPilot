from fastapi.testclient import TestClient


def test_user_list_metadata_filter_and_pagination_are_admin_only(h):
    user = h.register()
    headers = h.login()
    assert h.client.get("/api/v1/admin/users").status_code == 403
    assert h.client.patch(f'/api/v1/admin/users/{user["id"]}/status', json={"enabled": False}, headers=headers).status_code == 403
    h.make_admin()
    h.login("admin@example.org")
    response = h.client.get("/api/v1/admin/users", params={"q": "candidate", "role": "user", "limit": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1 and payload["accountCount"] == 2
    item = payload["items"][0]
    assert item["email"] == "candidate@example.org" and item["lastLoginAt"]
    assert item["interviews"] == 0 and item["practices"] == 0
    assert not any(k in item for k in ("password_hash", "token_hash", "source", "fields", "csrf_hash"))
    assert h.client.get("/api/v1/admin/users", params={"offset": 2}).json()["items"] == []
    assert h.client.get("/api/v1/admin/users", params={"q": "%"}).json()["total"] == 0


def test_disable_revokes_auth_preserves_account_and_reenable_requires_login(h):
    user = h.register()
    h.login()
    with TestClient(h.app) as victim:
        victim.cookies.update(h.client.cookies)
        h.make_admin()
        headers = h.login("admin@example.org")
        path = f'/api/v1/admin/users/{user["id"]}/status'
        assert h.client.patch(path, json={"enabled": False}).status_code == 403
        assert h.client.patch(path, json={"enabled": False}, headers=headers).status_code == 200
        assert victim.get("/api/v1/auth/me").status_code == 401
        assert h.user().enabled is False
        assert h.client.get("/api/v1/admin/users", params={"status": "disabled"}).json()["total"] == 1
        assert h.client.patch(path, json={"enabled": True}, headers=headers).status_code == 200
        assert victim.get("/api/v1/auth/me").status_code == 401
    h.login()


def test_admin_cannot_disable_self_or_change_role(h):
    h.make_admin()
    headers = h.login("admin@example.org")
    me = h.user("admin@example.org")
    path = f'/api/v1/admin/users/{me.id}/status'
    assert h.client.patch(path, json={"enabled": False}, headers=headers).status_code == 409
    assert h.client.patch(path, json={"enabled": True, "role": "user"}, headers=headers).status_code == 422
    assert h.user("admin@example.org").enabled is True

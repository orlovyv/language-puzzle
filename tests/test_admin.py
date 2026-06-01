"""Admin gate (unit) and admin flows (E2E against the live database)."""

import secrets

import pytest

import app.services.auth_service as auth_service


# ---------------------------------------------------------------------------
# unit: is_admin gate
# ---------------------------------------------------------------------------
def test_is_admin(monkeypatch):
    monkeypatch.setattr(auth_service, "ADMIN_EMAILS", {"boss@local.ru"})
    assert auth_service.is_admin({"email": "boss@local.ru"}) is True
    assert auth_service.is_admin({"email": "BOSS@local.ru"}) is True  # case-insensitive
    assert auth_service.is_admin({"email": "user@local.ru"}) is False
    assert auth_service.is_admin(None) is False


def test_is_admin_empty_allowlist(monkeypatch):
    monkeypatch.setattr(auth_service, "ADMIN_EMAILS", set())
    assert auth_service.is_admin({"email": "anyone@local.ru"}) is False


# ---------------------------------------------------------------------------
# E2E
# ---------------------------------------------------------------------------
@pytest.fixture
def env(monkeypatch):
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_ENABLED", False)
    monkeypatch.setattr(auth_service, "verify_turnstile", lambda token, ip=None: True)

    sent = {}
    monkeypatch.setattr(auth_service, "_send_email", lambda to, subject, body: sent.__setitem__(to, body))

    admin_email = f"admin_{secrets.token_hex(4)}@local.ru"
    monkeypatch.setattr(auth_service, "ADMIN_EMAILS", {admin_email})

    with TestClient(fastapi_app) as c:
        c.sent = sent
        c.admin_email = admin_email
        yield c


def _register(client, email, password="pass1"):
    r = client.post("/api/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text


def _login(client, email, password="pass1"):
    return client.post("/api/login", json={"email": email, "password": password})


def test_non_admin_forbidden(env):
    user_email = f"user_{secrets.token_hex(4)}@local.ru"
    _register(env, user_email)
    assert env.get("/api/admin/stats").status_code == 403
    assert env.get("/api/admin/users").status_code == 403


def test_admin_full_flow(env):
    # admin account
    _register(env, env.admin_email)
    me = env.get("/api/me").json()["user"]
    assert me["is_admin"] is True

    # a target user to manage
    target_email = f"t_{secrets.token_hex(4)}@local.ru"
    _register(env, target_email)
    target_id = env.get("/api/me").json()["user"]["id"]
    env.post("/api/logout")

    # back to admin
    assert _login(env, env.admin_email).status_code == 200

    # stats
    stats = env.get("/api/admin/stats").json()["stats"]
    assert stats["users_total"] >= 2

    # search finds the target, no password_hash leaked
    found = env.get(f"/api/admin/users?q={target_email}").json()
    assert found["total"] >= 1
    assert any(u["email"] == target_email for u in found["users"])
    assert all("password_hash" not in u for u in found["users"])

    # grant premium
    r = env.patch(f"/api/admin/users/{target_id}/subscription", json={"plan": "premium"})
    assert r.status_code == 200
    assert r.json()["user"]["is_premium"] is True

    # block -> target can't log in
    r = env.patch(f"/api/admin/users/{target_id}/block", json={"blocked": True})
    assert r.status_code == 200 and r.json()["user"]["is_blocked"] is True
    env.post("/api/logout")
    assert _login(env, target_email).status_code == 403  # blocked

    # admin cannot block self
    admin_id = _login(env, env.admin_email).json()["user"]["id"]
    assert env.patch(f"/api/admin/users/{admin_id}/block", json={"blocked": True}).status_code == 400

    # unblock + reset password
    assert env.patch(f"/api/admin/users/{target_id}/block", json={"blocked": False}).status_code == 200
    env.sent.pop(target_email, None)
    assert env.post(f"/api/admin/users/{target_id}/reset-password").status_code == 200
    assert target_email in env.sent  # temporary password emailed

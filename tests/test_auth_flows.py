"""End-to-end auth flows against the live database via TestClient.

Captures verification codes / temporary passwords by monkeypatching the email
sender, and forces EMAIL_VERIFICATION_ENABLED on while disabling Turnstile.
"""

import secrets

import pytest

import app.services.auth_service as auth_service


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    # Force the flows on/off regardless of local .env.
    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_ENABLED", True)
    # Turnstile: verify_turnstile is imported into auth_service's namespace.
    monkeypatch.setattr(auth_service, "verify_turnstile", lambda token, ip=None: True)

    sent = {}
    monkeypatch.setattr(auth_service, "_send_email", lambda to, subject, body: sent.__setitem__(to, (subject, body)))
    with TestClient(fastapi_app) as c:
        c.sent = sent
        yield c


def _code_from(body: str) -> str:
    import re
    return re.search(r"\b(\d{6})\b", body).group(1)


def test_full_registration_then_reset_then_change(client):
    email = f"flow_{secrets.token_hex(4)}@local.ru"

    # 1. Register -> requires verification, user NOT created yet
    r = client.post("/api/register", json={"email": email, "password": "pass1"})
    assert r.status_code == 200, r.text
    assert r.json().get("requires_verification") is True
    assert email in client.sent  # verification code was "sent"

    # logging in before verification must fail (no user)
    assert client.post("/api/login", json={"email": email, "password": "pass1"}).status_code == 401

    # 2. Verify with the 6-digit code -> user created and logged in
    code = _code_from(client.sent[email][1])
    r = client.post("/api/register/verify", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == email
    client.post("/api/logout")

    # 3. Password reset -> temporary password emailed, must_change set
    client.sent.pop(email, None)
    r = client.post("/api/password/reset-request", json={"email": email})
    assert r.status_code == 200
    temp_body = client.sent[email][1]
    temp_password = temp_body.split("Ваш временный пароль:")[1].split("\n")[0].strip()

    r = client.post("/api/login", json={"email": email, "password": temp_password})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["must_change_password"] is True

    # 4. Change password -> flag cleared, new password works
    r = client.post("/api/password/change", json={"current_password": temp_password, "new_password": "brandnew"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["must_change_password"] is False

    client.post("/api/logout")
    assert client.post("/api/login", json={"email": email, "password": "brandnew"}).status_code == 200
    # old temporary password no longer works
    assert client.post("/api/login", json={"email": email, "password": temp_password}).status_code == 401


def test_reset_for_unknown_email_is_silent(client):
    r = client.post("/api/password/reset-request", json={"email": "nobody_here@local.ru"})
    assert r.status_code == 200
    assert "nobody_here@local.ru" not in client.sent


def test_captcha_failure_blocks_registration(client, monkeypatch):
    monkeypatch.setattr(auth_service, "verify_turnstile", lambda token, ip=None: False)
    r = client.post("/api/register", json={"email": f"bot_{secrets.token_hex(3)}@local.ru", "password": "pass1"})
    assert r.status_code == 400
    assert "робот" in r.json()["detail"]

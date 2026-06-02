"""Email-delivery failure must not lock users out: the password is only rotated
when the temporary-password email was actually delivered."""

import secrets

import pytest

import app.services.auth_service as auth_service
from app.core.database import db
from app.repositories import user_repository
from app.utils.security import hash_password


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_ENABLED", False)
    monkeypatch.setattr(auth_service, "verify_turnstile", lambda token, ip=None: True)
    with TestClient(fastapi_app) as c:
        yield c


def _make_user(client):
    email = f"mailfail_{secrets.token_hex(4)}@local.ru"
    assert client.post("/api/register", json={"email": email, "password": "orig123"}).status_code == 200
    client.post("/api/logout")
    return email


def test_reset_failure_does_not_rotate_password(client, monkeypatch):
    email = _make_user(client)

    def boom(to, subject, body):
        raise auth_service.EmailDeliveryError("smtp down")

    monkeypatch.setattr(auth_service, "_send_email", boom)

    r = client.post("/api/password/reset-request", json={"email": email})
    assert r.status_code == 502

    # Original password still works — the user was NOT locked out.
    assert client.post("/api/login", json={"email": email, "password": "orig123"}).status_code == 200


def test_reset_success_rotates_password(client, monkeypatch):
    email = _make_user(client)
    captured = {}
    monkeypatch.setattr(auth_service, "_send_email",
                       lambda to, subject, body: captured.__setitem__("body", body))

    r = client.post("/api/password/reset-request", json={"email": email})
    assert r.status_code == 200
    temp = captured["body"].split("Ваш временный пароль:")[1].split("\n")[0].strip()
    # New temp password works, old one does not.
    assert client.post("/api/login", json={"email": email, "password": temp}).status_code == 200
    client.post("/api/logout")
    assert client.post("/api/login", json={"email": email, "password": "orig123"}).status_code == 401


def test_send_email_wraps_smtp_errors(monkeypatch):
    # _send_email must raise EmailDeliveryError (not a raw OSError) on connect failure.
    monkeypatch.setattr(auth_service, "SMTP_HOST", "smtp.invalid.example")
    monkeypatch.setattr(auth_service, "SMTP_PORT", 587)
    with pytest.raises(auth_service.EmailDeliveryError):
        auth_service._send_email("x@y.ru", "subj", "body")

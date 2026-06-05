"""E2E Robokassa billing flow against the live database via TestClient."""

import hashlib
import secrets

import pytest

import app.services.auth_service as auth_service
import app.services.billing.provider as provider
import app.services.billing.robokassa_client as rk


def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app import app as fastapi_app

    # No real captcha / email during signup.
    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_ENABLED", False)
    monkeypatch.setattr(auth_service, "verify_turnstile", lambda token, ip=None: True)

    # Configure Robokassa as the active, usable provider.
    monkeypatch.setattr(provider, "PAYMENT_PROVIDER", "robokassa")
    monkeypatch.setattr(rk, "ROBOKASSA_MERCHANT_LOGIN", "demo")
    monkeypatch.setattr(rk, "ROBOKASSA_PASSWORD1", "pass1")
    monkeypatch.setattr(rk, "ROBOKASSA_PASSWORD2", "pass2")
    monkeypatch.setattr(rk, "ROBOKASSA_IS_TEST", True)
    monkeypatch.setattr(rk, "SUBSCRIPTION_PRICE_RUB", 299.0)

    with TestClient(fastapi_app) as c:
        yield c


def _register(client):
    email = f"pay_{secrets.token_hex(4)}@local.ru"
    r = client.post("/api/register", json={"email": email, "password": "pass1"})
    assert r.status_code == 200, r.text
    return email


def test_status_reports_robokassa(client):
    _register(client)
    body = client.get("/api/billing/status").json()
    assert body["provider"] == "robokassa"
    assert body["available"] is True
    assert body["status"]["is_premium"] is False


def test_checkout_then_result_activates_premium(client):
    _register(client)
    # Checkout -> Robokassa redirect URL + numeric invoice id
    r = client.post("/api/billing/checkout", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    inv_id = data["payment_id"]
    assert "auth.robokassa.ru" in data["confirmation_url"]
    assert inv_id.isdigit()

    # Forged signature is rejected
    bad = client.post("/api/billing/robokassa-result",
                      data={"OutSum": "299.00", "InvId": inv_id, "SignatureValue": "deadbeef"})
    assert bad.status_code == 400

    # Valid Result callback activates premium and returns OK{InvId}
    sig = _md5(f"299.00:{inv_id}:pass2")
    ok = client.post("/api/billing/robokassa-result",
                    data={"OutSum": "299.00", "InvId": inv_id, "SignatureValue": sig})
    assert ok.status_code == 200
    assert ok.text == f"OK{inv_id}"

    status = client.get("/api/billing/status").json()["status"]
    assert status["is_premium"] is True
    # simple Robokassa flow does not auto-renew
    assert status["auto_renew"] is False

    # Idempotent: replaying the callback is a no-op success
    ok2 = client.post("/api/billing/robokassa-result",
                     data={"OutSum": "299.00", "InvId": inv_id, "SignatureValue": sig})
    assert ok2.status_code == 200
    assert ok2.text == f"OK{inv_id}"


def test_donation_flow_does_not_grant_premium(client):
    """A donation is recorded and paid, but never grants a subscription."""
    _register(client)
    status = client.get("/api/billing/status").json()
    assert status["donation_mode"] is True  # default BILLING_MODE=donation

    r = client.post("/api/billing/donate", json={"amount": 250})
    assert r.status_code == 200, r.text
    data = r.json()
    inv_id = data["payment_id"]
    assert "auth.robokassa.ru" in data["confirmation_url"]
    assert "250.00" in data["confirmation_url"]  # custom amount, not the sub price

    sig = _md5(f"250.00:{inv_id}:pass2")
    ok = client.post("/api/billing/robokassa-result",
                    data={"OutSum": "250.00", "InvId": inv_id, "SignatureValue": sig})
    assert ok.status_code == 200
    assert ok.text == f"OK{inv_id}"

    # Donation succeeded, but the user is NOT premium.
    after = client.get("/api/billing/status").json()
    assert after["status"]["is_premium"] is False
    assert after["payments"][0]["status"] == "succeeded"


def test_donation_rejects_amount_below_minimum(client):
    _register(client)
    r = client.post("/api/billing/donate", json={"amount": 1})
    assert r.status_code == 400

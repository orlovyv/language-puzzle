import hashlib

import app.services.billing.robokassa_client as rk


def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def _configure(monkeypatch, login="demo", p1="pass1", p2="pass2", is_test=True):
    monkeypatch.setattr(rk, "ROBOKASSA_MERCHANT_LOGIN", login)
    monkeypatch.setattr(rk, "ROBOKASSA_PASSWORD1", p1)
    monkeypatch.setattr(rk, "ROBOKASSA_PASSWORD2", p2)
    monkeypatch.setattr(rk, "ROBOKASSA_IS_TEST", is_test)
    monkeypatch.setattr(rk, "SUBSCRIPTION_PRICE_RUB", 299.0)


def test_is_configured(monkeypatch):
    monkeypatch.setattr(rk, "ROBOKASSA_MERCHANT_LOGIN", "")
    assert rk.is_configured() is False
    _configure(monkeypatch)
    assert rk.is_configured() is True


def test_build_payment_url_signature(monkeypatch):
    _configure(monkeypatch)
    url = rk.build_payment_url(12345, "Premium", amount=299.0)
    expected_sig = _md5("demo:299.00:12345:pass1")
    assert f"SignatureValue={expected_sig}" in url
    assert "OutSum=299.00" in url
    assert "InvId=12345" in url
    assert "IsTest=1" in url
    assert url.startswith("https://auth.robokassa.ru/")


def test_verify_result_ok(monkeypatch):
    _configure(monkeypatch)
    sig = _md5("299.00:12345:pass2")
    assert rk.verify_result("299.00", "12345", sig) is True
    # case-insensitive
    assert rk.verify_result("299.00", "12345", sig.upper()) is True


def test_verify_result_bad(monkeypatch):
    _configure(monkeypatch)
    assert rk.verify_result("299.00", "12345", "deadbeef") is False
    assert rk.verify_result("299.00", "12345", "") is False
    # wrong amount breaks the signature
    good = _md5("299.00:12345:pass2")
    assert rk.verify_result("199.00", "12345", good) is False


def test_verify_result_unconfigured(monkeypatch):
    monkeypatch.setattr(rk, "ROBOKASSA_MERCHANT_LOGIN", "")
    assert rk.verify_result("299.00", "12345", "anything") is False


def test_new_invoice_id_positive(monkeypatch):
    for _ in range(100):
        assert rk.new_invoice_id() > 0

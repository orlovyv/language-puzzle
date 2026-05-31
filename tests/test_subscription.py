from datetime import datetime, timedelta, timezone

import app.services.billing.subscription_service as sub


def _future(days=5):
    return datetime.now(timezone.utc) + timedelta(days=days)


def _past(days=1):
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_is_premium():
    assert sub.is_premium(None) is False
    assert sub.is_premium({"plan": "free"}) is False
    assert sub.is_premium({"plan": "premium", "premium_until": _future()}) is True
    assert sub.is_premium({"plan": "premium", "premium_until": _past()}) is False
    assert sub.is_premium({"plan": "premium", "premium_until": None}) is True


def test_extend_from_now_when_lapsed():
    user = {"premium_until": _past()}
    result = sub._extend_from(user, 30)
    expected = datetime.now(timezone.utc) + timedelta(days=30)
    assert abs((result - expected).total_seconds()) < 5


def test_extend_from_current_when_active():
    current = _future(10)
    user = {"premium_until": current}
    result = sub._extend_from(user, 30)
    # extends from the existing expiry, not from now
    assert abs((result - (current + timedelta(days=30))).total_seconds()) < 5


def test_status_for():
    user = {"plan": "premium", "premium_until": _future(), "subscription_auto_renew": True}
    status = sub.status_for(user)
    assert status["is_premium"] is True
    assert status["auto_renew"] is True
    assert status["plan"] == "premium"


class FakeRepo:
    def __init__(self):
        self.calls = []

    def set_subscription(self, conn, user_id, plan, premium_until, auto_renew, payment_method_id=None):
        self.calls.append(("set", user_id, plan, auto_renew, payment_method_id))
        return {"id": user_id, "plan": plan, "premium_until": premium_until, "subscription_auto_renew": auto_renew}

    def set_auto_renew(self, conn, user_id, auto_renew):
        self.calls.append(("renew", user_id, auto_renew))
        return {"id": user_id, "subscription_auto_renew": auto_renew}


def test_activate_and_cancel(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(sub.user_repository, "set_subscription", repo.set_subscription)
    monkeypatch.setattr(sub.user_repository, "set_auto_renew", repo.set_auto_renew)
    user = {"id": "u1", "plan": "free", "premium_until": None}

    activated = sub.activate_subscription(None, user, period_days=30, payment_method_id="pm_1")
    assert activated["plan"] == "premium"
    assert activated["subscription_auto_renew"] is True

    cancelled = sub.cancel_subscription(None, activated)
    assert cancelled["subscription_auto_renew"] is False

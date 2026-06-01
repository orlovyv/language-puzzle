from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
WORDNET_ARCHIVE = BASE_DIR / "wn3.1.dict.tar.gz"
MUSE_DICTIONARY = BASE_DIR / "data" / "dictionaries" / "muse-en-ru.txt"
MIGRATIONS_DIR = BASE_DIR / "migrations"


def load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue
        key, raw = value.split("=", 1)
        os.environ.setdefault(key.strip(), raw.strip().strip('"').strip("'"))


load_dotenv()


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes"}


USE_WORDNET_FALLBACK = os.getenv("USE_WORDNET_FALLBACK", "0").lower() in {
    "1",
    "true",
    "yes",
}
USE_GOOGLETRANS_FALLBACK = os.getenv(
    "USE_GOOGLETRANS_FALLBACK", "1"
).lower() in {"1", "true", "yes"}
GOOGLETRANS_SOURCE_LANG = os.getenv("GOOGLETRANS_SOURCE_LANG", "en")
GOOGLETRANS_TARGET_LANG = os.getenv("GOOGLETRANS_TARGET_LANG", "ru")
USE_IPA_TRANSCRIPTION = os.getenv("USE_IPA_TRANSCRIPTION", "1").lower() in {
    "1",
    "true",
    "yes",
}
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/language_puzzle",
)
DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
APP_SECRET = os.getenv("APP_SECRET", "language-puzzle-dev")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "3000"))
# Demo account seeded on startup. Override credentials via .env in real deployments.
DEMO_EMAIL = os.getenv("DEMO_EMAIL", "demo@local.ru")
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "123")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME or "noreply@language-puzzle.local")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Language Puzzle")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").lower() in {"1", "true", "yes"}
EMAIL_VERIFICATION_ENABLED = os.getenv("EMAIL_VERIFICATION_ENABLED", "1").lower() in {
    "1",
    "true",
    "yes",
}

# --- Cloudflare Turnstile ("я не робот"). Off => captcha check skipped ---
USE_TURNSTILE = _flag("USE_TURNSTILE", "0")
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")

# --- AI enrichment (OpenRouter) ---
# Premium-only features degrade silently to the free path when disabled or
# unconfigured.
USE_AI_FEATURES = _flag("USE_AI_FEATURES", "0")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
AI_DAILY_LIMIT_FREE = int(os.getenv("AI_DAILY_LIMIT_FREE", "0"))
AI_DAILY_LIMIT_PREMIUM = int(os.getenv("AI_DAILY_LIMIT_PREMIUM", "300"))

# --- Billing ---
# Active payment provider: "robokassa" (default) or "yookassa".
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "robokassa").strip().lower()
SUBSCRIPTION_PRICE_RUB = float(os.getenv("SUBSCRIPTION_PRICE_RUB", "299"))
SUBSCRIPTION_PERIOD_DAYS = int(os.getenv("SUBSCRIPTION_PERIOD_DAYS", "30"))
SUBSCRIPTION_RETURN_URL = os.getenv("SUBSCRIPTION_RETURN_URL", "http://localhost:3000/settings")

# YooKassa (kept available, but inactive unless PAYMENT_PROVIDER=yookassa)
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")

# Robokassa
ROBOKASSA_MERCHANT_LOGIN = os.getenv("ROBOKASSA_MERCHANT_LOGIN", "")
ROBOKASSA_PASSWORD1 = os.getenv("ROBOKASSA_PASSWORD1", "")
ROBOKASSA_PASSWORD2 = os.getenv("ROBOKASSA_PASSWORD2", "")
ROBOKASSA_IS_TEST = _flag("ROBOKASSA_IS_TEST", "1")
ROBOKASSA_BASE_URL = os.getenv("ROBOKASSA_BASE_URL", "https://auth.robokassa.ru/Merchant/Index.aspx")

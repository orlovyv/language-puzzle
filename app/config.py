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
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1").lower() in {"1", "true", "yes"}
EMAIL_VERIFICATION_ENABLED = os.getenv("EMAIL_VERIFICATION_ENABLED", "0").lower() in {
    "1",
    "true",
    "yes",
}

"""URL import: block extraction, SSRF guard and the extract-url endpoint."""

import secrets

import pytest

import app.services.url_extraction as urlx


SAMPLE_HTML = """
<html><head><title>Sample</title></head><body>
  <nav>home about contact menu navigation links here</nav>
  <article>
    <p>{p1}</p>
    <p>{p2}</p>
  </article>
  <section class="related">
    <p>{p3}</p>
  </section>
  <div class="tiny"><p>too short</p></div>
  <footer>Copyright notice and some boilerplate footer text goes here.</footer>
</body></html>
""".format(
    p1="This is the first long paragraph of the main article body. " * 8,
    p2="Here is a second substantial paragraph with enough words to count. " * 6,
    p3="An alternative block from a different section of the same page entirely. " * 6,
)


def test_collect_blocks_ranks_and_filters():
    blocks = urlx._collect_blocks(SAMPLE_HTML)
    assert blocks, "expected at least one substantial block"
    # Largest first.
    assert all(len(blocks[i]) >= len(blocks[i + 1]) for i in range(len(blocks) - 1))
    # Boilerplate / tiny fragments are excluded.
    joined = "\n".join(blocks)
    assert "too short" not in joined
    assert "navigation links" not in joined


def test_validate_url_rejects_unsafe(monkeypatch):
    from fastapi import HTTPException

    for bad in ["http://127.0.0.1/x", "http://localhost/x", "ftp://example.com", "notaurl", ""]:
        with pytest.raises(HTTPException):
            urlx._validate_url(bad)


class _FakeResponse:
    def __init__(self, html: str):
        self._html = html.encode("utf-8")
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield self._html

    def close(self):
        return None


def _stub_network(monkeypatch, html=SAMPLE_HTML):
    # Avoid real DNS + HTTP.
    monkeypatch.setattr(urlx.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(urlx.requests, "get", lambda *a, **k: _FakeResponse(html))


def test_extract_from_url_shape(monkeypatch):
    _stub_network(monkeypatch)
    result = urlx.extract_from_url("https://example.com/article")
    assert result["url"] == "https://example.com/article"
    assert isinstance(result["main_text"], str)
    assert result["blocks"], "expected alternative blocks"
    first = result["blocks"][0]
    assert {"id", "chars", "preview", "text"} <= set(first)
    assert first["chars"] == len(first["text"])


# ---------------------------------------------------------------------------
# Endpoint (requires auth + DB, mirrors tests/test_billing_flow.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import app.services.auth_service as auth_service
    from app import app as fastapi_app

    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_ENABLED", False)
    monkeypatch.setattr(auth_service, "verify_turnstile", lambda token, ip=None: True)
    with TestClient(fastapi_app) as c:
        yield c


def test_extract_url_endpoint(client, monkeypatch):
    _stub_network(monkeypatch)
    email = f"url_{secrets.token_hex(4)}@local.ru"
    assert client.post("/api/register", json={"email": email, "password": "pass1"}).status_code == 200

    r = client.post("/api/documents/extract-url", json={"url": "https://example.com/article"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == "https://example.com/article"
    assert "main_text" in body and "blocks" in body


def test_extract_url_requires_auth(client):
    r = client.post("/api/documents/extract-url", json={"url": "https://example.com/article"})
    assert r.status_code == 401

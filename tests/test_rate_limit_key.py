from starlette.requests import Request

from app.utils import rate_limit


def _request(xff=None, peer="10.0.0.1"):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_ignores_forwarded_header_by_default(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 0)
    assert rate_limit.client_ip(_request("1.2.3.4")) == "10.0.0.1"


def test_uses_the_ip_the_trusted_proxy_appended(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    assert rate_limit.client_ip(_request("203.0.113.9")) == "203.0.113.9"


def test_client_supplied_entries_cannot_change_the_key(monkeypatch):
    """A spoofed prefix is ignored — only the rightmost (proxy-appended) hop counts."""
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    assert rate_limit.client_ip(_request("6.6.6.6, 203.0.113.9")) == "203.0.113.9"


def test_falls_back_to_peer_when_header_is_missing(monkeypatch):
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
    assert rate_limit.client_ip(_request()) == "10.0.0.1"

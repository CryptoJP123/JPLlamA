from __future__ import annotations

import requests

from app.ollama.client import OllamaClient, OllamaConfig


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_ollama_chat_retries_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def fake_request(method, url, timeout=None, **kwargs):
        calls["count"] += 1
        if calls["count"] < 2:
            raise requests.ConnectionError("temporary")
        return _Response({"message": {"content": "ok"}})

    monkeypatch.setattr(requests, "request", fake_request)

    client = OllamaClient(OllamaConfig(base_url="http://example.test", max_retries=2, retry_backoff_seconds=0.0))
    result = client.chat(model="qwen", messages=[{"role": "user", "content": "hi"}])

    assert result == "ok"
    assert calls["count"] == 2


def test_ollama_chat_raises_after_exhausted_retries(monkeypatch):
    def fake_request(method, url, timeout=None, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "request", fake_request)
    client = OllamaClient(OllamaConfig(base_url="http://example.test", max_retries=1, retry_backoff_seconds=0.0))

    try:
        client.chat(model="qwen", messages=[{"role": "user", "content": "hi"}])
    except RuntimeError as exc:
        assert "Unable to reach Ollama" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when retries are exhausted")

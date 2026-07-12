from __future__ import annotations

import json
from pathlib import Path

from app.intelligence.reference_sources import (
    DP_WORLD_URL,
    download_and_index_dp_world_documentation_centre,
    is_reference_index_command,
)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_reference_index_command_detection():
    assert is_reference_index_command("Download and index the DP World Documentation Centre.") is True


def test_download_and_index_dp_world_documentation_centre_with_mocked_http(monkeypatch, tmp_path: Path):
    html = b"""
    <html><body>
      <a href=\"/docs/germany-terms.pdf\">Germany Standard Trading Conditions</a>
      <a href=\"/docs/netherlands-terms.pdf\">Netherlands Terms and Conditions</a>
      <a href=\"/docs/ssl-shipping.pdf\">Smart Solutions Line Shipping Documents</a>
    </body></html>
    """

    docs = {
        "https://www.dpworld.com/docs/germany-terms.pdf": b"GERMANY PDF",
        "https://www.dpworld.com/docs/netherlands-terms.pdf": b"NL PDF",
        "https://www.dpworld.com/docs/ssl-shipping.pdf": b"SSL PDF",
    }

    def _fake_urlopen(req, timeout=20.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url == DP_WORLD_URL:
            return _FakeResponse(html)
        if url in docs:
            return _FakeResponse(docs[url])
        raise RuntimeError(f"unexpected url: {url}")

    monkeypatch.setattr("app.intelligence.reference_sources.request.urlopen", _fake_urlopen)

    result = download_and_index_dp_world_documentation_centre(tmp_path / "vault")

    assert Path(result.index_path).exists()
    assert Path(result.markdown_index_path).exists()
    assert Path(result.snapshot_path).exists()
    assert result.documents_downloaded == 3
    assert result.documents_failed == 0

    payload = json.loads(Path(result.index_path).read_text(encoding="utf-8"))
    assert payload["source_url"] == DP_WORLD_URL
    assert len(payload["documents"]) == 3
    assert any(item["country"] == "Germany" for item in payload["documents"])
    assert any(item["status"] == "downloaded" for item in payload["documents"])

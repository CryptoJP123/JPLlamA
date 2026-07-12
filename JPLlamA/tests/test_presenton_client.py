from __future__ import annotations

import io
from pathlib import Path
import zipfile

import requests

from app.presenton.client import PresentonClient, PresentonConfig


class FakeResponse:
    def __init__(self, payload=None, *, status_code=200, headers=None, text="", content_bytes: bytes = b"", stream=False):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._content_bytes = content_bytes
        self._stream = stream

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload

    @property
    def content(self):
        if self._content_bytes:
            return self._content_bytes
        return self.text.encode("utf-8") if isinstance(self.text, str) else b""

    def iter_lines(self):
        if not self._stream:
            return []
        return iter(self._payload)


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError("No fake response available")
        return self._responses.pop(0)

    def post(self, *args, **kwargs):
        return self.request("POST", *args, **kwargs)

    def get(self, *args, **kwargs):
        return self.request("GET", *args, **kwargs)


def _minimal_pptx_bytes() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("[Content_Types].xml", """<?xml version='1.0' encoding='UTF-8'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
    <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
    <Default Extension='xml' ContentType='application/xml'/>
    <Override PartName='/ppt/presentation.xml' ContentType='application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'/>
    <Override PartName='/ppt/slides/slide1.xml' ContentType='application/vnd.openxmlformats-officedocument.presentationml.slide+xml'/>
</Types>
""")
                archive.writestr("_rels/.rels", """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
    <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='ppt/presentation.xml'/>
</Relationships>
""")
                archive.writestr("ppt/presentation.xml", """<?xml version='1.0' encoding='UTF-8'?>
<p:presentation xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships' xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'>
    <p:sldIdLst>
        <p:sldId id='256' r:id='rId1'/>
    </p:sldIdLst>
</p:presentation>
""")
                archive.writestr("ppt/slides/slide1.xml", """<?xml version='1.0' encoding='UTF-8'?>
<p:sld xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships' xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'>
    <p:cSld/>
</p:sld>
""")
        return buffer.getvalue()


def test_get_templates_handles_payload_dict():
    client = PresentonClient(PresentonConfig(base_url="http://example.test"))
    client.session = FakeSession([FakeResponse({"templates": [{"name": "general"}]})])

    templates = client.get_templates()

    assert templates == [{"name": "general"}]


def test_stream_presentation_waits_for_completed_event():
    client = PresentonClient(PresentonConfig(base_url="http://example.test"))
    stream_lines = [
        "event: progress",
        "data: working",
        "",
        "event: completed",
        "data: done",
        "",
    ]
    client.session = FakeSession([FakeResponse(stream_lines, stream=True)])

    payload = client.stream_presentation("abc123")

    assert "done" in payload
    assert "working" in payload


def test_build_presentation_renders_existing_presentation_with_presentation_id(tmp_path: Path):
    generated = tmp_path / "generated.pptx"
    generated.write_bytes(_minimal_pptx_bytes())

    client = PresentonClient(PresentonConfig(base_url="http://example.test"))
    client.session = FakeSession([
        FakeResponse({"id": "deck-1"}),
        FakeResponse({"ok": True}),
        FakeResponse({"id": "task-1"}),
        FakeResponse({"status": "completed", "data": {"path": str(generated)}}),
        FakeResponse(text="event: completed\ndata: done\n\n", stream=True),
        FakeResponse({"id": "task-2"}),
        FakeResponse({"status": "completed", "data": {"path": str(generated)}}),
    ])
    client.get_template = lambda template_name=None: {
        "name": "general",
        "slides": [{"id": "slide-1", "title": "Test"}],
    }

    result = client.build_presentation(
        "Hello world",
        outlines=[{"title": "Intro", "content": "Hello"}],
        output_dir=str(tmp_path / "exports"),
    )

    assert result["presentation_id"] == "deck-1"
    generate_calls = [
        call for call in client.session.calls
        if call[0] == "POST" and call[1].endswith("/api/v1/ppt/presentation/generate/async")
    ]
    assert len(generate_calls) == 2
    assert generate_calls[0][2]["json"]["presentation_id"] == "deck-1"
    assert result["export"]["path"].endswith("generated.pptx")
    assert result["path"].endswith("generated.pptx")


def test_generate_presentation_recovers_latest_pptx_when_payload_path_is_missing(tmp_path: Path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    recovered = output_dir / "recovered-deck.pptx"
    recovered.write_bytes(_minimal_pptx_bytes())

    client = PresentonClient(PresentonConfig(base_url="http://example.test"))
    client.session = FakeSession([
        FakeResponse({"id": "task-1"}),
        FakeResponse({"status": "completed", "data": {}}),
    ])

    result = client.generate_presentation("Hello", output_dir=str(output_dir), presentation_id="deck-1")

    assert result["path"] == str(recovered)
    assert result["filename"] == recovered.name
    assert result["exists"] is True
    assert result["recovered"] is True


def test_generate_presentation_uses_presentation_status_probe_when_task_status_stays_pending(tmp_path: Path):
    generated = tmp_path / "from-presentation-status.pptx"
    generated.write_bytes(_minimal_pptx_bytes())

    client = PresentonClient(PresentonConfig(base_url="http://example.test"))
    client.session = FakeSession([
        FakeResponse({"id": "task-1"}),
        FakeResponse({"status": "pending", "data": {}}),
        FakeResponse({"status": "pending", "data": {}}),
        FakeResponse({"status": "pending", "data": {}}),
        FakeResponse({"status": "pending", "data": {}}),
        FakeResponse({"status": "pending", "data": {}}),
        FakeResponse({"status": "completed", "data": {"path": str(generated), "presentation_id": "deck-1"}}),
    ])

    result = client.generate_presentation(
        "Hello",
        presentation_id="deck-1",
        output_dir=str(tmp_path / "exports"),
    )

    assert result["presentation_id"] == "deck-1"
    assert result["path"].endswith("from-presentation-status.pptx")
    assert result["exists"] is True


def test_prepare_presentation_uses_raw_layout_payload():
    client = PresentonClient(PresentonConfig(base_url="http://example.test"))
    client.session = FakeSession([FakeResponse({"ok": True})])

    template = {
        "name": "general",
        "slides": [{"id": "slide-1", "title": "Test"}],
    }

    client.prepare_presentation("deck-1", outlines=[{"title": "Intro", "content": "Hello"}], layout=template)

    prepare_call = client.session.calls[0]
    payload = prepare_call[2]["json"]

    assert payload["layout"]["name"] == template["name"]
    assert payload["layout"]["slides"] == template["slides"]
    assert "template" not in payload


def test_presenton_request_retries_then_succeeds():
    class RetrySession(FakeSession):
        def __init__(self):
            super().__init__([FakeResponse({"templates": [{"name": "general"}]})])
            self.attempts = 0

        def request(self, method, url, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise requests.ConnectionError("temporary")
            return super().request(method, url, **kwargs)

    client = PresentonClient(PresentonConfig(base_url="http://example.test", max_retries=2, retry_backoff_seconds=0.0))
    session = RetrySession()
    client.session = session

    templates = client.get_templates()

    assert templates == [{"name": "general"}]
    assert session.attempts == 2

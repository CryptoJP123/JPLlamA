from __future__ import annotations

from pathlib import Path

from app import main as main_module
from app.gui import main_window as gui_module
from app.gui.main_window import (
    BUTTON_TO_COMMAND,
    compose_prompt,
    create_backend,
    detect_content_type,
    detect_drop_primary_type,
    execute_prompt,
    suggest_actions_for_type,
)


def test_button_mapping_has_required_actions():
    required = {
        "Help",
        "Health",
        "Version",
        "Remember This",
        "Store Email",
        "Review RFQ",
        "Store Presentation",
        "Read from Vault",
    }
    assert required.issubset(set(BUTTON_TO_COMMAND.keys()))


def test_compose_prompt_requires_payload_for_store_actions():
    try:
        compose_prompt("Remember This", "")
        assert False, "Expected ValueError for empty payload"
    except ValueError as exc:
        assert "requires input" in str(exc)


def test_compose_prompt_for_help_ignores_payload():
    prompt = compose_prompt("Help", "anything")
    assert prompt == "help"


def test_detect_content_type_routes_email_and_rfq():
    assert detect_content_type("From: ops@example.com\nSubject: Update") == "email"
    assert detect_content_type("/tmp/customer_bid.rfq") == "rfq"


def test_detect_content_type_routes_presentation_and_image():
    assert detect_content_type("/tmp/exec_deck.pptx") == "presentation"
    assert detect_content_type("/tmp/screenshot.png") == "image"


def test_detect_drop_primary_type_uses_majority_signal():
    kind = detect_drop_primary_type([
        "/tmp/a.pptx",
        "/tmp/b.pptx",
        "/tmp/c.txt",
    ])
    assert kind == "presentation"


def test_suggest_actions_for_type_returns_expected_actions():
    actions = suggest_actions_for_type("rfq")
    assert "Review RFQ" in actions
    assert "Store RFQ" in actions


def test_execute_prompt_help_returns_capabilities(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    result = execute_prompt("help", backend)

    assert "KNOWLEDGE" in result
    assert "SYSTEM" in result


def test_execute_prompt_remember_this_stores_note(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "Reference").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    result = execute_prompt("remember this Team meeting decision is approved for rollout.", backend)

    assert "Stored successfully" in result
    assert list((vault / "Reference").glob("*.md"))


def test_execute_prompt_store_email_stores_note(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "eMails to Remember").mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    payload = "From: ops@example.com\nSubject: Daily status\n\nPlease complete by 2026-07-10."
    result = execute_prompt(f"store this email {payload}", backend)

    assert "Stored successfully" in result
    assert list((vault / "eMails to Remember").glob("*.md"))


def test_execute_prompt_read_from_vault_returns_knowledge_block(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "Customers").mkdir(parents=True)
    (vault / "Customers" / "acme.md").write_text(
        "---\n"
        "title: \"ACME Notes\"\n"
        "summary: \"ACME contract and timeline details\"\n"
        "---\n\n"
        "ACME contract timeline and review notes.",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    result = execute_prompt("read from vault ACME contract timeline", backend)

    assert "Knowledge retrieval" in result
    assert "Source note paths:" in result


def test_execute_prompt_general_question_routes_to_chat(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    monkeypatch.setattr(gui_module, "_run_general_chat", lambda _prompt, _backend: "[OK] general chat")

    result = execute_prompt("How many calories are on this plate?", backend)

    assert "general chat" in result


def test_execute_prompt_weather_routes_to_web_search(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    class _FakeObsidian:
        def search(self, *_args, **_kwargs):
            raise AssertionError("weather prompts should not search vault notes")

    backend.obsidian = _FakeObsidian()
    result = execute_prompt("how will the weather be tomorrow in Basel, Bern and Berlin?", backend)

    assert "Source mode: Direct" in result
    assert "requires explicit web mode" in result


def test_extract_customer_project_from_text():
    customer, project = gui_module._extract_customer_project("Customer: TDK\nProject: Air Freight Bid")
    assert customer == "TDK"
    assert project == "Air Freight Bid"


def test_run_general_chat_status_payload_collision_is_handled(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    class _FakeOllama:
        def __init__(self, _config):
            pass

        def chat(self, **kwargs):
            on_status = kwargs.get("on_status")
            if on_status:
                on_status("streaming_tokens", {"service": "ollama", "token_count": 3})
                on_status("completed", {"service": "ollama", "tokens": 3})
            return "27"

    monkeypatch.setattr(gui_module, "OllamaClient", _FakeOllama)

    captured = []

    def _on_status(stage: str, payload: dict) -> None:
        captured.append((stage, payload.get("service")))

    hooks = gui_module.ExecutionHooks(on_status=_on_status)
    result = gui_module._run_general_chat("What is 3x3x3?", backend, hooks=hooks)

    assert "AI response generated" in result
    assert ("streaming_tokens", "ollama") in captured


def test_extract_requested_slide_count_supports_two_slide_prompt():
    assert gui_module._extract_requested_slide_count("Make me a 2-slide PowerPoint about Ollama") == 2
    assert len(gui_module._build_presentation_outlines(2)) == 2


def test_timeout_threshold_for_presentation_uses_420_seconds():
    assert gui_module._timeout_threshold_for_workflow("presentation", "ollama") == 420
    assert gui_module._timeout_threshold_for_workflow("chat", "presenton") == 420
    assert gui_module._timeout_threshold_for_workflow("chat", "knowledge", web_search=True) == 90
    assert gui_module._timeout_threshold_for_workflow("chat", "ollama") == 30


def test_execute_prompt_password_lookup_uses_vault_only(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "Reference").mkdir(parents=True)
    (vault / "Reference" / "swisslos.md").write_text(
        "---\n"
        "title: \"Swisslos Access\"\n"
        "summary: \"Credential reference\"\n"
        "---\n\n"
        "Swisslos password: SWS-2026-BlueLine\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module.settings, "obsidian_vault", vault)
    backend = create_backend()

    result = execute_prompt("Can you find the password for Swisslos in my notes?", backend)

    assert "Vault credential lookup completed" in result
    assert "SWS-2026-BlueLine" in result
    assert "Source note path:" in result


def test_open_latest_result_opens_first_artifact(tmp_path: Path, monkeypatch):
    target = tmp_path / "deck.pptx"
    target.write_bytes(b"data")

    opened = {"path": None}

    def _fake_open_url(url):
        opened["path"] = url.toLocalFile()
        return True

    monkeypatch.setattr(gui_module.QDesktopServices, "openUrl", _fake_open_url)

    dummy = type("DummyWindow", (), {})()
    dummy._last_artifacts = [target]

    gui_module.MainWindow.open_latest_result(dummy)

    assert opened["path"] == str(target)


def test_reveal_latest_result_uses_finder_reveal_on_macos(tmp_path: Path, monkeypatch):
    target = tmp_path / "deck.pptx"
    target.write_bytes(b"data")

    called = {"args": None}

    def _fake_popen(args):
        called["args"] = args
        return object()

    monkeypatch.setattr(gui_module, "sys", type("DummySys", (), {"platform": "darwin"})())
    monkeypatch.setattr(gui_module.subprocess, "Popen", _fake_popen)

    dummy = type("DummyWindow", (), {})()
    dummy._last_artifacts = [target]

    gui_module.MainWindow.reveal_latest_result(dummy)

    assert called["args"] == ["open", "-R", str(target)]


def test_copy_latest_result_path_copies_first_artifact(tmp_path: Path, monkeypatch):
    target = tmp_path / "deck.pptx"
    target.write_bytes(b"data")

    copied = {"text": None}

    class _Clipboard:
        def setText(self, text):
            copied["text"] = text

    class _FakeApp:
        @staticmethod
        def clipboard():
            return _Clipboard()

    class _StatusBar:
        def showMessage(self, _text, _timeout):
            return None

    monkeypatch.setattr(gui_module, "QApplication", _FakeApp)

    dummy = type("DummyWindow", (), {})()
    dummy._last_artifacts = [target]
    dummy.statusBar = lambda: _StatusBar()

    gui_module.MainWindow.copy_latest_result_path(dummy)

    assert copied["text"] == str(target)

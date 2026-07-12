from __future__ import annotations

from pathlib import Path
import builtins

from app.email.parsers import EmailParser
from app.email.workflow import EmailWorkflow
from app.obsidian.client import ObsidianClient, ObsidianConfig


def test_email_parser_parses_and_summarizes_message():
    parser = EmailParser()
    message = parser.parse_message(
        {
            "id": "msg-1",
            "subject": "Q3 Planning Update",
            "from": "ceo@example.com",
            "to": ["ops@example.com"],
            "text": "Please prepare the Q3 budget summary and delivery schedule.",
            "attachments": [{"name": "budget.xlsx", "size": 1024}],
        }
    )

    summary = parser.summarize(message)

    assert message.message_id == "msg-1"
    assert message.attachments[0].filename == "budget.xlsx"
    assert summary.attachment_count == 1
    assert "q3" in summary.summary.lower() or "budget" in summary.summary.lower()


def test_email_parser_parses_eml_file(tmp_path: Path):
    parser = EmailParser()
    eml_path = tmp_path / "message.eml"
    eml_path.write_text(
        "\n".join(
            [
                "From: ceo@example.com",
                "To: ops@example.com",
                "Subject: Weekly Update",
                "Message-ID: <msg-2@example.com>",
                "Date: Tue, 07 Jul 2026 10:00:00 +0000",
                "Content-Type: text/plain; charset=utf-8",
                "",
                "Please share the delivery timeline and budget status.",
            ]
        ),
        encoding="utf-8",
    )

    message = parser.parse_eml_file(eml_path)
    summary = parser.summarize(message)

    assert message.provider == "eml"
    assert message.source_path and message.source_path.endswith("message.eml")
    assert "Weekly Update" in message.subject
    assert summary.provider == "eml"


def test_email_parser_detects_entities_and_actions():
    parser = EmailParser()
    message = parser.parse_text_email(
        "\n".join(
            [
                "From: jane.doe@example.com",
                "To: team@example.com",
                "Subject: Project Apollo weekly sync",
                "Date: Tue, 07 Jul 2026 10:00:00 +0000",
                "",
                "Client: ACME Corp",
                "Project: Apollo",
                "Please send the budget draft by July 14, 2026.",
                "Follow up with John Smith next week.",
                "Risk: vendor delay can impact deployment.",
                "Decision: approved option B.",
            ]
        )
    )

    entities = parser.detect_entities(message)
    actions = parser.extract_actions(message)

    assert entities.customers
    assert entities.projects
    assert entities.deadlines
    assert entities.people
    assert entities.email_addresses
    assert entities.organizations
    assert entities.people_confidence
    assert actions.todos
    assert actions.follow_ups
    assert actions.risks
    assert actions.decisions
    assert "2026-07-14" in actions.deadlines


def test_email_workflow_builds_context_with_obsidian_and_memory_hits(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Projects").mkdir(parents=True, exist_ok=True)
    (vault / "Projects" / "apollo.md").write_text(
        "---\n"
        "summary: \"Apollo customer delivery and budget notes\"\n"
        "---\n\n"
        "Project Apollo customer timeline and delivery plan.",
        encoding="utf-8",
    )

    obsidian = ObsidianClient(ObsidianConfig(vault_path=vault))
    workflow = EmailWorkflow()
    result = workflow.process(
        "From: ceo@example.com\nSubject: Apollo budget\n\nPlease share the Apollo plan by 2026-07-20.",
        obsidian=obsidian,
    )

    assert result.summary.summary
    assert "Email workflow context" in result.response_context
    assert result.obsidian_hits


def test_parse_msg_file_reports_install_hint(monkeypatch, tmp_path: Path):
    parser = EmailParser()
    msg_path = tmp_path / "sample.msg"
    msg_path.write_text("dummy", encoding="utf-8")

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "extract_msg":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    try:
        parser.parse_msg_file(msg_path)
    except ValueError as exc:
        assert "pip install extract-msg" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing extract-msg dependency")

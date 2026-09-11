"""Diagnostic redaction contracts."""

from __future__ import annotations

from infrastructure.llm.redaction import redact_diagnostic


def test_redact_diagnostic_neutralizes_log_control_characters() -> None:
    value = "provider failed\r\nforged=warning\tsecret=sk-unit-test-secret\x00tail"

    redacted = redact_diagnostic(value, limit=300)

    assert "\r" not in redacted
    assert "\n" not in redacted
    assert "\t" not in redacted
    assert "\x00" not in redacted
    assert "sk-unit-test-secret" not in redacted
    assert "forged=warning" in redacted

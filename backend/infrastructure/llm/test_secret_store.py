"""Security contracts for encrypted LLM credential storage."""

from __future__ import annotations

from infrastructure.llm.secret_store import fingerprint_secret


def test_secret_fingerprint_is_stable_keyed_and_domain_separated() -> None:
    secret = "unit-test-account-key"

    first = fingerprint_secret(secret, purpose="account-llm-api-key")
    second = fingerprint_secret(secret, purpose="account-llm-api-key")
    other_purpose = fingerprint_secret(secret, purpose="another-secret-kind")

    assert first == second
    assert len(first) == 64
    assert first != "87de9a16317df4e7f06c96479d6e18951198fd13f3a5f4daef213df277e73ce9"
    assert first != other_purpose


def test_secret_fingerprint_rejects_empty_values_and_purposes() -> None:
    for secret, purpose in (("", "account-llm-api-key"), ("value", "")):
        try:
            fingerprint_secret(secret, purpose=purpose)
        except ValueError:
            pass
        else:  # pragma: no cover - explicit security assertion
            raise AssertionError("empty fingerprint inputs must be rejected")

"""Offline guards for the private editorial prompt comparison runner."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.editorial_prompt_ab import (
    BASELINE_SHA,
    EXPECTED_EFFORT,
    EXPECTED_MODEL,
    EXPECTED_PROVIDER,
    ProfileMismatchError,
    RequestLedger,
    _ensure_private_output,
    _mark_interrupted_cases,
    _validate_request_ledger,
    _verify_owner_connection,
    extract_system_prompt,
    validate_profile,
)
from infrastructure.llm.schemas import LLMCallRequest
from modules.assistant.editorial import _SYSTEM


def _state(*, limit: int) -> dict:
    return {
        "cases": {},
        "request_count": 0,
        "request_limit": limit,
        "dependency_failure_streak": 0,
        "paused_reason": None,
        "observations": [],
    }


class FakeLLMClient:
    model_name = EXPECTED_MODEL
    profile_summary = {"provider_id": EXPECTED_PROVIDER, "model": EXPECTED_MODEL}
    cost_routing = {"enabled": False}

    def __init__(
        self, *, provider=EXPECTED_PROVIDER, model=EXPECTED_MODEL, effort=EXPECTED_EFFORT
    ):
        self.profile_summary = {"provider_id": provider, "model": model}
        self.effort = effort

    def resolve_request_defaults(self, request: LLMCallRequest) -> LLMCallRequest:
        return request.model_copy(
            update={
                "model": self.profile_summary["model"],
                "extra": {"reasoning_effort": self.effort},
            }
        )


def test_frozen_and_candidate_prompts_are_distinct() -> None:
    repo = Path(__file__).resolve().parents[3]
    baseline_prompt = extract_system_prompt(repo, BASELINE_SHA)
    assert _SYSTEM != baseline_prompt
    assert extract_system_prompt(repo, BASELINE_SHA) == baseline_prompt


def test_private_output_stays_outside_repo_and_restricts_permissions(
    tmp_path: Path,
) -> None:
    repo = Path(__file__).resolve().parents[3]
    output = tmp_path / "editorial-run"
    directories = _ensure_private_output(output, repo)

    assert all(path.stat().st_mode & 0o077 == 0 for path in (output, *directories))
    with pytest.raises(ValueError, match="outside the repository"):
        _ensure_private_output(repo / "private-output", repo)


def test_request_ledger_enforces_global_cap_and_case_stop() -> None:
    state = _state(limit=1)
    ledger = RequestLedger(state, lambda: None, request_limit=1)
    ledger.begin_arm("case-a", "baseline", raw_path="/private/raw.json")
    ledger.reserve("case-a", "baseline", metadata={})

    with pytest.raises(RuntimeError, match="global request limit"):
        ledger.reserve("case-a", "baseline", metadata={})
    assert state["request_count"] == 1

    state = _state(limit=5)
    ledger = RequestLedger(state, lambda: None, request_limit=5)
    ledger.begin_arm("case-a", "baseline", raw_path="/private/raw.json")
    receipt = ledger.reserve("case-a", "baseline", metadata={})
    ledger.finish_request(
        "case-a",
        "baseline",
        receipt,
        status="failed",
        metadata={},
        external_failure=True,
    )
    with pytest.raises(RuntimeError, match="already stopped"):
        ledger.begin_arm("case-a", "candidate", raw_path="/private/raw.json")
    _validate_request_ledger(state)


def test_three_external_failures_pause_and_interrupted_cases_are_not_replayed() -> None:
    state = _state(limit=4)
    ledger = RequestLedger(state, lambda: None, request_limit=4)
    for index in range(3):
        case_id = f"case-{index}"
        ledger.begin_arm(case_id, "baseline", raw_path=f"/private/{index}.json")
        receipt = ledger.reserve(case_id, "baseline", metadata={})
        ledger.finish_request(
            case_id,
            "baseline",
            receipt,
            status="failed",
            metadata={},
            external_failure=True,
        )
    assert state["paused_reason"] == "three_consecutive_dependency_failures"

    interrupted = _state(limit=2)
    ledger = RequestLedger(interrupted, lambda: None, request_limit=2)
    ledger.begin_arm("case-i", "candidate", raw_path="/private/i.json")
    ledger.reserve("case-i", "candidate", metadata={})
    _mark_interrupted_cases(interrupted, lambda: None)
    assert interrupted["cases"]["case-i"]["status"] == "stopped"
    assert interrupted["paused_reason"] == "interrupted_request_unknown"
    assert interrupted["observations"][0]["status"] == "unknown"
    _validate_request_ledger(interrupted)
    with pytest.raises(RuntimeError, match="already stopped"):
        ledger.begin_arm("case-i", "candidate", raw_path="/private/i.json")


def test_connection_mismatch_fails_before_any_model_request() -> None:
    client = FakeLLMClient(effort="high")
    provider_calls = []

    with pytest.raises(ProfileMismatchError, match="codex/gpt-6-luna"):
        validate_profile(client)
    assert provider_calls == []


async def test_unverified_owner_connection_refuses_start(monkeypatch) -> None:
    class FakeSettingsService:
        async def get_account_llm_connections(self, _db, *, owner_id):
            return SimpleNamespace(
                active_provider_id=EXPECTED_PROVIDER,
                providers=[
                    SimpleNamespace(
                        provider_id=EXPECTED_PROVIDER,
                        connected=False,
                        verified_at=None,
                        model=EXPECTED_MODEL,
                    )
                ],
            )

    monkeypatch.setattr("evals.editorial_prompt_ab.SettingsService", FakeSettingsService)
    with pytest.raises(ProfileMismatchError, match="Verified active owner"):
        await _verify_owner_connection(object())

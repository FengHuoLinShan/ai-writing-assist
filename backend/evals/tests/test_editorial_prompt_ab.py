"""Offline guards for the private editorial prompt comparison runner."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from evals import editorial_prompt_ab as runner
from evals.editorial_prompt_ab import (
    BASELINE_SHA,
    CONDITION_CARRY_FORWARD,
    EXPECTED_EFFORT,
    EXPECTED_MODEL,
    EXPECTED_PROVIDER,
    ProfileMismatchError,
    RequestLedger,
    _check_smoke,
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


def test_ab_prompts_and_internal_ledger_switch_are_distinct() -> None:
    repo = Path(__file__).resolve().parents[3]
    dataset, cases = runner._load_cases(repo)
    candidate_sha = runner._git(repo, "rev-parse", "HEAD")
    manifest = runner._manifest(dataset, cases, repo, BASELINE_SHA, candidate_sha)

    assert manifest["baseline_prompt"] == extract_system_prompt(repo, BASELINE_SHA)
    assert manifest["candidate_prompt"] == extract_system_prompt(repo, candidate_sha)
    assert manifest["baseline_prompt"] != manifest["candidate_prompt"]
    assert CONDITION_CARRY_FORWARD == {"baseline": False, "candidate": True}
    assert manifest["request_limit"] == 490
    assert _SYSTEM == manifest["candidate_prompt"]

    restarted = runner._manifest(
        dataset,
        cases,
        repo,
        BASELINE_SHA,
        candidate_sha,
        prior_run={
            "manifest_hash": "prior",
            "state_sha256": "state",
            "reserved_requests": 20,
        },
    )
    assert restarted["request_budget_offset"] == 20
    assert restarted["manifest_hash"] != manifest["manifest_hash"]


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


def test_request_ledger_counts_prior_run_reservations_against_same_cap() -> None:
    state = _state(limit=3)
    state["request_budget_offset"] = 2
    ledger = RequestLedger(state, lambda: None, request_limit=3)
    ledger.begin_arm("case-a", "baseline", raw_path="/private/raw.json")
    ledger.reserve("case-a", "baseline", metadata={})

    with pytest.raises(RuntimeError, match="global request limit"):
        ledger.reserve("case-a", "baseline", metadata={})
    assert state["request_count"] == 1
    _validate_request_ledger(state)


def test_prior_run_budget_requires_matching_private_stopped_ledger(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    state_path = private / "state.json"
    manifest_core = {
        "dataset_hash": "dataset",
        "baseline_sha": BASELINE_SHA,
        "candidate_sha": "candidate",
        "provider_id": EXPECTED_PROVIDER,
        "model": EXPECTED_MODEL,
        "reasoning_effort": EXPECTED_EFFORT,
        "request_limit": 490,
    }
    prior_manifest_hash = runner._canonical_hash(manifest_core)
    manifest = {**manifest_core, "manifest_hash": prior_manifest_hash}
    prior_state = {
        "manifest_hash": prior_manifest_hash,
        "manifest": manifest,
        "request_limit": 490,
        "request_count": 1,
        "dependency_failure_streak": 0,
        "paused_reason": "unknown_usage",
        "observations": [{"status": "unknown", "error_kind": "CancelledError"}],
        "cases": {
            "case-a": {
                "status": "stopped",
                "arms": {
                    "baseline": {
                        "requests": [
                            {"status": "unknown", "confirmed_provider_attempt": True}
                        ]
                    }
                },
            }
        },
    }
    runner._write_private_json(state_path, prior_state)

    record = runner._prior_run_usage(
        state_path,
        manifest_core,
        Path(__file__).resolve().parents[3],
    )
    assert record == {
        "manifest_hash": prior_manifest_hash,
        "state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "reserved_requests": 1,
    }


def test_parallel_runner_is_bounded_and_runs_each_arm_once() -> None:
    async def scenario():
        active = 0
        peak = 0
        seen = []

        async def run_one(item):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            seen.append(item)
            active -= 1

        await runner._run_parallel(range(6), run_one)
        assert peak == runner.PARALLEL_ARMS == 2
        assert sorted(seen) == list(range(6))

    asyncio.run(scenario())


def test_run_lock_rejects_a_second_process_for_the_same_output(tmp_path: Path) -> None:
    output = tmp_path / "editorial-run"
    output.mkdir(mode=0o700)
    with runner._run_lock(output):
        with pytest.raises(RuntimeError, match="another runner process"):
            with runner._run_lock(output):
                pass
    assert (output / ".runner.lock").stat().st_mode & 0o077 == 0


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


def test_smoke_requires_a_forwarded_and_validator_accepted_prior_quote(tmp_path):
    case_id = "unique_key_contradiction"
    state = {
        "cases": {
            case_id: {
                "status": "complete",
                "arms": {
                    condition: {
                        "requests": [
                            {"status": "succeeded"} for _ in range(7)
                        ]
                    }
                    for condition in ("baseline", "candidate")
                },
            }
        }
    }
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    first_quote = "钥匙在第一章被熔化"
    for condition in ("baseline", "candidate"):
        raw = {
            "status": "completed",
            "report": {
                "coverage_complete": True,
                "all_findings": [],
            },
            "validator_survivors": 1,
            "requests": [],
        }
        if condition == "candidate":
            raw["requests"] = [
                {
                    "chapter_index": 1,
                    "prior_evidence": [],
                    "output": {
                        "carry_forward": [
                            {"chapter_index": 1, "quote": first_quote}
                        ]
                    },
                },
                {
                    "chapter_index": 3,
                    "prior_evidence": [
                        {"chapter_index": 1, "quote": first_quote}
                    ],
                    "output": {},
                },
            ]
            raw["report"]["all_findings"] = [
                {
                    "evidence": [
                        {"chapter_index": 1, "quote": first_quote},
                        {"chapter_index": 3, "quote": "完好钥匙打开了门"},
                    ]
                }
            ]
        (raw_dir / f"{case_id}.{condition}.json").write_text(json.dumps(raw))

    persisted = []
    _check_smoke(state, raw_dir, lambda: persisted.append(True))
    assert state["smoke_status"] == "passed"
    assert persisted == [True]

    b_path = raw_dir / f"{case_id}.candidate.json"
    b_raw = json.loads(b_path.read_text())
    b_raw["report"]["all_findings"] = []
    b_path.write_text(json.dumps(b_raw))
    state.pop("smoke_status")
    with pytest.raises(RuntimeError, match="forward and validate"):
        _check_smoke(state, raw_dir, lambda: persisted.append(False))
    assert state["paused_reason"] == "smoke_cross_chapter_evidence_not_validated"
    assert persisted[-1] is False


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


async def test_arm_persists_json_state_path_without_starting_provider(
    tmp_path: Path, monkeypatch
) -> None:
    repo = Path(__file__).resolve().parents[3]
    output = tmp_path / "editorial-run"
    raw_dir, blind_dir, mapping_dir = _ensure_private_output(output, repo)
    state_path = output / "state.json"
    state = {
        "state_path": str(state_path),
        "cases": {},
        "request_count": 0,
        "request_limit": 406,
        "dependency_failure_streak": 0,
        "paused_reason": None,
        "observations": [],
    }
    ledger = RequestLedger(
        state,
        lambda: runner._write_private_json(Path(state["state_path"]), state),
        request_limit=406,
    )
    project = SimpleNamespace(id=uuid4())
    review = SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        llm_snapshot_json={
            "profile": {
                "provider_id": EXPECTED_PROVIDER,
                "model": EXPECTED_MODEL,
                "native_wrapper": {
                    "version": runner.CODEX_TEXT_ADAPTER_VERSION,
                    "instructions_hash": runner.CODEX_TEXT_INSTRUCTIONS_HASH,
                },
                "connection_verified": True,
            }
        },
    )

    @asynccontextmanager
    async def open_client(*_args, **_kwargs):
        yield FakeLLMClient()

    async def make_project(*_args, **_kwargs):
        return project

    async def submit_review(*_args, **_kwargs):
        return review

    async def stop_before_worker(request_db, **_kwargs):
        assert request_db.task_checkpoint_enabled is True
        raise RuntimeError("stop before provider")

    monkeypatch.setattr(runner, "open_project_llm_client", open_client)
    monkeypatch.setattr(runner, "_make_project", make_project)
    monkeypatch.setattr(runner, "_submit_review", submit_review)
    monkeypatch.setattr(runner, "run_task_inline", stop_before_worker)
    db = SimpleNamespace(info={})

    with pytest.raises(RuntimeError, match="stop before provider"):
        await runner._run_arm(
            db=db,
            case={"id": "S01_hard_contradiction", "chapters": []},
            condition="baseline",
            prompt="test prompt",
            manifest_hash="test-manifest",
            state=state,
            ledger=ledger,
            raw_dir=raw_dir,
            blind_dir=blind_dir,
            mapping_dir=mapping_dir,
        )

    assert state["request_count"] == 0
    assert state["cases"]["S01_hard_contradiction"]["status"] == "stopped"
    assert not hasattr(db, "task_checkpoint_enabled")
    assert json.loads(state_path.read_text())["request_count"] == 0
    raw = json.loads(
        (raw_dir / "S01_hard_contradiction.baseline.json").read_text()
    )
    assert raw["status"] == "stopped"

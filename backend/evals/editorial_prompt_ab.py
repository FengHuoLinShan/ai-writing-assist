"""Run a private, resumable Luna/max comparison of editorial prompts.

This opt-in runner uses only the local disposable codex_luna_runtime_test
database. Raw reports and blind-review artifacts stay outside the repository.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import random
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.engine import make_url

from app.bootstrap import register_container_services
from app.task_runtime import register_task_handlers
from core.config import get_settings
from core.database import get_manager
from core.execution_context import system_execution_scope
from evals.experiment import RequestObservation, experiment_evidence
from evals.schemas import SystemUnderTestProfile
from infrastructure.llm.cli_agent import (
    CODEX_TEXT_ADAPTER_VERSION,
    CODEX_TEXT_INSTRUCTIONS_HASH,
)
from infrastructure.llm.errors import LLMError
from infrastructure.llm.schemas import LLMCallRequest
from infrastructure.tasks.facade import run_task_inline
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.settings_service import SettingsService
from modules.assistant.editorial_contracts import ReviewSubmit
from modules.assistant.editorial_models import EditorialReview
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.editorial_brief import EditorialBrief
from modules.project.facade import open_project_llm_client
from modules.project.models import Project
from modules.writing.models import WritingDraft

BASELINE_SHA = "00d861283e34bdc0ef3f34ee5605c71e1f89c553"
EXPECTED_PROVIDER = "codex"
EXPECTED_MODEL = "gpt-6-luna"
EXPECTED_EFFORT = "max"
REQUESTS_PER_ARM = 7
DIMENSIONS = ["structure", "scene", "line", "copy", "reader"]


class RunStoppedError(RuntimeError):
    """A paid-run guard stopped the current case or the whole run."""


class ProfileMismatchError(RunStoppedError):
    """The current owner/project profile does not match the authorization."""


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _write_private_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _ensure_private_output(output: Path, repo: Path) -> tuple[Path, Path, Path]:
    resolved = output.expanduser().resolve()
    if resolved == repo or resolved.is_relative_to(repo):
        raise ValueError("Private evaluation output must be outside the repository")
    if any((parent / ".git").exists() for parent in (resolved, *resolved.parents)):
        raise ValueError("Private evaluation output cannot be inside a Git worktree")
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(resolved, 0o700)
    raw, blind, mapping = resolved / "raw", resolved / "blind", resolved / "mapping"
    for directory in (raw, blind, mapping):
        if directory.is_symlink():
            raise ValueError("Private output directories cannot be symlinks")
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
    if any(path.is_symlink() for path in resolved.rglob("*")):
        raise ValueError("Private evaluation output cannot contain symlinks")
    return raw, blind, mapping


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def extract_system_prompt(repo: Path, revision: str) -> str:
    source = subprocess.check_output(
        ["git", "show", f"{revision}:backend/modules/assistant/editorial.py"],
        cwd=repo,
        text=True,
    )
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_SYSTEM"
            for target in node.targets
        ):
            prompt = ast.literal_eval(node.value)
            if isinstance(prompt, str):
                return prompt
    raise ValueError(f"No literal _SYSTEM prompt in revision {revision}")


def validate_profile(client: Any) -> dict[str, str]:
    summary = client.profile_summary
    request = client.resolve_request_defaults(LLMCallRequest(messages=[]))
    observed = {
        "provider_id": str(summary.get("provider_id") or ""),
        "model": str(summary.get("model") or client.model_name),
        "request_model": str(request.model or ""),
        "reasoning_effort": str(request.extra.get("reasoning_effort") or ""),
    }
    if (
        observed["provider_id"] != EXPECTED_PROVIDER
        or observed["model"] != EXPECTED_MODEL
        or observed["request_model"] != EXPECTED_MODEL
        or observed["reasoning_effort"] != EXPECTED_EFFORT
    ):
        raise ProfileMismatchError(
            "Project facade profile must be codex/gpt-6-luna with max reasoning"
        )
    routing = getattr(client, "cost_routing", {}) or {}
    if (
        routing.get("enabled")
        and "assistant.editorial" in routing.get("capability_ids", [])
        and routing.get("cheap_model") != EXPECTED_MODEL
    ):
        raise ProfileMismatchError("Editorial cost routing would select another model")
    return observed


class RequestLedger:
    """Durable request reservations and fail-closed case stop rules."""

    def __init__(self, state: dict, persist, *, request_limit: int):
        self.state = state
        self.persist = persist
        self.request_limit = request_limit

    def begin_arm(self, case_id: str, condition: str, *, raw_path: str) -> str:
        case = self.state["cases"].setdefault(case_id, {"status": "running", "arms": {}})
        if case["status"] in {"stopped", "complete"}:
            raise RunStoppedError(f"case {case_id} is already {case['status']}")
        arm = case["arms"].get(condition)
        if arm is not None:
            raise RunStoppedError(f"arm {case_id}/{condition} is already recorded")
        case["arms"][condition] = {
            "status": "running",
            "raw_path": raw_path,
            "requests": [],
        }
        self.persist()
        return f"{case_id}:{condition}"

    def reserve(self, case_id: str, condition: str, *, metadata: dict) -> dict:
        case = self.state["cases"].get(case_id)
        arm = (case or {}).get("arms", {}).get(condition)
        if case is None or case["status"] == "stopped" or arm is None:
            raise RunStoppedError("case is not active")
        if arm["status"] != "running":
            raise RunStoppedError("arm is not active")
        if len(arm["requests"]) >= REQUESTS_PER_ARM:
            raise RunStoppedError("per-arm request limit reached")
        if self.state["request_count"] >= self.request_limit:
            self.state["paused_reason"] = "global_request_limit"
            self.persist()
            raise RunStoppedError("global request limit reached")
        receipt = {
            "request_id": str(uuid4()),
            "status": "started",
            **metadata,
        }
        self.state["request_count"] += 1
        arm["requests"].append(receipt)
        self.persist()
        return receipt

    def finish_request(
        self,
        case_id: str,
        condition: str,
        receipt: dict,
        *,
        status: str,
        metadata: dict,
        external_failure: bool = False,
    ) -> None:
        receipt.update(status=status, **metadata)
        if status != "succeeded":
            case = self.state["cases"][case_id]
            case["status"] = "stopped"
            case["stop_reason"] = status
            case["arms"][condition]["status"] = f"stopped_{status}"
            if status == "unknown":
                self.state["paused_reason"] = "unknown_usage"
            elif external_failure:
                self.state["dependency_failure_streak"] += 1
                if self.state["dependency_failure_streak"] >= 3:
                    self.state["paused_reason"] = "three_consecutive_dependency_failures"
        elif status == "succeeded":
            self.state["dependency_failure_streak"] = 0
        self.persist()

    def complete_arm(self, case_id: str, condition: str) -> None:
        case = self.state["cases"][case_id]
        if case["status"] == "stopped":
            raise RunStoppedError("stopped case cannot complete")
        case["arms"][condition]["status"] = "completed"
        if len(case["arms"]) == 2 and all(
            arm["status"] == "completed" for arm in case["arms"].values()
        ):
            case["status"] = "complete"
        self.persist()


def _record_uncertain_request(state: dict, receipt: dict, condition: str) -> None:
    receipt.update(
        status="unknown",
        usage_unknown=True,
        confirmed_provider_attempt=False,
        provider_attempt_uncertain=True,
    )
    if not any(
        item.get("request_id") == receipt["request_id"] for item in state["observations"]
    ):
        state["observations"].append(
            RequestObservation(
                request_id=receipt["request_id"],
                stage=f"assistant.editorial.{condition}",
                status="unknown",
                error_kind="interrupted_or_unconfirmed",
            ).model_dump(mode="json")
        )


def _mark_interrupted_cases(state: dict, persist) -> None:
    for case in state["cases"].values():
        if case.get("status") != "running":
            continue
        case["status"] = "stopped"
        case["stop_reason"] = "interrupted_process"
        for condition, arm in case.get("arms", {}).items():
            if arm.get("status") == "running":
                arm["status"] = "stopped_interrupted"
                for receipt in arm.get("requests", []):
                    if receipt.get("status") == "started":
                        _record_uncertain_request(state, receipt, condition)
                if any(r.get("usage_unknown") for r in arm.get("requests", [])):
                    state["paused_reason"] = "interrupted_request_unknown"
    persist()


def _validate_request_ledger(state: dict) -> None:
    receipts = [
        receipt
        for case in state["cases"].values()
        for arm in case.get("arms", {}).values()
        for receipt in arm.get("requests", [])
    ]
    if len(receipts) != state["request_count"] or len(receipts) > state["request_limit"]:
        raise RunStoppedError("durable request ledger does not match the global cap")
    if any(
        len(arm.get("requests", [])) > REQUESTS_PER_ARM
        for case in state["cases"].values()
        for arm in case.get("arms", {}).values()
    ):
        raise RunStoppedError("durable request ledger exceeded the per-arm cap")
    observed_attempts = sum(
        bool(receipt.get("confirmed_provider_attempt"))
        or bool(receipt.get("provider_attempt_uncertain"))
        for receipt in receipts
    )
    if observed_attempts != len(state["observations"]):
        raise RunStoppedError(
            "provider request observations do not match the durable ledger"
        )


def _check_smoke(state: dict, raw_dir: Path, persist) -> None:
    case = state["cases"].get("S01_hard_contradiction", {})
    if case.get("status") != "complete":
        raise RunStoppedError("both smoke arms must finish before full evaluation")
    raw_runs = [
        json.loads((raw_dir / f"S01_hard_contradiction.{condition}.json").read_text())
        for condition in ("baseline", "candidate")
    ]
    if any(
        item.get("status") != "completed"
        or not item.get("report", {}).get("coverage_complete")
        for item in raw_runs
    ):
        raise RunStoppedError("smoke output or chapter coverage is incomplete")
    if any(
        len(case["arms"][condition]["requests"]) != REQUESTS_PER_ARM
        or any(
            receipt.get("status") != "succeeded"
            for receipt in case["arms"][condition]["requests"]
        )
        for condition in ("baseline", "candidate")
    ):
        raise RunStoppedError(
            "smoke request accounting did not match seven calls per arm"
        )
    if not any(item.get("validator_survivors", 0) for item in raw_runs):
        state["paused_reason"] = "smoke_validator_not_observed"
        persist()
        raise RunStoppedError("smoke did not produce a source-validated finding")
    state["smoke_status"] = "passed"
    persist()


def _load_cases(repo: Path) -> tuple[dict, list[dict]]:
    path = repo / "backend/evals/datasets/editorial_cases_v3.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if dataset.get("version") != 3 or not dataset.get("cases"):
        raise ValueError("editorial case dataset v3 is required")
    if len({case["id"] for case in dataset["cases"]}) != len(dataset["cases"]):
        raise ValueError("duplicate editorial case IDs")
    for case in dataset["cases"]:
        for chapter in case["chapters"]:
            actual = hashlib.sha256(chapter["content"].encode()).hexdigest()
            if actual != chapter["content_sha256"]:
                raise ValueError(f"chapter hash mismatch: {case['id']}")
    return dataset, dataset["cases"]


def _worker_brief(case: dict) -> dict:
    source = dict(case.get("brief") or {})
    accepted = {
        "target_readers",
        "genre_promise",
        "goals",
        "voice",
        "preserve",
        "intentional_choices",
        "excluded_targets",
    }
    brief = {key: source[key] for key in source.keys() & accepted}
    goals = list(brief.get("goals") or [])
    goals.extend(
        f"{key}：{json.dumps(value, ensure_ascii=False, sort_keys=True)}"
        for key, value in source.items()
        if key not in accepted
    )
    for key in ("case_context", "scope_note"):
        if case.get(key):
            goals.append(f"{key}：{case[key]}")
    brief["goals"] = goals
    return EditorialBrief.model_validate(brief).model_dump(mode="json")


def _effective_scope(case: dict) -> str:
    indices = sorted(chapter["index"] for chapter in case["chapters"])
    if case["scope"] == "book" and indices != list(range(1, indices[-1] + 1)):
        return "range"
    return case["scope"]


def _mapping_with(path: Path, blind_id: str, value: dict) -> dict:
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if blind_id in current:
        raise ValueError("blind ID collision")
    return {**current, blind_id: value}


def _manifest(
    dataset: dict, cases: list[dict], repo: Path, baseline_sha: str, candidate_sha: str
) -> dict:
    baseline_prompt = extract_system_prompt(repo, baseline_sha)
    candidate_prompt = extract_system_prompt(repo, candidate_sha)
    if baseline_prompt == candidate_prompt:
        raise ValueError("baseline and candidate system prompts are identical")
    case_fingerprints = {
        case["id"]: _canonical_hash(
            {
                "scope": _effective_scope(case),
                "brief": _worker_brief(case),
                "chapters": [
                    {
                        "index": item["index"],
                        "title": item.get("title"),
                        "content_sha256": item["content_sha256"],
                    }
                    for item in case["chapters"]
                ],
            }
        )
        for case in cases
    }
    adapter_hash = CODEX_TEXT_INSTRUCTIONS_HASH
    core = {
        "dataset_hash": hashlib.sha256(
            (repo / "backend/evals/datasets/editorial_cases_v3.json").read_bytes()
        ).hexdigest(),
        "case_fingerprints": case_fingerprints,
        "baseline_sha": baseline_sha,
        "candidate_sha": candidate_sha,
        "baseline_prompt_hash": _canonical_hash(baseline_prompt),
        "candidate_prompt_hash": _canonical_hash(candidate_prompt),
        "adapter_version": CODEX_TEXT_ADAPTER_VERSION,
        "adapter_instructions_hash": adapter_hash,
        "provider_id": EXPECTED_PROVIDER,
        "model": EXPECTED_MODEL,
        "reasoning_effort": EXPECTED_EFFORT,
        "request_limit": len(cases) * 2 * REQUESTS_PER_ARM,
        "dimensions": DIMENSIONS,
    }
    return {
        **core,
        "manifest_hash": _canonical_hash(core),
        "baseline_prompt": baseline_prompt,
        "candidate_prompt": candidate_prompt,
    }


def _profile_snapshot(review: EditorialReview) -> None:
    profile = (review.llm_snapshot_json or {}).get("profile") or {}
    expected_wrapper = {
        "version": CODEX_TEXT_ADAPTER_VERSION,
        "instructions_hash": CODEX_TEXT_INSTRUCTIONS_HASH,
    }
    if (
        profile.get("provider_id") != EXPECTED_PROVIDER
        or profile.get("model") != EXPECTED_MODEL
        or profile.get("native_wrapper") != expected_wrapper
        or profile.get("connection_verified") is not True
    ):
        raise ProfileMismatchError(
            "Editorial review snapshot does not match Luna/max adapter"
        )


async def _verify_owner_connection(db) -> dict:
    connections = await SettingsService().get_account_llm_connections(
        db, owner_id=BOOTSTRAP_ACCOUNT_ID
    )
    codex = next(
        (item for item in connections.providers if item.provider_id == EXPECTED_PROVIDER),
        None,
    )
    if (
        connections.active_provider_id != EXPECTED_PROVIDER
        or codex is None
        or not codex.connected
        or codex.verified_at is None
        or codex.model != EXPECTED_MODEL
    ):
        raise ProfileMismatchError(
            "Verified active owner Codex/Luna connection is required"
        )
    return {
        "provider_id": EXPECTED_PROVIDER,
        "model": EXPECTED_MODEL,
        "verified_at": codex.verified_at.isoformat(),
        "adapter_version": CODEX_TEXT_ADAPTER_VERSION,
        "adapter_instructions_hash": CODEX_TEXT_INSTRUCTIONS_HASH,
    }


def _raw_report(report: dict) -> dict:
    def finding(item: dict) -> dict:
        return {
            key: item.get(key)
            for key in (
                "category",
                "judgment",
                "reader_impact",
                "severity",
                "evidence",
                "context_evidence",
                "counterevidence",
                "intent_relation",
                "intent_quote",
                "why_now",
                "unchecked",
                "directions",
                "fingerprint",
            )
            if key in item
        }

    return {
        **report,
        "top_findings": [finding(item) for item in report.get("top_findings", [])],
        "all_findings": [finding(item) for item in report.get("all_findings", [])],
    }


def _blind_report(report: dict) -> dict:
    def finding(item: dict) -> dict:
        result = {
            key: item.get(key)
            for key in (
                "category",
                "judgment",
                "reader_impact",
                "severity",
                "counterevidence",
                "intent_relation",
                "intent_quote",
                "why_now",
                "unchecked",
                "directions",
            )
            if key in item
        }
        result["evidence"] = [
            {"chapter_index": ref["chapter_index"], "quote": ref["quote"]}
            for ref in item.get("evidence", [])
        ]
        result["context_evidence"] = [
            {"source_kind": ref["source_kind"], "quote": ref["quote"]}
            for ref in item.get("context_evidence", [])
        ]
        return result

    return {
        "summary": report.get("summary", ""),
        "findings": [finding(item) for item in report.get("all_findings", [])],
        "checked_chapters": report.get("checked_chapters", []),
        "missing": report.get("missing", []),
        "coverage_complete": report.get("coverage_complete", False),
        "authority": report.get("authority", "editorial_suggestion"),
    }


async def _make_project(db, case: dict, *, manifest_hash: str) -> Project:
    brief = _worker_brief(case)
    project = Project(
        title=f"审读合成样本 {uuid4().hex[:12]}",
        owner_id=BOOTSTRAP_ACCOUNT_ID,
        project_kind="author",
        settings={"editorial_brief_v1": {"version": 0, "brief": brief}},
    )
    db.add(project)
    await db.flush()
    for chapter in case["chapters"]:
        content = chapter["content"]
        db.add(
            WritingDraft(
                novel_id=project.id,
                chapter_index=chapter["index"],
                title=chapter.get("title"),
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                version_number=1,
                status="draft",
                provenance_json={
                    "source": "editorial_eval_v3",
                    "manifest_hash": manifest_hash,
                },
            )
        )
    await db.commit()
    return project


async def _submit_review(db, project: Project, case: dict) -> EditorialReview:
    indices = [chapter["index"] for chapter in case["chapters"]]
    scope = _effective_scope(case)
    request = ReviewSubmit(
        novel_id=project.id,
        operation_id=uuid4(),
        scope=scope,
        start_chapter=min(indices) if scope == "range" else None,
        end_chapter=max(indices) if scope == "range" else None,
        dimensions=DIMENSIONS,
        expected_brief_version=0,
    )
    from modules.assistant.editorial import submit

    view = await submit(db, request)
    return await db.get(EditorialReview, UUID(view["id"]), populate_existing=True)


def _mark_case_stopped(state: dict, case_id: str, reason: str, persist) -> None:
    entry = state["cases"].setdefault(case_id, {"arms": {}})
    entry["status"] = "stopped"
    entry["stop_reason"] = reason
    persist()


async def _run_arm(
    *,
    db,
    case: dict,
    condition: str,
    prompt: str,
    manifest_hash: str,
    state: dict,
    ledger: RequestLedger,
    raw_dir: Path,
    blind_dir: Path,
    mapping_dir: Path,
) -> None:
    case_id = case["id"]
    state_path = Path(state["state_path"])
    case_state = state["cases"].get(case_id, {})
    if case_state.get("status") in {"stopped", "complete"}:
        return
    raw_path = raw_dir / f"{case_id}.{condition}.json"
    ledger.begin_arm(case_id, condition, raw_path=str(raw_path))
    arm = state["cases"][case_id]["arms"][condition]
    raw = {
        "case_id": case_id,
        "condition": condition,
        "manifest_hash": manifest_hash,
        "status": "started",
        "requests": [],
    }
    _write_private_json(raw_path, raw)
    project = await _make_project(db, case, manifest_hash=manifest_hash)
    arm["project_id"] = str(project.id)
    _write_private_json(state_path, state)

    async with open_project_llm_client(db, str(project.id)) as client:
        profile = validate_profile(client)
        current_prompt = prompt
        review = await _submit_review(db, project, case)
        _profile_snapshot(review)
        arm["review_id"] = str(review.id)
        arm["snapshot_profile"] = profile
        _write_private_json(state_path, state)

        async def before_request(
            request_db, _row, worker_client, budget, instructions, payload
        ):
            if worker_client is not client or not instructions.startswith(current_prompt):
                raise ProfileMismatchError(
                    "Worker prompt/client did not match this condition"
                )
            previous = validate_profile(worker_client)
            async with open_project_llm_client(request_db, str(project.id)) as current:
                current_profile = validate_profile(current)
            if previous != current_profile or previous != profile:
                raise ProfileMismatchError(
                    "Owner/project connection changed before request"
                )
            receipt = ledger.reserve(
                case_id,
                condition,
                metadata={
                    "provider_request_id": None,
                    "budget_requests_before": budget.requests,
                    "prompt_tokens_before": budget.prompt_tokens,
                    "completion_tokens_before": budget.completion_tokens,
                    "started_at": time.monotonic(),
                    "instruction_hash": _canonical_hash(instructions),
                    "input_hash": _canonical_hash(payload),
                },
            )
            raw["requests"].append(dict(receipt))
            _write_private_json(raw_path, raw)
            return receipt

        async def after_request(receipt, budget, result, error):
            if receipt is None:
                return
            request_delta = budget.requests - receipt["budget_requests_before"]
            input_delta = budget.prompt_tokens - receipt["prompt_tokens_before"]
            output_delta = budget.completion_tokens - receipt["completion_tokens_before"]
            unknown = bool(budget.pending_usage or budget.usage_unknown)
            if error is None and request_delta == 1 and not unknown:
                status = "succeeded"
            elif request_delta == 1 and unknown:
                status = "unknown"
            elif request_delta == 0:
                status = "not_sent"
            else:
                status = "failed"
            metadata = {
                "confirmed_provider_attempt": request_delta == 1,
                "input_tokens": input_delta
                if request_delta == 1 and not unknown
                else None,
                "output_tokens": output_delta
                if request_delta == 1 and not unknown
                else None,
                "usage_unknown": unknown,
                "error_kind": getattr(error, "error_kind", type(error).__name__)
                if error is not None
                else None,
                "output": result.model_dump(mode="json")
                if isinstance(result, BaseModel)
                else None,
                "duration_ms": max(
                    0.0, (time.monotonic() - receipt["started_at"]) * 1000
                ),
            }
            dependency_failure = isinstance(
                error, (LLMError, TimeoutError, ConnectionError, OSError)
            )
            ledger.finish_request(
                case_id,
                condition,
                receipt,
                status=status,
                metadata=metadata,
                external_failure=dependency_failure,
            )
            raw_receipt = next(
                item
                for item in raw["requests"]
                if item.get("request_id") == receipt["request_id"]
            )
            raw_receipt.update(receipt)
            if request_delta == 1:
                state["observations"].append(
                    RequestObservation(
                        request_id=receipt["request_id"],
                        stage=f"assistant.editorial.{condition}",
                        status=(
                            status
                            if status in {"succeeded", "failed", "unknown"}
                            else "failed"
                        ),
                        input_tokens=metadata["input_tokens"],
                        output_tokens=metadata["output_tokens"],
                        duration_ms=metadata["duration_ms"],
                        error_kind=metadata["error_kind"],
                    ).model_dump(mode="json")
                )
            _write_private_json(raw_path, raw)
            _write_private_json(state_path, state)
            if status != "succeeded":
                raise RunStoppedError(f"case stopped after {status} request")

        db.info["editorial_prompt_ab_options"] = {
            "_system_prompt": prompt,
            "_before_request": before_request,
            "_after_request": after_request,
            "_injected_client": client,
        }
        try:
            task_id = str(review.task_id)
            while True:
                previous_checkpoint = getattr(db, "task_checkpoint_enabled", None)
                db.task_checkpoint_enabled = True
                try:
                    await run_task_inline(
                        db,
                        task_id=task_id,
                        expected_task_type="assistant_editorial_review",
                    )
                finally:
                    if previous_checkpoint is None:
                        delattr(db, "task_checkpoint_enabled")
                    else:
                        db.task_checkpoint_enabled = previous_checkpoint
                current = await db.get(EditorialReview, review.id, populate_existing=True)
                if current.status != "partial":
                    break
                from modules.assistant.editorial import resume

                resumed = await resume(db, str(project.id), review.id)
                task_id = resumed["task_id"]
            if current.status != "completed" or not current.report_json.get(
                "coverage_complete"
            ):
                raise RunStoppedError("review did not complete with full source coverage")
            expected_chapters = sorted(c["index"] for c in case["chapters"])
            if current.report_json.get("checked_chapters") != expected_chapters:
                raise RunStoppedError("review chapter coverage does not match the sample")
            all_findings = current.report_json.get("all_findings", [])
            chapter_text = {item["index"]: item["content"] for item in case["chapters"]}
            for finding in all_findings:
                for evidence in finding.get("evidence", []):
                    if evidence["quote"] not in chapter_text.get(
                        evidence["chapter_index"], ""
                    ):
                        raise RunStoppedError(
                            "validator report contains a non-source quote"
                        )
            raw.update(
                status="completed",
                review_id=str(review.id),
                profile=profile,
                report=_raw_report(current.report_json),
                validator_survivors=len(all_findings),
            )
            _write_private_json(raw_path, raw)
            blind_id = secrets.token_urlsafe(12)
            while any(blind_id in path.name for path in blind_dir.glob("*.json")):
                blind_id = secrets.token_urlsafe(12)
            blind = {
                "blind_id": blind_id,
                "expected_result": case["expected_result"],
                "scope": _effective_scope(case),
                "brief": case.get("brief", {}),
                "case_context": case.get("case_context"),
                "scope_note": case.get("scope_note"),
                "chapters": [
                    {
                        "index": item["index"],
                        "title": item.get("title"),
                        "content": item["content"],
                    }
                    for item in case["chapters"]
                ],
                "evaluation_focus": case["evaluation_focus"],
                "report": _blind_report(current.report_json),
            }
            blind_path = blind_dir / f"{blind_id}.json"
            _write_private_json(blind_path, blind)
            _write_private_json(
                mapping_dir / "blind-map.json",
                _mapping_with(
                    mapping_dir / "blind-map.json",
                    blind_id,
                    {"case_id": case_id, "condition": condition},
                ),
            )
            raw["blind_id"] = blind_id
            raw["status"] = "completed"
            _write_private_json(raw_path, raw)
            ledger.complete_arm(case_id, condition)
        except BaseException as exc:
            for receipt in arm.get("requests", []):
                if receipt.get("status") == "started":
                    _record_uncertain_request(state, receipt, condition)
                    state["paused_reason"] = "interrupted_request_unknown"
            if state["cases"].get(case_id, {}).get("status") != "stopped":
                reason = (
                    "profile_mismatch"
                    if isinstance(exc, ProfileMismatchError)
                    else type(exc).__name__
                )
                _mark_case_stopped(
                    state,
                    case_id,
                    reason,
                    lambda: _write_private_json(state_path, state),
                )
            _write_private_json(state_path, state)
            raw.update(status="stopped", error_kind=type(exc).__name__)
            _write_private_json(raw_path, raw)
            raise
        finally:
            db.info.pop("editorial_prompt_ab_options", None)


async def run(output: Path, *, phase: str, candidate_sha: str) -> dict:
    repo = Path(__file__).resolve().parents[2]
    output = output.expanduser().resolve()
    raw_dir, blind_dir, mapping_dir = _ensure_private_output(output, repo)
    url_value = os.environ.get("DATABASE_URL", "")
    if not url_value:
        raise ValueError("DATABASE_URL is required")
    url = make_url(url_value)
    if (
        url.get_backend_name() != "postgresql"
        or url.database != "codex_luna_runtime_test"
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            "Only the dedicated local codex_luna_runtime_test database is allowed"
        )
    if CODEX_TEXT_ADAPTER_VERSION != "codex-text-v3":
        raise ValueError(
            "Codex text adapter version changed from the reviewed runner profile"
        )
    dataset, cases = _load_cases(repo)
    baseline_sha = BASELINE_SHA
    candidate_sha = _git(repo, "rev-parse", candidate_sha)
    if _git(repo, "merge-base", candidate_sha, "HEAD") != candidate_sha:
        raise ValueError("candidate SHA must be a fixed commit on the current branch")
    fixed_paths = [
        "backend/modules/assistant",
        "backend/modules/project",
        "backend/infrastructure/llm",
        "backend/infrastructure/tasks",
        "backend/evals/editorial_prompt_ab.py",
        "backend/evals/datasets/editorial_cases_v3.json",
    ]
    if _git(repo, "diff", candidate_sha, "HEAD", "--name-only", "--", *fixed_paths):
        raise ValueError(
            "worker inputs or execution code changed after the candidate commit"
        )
    if _git(repo, "diff", "HEAD", "--name-only", "--", *fixed_paths):
        raise ValueError(
            "commit all changes to the evaluation implementation before the run"
        )
    for path in fixed_paths[4:]:
        _git(repo, "ls-files", "--error-unmatch", path)
    manifest = _manifest(dataset, cases, repo, baseline_sha, candidate_sha)
    manifest_path = output.resolve() / "manifest.json"
    state_path = output.resolve() / "state.json"
    if manifest_path.exists():
        saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if saved_manifest.get("manifest_hash") != manifest["manifest_hash"]:
            raise ValueError("manifest changed; use a new private output directory")
        manifest = saved_manifest
    else:
        existing = [
            item
            for item in output.resolve().iterdir()
            if item.name not in {"raw", "blind", "mapping"}
        ]
        if (
            existing
            or any(raw_dir.iterdir())
            or any(blind_dir.iterdir())
            or any(mapping_dir.iterdir())
        ):
            raise ValueError("output directory is non-empty and has no matching manifest")
        _write_private_json(manifest_path, manifest)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("manifest_hash") != manifest["manifest_hash"]:
            raise ValueError("state does not match the fixed manifest")
        _mark_interrupted_cases(state, lambda: _write_private_json(state_path, state))
    else:
        seed = secrets.randbits(64)
        order = [(case["id"], arm) for case in cases for arm in ("baseline", "candidate")]
        random.Random(seed).shuffle(order)
        state = {
            "schema_version": 1,
            "run_id": uuid4().hex,
            "manifest_hash": manifest["manifest_hash"],
            "manifest": {
                key: value
                for key, value in manifest.items()
                if not key.endswith("_prompt")
            },
            "state_path": str(state_path),
            "order_seed": seed,
            "order": order,
            "request_limit": len(cases) * 2 * REQUESTS_PER_ARM,
            "request_count": 0,
            "dependency_failure_streak": 0,
            "paused_reason": None,
            "cases": {},
            "observations": [],
        }
        _write_private_json(state_path, state)
    ledger = RequestLedger(
        state,
        lambda: _write_private_json(state_path, state),
        request_limit=state["request_limit"],
    )
    if state["request_limit"] != manifest["request_limit"]:
        raise RunStoppedError("saved global request cap differs from the fixed manifest")
    _validate_request_ledger(state)
    if state.get("paused_reason"):
        raise RunStoppedError(f"run is paused: {state['paused_reason']}")
    register_container_services()
    register_task_handlers()
    manager = get_manager()
    settings = get_settings()
    if not (settings.assistant_enabled and settings.assistant_editorial_enabled):
        raise ValueError("Assistant editorial review must be enabled before the run")
    async with manager.session() as db:
        with system_execution_scope():
            if phase == "smoke":
                smoke_cases = [
                    case for case in cases if case["id"] == "S01_hard_contradiction"
                ]
                if not smoke_cases:
                    raise ValueError("Smoke sample S01_hard_contradiction is missing")
                run_order = [
                    item for item in state["order"] if item[0] == smoke_cases[0]["id"]
                ]
            else:
                smoke_case = state.get("cases", {}).get("S01_hard_contradiction", {})
                if (
                    state.get("smoke_status") != "passed"
                    or smoke_case.get("status") != "complete"
                ):
                    raise ValueError(
                        "Both smoke arms must complete before full evaluation"
                    )
                run_order = state["order"]
            state["owner_connection"] = await _verify_owner_connection(db)
            _write_private_json(state_path, state)
            for case_id, condition in run_order:
                if state.get("paused_reason"):
                    break
                case_state = state["cases"].get(case_id, {})
                if case_state.get("status") in {"complete", "stopped"}:
                    continue
                case = next(item for item in cases if item["id"] == case_id)
                prompt = manifest[f"{condition}_prompt"]
                try:
                    await _run_arm(
                        db=db,
                        case=case,
                        condition=condition,
                        prompt=prompt,
                        manifest_hash=manifest["manifest_hash"],
                        state=state,
                        ledger=ledger,
                        raw_dir=raw_dir,
                        blind_dir=blind_dir,
                        mapping_dir=mapping_dir,
                    )
                except ProfileMismatchError:
                    state["paused_reason"] = "profile_mismatch"
                    _write_private_json(state_path, state)
                    raise
                except ProjectLLMConfigurationError:
                    state["paused_reason"] = "profile_mismatch"
                    _write_private_json(state_path, state)
                    raise
                except RunStoppedError:
                    if state.get("paused_reason"):
                        break
                    continue
                except Exception as exc:
                    if state.get("cases", {}).get(case_id, {}).get("status") != "stopped":
                        _mark_case_stopped(
                            state,
                            case_id,
                            type(exc).__name__,
                            lambda: _write_private_json(state_path, state),
                        )
                    if state.get("paused_reason"):
                        break
                    continue
            _validate_request_ledger(state)
            _write_private_json(state_path, state)
            if phase == "smoke":
                _check_smoke(
                    state,
                    raw_dir,
                    lambda: _write_private_json(state_path, state),
                )
    await manager.close()
    observations = [
        RequestObservation.model_validate(item) for item in state["observations"]
    ]
    profile_hash = _canonical_hash(
        {
            key: state["manifest"][key]
            for key in ("provider_id", "model", "reasoning_effort", "adapter_version")
        }
    )
    source_fingerprints = {
        case["id"]: _canonical_hash(
            [chapter["content_sha256"] for chapter in case["chapters"]]
        )
        for case in cases
    }
    evidence = experiment_evidence(
        dataset=dataset,
        source_fingerprints=source_fingerprints,
        implementation_files=[
            repo / "backend/modules/assistant/editorial.py",
            repo / "backend/evals/editorial_prompt_ab.py",
            repo / "backend/evals/datasets/editorial_cases_v3.json",
        ],
        receipts=observations,
        effective_profile=SystemUnderTestProfile(
            provider_id=EXPECTED_PROVIDER,
            model=EXPECTED_MODEL,
            profile_hash=profile_hash,
        ),
        reasoning_effort=EXPECTED_EFFORT,
        observation_mode="live",
    )
    _write_private_json(raw_dir / "experiment-evidence.json", evidence)
    summary = {
        "manifest_hash": manifest["manifest_hash"],
        "candidate_sha": candidate_sha,
        "request_limit": state["request_limit"],
        "reserved_requests": state["request_count"],
        "confirmed_provider_requests": sum(
            item.status in {"succeeded", "failed", "unknown"}
            and item.error_kind != "interrupted_or_unconfirmed"
            for item in observations
        ),
        "uncertain_provider_requests": sum(
            item.error_kind == "interrupted_or_unconfirmed" for item in observations
        ),
        "unknown_usage_requests": sum(item.status == "unknown" for item in observations),
        "dependency_failure_streak": state["dependency_failure_streak"],
        "paused_reason": state["paused_reason"],
        "case_statuses": {
            key: value.get("status") for key, value in state["cases"].items()
        },
    }
    _write_private_json(raw_dir / "summary.json", summary)
    _write_private_json(state_path, state)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("smoke", "full"), required=True)
    parser.add_argument("--candidate-sha", default="HEAD")
    args = parser.parse_args()
    asyncio.run(run(args.output, phase=args.phase, candidate_sha=args.candidate_sha))


if __name__ == "__main__":
    main()

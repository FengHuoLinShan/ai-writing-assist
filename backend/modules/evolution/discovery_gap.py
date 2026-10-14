"""Explicit author exclusion of one unavailable optional discovery generation.

The original journal and receipt remain immutable evidence of an unknown result.
This is a scope decision, never billing reconciliation or a replacement output.
"""

import json
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

GAPS_KEY = "author_confirmed_discovery_gaps"


class DiscoveryGapConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation_id: UUID
    attempt_id: str = Field(min_length=1, max_length=120)
    journal_key: str = Field(pattern=r"^scene_discovery_(0|[1-9][0-9]*)$")
    expected_frozen_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    accept_unchecked_gap: Literal[True]

    @field_validator("accept_unchecked_gap", mode="before")
    @classmethod
    def require_explicit_consent(cls, value):
        if value is not True:
            raise ValueError("必须明确接受未检查缺口")
        return value


def gap_scope(frozen, key):
    from modules.evolution.discovery import _discovery_envelope, method_fingerprint

    payload = frozen.payload
    prepared = payload.get("discovery_preparation") or {}
    index = int(key.removeprefix("scene_discovery_"))
    batches = prepared.get("batches", [])
    journal = payload.get(key) or {}
    receipt = journal.get("paid_call_receipt") or {}
    read_set = journal.get("read_set") or {}
    if (
        payload.get("discovery_version") != 1
        or payload.get("category_rescan")
        or payload.get("world_audit_supplement")
        or index >= len(batches)
        or index in prepared.get("unsupported_batches", [])
        or prepared.get("method_fingerprint") != method_fingerprint()
        or journal.get("stage") != "failed"
        or "result" in journal
        or receipt.get("outcome") != "failed_final"
        or receipt.get("provider") != "codex"
        or receipt.get("model") != "gpt-6-luna"
        or read_set.get("consumer") != "scene_discovery"
        or not read_set.get("model_fingerprint")
        or journal.get("input_hash")
        != content_hash(_discovery_envelope(frozen, prepared, batches[index]))
        or any(
            candidate == f"scene_discovery_review_{index}"
            or candidate.startswith(f"scene_discovery_identity_{index}_")
            or candidate == f"discovery_no_action_{index}"
            for candidate in payload
        )
    ):
        raise ConflictError("该记录不能确认为未检查发现缺口；原请求保持不变")
    return {
        "novel_id": frozen.novel_id,
        "run_id": frozen.run_id,
        "attempt_id": frozen.attempt_id,
        "owner_epoch": frozen.owner_epoch,
        "source_manifest_hash": frozen.source_manifest_hash,
        "previous_receipt": frozen.previous_receipt,
        "previous_prefix": frozen.previous_committed_prefix.model_dump(mode="json")
        if frozen.previous_committed_prefix
        else None,
        "scene_index": payload["scene_index"],
        "source_binding_hash": content_hash(payload.get("source_binding")),
        "preparation_hash": content_hash(prepared),
        "journal_key": key,
        "batch_index": index,
        "journal_hash": content_hash(journal),
        "input_hash": journal["input_hash"],
        "model_fingerprint": read_set["model_fingerprint"],
    }


def confirmed_discovery_gaps(frozen):
    """Revalidate immutable scope on every resume, compile and receipt write."""
    gaps = frozen.payload.get(GAPS_KEY, [])
    keys = set()
    for gap in gaps:
        try:
            confirmation = DiscoveryGapConfirmation.model_validate_json(
                json.dumps(gap["confirmation"])
            )
            key = gap["scope"]["journal_key"]
            if (
                gap.get("version") != 1
                or gap.get("authorization_source") != "author_confirmation"
                or gap.get("accept_unchecked_gap") is not True
                or re.fullmatch(r"scene_discovery_(0|[1-9][0-9]*)", key) is None
                or key in keys
                or gap["scope"] != gap_scope(frozen, key)
                or confirmation.accept_unchecked_gap is not True
                or gap.get("confirmation", {}).get("original_request_hash")
                != gap.get("original_request_hash")
                or gap.get("confirmation", {}).get("operation_id")
                != gap.get("operation_id")
                or gap.get("confirmation", {}).get("attempt_id") != frozen.attempt_id
                or gap.get("confirmation", {}).get("journal_key") != key
            ):
                raise ConflictError("未检查缺口的确认范围已变化")
        except (KeyError, TypeError, ValueError) as error:
            raise ConflictError("未检查缺口的确认记录不完整") from error
        keys.add(key)
    return gaps


async def confirm_discovery_unknown_gap(db, novel_id, run_key, confirmation):
    """Owner-confirmed, compare-and-set scope change; no provider I/O/commit."""
    from infrastructure.tasks.facade import (
        list_task_lifecycle_contracts,
        update_task_projection,
    )
    from modules.evolution.pipeline import SceneSourceBinding, _source_verifier
    from modules.evolution.state_review import has_unreconciled_scene_calls
    from modules.evolution.store import PostgresAttemptStore
    from modules.evolution.workflow import _read_step
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        open_project_snapshot_llm_client,
        require_active_project_exclusive,
    )

    if not isinstance(confirmation, DiscoveryGapConfirmation):
        confirmation = DiscoveryGapConfirmation.model_validate(confirmation)
    await require_active_project_exclusive(db, novel_id)
    store = PostgresAttemptStore(db, novel_id)
    await store.require_project_owner(run_key)
    run = await store.load_run(run_key, for_update=True)
    if not run or run.status != "active" or run.execution_mode != "live":
        raise ConflictError("只能确认当前隔离理解运行的发现缺口")
    frozen = await store.load_pending_frozen(run_key, run.committed_scene_index + 1)
    if (
        not frozen
        or frozen.attempt_id != confirmation.attempt_id
        or frozen.owner_epoch != run.owner_epoch
        or frozen.payload.get("stage") != "verified"
        or frozen.payload.get("discovery_result")
    ):
        raise ConflictError("待恢复场景或阶段已变化")
    gaps = confirmed_discovery_gaps(frozen)
    existing = next(
        (item for item in gaps if item["operation_id"] == str(confirmation.operation_id)),
        None,
    )
    if existing:
        if existing["confirmation"] != confirmation.model_dump(mode="json"):
            raise ConflictError("同一缺口确认不能改变范围")
    if not existing and (
        gaps
        or content_hash(frozen.model_dump(mode="json"))
        != confirmation.expected_frozen_hash
    ):
        raise ConflictError("冻结内容已变化，请重新核对原请求")
    scope = gap_scope(frozen, confirmation.journal_key)
    snapshot = run.llm_snapshot_json or {}
    profile = snapshot.get("profile") or {}
    current = await build_project_llm_execution_snapshot(
        db, novel_id, provider_id="codex"
    )
    if (
        profile.get("provider_id") != "codex"
        or profile.get("model") != "gpt-6-luna"
        or profile.get("connection_verified") is not True
        or current.get("profile") != profile
        or scope["model_fingerprint"] != content_hash(snapshot)
    ):
        raise ConflictError("原生 Luna/max 账户或冻结模型配置已变化")
    async with open_project_snapshot_llm_client(db, novel_id, snapshot) as client:
        resolved = client.resolve_request_defaults(
            LLMCallRequest(
                messages=[
                    LLMMessage(
                        role="user",
                        content="Configuration verification only; do not send",
                    )
                ]
            )
        )
        if (
            client.model_name != "gpt-6-luna"
            or resolved.extra.get("reasoning_effort") != "max"
        ):
            raise ConflictError("本次业务必须使用原生 Luna/max")
    from modules.evolution.consumer_reuse import observation_tokens, read_set

    batch = frozen.payload["discovery_preparation"]["batches"][scope["batch_index"]]
    expected_read_set = read_set(
        run,
        "scene_discovery",
        {
            "method": frozen.payload["discovery_preparation"]["method_fingerprint"],
            "inputs": batch,
        },
        tokens=observation_tokens(frozen.payload),
    )
    if frozen.payload[confirmation.journal_key]["read_set"] != expected_read_set:
        raise ConflictError("原请求的消费输入或方法证明已变化")
    for step in run.reading_plan_json["steps"]:
        await _read_step(db, novel_id, step)
    await _source_verifier(
        SceneSourceBinding.model_validate(frozen.payload["source_binding"])
    )(db, frozen)
    if existing:
        return existing

    task_id = (run.reading_plan_json or {}).get("task_id")
    lifecycle = (
        await list_task_lifecycle_contracts(
            db,
            task_ids=[task_id] if task_id else [],
            novel_id=novel_id,
            max_heartbeat_gap=0,
        )
    ).get(task_id)
    if (
        not lifecycle
        or lifecycle.status != "failed"
        or lifecycle.recovery_policy != "manual_resume"
        or lifecycle.task_type != "evolution_scene_step_v2"
        or lifecycle.lease_id
    ):
        raise ConflictError("必须先等待原场景任务终止并释放租约")
    gap = {
        "version": 1,
        "authorization_source": "author_confirmation",
        "accept_unchecked_gap": True,
        "operation_id": str(confirmation.operation_id),
        "original_request_hash": confirmation.original_request_hash,
        "confirmation": confirmation.model_dump(mode="json"),
        "scope": scope,
        "coverage": "not_checked",
        "result_status": "unknown",
        "note": "作者确认保留未检查缺口；原生请求结果未知，不重发、不补写事实。",
    }
    updated = frozen.model_copy(update={"payload": {**frozen.payload, GAPS_KEY: [gap]}})
    if has_unreconciled_scene_calls(updated.payload, frozen=updated):
        raise ConflictError("仍有其它未知请求，不能继续理解")
    await store.replace_frozen_payload(updated)
    run.reading_plan_json = {
        **run.reading_plan_json,
        GAPS_KEY: [*(run.reading_plan_json.get(GAPS_KEY) or []), gap],
    }
    # The domain has verified a recoverable scope; preserve the original failure.
    flags = {"recovery_required": True, "recoverable": True}
    if not await update_task_projection(
        db,
        task_id=task_id,
        task_type="evolution_scene_step_v2",
        novel_id=novel_id,
        result_patch=flags,
        meta_patch=flags,
        allow_failed=True,
    ):
        raise ConflictError("原场景任务已变化，确认未保存")
    await db.flush()
    return gap

"""Durable optional work after the immutable main Scene receipt is committed.

The same reading task owns both phases. Existing paid-call journals and root/child
quotas remain authoritative; recovery never starts a replacement request for an
unknown journal. No provider I/O runs inside the main domain transaction.
"""

from dataclasses import asdict

from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.errors import LLMAdmissionStoppedError
from modules.evolution.commit import CommitConflictError
from modules.evolution.optional_steps import OPTIONAL_READING_STEPS
from modules.evolution.state_review import settled_output_failure
from modules.project.facade import require_active_project_exclusive
from modules.story.facade import get_scene_contract


async def initialize_optional_stage(db, store, frozen, receipt):
    if frozen.payload.get("optional_stage_version") != 1:
        return frozen
    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    if latest.payload.get("optional_scene_stage"):
        return latest

    shadow = frozen.payload.get("execution_mode") == "shadow"
    scene = (
        None
        if shadow
        else await get_scene_contract(db, frozen.novel_id, frozen.payload["scene_id"])
    )
    if not shadow and scene is None:
        raise CommitConflictError("scene_changed", "committed Scene disappeared")
    steps = {}
    for key, spec in OPTIONAL_READING_STEPS.items():
        enabled = bool(latest.payload.get(spec.method_version_field, 0))
        reason = "step_disabled" if not enabled else "shadow_isolated" if shadow else None
        steps[key] = {
            "status": "not_run" if reason else "pending",
            "gaps": [{"reason": reason}] if reason else [],
        }
    stage = {
        "version": 1,
        "receipt_attempt_id": receipt.attempt_id,
        "scene_card_hash": content_hash(asdict(scene)) if scene else None,
        "main_state_fingerprint": latest.payload.get("state_fingerprint"),
        "steps": steps,
    }
    latest = latest.model_copy(
        update={
            "payload": {
                **latest.payload,
                "optional_scene_stage": stage,
                **(
                    {
                        "optional_step_coverage": {
                            key: {
                                "status": "not_run",
                                "gaps": item["gaps"],
                            }
                            for key, item in steps.items()
                        }
                    }
                    if shadow
                    else {}
                ),
            }
        }
    )
    await store.replace_frozen_payload(latest)
    return latest


async def load_pending_optional_stage(store, run):
    if (run.reading_plan_json or {}).get(
        "optional_stage_version"
    ) != 1 or run.committed_scene_index < 0:
        return None
    receipt = await store.load_committed_scene_receipt(
        run.run_key, run.committed_scene_index
    )
    if receipt is None:
        return None
    frozen = await store.load_frozen(run.run_key, receipt.attempt_id)
    stage = frozen.payload.get("optional_scene_stage") or {}
    if any(
        item["status"] in {"pending", "running"}
        for item in stage.get("steps", {}).values()
    ):
        return frozen
    return None


async def require_committed_optional_parent(store, frozen):
    run = await store.load_run(frozen.run_id)
    receipt = await store.load_committed_scene_receipt(
        frozen.run_id,
        frozen.payload["scene_index"],
        source_manifest_hash=frozen.source_manifest_hash,
    )
    head = await store.load_head_receipt(frozen.run_id)
    stage = frozen.payload.get("optional_scene_stage") or {}
    if (
        run is None
        or run.status != "active"
        or run.owner_epoch != frozen.owner_epoch
        or receipt is None
        or receipt.attempt_id != frozen.attempt_id
        or receipt.previous_receipt != frozen.previous_receipt
        or receipt.previous_committed_prefix != frozen.previous_committed_prefix
        or head is None
        or head.attempt_id != frozen.attempt_id
        or run.committed_scene_index != frozen.payload["scene_index"]
        or stage.get("receipt_attempt_id") != receipt.attempt_id
    ):
        raise CommitConflictError(
            "parent_advanced", "optional stage lost its committed Scene/owner"
        )


async def verify_optional_source(db, frozen, source):
    from modules.evolution.pipeline import _source_verifier

    # Main enrichment legitimately changes the card; compare the committed card
    # instead. Other current-prefix readers retain their source-only verifier.
    await _source_verifier(source)(
        db, frozen.model_copy(update={"payload": {**frozen.payload, "scene_card": None}})
    )
    current = await get_scene_contract(db, frozen.novel_id, frozen.payload["scene_id"])
    if (
        current is None
        or content_hash(asdict(current))
        != frozen.payload["optional_scene_stage"]["scene_card_hash"]
    ):
        raise CommitConflictError("scene_changed", "Scene changed after main commit")


async def _guard(db, store, frozen, source):
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    await require_committed_optional_parent(store, frozen)
    await verify_optional_source(db, frozen, source)
    return frozen


async def _record_step(db, store, frozen, key, status, gaps):
    from modules.evolution.pipeline import scene_state_fingerprint

    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    payload = dict(latest.payload)
    stage = dict(payload["optional_scene_stage"])
    stage["steps"] = {**stage["steps"], key: {"status": status, "gaps": gaps}}
    payload["optional_scene_stage"] = stage
    if status not in {"pending", "running"}:
        coverage = dict(payload.get("optional_step_coverage") or {})
        current = dict(coverage.get(key) or {})
        current["status"] = (
            current.get("status", "inspected")
            if status == "complete"
            else ("unknown" if status == "unknown" else "not_run")
        )
        current["gaps"] = [
            *current.get("gaps", []),
            *(gap for gap in gaps if gap not in current.get("gaps", [])),
        ]
        coverage[key] = current
        payload["optional_step_coverage"] = coverage
        payload["state_fingerprint"] = scene_state_fingerprint(payload)
        stage["completed_state_fingerprint"] = payload["state_fingerprint"]
    await store.replace_frozen_payload(latest.model_copy(update={"payload": payload}))
    await db.commit()


async def finish_committed_optional_steps(db, store, frozen, source, caller):
    if (
        frozen.payload.get("optional_stage_version") != 1
        or frozen.payload.get("execution_mode") == "shadow"
    ):
        return
    from modules.evolution.discovery import apply_discovery, finish_scene_discovery
    from modules.evolution.spatial import finish_scene_spatial

    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    records = (latest.payload.get("optional_scene_stage") or {}).get("steps", {})
    if all(item["status"] not in {"pending", "running"} for item in records.values()):
        await db.commit()
        return
    for key, finish in (
        ("details", finish_scene_discovery),
        ("spatial", finish_scene_spatial),
    ):
        frozen = await _guard(db, store, frozen, source)
        record = frozen.payload["optional_scene_stage"]["steps"].get(key)
        await db.commit()
        if record is None or record["status"] not in {"pending", "running"}:
            continue
        await _record_step(db, store, frozen, key, "running", [])
        failure = None
        try:
            frozen = await finish(db, store, frozen, source, caller)
        except LLMAdmissionStoppedError:
            raise
        except CommitConflictError:
            raise
        except Exception as error:
            # Each provider journal was committed before I/O. A failed domain
            # transaction can be discarded without losing billing evidence.
            await db.rollback()
            failure = error
        await require_active_project_exclusive(db, frozen.novel_id)
        frozen = await _guard(db, store, frozen, source)
        prefix = OPTIONAL_READING_STEPS[key].journal_prefix + "_"
        unknown = any(
            name.startswith(prefix)
            and journal
            and journal.get("stage") != "sampled"
            and not settled_output_failure(journal)
            for name, journal in frozen.payload.items()
        )
        state = (frozen.payload.get("optional_step_coverage") or {}).get(key, {})
        unknown = unknown or state.get("status") == "unknown"
        status = "unknown" if unknown else "failed" if failure else "complete"
        gaps = (
            [{"reason": "request_requires_reconciliation"}]
            if unknown
            else (
                [{"reason": "optional_step_failed", "error_type": type(failure).__name__}]
                if failure
                else []
            )
        )
        if not failure and not unknown:
            try:
                async with db.begin_nested():
                    if key == "details":
                        await apply_discovery(db, store, frozen)
                    else:
                        await apply_spatial_result(db, store, frozen, frozen.novel_id)
            except Exception as error:
                status = "failed"
                gaps = [
                    {
                        "reason": "optional_materialization_failed",
                        "error_type": type(error).__name__,
                    }
                ]
            # Source drift/revocation during I/O must never authorize a write.
        await _record_step(db, store, frozen, key, status, gaps)


async def apply_spatial_result(db, store, frozen, novel_id):
    spatial_pending = []
    if (frozen.payload.get("spatial_discovery_result") or {}).get("batch"):
        from modules.evolution.spatial import apply_spatial_discovery

        stage_result = None
        stage_error = None
        try:
            async with db.begin_nested():
                stage_result = await apply_spatial_discovery(db, novel_id, frozen)
        except Exception as error:
            stage_error = error
        latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        latest_payload = dict(latest.payload)
        coverage = dict(latest_payload.get("optional_step_coverage") or {})
        spatial_coverage = dict(coverage.get("spatial") or {})
        if stage_error is not None:
            spatial_coverage.update(
                status="inspected",
                gaps=[
                    *spatial_coverage.get("gaps", []),
                    {
                        "reason": "world_stage_failed",
                        "detail": str(stage_error)[:300],
                    },
                ],
            )
            latest_payload["spatial_stage_result"] = {
                "status": "failed",
                "reason": f"{type(stage_error).__name__}: {stage_error}"[:500],
            }
            result = dict(latest_payload.get("spatial_discovery_result") or {})
            result["gaps"] = [
                *result.get("gaps", []),
                {
                    "reason": "world_stage_failed",
                    "detail": str(stage_error)[:300],
                },
            ]
            latest_payload["spatial_discovery_result"] = result
        elif stage_result is not None:
            dumped = stage_result.model_dump(mode="json")
            stale = any(
                item.get("code") == "source_binding_invalid"
                for item in dumped.get("rejected", [])
            )
            if dumped.get("rejected"):
                spatial_coverage["gaps"] = [
                    *spatial_coverage.get("gaps", []),
                    *(
                        {
                            "reason": "world_stage_rejected",
                            "clue_key": item.get("clue_key"),
                            "code": item.get("code"),
                        }
                        for item in dumped["rejected"]
                    ),
                ]
            if stale:
                spatial_coverage["status"] = "stale"
            latest_payload["spatial_stage_result"] = dumped
            spatial_pending = [
                "spatial_clue_requires_review" for _ in dumped.get("accepted", [])
            ] + ["spatial_clue_requires_verification" for _ in dumped.get("pending", [])]
        coverage["spatial"] = spatial_coverage
        latest_payload["optional_step_coverage"] = coverage
        await store.replace_frozen_payload(
            latest.model_copy(update={"payload": latest_payload})
        )

    return spatial_pending

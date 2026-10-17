"""Read immutable authoring output and fresh Evidence from the owning product."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select

from core.errors import DomainError
from evals.authoring_quality_guard import AuthoringQualityError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.models import AsyncTask
from modules.evidence.facade import prepare_confirmed_ai_action
from modules.project.facade import require_active_project
from modules.story.generation import STORY_ONE_CLICK_ACTION


async def _owned_row(db, model, novel_id, row_id):
    row = await db.scalar(
        select(model).where(model.novel_id == UUID(novel_id), model.id == UUID(row_id))
    )
    if row is None:
        raise AuthoringQualityError("product evidence is absent from the bound Project")
    return row


async def read_product_evidence(db, manifest, reference) -> dict:
    """The caller selects IDs; all success, source and output data come from DB."""
    try:
        return await _read_product_evidence(db, manifest, reference)
    except (DomainError, ValueError) as error:
        raise AuthoringQualityError(
            "product source or Evidence confirmation is invalid"
        ) from error


async def _read_product_evidence(db, manifest, reference) -> dict:
    if reference is None or reference.kind not in {"director", "world_progression"}:
        raise AuthoringQualityError("this domain has no product evidence reader")
    if len(reference.output_ids) != len(set(reference.output_ids)):
        raise AuthoringQualityError("duplicate product output IDs")
    novel_id = manifest.project_id
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    if reference.kind == "director":
        from modules.story.models import (
            StorySceneDirectorBranch as Branch,
        )
        from modules.story.models import (
            StorySceneDirectorRoot as Root,
        )
        from modules.story.models import (
            StorySceneDirectorRound as Output,
        )

        task_type, prefix, count_key = (
            "story_scene_director",
            "director",
            "completed_rounds",
        )
    else:
        from modules.story.world_progression_models import (
            StoryWorldProgressionBranch as Branch,
        )
        from modules.story.world_progression_models import (
            StoryWorldProgressionRoot as Root,
        )
        from modules.story.world_progression_models import (
            StoryWorldProgressionStep as Output,
        )

        task_type = "story_world_progression"
        prefix, count_key = "world_progression", "completed_steps"
    root = await _owned_row(db, Root, novel_id, reference.root_id)
    branch = await _owned_row(db, Branch, novel_id, reference.branch_id)
    task = await _owned_row(db, AsyncTask, novel_id, reference.task_id)
    result, meta = dict(task.result or {}), dict(task.meta or {})
    if (
        str(root.scene_id) != reference.scene_id
        or branch.root_id != root.id
        or branch.deleted_at is not None
        or branch.source_hash != reference.source_sha256
        or branch.status != "complete"
        or task.task_type != task_type
        or task.status != "done"
        or result.get("status") != "complete"
        or str(result.get("root_id")) != reference.root_id
        or str(result.get("branch_id")) != reference.branch_id
        or str(meta.get(f"{prefix}_root_id")) != reference.root_id
        or str(meta.get(f"{prefix}_branch_id")) != reference.branch_id
        or root.llm_execution_snapshot_json != manifest.project_snapshot
        or meta.get("llm_execution_snapshot") != manifest.project_snapshot
        or int(result.get(count_key) or 0) < len(reference.output_ids)
    ):
        raise AuthoringQualityError(
            "product task/root/branch receipt is incomplete or mismatched"
        )
    request = {**(root.request_json or {}), **(branch.request_json or {})}
    confirmation_id = request.get("context_confirmation_id")
    if not confirmation_id:
        raise AuthoringQualityError("product task has no original Evidence confirmation")
    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=str(confirmation_id),
    )
    confirmation = confirmed.confirmation
    if str((confirmed.compile_options or {}).get("scene_id")) != reference.scene_id:
        raise AuthoringQualityError("Evidence confirmation uses another Scene cutoff")
    if reference.kind == "director":
        from modules.story.director_context import (
            read_director_source,
            scope_director_source,
        )

        source = await read_director_source(
            db,
            novel_id=novel_id,
            scene_id=reference.scene_id,
            character_ids=list(request.get("character_ids") or []),
            related_object_ids=list(request.get("related_object_ids") or []),
        )
        source = await scope_director_source(db, source, confirmed)
    else:
        from modules.story.world_progression_context import read_progression_source
        from modules.story.world_progression_schemas import (
            ProgressionParticipant,
            ProgressionTarget,
        )

        source = await read_progression_source(
            db,
            novel_id=novel_id,
            scene_id=reference.scene_id,
            participants=[
                ProgressionParticipant.model_validate(x) for x in request["participants"]
            ],
            targets=[
                ProgressionTarget.model_validate(x) for x in request.get("targets", [])
            ],
            confirmed_context=confirmed,
        )
    if source["source_hash"] != reference.source_sha256:
        raise AuthoringQualityError("product source has changed since execution")
    outputs = []
    for output_id in reference.output_ids:
        row = await _owned_row(db, Output, novel_id, output_id)
        if (
            row.root_id != root.id
            or row.branch_id != branch.id
            or row.source_hash != reference.source_sha256
            or row.created_at < task.created_at
        ):
            raise AuthoringQualityError(
                "immutable output belongs to another product execution"
            )
        if reference.kind == "director":
            from modules.story.simulation_v3 import SimulationV3Context

            parent_id = row.parent_round_id
            parent = (
                await _owned_row(db, Output, novel_id, str(parent_id))
                if parent_id
                else None
            )
            previous = (
                parent.state_json
                if parent is not None
                else SimulationV3Context.model_validate(
                    row.input_json["initial_context"]
                ).initial_state()
            )
            expected_input = content_hash(
                {
                    "source_hash": row.source_hash,
                    "parent": str(parent_id) if parent_id else None,
                    "request": row.input_json,
                    "previous_state": previous,
                }
            )
            output = row.output_json
            expected_output = content_hash(output)
            if (row.input_json.get("source_snapshot") or {}).get("source_hash") != source[
                "source_hash"
            ]:
                raise AuthoringQualityError("director input source receipt drifted")
        else:
            parent_id = row.parent_step_id
            parent = (
                await _owned_row(db, Output, novel_id, str(parent_id))
                if parent_id
                else None
            )
            if (row.input_json.get("parent_output_hash") or None) != (
                parent.output_hash if parent else None
            ):
                raise AuthoringQualityError("progression parent output receipt drifted")
            expected_input = content_hash(
                {
                    "source_hash": row.source_hash,
                    "parent_step_id": str(parent_id) if parent_id else None,
                    "parent_output_hash": row.input_json.get("parent_output_hash"),
                    "input": row.input_json,
                }
            )
            output = row.result_json
            expected_output = content_hash(
                {
                    "input_hash": row.input_hash,
                    "output": output,
                    "state": row.state_json,
                }
            )
        if parent is not None and parent.root_id != root.id:
            raise AuthoringQualityError(
                "immutable parent belongs to another product root"
            )
        if row.input_hash != expected_input or row.output_hash != expected_output:
            raise AuthoringQualityError("product input/output hash receipt drifted")
        outputs.append(
            {
                "id": str(row.id),
                "input_sha256": row.input_hash,
                "output_sha256": row.output_hash,
                "input": row.input_json,
                "output": output,
            }
        )
    return {
        "domain": reference.kind,
        "project_id": novel_id,
        "root_id": str(root.id),
        "branch_id": str(branch.id),
        "source": source,
        "confirmation": asdict(confirmation),
        "task": {
            "id": str(task.id),
            "type": task.task_type,
            "status": task.status,
            "result": result,
        },
        "outputs": outputs,
    }

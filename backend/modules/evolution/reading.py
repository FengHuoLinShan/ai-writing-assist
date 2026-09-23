"""Project committed understanding into an exact, already-authorized root read set."""

from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.evolution.contracts import CommittedObservation, CommittedUnderstanding
from modules.evolution.models import EvolutionRun
from modules.evolution.store import PostgresAttemptStore
from modules.project.facade import require_active_project
from modules.story.facade import get_scene_contract, validate_scene_source_ranges


async def read_committed_understanding(db, novel_id, source_hashes, *, required=None):
    """Only reuse live prefixes whose *whole* transitive source set is selected.

    Bounded projection: inspect at most eight runs and 200 prefix steps per run.
    Long prefixes are omitted, never represented as fully checked summaries.
    """
    await require_active_project(db, str(novel_id))
    nid = UUID(str(novel_id))
    query = select(EvolutionRun).where(
        EvolutionRun.novel_id == nid,
        EvolutionRun.execution_mode == "live",
        EvolutionRun.status.in_(["active", "drained", "stopped"]),
    )
    runs = (
        await db.scalars(query.order_by(EvolutionRun.created_at.desc()).limit(8))
    ).all()
    available, omissions = [], []
    seen_scenes = set()
    store = PostgresAttemptStore(db, nid)
    for run in runs:
        pairs = await store.load_committed_pairs(run.run_key, limit=201)
        scene_ids = {frozen.payload_json.get("scene_id") for _, frozen in pairs}
        latest = await store.latest_scene_attempts(scene_ids)
        roots, previous, previous_hash, prior_observations = set(), None, None, set()
        for index, (receipt, frozen) in enumerate(pairs[:200]):
            payload = frozen.payload_json
            binding = payload.get("source_binding") or {}
            parts = [binding, *binding.get("additional_sources", [])]
            inputs = payload.get("input_manifest") or {}
            if (
                receipt.committed_scene_index != index
                or inputs.get("run_key") != receipt.run_key
                or inputs.get("scene_index") != index
                or inputs.get("dependency_status") != "committed"
                or inputs.get("source_manifest_hash") != frozen.source_manifest_hash
                or frozen.previous_receipt != previous
                or inputs.get("previous_scene_attempt_id") != previous
                or payload.get("execution_mode") != "live"
                or latest.get(payload.get("scene_id"))
                != (receipt.run_key, frozen.attempt_key)
                or any(
                    not isinstance(item, dict)
                    or item.get("observation_id") not in prior_observations
                    for item in inputs.get("previous_observations", [])
                )
                or any(
                    source_hashes.get(str(part.get("draft_id")))
                    != part.get("content_hash")
                    or not part.get("content_hash")
                    for part in parts
                )
            ):
                omissions.append("prefix_source_not_selected_or_changed")
                break
            scene_id = payload.get("scene_id")
            scene = (
                await get_scene_contract(db, str(novel_id), scene_id)
                if scene_id
                else None
            )
            if (
                scene is None
                or scene.status not in {"draft", "canonical"}
                or scene.scene_index != index
                or any(
                    str(part.get("chapter_index"))
                    not in {str(chapter) for chapter in scene.chapter_ids}
                    for part in parts
                )
            ):
                omissions.append("scene_not_current")
                break
            try:
                await validate_scene_source_ranges(
                    db, str(novel_id), scene_id, index, parts
                )
            except ValidationError:
                omissions.append("scene_boundary_not_current")
                break
            roots.update(f"writing_draft:{part['draft_id']}" for part in parts)
            previous = frozen.attempt_key
            observations = [
                CommittedObservation(
                    observation_id=item["observation_id"],
                    predicate=item["predicate"],
                    modality=item["modality"],
                    evidence_quotes=item["evidence_quotes"],
                    subjects=[mention["surface"] for mention in item.get("mentions", [])],
                )
                for item in payload.get("compiled_observations", [])
            ]
            ref = CommittedUnderstanding(
                novel_id=str(novel_id),
                run_key=receipt.run_key,
                attempt_id=frozen.attempt_key,
                receipt_id=str(receipt.id),
                scene_id=scene_id,
                scene_index=index,
                source_keys=sorted(roots),
                observations=observations,
                content_hash=content_hash(
                    [
                        frozen.source_manifest_hash,
                        inputs,
                        previous_hash,
                        [item.model_dump(mode="json") for item in observations],
                        sorted(roots),
                    ]
                ),
            )
            previous_hash = ref.content_hash
            prior_observations.update(item.observation_id for item in observations)
            if required is not None or scene_id not in seen_scenes:
                available.append(ref)
                seen_scenes.add(scene_id)
        if len(pairs) > 200:
            omissions.append("prefix_capacity")
    if required is not None:
        current = {(ref.run_key, ref.attempt_id): ref for ref in available}
        if any(current.get((ref.run_key, ref.attempt_id)) != ref for ref in required):
            raise ConflictError(
                "使用的场景理解或原文范围已变化", code="UNDERSTANDING_STALE"
            )
        return list(required), []
    if len(available) > 3:
        omissions.append("recent_three_scenes_only")
    return sorted(available, key=lambda ref: ref.scene_index)[-3:], sorted(set(omissions))


async def require_current_world_candidate(db, novel_id, reference):
    """Adoption never trusts an old candidate's source label without its receipt."""
    from modules.evolution.commit import CommitConflictError
    from modules.evolution.pipeline import SceneSourceBinding, _source_verifier

    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(reference["run_key"])
    frozen = await store.load_frozen(reference["run_key"], reference["attempt_id"])
    receipt = await store.load_receipt(reference["run_key"], reference["attempt_id"])
    if (
        not run
        or run.status not in {"active", "drained", "stopped"}
        or not receipt
        or not frozen
        or not frozen.payload.get("world_result")
        or frozen.payload.get("execution_mode") != "live"
    ):
        raise ConflictError("理解来源已失效，请先重新理解并核对新候选")
    scene_id = frozen.payload["scene_id"]
    latest = await store.latest_scene_attempts({scene_id})
    if latest.get(scene_id) != (frozen.run_id, frozen.attempt_id):
        raise ConflictError("已有更新的理解结果，请核对新候选")
    # Enrichment changes semantic fields during this very commit. The authoritative
    # boundary and actual draft must match; the pre-enrichment card need not.
    current = frozen.model_copy(
        update={"payload": {**frozen.payload, "scene_card": None}}
    )
    try:
        await _source_verifier(
            SceneSourceBinding.model_validate(frozen.payload["source_binding"])
        )(db, current)
    except CommitConflictError as error:
        raise ConflictError("理解来源已变化，请先重新理解并核对新候选") from error

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


def _recomputed_prefix_matches_baseline(
    current_run_key, plan, through_scene_index, current_pairs, baseline_pairs
):
    """Only bridge suffixes after every recomputed Scene matches its baseline."""
    from modules.evolution.pipeline import equivalent_scene_state_fingerprint

    baseline = plan.get("recompute_baseline") or {}
    first_scene = plan.get("recompute_from_scene_index")
    if first_scene is None:
        first_scene = 0
    steps = plan.get("steps") or []
    if (
        first_scene is None
        or first_scene > through_scene_index
        or not baseline.get("run_key")
        or through_scene_index >= len(steps)
    ):
        return False
    refs = {int(item["scene_index"]): item for item in baseline.get("receipts", [])}
    current_by_scene = {
        receipt.committed_scene_index: (receipt, frozen)
        for receipt, frozen in current_pairs
    }
    baseline_by_key = {
        (receipt.run_key, receipt.attempt_key): (receipt, frozen)
        for receipt, frozen in baseline_pairs
    }
    for scene_index in range(first_scene, through_scene_index + 1):
        ref = refs.get(scene_index)
        current = current_by_scene.get(scene_index)
        previous = baseline_by_key.get(
            (ref.get("run_key"), ref.get("attempt_id")) if ref else None
        )
        if not ref or not current or not previous:
            return False
        current_receipt, current_frozen = current
        previous_receipt, previous_frozen = previous
        step = steps[scene_index]
        current_payload = current_frozen.payload_json or {}
        previous_payload = previous_frozen.payload_json or {}
        if (
            current_receipt.committed_scene_index != scene_index
            or previous_receipt.committed_scene_index != scene_index
            or (
                current_receipt.run_key != current_run_key
                and (current_receipt.run_key, current_receipt.attempt_key)
                != (ref["run_key"], ref["attempt_id"])
            )
            or (previous_receipt.run_key, previous_receipt.attempt_key)
            != (ref["run_key"], ref["attempt_id"])
            or current_payload.get("scene_index") != scene_index
            or previous_payload.get("scene_index") != scene_index
            or current_payload.get("scene_id") != step["scene_id"]
            or previous_payload.get("scene_id") != step["scene_id"]
            or current_payload.get("source_binding") != step["source_binding"]
            or equivalent_scene_state_fingerprint(previous_payload, current_payload)
            is None
        ):
            return False
    return True


async def _validate_propagation_handoff(
    db, store, plan, previous_pair, next_pair, boundary_scene_index
):
    """Validate an explicit semantic-equality bridge before reusing an old suffix."""
    previous_receipt, previous_frozen = previous_pair
    receipt, frozen = next_pair
    payload = frozen.payload_json or {}
    inputs = payload.get("input_manifest") or {}
    baseline_attempt_id = frozen.previous_receipt
    proof = next(
        (
            item
            for item in plan.get("propagation_handoffs", [])
            if item.get("scene_index") == boundary_scene_index
            and item.get("current_run_key") == previous_receipt.run_key
            and item.get("current_attempt_id") == previous_receipt.attempt_key
            and item.get("baseline_attempt_id") == baseline_attempt_id
            and item.get("next_baseline_run_key") == receipt.run_key
            and item.get("next_baseline_attempt_id") == receipt.attempt_key
        ),
        None,
    )
    if (
        not proof
        or inputs.get("previous_scene_attempt_id") != baseline_attempt_id
        or receipt.committed_scene_index != boundary_scene_index + 1
        or receipt.committed_scene_index > proof.get("reused_through_scene_index", -1)
    ):
        return None
    baseline = plan.get("recompute_baseline") or {}
    if not baseline.get("run_key") or not await store.load_run(proof["current_run_key"]):
        return None
    current_pairs = await store.load_committed_pairs(proof["current_run_key"])
    baseline_pairs = await store.load_committed_pairs(baseline["run_key"])
    if not _recomputed_prefix_matches_baseline(
        proof["current_run_key"],
        plan,
        boundary_scene_index,
        current_pairs,
        baseline_pairs,
    ):
        return None
    baseline_frozen = await store.load_frozen(
        proof["baseline_run_key"], baseline_attempt_id
    )
    baseline_receipt = await store.load_receipt(
        proof["baseline_run_key"], baseline_attempt_id
    )
    previous_payload = previous_frozen.payload_json or {}
    baseline_payload = baseline_frozen.payload if baseline_frozen else {}
    steps = plan.get("steps", [])
    from modules.evolution.pipeline import (
        equivalent_scene_state_fingerprint,
        observation_equivalence_map,
    )

    fingerprint = proof.get("state_fingerprint")
    if (
        not baseline_frozen
        or not baseline_receipt
        or baseline_receipt.execution_status != "succeeded"
        or baseline_receipt.committed_prefix.through_scene_index != boundary_scene_index
        or baseline_payload.get("scene_index") != boundary_scene_index
        or previous_payload.get("scene_index") != boundary_scene_index
        or baseline_payload.get("scene_id") != previous_payload.get("scene_id")
        or (
            len(steps) > boundary_scene_index + 1
            and (
                previous_payload.get("scene_id")
                != steps[boundary_scene_index]["scene_id"]
                or payload.get("scene_id") != steps[boundary_scene_index + 1]["scene_id"]
            )
        )
        or equivalent_scene_state_fingerprint(baseline_payload, previous_payload)
        != fingerprint
    ):
        return None
    equivalent_observations = observation_equivalence_map(
        baseline_payload, previous_payload
    )
    if equivalent_observations != proof.get("observation_map"):
        return None
    return equivalent_observations


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
        observation_aliases = {}
        for index, (receipt, frozen) in enumerate(pairs[:200]):
            payload = frozen.payload_json
            binding = payload.get("source_binding") or {}
            parts = [binding, *binding.get("additional_sources", [])]
            inputs = payload.get("input_manifest") or {}
            chain_gap = bool(
                index
                and (
                    frozen.previous_receipt != previous
                    or inputs.get("previous_scene_attempt_id") != previous
                )
            )
            if chain_gap:
                aliases = await _validate_propagation_handoff(
                    db,
                    store,
                    run.reading_plan_json or {},
                    pairs[index - 1],
                    (receipt, frozen),
                    index - 1,
                )
                if aliases is None:
                    omissions.append("prefix_propagation_handoff_invalid")
                    break
                observation_aliases.update(aliases)
            if (
                receipt.committed_scene_index != index
                or (
                    not index
                    and (
                        frozen.previous_receipt is not None
                        or inputs.get("previous_scene_attempt_id") is not None
                    )
                )
                or inputs.get("run_key") != receipt.run_key
                or inputs.get("scene_index") != index
                or inputs.get("dependency_status") != "committed"
                or inputs.get("source_manifest_hash") != frozen.source_manifest_hash
                or payload.get("execution_mode") != "live"
                or latest.get(payload.get("scene_id"))
                != (receipt.run_key, frozen.attempt_key)
                or any(
                    not isinstance(item, dict)
                    or observation_aliases.get(
                        item.get("observation_id"), item.get("observation_id")
                    )
                    not in prior_observations
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


async def _inheriting_live_runs(db, novel_id, reference, *, limit=8):
    """最近 live run 中经 inherited_receipts 引用该回执身份的运行（新→旧）。

    这里只做候选筛选；继承是否有效由 :func:`require_current_prefix` 经
    propagation handoff 与重算前缀比对独立验证。
    """
    nid = UUID(str(novel_id))
    identity = (reference["run_key"], reference["attempt_id"])
    candidates, offset = [], 0
    while len(candidates) < limit:
        runs = (
            await db.scalars(
                select(EvolutionRun)
                .where(
                    EvolutionRun.novel_id == nid,
                    EvolutionRun.execution_mode == "live",
                    EvolutionRun.status.in_(["active", "drained", "stopped"]),
                )
                .order_by(EvolutionRun.created_at.desc(), EvolutionRun.run_key)
                .offset(offset)
                .limit(64)
            )
        ).all()
        for run in runs:
            if run.run_key != reference["run_key"] and any(
                (item.get("run_key"), item.get("attempt_id")) == identity
                for item in (run.reading_plan_json or {}).get("inherited_receipts", [])
            ):
                candidates.append(run.run_key)
                if len(candidates) == limit:
                    break
        if len(runs) < 64:
            break
        offset += len(runs)
    return candidates


async def require_current_world_candidate(db, novel_id, reference):
    """Adoption never trusts an old candidate's source label without its receipt."""
    from modules.evolution.commit import CommitConflictError
    from modules.evolution.pipeline import SceneSourceBinding, _source_verifier

    store = PostgresAttemptStore(db, novel_id)
    run = await store.load_run(reference["run_key"])
    frozen = await store.load_frozen(reference["run_key"], reference["attempt_id"])
    receipt = await store.load_receipt(reference["run_key"], reference["attempt_id"])
    if (
        not receipt
        or not frozen
        or not frozen.payload.get("world_result")
        or frozen.payload.get("execution_mode") != "live"
    ):
        raise ConflictError("理解来源已失效，请先重新理解并核对新候选")
    # 候选前缀宿主：原 run 状态合法时可用；否则接受经传播证明继承该回执的
    # live run（修订停止传播后，后缀候选的真实宿主是新 run）。
    candidates = []
    if run and run.status in {"active", "drained", "stopped"}:
        candidates.append(run.run_key)
    candidates.extend(await _inheriting_live_runs(db, novel_id, reference))
    if not candidates:
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
    first_error = None
    for candidate in candidates:
        try:
            await require_current_prefix(db, store, frozen, run_key=candidate)
            return
        except ConflictError as error:
            if first_error is None:
                first_error = error
    raise first_error or ConflictError("理解来源已失效，请先重新理解并核对新候选")


async def require_current_prefix(
    db, store, target, *, run_key=None, verified=None, cited_claim=None
):
    """Revalidate the original transitive receipts, including inherited runs.

    ``run_key`` 指定生效 run（其 plan 承载传播证明与继承清单）；缺省为
    target 所在 run。前缀末端身份仍必须是 target 本身。
    """
    from modules.evolution.commit import CommitConflictError
    from modules.evolution.pipeline import SceneSourceBinding, _source_verifier

    try:
        run = await store.load_run(run_key or target.run_id)
        if not run:
            raise ConflictError("理解运行已失效")
        pairs = await store.load_committed_pairs(run.run_key)
        through = target.payload["scene_index"]
        prefix = [pair for pair in pairs if pair[0].committed_scene_index <= through]
        if len(prefix) != through + 1 or (
            prefix[-1][0].run_key,
            prefix[-1][0].attempt_key,
        ) != (target.run_id, target.attempt_id):
            raise ConflictError("理解前序回执不完整，请重新理解并核对候选")
        latest = await store.latest_scene_attempts(
            {row.payload_json.get("scene_id") for _, row in prefix}
        )
        previous, observations, observation_aliases = None, set(), {}
        for index, (receipt, row) in enumerate(prefix):
            payload = row.payload_json
            inputs = payload.get("input_manifest") or {}
            chain_gap = bool(
                index
                and (
                    row.previous_receipt != previous
                    or inputs.get("previous_scene_attempt_id") != previous
                )
            )
            if chain_gap:
                aliases = await _validate_propagation_handoff(
                    db,
                    store,
                    run.reading_plan_json or {},
                    prefix[index - 1],
                    (receipt, row),
                    index - 1,
                )
                if aliases is None:
                    raise ConflictError("理解前序回执的传播边界未通过核验")
                observation_aliases.update(aliases)
            if (
                receipt.committed_scene_index != index
                or (
                    not index
                    and (
                        row.previous_receipt is not None
                        or inputs.get("previous_scene_attempt_id") is not None
                    )
                )
                or inputs.get("run_key") != receipt.run_key
                or inputs.get("scene_index") != index
                or inputs.get("dependency_status") != "committed"
                or inputs.get("source_manifest_hash") != row.source_manifest_hash
                or payload.get("execution_mode") != "live"
                or latest.get(payload.get("scene_id"))
                != (receipt.run_key, receipt.attempt_key)
                or any(
                    observation_aliases.get(
                        item.get("observation_id"), item.get("observation_id")
                    )
                    not in observations
                    for item in inputs.get("previous_observations", [])
                )
            ):
                raise ConflictError("理解前序依据已变化，请重新理解并核对候选")
            frozen = await store.load_frozen(receipt.run_key, receipt.attempt_key)
            if cited_claim is None:
                await _source_verifier(
                    SceneSourceBinding.model_validate(payload["source_binding"])
                )(
                    db,
                    frozen.model_copy(
                        update={"payload": {**frozen.payload, "scene_card": None}}
                    ),
                )
            previous = receipt.attempt_key
            observations.update(
                item["observation_id"]
                for item in payload.get("compiled_observations", [])
            )
        if cited_claim is not None:
            from modules.evolution.ledger import _claim_ranges_current

            if (
                await _claim_ranges_current(db, str(store.novel_id), cited_claim)
                != "current"
            ):
                raise ConflictError("台账引用的正文区间已变化")
        if verified is not None:
            verified.extend(prefix)
    except CommitConflictError as error:
        raise ConflictError("理解前序来源已变化，请重新理解并核对候选") from error

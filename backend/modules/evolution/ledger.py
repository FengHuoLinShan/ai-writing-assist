"""Persist derived themes and author decisions without writing World/Story Canon."""

from uuid import UUID, uuid4

from sqlalchemy import func, select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from modules.evolution.ledger_contracts import (
    DiscoveryChange,
    LedgerClaim,
    LedgerDecision,
    evidence_counts,
)
from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionLedgerEntry,
    EvolutionLedgerRevision,
    EvolutionRun,
)
from modules.evolution.store import PostgresAttemptStore
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.story.facade import get_scene_state_view, get_scenes_by_novel
from modules.story.outline_state.facade import get_active_foreshadowing
from modules.writing.facade import get_draft, get_latest_draft_for_chapter


async def require_author_ledger(db, novel_id):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)


async def _entry(db, novel_id, entry_id, *, lock=False):
    query = select(EvolutionLedgerEntry).where(
        EvolutionLedgerEntry.novel_id == UUID(str(novel_id)),
        EvolutionLedgerEntry.id == UUID(str(entry_id)),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    entry = await db.scalar(query)
    if entry is None:
        raise NotFoundError("没有找到这条记录")
    return entry


async def _revision(db, entry, revision=None):
    return await db.scalar(
        select(EvolutionLedgerRevision).where(
            EvolutionLedgerRevision.novel_id == entry.novel_id,
            EvolutionLedgerRevision.entry_id == entry.id,
            EvolutionLedgerRevision.revision == (revision or entry.head_revision),
        )
    )


async def _replay(db, novel_id, operation_key, request_hash):
    row = await db.scalar(
        select(EvolutionLedgerRevision).where(
            EvolutionLedgerRevision.novel_id == UUID(str(novel_id)),
            EvolutionLedgerRevision.operation_key == operation_key,
        )
    )
    if row is not None and row.request_hash != request_hash:
        raise ConflictError(
            "同一次操作的内容已变化，请重新提交", code="ledger_operation_conflict"
        )
    return row


async def persist_discovery_claim(db, novel_id, change, claim, *, operation_key, review):
    """Called only by the verified Scene applier in its receipt transaction."""
    change = DiscoveryChange.model_validate(change)
    claim = LedgerClaim.model_validate(claim)
    if any(item.source_ref.novel_id != str(novel_id) for item in claim.evidence):
        raise ConflictError("记录的来源不属于当前作品")
    if claim.category != change.category or claim.realm != "history":
        raise ConflictError("本次正文发现不能改写计划或试演范围")
    request_hash = content_hash(
        {
            "change": change.model_dump(mode="json"),
            "claim": claim.model_dump(mode="json"),
            "review": review,
        }
    )
    if replay := await _replay(db, novel_id, operation_key, request_hash):
        return {
            "entry_id": str(replay.entry_id),
            "revision": replay.revision,
            "replayed": True,
        }
    proposal_target = None
    if change.target_entry_id:
        entry = await _entry(db, novel_id, change.target_entry_id, lock=True)
        if (
            entry.head_revision != change.expected_revision
            or entry.category != claim.category
        ):
            raise ConflictError(
                "条目已有新修订，请基于最新记录核对", code="ledger_revision_conflict"
            )
        if change.action == "question" or review.get("verdict") == "uncertain":
            proposal_target = {"entry_id": str(entry.id), "revision": entry.head_revision}
        else:
            entry.head_revision += 1
    if not change.target_entry_id or proposal_target:
        origin_key = content_hash(
            [
                proposal_target,
                claim.category,
                claim.statement,
                sorted(item.observation_id for item in claim.evidence),
            ]
        )
        entry = await db.scalar(
            select(EvolutionLedgerEntry)
            .where(
                EvolutionLedgerEntry.novel_id == UUID(str(novel_id)),
                EvolutionLedgerEntry.origin_key == origin_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if entry is not None:
            previous = await _revision(db, entry)
            if (
                proposal_target is None
                and review.get("verdict") == "uncertain"
                and previous.body_json.get("review", {}).get("verdict") != "uncertain"
            ):
                # A new extraction can rediscover a theme without receiving its ID.
                # Origin matches obey the same candidate boundary as explicit updates.
                proposal_target = {
                    "entry_id": str(entry.id),
                    "revision": entry.head_revision,
                }
                origin_key = content_hash(
                    [
                        proposal_target,
                        claim.category,
                        claim.statement,
                        sorted(item.observation_id for item in claim.evidence),
                    ]
                )
                entry = await db.scalar(
                    select(EvolutionLedgerEntry)
                    .where(
                        EvolutionLedgerEntry.novel_id == UUID(str(novel_id)),
                        EvolutionLedgerEntry.origin_key == origin_key,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                previous = await _revision(db, entry) if entry is not None else None
        if entry is not None:
            if (
                previous.body_json["claim"] == claim.model_dump(mode="json")
                and previous.body_json.get("review", {}) == review
            ):
                # Identical qualification is not new evidence or an occurrence.
                return {
                    "entry_id": str(entry.id),
                    "revision": entry.head_revision,
                    "replayed": True,
                }
            # Re-extraction can refresh dependencies/method/review; keep author scope.
            entry.head_revision += 1
        else:
            entry = EvolutionLedgerEntry(
                id=uuid4(),
                novel_id=UUID(str(novel_id)),
                origin_key=origin_key,
                category=claim.category,
                head_revision=1,
                author_decision_json={},
            )
            db.add(entry)
            await db.flush()
    row = EvolutionLedgerRevision(
        id=uuid4(),
        novel_id=entry.novel_id,
        entry_id=entry.id,
        revision=entry.head_revision,
        operation_key=operation_key,
        request_hash=request_hash,
        scene_index=max(item.scene_index for item in claim.dependencies),
        kind=change.action,
        body_json={
            "claim": claim.model_dump(mode="json"),
            "review": review,
            "proposal_target": proposal_target,
            "author_decision": entry.author_decision_json,
        },
    )
    db.add(row)
    await db.flush()
    return {"entry_id": str(entry.id), "revision": row.revision, "replayed": False}


async def save_ledger_decision(db, novel_id, entry_id, data):
    await require_active_project_exclusive(db, str(novel_id))
    data = LedgerDecision.model_validate(data)
    operation_key = content_hash(["ledger_author", str(data.operation_id)])
    request_hash = content_hash([str(entry_id), data.model_dump(mode="json")])
    if replay := await _replay(db, novel_id, operation_key, request_hash):
        return {
            "entry_id": str(replay.entry_id),
            "revision": replay.revision,
            "saved": True,
            "replayed": True,
        }
    entry = await _entry(db, novel_id, entry_id, lock=True)
    if entry.head_revision != data.expected_revision:
        raise ConflictError(
            "记录已有新修订，输入已保留，请核对后再保存", code="ledger_revision_conflict"
        )
    previous = await _revision(db, entry)
    claim = LedgerClaim.model_validate(previous.body_json["claim"])
    last = max(claim.dependencies, key=lambda item: item.scene_index)
    decision = {
        **data.model_dump(mode="json"),
        "entry_id": str(entry.id),
        "basis_revision": entry.head_revision,
        "scene_id": str(last.scene_id),
        "scene_index": last.scene_index,
        "targets": [item.model_dump(mode="json") for item in claim.targets],
    }
    entry.head_revision += 1
    entry.author_decision_json = decision
    row = EvolutionLedgerRevision(
        id=uuid4(),
        novel_id=entry.novel_id,
        entry_id=entry.id,
        revision=entry.head_revision,
        operation_key=operation_key,
        request_hash=request_hash,
        scene_index=last.scene_index,
        kind="author_decision",
        body_json={**previous.body_json, "author_decision": decision},
    )
    db.add(row)
    await db.flush()
    return {
        "entry_id": str(entry.id),
        "revision": row.revision,
        "saved": True,
        "replayed": False,
    }


async def claim_freshness(db, novel_id, claim, *, cache=None):
    """Qualification changes independently of the immutable author decision."""
    from modules.evolution.freshness import dependency_current

    # Legacy caller dictionaries are not authoritative: they lack a mutation
    # epoch and can survive writes or be reused for a different project.
    store = PostgresAttemptStore(db, novel_id)
    grouped = {}
    for dependency in claim.dependencies:
        existing = grouped.get(dependency.run_key)
        if existing is None or dependency.scene_index > existing.scene_index:
            grouped[dependency.run_key] = dependency
    for dependency in grouped.values():
        if not await dependency_current(db, store, dependency):
            return "source_changed"
    return "current"


def _method_status(claim):
    from modules.evolution.discovery import method_fingerprint

    return (
        "current"
        if claim.method_fingerprint == method_fingerprint()
        else "method_changed"
    )


async def _identity_status(db, novel_id, claim):
    from modules.evolution.pipeline import exact_name_candidate_lookup

    lookup = exact_name_candidate_lookup(db)
    for target in claim.targets:
        if target.kind != "entity":
            continue
        matches = await lookup(str(novel_id), target.label)
        ids = {str(item.existing_entity_id) for item in matches}
        if ids != {str(target.target_id)}:
            return "needs_revalidation"
    return "unresolved" if claim.unresolved_subjects else "current"


def _extraction_count(history, through_revision):
    return len(
        {
            (dependency["run_key"], dependency["attempt_id"])
            for row in history
            if row.revision <= through_revision
            for dependency in row.body_json["claim"]["dependencies"]
        }
    )


async def _review_context(db, row):
    review = row.body_json.get("review", {})
    previous = None
    if row.body_json.get("proposal_target") or review.get("verdict") == "uncertain":
        target = row.body_json.get("proposal_target")
        prior = await db.scalar(
            select(EvolutionLedgerRevision)
            .where(
                EvolutionLedgerRevision.novel_id == row.novel_id,
                EvolutionLedgerRevision.entry_id
                == (UUID(target["entry_id"]) if target else row.entry_id),
                EvolutionLedgerRevision.revision
                <= (target["revision"] if target else row.revision - 1),
                EvolutionLedgerRevision.body_json["review"]["verdict"].as_string()
                == "supported",
            )
            .order_by(EvolutionLedgerRevision.revision.desc())
            .limit(1)
        )
        if prior is not None:
            previous = {"revision": prior.revision, "claim": prior.body_json["claim"]}
    return {
        "independent_review": review,
        "previous_supported": previous,
        "proposal_target": row.body_json.get("proposal_target"),
    }


async def read_ledger_entry(db, novel_id, entry_id, *, revision=None):
    await require_author_ledger(db, novel_id)
    entry = await _entry(db, novel_id, entry_id)
    row = await _revision(db, entry, revision)
    if row is None:
        raise NotFoundError("没有找到这个历史修订")
    claim = LedgerClaim.model_validate(row.body_json["claim"])
    history = (
        await db.scalars(
            select(EvolutionLedgerRevision)
            .where(
                EvolutionLedgerRevision.novel_id == entry.novel_id,
                EvolutionLedgerRevision.entry_id == entry.id,
            )
            .order_by(EvolutionLedgerRevision.revision.desc())
        )
    ).all()
    return {
        "entry_id": str(entry.id),
        "revision": row.revision,
        "head_revision": entry.head_revision,
        **await _review_context(db, row),
        "claim": claim.model_dump(mode="json"),
        "counts": {
            **evidence_counts(claim.evidence),
            "extractions": _extraction_count(history, row.revision),
        },
        "identity_status": await _identity_status(db, novel_id, claim),
        "source_status": await claim_freshness(db, novel_id, claim),
        "method_status": _method_status(claim),
        "author_decision": row.body_json.get("author_decision", {}),
        "current_author_decision": entry.author_decision_json,
        "history": [
            {
                "revision": item.revision,
                "kind": item.kind,
                "scene_index": item.scene_index,
            }
            for item in history
        ],
        "derived_only": True,
    }


async def list_ledger(
    db, novel_id, *, through_scene_index, category=None, query="", offset=0, limit=30
):
    await require_author_ledger(db, novel_id)
    ranked = (
        select(
            EvolutionLedgerRevision.id,
            func.row_number()
            .over(
                partition_by=EvolutionLedgerRevision.entry_id,
                order_by=EvolutionLedgerRevision.revision.desc(),
            )
            .label("position"),
        )
        .where(
            EvolutionLedgerRevision.novel_id == UUID(str(novel_id)),
            EvolutionLedgerRevision.scene_index <= through_scene_index,
        )
        .subquery()
    )
    statement = (
        select(EvolutionLedgerRevision, EvolutionLedgerEntry)
        .join(
            EvolutionLedgerEntry,
            EvolutionLedgerEntry.id == EvolutionLedgerRevision.entry_id,
        )
        .join(ranked, ranked.c.id == EvolutionLedgerRevision.id)
        .where(ranked.c.position == 1)
    )
    if category:
        statement = statement.where(EvolutionLedgerEntry.category == category)
    if query.strip():
        statement = statement.where(
            EvolutionLedgerRevision.body_json["claim"]["statement"]
            .as_string()
            .icontains(query.strip(), autoescape=True)
        )
    total = await db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = (
        await db.execute(
            statement.order_by(
                EvolutionLedgerRevision.scene_index.desc(), EvolutionLedgerRevision.id
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    history_by_entry = {}
    if rows:
        history = (
            await db.scalars(
                select(EvolutionLedgerRevision).where(
                    EvolutionLedgerRevision.novel_id == UUID(str(novel_id)),
                    EvolutionLedgerRevision.entry_id.in_([entry.id for _, entry in rows]),
                )
            )
        ).all()
        for version in history:
            history_by_entry.setdefault(version.entry_id, []).append(version)
    cache, items = {}, []
    for row, entry in rows:
        claim = LedgerClaim.model_validate(row.body_json["claim"])
        items.append(
            {
                "entry_id": str(entry.id),
                "revision": row.revision,
                **await _review_context(db, row),
                "claim": claim.model_dump(mode="json"),
                "counts": {
                    **evidence_counts(claim.evidence),
                    "extractions": _extraction_count(
                        history_by_entry[entry.id], row.revision
                    ),
                },
                "identity_status": await _identity_status(db, novel_id, claim),
                "author_decision": row.body_json.get("author_decision", {}),
                "source_status": await claim_freshness(db, novel_id, claim, cache=cache),
                "method_status": _method_status(claim),
            }
        )
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "derived_only": True,
    }


async def read_discovery_coverage(db, novel_id, scene_id):
    """A failed, partial or unsent batch never becomes 'checked, no findings'."""
    from modules.evolution.freshness import require_cached_prefix

    row = await db.scalar(
        select(EvolutionFrozenAttempt)
        .join(
            EvolutionRun,
            (EvolutionRun.novel_id == EvolutionFrozenAttempt.novel_id)
            & (EvolutionRun.run_key == EvolutionFrozenAttempt.run_key),
        )
        .where(
            EvolutionFrozenAttempt.novel_id == UUID(str(novel_id)),
            EvolutionFrozenAttempt.payload_json["scene_id"].as_string() == str(scene_id),
            EvolutionRun.execution_mode == "live",
            EvolutionFrozenAttempt.status != "abandoned",
        )
        .order_by(
            EvolutionFrozenAttempt.created_at.desc(), EvolutionFrozenAttempt.id.desc()
        )
        .limit(1)
    )
    if row is None:
        return {"status": "not_checked", "note": "本场尚未进行细节发现。"}
    payload = row.payload_json
    if payload.get("discovery_version", 0) != 1:
        return {
            "status": "not_enabled",
            "note": "这轮理解未启用细节发现；空台账不表示没有相关内容。",
        }
    result = payload.get("discovery_result")
    if not result or row.status != "applied":
        return {
            "status": "incomplete",
            "note": "本场发现尚未完成提交，已取得结果保留供恢复。",
            "scope": (payload.get("discovery_preparation") or {}).get("coverage"),
        }
    store = PostgresAttemptStore(db, novel_id)
    frozen = await store.load_frozen(row.run_key, row.attempt_key)
    try:
        await require_cached_prefix(db, store, frozen)
    except ConflictError:
        return {
            "status": "source_changed",
            "note": "正文或场景来源已变化，保留历史发现，当前范围待重新核对。",
        }
    partial = bool(
        result["coverage"]["unsupported_batches"]
        or result["coverage"].get("observation_gaps")
        or result["coverage"].get("failed_batches")
        or result["coverage"].get("identity_review_gaps")
    ) or any(batch["coverage"] != "inspected" for batch in result["inspected"])
    materialized = payload.get("discovery_materialization") or {}
    return {
        "status": "partial" if partial else "checked",
        "scope": result["coverage"],
        "inspected_batches": sum(
            batch["coverage"] != "not_checked" for batch in result["inspected"]
        ),
        "found": len(result["changes"]),
        "applied": len(materialized.get("applied", [])),
        "pending": materialized.get("pending", []),
        "method_status": _method_status(
            LedgerClaim.model_validate(result["changes"][0]["claim"])
        )
        if result["changes"]
        else (
            "current"
            if result["method_fingerprint"] == _current_method()
            else "method_changed"
        ),
        "note": "本次召回范围已检查。未检出不代表正文中不存在。"
        if not partial
        else "仅完成部分发现，请核对未检范围。",
    }


def _current_method():
    from modules.evolution.discovery import method_fingerprint

    return method_fingerprint()


async def _scene_changes(db, novel_id, state):
    scenes = await get_scenes_by_novel(db, str(novel_id))
    previous = max(
        (item for item in scenes if item["scene_index"] < state.scene_index),
        key=lambda item: item["scene_index"],
        default=None,
    )
    before = (
        await get_scene_state_view(
            db, str(novel_id), previous["id"], viewpoint={"kind": "author"}
        )
        if previous
        else None
    )

    def facts(view):
        return (
            {
                (dimension.dimension, fact.subject_id, fact.field, fact.layer): (
                    dimension.label,
                    fact,
                )
                for dimension in view.dimensions
                for fact in dimension.facts
            }
            if view
            else {}
        )

    old, current, items = facts(before), facts(state), []
    for key in sorted(old.keys() | current.keys(), key=str):
        previous_fact = old.get(key)
        current_fact = current.get(key)
        if (
            previous_fact
            and current_fact
            and previous_fact[1].value == current_fact[1].value
        ):
            continue
        label, fact = current_fact or previous_fact
        items.append(
            {
                "dimension": key[0],
                "dimension_label": label,
                "subject_label": fact.subject_label,
                "field": fact.field,
                "layer": fact.layer,
                "before_known": previous_fact is not None,
                "after_known": current_fact is not None,
                "before": previous_fact[1].value if previous_fact else None,
                "after": current_fact[1].value if current_fact else None,
                "before_source": previous_fact[1].source if previous_fact else None,
                "after_source": current_fact[1].source if current_fact else None,
            }
        )
    return {
        "items": items,
        "basis_scene_index": before.scene_index if before else None,
        "note": "对照前一已记录场景；缺少前值或后值表示未记载，不表示新增或消失。",
    }


async def read_author_panorama(db, novel_id, scene_id):
    await require_author_ledger(db, novel_id)
    state = await get_scene_state_view(
        db, str(novel_id), str(scene_id), viewpoint={"kind": "author"}
    )
    plans = []
    for status in (
        "draft",
        "planned",
        "seeded",
        "planted",
        "reinforced",
        "triggered",
        "paid_off",
    ):
        plans.extend(await get_active_foreshadowing(db, str(novel_id), status=status))
    return {
        "state": state.model_dump(mode="json"),
        "changes": await _scene_changes(db, novel_id, state),
        "coverage": await read_discovery_coverage(db, novel_id, scene_id),
        "plans": {
            "realm": "plan",
            "items": plans,
            "note": "当前作者计划；不是截止场景的已发生历史。",
        },
        "ledger": await list_ledger(db, novel_id, through_scene_index=state.scene_index),
        "author_only": True,
    }


async def read_ledger_evidence(db, novel_id, entry_id, evidence_index, *, revision=None):
    await require_author_ledger(db, novel_id)
    entry = await _entry(db, novel_id, entry_id)
    row = await _revision(db, entry, revision)
    if row is None:
        raise NotFoundError("没有找到这个历史修订")
    claim = LedgerClaim.model_validate(row.body_json["claim"])
    if evidence_index >= len(claim.evidence):
        raise NotFoundError("没有找到这段依据")
    evidence = claim.evidence[evidence_index]
    source = evidence.source_ref
    draft = await get_draft(db, str(novel_id), source.draft_id)
    if draft is None or draft.content_hash != source.content_hash:
        raise ConflictError(
            "原文版本已变化或无法回读，历史引用仍保留", code="ledger_source_changed"
        )
    text = draft.content or ""
    if text[source.start_offset : source.end_offset] != evidence.quote:
        raise ConflictError(
            "原文区间已变化，历史引用仍保留", code="ledger_source_changed"
        )
    chapter = evidence.position.chapter_index
    current = (
        await get_latest_draft_for_chapter(db, str(novel_id), chapter)
        if chapter is not None
        else None
    )
    return {
        "quote": evidence.quote,
        "context": text[
            max(0, source.start_offset - 120) : min(len(text), source.end_offset + 120)
        ],
        "chapter_index": chapter,
        "historical": current is None or str(current.id) != source.draft_id,
        "source_ref": source.model_dump(mode="json"),
    }

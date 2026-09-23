"""Versioned, source-bound understanding. No canonical writes or model calls."""

from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, text, update

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.contracts import CognitionRef, InputManifest, WorkOutput
from modules.collaboration.models import (
    CognitionCommit,
    CognitionHead,
    CognitionRecord,
    CollaborationArtifact,
    CollaborationWorkItem,
)
from modules.project.facade import require_active_project


def source_dependency(source):
    return source.model_dump(mode="json", exclude={"content", "label"})


def record_ref(row):
    return CognitionRef(
        commit_id=row.commit_id,
        record_id=row.record_id,
        revision_id=row.id,
        content_hash=row.content_hash,
        content=row.content_json,
        author_status=row.author_status,
        purpose=(
            "作者修正的解释，尚未经原文语义复核；不作为独立事实证据"
            if row.author_status == "corrected"
            else (
                "作者回顾解释（包含当时题目及保留项）；不作为独立事实证据，"
                "也不作为历史首次阅读证据"
            )
        ),
    )


async def read_head(db, novel_id, *, lock=False):
    nid = UUID(str(novel_id))
    if lock and db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"cognition:{nid}:author"},
        )
    query = select(CognitionHead).where(
        CognitionHead.novel_id == nid, CognitionHead.scope == "author"
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def current_records(db, novel_id, *, limit=201):
    return list(
        (
            await db.scalars(
                select(CognitionRecord)
                .where(
                    CognitionRecord.novel_id == UUID(str(novel_id)),
                    CognitionRecord.scope == "author",
                    CognitionRecord.is_current.is_(True),
                )
                .order_by(CognitionRecord.created_at.desc(), CognitionRecord.id)
                .limit(limit)
            )
        ).all()
    )


async def revalidate_refs(db, novel_id, refs):
    """Revalidate original revisions and their inherited understanding."""
    pending, checked = list(refs), {}
    while pending:
        ids = [ref.revision_id for ref in pending if ref.revision_id not in checked]
        if not ids:
            break
        if len(checked) + len(ids) > 1000:
            raise ConflictError("理解依赖过长，需要重新整理", code="COGNITION_STALE")
        rows = {
            row.id: row
            for row in (
                await db.scalars(
                    select(CognitionRecord)
                    .where(
                        CognitionRecord.novel_id == UUID(str(novel_id)),
                        CognitionRecord.id.in_(ids),
                    )
                    .execution_options(populate_existing=True)
                )
            ).all()
        }
        inherited = []
        for ref in pending:
            if ref.revision_id in checked:
                continue
            row = rows.get(ref.revision_id)
            if (
                row is None
                or not row.is_current
                or row.author_status == "withdrawn"
                or row.record_id != ref.record_id
                or row.commit_id != ref.commit_id
                or row.content_hash != ref.content_hash
                or row.content_json != ref.content
                or row.author_status != ref.author_status
            ):
                raise ConflictError(
                    "使用的理解已被修正或撤回，请重新读取", code="COGNITION_STALE"
                )
            checked[row.id] = row
            inherited.extend(
                CognitionRef.model_validate(value) for value in row.cognition_refs_json
            )
        pending = inherited
    return list(checked.values())


async def commit_changes(
    db,
    novel_id,
    *,
    operation_id,
    expected_commit_id,
    changes,
    read_set,
    method_version,
    provenance=None,
):
    """Append a receipt and record revisions, moving one author head by CAS."""
    await require_active_project(db, str(novel_id))
    nid, operation = UUID(str(novel_id)), UUID(str(operation_id))
    payload = {
        "expected": str(expected_commit_id) if expected_commit_id else None,
        "changes": changes,
        "read_set": read_set,
        "method": method_version,
        "provenance": provenance or {},
    }
    digest = content_hash(payload)
    head = await read_head(db, novel_id, lock=True)
    prior = await db.scalar(
        select(CognitionCommit).where(
            CognitionCommit.novel_id == nid, CognitionCommit.operation_id == operation
        )
    )
    if prior:
        if prior.request_hash != digest:
            raise ConflictError("该保留请求已用于其他内容", code="OPERATION_MISMATCH")
        return {"commit_id": str(prior.id), "outcome": prior.outcome, "replayed": True}
    current_id = head.commit_id if head else None
    if current_id != expected_commit_id:
        raise ConflictError(
            "理解已有新版本，请读取后再修改", code="COGNITION_HEAD_CHANGED"
        )
    existing = {
        row.record_id: row
        for row in (
            await db.scalars(
                select(CognitionRecord).where(
                    CognitionRecord.novel_id == nid,
                    CognitionRecord.is_current.is_(True),
                    CognitionRecord.record_id.in_(
                        [UUID(value["record_id"]) for value in changes]
                    ),
                )
            )
        ).all()
    }
    pending = []
    for change in changes:
        record_id = UUID(change["record_id"])
        previous = existing.get(record_id)
        if (
            previous
            and change["author_status"] == "derived"
            and previous.author_status != "derived"
        ):
            # Machine results cannot undo an author decision.
            continue
        change = {
            **change,
            "cognition_refs": [
                value
                for value in change.get("cognition_refs", [])
                if value["record_id"] != str(record_id)
            ],
        }
        if previous and all(
            [
                previous.content_json == change["content"],
                previous.dependencies_json == change["dependencies"],
                previous.query_dependencies_json == change.get("query_dependencies", []),
                previous.author_status == change["author_status"],
                previous.learned_at_chapter == change.get("learned_at_chapter"),
                previous.evolution_refs_json == change.get("evolution_refs", []),
            ]
        ):
            # Re-reading unchanged conclusions must not make them depend on each
            # other. Rebind only when the prior derivation is no longer usable.
            try:
                await revalidate_refs(
                    db,
                    novel_id,
                    [
                        CognitionRef.model_validate(value)
                        for value in previous.cognition_refs_json
                    ],
                )
            except ConflictError:
                pass
            else:
                continue
        value_hash = content_hash(
            {key: value for key, value in change.items() if key != "record_id"}
        )
        if previous and previous.content_hash == value_hash:
            continue
        pending.append((record_id, previous, change, value_hash))
    commit = CognitionCommit(
        id=uuid4(),
        novel_id=nid,
        operation_id=operation,
        parent_id=current_id,
        request_hash=digest,
        scope="author",
        outcome="updated" if pending else "no_change",
        method_version=method_version,
        read_set_json=read_set,
        changes_json=[str(item[0]) for item in pending],
        provenance_json=provenance or {},
    )
    db.add(commit)
    await db.flush()
    if not pending:
        return {"commit_id": str(commit.id), "outcome": "no_change", "replayed": False}
    if head is None:
        head = CognitionHead(novel_id=nid, scope="author", generation=0)
        db.add(head)
        await db.flush()
    for record_id, previous, change, value_hash in pending:
        if previous:
            previous.is_current = False
    await db.flush()
    for record_id, _, change, value_hash in pending:
        db.add(
            CognitionRecord(
                novel_id=nid,
                record_id=record_id,
                commit_id=commit.id,
                scope="author",
                content_json=change["content"],
                dependencies_json=change["dependencies"],
                cognition_refs_json=change.get("cognition_refs", []),
                evolution_refs_json=change.get("evolution_refs", []),
                query_dependencies_json=change.get("query_dependencies", []),
                content_hash=value_hash,
                author_status=change["author_status"],
                learned_at_chapter=change.get("learned_at_chapter"),
            )
        )
    moved = await db.execute(
        update(CognitionHead)
        .where(CognitionHead.id == head.id, CognitionHead.generation == head.generation)
        .values(commit_id=commit.id, generation=CognitionHead.generation + 1)
    )
    if moved.rowcount != 1:
        raise ConflictError("理解已有新版本", code="COGNITION_HEAD_CHANGED")
    await db.flush()
    return {"commit_id": str(commit.id), "outcome": "updated", "replayed": False}


async def retain_run_understanding(
    db, novel_id, run, manifest, grant, *, active_output_ids
):
    """Retain reviewed claims with consent, binding the whole run read set.

    A run can read prior results and a shared working record. Its complete set of
    materialized inputs is a conservative dependency for each retained claim.
    """
    if not grant.retain_understanding:
        return {"outcome": "not_authorized"}
    if manifest.subject.kind != "author" or grant.cutoff_chapter or grant.reading_stops:
        return {"outcome": "unsupported_scope"}
    artifacts = list(
        (
            await db.scalars(
                select(CollaborationArtifact)
                .where(
                    CollaborationArtifact.novel_id == UUID(novel_id),
                    CollaborationArtifact.run_id == run.id,
                )
                .order_by(CollaborationArtifact.created_at, CollaborationArtifact.id)
            )
        ).all()
    )
    if any(
        item.workspace_revision_id or item.kind in {"reading_point", "research_sources"}
        for item in artifacts
    ):
        return {"outcome": "unsupported_inputs"}
    manifests = [
        manifest,
        *[InputManifest.model_validate(item.manifest_json) for item in artifacts],
    ]
    from modules.evidence.facade import revalidate_creative_manifest

    dependencies, cognition_refs, queries, evolution_refs = {}, {}, {}, {}
    for packet in manifests:
        if packet.workspace_revision_id or any(
            source.kind
            not in {
                "writing_draft",
                "scene",
                "world_bible_draft",
                "foreshadowing_plan",
                "reveal_plan",
            }
            or source.read_range
            for source in packet.resources
        ):
            return {"outcome": "unsupported_inputs"}
        await revalidate_creative_manifest(db, novel_id, grant, packet)
        for source in packet.resources:
            value = source_dependency(source)
            if source.key in dependencies and dependencies[source.key] != value:
                raise ConflictError("本轮实际来源存在不同版本", code="SOURCE_STALE")
            dependencies[source.key] = value
        for ref in packet.cognition.records:
            cognition_refs[str(ref.revision_id)] = ref.model_dump(mode="json")
        for ref in packet.evolution:
            evolution_refs[ref.receipt_id] = ref.model_dump(mode="json")
        if packet.query_receipt:
            queries[packet.query_scope_hash] = {
                "scope_hash": packet.query_scope_hash,
                "receipt": packet.query_receipt,
            }
    inherited = await revalidate_refs(
        db,
        novel_id,
        [CognitionRef.model_validate(value) for value in cognition_refs.values()],
    )
    for row in inherited:
        for ref in row.evolution_refs_json:
            evolution_refs[ref["receipt_id"]] = ref
        for dependency in row.dependencies_json:
            key = f"{dependency['kind']}:{dependency['id']}"
            if dependencies.get(key) != dependency:
                raise ConflictError(
                    "继承理解的根来源未被本次完整读取", code="SOURCE_STALE"
                )
        for query in row.query_dependencies_json:
            queries[query["scope_hash"]] = query
    from modules.writing.facade import lock_chapter_versions_for_revalidation

    await lock_chapter_versions_for_revalidation(
        db,
        novel_id,
        sorted(
            {
                value["chapter_index"]
                for value in dependencies.values()
                if value["kind"] == "writing_draft" and value["chapter_index"] is not None
            }
        ),
    )
    for packet in manifests:
        await revalidate_creative_manifest(db, novel_id, grant, packet)
    changes = {}
    for artifact in artifacts:
        if (
            artifact.id not in active_output_ids
            or artifact.payload_json.get("knowledge_review", {}).get("status") != "passed"
        ):
            continue
        if artifact.output_hash != content_hash(artifact.payload_json):
            raise ConflictError("工作产物已变化，请重新查证", code="OUTPUT_CHANGED")
        output = WorkOutput.model_validate(
            {
                key: value
                for key, value in artifact.payload_json.items()
                if key in WorkOutput.model_fields
            }
        )
        for claim in output.claims:
            if (
                claim.kind not in {"source_statement", "interpretation", "hypothesis"}
                or not claim.evidence_keys
            ):
                continue
            if (
                set([*claim.evidence_keys, *claim.counterevidence_keys])
                - dependencies.keys()
            ):
                continue
            content = {"schema_version": 1, **claim.model_dump(mode="json")}
            record_id = str(uuid5(UUID(novel_id), "cognition:" + content_hash(content)))
            changes[record_id] = {
                "record_id": record_id,
                "content": content,
                "dependencies": list(dependencies.values()),
                "cognition_refs": list(cognition_refs.values()),
                "evolution_refs": list(evolution_refs.values()),
                "query_dependencies": list(queries.values()),
                "author_status": "derived",
                "learned_at_chapter": max(
                    (value["chapter_index"] or 0 for value in dependencies.values()),
                    default=0,
                )
                or None,
            }
    try:
        return await commit_changes(
            db,
            novel_id,
            operation_id=uuid5(run.id, "retain-understanding"),
            expected_commit_id=manifest.cognition.head_commit_id,
            changes=list(changes.values()),
            read_set=[packet.model_dump(mode="json") for packet in manifests],
            method_version="reviewed-run-claims/v1",
            provenance={
                "run_id": str(run.id),
                "scope": "author_retrospective",
                "author_instructions": {
                    key: run.request_json.get(key) for key in ("goal", "constraints")
                },
                "work_inputs": [
                    item.proposal_json
                    for item in (
                        await db.scalars(
                            select(CollaborationWorkItem).where(
                                CollaborationWorkItem.novel_id == UUID(str(novel_id)),
                                CollaborationWorkItem.run_id == run.id,
                            )
                        )
                    ).all()
                ],
            },
        )
    except ConflictError as error:
        if error.code != "COGNITION_HEAD_CHANGED":
            raise
        return {"outcome": "needs_rebase"}


async def correct_record(db, novel_id, record_id, data):
    await require_active_project(db, novel_id)
    row = await db.scalar(
        select(CognitionRecord).where(
            CognitionRecord.novel_id == UUID(novel_id),
            CognitionRecord.record_id == record_id,
            CognitionRecord.id == data.expected_revision_id,
        )
    )
    if row is None:
        raise NotFoundError("理解记录不可访问")
    if not row.is_current and not await db.scalar(
        select(CognitionCommit.id).where(
            CognitionCommit.novel_id == UUID(novel_id),
            CognitionCommit.operation_id == data.operation_id,
        )
    ):
        raise ConflictError("这条理解已被修正，请对照最新版本", code="COGNITION_STALE")
    change = {
        "record_id": str(row.record_id),
        "content": {
            **row.content_json,
            **(
                {"text": data.text, "kind": "interpretation"}
                if data.action == "correct"
                else {}
            ),
        },
        "dependencies": row.dependencies_json,
        "cognition_refs": row.cognition_refs_json,
        "evolution_refs": row.evolution_refs_json,
        "query_dependencies": row.query_dependencies_json,
        "learned_at_chapter": row.learned_at_chapter,
        "author_status": "corrected" if data.action == "correct" else "withdrawn",
    }
    return await commit_changes(
        db,
        novel_id,
        operation_id=data.operation_id,
        expected_commit_id=data.expected_commit_id,
        changes=[change],
        read_set=[],
        method_version="author-correction/v1",
        provenance={"revision_id": str(row.id)},
    )


async def understanding_view(db, novel_id, *, record_id=None):
    await require_active_project(db, novel_id)
    head = await read_head(db, novel_id)
    if record_id:
        rows = list(
            (
                await db.scalars(
                    select(CognitionRecord)
                    .where(
                        CognitionRecord.novel_id == UUID(novel_id),
                        CognitionRecord.record_id == record_id,
                    )
                    .order_by(CognitionRecord.created_at.desc(), CognitionRecord.id)
                    .limit(50)
                )
            ).all()
        )
    else:
        rows = await current_records(db, novel_id)
    from modules.evidence.facade import inspect_cognition_freshness

    items = []
    for row in rows[:200]:
        freshness = (
            await inspect_cognition_freshness(db, novel_id, row)
            if row.is_current
            else "history"
        )
        items.append(
            {
                "id": str(row.record_id),
                "revision_id": str(row.id),
                "commit_id": str(row.commit_id),
                "text": row.content_json.get("text", ""),
                "kind": row.content_json.get("kind"),
                "author_status": row.author_status,
                "freshness": freshness,
                "source_count": len(row.dependencies_json),
                "learned_at_chapter": row.learned_at_chapter,
                "created_at": row.created_at,
            }
        )
    return {
        "head_commit_id": str(head.commit_id) if head and head.commit_id else None,
        "items": items,
        "complete": len(rows) <= 200,
    }

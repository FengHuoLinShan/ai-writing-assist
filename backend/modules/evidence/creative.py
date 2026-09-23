"""Materialize authorized immutable inputs and safe workspace projections."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from core.container import get
from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.contracts import (
    CognitionSelection,
    Grant,
    InputManifest,
    ResourceRef,
    ResourceSnapshot,
    SubjectView,
)
from modules.evidence.compilation.contracts import VisibilityContextContract
from modules.evidence.compilation.facade import (
    inspect_novel_target,
    prepare_confirmed_ai_action,
)
from modules.project.facade import require_active_project


def manuscript_hashes(resources):
    return {
        str(source.id): hashlib.sha256(source.content["content"].encode()).hexdigest()
        for source in resources
        if source.kind == "writing_draft"
        and not source.read_range
        and isinstance(source.content.get("content"), str)
    }


async def collect_forecast_understanding(
    db, novel_id, *, chapter_index=None, excluded=()
):
    """Read a few reusable interpretations with their complete authorized roots.

    A writing focus admits only earlier complete chapters. Whole-chapter records
    in the current chapter cannot establish a Scene-local knowledge boundary.
    """
    from modules.collaboration.facade import read_cognition_records

    await require_active_project(db, novel_id)
    from modules.writing.facade import list_drafts_by_ids

    excluded_chapters = (
        {
            draft.chapter_index
            for draft in await list_drafts_by_ids(db, novel_id, list(excluded))
        }
        if excluded
        else set()
    )
    rows = await read_cognition_records(db, novel_id)
    ports, sources, omissions = get("collaboration.resources"), {}, []
    chosen = set()
    for row in rows[:200]:
        reason = None
        if row.author_status == "withdrawn":
            reason = "withdrawn"
        elif row.query_dependencies_json:
            reason = "query_scope_requires_explicit_selection"
        elif not row.dependencies_json or any(
            str(dep["id"]) in excluded
            or dep.get("chapter_index") in excluded_chapters
            or dep["kind"] != "writing_draft"
            or dep.get("read_range")
            or (
                chapter_index is not None
                and (
                    not dep.get("chapter_index") or dep["chapter_index"] >= chapter_index
                )
            )
            for dep in row.dependencies_json
        ):
            reason = "source_excluded_or_beyond_focus"
        elif chapter_index is not None and (
            row.author_status != "derived"
            or not row.learned_at_chapter
            or row.learned_at_chapter >= chapter_index
        ):
            reason = "unsupported_historical_derivation"
        elif len(chosen) >= 3:
            reason = "not_selected_capacity"
        if not reason:
            additions = {}
            try:
                for dependency in row.dependencies_json:
                    ref = ResourceRef(kind=dependency["kind"], id=dependency["id"])
                    source = sources.get(ref.key) or await ports[ref.kind].read(
                        db, novel_id, ref
                    )
                    if (
                        source.model_dump(mode="json", exclude={"content", "label"})
                        != dependency
                    ):
                        raise ConflictError("理解的来源已变化", code="SOURCE_STALE")
                    additions[source.key] = source
            except DomainError:
                reason = "source_excluded_or_changed"
            else:
                combined = {**sources, **additions}
                # Leave room in the forecast packet for the author's actual focus.
                if (
                    len(combined) > 32
                    or len(
                        json.dumps(
                            [s.content for s in combined.values()], ensure_ascii=False
                        )
                    )
                    > 8000
                ):
                    reason = "not_selected_capacity"
                else:
                    sources = combined
                    chosen.add(row.record_id)
        if reason:
            omissions.append({"record_id": str(row.record_id), "reason": reason})
    if not sources:
        return None, omissions
    grant = Grant(
        resources=[ResourceRef(kind=s.kind, id=s.id) for s in sources.values()],
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    manifest = InputManifest(
        goal_version=1,
        grant_hash=content_hash(grant.model_dump(mode="json")),
        resources=list(sources.values()),
        query_scope_hash=content_hash(
            [(s.key, s.revision, s.source_hash) for s in sources.values()]
        ),
    )
    manifest.cognition = await materialize_cognition(db, novel_id, grant, manifest)
    manifest.cognition.records = [
        ref for ref in manifest.cognition.records if ref.record_id in chosen
    ]
    creative_context_text(manifest)
    return (manifest if manifest.cognition.records else None), omissions


async def collect_creative_manifest(
    db, novel_id, grant: Grant, goal_version: int, *, query=None, subject=None
):
    await require_active_project(db, novel_id)
    excluded = {ref.key for ref in grant.excluded}
    from modules.writing.facade import list_drafts_by_ids

    excluded_drafts = [
        str(ref.id) for ref in grant.excluded if ref.kind == "writing_draft"
    ]
    excluded_chapters = (
        {
            draft.chapter_index
            for draft in await list_drafts_by_ids(db, novel_id, excluded_drafts)
        }
        if excluded_drafts
        else set()
    )
    selected = None
    confirmed_text = None
    if grant.context_confirmation_id:
        confirmed = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action=grant.context_confirmation_action,
            confirmation_id=str(grant.context_confirmation_id),
        )
        confirmed_text = confirmed.rendered_markdown
        selected = {
            str(value)
            for values in confirmed.confirmation.selected_asset_ids.values()
            for value in values
        }
        denied = {
            str(value)
            for values in confirmed.confirmation.excluded_asset_ids.values()
            for value in values
        }
        selected -= denied
    resources = []
    declared = {ref.key for ref in grant.resources}
    ports = get("collaboration.resources")
    for kind in sorted(set(grant.read_kinds)):
        if kind not in ports:
            raise ValidationError("此资料暂不支持试改", code="RESOURCE_UNSUPPORTED")
        for source in await ports[kind].inventory(db, novel_id):
            if grant.read_scope == "selected" and source.key not in {
                ref.key for ref in grant.resources
            }:
                continue
            if (
                source.key in excluded
                or source.kind == "writing_draft"
                and source.chapter_index in excluded_chapters
                or (selected is not None and str(source.id) not in selected)
            ):
                continue
            if grant.cutoff_chapter:
                if source.kind == "writing_draft":
                    if (
                        source.chapter_index is None
                        or source.chapter_index > grant.cutoff_chapter
                    ):
                        continue
                else:
                    view = await inspect_novel_target(
                        db,
                        novel_id=novel_id,
                        target_ref={
                            "target_type": {
                                "scene": "outline_scene",
                                "world_bible_draft": "world_bible_page_draft",
                            }.get(kind, kind),
                            "target_id": str(source.id),
                        },
                        content_mode="working",
                        visibility=VisibilityContextContract(
                            mode="author", cutoff_chapter=grant.cutoff_chapter
                        ),
                    )
                    if not view.get("visible"):
                        continue
            if confirmed_text is not None and source.key in declared:

                def strings(value):
                    if isinstance(value, str):
                        yield value
                    elif isinstance(value, dict):
                        for item in value.values():
                            yield from strings(item)
                    elif isinstance(value, list):
                        for item in value:
                            yield from strings(item)

                if any(
                    text and text not in confirmed_text
                    for text in strings(source.content)
                ):
                    raise ConflictError(
                        "原确认没有完整覆盖这份试改资源，请在原入口选择完整资料后重新确认",
                        code="CONFIRMATION_SCOPE_CONFLICT",
                    )
            resources.append(source)
    if grant.import_scope:
        from modules.imports.facade import inspect_consultation_scope

        dossier = await inspect_consultation_scope(db, novel_id, grant.import_scope)
        group = ResourceSnapshot(
            kind="import_review_group",
            id=uuid5(
                UUID(novel_id),
                "consult:" + ":".join(sorted(grant.import_scope.asset_keys)),
            ),
            revision=dossier["fingerprint"],
            source_hash=dossier["fingerprint"],
            label="明确选中的导入待决组与原文",
            content=dossier,
            chapter_index=grant.import_scope.chapter_from,
        )
        resources.append(group)
        declared.add(group.key)
    resources.sort(key=lambda source: source.key)
    keys = {source.key for source in resources}
    if any(ref.key not in keys for ref in grant.resources):
        raise NotFoundError("试改资源不在当前可访问资料范围内")
    if len(resources) > 5000:
        raise ValidationError(
            "资料范围过大，请缩小本次调查范围", code="CONTEXT_TOO_LARGE"
        )
    scope_hash = content_hash(
        [(source.key, source.revision, source.source_hash) for source in resources]
    )
    chosen = [source for source in resources if source.key in declared]
    receipt = None
    if query:
        if confirmed_text is not None:
            raise ValidationError(
                "原确认限定了实际材料；新增查证需回到原资料入口",
                code="CONFIRMATION_SCOPE_CONFLICT",
            )
        searchable = project_creative_resources(resources, subject or SubjectView())
        hits = []
        for source in searchable:
            text = json.dumps(source.content, ensure_ascii=False, sort_keys=True)
            offset = text.find(query)
            if offset >= 0:
                hits.append((source, text, offset))
        for source, text, offset in hits[:3]:
            if source.key in declared:
                continue
            start, end = max(0, offset - 200), min(len(text), offset + len(query) + 600)
            excerpt = text[start:end]
            chosen.append(
                source.model_copy(
                    update={
                        "content": {"excerpt": excerpt},
                        "read_range": (start, end),
                        "range_hash": content_hash(excerpt),
                    }
                )
            )
        receipt = {
            "method": "literal",
            "query": query,
            "scanned_resources": len(searchable),
            "matching_resources": len(hits),
            "returned_resources": min(3, len(hits)),
            "complete": len(hits) <= 3,
            "range_format": "serialized_resource_content",
            "note": "未找到字面词语不等于不存在相同含义；这里只回读至多三处。",
        }
    manifest = InputManifest(
        goal_version=goal_version,
        subject=subject or SubjectView(),
        query_receipt=receipt,
        grant_hash=content_hash(grant.model_dump(mode="json")),
        resources=chosen,
        query_scope_hash=scope_hash,
    )
    if (
        manifest.subject.kind == "author"
        and not grant.context_confirmation_id
        and not grant.reading_stops
    ):
        from modules.evolution.facade import read_committed_understanding

        (
            selected_understanding,
            manifest.evolution_omissions,
        ) = await read_committed_understanding(db, novel_id, manuscript_hashes(chosen))
        for ref in selected_understanding:
            trial = manifest.model_copy(update={"evolution": [*manifest.evolution, ref]})
            try:
                creative_context_text(trial)
            except ValidationError as error:
                if error.code != "CONTEXT_TOO_LARGE":
                    raise
                manifest.evolution_omissions.append("not_selected_capacity")
            else:
                manifest.evolution.append(ref)
    manifest.cognition = await materialize_cognition(db, novel_id, grant, manifest)
    return manifest


async def revalidate_creative_manifest(db, novel_id, grant, manifest):
    current = await collect_creative_manifest(
        db,
        novel_id,
        grant,
        manifest.goal_version,
        subject=manifest.subject,
        query=(manifest.query_receipt or {}).get("query"),
    )
    if (
        current.query_scope_hash != manifest.query_scope_hash
        or current.grant_hash != manifest.grant_hash
    ):
        raise ConflictError("参考资料或查询范围已变化，请重新查证", code="SOURCE_STALE")
    if manifest.cognition.records:
        checked = await materialize_cognition(
            db, novel_id, grant, current, frozen_refs=manifest.cognition.records
        )
        if checked.excluded:
            raise ConflictError("已读取理解的来源或适用范围变化", code="COGNITION_STALE")
    if manifest.evolution:
        from modules.evolution.facade import read_committed_understanding

        await read_committed_understanding(
            db,
            novel_id,
            manuscript_hashes(current.resources),
            required=manifest.evolution,
        )
    return current


async def materialize_cognition(db, novel_id, grant, manifest, *, frozen_refs=None):
    """Derived understanding may only reuse the exact original sources chosen now."""
    from modules.collaboration.facade import (
        cognition_record_ref,
        read_cognition_head,
        read_cognition_records,
        revalidate_cognition_refs,
    )

    selection = CognitionSelection(inspected=True)
    head = await read_cognition_head(db, novel_id)
    selection.head_commit_id = head.commit_id if head else None
    if (
        manifest.subject.kind != "author"
        or grant.reading_stops
        or grant.cutoff_chapter
        or manifest.subject.cutoff_chapter
    ):
        selection.excluded = [{"reason": "unsupported_subject_or_cutoff"}]
        return selection
    sources = {source.key: source for source in manifest.resources}
    rows = (
        await revalidate_cognition_refs(db, novel_id, frozen_refs)
        if frozen_refs is not None
        else await read_cognition_records(db, novel_id)
    )
    selection.complete = frozen_refs is not None or len(rows) <= 200
    for row in rows if frozen_refs is not None else rows[:200]:
        reason = ""
        if row.author_status == "withdrawn":
            reason = "withdrawn"
        elif any(
            query["scope_hash"] != manifest.query_scope_hash
            for query in row.query_dependencies_json
        ):
            reason = "query_scope_changed"
        else:
            for dependency in row.dependencies_json:
                source = sources.get(f"{dependency['kind']}:{dependency['id']}")
                if (
                    source is None
                    or source.read_range
                    or source.model_dump(mode="json", exclude={"content", "label"})
                    != dependency
                ):
                    reason = "source_excluded_or_changed"
                    break
        if not reason:
            try:
                await revalidate_cognition_refs(db, novel_id, [cognition_record_ref(row)])
                if row.evolution_refs_json:
                    from modules.evolution.contracts import CommittedUnderstanding
                    from modules.evolution.facade import read_committed_understanding

                    await read_committed_understanding(
                        db,
                        novel_id,
                        manuscript_hashes(manifest.resources),
                        required=[
                            CommittedUnderstanding.model_validate(ref)
                            for ref in row.evolution_refs_json
                        ],
                    )
            except ConflictError:
                reason = "understanding_changed"
        if not reason and frozen_refs is None:
            if len(selection.records) >= 32:
                reason = "not_selected_capacity"
            else:
                trial = selection.model_copy(
                    update={"records": [*selection.records, cognition_record_ref(row)]}
                )
                try:
                    creative_context_text(
                        manifest.model_copy(update={"cognition": trial})
                    )
                except ValidationError as error:
                    if error.code != "CONTEXT_TOO_LARGE":
                        raise
                    reason = "not_selected_capacity"
            if reason:
                selection.complete = False
        if reason:
            selection.excluded.append({"record_id": str(row.record_id), "reason": reason})
        else:
            selection.records.append(cognition_record_ref(row))
    return selection


def project_creative_resources(resources, subject: SubjectView):
    """Reader packets never include plans, goals, World secrets or author reports."""
    if subject.kind in {"author", "environment"}:
        return resources
    if subject.kind == "reader":
        return [
            source
            for source in resources
            if source.kind == "writing_draft"
            and source.chapter_index is not None
            and source.chapter_index <= subject.cutoff_chapter
        ]
    raise ValidationError(
        "人物观察必须从已确认的角色资料构建", code="SUBJECT_SCOPE_UNAVAILABLE"
    )


def creative_context_text(manifest: InputManifest, *, resources=None):
    sources = project_creative_resources(
        resources if resources is not None else manifest.resources, manifest.subject
    )
    text = json.dumps(
        [
            {
                "key": source.key,
                "source_hash": source.source_hash,
                "content": source.content,
                **(
                    {"chapter_index": source.chapter_index}
                    if source.chapter_index is not None
                    else {}
                ),
                **(
                    {"read_range": source.read_range, "range_hash": source.range_hash}
                    if source.read_range
                    else {}
                ),
            }
            for source in sources
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    if manifest.subject.kind == "author" and not manifest.workspace_revision_id:
        source_keys = {source.key: source.source_hash for source in sources}
        original_keys = {source.key: source.source_hash for source in manifest.resources}
        if source_keys == original_keys:
            if manifest.query_receipt:
                text += "\n本轮字面回读范围（过程回执，不是作品事实）：\n" + json.dumps(
                    manifest.query_receipt, ensure_ascii=False, sort_keys=True
                )
            if manifest.evolution:
                text += (
                    "\n已提交场景理解（模型观察；传闻、信念和假设仍非事实，须回读原文）：\n"
                    + json.dumps(
                        [ref.model_dump(mode="json") for ref in manifest.evolution],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            if manifest.cognition.records:
                text += "\n派生理解（可修订；事实仍须引用上方原资料）：\n" + json.dumps(
                    [ref.model_dump(mode="json") for ref in manifest.cognition.records],
                    ensure_ascii=False,
                    sort_keys=True,
                )
    # Group knowledge governance reads 24,000 characters. Reject, never truncate
    # a generator packet and then claim that a partial audit covered it.
    if len(text) > 24000:
        raise ValidationError(
            "本次完整资料超出精确复核范围，请选择更小范围", code="CONTEXT_TOO_LARGE"
        )
    return text


async def inspect_cognition_freshness(db, novel_id, row):
    """Author inspection uses the same resource ports as the task manifest."""
    from core.errors import DomainError
    from modules.collaboration.facade import (
        cognition_record_ref,
        revalidate_cognition_refs,
    )

    if row.author_status == "withdrawn":
        return "withdrawn"
    ports = get("collaboration.resources")
    sources = []
    try:
        await revalidate_cognition_refs(db, novel_id, [cognition_record_ref(row)])
        for dependency in row.dependencies_json:
            port = ports.get(dependency["kind"])
            if port is None or dependency.get("read_range"):
                return "unsupported"
            source = await port.read(
                db, novel_id, ResourceSnapshot(**dependency, label="来源", content={})
            )
            if source.model_dump(mode="json", exclude={"content", "label"}) != dependency:
                return "stale"
            sources.append(source)
        if row.evolution_refs_json:
            from modules.evolution.contracts import CommittedUnderstanding
            from modules.evolution.facade import read_committed_understanding

            await read_committed_understanding(
                db,
                novel_id,
                manuscript_hashes(sources),
                required=[
                    CommittedUnderstanding.model_validate(ref)
                    for ref in row.evolution_refs_json
                ],
            )
    except DomainError:
        return "stale"
    return "needs_scope_check" if row.query_dependencies_json else "current"

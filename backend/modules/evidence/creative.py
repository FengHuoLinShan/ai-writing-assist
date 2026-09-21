"""Materialize authorized immutable inputs and safe workspace projections."""

from __future__ import annotations

import json
from uuid import UUID, uuid5

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.contracts import (
    Grant,
    InputManifest,
    ResourceSnapshot,
    SubjectView,
)
from modules.evidence.compilation.contracts import VisibilityContextContract
from modules.evidence.compilation.facade import (
    inspect_novel_target,
    prepare_confirmed_ai_action,
)
from modules.project.facade import require_active_project


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
    return InputManifest(
        goal_version=goal_version,
        subject=subject or SubjectView(),
        query_receipt=receipt,
        grant_hash=content_hash(grant.model_dump(mode="json")),
        resources=chosen,
        query_scope_hash=scope_hash,
    )


async def revalidate_creative_manifest(db, novel_id, grant, manifest):
    current = await collect_creative_manifest(db, novel_id, grant, manifest.goal_version)
    if (
        current.query_scope_hash != manifest.query_scope_hash
        or current.grant_hash != manifest.grant_hash
    ):
        raise ConflictError("参考资料或查询范围已变化，请重新查证", code="SOURCE_STALE")
    return current


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
    # Group knowledge governance reads 24,000 characters. Reject, never truncate
    # a generator packet and then claim that a partial audit covered it.
    if len(text) > 24000:
        raise ValidationError(
            "本次完整资料超出精确复核范围，请选择更小范围", code="CONTEXT_TOO_LARGE"
        )
    return text

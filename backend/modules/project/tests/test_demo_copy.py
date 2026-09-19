from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import DomainError, NotFoundError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.evidence.compilation.models import EvidenceLink
from modules.imports.models import ImportedChapter, ImportRecord
from modules.project.demo_copy import DemoProjectCopyService
from modules.project.facade import lock_project_ids_for_owner
from modules.project.models import DemoProjectCopy, Project
from modules.project.schemas import ProjectCreate
from modules.project.services import ProjectService
from modules.story.continuity.models import MemoryEvent
from modules.story.outline_state.models import StoryOutlineHead, StoryOutlineRevision
from modules.world.authority import (
    EXPLICIT_AUTHOR_POLICY_REF,
    CanonAdmissionReceiptV1,
    CanonManifestV1,
    ExactResourceRevisionRef,
    ResourceRef,
    bootstrap_decision_id,
    canonical_digest,
    resource_revision_digest,
)
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_storage import page_object_key
from modules.world.models import CoreEntity, EntityRelation
from modules.world.models.authority import (
    EntityProfileTemplateRevision,
    WorldCanonHead,
    WorldCanonRevision,
)
from modules.world.models.profiles import EntityProfileTemplate
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.world_object_images import CHARACTER_IMAGE_LIMIT, image_object_key
from modules.writing.models import WritingDraft

_FAMILIES = ("name", "typed_scalar", "binary_relation", "event_time", "belief")
_TEMPLATE_SNAPSHOT = {"fields": [], "title": "人物模板"}


def _principal(
    account: Account,
    *,
    identity_type: str = "email",
    **kwargs,
) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type=identity_type,
        support_code=account.support_code,
        **kwargs,
    )


async def _seed_source(db: AsyncSession) -> tuple[Account, Account, Project]:
    source_owner = Account(status="active", support_code="DEMO-SOURCE")
    target_owner = Account(status="active", support_code="DEMO-TARGET")
    db.add_all([source_owner, target_owner])
    await db.flush()
    source = Project(
        owner_id=source_owner.id,
        title="公开演示小说",
        language="zh",
        default_reveal_policy="author_safe",
        settings={"llm": {"api_key": "legacy-secret", "model": "ignored"}},
    )
    db.add(source)
    await db.flush()
    outline = StoryOutlineRevision(
        novel_id=source.id,
        version_number=1,
        title="演示总纲",
        creative_core_json={},
        outline_markdown="总纲",
        major_storylines_json=[],
        macro_movements_json=[],
        open_decisions_json=[],
        source="manual",
        provenance_json={},
        idempotency_key="demo-outline",
        request_hash="c" * 64,
        content_hash="d" * 64,
    )
    db.add(outline)
    await db.flush()
    db.add(StoryOutlineHead(novel_id=source.id, current_revision_id=outline.id))

    record = ImportRecord(
        novel_id=source.id,
        file_name="source.txt",
        file_type="txt",
        file_size=12,
        total_chapters=1,
        imported_chapters=1,
        status="done",
    )
    first = CoreEntity(
        novel_id=source.id,
        entity_type="character",
        name="林舟",
        summary="source entity",
        status="canonical",
    )
    second = CoreEntity(
        novel_id=source.id,
        entity_type="location",
        name="雾港",
        summary="source location",
        content_json={},
        status="canonical",
    )
    candidate = CoreEntity(
        novel_id=source.id,
        entity_type="item",
        name="临时候选",
        status="candidate",
    )
    db.add_all([record, first, second, candidate])
    await db.flush()
    second.content_json = {"linked": str(first.id), "project_id": str(source.id)}
    chapter = ImportedChapter(
        novel_id=source.id,
        import_record_id=record.id,
        chapter_index=1,
        title="第一章",
        content="演示正文",
    )
    relation = EntityRelation(
        novel_id=source.id,
        source_id=first.id,
        target_id=second.id,
        relation_type="抵达",
        relation_kind="spatial",
        status="canonical",
    )
    memory_event = MemoryEvent(
        novel_id=source.id,
        chapter_index=1,
        scene_id=None,
        scene_index=None,
        scene_sequence=None,
        dimension="entities",
        sequence=1,
        event_type="entity_updated",
        entity_id=first.id,
        entity_type="character",
        snapshot_before=None,
        snapshot_after={"entity_id": str(first.id), "project_id": str(source.id)},
        source="manual_edit",
    )
    evidence = EvidenceLink(
        novel_id=source.id,
        target_ref={"entity_id": str(first.id)},
        target_hash="c" * 64,
        claim_path="summary",
        evidence_type="manuscript",
        source_ref={"chapter_index": 1, "project_id": str(source.id)},
        precision="range",
        status="active",
        provenance={},
    )
    template = EntityProfileTemplate(
        id=uuid.uuid4(),
        novel_id=source.id,
        profile_type="character",
        template_schema_json={"fields": []},
        display_schema_json={},
        version_number=1,
        status="active",
    )
    template_revision = EntityProfileTemplateRevision(
        id=uuid.uuid4(),
        novel_id=source.id,
        template_id=template.id,
        version_number=1,
        snapshot_json=_TEMPLATE_SNAPSHOT,
        revision_reason="bootstrap",
    )
    template_revision.revision_digest = resource_revision_digest(
        ResourceRef(
            kind="entity_profile_template",
            novel_id=source.id,
            resource_id=template.id,
        ),
        template_revision.id,
        _TEMPLATE_SNAPSHOT,
    )
    source_manifest = CanonManifestV1(
        family_authority={family: "formal-disabled" for family in _FAMILIES},
        active_resources=[
            ExactResourceRevisionRef(
                resource=ResourceRef(
                    kind="entity_profile_template",
                    novel_id=source.id,
                    resource_id=template.id,
                ),
                revision_id=template_revision.id,
                revision_digest=template_revision.revision_digest,
            )
        ],
    )
    canon_revision = WorldCanonRevision(
        id=uuid.uuid4(),
        novel_id=source.id,
        version_number=1,
        parent_revision_id=None,
        manifest_json=source_manifest.model_dump(mode="json"),
        manifest_digest=canonical_digest(source_manifest),
        receipt_json={},
        decision_id=uuid.uuid4(),
        decision_digest="e" * 64,
        created_at=datetime.now(UTC),
    )
    db.add_all(
        [
            chapter,
            relation,
            memory_event,
            evidence,
            template,
            template_revision,
            canon_revision,
            WritingDraft(
                novel_id=source.id,
                chapter_index=1,
                title="第一章",
                content="可编辑正文",
                content_hash="a" * 64,
                version_number=1,
                status="published",
            ),
            WritingDraft(
                novel_id=source.id,
                chapter_index=2,
                title="候选",
                content="不复制",
                content_hash="b" * 64,
                version_number=1,
                status="candidate",
            ),
        ]
    )
    await db.flush()
    db.add(
        WorldCanonHead(
            novel_id=source.id,
            current_revision_id=canon_revision.id,
        )
    )
    await db.flush()
    return source_owner, target_owner, source


@pytest.mark.asyncio
async def test_demo_copy_rewrites_author_assets_and_is_idempotent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source_owner, target_owner, source = await _seed_source(db_session)
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(source.id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "2026-09-14")
    get_settings.cache_clear()
    token = bind_principal(_principal(target_owner))
    try:
        from tests.fixtures.immutable_writes import forbid_immutable_writes

        service = DemoProjectCopyService()
        with forbid_immutable_writes(db_session) as guard:
            created = await service.copy(db_session)
            existing = await service.copy(db_session)
        guard.assert_clean()
        copied_id = uuid.UUID(created.project.id)

        assert created.status == "created"
        assert existing.status == "existing"
        assert copied_id != source.id
        assert created.project.settings.get("llm", {}).get("api_key") is None

        copied_chapter = (
            await db_session.execute(
                select(ImportedChapter).where(ImportedChapter.novel_id == copied_id)
            )
        ).scalar_one()
        assert copied_chapter.content == "演示正文"
        assert (
            copied_chapter.import_record_id
            != (
                await db_session.execute(
                    select(ImportRecord.id).where(ImportRecord.novel_id == source.id)
                )
            ).scalar_one()
        )

        drafts = list(
            (
                await db_session.execute(
                    select(WritingDraft).where(WritingDraft.novel_id == copied_id)
                )
            ).scalars()
        )
        assert [(draft.chapter_index, draft.status) for draft in drafts] == [
            (1, "published")
        ]

        copied_entities = {
            entity.name: entity
            for entity in (
                await db_session.execute(
                    select(CoreEntity).where(CoreEntity.novel_id == copied_id)
                )
            ).scalars()
        }
        assert set(copied_entities) == {"林舟", "雾港"}
        assert copied_entities["雾港"].content_json == {
            "linked": str(copied_entities["林舟"].id),
            "project_id": str(copied_id),
        }
        copied_relation = (
            await db_session.execute(
                select(EntityRelation).where(EntityRelation.novel_id == copied_id)
            )
        ).scalar_one()
        assert copied_relation.source_id == copied_entities["林舟"].id
        assert copied_relation.target_id == copied_entities["雾港"].id

        copied_memory = (
            await db_session.execute(
                select(MemoryEvent).where(MemoryEvent.novel_id == copied_id)
            )
        ).scalar_one()
        assert copied_memory.entity_id == copied_entities["林舟"].id
        assert copied_memory.snapshot_after == {
            "entity_id": str(copied_entities["林舟"].id),
            "project_id": str(copied_id),
        }
        copied_evidence = (
            await db_session.execute(
                select(EvidenceLink).where(EvidenceLink.novel_id == copied_id)
            )
        ).scalar_one()
        assert copied_evidence.target_ref == {
            "entity_id": str(copied_entities["林舟"].id)
        }
        copied_canon_head = await db_session.get(WorldCanonHead, copied_id)
        assert copied_canon_head is not None
        copied_canon_revisions = list(
            (
                await db_session.execute(
                    select(WorldCanonRevision).where(
                        WorldCanonRevision.novel_id == copied_id
                    )
                )
            ).scalars()
        )
        assert sorted(rev.version_number for rev in copied_canon_revisions) == [0, 1]
        bootstrap_revision = next(
            rev for rev in copied_canon_revisions if rev.version_number == 0
        )
        import_revision = next(
            rev for rev in copied_canon_revisions if rev.version_number == 1
        )
        assert copied_canon_head.current_revision_id == import_revision.id
        assert bootstrap_revision.decision_id == bootstrap_decision_id(copied_id)
        assert import_revision.parent_revision_id == bootstrap_revision.id
        source_canon_revision = (
            await db_session.execute(
                select(WorldCanonRevision).where(
                    WorldCanonRevision.novel_id == source.id
                )
            )
        ).scalar_one()
        receipt = import_revision.receipt_json
        assert receipt["action"] == "demo_import"
        assert receipt["authorization_policy"]["artifact_id"] == "world.canon.demo-import"
        with pytest.raises(ValueError, match="invalid explicit-author receipt"):
            CanonAdmissionReceiptV1.model_validate({
                **receipt,
                "authorization_policy": EXPLICIT_AUTHOR_POLICY_REF.model_dump(
                    mode="json"
                ),
            })
        assert receipt["authorizer"] == {
            "kind": "account",
            "version": 1,
            "account_id": str(target_owner.id),
        }
        assert receipt["expected_previous_head"] == str(bootstrap_revision.id)
        admission_input = receipt["admission_input"]
        assert admission_input["kind"] == "demo_import"
        assert admission_input["source_project_id"] == str(source.id)
        assert (
            admission_input["source_head_revision_id"]
            == str(source_canon_revision.id)
        )
        assert (
            admission_input["source_head_manifest_digest"]
            == source_canon_revision.manifest_digest
        )
        copied_template = (
            await db_session.execute(
                select(EntityProfileTemplate).where(
                    EntityProfileTemplate.novel_id == copied_id
                )
            )
        ).scalar_one()
        copied_template_revision = (
            await db_session.execute(
                select(EntityProfileTemplateRevision).where(
                    EntityProfileTemplateRevision.novel_id == copied_id
                )
            )
        ).scalar_one()
        manifest_ref = import_revision.manifest_json["active_resources"][0]
        assert manifest_ref["resource"]["resource_id"] == str(copied_template.id)
        assert manifest_ref["revision_id"] == str(copied_template_revision.id)
        from modules.world.canon_import import revision_import_digest

        assert manifest_ref["revision_digest"] == revision_import_digest(
            "entity_profile_template",
            novel_id=copied_id,
            resource_id=copied_template.id,
            revision_id=copied_template_revision.id,
            snapshot=_TEMPLATE_SNAPSHOT,
        )
        # The copied canon must replay end to end through the authority kernel.
        await WorldAuthorityService().get_head(db_session, str(copied_id))
        source_outline = (
            await db_session.execute(
                select(StoryOutlineRevision).where(
                    StoryOutlineRevision.novel_id == source.id
                )
            )
        ).scalar_one()
        copied_outline = (
            await db_session.execute(
                select(StoryOutlineRevision).where(
                    StoryOutlineRevision.novel_id == copied_id
                )
            )
        ).scalar_one()
        copied_head = (
            await db_session.execute(
                select(StoryOutlineHead).where(StoryOutlineHead.novel_id == copied_id)
            )
        ).scalar_one()
        assert copied_outline.id != source_outline.id
        assert copied_head.current_revision_id == copied_outline.id

        copied_project = await db_session.get(Project, copied_id)
        assert copied_project is not None
        copied_project.deleted_at = datetime.now(UTC)
        await db_session.flush()
        restored = await service.copy(db_session)
        assert restored.status == "restored"
        assert (await db_session.get(Project, copied_id)).deleted_at is None
        copies = list((await db_session.execute(select(DemoProjectCopy))).scalars())
        assert len(copies) == 1
    finally:
        reset_principal(token)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_demo_copy_recovers_a_concurrent_unique_conflict(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source_owner, target_owner, source = await _seed_source(db_session)
    winner = Project(
        owner_id=target_owner.id,
        title="已创建的演示副本",
        language="zh",
        default_reveal_policy="author_safe",
        settings={},
    )
    db_session.add(winner)
    await db_session.flush()
    db_session.add(
        DemoProjectCopy(
            owner_id=target_owner.id,
            source_project_id=source.id,
            source_version="concurrent-v1",
            project_id=winner.id,
        )
    )
    await db_session.flush()
    project_count = int(await db_session.scalar(select(func.count(Project.id))) or 0)

    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(source.id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "concurrent-v1")
    get_settings.cache_clear()
    token = bind_principal(_principal(target_owner))
    service = DemoProjectCopyService()
    find_copy = service._find_copy
    calls = 0

    async def hide_first_lookup(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return await find_copy(*args, **kwargs)

    monkeypatch.setattr(service, "_find_copy", hide_first_lookup)
    try:
        result = await service.copy(db_session)

        assert result.status == "existing"
        assert result.project.id == str(winner.id)
        assert (
            int(await db_session.scalar(select(func.count(Project.id))) or 0)
            == project_count
        )
    finally:
        reset_principal(token)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_demo_principal_is_limited_to_the_configured_project(
    db_session: AsyncSession,
) -> None:
    source_owner, _target_owner, source = await _seed_source(db_session)
    other = Project(
        owner_id=source_owner.id,
        title="同 owner 的私有项目",
        language="zh",
        default_reveal_policy="author_safe",
        settings={},
    )
    db_session.add(other)
    await db_session.flush()
    token = bind_principal(
        _principal(
            source_owner,
            identity_type="demo_readonly",
            access_scope="demo_readonly",
            demo_project_id=source.id,
        )
    )
    try:
        service = ProjectService()
        listed = await service.list_projects(db_session)
        assert [item.id for item in listed.items] == [str(source.id)]
        detail = await service.get_project(db_session, str(source.id))
        assert detail.id == str(source.id)
        with pytest.raises(NotFoundError):
            await service.get_project(db_session, str(other.id))
        with pytest.raises(NotFoundError):
            await service.create_project(db_session, data=ProjectCreate(title="blocked"))
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_demo_copy_copies_world_object_media_with_fresh_keys(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source_owner, target_owner, source = await _seed_source(db_session)
    entity = (
        await db_session.execute(
            select(CoreEntity).where(
                CoreEntity.novel_id == source.id,
                CoreEntity.name == "林舟",
            )
        )
    ).scalar_one()
    entity.image_version = uuid.uuid4()
    await db_session.flush()
    storage = _ImageStorage()
    lock_acquired = False

    async def tracked_lock(db, owner_id):
        nonlocal lock_acquired
        lock_acquired = True
        return await lock_project_ids_for_owner(db, owner_id)

    def require_unlocked_storage() -> None:
        assert lock_acquired is False

    storage.on_io = require_unlocked_storage
    monkeypatch.setattr(
        "modules.project.demo_copy.lock_project_ids_for_owner",
        tracked_lock,
    )
    for variant in ("full", "thumbnail"):
        source_key = image_object_key(
            str(source.id), str(entity.id), str(entity.image_version), variant
        )
        storage.objects[source_key] = variant.encode()

    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(source.id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "with-image")
    get_settings.cache_clear()
    token = bind_principal(_principal(target_owner))
    try:
        result = await DemoProjectCopyService(image_storage=storage).copy(db_session)
        copied_id = uuid.UUID(result.project.id)
        copied = (
            await db_session.execute(
                select(CoreEntity).where(
                    CoreEntity.novel_id == copied_id,
                    CoreEntity.name == "林舟",
                )
            )
        ).scalar_one()
        assert lock_acquired is True
        assert copied.image_version is not None
        assert copied.image_version != entity.image_version
        for variant in ("full", "thumbnail"):
            assert (
                storage.objects[
                    image_object_key(
                        str(copied_id), str(copied.id), str(copied.image_version), variant
                    )
                ]
                == variant.encode()
            )
    finally:
        reset_principal(token)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_demo_copy_rejects_images_above_the_account_quota(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source_owner, target_owner, source = await _seed_source(db_session)
    source_entity = (
        await db_session.execute(
            select(CoreEntity).where(
                CoreEntity.novel_id == source.id,
                CoreEntity.name == "林舟",
            )
        )
    ).scalar_one()
    source_entity.image_version = uuid.uuid4()
    quota_project = Project(
        owner_id=target_owner.id,
        title="图片配额",
        language="zh",
        default_reveal_policy="author_safe",
        settings={},
    )
    db_session.add(quota_project)
    await db_session.flush()
    db_session.add_all(
        [
            CoreEntity(
                novel_id=quota_project.id,
                entity_type="character",
                name=f"已有人物 {index}",
                status="canonical",
                image_version=uuid.uuid4(),
            )
            for index in range(CHARACTER_IMAGE_LIMIT)
        ]
    )
    await db_session.flush()
    storage = _ImageStorage()
    storage.on_delete = lambda: (
        None
        if not db_session.in_transaction()
        else pytest.fail("必须在释放账户配额锁后清理对象存储")
    )
    for variant in ("full", "thumbnail"):
        storage.objects[
            image_object_key(
                str(source.id),
                str(source_entity.id),
                str(source_entity.image_version),
                variant,
            )
        ] = variant.encode()

    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(source.id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "image-quota")
    get_settings.cache_clear()
    token = bind_principal(_principal(target_owner))
    try:
        with pytest.raises(DomainError, match="人物图片已达上限"):
            await DemoProjectCopyService(image_storage=storage).copy(db_session)
        assert len(storage.objects) == 2
    finally:
        reset_principal(token)
        get_settings.cache_clear()


class _ImageStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.on_io = lambda: None
        self.on_delete = lambda: None

    async def get_webp(self, key: str, *, max_bytes: int) -> bytes:
        del max_bytes
        self.on_io()
        return self.objects[key]

    async def put_webp(self, key: str, payload: bytes) -> None:
        self.on_io()
        self.objects[key] = payload

    async def delete_object(self, key: str) -> None:
        self.on_delete()
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_demo_copy_rewrites_map_media_into_the_destination_prefix(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source_owner, target_owner, source = await _seed_source(db_session)
    run = MapAtlasRun(novel_id=source.id, run_kind="initial", status="completed")
    unfinished_run = MapAtlasRun(
        novel_id=source.id,
        run_kind="update",
        status="partial",
    )
    node = MapAtlasNode(
        novel_id=source.id,
        semantic_key="world",
        title="世界地图",
        level="world",
        status="adopted",
    )
    db_session.add_all([run, unfinished_run, node])
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=source.id,
        run_id=run.id,
        node_id=node.id,
        generation_status="review_ready",
        review_status="adopted",
        title="世界地图",
        visual_brief="海岸线",
        prompt="世界地图",
    )
    db_session.add(page)
    db_session.add(
        MapAtlasPage(
            novel_id=source.id,
            run_id=unfinished_run.id,
            node_id=node.id,
            generation_status="review_ready",
            review_status="adopted",
            title="未完成地图",
            visual_brief="尚未收口",
            prompt="不应复制",
        )
    )
    await db_session.flush()
    source_key = page_object_key(str(source.id), str(page.id))
    page.object_key = source_key
    await db_session.flush()
    storage = _MapStorage({source_key: b"png"})

    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(source.id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "with-map")
    get_settings.cache_clear()
    token = bind_principal(_principal(target_owner))
    try:
        result = await DemoProjectCopyService(map_storage=storage).copy(db_session)
        copied_id = uuid.UUID(result.project.id)
        copied_page = (
            await db_session.execute(
                select(MapAtlasPage).where(MapAtlasPage.novel_id == copied_id)
            )
        ).scalar_one()
        expected_key = page_object_key(str(copied_id), str(copied_page.id))
        assert copied_page.object_key == expected_key
        assert storage.objects[copied_page.object_key] == b"png"
        copied_run = await db_session.get(MapAtlasRun, copied_page.run_id)
        assert copied_run is not None
        assert copied_run.task_id is None
        assert copied_run.status == "completed"
        assert (
            await db_session.scalar(
                select(func.count(MapAtlasRun.id)).where(
                    MapAtlasRun.novel_id == copied_id
                )
            )
            == 1
        )
    finally:
        reset_principal(token)
        get_settings.cache_clear()


class _MapStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    async def get_png(self, key: str) -> bytes:
        return self.objects[key]

    async def put_png(self, key: str, payload: bytes) -> None:
        self.objects[key] = payload

    async def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_owner_advisory_lock_applies_before_project_lookup() -> None:
    db = _PostgresLikeSession()

    assert await lock_project_ids_for_owner(db, uuid.uuid4()) == []
    assert "pg_advisory_xact_lock" in str(db.calls[0][0])
    assert len(db.calls) == 2


class _PostgresLikeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object | None]] = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

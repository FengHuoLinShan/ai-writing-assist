"""Demo copy against the trigger-enabled PostgreSQL schema.

The unit suite runs on SQLite without triggers, so only here can we prove
that the copy protocol never rewrites an immutable revision row, that the
re-based canon replays through the authority kernel, and that a mid-copy
failure leaves no residue.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from core.errors import DomainError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.evidence.compilation.models import EvidenceLink
from modules.project.demo_copy import DemoProjectCopyService
from modules.project.models import DemoProjectCopy, Project
from modules.story.models import CharacterCard, CharacterCardRevision
from modules.story.outline_state.models import StoryOutlineHead, StoryOutlineRevision
from modules.world.authority import (
    CanonManifestV1,
    ExactResourceRevisionRef,
    ResourceRef,
    bootstrap_decision_id,
    resource_revision_digest,
)
from modules.world.models import CoreEntity
from modules.world.models.authority import (
    EntityProfileTemplateRevision,
    WorldCanonHead,
    WorldCanonRevision,
)
from modules.world.models.profiles import EntityProfileTemplate
from modules.world.models.worldbuilding import WorldBiblePage, WorldBiblePageRevision
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from tests.e2e.config import DATABASE_URL
from tests.fixtures.immutable_writes import forbid_immutable_writes

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

_TEMPLATE_SNAPSHOT = {"fields": [], "title": "人物模板"}


def _principal(account_id: uuid.UUID, support_code: str) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account_id,
        status="active",
        identity_type="email",
        support_code=support_code,
    )


async def _require_immutable_triggers(engine) -> None:
    """Fail loudly when the schema does not carry the immutability guards."""
    statement = text(
        """
        SELECT tgrelid::regclass::text
        FROM pg_trigger
        WHERE NOT tgisinternal
          AND tgrelid IN (
            'world_canon_revisions'::regclass,
            'story_outline_revisions'::regclass
          )
        """
    )
    async with engine.connect() as connection:
        guarded = {
            row[0] for row in (await connection.execute(statement)).fetchall()
        }
    assert "world_canon_revisions" in guarded
    assert "story_outline_revisions" in guarded


async def _seed_history_source(
    db, *, source_id: uuid.UUID, owner_id: uuid.UUID, copy_owner_id: uuid.UUID
):
    """Create one demo source carrying real revision history.

    Includes an outline tree (DAG with a cross reference), a character-card
    head/revision FK cycle, and a canon head whose manifest references an
    entity profile template revision.
    """
    db.add_all(
        [
            Account(
                id=owner_id,
                status="active",
                support_code=f"DEMO-HISTORY-{owner_id.hex[:12]}",
            ),
            Account(
                id=copy_owner_id,
                status="active",
                support_code=f"DEMO-HISTORY-{copy_owner_id.hex[:12]}",
            ),
        ]
    )
    source = Project(
        id=source_id,
        owner_id=owner_id,
        title="带历史演示源",
        project_kind="author",
        language="zh",
        default_reveal_policy="author_safe",
        settings={},
    )
    db.add(source)
    await db.flush()
    authority = WorldAuthorityService()
    bootstrap_revision = await authority.initialize_empty_canon(db, str(source_id))

    entity = CoreEntity(
        novel_id=source_id,
        entity_type="item",
        name="来源道具",
        status="canonical",
        content_json={"project_id": str(source_id)},
    )
    db.add(entity)
    await db.flush()
    page = WorldBiblePage(
        novel_id=source_id,
        page_type="location",
        page_key="linked-place",
        title="关联地点",
        status="canonical",
        linked_asset_refs_json=[{"type": "profile", "id": str(entity.id)}],
    )
    db.add(page)
    await db.flush()
    page_snapshot = {
        "page_type": page.page_type,
        "page_key": page.page_key,
        "title": page.title,
        "status": page.status,
        "page_meta_json": page.page_meta_json,
        "free_text": page.free_text,
        "sections_json": page.sections_json,
        "linked_asset_refs_json": page.linked_asset_refs_json,
        "activation_defaults_json": page.activation_defaults_json,
        "template_key": page.template_key,
        "template_version": page.template_version,
        "sort_order": page.sort_order,
    }
    page_revision_id = uuid.uuid4()
    page_revision = WorldBiblePageRevision(
        id=page_revision_id,
        novel_id=source_id,
        page_id=page.id,
        version_number=1,
        snapshot_json=page_snapshot,
        revision_digest=resource_revision_digest(
            ResourceRef(kind="world_bible_page", novel_id=source_id, resource_id=page.id),
            page_revision_id,
            page_snapshot,
        ),
        revision_reason="bootstrap",
    )
    db.add(page_revision)
    await db.flush()

    template_id = uuid.uuid4()
    template_revision_id = uuid.uuid4()
    template = EntityProfileTemplate(
        id=template_id,
        novel_id=source_id,
        profile_type="character",
        template_schema_json={"fields": []},
        display_schema_json={},
        version_number=1,
        status="active",
    )
    snapshot = dict(_TEMPLATE_SNAPSHOT)
    template_revision = EntityProfileTemplateRevision(
        id=template_revision_id,
        novel_id=source_id,
        template_id=template_id,
        version_number=1,
        snapshot_json=snapshot,
        revision_reason="bootstrap",
    )
    template_revision.revision_digest = resource_revision_digest(
        ResourceRef(
            kind="entity_profile_template",
            novel_id=source_id,
            resource_id=template_id,
        ),
        template_revision_id,
        snapshot,
    )
    manifest = CanonManifestV1(
        family_authority={
            family: "formal-disabled"
            for family in (
                "name", "typed_scalar", "binary_relation", "event_time", "belief",
            )
        },
        active_resources=[
            ExactResourceRevisionRef(
                resource=ResourceRef(
                    kind="entity_profile_template",
                    novel_id=source_id,
                    resource_id=template_id,
                ),
                revision_id=template_revision_id,
                revision_digest=template_revision.revision_digest,
            ),
            ExactResourceRevisionRef(
                resource=ResourceRef(
                    kind="world_bible_page", novel_id=source_id, resource_id=page.id
                ),
                revision_id=page_revision.id,
                revision_digest=page_revision.revision_digest,
            ),
        ],
    )
    # The ORM unit of work does not order this composite-FK pair reliably on
    # PostgreSQL, so the parent row is flushed before the revision row.
    db.add(template)
    await db.flush()
    db.add(template_revision)
    await db.flush()
    # Append the source head revision through the real admission protocol so
    # the seeded source canon is fully replay-valid.
    await authority.append_demo_import_revision(
        db,
        novel_id=str(source_id),
        authorizer_id=owner_id,
        source_project_id=source_id,
        source_demo_version="seed-v1",
        source_head_revision_id=bootstrap_revision.id,
        source_head_manifest_digest=bootstrap_revision.manifest_digest,
        manifest=manifest,
        decision_id=uuid.uuid4(),
    )
    await db.flush()

    outline_root_id, outline_branch_id, outline_head_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    outline_root = StoryOutlineRevision(
        id=outline_root_id,
        novel_id=source_id,
        version_number=1,
        title="总纲 v1",
        creative_core_json={},
        outline_markdown="v1",
        major_storylines_json=[],
        macro_movements_json=[],
        open_decisions_json=[],
        source="manual",
        provenance_json={},
        idempotency_key="demo-history-v1",
        request_hash="1" * 64,
        content_hash="a" * 64,
    )
    outline_branch = StoryOutlineRevision(
        id=outline_branch_id,
        novel_id=source_id,
        version_number=2,
        base_revision_id=outline_root_id,
        title="总纲 v2",
        creative_core_json={},
        outline_markdown="v2",
        major_storylines_json=[],
        macro_movements_json=[],
        open_decisions_json=[],
        source="manual",
        provenance_json={},
        idempotency_key="demo-history-v2",
        request_hash="2" * 64,
        content_hash="b" * 64,
    )
    outline_head_revision = StoryOutlineRevision(
        id=outline_head_id,
        novel_id=source_id,
        version_number=3,
        base_revision_id=outline_root_id,
        restored_from_revision_id=outline_branch_id,
        title="总纲 v3",
        creative_core_json={},
        outline_markdown="v3",
        major_storylines_json=[],
        macro_movements_json=[],
        open_decisions_json=[],
        source="restore",
        provenance_json={},
        idempotency_key="demo-history-v3",
        request_hash="3" * 64,
        content_hash="c" * 64,
    )
    db.add_all([outline_root, outline_branch, outline_head_revision])
    await db.flush()
    db.add(
        StoryOutlineHead(
            novel_id=source_id, current_revision_id=outline_head_revision.id
        )
    )

    card = CharacterCard(
        novel_id=source_id,
        scene_id=uuid.uuid4(),
        character_id=uuid.uuid4(),
        stale=False,
    )
    db.add(card)
    await db.flush()
    card_revisions = [
        CharacterCardRevision(
            novel_id=source_id,
            card_id=card.id,
            scene_id=card.scene_id,
            character_id=card.character_id,
            version_number=version,
            payload_json={"version": version, "project_id": str(source_id)},
            content_hash=("d" * 31 + str(version)).ljust(64, "0"),
            status="canonical",
        )
        for version in (1, 2)
    ]
    db.add_all(card_revisions)
    await db.flush()
    card.current_revision_id = card_revisions[-1].id

    db.add(
        EvidenceLink(
            novel_id=source_id,
            target_ref={"entity_id": str(entity.id), "project_id": str(source_id)},
            target_hash="f" * 64,
            evidence_type="manuscript",
            source_ref={"project_id": str(source_id)},
            status="active",
        )
    )
    await db.flush()
    return {"entity_id": entity.id}


def _demo_env(
    monkeypatch: pytest.MonkeyPatch, source_id: uuid.UUID, version: str
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("AUTH_SECRET_KEY", "e2e-demo-history-secret-key-32-bytes")
    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", str(source_id))
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", version)
    get_settings.cache_clear()


async def test_demo_copy_rebases_history_without_rewriting_immutables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_owner_id = uuid.uuid4()
    target_owner_id = uuid.uuid4()
    source_id = uuid.uuid4()
    _demo_env(monkeypatch, source_id, "history-v1")
    try:
        await _require_immutable_triggers(engine)
        async with sessions.begin() as setup_db:
            await _seed_history_source(
                setup_db,
                source_id=source_id,
                owner_id=source_owner_id,
                copy_owner_id=target_owner_id,
            )

        support_code = f"DEMO-HISTORY-{target_owner_id.hex[:12]}"
        token = bind_principal(_principal(target_owner_id, support_code))
        try:
            async with sessions.begin() as db:
                service = DemoProjectCopyService()
                with forbid_immutable_writes(db) as guard:
                    result = await service.copy(db)
                guard.assert_clean()
        finally:
            reset_principal(token)

        copied_id = uuid.UUID(result.project.id)
        async with sessions() as verify_db:
            canon_revisions = list(
                (
                    await verify_db.execute(
                        select(WorldCanonRevision).where(
                            WorldCanonRevision.novel_id == copied_id
                        )
                    )
                ).scalars()
            )
            assert sorted(rev.version_number for rev in canon_revisions) == [0, 1]
            bootstrap_revision = next(
                rev for rev in canon_revisions if rev.version_number == 0
            )
            import_revision = next(
                rev for rev in canon_revisions if rev.version_number == 1
            )
            assert bootstrap_revision.decision_id == bootstrap_decision_id(copied_id)
            assert import_revision.parent_revision_id == bootstrap_revision.id
            head = await verify_db.get(WorldCanonHead, copied_id)
            assert head is not None
            assert head.current_revision_id == import_revision.id
            receipt = import_revision.receipt_json
            assert receipt["action"] == "demo_import"
            assert (
                receipt["authorization_policy"]["artifact_id"]
                == "world.canon.demo-import"
            )
            assert receipt["admission_input"]["source_project_id"] == str(source_id)

            outline_revisions = list(
                (
                    await verify_db.execute(
                        select(StoryOutlineRevision).where(
                            StoryOutlineRevision.novel_id == copied_id
                        )
                    )
                ).scalars()
            )
            outline_head = (
                await verify_db.execute(
                    select(StoryOutlineHead).where(
                        StoryOutlineHead.novel_id == copied_id
                    )
                )
            ).scalar_one()
            assert outline_head is not None
            head_copied = next(
                rev
                for rev in outline_revisions
                if rev.id == outline_head.current_revision_id
            )
            assert head_copied.version_number == 3
            copied_by_version = {
                rev.version_number: rev for rev in outline_revisions
            }
            assert (
                copied_by_version[3].base_revision_id
                == copied_by_version[1].id
            )
            assert (
                copied_by_version[3].restored_from_revision_id
                == copied_by_version[2].id
            )

            copied_card = (
                await verify_db.execute(
                    select(CharacterCard).where(
                        CharacterCard.novel_id == copied_id
                    )
                )
            ).scalar_one()
            copied_card_revisions = list(
                (
                    await verify_db.execute(
                        select(CharacterCardRevision).where(
                            CharacterCardRevision.novel_id == copied_id
                        )
                    )
                ).scalars()
            )
            assert len(copied_card_revisions) == 2
            assert (
                copied_card.current_revision_id
                == next(
                    rev.id
                    for rev in copied_card_revisions
                    if rev.version_number == 2
                )
            )

            copied_entity = (
                await verify_db.execute(
                    select(CoreEntity).where(CoreEntity.novel_id == copied_id)
                )
            ).scalar_one()
            copied_evidence = (
                await verify_db.execute(
                    select(EvidenceLink).where(EvidenceLink.novel_id == copied_id)
                )
            ).scalar_one()
            assert copied_entity.content_json["project_id"] == str(copied_id)
            assert copied_evidence.target_ref["project_id"] == str(copied_id)
            assert copied_evidence.source_ref["project_id"] == str(copied_id)
            copied_page_revision = (
                await verify_db.execute(
                    select(WorldBiblePageRevision).where(
                        WorldBiblePageRevision.novel_id == copied_id
                    )
                )
            ).scalar_one()
            assert copied_page_revision.snapshot_json["linked_asset_refs_json"] == [
                {"type": "profile", "id": str(copied_entity.id)}
            ]

            # The copied canon must replay end to end on PostgreSQL.
            await WorldAuthorityService().get_head(verify_db, str(copied_id))
    finally:
        get_settings.cache_clear()
        async with sessions.begin() as cleanup_db:
            await _delete_accounts(cleanup_db, [source_owner_id, target_owner_id])
        await engine.dispose()


async def _delete_accounts(db, ids) -> None:
    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(Account).where(Account.id.in_(ids)))


async def test_demo_copy_failure_leaves_no_residue_and_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_owner_id = uuid.uuid4()
    target_owner_id = uuid.uuid4()
    source_id = uuid.uuid4()
    _demo_env(monkeypatch, source_id, "history-rollback-v1")
    try:
        await _require_immutable_triggers(engine)
        async with sessions.begin() as setup_db:
            seeded = await _seed_history_source(
                setup_db,
                source_id=source_id,
                owner_id=source_owner_id,
                copy_owner_id=target_owner_id,
            )
            entity = await setup_db.get(CoreEntity, seeded["entity_id"])
            entity.image_version = uuid.uuid4()
            await setup_db.flush()

        async def snapshot_counts() -> tuple[int, int, int]:
            async with sessions() as verify_db:
                projects = await verify_db.scalar(
                    select(func.count(Project.id)).where(
                        Project.owner_id == target_owner_id
                    )
                )
                copies = await verify_db.scalar(
                    select(func.count(DemoProjectCopy.id)).where(
                        DemoProjectCopy.owner_id == target_owner_id
                    )
                )
                canon = await verify_db.scalar(
                    select(func.count(WorldCanonRevision.id))
                )
                return int(projects or 0), int(copies or 0), int(canon or 0)

        before = await snapshot_counts()

        class ExplodingStorage:
            async def get_webp(self, key: str, *, max_bytes: int) -> bytes:
                del key, max_bytes
                raise RuntimeError("storage exploded mid-copy")

        class MemoryStorage:
            def __init__(self) -> None:
                self.objects: dict[str, bytes] = {}

            async def get_webp(self, key: str, *, max_bytes: int) -> bytes:
                del max_bytes
                return self.objects[key]

            async def put_webp(self, key: str, payload: bytes) -> None:
                self.objects[key] = payload

        support_code = f"DEMO-HISTORY-{target_owner_id.hex[:12]}"
        token = bind_principal(_principal(target_owner_id, support_code))
        try:
            # Mirror the request-scoped dependency: get_db rolls back when the
            # handler raises; a failing copy never reaches commit.
            async with sessions() as db:
                service = DemoProjectCopyService(image_storage=ExplodingStorage())
                try:
                    await service.copy(db)
                    raise AssertionError("copy must fail on storage errors")
                except DomainError as exc:
                    assert "Demo image copy failed" in str(exc)
                    await db.rollback()
        finally:
            reset_principal(token)

        after_failure = await snapshot_counts()
        assert after_failure == before, "a failed copy must leave no residue"

        support_code = f"DEMO-HISTORY-{target_owner_id.hex[:12]}"
        token = bind_principal(_principal(target_owner_id, support_code))
        try:
            async with sessions.begin() as db:
                from modules.world.world_object_images import image_object_key

                storage = MemoryStorage()
                entity_row = (
                    await db.execute(
                        select(CoreEntity).where(
                            CoreEntity.novel_id == source_id,
                            CoreEntity.id == seeded["entity_id"],
                        )
                    )
                ).scalar_one()
                for variant in ("full", "thumbnail"):
                    source_key = image_object_key(
                        str(source_id),
                        str(seeded["entity_id"]),
                        str(entity_row.image_version),
                        variant,
                    )
                    storage.objects[source_key] = variant.encode()
                result = await DemoProjectCopyService(image_storage=storage).copy(db)
            assert result.status == "created"
        finally:
            reset_principal(token)

        after_retry = await snapshot_counts()
        assert after_retry[0] == 1
        assert after_retry[1] == 1
        assert after_retry[2] == before[2] + 2
    finally:
        get_settings.cache_clear()
        async with sessions.begin() as cleanup_db:
            await _delete_accounts(cleanup_db, [source_owner_id, target_owner_id])
        await engine.dispose()

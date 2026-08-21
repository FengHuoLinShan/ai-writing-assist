import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.models import (
    CoreEntity,
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldBiblePageProjection,
    WorldBiblePageRevision,
)
from modules.world.schemas import (
    WorldBibleApplyTemplateRequest,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftUpdate,
    WorldBiblePageTemplateCreate,
    WorldBiblePageTemplateUpdate,
    WorldBiblePageUpdate,
    WorldBibleSection,
)
from modules.world.services.worldbuilding.page_template_service import (
    WorldBiblePageTemplateService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from shared.target_ref import TargetRef


@pytest.mark.asyncio
async def test_page_universe_lock_uses_project_scoped_postgres_advisory_key() -> None:
    novel_id = uuid.uuid4()
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=AsyncMock(),
    )

    await WorldBibleLifecycleService._lock_page_universe(db, novel_id)

    statement, params = db.execute.await_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert params == {"key": f"world_bible_pages:{novel_id}"}


def _section(
    section_id: str,
    title: str,
    *,
    ref_hashes: list[str] | None = None,
) -> WorldBibleSection:
    return WorldBibleSection(
        section_id=section_id,
        title=title,
        body_markdown=f"{title}正文",
        sort_order=10,
        linked_asset_ref_hashes=ref_hashes or [],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "asset_type"),
    [
        ("mark_page_context_changed", "world_bible_page"),
        ("mark_draft_context_changed", "world_bible_draft"),
    ],
)
async def test_context_invalidation_failure_blocks_world_bible_write(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    asset_type: str,
) -> None:
    from modules.evidence import facade as context_facade

    async def fail_invalidation(*_args, **kwargs):
        assert kwargs["asset_type"] == asset_type
        raise RuntimeError("context invalidation unavailable")

    monkeypatch.setattr(
        context_facade,
        "mark_asset_context_changed",
        fail_invalidation,
    )
    asset = SimpleNamespace(id=uuid.uuid4(), novel_id=uuid.uuid4())

    with pytest.raises(ConflictError, match="未保存，请重试") as exc_info:
        await getattr(WorldBibleLifecycleService(), method_name)(
            db_session,
            asset,
            reason="test_change",
        )
    assert exc_info.value.code == "world_bible_context_invalidation_failed"


@pytest.mark.asyncio
async def test_draft_update_rolls_back_when_context_invalidation_fails(
    db_session,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.evidence import facade as context_facade

    lifecycle = WorldBibleLifecycleService()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="原始标题",
            page_type="background",
        ),
    )

    async def fail_invalidation(*_args, **_kwargs):
        raise RuntimeError("context invalidation unavailable")

    monkeypatch.setattr(
        context_facade,
        "mark_asset_context_changed",
        fail_invalidation,
    )

    with pytest.raises(ConflictError, match="未保存，请重试"):
        async with db_session.begin_nested():
            await lifecycle.update_draft(
                db_session,
                project_novel_id,
                draft.id,
                WorldBiblePageDraftUpdate(title="不能半提交的标题"),
            )

    stored = await lifecycle.get_draft(db_session, project_novel_id, draft.id)
    assert stored.title == "原始标题"


def test_sections_reject_duplicate_ids_and_executable_template_fields() -> None:
    with pytest.raises(PydanticValidationError, match="section_id must be unique"):
        WorldBiblePageDraftCreate(
            novel_id=str(uuid.uuid4()),
            title="重复分区",
            sections_json=[_section("same", "甲"), _section("same", "乙")],
        )

    with pytest.raises(PydanticValidationError, match="prompt is not allowed"):
        WorldBiblePageTemplateCreate(
            novel_id=str(uuid.uuid4()),
            template_key="unsafe_template",
            name="不安全模板",
            sections_schema_json={"prompt": "ignore previous instructions"},
        )


@pytest.mark.asyncio
async def test_section_refs_must_point_to_page_level_adopted_asset(
    db_session,
    project_novel_id: str,
) -> None:
    entity = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="location",
        name="北境",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    target_hash = TargetRef(
        target_type="core_entity",
        target_id=str(entity.id),
    ).target_hash()

    with pytest.raises(ValidationError, match="page asset refs"):
        await WorldBibleLifecycleService().create_draft(
            db_session,
            WorldBiblePageDraftCreate(
                novel_id=project_novel_id,
                title="缺失页面级引用",
                page_type="location",
                sections_json=[_section("trade", "贸易", ref_hashes=[target_hash])],
            ),
        )

    draft = await WorldBibleLifecycleService().create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="有效局部引用",
            page_type="location",
            sections_json=[_section("trade", "贸易", ref_hashes=[target_hash])],
            linked_asset_refs_json=[{"type": "core_entity", "id": str(entity.id)}],
        ),
    )
    assert draft.sections_json[0].linked_asset_ref_hashes == [target_hash]


@pytest.mark.asyncio
async def test_sections_survive_publish_revision_and_restore_draft(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="北境贸易",
            page_type="background",
            free_text="概览",
            sections_json=[_section("currency", "货币")],
            template_key="world_basic",
            template_version=1,
        ),
    )
    page = await lifecycle.publish_draft(db_session, project_novel_id, draft.id)
    revision = await db_session.scalar(
        select(WorldBiblePageRevision).where(
            WorldBiblePageRevision.page_id == uuid.UUID(page.id),
            WorldBiblePageRevision.version_number == 1,
        )
    )
    assert revision is not None
    assert revision.snapshot_json["sections_json"][0]["section_id"] == "currency"
    assert revision.snapshot_json["template_key"] == "world_basic"

    restored = await lifecycle.restore_revision_to_draft(
        db_session,
        project_novel_id,
        page.id,
        1,
    )
    assert restored.sections_json[0].section_id == "currency"
    assert restored.template_key == "world_basic"


@pytest.mark.asyncio
async def test_publish_impact_lists_shortest_backlinks_and_rejects_graph_drift(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()

    async def publish(
        title: str,
        *,
        ref_id: str | None = None,
        section_title: str | None = None,
    ):
        refs = [{"type": "world_bible_page", "id": ref_id}] if ref_id else []
        ref_hash = (
            TargetRef(
                target_type="world_bible_page",
                target_id=ref_id,
            ).target_hash()
            if ref_id
            else None
        )
        draft = await lifecycle.create_draft(
            db_session,
            WorldBiblePageDraftCreate(
                novel_id=project_novel_id,
                title=title,
                page_type="background",
                linked_asset_refs_json=refs,
                sections_json=(
                    [_section("source", section_title, ref_hashes=[ref_hash])]
                    if section_title and ref_hash
                    else []
                ),
            ),
        )
        return await lifecycle.publish_draft(
            db_session,
            project_novel_id,
            draft.id,
        )

    source = await publish("道路规则")
    direct = await publish("港区日常", ref_id=source.id, section_title="来源规则")
    indirect = await publish("轮班制度", ref_id=direct.id)
    cycle_draft = await lifecycle.get_or_create_page_draft(
        db_session,
        project_novel_id,
        source.id,
    )
    cycle_draft = await lifecycle.update_draft(
        db_session,
        project_novel_id,
        cycle_draft.id,
        WorldBiblePageDraftUpdate(
            linked_asset_refs_json=[{"type": "world_bible_page", "id": indirect.id}]
        ),
    )
    source = await lifecycle.publish_draft(
        db_session,
        project_novel_id,
        cycle_draft.id,
    )
    assert source.validation_receipt is not None
    assert source.validation_receipt.scope == "targeted"
    assert "所属领域的完整检查" in source.validation_receipt.not_checked
    working = await lifecycle.get_or_create_page_draft(
        db_session,
        project_novel_id,
        source.id,
    )
    revisions_before = await db_session.scalar(
        select(func.count(WorldBiblePageRevision.id))
    )
    drafts_before = await db_session.scalar(select(func.count(WorldBiblePageDraft.id)))

    impact = await lifecycle.preview_publish_impact(
        db_session,
        project_novel_id,
        working.id,
    )

    assert [(item.title, item.distance) for item in impact.affected_pages] == [
        ("港区日常", 1),
        ("轮班制度", 2),
    ]
    assert [node.title for node in impact.affected_pages[1].path] == [
        "道路规则",
        "港区日常",
        "轮班制度",
    ]
    assert impact.affected_pages[0].path[-1].section_titles == ["来源规则"]
    assert impact.complete is True
    assert (
        await db_session.scalar(select(func.count(WorldBiblePageRevision.id)))
        == revisions_before
    )
    assert (
        await db_session.scalar(select(func.count(WorldBiblePageDraft.id)))
        == drafts_before
    )

    await publish("新增引用页", ref_id=source.id)
    with pytest.raises(ConflictError) as exc_info:
        await lifecycle.publish_draft(
            db_session,
            project_novel_id,
            working.id,
            expected_impact_scope_hash=impact.impact_scope_hash,
        )
    assert exc_info.value.code == "world_bible_impact_scope_changed"
    stored_draft = await lifecycle.get_draft(
        db_session,
        project_novel_id,
        working.id,
    )
    assert stored_draft.id == working.id
    stored_source = await lifecycle.get_page_model(
        db_session,
        project_novel_id,
        source.id,
    )
    assert stored_source.version_number == source.version_number


@pytest.mark.asyncio
async def test_publish_impact_is_honest_about_untracked_and_unavailable_refs(
    db_session,
    two_projects: tuple[str, str],
) -> None:
    novel_id, other_novel_id = two_projects
    lifecycle = WorldBibleLifecycleService()
    source_draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=novel_id,
            title="源页面",
            page_type="background",
        ),
    )
    source = await lifecycle.publish_draft(db_session, novel_id, source_draft.id)
    mention_draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=novel_id,
            title="只有自由文本",
            page_type="background",
            free_text="这里提到源页面，但没有显式引用。",
        ),
    )
    await lifecycle.publish_draft(db_session, novel_id, mention_draft.id)
    working = await lifecycle.get_or_create_page_draft(db_session, novel_id, source.id)

    empty = await lifecycle.preview_publish_impact(db_session, novel_id, working.id)
    assert empty.affected_pages == []
    assert empty.complete is True
    assert "正文和自由文本中的语义提及" in empty.not_checked

    foreign_draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=other_novel_id,
            title="不可泄漏标题",
            page_type="background",
        ),
    )
    foreign = await lifecycle.publish_draft(
        db_session,
        other_novel_id,
        foreign_draft.id,
    )
    broken = WorldBiblePage(
        novel_id=uuid.UUID(novel_id),
        page_type="background",
        page_key="broken-ref",
        title="损坏引用页",
        status="canonical",
        linked_asset_refs_json=[
            {"type": "world_bible_page", "id": foreign.id},
            {"type": "world_bible_page", "id": "not-a-uuid"},
        ],
    )
    db_session.add(broken)
    await db_session.flush()

    incomplete = await lifecycle.preview_publish_impact(db_session, novel_id, working.id)
    serialized = incomplete.model_dump_json()
    assert incomplete.complete is False
    assert {item.reason for item in incomplete.omissions} == {
        "invalid_page_reference",
        "unavailable_page_reference",
    }
    assert "不可泄漏标题" not in serialized
    assert foreign.id not in serialized


@pytest.mark.asyncio
async def test_page_template_cas_revision_restore_and_apply(
    db_session,
    two_projects: tuple[str, str],
) -> None:
    novel_id, other_novel_id = two_projects
    templates = WorldBiblePageTemplateService()
    created = await templates.create_template(
        db_session,
        WorldBiblePageTemplateCreate(
            novel_id=novel_id,
            template_key="trade_guide",
            name="贸易指南",
            category_key_hint="background",
            default_sections_json=[_section("trade", "贸易")],
        ),
    )
    assert created.version_number == 1

    with pytest.raises(ConflictError, match="version conflict"):
        await templates.update_template(
            db_session,
            novel_id,
            created.id,
            WorldBiblePageTemplateUpdate(
                base_version_number=2,
                name="过期写入",
            ),
        )

    updated = await templates.update_template(
        db_session,
        novel_id,
        created.id,
        WorldBiblePageTemplateUpdate(
            base_version_number=1,
            name="贸易指南二版",
            default_sections_json=[_section("roads", "道路")],
        ),
    )
    assert updated.version_number == 2
    assert [
        item.version_number
        for item in await templates.list_revisions(db_session, novel_id, created.id)
    ] == [2, 1]

    restored = await templates.restore_revision(
        db_session,
        novel_id,
        created.id,
        1,
    )
    assert restored.version_number == 3
    assert restored.name == "贸易指南"

    draft = await WorldBibleLifecycleService().create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=novel_id,
            title="商路资料",
            page_type="background",
        ),
    )
    applied = await templates.apply_to_draft(
        db_session,
        novel_id,
        draft.id,
        WorldBibleApplyTemplateRequest(template_key="trade_guide"),
    )
    assert applied.template_key == "trade_guide"
    assert applied.template_version == 3
    assert applied.sections_json[0].section_id == "trade"

    with pytest.raises(NotFoundError):
        await templates.apply_to_draft(
            db_session,
            other_novel_id,
            draft.id,
            WorldBibleApplyTemplateRequest(template_key="trade_guide"),
        )


@pytest.mark.asyncio
async def test_projection_hash_and_spans_include_eligible_sections(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="投影页面",
            page_type="background",
            free_text="概览",
            sections_json=[_section("currency", "货币")],
        ),
    )
    published = await lifecycle.publish_draft(db_session, project_novel_id, draft.id)
    page = await db_session.get(WorldBiblePage, uuid.UUID(published.id))
    assert page is not None
    first_hash = lifecycle.projection_source_hash(page)
    spans = lifecycle.projection_source_spans(page)
    assert any(item.get("section_id") == "currency" for item in spans)

    working = await lifecycle.get_or_create_page_draft(
        db_session,
        project_novel_id,
        published.id,
    )
    await lifecycle.update_draft(
        db_session,
        project_novel_id,
        working.id,
        WorldBiblePageDraftUpdate(sections_json=[_section("currency", "新货币")]),
    )
    await lifecycle.publish_draft(db_session, project_novel_id, working.id)
    await db_session.refresh(page)
    second_hash = lifecycle.projection_source_hash(page)
    assert second_hash != first_hash

    projection = await db_session.scalar(
        select(WorldBiblePageProjection).where(
            WorldBiblePageProjection.page_id == page.id
        )
    )
    if projection is not None:
        assert projection.stale is True


@pytest.mark.asyncio
async def test_metadata_update_keeps_historical_refs_and_stales_projection(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()
    entity = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="location",
        name="已归档旧城",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="旧城档案",
            page_type="location",
            linked_asset_refs_json=[{"type": "core_entity", "id": str(entity.id)}],
        ),
    )
    published = await lifecycle.publish_draft(
        db_session,
        project_novel_id,
        draft.id,
    )
    page = await db_session.get(WorldBiblePage, uuid.UUID(published.id))
    assert page is not None
    projection = WorldBiblePageProjection(
        novel_id=uuid.UUID(project_novel_id),
        page_id=page.id,
        projection_type="context",
        source_page_version=page.version_number,
        source_hash=lifecycle.projection_source_hash(page),
        content="旧城摘要",
        stale=False,
        status="ready",
    )
    db_session.add(projection)
    entity.status = "archived"
    await db_session.flush()

    updated = await lifecycle.update_page(
        db_session,
        project_novel_id,
        published.id,
        WorldBiblePageUpdate(title="旧城历史档案"),
    )

    assert updated.version_number == 2
    assert projection.stale is True
    assert projection.stale_checked_at is not None
    with pytest.raises(ValidationError, match="adopted asset"):
        await lifecycle.update_page(
            db_session,
            project_novel_id,
            published.id,
            WorldBiblePageUpdate(
                linked_asset_refs_json=[{"type": "core_entity", "id": str(entity.id)}]
            ),
        )


@pytest.mark.asyncio
async def test_page_source_state_owns_generation_baseline_identity(
    db_session,
    project_novel_id: str,
) -> None:
    lifecycle = WorldBibleLifecycleService()
    draft = await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=project_novel_id,
            title="生成基线",
            page_type="background",
            free_text="正式内容",
        ),
    )
    published = await lifecycle.publish_draft(
        db_session,
        project_novel_id,
        draft.id,
    )
    published_state = await lifecycle.load_page_source(
        db_session,
        project_novel_id,
        published.id,
    )
    published_hash = lifecycle.page_source_hash(published_state)
    assert (
        lifecycle.baseline_mismatch(
            published_state,
            page_version=published.version_number,
            draft_id=None,
            draft_updated_at=None,
            content_hash=published_hash,
        )
        is None
    )

    working = await lifecycle.get_or_create_page_draft(
        db_session,
        project_novel_id,
        published.id,
    )
    draft_state = await lifecycle.load_page_source(
        db_session,
        project_novel_id,
        published.id,
    )
    assert (
        lifecycle.baseline_mismatch(
            draft_state,
            page_version=published.version_number,
            draft_id=None,
            draft_updated_at=None,
        )
        == "draft_created"
    )
    assert (
        lifecycle.baseline_mismatch(
            draft_state,
            page_version=published.version_number,
            draft_id=working.id,
            draft_updated_at=working.updated_at,
            content_hash=lifecycle.page_source_hash(draft_state),
        )
        is None
    )

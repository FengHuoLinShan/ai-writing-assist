"""Phase 4 review ownership tests (ADR-0022)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.world.map_atlas_models import MapAtlasNode
from modules.world.models import (
    Character,
    CoreEntity,
    EntityRelation,
    WorldBiblePage,
    WorldValidationRun,
)
from modules.world.schemas import (
    WorldBiblePageCreate,
    WorldBiblePageDraftCreate,
    WorldImpactPreviewResponse,
    WorldValidationPolicyDraftUpsert,
    WorldValidationReviewItemInput,
    WorldValidationReviewRequest,
    WorldValidationRunCreate,
)
from modules.world.services.worldbuilding.conflict_queue_service import (
    ConflictQueueService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.world_impact_service import (
    WorldImpactService,
)
from modules.world.services.worldbuilding.world_validation_engine import (
    build_review_packets,
    stable_hash,
)
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)

from .test_world_validation import _activate_policy, _policy


def _finding(
    finding_id: str,
    *,
    severity: str = "warning",
    action: str = "KEEP-GATE",
    category: str = "policy:test",
    source_key: str | None = "draft:x",
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "layer": "engine",
        "severity": severity,
        "category": category,
        "action": action,
        "message": "测试发现",
        "source_key": source_key,
        "location": None,
        "excerpt": None,
        "question_id": None,
    }


async def _draft_for_target(db_session, novel_id: str):
    lifecycle = WorldBibleLifecycleService()
    return await lifecycle.create_draft(
        db_session,
        WorldBiblePageDraftCreate(
            novel_id=novel_id,
            page_type="location",
            title="复核目标页",
            free_text="潮汐术必须支付记忆代价。",
        ),
    )


async def _completed_run(
    db_session,
    novel_id: str,
    *,
    findings: list[dict[str, Any]],
    verdict: str = "author-required",
    gate: str = "block",
):
    policy, policy_hash = await _activate_policy(db_session, novel_id)
    service = WorldValidationService()
    draft = await _draft_for_target(db_session, novel_id)
    manifest, dependency_hash, target_hash = await service._freeze_manifest(
        db_session,
        novel_id=novel_id,
        scope="targeted",
        target_type="world_bible_draft",
        target_id=draft.id,
    )
    run = WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        trigger="manual",
        scope="targeted",
        scope_json={
            "target_type": "world_bible_draft",
            "target_id": draft.id,
            "target_hash": target_hash,
            "required_question_ids": [],
        },
        status="completed",
        verdict=verdict,
        gate=gate,
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        manifest_json=manifest,
        manifest_hash=stable_hash(manifest),
        dependency_hash=dependency_hash,
        findings_json=findings,
        packet_hashes_json=[{"receipt_hash": stable_hash("receipt")}],
    )
    db_session.add(run)
    await db_session.flush()
    return run, draft


# ----------------------------------------------------------------------
# Per-finding review records
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_author_required_gate_needs_per_finding_review(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    run, draft = await _completed_run(
        db_session,
        project_novel_id,
        findings=[_finding("finding:a1", action="AUTHOR-REQUIRED")],
    )

    with pytest.raises(ConflictError) as exc_info:
        await service.require_gate(
            db_session,
            novel_id=project_novel_id,
            validation_run_id=str(run.id),
            target_type="world_bible_draft",
            target_id=draft.id,
            target_hash=run.scope_json["target_hash"],
        )
    assert exc_info.value.context["reason"] == "review_pending"

    reviewed = await service.review_items(
        db_session,
        project_novel_id,
        str(run.id),
        WorldValidationReviewRequest(
            items=[
                WorldValidationReviewItemInput(
                    finding_id="finding:a1", disposition="resolved", note="已裁定"
                )
            ]
        ),
    )
    assert reviewed.review["required"] == 1
    assert reviewed.review["reviewed"] == 1
    assert reviewed.review["pending_finding_ids"] == []

    await service.require_gate(
        db_session,
        novel_id=project_novel_id,
        validation_run_id=str(run.id),
        target_type="world_bible_draft",
        target_id=draft.id,
        target_hash=run.scope_json["target_hash"],
    )


@pytest.mark.asyncio
async def test_review_items_reject_unknown_or_unreviewable_findings(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    run, _ = await _completed_run(
        db_session,
        project_novel_id,
        findings=[
            _finding("finding:a1", action="AUTHOR-REQUIRED"),
            _finding("finding:e1", severity="error", action="CLOSE"),
        ],
    )
    with pytest.raises(ValidationError):
        await service.review_items(
            db_session,
            project_novel_id,
            str(run.id),
            WorldValidationReviewRequest(
                items=[
                    WorldValidationReviewItemInput(
                        finding_id="finding:missing",
                        disposition="resolved",
                    )
                ]
            ),
        )
    with pytest.raises(ValidationError):
        await service.review_items(
            db_session,
            project_novel_id,
            str(run.id),
            WorldValidationReviewRequest(
                items=[
                    WorldValidationReviewItemInput(
                        finding_id="finding:e1",
                        disposition="resolved",
                    )
                ]
            ),
        )
    listing = await service.list_review_items(db_session, project_novel_id, str(run.id))
    assert listing.total == 0


@pytest.mark.asyncio
async def test_review_snapshot_binds_target_and_manifest_hashes(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    run, _ = await _completed_run(
        db_session,
        project_novel_id,
        findings=[_finding("finding:a1", action="AUTHOR-REQUIRED")],
    )
    await service.review_items(
        db_session,
        project_novel_id,
        str(run.id),
        WorldValidationReviewRequest(
            items=[
                WorldValidationReviewItemInput(
                    finding_id="finding:a1", disposition="acknowledged"
                )
            ]
        ),
    )
    listing = await service.list_review_items(db_session, project_novel_id, str(run.id))
    snapshot = listing.items[0].finding_snapshot
    assert snapshot["target_hash"] == run.scope_json["target_hash"]
    assert snapshot["manifest_hash"] == run.manifest_hash
    assert snapshot["action"] == "AUTHOR-REQUIRED"


@pytest.mark.asyncio
async def test_target_change_stales_run_and_requires_new_review(
    db_session, project_novel_id: str
) -> None:
    from modules.world.schemas import WorldBiblePageDraftUpdate

    service = WorldValidationService()
    run, draft = await _completed_run(
        db_session,
        project_novel_id,
        findings=[_finding("finding:a1", action="AUTHOR-REQUIRED")],
    )
    await service.review_items(
        db_session,
        project_novel_id,
        str(run.id),
        WorldValidationReviewRequest(
            items=[
                WorldValidationReviewItemInput(
                    finding_id="finding:a1",
                    disposition="resolved",
                )
            ]
        ),
    )
    lifecycle = WorldBibleLifecycleService()
    await lifecycle.update_draft(
        db_session,
        project_novel_id,
        draft.id,
        WorldBiblePageDraftUpdate(free_text="内容已修改，目标版本变化。"),
    )
    refreshed = await service.get(db_session, project_novel_id, str(run.id))
    assert refreshed.status == "stale"
    assert refreshed.stale_reason in {"target", "manifest"}
    with pytest.raises(ConflictError) as exc_info:
        await service.require_gate(
            db_session,
            novel_id=project_novel_id,
            validation_run_id=str(run.id),
            target_type="world_bible_draft",
            target_id=draft.id,
            target_hash=run.scope_json["target_hash"],
        )
    assert exc_info.value.context["status"] == "stale"


@pytest.mark.asyncio
async def test_policy_change_records_stale_reason(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    run, _ = await _completed_run(
        db_session,
        project_novel_id,
        findings=[],
        verdict="pass",
        gate="pass",
    )
    from modules.world.models import WorldBiblePage as PolicyPage

    policy_page = (
        await db_session.execute(
            select(PolicyPage).where(
                PolicyPage.novel_id == uuid.UUID(project_novel_id),
                PolicyPage.page_key == "validation-policy",
            )
        )
    ).scalar_one()
    policy_page.page_meta_json = {
        **(policy_page.page_meta_json or {}),
        "validation_policy": _policy()
        .model_copy(update={"policy_version": "changed-v2"})
        .model_dump(mode="json"),
    }
    await db_session.flush()
    refreshed = await service.get(db_session, project_novel_id, str(run.id))
    assert refreshed.status == "stale"
    assert refreshed.stale_reason == "policy"


@pytest.mark.asyncio
async def test_review_rejected_for_stale_run(
    db_session, project_novel_id: str
) -> None:
    from modules.world.schemas import WorldBiblePageDraftUpdate

    service = WorldValidationService()
    run, draft = await _completed_run(
        db_session,
        project_novel_id,
        findings=[_finding("finding:a1", action="AUTHOR-REQUIRED")],
    )
    lifecycle = WorldBibleLifecycleService()
    await lifecycle.update_draft(
        db_session,
        project_novel_id,
        draft.id,
        WorldBiblePageDraftUpdate(free_text="目标已变化。"),
    )
    with pytest.raises(ConflictError) as exc_info:
        await service.review_items(
            db_session,
            project_novel_id,
            str(run.id),
            WorldValidationReviewRequest(
                items=[
                    WorldValidationReviewItemInput(
                    finding_id="finding:a1",
                    disposition="resolved",
                )
                ]
            ),
        )
    assert exc_info.value.code == "validation_run_not_reviewable"


# ----------------------------------------------------------------------
# Findings pagination + filters
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_findings_page_filters_and_paginates(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    findings = [
        _finding(f"finding:w{i}", severity="warning") for i in range(5)
    ] + [_finding("finding:e0", severity="error", action="CLOSE")]
    run, _ = await _completed_run(
        db_session, project_novel_id, findings=findings
    )
    page = await service.findings_page(
        db_session,
        project_novel_id,
        str(run.id),
        severity="warning",
        page=2,
        page_size=2,
    )
    assert page.total == 5
    assert page.page == 2
    assert len(page.items) == 2
    errors_first = await service.findings_page(
        db_session, project_novel_id, str(run.id), page=1, page_size=20
    )
    assert len(errors_first.items) == 6
    assert errors_first.items[0].finding_id == "finding:e0"
    assert all(item.severity == "warning" for item in errors_first.items[1:])
    reviewed = await service.review_items(
        db_session,
        project_novel_id,
        str(run.id),
        WorldValidationReviewRequest(
            items=[
                WorldValidationReviewItemInput(
                    finding_id="finding:w0",
                    disposition="resolved",
                )
            ]
        ),
    )
    assert reviewed.review["required"] == 5
    with_page = await service.findings_page(
        db_session, project_novel_id, str(run.id), page=1, page_size=20
    )
    assert with_page.dispositions == {"finding:w0": "resolved"}


# ----------------------------------------------------------------------
# Continuation of interrupted full checks
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_continue_failed_run_preserves_packet_progress(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    run, _ = await _completed_run(
        db_session,
        project_novel_id,
        findings=[],
        verdict="pass",
        gate="pass",
    )
    run.status = "failed"
    run.gate = "block"
    run.error_code = "TransientError"
    run.packet_hashes_json = [
        {"input_hash": "h1", "result_hash": "r1"},
        {"receipt_hash": stable_hash("receipt")},
    ]
    await db_session.flush()

    continued = await service.continue_run(db_session, project_novel_id, str(run.id))
    assert continued.status == "queued"
    assert continued.continued_count == 1
    assert continued.task_id is not None
    task = await db_session.scalar(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(continued.task_id or ""))
    )
    assert task is not None
    assert task.meta["run_id"] == str(run.id)
    persisted = await service.get(db_session, project_novel_id, str(run.id))
    assert persisted.progress["packets_completed"] == 1
    assert persisted.findings == []

    with pytest.raises(ConflictError) as exc_info:
        await service.continue_run(db_session, project_novel_id, str(run.id))
    assert exc_info.value.code == "validation_run_not_continuable"


@pytest.mark.asyncio
async def test_continue_budget_exhausted_run_is_allowed(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    run, _ = await _completed_run(
        db_session,
        project_novel_id,
        findings=[],
        verdict="insufficient-evidence",
        gate="block",
    )
    run.omissions_json = ["semantic_budget_exceeded"]
    await db_session.flush()
    continued = await service.continue_run(db_session, project_novel_id, str(run.id))
    assert continued.status == "queued"
    assert continued.continued_count == 1
    assert continued.omissions == []


# ----------------------------------------------------------------------
# Batch packets: stable hashes, budget slicing, resume
# ----------------------------------------------------------------------


def _manifest_for_batches() -> dict[str, Any]:
    items = []
    for index in range(3):
        items.append(
            {
                "source_key": f"page:{index}",
                "target_type": "world_bible_page",
                "target_id": str(index),
                "title": f"页{index}",
                "content": "x" * 5000,
            }
        )
    return {"scope": "full", "items": items}


def test_over_budget_strict_mode_returns_empty() -> None:
    policy = _policy(semantic=True).model_copy(
        update={"packet_character_limit": 4000, "max_input_characters": 4000}
    )
    packets, budget = build_review_packets(
        run_id="run", scope="full", policy=policy, manifest=_manifest_for_batches()
    )
    assert packets == []
    assert budget["planned_packets"] == 6


def test_over_budget_batch_mode_slices_and_keeps_hash_stability() -> None:
    policy = _policy(semantic=True).model_copy(
        update={"packet_character_limit": 4000, "max_input_characters": 8000}
    )
    manifest = _manifest_for_batches()
    batch1, budget = build_review_packets(
        run_id="run",
        scope="full",
        policy=policy,
        manifest=manifest,
        allow_over_budget=True,
    )
    assert budget["planned_packets"] == 6
    assert budget["budget_exceeded"] is True
    all_packets, _ = build_review_packets(
        run_id="run",
        scope="full",
        policy=policy.model_copy(update={"max_input_characters": 8000 * 3}),
        manifest=manifest,
    )
    full_hashes = {packet["input_hash"] for packet in all_packets}
    covered = {packet["input_hash"] for packet in batch1}
    assert covered <= full_hashes
    batches = [batch1]
    for _ in range(10):
        nxt, _ = build_review_packets(
            run_id="run",
            scope="full",
            policy=policy,
            manifest=manifest,
            completed_input_hashes=covered,
            allow_over_budget=True,
        )
        if not nxt:
            break
        batches.append(nxt)
        covered |= {packet["input_hash"] for packet in nxt}
    assert covered == full_hashes
    assert all(len(batch) <= 2 for batch in batches)


# ----------------------------------------------------------------------
# Semantic gap scope
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_gap_freezes_root_and_declared_one_hop(
    db_session, project_novel_id: str
) -> None:
    lifecycle = WorldBibleLifecycleService()
    root = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_key="root-page",
            page_type="location",
            title="根页",
            status="canonical",
            free_text="根页内容。",
        ),
    )
    entity = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="faction",
        name="潮汐商会",
        summary="掌握潮汐术的商会。",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_key="dependent-page",
            page_type="faction",
            title="依赖页",
            status="canonical",
            free_text="依赖页内容。",
        ),
    )
    # attach refs after both exist: root depends on the entity; the dependent
    # page declares requires on the root page.
    root_page = await db_session.get(WorldBiblePage, uuid.UUID(root.id))
    root_page.linked_asset_refs_json = [
        {"type": "core_entity", "id": str(entity.id), "relation": "requires"}
    ]
    dependent = (
        await db_session.execute(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == uuid.UUID(project_novel_id),
                WorldBiblePage.page_key == "dependent-page",
            )
        )
    ).scalar_one()
    dependent.linked_asset_refs_json = [
        {
            "type": "world_bible_page",
            "id": str(root.id),
            "relation": "requires",
        }
    ]
    await db_session.flush()

    service = WorldValidationService()
    manifest, _, target_hash = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="targeted",
        target_type="semantic_gap",
        target_id=root.id,
        root_type="world_bible_page",
    )
    keys = [item["source_key"] for item in manifest["items"]]
    assert keys == [f"page:{root.id}", f"entity:{entity.id}"]
    assert target_hash

    entity_manifest, _, entity_target = await service._freeze_manifest(
        db_session,
        novel_id=project_novel_id,
        scope="targeted",
        target_type="semantic_gap",
        target_id=str(entity.id),
        root_type="core_entity",
    )
    entity_keys = [item["source_key"] for item in entity_manifest["items"]]
    assert f"entity:{entity.id}" in entity_keys
    # the root page declares requires on the entity, so it joins the scope;
    # the page that depends on the *root page* stays outside the one-hop set.
    assert f"page:{root.id}" in entity_keys
    assert f"page:{dependent.id}" not in entity_keys
    assert entity_target


@pytest.mark.asyncio
async def test_semantic_gap_run_freezes_scope_and_stales_on_change(
    db_session, project_novel_id: str
) -> None:
    lifecycle = WorldBibleLifecycleService()
    root = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_key="gap-root",
            page_type="location",
            title="查漏根页",
            status="canonical",
            free_text="根页内容。",
        ),
    )
    service = WorldValidationService()
    created = await service.create_run(
        db_session,
        WorldValidationRunCreate(
            novel_id=project_novel_id,
            operation_id=uuid.uuid4(),
            scope="targeted",
            target_type="semantic_gap",
            target_id=root.id,
            root_type="world_bible_page",
        ),
    )
    assert created.target_type == "semantic_gap"
    assert created.impact["mode"] == "targeted"
    assert created.impact["target"]["target_type"] == "world_bible_page"
    assert created.status == "queued"

    task = await db_session.scalar(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(created.task_id or ""))
    )
    assert task is not None
    task.mark_running(lease_id=str(uuid.uuid4()))
    await db_session.flush()
    result = await service.execute_run(
        db_session,
        novel_id=project_novel_id,
        run_id=created.id,
        attempt=task.attempt,
        task_id=str(task.id),
        lease_id=str(task.lease_id),
    )
    assert result["status"] == "completed"

    root_page = await db_session.get(WorldBiblePage, uuid.UUID(root.id))
    root_page.free_text = "根页内容已修改。"
    await db_session.flush()
    refreshed = await service.latest(
        db_session,
        project_novel_id,
        scope="targeted",
        target_type="semantic_gap",
        target_id=root.id,
    )
    assert refreshed is not None
    assert refreshed.status == "stale"
    assert refreshed.stale_reason in {"target", "manifest"}


@pytest.mark.asyncio
async def test_semantic_gap_rejects_foreign_root(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    with pytest.raises(Exception):
        await service._freeze_manifest(
            db_session,
            novel_id=project_novel_id,
            scope="targeted",
            target_type="semantic_gap",
            target_id=str(uuid.uuid4()),
            root_type="world_bible_page",
        )


# ----------------------------------------------------------------------
# Impact preview
# ----------------------------------------------------------------------


def _thread(thread_id: str, name: str, entity_id: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=thread_id,
        name=name,
        thread_type="main",
        summary=None,
        visible_goal=None,
        hidden_truth=None,
        start_chapter=1,
        planned_payoff_chapter=10,
        current_stage="rising",
        related_character_ids=[],
        related_entity_ids=[entity_id],
        reader_known_state=None,
        author_known_state=None,
        status="active",
    )


class SimpleNamespaceSourceRef:
    def __init__(self, chapter: int) -> None:
        self.chapter_index = chapter
        self.range_hash = f"rangehash{chapter}"
        self.source_hash = f"sourcehash{chapter}"


class SimpleNamespaceHit:
    def __init__(self, chapter: int, count: int) -> None:
        self.source_ref = SimpleNamespaceSourceRef(chapter)
        self.title = f"第{chapter}章"
        self.terms = ["潮汐商会"]
        self.match_count = count


class SimpleNamespaceScan:
    def __init__(self, hits, cursor=None) -> None:
        self.hits = hits
        self.cursor = cursor
        self.scanned_chapters = []
        self.total_chapters = 0


@pytest.mark.asyncio
async def test_impact_preview_enumerates_proven_cross_module_sources(
    db_session, project_novel_id: str
) -> None:
    lifecycle = WorldBibleLifecycleService()
    entity = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="faction",
        name="潮汐商会",
        summary="商会。",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    character = Character(
        entity_id=entity.id,
        novel_id=uuid.UUID(project_novel_id),
        name="会长",
    )
    db_session.add(character)
    other = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="location",
        name="海崖城",
        status="canonical",
    )
    db_session.add(other)
    await db_session.flush()
    relation = EntityRelation(
        novel_id=uuid.UUID(project_novel_id),
        source_id=entity.id,
        target_id=other.id,
        relation_type="controls",
        relation_kind="causal",
        status="canonical",
    )
    db_session.add(relation)
    await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_key="ref-page",
            page_type="faction",
            title="引用页",
            status="canonical",
            free_text="引用。",
            linked_asset_refs_json=[
                {"type": "core_entity", "id": str(entity.id), "relation": "requires"}
            ],
        ),
    )
    node = MapAtlasNode(
        novel_id=uuid.UUID(project_novel_id),
        semantic_key=f"loc:{entity.id}",
        title="商会地图",
        level="region",
        status="adopted",
        location_entity_id=entity.id,
    )
    db_session.add(node)
    await db_session.flush()

    thread = _thread("thread-1", "商会主线", str(entity.id))
    with (
        patch(
            "modules.story.facade.list_plot_threads_referencing_entities",
            autospec=True,
        ) as thread_mock,
        patch(
            "modules.writing.facade.get_manuscript_source_manifest",
            autospec=True,
        ) as manifest_mock,
        patch(
            "modules.writing.facade.scan_manuscript_terms",
            autospec=True,
        ) as scan_mock,
    ):
        thread_mock.return_value = [thread]
        manifest_mock.return_value = [{"draft_id": "d1", "source_hash": "s1"}]
        scan_mock.return_value = SimpleNamespaceScan(
            [SimpleNamespaceHit(3, 4)], cursor=None
        )
        preview = await WorldImpactService().preview(
            db_session,
            project_novel_id,
            target_type="core_entity",
            target_id=str(entity.id),
        )
        thread_mock.assert_called_once()
        manifest_mock.assert_called_once()
        scan_mock.assert_called_once()

    assert isinstance(preview, WorldImpactPreviewResponse)
    sections = {section.section: section for section in preview.sections}
    assert sections["world_pages"].items[0].label == "引用页"
    assert sections["world_pages"].items[0].distance == 1
    assert any(
        item.kind == "entity_relation" for item in sections["world_entities"].items
    )
    assert sections["characters"].items[0].label == "会长"
    assert sections["story_threads"].items[0].label == "商会主线"
    assert sections["prose"].items[0].id == "3"
    assert sections["map"].items[0].label == "商会地图"
    assert preview.uncovered
    assert preview.complete is True  # nothing truncated / no read failures


@pytest.mark.asyncio
async def test_impact_preview_isolates_projects(
    db_session, two_projects: tuple[str, str]
) -> None:
    novel_a, novel_b = two_projects
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_a),
        entity_type="faction",
        name="仅A项目的对象",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    service = WorldImpactService()
    preview_a = await service.preview(
        db_session, novel_a, target_type="core_entity", target_id=str(entity.id)
    )
    assert preview_a.target.label == "仅A项目的对象"
    from core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await service.preview(
            db_session, novel_b, target_type="core_entity", target_id=str(entity.id)
        )


# ----------------------------------------------------------------------
# Policy draft endpoint
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_draft_upsert_and_status(
    db_session, project_novel_id: str
) -> None:
    service = WorldValidationService()
    policy = _policy(semantic=True)
    first = await service.save_policy_draft(
        db_session,
        project_novel_id,
        WorldValidationPolicyDraftUpsert(policy=policy, summary="第一版草稿"),
    )
    assert first.page_id
    status = await service.policy_status(db_session, project_novel_id)
    assert status.draft is not None
    assert status.draft.policy.policy_version == policy.policy_version
    assert not status.active

    updated = await service.save_policy_draft(
        db_session,
        project_novel_id,
        WorldValidationPolicyDraftUpsert(
            policy=policy.model_copy(update={"policy_version": "draft-v2"}),
            summary="第二版草稿",
        ),
    )
    status2 = await service.policy_status(db_session, project_novel_id)
    assert status2.draft.policy.policy_version == "draft-v2"
    assert status2.draft.draft_id == updated.id


# ----------------------------------------------------------------------
# Conflicts pagination
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conflicts_list_paginates(
    db_session, project_novel_id: str
) -> None:
    from modules.world.models import ConflictCheckQueueItem

    for i in range(3):
        db_session.add(
            ConflictCheckQueueItem(
                novel_id=uuid.UUID(project_novel_id),
                conflict_type="semantic_inspection",
                severity="medium",
                source_module="world",
                target={"source_key": f"page:{i}"},
                summary=f"冲突 {i}",
                resolution_json={"author_action": "needs_decision"},
                status="pending",
            )
        )
    await db_session.flush()
    service = ConflictQueueService()
    items, total = await service.list(
        db_session, project_novel_id, status="pending", skip=1, limit=1
    )
    assert total == 3
    assert len(items) == 1
    page = await service.list(
        db_session, project_novel_id, status="pending", skip=0, limit=10
    )
    assert len(page[0]) == 3

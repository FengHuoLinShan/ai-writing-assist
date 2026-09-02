from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.interaction.generation import (
    InteractionContextBudgetError,
    InteractionGenerationWorkflow,
)
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionSourceRevision,
)
from modules.interaction.repositories import InteractionRepository
from modules.interaction.schemas import (
    InteractionPlayerIdentity,
    InteractionReferenceUpdateRequest,
    InteractionSourceUpdateRequest,
    JourneyCreateRequest,
    JourneySourceSetup,
)
from modules.interaction.services import InteractionService
from modules.interaction.source_service import InteractionSourceService
from modules.project.services import ProjectService

pytestmark = pytest.mark.asyncio


def _anchor(label: str, chapter: int, offset: int) -> dict:
    return {
        "anchor_key": uuid.uuid5(uuid.NAMESPACE_URL, label).hex * 2,
        "chapter_index": chapter,
        "chapter_title": f"第{chapter}章",
        "label": label,
        "excerpt": "",
        "end_offset": offset,
        "scene_id": None,
    }


async def test_batched_journey_sources_preserve_order_and_probe_project_once() -> None:
    source_novel_id = uuid.uuid4()
    latest = SimpleNamespace(
        id=uuid.uuid4(),
        source_novel_id=source_novel_id,
        owner_id=LOCAL_OWNER_ID,
        version_number=2,
        title="新版本",
        status="ready",
    )
    older = SimpleNamespace(
        id=uuid.uuid4(),
        source_novel_id=source_novel_id,
        owner_id=LOCAL_OWNER_ID,
        version_number=1,
        title="旧版本",
        status="ready",
    )
    repo = InteractionRepository()
    service = InteractionSourceService(repo)
    anchor = {"label": "第一章", "chapter_index": 1, "end_offset": 120}
    requests = [
        {
            "revision_id": older.id,
            "anchor": anchor,
            "player_identity": {"name": "甲"},
            "source_context_epoch": 3,
        },
        {
            "revision_id": latest.id,
            "anchor": anchor,
            "player_identity": {"name": "乙"},
            "source_context_epoch": 4,
        },
    ]

    with (
        patch.object(
            repo,
            "list_source_revisions",
            autospec=True,
            return_value=[latest, older],
        ) as list_revisions,
        patch.object(service, "_refresh", autospec=True) as refresh,
        patch.object(
            service,
            "require_author_project",
            autospec=True,
        ) as require_project,
        patch(
            "modules.interaction.source_service.current_account_id",
            autospec=True,
            return_value=LOCAL_OWNER_ID,
        ),
    ):
        responses = await service.journey_source_responses(
            SimpleNamespace(),
            requests,
        )

    assert [item.revision_id for item in responses] == [str(older.id), str(latest.id)]
    assert [item.update_available for item in responses] == [True, False]
    assert [item.player_label for item in responses] == ["甲", "乙"]
    list_revisions.assert_awaited_once()
    assert refresh.await_count == 2
    require_project.assert_awaited_once()


async def _ready_source(db_session, project_factory):  # noqa: ANN001
    project_id = await project_factory.create_project(
        title="未完结的连载",
        project_kind="author",
        owner_id=LOCAL_OWNER_ID,
    )
    first = _anchor("第一章中段", 1, 120)
    later = _anchor("第二章结束", 2, 300)
    character_key = "c" * 64
    revision = InteractionSourceRevision(
        source_novel_id=project_id,
        owner_id=LOCAL_OWNER_ID,
        version_number=1,
        title="未完结的连载",
        status="ready",
        source_manifest=[
            {
                "draft_id": str(uuid.uuid4()),
                "chapter_index": 1,
                "version_number": 1,
                "source_hash": "a" * 64,
                "title": "第一章",
                "char_count": 200,
            },
            {
                "draft_id": str(uuid.uuid4()),
                "chapter_index": 2,
                "version_number": 1,
                "source_hash": "b" * 64,
                "title": "第二章",
                "char_count": 300,
            },
        ],
        anchor_manifest=[first, later],
        reference_manifest=[
            {
                "reference_key": character_key,
                "target_id": str(uuid.uuid4()),
                "entity_type": "character",
                "label": "林默",
                "aliases": ["默默"],
                "status": "canonical",
                "summary": "",
                "knowledge": [],
                "appearance_chapters": [1, 2],
                "first_chapter_index": 1,
                "first_end_offset": 100,
            }
        ],
        ambiguities=[],
        resolutions={},
        readiness_summary={"message": "作品资料已完整整理"},
        manifest_hash="d" * 64,
        fingerprint="f" * 64,
    )
    db_session.add(revision)
    await db_session.flush()
    return project_id, revision, first, later, character_key


async def _source_journey(db_session, project_factory):  # noqa: ANN001
    project_id, revision, first, later, character_key = await _ready_source(
        db_session, project_factory
    )
    service = InteractionService()
    with patch(
        "modules.interaction.services.build_project_llm_execution_snapshot",
        autospec=True,
        return_value={
            "version": "1",
            "novel_id": "filled-by-test",
            "profile": {"provider_id": "deepseek", "model": "test-model"},
        },
    ):
        response = await service.create_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="我在雾都车站醒来。",
                idempotency_key="source-journey-create",
                source_setup=JourneySourceSetup(
                    source_revision_id=str(revision.id),
                    progress_anchor_key=first["anchor_key"],
                    player_identity=InteractionPlayerIdentity(
                        kind="source_character",
                        reference_key=character_key,
                    ),
                ),
            ),
        )
    journey = await db_session.get(InteractionJourney, uuid.UUID(response.journey.id))
    attempt = await db_session.get(
        InteractionGenerationAttempt, uuid.UUID(response.attempt.id)
    )
    assert journey is not None and attempt is not None
    return service, project_id, revision, first, later, journey, attempt


async def test_source_bound_journey_freezes_revision_anchor_and_epoch(
    db_session,
    project_factory,
) -> None:
    _service, _project, revision, first, _later, journey, attempt = await _source_journey(
        db_session, project_factory
    )

    assert journey.source_revision_id == revision.id
    assert journey.source_anchor_key == first["anchor_key"]
    assert journey.player_identity["label"] == "林默"
    assert attempt.source_revision_id == revision.id
    assert attempt.started_source_context_epoch == 0


async def test_source_bound_empty_context_packet_fails_before_provider(
    db_session,
    project_factory,
) -> None:
    (
        _service,
        _project,
        _revision,
        _first,
        _later,
        journey,
        attempt,
    ) = await _source_journey(db_session, project_factory)
    db_session.task_checkpoint_enabled = True
    task = await db_session.get(AsyncTask, attempt.task_id)
    assert task is not None

    with patch(
        "modules.interaction.generation.compile_interaction_story_context",
        autospec=True,
        return_value=SimpleNamespace(blockers=[], rendered_context=""),
    ):
        with pytest.raises(
            InteractionContextBudgetError,
            match="without rendered content",
        ) as caught:
            await InteractionGenerationWorkflow().prepare_story_task(
                db_session,
                task=task,
            )

    assert caught.value.kind == "source_context_blocked"


async def test_source_context_receives_only_the_remaining_prompt_budget(
    db_session,
    project_factory,
) -> None:
    (
        _service,
        _project,
        _revision,
        _first,
        _later,
        journey,
        attempt,
    ) = await _source_journey(db_session, project_factory)
    db_session.task_checkpoint_enabled = True
    task = await db_session.get(AsyncTask, attempt.task_id)
    assert task is not None
    compiled = SimpleNamespace(
        blockers=[],
        rendered_context="<SOURCE_REFERENCE_DATA>已校验资料</SOURCE_REFERENCE_DATA>",
        snapshot_id=None,
        fingerprint="f" * 64,
        included_refs=[],
    )

    with (
        patch(
            "modules.interaction.generation.compile_interaction_story_context",
            autospec=True,
            return_value=compiled,
        ) as compile_context,
        patch(
            "modules.interaction.generation.restore_project_llm_execution_settings",
            autospec=True,
            return_value={"llm": {"model": "deepseek-v4-flash"}},
        ),
    ):
        await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=task,
        )

    assert compile_context.await_args.kwargs["budget_tokens"] == 16_000


async def test_source_setup_rejects_character_before_first_appearance(
    db_session,
    project_factory,
) -> None:
    _project, revision, first, _later, character_key = await _ready_source(
        db_session, project_factory
    )
    revision.reference_manifest[0]["appearance_chapters"] = [2]
    revision.reference_manifest[0]["first_chapter_index"] = 2

    with pytest.raises(ValidationError, match="尚未登场"):
        await InteractionService()._sources.prepare_setup(  # noqa: SLF001
            db_session,
            JourneySourceSetup(
                source_revision_id=str(revision.id),
                progress_anchor_key=first["anchor_key"],
                player_identity=InteractionPlayerIdentity(
                    kind="source_character",
                    reference_key=character_key,
                ),
            ),
        )


async def test_ambiguity_resolution_freezes_ready_revision_fingerprint(
    db_session,
    project_factory,
) -> None:
    _project, revision, _first, _later, character_key = await _ready_source(
        db_session, project_factory
    )
    revision.status = "needs_confirmation"
    revision.ambiguities = [
        {
            "ambiguity_key": "ambiguity-1",
            "label": "林默",
            "reason": "同名",
            "choices": [
                {
                    "choice_key": character_key,
                    "label": "林默",
                    "entity_type": "character",
                }
            ],
        }
    ]
    revision.resolutions = {}
    previous_fingerprint = revision.fingerprint
    service = InteractionService()._sources  # noqa: SLF001

    response = await service.resolve_ambiguity(
        db_session,
        revision_id=str(revision.id),
        ambiguity_key="ambiguity-1",
        choice_key=character_key,
    )

    assert response.status == "ready"
    assert revision.fingerprint != previous_fingerprint
    with pytest.raises(ConflictError, match="已冻结"):
        await service.resolve_ambiguity(
            db_session,
            revision_id=str(revision.id),
            ambiguity_key="ambiguity-1",
            choice_key=character_key,
        )


async def test_ambiguity_resolution_rejects_unfinished_revision(
    db_session,
    project_factory,
) -> None:
    _project, revision, _first, _later, character_key = await _ready_source(
        db_session, project_factory
    )
    revision.status = "organizing"

    with pytest.raises(ConflictError, match="尚未进入关键指代确认"):
        await InteractionService()._sources.resolve_ambiguity(  # noqa: SLF001
            db_session,
            revision_id=str(revision.id),
            ambiguity_key="not-finalized",
            choice_key=character_key,
        )


async def test_unfinished_serial_becomes_ready_when_current_import_is_fully_organized(
    db_session,
    project_factory,
) -> None:
    _project, revision, first, later, _character = await _ready_source(
        db_session, project_factory
    )
    revision.status = "organizing"
    revision.ready_at = None
    service = InteractionService()._sources  # noqa: SLF001
    with (
        patch(
            "modules.interaction.source_service.get_scene_span_coverage",
            autospec=True,
            return_value=SimpleNamespace(
                scene_count=2,
                scene_without_span_count=0,
                imprecise_span_count=0,
            ),
        ),
        patch.object(
            service,
            "_reference_manifest",
            autospec=True,
            return_value=(revision.reference_manifest, []),
        ),
        patch.object(
            service,
            "_anchor_manifest",
            autospec=True,
            return_value=[first, later],
        ),
    ):
        await service._finalize(db_session, revision)  # noqa: SLF001

    assert revision.status == "ready"
    assert revision.fingerprint
    assert revision.readiness_summary["message"] == "作品资料已完整整理，可以开始旅程"
    assert "ending" not in revision.readiness_summary


async def test_organizing_revision_fails_if_author_changes_frozen_manuscript(
    db_session,
    project_factory,
) -> None:
    _project, revision, _first, _later, _character = await _ready_source(
        db_session, project_factory
    )
    revision.status = "organizing"
    revision.task_id = uuid.uuid4()
    service = InteractionService()._sources  # noqa: SLF001
    with (
        patch(
            "modules.interaction.source_service.list_task_lifecycle_contracts",
            autospec=True,
            return_value={
                str(revision.task_id): SimpleNamespace(
                    status="done",
                    recovery_required=False,
                )
            },
        ),
        patch.object(
            service,
            "_source_manifest_is_current",
            autospec=True,
            return_value=False,
        ),
    ):
        await service._refresh(db_session, revision)  # noqa: SLF001

    assert revision.status == "failed"
    assert "正文发生变化" in revision.readiness_summary["message"]


async def test_organizing_revision_fails_when_primary_task_is_cancelled(
    db_session,
    project_factory,
) -> None:
    _project, revision, _first, _later, _character = await _ready_source(
        db_session, project_factory
    )
    revision.status = "organizing"
    revision.task_id = uuid.uuid4()
    service = InteractionService()._sources  # noqa: SLF001
    with patch(
        "modules.interaction.source_service.list_task_lifecycle_contracts",
        autospec=True,
        return_value={
            str(revision.task_id): SimpleNamespace(
                status="cancelled",
                recovery_required=False,
            )
        },
    ):
        await service._refresh(db_session, revision)  # noqa: SLF001

    assert revision.status == "failed"
    assert "完整整理中断" in revision.readiness_summary["message"]


@pytest.mark.parametrize(
    "reannotation_status",
    ["pending", "failed", "cancelled", "done"],
)
async def test_organizing_revision_requires_successful_object_reannotation(
    db_session,
    project_factory,
    reannotation_status,
) -> None:
    _project, revision, _first, _later, _character = await _ready_source(
        db_session, project_factory
    )
    revision.status = "organizing"
    revision.task_id = uuid.uuid4()
    service = InteractionService()._sources  # noqa: SLF001
    with (
        patch(
            "modules.interaction.source_service.list_task_lifecycle_contracts",
            autospec=True,
            return_value={
                str(revision.task_id): SimpleNamespace(
                    status="done",
                    recovery_required=False,
                )
            },
        ),
        patch.object(
            service,
            "_source_manifest_is_current",
            autospec=True,
            return_value=True,
        ),
        patch.object(
            service,
            "_indices_are_fresh",
            autospec=True,
            return_value=True,
        ),
        patch(
            "modules.interaction.source_service.get_latest_coalesced_task",
            autospec=True,
            return_value=SimpleNamespace(status=reannotation_status),
        ),
        patch.object(service, "_finalize", autospec=True) as finalize,
    ):
        await service._refresh(db_session, revision)  # noqa: SLF001

    if reannotation_status == "done":
        finalize.assert_awaited_once()
        return
    assert revision.status == (
        "organizing" if reannotation_status == "pending" else "failed"
    )
    assert (
        "核对对象" if reannotation_status == "pending" else "关联核对中断"
    ) in revision.readiness_summary["message"]
    finalize.assert_not_awaited()


async def test_relation_evidence_chapter_requires_frozen_source(
    db_session,
) -> None:
    draft_id = str(uuid.uuid4())
    source_hash = "a" * 64
    service = InteractionSourceService()
    exact = {
        "draft_id": draft_id,
        "source_hash": source_hash,
        "chapter_index": 2,
    }
    stale = {**exact, "source_hash": "c" * 64}
    with patch(
        "modules.interaction.source_service.trace_novel_evidence",
        autospec=True,
        return_value={
            "links": [
                {"status": "active", "source_ref": stale},
                {"status": "needs_review", "source_ref": exact},
                {"status": "active", "source_ref": exact},
            ]
        },
    ) as trace:
        chapter = await service._relation_evidence_chapter(  # noqa: SLF001
            db_session,
            source_id=str(uuid.uuid4()),
            relation_id=str(uuid.uuid4()),
            frozen_sources={draft_id: (source_hash, 2)},
        )

    assert chapter == 2
    assert trace.await_args.kwargs["content_mode"] == "working"

    with patch(
        "modules.interaction.source_service.trace_novel_evidence",
        autospec=True,
        return_value={"links": [{"status": "active", "source_ref": stale}]},
    ):
        assert (
            await service._relation_evidence_chapter(  # noqa: SLF001
                db_session,
                source_id=str(uuid.uuid4()),
                relation_id=str(uuid.uuid4()),
                frozen_sources={draft_id: (source_hash, 2)},
            )
            is None
        )


async def test_reference_control_uses_source_epoch_and_blocks_stale_writer(
    db_session,
    project_factory,
) -> None:
    (
        service,
        _project,
        _revision,
        _first,
        _later,
        journey,
        attempt,
    ) = await _source_journey(db_session, project_factory)
    attempt.status = "completed"
    key = journey.player_identity["reference_key"]
    summary = await service.update_references(
        db_session,
        journey_id=str(journey.id),
        data=InteractionReferenceUpdateRequest(
            action="pin",
            reference_key=key,
            expected_source_context_epoch=0,
        ),
    )

    assert summary.source.source_context_epoch == 1
    assert summary.pinned[0].label == "林默"
    with pytest.raises(ConflictError, match="已在其他页面更新"):
        await service.update_references(
            db_session,
            journey_id=str(journey.id),
            data=InteractionReferenceUpdateRequest(
                action="reset",
                expected_source_context_epoch=0,
            ),
        )


async def test_started_journey_cannot_move_progress_backward(
    db_session,
    project_factory,
) -> None:
    service, _project, revision, first, later, journey, attempt = await _source_journey(
        db_session, project_factory
    )
    attempt.status = "completed"
    journey.source_anchor = later
    journey.source_anchor_key = later["anchor_key"]

    with pytest.raises(ConflictError, match="不能回退"):
        await service.update_journey_source(
            db_session,
            journey_id=str(journey.id),
            data=InteractionSourceUpdateRequest(
                source_revision_id=str(revision.id),
                progress_anchor_key=first["anchor_key"],
                expected_selection_epoch=journey.selection_epoch,
                expected_source_context_epoch=journey.source_context_epoch,
            ),
        )


async def test_late_result_revalidates_source_context_epoch(
    db_session,
    project_factory,
) -> None:
    (
        _service,
        _project,
        _revision,
        _first,
        _later,
        journey,
        attempt,
    ) = await _source_journey(db_session, project_factory)
    attempt.status = "running"
    attempt.visible_text = "这段内容来自旧的作品上下文。"
    attempt.visible_offset = len(attempt.visible_text)
    journey.source_context_epoch += 1
    db_session.task_checkpoint_enabled = True
    task = SimpleNamespace(
        id=attempt.task_id,
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "attempt_id": str(attempt.id),
            "llm_execution_snapshot": attempt.llm_execution_snapshot,
        },
        progress=0.0,
    )
    task.update_progress = lambda value: setattr(task, "progress", value)

    result = await InteractionGenerationWorkflow().finalize_story_task(
        db_session,
        task=task,
        finish_reason="stop",
        metadata=None,
    )

    assert result["status"] == "failed"
    assert attempt.error_kind == "source_context_stale"
    assert attempt.error_message == "作品资料已变化，请重新生成"
    assert attempt.result_node_id is None


async def test_archived_source_fails_closed_and_permanent_delete_is_blocked(
    db_session,
    project_factory,
) -> None:
    (
        _service,
        project_id,
        _revision,
        _first,
        _later,
        journey,
        attempt,
    ) = await _source_journey(db_session, project_factory)
    await ProjectService().delete_project(db_session, str(project_id))
    db_session.task_checkpoint_enabled = True
    task = await db_session.get(AsyncTask, attempt.task_id)
    assert task is not None

    with pytest.raises(NotFoundError):
        await InteractionGenerationWorkflow().prepare_story_task(
            db_session,
            task=task,
        )
    with pytest.raises(ConflictError, match="RP 旅程"):
        await ProjectService().permanent_delete_project(
            db_session,
            str(project_id),
            confirmed=True,
        )


async def test_other_owner_cannot_bind_source_revision(
    db_session,
    project_factory,
) -> None:
    project_id = await project_factory.create_project(
        title="他人作品",
        project_kind="author",
    )
    revision = InteractionSourceRevision(
        source_novel_id=project_id,
        owner_id=uuid.uuid4(),
        version_number=1,
        title="他人作品",
        status="ready",
        source_manifest=[],
        anchor_manifest=[_anchor("起点", 1, 10)],
        reference_manifest=[],
        ambiguities=[],
        resolutions={},
        readiness_summary={},
        manifest_hash="e" * 64,
        fingerprint="f" * 64,
    )
    # The owner FK is intentionally not bypassed; create a real account row.
    from modules.account.models import Account

    account = Account(id=revision.owner_id, status="active", support_code="U-SOURCE-X")
    db_session.add_all([account, revision])
    await db_session.flush()

    with pytest.raises(NotFoundError):
        await InteractionService()._sources.prepare_setup(  # noqa: SLF001
            db_session,
            JourneySourceSetup(
                source_revision_id=str(revision.id),
                progress_anchor_key=revision.anchor_manifest[0]["anchor_key"],
                player_identity=InteractionPlayerIdentity(
                    kind="original",
                    name="原创角色",
                ),
            ),
        )


async def test_source_list_includes_author_project_without_revision(
    db_session,
    project_factory,
) -> None:
    project_id = await project_factory.create_project(
        title="尚未整理的作品",
        project_kind="author",
        owner_id=LOCAL_OWNER_ID,
    )

    result = await InteractionService()._sources.list_sources(db_session)  # noqa: SLF001

    project = next(item for item in result.projects if item.project_id == str(project_id))
    assert project.latest_revision is None

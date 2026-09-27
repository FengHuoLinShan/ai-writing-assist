from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, String, Text, select

from core.base import Base
from core.config import Settings
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.evidence.compilation.models import ContextSnapshot
from modules.evidence.compilation.services.interaction_story_context import (
    InteractionStoryContextService,
)
from modules.evidence.facade import compile_interaction_story_context
from modules.evidence.indexing.repositories import RagChunkRepository
from modules.evidence.indexing.schemas import RagChunkCreate
from modules.interaction.api import _require_non_anonymous_care
from modules.interaction.generation import (
    PreparedStoryGeneration,
    PreparedSummaryGeneration,
)
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionSourceRevision,
)
from modules.interaction.prompts import LLMMessage
from modules.interaction.runtime_policy import anonymous_rp_execution_settings
from modules.interaction.schemas import (
    InteractionPlayerIdentity,
    InteractionSummaryOutput,
    JourneyCreateRequest,
    JourneySourceSetup,
)
from modules.interaction.services import InteractionService
from modules.interaction.source_service import InteractionSourceService, _fingerprint
from modules.interaction.streaming import stream_anonymous_rp_attempt
from modules.interaction.tests.governance_fakes import GovernedAuditMixin
from modules.story.outline_state.models import Scene, SceneSpan
from modules.writing.facade import create_published_draft_only

pytestmark = pytest.mark.asyncio


def _principal(account: Account) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type="anonymous_rp",
        support_code=account.support_code,
    )


def _settings(revision_id: uuid.UUID, project_id: uuid.UUID) -> Settings:
    return Settings(
        public_demo_enabled=True,
        public_demo_project_id=str(project_id),
        public_demo_version="test-v1",
        public_demo_rp_enabled=True,
        public_demo_rp_source_revision_id=str(revision_id),
    )


async def test_anonymous_rp_cannot_use_proactive_care() -> None:
    account = Account(status="active", support_code="U-DEMO-CARE")
    token = bind_principal(_principal(account))
    try:
        with pytest.raises(ValidationError, match="主动后台续写"):
            _require_non_anonymous_care()
    finally:
        reset_principal(token)


async def _public_source(db_session, project_factory):  # noqa: ANN001
    source_owner = Account(status="active", support_code="U-DEMO-SOURCE")
    db_session.add(source_owner)
    await db_session.flush()
    source_project_id = await project_factory.create_project(
        title="公开作品",
        project_kind="author",
        owner_id=source_owner.id,
    )
    source_text = ("雾从海面涌来，林默听见远处的汽笛。" * 8)[:120]
    draft = await create_published_draft_only(
        db_session,
        str(source_project_id),
        1,
        "第一章",
        source_text,
    )
    target_id = uuid.uuid4()
    await RagChunkRepository().replace_chapter_chunks(
        db_session,
        source_project_id,
        source_type="chapter_text",
        chapter_index=1,
        content_mode="canonical",
        items=[
            RagChunkCreate(
                source_type="chapter_text",
                source_id=str(draft.id),
                source_content_hash=draft.content_hash,
                content_mode="canonical",
                chapter_index=1,
                chunk_index=0,
                start_offset=0,
                end_offset=len(source_text),
                char_count=len(source_text),
                text=source_text,
                character_ids=[str(target_id)],
                entity_ids=[str(target_id)],
                index_version="cn-novel-v1",
            )
        ],
    )
    scene = Scene(
        novel_id=source_project_id,
        scene_index=0,
        title="雾港初见",
        status="canonical",
    )
    db_session.add(scene)
    await db_session.flush()
    db_session.add(
        SceneSpan(
            novel_id=source_project_id,
            scene_id=scene.id,
            chapter_index=1,
            content_mode="canonical",
            source_draft_id=uuid.UUID(str(draft.id)),
            source_content_hash=draft.content_hash,
            start_offset=0,
            end_offset=len(source_text),
            part_no=1,
            mapping_status="exact",
            source="manual",
            status="canonical",
        )
    )
    anchor = {
        "anchor_key": "a" * 64,
        "chapter_index": 1,
        "chapter_title": "第一章",
        "label": "雾港初见",
        "excerpt": "雾从海面涌来。",
        "end_offset": len(source_text),
        "scene_id": str(scene.id),
    }
    reference_key = "c" * 64
    manifest = [
        {
            "draft_id": str(draft.id),
            "chapter_index": 1,
            "version_number": 1,
            "source_hash": draft.content_hash,
            "title": "第一章",
            "char_count": len(source_text),
        }
    ]
    references = [
        {
            "reference_key": reference_key,
            "target_id": str(target_id),
            "entity_type": "character",
            "label": "林默",
            "aliases": ["默默"],
            "first_chapter_index": 1,
            "first_end_offset": min(80, len(source_text)),
        }
    ]
    revision = InteractionSourceRevision(
        source_novel_id=source_project_id,
        owner_id=source_owner.id,
        version_number=1,
        title="公开作品",
        status="ready",
        source_manifest=manifest,
        anchor_manifest=[anchor],
        reference_manifest=references,
        ambiguities=[],
        resolutions={},
        readiness_summary={"message": "已冻结"},
        manifest_hash="d" * 64,
        fingerprint=_fingerprint(
            {
                "source_manifest": manifest,
                "anchors": [anchor],
                "references": references,
                "ambiguities": [],
                "resolutions": {},
            }
        ),
    )
    db_session.add(revision)
    await db_session.flush()
    return revision, anchor, reference_key


async def test_anonymous_demo_journey_is_isolated_and_never_enqueues(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    revision, anchor, reference_key = await _public_source(db_session, project_factory)
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, revision.source_novel_id),
    )
    first = Account(status="active", support_code="U-DEMO-ONE")
    second = Account(status="active", support_code="U-DEMO-TWO")
    db_session.add_all([first, second])
    await db_session.flush()
    service = InteractionService()
    request = JourneyCreateRequest(
        opening_text="我在雾港的雨里醒来。",
        idempotency_key="anonymous-demo-opening-1",
        source_setup=JourneySourceSetup(
            source_revision_id=str(revision.id),
            progress_anchor_key=anchor["anchor_key"],
            player_identity=InteractionPlayerIdentity(
                kind="source_character",
                reference_key=reference_key,
            ),
        ),
    )

    first_token = bind_principal(_principal(first))
    try:
        created = await service.create_demo_journey(db_session, request)
        references = await service.get_reference_summary(
            db_session,
            journey_id=created.journey.id,
        )
    finally:
        reset_principal(first_token)

    attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(created.attempt.id),
    )
    assert attempt is not None
    assert attempt.task_id is None
    assert attempt.status == "pending"
    assert references.source.revision_id == str(revision.id)
    assert "api_key" not in json.dumps(attempt.llm_execution_snapshot)
    assert "deepseek-v4-flash" in json.dumps(attempt.llm_execution_snapshot)
    tasks = list(
        (
            await db_session.execute(
                select(AsyncTask).where(AsyncTask.novel_id == attempt.novel_id)
            )
        ).scalars()
    )
    assert tasks == []

    second_token = bind_principal(_principal(second))
    try:
        listed = await service.list_journeys(
            db_session,
            status="active",
            search=None,
            offset=0,
            limit=10,
        )
        with pytest.raises(NotFoundError):
            await service.get_attempt_state(
                db_session,
                journey_id=created.journey.id,
                attempt_id=created.attempt.id,
            )
    finally:
        reset_principal(second_token)

    assert listed.items == []


async def test_anonymous_demo_rejects_any_source_but_the_configured_revision(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    revision, anchor, reference_key = await _public_source(db_session, project_factory)
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, revision.source_novel_id),
    )
    account = Account(status="active", support_code="U-DEMO-SOURCE-GATE")
    db_session.add(account)
    await db_session.flush()
    token = bind_principal(_principal(account))
    try:
        with pytest.raises(NotFoundError):
            await InteractionService().create_demo_journey(
                db_session,
                JourneyCreateRequest(
                    opening_text="错误来源。",
                    idempotency_key="anonymous-demo-wrong-source",
                    source_setup=JourneySourceSetup(
                        source_revision_id=str(uuid.uuid4()),
                        progress_anchor_key=anchor["anchor_key"],
                        player_identity=InteractionPlayerIdentity(
                            kind="source_character",
                            reference_key=reference_key,
                        ),
                    ),
                ),
            )
    finally:
        reset_principal(token)


async def test_public_demo_source_fails_closed_for_an_empty_frozen_manifest(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    revision, _anchor, _reference_key = await _public_source(
        db_session,
        project_factory,
    )
    revision.reference_manifest = []
    revision.fingerprint = _fingerprint(
        {
            "source_manifest": revision.source_manifest,
            "anchors": revision.anchor_manifest,
            "references": revision.reference_manifest,
            "ambiguities": revision.ambiguities,
            "resolutions": revision.resolutions,
        }
    )
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, revision.source_novel_id),
    )

    with pytest.raises(NotFoundError):
        await InteractionSourceService().public_demo_source(db_session)


async def test_public_demo_source_must_belong_to_the_configured_project(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    revision, _anchor, _reference_key = await _public_source(
        db_session,
        project_factory,
    )
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, uuid.uuid4()),
    )

    with pytest.raises(NotFoundError):
        await InteractionSourceService().public_demo_source(db_session)


async def test_public_demo_source_fails_closed_after_the_manuscript_changes(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    revision, _anchor, _reference_key = await _public_source(
        db_session,
        project_factory,
    )
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, revision.source_novel_id),
    )
    await create_published_draft_only(
        db_session,
        str(revision.source_novel_id),
        1,
        "第一章（已修订）",
        "演示正文已发生变化。",
    )

    with pytest.raises(NotFoundError):
        await InteractionSourceService().public_demo_source(db_session)


async def test_evidence_public_demo_exception_rejects_an_arbitrary_revision(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    revision, _anchor, _reference_key = await _public_source(
        db_session,
        project_factory,
    )
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, revision.source_novel_id),
    )

    with pytest.raises(NotFoundError):
        await compile_interaction_story_context(
            db_session,
            source_novel_id=str(revision.source_novel_id),
            consumer_novel_id=str(uuid.uuid4()),
            source_revision_id=str(uuid.uuid4()),
            source_manifest=[],
            anchor={},
            player_identity={},
            reference_manifest=[],
            ambiguities=[],
            resolutions={},
            reference_policy={},
            query="",
            task_id=None,
            model="deepseek-v4-flash",
            public_demo_source=True,
            public_demo_source_fingerprint=revision.fingerprint,
        )


async def test_public_demo_context_snapshot_is_owned_by_the_consumer_project(
    db_session,
    project_factory,
) -> None:
    revision, anchor, _reference_key = await _public_source(
        db_session,
        project_factory,
    )
    consumer_owner = Account(status="active", support_code="U-DEMO-CONSUMER")
    db_session.add(consumer_owner)
    await db_session.flush()
    consumer_id = await project_factory.create_project(
        title="匿名旅程",
        project_kind="interaction",
        owner_id=consumer_owner.id,
    )

    compiled = await InteractionStoryContextService()._snapshot_result(  # noqa: SLF001
        db_session,
        source_novel_id=str(revision.source_novel_id),
        consumer_novel_id=str(consumer_id),
        source_revision_id=str(revision.id),
        anchor=anchor,
        task_id=None,
        model="deepseek-v4-flash",
        rendered="雾港雨夜",
        included_refs=[],
        warnings=[],
        blockers=[],
    )
    snapshot = await db_session.get(ContextSnapshot, uuid.UUID(compiled.snapshot_id))

    assert snapshot is not None
    assert snapshot.novel_id == consumer_id
    assert snapshot.consumer_novel_id == consumer_id
    assert (
        list(
            (
                await db_session.execute(
                    select(ContextSnapshot).where(
                        ContextSnapshot.novel_id == revision.source_novel_id
                    )
                )
            ).scalars()
        )
        == []
    )


async def test_freeze_candidate_is_dry_run_by_default_and_writes_only_after_gate(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    import modules.interaction.source_service as source_module

    owner = Account(status="active", support_code="U-DEMO-FREEZE")
    db_session.add(owner)
    await db_session.flush()
    project_id = await project_factory.create_project(
        title="公开作品",
        project_kind="author",
        owner_id=owner.id,
    )
    draft_id = uuid.uuid4()
    service = source_module.InteractionSourceService()
    source = SimpleNamespace(
        id=str(draft_id),
        chapter_index=1,
        version_number=1,
        content_hash="e" * 64,
        title="第一章",
        content="雾港的雨落下。",
    )
    reference = {
        "reference_key": "r" * 64,
        "target_id": str(uuid.uuid4()),
        "entity_type": "character",
        "label": "林默",
        "aliases": [],
        "first_chapter_index": 1,
        "first_end_offset": 3,
    }
    anchor = {
        "anchor_key": "a" * 64,
        "chapter_index": 1,
        "chapter_title": "第一章",
        "label": "开场",
        "excerpt": "雾港",
        "end_offset": len(source.content),
        "scene_id": None,
    }

    async def project_context(_db, _project_id):  # noqa: ANN001
        return SimpleNamespace(
            project_kind="author",
            owner_id=str(owner.id),
            title="公开作品",
        )

    async def chapter_indices(_db, _project_id):  # noqa: ANN001
        return [1]

    async def manuscript_sources(_db, _project_id, _indices, **_kwargs):  # noqa: ANN001
        return [source]

    async def index_coverage(_db, _project_id, _manifest):  # noqa: ANN001
        return {1}

    async def scene_coverage(_db, _project_id, **_kwargs):  # noqa: ANN001
        return SimpleNamespace(
            scene_count=1,
            scene_without_span_count=0,
            imprecise_span_count=0,
        )

    async def references(_db, _revision):  # noqa: ANN001
        return [dict(reference)], []

    async def anchors(_db, _revision):  # noqa: ANN001
        return [{**anchor, "anchor_key": str(_revision.id)}]

    monkeypatch.setattr(source_module, "get_project_context", project_context)
    monkeypatch.setattr(source_module, "list_effective_chapter_indices", chapter_indices)
    monkeypatch.setattr(source_module, "list_manuscript_sources", manuscript_sources)
    monkeypatch.setattr(source_module, "get_manifest_index_coverage", index_coverage)
    monkeypatch.setattr(source_module, "get_scene_span_coverage", scene_coverage)
    monkeypatch.setattr(service, "_reference_manifest", references)
    monkeypatch.setattr(service, "_anchor_manifest", anchors)

    preview, created = await service.materialize_frozen_source_candidate(
        db_session,
        project_id=str(project_id),
        execute=False,
    )
    assert created is False
    assert preview.status == "ready"
    assert (
        list((await db_session.execute(select(InteractionSourceRevision))).scalars())
        == []
    )

    stored, created = await service.materialize_frozen_source_candidate(
        db_session,
        project_id=str(project_id),
        execute=True,
    )
    assert created is True
    assert stored.fingerprint
    assert list(
        (await db_session.execute(select(InteractionSourceRevision))).scalars()
    ) == [stored]

    unchanged, created = await service.materialize_frozen_source_candidate(
        db_session, project_id=str(project_id), execute=True, refresh_existing=True
    )
    assert not created and unchanged.id == stored.id
    original_fingerprint = stored.fingerprint
    reference["summary"] = "新核对的人物资料"
    refreshed, created = await service.materialize_frozen_source_candidate(
        db_session, project_id=str(project_id), execute=True, refresh_existing=True
    )
    assert created and refreshed.id != stored.id
    assert refreshed.version_number == stored.version_number + 1
    assert refreshed.parent_revision_id == stored.id
    assert refreshed.manifest_hash == stored.manifest_hash
    assert stored.fingerprint == original_fingerprint
    assert "summary" not in stored.reference_manifest[0]
    latest = await service._repo.source_revision_by_manifest(
        db_session,
        source_novel_id=project_id,
        owner_id=owner.id,
        manifest_hash=stored.manifest_hash,
    )
    assert latest.id == refreshed.id


async def test_reference_refresh_rejects_another_owner(db_session, project_factory):
    revision, _anchor, _reference = await _public_source(db_session, project_factory)
    with pytest.raises(NotFoundError):
        await InteractionSourceService().refresh_references(db_session, str(revision.id))


async def test_anonymous_attempt_claim_is_single_owner_and_blocks_background_modes(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    revision, anchor, reference_key = await _public_source(db_session, project_factory)
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, revision.source_novel_id),
    )
    account = Account(status="active", support_code="U-DEMO-CLAIM")
    db_session.add(account)
    await db_session.flush()
    token = bind_principal(_principal(account))
    try:
        service = InteractionService()
        created = await service.create_demo_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="我抵达雾港。",
                idempotency_key="anonymous-demo-claim",
                source_setup=JourneySourceSetup(
                    source_revision_id=str(revision.id),
                    progress_anchor_key=anchor["anchor_key"],
                    player_identity=InteractionPlayerIdentity(
                        kind="source_character",
                        reference_key=reference_key,
                    ),
                ),
            ),
        )
        execution_id = await service.claim_anonymous_attempt(
            db_session,
            journey_id=created.journey.id,
            attempt_id=created.attempt.id,
        )
        with pytest.raises(ConflictError):
            await service.claim_anonymous_attempt(
                db_session,
                journey_id=created.journey.id,
                attempt_id=created.attempt.id,
            )
        with pytest.raises(ValidationError, match="持续观看或联网"):
            await service.update_modes(
                db_session,
                journey_id=created.journey.id,
                see_sea_enabled=True,
                action_options_enabled=None,
                web_search_enabled=None,
                expected_selection_epoch=0,
            )
    finally:
        reset_principal(token)

    attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(created.attempt.id),
    )
    assert attempt is not None
    assert attempt.status == "preparing_context"
    assert attempt.usage["inline_execution_id"] == execution_id
    assert "key" not in json.dumps(attempt.usage).lower()


class _SessionScope:
    def __init__(self, session) -> None:  # noqa: ANN001
        self._session = session

    async def __aenter__(self):  # noqa: ANN204
        return self._session

    async def __aexit__(self, *_args) -> None:  # noqa: ANN002
        return None


class _Manager:
    def __init__(self, session) -> None:  # noqa: ANN001
        self._session = session

    def session_factory(self) -> _SessionScope:
        return _SessionScope(self._session)


class _Request:
    def __init__(self, disconnected: bool = False) -> None:
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


async def _assert_no_stored_sentinel(db, sentinel: str) -> None:  # noqa: ANN001
    seen_tables: set[str] = set()
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table.fullname in seen_tables:
            continue
        seen_tables.add(table.fullname)
        columns = [
            column
            for column in table.columns
            if isinstance(column.type, (JSON, String, Text))
        ]
        if not columns:
            continue
        rows = await db.execute(select(*columns).select_from(table))
        for row in rows:
            assert sentinel not in json.dumps(tuple(row), default=str)


async def _claimed_demo_attempt(db_session, project_factory, monkeypatch):  # noqa: ANN001
    revision, anchor, reference_key = await _public_source(db_session, project_factory)
    monkeypatch.setattr(
        "modules.interaction.source_service.get_settings",
        lambda: _settings(revision.id, revision.source_novel_id),
    )
    account = Account(status="active", support_code="U-DEMO-STREAM")
    db_session.add(account)
    await db_session.flush()
    principal = _principal(account)
    token = bind_principal(principal)
    try:
        service = InteractionService()
        created = await service.create_demo_journey(
            db_session,
            JourneyCreateRequest(
                opening_text="我踏进雾港。",
                idempotency_key="anonymous-demo-stream",
                source_setup=JourneySourceSetup(
                    source_revision_id=str(revision.id),
                    progress_anchor_key=anchor["anchor_key"],
                    player_identity=InteractionPlayerIdentity(
                        kind="source_character",
                        reference_key=reference_key,
                    ),
                ),
            ),
        )
        execution_id = await service.claim_anonymous_attempt(
            db_session,
            journey_id=created.journey.id,
            attempt_id=created.attempt.id,
        )
    finally:
        reset_principal(token)
    return principal, created, execution_id


def _govern_passed():
    async def _govern(db, *, task, client, prepared):  # noqa: ANN001
        return {"status": "passed", "text": "审查通过的故事。", "review": {}}

    return _govern


def _noop_async():
    async def _noop(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    return _noop


async def test_request_stream_keeps_temporary_key_out_of_attempt_and_task_storage(
    db_session,
    project_factory,
    monkeypatch,
    caplog,
) -> None:
    import modules.interaction.streaming as streaming

    principal, created, execution_id = await _claimed_demo_attempt(
        db_session,
        project_factory,
        monkeypatch,
    )
    captured_settings: list[dict] = []
    prepare_calls = 0
    summary_finalized = []

    async def prepare(db, *, task):  # noqa: ANN001
        nonlocal prepare_calls
        prepare_calls += 1
        attempt = await db.get(
            InteractionGenerationAttempt, uuid.UUID(created.attempt.id)
        )
        assert attempt is not None
        settings = anonymous_rp_execution_settings(dict(attempt.llm_execution_snapshot))
        if prepare_calls == 1:
            return PreparedSummaryGeneration(
                novel_id=str(attempt.novel_id),
                journey_id=created.journey.id,
                path_hash="a" * 64,
                node_ids=[],
                segment_node_ids=[],
                started_overview_epoch=0,
                messages=[LLMMessage(role="user", content="压缩前情")],
                executable_settings=settings,
            )
        attempt.status = "running"
        return PreparedStoryGeneration(
            novel_id=str(attempt.novel_id),
            journey_id=created.journey.id,
            attempt_id=created.attempt.id,
            request_kind="opening",
            messages=[LLMMessage(role="user", content="继续")],
            executable_settings=settings,
            existing_visible_text="",
        )

    async def checkpoint(db, *, task, visible_delta, **_kwargs):  # noqa: ANN001
        attempt = await db.get(
            InteractionGenerationAttempt, uuid.UUID(created.attempt.id)
        )
        assert attempt is not None
        attempt.visible_text += visible_delta
        attempt.visible_offset = len(attempt.visible_text)
        return attempt.visible_offset

    async def finalize(db, *, task, **_kwargs):  # noqa: ANN001
        attempt = await db.get(
            InteractionGenerationAttempt, uuid.UUID(created.attempt.id)
        )
        assert attempt is not None
        attempt.status = "completed"
        return {"status": "completed"}

    async def finalize_summary(db, *, task, prepared, output, **_kwargs):  # noqa: ANN001
        summary_finalized.append((prepared, output))
        return {"status": "completed", "story_resume": True}

    class Client(GovernedAuditMixin):
        async def generate_structured(self, _request, _schema, **_kwargs):  # noqa: ANN001
            return InteractionSummaryOutput.model_validate(
                {
                    "segment_summary": "旧事已压缩。",
                    "overview": {"current_situation": "仍在雾港。"},
                }
            )

        async def generate_stream(self, _request, *, transport_retries):  # noqa: ANN001
            yield SimpleNamespace(
                content="雨落在雾港。", finish_reason="stop", usage=None
            )

        async def close(self) -> None:
            return None

    def make_client(settings, *, novel_id):  # noqa: ANN001
        captured_settings.append(settings)
        return Client()

    monkeypatch.setattr(streaming, "get_manager", lambda: _Manager(db_session))
    monkeypatch.setattr(streaming._inline_workflow, "prepare_story_task", prepare)
    monkeypatch.setattr(streaming._inline_workflow, "checkpoint_story_task", checkpoint)
    monkeypatch.setattr(streaming._inline_workflow, "finalize_story_task", finalize)
    monkeypatch.setattr(
        streaming._inline_workflow,
        "govern_held_story",
        _govern_passed(),
    )
    monkeypatch.setattr(
        streaming._inline_workflow,
        "release_story_task",
        _noop_async(),
    )
    monkeypatch.setattr(
        streaming._inline_workflow,
        "finalize_summary_task",
        finalize_summary,
    )
    monkeypatch.setattr(streaming, "create_project_snapshot_llm_client", make_client)

    events = [
        event
        async for event in stream_anonymous_rp_attempt(
            request=_Request(),
            principal=principal,
            journey_id=uuid.UUID(created.journey.id),
            attempt_id=uuid.UUID(created.attempt.id),
            api_key="temporary-deepseek-key",
            execution_id=execution_id,
        )
    ]

    attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(created.attempt.id),
    )
    assert attempt is not None
    assert any("event: chunk" in event for event in events)
    assert len(summary_finalized) == 1
    assert all(
        settings["llm"]["api_key"] == "temporary-deepseek-key"
        for settings in captured_settings
    )
    assert "temporary-deepseek-key" not in json.dumps(attempt.llm_execution_snapshot)
    assert "temporary-deepseek-key" not in json.dumps(attempt.usage)
    tasks = list(
        (
            await db_session.execute(
                select(AsyncTask).where(AsyncTask.novel_id == attempt.novel_id)
            )
        ).scalars()
    )
    assert tasks == []
    await _assert_no_stored_sentinel(db_session, "temporary-deepseek-key")
    assert "temporary-deepseek-key" not in caplog.text


async def test_provider_error_never_persists_or_logs_the_temporary_key(
    db_session,
    project_factory,
    monkeypatch,
    caplog,
) -> None:
    import modules.interaction.streaming as streaming
    from infrastructure.llm.errors import LLMAuthError

    principal, created, execution_id = await _claimed_demo_attempt(
        db_session,
        project_factory,
        monkeypatch,
    )

    async def prepare(db, *, task):  # noqa: ANN001
        attempt = await db.get(
            InteractionGenerationAttempt,
            uuid.UUID(created.attempt.id),
        )
        assert attempt is not None
        attempt.status = "running"
        return PreparedStoryGeneration(
            novel_id=str(attempt.novel_id),
            journey_id=created.journey.id,
            attempt_id=created.attempt.id,
            request_kind="opening",
            messages=[LLMMessage(role="user", content="继续")],
            executable_settings=anonymous_rp_execution_settings(
                dict(attempt.llm_execution_snapshot)
            ),
            existing_visible_text="",
        )

    class Client:
        async def generate_stream(self, _request, *, transport_retries):  # noqa: ANN001
            raise LLMAuthError("provider rejected temporary-deepseek-key")
            yield  # pragma: no cover

        async def close(self) -> None:
            return None

    monkeypatch.setattr(streaming, "get_manager", lambda: _Manager(db_session))
    monkeypatch.setattr(streaming._inline_workflow, "prepare_story_task", prepare)
    monkeypatch.setattr(
        streaming,
        "create_project_snapshot_llm_client",
        lambda *_args, **_kwargs: Client(),
    )

    events = [
        event
        async for event in stream_anonymous_rp_attempt(
            request=_Request(),
            principal=principal,
            journey_id=uuid.UUID(created.journey.id),
            attempt_id=uuid.UUID(created.attempt.id),
            api_key="temporary-deepseek-key",
            execution_id=execution_id,
        )
    ]

    attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(created.attempt.id),
    )
    assert attempt is not None
    assert attempt.status == "failed"
    assert attempt.error_kind == "configuration"
    assert "temporary-deepseek-key" not in (attempt.error_message or "")
    assert "temporary-deepseek-key" not in "".join(events)
    await _assert_no_stored_sentinel(db_session, "temporary-deepseek-key")
    assert "temporary-deepseek-key" not in caplog.text


async def test_disconnected_request_cancels_its_claimed_anonymous_attempt(
    db_session,
    project_factory,
    monkeypatch,
) -> None:
    import modules.interaction.streaming as streaming

    principal, created, execution_id = await _claimed_demo_attempt(
        db_session,
        project_factory,
        monkeypatch,
    )
    monkeypatch.setattr(streaming, "get_manager", lambda: _Manager(db_session))

    events = [
        event
        async for event in stream_anonymous_rp_attempt(
            request=_Request(disconnected=True),
            principal=principal,
            journey_id=uuid.UUID(created.journey.id),
            attempt_id=uuid.UUID(created.attempt.id),
            api_key="temporary-deepseek-key",
            execution_id=execution_id,
        )
    ]

    attempt = await db_session.get(
        InteractionGenerationAttempt,
        uuid.UUID(created.attempt.id),
    )
    assert events == []
    assert attempt is not None
    assert attempt.status == "cancelled"
    assert attempt.error_kind == "client_disconnected"

"""
Context 模块测试

测试 Context Compiler 的核心逻辑：
1. 各 scope 编译正确性
2. Budget 控制
3. Reveal 模式过滤
4. Markdown 渲染
5. 无数据库时的优雅降级

编译器仍以组合各模块资料为主；确认记录和自动上下文快照由 context 模块持久化。
测试中确保即使业务资料为空，编译器也能正常工作。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CONTEXT_BUDGET,
    ContextConfirmationContract,
    ContextSnapshotRequest,
    StructureContextBundle,
)
from modules.context.facade import (
    compile_structure_context,
    render_context_markdown,
)
from modules.context.markdown_renderer import render_context_markdown as render_md
from modules.context.services import CompileOptions


def _snapshot_request(
    novel_id: str,
    **overrides,
) -> ContextSnapshotRequest:
    payload = {
        "phase": "entity_extraction",
        "operation": "scene_entity_extraction",
        "prompt_name": "scene_entity_extraction",
        "model": "test-model",
        "compile_options": {},
        "included_asset_ids": {},
        "context_summary": {},
        "section_metadata": {},
        "token_metadata": {},
    }
    payload.update(overrides)
    return ContextSnapshotRequest(novel_id=novel_id, **payload)


async def _open_snapshot(
    db_session: AsyncSession,
    novel_id: str,
    **overrides,
):
    from modules.context.facade import open_context_snapshot

    return await open_context_snapshot(
        db_session,
        _snapshot_request(novel_id, **overrides),
    )


# ============================================================
# Context Confirmation 测试
# ============================================================


class TestConfirmedAiAction:
    """测试确认后的 AI 动作上下文 materialization。"""

    @pytest.mark.asyncio
    async def test_prepare_confirmed_ai_action_materializes_markdown(self) -> None:
        from modules.context.services.compiled_context import (
            CompiledContext,
            ContextSection,
            Tier,
        )
        from modules.context.services.confirmed_ai_action import (
            ConfirmedAIActionService,
        )

        confirmation = ContextConfirmationContract(
            id="conf-1",
            novel_id="novel-1",
            action="writing.generate",
            task="写作",
            scope="chapter",
            context_mode="canonical",
            include_pending_objects=False,
            excluded_asset_ids={},
            selected_asset_ids={"context_sections": ["project"]},
            user_note=None,
            compile_options={"budget_tokens": 1200},
            warnings=[],
            sections=[],
            budget_events=[],
            result_refs=[{"type": "task", "id": "old-task"}],
            result_status="pending",
            stale_reasons=[],
            compiled_at="2026-07-03T00:00:00+00:00",
            created_at="2026-07-03T00:00:00+00:00",
        )
        compiled = CompiledContext(
            sections=[
                ContextSection(
                    key="project",
                    tier=Tier.P0,
                    title="项目",
                    content="确认后的上下文",
                    token_count=8,
                )
            ],
            total_tokens=8,
            budget_tokens=1200,
        )

        class FakeConfirmationService:
            async def require_fresh_confirmation(self, db, **kwargs):
                assert kwargs == {
                    "novel_id": "novel-1",
                    "action": "writing.generate",
                    "confirmation_id": "conf-1",
                }
                return confirmation

            async def compile_from_confirmation(self, db, **kwargs):
                assert kwargs["confirmation_id"] == "conf-1"
                return compiled

        service = ConfirmedAIActionService(confirmation_service=FakeConfirmationService())

        result = await service.prepare(
            object(),
            novel_id="novel-1",
            action="writing.generate",
            confirmation_id="conf-1",
        )

        assert result.confirmation is confirmation
        assert result.compiled is compiled
        assert "确认后的上下文" in result.rendered_markdown
        assert result.compile_options == {"budget_tokens": 1200}
        assert result.result_refs == [{"type": "task", "id": "old-task"}]

    @pytest.mark.asyncio
    async def test_prepare_confirmed_ai_action_rejects_stale_confirmation(self) -> None:
        from modules.context.services.confirmed_ai_action import (
            ConfirmedAIActionService,
        )

        class FakeConfirmationService:
            async def require_fresh_confirmation(self, db, **kwargs):
                raise ValueError("context confirmation is stale_context")

        service = ConfirmedAIActionService(confirmation_service=FakeConfirmationService())

        with pytest.raises(ValueError, match="stale_context"):
            await service.prepare(
                object(),
                novel_id="novel-1",
                action="writing.generate",
                confirmation_id="conf-1",
            )

    @pytest.mark.asyncio
    async def test_character_confirmation_materialization_filters_unknown_content(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.context.facade import confirm_context, prepare_confirmed_ai_action
        from modules.project.models import Project
        from modules.world.models import Character, CharacterKnowledge, CoreEntity

        nid = uuid.uuid4()
        novel_id = str(nid)
        char_id = uuid.uuid4()
        target_id = uuid.uuid4()

        db_session.add(
            Project(
                id=nid,
                title="测试小说",
                genre="悬疑",
                language="zh",
            )
        )
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=nid,
                entity_type="character",
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            Character(
                entity_id=char_id,
                novel_id=nid,
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            CoreEntity(
                id=target_id,
                novel_id=nid,
                entity_type="artifact",
                name="禁忌宝石",
                summary="一枚普通宝石。",
                hidden_truth="真实隐藏真相：宝石里封印着凶手记忆。",
                status="canonical",
                importance_level="core",
            )
        )
        db_session.add(
            CharacterKnowledge(
                id=uuid.uuid4(),
                novel_id=nid,
                character_id=char_id,
                target_type="entity",
                target_id=target_id,
                knowledge_level="unknown",
            )
        )
        await db_session.flush()

        confirmation = await confirm_context(
            db_session,
            novel_id=novel_id,
            action="writing.generate",
            task="基于当前 Scene 的 POV 角色有限认知，生成正文候选草稿",
            scope="world_character",
            character_ids=[str(char_id)],
            reveal_mode="character",
            viewpoint_character_id=str(char_id),
            include_pending_objects=True,
        )
        prepared = await prepare_confirmed_ai_action(
            db_session,
            novel_id=novel_id,
            action="writing.generate",
            confirmation_id=confirmation.id,
        )

        assert confirmation.compile_options["reveal_mode"] == "character"
        assert confirmation.compile_options["viewpoint_character_id"] == str(char_id)
        assert prepared.compile_options["viewpoint_character_id"] == str(char_id)
        assert "真实隐藏真相" not in prepared.rendered_markdown
        assert "宝石里封印着凶手记忆" not in prepared.rendered_markdown
        assert "禁忌宝石" not in prepared.rendered_markdown


class TestContextReviewProjection:
    """测试 Context review projection 保持现有 API shape。"""

    def test_context_review_projection_builds_tier_response(self) -> None:
        from modules.context.schemas import ContextCompileRequest
        from modules.context.services.compiled_context import (
            CompiledContext,
            ContextBudgetEvent,
            ContextSection,
            Tier,
        )
        from modules.context.services.review_projection import (
            build_tier_compile_response,
        )

        request = ContextCompileRequest(
            novel_id="novel-1",
            task="写作",
            scope="chapter",
            chapter_index=1,
            budget_tokens=500,
        )
        context = CompiledContext(
            sections=[
                ContextSection(
                    key="project",
                    tier=Tier.P0,
                    content="项目内容",
                    token_count=4,
                    title="项目",
                    status="canonical",
                    can_exclude=True,
                )
            ],
            total_tokens=4,
            budget_tokens=500,
            truncated_keys=["project"],
            budget_events=[
                ContextBudgetEvent(
                    section_key="project",
                    event_type="truncated",
                    reason="测试",
                    before_tokens=8,
                    after_tokens=4,
                    tier=0,
                )
            ],
            warnings=["warn"],
        )

        response = build_tier_compile_response(request, context)

        assert response.novel_id == "novel-1"
        assert response.sections[0].key == "project"
        assert response.sections[0].truncated is True
        assert response.sections[0].can_exclude is False
        assert response.budget_events[0].event_type == "truncated"
        assert response.warnings == ["warn"]


class TestContextSnapshot:
    """测试自动 AI 调用上下文快照。"""

    @pytest.mark.asyncio
    async def test_open_snapshot_request_defaults_and_legacy_equivalence(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.context.facade import (
            create_context_snapshot,
            fail_context_snapshot,
            mark_context_snapshot_failed,
            mark_context_snapshot_succeeded,
            open_context_snapshot,
        )

        novel_id = "00000000-0000-0000-0000-000000000200"
        request = ContextSnapshotRequest(
            novel_id=novel_id,
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={"scope": "scene"},
            included_asset_ids={"scenes": ["scene-1"]},
            context_summary={"scene_index": 1},
            section_metadata={"sections": []},
            token_metadata={"total_tokens": 12},
            rendered_context="full markdown should stay compact by default",
        )

        assert request.context_mode == "working"
        assert request.include_pending_objects is True
        assert request.attempt == 1
        assert request.excluded_asset_ids is None
        assert request.retain_rendered_context is False

        opened = await open_context_snapshot(db_session, request)
        legacy = await create_context_snapshot(
            db_session,
            novel_id=novel_id,
            phase=request.phase,
            operation=request.operation,
            prompt_name=request.prompt_name,
            model=request.model,
            compile_options=request.compile_options,
            included_asset_ids=request.included_asset_ids,
            context_summary=request.context_summary,
            section_metadata=request.section_metadata,
            token_metadata=request.token_metadata,
            rendered_context=request.rendered_context,
        )

        assert opened.status == "running"
        assert opened.context_mode == "working"
        assert opened.include_pending_objects is True
        assert opened.rendered_context is None
        assert opened.included_asset_ids == {"scenes": ["scene-1"]}
        assert opened.prompt_hash == legacy.prompt_hash
        legacy_done = await mark_context_snapshot_succeeded(
            db_session,
            snapshot_id=legacy.id,
            result_refs=[{"type": "scene", "id": "scene-1"}],
        )
        assert legacy_done.status == "succeeded"
        assert legacy_done.result_refs == [{"type": "scene", "id": "scene-1"}]

        failed = await fail_context_snapshot(
            db_session,
            snapshot_id=opened.id,
            error_kind="long_error",
            error_message="x" * 800,
        )
        assert failed.status == "failed"
        assert failed.error_kind == "long_error"
        assert failed.error_message == "x" * 500
        legacy_failed_target = await _open_snapshot(
            db_session,
            novel_id,
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
        )
        legacy_failed = await mark_context_snapshot_failed(
            db_session,
            snapshot_id=legacy_failed_target.id,
            error_kind="compat_timeout",
            error_message="compat failed",
        )
        assert legacy_failed.status == "failed"
        assert legacy_failed.error_kind == "compat_timeout"

    @pytest.mark.asyncio
    async def test_create_snapshot_defaults_to_compact_storage(
        self,
        db_session: AsyncSession,
    ) -> None:
        """默认只保存摘要和 metadata，不保存完整 rendered_context。"""

        novel_id = "00000000-0000-0000-0000-000000000201"
        snapshot = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="wf-1",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            scene_index=1,
            chapter_index=1,
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={"scope": "scene"},
            included_asset_ids={"scenes": ["scene-1"]},
            context_summary={"scene_index": 1},
            section_metadata={"sections": []},
            token_metadata={"total_tokens": 12},
            rendered_context="full markdown should not persist by default",
        )

        assert snapshot.status == "running"
        assert snapshot.novel_id == novel_id
        assert snapshot.context_mode == "working"
        assert snapshot.include_pending_objects is True
        assert snapshot.rendered_context is None
        assert snapshot.rendered_context_expires_at is None
        assert snapshot.included_asset_ids == {"scenes": ["scene-1"]}
        assert snapshot.token_metadata == {"total_tokens": 12}

    @pytest.mark.asyncio
    async def test_create_snapshot_can_retain_rendered_context(
        self,
        db_session: AsyncSession,
    ) -> None:
        """显式 retain_rendered_context 时保存完整上下文并设置过期时间。"""

        snapshot = await _open_snapshot(
            db_session,
            "00000000-0000-0000-0000-000000000202",
            workflow_id="wf-2",
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
            model="test-model",
            compile_options={"scope": "full"},
            included_asset_ids={"context_sections": ["project"]},
            context_summary={"section_count": 1},
            section_metadata={"sections": [{"key": "project"}]},
            token_metadata={"total_tokens": 20},
            rendered_context="retained markdown",
            retain_rendered_context=True,
        )

        assert snapshot.rendered_context == "retained markdown"
        assert snapshot.rendered_context_expires_at is not None

    @pytest.mark.asyncio
    async def test_snapshot_success_failure_and_prune(
        self,
        db_session: AsyncSession,
    ) -> None:
        """快照可标记成功/失败，prune 只清空 full context。"""
        from modules.context.facade import (
            fail_context_snapshot,
            prune_rendered_context,
            succeed_context_snapshot,
        )

        novel_id = "00000000-0000-0000-0000-000000000203"
        succeeded = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="wf-3",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
            rendered_context="debug markdown",
            retain_rendered_context=True,
        )
        failed = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="wf-3",
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )

        done = await succeed_context_snapshot(
            db_session,
            snapshot_id=succeeded.id,
            result_refs=[{"type": "core_entity", "id": "entity-1"}],
        )
        errored = await fail_context_snapshot(
            db_session,
            snapshot_id=failed.id,
            error_kind="timeout",
            error_message="LLM timeout",
        )

        assert done.status == "succeeded"
        assert done.result_refs == [{"type": "core_entity", "id": "entity-1"}]
        assert errored.status == "failed"
        assert errored.error_kind == "timeout"
        assert errored.error_message == "LLM timeout"

        from modules.context.models import ContextSnapshot

        result = await db_session.execute(
            select(ContextSnapshot).where(ContextSnapshot.id == uuid.UUID(done.id))
        )
        retained = result.scalar_one()
        retained.rendered_context_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.flush()

        pruned = await prune_rendered_context(
            db_session,
            novel_id=novel_id,
            retain_latest_full_context_per_project=200,
        )
        assert pruned == 1

        from modules.context.facade import get_context_snapshot

        after_prune = await get_context_snapshot(
            db_session,
            novel_id=novel_id,
            snapshot_id=done.id,
        )
        assert after_prune.rendered_context is None
        assert after_prune.result_refs == [{"type": "core_entity", "id": "entity-1"}]
        assert after_prune.prompt_name == "scene_entity_extraction"


class TestContextSceneIsolation:
    """Context scene-centric loaders must respect novel_id isolation."""

    @pytest.mark.asyncio
    async def test_scene_loader_ignores_scene_from_another_novel(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.context.services.loaders.scene_loader import SceneLoader
        from modules.outline.repositories import SceneRepository
        from modules.outline.schemas import SceneCreate

        owner_novel = str(uuid.uuid4())
        other_novel = str(uuid.uuid4())
        other_scene = await SceneRepository().create(
            db_session,
            uuid.UUID(other_novel),
            SceneCreate(
                scene_index=0,
                title="Other novel scene",
                must_not_happen="不能泄露另一个项目的设定",
            ),
        )
        bundle = StructureContextBundle(
            novel_id=owner_novel,
            task="生成当前场景",
            scope="scene",
        )

        await SceneLoader().load(
            db_session,
            CompileOptions(
                novel_id=owner_novel,
                task="生成当前场景",
                scope="scene",
                scene_id=str(other_scene.id),
            ),
            bundle,
        )

        assert bundle.scene is None
        assert any(str(other_scene.id) in warning for warning in bundle.warnings)

    @pytest.mark.asyncio
    async def test_constraint_engine_ignores_scene_from_another_novel(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.context.services.constraint_engine import ConstraintEngine
        from modules.outline.repositories import SceneRepository
        from modules.outline.schemas import SceneCreate

        owner_novel = str(uuid.uuid4())
        other_scene = await SceneRepository().create(
            db_session,
            uuid.uuid4(),
            SceneCreate(
                scene_index=0,
                title="Other novel scene",
                must_not_happen="不能泄露另一个项目的硬约束",
            ),
        )

        sections = await ConstraintEngine()._scene_constraints(
            db_session,
            owner_novel,
            scene_id=str(other_scene.id),
        )

        assert sections == []

    @pytest.mark.asyncio
    async def test_snapshot_api_isolated_by_novel_id(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """只读 API 必须按 novel_id 隔离。"""

        owner_novel = "00000000-0000-0000-0000-000000000204"
        other_novel = "00000000-0000-0000-0000-000000000205"
        created = await _open_snapshot(
            db_session,
            owner_novel,
            workflow_id="wf-api",
            task_id="task-api",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )
        await db_session.commit()

        list_response = await async_client.get(
            "/api/context/snapshots",
            params={"novel_id": owner_novel, "workflow_id": "wf-api"},
        )
        assert list_response.status_code == 200, list_response.text
        assert [item["id"] for item in list_response.json()["items"]] == [created.id]

        detail_response = await async_client.get(
            f"/api/context/snapshots/{created.id}",
            params={"novel_id": owner_novel},
        )
        assert detail_response.status_code == 200, detail_response.text
        assert detail_response.json()["id"] == created.id

        forbidden = await async_client.get(
            f"/api/context/snapshots/{created.id}",
            params={"novel_id": other_novel},
        )
        assert forbidden.status_code == 404

    @pytest.mark.asyncio
    async def test_snapshot_list_api_is_lightweight_and_bounded(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """列表 API 不返回完整 rendered_context，并支持分页限制。"""

        novel_id = "00000000-0000-0000-0000-000000000206"
        first = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="wf-light",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
            rendered_context="retained markdown",
            retain_rendered_context=True,
        )
        await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="wf-light",
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )
        await db_session.commit()

        list_response = await async_client.get(
            "/api/context/snapshots",
            params={"novel_id": novel_id, "workflow_id": "wf-light", "limit": 1},
        )
        assert list_response.status_code == 200, list_response.text
        list_data = list_response.json()
        assert len(list_data["items"]) == 1
        assert "rendered_context" not in list_data["items"][0]
        assert list_data["items"][0]["has_rendered_context"] is True

        detail_response = await async_client.get(
            f"/api/context/snapshots/{first.id}",
            params={"novel_id": novel_id},
        )
        assert detail_response.status_code == 200, detail_response.text
        assert detail_response.json()["rendered_context"] == "retained markdown"

    @pytest.mark.asyncio
    async def test_snapshot_health_summary_counts_workflow_and_stale_running(
        self,
        db_session: AsyncSession,
    ) -> None:
        """健康摘要按 workflow 聚合状态、phase 和超时 running 计数。"""
        from modules.context.facade import (
            build_snapshot_health_summary,
            fail_context_snapshot,
            succeed_context_snapshot,
        )
        from modules.context.models import ContextSnapshot

        novel_id = "00000000-0000-0000-0000-000000000207"
        workflow_id = "wf-health"
        stale = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id=workflow_id,
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )
        succeeded = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id=workflow_id,
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
            rendered_context="retained",
            retain_rendered_context=True,
        )
        failed = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id=workflow_id,
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )
        await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="other-workflow",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )

        await succeed_context_snapshot(
            db_session,
            snapshot_id=succeeded.id,
            result_refs=[{"type": "plot_thread", "id": "thread-1"}],
        )
        await fail_context_snapshot(
            db_session,
            snapshot_id=failed.id,
            error_kind="parse_empty",
            error_message="no rows",
        )
        result = await db_session.execute(
            select(ContextSnapshot).where(ContextSnapshot.id == uuid.UUID(stale.id))
        )
        stale_record = result.scalar_one()
        stale_record.created_at = datetime.now(UTC) - timedelta(hours=3)
        await db_session.flush()

        summary = await build_snapshot_health_summary(
            db_session,
            novel_id=novel_id,
            workflow_id=workflow_id,
            running_timeout_minutes=120,
        )

        assert summary["novel_id"] == novel_id
        assert summary["workflow_id"] == workflow_id
        assert summary["total_snapshots"] == 3
        assert summary["by_status"] == {
            "running": 1,
            "succeeded": 1,
            "failed": 1,
        }
        assert summary["by_phase"]["entity_extraction"]["running"] == 1
        assert summary["by_phase"]["structure_analysis"]["succeeded"] == 1
        assert summary["stale_running_count"] == 1
        assert summary["retained_rendered_context_count"] == 1
        assert summary["latest_failure"]["error_kind"] == "parse_empty"
        assert "result_refs" not in summary["latest_failure"]

    @pytest.mark.asyncio
    async def test_snapshot_maintenance_dry_run_and_execute(
        self,
        db_session: AsyncSession,
    ) -> None:
        """maintenance 支持 dry-run，并只清理正文不删除 provenance metadata。"""
        from modules.context.facade import (
            get_context_snapshot,
            run_snapshot_maintenance,
        )
        from modules.context.models import ContextSnapshot

        novel_id = "00000000-0000-0000-0000-000000000208"
        workflow_id = "wf-maintenance"
        stale = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id=workflow_id,
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={"scope": "scene"},
            included_asset_ids={"scenes": ["scene-1"]},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )
        retained = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id=workflow_id,
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
            model="test-model",
            compile_options={},
            included_asset_ids={"context_sections": ["project"]},
            context_summary={},
            section_metadata={"sections": [{"key": "project"}]},
            token_metadata={"total_tokens": 30},
            rendered_context="expired rendered context",
            retain_rendered_context=True,
        )
        await _open_snapshot(
            db_session,
            "00000000-0000-0000-0000-000000000209",
            workflow_id=workflow_id,
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
            rendered_context="other project context",
            retain_rendered_context=True,
        )

        result = await db_session.execute(
            select(ContextSnapshot).where(
                ContextSnapshot.id.in_([uuid.UUID(stale.id), uuid.UUID(retained.id)])
            )
        )
        records = {str(record.id): record for record in result.scalars().all()}
        records[stale.id].created_at = datetime.now(UTC) - timedelta(hours=3)
        records[stale.id].result_refs = [{"type": "scene", "id": "scene-1"}]
        records[retained.id].rendered_context_expires_at = datetime.now(UTC) - timedelta(
            minutes=1
        )
        await db_session.flush()

        dry_run = await run_snapshot_maintenance(
            db_session,
            novel_id=novel_id,
            workflow_id=workflow_id,
            dry_run=True,
        )
        assert dry_run["dry_run"] is True
        assert dry_run["stale_running_count"] == 1
        assert dry_run["pruned_rendered_context_count"] == 1
        assert dry_run["would_change_count"] == 2

        stale_after_dry_run = await get_context_snapshot(
            db_session,
            novel_id=novel_id,
            snapshot_id=stale.id,
        )
        retained_after_dry_run = await get_context_snapshot(
            db_session,
            novel_id=novel_id,
            snapshot_id=retained.id,
        )
        assert stale_after_dry_run.status == "running"
        assert retained_after_dry_run.rendered_context == "expired rendered context"

        executed = await run_snapshot_maintenance(
            db_session,
            novel_id=novel_id,
            workflow_id=workflow_id,
            dry_run=False,
        )
        assert executed["dry_run"] is False
        assert executed["stale_running_count"] == 1
        assert executed["pruned_rendered_context_count"] == 1
        assert executed["would_change_count"] == 0

        stale_after_execute = await get_context_snapshot(
            db_session,
            novel_id=novel_id,
            snapshot_id=stale.id,
        )
        retained_after_execute = await get_context_snapshot(
            db_session,
            novel_id=novel_id,
            snapshot_id=retained.id,
        )
        assert stale_after_execute.status == "failed"
        assert stale_after_execute.error_kind == "stale_running"
        assert stale_after_execute.result_refs == [{"type": "scene", "id": "scene-1"}]
        assert retained_after_execute.rendered_context is None
        assert retained_after_execute.rendered_context_expires_at is None
        assert retained_after_execute.included_asset_ids == {
            "context_sections": ["project"]
        }
        assert retained_after_execute.section_metadata == {
            "sections": [{"key": "project"}]
        }

    @pytest.mark.asyncio
    async def test_snapshot_maintenance_api_isolated_by_novel_id(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """maintenance API 只统计和修改请求 novel_id 下的快照。"""
        from modules.context.models import ContextSnapshot

        owner_novel = "00000000-0000-0000-0000-000000000210"
        other_novel = "00000000-0000-0000-0000-000000000211"
        owner = await _open_snapshot(
            db_session,
            owner_novel,
            workflow_id="wf-maint-api",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )
        other = await _open_snapshot(
            db_session,
            other_novel,
            workflow_id="wf-maint-api",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
        )
        result = await db_session.execute(
            select(ContextSnapshot).where(
                ContextSnapshot.id.in_([uuid.UUID(owner.id), uuid.UUID(other.id)])
            )
        )
        for record in result.scalars().all():
            record.created_at = datetime.now(UTC) - timedelta(hours=3)
        await db_session.commit()

        response = await async_client.post(
            "/api/context/snapshots/maintenance",
            json={
                "novel_id": owner_novel,
                "workflow_id": "wf-maint-api",
                "dry_run": False,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["stale_running_count"] == 1
        assert data["snapshot_health_summary"]["total_snapshots"] == 1

        owner_detail = await async_client.get(
            f"/api/context/snapshots/{owner.id}",
            params={"novel_id": owner_novel},
        )
        other_detail = await async_client.get(
            f"/api/context/snapshots/{other.id}",
            params={"novel_id": other_novel},
        )
        assert owner_detail.json()["status"] == "failed"
        assert owner_detail.json()["error_kind"] == "stale_running"
        assert other_detail.json()["status"] == "running"

    @pytest.mark.asyncio
    async def test_prune_retention_cap_is_project_wide_when_workflow_filtered(
        self,
        db_session: AsyncSession,
    ) -> None:
        """workflow 过滤不能让每个 workflow 各自保留一批 full context。"""
        from modules.context.facade import (
            get_context_snapshot,
            prune_rendered_context,
        )
        from modules.context.models import ContextSnapshot

        novel_id = "00000000-0000-0000-0000-000000000212"
        newest_other_workflow = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="wf-b",
            phase="entity_extraction",
            operation="scene_entity_extraction",
            prompt_name="scene_entity_extraction",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
            rendered_context="newest other workflow",
            retain_rendered_context=True,
        )
        older_target_workflow = await _open_snapshot(
            db_session,
            novel_id,
            workflow_id="wf-a",
            phase="structure_analysis",
            operation="plot_structure_generation",
            prompt_name="structure_plot",
            model="test-model",
            compile_options={},
            included_asset_ids={},
            context_summary={},
            section_metadata={},
            token_metadata={},
            rendered_context="older target workflow",
            retain_rendered_context=True,
        )

        result = await db_session.execute(
            select(ContextSnapshot).where(
                ContextSnapshot.id.in_(
                    [
                        uuid.UUID(newest_other_workflow.id),
                        uuid.UUID(older_target_workflow.id),
                    ]
                )
            )
        )
        records = {str(record.id): record for record in result.scalars().all()}
        records[newest_other_workflow.id].created_at = datetime.now(UTC)
        records[older_target_workflow.id].created_at = datetime.now(UTC) - timedelta(
            minutes=20
        )
        await db_session.flush()

        pruned = await prune_rendered_context(
            db_session,
            novel_id=novel_id,
            workflow_id="wf-a",
            retain_latest_full_context_per_project=1,
        )

        assert pruned == 1
        assert (
            await get_context_snapshot(
                db_session,
                novel_id=novel_id,
                snapshot_id=newest_other_workflow.id,
            )
        ).rendered_context == "newest other workflow"
        assert (
            await get_context_snapshot(
                db_session,
                novel_id=novel_id,
                snapshot_id=older_target_workflow.id,
            )
        ).rendered_context is None


class TestContextConfirmation:
    """测试手动 AI 操作前的上下文确认记录。"""

    @pytest.mark.asyncio
    async def test_compile_response_includes_section_metadata(
        self,
        async_client: AsyncClient,
    ) -> None:
        """编译响应应返回可审查的参考资料 section 元数据。"""
        novel_id = "00000000-0000-0000-0000-000000000091"

        response = await async_client.post(
            "/api/context/compile",
            json={
                "novel_id": novel_id,
                "task": "生成第 1 章正文草稿",
                "scope": "chapter",
                "chapter_index": 1,
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        objective = next(
            section
            for section in data["sections"]
            if section["key"] == "writing_objective"
        )
        assert objective["title"] == "本次任务"
        assert objective["status"] == "system"
        assert objective["activation_reason"] == "用户当前发起的 AI 操作"
        assert objective["can_exclude"] is False
        assert objective["excluded"] is False
        assert objective["preview"] == "生成第 1 章正文草稿"
        assert objective["sources"] == [
            {
                "type": "task",
                "id": "writing_objective",
                "label": "生成第 1 章正文草稿",
                "status": "system",
            }
        ]
        assert data["budget_events"] == []

    @pytest.mark.asyncio
    async def test_confirm_response_includes_review_sections(
        self,
        async_client: AsyncClient,
    ) -> None:
        """确认响应应返回审查 sections 和预算事件，但不返回 raw prompt。"""
        novel_id = "00000000-0000-0000-0000-000000000092"

        response = await async_client.post(
            "/api/context/confirm",
            json={
                "novel_id": novel_id,
                "action": "writing.generate",
                "task": "生成第 1 章正文草稿",
                "scope": "chapter",
                "chapter_index": 1,
            },
        )

        assert response.status_code == 201, response.text
        data = response.json()
        assert "rendered_context" not in data
        assert data["sections"]
        assert data["sections"][0]["key"] == "writing_objective"
        assert data["sections"][0]["title"] == "本次任务"
        assert data["budget_events"] == []
        assert data["selected_asset_ids"]["context_sections"] == [
            section["key"] for section in data["sections"]
        ]

    @pytest.mark.asyncio
    async def test_excluding_context_section_removes_non_p0_section(
        self,
        async_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """context_sections 排除项应移除可排除 section。"""
        from dataclasses import dataclass, field

        @dataclass
        class _FakeRagResult:
            chunks: list = field(default_factory=list)
            warnings: list[str] = field(default_factory=list)
            degraded: bool = False

        async def _fake_retrieve(*args, **kwargs):
            return _FakeRagResult(
                chunks=[
                    {
                        "chunk_id": "chunk-1",
                        "text": "旧城门在暴雨夜关闭。",
                        "source_type": "draft",
                    }
                ]
            )

        monkeypatch.setattr("modules.rag.facade.retrieve", _fake_retrieve)
        novel_id = "00000000-0000-0000-0000-000000000093"

        response = await async_client.post(
            "/api/context/confirm",
            json={
                "novel_id": novel_id,
                "action": "writing.generate",
                "task": "生成第 1 章正文草稿",
                "scope": "full",
                "excluded_asset_ids": {"context_sections": ["retrieval_evidence_packs"]},
            },
        )

        assert response.status_code == 201, response.text
        data = response.json()
        section_keys = [section["key"] for section in data["sections"]]
        assert "retrieval_evidence_packs" not in section_keys
        assert (
            "retrieval_evidence_packs"
            not in data["selected_asset_ids"]["context_sections"]
        )
        assert data["excluded_asset_ids"] == {
            "context_sections": ["retrieval_evidence_packs"]
        }

    @pytest.mark.asyncio
    async def test_excluding_p0_section_is_ignored_with_warning(
        self,
        async_client: AsyncClient,
    ) -> None:
        """P0 核心 section 不可排除，并应返回可见 warning。"""
        novel_id = "00000000-0000-0000-0000-000000000094"

        response = await async_client.post(
            "/api/context/compile",
            json={
                "novel_id": novel_id,
                "task": "生成第 1 章正文草稿",
                "scope": "chapter",
                "chapter_index": 1,
                "excluded_asset_ids": {
                    "context_sections": ["writing_objective", "hard_constraints"]
                },
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        section_keys = [section["key"] for section in data["sections"]]
        assert "writing_objective" in section_keys
        hard_constraints = next(
            section
            for section in data["sections"]
            if section["key"] == "hard_constraints"
        )
        assert hard_constraints["can_exclude"] is False
        assert "核心参考资料不可排除：writing_objective" in "\n".join(data["warnings"])
        assert "核心参考资料不可排除：hard_constraints" in "\n".join(data["warnings"])

    def test_budget_events_record_eviction_and_truncation(self) -> None:
        """预算裁剪应记录已移除和已裁剪 section 的事件。"""
        from modules.context.services.compiled_context import (
            CompiledContext,
            ContextSection,
            Tier,
        )

        ctx = CompiledContext(
            sections=[
                ContextSection(
                    key="writing_objective",
                    tier=Tier.P0,
                    content="目标",
                    token_count=1,
                    title="本次任务",
                    can_exclude=False,
                ),
                ContextSection(
                    key="open_narrative_obligations",
                    tier=Tier.P2,
                    content="\n".join(f"剧情线 {i}" for i in range(80)),
                    token_count=200,
                    title="剧情线与未完成义务",
                    truncatable_per_item=True,
                ),
                ContextSection(
                    key="style_assets",
                    tier=Tier.P3,
                    content="风格设定" * 80,
                    token_count=120,
                    title="项目风格与基础设定",
                ),
            ],
            total_tokens=321,
            budget_tokens=60,
        )

        result = ctx.enforce_budget()

        assert "style_assets" in result.evicted_keys
        assert "open_narrative_obligations" in result.truncated_keys
        assert [event.event_type for event in result.budget_events] == [
            "evicted",
            "truncated",
        ]
        assert result.budget_events[0].section_key == "style_assets"
        assert result.budget_events[0].before_tokens == 120
        assert result.budget_events[0].after_tokens == 0
        assert result.budget_events[1].section_key == "open_narrative_obligations"
        assert result.budget_events[1].before_tokens == 200
        assert result.budget_events[1].after_tokens < 200

    @pytest.mark.asyncio
    async def test_confirm_context_api_creates_summary_without_rendered_context(
        self,
        async_client: AsyncClient,
    ) -> None:
        """POST /api/context/confirm 应重新编译并保存确认摘要。"""
        novel_id = "00000000-0000-0000-0000-000000000101"

        response = await async_client.post(
            "/api/context/confirm",
            json={
                "novel_id": novel_id,
                "action": "writing.generate",
                "task": "生成第 1 章正文草稿",
                "scope": "chapter",
                "chapter_index": 1,
                "context_mode": "canonical",
                "include_pending_objects": False,
                "excluded_asset_ids": {"world_entities": ["entity-1"]},
                "user_note": "本次注意保持克制语气",
            },
        )

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["id"]
        assert data["novel_id"] == novel_id
        assert data["action"] == "writing.generate"
        assert data["context_mode"] == "canonical"
        assert data["include_pending_objects"] is False
        assert data["excluded_asset_ids"] == {"world_entities": ["entity-1"]}
        assert data["user_note"] == "本次注意保持克制语气"
        assert data["selected_asset_ids"]
        assert "rendered_context" not in data

    @pytest.mark.asyncio
    async def test_facade_requires_matching_confirmation(
        self,
        db_session: AsyncSession,
    ) -> None:
        """require_confirmation 应校验 novel_id 和 action。"""
        from modules.context.facade import confirm_context, require_confirmation

        novel_id = "00000000-0000-0000-0000-000000000102"
        created = await confirm_context(
            db_session,
            novel_id=novel_id,
            action="outline.generate",
            task="生成剧情结构",
            scope="chapter",
            chapter_index=1,
        )

        ok = await require_confirmation(
            db_session,
            novel_id=novel_id,
            action="outline.generate",
            confirmation_id=created.id,
        )
        assert ok.id == created.id

        with pytest.raises(ValueError, match="action"):
            await require_confirmation(
                db_session,
                novel_id=novel_id,
                action="writing.generate",
                confirmation_id=created.id,
            )

        with pytest.raises(ValueError, match="novel_id"):
            await require_confirmation(
                db_session,
                novel_id="00000000-0000-0000-0000-000000000103",
                action="outline.generate",
                confirmation_id=created.id,
            )

    @pytest.mark.asyncio
    async def test_confirmation_result_refs_and_stale_marking(
        self,
        db_session: AsyncSession,
    ) -> None:
        """确认记录可追踪结果引用，并在相关资产变化时标记为 stale。"""
        from modules.context.facade import (
            attach_result_ref,
            confirm_context,
            mark_asset_context_changed,
            require_confirmation,
        )

        novel_id = "00000000-0000-0000-0000-000000000104"
        created = await confirm_context(
            db_session,
            novel_id=novel_id,
            action="world.entities.extract",
            task="补抽世界对象",
            scope="world",
            context_mode="working",
            include_pending_objects=True,
        )

        await attach_result_ref(
            db_session,
            confirmation_id=created.id,
            result_type="task",
            result_id="task-1",
            status="running",
        )
        with_ref = await require_confirmation(
            db_session,
            novel_id=novel_id,
            action="world.entities.extract",
            confirmation_id=created.id,
        )
        assert with_ref.result_refs == [{"type": "task", "id": "task-1"}]
        assert with_ref.result_status == "running"

        changed = await mark_asset_context_changed(
            db_session,
            novel_id=novel_id,
            asset_type="world_entities",
            asset_id="task-1",
            reason="ignored",
        )
        assert changed == 1

        stale = await require_confirmation(
            db_session,
            novel_id=novel_id,
            action="world.entities.extract",
            confirmation_id=created.id,
        )
        assert stale.result_status == "stale_context"
        assert stale.stale_reasons == ["ignored"]

        from modules.context.facade import require_fresh_confirmation

        with pytest.raises(ValueError, match="stale_context"):
            await require_fresh_confirmation(
                db_session,
                novel_id=novel_id,
                action="world.entities.extract",
                confirmation_id=created.id,
            )

    @pytest.mark.asyncio
    async def test_attach_result_refs_batches_and_deduplicates(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.context.facade import (
            attach_result_ref,
            attach_result_refs,
            confirm_context,
            require_confirmation,
        )

        novel_id = "00000000-0000-0000-0000-000000000114"
        created = await confirm_context(
            db_session,
            novel_id=novel_id,
            action="outline.generate",
            task="生成 Scene",
            scope="chapter",
        )
        await attach_result_ref(
            db_session,
            confirmation_id=created.id,
            result_type="outline_scene",
            result_id="scene-1",
            status="running",
        )

        updated = await attach_result_refs(
            db_session,
            confirmation_id=created.id,
            result_refs=[
                {"type": "outline_scene", "id": "scene-1"},
                {"type": "outline_scene", "id": "scene-2"},
                {"type": "outline_scene", "id": "scene-3"},
            ],
            status="done",
        )

        assert updated.result_refs == [
            {"type": "outline_scene", "id": "scene-1"},
            {"type": "outline_scene", "id": "scene-2"},
            {"type": "outline_scene", "id": "scene-3"},
        ]
        assert updated.result_status == "done"

        with_ref = await require_confirmation(
            db_session,
            novel_id=novel_id,
            action="outline.generate",
            confirmation_id=created.id,
        )
        assert with_ref.result_refs == updated.result_refs

    @pytest.mark.asyncio
    async def test_attach_result_refs_keeps_last_position_for_duplicates(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.context.facade import (
            attach_result_ref,
            attach_result_refs,
            confirm_context,
        )

        created = await confirm_context(
            db_session,
            novel_id="00000000-0000-0000-0000-000000000115",
            action="outline.generate",
            task="生成 Scene",
            scope="chapter",
        )
        await attach_result_ref(
            db_session,
            confirmation_id=created.id,
            result_type="outline_scene",
            result_id="scene-1",
            status="running",
        )
        await attach_result_ref(
            db_session,
            confirmation_id=created.id,
            result_type="outline_scene",
            result_id="scene-3",
            status="running",
        )

        updated = await attach_result_refs(
            db_session,
            confirmation_id=created.id,
            result_refs=[
                {"type": "outline_scene", "id": "scene-2"},
                {"type": "outline_scene", "id": "scene-3"},
                {"type": "outline_scene", "id": "scene-2"},
            ],
            status="done",
        )

        assert updated.result_refs == [
            {"type": "outline_scene", "id": "scene-1"},
            {"type": "outline_scene", "id": "scene-3"},
            {"type": "outline_scene", "id": "scene-2"},
        ]

    @pytest.mark.asyncio
    async def test_mark_asset_context_changed_updates_records_in_one_batch(
        self,
        db_session: AsyncSession,
    ) -> None:
        """批量标记失效确认记录时不应逐条 flush。"""
        from modules.context.services.confirmation_service import (
            ContextConfirmationService,
        )

        records = [
            SimpleNamespace(stale_reasons=[]),
            SimpleNamespace(stale_reasons=["older_reason"]),
        ]
        batch_calls: list[tuple[list[object], str, list[list[str]]]] = []

        class FakeRepository:
            async def list_by_asset_ref(self, db, *, novel_id, asset_type, asset_id):
                return records

            async def update_tracking(self, *args, **kwargs):
                raise AssertionError("should not update stale records one by one")

            async def update_tracking_many(self, db, updates, *, result_status):
                batch_calls.append(
                    (
                        [record for record, _reasons in updates],
                        result_status,
                        [reasons for _record, reasons in updates],
                    )
                )
                return len(updates)

        changed = await ContextConfirmationService(
            repository=FakeRepository(),  # type: ignore[arg-type]
        ).mark_asset_context_changed(
            db_session,
            novel_id="00000000-0000-0000-0000-000000000104",
            asset_type="world_entities",
            asset_id="entity-1",
            reason="candidate_promoted",
        )

        assert changed == 2
        assert batch_calls == [
            (
                records,
                "needs_review",
                [["candidate_promoted"], ["older_reason", "candidate_promoted"]],
            )
        ]

    @pytest.mark.asyncio
    async def test_list_by_asset_ref_ignores_malformed_result_refs(
        self,
        db_session: AsyncSession,
    ) -> None:
        from modules.context.repositories import ContextConfirmationRepository

        repo = ContextConfirmationRepository()
        novel_id = uuid.UUID("00000000-0000-0000-0000-000000000116")
        selected = await repo.create(
            db_session,
            novel_id=novel_id,
            action="outline.generate",
            task="生成 Scene",
            scope="chapter",
            context_mode="canonical",
            include_pending_objects=False,
            excluded_asset_ids={},
            selected_asset_ids={"world_entities": ["entity-1", 123]},
            user_note=None,
            compile_options={},
            warnings=[],
        )
        result_ref = await repo.create(
            db_session,
            novel_id=novel_id,
            action="writing.generate",
            task="写作",
            scope="chapter",
            context_mode="canonical",
            include_pending_objects=False,
            excluded_asset_ids={},
            selected_asset_ids={},
            user_note=None,
            compile_options={},
            warnings=[],
        )
        result_ref.result_refs = [
            "legacy-bad-ref",
            {"type": "task"},
            {"type": "core_entity", "id": "entity-1"},
        ]
        unmatched = await repo.create(
            db_session,
            novel_id=novel_id,
            action="rag.index",
            task="索引",
            scope="chapter",
            context_mode="canonical",
            include_pending_objects=False,
            excluded_asset_ids={},
            selected_asset_ids={"world_entities": ["entity-2"]},
            user_note=None,
            compile_options={},
            warnings=[],
        )
        await db_session.flush()

        matched = await repo.list_by_asset_ref(
            db_session,
            novel_id=novel_id,
            asset_type="world_entities",
            asset_id="entity-1",
        )

        assert [record.id for record in matched] == [selected.id, result_ref.id]
        assert unmatched.id not in {record.id for record in matched}


# ============================================================
# 基本导入测试
# ============================================================


class TestImports:
    """验证模块可正常导入"""

    def test_import_contracts(self) -> None:
        from modules.context.contracts import (
            AUTHOR_ONLY_WARNING,
            StructureContextBundle,
        )

        assert StructureContextBundle is not None
        assert AUTHOR_ONLY_WARNING
        assert isinstance(CONTEXT_BUDGET, dict)

    def test_import_schemas(self) -> None:
        from modules.context.schemas import (
            BudgetUsedItem,
            ContextCompileRequest,
            ContextRenderRequest,
            ContextRenderResponse,
            ContextSectionItem,
            ContextTierCompileResponse,
        )

        assert ContextCompileRequest is not None
        assert ContextRenderRequest is not None
        assert ContextRenderResponse is not None
        assert ContextSectionItem is not None
        assert ContextTierCompileResponse is not None
        assert BudgetUsedItem is not None

    def test_import_facade(self) -> None:
        from modules.context.facade import (
            compile_structure_context,
            render_context_markdown,
        )

        assert compile_structure_context is not None
        assert render_context_markdown is not None


# ============================================================
# StructureContextBundle 基础测试
# ============================================================


class TestStructureContextBundle:
    """测试 StructureContextBundle 数据结构"""

    def test_create_empty_bundle(self) -> None:
        """验证可以创建空 bundle"""
        bundle = StructureContextBundle(
            novel_id="test-novel-id",
            task="测试任务",
            scope="project",
        )
        assert bundle.novel_id == "test-novel-id"
        assert bundle.task == "测试任务"
        assert bundle.scope == "project"
        assert bundle.chapter_index is None
        assert bundle.world_entities == []
        assert bundle.characters == []
        assert bundle.warnings == []
        assert bundle.geo_filtered is False

    def test_create_full_bundle(self) -> None:
        """验证完整 bundle 创建"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="生成章节卡",
            scope="chapter",
            chapter_index=5,
            arc_id="arc-1",
            project={"title": "测试小说"},
            world_entities=[{"name": "王国", "entity_type": "location"}],
            characters=[{"name": "主角"}],
            geo_locations=[{"location": {"name": "王城"}}],
            memory_records=[{"summary": "主角出发了", "memory_type": "event"}],
            timeline_events=[{"title": "启程", "summary": "主角离开家乡"}],
            plot_threads=[{"name": "主线"}],
            outline_arc={"title": "第一卷"},
            chapter_card={"chapter_index": 5, "chapter_goal": "主角到达王城"},
            rag_chunks=[{"text": "王城描述", "source_type": "world_entity"}],
            reveal_mode="author_safe",
            budget_used={"core_entities": 3, "characters": 2},
            warnings=["测试警告"],
        )
        assert len(bundle.world_entities) == 1
        assert len(bundle.characters) == 1
        assert bundle.chapter_index == 5


# ============================================================
# Context Compiler 核心测试
# ============================================================


class TestContextCompiler:
    """测试 Context Compiler 核心逻辑"""

    def test_rag_section_metadata_keeps_stable_source_ref(self) -> None:
        from modules.context.services.context_compiler import ContextCompiler

        source_ref = {
            "draft_id": "00000000-0000-0000-0000-000000000123",
            "chapter_index": 3,
            "version_number": 2,
            "content_mode": "working",
            "start_offset": 10,
            "end_offset": 20,
            "source_hash": "a" * 64,
            "range_hash": "b" * 64,
        }
        bundle = StructureContextBundle(
            novel_id="00000000-0000-0000-0000-000000000399",
            task="稳定来源",
            scope="full",
            rag_chunks=[
                {
                    "id": "chunk-1",
                    "source_type": "chapter_text",
                    "text": "已从 writing 回读的原文",
                    "source_ref": source_ref,
                }
            ],
        )
        options = CompileOptions(
            novel_id=bundle.novel_id,
            task=bundle.task,
            scope=bundle.scope,
            content_mode="working",
        )

        sections = ContextCompiler()._build_sections(bundle, options)
        section = next(
            item for item in sections if item.key == "retrieval_evidence_packs"
        )

        assert section.sources[0]["source_ref"] == source_ref
        assert section.sources[0]["source_hash"] == "a" * 64

    @pytest.mark.asyncio
    async def test_rag_loader_propagates_retrieval_warnings(
        self,
        db_session: AsyncSession,
    ) -> None:
        """RAG 检索降级应进入 Context Compiler warnings。"""
        from dataclasses import dataclass, field

        from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader

        @dataclass
        class _FakeRagResult:
            chunks: list = field(default_factory=list)
            warnings: list[str] = field(default_factory=list)
            degraded: bool = False

        async def _fake_retrieve(*args, **kwargs):
            return _FakeRagResult(
                chunks=[],
                warnings=["embedding 生成失败，本次检索已降级"],
                degraded=True,
            )

        bundle = StructureContextBundle(
            novel_id="00000000-0000-0000-0000-000000000399",
            task="测试 RAG warning",
            scope="full",
        )
        options = CompileOptions(
            novel_id=bundle.novel_id,
            task=bundle.task,
            scope=bundle.scope,
        )

        await RagChunksLoader(retrieve_fn=_fake_retrieve).load(
            db_session,
            options,
            bundle,
        )

        assert "embedding 生成失败，本次检索已降级" in bundle.warnings
        assert "RAG 检索降级" in bundle.warnings

    @pytest.mark.asyncio
    async def test_rag_loader_passes_visible_until_chapter(
        self,
        db_session: AsyncSession,
    ) -> None:
        from dataclasses import dataclass, field

        from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader

        calls: list[dict] = []

        @dataclass
        class _FakeRagResult:
            chunks: list = field(default_factory=list)
            warnings: list[str] = field(default_factory=list)
            degraded: bool = False

        async def _fake_retrieve(*args, **kwargs):
            calls.append(kwargs)
            return _FakeRagResult()

        bundle = StructureContextBundle(
            novel_id="00000000-0000-0000-0000-000000000398",
            task="测试 RAG 读者进度",
            scope="chapter",
        )
        options = CompileOptions(
            novel_id=bundle.novel_id,
            task=bundle.task,
            scope=bundle.scope,
            chapter_index=3,
        )

        await RagChunksLoader(retrieve_fn=_fake_retrieve).load(
            db_session,
            options,
            bundle,
        )

        assert calls[0]["chapter_index"] == 3
        assert calls[0]["reference_chapter_index"] == 3
        assert calls[0]["visible_until_chapter"] == 3

        calls.clear()
        options.visible_until_chapter = 5
        await RagChunksLoader(retrieve_fn=_fake_retrieve).load(
            db_session,
            options,
            bundle,
        )
        assert calls[0]["visible_until_chapter"] == 5

    @pytest.mark.asyncio
    async def test_compile_empty_db_project_scope(
        self,
        db_session: AsyncSession,
    ) -> None:
        """空数据库中 project scope 应优雅降级"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000001",
            task="测试",
            scope="project",
        )
        assert bundle.novel_id == "00000000-0000-0000-0000-000000000001"
        assert bundle.scope == "project"
        assert bundle.project is None
        # 不应崩溃

    @pytest.mark.asyncio
    async def test_compile_empty_db_world_scope(
        self,
        db_session: AsyncSession,
    ) -> None:
        """空数据库中 world scope 应返回空列表"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000002",
            task="测试世界",
            scope="world",
        )
        assert bundle.scope == "world"
        assert bundle.world_entities == []

    @pytest.mark.asyncio
    async def test_compile_empty_db_full_scope(
        self,
        db_session: AsyncSession,
    ) -> None:
        """空数据库中 full scope 不应崩溃，所有数据应为空"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000003",
            task="完整测试",
            scope="full",
        )
        assert bundle.scope == "full"
        assert bundle.project is None
        assert bundle.world_entities == []
        assert bundle.characters == []
        assert bundle.geo_locations == []
        # memory_records 现在是全景 dict（启用后），空列表兜底也兼容
        assert isinstance(bundle.memory_records, (list, dict))
        assert bundle.timeline_events == []
        assert bundle.plot_threads == []
        assert bundle.outline_arc is None
        assert bundle.chapter_card is None
        assert bundle.rag_chunks == []

    @pytest.mark.asyncio
    async def test_compile_chapter_scope_no_chapter_index(
        self,
        db_session: AsyncSession,
    ) -> None:
        """chapter scope 不提供 chapter_index 应仍能工作"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000004",
            task="生成章节卡",
            scope="chapter",
        )
        assert bundle.scope == "chapter"
        assert bundle.chapter_index is None
        assert bundle.chapter_card is None
        # 不应崩溃

    @pytest.mark.asyncio
    async def test_compile_with_entity_ids(
        self,
        db_session: AsyncSession,
    ) -> None:
        """指定 entity_ids 应正确传递"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000005",
            task="测试",
            scope="world",
            entity_ids=["e1", "e2", "e3"],
        )
        assert bundle.scope == "world"
        # 数据库为空，所以不会返回数据
        # 但重要的是不崩溃

    @pytest.mark.asyncio
    async def test_compile_with_character_ids(
        self,
        db_session: AsyncSession,
    ) -> None:
        """指定 character_ids 应正确传递"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000006",
            task="测试人物",
            scope="world_character",
            character_ids=["c1", "c2"],
        )
        assert bundle.scope == "world_character"

    @pytest.mark.asyncio
    async def test_compile_nonexistent_project(
        self,
        db_session: AsyncSession,
    ) -> None:
        """项目不存在时应有警告"""
        bundle = await compile_structure_context(
            db=db_session,
            novel_id="00000000-0000-0000-0000-000000000007",
            task="测试",
            scope="project",
        )
        # 项目不存在时 project 应为 None
        assert bundle.project is None

    @pytest.mark.asyncio
    async def test_compile_character_false_belief_hides_hidden_truth(
        self,
        db_session: AsyncSession,
    ) -> None:
        """RED: character 视角 false_belief 应显示误解，不暴露 hidden_truth"""
        from modules.project.models import Project
        from modules.world.models import Character, CharacterKnowledge, CoreEntity

        nid = uuid.uuid4()
        novel_id = str(nid)
        db_session.add(
            Project(
                id=nid,
                title="测试小说",
                genre="奇幻",
                language="zh",
            )
        )

        # POV 人物
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=nid,
                entity_type="character",
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            Character(
                entity_id=char_id,
                novel_id=nid,
                name="POV角色",
                status="canonical",
            )
        )

        # 目标实体：带 hidden_truth
        target_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=target_id,
                novel_id=nid,
                entity_type="faction",
                name="暗影组织",
                summary="一个神秘组织。",
                hidden_truth="真实隐藏真相：首领是国王。",
                status="canonical",
                importance_level="core",
            )
        )

        # 人物知识边界：false_belief
        db_session.add(
            CharacterKnowledge(
                id=uuid.uuid4(),
                novel_id=nid,
                character_id=char_id,
                target_type="entity",
                target_id=target_id,
                knowledge_level="false_belief",
                known_content="一个神秘组织。",
                misconception="错误认知：暗影组织是正义的。",
                source_chapter_index=1,
            )
        )
        await db_session.flush()

        bundle = await compile_structure_context(
            db=db_session,
            novel_id=novel_id,
            task="生成章节",
            scope="world_character",
            character_ids=[str(char_id)],
            reveal_mode="character",
            viewpoint_character_id=str(char_id),
            visible_until_chapter=2,
        )
        rendered = render_context_markdown(bundle)

        assert "错误认知" in rendered
        assert "真实隐藏真相" not in rendered

        # 强断言：summary 被 misconception 替换，hidden_truth 字段被移除
        assert bundle.world_entities, "应保留至少一个世界对象"
        assert bundle.world_entities[0]["summary"] == "错误认知：暗影组织是正义的。"
        assert "hidden_truth" not in bundle.world_entities[0]

    @pytest.mark.asyncio
    async def test_compile_author_safe_preserves_entities_without_knowledge(
        self,
        db_session: AsyncSession,
    ) -> None:
        """RED: 非 character 模式下，无 knowledge 记录的世界对象应被保留"""
        from modules.project.models import Project
        from modules.world.models import Character, CoreEntity

        nid = uuid.uuid4()
        novel_id = str(nid)
        db_session.add(
            Project(
                id=nid,
                title="测试小说",
                genre="奇幻",
                language="zh",
            )
        )

        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=nid,
                entity_type="character",
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            Character(
                entity_id=char_id,
                novel_id=nid,
                name="POV角色",
                status="canonical",
            )
        )

        target_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=target_id,
                novel_id=nid,
                entity_type="faction",
                name="暗影组织",
                summary="一个神秘组织。",
                hidden_truth="真实隐藏真相：首领是国王。",
                status="canonical",
                importance_level="core",
            )
        )
        await db_session.flush()

        bundle = await compile_structure_context(
            db=db_session,
            novel_id=novel_id,
            task="生成章节",
            scope="world_character",
            character_ids=[str(char_id)],
            reveal_mode="author_safe",
        )

        faction_entities = [
            e for e in bundle.world_entities if e.get("entity_type") == "faction"
        ]
        assert len(faction_entities) == 1, (
            "无 knowledge 记录的 faction 实体在 author_safe 模式下应被保留"
        )
        assert faction_entities[0]["name"] == "暗影组织"
        assert faction_entities[0]["summary"] == "一个神秘组织。"

    @pytest.mark.asyncio
    async def test_compile_character_reveal_allows_public_info_without_knowledge(
        self,
        db_session: AsyncSession,
    ) -> None:
        """character 视角下，无 knowledge 记录不等同 unknown，只保留公开最小视图。"""
        from modules.project.models import Project
        from modules.world.models import Character, CoreEntity

        nid = uuid.uuid4()
        novel_id = str(nid)
        db_session.add(
            Project(
                id=nid,
                title="测试小说",
                genre="奇幻",
                language="zh",
            )
        )

        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=nid,
                entity_type="character",
                name="POV角色",
                status="canonical",
            )
        )
        db_session.add(
            Character(
                entity_id=char_id,
                novel_id=nid,
                name="POV角色",
                status="canonical",
            )
        )

        target_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=target_id,
                novel_id=nid,
                entity_type="faction",
                name="暗影组织",
                summary="作者摘要：这个组织由国王秘密操纵。",
                public_info="公开信息：城中传闻有暗影组织活动。",
                hidden_truth="真实隐藏真相：首领是国王。",
                status="canonical",
                importance_level="core",
            )
        )
        await db_session.flush()

        bundle = await compile_structure_context(
            db=db_session,
            novel_id=novel_id,
            task="生成章节",
            scope="world_character",
            character_ids=[str(char_id)],
            reveal_mode="character",
            viewpoint_character_id=str(char_id),
            visible_until_chapter=2,
        )

        faction_entities = [
            e for e in bundle.world_entities if e.get("entity_type") == "faction"
        ]
        assert len(faction_entities) == 1
        assert faction_entities[0]["public_info"] == "公开信息：城中传闻有暗影组织活动。"
        assert faction_entities[0]["summary"] == "公开信息：城中传闻有暗影组织活动。"
        assert faction_entities[0]["knowledge_level"] == "public_default"
        assert "hidden_truth" not in faction_entities[0]
        assert "国王秘密操纵" not in str(faction_entities[0])

    def test_character_reveal_sections_split_role_and_director_context(self) -> None:
        """character reveal 渲染角色可见面，不重复旧 scene_blueprint/pov_knowledge。"""
        from modules.context.markdown_renderer import render_compiled_context
        from modules.context.services.compiled_context import CompiledContext
        from modules.context.services.context_compiler import ContextCompiler

        scene_id = str(uuid.uuid4())
        char_id = str(uuid.uuid4())
        options = CompileOptions(
            novel_id=str(uuid.uuid4()),
            task="生成角色视角草稿",
            scope="chapter",
            chapter_index=2,
            scene_id=scene_id,
            character_ids=[char_id],
            reveal_mode="character",
            viewpoint_character_id=char_id,
        )
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            chapter_index=2,
            reveal_mode="character",
            viewpoint_character_id=char_id,
            characters=[
                {
                    "character_id": char_id,
                    "name": "秦岚",
                    "role": "调查员",
                    "current_goal": "确认警报来源",
                }
            ],
            world_entities=[
                {
                    "entity_id": "entity-public",
                    "entity_type": "faction",
                    "name": "暗影组织",
                    "public_info": "公开信息：城中传闻有暗影组织活动。",
                    "summary": "作者摘要：国王秘密操纵暗影组织。",
                    "hidden_truth": "真实隐藏真相：首领是国王。",
                    "knowledge_level": "public_default",
                },
                {
                    "entity_id": "relation-secret",
                    "entity_type": "relation",
                    "name": "秘密同盟",
                    "description": "隐藏关系描述：秦岚暗中背叛林澈。",
                },
            ],
            scene={
                "scene_id": scene_id,
                "title": "主控室警报",
                "scene_index": 3,
                "pov_character_id": char_id,
                "goal": "作者目标：让秦岚发现线索。",
                "core_conflict": "作者冲突：林澈试图隐瞒。",
                "must_happen": "必须发生：发现林澈撒谎。",
                "must_not_happen": "不得发生：直接揭露凶手。",
                "atmosphere": "警报声刺耳。",
            },
            rag_chunks=[
                {
                    "chunk_id": "rag-a",
                    "scene_id": scene_id,
                    "text": "秦岚听见警报声，看见主控台闪烁。",
                    "summary": "隐藏摘要不应进入 source",
                },
                {
                    "chunk_id": "rag-b",
                    "scene_id": str(uuid.uuid4()),
                    "text": "未来 Scene 泄漏内容。",
                },
                {
                    "chunk_id": "rag-null",
                    "scene_id": None,
                    "text": "无 Scene 标注的章节 fallback 内容。",
                },
            ],
            memory_records=[
                {
                    "id": "memory-1",
                    "full_state": {"secret": "完整记忆快照隐藏内容"},
                    "summary": "不应直接渲染完整快照。",
                }
            ],
        )

        sections = ContextCompiler()._build_sections(bundle, options)
        keys = {section.key for section in sections}
        assert {
            "role_profile",
            "role_visible_knowledge",
            "role_relationship_context",
            "role_scene_perception",
            "scene_director_constraints",
            "scene_time_boundary",
        }.issubset(keys)
        assert "scene_blueprint" not in keys
        assert "pov_knowledge" not in keys

        role_text = "\n".join(
            section.content
            for section in sections
            if section.key.startswith("role_") or section.key == "current_scene_evidence"
        )
        assert "公开信息：城中传闻有暗影组织活动。" in role_text
        assert "真实隐藏真相" not in role_text
        assert "国王秘密操纵" not in role_text
        assert "隐藏关系描述" not in role_text
        assert "必须发生" not in role_text
        assert "未来 Scene 泄漏内容" not in role_text
        assert "无 Scene 标注的章节 fallback 内容" not in role_text

        director = next(s for s in sections if s.key == "scene_director_constraints")
        assert director.status == "director_only"
        assert "DIRECTOR_ONLY" in director.content
        assert "必须发生：发现林澈撒谎" in director.content

        rendered = render_compiled_context(
            CompiledContext(sections=sections, total_tokens=1, budget_tokens=4000)
        )
        source_text = "\n".join(
            str(source) for section in sections for source in section.sources
        )
        assert "完整记忆快照隐藏内容" not in rendered
        assert "完整记忆快照隐藏内容" not in source_text
        assert "隐藏摘要不应进入 source" not in source_text


# ============================================================
# CompileOptions 测试
# ============================================================


class TestCompileOptions:
    """测试 CompileOptions 数据类"""

    def test_create_default(self) -> None:
        opts = CompileOptions(
            novel_id="test-id",
            task="测试",
            scope="project",
        )
        assert opts.novel_id == "test-id"
        assert opts.reveal_mode == "author_safe"
        assert opts.enable_geo_filter is False

    def test_create_full(self) -> None:
        opts = CompileOptions(
            novel_id="test-id",
            task="生成剧情线",
            scope="arc",
            chapter_index=3,
            arc_id="arc-1",
            entity_ids=["e1", "e2"],
            character_ids=["c1"],
            location_ids=["l1"],
            reveal_mode="author_full",
            enable_geo_filter=True,
        )
        assert opts.chapter_index == 3
        assert opts.arc_id == "arc-1"
        assert opts.reveal_mode == "author_full"
        assert opts.enable_geo_filter is True


# ============================================================
# Markdown 渲染测试
# ============================================================


class TestMarkdownRenderer:
    """测试 Markdown 渲染"""

    def test_render_empty_bundle(self) -> None:
        """空 bundle 应渲染为完整结构"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试任务",
            scope="project",
        )
        md = render_md(bundle)
        # 验证基本结构存在
        assert "# 结构化创作上下文" in md
        assert "一、当前任务" in md
        assert "二、必须遵守的硬约束" in md
        assert "三、当前剧情阶段" in md
        assert "四、相关人物" in md
        assert "五、相关世界对象" in md
        assert "六、相关地理与历史" in md
        assert "七、相关剧情线" in md
        assert "八、相关 Memory" in md
        assert "九、相关伏笔与信息揭示" in md
        assert "十、禁止事项" in md
        assert "十一、可用创作素材" in md
        assert "十二、风险提示" in md

    def test_render_task_section(self) -> None:
        """任务段落应显示任务信息"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="生成第 5 章章节卡",
            scope="chapter",
            chapter_index=5,
        )
        md = render_md(bundle)
        assert "生成第 5 章章节卡" in md
        assert "第 5 章" in md

    def test_render_with_project(self) -> None:
        """项目信息应出现在当前剧情阶段段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="project",
            project={
                "title": "星辰之旅",
                "genre": "科幻",
                "tone": "严肃",
                "current_stage": "outlining",
            },
        )
        md = render_md(bundle)
        assert "星辰之旅" in md
        assert "科幻" in md
        assert "outlining" in md

    def test_render_with_characters(self) -> None:
        """人物信息应出现在相关人物段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="world_character",
            characters=[
                {
                    "name": "林明",
                    "role": "protagonist",
                    "current_goal": "寻找失落的文明",
                    "current_state": "准备出发",
                    "stance": "正义",
                    "voice_style": "沉稳",
                    "character_id": "c1",
                },
            ],
        )
        md = render_md(bundle)
        assert "林明" in md
        assert "protagonist" in md
        assert "寻找失落的文明" in md
        assert "知识边界" in md

    def test_render_with_world_entities(self) -> None:
        """世界对象应出现在相关世界对象段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="world",
            world_entities=[
                {
                    "name": "艾尔王国",
                    "entity_type": "location",
                    "summary": "大陆中央的古老王国",
                    "public_info": "以魔法文明著称",
                    "importance_level": "core",
                },
                {
                    "name": "暗影组织",
                    "entity_type": "faction",
                    "summary": "秘密操控世界的组织",
                    "hidden_truth": "幕后黑手是王室",
                    "importance_level": "important",
                },
            ],
        )
        md = render_md(bundle)
        assert "艾尔王国" in md
        assert "暗影组织" in md
        assert "大陆中央的古老王国" in md

    def test_render_with_memory(self) -> None:
        """记忆应出现在 Memory 段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            memory_records=[
                {
                    "memory_type": "event",
                    "title": "主角出发",
                    "summary": "林明离开村庄开始冒险",
                    "chapter_index": 1,
                },
            ],
        )
        md = render_md(bundle)
        assert "主角出发" in md
        assert "林明离开村庄开始冒险" in md

    def test_render_with_plot_threads(self) -> None:
        """剧情线应出现在剧情线段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            plot_threads=[
                {
                    "name": "寻找神器",
                    "thread_type": "main",
                    "summary": "主角寻找失落神器的旅程",
                    "current_stage": "启程阶段",
                },
            ],
        )
        md = render_md(bundle)
        assert "寻找神器" in md
        assert "main" in md
        assert "启程阶段" in md

    def test_render_with_warnings(self) -> None:
        """警告应出现在风险提示段落"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="测试",
            scope="full",
            warnings=["加载 geo_locations 时出错: 连接超时"],
            budget_used={"core_entities": 8, "characters": 6},
        )
        md = render_md(bundle)
        assert "加载 geo_locations" in md


# ============================================================
# Static Renderer Tests (no DB needed)
# ============================================================


class TestFacadeRenderContextMarkdown:
    """测试 facade.render_context_markdown（静态渲染，无需 DB）"""

    def test_facade_render(self) -> None:
        """facade 的 render_context_markdown 应正常工作"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="静态渲染测试",
            scope="project",
        )
        md = render_context_markdown(bundle)
        assert isinstance(md, str)
        assert "静态渲染测试" in md

    def test_facade_render_with_data(self) -> None:
        """带数据的渲染"""
        bundle = StructureContextBundle(
            novel_id="test-id",
            task="带数据渲染",
            scope="world_character",
            project={"title": "测试", "genre": "玄幻"},
            characters=[{"name": "张三", "role": "protagonist"}],
            world_entities=[
                {"name": "灵界", "entity_type": "location", "summary": "修炼世界"}
            ],
        )
        md = render_context_markdown(bundle)
        assert "测试" in md
        assert "张三" in md
        assert "灵界" in md


# ============================================================
# API Schema 测试
# ============================================================


class TestApiSchemas:
    """测试 API 请求/响应 Schema 校验"""

    def test_compile_request_valid(self) -> None:
        """有效请求应能创建"""
        from modules.context.schemas import ContextCompileRequest

        req = ContextCompileRequest(
            novel_id="test-id",
            task="测试任务",
            scope="chapter",
            chapter_index=5,
        )
        assert req.novel_id == "test-id"
        assert req.scope == "chapter"
        assert req.chapter_index == 5

    def test_compile_request_minimal(self) -> None:
        """最小请求"""
        from modules.context.schemas import ContextCompileRequest

        req = ContextCompileRequest(
            novel_id="test-id",
            task="测试",
            scope="project",
        )
        assert req.reveal_mode == "author_safe"

    def test_render_request_valid(self) -> None:
        """渲染请求校验"""
        from modules.context.schemas import ContextRenderRequest

        req = ContextRenderRequest(
            novel_id="test-id",
            task="生成剧情线",
            scope="arc",
            arc_id="arc-1",
        )
        assert req.arc_id == "arc-1"

    def test_budget_used_item(self) -> None:
        """预算使用明细"""
        from modules.context.schemas import BudgetUsedItem

        item = BudgetUsedItem(category="core_entities", budget=8, used=3)
        assert item.category == "core_entities"
        assert item.budget == 8
        assert item.used == 3


# ============================================================
# GeoReachabilityFilter 测试
# ============================================================


# ============================================================
# API 集成测试
# ============================================================


async def _setup_character_knowledge(
    db_session: AsyncSession,
    knowledge_level: str,
    known_content: str | None = None,
    misconception: str | None = None,
) -> tuple[str, str, str, str]:
    """创建项目、POV 人物、目标实体与知识边界记录。

    返回: (novel_id_hex, character_id_hex, target_id_hex, hidden_truth)
    """
    from modules.project.models import Project
    from modules.world.models import Character, CharacterKnowledge, CoreEntity

    nid = uuid.uuid4()
    novel_id_hex = nid.hex
    db_session.add(
        Project(
            id=nid,
            title="测试小说",
            genre="奇幻",
            language="zh",
        )
    )

    char_id = uuid.uuid4()
    db_session.add(
        CoreEntity(
            id=char_id,
            novel_id=nid,
            entity_type="character",
            name="POV角色",
            status="canonical",
        )
    )
    db_session.add(
        Character(
            entity_id=char_id,
            novel_id=nid,
            name="POV角色",
            status="canonical",
        )
    )

    target_id = uuid.uuid4()
    hidden_truth = "源堡是诡秘之主的唯一性"
    db_session.add(
        CoreEntity(
            id=target_id,
            novel_id=nid,
            entity_type="location",
            name="源堡",
            summary="神秘的源质空间",
            hidden_truth=hidden_truth,
            status="canonical",
            importance_level="core",
            importance=0.9,
        )
    )
    db_session.add(
        CharacterKnowledge(
            id=uuid.uuid4(),
            novel_id=nid,
            character_id=char_id,
            target_type="location",
            target_id=target_id,
            knowledge_level=knowledge_level,
            known_content=known_content,
            misconception=misconception,
            source_chapter_index=1,
        )
    )
    await db_session.flush()
    return novel_id_hex, char_id.hex, target_id.hex, hidden_truth


def _response_text(data: dict) -> str:
    """把 API 返回的 Tier 编译结果合并为可搜索文本。"""
    parts = [s.get("content", "") for s in data.get("sections", [])]
    return "\n".join(parts)


class TestContextApiIntegration:
    """通过 API client 验证知识边界与渲染行为"""

    @pytest.mark.asyncio
    async def test_character_mode_hides_hidden_truth(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
    ) -> None:
        """character 视角 unknown 知识不应暴露 hidden_truth"""
        novel_id, char_id, target_id, hidden_truth = await _setup_character_knowledge(
            db_session,
            knowledge_level="unknown",
        )

        response = await async_client.post(
            "/api/context/compile",
            json={
                "novel_id": novel_id,
                "task": "生成场景",
                "scope": "world_character",
                "reveal_mode": "character",
                "visible_until_chapter": 2,
                "viewpoint_character_id": char_id,
                "character_ids": [char_id],
                "entity_ids": [target_id],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["reveal_mode"] == "character"
        assert hidden_truth not in _response_text(data)

    @pytest.mark.asyncio
    async def test_character_mode_restricted_redacts_hidden_truth(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
    ) -> None:
        """character 视角 restricted 知识应显示 known_content 并隐藏 hidden_truth"""
        known_content = "主角知道这是神秘空间"
        novel_id, char_id, target_id, hidden_truth = await _setup_character_knowledge(
            db_session,
            knowledge_level="restricted",
            known_content=known_content,
        )

        response = await async_client.post(
            "/api/context/compile",
            json={
                "novel_id": novel_id,
                "task": "生成场景",
                "scope": "world_character",
                "reveal_mode": "character",
                "visible_until_chapter": 2,
                "viewpoint_character_id": char_id,
                "character_ids": [char_id],
                "entity_ids": [target_id],
            },
        )

        assert response.status_code == 200
        data = response.json()
        text = _response_text(data)
        assert hidden_truth not in text
        assert known_content in text

    @pytest.mark.asyncio
    async def test_character_mode_misunderstood_shows_misconception(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
    ) -> None:
        """character 视角 misunderstood 知识应显示 misconception 并隐藏 hidden_truth"""
        misconception = "主角误以为这是梦境"
        novel_id, char_id, target_id, hidden_truth = await _setup_character_knowledge(
            db_session,
            knowledge_level="misunderstood",
            misconception=misconception,
        )

        response = await async_client.post(
            "/api/context/compile",
            json={
                "novel_id": novel_id,
                "task": "生成场景",
                "scope": "world_character",
                "reveal_mode": "character",
                "visible_until_chapter": 2,
                "viewpoint_character_id": char_id,
                "character_ids": [char_id],
                "entity_ids": [target_id],
            },
        )

        assert response.status_code == 200
        data = response.json()
        text = _response_text(data)
        assert hidden_truth not in text
        assert misconception in text

    @pytest.mark.asyncio
    async def test_render_endpoint_returns_markdown(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
    ) -> None:
        """/api/context/render 应返回包含 Tier 标题的 markdown"""
        from modules.project.models import Project

        nid = uuid.uuid4()
        db_session.add(
            Project(
                id=nid,
                title="测试渲染",
                genre="奇幻",
                language="zh",
            )
        )
        await db_session.flush()

        response = await async_client.post(
            "/api/context/render",
            json={
                "novel_id": nid.hex,
                "task": "测试渲染",
                "scope": "project",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "markdown" in data
        assert "## 一、创作目标" in data["markdown"]

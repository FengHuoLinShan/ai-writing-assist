"""InteractionService core mutations and stable service entry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY
from infrastructure.tasks.facade import (
    cancel_exact_task,
    enqueue_task,
    list_task_lifecycle_contracts,
)
from modules.account.facade import current_account_id, is_anonymous_rp_principal
from modules.interaction.journey_overview import JourneyOverviewMixin
from modules.interaction.journey_views import JourneyViewsMixin
from modules.interaction.models import (
    InteractionAccountPreference,
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
)
from modules.interaction.repositories import InteractionRepository
from modules.interaction.runtime_policy import (
    STORY_TASK_TYPES,
    anonymous_rp_execution_snapshot,
    authorize_interaction_story_continuation,
    clear_private_agent_state,
    is_anonymous_rp_snapshot,
    new_interaction_story_envelope,
    story_task_type,
)
from modules.interaction.schemas import (
    InteractionHeartbeatResponse,
    InteractionMutationResponse,
    InteractionPreferencesResponse,
    InteractionReferenceSummaryResponse,
    InteractionReferenceUpdateRequest,
    InteractionSourceUpdateRequest,
    InteractionStopResponse,
    JourneyCreateRequest,
    JourneyDetailResponse,
)
from modules.interaction.service_support import (
    MAX_ACTIVE_STORY_ATTEMPTS as MAX_ACTIVE_STORY_ATTEMPTS,
)
from modules.interaction.service_support import (
    RECENT_MESSAGE_LIMIT as RECENT_MESSAGE_LIMIT,
)
from modules.interaction.service_support import (
    SEE_SEA_HEARTBEAT_TTL_SECONDS as SEE_SEA_HEARTBEAT_TTL_SECONDS,
)
from modules.interaction.service_support import (
    SEE_SEA_MANUAL_CLAIM_SECONDS as SEE_SEA_MANUAL_CLAIM_SECONDS,
)
from modules.interaction.service_support import (
    SUMMARY_TRIGGER_TOKENS as SUMMARY_TRIGGER_TOKENS,
)
from modules.interaction.service_support import (
    _enqueue_overview_refresh_task as _enqueue_overview_refresh_task,
)
from modules.interaction.service_support import (
    _fallback_title as _fallback_title,
)
from modules.interaction.service_support import (
    _parse_uuid as _parse_uuid,
)
from modules.interaction.service_support import (
    _summary_compressible_prefix_end as _summary_compressible_prefix_end,
)
from modules.interaction.service_support import (
    estimate_story_tokens as estimate_story_tokens,
)
from modules.interaction.service_support import (
    path_hash as path_hash,
)
from modules.interaction.source_service import InteractionSourceService
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    archive_interaction_project,
    build_project_llm_execution_snapshot,
    create_interaction_project,
    permanently_delete_interaction_project,
    require_interaction_project,
    restore_interaction_project,
)


class InteractionService(JourneyViewsMixin, JourneyOverviewMixin):
    def __init__(
        self,
        repo: InteractionRepository | None = None,
        source_service: InteractionSourceService | None = None,
    ) -> None:
        self._repo = repo or InteractionRepository()
        self._sources = source_service or InteractionSourceService(self._repo)

    async def create_journey(
        self,
        db: AsyncSession,
        data: JourneyCreateRequest,
    ) -> InteractionMutationResponse:
        if is_anonymous_rp_principal():
            raise ValidationError("匿名体验只能从公开作品开始")
        return await self._create_journey(db, data)

    async def create_demo_journey(
        self,
        db: AsyncSession,
        data: JourneyCreateRequest,
    ) -> InteractionMutationResponse:
        if not is_anonymous_rp_principal():
            raise NotFoundError("公开体验不可用")
        if data.source_setup is None:
            raise ValidationError("请选择公开作品的剧情位置和身份")
        if data.see_sea_enabled or data.web_search_enabled:
            raise ValidationError("匿名体验不支持持续观看或联网")
        source_binding = await self._sources.prepare_public_demo_setup(
            db,
            data.source_setup,
        )
        return await self._create_journey(
            db,
            data,
            source_binding=source_binding,
        )

    async def _create_journey(
        self,
        db: AsyncSession,
        data: JourneyCreateRequest,
        *,
        source_binding: tuple | None = None,
    ) -> InteractionMutationResponse:
        owner_id = current_account_id()
        existing = await self._repo.get_attempt_by_idempotency(
            db,
            owner_id=owner_id,
            idempotency_key=data.idempotency_key,
        )
        if existing is not None:
            journey = await self._repo.get_journey(
                db,
                journey_id=existing.journey_id,
                owner_id=owner_id,
                status=None,
            )
            if journey is None:
                raise ConflictError("该创建请求的历史记录已不可用")
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(existing),
            )

        await self._repo.lock_owner_generation_slots(db, owner_id=owner_id)
        existing = await self._repo.get_attempt_by_idempotency(
            db,
            owner_id=owner_id,
            idempotency_key=data.idempotency_key,
        )
        if existing is not None:
            journey = await self._repo.get_journey(
                db,
                journey_id=existing.journey_id,
                owner_id=owner_id,
                status=None,
            )
            if journey is None:
                raise ConflictError("该创建请求的历史记录已不可用")
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(existing),
            )
        await self._require_generation_slot(db, owner_id)
        if source_binding is None:
            source_binding = (
                await self._sources.prepare_setup(db, data.source_setup)
                if data.source_setup
                else None
            )
        title = (
            f"{source_binding[0].title} · 新旅程"[:255]
            if source_binding
            else _fallback_title(data.opening_text)
        )
        project = await create_interaction_project(db, title=title)
        now = datetime.now(UTC)
        journey = InteractionJourney(
            novel_id=uuid.UUID(project.novel_id),
            owner_id=owner_id,
            title=title,
            title_source="fallback",
            opening_text=data.opening_text,
            status="active",
            see_sea_enabled=data.see_sea_enabled,
            see_sea_last_heartbeat_at=now if data.see_sea_enabled else None,
            action_options_enabled=data.action_options_enabled,
            web_search_enabled=data.web_search_enabled,
            generation_mode=data.generation_mode,
            selection_epoch=0,
            overview_epoch=0,
            source_revision_id=source_binding[0].id if source_binding else None,
            source_anchor_key=(
                source_binding[1]["anchor_key"] if source_binding else None
            ),
            source_anchor=source_binding[1] if source_binding else {},
            player_identity=source_binding[2] if source_binding else {},
            reference_policy=source_binding[3] if source_binding else {},
            source_context_epoch=0,
            latest_activity_at=now,
        )
        db.add(journey)
        await db.flush()
        from modules.interaction.schemas import interaction_input_metadata

        opening = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=None,
            role="user",
            message_kind="setup",
            content=data.opening_text,
            input_json=interaction_input_metadata(
                data.opening_input_kind, data.ensemble_cast_keys
            ),
            completion_state="complete",
            token_estimate=estimate_story_tokens(data.opening_text),
        )
        db.add(opening)
        await db.flush()
        await self._repo.set_selected_child(
            db,
            journey=journey,
            parent_node_id=None,
            child_node_id=opening.id,
        )
        journey.selected_leaf_node_id = opening.id
        snapshot = (
            anonymous_rp_execution_snapshot()
            if is_anonymous_rp_principal()
            else await build_project_llm_execution_snapshot(
                db,
                str(journey.novel_id),
                **({"web_search_enabled": True} if journey.web_search_enabled else {}),
                **(
                    {"interaction_ensemble": True}
                    if journey.generation_mode == "ensemble"
                    else {}
                ),
            )
        )
        attempt = await self._create_attempt(
            db,
            journey=journey,
            response_to=opening,
            context_nodes=[opening],
            idempotency_key=data.idempotency_key,
            request_kind="opening",
            llm_execution_snapshot=snapshot,
        )
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt),
        )

    async def update_journey_source(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        data: InteractionSourceUpdateRequest,
    ) -> JourneyDetailResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        self._check_epoch(journey, data.expected_selection_epoch)
        self._check_source_epoch(journey, data.expected_source_context_epoch)
        await self._require_source_mutable(db, journey)
        if journey.source_revision_id is None:
            raise ConflictError("已开始的无资料旅程不能中途切换作品，请新建旅程")
        current = await self._sources.require_ready_revision(
            db, journey.source_revision_id
        )
        target = await self._sources.require_ready_revision(
            db, _parse_uuid(data.source_revision_id, "source_revision_id")
        )
        if target.source_novel_id != current.source_novel_id:
            raise ConflictError("已开始的旅程不能切换作品，请新建旅程")
        target_anchor = self._sources._find_anchor(target, data.progress_anchor_key)
        old_position = (
            int((journey.source_anchor or {}).get("chapter_index") or 0),
            int((journey.source_anchor or {}).get("end_offset") or 0),
        )
        new_position = (
            int(target_anchor.get("chapter_index") or 0),
            int(target_anchor.get("end_offset") or 0),
        )
        if new_position < old_position:
            raise ConflictError("已开始的旅程不能回退剧情进度，请新建旅程")

        old_refs = {
            item["reference_key"]: item for item in current.reference_manifest or []
        }
        new_refs = {item["target_id"]: item for item in target.reference_manifest or []}

        def available(item: dict | None) -> bool:
            return bool(
                item and self._sources.reference_visible(target, item, target_anchor)
            )

        def remap(keys: list[str], *, required: bool) -> list[str]:
            mapped = []
            for key in keys:
                old = old_refs.get(key)
                new = new_refs.get(old.get("target_id")) if old else None
                if not available(new):
                    if required:
                        raise ConflictError("新版本无法对应已固定对象，请新建旅程")
                    continue
                mapped.append(new["reference_key"])
            return mapped

        policy = dict(journey.reference_policy or {})
        player = dict(journey.player_identity or {})
        if player.get("kind") == "source_character":
            replacement = new_refs.get(player.get("target_id"))
            if (
                not available(replacement)
                or replacement.get("entity_type") != "character"
            ):
                raise ConflictError("新版本无法对应玩家角色，请新建旅程")
            player.update(
                reference_key=replacement["reference_key"],
                label=replacement["label"],
            )
        journey.source_revision_id = target.id
        journey.source_anchor_key = target_anchor["anchor_key"]
        journey.source_anchor = target_anchor
        journey.player_identity = player
        journey.reference_policy = {
            "pinned": remap(list(policy.get("pinned") or []), required=True),
            "excluded": remap(list(policy.get("excluded") or []), required=False),
        }
        journey.source_context_epoch += 1
        await self._repo.notify_state_changed(db, journey)
        self._repo.touch(journey)
        await db.flush()
        return await self._detail(db, journey)

    async def update_references(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        data: InteractionReferenceUpdateRequest,
    ) -> InteractionReferenceSummaryResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        self._check_source_epoch(journey, data.expected_source_context_epoch)
        await self._require_source_mutable(db, journey)
        if journey.source_revision_id is None:
            raise ConflictError("该旅程未使用作品资料")
        revision = (
            await self._sources.require_public_demo_ready_revision(
                db,
                revision_id=str(journey.source_revision_id),
            )
            if is_anonymous_rp_principal()
            else await self._sources.require_ready_revision(
                db, journey.source_revision_id
            )
        )
        references = {
            item["reference_key"]: item for item in revision.reference_manifest or []
        }
        policy = dict(journey.reference_policy or {})
        pinned = list(policy.get("pinned") or [])
        excluded = list(policy.get("excluded") or [])
        key = data.reference_key
        if data.action == "reset":
            pinned, excluded = [], []
        elif key not in references:
            raise ValidationError("所选作品资料已不可用")
        elif data.action == "pin":
            if not self._sources.reference_visible(
                revision,
                references[key],
                journey.source_anchor or {},
            ):
                raise ValidationError("所选作品资料超出当前剧情进度")
            pinned = list(dict.fromkeys([*pinned, key]))
            excluded = [item for item in excluded if item != key]
        else:
            if key == (journey.player_identity or {}).get("reference_key"):
                raise ValidationError("玩家角色不能被忽略")
            excluded = list(dict.fromkeys([*excluded, key]))
            pinned = [item for item in pinned if item != key]
        journey.reference_policy = {"pinned": pinned, "excluded": excluded}
        journey.source_context_epoch += 1
        await self._repo.notify_state_changed(db, journey)
        self._repo.touch(journey)
        await db.flush()
        return await self.get_reference_summary(db, journey_id=journey_id)

    async def _validate_observation_input(self, db, journey, input_meta, nodes, content):
        if not input_meta:
            return
        if (
            not get_settings().collaboration_v2_enabled
            or journey.generation_mode != "ensemble"
        ):
            raise ConflictError("当前旅程未开启本轮输入分类")
        if len(content) > (
            1500 if input_meta.get("kind") in {"action", "narration"} else 12000
        ):
            raise ValidationError("请将本轮输入分成更短的动作或对话")
        from modules.interaction.ensemble import selected_actor_states
        from modules.interaction.ensemble_v2 import restore_environment

        revision = await self._sources.require_ready_revision(
            db, journey.source_revision_id
        )
        references = {
            item["reference_key"]: str(item["target_id"])
            for item in revision.reference_manifest or []
            if item.get("entity_type") == "character"
            and item["reference_key"]
            not in (journey.reference_policy or {}).get("excluded", [])
            and self._sources.reference_visible(revision, item, journey.source_anchor)
        }
        prior = await selected_actor_states(db, journey, nodes, revision.id)
        present = set(restore_environment(prior, nodes).get("participants", []))
        cast = input_meta.get("cast_keys")
        if cast is not None:
            if len(cast) > 3 or set(cast) - references.keys():
                raise ValidationError("本场人物不在可用资料内")
            present = {references[key] for key in cast}
        whispers = input_meta.get("whisper_to") or []
        if set(whispers) - references.keys() or any(
            references[key] not in present for key in whispers
        ):
            raise ValidationError("请确认私语对象仍在本场人物中")

    async def _validate_input_replay(self, db, journey, attempt, content, input_meta):
        previous = await self._required_node(
            db, journey, str(attempt.response_to_node_id)
        )
        if previous.content != content or (
            input_meta and previous.input_json != input_meta
        ):
            raise ConflictError("同一发送请求已用于不同的文字或接收范围")

    async def send_message(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        content: str,
        expected_selection_epoch: int,
        idempotency_key: str,
        input_meta: dict | None = None,
    ) -> InteractionMutationResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        existing = await self._idempotent_attempt(
            db,
            journey=journey,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            await self._validate_input_replay(db, journey, existing, content, input_meta)
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(existing),
            )
        self._check_epoch(journey, expected_selection_epoch)
        await self._ensure_no_unresolved_attempt(db, journey)
        selected_path = await self._repo.get_selected_path(db, journey=journey)
        if not selected_path:
            raise ConflictError("当前发展不存在")
        await self._validate_observation_input(
            db, journey, input_meta, selected_path, content
        )
        parent = selected_path[-1]
        story_started = self._story_started(selected_path)
        message_kind = "story" if story_started else "setup"
        user_node = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=parent.id,
            role="user",
            message_kind=message_kind,
            content=content,
            input_json=input_meta or {},
            completion_state="complete",
            token_estimate=estimate_story_tokens(content),
        )
        db.add(user_node)
        await db.flush()
        await self._repo.set_selected_child(
            db,
            journey=journey,
            parent_node_id=parent.id,
            child_node_id=user_node.id,
        )
        journey.selection_epoch += 1
        journey.selected_leaf_node_id = user_node.id
        self._repo.touch(journey)
        context_nodes = [*selected_path, user_node]
        attempt = await self._start_new_attempt(
            db,
            journey=journey,
            response_to=user_node,
            context_nodes=context_nodes,
            idempotency_key=idempotency_key,
            request_kind="message" if story_started else "setup_continue",
        )
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt),
        )

    async def continue_from_node(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        node_id: str,
        content: str,
        expected_selection_epoch: int,
        idempotency_key: str,
        input_meta: dict | None = None,
    ) -> InteractionMutationResponse:
        """Explicitly branch from the client's still-visible old position."""
        journey = await self._active_journey_for_update(db, journey_id)
        existing = await self._idempotent_attempt(
            db,
            journey=journey,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            await self._validate_input_replay(db, journey, existing, content, input_meta)
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(existing),
            )
        self._check_epoch(journey, expected_selection_epoch)
        await self._ensure_no_unresolved_attempt(db, journey)
        branch_point = await self._required_node(db, journey, node_id)
        ancestry = await self._repo.get_ancestry(
            db,
            journey=journey,
            node=branch_point,
        )
        await self._validate_observation_input(db, journey, input_meta, ancestry, content)
        story_started = self._story_started(ancestry)
        message_kind = "story" if story_started else "setup"
        await self._select_ancestry(db, journey=journey, ancestry=ancestry)
        user_node = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=branch_point.id,
            role="user",
            message_kind=message_kind,
            content=content,
            input_json=input_meta or {},
            completion_state="complete",
            token_estimate=estimate_story_tokens(content),
        )
        db.add(user_node)
        await db.flush()
        await self._repo.set_selected_child(
            db,
            journey=journey,
            parent_node_id=branch_point.id,
            child_node_id=user_node.id,
        )
        journey.selection_epoch += 1
        journey.selected_leaf_node_id = user_node.id
        self._repo.touch(journey)
        attempt = await self._start_new_attempt(
            db,
            journey=journey,
            response_to=user_node,
            context_nodes=[*ancestry, user_node],
            idempotency_key=idempotency_key,
            request_kind="from_here" if story_started else "setup_continue",
        )
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt),
        )

    async def regenerate(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        assistant_node_id: str,
        expected_selection_epoch: int,
        idempotency_key: str,
    ) -> InteractionMutationResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        existing = await self._idempotent_attempt(
            db,
            journey=journey,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(existing),
            )
        self._check_epoch(journey, expected_selection_epoch)
        await self._ensure_no_unresolved_attempt(db, journey)
        assistant = await self._required_node(
            db,
            journey,
            assistant_node_id,
        )
        if assistant.role != "assistant" or assistant.parent_node_id is None:
            raise ValidationError("只能重新生成模型故事")
        selected_path = await self._repo.get_selected_path(db, journey=journey)
        selected_ids = [node.id for node in selected_path]
        if assistant.id not in selected_ids:
            raise ConflictError("请先切换到这个发展再重新生成")
        parent_index = selected_ids.index(assistant.id) - 1
        if parent_index < 0:
            raise ConflictError("该故事没有可重新生成的用户起点")
        response_to = selected_path[parent_index]
        if response_to.id != assistant.parent_node_id:
            raise ConflictError("故事分支结构已变化，请刷新后重试")
        context_nodes = selected_path[: parent_index + 1]
        siblings = await self._repo.list_children(
            db,
            journey=journey,
            parent_node_id=response_to.id,
        )
        assistant_position = next(
            (
                index
                for index, sibling in enumerate(siblings)
                if sibling.id == assistant.id
            ),
            len(siblings),
        )
        earlier_siblings = [
            sibling
            for sibling in siblings[:assistant_position]
            if sibling.role == "assistant" and sibling.id != assistant.id
        ][-2:]
        attempt = await self._start_new_attempt(
            db,
            journey=journey,
            response_to=response_to,
            context_nodes=context_nodes,
            idempotency_key=idempotency_key,
            request_kind="regenerate",
            reference_node_ids=[
                assistant.id,
                *(sibling.id for sibling in earlier_siblings),
            ],
        )
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt),
        )

    async def retry_attempt(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        attempt_id: str,
        expected_selection_epoch: int,
        idempotency_key: str,
    ) -> InteractionMutationResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        existing = await self._idempotent_attempt(
            db,
            journey=journey,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(existing),
            )
        self._check_epoch(journey, expected_selection_epoch)
        previous = await self._required_attempt(
            db,
            journey,
            attempt_id,
            for_update=True,
        )
        unresolved = await self._repo.get_unresolved_attempt(
            db,
            journey=journey,
            for_update=True,
        )
        if unresolved is not None and unresolved.id != previous.id:
            raise ConflictError("请先处理当前未完成的故事，再重试较早的记录")
        if previous.status not in {"failed", "cancelled", "awaiting_continue"}:
            raise ConflictError("这次生成当前不能重试")
        current_path = await self._repo.get_selected_path(db, journey=journey)
        if (
            not current_path
            or current_path[-1].id != previous.response_to_node_id
            or path_hash(current_path) != previous.context_path_hash
        ):
            raise ConflictError("当前发展已经改变，请在对应位置重新生成")
        if previous.status == "awaiting_continue":
            previous.status = "cancelled"
            previous.finish_reason = "regenerated"
            previous.metadata_text = ""
            clear_private_agent_state(previous)
        attempt = await self._start_new_attempt(
            db,
            journey=journey,
            response_to=current_path[-1],
            context_nodes=current_path,
            idempotency_key=idempotency_key,
            request_kind="retry",
        )
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt),
        )

    async def claim_anonymous_attempt(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        attempt_id: str,
    ) -> str:
        if not is_anonymous_rp_principal():
            raise ValidationError("仅公开体验使用当前生成方式")
        journey = await self._active_journey_for_update(db, journey_id)
        attempt = await self._required_attempt(
            db,
            journey,
            attempt_id,
            for_update=True,
        )
        if attempt.task_id is not None or not is_anonymous_rp_snapshot(
            dict(attempt.llm_execution_snapshot or {})
        ):
            raise NotFoundError("生成记录不存在")
        if attempt.status != "pending":
            raise ConflictError("这次生成已在另一处开始")
        execution_id = uuid.uuid4().hex
        attempt.status = "preparing_context"
        attempt.error_kind = None
        attempt.error_message = None
        attempt.usage = {
            **dict(attempt.usage or {}),
            "inline_execution_id": execution_id,
        }
        self._repo.touch(journey)
        await db.flush()
        return execution_id

    async def edit_user_message(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        user_node_id: str,
        content: str,
        expected_selection_epoch: int,
        idempotency_key: str,
        input_meta: dict | None = None,
    ) -> InteractionMutationResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        existing = await self._idempotent_attempt(
            db,
            journey=journey,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            await self._validate_input_replay(db, journey, existing, content, input_meta)
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(existing),
            )
        self._check_epoch(journey, expected_selection_epoch)
        await self._ensure_no_unresolved_attempt(db, journey)
        original = await self._required_node(db, journey, user_node_id)
        if original.role != "user":
            raise ValidationError("第一版只能修改自己的输入")
        selected_path = await self._repo.get_selected_path(db, journey=journey)
        selected_ids = [node.id for node in selected_path]
        if original.id not in selected_ids:
            raise ConflictError("请先切换到这个发展再修改")
        original_index = selected_ids.index(original.id)
        prefix = selected_path[:original_index]
        await self._validate_observation_input(db, journey, input_meta, prefix, content)
        edited = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=original.parent_node_id,
            role="user",
            message_kind=original.message_kind,
            content=content,
            input_json=input_meta or dict(original.input_json or {}),
            completion_state="complete",
            token_estimate=estimate_story_tokens(content),
        )
        db.add(edited)
        await db.flush()
        await self._repo.set_selected_child(
            db,
            journey=journey,
            parent_node_id=original.parent_node_id,
            child_node_id=edited.id,
        )
        journey.selection_epoch += 1
        journey.selected_leaf_node_id = edited.id
        self._repo.touch(journey)
        attempt = await self._start_new_attempt(
            db,
            journey=journey,
            response_to=edited,
            context_nodes=[*prefix, edited],
            idempotency_key=idempotency_key,
            request_kind=(
                "setup_continue"
                if original.message_kind == "setup" and not self._story_started(prefix)
                else "edit"
            ),
        )
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt),
        )

    async def select_branch(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        node_id: str,
        expected_selection_epoch: int,
    ) -> JourneyDetailResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        self._check_epoch(journey, expected_selection_epoch)
        await self._ensure_no_unresolved_attempt(db, journey)
        node = await self._required_node(db, journey, node_id)
        ancestry = await self._repo.get_ancestry(
            db,
            journey=journey,
            node=node,
        )
        await self._select_ancestry(db, journey=journey, ancestry=ancestry)
        journey.selection_epoch += 1
        path = await self._repo.get_selected_path(db, journey=journey)
        journey.selected_leaf_node_id = path[-1].id if path else node.id
        active_overview = await self._activate_best_overview_head(
            db,
            journey=journey,
            path=path,
        )
        if (
            not is_anonymous_rp_principal()
            and active_overview is None
            and self._story_started(path)
        ):
            try:
                snapshot = await build_project_llm_execution_snapshot(
                    db,
                    str(journey.novel_id),
                )
                await _enqueue_overview_refresh_task(
                    db,
                    journey=journey,
                    path=path,
                    snapshot=snapshot,
                )
            except ProjectLLMConfigurationError:
                # Branch browsing remains available without a connected model.
                pass
        self._repo.touch(journey)
        return await self._detail(db, journey)

    async def acknowledge_see_sea_notice(
        self,
        db: AsyncSession,
    ) -> InteractionPreferencesResponse:
        owner_id = current_account_id()
        await self._repo.lock_account_preference(db, owner_id=owner_id)
        preference = await self._repo.get_account_preference(
            db,
            owner_id=owner_id,
            for_update=True,
        )
        if preference is None:
            preference = InteractionAccountPreference(
                owner_id=owner_id,
                see_sea_notice_acknowledged=True,
            )
            db.add(preference)
        else:
            preference.see_sea_notice_acknowledged = True
        await db.flush()
        return InteractionPreferencesResponse(see_sea_notice_acknowledged=True)

    async def stop_attempt(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        attempt_id: str,
        expected_selection_epoch: int,
    ) -> InteractionStopResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        attempt = await self._required_attempt(
            db,
            journey,
            attempt_id,
            for_update=True,
        )
        if attempt.result_node_id is not None or attempt.status in {
            "completed",
            "stopped",
            "cancelled",
        }:
            partial = (
                await self._repo.get_node(
                    db,
                    journey=journey,
                    node_id=attempt.result_node_id,
                )
                if attempt.result_node_id is not None
                else None
            )
            return InteractionStopResponse(
                attempt=self._attempt_response(attempt),
                partial_node=self._message_response(partial) if partial else None,
            )
        self._check_epoch(journey, expected_selection_epoch)
        if attempt.status == "failed":
            raise ConflictError("失败残段请使用“保留这段”或“重新生成”处理")
        unresolved = await self._repo.get_unresolved_attempt(
            db,
            journey=journey,
            for_update=True,
        )
        if unresolved is None or unresolved.id != attempt.id:
            raise ConflictError("这次生成已不是当前未完成的故事")
        journey.see_sea_enabled = False
        journey.see_sea_last_heartbeat_at = None
        partial = await self._stop_locked_attempt(
            db,
            journey=journey,
            attempt=attempt,
            end_reason="user_stopped",
            formalize_visible=True,
        )
        if partial is not None and journey.selected_leaf_node_id == partial.id:
            await self._maybe_enqueue_overview_after_formalization(
                db,
                journey=journey,
                snapshot=dict(attempt.llm_execution_snapshot or {}),
            )
        return InteractionStopResponse(
            attempt=self._attempt_response(attempt),
            partial_node=self._message_response(partial) if partial else None,
        )

    async def keep_partial(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        attempt_id: str,
        expected_selection_epoch: int,
    ) -> InteractionStopResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        attempt = await self._required_attempt(
            db,
            journey,
            attempt_id,
            for_update=True,
        )
        if attempt.result_node_id is not None:
            partial = await self._repo.get_node(
                db,
                journey=journey,
                node_id=attempt.result_node_id,
            )
            return InteractionStopResponse(
                attempt=self._attempt_response(attempt),
                partial_node=self._message_response(partial) if partial else None,
            )
        self._check_epoch(journey, expected_selection_epoch)
        if attempt.status not in {"awaiting_continue", "failed"}:
            raise ConflictError("这次生成当前不能保留为故事")
        unresolved = await self._repo.get_unresolved_attempt(
            db,
            journey=journey,
            for_update=True,
        )
        if unresolved is not None and unresolved.id != attempt.id:
            raise ConflictError("请先处理当前未完成的故事")
        force_select = attempt.status == "failed"
        partial = await self._stop_locked_attempt(
            db,
            journey=journey,
            attempt=attempt,
            end_reason="provider_failed" if force_select else "kept_partial",
            formalize_visible=True,
            force_select=force_select,
        )
        if partial is not None and journey.selected_leaf_node_id == partial.id:
            await self._maybe_enqueue_overview_after_formalization(
                db,
                journey=journey,
                snapshot=dict(attempt.llm_execution_snapshot or {}),
            )
        return InteractionStopResponse(
            attempt=self._attempt_response(attempt),
            partial_node=self._message_response(partial) if partial else None,
        )

    async def continue_attempt(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        attempt_id: str,
        expected_selection_epoch: int,
        idempotency_key: str,
    ) -> InteractionMutationResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        attempt = await self._required_attempt(
            db,
            journey,
            attempt_id,
            for_update=True,
        )
        continuation_keys = list(attempt.usage.get("continuation_keys", []))
        if idempotency_key in continuation_keys:
            return InteractionMutationResponse(
                journey=await self._detail(db, journey),
                attempt=self._attempt_response(attempt),
            )
        self._check_epoch(journey, expected_selection_epoch)
        if attempt.status != "awaiting_continue":
            raise ConflictError("这次生成当前不需要继续写完")
        if attempt.continuation_count >= 1:
            raise ConflictError("这段已经继续写过一次，请保留当前内容或重新生成")
        await self._repo.lock_owner_generation_slots(
            db,
            owner_id=journey.owner_id,
        )
        await self._require_generation_slot(db, journey.owner_id)
        if await self._repo.get_active_attempt(db, journey=journey) is not None:
            raise ConflictError("这个旅程已有一段故事正在生成")
        continuation_keys.append(idempotency_key)
        attempt.usage = {
            **dict(attempt.usage or {}),
            "continuation_keys": continuation_keys[-20:],
        }
        attempt.status = "pending"
        attempt.request_kind = "continue"
        attempt.continuation_count += 1
        if not is_anonymous_rp_principal():
            task_type = story_task_type(dict(attempt.llm_execution_snapshot or {}))
            await authorize_interaction_story_continuation(
                attempt,
                task_type=task_type,
            )
            task_id = enqueue_task(
                db,
                task_type,
                meta=self._story_task_meta(journey, attempt),
                novel_id=str(journey.novel_id),
            )
            attempt.task_id = uuid.UUID(task_id)
        attempt.error_kind = None
        attempt.error_message = None
        self._repo.touch(journey)
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt),
        )

    async def update_modes(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        see_sea_enabled: bool | None,
        action_options_enabled: bool | None,
        expected_selection_epoch: int,
        web_search_enabled: bool | None = None,
        generation_mode: str | None = None,
    ) -> InteractionMutationResponse:
        if is_anonymous_rp_principal() and (
            see_sea_enabled is True or web_search_enabled is True
        ):
            raise ValidationError("匿名体验不支持持续观看或联网")
        journey = await self._active_journey_for_update(db, journey_id)
        self._check_epoch(journey, expected_selection_epoch)
        if generation_mode is not None:
            if generation_mode not in {"standard", "ensemble"}:
                raise ValidationError("不支持的演绎方式")
            if generation_mode == "ensemble":
                if (
                    not get_settings().interaction_team_enabled
                    or not journey.source_revision_id
                    or is_anonymous_rp_principal()
                ):
                    raise ValidationError("多角色演绎尚未开启，或尚未选择作品资料")
            journey.generation_mode = generation_mode
        if see_sea_enabled is not None:
            journey.see_sea_enabled = see_sea_enabled
            journey.see_sea_last_heartbeat_at = (
                datetime.now(UTC) if see_sea_enabled else None
            )
        if action_options_enabled is not None:
            journey.action_options_enabled = action_options_enabled
        if web_search_enabled is not None:
            if web_search_enabled:
                from infrastructure.llm.web_search import search_snapshot

                if search_snapshot() is None:
                    raise ValidationError("公开资料搜索尚未配置")
            journey.web_search_enabled = web_search_enabled
        self._repo.touch(journey)
        attempt = await self._repo.get_unresolved_attempt(db, journey=journey)
        if (
            attempt is not None
            and attempt.status in {"pending", "preparing_context", "running"}
            and see_sea_enabled is True
        ):
            attempt.usage = {
                **dict(attempt.usage or {}),
                # Once a running generation has become the current sea beat,
                # switching the loop off means "stop after this beat".  Keep
                # the marker so a length continuation still finishes that
                # same beat and its action suggestions remain suppressed.
                "see_sea_adopted": True,
            }
        if (
            attempt is not None
            and attempt.status == "awaiting_continue"
            and see_sea_enabled is True
        ):
            attempt = await self._try_resume_awaiting_see_sea_or_wait(
                db,
                journey=journey,
                attempt=attempt,
            )
        if (
            journey.see_sea_enabled
            and attempt is None
            and journey.selected_leaf_node_id is not None
        ):
            path = await self._repo.get_selected_path(db, journey=journey)
            if path:
                attempt = await self._try_start_see_sea_or_wait(
                    db,
                    journey=journey,
                    context_nodes=path,
                    response_to=path[-1],
                )
        return InteractionMutationResponse(
            journey=await self._detail(db, journey),
            attempt=self._attempt_response(attempt) if attempt else None,
        )

    async def heartbeat(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionHeartbeatResponse:
        if is_anonymous_rp_principal():
            raise ValidationError("匿名体验不支持持续观看")
        journey = await self._active_journey_for_update(db, journey_id)
        if not journey.see_sea_enabled:
            return InteractionHeartbeatResponse(
                see_sea_enabled=False,
                accepted=False,
            )
        if not self._see_sea_is_authorized(journey):
            journey.see_sea_enabled = False
            journey.see_sea_last_heartbeat_at = None
            self._repo.touch(journey)
            return InteractionHeartbeatResponse(
                see_sea_enabled=False,
                accepted=False,
            )
        journey.see_sea_last_heartbeat_at = datetime.now(UTC)
        attempt = await self._repo.get_unresolved_attempt(db, journey=journey)
        if attempt is not None and attempt.status == "awaiting_continue":
            attempt = await self._try_resume_awaiting_see_sea_or_wait(
                db,
                journey=journey,
                attempt=attempt,
            )
        elif attempt is None:
            path = await self._repo.get_selected_path(db, journey=journey)
            if path:
                attempt = await self._try_start_see_sea_or_wait(
                    db,
                    journey=journey,
                    context_nodes=path,
                    response_to=path[-1],
                )
        return InteractionHeartbeatResponse(
            see_sea_enabled=True,
            accepted=True,
            attempt=self._attempt_response(attempt) if attempt else None,
        )

    async def leave_story_page(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionHeartbeatResponse:
        """Revoke foreground sea-loop authorization without cancelling its step."""

        if is_anonymous_rp_principal():
            raise ValidationError("匿名体验不支持持续观看")

        journey = await self._active_journey_for_update(db, journey_id)
        journey.see_sea_last_heartbeat_at = None
        attempt = await self._repo.get_active_attempt(db, journey=journey)
        if attempt is None:
            journey.see_sea_enabled = False
        self._repo.touch(journey)
        return InteractionHeartbeatResponse(
            see_sea_enabled=journey.see_sea_enabled,
            accepted=False,
            attempt=self._attempt_response(attempt) if attempt else None,
        )

    async def update_title(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        title: str,
    ) -> JourneyDetailResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        journey.title = title
        journey.title_source = "manual"
        self._repo.touch(journey)
        return await self._detail(db, journey)

    async def archive_journey(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        confirmed: bool,
    ) -> JourneyDetailResponse:
        if not confirmed:
            raise ValidationError("归档前需要确认")
        # Lock the hidden project before the journey. Story workers use the
        # same project -> journey order, so archiving cannot hold the journey
        # while waiting to upgrade a shared project lock.
        journey = await self._owned_journey(
            db,
            journey_id,
            status="active",
            for_update=False,
            require_project=False,
        )
        await archive_interaction_project(db, str(journey.novel_id))
        journey = await self._owned_journey(
            db,
            journey_id,
            status="active",
            for_update=True,
            require_project=False,
        )
        unresolved = await self._repo.get_unresolved_attempt(
            db,
            journey=journey,
            for_update=True,
        )
        if unresolved is None:
            latest = await self._repo.get_latest_attempt(
                db,
                journey=journey,
                for_update=True,
            )
            if (
                latest is not None
                and latest.status == "failed"
                and latest.result_node_id is None
                and latest.visible_text.strip()
                and latest.started_selection_epoch == journey.selection_epoch
            ):
                unresolved = latest
        if unresolved is not None:
            await self._stop_locked_attempt(
                db,
                journey=journey,
                attempt=unresolved,
                end_reason="archived",
                formalize_visible=True,
            )
        journey.status = "archived"
        journey.see_sea_enabled = False
        journey.see_sea_last_heartbeat_at = None
        self._repo.touch(journey)
        return await self._detail(db, journey)

    async def restore_journey(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> JourneyDetailResponse:
        journey = await self._owned_journey(
            db,
            journey_id,
            status="archived",
            for_update=True,
            require_project=False,
        )
        await restore_interaction_project(db, str(journey.novel_id))
        journey.status = "active"
        self._repo.touch(journey)
        return await self._detail(db, journey)

    async def delete_journey(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        title_confirmation: str,
    ) -> None:
        journey = await self._owned_journey(
            db,
            journey_id,
            status="archived",
            for_update=True,
            require_project=False,
        )
        if title_confirmation != journey.title:
            raise ValidationError("输入的旅程标题不一致")
        await permanently_delete_interaction_project(db, str(journey.novel_id))

    async def _active_journey_for_update(
        self,
        db: AsyncSession,
        journey_id: str,
    ) -> InteractionJourney:
        return await self._owned_journey(
            db,
            journey_id,
            status="active",
            for_update=True,
            require_project=True,
        )

    async def _owned_journey(
        self,
        db: AsyncSession,
        journey_id: str,
        *,
        status: str | None = "active",
        for_update: bool = False,
        require_project: bool = True,
    ) -> InteractionJourney:
        owner_id = current_account_id()
        parsed_id = _parse_uuid(journey_id, "journey_id")
        journey = await self._repo.get_journey(
            db,
            journey_id=parsed_id,
            owner_id=owner_id,
            status=status,
            for_update=False,
        )
        if journey is None:
            raise NotFoundError("旅程不存在")
        if require_project:
            await require_interaction_project(db, str(journey.novel_id))
        if for_update:
            journey = await self._repo.get_journey(
                db,
                journey_id=parsed_id,
                owner_id=owner_id,
                status=status,
                for_update=True,
            )
            if journey is None:
                raise NotFoundError("旅程不存在")
        return journey

    async def _required_node(
        self,
        db: AsyncSession,
        journey: InteractionJourney,
        node_id: str,
    ) -> InteractionMessageNode:
        node = await self._repo.get_node(
            db,
            journey=journey,
            node_id=_parse_uuid(node_id, "node_id"),
        )
        if node is None:
            raise NotFoundError("故事节点不存在")
        return node

    async def _required_attempt(
        self,
        db: AsyncSession,
        journey: InteractionJourney,
        attempt_id: str,
        *,
        for_update: bool,
    ) -> InteractionGenerationAttempt:
        attempt = await self._repo.get_attempt(
            db,
            journey=journey,
            attempt_id=_parse_uuid(attempt_id, "attempt_id"),
            for_update=for_update,
        )
        if attempt is None:
            raise NotFoundError("生成记录不存在")
        return attempt

    @staticmethod
    def _check_epoch(
        journey: InteractionJourney,
        expected: int,
    ) -> None:
        if journey.selection_epoch != expected:
            raise ConflictError(
                "旅程已在另一处更新",
                code="interaction_selection_conflict",
                context={"current_selection_epoch": journey.selection_epoch},
            )

    @staticmethod
    def _check_source_epoch(journey: InteractionJourney, expected: int) -> None:
        if journey.source_context_epoch != expected:
            raise ConflictError(
                "作品资料已在其他页面更新，请刷新后重试",
                context={"current_source_context_epoch": journey.source_context_epoch},
            )

    async def _require_source_mutable(
        self,
        db: AsyncSession,
        journey: InteractionJourney,
    ) -> None:
        if await self._repo.get_active_attempt(db, journey=journey):
            raise ConflictError("生成进行中，暂不能修改作品资料")
        if journey.selected_leaf_node_id is None:
            return
        latest = await self._repo.get_latest_attempt_for_selected_leaf(
            db,
            journey=journey,
            response_to_node_id=journey.selected_leaf_node_id,
        )
        if latest is not None and latest.status == "awaiting_continue":
            raise ConflictError("请先处理当前未完整的回应")

    async def _ensure_no_unresolved_attempt(
        self,
        db: AsyncSession,
        journey: InteractionJourney,
    ) -> None:
        attempt = await self._repo.get_unresolved_attempt(db, journey=journey)
        if attempt is None:
            return
        if attempt.status == "awaiting_continue":
            raise ConflictError("请先继续写完、保留或重新生成上一段故事")
        raise ConflictError("这个旅程已有一段故事正在生成")

    async def _select_ancestry(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        ancestry: list[InteractionMessageNode],
    ) -> None:
        parent_node_id = None
        for node in ancestry:
            await self._repo.set_selected_child(
                db,
                journey=journey,
                parent_node_id=parent_node_id,
                child_node_id=node.id,
            )
            parent_node_id = node.id

    async def _require_generation_slot(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID,
    ) -> None:
        if (
            await self._repo.count_active_attempts(db, owner_id=owner_id)
            >= MAX_ACTIVE_STORY_ATTEMPTS
        ):
            raise ConflictError(
                "已有 8 段故事正在生成，请先等待或停止一段",
                code="interaction_concurrency_limit",
            )

    async def _idempotent_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        idempotency_key: str,
    ) -> InteractionGenerationAttempt | None:
        attempt = await self._repo.get_attempt_by_idempotency(
            db,
            owner_id=journey.owner_id,
            idempotency_key=idempotency_key,
        )
        if attempt is not None and attempt.journey_id != journey.id:
            raise ConflictError("该操作标识已用于另一段旅程")
        return attempt

    async def _start_new_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        response_to: InteractionMessageNode,
        context_nodes: list[InteractionMessageNode],
        idempotency_key: str,
        request_kind: str,
        reference_node_ids: list[uuid.UUID] | None = None,
    ) -> InteractionGenerationAttempt:
        await self._activate_best_overview_head(
            db,
            journey=journey,
            path=context_nodes,
        )
        await self._repo.lock_owner_generation_slots(
            db,
            owner_id=journey.owner_id,
        )
        await self._require_generation_slot(db, journey.owner_id)
        snapshot = (
            anonymous_rp_execution_snapshot()
            if is_anonymous_rp_principal()
            else await build_project_llm_execution_snapshot(
                db,
                str(journey.novel_id),
                **({"web_search_enabled": True} if journey.web_search_enabled else {}),
                **(
                    {"interaction_ensemble": True}
                    if journey.generation_mode == "ensemble"
                    else {}
                ),
            )
        )
        return await self._create_attempt(
            db,
            journey=journey,
            response_to=response_to,
            context_nodes=context_nodes,
            idempotency_key=idempotency_key,
            request_kind=request_kind,
            llm_execution_snapshot=snapshot,
            reference_node_ids=reference_node_ids,
        )

    async def _create_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        response_to: InteractionMessageNode,
        context_nodes: list[InteractionMessageNode],
        idempotency_key: str,
        request_kind: str,
        llm_execution_snapshot: dict,
        reference_node_ids: list[uuid.UUID] | None = None,
    ) -> InteractionGenerationAttempt:
        if journey.generation_mode == "ensemble":
            if (
                not get_settings().interaction_team_enabled
                or not journey.source_revision_id
                or is_anonymous_rp_principal()
            ):
                raise ValidationError("多角色演绎需要已启用的功能与冻结作品资料")
            if (llm_execution_snapshot.get("agent_runtime") or {}).get("version") != "3":
                raise ValidationError("多角色演绎没有有效的项目执行快照")
        attempt = InteractionGenerationAttempt(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            owner_id=journey.owner_id,
            response_to_node_id=response_to.id,
            idempotency_key=idempotency_key,
            request_kind=request_kind,
            status="pending",
            started_selection_epoch=journey.selection_epoch,
            source_revision_id=journey.source_revision_id,
            started_source_context_epoch=journey.source_context_epoch,
            visible_text="",
            visible_offset=0,
            metadata_text="",
            llm_execution_snapshot=llm_execution_snapshot,
            context_path_hash=path_hash(context_nodes),
            # Persist only the selected leaf. The worker reconstructs and
            # hash-validates the immutable path, avoiding O(n²) UUID copies
            # across a long journey.
            context_node_ids=[str(response_to.id)],
            reference_node_ids=[str(node_id) for node_id in (reference_node_ids or [])],
            usage=({"see_sea_adopted": True} if journey.see_sea_enabled else {}),
        )
        if is_anonymous_rp_principal() and not is_anonymous_rp_snapshot(
            llm_execution_snapshot
        ):
            raise RuntimeError("anonymous RP attempt requires a fixed execution snapshot")
        db.add(attempt)
        await db.flush()
        if not is_anonymous_rp_principal():
            attempt.agent_checkpoint_json = {
                AI_RUN_ENVELOPE_KEY: new_interaction_story_envelope(
                    attempt_id=str(attempt.id),
                    novel_id=str(journey.novel_id),
                    task_type=story_task_type(dict(llm_execution_snapshot or {})),
                )
            }
            await db.flush()
        if not is_anonymous_rp_principal():
            task_id = enqueue_task(
                db,
                story_task_type(dict(attempt.llm_execution_snapshot or {})),
                meta=self._story_task_meta(journey, attempt),
                novel_id=str(journey.novel_id),
            )
            attempt.task_id = uuid.UUID(task_id)
        await db.flush()
        return attempt

    @staticmethod
    def _story_task_meta(
        journey: InteractionJourney,
        attempt: InteractionGenerationAttempt,
    ) -> dict:
        meta = {
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "attempt_id": str(attempt.id),
            "llm_execution_snapshot": dict(attempt.llm_execution_snapshot or {}),
        }
        local = (attempt.llm_execution_snapshot or {}).get("local_agent") or {}
        if local.get("device_id"):
            meta.update(
                {
                    "_local_agent": True,
                    "_local_ready": False,
                    "_local_approved": False,
                    "_local_device_id": local["device_id"],
                }
            )
        envelope = dict(attempt.agent_checkpoint_json or {}).get(AI_RUN_ENVELOPE_KEY)
        if isinstance(envelope, dict) and envelope:
            meta[AI_RUN_ENVELOPE_KEY] = envelope
        return meta

    async def _try_start_see_sea(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        context_nodes: list[InteractionMessageNode],
        response_to: InteractionMessageNode,
    ) -> InteractionGenerationAttempt | None:
        if is_anonymous_rp_principal():
            return None
        if not journey.see_sea_enabled or not self._see_sea_is_authorized(journey):
            journey.see_sea_enabled = False
            journey.see_sea_last_heartbeat_at = None
            return None
        # An opening clarification is setup, not a completed story beat.
        # Keep the sea mode prepared, but wait for the user's answer instead
        # of manufacturing a successor from an unanswered question.
        if not self._story_started(context_nodes):
            return None
        response_created_at = response_to.created_at
        if response_created_at.tzinfo is None:
            response_created_at = response_created_at.replace(tzinfo=UTC)
        if response_created_at > datetime.now(UTC) - timedelta(
            seconds=SEE_SEA_MANUAL_CLAIM_SECONDS
        ):
            # A formalized beat has a small server-enforced boundary in which
            # a prepared manual send/regenerate can claim the free path before
            # any heartbeat is allowed to create the automatic successor.
            return None
        key = f"see-sea:{journey.id}:{response_to.id}"
        existing = await self._repo.get_attempt_by_idempotency(
            db,
            owner_id=journey.owner_id,
            idempotency_key=key,
        )
        if existing is not None and existing.status in {
            "pending",
            "preparing_context",
            "running",
            "awaiting_continue",
        }:
            return existing
        if existing is not None:
            key = f"{key}:{uuid.uuid4()}"
        await self._repo.lock_owner_generation_slots(
            db,
            owner_id=journey.owner_id,
        )
        await self._require_generation_slot(db, journey.owner_id)
        snapshot = (
            anonymous_rp_execution_snapshot()
            if is_anonymous_rp_principal()
            else await build_project_llm_execution_snapshot(
                db,
                str(journey.novel_id),
                **({"web_search_enabled": True} if journey.web_search_enabled else {}),
                **(
                    {"interaction_ensemble": True}
                    if journey.generation_mode == "ensemble"
                    else {}
                ),
            )
        )
        return await self._create_attempt(
            db,
            journey=journey,
            response_to=response_to,
            context_nodes=context_nodes,
            idempotency_key=key,
            request_kind="see_sea",
            llm_execution_snapshot=snapshot,
        )

    async def _try_start_see_sea_or_wait(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        context_nodes: list[InteractionMessageNode],
        response_to: InteractionMessageNode,
    ) -> InteractionGenerationAttempt | None:
        """Keep foreground authorization while the account's eight slots are full."""

        try:
            return await self._try_start_see_sea(
                db,
                journey=journey,
                context_nodes=context_nodes,
                response_to=response_to,
            )
        except ConflictError as exc:
            if exc.code != "interaction_concurrency_limit":
                raise
            return None

    async def _try_resume_awaiting_see_sea_or_wait(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        attempt: InteractionGenerationAttempt,
    ) -> InteractionGenerationAttempt:
        """Adopt one unfinished length response without creating a sibling."""

        if attempt.status != "awaiting_continue":
            return attempt
        if attempt.continuation_count >= 1:
            journey.see_sea_enabled = False
            journey.see_sea_last_heartbeat_at = None
            return attempt
        await self._repo.lock_owner_generation_slots(
            db,
            owner_id=journey.owner_id,
        )
        try:
            await self._require_generation_slot(db, journey.owner_id)
        except ConflictError as exc:
            if exc.code != "interaction_concurrency_limit":
                raise
            return attempt
        if await self._repo.get_active_attempt(db, journey=journey) is not None:
            return attempt
        attempt.usage = {
            **dict(attempt.usage or {}),
            "see_sea_adopted": True,
        }
        attempt.status = "pending"
        attempt.request_kind = "see_sea_continue"
        attempt.continuation_count += 1
        attempt.error_kind = None
        attempt.error_message = None
        task_type = story_task_type(dict(attempt.llm_execution_snapshot or {}))
        await authorize_interaction_story_continuation(
            attempt,
            task_type=task_type,
        )
        task_id = enqueue_task(
            db,
            task_type,
            meta=self._story_task_meta(journey, attempt),
            novel_id=str(journey.novel_id),
        )
        attempt.task_id = uuid.UUID(task_id)
        self._repo.touch(journey)
        return attempt

    async def _stop_locked_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        attempt: InteractionGenerationAttempt,
        end_reason: str,
        formalize_visible: bool,
        force_select: bool = False,
    ) -> InteractionMessageNode | None:
        if attempt.result_node_id is not None:
            return await self._repo.get_node(
                db,
                journey=journey,
                node_id=attempt.result_node_id,
            )
        if attempt.status in {"completed", "stopped", "cancelled"}:
            return None
        if attempt.task_id is not None:
            await cancel_exact_task(
                db,
                task_id=str(attempt.task_id),
                task_types=STORY_TASK_TYPES,
                novel_id=str(journey.novel_id),
                transition_reason=end_reason,
            )
        visible = attempt.visible_text.strip()
        node = None
        if formalize_visible and visible:
            node = await self._formalize_partial_attempt(
                db,
                journey=journey,
                attempt=attempt,
                end_reason=end_reason,
                force_select=force_select,
            )
        else:
            attempt.status = "cancelled"
            attempt.finish_reason = end_reason
        attempt.metadata_text = ""
        self._repo.touch(journey)
        clear_private_agent_state(attempt)
        return node

    async def _formalize_partial_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        attempt: InteractionGenerationAttempt,
        end_reason: str,
        force_select: bool = False,
    ) -> InteractionMessageNode:
        node = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=attempt.response_to_node_id,
            role="assistant",
            content=attempt.visible_text,
            completion_state="partial",
            end_reason=end_reason,
            branch_hint=self._branch_hint(attempt.visible_text),
            story_ended=False,
            action_suggestions=[],
            token_estimate=estimate_story_tokens(attempt.visible_text),
            origin_attempt_id=attempt.id,
        )
        db.add(node)
        await db.flush()
        attempt.result_node_id = node.id
        attempt.status = "stopped"
        attempt.finish_reason = end_reason
        attempt.metadata_text = ""
        if force_select:
            response_to = await self._repo.get_node(
                db,
                journey=journey,
                node_id=attempt.response_to_node_id,
            )
            if response_to is None:
                raise ConflictError("这段失败内容的原发展已不可用")
            ancestry = await self._repo.get_ancestry(
                db,
                journey=journey,
                node=response_to,
            )
            await self._select_ancestry(
                db,
                journey=journey,
                ancestry=[*ancestry, node],
            )
            journey.selected_leaf_node_id = node.id
            journey.selection_epoch += 1
        elif journey.selection_epoch == attempt.started_selection_epoch:
            await self._repo.set_selected_child(
                db,
                journey=journey,
                parent_node_id=attempt.response_to_node_id,
                child_node_id=node.id,
            )
            journey.selected_leaf_node_id = node.id
            journey.selection_epoch += 1
        return node

    async def reconcile_task_owners(self, db: AsyncSession) -> int:
        """Converge story attempts after generic queue stale recovery."""

        attempts = await self._repo.list_attempts_for_task_reconciliation(db)
        attempts_by_novel: dict[uuid.UUID, list[InteractionGenerationAttempt]] = {}
        for attempt in attempts:
            attempts_by_novel.setdefault(attempt.novel_id, []).append(attempt)

        contracts_by_task = {}
        for novel_id, novel_attempts in attempts_by_novel.items():
            contracts_by_task.update(
                await list_task_lifecycle_contracts(
                    db,
                    task_ids=[
                        str(attempt.task_id)
                        for attempt in novel_attempts
                        if attempt.task_id is not None
                    ],
                    novel_id=str(novel_id),
                    max_heartbeat_gap=0.0,
                )
            )

        repaired = 0
        for attempt in attempts:
            task = contracts_by_task.get(str(attempt.task_id))
            if task is not None and task.status in {"pending", "running"}:
                continue
            journey = await self._repo.get_journey_for_task(
                db,
                journey_id=attempt.journey_id,
                novel_id=attempt.novel_id,
                for_update=True,
            )
            if journey is None:
                continue
            current = await self._repo.get_attempt(
                db,
                journey=journey,
                attempt_id=attempt.id,
                for_update=True,
            )
            if current is None or current.status not in {
                "pending",
                "preparing_context",
                "running",
            }:
                continue
            journey.see_sea_enabled = False
            journey.see_sea_last_heartbeat_at = None
            # A worker failure is not a user decision. Keep any checkpointed
            # text on the failed attempt so the user can explicitly keep or
            # regenerate it, but never promote it into the selected story.
            current.status = "failed"
            current.finish_reason = "worker_interrupted"
            current.error_kind = "worker_interrupted"
            current.error_message = "生成服务曾中断，请重新生成"
            current.metadata_text = ""
            clear_private_agent_state(current)
            self._repo.touch(journey)
            repaired += 1
        if repaired:
            await db.flush()
        return repaired

    @staticmethod
    def _story_started(path: list[InteractionMessageNode]) -> bool:
        return any(
            node.role == "assistant" and node.message_kind == "story" for node in path
        )

    @staticmethod
    def _see_sea_is_authorized(journey: InteractionJourney) -> bool:
        heartbeat = journey.see_sea_last_heartbeat_at
        if heartbeat is None:
            return False
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        return heartbeat >= datetime.now(UTC) - timedelta(
            seconds=SEE_SEA_HEARTBEAT_TTL_SECONDS
        )

"""Deterministic interaction workflows and branch selection rules."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.facade import (
    cancel_exact_task,
    enqueue_coalesced_task,
    enqueue_task,
    get_latest_coalesced_task,
    list_task_lifecycle_contracts,
)
from modules.account.facade import current_account_id
from modules.interaction.models import (
    InteractionAccountPreference,
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
    InteractionOverviewRevision,
)
from modules.interaction.prompts import render_overview_sections
from modules.interaction.repositories import InteractionRepository
from modules.interaction.schemas import (
    InteractionActionSuggestion,
    InteractionAttemptResponse,
    InteractionBranchListResponse,
    InteractionBranchVariantResponse,
    InteractionGenerationRecordListResponse,
    InteractionHeartbeatResponse,
    InteractionMessagePageResponse,
    InteractionMessageResponse,
    InteractionMutationResponse,
    InteractionOverviewResponse,
    InteractionOverviewSections,
    InteractionPathIndexItemResponse,
    InteractionPathIndexResponse,
    InteractionPreferencesResponse,
    InteractionReferenceSummaryResponse,
    InteractionReferenceUpdateRequest,
    InteractionSourceObjectResponse,
    InteractionSourceUpdateRequest,
    InteractionStopResponse,
    InteractionTreeBranchPointResponse,
    InteractionTreeResponse,
    InteractionTreeVariantResponse,
    JourneyCreateRequest,
    JourneyDetailResponse,
    JourneyListResponse,
    JourneySummaryResponse,
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

MAX_ACTIVE_STORY_ATTEMPTS = 8
RECENT_MESSAGE_LIMIT = 20
SUMMARY_TRIGGER_TOKENS = 16_000
SEE_SEA_HEARTBEAT_TTL_SECONDS = 60
SEE_SEA_MANUAL_CLAIM_SECONDS = 1


def estimate_story_tokens(text: str) -> int:
    # Conservative for Chinese-heavy prose; exact provider tokenizers remain
    # capability-profile concerns rather than user settings.
    return max(1, (len(text) + 1) // 2)


def path_hash(nodes: list[InteractionMessageNode]) -> str:
    payload = "|".join(str(node.id) for node in nodes)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _summary_compressible_prefix_end(
    nodes: list[InteractionMessageNode],
) -> int:
    """Return the exclusive end of the oldest prefix safe to summarize."""
    if len(nodes) <= 2:
        return 0
    protected_tokens = 0
    index = len(nodes)
    while index > 0 and (
        protected_tokens < SUMMARY_TRIGGER_TOKENS or len(nodes) - index < 2
    ):
        index -= 1
        protected_tokens += max(1, nodes[index].token_estimate)
    if index > 0 and nodes[index].role == "assistant" and nodes[index - 1].role == "user":
        index -= 1
    return index


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} 格式无效") from exc


def _fallback_title(opening_text: str) -> str:
    patterns = (
        r"《([^》]{1,40})》",
        r"(?:进入|来到|身处)([^，。！？\n]{1,30}?)(?:世界|宇宙)",
        r"([^，。！？\n]{1,24}?世界)",
    )
    for pattern in patterns:
        match = re.search(pattern, opening_text)
        if match:
            world = match.group(1).strip("“”\"' ")
            if world:
                return f"{world} · 新旅程"[:255]
    return "新旅程"


class InteractionService:
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
        opening = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=None,
            role="user",
            message_kind="setup",
            content=data.opening_text,
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
        snapshot = await build_project_llm_execution_snapshot(
            db,
            str(journey.novel_id),
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

    async def list_journeys(
        self,
        db: AsyncSession,
        *,
        status: str,
        search: str | None,
        offset: int,
        limit: int,
    ) -> JourneyListResponse:
        if status not in {"active", "archived"}:
            raise ValidationError("status 必须是 active 或 archived")
        owner_id = current_account_id()
        items, total = await self._repo.list_journeys(
            db,
            owner_id=owner_id,
            status=status,
            search=search,
            offset=max(0, offset),
            limit=min(max(1, limit), 50),
        )
        leaf_nodes = await self._repo.get_nodes_for_journey_cards(
            db,
            journeys=items,
            node_ids=[
                journey.selected_leaf_node_id
                for journey in items
                if journey.selected_leaf_node_id is not None
            ],
        )
        parent_nodes = await self._repo.get_nodes_for_journey_cards(
            db,
            journeys=items,
            node_ids=[
                node.parent_node_id
                for node in leaf_nodes.values()
                if node.parent_node_id is not None
            ],
        )
        overview_heads = await self._repo.get_overviews_for_journey_cards(
            db,
            journeys=items,
        )
        selected_attempts = await self._repo.get_attempts_for_journey_cards(
            db,
            owner_id=owner_id,
            journeys=items,
        )
        responses: list[JourneySummaryResponse] = []
        for journey in items:
            selected_attempt = selected_attempts.get(journey.id)
            active_on_path = (
                selected_attempt
                if selected_attempt is not None
                and selected_attempt.status in {"pending", "preparing_context", "running"}
                else None
            )
            current = None
            overview = (
                overview_heads.get(journey.overview_head_revision_id)
                if journey.overview_head_revision_id is not None
                else None
            )
            if overview is not None:
                current = str(
                    (overview.sections or {}).get("current_situation") or ""
                ).strip()
            if not current:
                leaf = (
                    leaf_nodes.get(journey.selected_leaf_node_id)
                    if journey.selected_leaf_node_id is not None
                    else None
                )
                candidate = leaf
                if leaf is not None and leaf.role != "assistant":
                    candidate = (
                        parent_nodes.get(leaf.parent_node_id)
                        if leaf.parent_node_id is not None
                        else None
                    )
                if (
                    candidate is not None
                    and candidate.role == "assistant"
                    and candidate.message_kind == "story"
                ):
                    current = candidate.content
            responses.append(
                JourneySummaryResponse(
                    id=str(journey.id),
                    title=journey.title,
                    title_source=journey.title_source,
                    opening_excerpt=journey.opening_text[:180],
                    status=journey.status,
                    see_sea_enabled=journey.see_sea_enabled,
                    action_options_enabled=journey.action_options_enabled,
                    selection_epoch=journey.selection_epoch,
                    latest_activity_at=journey.latest_activity_at,
                    current_excerpt=current[:240] if current else None,
                    attempt_status=(
                        selected_attempt.status if selected_attempt else None
                    ),
                    active_attempt_id=(
                        str(active_on_path.id) if active_on_path else None
                    ),
                    source=(
                        await self._sources.journey_source_response(
                            db,
                            revision_id=journey.source_revision_id,
                            anchor=journey.source_anchor,
                            player_identity=journey.player_identity,
                            source_context_epoch=journey.source_context_epoch,
                        )
                        if journey.source_revision_id
                        else None
                    ),
                )
            )
        return JourneyListResponse(items=responses, total=total)

    async def get_journey(
        self,
        db: AsyncSession,
        journey_id: str,
        *,
        status: str | None = "active",
    ) -> JourneyDetailResponse:
        journey = await self._owned_journey(
            db,
            journey_id,
            status=status,
            for_update=False,
            require_project=status == "active",
        )
        return await self._detail(db, journey)

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
                item and self._sources._reference_visible(target, item, target_anchor)
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
        revision = await self._sources.require_ready_revision(
            db, journey.source_revision_id
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
            if not self._sources._reference_visible(
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
        self._repo.touch(journey)
        await db.flush()
        return await self.get_reference_summary(db, journey_id=journey_id)

    async def get_reference_summary(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionReferenceSummaryResponse:
        journey = await self._owned_journey(db, journey_id)
        if journey.source_revision_id is None:
            raise ConflictError("该旅程未使用作品资料")
        revision = await self._sources.require_ready_revision(
            db, journey.source_revision_id
        )
        references = {
            item["reference_key"]: item for item in revision.reference_manifest or []
        }
        policy = journey.reference_policy or {}

        def objects(keys: list[str]) -> list[InteractionSourceObjectResponse]:
            return [
                self._sources._object_response(references[key])
                for key in keys
                if key in references
            ]

        latest = None
        if journey.selected_leaf_node_id:
            latest = await self._repo.get_latest_attempt_for_selected_leaf(
                db,
                journey=journey,
                response_to_node_id=journey.selected_leaf_node_id,
            )
        return InteractionReferenceSummaryResponse(
            source=await self._sources.journey_source_response(
                db,
                revision_id=journey.source_revision_id,
                anchor=journey.source_anchor,
                player_identity=journey.player_identity,
                source_context_epoch=journey.source_context_epoch,
            ),
            pinned=objects(list(policy.get("pinned") or [])),
            excluded=objects(list(policy.get("excluded") or [])),
            last_used=[
                {
                    "label": str(item.get("label") or "作品资料"),
                    "reason": str(item.get("reason") or "原文片段关联"),
                }
                for item in (latest.reference_trace if latest else [])
            ],
        )

    async def get_message_page(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        before_node_id: str | None,
        around_node_id: str | None = None,
        limit: int,
    ) -> InteractionMessagePageResponse:
        journey = await self._owned_journey(db, journey_id)
        path = [
            node
            for node in await self._repo.get_selected_path(db, journey=journey)
            if node.message_kind == "story"
        ]
        if before_node_id and around_node_id:
            raise ValidationError("不能同时指定两个阅读位置")
        end = len(path)
        start = 0
        size = min(max(1, limit), 50)
        ids = [node.id for node in path]
        if around_node_id:
            parsed = _parse_uuid(around_node_id, "around_node_id")
            if parsed not in ids:
                raise ConflictError("该阅读位置不在当前发展中")
            center = ids.index(parsed)
            start = max(0, center - (size // 2))
            end = min(len(path), start + size)
            start = max(0, end - size)
        if before_node_id:
            parsed = _parse_uuid(before_node_id, "before_node_id")
            if parsed not in ids:
                raise ConflictError("该阅读位置不在当前发展中")
            end = ids.index(parsed)
            start = max(0, end - size)
        elif not around_node_id:
            start = max(0, end - size)
        return InteractionMessagePageResponse(
            items=[self._message_response(node) for node in path[start:end]],
            has_more=start > 0,
            has_older=start > 0,
            has_newer=end < len(path),
            selection_epoch=journey.selection_epoch,
        )

    async def get_path_index(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionPathIndexResponse:
        journey = await self._owned_journey(db, journey_id)
        nodes = [
            node
            for node in await self._repo.get_selected_path(db, journey=journey)
            if node.message_kind == "story" and node.role == "assistant"
        ]
        total = len(nodes)
        return InteractionPathIndexResponse(
            selection_epoch=journey.selection_epoch,
            items=[
                InteractionPathIndexItemResponse(
                    id=str(node.id),
                    ordinal=index,
                    total=total,
                    excerpt=self._locator_excerpt(node),
                    completion_state=node.completion_state,
                )
                for index, node in enumerate(nodes, start=1)
            ],
        )

    async def send_message(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        content: str,
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
        selected_path = await self._repo.get_selected_path(db, journey=journey)
        if not selected_path:
            raise ConflictError("当前发展不存在")
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
    ) -> InteractionMutationResponse:
        """Explicitly branch from the client's still-visible old position."""
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
        branch_point = await self._required_node(db, journey, node_id)
        ancestry = await self._repo.get_ancestry(
            db,
            journey=journey,
            node=branch_point,
        )
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

    async def get_attempt_state(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        attempt_id: str,
    ) -> InteractionAttemptResponse:
        journey = await self._owned_journey(
            db,
            journey_id,
            status=None,
            require_project=False,
        )
        attempt = await self._required_attempt(
            db,
            journey,
            attempt_id,
            for_update=False,
        )
        return self._attempt_response(attempt)

    async def list_generation_records(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionGenerationRecordListResponse:
        journey = await self._owned_journey(
            db,
            journey_id,
            status=None,
            require_project=False,
        )
        records = await self._repo.list_unadopted_failure_records(
            db,
            journey=journey,
        )
        return InteractionGenerationRecordListResponse(
            items=[self._attempt_response(record) for record in records]
        )

    async def edit_user_message(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        user_node_id: str,
        content: str,
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
        original = await self._required_node(db, journey, user_node_id)
        if original.role != "user":
            raise ValidationError("第一版只能修改自己的输入")
        selected_path = await self._repo.get_selected_path(db, journey=journey)
        selected_ids = [node.id for node in selected_path]
        if original.id not in selected_ids:
            raise ConflictError("请先切换到这个发展再修改")
        original_index = selected_ids.index(original.id)
        prefix = selected_path[:original_index]
        edited = InteractionMessageNode(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            parent_node_id=original.parent_node_id,
            role="user",
            message_kind=original.message_kind,
            content=content,
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
        if active_overview is None and self._story_started(path):
            try:
                snapshot = await build_project_llm_execution_snapshot(
                    db,
                    str(journey.novel_id),
                )
                await self._enqueue_overview_refresh(
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

    async def list_branches(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        node_id: str,
    ) -> InteractionBranchListResponse:
        journey = await self._owned_journey(db, journey_id)
        node = await self._required_node(db, journey, node_id)
        siblings = await self._repo.list_children(
            db,
            journey=journey,
            parent_node_id=node.parent_node_id,
        )
        selected_path = await self._repo.get_selected_path(db, journey=journey)
        selected_ids = {item.id for item in selected_path}
        total = len(siblings)
        return InteractionBranchListResponse(
            parent_node_id=str(node.parent_node_id) if node.parent_node_id else None,
            variants=[
                InteractionBranchVariantResponse(
                    node_id=str(item.id),
                    selected=item.id in selected_ids,
                    ordinal=index,
                    total=total,
                    excerpt=item.branch_hint or self._branch_hint(item.content) or "",
                    created_at=item.created_at,
                )
                for index, item in enumerate(siblings, start=1)
            ],
        )

    async def get_tree(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionTreeResponse:
        journey = await self._owned_journey(db, journey_id)
        nodes = await self._repo.list_tree_nodes(db, journey=journey)
        selected = {
            node.id for node in await self._repo.get_selected_path(db, journey=journey)
        }
        by_id = {node.id: node for node in nodes}
        children: dict[uuid.UUID | None, list[InteractionMessageNode]] = {}
        for node in nodes:
            children.setdefault(node.parent_node_id, []).append(node)

        def continuation_count(node: InteractionMessageNode) -> int:
            count = 0
            current = node
            seen: set[uuid.UUID] = set()
            while current.id not in seen:
                seen.add(current.id)
                next_nodes = children.get(current.id, [])
                if len(next_nodes) != 1:
                    break
                current = next_nodes[0]
                if current.role == "assistant" and current.message_kind == "story":
                    count += 1
            return count

        branch_points: list[InteractionTreeBranchPointResponse] = []
        for parent_id, variants in children.items():
            if len(variants) < 2:
                continue
            parent = by_id.get(parent_id) if parent_id else None
            branch_points.append(
                InteractionTreeBranchPointResponse(
                    parent_node_id=str(parent_id) if parent_id else None,
                    label=(
                        self._branch_hint(parent.content)
                        if parent is not None
                        else "旅程开场"
                    )
                    or "这里出现了不同发展",
                    variants=[
                        InteractionTreeVariantResponse(
                            node_id=str(item.id),
                            selected=item.id in selected,
                            excerpt=(
                                item.branch_hint
                                or self._branch_hint(item.content)
                                or "未命名的发展"
                            ),
                            continuation_count=continuation_count(item),
                        )
                        for item in variants
                    ],
                )
            )
        return InteractionTreeResponse(
            branch_points=branch_points,
        )

    async def get_preferences(
        self,
        db: AsyncSession,
    ) -> InteractionPreferencesResponse:
        owner_id = current_account_id()
        preference = await self._repo.get_account_preference(
            db,
            owner_id=owner_id,
        )
        return InteractionPreferencesResponse(
            see_sea_notice_acknowledged=bool(
                preference and preference.see_sea_notice_acknowledged
            )
        )

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
        task_id = enqueue_task(
            db,
            "interaction_story_generate",
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
    ) -> InteractionMutationResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        self._check_epoch(journey, expected_selection_epoch)
        if see_sea_enabled is not None:
            journey.see_sea_enabled = see_sea_enabled
            journey.see_sea_last_heartbeat_at = (
                datetime.now(UTC) if see_sea_enabled else None
            )
        if action_options_enabled is not None:
            journey.action_options_enabled = action_options_enabled
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

    async def get_overview(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionOverviewResponse:
        journey = await self._owned_journey(db, journey_id)
        head = await self._repo.get_overview_head(db, journey=journey)
        path = await self._repo.get_selected_path(db, journey=journey)
        if head is not None:
            ids = [node.id for node in path]
            if head.anchor_node_id not in ids:
                head = None
            else:
                anchor_index = ids.index(head.anchor_node_id)
                if path_hash(path[: anchor_index + 1]) != head.path_hash:
                    head = None
        latest_task = await get_latest_coalesced_task(
            db,
            task_type="interaction_summary_refresh",
            novel_id=str(journey.novel_id),
            scope=("interaction_summary", str(journey.id)),
        )
        refreshing = latest_task is not None and latest_task.status in {
            "pending",
            "running",
        }
        failed = self._overview_failure_applies(journey, path)
        status = (
            "refreshing"
            if refreshing
            else ("failed" if failed else ("ready" if head is not None else "forming"))
        )
        return InteractionOverviewResponse(
            sections=InteractionOverviewSections.model_validate(
                head.sections if head else {}
            ),
            source=head.source if head else "automatic",
            overview_epoch=journey.overview_epoch,
            anchor_node_id=(str(self._overview_coverage_anchor(head)) if head else None),
            updated_at=head.created_at if head else None,
            is_refreshing=refreshing,
            status=status,
            base_revision_id=str(head.id) if head else None,
            base_selected_leaf_node_id=(
                str(path[-1].id) if head is not None and path else None
            ),
            base_selected_path_hash=(
                path_hash(path) if head is not None and path else None
            ),
        )

    async def update_overview(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        sections: InteractionOverviewSections,
        expected_overview_epoch: int,
        expected_selection_epoch: int,
        base_revision_id: str | None = None,
        base_selected_leaf_node_id: str | None = None,
        base_selected_path_hash: str | None = None,
    ) -> InteractionOverviewResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        if (
            expected_selection_epoch > journey.selection_epoch
            or expected_overview_epoch > journey.overview_epoch
        ):
            raise ConflictError(
                "旅程在别处发生了变化",
                code="interaction_overview_conflict",
            )
        path = await self._repo.get_selected_path(db, journey=journey)
        if not path:
            raise ConflictError("当前发展不存在")
        if (
            base_revision_id is None
            or base_selected_leaf_node_id is None
            or base_selected_path_hash is None
        ):
            # Internal callers written before browser edit-context fencing use
            # the current head. The public request schema always supplies all
            # three frozen values.
            current_head = await self._repo.get_overview_head(
                db,
                journey=journey,
            )
            if current_head is None:
                if (
                    journey.selection_epoch != expected_selection_epoch
                    or journey.overview_epoch != expected_overview_epoch
                ):
                    raise ConflictError(
                        "旅程在别处发生了变化",
                        code="interaction_overview_conflict",
                    )
                revision = InteractionOverviewRevision(
                    novel_id=journey.novel_id,
                    journey_id=journey.id,
                    anchor_node_id=path[-1].id,
                    path_hash=path_hash(path),
                    coverage_anchor_node_id=path[-1].id,
                    coverage_path_hash=path_hash(path),
                    sections=sections.model_dump(),
                    source="manual",
                    based_on_revision_id=None,
                    started_overview_epoch=journey.overview_epoch,
                    promoted=True,
                    producer={"kind": "user"},
                )
                db.add(revision)
                await db.flush()
                journey.overview_head_revision_id = revision.id
                journey.overview_epoch += 1
                self._repo.touch(journey)
                return InteractionOverviewResponse(
                    sections=InteractionOverviewSections.model_validate(
                        revision.sections
                    ),
                    source=revision.source,
                    overview_epoch=journey.overview_epoch,
                    anchor_node_id=str(revision.anchor_node_id),
                    updated_at=revision.created_at,
                    status="ready",
                    base_revision_id=str(revision.id),
                    base_selected_leaf_node_id=str(path[-1].id),
                    base_selected_path_hash=path_hash(path),
                )
            base_revision_id = str(current_head.id)
            base_selected_leaf_node_id = str(path[-1].id)
            base_selected_path_hash = path_hash(path)
        base_leaf_id = _parse_uuid(
            base_selected_leaf_node_id,
            "base_selected_leaf_node_id",
        )
        current_ids = [node.id for node in path]
        if base_leaf_id not in current_ids:
            raise ConflictError(
                "旅程在别处发生了变化",
                code="interaction_overview_conflict",
            )
        base_leaf_index = current_ids.index(base_leaf_id)
        original_path = path[: base_leaf_index + 1]
        if path_hash(original_path) != base_selected_path_hash:
            raise ConflictError(
                "旅程在别处发生了变化",
                code="interaction_overview_conflict",
            )
        base_revision = await self._repo.get_overview_revision(
            db,
            journey=journey,
            revision_id=_parse_uuid(base_revision_id, "base_revision_id"),
        )
        if base_revision is None or not self._overview_matches_path(
            base_revision, original_path
        ):
            raise ConflictError(
                "旅程在别处发生了变化",
                code="interaction_overview_conflict",
            )
        previous = await self._repo.get_overview_head(db, journey=journey)
        if previous is None or not await self._automatic_overview_descends_from(
            db,
            journey=journey,
            current=previous,
            base=base_revision,
        ):
            raise ConflictError(
                "回顾已在别处手动修改",
                code="interaction_overview_conflict",
            )
        previous.promoted = False
        revision = InteractionOverviewRevision(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            anchor_node_id=base_leaf_id,
            path_hash=base_selected_path_hash,
            coverage_anchor_node_id=self._overview_coverage_anchor(base_revision),
            coverage_path_hash=self._overview_coverage_hash(base_revision),
            sections=sections.model_dump(),
            source="manual",
            based_on_revision_id=base_revision.id,
            started_overview_epoch=journey.overview_epoch,
            promoted=True,
            producer={"kind": "user"},
        )
        db.add(revision)
        await db.flush()
        journey.overview_head_revision_id = revision.id
        journey.overview_epoch += 1
        self._repo.touch(journey)
        enqueued = False
        if await self._overview_refresh_is_due(db, journey=journey, path=path):
            try:
                snapshot = await build_project_llm_execution_snapshot(
                    db,
                    str(journey.novel_id),
                )
                await self._enqueue_overview_refresh(
                    db,
                    journey=journey,
                    path=path,
                    snapshot=snapshot,
                )
                enqueued = True
            except ProjectLLMConfigurationError:
                # The user's correction is valid without a connected model. The
                # uncovered raw tail remains in story compilation until a later
                # automatic refresh can absorb it.
                pass
        return InteractionOverviewResponse(
            sections=InteractionOverviewSections.model_validate(revision.sections),
            source=revision.source,
            overview_epoch=journey.overview_epoch,
            anchor_node_id=str(self._overview_coverage_anchor(revision)),
            updated_at=revision.created_at,
            is_refreshing=enqueued,
            status="refreshing" if enqueued else "ready",
            base_revision_id=str(revision.id),
            base_selected_leaf_node_id=str(path[-1].id),
            base_selected_path_hash=path_hash(path),
        )

    async def retry_overview(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionOverviewResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        path = await self._repo.get_selected_path(db, journey=journey)
        if not self._story_started(path):
            raise ConflictError("故事开始后才会形成回顾")
        if not self._overview_failure_applies(journey, path):
            raise ConflictError("当前回顾不需要重新整理")
        snapshot = await build_project_llm_execution_snapshot(
            db,
            str(journey.novel_id),
        )
        await self._enqueue_overview_refresh(
            db,
            journey=journey,
            path=path,
            snapshot=snapshot,
        )
        journey.overview_failure = {}
        return await self.get_overview(db, journey_id=journey_id)

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

    async def export_journey(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        format_name: str,
        story_only: bool,
        include_overview: bool,
    ) -> tuple[str, str, str]:
        journey = await self._owned_journey(
            db,
            journey_id,
            status=None,
            require_project=False,
        )
        path = await self._repo.get_selected_path(db, journey=journey)
        lines: list[str] = []
        if story_only:
            for node in path:
                if node.role == "assistant" and node.message_kind == "story":
                    lines.extend([node.content, ""])
        else:
            lines.extend([f"# {journey.title}", ""])
            setup_nodes = [node for node in path if node.message_kind == "setup"]
            if setup_nodes:
                lines.extend(["## 开场设定", ""])
                for node in setup_nodes:
                    label = "我" if node.role == "user" else "开场说明"
                    lines.extend([f"### {label}", "", node.content, ""])
        for node in path:
            if story_only or node.message_kind != "story":
                continue
            label = "我" if node.role == "user" else "故事"
            suffix = "（保留的未完整片段）" if node.completion_state == "partial" else ""
            lines.extend([f"## {label}{suffix}", "", node.content, ""])
        if include_overview and not story_only:
            head = await self._repo.get_overview_head(db, journey=journey)
            if head is not None and self._overview_matches_path(head, path):
                lines.extend(
                    [
                        "## 当前回顾",
                        "",
                        render_overview_sections(head.sections),
                        "",
                    ]
                )
        content = "\n".join(lines).rstrip() + "\n"
        safe_title = re.sub(r"[/\\\\:*?\"<>|]", "_", journey.title)[:80] or "旅程"
        if format_name == "txt":
            content = re.sub(r"^#{1,6} ", "", content, flags=re.MULTILINE)
            return f"{safe_title}.txt", "text/plain; charset=utf-8", content
        if format_name != "md":
            raise ValidationError("导出格式必须是 md 或 txt")
        return f"{safe_title}.md", "text/markdown; charset=utf-8", content

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

    async def _ensure_no_active_attempt(
        self,
        db: AsyncSession,
        journey: InteractionJourney,
    ) -> None:
        if await self._repo.get_active_attempt(db, journey=journey) is not None:
            raise ConflictError("这个旅程已有一段故事正在生成")

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
        snapshot = await build_project_llm_execution_snapshot(
            db,
            str(journey.novel_id),
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
        db.add(attempt)
        await db.flush()
        task_id = enqueue_task(
            db,
            "interaction_story_generate",
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
        return {
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "attempt_id": str(attempt.id),
            "llm_execution_snapshot": dict(attempt.llm_execution_snapshot or {}),
        }

    async def _try_start_see_sea(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        context_nodes: list[InteractionMessageNode],
        response_to: InteractionMessageNode,
    ) -> InteractionGenerationAttempt | None:
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
        snapshot = await build_project_llm_execution_snapshot(
            db,
            str(journey.novel_id),
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
        task_id = enqueue_task(
            db,
            "interaction_story_generate",
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
                task_types={"interaction_story_generate"},
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
            self._repo.touch(journey)
            repaired += 1
        if repaired:
            await db.flush()
        return repaired

    async def _detail(
        self,
        db: AsyncSession,
        journey: InteractionJourney,
    ) -> JourneyDetailResponse:
        path = await self._repo.get_selected_path(db, journey=journey)
        setup = [node for node in path if node.message_kind == "setup"]
        story = [node for node in path if node.message_kind == "story"]
        recent = story[-RECENT_MESSAGE_LIMIT:]
        active = await self._repo.get_active_attempt(db, journey=journey)
        if active is None and path:
            latest = await self._repo.get_latest_attempt_for_selected_leaf(
                db,
                journey=journey,
                response_to_node_id=path[-1].id,
            )
            if latest is not None and latest.status in {
                "awaiting_continue",
                "failed",
                "cancelled",
            }:
                active = latest
        return JourneyDetailResponse(
            id=str(journey.id),
            title=journey.title,
            title_source=journey.title_source,
            opening_text=journey.opening_text,
            status=journey.status,
            see_sea_enabled=journey.see_sea_enabled,
            action_options_enabled=journey.action_options_enabled,
            selection_epoch=journey.selection_epoch,
            overview_epoch=journey.overview_epoch,
            selected_leaf_node_id=(
                str(journey.selected_leaf_node_id)
                if journey.selected_leaf_node_id
                else None
            ),
            setup_messages=[self._message_response(node) for node in setup],
            messages=[self._message_response(node) for node in recent],
            has_older_messages=len(story) > len(recent),
            active_attempt=self._attempt_response(active) if active else None,
            source=(
                await self._sources.journey_source_response(
                    db,
                    revision_id=journey.source_revision_id,
                    anchor=journey.source_anchor,
                    player_identity=journey.player_identity,
                    source_context_epoch=journey.source_context_epoch,
                )
                if journey.source_revision_id
                else None
            ),
        )

    @staticmethod
    def _message_response(
        node: InteractionMessageNode,
    ) -> InteractionMessageResponse:
        suggestions: list[InteractionActionSuggestion] = []
        for value in node.action_suggestions or []:
            try:
                suggestions.append(InteractionActionSuggestion.model_validate(value))
            except ValueError:
                continue
        return InteractionMessageResponse(
            id=str(node.id),
            parent_node_id=str(node.parent_node_id) if node.parent_node_id else None,
            role=node.role,
            message_kind=node.message_kind,
            content=node.content,
            completion_state=node.completion_state,
            end_reason=node.end_reason,
            branch_hint=node.branch_hint or InteractionService._branch_hint(node.content),
            story_ended=node.story_ended,
            action_suggestions=suggestions[:3],
            created_at=node.created_at,
        )

    @staticmethod
    def _attempt_response(
        attempt: InteractionGenerationAttempt,
    ) -> InteractionAttemptResponse:
        return InteractionAttemptResponse(
            id=str(attempt.id),
            journey_id=str(attempt.journey_id),
            task_id=str(attempt.task_id) if attempt.task_id else None,
            response_to_node_id=str(attempt.response_to_node_id),
            status=attempt.status,
            visible_text=attempt.visible_text,
            visible_offset=attempt.visible_offset,
            finish_reason=attempt.finish_reason,
            error_kind=attempt.error_kind,
            error_message=attempt.error_message,
            result_node_id=(
                str(attempt.result_node_id) if attempt.result_node_id else None
            ),
            references=[
                {
                    "label": str(item.get("label") or "作品资料"),
                    "reason": str(item.get("reason") or "原文片段关联"),
                }
                for item in attempt.reference_trace or []
            ],
            created_at=attempt.created_at,
        )

    @staticmethod
    def _branch_hint(content: str) -> str | None:
        compact = re.sub(r"\s+", " ", content).strip()
        if not compact:
            return None
        first = re.split(r"(?<=[。！？!?])", compact, maxsplit=1)[0]
        return first[:40]

    @staticmethod
    def _locator_excerpt(node: InteractionMessageNode) -> str:
        compact = re.sub(r"\s+", " ", node.content).strip()
        excerpt = compact[:40]
        if node.completion_state == "partial":
            return f"未完整 · {excerpt}"
        return excerpt

    @staticmethod
    def _overview_matches_path(
        overview: InteractionOverviewRevision,
        path: list[InteractionMessageNode],
    ) -> bool:
        ids = [node.id for node in path]
        if overview.anchor_node_id not in ids:
            return False
        anchor_index = ids.index(overview.anchor_node_id)
        return path_hash(path[: anchor_index + 1]) == overview.path_hash

    @staticmethod
    def _overview_coverage_anchor(
        overview: InteractionOverviewRevision,
    ) -> uuid.UUID:
        return overview.coverage_anchor_node_id or overview.anchor_node_id

    @staticmethod
    def _overview_coverage_hash(
        overview: InteractionOverviewRevision,
    ) -> str:
        return overview.coverage_path_hash or overview.path_hash

    @classmethod
    def _overview_coverage_matches_path(
        cls,
        overview: InteractionOverviewRevision,
        path: list[InteractionMessageNode],
    ) -> bool:
        anchor = cls._overview_coverage_anchor(overview)
        ids = [node.id for node in path]
        if anchor not in ids:
            return False
        anchor_index = ids.index(anchor)
        return path_hash(path[: anchor_index + 1]) == cls._overview_coverage_hash(
            overview
        )

    @staticmethod
    def _overview_failure_applies(
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> bool:
        failure = dict(journey.overview_failure or {})
        failed_hash = str(failure.get("path_hash") or "")
        anchor_value = failure.get("anchor_node_id")
        if anchor_value:
            try:
                anchor_id = uuid.UUID(str(anchor_value))
            except (TypeError, ValueError):
                return False
            ids = [node.id for node in path]
            if anchor_id not in ids or not failed_hash:
                return False
            anchor_index = ids.index(anchor_id)
            return path_hash(path[: anchor_index + 1]) == failed_hash
        node_ids = [str(value) for value in (failure.get("node_ids") or [])]
        if not node_ids or not failed_hash or len(path) < len(node_ids):
            return False
        prefix = path[: len(node_ids)]
        return [str(node.id) for node in prefix] == node_ids and path_hash(
            prefix
        ) == failed_hash

    async def _best_overview_for_path(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> InteractionOverviewRevision | None:
        positions = {node.id: index for index, node in enumerate(path)}
        candidates = await self._repo.list_overview_revisions_for_anchors(
            db,
            journey=journey,
            anchor_node_ids=list(positions),
        )
        valid = [
            candidate
            for candidate in candidates
            if path_hash(path[: positions[candidate.anchor_node_id] + 1])
            == candidate.path_hash
        ]
        manuals = [candidate for candidate in valid if candidate.source == "manual"]
        latest_manual = max(
            manuals,
            key=lambda candidate: candidate.started_overview_epoch,
            default=None,
        )
        if latest_manual is not None:
            compatible = []
            for candidate in valid:
                if candidate.id == latest_manual.id or (
                    candidate.source == "automatic"
                    and await self._automatic_overview_descends_from(
                        db,
                        journey=journey,
                        current=candidate,
                        base=latest_manual,
                    )
                ):
                    compatible.append(candidate)
            valid = compatible
        best = None
        best_key = (-1, -1)
        for candidate in valid:
            position = positions[candidate.anchor_node_id]
            key = (position, candidate.started_overview_epoch)
            if key <= best_key:
                continue
            best = candidate
            best_key = key
        return best

    async def _activate_best_overview_head(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> InteractionOverviewRevision | None:
        current = await self._repo.get_overview_head(db, journey=journey)
        best = await self._best_overview_for_path(
            db,
            journey=journey,
            path=path,
        )
        if current is None and best is None:
            return None
        if current is not None and best is not None and current.id == best.id:
            return current
        if current is not None:
            current.promoted = False
        if best is not None:
            best.promoted = True
            journey.overview_head_revision_id = best.id
        else:
            journey.overview_head_revision_id = None
        journey.overview_epoch += 1
        return best

    async def _automatic_overview_descends_from(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        current: InteractionOverviewRevision,
        base: InteractionOverviewRevision,
    ) -> bool:
        candidate = current
        seen: set[uuid.UUID] = set()
        for _ in range(1000):
            if candidate.id == base.id:
                return True
            if candidate.id in seen or candidate.source != "automatic":
                return False
            seen.add(candidate.id)
            if candidate.based_on_revision_id is None:
                return False
            parent = await self._repo.get_overview_revision(
                db,
                journey=journey,
                revision_id=candidate.based_on_revision_id,
            )
            if parent is None:
                return False
            candidate = parent
        return False

    async def _overview_manual_ancestor(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        current: InteractionOverviewRevision,
    ) -> InteractionOverviewRevision | None:
        candidate = current
        seen: set[uuid.UUID] = set()
        for _ in range(1000):
            if candidate.source == "manual":
                return candidate
            if (
                candidate.id in seen
                or candidate.source != "automatic"
                or candidate.based_on_revision_id is None
            ):
                return None
            seen.add(candidate.id)
            parent = await self._repo.get_overview_revision(
                db,
                journey=journey,
                revision_id=candidate.based_on_revision_id,
            )
            if parent is None:
                return None
            candidate = parent
        return None

    async def _enqueue_overview_refresh(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
        snapshot: dict,
    ) -> str:
        contract = await enqueue_coalesced_task(
            db,
            task_type="interaction_summary_refresh",
            novel_id=str(journey.novel_id),
            scope=("interaction_summary", str(journey.id)),
            mode="one_pending_follower",
            meta={
                "novel_id": str(journey.novel_id),
                "journey_id": str(journey.id),
                "path_hash": path_hash(path),
                "selected_leaf_node_id": str(path[-1].id),
                "started_overview_epoch": journey.overview_epoch,
                "llm_execution_snapshot": dict(snapshot),
            },
        )
        return contract.task_id

    async def _overview_refresh_is_due(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> bool:
        if not self._story_started(path) or self._overview_failure_applies(
            journey,
            path,
        ):
            return False
        head = await self._repo.get_overview_head(db, journey=journey)
        start_index = 0
        if (
            head is not None
            and self._overview_matches_path(head, path)
            and self._overview_coverage_matches_path(head, path)
        ):
            current_ids = [node.id for node in path]
            coverage_index = current_ids.index(self._overview_coverage_anchor(head))
            start_index = coverage_index + 1
        uncovered = path[start_index:]
        prefix_end = _summary_compressible_prefix_end(uncovered)
        return (
            sum(node.token_estimate for node in uncovered[:prefix_end])
            >= SUMMARY_TRIGGER_TOKENS
        )

    async def _maybe_enqueue_overview_after_formalization(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        snapshot: dict,
    ) -> str | None:
        path = await self._repo.get_selected_path(db, journey=journey)
        await self._activate_best_overview_head(
            db,
            journey=journey,
            path=path,
        )
        if not await self._overview_refresh_is_due(
            db,
            journey=journey,
            path=path,
        ):
            return None
        return await self._enqueue_overview_refresh(
            db,
            journey=journey,
            path=path,
            snapshot=snapshot,
        )

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

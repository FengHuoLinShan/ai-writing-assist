"""journey views operations for InteractionService."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import ConflictError, ValidationError
from modules.account.facade import current_account_id, is_anonymous_rp_principal
from modules.interaction.framing import visible_story_content
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
)
from modules.interaction.prompts import render_overview_sections
from modules.interaction.schemas import (
    InteractionActionSuggestion,
    InteractionAttemptResponse,
    InteractionBranchListResponse,
    InteractionBranchVariantResponse,
    InteractionGenerationRecordListResponse,
    InteractionMessagePageResponse,
    InteractionMessageResponse,
    InteractionPathIndexItemResponse,
    InteractionPathIndexResponse,
    InteractionPreferencesResponse,
    InteractionReferenceSummaryResponse,
    InteractionSourceObjectResponse,
    InteractionTreeBranchPointResponse,
    InteractionTreeResponse,
    InteractionTreeVariantResponse,
    JourneyDetailResponse,
    JourneyListResponse,
    JourneySummaryResponse,
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


class JourneyViewsMixin:
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
        source_requests = [
            {
                "revision_id": journey.source_revision_id,
                "anchor": journey.source_anchor,
                "player_identity": journey.player_identity,
                "source_context_epoch": journey.source_context_epoch,
            }
            for journey in items
            if journey.source_revision_id
        ]
        source_responses = (
            [
                await self._sources.public_demo_journey_source_response(
                    db,
                    revision_id=request["revision_id"],
                    anchor=request["anchor"],
                    player_identity=request["player_identity"],
                    source_context_epoch=request["source_context_epoch"],
                )
                for request in source_requests
            ]
            if is_anonymous_rp_principal()
            else await self._sources.journey_source_responses(db, source_requests)
        )
        responses: list[JourneySummaryResponse] = []
        source_index = 0
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
                    web_search_enabled=journey.web_search_enabled,
                    generation_mode=journey.generation_mode,
                    ensemble_available=bool(
                        get_settings().interaction_team_enabled
                        and journey.source_revision_id
                        and not is_anonymous_rp_principal()
                    ),
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
                        # 两个列表必须同序:source_requests 按 source-bound 旅程
                        # 出现顺序构造,这里逐个消费。
                        source_responses[source_index]
                        if journey.source_revision_id
                        else None
                    ),
                )
            )
            if journey.source_revision_id:
                source_index += 1
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

    async def get_reference_summary(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionReferenceSummaryResponse:
        journey = await self._owned_journey(db, journey_id)
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
            source=(
                await self._sources.public_demo_journey_source_response(
                    db,
                    revision_id=journey.source_revision_id,
                    anchor=journey.source_anchor,
                    player_identity=journey.player_identity,
                    source_context_epoch=journey.source_context_epoch,
                )
                if is_anonymous_rp_principal()
                else await self._sources.journey_source_response(
                    db,
                    revision_id=journey.source_revision_id,
                    anchor=journey.source_anchor,
                    player_identity=journey.player_identity,
                    source_context_epoch=journey.source_context_epoch,
                )
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
                    lines.extend([visible_story_content(node.content), ""])
        else:
            lines.extend([f"# {journey.title}", ""])
            setup_nodes = [node for node in path if node.message_kind == "setup"]
            if setup_nodes:
                lines.extend(["## 开场设定", ""])
                for node in setup_nodes:
                    label = "我" if node.role == "user" else "开场说明"
                    lines.extend(
                        [
                            f"### {label}",
                            "",
                            visible_story_content(node.content)
                            if node.role == "assistant"
                            else node.content,
                            "",
                        ]
                    )
        for node in path:
            if story_only or node.message_kind != "story":
                continue
            label = "我" if node.role == "user" else "故事"
            suffix = "（保留的未完整片段）" if node.completion_state == "partial" else ""
            lines.extend(
                [
                    f"## {label}{suffix}",
                    "",
                    visible_story_content(node.content)
                    if node.role == "assistant"
                    else node.content,
                    "",
                ]
            )
        if include_overview and not story_only:
            head = await self._repo.get_overview_head(db, journey=journey)
            if head is not None and self._overview_matches_path(head, path):
                lines.extend(
                    [
                        "## 当前回顾",
                        "",
                        "\n\n".join(
                            filter(
                                None,
                                [
                                    ("长期约定\n" + head.sections["long_term_agreements"])
                                    if head.sections.get("long_term_agreements")
                                    else "",
                                    render_overview_sections(head.sections),
                                ],
                            )
                        ),
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
        cast_keys = []
        if journey.generation_mode == "ensemble" and journey.source_revision_id:
            from modules.interaction.ensemble import selected_actor_states
            from modules.interaction.ensemble_v2 import restore_environment

            actor_states = await selected_actor_states(
                db, journey, path, journey.source_revision_id
            )
            participants = set(
                restore_environment(actor_states, path).get("participants", [])
            )
            cast_keys = [
                row.state_json["reference_key"]
                for row in actor_states.values()
                if row.state_json.get("reference_key")
                and str(row.actor_id) in participants
            ]
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
            novel_id=str(journey.novel_id),
            title=journey.title,
            title_source=journey.title_source,
            opening_text=journey.opening_text,
            status=journey.status,
            see_sea_enabled=journey.see_sea_enabled,
            action_options_enabled=journey.action_options_enabled,
            web_search_enabled=journey.web_search_enabled,
            generation_mode=journey.generation_mode,
            ensemble_protocol="observation_v2"
            if get_settings().collaboration_v2_enabled
            else "team_v1",
            ensemble_cast_keys=cast_keys,
            ensemble_available=bool(
                get_settings().interaction_team_enabled
                and journey.source_revision_id
                and not is_anonymous_rp_principal()
            ),
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
                (
                    await self._sources.public_demo_journey_source_response(
                        db,
                        revision_id=journey.source_revision_id,
                        anchor=journey.source_anchor,
                        player_identity=journey.player_identity,
                        source_context_epoch=journey.source_context_epoch,
                    )
                    if is_anonymous_rp_principal()
                    else await self._sources.journey_source_response(
                        db,
                        revision_id=journey.source_revision_id,
                        anchor=journey.source_anchor,
                        player_identity=journey.player_identity,
                        source_context_epoch=journey.source_context_epoch,
                    )
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
            content=visible_story_content(node.content)
            if node.role == "assistant"
            else node.content,
            completion_state=node.completion_state,
            end_reason=node.end_reason,
            branch_hint=node.branch_hint or JourneyViewsMixin._branch_hint(node.content),
            story_ended=node.story_ended,
            action_suggestions=suggestions[:3],
            input_kind=(node.input_json or {}).get("kind"),
            ensemble_cast_keys=(node.input_json or {}).get("cast_keys"),
            whisper_to=(node.input_json or {}).get("whisper_to", []),
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
            local_agent={
                "kind": attempt.llm_execution_snapshot["local_agent"]["kind"],
                "approved": bool(
                    (attempt.agent_checkpoint_json or {}).get("local_approved")
                ),
            }
            if (attempt.llm_execution_snapshot or {}).get("local_agent")
            else None,
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

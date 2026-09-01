"""Reusable, version-pinned author-project sources for RP journeys."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.facade import (
    get_latest_coalesced_task,
    list_task_lifecycle_contracts,
)
from modules.account.facade import current_account_id
from modules.evidence.facade import (
    VisibilityContextContract,
    get_manifest_entity_appearances,
    get_manifest_index_coverage,
    trace_novel_evidence,
)
from modules.imports.facade import resume_deep_import, start_deep_import
from modules.interaction.models import InteractionSourceRevision
from modules.interaction.repositories import InteractionRepository
from modules.interaction.schemas import (
    InteractionJourneySourceResponse,
    InteractionSourceAmbiguity,
    InteractionSourceAmbiguityChoice,
    InteractionSourceAnchorListResponse,
    InteractionSourceAnchorResponse,
    InteractionSourceListResponse,
    InteractionSourceObjectListResponse,
    InteractionSourceObjectResponse,
    InteractionSourceProjectResponse,
    InteractionSourceRevisionResponse,
    JourneySourceSetup,
)
from modules.project.facade import (
    get_project_context,
    list_active_project_summaries,
    require_active_project,
    require_active_project_exclusive,
)
from modules.story.facade import get_scene_span_coverage, get_scenes_by_novel
from modules.world.facade import (
    get_character_knowledge_entries,
    get_characters_context,
    get_entity_relations,
    get_world_context,
    list_characters,
    list_entities,
    list_entity_terms,
)
from modules.writing.facade import (
    list_effective_chapter_indices,
    list_manuscript_sources,
)
from shared.utils import parse_uuid


class InteractionSourceService:
    def __init__(self, repo: InteractionRepository | None = None) -> None:
        self._repo = repo or InteractionRepository()

    async def list_sources(self, db: AsyncSession) -> InteractionSourceListResponse:
        owner_id = current_account_id()
        revisions = await self._repo.list_source_revisions(db, owner_id=owner_id)
        latest: dict[uuid.UUID, InteractionSourceRevision] = {}
        for revision in revisions:
            latest.setdefault(revision.source_novel_id, revision)
        responses = {
            project_id: await self._response(db, revision, include_details=False)
            for project_id, revision in latest.items()
        }
        projects, _total = await list_active_project_summaries(db, limit=100)
        return InteractionSourceListResponse(
            items=list(responses.values()),
            projects=[
                InteractionSourceProjectResponse(
                    project_id=str(project.project_id),
                    title=project.title,
                    latest_revision=responses.get(project.project_id),
                )
                for project in projects
            ],
        )

    async def prepare_setup(
        self,
        db: AsyncSession,
        setup: JourneySourceSetup,
    ) -> tuple[InteractionSourceRevision, dict, dict, dict]:
        revision = await self._owned_revision(db, setup.source_revision_id)
        await self._refresh(db, revision)
        if revision.status != "ready" or not revision.fingerprint:
            raise ConflictError("作品资料尚未整理完成")
        await self.require_author_project(db, str(revision.source_novel_id))
        anchor = self._find_anchor(revision, setup.progress_anchor_key)
        references = {
            item["reference_key"]: item for item in revision.reference_manifest or []
        }
        player = setup.player_identity.model_dump(exclude_none=True)
        if setup.player_identity.kind == "source_character":
            reference = references.get(str(setup.player_identity.reference_key))
            if reference is None or reference.get("entity_type") != "character":
                raise ValidationError("所选原作角色已不可用")
            if not self._reference_visible(revision, reference, anchor):
                raise ValidationError("所选角色在当前剧情进度尚未登场")
            player["label"] = reference["label"]
            player["target_id"] = reference["target_id"]
        pinned = list(dict.fromkeys(setup.pinned_reference_keys))
        if any(key not in references for key in pinned):
            raise ValidationError("部分固定资料已不可用")
        if any(
            not self._reference_visible(revision, references[key], anchor)
            for key in pinned
        ):
            raise ValidationError("部分固定资料超出当前剧情进度")
        return revision, anchor, player, {"pinned": pinned, "excluded": []}

    async def journey_source_response(
        self,
        db: AsyncSession,
        *,
        revision_id: uuid.UUID,
        anchor: dict,
        player_identity: dict,
        source_context_epoch: int,
    ) -> InteractionJourneySourceResponse:
        revision = await self._repo.get_source_revision(
            db,
            revision_id=revision_id,
            owner_id=current_account_id(),
        )
        if revision is None:
            raise NotFoundError("作品资料不存在")
        await self._refresh(db, revision)
        active = True
        try:
            await self.require_author_project(db, str(revision.source_novel_id))
        except NotFoundError:
            active = False
        latest = await self._repo.latest_source_revision(
            db,
            source_novel_id=revision.source_novel_id,
            owner_id=revision.owner_id,
        )
        return self._journey_source_response(
            revision,
            anchor=anchor,
            player_identity=player_identity,
            source_context_epoch=source_context_epoch,
            active=active,
            latest=latest,
        )

    async def journey_source_responses(
        self,
        db: AsyncSession,
        requests: list[dict],
    ) -> list[InteractionJourneySourceResponse]:
        """Batched journey_source_response for list views.

        ``requests`` carry revision_id/anchor/player_identity/
        source_context_epoch exactly like the single-row helper; the returned
        list is aligned with the input order.  One revision query serves all
        journeys and archived sources are probed once per distinct project.
        """
        if not requests:
            return []
        revisions = await self._repo.list_source_revisions(
            db,
            owner_id=current_account_id(),
        )
        by_id = {revision.id: revision for revision in revisions}
        latest_by_source: dict[uuid.UUID, InteractionSourceRevision] = {}
        for revision in revisions:
            latest_by_source.setdefault(revision.source_novel_id, revision)
        active_by_source: dict[uuid.UUID, bool] = {}
        responses = []
        for request in requests:
            revision = by_id.get(request["revision_id"])
            if revision is None:
                raise NotFoundError("作品资料不存在")
            await self._refresh(db, revision)
            if revision.source_novel_id not in active_by_source:
                try:
                    await self.require_author_project(
                        db,
                        str(revision.source_novel_id),
                    )
                    active_by_source[revision.source_novel_id] = True
                except NotFoundError:
                    active_by_source[revision.source_novel_id] = False
            responses.append(
                self._journey_source_response(
                    revision,
                    anchor=request["anchor"],
                    player_identity=request["player_identity"],
                    source_context_epoch=request["source_context_epoch"],
                    active=active_by_source[revision.source_novel_id],
                    latest=latest_by_source.get(revision.source_novel_id),
                )
            )
        return responses

    def _journey_source_response(
        self,
        revision: InteractionSourceRevision,
        *,
        anchor: dict,
        player_identity: dict,
        source_context_epoch: int,
        active: bool,
        latest: InteractionSourceRevision | None,
    ) -> InteractionJourneySourceResponse:
        update_available = bool(
            latest
            and latest.id != revision.id
            and latest.version_number > revision.version_number
            and latest.status == "ready"
        )
        return InteractionJourneySourceResponse(
            revision_id=str(revision.id),
            source_title=revision.title,
            version_number=revision.version_number,
            status=revision.status,
            progress_label=(
                str(anchor.get("label") or "已选剧情进度")
                if active
                else "来源作品已归档，恢复后可继续"
            ),
            progress_chapter_index=int(anchor["chapter_index"]),
            progress_end_offset=int(anchor["end_offset"]),
            player_label=str(
                player_identity.get("label") or player_identity.get("name") or ""
            )
            or None,
            source_context_epoch=source_context_epoch,
            update_available=update_available,
        )

    async def require_ready_revision(
        self,
        db: AsyncSession,
        revision_id: uuid.UUID,
    ) -> InteractionSourceRevision:
        revision = await self._repo.get_source_revision(
            db,
            revision_id=revision_id,
            owner_id=current_account_id(),
        )
        if revision is None:
            raise NotFoundError("作品资料不存在")
        await self._refresh(db, revision)
        if revision.status != "ready" or not revision.fingerprint:
            raise ConflictError("作品资料尚未整理完成")
        await self.require_author_project(db, str(revision.source_novel_id))
        return revision

    @staticmethod
    def _find_anchor(revision: InteractionSourceRevision, anchor_key: str) -> dict:
        anchor = next(
            (
                item
                for item in revision.anchor_manifest or []
                if item.get("anchor_key") == anchor_key
            ),
            None,
        )
        if anchor is None:
            raise ValidationError("所选剧情位置已不可用")
        return dict(anchor)

    @staticmethod
    def _reference_chapter(item: dict) -> int:
        return int(
            item.get("first_chapter_index") or item.get("source_chapter_index") or 0
        )

    @classmethod
    def _reference_visible(
        cls,
        revision: InteractionSourceRevision,
        item: dict,
        anchor: dict,
    ) -> bool:
        source_chapter = cls._reference_chapter(item)
        cutoff_chapter = int(anchor.get("chapter_index") or 0)
        cutoff_offset = int(anchor.get("end_offset") or 0)
        if source_chapter < 1 or source_chapter > cutoff_chapter:
            return False
        if source_chapter < cutoff_chapter:
            return True
        if item.get("entity_type") != "relation":
            return 0 < int(item.get("first_end_offset") or 0) <= cutoff_offset
        chapter = next(
            (
                value
                for value in revision.source_manifest or []
                if int(value.get("chapter_index") or 0) == cutoff_chapter
            ),
            None,
        )
        chapter_end = int((chapter or {}).get("char_count") or 0)
        return chapter_end > 0 and cutoff_offset >= chapter_end

    async def get_source(
        self,
        db: AsyncSession,
        revision_id: str,
    ) -> InteractionSourceRevisionResponse:
        revision = await self._owned_revision(db, revision_id, for_update=True)
        return await self._response(db, revision)

    async def create_from_project(
        self,
        db: AsyncSession,
        *,
        project_id: str,
        import_record_id: str | None = None,
        authorization_confirmed: bool,
    ) -> InteractionSourceRevisionResponse:
        if authorization_confirmed is not True:
            raise ValidationError("请先确认完整整理会使用模型额度")
        project = await self.require_author_project(db, project_id)
        await require_active_project_exclusive(db, project_id)
        owner_id = current_account_id()
        indices = await list_effective_chapter_indices(db, project_id)
        if not indices:
            raise ValidationError("作品还没有可整理的正文")
        sources = await list_manuscript_sources(
            db,
            project_id,
            indices,
            content_mode="canonical",
        )
        manifest = [
            {
                "draft_id": item.id,
                "chapter_index": item.chapter_index,
                "version_number": item.version_number,
                "content_mode": "canonical",
                "source_hash": item.content_hash,
                "title": item.title or f"第{item.chapter_index}章",
                "char_count": len(item.content or ""),
            }
            for item in sources
            if item.id and item.content_hash
        ]
        if len(manifest) != len(indices):
            raise ValidationError("部分章节缺少已发布正文，请先完成保存")
        manifest_hash = _fingerprint(manifest)
        existing = await self._repo.source_revision_by_manifest(
            db,
            source_novel_id=parse_uuid(project_id, "project_id"),
            owner_id=owner_id,
            manifest_hash=manifest_hash,
        )
        if existing is not None:
            if existing.status == "failed":
                indices = [
                    int(item["chapter_index"]) for item in existing.source_manifest or []
                ]
                submitted = None
                if existing.task_id and (existing.readiness_summary or {}).get(
                    "recovery_required"
                ):
                    try:
                        submitted = await resume_deep_import(
                            db,
                            str(existing.task_id),
                        )
                    except (ConflictError, ValidationError):
                        submitted = None
                if submitted is None:
                    submitted = await start_deep_import(
                        db,
                        project_id,
                        min(indices),
                        max(indices),
                        force=True,
                        high_quality=True,
                        authorization_confirmed=True,
                    )
                task_id = submitted.get("task_id")
                if not task_id:
                    raise ConflictError("完整整理任务未能恢复，请稍后重试")
                existing.task_id = parse_uuid(task_id, "task_id")
                if submitted.get("workflow_id"):
                    existing.workflow_id = parse_uuid(
                        submitted["workflow_id"], "workflow_id"
                    )
                existing.status = "organizing"
                existing.readiness_summary = {
                    "message": "正在恢复完整整理",
                    "chapter_count": len(indices),
                }
                await db.flush()
            return await self._response(db, existing)
        previous = await self._repo.latest_source_revision(
            db,
            source_novel_id=parse_uuid(project_id, "project_id"),
            owner_id=owner_id,
        )
        revision = InteractionSourceRevision(
            source_novel_id=parse_uuid(project_id, "project_id"),
            owner_id=owner_id,
            parent_revision_id=previous.id if previous else None,
            import_record_id=(
                parse_uuid(import_record_id, "import_record_id")
                if import_record_id
                else None
            ),
            version_number=(previous.version_number + 1 if previous else 1),
            title=project.title,
            status="organizing",
            source_manifest=manifest,
            anchor_manifest=[],
            reference_manifest=[],
            ambiguities=[],
            resolutions={},
            readiness_summary={"message": "正在提交完整整理任务"},
            manifest_hash=manifest_hash,
        )
        db.add(revision)
        await db.flush()
        try:
            submitted = await start_deep_import(
                db,
                project_id,
                min(indices),
                max(indices),
                force=True,
                high_quality=True,
                authorization_confirmed=True,
            )
            task_id = submitted.get("task_id")
            workflow_id = submitted.get("workflow_id")
            if not task_id:
                raise ConflictError("完整整理任务未能提交，请重试")
            revision.task_id = parse_uuid(task_id, "task_id")
            if workflow_id:
                revision.workflow_id = parse_uuid(workflow_id, "workflow_id")
            revision.readiness_summary = {
                "message": "正在完整整理当前导入版本，可以离开后再回来",
                "chapter_count": len(manifest),
            }
        except Exception as exc:
            revision.status = "failed"
            revision.readiness_summary = {
                "message": "完整整理任务提交失败，请检查模型连接后重试",
                "error_kind": type(exc).__name__,
            }
            raise
        await db.flush()
        return await self._response(db, revision, refresh=False)

    async def require_author_project(self, db: AsyncSession, project_id: str):
        """Require one active author project owned by the current account."""
        await require_active_project(db, project_id)
        project = await get_project_context(db, project_id)
        if (
            project is None
            or project.owner_id != str(current_account_id())
            or project.project_kind != "author"
        ):
            raise NotFoundError("作品项目不存在")
        return project

    async def resolve_ambiguity(
        self,
        db: AsyncSession,
        *,
        revision_id: str,
        ambiguity_key: str,
        choice_key: str,
    ) -> InteractionSourceRevisionResponse:
        revision = await self._owned_revision(db, revision_id, for_update=True)
        if revision.status == "ready":
            raise ConflictError("已就绪的资料版本已冻结，请创建新版本后再调整")
        if revision.status != "needs_confirmation":
            raise ConflictError("作品资料尚未进入关键指代确认")
        ambiguity = next(
            (
                item
                for item in revision.ambiguities or []
                if item.get("ambiguity_key") == ambiguity_key
            ),
            None,
        )
        if ambiguity is None:
            raise NotFoundError("需要确认的资料不存在")
        choices = {item.get("choice_key") for item in ambiguity.get("choices") or []}
        if choice_key not in choices:
            raise ValidationError("所选人物或对象已不可用")
        revision.resolutions = {**(revision.resolutions or {}), ambiguity_key: choice_key}
        unresolved = [
            item
            for item in revision.ambiguities or []
            if item.get("ambiguity_key") not in revision.resolutions
        ]
        revision.status = "needs_confirmation" if unresolved else "ready"
        revision.readiness_summary = {
            **(revision.readiness_summary or {}),
            "message": (
                f"还有 {len(unresolved)} 处人物或别名需要确认"
                if unresolved
                else "作品资料已完整整理，可以开始旅程"
            ),
        }
        if not unresolved:
            revision.ready_at = datetime.now(UTC)
        self._set_fingerprint(revision)
        await db.flush()
        return await self._response(db, revision, refresh=False)

    async def list_anchors(
        self,
        db: AsyncSession,
        *,
        revision_id: str,
        chapter_index: int | None = None,
    ) -> InteractionSourceAnchorListResponse:
        revision = await self._owned_revision(db, revision_id)
        items = [
            self._anchor_response(item)
            for item in revision.anchor_manifest or []
            if chapter_index is None or item.get("chapter_index") == chapter_index
        ]
        return InteractionSourceAnchorListResponse(items=items)

    async def match_anchors(
        self,
        db: AsyncSession,
        *,
        revision_id: str,
        chapter_index: int,
        description: str,
    ) -> InteractionSourceAnchorListResponse:
        anchors = (
            await self.list_anchors(
                db,
                revision_id=revision_id,
                chapter_index=chapter_index,
            )
        ).items
        query = _normalize(description)
        # ponytail: simple bigram overlap; replace with semantic matching only if
        # real anchor-selection failures justify another model call.
        ranked = sorted(
            anchors,
            key=lambda item: _text_overlap(
                query,
                _normalize(f"{item.label} {item.excerpt}"),
            ),
            reverse=True,
        )
        return InteractionSourceAnchorListResponse(items=ranked[:5])

    async def list_objects(
        self,
        db: AsyncSession,
        *,
        revision_id: str,
        entity_type: str | None = None,
        query: str | None = None,
        chapter_index: int | None = None,
        end_offset: int | None = None,
    ) -> InteractionSourceObjectListResponse:
        revision = await self._owned_revision(db, revision_id)
        needle = _normalize(query or "")
        items = []
        for item in revision.reference_manifest or []:
            if entity_type and item.get("entity_type") != entity_type:
                continue
            if chapter_index is not None and not self._reference_visible(
                revision,
                item,
                {"chapter_index": chapter_index, "end_offset": end_offset or 0},
            ):
                continue
            searchable = _normalize(
                " ".join([str(item.get("label") or ""), *(item.get("aliases") or [])])
            )
            if needle and needle not in searchable:
                continue
            items.append(self._object_response(item))
        return InteractionSourceObjectListResponse(items=items[:100])

    async def _owned_revision(
        self,
        db: AsyncSession,
        revision_id: str,
        *,
        for_update: bool = False,
    ) -> InteractionSourceRevision:
        revision = await self._repo.get_source_revision(
            db,
            revision_id=parse_uuid(revision_id, "source_revision_id"),
            owner_id=current_account_id(),
            for_update=for_update,
        )
        if revision is None:
            raise NotFoundError("作品资料不存在")
        return revision

    async def _response(
        self,
        db: AsyncSession,
        revision: InteractionSourceRevision,
        *,
        refresh: bool = True,
        include_details: bool = True,
    ) -> InteractionSourceRevisionResponse:
        if refresh:
            await self._refresh(db, revision)
        summary = dict(revision.readiness_summary or {})
        return InteractionSourceRevisionResponse(
            id=str(revision.id),
            project_id=str(revision.source_novel_id),
            title=revision.title,
            version_number=revision.version_number,
            status=revision.status,
            chapter_count=len(revision.source_manifest or []),
            progress_message=str(summary.get("message") or "正在整理作品资料"),
            recovery_required=bool(summary.get("recovery_required")),
            ambiguities=[
                InteractionSourceAmbiguity(
                    **item,
                    selected_choice_key=(revision.resolutions or {}).get(
                        item.get("ambiguity_key")
                    ),
                )
                for item in revision.ambiguities or []
            ]
            if include_details
            else [],
            anchors=[
                self._anchor_response(item) for item in revision.anchor_manifest or []
            ]
            if include_details
            else [],
            objects=[
                self._object_response(item) for item in revision.reference_manifest or []
            ]
            if include_details
            else [],
            ready_at=revision.ready_at,
            update_available=False,
        )

    async def _refresh(
        self,
        db: AsyncSession,
        revision: InteractionSourceRevision,
    ) -> None:
        if revision.status != "organizing":
            return
        if revision.task_id is None:
            revision.status = "failed"
            revision.readiness_summary = {"message": "完整整理任务已不可用，请重新开始"}
            await db.flush()
            return
        lifecycle = await list_task_lifecycle_contracts(
            db,
            task_ids=[str(revision.task_id)],
            novel_id=str(revision.source_novel_id),
            max_heartbeat_gap=0.0,
        )
        task = lifecycle.get(str(revision.task_id))
        if task is None:
            revision.status = "failed"
            revision.readiness_summary = {"message": "完整整理任务已不可用"}
            await db.flush()
            return
        if task.status in {"failed", "cancelled"}:
            revision.status = "failed"
            revision.readiness_summary = {
                "message": "完整整理中断，可以从原任务继续恢复",
                "recovery_required": task.recovery_required,
            }
            await db.flush()
            return
        if task.status != "done":
            revision.readiness_summary = {
                **(revision.readiness_summary or {}),
                "message": "正在完整整理当前导入版本，可以离开后再回来",
            }
            return
        if not await self._source_manifest_is_current(db, revision):
            revision.status = "failed"
            revision.readiness_summary = {
                "message": "整理期间正文发生变化，请为当前正文创建新资料版本",
            }
            await db.flush()
            return
        if not await self._indices_are_fresh(db, revision):
            revision.readiness_summary = {
                **(revision.readiness_summary or {}),
                "message": "正文已整理，正在建立可检索索引",
            }
            return
        reannotation = await get_latest_coalesced_task(
            db,
            task_type="rag_reannotate_entities",
            novel_id=str(revision.source_novel_id),
            scope=("entity_activity",),
        )
        if reannotation:
            if reannotation.status in {"pending", "running"}:
                revision.readiness_summary = {
                    **(revision.readiness_summary or {}),
                    "message": "索引已完成，正在核对对象与原文关联",
                }
                return
            if reannotation.status != "done":
                revision.status = "failed"
                revision.readiness_summary = {
                    "message": "对象与原文关联核对中断，请重新开始完整整理",
                }
                await db.flush()
                return
        await self._finalize(db, revision)

    async def _source_manifest_is_current(
        self,
        db: AsyncSession,
        revision: InteractionSourceRevision,
    ) -> bool:
        chapter_indices = [
            int(item["chapter_index"]) for item in revision.source_manifest or []
        ]
        if sorted(chapter_indices) != await list_effective_chapter_indices(
            db, str(revision.source_novel_id)
        ):
            return False
        current = await list_manuscript_sources(
            db,
            str(revision.source_novel_id),
            chapter_indices,
            content_mode="canonical",
        )
        current_manifest = {
            (item.chapter_index, str(item.id), item.content_hash)
            for item in current
            if item.id and item.content_hash
        }
        frozen_manifest = {
            (
                int(item["chapter_index"]),
                str(item["draft_id"]),
                str(item["source_hash"]),
            )
            for item in revision.source_manifest or []
        }
        return current_manifest == frozen_manifest

    async def _indices_are_fresh(
        self,
        db: AsyncSession,
        revision: InteractionSourceRevision,
    ) -> bool:
        chapters = [item["chapter_index"] for item in revision.source_manifest or []]
        if not chapters:
            return False
        coverage = await get_manifest_index_coverage(
            db,
            str(revision.source_novel_id),
            {
                str(item["draft_id"]): str(item["source_hash"])
                for item in revision.source_manifest or []
            },
        )
        return coverage == set(chapters)

    async def _finalize(
        self,
        db: AsyncSession,
        revision: InteractionSourceRevision,
    ) -> None:
        source_id = str(revision.source_novel_id)
        coverage = await get_scene_span_coverage(
            db,
            source_id,
            content_mode="canonical",
        )
        if (
            coverage.scene_count == 0
            or coverage.scene_without_span_count
            or coverage.imprecise_span_count
        ):
            revision.status = "failed"
            revision.readiness_summary = {
                "message": "部分剧情位置缺少可靠原文锚点，请恢复完整整理任务",
                "scene_count": coverage.scene_count,
                "missing_scene_spans": coverage.scene_without_span_count,
                "imprecise_scene_spans": coverage.imprecise_span_count,
            }
            await db.flush()
            return

        references, ambiguities = await self._reference_manifest(db, revision)
        anchors = await self._anchor_manifest(db, revision)
        revision.reference_manifest = references
        revision.anchor_manifest = anchors
        revision.ambiguities = ambiguities
        self._set_fingerprint(revision)
        unresolved = [
            item
            for item in ambiguities
            if item["ambiguity_key"] not in (revision.resolutions or {})
        ]
        revision.status = "needs_confirmation" if unresolved else "ready"
        revision.ready_at = None if unresolved else datetime.now(UTC)
        revision.readiness_summary = {
            "message": (
                f"还有 {len(unresolved)} 处人物或别名需要确认"
                if unresolved
                else "作品资料已完整整理，可以开始旅程"
            ),
            "chapter_count": len(revision.source_manifest or []),
            "scene_count": coverage.scene_count,
            "reference_count": len(references),
        }
        await db.flush()

    @staticmethod
    def _set_fingerprint(revision: InteractionSourceRevision) -> None:
        revision.fingerprint = _fingerprint(
            {
                "source_manifest": revision.source_manifest,
                "anchors": revision.anchor_manifest,
                "references": revision.reference_manifest,
                "ambiguities": revision.ambiguities,
                "resolutions": revision.resolutions,
            }
        )

    async def _reference_manifest(
        self,
        db: AsyncSession,
        revision: InteractionSourceRevision,
    ) -> tuple[list[dict], list[dict]]:
        source_id = str(revision.source_novel_id)
        frozen_sources = {
            str(item["draft_id"]): (
                str(item["source_hash"]),
                int(item["chapter_index"]),
            )
            for item in revision.source_manifest or []
        }
        appearances = await get_manifest_entity_appearances(
            db,
            source_id,
            {draft_id: value[0] for draft_id, value in frozen_sources.items()},
        )
        entities = await list_entities(
            db,
            source_id,
            statuses=("canonical", "draft", "candidate", "conflicted"),
            limit=10_000,
        )
        entities = [item for item in entities if str(item["id"]) in appearances]
        terms = await list_entity_terms(
            db,
            source_id,
            limit=10_000,
            include_review=True,
        )
        term_by_id = {str(item["id"]): item for item in terms}
        ids = [str(item["id"]) for item in entities]
        if not ids:
            return [], []
        world = await get_world_context(
            db,
            source_id,
            entity_ids=ids,
            reveal_mode="reader",
            limit=max(1, len(ids)),
            include_review=True,
        )
        world_by_id = {str(item.entity_id): item for item in world.entities}
        character_rows, _character_total = await list_characters(
            db,
            source_id,
            limit=10_000,
        )
        character_model_by_entity = {
            str(item.entity_id): str(item.id) for item in character_rows
        }
        characters = await get_characters_context(
            db,
            source_id,
            list(character_model_by_entity.values()),
            reveal_mode="reader",
        )
        character_by_id = {
            str(item.character_id): item.model_dump(exclude_none=True)
            for item in characters.characters
        }
        knowledge_by_entity: dict[str, list[dict]] = defaultdict(list)
        entity_by_character_model = {
            model_id: entity_id
            for entity_id, model_id in character_model_by_entity.items()
        }
        for entry in await get_character_knowledge_entries(db, source_id):
            entity_id = entity_by_character_model.get(str(entry.get("character_id")))
            if entity_id and entry.get("status") == "canonical":
                knowledge_by_entity[entity_id].append(entry)
        references = []
        terms_to_refs: dict[str, list[dict]] = defaultdict(list)
        for entity in entities:
            entity_id = str(entity["id"])
            appearance_ranges = appearances[entity_id]
            first_appearance = appearance_ranges[0]
            context = world_by_id.get(entity_id)
            term = term_by_id.get(entity_id) or {}
            aliases = [
                value
                for value in term.get("terms") or []
                if value and value != entity.get("name")
            ]
            reference_key = _fingerprint(
                {"manifest": revision.manifest_hash, "entity_id": entity_id}
            )
            item = {
                "reference_key": reference_key,
                "target_id": entity_id,
                "entity_type": str(entity.get("entity_type") or "object"),
                "label": str(entity.get("name") or "未命名对象"),
                "aliases": aliases,
                "status": str(term.get("status") or "candidate"),
                "appearance_ranges": appearance_ranges,
                "appearance_chapters": [
                    value["chapter_index"] for value in appearance_ranges
                ],
                "first_chapter_index": first_appearance["chapter_index"],
                "first_end_offset": first_appearance["first_end_offset"],
                "summary": (
                    str(context.summary or context.public_info or "")
                    if context is not None and context.status == "canonical"
                    else ""
                ),
                "character": (
                    character_by_id.get(entity_id)
                    if context is not None and context.status == "canonical"
                    else None
                ),
                "knowledge": knowledge_by_entity.get(entity_id, []),
            }
            references.append(item)
            for value in [item["label"], *aliases]:
                normalized = _normalize(value)
                if normalized:
                    terms_to_refs[normalized].append(item)

        ambiguities = []
        relation_rows, _relation_total = await get_entity_relations(
            db,
            source_id,
            entity_ids=ids,
        )
        names = {
            str(item["id"]): str(item.get("name") or "未命名对象") for item in entities
        }
        for relation in relation_rows:
            if relation.status != "canonical":
                continue
            if (
                str(relation.source_id) not in names
                or str(relation.target_id) not in names
            ):
                continue
            source_chapter_index = await self._relation_evidence_chapter(
                db,
                source_id=source_id,
                relation_id=str(relation.id),
                frozen_sources=frozen_sources,
            )
            if source_chapter_index is None:
                continue
            references.append(
                {
                    "reference_key": _fingerprint(
                        {"manifest": revision.manifest_hash, "relation_id": relation.id}
                    ),
                    "target_id": str(relation.id),
                    "entity_type": "relation",
                    "label": (
                        f"{names.get(str(relation.source_id), '未命名对象')} "
                        f"{relation.relation_type} "
                        f"{names.get(str(relation.target_id), '未命名对象')}"
                    ),
                    "aliases": [],
                    "status": "canonical",
                    "summary": str(relation.description or ""),
                    "source_target_id": str(relation.source_id),
                    "target_target_id": str(relation.target_id),
                    "source_chapter_index": source_chapter_index,
                }
            )
        for term, candidates in sorted(terms_to_refs.items()):
            unique = {item["reference_key"]: item for item in candidates}
            if len(unique) <= 1:
                continue
            ambiguity_key = _fingerprint(
                {"manifest": revision.manifest_hash, "term": term}
            )
            ambiguities.append(
                {
                    "ambiguity_key": ambiguity_key,
                    "term": term,
                    "label": candidates[0]["label"],
                    "reason": "同一名称或别名对应多个对象，请选择本版本中的含义",
                    "choices": [
                        InteractionSourceAmbiguityChoice(
                            choice_key=item["reference_key"],
                            label=item["label"],
                            entity_type=item["entity_type"],
                        ).model_dump()
                        for item in unique.values()
                    ],
                }
            )
        return references, ambiguities

    @staticmethod
    async def _relation_evidence_chapter(
        db: AsyncSession,
        *,
        source_id: str,
        relation_id: str,
        frozen_sources: dict[str, tuple[str, int]],
    ) -> int | None:
        try:
            trace = await trace_novel_evidence(
                db,
                novel_id=source_id,
                target_ref={
                    "target_type": "entity_relation",
                    "target_id": relation_id,
                    "target_path": "description",
                },
                claim_path="description",
                visibility=VisibilityContextContract(mode="author"),
                content_mode="working",
            )
        except (NotFoundError, ValidationError, ValueError):
            return None
        chapters = []
        for link in trace.get("links") or []:
            if link.get("status") != "active":
                continue
            source_ref = link.get("source_ref") or {}
            try:
                frozen = frozen_sources.get(str(source_ref.get("draft_id") or ""))
                current = (
                    str(source_ref.get("source_hash") or ""),
                    int(source_ref.get("chapter_index") or 0),
                )
            except (TypeError, ValueError):
                continue
            if frozen == current:
                chapters.append(current[1])
        return min(chapters, default=None)

    async def _anchor_manifest(
        self,
        db: AsyncSession,
        revision: InteractionSourceRevision,
    ) -> list[dict]:
        source_id = str(revision.source_novel_id)
        chapters = {item["chapter_index"]: item for item in revision.source_manifest}
        anchors = [
            self._anchor(
                revision,
                chapter_index=index,
                chapter_title=item["title"],
                label=f"{item['title']}结束",
                excerpt="",
                end_offset=item["char_count"],
                scene_id=None,
            )
            for index, item in chapters.items()
        ]
        scenes = await get_scenes_by_novel(
            db,
            source_id,
            status_filter=["canonical", "draft", "candidate"],
        )
        for scene in scenes:
            for chunk in scene.get("scene_chunks") or []:
                chapter_index = int(chunk.get("chapter_index") or 0)
                end_offset = chunk.get("end_offset", chunk.get("end_pos"))
                if (
                    chapter_index not in chapters
                    or not isinstance(end_offset, int)
                    or not 0 < end_offset <= int(chapters[chapter_index]["char_count"])
                ):
                    continue
                anchors.append(
                    self._anchor(
                        revision,
                        chapter_index=chapter_index,
                        chapter_title=chapters[chapter_index]["title"],
                        label=str(
                            scene.get("title")
                            or scene.get("goal")
                            or f"第{chapter_index}章剧情节点"
                        )[:160],
                        excerpt=str(
                            scene.get("summary")
                            or scene.get("core_conflict")
                            or scene.get("emotional_beat")
                            or ""
                        )[:240],
                        end_offset=end_offset,
                        scene_id=str(scene.get("id") or "") or None,
                    )
                )
        return list({item["anchor_key"]: item for item in anchors}.values())

    @staticmethod
    def _anchor(
        revision: InteractionSourceRevision,
        *,
        chapter_index: int,
        chapter_title: str,
        label: str,
        excerpt: str,
        end_offset: int,
        scene_id: str | None,
    ) -> dict:
        value = {
            "chapter_index": chapter_index,
            "chapter_title": chapter_title,
            "label": label,
            "excerpt": excerpt,
            "end_offset": end_offset,
            "scene_id": scene_id,
        }
        return {**value, "anchor_key": _fingerprint({"revision": revision.id, **value})}

    @staticmethod
    def _anchor_response(item: dict) -> InteractionSourceAnchorResponse:
        return InteractionSourceAnchorResponse(
            anchor_key=item["anchor_key"],
            chapter_index=item["chapter_index"],
            chapter_title=item["chapter_title"],
            label=item["label"],
            excerpt=item.get("excerpt") or "",
            end_offset=item["end_offset"],
        )

    @staticmethod
    def _object_response(item: dict) -> InteractionSourceObjectResponse:
        return InteractionSourceObjectResponse(
            reference_key=item["reference_key"],
            label=item["label"],
            entity_type=item["entity_type"],
            summary="",
            aliases=list(item.get("aliases") or []),
            first_chapter_index=item.get("first_chapter_index"),
            first_end_offset=item.get("first_end_offset"),
        )


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(value: str) -> str:
    return "".join(str(value or "").lower().split())


def _text_overlap(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return 2.0
    left_parts = {left[index : index + 2] for index in range(max(1, len(left) - 1))}
    right_parts = {right[index : index + 2] for index in range(max(1, len(right) - 1))}
    return len(left_parts & right_parts) / max(1, len(left_parts | right_parts))

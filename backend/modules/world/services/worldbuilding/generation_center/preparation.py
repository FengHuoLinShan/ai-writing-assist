"""准备阶段：来源校验、资产目录、后台上下文冻结与快照收尾。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.stable_hash import stable_hash
from modules.world.models import CoreEntity, EntityRelation, WorldBiblePage
from modules.world.schemas import (
    GenerationContextUsage,
    ObjectDraftChatMessage,
    WorldGenerationCoreEntityTarget,
    WorldGenerationNewPageTarget,
    WorldGenerationPageSource,
    WorldGenerationRequestBase,
    WorldGenerationSourceSnapshot,
)
from modules.world.services.common import parse_uuid
from modules.world.services.worldbuilding.generation_center.shared import (
    _SELECTED_CHAPTER_CONTEXT_BUDGET,
    _SUPPORTED_ASSET_TYPES,
    WORLD_GENERATION_TIMEOUT_SECONDS,
    WorldGenerationSourceConflictError,
    _best_focus_match,
    logger,
)


class _PrepareStageMixin:
    async def _prepare(
        self,
        db: AsyncSession,
        data: WorldGenerationRequestBase,
        *,
        operation: str,
        model: str,
        capture_context_snapshot: bool = True,
    ) -> dict[str, Any]:
        parse_uuid(data.novel_id, "novel_id")
        from modules.world.services.worldbuilding.cocreation_session_service import (
            WorldCocreationSessionService,
        )

        session_context = await WorldCocreationSessionService().generation_context(
            db, data
        )
        if session_context:
            author = next(
                (item for item in reversed(data.messages) if item.role == "user"), None
            )
            recent = [
                ObjectDraftChatMessage(
                    role="user" if item["role"] == "author" else "assistant",
                    content=item["content"],
                )
                for item in session_context["recent_messages"]
            ]
            data = data.model_copy(
                update={"messages": [*recent[-39:], author] if author else recent}
            )
        source = await self._load_source(db, data)
        object_template = None
        if isinstance(data.target, WorldGenerationCoreEntityTarget):
            object_template = await self._prompt_templates.resolve_for_generation(
                db,
                novel_id=data.novel_id,
                template_id=data.target.template_id,
                template_version=data.target.template_version,
                template_variables=data.target.template_variables,
                object_template=data.target.template,
                template_name=data.target.template_name,
                template_prompt=data.target.template_prompt,
            )
        page_template = await self._resolve_page_template(db, data, source)
        categories = await self._lifecycle.list_categories(db, data.novel_id)
        allowed_page_types = {
            item.category_key: {
                "name": item.name,
                "description": item.description,
            }
            for item in categories
        }
        if (
            isinstance(data.target, WorldGenerationNewPageTarget)
            and data.target.page_type not in allowed_page_types
        ):
            raise ValidationError(
                f"Unknown World Bible page type: {data.target.page_type}"
            )
        chapters = await self._load_selected_chapters(
            db,
            data.novel_id,
            data.selected_chapter_indices,
            focus_text=self._focus_text(data, object_template),
        )
        assets = await self._asset_catalog(db, data, source)
        await self._validate_explicit_context(db, data)
        background: dict[str, Any] | None = None
        try:
            background = await self._compile_generation_background(
                db,
                data,
                operation=operation,
                focus_text=self._focus_text(data, object_template),
                assets=assets,
                source_snapshot=source["source_snapshot"],
                model=model,
                capture_snapshot=capture_context_snapshot,
            )
            source_refs = self._source_refs(
                data,
                source,
                chapters,
                assets,
                background,
            )
            prepared = {
                **source,
                "session_context": session_context,
                "conversation_messages": data.messages,
                "request_target": data.target,
                "object_template": object_template,
                "page_template": page_template,
                "allowed_page_types": allowed_page_types,
                "chapters": chapters,
                "assets": assets,
                "background": background,
                "source_refs": source_refs,
                "page_catalog": [
                    {
                        "title": item.get("label", "资料页"),
                        "overview": item.get("summary", ""),
                    }
                    for item in (background.get("context_usage") or {})
                    .get("included_asset_manifest", {})
                    .get("world_bible_page", [])
                ],
                "operation": operation,
                "model": model,
            }
        except Exception as exc:
            if background is not None:
                await self._finish_context_snapshot(
                    db,
                    data.novel_id,
                    background,
                    error=exc,
                )
            raise
        # Freeze the same filtered reference that generation consumes, including
        # the saved workspace, selected page/chapters and pasted author material.
        prepared["knowledge_context"] = self._reference_message(data, prepared)
        return prepared

    @staticmethod
    async def _validate_explicit_context(
        db: AsyncSession,
        data: WorldGenerationRequestBase,
    ) -> None:
        """Fail closed when an author-selected context asset cannot be loaded."""
        if data.scene_id:
            from modules.story.facade import get_scene_contract

            scene = await get_scene_contract(db, data.novel_id, data.scene_id)
            if scene is None or scene.status not in {"candidate", "draft", "canonical"}:
                raise ValidationError("Selected Scene is not available in this project")

        if data.thread_ids:
            from modules.story.facade import get_plot_threads_for_context

            requested = list(dict.fromkeys(data.thread_ids))
            threads = await get_plot_threads_for_context(
                db,
                data.novel_id,
                thread_ids=requested,
            )
            loaded = {str(item.id) for item in threads}
            missing = [item for item in requested if item not in loaded]
            if missing:
                raise ValidationError(
                    f"Selected plot threads are not available in this project: {missing}"
                )

        if data.entity_ids:
            from modules.world.facade import get_world_context

            requested = list(dict.fromkeys(data.entity_ids))
            context = await get_world_context(
                db,
                data.novel_id,
                entity_ids=requested,
                reveal_mode="author_safe",
                limit=len(requested),
            )
            loaded = {str(item.entity_id) for item in context.entities}
            missing = [item for item in requested if item not in loaded]
            if missing:
                raise ValidationError(
                    f"Selected world objects are not available in this project: {missing}"
                )

        if data.character_ids:
            from modules.world.facade import get_characters_context

            requested = list(dict.fromkeys(data.character_ids))
            context = await get_characters_context(
                db,
                data.novel_id,
                character_ids=requested,
                reveal_mode="author_safe",
            )
            loaded = {str(item.character_id) for item in context.characters}
            missing = [item for item in requested if item not in loaded]
            if missing:
                raise ValidationError(
                    f"Selected characters are not available in this project: {missing}"
                )

    async def _load_source(
        self,
        db: AsyncSession,
        data: WorldGenerationRequestBase,
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(data.source_context, WorldGenerationPageSource):
            return {
                "source_snapshot": WorldGenerationSourceSnapshot(kind="project"),
                "source_page": None,
                "source_draft": None,
                "source_page_data": None,
            }
        state = await self._lifecycle.load_page_source(
            db,
            data.novel_id,
            data.source_context.page_id,
            for_update=for_update,
        )
        baseline = data.source_context.baseline
        draft_id = baseline.draft_id if baseline.kind == "draft" else None
        draft_updated_at = baseline.draft_updated_at if baseline.kind == "draft" else None
        mismatch = self._lifecycle.baseline_mismatch(
            state,
            page_version=baseline.page_version,
            draft_id=draft_id,
            draft_updated_at=draft_updated_at,
        )
        self._raise_source_mismatch(mismatch)
        active = state.content()
        draft = active if state.draft is not None else None
        snapshot = WorldGenerationSourceSnapshot(
            kind="world_bible_page",
            page_id=str(state.page.id),
            page_version=state.page.version_number,
            draft_id=draft["id"] if draft else None,
            draft_updated_at=draft["updated_at"] if draft else None,
            content_hash=self._lifecycle.page_source_hash(state),
            title=active["title"],
        )
        return {
            "source_snapshot": snapshot,
            "source_page": state.page,
            "source_draft": draft,
            "source_page_data": active,
        }

    @staticmethod
    def _raise_source_mismatch(mismatch: str | None) -> None:
        if mismatch == "page_version":
            raise WorldGenerationSourceConflictError(
                "World Bible page version changed before generation"
            )
        if mismatch == "draft_created":
            raise WorldGenerationSourceConflictError(
                "World Bible working draft was created before generation"
            )
        if mismatch == "draft_changed":
            raise WorldGenerationSourceConflictError(
                "World Bible working draft changed before generation"
            )

    async def _resolve_page_template(
        self,
        db: AsyncSession,
        data: WorldGenerationRequestBase,
        source: dict[str, Any],
    ):
        template_key = None
        expected_version = None
        if isinstance(data.target, WorldGenerationNewPageTarget):
            template_key = data.target.page_template_key
            expected_version = data.target.page_template_version
        if not template_key:
            return None
        templates = await self._page_templates.list_templates(db, data.novel_id)
        template = next(
            (item for item in templates if item.template_key == template_key),
            None,
        )
        if template is None:
            raise ValidationError(f"World Bible page template not found: {template_key}")
        if expected_version is not None and template.version_number != expected_version:
            raise ConflictError("World Bible page template version conflict")
        return template

    async def _asset_catalog(
        self,
        db: AsyncSession,
        data: WorldGenerationRequestBase,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        requested = list(data.selected_asset_refs)
        if source.get("source_page_data"):
            requested.extend(source["source_page_data"]["linked_asset_refs_json"])
        if not requested:
            return {
                "items": [],
                "by_key": {},
                "hash_to_key": {},
                "entity_ids": [],
                "character_ids": [],
            }
        nid = parse_uuid(data.novel_id, "novel_id")
        identities: list[tuple[str, str, str]] = []
        parsed_ids: dict[tuple[str, str], Any] = {}
        for raw in requested:
            asset_identity = self._normalized_identity(
                str(
                    raw.get("type")
                    or raw.get("source_type")
                    or raw.get("target_type")
                    or ""
                ),
                str(raw.get("id") or raw.get("source_id") or raw.get("target_id") or ""),
            )
            identity = (*asset_identity, str(raw.get("target_path") or ""))
            if identity in identities:
                continue
            if asset_identity[0] not in _SUPPORTED_ASSET_TYPES:
                raise ValidationError(
                    f"Unsupported World Bible asset ref: {asset_identity[0]}"
                )
            # 待发布资料集引用（local:）不进生成上下文资产目录（m1-contract 第 4 条）
            if asset_identity[1].startswith("local:"):
                continue
            parsed_ids[asset_identity] = parse_uuid(
                asset_identity[1],
                "asset_ref_id",
            )
            identities.append(identity)

        resolved: dict[tuple[str, str], dict[str, Any]] = {}
        entity_ids = [
            value
            for identity, value in parsed_ids.items()
            if identity[0] == "core_entity"
        ]
        if entity_ids:
            rows = await db.scalars(
                select(CoreEntity).where(
                    CoreEntity.novel_id == nid,
                    CoreEntity.id.in_(entity_ids),
                    CoreEntity.status == "canonical",
                )
            )
            for row in rows.all():
                resolved[("core_entity", str(row.id))] = {
                    "type": "core_entity",
                    "id": str(row.id),
                    "title": row.name,
                    "summary": row.summary or row.public_info or row.name,
                    "entity_type": row.entity_type,
                }

        relation_ids = [
            value
            for identity, value in parsed_ids.items()
            if identity[0] == "entity_relation"
        ]
        if relation_ids:
            rows = await db.scalars(
                select(EntityRelation).where(
                    EntityRelation.novel_id == nid,
                    EntityRelation.id.in_(relation_ids),
                    EntityRelation.status == "canonical",
                )
            )
            for row in rows.all():
                resolved[("entity_relation", str(row.id))] = {
                    "type": "entity_relation",
                    "id": str(row.id),
                    "title": row.relation_type,
                    "summary": row.description or row.relation_type,
                }

        page_ids = [
            value
            for identity, value in parsed_ids.items()
            if identity[0] == "world_bible_page"
        ]
        if page_ids:
            rows = await db.scalars(
                select(WorldBiblePage).where(
                    WorldBiblePage.novel_id == nid,
                    WorldBiblePage.id.in_(page_ids),
                    WorldBiblePage.status.in_({"canonical", "confirmed"}),
                )
            )
            for row in rows.all():
                sections = [
                    {
                        "title": str(item.get("title") or ""),
                        "body_markdown": str(item.get("body_markdown") or ""),
                        "projection_policy": str(
                            item.get("projection_policy") or "eligible"
                        ),
                        "sensitivity_hint": str(
                            item.get("sensitivity_hint") or "author_safe"
                        ),
                    }
                    for item in (row.sections_json or [])
                ]
                page_content = json.dumps(
                    {
                        "title": row.title,
                        "page_type": row.page_type,
                        "overview": row.free_text,
                        "sections": sections,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                resolved[("world_bible_page", str(row.id))] = {
                    "type": "world_bible_page",
                    "id": str(row.id),
                    "title": row.title,
                    "summary": "\n".join(
                        filter(
                            None,
                            [
                                row.free_text,
                                *(
                                    f"{item['title']}\n{item['body_markdown']}"
                                    for item in sections
                                ),
                            ],
                        )
                    )
                    or row.title,
                    "content": page_content,
                }

        items: list[dict[str, Any]] = []
        by_key: dict[str, dict[str, Any]] = {}
        hash_to_key: dict[str, str] = {}
        selected_entity_ids: list[str] = []
        selected_character_ids: list[str] = []
        for source_type, source_id, target_path in identities:
            entry = resolved.get((source_type, source_id))
            if entry is None:
                raise ValidationError(
                    "Selected world asset does not belong to the project or is not "
                    "adopted"
                )
            key = f"A{len(items) + 1}"
            ref = {
                "type": entry["type"],
                "id": entry["id"],
                "target_path": target_path,
            }
            summary = " ".join(str(entry["summary"] or entry["title"] or "").split())[
                :1000
            ]
            content = str(
                entry.get("content")
                or json.dumps(
                    {
                        "type": entry["type"],
                        "title": entry["title"],
                        "summary": entry["summary"],
                        "target_path": target_path,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            item = {
                "key": key,
                "type": entry["type"],
                "title": entry["title"],
                "summary": summary,
                "target_path": target_path,
                "ref": ref,
                "content": content,
                "source_hash": stable_hash(content, passthrough_str=True),
            }
            items.append({k: v for k, v in item.items() if k not in {"ref", "content"}})
            by_key[key] = item
            hash_to_key[self._asset_ref_hash(ref)] = key
            if source_type == "core_entity":
                if entry.get("entity_type") == "character":
                    selected_character_ids.append(entry["id"])
                else:
                    selected_entity_ids.append(entry["id"])
        return {
            "items": items,
            "by_key": by_key,
            "hash_to_key": hash_to_key,
            "entity_ids": list(dict.fromkeys(selected_entity_ids)),
            "character_ids": list(dict.fromkeys(selected_character_ids)),
        }

    @staticmethod
    def _normalized_identity(source_type: str, source_id: str) -> tuple[str, str]:
        aliases = {
            "entity": "core_entity",
            "profile": "core_entity",
            "event": "core_entity",
            "page": "world_bible_page",
            "relation": "entity_relation",
        }
        return aliases.get(source_type, source_type), source_id


    async def _load_selected_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_indices: list[int],
        *,
        focus_text: str,
    ) -> list[dict[str, Any]]:
        requested = sorted({int(idx) for idx in chapter_indices if int(idx) > 0})
        if not requested:
            return []
        from modules.writing.facade import list_latest_drafts_for_chapters

        drafts = await list_latest_drafts_for_chapters(db, novel_id, requested)
        by_index = {draft.chapter_index: draft for draft in drafts}
        missing = [idx for idx in requested if idx not in by_index]
        if missing:
            raise ValidationError(f"selected chapters not found: {missing}")
        excerpt_limit = max(
            600,
            min(2400, _SELECTED_CHAPTER_CONTEXT_BUDGET // len(requested)),
        )
        return [
            {
                "chapter_index": draft.chapter_index,
                "title": draft.title or f"第{draft.chapter_index}章",
                "excerpt": self._excerpt(
                    draft.content or "",
                    limit=excerpt_limit,
                    focus_text=focus_text,
                ),
            }
            for draft in drafts
        ]

    @staticmethod
    def _excerpt(content: str, *, limit: int, focus_text: str) -> str:
        text = " ".join((content or "").split())
        if len(text) <= limit:
            return text
        matched_index = _best_focus_match(text, focus_text)
        if matched_index is not None:
            start = max(0, matched_index - limit // 3)
            end = min(len(text), start + limit)
            start = max(0, end - limit)
            return (
                ("... " if start else "")
                + text[start:end]
                + (" ..." if end < len(text) else "")
            )
        head_limit = max(1, (limit * 2) // 3)
        return f"{text[:head_limit]} ... {text[-(limit - head_limit) :]}"

    async def _compile_generation_background(
        self,
        db: AsyncSession,
        data: WorldGenerationRequestBase,
        *,
        operation: str,
        model: str,
        focus_text: str,
        assets: dict[str, Any],
        source_snapshot: WorldGenerationSourceSnapshot,
        capture_snapshot: bool = True,
    ) -> dict[str, Any]:
        provider = self._generation_background_provider
        if provider is None:
            try:
                from core.container import get as get_container_service
                from core.service_keys import (
                    CONTEXT_GENERATION_BACKGROUND,
                )

                provider = get_container_service(CONTEXT_GENERATION_BACKGROUND)
            except KeyError:
                from modules.evidence.facade import compile_generation_background

                provider = compile_generation_background
        if operation == "world.generation.chat":
            prompt_name = "world.generation.chat.generate"
        elif operation == "world.generation.convergence":
            prompt_name = "world.generation.convergence.map"
        elif operation == "world.generation.exploration":
            prompt_name = "world.generation.exploration.preview"
        elif operation == "world.generation.semantic_inspection":
            prompt_name = "world.generation.semantic_inspection"
        elif operation == "world.generation.core_entity":
            prompt_name = "world.generation.core_entity.structured"
        elif isinstance(data.target, WorldGenerationNewPageTarget):
            prompt_name = "world.generation.world_bible_new_page.structured"
        else:
            prompt_name = "world.generation.world_bible_page.structured"
        return await provider(
            db,
            novel_id=data.novel_id,
            task="生成中心世界设定共创",
            include_world_synopsis=data.include_world_synopsis,
            selected_world_bible_draft_ids=[],
            activation_profile_id=data.activation_profile_id,
            activation_profile_version=data.activation_profile_version,
            operation=operation,
            prompt_name=prompt_name,
            model=model,
            focus_text=focus_text,
            reference_chapter_index=(
                max(data.selected_chapter_indices)
                if data.selected_chapter_indices
                else None
            ),
            scene_id=data.scene_id,
            thread_ids=data.thread_ids,
            character_ids=list(
                dict.fromkeys([*data.character_ids, *assets.get("character_ids", [])])
            ),
            entity_ids=list(
                dict.fromkeys([*data.entity_ids, *assets.get("entity_ids", [])])
            ),
            source_snapshot=source_snapshot.model_dump(mode="json"),
            capture_snapshot=capture_snapshot,
            context_confirmation_id=data.context_confirmation_id,
        )


    @asynccontextmanager
    async def _open_client(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        execution_snapshot: dict[str, Any] | None = None,
        high_quality: bool = False,
    ) -> AsyncIterator[LLMClient]:
        if self._llm_client is not None:
            await self._checkpoint_before_provider(db)
            yield self._llm_client
            return

        from modules.project.facade import (
            build_project_llm_execution_snapshot,
            create_project_snapshot_llm_client,
            restore_project_llm_execution_settings,
        )

        snapshot = execution_snapshot or await build_project_llm_execution_snapshot(
            db,
            novel_id,
        )
        settings = await restore_project_llm_execution_settings(
            db,
            novel_id,
            snapshot,
        )
        client = create_project_snapshot_llm_client(
            settings,
            timeout_override=WORLD_GENERATION_TIMEOUT_SECONDS,
            novel_id=novel_id,
            high_quality=high_quality,
        )
        try:
            await self._checkpoint_before_provider(db)
            yield client
        finally:
            await client.close()

    async def _freeze_execution_snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> tuple[dict[str, Any] | None, str]:
        if self._llm_client is not None:
            return None, str(self._llm_client.model_name)
        from modules.project.facade import build_project_llm_execution_snapshot

        snapshot = await build_project_llm_execution_snapshot(db, novel_id)
        return snapshot, str(snapshot["profile"]["model"])

    @staticmethod
    async def _checkpoint_before_provider(db: AsyncSession) -> None:
        await db.commit()
        if db.in_transaction():
            raise RuntimeError(
                "World generation provider execution requires a transaction-free "
                "checkpoint"
            )

    async def _revalidate_source(
        self,
        db: AsyncSession,
        data: WorldGenerationRequestBase,
        prepared: dict[str, Any],
    ) -> None:
        from modules.project.facade import require_active_project

        await require_active_project(db, data.novel_id)
        locked_source = await self._load_source(db, data, for_update=True)
        if locked_source["source_snapshot"] != prepared["source_snapshot"]:
            raise WorldGenerationSourceConflictError(
                "World generation source changed while the model was running"
            )
        try:
            current = await self._prepare(
                db,
                data,
                operation=prepared["operation"],
                model=prepared["model"],
                capture_context_snapshot=False,
            )
        except ValidationError as exc:
            raise WorldGenerationSourceConflictError(
                "World generation selected references changed while the model was running"
            ) from exc
        if self._freshness_evidence(data, current) != self._freshness_evidence(
            data,
            prepared,
        ):
            raise WorldGenerationSourceConflictError(
                "World generation selected references changed while the model was running"
            )

    def _freshness_evidence(
        self,
        data: WorldGenerationRequestBase,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        usage = dict(prepared["background"].get("context_usage") or {})
        usage.pop("context_snapshot_id", None)
        evidence: dict[str, Any] = {
            "session_context": prepared.get("session_context") or None,
            "source_snapshot": prepared["source_snapshot"].model_dump(mode="json"),
            "chapters": prepared["chapters"],
            "assets": prepared["assets"]["items"],
            "background": prepared["background"].get("rendered_context", ""),
            "context_usage": usage,
        }
        if prepared["operation"] in {
            "world.generation.chat",
            "world.generation.core_entity",
            "world.generation.world_bible_page",
        }:
            template = prepared.get("object_template")
            evidence["reference_message"] = self._reference_message(data, prepared)
            evidence["object_template"] = (
                None
                if template is None
                else {
                    "template_id": template.template_id,
                    "template_version": template.template_version,
                    "template_hash": template.template_hash,
                    "object_template": template.object_template,
                    "label": template.label,
                    "rendered_prompt": template.rendered_prompt,
                }
            )
        return evidence

    @staticmethod
    def _context_usage(background: dict[str, Any]) -> GenerationContextUsage | None:
        usage = background.get("context_usage")
        return None if usage is None else GenerationContextUsage.model_validate(usage)

    @staticmethod
    def _context_snapshot_id(background: dict[str, Any]) -> str | None:
        usage = background.get("context_usage") or {}
        return usage.get("context_snapshot_id")

    @classmethod
    async def _finish_context_snapshot(
        cls,
        db: AsyncSession,
        novel_id: str,
        background: dict[str, Any],
        *,
        result_refs: list[dict[str, str]] | None = None,
        error: Exception | None = None,
    ) -> None:
        snapshot_id = cls._context_snapshot_id(background)
        if not snapshot_id:
            return
        try:
            if error is not None:
                from modules.evidence.facade import fail_generation_context_snapshot

                await fail_generation_context_snapshot(
                    db,
                    novel_id=novel_id,
                    snapshot_id=snapshot_id,
                    error_kind=error.__class__.__name__,
                    error_message=redact_diagnostic(error, limit=1000),
                )
            else:
                from modules.evidence.facade import succeed_generation_context_snapshot

                await succeed_generation_context_snapshot(
                    db,
                    novel_id=novel_id,
                    snapshot_id=snapshot_id,
                    result_refs=result_refs or [],
                )
        except Exception as finish_error:
            logger.warning(
                "世界生成中心上下文快照收尾失败 snapshot_id=%s reason=%s",
                snapshot_id,
                redact_diagnostic(finish_error, limit=300),
            )
            if error is not None:
                return
            try:
                from modules.evidence.facade import fail_generation_context_snapshot

                await fail_generation_context_snapshot(
                    db,
                    novel_id=novel_id,
                    snapshot_id=snapshot_id,
                    error_kind="snapshot_finalization_failed",
                    error_message=redact_diagnostic(finish_error, limit=1000),
                )
            except Exception as fallback_error:
                logger.warning(
                    "世界生成中心上下文快照失败回退也未完成 snapshot_id=%s reason=%s",
                    snapshot_id,
                    redact_diagnostic(fallback_error, limit=300),
                )

"""Create one owner-scoped, editable copy of the configured public demo."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.schema import Table

from core.base import Base
from core.config import get_settings
from core.errors import DomainError, NotFoundError
from modules.account.facade import (
    current_account_id,
    current_account_principal,
    is_demo_readonly_principal,
    require_account_active,
)
from modules.account.public_demo import configured_public_demo
from modules.project.facade import lock_project_ids_for_owner
from modules.project.models import DemoProjectCopy, Project
from modules.project.schemas import ProjectCreate, ProjectResponse
from modules.project.services import ProjectService, _secret_free_project_context_settings

# Only durable author-editable assets are copied.  Async tasks, generated
# candidates, assistant/RP data, retrieval indexes, and user UI history stay out.
_COPY_TABLE_NAMES = (
    "import_records",
    "writing_drafts",
    "imported_chapters",
    "core_entities",
    "characters",
    "species_profiles",
    "faction_profiles",
    "location_profiles",
    "rule_profiles",
    "item_profiles",
    "secret_profiles",
    "entity_profile_templates",
    "entity_profile_template_revisions",
    "generic_entity_profiles",
    "entity_revisions",
    "events",
    "entity_relations",
    "text_archive",
    "world_bible_categories",
    "world_bible_page_templates",
    "world_bible_page_template_revisions",
    "world_bible_pages",
    "world_bible_page_revisions",
    "world_bible_page_projections",
    "world_bible_page_drafts",
    "knowledge_tags",
    "knowledge_visibility_policies",
    "reader_reveal_policies",
    "asset_knowledge_tags",
    "character_knowledge",
    "character_knowledge_tags",
    "knowledge_tag_exclusions",
    "generation_prompt_templates",
    "generation_prompt_template_revisions",
    "story_outline_revisions",
    "story_outline_heads",
    "plot_threads",
    "outline_arcs",
    "scenes",
    "scene_spans",
    "scene_chapter_links",
    "foreshadowing_plans",
    "reveal_plans",
    "story_character_cards",
    "story_character_card_revisions",
    "story_scene_script_files",
    "story_scene_script_revisions",
    "world_canon_revisions",
    "world_canon_heads",
    "memory_events",
    "memory_snapshots",
    "delta_log",
    "memory_scene_checkpoints",
    "memory_scene_snapshots",
    "evidence_links",
    "map_atlas_runs",
    "map_atlas_nodes",
    "map_atlas_revisions",
    "map_atlas_pages",
    "map_atlas_annotations",
)
_CANDIDATE_STATUSES = {"candidate", "pending", "rejected", "failed"}
_DERIVED_COLUMNS = {"embedding", "embedding_text", "pinyin_string", "search_text"}


@dataclass(frozen=True, slots=True)
class DemoCopyResult:
    status: str
    project: ProjectResponse


class DemoProjectCopyService:
    def __init__(
        self,
        *,
        project_service: ProjectService | None = None,
        image_storage: Any | None = None,
        map_storage: Any | None = None,
    ) -> None:
        self._projects = project_service or ProjectService()
        self._image_storage = image_storage
        self._map_storage = map_storage

    async def copy(self, db: AsyncSession) -> DemoCopyResult:
        config = configured_public_demo()
        if not config.enabled or config.project_id is None or config.version is None:
            raise NotFoundError("Demo unavailable")
        self._require_account_principal()
        owner_id = current_account_id()
        await require_account_active(db, owner_id)
        await lock_project_ids_for_owner(db, owner_id)

        copy = (
            await db.execute(
                select(DemoProjectCopy)
                .where(
                    DemoProjectCopy.owner_id == owner_id,
                    DemoProjectCopy.source_project_id == config.project_id,
                    DemoProjectCopy.source_version == config.version,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if copy is not None:
            existing = await db.get(Project, copy.project_id, with_for_update=True)
            if existing is not None and existing.owner_id == owner_id:
                status = "existing"
                if existing.deleted_at is not None:
                    existing.deleted_at = None
                    await db.flush()
                    status = "restored"
                return DemoCopyResult(
                    status=status,
                    project=await self._projects.get_project(db, str(existing.id)),
                )
            await db.delete(copy)
            await db.flush()

        source = await self._source_project(db, config.project_id)
        destination = await self._projects.create_project(
            db,
            ProjectCreate(
                title=source.title,
                genre=source.genre,
                tone=source.tone,
                language=source.language,
                target_length=source.target_length,
                current_stage=source.current_stage,
                default_reveal_policy=source.default_reveal_policy,
                settings=_secret_free_project_context_settings(source.settings),
            ),
        )
        destination_id = uuid.UUID(destination.id)
        db.add(
            DemoProjectCopy(
                owner_id=owner_id,
                source_project_id=source.id,
                source_version=config.version,
                project_id=destination_id,
            )
        )
        await db.flush()

        copied_rows, rewrites = await self._copy_assets(
            db,
            source_id=source.id,
            destination_id=destination_id,
        )
        await self._copy_media(
            db,
            source_id=source.id,
            destination_id=destination_id,
            copied_rows=copied_rows,
            rewrites=rewrites,
        )
        return DemoCopyResult(
            status="created",
            project=await self._projects.get_project(db, str(destination_id)),
        )

    @staticmethod
    def _require_account_principal() -> None:
        principal = current_account_principal()
        if is_demo_readonly_principal() or (
            principal is not None
            and principal.identity_type in {"anonymous_rp", "demo_readonly"}
        ):
            raise NotFoundError("Authentication required")
        if get_settings().auth_mode == "public" and principal is None:
            raise NotFoundError("Authentication required")

    @staticmethod
    async def _source_project(db: AsyncSession, project_id: uuid.UUID) -> Project:
        source = (
            await db.execute(
                select(Project).where(
                    Project.id == project_id,
                    Project.project_kind == "author",
                    Project.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise NotFoundError("Demo unavailable")
        await require_account_active(db, source.owner_id)
        return source

    async def _copy_assets(
        self,
        db: AsyncSession,
        *,
        source_id: uuid.UUID,
        destination_id: uuid.UUID,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[Any, uuid.UUID]]]:
        tables = self._copy_tables()
        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        rewrites: dict[str, dict[Any, uuid.UUID]] = {}
        for table in tables:
            rows = [
                dict(row)
                for row in (
                    await db.execute(select(table).where(table.c.novel_id == source_id))
                ).mappings()
                if self._copyable_row(table, row)
            ]
            rows_by_table[table.name] = rows
            if "id" in table.primary_key.columns:
                rewrites[table.name] = {
                    row["id"]: uuid.uuid4() for row in rows if row.get("id") is not None
                }

        global_rewrites = {
            str(source_id): destination_id,
        } | {
            str(source): replacement
            for table_rewrites in rewrites.values()
            for source, replacement in table_rewrites.items()
        }
        if rows_by_table.get("world_canon_revisions"):
            canon_heads = Base.metadata.tables["world_canon_heads"]
            canon_revisions = Base.metadata.tables["world_canon_revisions"]
            await db.execute(
                delete(canon_heads).where(canon_heads.c.novel_id == destination_id)
            )
            await db.execute(
                delete(canon_revisions).where(
                    canon_revisions.c.novel_id == destination_id
                )
            )
        deferred: list[tuple[Table, uuid.UUID, str, uuid.UUID]] = []
        for position, table in enumerate(tables):
            for row in rows_by_table[table.name]:
                values = self._row_values(
                    table,
                    row,
                    destination_id=destination_id,
                    rewrites=rewrites,
                    global_rewrites=global_rewrites,
                    table_position=position,
                    tables=tables,
                    deferred=deferred,
                )
                if values is not None:
                    await db.execute(table.insert().values(**values))

        for table, row_id, column_name, value in deferred:
            await db.execute(
                update(table).where(table.c.id == row_id).values({column_name: value})
            )
        await db.flush()
        return rows_by_table, rewrites

    @staticmethod
    def _copy_tables() -> list[Table]:
        missing = [name for name in _COPY_TABLE_NAMES if name not in Base.metadata.tables]
        if missing:
            raise RuntimeError(
                f"Demo copy tables are not registered: {', '.join(missing)}"
            )
        return [Base.metadata.tables[name] for name in _COPY_TABLE_NAMES]

    @staticmethod
    def _copyable_row(table: Table, row: dict[str, Any]) -> bool:
        if table.name == "map_atlas_pages":
            return row.get("review_status") in {"adopted", "deprecated"}
        status = row.get("status")
        return not isinstance(status, str) or status not in _CANDIDATE_STATUSES

    @staticmethod
    def _row_values(
        table: Table,
        row: dict[str, Any],
        *,
        destination_id: uuid.UUID,
        rewrites: dict[str, dict[Any, uuid.UUID]],
        global_rewrites: dict[str, uuid.UUID],
        table_position: int,
        tables: list[Table],
        deferred: list[tuple[Table, uuid.UUID, str, uuid.UUID]],
    ) -> dict[str, Any] | None:
        values = {
            column.name: _rewrite_embedded_ids(value, global_rewrites)
            for column in table.columns
            if column.name in row
            and column.name not in {"created_at", "updated_at"}
            and column.name not in _DERIVED_COLUMNS
            and column.computed is None
            for value in [row[column.name]]
        }
        if "novel_id" in values:
            values["novel_id"] = destination_id
        if "id" in values and table.name in rewrites:
            values["id"] = rewrites[table.name][row["id"]]
        if table.name == "core_entities" and values.get("image_version") is not None:
            values["image_version"] = uuid.uuid4()
        if table.name == "map_atlas_pages":
            values["object_key"] = None
            values["mask_object_key"] = None
        if table.name == "map_atlas_runs":
            for column_name, value in {
                "task_id": None,
                "context_snapshot": {},
                "source_manifest": [],
                "llm_execution_snapshot": {},
                "image_execution_snapshot": {},
                "error_code": None,
                "error_message": None,
            }.items():
                if column_name in values:
                    values[column_name] = value

        positions = {candidate.name: index for index, candidate in enumerate(tables)}
        for foreign_key in table.foreign_keys:
            column = foreign_key.parent
            value = row.get(column.name)
            if value is None or column.name == "novel_id":
                continue
            target = foreign_key.column.table
            target_rewrites = rewrites.get(target.name)
            if target_rewrites is None:
                if target.name in {"async_tasks", "map_atlas_runs"}:
                    values[column.name] = None
                continue
            replacement = target_rewrites.get(value)
            if replacement is None:
                if column.nullable:
                    values[column.name] = None
                    continue
                return None
            target_after_current = positions.get(target.name, -1) > table_position
            if target.name == table.name or target_after_current:
                values[column.name] = None
                if "id" in values:
                    deferred.append((table, values["id"], column.name, replacement))
            else:
                values[column.name] = replacement
        return values

    async def _copy_media(
        self,
        db: AsyncSession,
        *,
        source_id: uuid.UUID,
        destination_id: uuid.UUID,
        copied_rows: dict[str, list[dict[str, Any]]],
        rewrites: dict[str, dict[Any, uuid.UUID]],
    ) -> None:
        written: list[tuple[Any, str]] = []
        try:
            await self._copy_entity_images(
                db,
                source_id=source_id,
                destination_id=destination_id,
                rows=copied_rows.get("core_entities", []),
                rewrites=rewrites.get("core_entities", {}),
                written=written,
            )
            await self._copy_map_images(
                db,
                source_id=source_id,
                destination_id=destination_id,
                rows=copied_rows.get("map_atlas_pages", []),
                rewrites=rewrites.get("map_atlas_pages", {}),
                written=written,
            )
        except Exception:
            await self._cleanup_media(written)
            raise

    async def _copy_entity_images(
        self,
        db: AsyncSession,
        *,
        source_id: uuid.UUID,
        destination_id: uuid.UUID,
        rows: Iterable[dict[str, Any]],
        rewrites: dict[Any, uuid.UUID],
        written: list[tuple[Any, str]],
    ) -> None:
        image_rows = [row for row in rows if row.get("image_version") is not None]
        if not image_rows:
            return
        from modules.world.world_object_images import (
            WorldObjectImageStorage,
            image_object_key,
        )

        try:
            storage = self._image_storage or WorldObjectImageStorage()
        except RuntimeError as exc:
            raise DomainError(
                "Demo image storage is unavailable",
                code="demo_media_copy_unavailable",
                status_code=503,
            ) from exc
        try:
            table = Base.metadata.tables["core_entities"]
            for row in image_rows:
                new_entity_id = rewrites.get(row["id"])
                if new_entity_id is None:
                    continue
                destination = await db.scalar(
                    select(table.c.image_version).where(table.c.id == new_entity_id)
                )
                if destination is None:
                    continue
                for variant in ("full", "thumbnail"):
                    destination_key = image_object_key(
                        str(destination_id),
                        str(new_entity_id),
                        str(destination),
                        variant,
                    )
                    payload = await storage.get_webp(
                        image_object_key(
                            str(source_id),
                            str(row["id"]),
                            str(row["image_version"]),
                            variant,
                        ),
                        max_bytes=256 * 1024,
                    )
                    written.append((storage, destination_key))
                    await storage.put_webp(destination_key, payload)
        except Exception as exc:
            raise DomainError(
                "Demo image copy failed",
                code="demo_media_copy_failed",
                status_code=503,
            ) from exc

    async def _copy_map_images(
        self,
        db: AsyncSession,
        *,
        source_id: uuid.UUID,
        destination_id: uuid.UUID,
        rows: Iterable[dict[str, Any]],
        rewrites: dict[Any, uuid.UUID],
        written: list[tuple[Any, str]],
    ) -> None:
        image_rows = [
            row for row in rows if row.get("object_key") or row.get("mask_object_key")
        ]
        if not image_rows:
            return
        from modules.world.map_atlas_storage import MapAtlasStorage, page_object_key

        try:
            storage = self._map_storage or MapAtlasStorage()
        except RuntimeError as exc:
            raise DomainError(
                "Demo map storage is unavailable",
                code="demo_media_copy_unavailable",
                status_code=503,
            ) from exc
        table = Base.metadata.tables["map_atlas_pages"]
        try:
            for row in image_rows:
                new_page_id = rewrites.get(row["id"])
                if new_page_id is None:
                    continue
                values: dict[str, str] = {}
                if row.get("object_key"):
                    destination_key = page_object_key(
                        str(destination_id), str(new_page_id)
                    )
                    payload = await storage.get_png(str(row["object_key"]))
                    written.append((storage, destination_key))
                    await storage.put_png(destination_key, payload)
                    values["object_key"] = destination_key
                if row.get("mask_object_key"):
                    destination_key = page_object_key(
                        str(destination_id), str(new_page_id), mask=True
                    )
                    payload = await storage.get_png(str(row["mask_object_key"]))
                    written.append((storage, destination_key))
                    await storage.put_png(destination_key, payload)
                    values["mask_object_key"] = destination_key
                if values:
                    await db.execute(
                        update(table).where(table.c.id == new_page_id).values(**values)
                    )
        except Exception as exc:
            raise DomainError(
                "Demo map copy failed",
                code="demo_media_copy_failed",
                status_code=503,
            ) from exc

    @staticmethod
    async def _cleanup_media(items: Iterable[tuple[Any, str]]) -> None:
        for storage, key in reversed(list(items)):
            try:
                await storage.delete_object(key)
            except Exception:
                pass


def _rewrite_embedded_ids(value: Any, rewrites: dict[str, uuid.UUID]) -> Any:
    if isinstance(value, uuid.UUID):
        return rewrites.get(str(value), value)
    if isinstance(value, str):
        replacement = rewrites.get(value)
        return str(replacement) if replacement is not None else value
    if isinstance(value, list):
        return [_rewrite_embedded_ids(item, rewrites) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_embedded_ids(item, rewrites) for key, item in value.items()}
    return value

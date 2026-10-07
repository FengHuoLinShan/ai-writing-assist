"""
Project 对外契约

定义其他模块可以安全依赖的项目接口和数据类。
仅可导入 contracts.py 和 facade.py。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.project.schemas import ProjectContext  # noqa: F401


@dataclass(frozen=True)
class ProjectSummary:
    """Lightweight active project projection for cross-module aggregations."""

    project_id: uuid.UUID
    title: str


@dataclass(frozen=True)
class InteractionProjectContract:
    """Hidden interaction project created for exactly one RP journey."""

    novel_id: str
    owner_id: uuid.UUID


class ProjectLLMConfigurationError(ValidationError):
    """The requested project has no usable business LLM profile."""

    code = "project_llm_configuration_error"


class ProjectImageConfigurationError(ValidationError):
    """The project's owner has no usable GPT Image 2 connection."""

    code = "project_image_configuration_error"


# ============================================================
# 工作台统计与智能去重 provider SPI（AO-4）— project 是 L1 隔离根，
# 不再顶层 import world/story/writing 聚合统计；各域在组合根注册
# 下方协议的薄 adapter，project 侧只消费这里的稳定形状 + core.container。
# ============================================================


@dataclass(frozen=True)
class WorkspaceWritingStats:
    """Project-side manuscript statistics for one novel (latest per chapter)."""

    novel_id: str
    chapter_count: int = 0
    word_count: int = 0


@dataclass(frozen=True)
class WorkspaceChapterDraft:
    """Latest-draft projection of one chapter for the workspace continuation."""

    chapter_index: int
    title: str | None = None
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class WorkspaceAttentionItem:
    """One domain attention item projected into the workspace read model."""

    key: str
    title: str = ""
    summary: str = ""
    author_action: str | None = None
    severity: str | None = None
    source_kind: str | None = None
    target_kind: str | None = None
    item_id: str | None = None
    chapter_index: int | None = None
    scene_id: str | None = None
    scene_ids: tuple[str, ...] = ()
    page_id: str | None = None
    suggestion_id: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class WorkspaceWorldAttentionSummary:
    """World review counts and items for the workspace attention summary."""

    novel_id: str
    world_objects: int = 0
    world_aliases: int = 0
    world_relations: int = 0
    items: tuple[WorkspaceAttentionItem, ...] = ()

    @property
    def total(self) -> int:
        return self.world_objects + self.world_aliases + self.world_relations


@dataclass(frozen=True)
class WorkspaceSceneFocus:
    """Scene chapter membership used to validate a workspace focus scene."""

    id: str
    chapter_indices: tuple[int, ...] = ()


class WritingWorkspaceStatsProvider(Protocol):
    """Manuscript statistics and conflict attention owned by Writing."""

    async def get_project_stats(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WorkspaceWritingStats: ...

    async def list_project_stats(
        self,
        db: AsyncSession,
        novel_ids: list[str],
    ) -> dict[str, WorkspaceWritingStats]: ...

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[int]: ...

    async def list_latest_drafts(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_indices: list[int],
        *,
        content_limit: int | None = None,
    ) -> list[WorkspaceChapterDraft]: ...

    async def get_attention_items(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> Sequence[WorkspaceAttentionItem]: ...


class WorldWorkspaceStatsProvider(Protocol):
    """World review counts and attention items for the workspace summary."""

    async def get_attention_summary(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WorkspaceWorldAttentionSummary: ...


class StoryWorkspaceStatsProvider(Protocol):
    """Scene progress and attention items owned by Story."""

    async def count_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status_filter: list[str] | None = None,
    ) -> int: ...

    async def get_attention_items(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> Sequence[WorkspaceAttentionItem]: ...

    async def get_scene_focus(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> WorkspaceSceneFocus | None: ...


class WorldDedupSuggestionProvider(Protocol):
    """World entity-fusion dedup suggestions and caller-transactional applies."""

    async def suggest_entity_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int,
        max_suggestions: int,
        group_before_budget: bool,
        progress_callback: Any | None,
        exclusions: list[dict[str, Any]] | None,
        llm_client: Any | None,
    ) -> dict[str, Any]: ...

    async def apply_entity_fusion_group(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        primary_entity_id: str,
        operations: list[dict[str, Any]],
        validate_only: bool,
        execution_fingerprints_prevalidated: bool,
    ) -> list[dict[str, Any]]: ...

    async def apply_entity_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        confirmed: bool,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


class StoryDedupSuggestionProvider(Protocol):
    """Story structure dedup suggestions and caller-transactional applies."""

    async def suggest_structure_dedup(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        asset_types: list[str],
        limit: int,
        max_suggestions: int,
        progress_callback: Any | None,
        exclusions: list[dict[str, Any]] | None,
        llm_client: Any | None,
    ) -> dict[str, Any]: ...

    async def apply_structure_dedup_group(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        asset_type: str,
        primary_asset_id: str,
        operations: list[dict[str, Any]],
        validate_only: bool,
        execution_fingerprints_prevalidated: bool,
    ) -> list[dict[str, Any]]: ...

    async def apply_structure_dedup(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        confirmed: bool,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

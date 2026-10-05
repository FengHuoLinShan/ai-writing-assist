"""Restricted, review-first import of external worldbook text files."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from yaml.tokens import AliasToken, AnchorToken, TagToken

from core.errors import ConflictError, ValidationError
from modules.world.models import (
    WorldBibleCategory,
    WorldBiblePage,
    WorldBiblePageDraft,
)
from modules.world.schemas import (
    CreationSuggestionCreate,
    WorldBibleCategoryCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftUpdate,
    WorldbookImportApplyRequest,
    WorldbookImportApplyResponse,
    WorldbookImportFile,
    WorldbookImportItem,
    WorldbookImportLegacyBinding,
    WorldbookImportManifest,
    WorldbookImportPayload,
    WorldbookImportPreviewResponse,
    WorldValidationPolicy,
)
from modules.world.services.worldbuilding.conflict_queue_service import (
    ConflictQueueService,
)
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    BUILTIN_WORLD_BIBLE_CATEGORIES,
    WorldBibleLifecycleService,
)
from shared.utils import parse_uuid

_ALLOWED_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})
_CONTROL_NAMES = frozenset(
    {"agents.md", "claude.md", "skill.md", "gemfile", "rakefile", "_sidebar.md"}
)
_CONTROL_PARTS = frozenset(
    {".git", ".github", ".obsidian", "node_modules", "scripts", "tools"}
)
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_BYTES = 25 * 1024 * 1024
# 与 WorldBibleCategoryCreate.category_key 的 schema 约束保持一致
# （pattern ^[a-z][a-z0-9_]*$ + min_length=2 + max_length=64）。
_CATEGORY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
# 双链扫描形态与校验引擎的 `_WIKILINK_RE`（world_validation_engine.py）保持同一
# 词法：`[[…]]` 内不含换行。预览四态与引擎 findings 是两套独立机制
# （m1-contract 第 4 条冻结），这里只借用词法定义，不消费引擎结论。
_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
# 与 `_validate_asset_refs` 的每页上限（world_bible_lifecycle_service）对齐；
# 物化超出即截断，并在对应 item.reason 明示。
_MAX_ASSET_REFS = 100


@dataclass(frozen=True)
class _LinkOccurrence:
    """单条引用出现的解析结果（m1-contract 第 4 条）。

    ``alias``（``|显示文本``）与 ``anchor``（``#段落``）不参与身份匹配，
    仅保留在解析结果中供预览展示；``origin`` 区分正文双链与 frontmatter
    ``related``。原始正文与文件绝不改写。
    """

    raw: str
    target: str
    alias: str
    anchor: str
    is_path: bool
    origin: str


@dataclass(frozen=True)
class _LinkCandidate:
    """四态判定的命中候选；``identity`` 用于跨来源去重同一页面对象。

    ``identity`` 统一取 (``"key"``, source_key)（本批与既有 dataset 成员同
    key 即同一对象，preserve/update 重导天然去重）；无导入 meta 的已发布页
    退化为 (``"page"``, page_id)。``rel_path`` 为未归一化的资料集内相对路径，
    供 ``local:`` 约定拼接。
    """

    identity: tuple
    kind: str  # "batch" | "member" | "published"
    title_key: str
    rel_key: str | None
    rel_path: str | None
    target: Any


@dataclass(frozen=True)
class _LinkPlan:
    """每页引用计划：四态计数 + 可物化 refs（已按去重与上限截断）。"""

    summary: dict[str, int]
    refs: list[dict[str, Any]]
    truncated: bool
    reason_suffix: str = ""


@dataclass(frozen=True)
class _DatasetIdentity:
    """作者声明资料集的稳定身份（m1-contract 第 2 条，冻结）。

    ``key`` 由归一化 dataset_name 派生，不使用本机绝对路径或所选根目录名；
    ``commit_mode`` 决定 missing 判定范围（m1-contract 第 3 条）；``intent``
    承载作者的新建/继续/接续选择（接续 legacy 见 ``_analyze`` 的绑定索引）。
    """

    key: str
    name: str
    commit_mode: str
    intent: str = "continue"


class WorldbookImportService:
    def __init__(
        self,
        *,
        suggestions: SuggestionQueueService | None = None,
        conflicts: ConflictQueueService | None = None,
        lifecycle: WorldBibleLifecycleService | None = None,
    ) -> None:
        self._suggestions = suggestions or SuggestionQueueService()
        self._conflicts = conflicts or ConflictQueueService()
        self._lifecycle = lifecycle or WorldBibleLifecycleService()

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        manifest: WorldbookImportManifest,
    ) -> WorldbookImportPreviewResponse:
        dataset = self._dataset_identity(manifest)
        analysis = await self._analyze(
            db,
            novel_id,
            manifest.files,
            source_format=(
                manifest.source_format if manifest.source_format != "auto" else None
            ),
            dataset=dataset,
            strip_roots=dataset is not None,
        )
        dataset_payload = dataset is not None or (
            manifest.schema_version == "world_worldbook_import.v2"
        )
        payload = WorldbookImportPayload(
            schema_version=(
                "world_worldbook_import.v2"
                if dataset_payload
                else "world_worldbook_import.v1"
            ),
            source_format=analysis["source_format"],
            manifest_hash=analysis["manifest_hash"],
            preview_hash=analysis["preview_hash"],
            dataset_name=dataset.name if dataset else None,
            dataset_key=dataset.key if dataset else None,
            dataset_intent=dataset.intent if dataset else "continue",
            commit_mode=manifest.commit_mode,
            source_paths=analysis["source_paths"],
            files=analysis["files"],
            items=analysis["items"],
            ignored_paths=analysis["ignored_paths"],
            legacy_bindings=analysis["legacy_bindings"],
        )
        suggestion = await self._suggestions.create(
            db,
            CreationSuggestionCreate(
                novel_id=novel_id,
                source_module="world",
                review_group="worldbook_import",
                target_type="worldbook_import",
                action_schema=payload.schema_version,
                payload_json=payload.model_dump(mode="json"),
                risk_level="high",
            ),
        )
        return self._preview_response(suggestion.id, payload)

    @staticmethod
    def _dataset_identity(manifest: WorldbookImportManifest) -> _DatasetIdentity | None:
        """从 manifest 派生资料集身份；无 dataset_name 即 legacy 语义。"""
        if manifest.dataset_name is None:
            return None
        name = unicodedata.normalize("NFC", manifest.dataset_name).strip()
        if not name or len(name) > 80:
            raise ValidationError("Dataset name must be 1-80 characters")
        key = hashlib.sha256(
            f"worldbook.dataset.v1\0{name.casefold()}".encode()
        ).hexdigest()
        return _DatasetIdentity(
            key=key,
            name=name,
            commit_mode=manifest.commit_mode,
            intent=manifest.dataset_intent,
        )

    async def get_preview(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> WorldbookImportPreviewResponse:
        suggestion = await self._suggestions._get_suggestion(db, novel_id, suggestion_id)
        if suggestion.target_type != "worldbook_import":
            raise ValidationError("Suggestion is not a worldbook import")
        return self._preview_response(
            str(suggestion.id),
            WorldbookImportPayload.model_validate(suggestion.payload_json),
        )

    async def apply(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        request: WorldbookImportApplyRequest,
    ) -> WorldbookImportApplyResponse:
        suggestion = await self._suggestions._get_pending(db, novel_id, suggestion_id)
        if suggestion.target_type != "worldbook_import":
            raise ValidationError("Suggestion is not a worldbook import")
        stored = WorldbookImportPayload.model_validate(suggestion.payload_json)
        dataset = None
        if stored.dataset_key:
            dataset = _DatasetIdentity(
                key=stored.dataset_key,
                name=str(stored.dataset_name or ""),
                commit_mode=stored.commit_mode,
                intent=stored.dataset_intent,
            )
        # m1-contract 第 6 条冻结前提：先取项目+资料集 advisory lock，在锁内重放
        # _analyze 复验来源身份与目标基线，再 claim 写入。锁键与 publish 链的
        # world_bible_pages:{novel_id} 不同；导入链不取 universe 锁，两把锁
        # 无交叉获取顺序。重放直接以 stored.files 的 rel_path 计算，不二次剥根。
        await self._lock_import(db, novel_id, stored.dataset_key)
        analysis = await self._analyze(
            db,
            novel_id,
            stored.files,
            source_format=stored.source_format,
            dataset=dataset,
            strip_roots=False,
            stored_ignored_paths=stored.ignored_paths,
            source_paths=stored.source_paths or None,
        )
        if analysis["manifest_hash"] != stored.manifest_hash:
            raise ConflictError("Worldbook import manifest changed; preview again")
        if (
            request.expected_preview_hash != stored.preview_hash
            or analysis["preview_hash"] != stored.preview_hash
        ):
            raise ConflictError("Worldbook target changed; preview again")

        # ponytail: bounded 25 MiB apply stays atomic; add task checkpoints only if
        # measured request latency exceeds the HTTP budget.
        suggestion = await self._suggestions._claim_pending(db, novel_id, suggestion_id)
        await self._ensure_declared_categories(db, novel_id, analysis["items"])
        mapped_files = {item["source_key"]: item for item in analysis["mapped_files"]}
        draft_ids: list[str] = []
        conflict_items: list[WorldbookImportItem] = []
        for item in analysis["items"]:
            if item.action == "missing":
                current = analysis["existing_sources"].get(item.source_key)
                if current is not None:
                    missing_meta = dict(current.page_meta_json or {})
                    source_meta = dict(missing_meta.get("worldbook_import") or {})
                    source_meta.update(
                        {
                            "source_missing": True,
                            "missing_manifest_hash": analysis["manifest_hash"],
                        }
                    )
                    missing_meta["worldbook_import"] = source_meta
                    if isinstance(current, WorldBiblePageDraft):
                        marked = await self._lifecycle.update_draft(
                            db,
                            novel_id,
                            str(current.id),
                            WorldBiblePageDraftUpdate(
                                page_meta_json=missing_meta,
                                updated_by="worldbook_import",
                            ),
                        )
                    else:
                        marked = await self._lifecycle.create_draft(
                            db,
                            WorldBiblePageDraftCreate(
                                novel_id=novel_id,
                                page_id=str(current.id),
                                title=current.title,
                                page_type=current.page_type,
                                page_meta_json=missing_meta,
                                free_text=current.free_text,
                                sections_json=list(current.sections_json or []),
                                linked_asset_refs_json=list(
                                    current.linked_asset_refs_json or []
                                ),
                                sort_order=current.sort_order,
                                template_key=current.template_key,
                                template_version=current.template_version,
                                created_by="worldbook_import",
                            ),
                            # 恢复工作稿只复制页面既有 refs；若页面历史 refs
                            # 含 local: 约定，保持原样不升级校验口径。
                            allow_local_refs=True,
                        )
                    draft_ids.append(marked.id)
                conflict_items.append(item)
                continue
            if item.action == "conflict":
                conflict_items.append(item)
                continue
            if item.action == "preserve":
                current = analysis["existing_sources"].get(item.source_key) or analysis[
                    "bound_sources"
                ].get(item.source_key)
                source_meta = dict(
                    ((current.page_meta_json or {}).get("worldbook_import") or {})
                    if current is not None
                    else {}
                )
                # adopt_legacy 接续：preserve 条目一次性补写 dataset 绑定字段
                # （走 update_draft，接受既有 confirmation 失效副作用，契约第 2 条）。
                needs_binding = (
                    dataset is not None
                    and current is not None
                    and not source_meta.get("dataset_key")
                )
                if isinstance(current, WorldBiblePageDraft) and (
                    source_meta.get("source_missing") or needs_binding
                ):
                    mapped = mapped_files[item.source_key]
                    restored_meta = dict(current.page_meta_json or {})
                    # preserve 不物化 refs；基线口径保持该页现值 refs，与
                    # preserve 判定（current_hash == baseline）同口径，
                    # 不在物化之外改写 baseline（m1-contract 第 4 条）。
                    new_meta = self._source_meta(
                        mapped,
                        analysis["source_format"],
                        analysis["manifest_hash"],
                        dataset,
                        refs=list(current.linked_asset_refs_json or []),
                    )
                    self._carry_forward_source_path(new_meta, source_meta, dataset)
                    restored_meta["worldbook_import"] = new_meta
                    restored = await self._lifecycle.update_draft(
                        db,
                        novel_id,
                        str(current.id),
                        WorldBiblePageDraftUpdate(
                            page_meta_json=restored_meta,
                            updated_by="worldbook_import",
                        ),
                    )
                    draft_ids.append(restored.id)
                continue
            mapped = mapped_files[item.source_key]
            # 物化（m1-contract 第 4 条）：仅 create/update 建引用；refs 按本批
            # item 的最终引用计划取值，baseline 在 `_source_meta` 内按含 refs
            # 字段组计算（冻结决定 a）。ambiguous/unresolved/unselected 不建。
            plan = analysis["link_plans"].get(item.source_key)
            refs = list(plan.refs) if plan is not None else []
            allow_local_refs = any(
                str(ref.get("target_id") or "").startswith("local:") for ref in refs
            )
            meta = self._source_meta(
                mapped,
                analysis["source_format"],
                analysis["manifest_hash"],
                dataset,
                refs=refs,
            )
            if dataset is not None and item.action in {"update", "preserve"}:
                previous = analysis["existing_sources"].get(item.source_key) or analysis[
                    "bound_sources"
                ].get(item.source_key)
                if previous is not None:
                    self._carry_forward_source_path(
                        meta,
                        dict(
                            (previous.page_meta_json or {}).get("worldbook_import") or {}
                        ),
                        dataset,
                    )
            if item.action == "create":
                created = await self._lifecycle.create_draft(
                    db,
                    WorldBiblePageDraftCreate(
                        novel_id=novel_id,
                        title=mapped["title"],
                        page_type=mapped["page_type"],
                        page_meta_json=self._page_meta(mapped, meta),
                        free_text=mapped["content"],
                        linked_asset_refs_json=refs,
                        created_by="worldbook_import",
                    ),
                    allow_local_refs=allow_local_refs,
                )
            elif item.target_kind == "draft":
                created = await self._lifecycle.update_draft(
                    db,
                    novel_id,
                    item.target_id or "",
                    WorldBiblePageDraftUpdate(
                        title=mapped["title"],
                        page_type=mapped["page_type"],
                        page_meta_json=self._page_meta(mapped, meta),
                        free_text=mapped["content"],
                        linked_asset_refs_json=refs,
                        updated_by="worldbook_import",
                    ),
                    allow_local_refs=allow_local_refs,
                )
            else:
                created = await self._lifecycle.create_draft(
                    db,
                    WorldBiblePageDraftCreate(
                        novel_id=novel_id,
                        page_id=item.target_id,
                        title=mapped["title"],
                        page_type=mapped["page_type"],
                        page_meta_json=self._page_meta(mapped, meta),
                        free_text=mapped["content"],
                        linked_asset_refs_json=refs,
                        created_by="worldbook_import",
                    ),
                    allow_local_refs=allow_local_refs,
                )
            draft_ids.append(created.id)

        conflicts = await self._conflicts.replace_worldbook_import_conflicts(
            db,
            novel_id,
            suggestion_id=suggestion_id,
            manifest_hash=analysis["manifest_hash"],
            items=conflict_items,
        )
        counts = self._counts(analysis["items"])
        suggestion.result_ref_json = {
            "type": "worldbook_import",
            "receipt": "accepted",
            "manifest_hash": analysis["manifest_hash"],
            "preview_hash": analysis["preview_hash"],
            "counts": counts,
            "draft_ids": draft_ids,
            "conflict_ids": [item.id for item in conflicts],
        }
        suggestion.status = "accepted"
        await db.flush()
        return WorldbookImportApplyResponse(
            suggestion_id=suggestion_id,
            status="accepted",
            manifest_hash=analysis["manifest_hash"],
            preview_hash=analysis["preview_hash"],
            counts=counts,
            draft_ids=draft_ids,
            conflict_ids=[item.id for item in conflicts],
        )

    async def _ensure_declared_categories(
        self,
        db: AsyncSession,
        novel_id: str,
        items: list[WorldbookImportItem],
    ) -> None:
        """为导入声明的非内建 page_type 保障项目内活动分类存在。

        资料正文可声明任意受限 page_type（如 concept）；不补分类时 create/update
        会被 `_ensure_category_key` 拒绝。仅创建缺失分类，不触碰既有（含已归档）
        分类；已归档分类仍由工作稿校验给出明确错误，不静默复活。不符合分类键
        规则（`^[a-z][a-z0-9_]*$`、≥2 字符）的声明不在此构造分类，交由工作稿
        校验抛出业务 ValidationError，避免 pydantic 校验异常冒泡为内部错误。
        """
        nid = parse_uuid(novel_id, "novel_id")
        builtin = {item["category_key"] for item in BUILTIN_WORLD_BIBLE_CATEGORIES}
        declared = {
            item.page_type
            for item in items
            if item.action in {"create", "update"}
            and item.page_type not in builtin
            and _CATEGORY_KEY_RE.fullmatch(item.page_type)
        }
        for key in sorted(declared):
            exists = await db.scalar(
                select(WorldBibleCategory.id).where(
                    WorldBibleCategory.novel_id == nid,
                    WorldBibleCategory.category_key == key,
                )
            )
            if exists is not None:
                continue
            try:
                await self._lifecycle.create_category(
                    db,
                    WorldBibleCategoryCreate(
                        novel_id=novel_id,
                        category_key=key,
                        name=key,
                        description="由世界书导入声明的资料类型自动创建",
                        color="#475569",
                        icon="资料",
                        sort_order=500,
                    ),
                )
            except ConflictError as exc:
                raise ValidationError(
                    f"World Bible category for imported page_type is unavailable: {key}"
                ) from exc

    async def _analyze(
        self,
        db: AsyncSession,
        novel_id: str,
        files: list[WorldbookImportFile],
        *,
        source_format: str | None = None,
        dataset: _DatasetIdentity | None = None,
        strip_roots: bool = False,
        stored_ignored_paths: list[str] | None = None,
        source_paths: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        # identity_path：参与身份与指纹的路径（legacy=原始提交路径；
        # dataset=资料集内 rel_path）。original_path：原始提交路径（含根名），
        # 仅用于 page_meta.worldbook_import.source_path 语义保留。
        declared_sources = source_paths or {}
        entries: list[tuple[str, str, str]] = []
        ignored_paths: list[str] = []
        seen: set[str] = set()
        seen_rel: set[str] = set()
        total_bytes = 0
        raw_paths: list[str] = []
        for file in files:
            path = self._normalize_path(file.path)
            folded = unicodedata.normalize("NFC", path).casefold()
            if folded in seen:
                raise ValidationError(f"Duplicate worldbook path: {path}")
            seen.add(folded)
            identity_path = path
            original_path = declared_sources.get(path) or path
            if dataset is not None:
                if strip_roots:
                    # 冻结剥根规则：≥2 段去首段（所选根目录名），单段整段即 rel_path。
                    identity_path = self._strip_root(path)
                rel_folded = unicodedata.normalize("NFC", identity_path).casefold()
                if rel_folded in seen_rel:
                    raise ValidationError(
                        f"Duplicate worldbook dataset rel_path: {identity_path}"
                    )
                seen_rel.add(rel_folded)
            raw_paths.append(original_path)
            if (
                self._is_control_path(path)
                or PurePosixPath(path).suffix.lower() not in _ALLOWED_SUFFIXES
            ):
                ignored_paths.append(identity_path)
                continue
            size = len(file.content.encode("utf-8"))
            if "\x00" in file.content or "\ufffd" in file.content:
                raise ValidationError(
                    f"Worldbook file is not valid clean UTF-8 text: {identity_path}"
                )
            if size > _MAX_FILE_BYTES:
                raise ValidationError(f"Worldbook file exceeds 2 MiB: {identity_path}")
            total_bytes += size
            if total_bytes > _MAX_TOTAL_BYTES:
                raise ValidationError("Worldbook import exceeds 25 MiB")
            entries.append((identity_path, original_path, file.content))
        if not entries:
            raise ValidationError("Worldbook import contains no supported text files")

        source_format = source_format or self._detect_format(raw_paths)
        mapped_files = [
            self._map_file(
                WorldbookImportFile(path=identity_path, content=content),
                source_format,
                dataset_key=dataset.key if dataset else None,
                source_path=original_path,
            )
            for identity_path, original_path, content in entries
        ]
        if dataset is None:
            manifest_hash = self._hash(
                [
                    {"path": item["path"], "source_hash": item["source_hash"]}
                    for item in mapped_files
                ]
            )
        else:
            manifest_hash = self._hash(
                {
                    "schema_version": "world_worldbook_import.v2",
                    "dataset_key": dataset.key,
                    "files": sorted(
                        (
                            {"path": item["path"], "source_hash": item["source_hash"]}
                            for item in mapped_files
                        ),
                        key=lambda entry: (entry["path"].casefold(), entry["path"]),
                    ),
                }
            )
        existing = await self._existing_sources(db, novel_id)
        # 四态扫描候选集：项目内已发布页（canonical/confirmed）标题参与
        # 「唯一标题命中」；本批与同 dataset 既有成员索引见 `_build_link_index`。
        published_pages = await self._published_pages(db, novel_id)
        link_index = self._build_link_index(
            mapped_files, existing, dataset, published_pages
        )
        link_plans = {
            mapped["source_key"]: self._link_plan(mapped, link_index, dataset)
            for mapped in mapped_files
        }
        if dataset is not None and dataset.intent == "new":
            # m1-contract 第 2 条：显式声明新资料集时，派生 key 已存在即拒绝
            # （ValidationError→HTTP 400），提示继续维护或换名；不静默改写既有集。
            for current in existing.values():
                meta = dict((current.page_meta_json or {}).get("worldbook_import") or {})
                if str(meta.get("dataset_key") or "") == dataset.key:
                    raise ValidationError(
                        "Dataset name already exists in this project: "
                        f"{dataset.name}; continue maintaining it or choose "
                        "another name"
                    )
        # adopt_legacy：legacy 条目（meta 无 dataset_key 但有 source_key）按等效
        # rel_path（source_path 应用同一剥根规则 + NFC + casefold）建索引；同一
        # 等效 rel_path 出现多个 legacy 条目时置空，不按名称猜测身份。
        legacy_index: dict[str, tuple[str, Any, str] | None] = {}
        if dataset is not None and dataset.intent == "adopt_legacy":
            for key, current in existing.items():
                meta = dict((current.page_meta_json or {}).get("worldbook_import") or {})
                if meta.get("dataset_key") or not meta.get("source_key"):
                    continue
                legacy_rel = self._strip_root(str(meta.get("source_path") or ""))
                if not legacy_rel:
                    continue
                folded = unicodedata.normalize("NFC", legacy_rel).casefold()
                legacy_index[folded] = (
                    None
                    if folded in legacy_index
                    else (
                        key,
                        current,
                        str(meta.get("source_path") or ""),
                    )
                )
        bound_sources: dict[str, Any] = {}
        legacy_bindings: list[WorldbookImportLegacyBinding] = []
        items: list[WorldbookImportItem] = []
        seen_keys: set[str] = set()
        for mapped in mapped_files:
            source_key = mapped["source_key"]
            seen_keys.add(source_key)
            current = existing.get(source_key)
            if (
                current is None
                and dataset is not None
                and dataset.intent == "adopt_legacy"
            ):
                hit = legacy_index.get(
                    unicodedata.normalize("NFC", mapped["path"]).casefold()
                )
                if hit is not None:
                    legacy_source_key, current, legacy_source_path = hit
                    bound_sources[source_key] = current
                    legacy_bindings.append(
                        WorldbookImportLegacyBinding(
                            source_key=legacy_source_key,
                            legacy_source_path=legacy_source_path,
                            rel_path=mapped["path"],
                        )
                    )
            if current is None:
                action, reason = "create", "新来源"
                target_id = target_kind = current_hash = None
            else:
                current_hash = self._editable_content_hash(current)
                meta = dict((current.page_meta_json or {}).get("worldbook_import") or {})
                old_source_hash = str(meta.get("source_hash") or "")
                baseline_hash = str(meta.get("baseline_content_hash") or "")
                target_id = str(current.id)
                target_kind = (
                    "draft" if isinstance(current, WorldBiblePageDraft) else "page"
                )
                if mapped["source_hash"] == old_source_hash:
                    action, reason = "preserve", "来源未变化，保留项目版本"
                elif current_hash == baseline_hash:
                    action, reason = "update", "仅来源变化，可安全更新工作稿"
                else:
                    action, reason = "conflict", "来源和项目版本都已变化"
            items.append(
                WorldbookImportItem(
                    source_key=source_key,
                    path=mapped["path"],
                    title=mapped["title"],
                    page_type=mapped["page_type"],
                    source_hash=mapped["source_hash"],
                    action=action,
                    target_id=target_id,
                    target_kind=target_kind,
                    current_content_hash=current_hash,
                    reason=reason + link_plans[source_key].reason_suffix,
                    link_summary=dict(link_plans[source_key].summary),
                )
            )
        # missing 判定输入按提交语义收窄（m1-contract 第 3 条）：legacy 沿用
        # 项目级判定；dataset + full_snapshot 只看本 dataset_key 成员；append 不产生
        # missing，未出现成员一律不触碰。
        if dataset is None:
            missing_scope = existing
        elif dataset.commit_mode == "full_snapshot":
            missing_scope = {
                key: current
                for key, current in existing.items()
                if str(
                    ((current.page_meta_json or {}).get("worldbook_import") or {}).get(
                        "dataset_key"
                    )
                    or ""
                )
                == dataset.key
            }
        else:
            missing_scope = {}
        for source_key, current in missing_scope.items():
            if source_key in seen_keys:
                continue
            meta = dict((current.page_meta_json or {}).get("worldbook_import") or {})
            if dataset is None:
                missing_path = str(meta.get("source_path") or "missing")
            else:
                missing_path = str(
                    meta.get("rel_path") or meta.get("source_path") or "missing"
                )
            items.append(
                WorldbookImportItem(
                    source_key=source_key,
                    path=missing_path,
                    title=current.title,
                    page_type=current.page_type,
                    source_hash=str(meta.get("source_hash") or "0" * 64),
                    action="missing",
                    target_id=str(current.id),
                    target_kind=(
                        "draft" if isinstance(current, WorldBiblePageDraft) else "page"
                    ),
                    current_content_hash=self._editable_content_hash(current),
                    reason="原来源本次缺失；不会删除项目内容",
                )
            )
        items.sort(key=lambda item: (item.path.casefold(), item.source_key))
        ignored_sorted = sorted(ignored_paths, key=str.casefold)
        # 重放不得重算 ignored_paths（stored.files 只含纳入文件，重算恒为空集），
        # 指纹使用 stored 值保持与预览一致（m1-contract 第 5 条）。
        fingerprint_ignored = (
            sorted(stored_ignored_paths, key=str.casefold)
            if stored_ignored_paths is not None
            else ignored_sorted
        )
        if dataset is None:
            preview_hash = self._hash(
                {
                    "manifest_hash": manifest_hash,
                    "source_format": source_format,
                    "items": [item.model_dump(mode="json") for item in items],
                }
            )
        else:
            preview_hash = self._hash(
                {
                    "manifest_hash": manifest_hash,
                    "source_format": source_format,
                    "dataset_key": dataset.key,
                    "dataset_name": dataset.name,
                    "commit_mode": dataset.commit_mode,
                    "items": [item.model_dump(mode="json") for item in items],
                    "ignored_paths": fingerprint_ignored,
                }
            )
        return {
            "source_format": source_format,
            "manifest_hash": manifest_hash,
            "preview_hash": preview_hash,
            "files": [
                WorldbookImportFile(path=identity_path, content=content)
                for identity_path, _original, content in entries
            ],
            "source_paths": {
                item["path"]: item["source_path"]
                for item in mapped_files
                if item["source_path"] != item["path"]
            },
            "mapped_files": mapped_files,
            "items": items,
            "link_plans": link_plans,
            "ignored_paths": ignored_sorted,
            "existing_sources": existing,
            "bound_sources": bound_sources,
            "legacy_bindings": legacy_bindings,
        }

    async def _existing_sources(
        self, db: AsyncSession, novel_id: str
    ) -> dict[str, WorldBiblePageDraft | WorldBiblePage]:
        nid = parse_uuid(novel_id, "novel_id")
        drafts = (
            (
                await db.execute(
                    select(WorldBiblePageDraft).where(WorldBiblePageDraft.novel_id == nid)
                )
            )
            .scalars()
            .all()
        )
        pages = (
            (
                await db.execute(
                    select(WorldBiblePage).where(WorldBiblePage.novel_id == nid)
                )
            )
            .scalars()
            .all()
        )
        found: dict[str, WorldBiblePageDraft | WorldBiblePage] = {}
        for item in [*pages, *drafts]:
            key = str(
                ((item.page_meta_json or {}).get("worldbook_import") or {}).get(
                    "source_key"
                )
                or ""
            )
            if key:
                found[key] = item
        return found

    @staticmethod
    async def _published_pages(
        db: AsyncSession, novel_id: str
    ) -> list[Any]:
        """项目内已发布 WorldBiblePage（canonical/confirmed）行。

        `_existing_sources` 只覆盖带导入 meta 的条目；四态扫描的「唯一标题
        命中」还须包含作者手动创建的已发布页（m1-contract 第 4 条）。
        """
        nid = parse_uuid(novel_id, "novel_id")
        return list(
            (
                await db.execute(
                    select(
                        WorldBiblePage.id,
                        WorldBiblePage.title,
                        WorldBiblePage.status,
                    ).where(
                        WorldBiblePage.novel_id == nid,
                        WorldBiblePage.status.in_({"canonical", "confirmed"}),
                    )
                )
            )
            .all()
        )

    @classmethod
    def _map_file(
        cls,
        file: WorldbookImportFile,
        source_format: str,
        *,
        dataset_key: str | None = None,
        source_path: str | None = None,
    ) -> dict[str, Any]:
        content = file.content
        original_path = source_path or file.path
        title = PurePosixPath(file.path).stem
        metadata: dict[str, Any] = {}
        if PurePosixPath(file.path).suffix.lower() == ".md" and content.startswith(
            "---\n"
        ):
            end = content.find("\n---", 4, 20_004)
            if end != -1:
                metadata = cls._safe_yaml(content[4:end])
                title = str(metadata.get("title") or metadata.get("name") or title)
                content = content[end + 4 :].lstrip("\r\n")
        title = title.strip()[:255] or "未命名资料"
        page_type = cls._page_type(file.path, source_format, metadata)
        validation_policy = None
        declared_type = (
            str(metadata.get("page_type") or metadata.get("type") or "")
            .strip()
            .casefold()
            .replace("-", "_")
        )
        if declared_type == "validation_policy":
            raw_policy = metadata.get("validation_policy")
            if not isinstance(raw_policy, dict):
                raise ValidationError(
                    "A validation_policy page requires validation_policy metadata"
                )
            validation_policy = WorldValidationPolicy.model_validate(
                raw_policy
            ).model_dump(mode="json")
        source_hash = hashlib.sha256(file.content.encode("utf-8")).hexdigest()
        if dataset_key is None:
            # legacy 页级身份：格式 + 原始提交路径（v1 行为逐字节保留）。
            source_key = hashlib.sha256(
                f"{source_format}\0{file.path}".encode()
            ).hexdigest()
        else:
            # v2 页级身份：dataset_key + 资料集内 rel_path（m1-contract 第 2 条）。
            source_key = hashlib.sha256(
                f"{dataset_key}\0{file.path}".encode()
            ).hexdigest()
        return {
            "path": file.path,
            "source_path": original_path,
            "title": title,
            "page_type": page_type,
            "content": content,
            "frontmatter": metadata,
            "validation_policy": validation_policy,
            "source_hash": source_hash,
            "source_key": source_key,
        }

    @classmethod
    def _safe_yaml(cls, value: str) -> dict[str, Any]:
        try:
            tokens = yaml.scan(value)
            if any(
                isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in tokens
            ):
                raise ValidationError(
                    "Worldbook YAML aliases, anchors, and tags are forbidden"
                )
            parsed = yaml.safe_load(value) or {}
        except ValidationError:
            raise
        except yaml.YAMLError as exc:
            raise ValidationError("Worldbook YAML metadata is invalid") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("Worldbook YAML metadata must be an object")
        budget = [0]
        return cls._bounded_yaml(parsed, depth=0, budget=budget)

    @classmethod
    def _bounded_yaml(cls, value: Any, *, depth: int, budget: list[int]) -> Any:
        budget[0] += 1
        if depth > 6 or budget[0] > 2_000:
            raise ValidationError("Worldbook YAML metadata is too complex")
        if isinstance(value, dict):
            if len(value) > 200:
                raise ValidationError("Worldbook YAML metadata is too complex")
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > 128:
                    raise ValidationError(
                        "Worldbook YAML metadata keys must be bounded strings"
                    )
                normalized[key] = cls._bounded_yaml(item, depth=depth + 1, budget=budget)
            return normalized
        if isinstance(value, list):
            if len(value) > 200:
                raise ValidationError("Worldbook YAML metadata is too complex")
            return [
                cls._bounded_yaml(item, depth=depth + 1, budget=budget) for item in value
            ]
        if isinstance(value, str) and len(value) > 10_000:
            raise ValidationError("Worldbook YAML metadata value is too long")
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        raise ValidationError("Worldbook YAML metadata contains an unsupported value")

    @staticmethod
    def _normalize_path(value: str) -> str:
        if not value or "\x00" in value or "\\" in value or value.startswith("/"):
            raise ValidationError("Worldbook path must be a safe relative POSIX path")
        normalized = unicodedata.normalize("NFC", value)
        parts = normalized.split("/")
        if any(not part or part in {".", ".."} or len(part) > 255 for part in parts):
            raise ValidationError("Worldbook path contains an unsafe segment")
        if len(normalized) > 1024 or (len(parts[0]) >= 2 and parts[0][1] == ":"):
            raise ValidationError("Worldbook path is too long or drive-qualified")
        return str(PurePosixPath(*parts))

    @staticmethod
    def _strip_root(path: str) -> str:
        """剥除所选根目录名：≥2 段去首段，单段整段即 rel_path（冻结规则）。"""
        parts = PurePosixPath(path).parts
        if len(parts) < 2:
            return path
        return str(PurePosixPath(*parts[1:]))

    @staticmethod
    def _is_control_path(path: str) -> bool:
        parts = [part.casefold() for part in PurePosixPath(path).parts]
        return bool(
            set(parts) & _CONTROL_PARTS
            or parts[-1] in _CONTROL_NAMES
            or parts[-1].endswith((".rb", ".py", ".sh", ".js", ".ts"))
        )

    @staticmethod
    def _detect_format(paths: list[str]) -> str:
        folded = [path.casefold() for path in paths]
        if any("/.obsidian/" in f"/{path}/" for path in folded):
            return "obsidian"
        if any(
            "/.wiki/raw/" in f"/{path}/" or "/.wiki/wiki/" in f"/{path}/"
            for path in folded
        ):
            return "llmwiki"
        if any(
            PurePosixPath(path).name.casefold() in {"_sidebar.md", "home.md"}
            for path in folded
        ):
            return "llmwiki"
        return "generic"

    @staticmethod
    def _page_type(
        path: str,
        source_format: str,
        metadata: dict[str, Any],
    ) -> str:
        folded_parts = [part.casefold() for part in PurePosixPath(path).parts]
        is_raw = "_raw" in folded_parts or (
            ".wiki" in folded_parts
            and "raw" in folded_parts[folded_parts.index(".wiki") + 1 :]
        )
        if is_raw or PurePosixPath(path).suffix.lower() != ".md":
            return "source_material"
        if source_format not in {"obsidian", "llmwiki", "wiki_markdown"}:
            return "source_material"
        candidate = str(metadata.get("page_type") or metadata.get("type") or "custom")
        normalized = candidate.strip().casefold().replace("-", "_")
        if (
            not normalized
            or len(normalized) > 64
            or not all(char.isalnum() or char == "_" for char in normalized)
        ):
            return "custom"
        if normalized == "validation_policy":
            return "rule"
        return "source_material" if normalized in {"source", "raw"} else normalized

    # ------------------------------------------------------------------
    # Wiki 引用四态扫描（m1-contract 第 4 条）：解析与判定均为确定性纯
    # 函数，preview 与 apply 重放共用同一实现；候选集构建是唯一 IO 边界，
    # 在 `_analyze` 内完成后传入，同一事务内天然一致。
    # ------------------------------------------------------------------

    @classmethod
    def _parse_link_occurrences(cls, mapped: dict[str, Any]) -> list[_LinkOccurrence]:
        """解析单页引用：正文双链 + frontmatter ``related``（逐项拆分）。

        ``related`` 值为字符串或列表，项可含 ``[[…]]``（逐个解析）或纯名称
        （整项作为目标）。原始正文与文件绝不改写。
        """
        occurrences: list[_LinkOccurrence] = []
        for match in _WIKILINK_RE.finditer(str(mapped.get("content") or "")):
            occurrence = cls._parse_wikilink(match.group(1), "free_text")
            if occurrence is not None:
                occurrences.append(occurrence)
        related = (mapped.get("frontmatter") or {}).get("related")
        for value in cls._related_values(related):
            stripped = value.strip()
            matches = list(_WIKILINK_RE.finditer(stripped))
            if matches:
                for match in matches:
                    occurrence = cls._parse_wikilink(match.group(1), "frontmatter")
                    if occurrence is not None:
                        occurrences.append(occurrence)
            elif stripped:
                occurrences.append(
                    _LinkOccurrence(
                        raw=stripped,
                        target=stripped,
                        alias="",
                        anchor="",
                        is_path="/" in stripped,
                        origin="frontmatter",
                    )
                )
        return occurrences

    @staticmethod
    def _related_values(related: Any) -> list[str]:
        if related is None:
            return []
        if isinstance(related, str):
            return [related]
        if isinstance(related, list):
            return [item for item in related if isinstance(item, str)]
        return []

    @staticmethod
    def _parse_wikilink(inner: str, origin: str) -> _LinkOccurrence | None:
        """拆分 ``[[…]]`` 内部：``|显示文本`` 与 ``#段落`` 不参与身份匹配。"""
        target_part, _, alias = inner.partition("|")
        target, _, anchor = target_part.partition("#")
        target = target.strip()
        if not target:
            return None
        return _LinkOccurrence(
            raw=f"[[{inner}]]",
            target=target,
            alias=alias.strip(),
            anchor=anchor.strip(),
            is_path="/" in target,
            origin=origin,
        )

    @staticmethod
    def _normalize_link_title(value: str) -> str:
        return unicodedata.normalize("NFC", value.strip()).casefold()

    @staticmethod
    def _normalize_link_path(value: str) -> str:
        """路径目标归一化：去 ``.md`` 后缀 + NFC + casefold（``#anchor`` 已拆）。"""
        stripped = value.strip()
        if stripped.lower().endswith(".md"):
            stripped = stripped[: -len(".md")]
        return unicodedata.normalize("NFC", stripped).casefold()

    @classmethod
    def _build_link_index(
        cls,
        mapped_files: list[dict[str, Any]],
        existing: dict[str, WorldBiblePageDraft | WorldBiblePage],
        dataset: _DatasetIdentity | None,
        published_pages: list[Any],
    ) -> dict[str, dict[str, list[_LinkCandidate]]]:
        """构建四态判定候选索引（唯一 IO 之后的确定性步骤）。

        路径候选 = 本批 rel_path ∪ 同 dataset 既有成员 rel_path；标题候选 =
        本批 title ∪ 同 dataset 既有成员 title ∪ 项目内已发布 WorldBiblePage
        （canonical/confirmed）title。同一页面对象（本批/成员/已发布页重合）
        经 ``identity`` 去重，避免 preserve 重导把自身判成歧义。
        """
        batch_by_rel: dict[str, list[_LinkCandidate]] = {}
        batch_by_title: dict[str, list[_LinkCandidate]] = {}
        for mapped in mapped_files:
            candidate = _LinkCandidate(
                identity=("key", mapped["source_key"]),
                kind="batch",
                title_key=cls._normalize_link_title(str(mapped["title"])),
                rel_key=cls._normalize_link_path(str(mapped["path"])),
                rel_path=str(mapped["path"]),
                target=mapped,
            )
            batch_by_rel.setdefault(candidate.rel_key, []).append(candidate)
            batch_by_title.setdefault(candidate.title_key, []).append(candidate)
        member_by_rel: dict[str, list[_LinkCandidate]] = {}
        member_by_title: dict[str, list[_LinkCandidate]] = {}
        if dataset is not None:
            for source_key, current in existing.items():
                meta = dict(
                    (current.page_meta_json or {}).get("worldbook_import") or {}
                )
                if str(meta.get("dataset_key") or "") != dataset.key:
                    continue
                rel_path = str(meta.get("rel_path") or "")
                candidate = _LinkCandidate(
                    identity=("key", source_key),
                    kind="member",
                    title_key=cls._normalize_link_title(str(current.title)),
                    rel_key=cls._normalize_link_path(rel_path) if rel_path else None,
                    rel_path=rel_path or None,
                    target=current,
                )
                if candidate.rel_key is not None:
                    member_by_rel.setdefault(candidate.rel_key, []).append(candidate)
                member_by_title.setdefault(candidate.title_key, []).append(candidate)
        # 已发布页若有导入 meta（在 existing 中按 id 反查 source_key），身份
        # 与 dataset 成员候选对齐，避免同一对象在两个候选列表中被算两次。
        page_key_by_id = {
            str(current.id): source_key
            for source_key, current in existing.items()
            if isinstance(current, WorldBiblePage)
        }
        published_by_title: dict[str, list[_LinkCandidate]] = {}
        for row in published_pages:
            source_key = page_key_by_id.get(str(row.id))
            candidate = _LinkCandidate(
                identity=("key", source_key) if source_key else ("page", str(row.id)),
                kind="published",
                title_key=cls._normalize_link_title(str(row.title)),
                rel_key=None,
                rel_path=None,
                target=row,
            )
            published_by_title.setdefault(candidate.title_key, []).append(candidate)
        return {
            "batch_by_rel": batch_by_rel,
            "batch_by_title": batch_by_title,
            "member_by_rel": member_by_rel,
            "member_by_title": member_by_title,
            "published_by_title": published_by_title,
        }

    @classmethod
    def _resolve_occurrence(
        cls,
        occurrence: _LinkOccurrence,
        index: dict[str, dict[str, list[_LinkCandidate]]],
    ) -> tuple[str, _LinkCandidate | None]:
        """单条引用四态判定（确定性纯函数）。

        路径形态：命中本批 → resolved；命中同 dataset 既有成员但不在本批 →
        unselected；无命中 → unresolved。标题形态：0 命中 → unresolved，
        1 命中 → resolved（按命中对象区分 target），≥2 → ambiguous（同名
        不猜身份）。
        """
        if occurrence.is_path:
            rel_key = cls._normalize_link_path(occurrence.target)
            batch_hits = index["batch_by_rel"].get(rel_key) or []
            if batch_hits:
                return "resolved", batch_hits[0]
            member_hits = index["member_by_rel"].get(rel_key) or []
            if member_hits:
                return "unselected", member_hits[0]
            return "unresolved", None
        title_key = cls._normalize_link_title(occurrence.target)
        if not title_key:
            return "unresolved", None
        hits: list[_LinkCandidate] = []
        seen: set[tuple] = set()
        for candidates in (
            index["batch_by_title"].get(title_key) or [],
            index["member_by_title"].get(title_key) or [],
            index["published_by_title"].get(title_key) or [],
        ):
            for candidate in candidates:
                if candidate.identity in seen:
                    continue
                seen.add(candidate.identity)
                hits.append(candidate)
        if not hits:
            return "unresolved", None
        if len(hits) == 1:
            return "resolved", hits[0]
        return "ambiguous", None

    @classmethod
    def _materialize_ref(
        cls,
        hit: _LinkCandidate,
        dataset: _DatasetIdentity | None,
    ) -> dict[str, Any] | None:
        """把 resolved 命中转为可物化 ref（relation 固定 informs）。

        已发布 WorldBiblePage → 真实页 id；本批工作稿或既有 draft →
        ``local:{dataset_key}:{rel_path}`` 约定（不伪造正式页 id）。legacy
        提交（无 dataset 身份）的工作稿目标无可物化的稳定引用，保持 resolved
        计数不建 ref；超出 TargetRef ``target_id`` 255 上限的 local 目标同理
        （TargetRef 契约零改动，m1-contract 第 8 条）。
        """
        if dataset is None:
            return None
        if hit.kind == "published" or (
            hit.kind == "member" and isinstance(hit.target, WorldBiblePage)
        ):
            ref_id = str(hit.target.id)
        else:
            # local 目标指向被引用页的资料集内 rel_path（batch 命中取目标
            # candidate 的 rel_path，不是引用页自身路径）。
            rel_path = str(hit.rel_path or "")
            if not rel_path:
                return None
            ref_id = f"local:{dataset.key}:{rel_path}"
            if len(ref_id) > 255:
                return None
        ref = {
            "target_type": "world_bible_page",
            "target_id": ref_id,
            "relation": "informs",
        }
        ref["target_hash"] = WorldBibleLifecycleService._asset_ref_hash(ref)
        return ref

    @classmethod
    def _link_plan(
        cls,
        mapped: dict[str, Any],
        index: dict[str, dict[str, list[_LinkCandidate]]],
        dataset: _DatasetIdentity | None,
    ) -> _LinkPlan:
        """单页引用计划：四态计数 + 去重/截断后的物化 refs。"""
        summary = {"resolved": 0, "ambiguous": 0, "unresolved": 0, "unselected": 0}
        refs: list[dict[str, Any]] = []
        seen_refs: set[tuple[str, str]] = set()
        for occurrence in cls._parse_link_occurrences(mapped):
            state, hit = cls._resolve_occurrence(occurrence, index)
            summary[state] += 1
            if state != "resolved":
                continue
            ref = cls._materialize_ref(hit, dataset)
            if ref is None:
                continue
            dedup_key = (
                str(ref["relation"]),
                WorldBibleLifecycleService._normalize_asset_ref(ref).canonical_json(),
            )
            if dedup_key in seen_refs:
                continue
            seen_refs.add(dedup_key)
            refs.append(ref)
        truncated = len(refs) > _MAX_ASSET_REFS
        return _LinkPlan(
            summary=summary,
            refs=refs[:_MAX_ASSET_REFS],
            truncated=truncated,
            reason_suffix="；引用目标超过 100，仅物化前 100 条" if truncated else "",
        )

    @staticmethod
    def _editable_content_hash(item: WorldBiblePageDraft | WorldBiblePage) -> str:
        return WorldbookImportService._editable_fields_hash(
            title=item.title,
            page_type=item.page_type,
            free_text=item.free_text,
            sections_json=list(item.sections_json or []),
            linked_asset_refs_json=list(item.linked_asset_refs_json or []),
            template_key=item.template_key,
            template_version=item.template_version,
        )

    @staticmethod
    def _editable_fields_hash(
        *,
        title: str,
        page_type: str,
        free_text: str | None,
        sections_json: list,
        linked_asset_refs_json: list,
        template_key: str | None,
        template_version: int,
    ) -> str:
        return WorldbookImportService._hash(
            {
                "title": title,
                "page_type": page_type,
                "free_text": free_text,
                "sections_json": sections_json,
                "linked_asset_refs_json": linked_asset_refs_json,
                "template_key": template_key,
                "template_version": template_version,
            }
        )

    @classmethod
    def _source_meta(
        cls,
        mapped: dict[str, Any],
        source_format: str,
        manifest_hash: str,
        dataset: _DatasetIdentity | None = None,
        *,
        refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """构造 page_meta.worldbook_import；``refs`` 参与基线口径。

        m1-contract 第 4 条冻结决定 a：物化 refs 的页面，baseline 在同一
        apply 事务内按「物化后含 refs」的字段组计算——调用方传入该 item
        最终 refs；preview 与 apply 重放走同一函数同一输入。preserve 恢复/
        绑定补写路径传该页现值 refs，保持口径一致，不在物化之外改写 baseline。
        """
        baseline_content_hash = cls._editable_fields_hash(
            title=mapped["title"],
            page_type=mapped["page_type"],
            free_text=mapped["content"],
            sections_json=[],
            linked_asset_refs_json=list(refs or []),
            template_key=None,
            template_version=1,
        )
        meta = {
            "source_format": source_format,
            # source_path 保留原始提交路径（含根名）；校验引擎的
            # schema.source_prefixes 与校验清单消费该字段（m1-contract 第 8 条）。
            "source_path": mapped["source_path"],
            "source_key": mapped["source_key"],
            "source_hash": mapped["source_hash"],
            "baseline_content_hash": baseline_content_hash,
            "manifest_hash": manifest_hash,
            "source_authority_hint": "candidate",
            "source_missing": False,
            "activation_eligible": mapped["page_type"] != "source_material",
            "frontmatter": mapped["frontmatter"],
        }
        if dataset is not None:
            parts = PurePosixPath(str(mapped["source_path"])).parts
            meta.update(
                {
                    "dataset_key": dataset.key,
                    "dataset_name": dataset.name,
                    "rel_path": mapped["path"],
                    "commit_mode": dataset.commit_mode,
                    # 仅诊断：本次提交的所选根目录名（单段路径为空）。
                    "dataset_root_name": parts[0] if len(parts) >= 2 else "",
                }
            )
        return meta

    @staticmethod
    def _carry_forward_source_path(
        meta: dict[str, Any],
        previous_meta: dict[str, Any],
        dataset: _DatasetIdentity | None,
    ) -> None:
        """dataset 写路径保留既有页最初的原始提交路径（m1-contract 第 8 条）。

        校验引擎的 ``schema.source_prefixes`` 与校验清单消费 ``source_path``；
        接续绑定/来源更新重写整份 meta 时必须携带旧值，不得改写为本次提交的
        剥根路径。legacy（v1）路径保持现状逐字节一致，不做携带。
        """
        if dataset is None:
            return
        previous_path = str(previous_meta.get("source_path") or "")
        if previous_path:
            meta["source_path"] = previous_path

    @staticmethod
    def _page_meta(mapped: dict[str, Any], source_meta: dict[str, Any]) -> dict[str, Any]:
        metadata = {"worldbook_import": source_meta}
        if isinstance(mapped.get("validation_policy"), dict):
            # A directory import can stage policy as a draft, but only explicit publish
            # makes this top-level policy active.
            metadata["validation_policy"] = mapped["validation_policy"]
        return metadata

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _counts(items: list[WorldbookImportItem]) -> dict[str, int]:
        counts = Counter(item.action for item in items)
        return {
            key: counts.get(key, 0)
            for key in ("create", "update", "preserve", "conflict", "missing")
        }

    @classmethod
    def _preview_response(
        cls, suggestion_id: str, payload: WorldbookImportPayload
    ) -> WorldbookImportPreviewResponse:
        return WorldbookImportPreviewResponse(
            suggestion_id=suggestion_id,
            source_format=payload.source_format,
            manifest_hash=payload.manifest_hash,
            preview_hash=payload.preview_hash,
            counts=cls._counts(payload.items),
            items=payload.items,
            ignored_paths=payload.ignored_paths,
            dataset_name=payload.dataset_name,
            dataset_key=payload.dataset_key,
            dataset_intent=payload.dataset_intent if payload.dataset_key else None,
            commit_mode=payload.commit_mode if payload.dataset_key else None,
            legacy_bindings=payload.legacy_bindings,
        )

    @staticmethod
    async def _lock_import(
        db: AsyncSession, novel_id: str, dataset_key: str | None
    ) -> None:
        """跨 suggestion 并发 apply 的项目+资料集互斥（m1-contract 第 6 条）。

        沿用 `_lock_page_universe` 的 `pg_advisory_xact_lock` 先例；键空间独立于
        publish 链的 ``world_bible_pages:{novel_id}``，导入链不取 universe 锁，
        无交叉加锁顺序。非 PostgreSQL 方言（模块测试）为无操作。
        """
        bind = db.get_bind()
        if bind.dialect.name != "postgresql":
            return
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"worldbook_import:{novel_id}:{dataset_key or ''}"},
        )


__all__ = ["WorldbookImportService"]

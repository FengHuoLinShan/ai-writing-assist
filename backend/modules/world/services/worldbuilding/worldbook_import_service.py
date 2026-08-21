"""Restricted, review-first import of external worldbook text files."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yaml.tokens import AliasToken, AnchorToken, TagToken

from core.errors import ConflictError, ValidationError
from modules.world.models import WorldBiblePage, WorldBiblePageDraft
from modules.world.schemas import (
    CreationSuggestionCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftUpdate,
    WorldbookImportApplyRequest,
    WorldbookImportApplyResponse,
    WorldbookImportFile,
    WorldbookImportItem,
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
        analysis = await self._analyze(db, novel_id, manifest.files)
        payload = WorldbookImportPayload(
            schema_version="world_worldbook_import.v1",
            source_format=analysis["source_format"],
            manifest_hash=analysis["manifest_hash"],
            preview_hash=analysis["preview_hash"],
            files=analysis["files"],
            items=analysis["items"],
            ignored_paths=analysis["ignored_paths"],
        )
        suggestion = await self._suggestions.create(
            db,
            CreationSuggestionCreate(
                novel_id=novel_id,
                source_module="world",
                review_group="worldbook_import",
                target_type="worldbook_import",
                action_schema="world_worldbook_import.v1",
                payload_json=payload.model_dump(mode="json"),
                risk_level="high",
            ),
        )
        return self._preview_response(suggestion.id, payload)

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
        analysis = await self._analyze(
            db,
            novel_id,
            stored.files,
            source_format=stored.source_format,
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
                        )
                    draft_ids.append(marked.id)
                conflict_items.append(item)
                continue
            if item.action == "conflict":
                conflict_items.append(item)
                continue
            if item.action == "preserve":
                current = analysis["existing_sources"].get(item.source_key)
                source_meta = dict(
                    ((current.page_meta_json or {}).get("worldbook_import") or {})
                    if current is not None
                    else {}
                )
                if isinstance(current, WorldBiblePageDraft) and source_meta.get(
                    "source_missing"
                ):
                    mapped = mapped_files[item.source_key]
                    restored_meta = dict(current.page_meta_json or {})
                    restored_meta["worldbook_import"] = self._source_meta(
                        mapped,
                        analysis["source_format"],
                        analysis["manifest_hash"],
                    )
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
            meta = self._source_meta(
                mapped,
                analysis["source_format"],
                analysis["manifest_hash"],
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
                        created_by="worldbook_import",
                    ),
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
                        updated_by="worldbook_import",
                    ),
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
                        created_by="worldbook_import",
                    ),
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

    async def _analyze(
        self,
        db: AsyncSession,
        novel_id: str,
        files: list[WorldbookImportFile],
        *,
        source_format: str | None = None,
    ) -> dict[str, Any]:
        normalized: list[WorldbookImportFile] = []
        ignored_paths: list[str] = []
        seen: set[str] = set()
        total_bytes = 0
        raw_paths: list[str] = []
        for file in files:
            path = self._normalize_path(file.path)
            folded = unicodedata.normalize("NFC", path).casefold()
            if folded in seen:
                raise ValidationError(f"Duplicate worldbook path: {path}")
            seen.add(folded)
            raw_paths.append(path)
            if (
                self._is_control_path(path)
                or PurePosixPath(path).suffix.lower() not in _ALLOWED_SUFFIXES
            ):
                ignored_paths.append(path)
                continue
            size = len(file.content.encode("utf-8"))
            if "\x00" in file.content or "\ufffd" in file.content:
                raise ValidationError(
                    f"Worldbook file is not valid clean UTF-8 text: {path}"
                )
            if size > _MAX_FILE_BYTES:
                raise ValidationError(f"Worldbook file exceeds 2 MiB: {path}")
            total_bytes += size
            if total_bytes > _MAX_TOTAL_BYTES:
                raise ValidationError("Worldbook import exceeds 25 MiB")
            normalized.append(WorldbookImportFile(path=path, content=file.content))
        if not normalized:
            raise ValidationError("Worldbook import contains no supported text files")

        source_format = source_format or self._detect_format(raw_paths)
        mapped_files = [self._map_file(file, source_format) for file in normalized]
        manifest_hash = self._hash(
            [
                {"path": item["path"], "source_hash": item["source_hash"]}
                for item in mapped_files
            ]
        )
        existing = await self._existing_sources(db, novel_id)
        items: list[WorldbookImportItem] = []
        seen_keys: set[str] = set()
        for mapped in mapped_files:
            source_key = mapped["source_key"]
            seen_keys.add(source_key)
            current = existing.get(source_key)
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
                    reason=reason,
                )
            )
        for source_key, current in existing.items():
            if source_key in seen_keys:
                continue
            meta = dict((current.page_meta_json or {}).get("worldbook_import") or {})
            items.append(
                WorldbookImportItem(
                    source_key=source_key,
                    path=str(meta.get("source_path") or "missing"),
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
        preview_hash = self._hash(
            {
                "manifest_hash": manifest_hash,
                "source_format": source_format,
                "items": [item.model_dump(mode="json") for item in items],
            }
        )
        return {
            "source_format": source_format,
            "manifest_hash": manifest_hash,
            "preview_hash": preview_hash,
            "files": normalized,
            "mapped_files": mapped_files,
            "items": items,
            "ignored_paths": sorted(ignored_paths, key=str.casefold),
            "existing_sources": existing,
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

    @classmethod
    def _map_file(cls, file: WorldbookImportFile, source_format: str) -> dict[str, Any]:
        content = file.content
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
        source_key = hashlib.sha256(f"{source_format}\0{file.path}".encode()).hexdigest()
        return {
            "path": file.path,
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
        if source_format not in {"obsidian", "llmwiki"}:
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
        cls, mapped: dict[str, Any], source_format: str, manifest_hash: str
    ) -> dict[str, Any]:
        baseline_content_hash = cls._editable_fields_hash(
            title=mapped["title"],
            page_type=mapped["page_type"],
            free_text=mapped["content"],
            sections_json=[],
            linked_asset_refs_json=[],
            template_key=None,
            template_version=1,
        )
        return {
            "source_format": source_format,
            "source_path": mapped["path"],
            "source_key": mapped["source_key"],
            "source_hash": mapped["source_hash"],
            "baseline_content_hash": baseline_content_hash,
            "manifest_hash": manifest_hash,
            "source_authority_hint": "candidate",
            "source_missing": False,
            "activation_eligible": mapped["page_type"] != "source_material",
            "frontmatter": mapped["frontmatter"],
        }

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
        )


__all__ = ["WorldbookImportService"]

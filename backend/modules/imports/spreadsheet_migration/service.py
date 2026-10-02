"""表格迁移会话服务（计划 §4 L4）。

上传 → 解析（to_thread）→ 识别 → 建会话；mapping/decisions 带 revision CAS 并重算
preview；apply 在同一事务内完成「重算 preview 比对 hash → 项目排他锁 → world.apply →
story.apply → mark_applied → commit」；rollback 先 story 后 world，按回执逆序。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.imports.models import ImportMigrationSession
from modules.imports.spreadsheet_migration import classify, planning
from modules.imports.spreadsheet_migration.ai import ai_items_for_planning
from modules.imports.spreadsheet_migration.constants import (
    CHARACTER_COLUMN_TARGETS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_SESSION_CHARS,
    RELATION_COLUMN_TARGETS,
    SPREADSHEET_EXTENSIONS,
    STORY_COLUMN_TARGETS,
    WORLD_COLUMN_TARGETS,
)
from modules.imports.spreadsheet_migration.parsing import ParsedUpload
from modules.imports.spreadsheet_migration.repository import (
    ImportMigrationSessionRepository,
)

logger = logging.getLogger(__name__)

_ACTION_LABELS = {
    "create": "新建",
    "fill_empty": "补全空字段",
    "adopt_existing": "采用候选",
    "existing_ref": "已存在",
    "conflict": "冲突，未导入",
    "needs_review": "需要确认",
    "similar_name": "名称相似，需确认",
    "alias_collision": "别名重名",
    "skip": "跳过",
    "planned_scene": "新建细纲",
    "link_scene": "关联已写章节",
    "reference_only": "仅参考",
}

_REASON_LABELS = {
    "duplicate_in_file": "同一文件里有重名条目",
    "target_not_found": "指定的已有对象不存在",
    "ambiguous_identity": "同名对象有多个，无法确定",
    "field_conflict": "与已有内容不一致",
    "alias_collision": "别名与其他对象重名",
    "similar_name": "与已有对象名称相似",
    "compatibility_shadow": "同名对象仍在确认中",
    "stale_candidate": "同名候选的来源已过期",
    "endpoint_missing": "关系一端的对象不存在",
    "endpoint_ambiguous": "关系一端有多个同名对象",
    "endpoint_item_blocked": "关系一端的条目未导入",
    "endpoint_item_unknown": "关系一端无法解析",
    "self_loop": "关系两端是同一对象",
    "duplicate": "与已有关系重复",
    "candidate_edge_exists": "已有待确认的关系",
    "description_conflict": "关系描述与已有内容不一致",
    "modified_after_migration": "导入后被修改过",
    "referenced": "已被其他内容引用",
    "outline_core_missing": "总纲缺少核心设定（前提/基调/故事引擎）",
    "outline_markdown_missing": "总纲内容为空",
    "arc_range_overlap": "卷的章节范围与已有卷重叠",
    "duplicate_in_migration": "本次迁移中有重名条目",
}

_KIND_LABELS = {
    "arc": "卷",
    "thread": "剧情线",
    "foreshadowing": "伏笔",
    "chapter_plan": "章节细纲",
    "entity": "人物与设定",
    "relation": "关系",
}

_FIELD_LABELS = {
    "aliases": "别名",
    "summary": "简介",
    "public_info": "公开信息",
    "hidden_truth": "秘密",
    "role": "身份",
    "appearance": "外貌",
    "personality": "性格",
    "desire": "渴望",
    "fear": "恐惧",
    "weakness": "弱点",
    "current_goal": "当前目标",
    "current_state": "现状",
    "stance": "立场",
    "voice_style": "说话风格",
    "relationship_summary": "人际关系",
    "arc_goal": "卷目标",
    "core_conflict": "核心冲突",
    "climax": "高潮",
    "result": "结果",
    "next_hook": "下一卷钩子",
    "thread_type": "线型",
    "visible_goal": "表面目标",
    "title": "标题",
    "goal": "目标",
    "emotional_beat": "情绪节拍",
    "must_happen": "必须发生",
    "must_not_happen": "不能发生",
    "surface_meaning": "表面含义",
    "hidden_meaning": "隐藏含义",
    "seed_chapter": "埋设章",
    "payoff_chapter": "兑现章",
    "reinforce_chapters": "强化章",
    "chapter_start": "起始章",
    "chapter_end": "结束章",
    "start_chapter": "起始章",
    "end_chapter": "结束章",
    "planned_payoff_chapter": "计划兑现章",
}

_TASK_STATUS_TO_AI = {
    "pending": "queued",
    "queued": "queued",
    "running": "running",
    "done": "done",
    "failed": "failed",
    "cancelled": "failed",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _reason_label(reason: str | None) -> str | None:
    if not reason:
        return None
    return _REASON_LABELS.get(reason, reason)


def _field_labels(fields: list[str]) -> list[str]:
    return [_FIELD_LABELS.get(name, name) for name in fields]


class SpreadsheetMigrationService:
    """表格迁移会话编排（imports 内部，路由层只做参数适配）。"""

    def __init__(self) -> None:
        self._repo = ImportMigrationSessionRepository()

    # ── 上传与会话读取 ─────────────────────────────────────────

    async def create_session(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        owner_id: str,
        files: list[tuple[str, bytes]],
    ) -> ImportMigrationSession:
        if not files or len(files) > MAX_FILES:
            raise ValidationError(f"请一次上传 1 到 {MAX_FILES} 个表格文件")
        uploads: list[tuple[str, str, ParsedUpload]] = []
        for file_name, data in files:
            name = file_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            lowered = name.lower()
            suffix = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
            extension = f".{suffix}" if suffix else ""
            if extension not in SPREADSHEET_EXTENSIONS:
                raise ValidationError(
                    "仅支持 .xlsx 和 .csv 表格文件；"
                    "旧版 .xls 请先在 Excel/WPS 中另存为 .xlsx"
                )
            if not data:
                raise ValidationError("上传的文件是空的")
            if len(data) > MAX_FILE_BYTES:
                raise ValidationError(
                    f"单个表格文件不能超过 {MAX_FILE_BYTES // (1024 * 1024)}MB",
                    status_code=413,
                )
            from modules.imports.parsers import parse_spreadsheet_file

            try:
                upload = await asyncio.to_thread(parse_spreadsheet_file, data, name)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            uploads.append((name, extension, upload))

        file_manifest: list[dict[str, Any]] = []
        rows_json: dict[str, list[list[str]]] = {}
        mapping_sheets: list[dict[str, Any]] = []
        for file_idx, (name, extension, upload) in enumerate(uploads):
            file_key = f"f{file_idx}"
            renumbered = self._renumber_upload(upload, file_key)
            sheets_manifest: list[dict[str, Any]] = []
            for sheet in renumbered.sheets:
                suggestion = classify.classify_sheet(sheet)
                header = (
                    sheet.rows[suggestion.header_row]
                    if suggestion.header_row < len(sheet.rows)
                    else []
                )
                sheets_manifest.append(
                    {
                        "sheet_key": sheet.sheet_key,
                        "name": sheet.name,
                        "hidden": sheet.hidden,
                        "row_count": len(sheet.rows),
                        "col_count": max((len(row) for row in sheet.rows), default=0),
                        "warnings": list(sheet.warnings),
                        "headers": header,
                        "suggested": {
                            "kind": suggestion.kind,
                            "header_row": suggestion.header_row,
                            "columns": {
                                column.column_key: column.target
                                for column in suggestion.columns
                            },
                        },
                    }
                )
                rows_json[sheet.sheet_key] = sheet.rows
                mapping_sheets.append(
                    {
                        "sheet_key": sheet.sheet_key,
                        "kind": suggestion.kind,
                        "header_row": suggestion.header_row,
                        "default_entity_type": self._default_entity_type(
                            suggestion.kind, sheet.name
                        ),
                        "columns": {
                            column.column_key: column.target
                            for column in suggestion.columns
                        },
                    }
                )
            file_manifest.append(
                {
                    "file_key": file_key,
                    "file_name": renumbered.file_name,
                    "file_type": extension.lstrip("."),
                    "size": renumbered.size,
                    "sha256": renumbered.sha256,
                    "sheets": sheets_manifest,
                }
            )

        session_chars = len(_canonical_json(rows_json))
        if session_chars > MAX_SESSION_CHARS:
            raise ValidationError(
                "表格内容总量过大，请减少行列后分次上传",
                status_code=413,
            )

        session = await self._repo.create(
            db,
            novel_id=uuid.UUID(novel_id),
            owner_id=uuid.UUID(owner_id),
            file_manifest=file_manifest,
            rows_json=rows_json,
            mapping_json={
                "sheets": mapping_sheets,
                "options": {
                    "written_chapter_policy": "reference_only",
                    "outline_head_policy": "create_if_missing",
                },
            },
        )
        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    def _renumber_upload(upload: ParsedUpload, file_key: str) -> ParsedUpload:
        """parse_spreadsheet_file 固定产出 f0 前缀；按文件序号重编 key。"""
        sheets = [
            replace(
                sheet,
                file_key=file_key,
                sheet_key=f"{file_key}s{sheet.sheet_key.rsplit('s', 1)[-1]}",
            )
            for sheet in upload.sheets
        ]
        return replace(upload, file_key=file_key, sheets=sheets)

    @staticmethod
    def _default_entity_type(kind: str, sheet_name: str) -> str | None:
        if kind == "characters":
            return "character"
        if kind == "world_objects":
            from modules.imports.spreadsheet_migration import synonyms

            return synonyms.normalize_entity_type(sheet_name)
        return None

    async def get_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        novel_id: str,
        owner_id: str,
        for_update: bool = False,
    ) -> ImportMigrationSession:
        session = await self._repo.get(
            db,
            uuid.UUID(session_id),
            novel_id=uuid.UUID(novel_id),
            owner_id=uuid.UUID(owner_id),
            for_update=for_update,
        )
        if session is None:
            raise NotFoundError("迁移记录不存在")
        return session

    async def list_sessions(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        owner_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[ImportMigrationSession], int]:
        return await self._repo.list_recent(
            db,
            novel_id=uuid.UUID(novel_id),
            owner_id=uuid.UUID(owner_id),
            limit=limit,
            offset=offset,
        )

    async def get_rows(
        self,
        *,
        session: ImportMigrationSession,
        sheet_key: str,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        rows = session.rows_json.get(sheet_key)
        if rows is None or session.status != "draft":
            raise ConflictError(
                "该迁移的表格内容已随采用清除，无法再查看原始行",
                code="migration_rows_cleared",
                status_code=410,
            )
        mapping_sheet = self._mapping_sheet(session, sheet_key)
        header_row = mapping_sheet.get("header_row", 0) if mapping_sheet else 0
        header = rows[header_row] if header_row < len(rows) else []
        body = rows[header_row + 1 :]
        total = len(body)
        window = body[offset : offset + limit]
        return {
            "header": header,
            "rows": [
                {"row": header_row + 1 + offset + i, "cells": cells}
                for i, cells in enumerate(window)
            ],
            "total": total,
        }

    # ── mapping 与 decisions ────────────────────────────────────

    async def save_mapping(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
        expected_revision: int,
        sheets: list[dict[str, Any]],
        options: dict[str, Any],
    ) -> ImportMigrationSession:
        manifest_keys = {
            sheet["sheet_key"]
            for file in session.file_manifest
            for sheet in file.get("sheets", [])
        }
        for sheet in sheets:
            key = sheet.get("sheet_key")
            if key not in manifest_keys:
                raise ValidationError(f"表格 {key} 不在本次上传中")
            self._validate_kind_targets(sheet.get("kind", ""), sheet.get("columns", {}))
            if int(sheet.get("header_row", 0)) > 32:
                raise ValidationError("表头行超出可识别范围")
        mapping_json = {
            "sheets": sheets,
            "options": {
                "written_chapter_policy": options.get(
                    "written_chapter_policy", "reference_only"
                ),
                "outline_head_policy": options.get(
                    "outline_head_policy", "create_if_missing"
                ),
            },
        }
        session = await self._repo.save_mapping(
            db,
            session,
            mapping_json=mapping_json,
            expected_revision=expected_revision,
        )
        await self._refresh_preview(db, session=session)
        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    def _validate_kind_targets(kind: str, columns: dict[str, str]) -> None:
        if kind in {"characters", "world_objects"}:
            allowed = WORLD_COLUMN_TARGETS | CHARACTER_COLUMN_TARGETS
        elif kind == "relations":
            allowed = RELATION_COLUMN_TARGETS
        else:
            allowed = STORY_COLUMN_TARGETS
        for column_key, target in columns.items():
            if target not in allowed:
                raise ValidationError(
                    f"列 {column_key} 的目标 {target} 不适用于该表类型"
                )

    async def save_decisions(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
        expected_revision: int,
        decisions: list[dict[str, Any]],
        relation_kind_groups: dict[str, str] | None,
    ) -> ImportMigrationSession:
        decisions_json: dict[str, Any] = {
            str(item.get("item_key")): {
                key: value for key, value in item.items() if key != "item_key"
            }
            for item in decisions
        }
        if relation_kind_groups:
            decisions_json["relation_kind_groups"] = dict(relation_kind_groups)
        session = await self._repo.save_decisions(
            db,
            session,
            decisions_json=decisions_json,
            expected_revision=expected_revision,
        )
        await self._refresh_preview(db, session=session)
        await db.commit()
        await db.refresh(session)
        return session

    # ── AI ──────────────────────────────────────────────────────

    async def submit_ai(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
        expected_revision: int,
        scope: dict[str, Any],
        operation_id: str,
    ) -> dict[str, Any]:
        if session.revision != expected_revision or session.status != "draft":
            raise ConflictError(
                "迁移会话已更新，请刷新后重试",
                code="migration_revision_stale",
            )
        from modules.imports.spreadsheet_migration import ai as ai_module

        task_ref = await ai_module.submit_ai_run(
            db,
            novel_id=str(session.novel_id),
            session=session,
            scope=scope,
            operation_id=operation_id,
        )
        await db.commit()
        await db.refresh(session)
        return {
            "task_id": task_ref.task_id,
            "status": task_ref.status,
            "reused": task_ref.reused,
        }

    async def reconcile_ai_status(
        self,
        db: AsyncSession,
        session: ImportMigrationSession,
    ) -> None:
        """对照任务最终状态修正 ai_status，避免长期停在 running。"""
        if (
            session.ai_status not in {"queued", "running"}
            or session.ai_task_id is None
        ):
            return
        row = (
            await db.execute(
                select(AsyncTask).where(AsyncTask.id == session.ai_task_id)
            )
        ).scalar_one_or_none()
        if row is None:
            session.ai_status = "failed"
            await db.flush()
            return
        mapped = _TASK_STATUS_TO_AI.get(row.status)
        if mapped and mapped != session.ai_status and mapped != "queued":
            session.ai_status = mapped
            await db.flush()

    # ── 预览与采用 ─────────────────────────────────────────────

    async def _refresh_preview(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
    ) -> tuple[dict[str, Any], str]:
        """重算 preview 并写回 plan_json/preview_hash（不提升 revision）。"""
        world_plan, story_plan, requests, preview_hash = await self._compose_plans(
            db, session=session
        )
        rendered = self._render_preview(
            session=session,
            requests=requests,
            world_plan=world_plan,
            story_plan=story_plan,
        )
        rendered["preview_hash"] = preview_hash
        session.plan_json = {
            "world": world_plan.model_dump(mode="json"),
            "story": story_plan.model_dump(mode="json"),
            "labels": {
                key: {
                    "label": label.label,
                    "sheet_key": label.source.sheet_key if label.source else "",
                    "sheet_name": label.source.sheet_name if label.source else "",
                    "row": label.source.row if label.source else 0,
                }
                for key, label in requests.labels.items()
            },
            "preview": rendered,
        }
        session.preview_hash = preview_hash
        await db.flush()
        return rendered, preview_hash

    async def _compose_plans(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
    ) -> tuple[Any, Any, planning.MigrationPlanRequests, str]:
        from modules.story.outline_state import facade as story_facade
        from modules.world import facade as world_facade

        options = session.mapping_json.get("options", {})
        ai_input = None
        if session.ai_result_json:
            ai_input = ai_items_for_planning(
                session.ai_result_json, session.decisions_json
            )
        requests = planning.build_migration_requests(
            migration_id=str(session.id),
            sheets=self._sheet_contexts(session),
            decisions=session.decisions_json,
            ai_input=ai_input,
            plan_targets=self._plan_targets(session),
            written_chapter_policy=options.get(
                "written_chapter_policy", "reference_only"
            ),
            outline_head_policy=options.get(
                "outline_head_policy", "create_if_missing"
            ),
        )
        entity_refs: dict[str, str | None] = {
            entity.item_key: (
                entity.target_entity_id if entity.decision == "use_existing" else None
            )
            for entity in requests.world_request.entities
        }
        novel_id = str(session.novel_id)
        world_plan = await world_facade.plan_author_migration_world(
            db, novel_id, requests.world_request
        )
        story_plan = await story_facade.plan_author_migration_structures(
            db, novel_id, requests.story_request, entity_refs=entity_refs
        )
        accepted = ",".join(requests.ai_accepted_refs)
        digest = hashlib.sha256(
            "\n".join(
                [
                    world_plan.fingerprint,
                    story_plan.fingerprint,
                    _canonical_json(session.mapping_json),
                    _canonical_json(session.decisions_json),
                    accepted,
                    str(session.revision),
                ]
            ).encode("utf-8")
        ).hexdigest()
        return world_plan, story_plan, requests, digest

    def _sheet_contexts(
        self, session: ImportMigrationSession
    ) -> list[planning.SheetContext]:
        mapping_sheets = {
            sheet["sheet_key"]: sheet
            for sheet in session.mapping_json.get("sheets", [])
        }
        contexts: list[planning.SheetContext] = []
        for file in session.file_manifest:
            for sheet in file.get("sheets", []):
                key = sheet["sheet_key"]
                mapped = mapping_sheets.get(key)
                if not mapped or mapped.get("kind") == "skip":
                    continue
                contexts.append(
                    planning.SheetContext(
                        sheet_key=key,
                        name=sheet["name"],
                        kind=mapped["kind"],
                        header_row=int(mapped.get("header_row", 0)),
                        default_entity_type=mapped.get("default_entity_type"),
                        columns=dict(mapped.get("columns", {})),
                        rows=list(session.rows_json.get(key, [])),
                    )
                )
        return contexts

    @staticmethod
    def _plan_targets(session: ImportMigrationSession) -> dict[str, str]:
        targets: dict[str, str] = {}
        for item_key, decision in session.decisions_json.items():
            if item_key == "relation_kind_groups":
                continue
            if (
                isinstance(decision, dict)
                and decision.get("action") == "use_existing"
                and decision.get("target_entity_id")
            ):
                targets[str(item_key)] = str(decision["target_entity_id"])
        return targets

    @staticmethod
    def _mapping_sheet(
        session: ImportMigrationSession, sheet_key: str
    ) -> dict[str, Any] | None:
        for sheet in session.mapping_json.get("sheets", []):
            if sheet.get("sheet_key") == sheet_key:
                return sheet
        return None

    def _render_preview(
        self,
        *,
        session: ImportMigrationSession,
        requests: planning.MigrationPlanRequests,
        world_plan: Any,
        story_plan: Any,
    ) -> dict[str, Any]:
        labels = requests.labels
        ai_coverage = self._ai_coverage(session)

        def label_of(item_key: str) -> planning.PlannedLabel:
            return labels.get(
                item_key, planning.PlannedLabel(label=item_key, source=None)
            )

        def ai_flags(source_ref: str | None) -> dict[str, Any]:
            covered = ai_coverage.get(source_ref or "")
            if covered is None:
                return {"ai_available": False, "ai_passed": None, "ai_accepted": None}
            return covered

        world_items: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        counts = {
            "create": 0,
            "fill": 0,
            "adopt": 0,
            "existing": 0,
            "conflict": 0,
            "skip": 0,
            "relations": 0,
            "structures": 0,
            "reference_only": 0,
        }
        for item in world_plan.items:
            plan_label = label_of(item.item_key)
            source = plan_label.source
            flags = ai_flags(f"{source.sheet_key}:r{source.row}" if source else None)
            if item.kind == "relation":
                relations.append(
                    {
                        "item_key": item.item_key,
                        "source_label": plan_label.label.split(" → ")[0]
                        if " → " in plan_label.label
                        else plan_label.label,
                        "target_label": item.target_label
                        or (
                            plan_label.label.split(" → ")[-1]
                            if " → " in plan_label.label
                            else ""
                        ),
                        "relation_type": getattr(item, "target_label", "")
                        or plan_label.label,
                        "relation_kind": item.relation_kind,
                        "kind_guessed": item.relation_kind_guessed,
                        "action": item.action,
                        "reason": _reason_label(item.reason_code),
                        "source_sheet_name": source.sheet_name if source else "",
                        "source_row": source.row if source else 0,
                        "decision": self._decision_label(session, item.item_key),
                    }
                )
                counts["relations"] += 1
                if item.action == "conflict":
                    counts["conflict"] += 1
                elif item.action == "skip":
                    counts["skip"] += 1
                continue
            world_items.append(
                {
                    "item_key": item.item_key,
                    "label": plan_label.label,
                    "type_label": "条目",
                    "action": item.action,
                    "target_id": item.target_id,
                    "target_label": item.target_label,
                    "fills": _field_labels(item.fills),
                    "conflicts": [
                        {
                            "field_label": _FIELD_LABELS.get(c.field, c.field),
                            "current_excerpt": c.current_excerpt,
                            "incoming_excerpt": c.incoming_excerpt,
                        }
                        for c in item.conflicts
                    ],
                    "similar": [{"label": s.get("name", "")} for s in item.similar],
                    "source_sheet_name": source.sheet_name if source else "",
                    "source_row": source.row if source else 0,
                    "decision": self._decision_label(session, item.item_key),
                    **flags,
                }
            )
            if item.action == "create":
                counts["create"] += 1
            elif item.action == "fill_empty":
                counts["fill"] += 1
            elif item.action == "adopt_existing":
                counts["adopt"] += 1
            elif item.action in {
                "existing_ref",
                "similar_name",
                "alias_collision",
                "needs_review",
            }:
                counts["existing"] += 1
            elif item.action == "conflict":
                counts["conflict"] += 1
            elif item.action == "skip":
                counts["skip"] += 1

        structures: list[dict[str, Any]] = []
        for item in story_plan.items:
            plan_label = label_of(item.item_key)
            source = plan_label.source
            is_outline = item.item_key == planning.OUTLINE_ITEM_KEY
            structures.append(
                {
                    "item_key": item.item_key,
                    "kind": "outline"
                    if is_outline
                    else self._story_kind(item.item_key, requests),
                    "label": "总纲" if is_outline else plan_label.label,
                    "chapter_label": None,
                    "action": item.action,
                    "target_label": item.target_label,
                    "reason": _reason_label(item.reason_code),
                    "source_sheet_name": "总纲"
                    if is_outline
                    else (source.sheet_name if source else ""),
                    "source_row": source.row if source else 0,
                    "decision": self._decision_label(session, item.item_key),
                    "ai_available": False,
                    "ai_passed": None,
                    "ai_accepted": None,
                }
            )
            counts["structures"] += 1
            if item.action == "conflict":
                counts["conflict"] += 1
            elif item.action == "reference_only":
                counts["reference_only"] += 1
            elif item.action == "skip":
                counts["skip"] += 1

        outline = None
        if story_plan.outline_action and story_plan.outline_action != "skip":
            outline = {
                "action": story_plan.outline_action,
                "title": requests.story_request.outline.title
                if requests.story_request.outline
                else None,
            }

        return {
            "preview_hash": "",
            "validation_policy_active": world_plan.validation_policy_active,
            "counts": counts,
            "world_items": world_items,
            "relations": relations,
            "structures": structures,
            "outline": outline,
        }

    @staticmethod
    def _story_kind(item_key: str, requests: planning.MigrationPlanRequests) -> str:
        for story_item in requests.story_request.items:
            if story_item.item_key == item_key:
                return _KIND_LABELS.get(story_item.kind, story_item.kind)
        return "结构"

    @staticmethod
    def _decision_label(session: ImportMigrationSession, item_key: str) -> str:
        decision = session.decisions_json.get(item_key)
        if not isinstance(decision, dict):
            return "auto"
        return str(decision.get("action", "auto"))

    @staticmethod
    def _ai_coverage(session: ImportMigrationSession) -> dict[str, dict[str, Any]]:
        """row_ref → {ai_available, ai_passed, ai_accepted}。"""
        coverage: dict[str, dict[str, Any]] = {}
        result = session.ai_result_json or {}
        for operation in ("outline", "cleanup"):
            for group in result.get(operation, []) or []:
                if not isinstance(group, dict):
                    continue
                passed = (group.get("governance") or {}).get("status") == "passed"
                entry = {
                    "ai_available": True,
                    "ai_passed": passed,
                    "ai_accepted": None,
                }
                for row_ref in group.get("source_rows", []) or []:
                    coverage[str(row_ref)] = entry
        return coverage

    async def apply_session(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
        expected_preview_hash: str,
        authorized_by: str,
    ) -> dict[str, Any]:
        from modules.project.facade import require_active_project_exclusive
        from modules.story.outline_state import facade as story_facade
        from modules.world import facade as world_facade

        if session.status != "draft":
            raise ConflictError(
                "该迁移已采用过，不能重复采用",
                code="migration_already_applied",
            )
        world_plan, story_plan, requests, preview_hash = await self._compose_plans(
            db, session=session
        )
        if preview_hash != expected_preview_hash:
            raise ConflictError(
                "预览已过期，内容或决策在预览后有变化，请重新确认",
                code="migration_preview_stale",
                context={"preview_hash": preview_hash},
            )
        novel_id = str(session.novel_id)
        await require_active_project_exclusive(db, novel_id)
        world_receipt = await world_facade.apply_author_migration_world(
            db,
            novel_id,
            requests.world_request,
            expected_fingerprint=world_plan.fingerprint,
            authorized_by=authorized_by,
        )
        story_receipt = await story_facade.apply_author_migration_structures(
            db,
            novel_id,
            requests.story_request,
            entity_ids=world_receipt.entity_ids,
            expected_fingerprint=story_plan.fingerprint,
            authorized_by=authorized_by,
        )
        receipt = {
            "world": world_receipt.model_dump(mode="json"),
            "story": story_receipt.model_dump(mode="json"),
            "counts": self._receipt_counts(world_receipt, story_receipt),
            "labels": {key: label.label for key, label in requests.labels.items()},
        }
        await self._repo.mark_applied(
            db, session, receipt=receipt, preview_hash=preview_hash
        )
        await db.commit()
        await db.refresh(session)
        return receipt["counts"]

    @staticmethod
    def _receipt_counts(world_receipt: Any, story_receipt: Any) -> dict[str, int]:
        world_changes = world_receipt.applied_changes
        story_changes = story_receipt.applied_changes
        return {
            "created": sum(1 for c in world_changes if c.operation == "create"),
            "filled": sum(1 for c in world_changes if c.operation == "fill_empty"),
            "adopted": sum(1 for c in world_changes if c.operation == "promote"),
            "relations": sum(1 for c in world_changes if c.kind == "relation"),
            "structures": len(story_changes),
            "outline": 1 if story_receipt.outline_change else 0,
        }

    # ── 回滚与删除 ──────────────────────────────────────────────

    async def rollback_session(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
        dry_run: bool,
    ) -> dict[str, Any]:
        from modules.project.facade import require_active_project_exclusive
        from modules.story.outline_state import facade as story_facade
        from modules.story.outline_state.contracts import StoryMigrationReceipt
        from modules.world import facade as world_facade
        from modules.world.contracts import WorldMigrationReceipt

        if session.status != "applied":
            raise ConflictError(
                "只有已采用的迁移才能撤销",
                code="migration_not_applied",
            )
        receipt = session.receipt_json or {}
        story_receipt = StoryMigrationReceipt(**receipt.get("story", {}))
        world_receipt = WorldMigrationReceipt(**receipt.get("world", {}))
        novel_id = str(session.novel_id)
        if not dry_run:
            await require_active_project_exclusive(db, novel_id)
        story_result = await story_facade.rollback_author_migration_structures(
            db, novel_id, story_receipt, dry_run=dry_run
        )
        world_result = await world_facade.rollback_author_migration_world(
            db, novel_id, world_receipt, dry_run=dry_run
        )
        labels = dict(receipt.get("labels", {}))

        def label_for(entry: dict[str, Any]) -> str:
            key = str(entry.get("item_key", ""))
            return labels.get(key, key)

        revertible = [
            {"item_key": key, "label": labels.get(key, key)}
            for key in [*story_result.reverted, *world_result.reverted]
        ]
        kept = [
            {
                "item_key": str(entry.get("item_key", "")),
                "label": label_for(entry),
                "reason": _reason_label(str(entry.get("reason_code", ""))),
            }
            for entry in [*story_result.kept, *world_result.kept]
        ]
        if dry_run:
            await db.rollback()
            return {"revertible": revertible, "kept": kept}

        await self._repo.mark_rolled_back(db, session, partially=bool(kept))
        await db.commit()
        await db.refresh(session)
        return {"revertible": revertible, "kept": kept}

    async def delete_session(
        self,
        db: AsyncSession,
        *,
        session: ImportMigrationSession,
    ) -> None:
        await self._repo.delete(db, session)
        await db.commit()


__all__ = ["SpreadsheetMigrationService"]

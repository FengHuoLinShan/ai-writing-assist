"""Bounded R0 assistant reads backed by Evidence's public facade."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.evidence.compilation.contracts import VisibilityContextContract
from modules.evidence.compilation.facade import (
    inspect_novel_target,
    read_novel_evidence,
    render_compiled_context,
    search_novel_evidence,
)
from modules.evidence.source_ref_contracts import SourceRangeRefContract
from modules.project.facade import get_any_project_context, require_any_active_project
from shared.target_ref import TargetRef


class SearchProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    scopes: list[Literal["manuscript", "world", "outline"]] = Field(
        default_factory=lambda: ["manuscript"], min_length=1, max_length=3
    )

    @model_validator(mode="after")
    def unique_scopes(self):
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("检索范围不能重复")
        return self


class SourceRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=64)
    chapter_index: int = Field(ge=1)
    version_number: int = Field(ge=1)
    content_mode: Literal["working", "canonical"]
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    range_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReadSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: SourceRange


class TargetScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=255)
    target_path: str = Field(default="", max_length=512)


class PreviewKnowledgeScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: TargetScope


async def _require_owned_author_project(db, novel_id, context):
    if context is None or not context.owner_id:
        raise NotFoundError("作者项目读取需要已验证的作者范围")
    await require_any_active_project(db, str(novel_id))
    project = await get_any_project_context(db, str(novel_id))
    if (
        project is None
        or str(project.owner_id) != str(context.owner_id)
        or project.project_kind != "author"
    ):
        raise NotFoundError("项目不可访问")
    return context.work


def _visibility(work) -> VisibilityContextContract:
    return VisibilityContextContract(
        mode="author",
        cutoff_chapter=work.chapter_index if work.scope == "current" else None,
        cutoff_scene_id=(
            str(work.scene_id) if work.scene_id and work.scope == "current" else None
        ),
    )


def _excluded(work) -> set[str]:
    values = set(work.excluded_targets or [])
    values.update(value.rsplit(":", 1)[-1] for value in list(values))
    return values


def _is_excluded(hit: dict, excluded: set[str]) -> bool:
    target = hit.get("target_ref") or {}
    source = hit.get("source_ref") or {}
    target_id = str(target.get("target_id") or target.get("id") or "")
    target_type = str(target.get("target_type") or target.get("type") or "")
    identities = {
        target_id,
        str(source.get("draft_id") or ""),
        f"{target_type}:{target_id}" if target_type and target_id else "",
    }
    return bool(identities.intersection(excluded))


def _confirmed_source_selected(confirmed, source_ref: SourceRangeRefContract) -> bool:
    confirmation = confirmed.confirmation
    draft_id = str(source_ref.draft_id)
    if draft_id not in set(confirmation.selected_asset_ids.get("writing_drafts", [])):
        return False
    if draft_id in set(confirmation.excluded_asset_ids.get("writing_drafts", [])):
        return False

    expected = {
        "draft_id": draft_id,
        "chapter_index": source_ref.chapter_index,
        "version_number": source_ref.version_number,
        "content_mode": source_ref.content_mode,
        "start_offset": source_ref.start_offset,
        "end_offset": source_ref.end_offset,
        "source_hash": source_ref.source_hash,
        "range_hash": source_ref.range_hash,
    }
    for item in confirmed.compiled.excluded_items + confirmed.compiled.omitted_items:
        sources = item.sources or ([item.source] if item.source else [])
        if any(source.get("source_ref") == expected for source in sources):
            return False
    for section in confirmed.compiled.sections:
        if section.excluded:
            continue
        for item in section.materialize_items().items:
            if item.selection_state in {"excluded", "omitted"}:
                continue
            sources = item.sources or ([item.source] if item.source else [])
            if any(source.get("source_ref") == expected for source in sources):
                return True
    return False


async def _search(db, novel_id, args, *, context=None):
    work = await _require_owned_author_project(db, novel_id, context)
    if work.context_confirmation_id:
        if not work.context_confirmation_action:
            raise ConflictError("原资料确认缺少操作范围，不能重新检索")
        from modules.evidence.facade import prepare_confirmed_ai_action

        confirmed = await prepare_confirmed_ai_action(
            db,
            novel_id=str(novel_id),
            action=work.context_confirmation_action,
            confirmation_id=str(work.context_confirmation_id),
        )
        return {
            "title": "仅使用本次已确认的参考资料",
            "confirmation_id": str(confirmed.confirmation.id),
            "text": render_compiled_context(confirmed.compiled),
            "coverage": "original_confirmation_only",
            "warnings": [],
        }
    found = await search_novel_evidence(
        db,
        novel_id=str(novel_id),
        query=args.query,
        content_mode="working",
        visibility=_visibility(work),
        scopes=args.scopes,
        top_k=12,
        context_scene_id=str(work.scene_id) if work.scene_id else None,
    )
    hits = [
        item for item in found.get("hits", []) if not _is_excluded(item, _excluded(work))
    ]
    return {
        "hits": hits,
        "warnings": found.get("warnings", []),
        "degraded": bool(found.get("degraded", False)),
        "coverage": "retrieval_only",
    }


async def _read_source(db, novel_id, args, *, context=None):
    work = await _require_owned_author_project(db, novel_id, context)
    source_ref = SourceRangeRefContract(**args.source_ref.model_dump())
    if _is_excluded({"source_ref": {"draft_id": source_ref.draft_id}}, _excluded(work)):
        raise ConflictError("该正文版本已被本次资料范围排除")
    if work.context_confirmation_id:
        if not work.context_confirmation_action:
            raise ConflictError("原资料确认缺少操作范围，不能回读来源")
        from modules.evidence.facade import prepare_confirmed_ai_action

        confirmed = await prepare_confirmed_ai_action(
            db,
            novel_id=str(novel_id),
            action=work.context_confirmation_action,
            confirmation_id=str(work.context_confirmation_id),
        )
        if not _confirmed_source_selected(confirmed, source_ref):
            raise ConflictError("来源不在原确认的已选范围内或已被排除")
    return await read_novel_evidence(
        db,
        novel_id=str(novel_id),
        source_ref=source_ref,
        visibility=_visibility(work),
        before=0,
        after=0,
    )


async def _preview_scope(db, novel_id, args, *, context=None):
    work = await _require_owned_author_project(db, novel_id, context)
    target_ref = TargetRef.model_validate(args.target.model_dump())
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db,
        str(novel_id),
        context,
        [(target_ref.target_type, target_ref.target_id)],
    )
    inspected = await inspect_novel_target(
        db,
        novel_id=str(novel_id),
        target_ref=target_ref,
        content_mode="working",
        visibility=_visibility(work),
    )
    if not inspected.get("visible"):
        return {
            "target_ref": target_ref.canonical_dict(),
            "visible": False,
            "omission": "目标不在当前作者可见范围",
        }
    return {
        "target_ref": target_ref.canonical_dict(),
        "visible": True,
        "inspection": inspected,
        "effect": "只预览 Evidence 当前可见的目标资料；不扩大确认范围或修改任何资产",
    }


OPERATIONS_SPEC = {
    "evidence.project.search": {
        "label": "检索当前作品资料",
        "schema": SearchProject,
        "prepare": _search,
        "permission": "read",
        "op_version": "1",
        "description": (
            "在作者当前可见范围内检索正文、世界或大纲资料；"
            "若已有资料确认，只回传原确认内容。"
        ),
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("作者对当前作品具有读取权限",),
        "produces": ("evidence_search_hits",),
        "target_type": "evidence_scope",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("query", "scopes"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "evidence.source.read": {
        "label": "回读精确正文来源",
        "schema": ReadSource,
        "prepare": _read_source,
        "permission": "read",
        "op_version": "1",
        "description": (
            "按 Evidence 来源引用回读精确正文片段，并重验作品、版本、"
            "来源 hash 与当前可见截止。"
        ),
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("来源引用可由 Evidence 精确回读", "当前范围允许该正文版本"),
        "produces": ("evidence_source_read",),
        "target_type": "evidence_source",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("source_ref",),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "evidence.knowledge.preview_scope": {
        "label": "預覽知識範圍",
        "schema": PreviewKnowledgeScope,
        "prepare": _preview_scope,
        "permission": "read",
        "op_version": "1",
        "description": (
            "通过 Evidence 的 owner、作品、排除项、Scene 截止与可见性检查，"
            "预览一个目标的当前知识范围。"
        ),
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("目標由 Evidence 支持且位於作者可見範圍",),
        "produces": ("evidence_knowledge_scope_preview",),
        "target_type": "evidence_target",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("target",),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}

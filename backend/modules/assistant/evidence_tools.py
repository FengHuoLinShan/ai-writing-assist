"""Read-only tools: server scope and original confirmation precede model access."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext, Tool

from core.config import get_settings
from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import (
    WORLD_READ_MAP_SPATIAL_BRIEF,
    WORLD_READ_PROJECT_VOCABULARY,
)
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.workflow_budget import budgeted_tool
from infrastructure.stable_hash import stable_hash
from modules.assistant.operation_scope import require_operation_targets
from modules.assistant.schemas import WorkContext
from modules.evidence import facade as evidence
from modules.evidence.contracts import VisibilityContextContract
from modules.project.facade import get_any_project_context, require_any_active_project
from modules.story.facade import get_scene_contract
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import get_draft, get_latest_draft_for_chapter


def fingerprint(value: Any) -> str:
    return stable_hash(value)


def fixed_reference_context(confirmed):
    compiled = confirmed.compiled
    map_section = next(
        (section for section in compiled.sections if section.key == "map_spatial"),
        None,
    )
    map_spatial = None
    if map_section is not None:
        map_spatial = {
            "scene_id": (map_section.retrieval_metadata or {}).get("scene_id"),
            "chapter_index": (map_section.retrieval_metadata or {}).get("chapter_index"),
            "items": [
                {
                    **dict(item.source or {}),
                    "node_id": (item.source or {}).get("node_id")
                    or (item.source or {}).get("id"),
                    "content": item.content,
                }
                for item in map_section.materialize_items().items
                if item.selection_state not in {"excluded", "omitted"}
            ],
            "omitted_count": int(
                (map_section.retrieval_metadata or {}).get("omitted_count") or 0
            ),
        }
    return {
        "title": "已确认的参考资料",
        "text": evidence.render_compiled_context(compiled),
        "confirmation_id": str(confirmed.confirmation.id),
        "map_spatial": map_spatial,
    }


@dataclass
class AssistantToolContext:
    db: Any
    novel_id: str
    owner_id: str
    work: WorkContext
    client: Any
    budget: AgentRunBudget
    checkpoint: Any
    allow_web: bool = False
    evidence_refs: dict[str, dict] = field(default_factory=dict)
    fixed_context: dict | None = None
    run_id: str | None = None
    task_id: str | None = None
    llm_snapshot: dict | None = None
    operations: dict | None = None
    operation_catalog_snapshot: dict | None = None
    operation_trace_incomplete: bool = False
    operation_trace_enabled: bool = False
    final_requests: int = 1
    session_id: str | None = None
    web_snapshot: dict | None = None
    team_blueprint: str | None = None

    async def guard(self):
        await require_any_active_project(self.db, self.novel_id)
        project = await get_any_project_context(self.db, self.novel_id)
        if (
            project is None
            or str(project.owner_id) != self.owner_id
            or project.project_kind != "author"
        ):
            raise NotFoundError("项目不可访问")
        if (
            self.work.scene_id
            and await get_scene_contract(self.db, self.novel_id, str(self.work.scene_id))
            is None
        ):
            raise NotFoundError("当前场景不属于本次项目")
        if self.work.draft_id:
            draft = await get_draft(self.db, self.novel_id, str(self.work.draft_id))
            latest = (
                await get_latest_draft_for_chapter(
                    self.db, self.novel_id, draft.chapter_index
                )
                if draft
                else None
            )
            if (
                draft is None
                or draft.status == "deprecated"
                or (
                    draft.status != "candidate"
                    and (latest is None or latest.id != draft.id)
                )
                or (self.work.source_hash and draft.content_hash != self.work.source_hash)
            ):
                raise ConflictError(
                    "当前正文已变化，请重新读取版本", code="assistant_source_stale"
                )
        if self.work.context_confirmation_id:
            confirmed = await evidence.prepare_confirmed_ai_action(
                self.db,
                novel_id=self.novel_id,
                action=self.work.context_confirmation_action,
                confirmation_id=str(self.work.context_confirmation_id),
            )
            self.fixed_context = fixed_reference_context(confirmed)
        return project

    @property
    def visibility(self):
        return VisibilityContextContract(
            mode="author",
            cutoff_chapter=self.work.chapter_index
            if self.work.scope == "current"
            else None,
            cutoff_scene_id=str(self.work.scene_id)
            if self.work.scene_id and self.work.scope == "current"
            else None,
        )

    def remember(self, payload: dict) -> dict | None:
        target = payload.get("target_ref") or {}
        source = payload.get("source_ref") or {}
        target_id = str(target.get("target_id") or target.get("id") or "")
        target_type = str(target.get("target_type") or target.get("type") or "")
        identities = {
            target_id,
            str(source.get("draft_id", "")),
            f"{target_type}:{target_id}",
        }
        excluded = set(self.work.excluded_targets) | {
            value.rsplit(":", 1)[-1] for value in self.work.excluded_targets
        }
        if target_type == "map_spatial":
            excluded.update(
                parts[1]
                for value in self.work.excluded_targets
                if (parts := value.split(":"))
                and len(parts) > 1
                and parts[0] == "map_spatial"
            )
        if identities.intersection(excluded):
            return None
        key = fingerprint(payload)
        self.evidence_refs[key] = payload
        return {"evidence_id": key, **payload}

    async def revalidate(self, keys: list[str]):
        await self.guard()
        for key in keys:
            if key not in self.evidence_refs:
                raise ConflictError(
                    "回答引用了本次未查证的资料", code="assistant_unknown_evidence"
                )
            item = self.evidence_refs[key]
            if item.get("spatial_advisory"):
                from modules.assistant.map_spatial_advisories import _identity, _read

                result = await _read(self.db, self.novel_id, self.work)
                if result is None or not any(
                    _identity(result.scene_id, entry.model_dump(mode="json"))
                    == item["advisory_fingerprint"]
                    for entry in result.items
                ):
                    raise ConflictError(
                        "空间提醒所用地图或来源已变化，请重新读取",
                        code="assistant_source_stale",
                    )
                continue
            if item.get("map_spatial_guard"):
                guard = item["map_spatial_guard"]
                if guard.get("fixed_context"):
                    map_context = (self.fixed_context or {}).get("map_spatial") or {}
                    current_items = map_context.get("items") or []
                    current_by_id = {
                        str(entry.get("node_id") or entry.get("id") or ""): entry
                        for entry in current_items
                    }
                    if any(
                        (entry := current_by_id.get(expected["node_id"])) is None
                        or str(entry.get("revision_id") or "") != expected["revision_id"]
                        or str(entry.get("revision_hash") or "")
                        != expected["revision_hash"]
                        or str(entry.get("geometry_hash") or "")
                        != expected["geometry_hash"]
                        or str(entry.get("content_hash") or "")
                        != expected["content_hash"]
                        or sorted(entry.get("source_hashes") or [])
                        != expected["source_hashes"]
                        for expected in guard["baseline"]
                    ):
                        raise ConflictError(
                            "確認後地圖參考已變化，請重新讀取後再引用",
                            code="assistant_source_stale",
                        )
                    continue
                current = await get(WORLD_READ_MAP_SPATIAL_BRIEF)(
                    self.db,
                    guard["request"],
                )
                current_by_id = {entry.node_id: entry for entry in current.items}
                baseline = guard["baseline"]
                if any(
                    (entry := current_by_id.get(expected["node_id"])) is None
                    or entry.title != expected["title"]
                    or entry.revision_id != expected["revision_id"]
                    or entry.revision_hash != expected["revision_hash"]
                    or entry.geometry_hash != expected["geometry_hash"]
                    or entry.content_hash != expected["content_hash"]
                    or sorted(entry.source_hashes) != expected["source_hashes"]
                    for expected in baseline
                ):
                    raise ConflictError(
                        "空间参考地图版本已变化，请重新读取后再引用",
                        code="assistant_source_stale",
                    )
                continue
            if item.get("source_guard"):
                from core.service_keys import (
                    ASSISTANT_OPERATIONS,
                )
                from modules.assistant.contracts import AssistantOperationContext

                guard = item["source_guard"]
                operation = get(ASSISTANT_OPERATIONS).get(guard["capability"])
                if operation is None or operation.permission != "suggest":
                    raise ConflictError("复核来源协议已变化")
                preview = await operation.prepare(
                    self.db,
                    self.novel_id,
                    operation.schema.model_validate(guard["arguments"]),
                    context=AssistantOperationContext(
                        self.run_id or "",
                        self.owner_id,
                        self.work,
                        trace_enabled=self.operation_trace_enabled,
                        trace_session_id=self.session_id,
                    ),
                )
                if fingerprint(preview) != guard["baseline_hash"]:
                    raise ConflictError("复核所依据的资料已变化，请重新检查")
                continue
            if (item.get("target_ref") or {}).get("target_type") == "project_workspace":
                # A status/count observation does not authorize any asset write.
                # Each proposed operation still rechecks its concrete baseline.
                continue
            if item.get("source_ref"):
                source = SourceRangeRefContract(**item["source_ref"])
                if source.content_mode == "working":
                    latest = await get_latest_draft_for_chapter(
                        self.db, self.novel_id, source.chapter_index
                    )
                    if latest is None or str(latest.id) != source.draft_id:
                        raise ConflictError(
                            "参考正文的当前版本已变化", code="assistant_source_stale"
                        )
                await evidence.read_novel_evidence(
                    self.db,
                    novel_id=self.novel_id,
                    source_ref=source,
                    visibility=self.visibility,
                    before=0,
                    after=0,
                )
            elif item.get("target_ref"):
                current = await evidence.inspect_novel_target(
                    self.db,
                    novel_id=self.novel_id,
                    target_ref=item["target_ref"],
                    content_mode="working",
                    visibility=self.visibility,
                )
                if fingerprint(current) != fingerprint(item.get("inspection")):
                    raise ConflictError(
                        "参考资料已变化，请重新查证", code="assistant_source_stale"
                    )
            elif item.get("scene_lens") is not None:
                lens = await evidence.load_scene_lens(
                    self.db,
                    novel_id=self.novel_id,
                    scene_id=str(self.work.scene_id),
                    chapter_index=self.work.chapter_index,
                )
                if fingerprint(lens) != fingerprint(item["scene_lens"]):
                    raise ConflictError(
                        "场景资料已变化，请重新查证", code="assistant_source_stale"
                    )

    async def record_confirmed_write(self, result: dict):
        """Freeze a domain's actual write for batch retry, not as new model evidence.

        Only the returned target changes. Original confirmations and review
        guards remain strict; unrelated sources retain their original baseline.
        """
        target = result.get("target") or result
        target_id = str(target.get("id") or "")
        if not target_id:
            return
        if result.get("type") == "writing_draft" and str(
            self.work.draft_id
        ) == result.get("replaces_draft_id"):
            self.work = WorkContext.model_validate(
                {
                    **self.work.model_dump(),
                    "draft_id": target_id,
                    "source_hash": result["source_hash"],
                }
            )
        for key, item in list(self.evidence_refs.items()):
            reference = item.get("target_ref") or {}
            if (
                str(reference.get("target_id")) == target_id
                and "inspection" in item
                and not item.get("source_guard")
            ):
                current = await evidence.inspect_novel_target(
                    self.db,
                    novel_id=self.novel_id,
                    target_ref=reference,
                    content_mode="working",
                    visibility=self.visibility,
                )
                self.evidence_refs[key] = {**item, "inspection": current}


@budgeted_tool
async def search_project(
    ctx: RunContext[AssistantToolContext], query: str, scope: str = "manuscript"
) -> dict:
    """查找当前授权项目资料。scope 为 manuscript、world 或 outline；返回可引用证据 ID。"""
    deps = ctx.deps
    if (
        scope not in {"manuscript", "world", "outline"}
        or not 1 <= len(query.strip()) <= 1000
    ):
        raise ModelRetry("请使用 manuscript、world 或 outline 范围与简短查询")
    await deps.guard()
    if deps.fixed_context is not None:
        item = deps.remember(deps.fixed_context)
        await deps.db.commit()
        return {"hits": [item] if item else [], "coverage": "original_confirmation_only"}
    found = await evidence.search_novel_evidence(
        deps.db,
        novel_id=deps.novel_id,
        query=query,
        content_mode="working",
        visibility=deps.visibility,
        scopes=[scope],
        top_k=12,
        context_scene_id=str(deps.work.scene_id) if deps.work.scene_id else None,
    )
    hits = []
    for hit in found.get("hits", []):
        if hit.get("target_ref") and not hit.get("source_ref"):
            inspection = await evidence.inspect_novel_target(
                deps.db,
                novel_id=deps.novel_id,
                target_ref=hit["target_ref"],
                content_mode="working",
                visibility=deps.visibility,
            )
            if not inspection.get("visible"):
                continue
            hit = {**hit, "inspection": inspection}
        if (item := deps.remember(hit)) is not None:
            hits.append(item)
    await deps.db.commit()
    return {
        "hits": hits,
        "warnings": found.get("warnings", []),
        "degraded": found.get("degraded", False),
        "coverage": "retrieval_only",
    }


@budgeted_tool
async def read_evidence(ctx: RunContext[AssistantToolContext], evidence_id: str) -> dict:
    """回读本轮已找到的精确证据；不能使用任意对象 ID 扩大权限。"""
    deps = ctx.deps
    await deps.guard()
    item = deps.evidence_refs.get(evidence_id)
    if item is None:
        await deps.db.rollback()
        raise ModelRetry("请选择本轮实际返回的 evidence_id")
    if item.get("source_ref"):
        item = await evidence.read_novel_evidence(
            deps.db,
            novel_id=deps.novel_id,
            source_ref=SourceRangeRefContract(**item["source_ref"]),
            visibility=deps.visibility,
            before=0,
            after=0,
        )
    result = deps.remember(item)
    await deps.db.commit()
    return result or {"omission": "资料已被排除"}


@budgeted_tool
async def current_scene(ctx: RunContext[AssistantToolContext]) -> dict:
    """读取当前场景的角色可知信息和历史状态；缺少视角时明确返回未覆盖。"""
    deps = ctx.deps
    await deps.guard()
    if deps.fixed_context is not None:
        result = deps.remember(deps.fixed_context)
    elif deps.work.excluded_targets:
        result = {"omission": "存在排除资料，请使用重新确认的场景资料检查知识边界"}
    elif deps.work.scene_id and deps.work.chapter_index:
        lens = await evidence.load_scene_lens(
            deps.db,
            novel_id=deps.novel_id,
            scene_id=str(deps.work.scene_id),
            chapter_index=deps.work.chapter_index,
        )
        result = deps.remember({"title": "当前场景", "scene_lens": lens})
    else:
        result = {"omission": "没有绑定当前场景，未检查人物知识边界"}
    await deps.db.commit()
    return result or {"omission": "资料已被排除"}


@budgeted_tool
async def research_fact(ctx: RunContext[AssistantToolContext], question: str) -> dict:
    """使用当前供应商原生联网查现实通用事实。只传必要问题，禁止小说剧情及私人正文。"""
    deps = ctx.deps
    if not deps.allow_web:
        raise ValueError("本次未启用联网")
    from infrastructure.llm.native_search import (
        NativeSearchUnavailableError,
        factual_result_allowed,
        private_text_fragments,
        validate_fact_question,
    )

    project = await deps.guard()
    private_texts = [deps.work.selection]
    for ref in deps.evidence_refs.values():
        if not ref.get("external"):
            private_texts.extend(private_text_fragments(ref))
    try:
        question = validate_fact_question(
            question, protected_terms=[project.title], private_texts=private_texts
        )
    except ValueError:
        await deps.db.commit()
        return {"omission": "联网问题需去除作品身份、剧情和私人原文，请改为通用事实问题"}
    await deps.db.commit()

    async def reserve():
        deps.budget.reserve(requests=1, web=1)
        await deps.checkpoint(deps.budget.model_dump(mode="json"))

    try:
        result = await deps.client.research(question, before_request=reserve)
    except NativeSearchUnavailableError as error:
        if error.requests:
            deps.budget.add_usage(error.usage, requests=error.requests)
        await deps.checkpoint(deps.budget.model_dump(mode="json"))
        return {"omission": "供应商未完成可验证的搜索，未采用其回答"}
    deps.budget.add_usage(result.usage, requests=result.requests)
    await deps.checkpoint(deps.budget.model_dump(mode="json"))
    if not factual_result_allowed(result, protected_terms=[project.title]):
        return {"omission": "联网结果缺少可引用来源或含越界内容，未用作事实依据"}
    data = result.model_dump(exclude={"usage"})
    return deps.remember({"title": "外部参考", "external": True, **data}) or {}


@budgeted_tool
async def inspect_current(ctx: RunContext[AssistantToolContext], offset: int = 0) -> dict:
    """读取作者当前所选对象或正文原文；长正文每次最多八千字，可按返回位置继续。"""
    deps = ctx.deps
    await deps.guard()
    if deps.fixed_context:
        result = deps.remember(deps.fixed_context)
    elif deps.work.draft_id:
        from modules.writing.facade import build_manuscript_range_ref

        draft = await get_draft(deps.db, deps.novel_id, str(deps.work.draft_id))
        text = draft.content or ""
        if not 0 <= offset < max(1, len(text)):
            await deps.db.rollback()
            raise ModelRetry(
                "正文位置超出当前版本，请使用返回的 next_offset；为空表示已到正文末尾"
            )
        if not text:
            await deps.db.commit()
            return {"omission": "当前正文为空"}
        end = min(len(text), offset + 8000)
        if draft.status == "candidate":
            target = {
                "target_type": "writing_candidate",
                "target_id": str(draft.id),
                "target_path": f"content[{offset}]",
            }
            inspection = await evidence.inspect_novel_target(
                deps.db,
                novel_id=deps.novel_id,
                target_ref=target,
                content_mode="working",
                visibility=deps.visibility,
            )
            result = (
                deps.remember(
                    {"title": draft.title, "target_ref": target, "inspection": inspection}
                )
                if inspection.get("visible")
                else None
            )
            await deps.db.commit()
            return result or {"omission": "这份候选不在当前可审阅范围内"}
        source = await build_manuscript_range_ref(
            deps.db,
            deps.novel_id,
            draft_id=draft.id,
            content_mode="working",
            start_offset=offset,
            end_offset=end,
        )
        item = await evidence.read_novel_evidence(
            deps.db,
            novel_id=deps.novel_id,
            source_ref=source,
            visibility=deps.visibility,
            before=0,
            after=0,
        )
        result = deps.remember(
            {
                **item,
                "title": draft.title,
                "total_characters": len(text),
                "next_offset": end if end < len(text) else None,
            }
        )
    elif deps.work.target:
        target = deps.work.target
        if target.get("target_type") == "map_atlas_node" and deps.work.excluded_targets:
            await deps.db.commit()
            return {"omission": "当前排除范围下不能完整回读地图依据，请从地图工作台核对"}
        if str(target.get("target_id")) in {
            value.rsplit(":", 1)[-1] for value in deps.work.excluded_targets
        }:
            await deps.db.commit()
            return {"omission": "当前资料已被排除"}
        inspection = await evidence.inspect_novel_target(
            deps.db,
            novel_id=deps.novel_id,
            target_ref=target,
            content_mode="working",
            visibility=deps.visibility,
        )
        result = (
            deps.remember({"target_ref": target, "inspection": inspection})
            if inspection.get("visible")
            else None
        )
    else:
        result = None
    await deps.db.commit()
    return result or {
        "omission": "当前位置没有可读取的对象，请选择正文、资料或使用项目查找"
    }


@budgeted_tool
async def project_overview(ctx: RunContext[AssistantToolContext]) -> dict:
    """查看当前作品的继续写作位置、待办和待处理事项；不是整部作品事实或检查结果。"""
    deps = ctx.deps
    await deps.guard()
    if deps.fixed_context or deps.work.excluded_targets:
        await deps.db.commit()
        return {"omission": "当前限定资料范围，不扩展为全项目事项概览"}
    target = {"target_type": "project_workspace", "target_id": deps.novel_id}
    inspection = await evidence.inspect_novel_target(
        deps.db,
        novel_id=deps.novel_id,
        target_ref=target,
        content_mode="working",
        visibility=deps.visibility,
    )
    result = deps.remember(
        {"title": "当前工作概览", "target_ref": target, "inspection": inspection}
    )
    await deps.db.commit()
    return result or {}


@budgeted_tool
async def scene_assets(ctx: RunContext[AssistantToolContext]) -> dict:
    """读取当前场景的人物卡和剧本版本；这些作者资料不等于人物已知事实。"""
    deps = ctx.deps
    await deps.guard()
    if not deps.work.scene_id or deps.fixed_context or deps.work.excluded_targets:
        await deps.db.commit()
        return {"omission": "需要当前场景且资料范围允许；不会扩展已确认或排除范围"}
    target = {"target_type": "scene_story_assets", "target_id": str(deps.work.scene_id)}
    inspection = await evidence.inspect_novel_target(
        deps.db,
        novel_id=deps.novel_id,
        target_ref=target,
        content_mode="working",
        visibility=deps.visibility,
    )
    result = deps.remember(
        {"title": "场景人物卡与剧本", "target_ref": target, "inspection": inspection}
    )
    await deps.db.commit()
    return result or {}


@budgeted_tool
async def author_tasks(
    ctx: RunContext[AssistantToolContext],
    on_date: str,
    scope: Literal["today", "inbox", "later", "completed", "archived"] = "today",
    skip: int = 0,
) -> dict:
    """查作者待办。today 含到期与逾期，later 为未来；每页30项，可指定日期。"""
    from datetime import date

    deps = ctx.deps
    await deps.guard()
    if deps.fixed_context or deps.work.excluded_targets:
        await deps.db.commit()
        return {"omission": "当前限定资料范围，不扩展读取作者待办"}
    if not 0 <= skip <= 10000:
        raise ValueError("待办分页超出范围")
    calendar = date.fromisoformat(on_date)
    target = {"target_type": "project_workspace", "target_id": deps.novel_id}
    inspection = await evidence.list_author_task_evidence(
        deps.db,
        novel_id=deps.novel_id,
        scope=scope,
        on_date=calendar,
        skip=skip,
        visibility=deps.visibility,
    )
    result = deps.remember(
        {"title": "作者待办", "target_ref": target, "inspection": inspection}
    )
    await deps.db.commit()
    return result or {}


@budgeted_tool
async def organization_status(
    ctx: RunContext[AssistantToolContext], task_id: UUID | None = None
) -> dict:
    """查看最近或指定整理的进度、原章节范围与可恢复状态，不读取正文或私有模型历史。"""
    deps = ctx.deps
    await deps.guard()
    if deps.fixed_context or deps.work.excluded_targets:
        await deps.db.commit()
        return {"omission": "当前限定资料范围，请到原整理回执查看进度"}
    value = await evidence.read_organization_evidence(
        deps.db,
        novel_id=deps.novel_id,
        task_id=str(task_id) if task_id else None,
        visibility=deps.visibility,
    )
    result = deps.remember(
        {
            "title": "整理回执",
            "target_ref": {
                "target_type": "project_workspace",
                "target_id": deps.novel_id,
            },
            "inspection": value,
        }
    )
    await deps.db.commit()
    return result or {}


@budgeted_tool
async def session_context(ctx: RunContext[AssistantToolContext]) -> dict:
    """读取本次讨论的来源与已保存阶段成果；它们不是自动采用的世界事实。"""
    deps = ctx.deps
    await deps.guard()
    if (
        not deps.session_id
        or deps.fixed_context
        or deps.work.excluded_targets
        or deps.visibility.cutoff_chapter is not None
        or deps.visibility.cutoff_scene_id
    ):
        await deps.db.commit()
        return {"omission": "当前范围受限，不扩展读取整份讨论阶段成果"}
    target = {"target_type": "assistant_session", "target_id": deps.session_id}
    inspection = await evidence.inspect_novel_target(
        deps.db,
        novel_id=deps.novel_id,
        target_ref=target,
        content_mode="working",
        visibility=deps.visibility,
    )
    result = {
        "discussion": deps.remember({"target_ref": target, "inspection": inspection})
    }
    checkpoint = (inspection.get("item") or {}).get("checkpoint_id")
    if checkpoint:
        target = {"target_type": "world_checkpoint", "target_id": checkpoint}
        inspection = await evidence.inspect_novel_target(
            deps.db,
            novel_id=deps.novel_id,
            target_ref=target,
            content_mode="working",
            visibility=deps.visibility,
        )
        if inspection.get("visible"):
            if len(json.dumps(inspection, ensure_ascii=False, default=str)) <= 30000:
                result["checkpoint"] = deps.remember(
                    {"target_ref": target, "inspection": inspection}
                )
            else:
                result["omission"] = "阶段成果较大，请在世界工作台按部分继续核对"
    await deps.db.commit()
    return result


async def _web_scope(deps):
    from infrastructure.llm.native_search import private_text_fragments
    from infrastructure.llm.web_search import require_search_snapshot

    if not deps.allow_web:
        raise ValueError("本次未启用公开资料查证")
    require_search_snapshot(deps.web_snapshot)
    project = await deps.guard()
    private = [deps.work.selection, *(private_text_fragments(deps.fixed_context or {}))]
    for ref in deps.evidence_refs.values():
        if not ref.get("external"):
            private.extend(private_text_fragments(ref))
    protected = [project.title]
    await deps.db.commit()
    return protected, private


@budgeted_tool
async def search_general_fact(
    ctx: RunContext[AssistantToolContext], question: str
) -> dict:
    """搜索现实通用事实，返回未核实的网页摘要；引用前须用 read_web_source 读取原文。"""
    from infrastructure.llm.web_search import WebReadError, search_public_fact

    deps = ctx.deps
    protected, private = await _web_scope(deps)

    async def reserve():
        if deps.budget.web_requests >= deps.budget.limits[2]:
            raise WebReadError(
                "本轮联网额度已用完，请根据已有依据继续；未读网页不作为事实"
            )
        deps.budget.reserve(web=1)
        await deps.checkpoint(deps.budget.model_dump(mode="json"))

    try:
        result = await search_public_fact(
            question,
            snapshot=deps.web_snapshot,
            before_request=reserve,
            protected_terms=protected,
            private_texts=private,
        )
    except WebReadError as error:
        return {"omission": str(error), "hits": []}

    hits = [
        deps.remember({"external": True, "web_result": hit, **hit})
        for hit in result["hits"]
    ]
    await deps.checkpoint(deps.budget.model_dump(mode="json"))
    return {**result, "hits": hits}


@budgeted_tool
async def read_web_source(
    ctx: RunContext[AssistantToolContext], evidence_id: str
) -> dict:
    """读取本次搜索返回的网页引用，不能传 URL；结果只代表实际读取的外部参考。"""
    from infrastructure.llm.web_search import WebReadError, read_public_page

    deps = ctx.deps
    protected, _ = await _web_scope(deps)
    ref = deps.evidence_refs.get(evidence_id, {})
    if not ref.get("external") or not ref.get("web_result"):
        raise ModelRetry("请选择本次搜索返回的网页引用")
    # Completed page reads survive disconnects without issuing the HTTP call again.
    for key, item in deps.evidence_refs.items():
        if item.get("search_evidence_id") == evidence_id:
            return {"evidence_id": key, **item}

    async def reserve():
        if deps.budget.web_requests >= deps.budget.limits[2]:
            raise WebReadError(
                "本轮联网额度已用完，请根据已有依据继续；未读网页不作为事实"
            )
        deps.budget.reserve(web=1)
        await deps.checkpoint(deps.budget.model_dump(mode="json"))

    try:
        page = await read_public_page(
            ref["web_result"]["url"], before_request=reserve, protected_terms=protected
        )
    except WebReadError as error:
        return {"omission": str(error)}
    result = deps.remember(
        {
            "external": True,
            "search_evidence_id": evidence_id,
            **page,
            "sources": [{"url": page["url"], "title": page["title"]}],
        }
    )
    await deps.checkpoint(deps.budget.model_dump(mode="json"))
    return result


@budgeted_tool
async def world_page_history(
    ctx: RunContext[AssistantToolContext], page_id: str, version_number: int | None = None
) -> dict:
    """查看世界书页面最近二十个版本；指定版本可读历史摘录，恢复仍需具体修改确认。"""
    deps = ctx.deps
    await deps.guard()
    await require_operation_targets(
        deps.db, deps.novel_id, deps, [("world_bible_page", page_id)], aggregate=True
    )
    target = {
        "target_type": "world_bible_page_history",
        "target_id": str(UUID(page_id)),
        "target_path": str(version_number) if version_number is not None else None,
    }
    item = await evidence.inspect_novel_target(
        deps.db,
        novel_id=deps.novel_id,
        target_ref=target,
        content_mode="working",
        visibility=deps.visibility,
    )
    await deps.db.commit()
    if not item.get("visible"):
        return {"omission": "历史资料未在本次范围内开放，请在世界书中查看"}
    return (
        deps.remember({"target_ref": target, "inspection": item, "title": "资料历史版本"})
        or {}
    )


@budgeted_tool
async def review_resolution_result(
    ctx: RunContext[AssistantToolContext], task_id: UUID
) -> dict:
    """读取本次智能整理的关键问题、候选字段和可选择成员；建议不是作品事实。"""
    deps = ctx.deps
    await deps.guard()
    if deps.fixed_context or deps.work.excluded_targets:
        await deps.db.commit()
        return {"omission": "当前限定资料范围，请到原整理回执查看"}
    value = await evidence.read_review_resolution_evidence(
        deps.db, novel_id=deps.novel_id, task_id=str(task_id), visibility=deps.visibility
    )
    result = deps.remember(
        {
            "title": "智能整理结果",
            "target_ref": {
                "target_type": "project_workspace",
                "target_id": deps.novel_id,
            },
            "inspection": value,
        }
    )
    await deps.db.commit()
    return result or {}


@budgeted_tool
async def project_vocabulary(
    ctx: RunContext[AssistantToolContext], kind: str | None = None, limit: int = 100
) -> dict:
    """读取本项目词条身份和当前修订，为类型修改准备参数；省略项不代表不存在。

    仅全书资料范围可读。返回词表维护资料，不作为正文或世界事实证据。
    """
    deps = ctx.deps
    await deps.guard()
    await require_operation_targets(deps.db, deps.novel_id, deps, [], aggregate=True)
    if deps.work.scope == "current" and (deps.work.chapter_index or deps.work.scene_id):
        raise ModelRetry("项目词表属于全书范围，请切换到项目资料范围后再读取")
    if not 1 <= limit <= 500:
        raise ModelRetry("一次读取词表的上限须为 1 至 500 项")
    response = await get(WORLD_READ_PROJECT_VOCABULARY)(
        deps.db, deps.novel_id, kind=kind, limit=limit, include_archived=True
    )
    fields = {
        "id",
        "revision_id",
        "kind",
        "name",
        "description",
        "aliases",
        "traits",
        "status",
        "source",
        "author_confirmed",
        "redirect_to_id",
    }
    result = {
        "items": [
            item.model_dump(mode="json", include=fields) for item in response.items
        ],
        "total_count": response.total_count,
        "omitted_count": response.omitted_count,
    }
    await deps.db.commit()
    return result


@budgeted_tool
async def map_spatial_brief(
    ctx: RunContext[AssistantToolContext], query: str, limit: int = 5
) -> dict:
    """只读已采用地图的地点、明示通路、行程和有时点的位置参考。"""
    deps = ctx.deps
    query = query.strip()
    if not 1 <= len(query) <= 1000 or not 1 <= limit <= 8:
        raise ModelRetry("地图查询需提供简短问题，limit 须为 1 至 8")
    await deps.guard()
    if "assistant.turn" not in get_settings().map_spatial_enabled_capabilities:
        await deps.db.commit()
        return {"enabled": False, "items": [], "message": "空间参考尚未为本能力启用"}
    if (
        deps.fixed_context is None
        and deps.work.scope == "current"
        and not (deps.work.scene_id or deps.work.chapter_index)
    ):
        raise ModelRetry("当前范围需要明确章节或 Scene；也可切换到项目资料范围查询地图")
    await require_operation_targets(deps.db, deps.novel_id, deps, [])

    fixed_map = (
        deps.fixed_context.get("map_spatial") if deps.fixed_context is not None else None
    )
    if deps.fixed_context is not None:
        map_context = fixed_map or {"items": [], "omitted_count": 0}
        raw_items = list(map_context.get("items") or [])
        scene_id = map_context.get("scene_id")
        chapter_index = map_context.get("chapter_index")
        omitted_count = int(map_context.get("omitted_count") or 0)
    else:
        request = {
            "novel_id": deps.novel_id,
            "scene_id": (str(deps.work.scene_id) if deps.work.scene_id else None),
            "chapter_index": deps.work.chapter_index,
            "reveal_mode": "author_safe",
            "query_text": query,
            "excluded_ids": list(deps.work.excluded_targets),
            "limit": limit,
        }
        result = await get(WORLD_READ_MAP_SPATIAL_BRIEF)(deps.db, request)
        raw_items = [item.model_dump(mode="json") for item in result.items]
        scene_id = result.scene_id
        chapter_index = result.chapter_index
        omitted_count = result.omitted_count

    evidence = []
    excluded_count = 0
    for raw in raw_items[:limit]:
        node_id = str(raw.get("node_id") or raw.get("id") or "")
        revision_id = str(raw.get("revision_id") or "")
        title = str(raw.get("title") or raw.get("label") or "已保存地图")[:200]
        content = str(raw.get("content") or "")
        baseline = {
            "node_id": node_id,
            "title": title,
            "revision_id": revision_id,
            "revision_hash": str(raw.get("revision_hash") or ""),
            "geometry_hash": str(raw.get("geometry_hash") or ""),
            "content_hash": str(raw.get("content_hash") or ""),
            "source_hashes": list(raw.get("source_hashes") or [])[:64],
        }
        if not node_id or not revision_id or not content or not baseline["content_hash"]:
            continue
        source_ref = {"target_type": "map_spatial", "target_id": node_id}
        item = deps.remember(
            {
                "title": title,
                "snippet": content,
                "target_ref": source_ref,
                "domain_reference": {
                    "type": "map_spatial",
                    "id": node_id,
                    "label": title,
                },
                "map_spatial_guard": {
                    "request": {
                        "novel_id": deps.novel_id,
                        "scene_id": scene_id,
                        "chapter_index": chapter_index,
                        "reveal_mode": "author_safe",
                        "query_text": query,
                        "excluded_ids": list(deps.work.excluded_targets),
                        "limit": limit,
                    },
                    "fixed_context": deps.fixed_context is not None,
                    "baseline": [baseline],
                },
            }
        )
        if item is None:
            excluded_count += 1
        else:
            evidence.append(
                {key: value for key, value in item.items() if key != "map_spatial_guard"}
            )
    await deps.db.commit()
    return {
        "enabled": True,
        "items": evidence,
        "omitted_count": omitted_count + excluded_count + max(0, len(raw_items) - limit),
        "note": "只作空间参考；不替代正文、世界正史或作者确认。",
    }


async def map_journey(
    ctx: RunContext[AssistantToolContext], origin: str, destination: str
) -> dict:
    """查询两地之间已采用的行程声明；名称歧义或缺少依据时返回 unknown。"""
    if (
        not origin.strip()
        or not destination.strip()
        or max(len(origin), len(destination)) > 200
    ):
        raise ModelRetry("请提供两个明确的地点名称")
    found = await map_spatial_brief(ctx, query=f"{origin} {destination}")
    matches = []
    for item in found.get("items", []):
        try:
            payload = json.loads(item.get("snippet") or "{}")
        except (ValueError, TypeError):
            continue
        rows = [
            row
            for row in payload.get("行程与通行条件", [])
            if row.get("from") == origin.strip() and row.get("to") == destination.strip()
        ]
        if rows:
            matches.append(
                {
                    "evidence_id": item["evidence_id"],
                    "journeys": rows,
                    "map": item.get("domain_reference"),
                }
            )
    return {
        "status": "known" if len(matches) == 1 else "unknown",
        "items": matches if len(matches) == 1 else [],
        "reason": "只有同一对明确地点的已采用行程可作为依据；缺失或同名歧义不猜测",
    }


async def map_object_position(
    ctx: RunContext[AssistantToolContext], object_name: str
) -> dict:
    """查询当前 Scene 截止时移动对象的最后明确位置；不从档案或地图回填位置。"""
    if not object_name.strip() or len(object_name) > 200:
        raise ModelRetry("请提供一个明确的移动对象名称")
    found = await map_spatial_brief(ctx, query=object_name)
    matches = []
    for item in found.get("items", []):
        try:
            payload = json.loads(item.get("snippet") or "{}")
        except (ValueError, TypeError):
            continue
        rows = [
            row
            for row in payload.get("移动对象最后位置", [])
            if row.get("object") == object_name.strip()
        ]
        if rows:
            matches.append(
                {
                    "evidence_id": item["evidence_id"],
                    "positions": rows,
                    "map": item.get("domain_reference"),
                }
            )
    return {
        "status": "known" if len(matches) == 1 else "unknown",
        "items": matches if len(matches) == 1 else [],
        "reason": "仅报告当前Scene及以前有精确正文来源的最后位置；没有记录时返回未知",
    }


def author_read_tools(*, allow_web: bool, version: str = "2") -> list[Tool]:
    functions = [
        search_project,
        read_evidence,
        inspect_current,
        project_overview,
        scene_assets,
        current_scene,
        session_context,
        author_tasks,
        organization_status,
    ]
    if allow_web:
        functions.extend(
            [search_general_fact, read_web_source]
            if version in {"3", "4", "5", "6", "7"}
            else [research_fact]
        )
    if version in {"3", "4", "5", "6", "7"}:
        functions.extend([world_page_history, review_resolution_result])
    if version in {"4", "5", "6", "7"}:
        functions.append(project_vocabulary)
    if version in {"5", "6", "7"}:
        functions.append(map_spatial_brief)
    if version in {"6", "7"}:
        from modules.assistant.map_spatial_advisories import map_spatial_advisories

        functions.extend([map_spatial_advisories, map_journey, map_object_position])
    return [Tool(function, sequential=True) for function in functions]

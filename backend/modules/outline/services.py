from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from core.crud import CrudService
from infrastructure.llm.errors import LLMInvalidResponseError
from modules.outline.contracts import OutlineArcContract, PlotThreadContract
from modules.outline.models import OutlineArc, PlotThread
from modules.outline.repositories import OutlineArcRepository, PlotThreadRepository
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

_P = TypeVar("_P", bound=BaseModel)


class PlotThreadService(CrudService[PlotThread, PlotThreadCreate, PlotThreadUpdate, PlotThreadResponse]):
    repo = PlotThreadRepository()
    response = PlotThreadResponse
    list_response = PlotThreadListResponse
    label = "PlotThread"
    id_param = "thread_id"

    async def get_active(
        self, db: AsyncSession, novel_id: str, chapter_index: int,
    ) -> list[PlotThreadContract]:
        nid = parse_uuid(novel_id, "novel_id")
        threads = await self.repo.get_active(db, nid, chapter_index)
        return [
            PlotThreadContract(
                id=str(t.id), novel_id=str(t.novel_id),
                name=t.name, thread_type=t.thread_type,
                summary=t.summary, visible_goal=t.visible_goal,
                hidden_truth=t.hidden_truth,
                start_chapter=t.start_chapter,
                planned_payoff_chapter=t.planned_payoff_chapter,
                current_stage=t.current_stage,
                related_character_ids=t.related_character_ids or [],
                related_entity_ids=t.related_entity_ids or [],
                reader_known_state=t.reader_known_state,
                author_known_state=t.author_known_state,
                status=t.status,
            )
            for t in threads
        ]


class OutlineArcService(CrudService[OutlineArc, OutlineArcCreate, OutlineArcUpdate, OutlineArcResponse]):
    repo = OutlineArcRepository()
    response = OutlineArcResponse
    list_response = OutlineArcListResponse
    label = "OutlineArc"
    id_param = "arc_id"

    async def get_by_chapter(
        self, db: AsyncSession, novel_id: str, chapter_index: int,
    ) -> OutlineArcContract | None:
        nid = parse_uuid(novel_id, "novel_id")
        arc = await self.repo.get_by_chapter(db, nid, chapter_index)
        if arc is None:
            return None
        return OutlineArcContract(
            id=str(arc.id), novel_id=str(arc.novel_id),
            title=arc.title, arc_index=arc.arc_index,
            start_chapter=arc.start_chapter, end_chapter=arc.end_chapter,
            arc_goal=arc.arc_goal, core_conflict=arc.core_conflict,
            main_opposition=arc.main_opposition, entry_hook=arc.entry_hook,
            midpoint_turn=arc.midpoint_turn, climax=arc.climax,
            result=arc.result, next_hook=arc.next_hook,
            related_thread_ids=arc.related_thread_ids or [],
            related_character_ids=arc.related_character_ids or [],
            related_entity_ids=arc.related_entity_ids or [],
            status=arc.status,
        )


def _per_item_validate(
    data: dict | list | None,
    thread_cls: type[BaseModel],
    arc_cls: type[BaseModel],
    extra_models: dict[str, type[BaseModel]] | None,
    output_cls: type[_P],
) -> _P:
    """逐项校验，单字段错不整批丢弃。

    LLM 常输出类型错误的值（如 planned_payoff_chapter="后续篇章"），
    generate_structured 的全局校验会丢弃整批数据。此函数对每条
    thread/arc 做独立校验，只丢弃无效项。
    """
    if not isinstance(data, dict):
        logger.warning("_per_item_validate: expected dict, got %s", type(data).__name__)
        return output_cls()

    threads = []
    for t in data.get("plot_threads", []):
        try:
            threads.append(thread_cls.model_validate(t))
        except ValidationError as e:
            logger.warning("Skipping invalid thread: %s", e)

    arcs = []
    for a in data.get("outline_arcs", []):
        try:
            arcs.append(arc_cls.model_validate(a))
        except ValidationError as e:
            logger.warning("Skipping invalid arc: %s", e)

    extra_kw: dict[str, list] = {}
    section_keys = ("foreshadowing_plans", "reveal_plans",
                    "offscreen_progress", "risks", "questions_for_user")
    for section_key in section_keys:
        items = data.get(section_key, [])
        if not isinstance(items, list):
            logger.warning("_per_item_validate: '%s' expected list, got %s",
                           section_key, type(items).__name__)
            extra_kw[section_key] = []
            continue
        model_cls = (extra_models or {}).get(section_key)
        validated_items = []
        for item in items:
            if model_cls is not None:
                try:
                    validated_items.append(model_cls.model_validate(item))
                except ValidationError as e:
                    logger.warning("Skipping invalid %s item: %s", section_key, e)
            else:
                validated_items.append(item)
        extra_kw[section_key] = validated_items

    return output_cls(plot_threads=threads, outline_arcs=arcs, **extra_kw)


class PlotStructureGenerator:
    """AI 剧情结构生成器"""

    MAX_EMPTY_RETRIES = 2  # 空结果重试次数

    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest

        nid = parse_uuid(novel_id, "novel_id")
        warnings_list: list[str] = []

        # ============================================================
        # 1. 加载上下文
        # ============================================================
        bundle = await _container_get("context.compile")(
            db=db, novel_id=novel_id,
            task="生成剧情结构",
            scope="full",
            chapter_index=start_chapter,
            reveal_mode="author_only",
        )

        # ============================================================
        # 2. 构建上下文文本（将注入到 prompt 中）
        # ============================================================
        context_md = ""
        if bundle.project:
            context_md += f"## 项目\n{bundle.project}\n\n"
        if bundle.world_entities:
            context_md += "## 世界对象\n"
            for e in bundle.world_entities:
                context_md += f"- {e.get('name', '?')} ({e.get('entity_type', '?')}): {e.get('summary', '')}\n"
        if bundle.characters:
            context_md += "\n## 人物\n"
            for c in bundle.characters:
                context_md += f"- {c.get('name', '?')} ({c.get('role', '?')}): {c.get('desire', '')}\n"

        # 构建名称→ID 映射表（用于 Fix 2：related_*_names → related_*_ids）
        entity_name_to_id = {
            e["name"]: e["entity_id"]
            for e in (bundle.world_entities or [])
            if e.get("entity_id") and e.get("name")
        }
        character_name_to_id = {
            ch["name"]: ch["character_id"]
            for ch in (bundle.characters or [])
            if ch.get("character_id") and ch.get("name")
        }

        # ============================================================
        # 3. 加载 prompt（已无用的模板变量保留以兼容现有结构）
        # ============================================================
        from core.config import get_settings
        settings = get_settings()

        system_prompt = load_prompt("structure_plot",
            world_context="",
            user_intent="",
            target_scope=f"章节 {start_chapter}-{end_chapter}",
        )
        # Fix 1：追加上下文（prompt 模版没有 {world_context} 占位符）
        system_prompt += f"\n\n## 当前上下文\n\n{context_md}"

        # ============================================================
        # 4. 定义输出 Pydantic 模型（Fix 5：增加提示词全部输出章节）
        # ============================================================

        class _GeneratedThread(BaseModel):
            name: str
            thread_type: str
            summary: str | None = None
            visible_goal: str | None = None
            hidden_truth: str | None = None
            start_chapter: int | None = None
            planned_payoff_chapter: int | None = None
            current_stage: str | None = None
            related_character_names: list[str] = []
            related_entity_names: list[str] = []

        class _GeneratedArc(BaseModel):
            title: str
            arc_index: int | None = None
            start_chapter: int | None = None
            end_chapter: int | None = None
            arc_goal: str | None = None
            core_conflict: str | None = None
            main_opposition: str | None = None
            entry_hook: str | None = None
            midpoint_turn: str | None = None
            climax: str | None = None
            result: str | None = None
            next_hook: str | None = None
            related_character_names: list[str] = []
            related_entity_names: list[str] = []
            related_thread_names: list[str] = []

        class _ForeshadowingPlan(BaseModel):
            name: str = ""
            summary: str | None = None
            planned_seed_chapter: int | None = None
            planned_payoff_chapter: int | None = None
            status: str = "draft"

        class _RevealPlan(BaseModel):
            target_name: str = ""
            target_type: str = "world_entity"
            secret_summary: str | None = None
            status: str = "draft"

        class _OffscreenProgress(BaseModel):
            thread_name: str = ""
            offscreen_description: str | None = None
            importance: str = "medium"

        class _Risk(BaseModel):
            risk_type: str = "其他"
            description: str | None = None
            severity: str = "medium"

        class _Question(BaseModel):
            question: str = ""
            context: str | None = None
            suggested_options: list[str] = []

        class _GenerationOutput(BaseModel):
            plot_threads: list[_GeneratedThread] = []
            outline_arcs: list[_GeneratedArc] = []
            foreshadowing_plans: list[_ForeshadowingPlan] = []
            reveal_plans: list[_RevealPlan] = []
            offscreen_progress: list[_OffscreenProgress] = []
            risks: list[_Risk] = []
            questions_for_user: list[_Question] = []

        # ============================================================
        # 5. 调用 LLM（Fix 3：空结果重试 + Fix 4：逐项校验降级）
        # ============================================================
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"请为章节 {start_chapter}-{end_chapter} 生成剧情结构和篇章大纲。"
                    f"\n\n当前上下文：\n{context_md}"
                )},
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient()
        result: _GenerationOutput | None = None

        for attempt in range(self.MAX_EMPTY_RETRIES + 1):
            try:
                parsed = await llm_client.generate_structured(request, _GenerationOutput)
            except (LLMInvalidResponseError, ValidationError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Structured validation failed (attempt %d/%d), "
                    "falling back to per-item validation: %s",
                    attempt + 1, self.MAX_EMPTY_RETRIES + 1, exc,
                )
                # Fix 4：降级到逐项校验
                try:
                    raw = await llm_client.generate(request)
                    raw_data = json.loads(raw.content)
                    extra_models = {
                        "foreshadowing_plans": _ForeshadowingPlan,
                        "reveal_plans": _RevealPlan,
                        "offscreen_progress": _OffscreenProgress,
                        "risks": _Risk,
                        "questions_for_user": _Question,
                    }
                    parsed = _per_item_validate(
                        raw_data, _GeneratedThread, _GeneratedArc, extra_models, _GenerationOutput,
                    )
                except Exception as inner_exc:
                    logger.warning("Per-item validation also failed: %s", inner_exc)
                    continue
            except Exception as exc:
                logger.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, self.MAX_EMPTY_RETRIES + 1, exc)
                continue

            # Fix 3：检查空结果（覆盖全部 section 字段，避免 extra_sections 被丢弃）
            has_content = (
                parsed.plot_threads or parsed.outline_arcs or
                parsed.foreshadowing_plans or parsed.reveal_plans or
                parsed.offscreen_progress or parsed.risks or parsed.questions_for_user
            )
            if has_content:
                result = parsed
                break

            logger.warning(
                "Empty LLM result (attempt %d/%d), retrying...",
                attempt + 1, self.MAX_EMPTY_RETRIES + 1,
            )
        else:
            logger.error("All %d generation attempts returned empty or failed", self.MAX_EMPTY_RETRIES + 1)
            return {
                "total_threads": 0, "total_arcs": 0,
                "threads": [], "arcs": [],
                "extra_sections": {},
                "warnings": ["LLM 多次返回空结果，请重试"],
            }

        # Fix 12：for-else 保证 result 非空；防御性检查防 python -O 跳过 assert
        if result is None:
            return {
                "total_threads": 0, "total_arcs": 0,
                "threads": [], "arcs": [],
                "extra_sections": {},
                "warnings": ["LLM 生成结果为空，请重试"],
            }

        # ============================================================
        # 6. 去重检查（Fix 6）
        # ============================================================
        existing_threads = await PlotThreadRepository().count_by_novel_and_range(
            db, nid, start_chapter, end_chapter,
        )
        existing_arcs = await OutlineArcRepository().count_by_novel_and_range(
            db, nid, start_chapter, end_chapter,
        )
        if existing_threads > 0 or existing_arcs > 0:
            msg = (
                f"章节 {start_chapter}-{end_chapter} 已有 "
                f"{existing_threads} 条剧情线、{existing_arcs} 个篇章纲"
            )
            logger.warning("Duplicate generation warning: %s", msg)
            warnings_list.append(msg)

        # ============================================================
        # 7. 持久化 PlotThread（Fix 2：名称→ID 映射）
        # ============================================================
        created_threads: list[dict] = []
        for t in result.plot_threads:
            if not t.name:
                continue

            # 映射名称到 UUID
            thread_char_ids = [
                character_name_to_id[n] for n in t.related_character_names
                if n in character_name_to_id
            ]
            thread_entity_ids = [
                entity_name_to_id[n] for n in t.related_entity_names
                if n in entity_name_to_id
            ]

            thread_data = PlotThreadCreate(
                name=t.name,
                thread_type=t.thread_type,
                summary=t.summary,
                visible_goal=t.visible_goal,
                hidden_truth=t.hidden_truth,
                start_chapter=t.start_chapter if t.start_chapter is not None else start_chapter,
                planned_payoff_chapter=t.planned_payoff_chapter,
                current_stage=t.current_stage,
                related_character_ids=thread_char_ids,
                related_entity_ids=thread_entity_ids,
                status="draft",
            )
            try:
                thread = await PlotThreadRepository().create(db, nid, thread_data)
                created_threads.append({
                    "id": str(thread.id), "name": thread.name,
                    "thread_type": thread.thread_type,
                })
            except Exception as exc:
                logger.warning("Failed to create thread '%s': %s", t.name, exc)

        # ============================================================
        # 8. 持久化 OutlineArc（Fix 5：名称→ID 映射）
        # ============================================================
        created_arcs: list[dict] = []

        thread_name_to_id: dict[str, str] = {}
        for t in created_threads:
            thread_name_to_id[t["name"]] = t["id"]

        for a in result.outline_arcs:
            if not a.title:
                continue

            arc_related_thread_ids = [
                thread_name_to_id[n] for n in a.related_thread_names
                if n in thread_name_to_id
            ]
            arc_related_char_ids = [
                character_name_to_id[n] for n in a.related_character_names
                if n in character_name_to_id
            ]
            arc_related_entity_ids = [
                entity_name_to_id[n] for n in a.related_entity_names
                if n in entity_name_to_id
            ]

            arc_data = OutlineArcCreate(
                title=a.title,
                arc_index=a.arc_index,
                start_chapter=a.start_chapter if a.start_chapter is not None else start_chapter,
                end_chapter=a.end_chapter if a.end_chapter is not None else end_chapter,
                arc_goal=a.arc_goal,
                core_conflict=a.core_conflict,
                main_opposition=a.main_opposition,
                entry_hook=a.entry_hook,
                midpoint_turn=a.midpoint_turn,
                climax=a.climax,
                result=a.result,
                next_hook=a.next_hook,
                related_thread_ids=arc_related_thread_ids,
                related_character_ids=arc_related_char_ids,
                related_entity_ids=arc_related_entity_ids,
                status="draft",
            )
            try:
                arc = await OutlineArcRepository().create(db, nid, arc_data)
                created_arcs.append({
                    "id": str(arc.id), "title": arc.title,
                    "arc_index": arc.arc_index,
                })
            except Exception as exc:
                logger.warning("Failed to create arc '%s': %s", a.title, exc)

        await db.flush()

        # ============================================================
        # 9. 构建返回（含 extra_sections, warnings）
        # ============================================================
        return {
            "total_threads": len(created_threads),
            "total_arcs": len(created_arcs),
            "threads": created_threads,
            "arcs": created_arcs,
            "extra_sections": {
                "foreshadowing_plans": [
                    p.model_dump() for p in result.foreshadowing_plans
                ],
                "reveal_plans": [
                    p.model_dump() for p in result.reveal_plans
                ],
                "offscreen_progress": [
                    p.model_dump() for p in result.offscreen_progress
                ],
                "risks": [
                    p.model_dump() for p in result.risks
                ],
                "questions_for_user": [
                    q.model_dump() for q in result.questions_for_user
                ],
            },
            "warnings": warnings_list,
        }

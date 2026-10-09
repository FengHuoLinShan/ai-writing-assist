"""新书开篇世界观骨架：一次结构化产出、条目级取舍与整体撤销。

``world.draft_opening_skeleton`` suggest 操作入队 World 自有任务
（``world_opening_skeleton``，root capability ``world.opening_skeleton``，
请求额度 6 次 = 1 次结构化生成 + 至多 2 次修复 + 知识审查及其返修）。
任务输出一个 pending 的 ``world_adoption_package.v2``：

- 覆盖世界前提与基调（concept 条目）、核心规则 2-4（world_core 的
  can/cannot/cost/failure/maintenance 约束写法）、主要地点 3-5、势力/组织
  2-4、关键人物 3-5（恰好一名主角）、历史/传说/秘密 1-3 与核心关系；
- 实体至多 20、关系至多 12，超出的生成条目按确定性顺序丢弃并记录；
- 组装前先读项目已有对象并与包内条目去重：同名（含别名）改为补充已有
  对象（fill_empty/existing_ref），近名改为向已有对象附加别名；包内近名
  合并为一个条目，关系端点重定向到保留条目；
- 带 hidden_truth 的条目一律 ``reveal_level="author_only"``：作者完整
  （author_full）上下文可见，读者/角色与 author_safe 上下文不可见。

整包撤销复用 ``applied_change_reversal`` 的"回执逆序回滚、作者已改动的
对象保留并说明原因"语义，只作用于携带 ``opening_skeleton`` 来源的已采用包。
"""

from __future__ import annotations

import asyncio
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.account.facade import current_account_id
from modules.evidence.contracts import REPAIR_INSTRUCTION_TEMPLATE
from modules.project.facade import (
    get_project_context,
    open_project_snapshot_llm_client,
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.llm_schemas import GeneratedOpeningSkeleton
from modules.world.models import CoreEntity
from modules.world.schemas import (
    OpeningSkeletonRef,
    WorldAdoptionPackageItem,
    WorldAdoptionPackageItemsUpdateRequest,
    WorldAdoptionPackagePayload,
    WorldAdoptionPackageSaveRequest,
    WorldOpeningSkeletonTaskRequest,
)
from modules.world.services.worldbuilding.applied_change_reversal import (
    reverse_applied_changes,
)

# 世界侧实体活动重标注桥与 focused 回滚共用同一处 core 导入，不新增棘轮流量。
from modules.world.services.worldbuilding.focused_adoption import (
    request_entity_activity_reannotation,
)
from modules.world.services.worldbuilding.knowledge_governance import (
    govern_world_output,
    serialize_governed_output,
)
from shared.utils import parse_uuid

OPENING_SKELETON_TASK_TYPE = "world_opening_skeleton"
OPENING_SKELETON_CAPABILITY = "world.opening_skeleton"

# 计划覆盖面：各类目目标条数与硬上限（schema 层已先做绝对上限校验）。
RULE_RANGE = (2, 4)
LOCATION_RANGE = (3, 5)
FACTION_RANGE = (2, 4)
CHARACTER_RANGE = (3, 5)
LORE_RANGE = (1, 3)
MAX_ENTITIES = 20
MAX_RELATIONS = 12

MAX_CATALOG_OBJECTS = 200
# 与 WorldEntityService.create 的同名冲突阈值一致（0.9）。
NEAR_NAME_THRESHOLD = 0.9

_TIMEOUT_SECONDS = 1800


@dataclass
class SkeletonAssemblyStats:
    """包装配回执：条目计数与被丢弃的生成条目名。"""

    created_entities: int = 0
    fill_existing: int = 0
    reference_existing: int = 0
    attached_aliases: int = 0
    relations: int = 0
    dropped_items: list[str] = field(default_factory=list)
    dropped_relations: int = 0


def normalized_name(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(str(value or "").split())).casefold()


def name_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None, normalized_name(left), normalized_name(right)
    ).ratio()


def active_alias_terms(content_json: dict | None) -> tuple[str, ...]:
    """与 focused_world_read 同口径的活跃别名文本。"""
    terms = []
    for alias in (content_json or {}).get("aliases") or []:
        if isinstance(alias, str):
            terms.append(alias)
        elif (
            isinstance(alias, dict)
            and alias.get("status")
            in {None, "active", "canonical", "confirmed", "published"}
            and not alias.get("rolled_back")
        ):
            terms.append(str(alias.get("alias") or ""))
    return tuple(term for term in terms if term)


@dataclass(frozen=True)
class ExistingObject:
    entity_id: str
    name: str
    entity_type: str
    summary: str | None
    public_info: str | None
    hidden_truth: str | None
    aliases: tuple[str, ...]


def _identity_terms(obj: ExistingObject) -> tuple[str, ...]:
    return (obj.name, *obj.aliases)


def _match_existing(
    name: str, catalog: list[ExistingObject]
) -> tuple[ExistingObject, float] | None:
    """同名/别名精确命中优先；其后全库近名（阈值同创建冲突 0.9）。"""
    target = normalized_name(name)
    if not target:
        return None
    for obj in catalog:
        for term in _identity_terms(obj):
            if normalized_name(term) == target:
                return obj, 1.0
    best: tuple[ExistingObject, float] | None = None
    for obj in catalog:
        for term in _identity_terms(obj):
            score = name_similarity(name, term)
            if score >= NEAR_NAME_THRESHOLD and (best is None or score > best[1]):
                best = (obj, score)
    return best


def _entity_item_key(kind: str, index: int) -> str:
    return f"entity-{kind}-{index:02d}"


def _source_refs(input_hash: str, task_ref: str, title: str) -> list[dict[str, Any]]:
    """骨架条目的来源是作者的选定方向与构想（author_decision）。"""
    return [
        {
            "source_type": "author_decision",
            "source_id": task_ref,
            "source_hash": input_hash,
            "quote": title[:200],
        }
    ]


def _entity_create_payload(
    *,
    entity_type: str,
    name: str,
    summary: str,
    public_info: str | None,
    hidden_truth: str | None,
    content_json: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "operation": "create",
        "entity": {
            "entity_type": entity_type,
            "name": name,
            "summary": summary,
            "public_info": public_info,
            "hidden_truth": hidden_truth,
            "content_json": content_json,
            "importance": 0.5,
            "importance_level": "normal",
            # 秘密/真相默认只对作者可见；author_full 上下文可见，
            # 读者/角色与 author_safe 上下文不可见。
            "reveal_level": "author_only" if (hidden_truth or "").strip() else "hinted",
            "status": "canonical",
        },
    }


def _dedupe_within_package(
    generated: GeneratedOpeningSkeleton,
) -> tuple[GeneratedOpeningSkeleton, list[str]]:
    """包内近名合并：后出现条目并入先出现条目，关系名同步重定向。"""
    dropped: list[str] = []
    rename: dict[str, str] = {}
    kept_names: dict[str, str] = {}

    def _register(name: str) -> tuple[str, bool]:
        """返回 (保留名, 是否保留条目)；并入近名时条目被丢弃。"""
        target = normalized_name(name)
        for known_key, canonical in kept_names.items():
            if known_key == target or name_similarity(name, canonical) >= (
                NEAR_NAME_THRESHOLD
            ):
                if known_key != target:
                    rename[target] = canonical
                    dropped.append(name)
                return canonical, False
        kept_names[target] = name
        return name, True

    rules = []
    for rule in generated.rules:
        _kept_name, kept = _register(rule.name)
        if kept:
            rules.append(rule)
    locations = [
        item for item in generated.locations if _register(item.name)[1]
    ]
    factions = [
        item for item in generated.factions if _register(item.name)[1]
    ]
    protagonist_name: str | None = None
    characters = []
    for item in generated.characters:
        canonical, kept = _register(item.name)
        if item.is_protagonist:
            # 主角条目并入近名对象时，主角标记跟随保留条目。
            protagonist_name = canonical
        if kept:
            characters.append(item)
    if protagonist_name is not None:
        characters = [
            item.model_copy(update={"is_protagonist": item.name == protagonist_name})
            for item in characters
        ]
    lore = [item for item in generated.lore if _register(item.name)[1]]

    def _redirect(name: str) -> str:
        return rename.get(normalized_name(name), name)

    relations = [
        item.model_copy(
            update={"source": _redirect(item.source), "target": _redirect(item.target)}
        )
        for item in generated.relations
        if _redirect(item.source) != _redirect(item.target)
    ]
    merged = generated.model_copy(
        update={
            "rules": rules,
            "locations": locations,
            "factions": factions,
            "characters": characters,
            "lore": lore,
            "relations": relations[:MAX_RELATIONS],
        }
    )
    return merged, dropped


def _rule_constraints(rule) -> dict[str, Any]:
    """world_core 约束写法：can/cannot/cost/failure/maintenance 原子。"""
    constraints = {
        "can": rule.can,
        "cannot": rule.cannot,
        "cost": rule.cost,
        "failure": rule.failure,
        "maintenance": rule.maintenance,
    }
    na = {key: value for key, value in (rule.na_reasons or {}).items() if value}
    if na:
        constraints["na_reasons"] = na
    return constraints


class OpeningSkeletonService:
    """Own the opening-skeleton task, package assembly, item triage and rollback."""

    # ---------- 已有对象目录 ----------

    async def existing_catalog(
        self, db: AsyncSession, novel_id: str
    ) -> list[ExistingObject]:
        rows = (
            (
                await db.execute(
                    select(CoreEntity)
                    .where(
                        CoreEntity.novel_id == parse_uuid(novel_id),
                        CoreEntity.status.in_(("canonical", "draft", "candidate")),
                    )
                    .order_by(CoreEntity.importance.desc(), CoreEntity.name.asc())
                    .limit(MAX_CATALOG_OBJECTS)
                )
            )
            .scalars()
            .all()
        )
        return [
            ExistingObject(
                entity_id=str(row.id),
                name=row.name or "",
                entity_type=row.entity_type,
                summary=row.summary,
                public_info=row.public_info,
                hidden_truth=row.hidden_truth,
                aliases=active_alias_terms(row.content_json),
            )
            for row in rows
        ]

    # ---------- 生成入队 ----------

    async def submit_task(
        self,
        db: AsyncSession,
        request: WorldOpeningSkeletonTaskRequest,
        *,
        llm_snapshot: dict[str, Any] | None,
        internal_meta: dict[str, Any] | None = None,
        operation_id: str | None = None,
    ) -> dict[str, str]:
        await self._require_owner(db, request.novel_id)
        from infrastructure.tasks.facade import (
            enqueue_task_with_optional_operation,
            get_operation_task,
        )

        payload = request.model_dump(mode="json", exclude={"operation_id"})
        identity = {"capability": OPENING_SKELETON_CAPABILITY, "arguments": payload}
        existing = await get_operation_task(
            db,
            operation_id=operation_id,
            task_type=OPENING_SKELETON_TASK_TYPE,
            novel_id=request.novel_id,
            request_payload=identity,
        )
        if existing is not None:
            return {
                "task_id": existing.task_id,
                "status": existing.status,
                "reused": "true",
            }
        if not llm_snapshot:
            raise ValidationError("骨架生成需要当前账户已验证的模型连接")
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=operation_id,
            task_type=OPENING_SKELETON_TASK_TYPE,
            novel_id=request.novel_id,
            request_payload=identity,
            meta={
                **payload,
                "llm_execution_snapshot": llm_snapshot,
                **(internal_meta or {}),
            },
        )
        await db.flush()
        return {"task_id": receipt.task_id, "status": receipt.status, "reused": "false"}

    # ---------- 任务执行 ----------

    async def generate_for_task(
        self,
        db: AsyncSession,
        novel_id: str,
        request: WorldOpeningSkeletonTaskRequest,
        *,
        llm_execution_snapshot: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        await require_active_project(db, novel_id)
        catalog = await self.existing_catalog(db, novel_id)
        model = str(llm_execution_snapshot["profile"]["model"])
        input_hash = stable_hash(
            {
                "vision": request.vision,
                "direction_title": request.direction_title,
                "direction": request.direction,
                "existing": [obj.entity_id for obj in catalog],
            }
        )
        author_block = self._author_input_block(request)
        rendered_context = "\n\n".join([author_block, self._catalog_block(catalog)])
        async with open_project_snapshot_llm_client(
            db, novel_id, llm_execution_snapshot
        ) as client:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                generated = await self._generate_structured(
                    client, request, catalog, model=model
                )
                generated, package_dropped = _dedupe_within_package(generated)
                generated, review = await self._govern(
                    client,
                    novel_id=novel_id,
                    author_block=author_block,
                    rendered_context=rendered_context,
                    generated=generated,
                    model=model,
                )
        package, stats = self.assemble_package(
            generated,
            catalog,
            input_hash=input_hash,
            task_id=task_id,
            direction_title=request.direction_title,
            knowledge_review=review or None,
        )
        stats.dropped_items = [*package_dropped, *stats.dropped_items]
        saved = await self._save_package(db, novel_id, package)
        return {
            "package_suggestion_id": saved.id,
            "knowledge_review_status": str(review.get("status") or "unknown"),
            "created_entities": stats.created_entities,
            "fill_existing": stats.fill_existing,
            "reference_existing": stats.reference_existing,
            "attached_aliases": stats.attached_aliases,
            "relations": stats.relations,
            "dropped_items": stats.dropped_items,
            "dropped_relations": stats.dropped_relations,
        }

    async def _generate_structured(
        self,
        client,
        request: WorldOpeningSkeletonTaskRequest,
        catalog: list[ExistingObject],
        *,
        model: str,
    ) -> GeneratedOpeningSkeleton:
        from infrastructure.llm.agent_step_harness import run_managed_structured
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=self._author_input_block(request)),
            LLMMessage(role="user", content=self._catalog_block(catalog)),
            LLMMessage(role="user", content=_OUTPUT_CONTRACT),
        ]
        llm_request = LLMCallRequest(model=model, messages=messages, temperature=0.4)
        return await run_managed_structured(
            client,
            llm_request,
            GeneratedOpeningSkeleton,
            step_name="world.opening_skeleton.structured",
            max_fix_attempts=2,
            timeout=_TIMEOUT_SECONDS,
        )

    async def _govern(
        self,
        client,
        *,
        novel_id: str,
        author_block: str,
        rendered_context: str,
        generated: GeneratedOpeningSkeleton,
        model: str,
    ) -> tuple[GeneratedOpeningSkeleton, dict[str, Any]]:
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
        from modules.world.schemas import WorldBibleSourceRef

        input_hash = stable_hash(rendered_context)
        source_refs = [
            WorldBibleSourceRef(
                source_type="author_messages",
                source_id="opening_skeleton",
                source_hash=input_hash,
                title="作者构想与选定方向",
            )
        ]
        request = LLMCallRequest(
            model=model,
            messages=[LLMMessage(role="user", content="<SKELETON_DRAFT />")],
        )
        holder: dict[str, Any] = {"output": generated}

        async def _repair(findings_block: str) -> str:
            repair_request = request.model_copy(deep=True)
            repair_request.messages.extend(
                [
                    LLMMessage(
                        role="assistant",
                        content=serialize_governed_output(holder["output"]),
                    ),
                    LLMMessage(
                        role="user",
                        content=REPAIR_INSTRUCTION_TEMPLATE.format(
                            findings_block=findings_block
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            "按作者构想与已有对象清单，重新输出完整骨架。覆盖面、"
                            "去重约束与作者语言要求不变；不得伪造来源或已有对象。"
                        ),
                    ),
                ]
            )
            holder["output"] = await run_managed_structured_repair(
                client, repair_request, model=model
            )
            return serialize_governed_output(holder["output"])

        result = await govern_world_output(
            client,
            capability=OPENING_SKELETON_CAPABILITY,
            novel_id=novel_id,
            source_refs=source_refs,
            rendered_context=rendered_context,
            output=serialize_governed_output(holder["output"]),
            task_instruction=(
                "为作者的新书开篇生成世界观骨架待审采用包；输出只作候选，"
                "不得声称已采用或已保存。"
            ),
            author_requirements=author_block,
            repair=_repair,
            step_prefix="world.opening_skeleton",
        )
        return holder["output"], dict(result.get("review") or {})

    # ---------- 确定性包装配（去重与上限） ----------

    def assemble_package(
        self,
        generated: GeneratedOpeningSkeleton,
        catalog: list[ExistingObject],
        *,
        input_hash: str,
        task_id: str,
        direction_title: str | None,
        knowledge_review: dict[str, Any] | None = None,
    ) -> tuple[WorldAdoptionPackagePayload, SkeletonAssemblyStats]:
        stats = SkeletonAssemblyStats()
        refs = _source_refs(input_hash, task_id, generated.premise_name)
        items: list[dict[str, Any]] = []
        entity_keys: dict[str, str] = {}
        package_names: dict[str, str] = {}

        def _register_key(name: str, key: str) -> None:
            normalized = normalized_name(name)
            entity_keys[normalized] = key
            package_names.setdefault(normalized, name)

        def _add_item(entry: dict[str, Any]) -> str:
            items.append(entry)
            return str(entry["item_key"])

        def _emit_new_entity(
            kind_label: str,
            index: int,
            name: str,
            entity_type: str,
            summary: str,
            public_info: str | None,
            hidden_truth: str | None,
            content_json: dict | None,
        ) -> None:
            created_count = sum(
                1 for key in entity_keys.values() if key.startswith("entity-")
            )
            if created_count >= MAX_ENTITIES:
                stats.dropped_items.append(name)
                return
            key = _entity_item_key(kind_label, index)
            _add_item(
                {
                    "item_key": key,
                    "kind": "core_entity",
                    "disposition": "include",
                    "authority_kind": "generated_bridge",
                    "source_refs": refs,
                    "payload": _entity_create_payload(
                        entity_type=entity_type,
                        name=name,
                        summary=summary,
                        public_info=public_info,
                        hidden_truth=hidden_truth,
                        content_json=content_json,
                    ),
                }
            )
            _register_key(name, key)
            stats.created_entities += 1

        def _emit_fill_or_ref(
            name: str,
            obj: ExistingObject,
            draft_summary: str,
            draft_public: str | None,
            draft_hidden: str | None,
        ) -> None:
            fields: dict[str, str] = {}
            for field_name, value in (
                ("summary", draft_summary),
                ("public_info", draft_public),
                ("hidden_truth", draft_hidden),
            ):
                if value and not (getattr(obj, field_name) or "").strip():
                    fields[field_name] = value
            key = f"entity-existing-{len(items):02d}"
            if fields:
                payload: dict[str, Any] = {
                    "operation": "fill_empty",
                    "entity_id": obj.entity_id,
                    "fields": fields,
                }
                stats.fill_existing += 1
            else:
                payload = {"operation": "existing_ref", "entity_id": obj.entity_id}
                stats.reference_existing += 1
            _add_item(
                {
                    "item_key": key,
                    "kind": "core_entity",
                    "disposition": "include",
                    "authority_kind": "generated_bridge",
                    "source_refs": refs,
                    "payload": payload,
                }
            )
            _register_key(name, key)

        def _emit_alias(name: str, obj: ExistingObject) -> None:
            key = _add_item(
                {
                    "item_key": f"alias-existing-{len(items):02d}",
                    "kind": "entity_alias",
                    "disposition": "include",
                    "authority_kind": "generated_bridge",
                    "source_refs": refs,
                    "payload": {
                        "entity_ref": obj.entity_id,
                        "alias": name,
                        "alias_kind": "name",
                        "alias_type": "alias",
                    },
                }
            )
            stats.attached_aliases += 1
            _register_key(name, key)

        def _place(
            kind_label: str,
            index: int,
            name: str,
            entity_type: str,
            summary: str,
            public_info: str | None,
            hidden_truth: str | None,
            content_json: dict | None,
        ) -> None:
            # 包内同名/近名合并到先出现的条目（生成路径已先经过
            # _dedupe_within_package；这里保证组装自身也是确定性的）。
            normalized = normalized_name(name)
            if normalized in entity_keys or any(
                name_similarity(name, known) >= NEAR_NAME_THRESHOLD
                for known in package_names.values()
            ):
                stats.dropped_items.append(name)
                return
            match = _match_existing(name, catalog)
            if match is not None and match[1] >= 1.0:
                # 同名：补充已有对象，不新建重复实体。
                _emit_fill_or_ref(name, match[0], summary, public_info, hidden_truth)
                return
            if match is not None:
                # 近名：别名只附着已有对象。
                _emit_alias(name, match[0])
                return
            _emit_new_entity(
                kind_label,
                index,
                name,
                entity_type,
                summary,
                public_info,
                hidden_truth,
                content_json,
            )

        # 世界前提与基调：一个 concept 条目承载。
        _place(
            "premise",
            0,
            generated.premise_name,
            "concept",
            generated.premise,
            None,
            None,
            {"details": {"tone": generated.tone}, "_meta_source": "opening_skeleton"},
        )
        for index, rule in enumerate(generated.rules):
            _place(
                "rule",
                index,
                rule.name,
                rule.entity_type,
                rule.summary,
                None,
                rule.hidden_truth,
                {"details": {"rule_constraints": _rule_constraints(rule)}},
            )
        for index, item in enumerate(generated.locations):
            _place(
                "location",
                index,
                item.name,
                item.entity_type,
                item.summary,
                item.public_info,
                item.hidden_truth,
                None,
            )
        for index, item in enumerate(generated.characters):
            content = (
                {"character_card": item.character_card} if item.character_card else None
            )
            _place(
                "character",
                index,
                item.name,
                "character",
                item.summary,
                item.public_info,
                item.hidden_truth,
                content,
            )
        for index, item in enumerate(generated.factions):
            _place(
                "faction",
                index,
                item.name,
                item.entity_type,
                item.summary,
                item.public_info,
                item.hidden_truth,
                None,
            )
        for index, item in enumerate(generated.lore):
            _place(
                "lore",
                index,
                item.name,
                item.entity_type,
                item.summary,
                item.public_info,
                item.hidden_truth,
                None,
            )

        # 关系：端点解析到包内条目或已有对象；两端都可用才保留。
        relation_count = 0
        for relation in generated.relations:
            if relation_count >= MAX_RELATIONS:
                stats.dropped_relations += 1
                continue

            def _endpoint_ref(name: str) -> str | None:
                key = entity_keys.get(normalized_name(name))
                if key is not None:
                    return f"local:{key}"
                match = _match_existing(name, catalog)
                if match is not None and match[1] >= 1.0:
                    return match[0].entity_id
                return None

            source_ref = _endpoint_ref(relation.source)
            target_ref = _endpoint_ref(relation.target)
            if not source_ref or not target_ref:
                stats.dropped_relations += 1
                continue
            items.append(
                {
                    "item_key": f"relation-{relation_count:02d}",
                    "kind": "entity_relation",
                    "disposition": "include",
                    "authority_kind": "generated_bridge",
                    "source_refs": refs,
                    "payload": {
                        "source_ref": source_ref,
                        "target_ref": target_ref,
                        "relation_type": relation.relation_type,
                        "relation_kind": relation.relation_kind,
                        "description": relation.description,
                    },
                }
            )
            relation_count += 1
        stats.relations = relation_count

        package = WorldAdoptionPackagePayload(
            schema_version="world_adoption_package.v2",
            source_manifest_hash=input_hash,
            items=items,
            opening_skeleton=OpeningSkeletonRef(
                task_id=task_id,
                input_hash=input_hash,
                direction_title=direction_title,
                created_at=datetime.now(UTC).isoformat(),
                dropped_items=stats.dropped_items[:32],
            ),
            knowledge_review=knowledge_review,
        )
        return package, stats

    # ---------- 条目级取舍与轻量编辑 ----------

    async def update_package_items(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
        request: WorldAdoptionPackageItemsUpdateRequest,
    ) -> tuple[Any, list[dict[str, Any]]]:
        from modules.world.models import CreationSuggestion
        from modules.world.services.worldbuilding.adoption_package_service import (
            WorldAdoptionPackageService,
        )

        await self._require_owner(db, novel_id)
        suggestion = await db.scalar(
            select(CreationSuggestion)
            .where(
                CreationSuggestion.id == parse_uuid(suggestion_id),
                CreationSuggestion.novel_id == parse_uuid(novel_id),
                CreationSuggestion.target_type == "world_adoption_package",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if suggestion is None or suggestion.status != "pending":
            raise ValidationError("骨架采用包不存在或已不在待确认状态")
        package = WorldAdoptionPackagePayload.model_validate(suggestion.payload_json)
        if package.opening_skeleton is None:
            raise ValidationError("只有新书开篇骨架包支持条目级取舍")
        if request.expected_updated_at is not None and suggestion.updated_at is not None:
            stored = suggestion.updated_at.replace(tzinfo=None)
            expected = request.expected_updated_at.replace(tzinfo=None)
            if stored != expected:
                raise ConflictError(
                    "骨架包已被其他编辑更新；请刷新后重试",
                    code="edit_baseline_stale",
                )

        by_key = {item.item_key: item for item in package.items}
        for update in request.items:
            item = by_key.get(update.item_key)
            if item is None:
                raise ValidationError(f"条目不存在：{update.item_key}")
            self._apply_item_update(item, update)

        self._reconcile_excluded_endpoints(package)
        conflicts = await self._item_conflicts(db, novel_id, package)

        updated = WorldAdoptionPackagePayload.model_validate(
            package.model_dump(mode="json")
        )
        suggestion.payload_json = updated.model_dump(mode="json")
        await db.flush()
        response = await WorldAdoptionPackageService().get(db, novel_id, suggestion_id)
        return response, conflicts

    def _apply_item_update(self, item: WorldAdoptionPackageItem, update) -> None:
        if update.included is True:
            item.disposition = "include"
            item.review_reasons = [
                reason for reason in item.review_reasons if reason != "author_excluded"
            ]
        elif update.included is False:
            item.disposition = "open"
            item.review_reasons = list(
                dict.fromkeys([*item.review_reasons, "author_excluded"])
            )
        content_fields = (
            update.name,
            update.summary,
            update.public_info,
            update.hidden_truth,
        )
        if item.kind != "core_entity":
            if any(value is not None for value in content_fields):
                raise ValidationError("只有对象条目支持改名或修改简介")
            return
        from modules.world.schemas import WorldAdoptionCoreEntityPayload

        payload = WorldAdoptionCoreEntityPayload.model_validate(item.payload)
        if payload.operation != "create":
            if any(value is not None for value in content_fields):
                raise ValidationError("补充已有对象的条目不支持内容编辑")
            return
        entity = dict(payload.entity or {})
        if update.name is not None:
            entity["name"] = update.name
        if update.summary is not None:
            entity["summary"] = update.summary
        if update.public_info is not None:
            entity["public_info"] = update.public_info
        if update.hidden_truth is not None:
            entity["hidden_truth"] = update.hidden_truth
        # 秘密/真相内容默认只对作者可见，如实固定可见层级。
        if (entity.get("hidden_truth") or "").strip():
            entity["reveal_level"] = "author_only"
        item.payload = {**item.payload, "entity": entity}

    def _reconcile_excluded_endpoints(self, package: WorldAdoptionPackagePayload) -> None:
        """端点被排除的关系/别名不可能再采用；自动转为待定并说明原因。"""
        excluded = {
            item.item_key
            for item in package.items
            if item.kind == "core_entity" and item.disposition != "include"
        }
        for item in package.items:
            if item.kind not in {"entity_relation", "entity_alias"}:
                continue
            refs = [
                str(item.payload.get(key) or "")[6:]
                for key in ("source_ref", "target_ref", "entity_ref")
                if str(item.payload.get(key) or "").startswith("local:")
            ]
            reasons = [
                reason for reason in item.review_reasons if reason != "endpoint_excluded"
            ]
            if any(ref in excluded for ref in refs):
                item.disposition = "open"
                reasons.append("endpoint_excluded")
            item.review_reasons = reasons

    async def _item_conflicts(
        self,
        db: AsyncSession,
        novel_id: str,
        package: WorldAdoptionPackagePayload,
    ) -> list[dict[str, Any]]:
        """逐条冲突：包内近名 + 与当前项目对象的同名（创建冲突按 0.9）。"""
        catalog = await self.existing_catalog(db, novel_id)
        included_names = {
            item.item_key: str((item.payload.get("entity") or {}).get("name") or "")
            for item in package.items
            if item.kind == "core_entity" and item.disposition == "include"
        }
        conflicts: list[dict[str, Any]] = []
        for item in package.items:
            entry: dict[str, Any] = {"item_key": item.item_key, "conflicts": []}
            if item.kind == "core_entity" and item.disposition == "include":
                name = included_names.get(item.item_key) or ""
                if name:
                    others = sorted(
                        other
                        for key, other in included_names.items()
                        if key != item.item_key
                        and name_similarity(name, other) >= NEAR_NAME_THRESHOLD
                    )
                    if others:
                        entry["conflicts"].append(
                            {"reason": "duplicate_name", "with": others[:5]}
                        )
                    match = _match_existing(name, catalog)
                    if match is not None and match[1] >= 1.0:
                        entry["conflicts"].append(
                            {"reason": "same_name_existing", "with": [match[0].name]}
                        )
            conflicts.append(entry)
        return conflicts

    # ---------- 整体撤销 ----------

    async def rollback_package(
        self, db: AsyncSession, novel_id: str, suggestion_id: str
    ) -> dict[str, Any]:
        from modules.world.models import CreationSuggestion
        from modules.world.services.worldbuilding.adoption_package_service import (
            WorldAdoptionPackageService,
        )

        await require_active_project_exclusive(db, novel_id)
        project = await get_project_context(db, novel_id)
        if not project or project.owner_id != str(current_account_id()):
            raise ValidationError("整体撤销需要当前项目所有者")
        suggestion = await db.scalar(
            select(CreationSuggestion)
            .where(
                CreationSuggestion.id == parse_uuid(suggestion_id),
                CreationSuggestion.novel_id == parse_uuid(novel_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            suggestion is None
            or suggestion.status != "accepted"
            or suggestion.target_type != "world_adoption_package"
            or (suggestion.payload_json or {}).get("opening_skeleton") is None
        ):
            raise ValidationError("没有可整体撤销的骨架采用包")
        receipt = dict(suggestion.result_ref_json or {})
        reversal = await reverse_applied_changes(
            db,
            novel_id,
            list(receipt.get("applied_changes") or []),
            modified_reason="modified_after_adoption",
            referenced_reason="referenced_by_author",
            revision_reason="opening_skeleton_rollback",
        )
        receipt["rollback"] = reversal.outcomes
        suggestion.result_ref_json = receipt
        await db.flush()
        if reversal.changed:
            await WorldAdoptionPackageService()._mark_context_changed(
                db, novel_id, reversal.changed
            )
            from modules.world.services.worldbuilding.synopsis_invalidation import (
                mark_synopsis_source_changed,
            )

            await request_entity_activity_reannotation(db, novel_id)
            await mark_synopsis_source_changed(
                db,
                novel_id,
                source_type="opening_skeleton_rollback",
                source_id=suggestion_id,
            )
        return {"suggestion_id": suggestion_id, "results": reversal.outcomes}

    # ---------- 内部 ----------

    async def _save_package(self, db: AsyncSession, novel_id: str, package):
        from modules.world.services.worldbuilding.adoption_package_service import (
            WorldAdoptionPackageService,
        )

        return await WorldAdoptionPackageService().save(
            db,
            WorldAdoptionPackageSaveRequest(novel_id=novel_id, package=package),
            source_module="world",
        )

    async def _require_owner(self, db: AsyncSession, novel_id: str) -> None:
        await require_active_project(db, novel_id)
        project = await get_project_context(db, novel_id)
        if not project or project.owner_id != str(current_account_id()):
            raise ValidationError("骨架生成需要当前项目所有者")

    @staticmethod
    def _author_input_block(request: WorldOpeningSkeletonTaskRequest) -> str:
        direction = request.direction or {}
        direction_lines = "\n".join(
            f"- {key}：{value}" for key, value in direction.items() if value.strip()
        )
        parts = ["<AUTHOR_VISION>", request.vision.strip()]
        if request.direction_title:
            parts.append(f"方向：{request.direction_title}")
        if direction_lines:
            parts.append("选定方向卡字段：\n" + direction_lines)
        parts.append("</AUTHOR_VISION>")
        return "\n".join(parts)

    @staticmethod
    def _catalog_block(catalog: list[ExistingObject]) -> str:
        if not catalog:
            return (
                "<EXISTING_WORLD_OBJECTS>\n（本项目尚无已有世界对象）\n"
                "</EXISTING_WORLD_OBJECTS>"
            )
        lines = []
        for obj in catalog:
            aliases = "、".join(obj.aliases[:4])
            summary = (obj.summary or "").strip()[:120]
            lines.append(
                f"- {obj.name}（类型 {obj.entity_type}）"
                + (f" 别名：{aliases}" if aliases else "")
                + (f"：{summary}" if summary else "")
            )
        return (
            "<EXISTING_WORLD_OBJECTS>\n以下是项目已有对象。与它们同名或近名的构想"
            "必须复用这些对象（补充其空缺信息或作为其别名），不得生成重复实体：\n"
            + "\n".join(lines)
            + "\n</EXISTING_WORLD_OBJECTS>"
        )


async def run_managed_structured_repair(client, request, *, model: str):
    from infrastructure.llm.agent_step_harness import run_managed_structured

    return await run_managed_structured(
        client,
        request,
        GeneratedOpeningSkeleton,
        step_name="world.opening_skeleton.knowledge.repair",
        max_fix_attempts=2,
        timeout=_TIMEOUT_SECONDS,
    )


_OUTPUT_CONTRACT = (
    "<OUTPUT_CONTRACT>\n"
    "覆盖面（条数为硬性范围）：世界前提与基调 1（concept 条目）；"
    f"核心规则或力量体系 {RULE_RANGE[0]}-{RULE_RANGE[1]}；"
    f"主要地点 {LOCATION_RANGE[0]}-{LOCATION_RANGE[1]}；"
    f"势力/组织 {FACTION_RANGE[0]}-{FACTION_RANGE[1]}；"
    f"关键人物 {CHARACTER_RANGE[0]}-{CHARACTER_RANGE[1]}"
    "（恰好 1 名 is_protagonist=true 的主角）；"
    f"历史/传说/秘密 {LORE_RANGE[0]}-{LORE_RANGE[1]}；"
    f"核心关系至多 {MAX_RELATIONS} 条。实体总数至多 {MAX_ENTITIES}。"
    "直接输出一个匹配本次对话 schema 的 JSON 对象；不要添加外层包装。\n"
    "</OUTPUT_CONTRACT>"
)


_SYSTEM_PROMPT = """\
你是小说开篇的世界观设定编辑。作者给出一句到一段话的构想（可能附带选定的方向卡
字段），你一次产出这本书可以直接开始创作的较完整世界观骨架待审采用包。

硬性要求：
- 使用作者语言：名称与简介面向作者阅读，不出现 ID、JSON、协议字段或数据库概念。
- 世界前提与基调用一个 concept 条目承载：它说明这个世界的核心差异、日常质感
  与叙事基调，让读者翻开第一章就能感到它。
- 核心规则/力量体系沿用约束写法：每条必须说清 can（能做什么）、cannot（不能
  做什么）、cost（代价）、failure（失效/失控形态）、maintenance（维持条件）；
  某一项确实不适用时在 na_reasons 说明理由，不要编造。
- 主要地点是能发生场景的地方；势力/组织是有集体行动能力的群体；关键人物包含
  恰好一名主角（is_protagonist=true），人物条目聚焦可推动剧情的动机与处境。
- 历史/传说/秘密条目只写真正有叙事价值的隐层；隐藏层内容写进 hidden_truth，
  默认只有作者可见，读者与角色上下文不会看到。
- 关系只保留能推动开篇冲突或悬念的核心关系，两端必须引用本次输出中的条目名
  或已有对象名。
- 与已有世界对象同名或近名的构想必须复用已有对象：改为补充其空缺信息或作为
  其别名，不得新建重复实体；包内彼此近名的条目合并为一个。
- 不要为了填满数量而注水；每一条都应能改变人物的选择。未知与悬念可以保留。
- 输出尚未采用：不得声称任何条目已被保存、采用或发布。
"""

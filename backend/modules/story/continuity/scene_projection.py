"""Scene-anchored deterministic memory projections and manual repair workflow."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.story.continuity.basis import compute_scene_basis
from modules.story.continuity.contracts import (
    CURRENT_SCENE_MEMORY_CONTRACT_VERSION,
    SCENE_MEMORY_DIMENSIONS,
    SCENE_MEMORY_DIMENSIONS_V1,
)
from modules.story.continuity.field_provenance import (
    FIELD_PROVENANCE_STATE_KEY,
    FieldProvenance,
    ProvenanceSourceRef,
    motif_fields_for_dimension,
    read_field_provenance,
)
from modules.story.continuity.knowledge_contract import read_knowledge_statement
from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.continuity.repositories import (
    EventRepository,
    SceneCheckpointRepository,
    SceneSnapshotRepository,
)
from modules.story.continuity.schemas import (
    SceneCheckpointRepairRequest,
    SceneCheckpointRepairResponse,
    SceneCheckpointResponse,
    SceneCheckpointSetResponse,
)
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import list_manuscript_sources
from shared.utils import parse_uuid

_AUTO_RETRY_LIMIT = 2
_SPARSE_SNAPSHOT_INTERVAL = 10
# recorded_at_sequence 组装步长：单 Scene 事件量上限 500（services 上限 +
# append_confirmed 封顶），512 保证 (scene_index, Scene 内序) 合成整数跨
# Scene 严格单调，链裁决按叙事顺序「后者胜」而不是各 Scene 内序互相打平。
_PROVENANCE_SEQUENCE_STRIDE = 512


class _CoverageGapError(Exception):
    def __init__(self, message: str, *, coverage: dict[str, int]) -> None:
        super().__init__(message)
        self.coverage = coverage


def _annotate_knowledge_dialect(state_json: dict[str, Any] | None) -> dict[str, Any]:
    """knowledge checkpoint ``state_json`` 副本逐条附 ``knowledge_class`` 标注。

    P2-B 历史回开的方言分类（B1 契约）：每条知识条目经
    ``read_knowledge_statement`` 容错读入后把三分类（known / unknown /
    false_belief）追加到响应副本上——分类按**该历史行自身 payload** 判定，
    不被当前 Canon head 或投影重建洗掉；误信历史行仍标 false_belief。
    原条目键全保留（只增不删）；无 holder/非法形态的条目原样保留不标注。
    深拷贝后追加，不污染 ORM 行载荷。
    """
    state = deepcopy(state_json or {})
    entries = state.get("character_knowledge")
    if not isinstance(entries, list):
        return state
    annotated: list[Any] = []
    for payload in entries:
        if isinstance(payload, dict):
            statement = read_knowledge_statement(payload)
            if statement is not None:
                payload = {**payload, "knowledge_class": statement.knowledge_class.value}
        annotated.append(payload)
    state["character_knowledge"] = annotated
    return state


class SceneMemoryProjectionService:
    """Own the Scene timeline; never reads today's World as a historical fallback."""

    def __init__(
        self,
        event_repo: EventRepository | None = None,
        checkpoint_repo: SceneCheckpointRepository | None = None,
        snapshot_repo: SceneSnapshotRepository | None = None,
    ) -> None:
        self._events = event_repo or EventRepository()
        self._checkpoints = checkpoint_repo or SceneCheckpointRepository()
        self._snapshots = snapshot_repo or SceneSnapshotRepository()

    async def ensure_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> SceneCheckpointSetResponse:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self._ordered_scenes(db, novel_id)
        target = next((item for item in scenes if str(item["id"]) == scene_id), None)
        if target is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        await self._reconcile_event_order(db, nid, scenes)
        allowed_scene_ids = self._scene_ids(scenes)
        await self._snapshots.ensure_stage0(
            db,
            nid,
            self._empty_full_state(),
            self._hash(self._empty_full_state()),
        )
        for position, scene in enumerate(scenes):
            if int(scene["scene_index"]) > int(target["scene_index"]):
                break
            previous_scene = scenes[position - 1] if position > 0 else None
            basis = await compute_scene_basis(
                db,
                novel_id,
                scenes,
                up_to_scene_index=int(scene["scene_index"]),
            )
            for dimension in SCENE_MEMORY_DIMENSIONS:
                checkpoint = await self._build_dimension(
                    db,
                    novel_id,
                    scene,
                    dimension,
                    previous_scene=previous_scene,
                    allowed_scene_ids=allowed_scene_ids,
                    basis=basis,
                )
                retries = 0
                while (
                    checkpoint.status == "retry_pending" and retries < _AUTO_RETRY_LIMIT
                ):
                    checkpoint = await self._build_dimension(
                        db,
                        novel_id,
                        scene,
                        dimension,
                        previous_scene=previous_scene,
                        allowed_scene_ids=allowed_scene_ids,
                        basis=basis,
                    )
                    retries += 1
            await self._capture_sparse_if_needed(db, nid, scenes, scene)
        return await self.get_scene(db, novel_id, scene_id, scenes=scenes)

    async def rebuild_from_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        from_scene_id: str | None,
        dimensions: list[str],
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self._ordered_scenes(db, novel_id)
        await self._reconcile_event_order(db, nid, scenes)
        allowed_scene_ids = self._scene_ids(scenes)
        start_index = 0
        if from_scene_id:
            source = next(
                (item for item in scenes if str(item["id"]) == from_scene_id), None
            )
            if source is None:
                raise NotFoundError("Scene not found", code="scene_not_found")
            start_index = int(source["scene_index"])
        await self._checkpoints.supersede_system_from(
            db,
            nid,
            start_index,
            dimensions,
            include_start=True,
        )
        await self._snapshots.supersede_from(
            db,
            nid,
            start_index,
            include_start=True,
        )
        rebuilt = 0
        for position, scene in enumerate(scenes):
            if int(scene["scene_index"]) < start_index:
                continue
            previous_scene = scenes[position - 1] if position > 0 else None
            basis = await compute_scene_basis(
                db,
                novel_id,
                scenes,
                up_to_scene_index=int(scene["scene_index"]),
            )
            for dimension in dimensions:
                await self._build_dimension(
                    db,
                    novel_id,
                    scene,
                    dimension,
                    previous_scene=previous_scene,
                    allowed_scene_ids=allowed_scene_ids,
                    basis=basis,
                )
            await self._capture_sparse_if_needed(db, nid, scenes, scene)
            rebuilt += 1
        return {
            "from_scene_id": from_scene_id,
            "dimensions": dimensions,
            "rebuilt_scene_count": rebuilt,
        }

    async def get_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        *,
        scenes: list[dict[str, Any]] | None = None,
    ) -> SceneCheckpointSetResponse:
        nid = parse_uuid(novel_id, "novel_id")
        ordered = scenes or await self._ordered_scenes(db, novel_id)
        scene = next((item for item in ordered if str(item["id"]) == scene_id), None)
        if scene is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        rows = await self._checkpoints.list_current_for_scene(
            db, nid, parse_uuid(scene_id, "scene_id")
        )
        by_dimension = {item.dimension: item for item in rows}
        missing = [
            dimension
            for dimension in SCENE_MEMORY_DIMENSIONS
            if dimension not in by_dimension
            or by_dimension[dimension].status == "missing"
        ]
        statuses = {item.status for item in rows}
        if missing:
            coverage_status = "missing"
        elif "manual_required" in statuses:
            coverage_status = "manual_required"
        elif "retry_pending" in statuses:
            coverage_status = "retry_pending"
        elif statuses == {"ready"}:
            coverage_status = "ready"
        else:
            coverage_status = "gap"
        return SceneCheckpointSetResponse(
            novel_id=novel_id,
            scene_id=scene_id,
            scene_index=int(scene["scene_index"]),
            stage_index=int(scene["scene_index"]) + 1,
            scene_title=scene.get("title"),
            coverage_status=coverage_status,
            contract_version=CURRENT_SCENE_MEMORY_CONTRACT_VERSION,
            required_dimensions=list(SCENE_MEMORY_DIMENSIONS),
            items=[SceneCheckpointResponse.model_validate(item) for item in rows],
            missing_dimensions=missing,
        )

    async def get_record(
        self, db: AsyncSession, novel_id: str, checkpoint_id: str
    ) -> SceneCheckpointResponse:
        row = await self._checkpoints.get_by_id(
            db,
            parse_uuid(novel_id, "novel_id"),
            parse_uuid(checkpoint_id, "checkpoint_id"),
        )
        if row is None:
            raise NotFoundError("状态依据不存在", code="checkpoint_not_found")
        response = SceneCheckpointResponse.model_validate(row)
        # P2-A 历史回开：暴露构建当时内嵌在该行 state_json 里的逐字段来源，
        # 不与当前 Canon head 重算混合；旧格式行为空列表。聚合逻辑住在
        # scene_state_view（读取端；本模块被其顶层导入，函数内导入避免顶层环）。
        from modules.story.continuity.scene_state_view import summarize_field_provenance

        summaries = summarize_field_provenance(row.state_json, row.dimension)
        response.field_provenance = [
            summaries[key] | {"subject": key[1]}
            for key in sorted(summaries, key=lambda item: (item[0], item[1] or ""))
        ]
        # P2-B 历史回开：knowledge 维度行补方言分类标注。get_record 是作者
        # 诊断端点（无 viewpoint 参数、raw 原文回开），故保留 raw 只追加
        # ``knowledge_class`` 派生标注；面向角色/读者的视角过滤在
        # scene_state_view.get_view 的视角边界完成，不经本端点。
        if row.dimension == "knowledge":
            response.state_json = _annotate_knowledge_dialect(row.state_json)
        return response

    async def repair(
        self,
        db: AsyncSession,
        novel_id: str,
        request: SceneCheckpointRepairRequest,
    ) -> SceneCheckpointRepairResponse:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(request.scene_id, "scene_id")
        scenes = await self._ordered_scenes(db, novel_id)
        await self._reconcile_event_order(db, nid, scenes)
        allowed_scene_ids = self._scene_ids(scenes)
        scene = next(
            (item for item in scenes if str(item["id"]) == request.scene_id), None
        )
        if scene is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        current = await self._checkpoints.lock_current(
            db,
            nid,
            sid,
            request.dimension,
        )
        if current is None:
            raise NotFoundError("Checkpoint not found", code="checkpoint_not_found")
        if str(current.id) != request.expected_checkpoint_id:
            raise ConflictError(
                "Checkpoint changed; reload the latest facts before deciding",
                code="checkpoint_version_conflict",
            )
        if current.source != "system_generated" or current.confirmed:
            raise ConflictError(
                "Manual or confirmed checkpoint is preserved",
                code="checkpoint_protected",
            )
        state = self._manual_state(current, request)
        summary = self._manual_display_summary(request, state)
        repaired = await self._checkpoints.create_manual_repair(
            db,
            current=current,
            state_json=state,
            evidence_refs=list(current.evidence_refs or []),
            display_summary=summary,
            source_hash=self._hash(
                {
                    "state": state,
                    "decision": request.decision,
                    "decision_summary": request.decision_summary,
                }
            ),
            decision_summary=request.decision_summary,
        )
        await self._checkpoints.supersede_system_from(
            db,
            nid,
            int(scene["scene_index"]),
            [request.dimension],
            include_start=False,
        )
        await self._snapshots.supersede_from(
            db,
            nid,
            int(scene["scene_index"]),
            include_start=True,
        )
        await self._capture_sparse_if_needed(db, nid, scenes, scene)
        rebuilt = 0
        for position, downstream in enumerate(scenes):
            if int(downstream["scene_index"]) <= int(scene["scene_index"]):
                continue
            basis = await compute_scene_basis(
                db,
                novel_id,
                scenes,
                up_to_scene_index=int(downstream["scene_index"]),
            )
            await self._build_dimension(
                db,
                novel_id,
                downstream,
                request.dimension,
                previous_scene=scenes[position - 1] if position > 0 else None,
                allowed_scene_ids=allowed_scene_ids,
                basis=basis,
            )
            await self._capture_sparse_if_needed(db, nid, scenes, downstream)
            rebuilt += 1
        return SceneCheckpointRepairResponse(
            scene_id=request.scene_id,
            dimension=request.dimension,
            rebuilt_scene_count=rebuilt,
            checkpoint=SceneCheckpointResponse.model_validate(repaired),
        )

    async def _build_dimension(
        self,
        db: AsyncSession,
        novel_id: str,
        scene: dict[str, Any],
        dimension: str,
        *,
        previous_scene: dict[str, Any] | None,
        allowed_scene_ids: list[uuid.UUID],
        basis: dict[str, Any] | None = None,
    ) -> MemorySceneCheckpoint:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(str(scene["id"]), "scene_id")
        scene_index = int(scene["scene_index"])
        current = await self._checkpoints.get_current(db, nid, sid, dimension)
        if current is not None and (
            current.source != "system_generated" or current.confirmed
        ):
            # Stage coordinates are derived from the live outline ordering.  Keep
            # the protected author decision, but do not let stale coordinates
            # make it appear before a Scene that now precedes it.
            if current.scene_index != scene_index:
                current.scene_index = scene_index
                current.stage_index = scene_index + 1
                await db.flush()
            return current
        previous = None
        previous_scene_index = None
        if previous_scene is not None:
            previous_scene_index = int(previous_scene["scene_index"])
            candidate = await self._checkpoints.get_current(
                db,
                nid,
                parse_uuid(str(previous_scene["id"]), "scene_id"),
                dimension,
            )
            if candidate is not None and candidate.status == "ready":
                previous = candidate
        try:
            state, refs = await self._project_dimension(
                db,
                novel_id,
                scene,
                dimension,
                previous,
                previous_scene_index=previous_scene_index,
                allowed_scene_ids=allowed_scene_ids,
            )
            source_hash = self._hash(
                {
                    "previous": previous.source_hash if previous else "stage0",
                    "state": state,
                    "refs": refs,
                }
            )
            projected_status = (
                "missing"
                if dimension not in SCENE_MEMORY_DIMENSIONS_V1
                and previous is None
                and not refs
                else "ready"
            )
            if (
                current is not None
                and current.status == projected_status
                and current.scene_index == scene_index
                and current.source_hash == source_hash
            ):
                # 只补旧行未登记的基线；漂移基线不能被原事件重放洗成新鲜。
                if current.basis_json is None:
                    current.basis_json = basis
                    await db.flush()
                return current
            return await self._checkpoints.replace_system(
                db,
                novel_id=nid,
                scene_id=sid,
                scene_index=scene_index,
                dimension=dimension,
                values={
                    "status": projected_status,
                    "confirmed": False,
                    "is_current": True,
                    "state_json": state,
                    "evidence_refs": refs,
                    "display_summary": self._display_summary(dimension, state),
                    "source_hash": source_hash,
                    "basis_json": basis,
                    "retry_count": 0,
                },
            )
        except _CoverageGapError as exc:
            retry_count = int(current.retry_count if current else 0) + 1
            status = (
                "manual_required" if retry_count > _AUTO_RETRY_LIMIT else "retry_pending"
            )
            base_state = deepcopy(
                previous.state_json if previous else self._empty_dimension(dimension)
            )
            base_state.setdefault("_coverage", {}).update(exc.coverage)
            return await self._checkpoints.replace_system(
                db,
                novel_id=nid,
                scene_id=sid,
                scene_index=scene_index,
                dimension=dimension,
                values={
                    "status": status,
                    "confirmed": False,
                    "is_current": True,
                    "state_json": base_state,
                    "evidence_refs": list(previous.evidence_refs or [])
                    if previous
                    else [],
                    "display_summary": self._display_summary(dimension, base_state),
                    "source_hash": self._hash(
                        {"gap": str(exc), "retry_count": retry_count}
                    ),
                    "gap_reason": str(exc),
                    "retry_count": retry_count,
                },
            )

    async def _project_dimension(
        self,
        db: AsyncSession,
        novel_id: str,
        scene: dict[str, Any],
        dimension: str,
        previous: MemorySceneCheckpoint | None,
        *,
        previous_scene_index: int | None,
        allowed_scene_ids: list[uuid.UUID],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        scene_index = int(scene["scene_index"])
        after_scene_index = previous_scene_index if previous else None
        state = deepcopy(
            previous.state_json if previous else self._empty_dimension(dimension)
        )
        # 保留继承链，避免每个场景重复复制全部历史事件引用。
        refs: list[dict[str, Any]] = (
            [
                {
                    "type": "scene_checkpoint",
                    "id": str(previous.id),
                    "label": "此前场景状态",
                }
            ]
            if previous
            else []
        )
        max_chapter = max(self._chapter_indices(scene) or [0])
        unanchored = await self._events.count_unanchored_through_chapter(
            db, parse_uuid(novel_id, "novel_id"), max_chapter
        )
        confirmed_coverage = (
            previous.state_json.get("_coverage_confirmed") or {} if previous else {}
        )
        covered_unanchored = int(
            confirmed_coverage.get("unanchored_memory_event_count", 0)
        )
        if unanchored > covered_unanchored:
            missing_count = unanchored - covered_unanchored
            raise _CoverageGapError(
                f"{missing_count} 条记忆事件只有章节锚点，无法确定所属 Scene",
                coverage={"unanchored_memory_event_count": unanchored},
            )
        events = await self._events.get_through_scene(
            db,
            parse_uuid(novel_id, "novel_id"),
            scene_index,
            dimension=dimension,
            after_scene_index=after_scene_index,
            allowed_scene_ids=allowed_scene_ids,
        )
        # 逐字段赋值链（P2-A）：previous 的 ``_field_provenance`` 已随
        # deepcopy 继承进 state，这里校验归一并追加本场新赋值；无链字段
        # 不写键（旧格式语义：缺键 = 来源待核实，不冒充）。
        provenance = read_field_provenance(state)
        chapter_sources: dict[int, tuple[ProvenanceSourceRef, ...]] = {}
        for event in events:
            self._apply_event(state, dimension, event)
            refs.append(
                {
                    "type": "memory_event",
                    "id": str(event.id),
                    "label": self._event_label(event),
                }
            )
            assigned = self._assigned_motif_fields(state, dimension, event)
            if not assigned:
                continue
            source_refs = await self._event_source_refs(
                db, novel_id, event, chapter_sources
            )
            for field_key, subject_ref in assigned:
                provenance.append(
                    FieldProvenance(
                        field_key=field_key,
                        dimension=dimension,
                        event_id=str(event.id),
                        subject_ref=subject_ref,
                        source_refs=source_refs,
                        version=source_refs[0].version_number if source_refs else 0,
                        recorded_at_sequence=self._provenance_sequence(event),
                    )
                )
        if provenance:
            state[FIELD_PROVENANCE_STATE_KEY] = [
                record.model_dump(mode="json") for record in provenance
            ]
        return state, refs

    # ── 逐字段赋值链（P2-A 写入端，契约见 field_provenance）──

    @staticmethod
    def _assigned_motif_fields(
        state: dict[str, Any], dimension: str, event: Any
    ) -> tuple[tuple[str, str | None], ...]:
        """本次事件实际落入核心状态的受控母题字段 ``(field_key, subject_ref)`` 对。

        只认 reducer 的核心状态落点（entities / character_locations / facts）：
        进观察层 ``changes`` 的负载（manual_correction、未知实体的
        entity_updated 等）不算赋值，不挂链。判定 = 事件路由到达核心容器
        且注册字段的值与负载一致（重复断言同值也算一次赋值——该事件
        就是当前值的最后陈述）。subject_ref 为实体锚（entities/locations
        维度为实体 ID，timeline 无实体容器为 None）——同维度多实体的
        同名字段靠它隔离裁决链。
        """
        registered = motif_fields_for_dimension(dimension)
        if not registered:
            return ()
        payload = event.snapshot_after
        if not isinstance(payload, dict):
            return ()
        event_type = str(event.event_type)
        if dimension == "timeline":
            # timeline 每条事件都追加为 fact；以最后一条 fact 为落点。
            facts = state.get("facts")
            landed = facts[-1] if isinstance(facts, list) and facts else None
            subject_ref = None
        else:
            entity_id = str(event.entity_id) if event.entity_id else None
            if not entity_id:
                return ()
            subject_ref = entity_id
            if dimension == "entities":
                entities = state.get("entities") or {}
                if event_type in ("entity_created", "entity_updated"):
                    # 未知实体的更新进观察层不算核心赋值（reducer 同口径），
                    # get() 自然返回 None。
                    landed = entities.get(entity_id)
                else:
                    return ()
            elif dimension == "locations":
                if event_type != "entity_moved":
                    return ()
                landed = (state.get("character_locations") or {}).get(entity_id)
            else:
                return ()
        if not isinstance(landed, dict):
            return ()
        return tuple(
            (item.field_key, subject_ref)
            for item in registered
            if item.field_key in payload
            and landed.get(item.field_key) == payload[item.field_key]
        )

    @staticmethod
    def _provenance_sequence(event: Any) -> int:
        """赋值事件序（A1 契约单 int）：scene_index 为主位，Scene 内序为次位。

        Scene 内优先事件 ``scene_sequence``；无 Scene 锚（历史章路径行）回退
        章内 ``sequence`` 充当次位，主位仍取 ``scene_index``，保证跨 Scene
        严格单调。
        """
        slot = event.scene_sequence
        if slot is None:
            slot = event.sequence
        return int(event.scene_index or 0) * _PROVENANCE_SEQUENCE_STRIDE + int(slot or 0)

    @staticmethod
    async def _event_source_refs(
        db: AsyncSession,
        novel_id: str,
        event: Any,
        cache: dict[int, tuple[ProvenanceSourceRef, ...]],
    ) -> tuple[ProvenanceSourceRef, ...]:
        """事件赋值的稿源区间：事件所属章最新 working 稿的整章区间。

        scene memory 事件链派生自 working 稿（basis.py 同口径）；抽取侧
        当前不记录更细区间，整章即诚实的最大锚。该章无 working 稿或稿为
        空 → 空区间（unverified 语义），禁止拿别章/整场事件冒充。
        """
        chapter_index = int(event.chapter_index)
        if chapter_index not in cache:
            cache[chapter_index] = await SceneMemoryProjectionService._working_refs(
                db, novel_id, chapter_index
            )
        return cache[chapter_index]

    @staticmethod
    async def _working_refs(
        db: AsyncSession, novel_id: str, chapter_index: int
    ) -> tuple[ProvenanceSourceRef, ...]:
        if chapter_index < 1:
            return ()
        sources = await list_manuscript_sources(
            db, novel_id, [chapter_index], content_mode="working"
        )
        candidates = [
            item for item in sources if int(item.chapter_index) == chapter_index
        ]
        if not candidates:
            return ()
        # 同章并列最新版本时按 (version, id) 确定性取一，避免重建换锚漂移。
        source = max(
            candidates, key=lambda item: (int(item.version_number), str(item.id))
        )
        content = source.content or ""
        # list_manuscript_sources 的契约层已保证 content_hash 非空
        # （draft.content_hash or hash_text(content)）；仍缺视为无可锚区间。
        if not source.id or not content or not source.content_hash:
            return ()
        text_hash = source.content_hash
        contract = SourceRangeRefContract(
            draft_id=str(source.id),
            chapter_index=chapter_index,
            version_number=int(source.version_number),
            content_mode="working",
            start_offset=0,
            end_offset=len(content),
            source_hash=text_hash,
            range_hash=text_hash,
        )
        return (ProvenanceSourceRef.from_source_range_contract(contract),)

    async def _capture_sparse_if_needed(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scenes: list[dict[str, Any]],
        scene: dict[str, Any],
    ) -> None:
        scene_index = int(scene["scene_index"])
        reasons: list[str] = []
        if (scene_index + 1) % _SPARSE_SNAPSHOT_INTERVAL == 0:
            reasons.append("periodic")
        position = next(i for i, item in enumerate(scenes) if item["id"] == scene["id"])
        next_scene = scenes[position + 1] if position + 1 < len(scenes) else None
        current_chapters = self._chapter_indices(scene)
        next_chapters = self._chapter_indices(next_scene) if next_scene else []
        if current_chapters and (
            not next_chapters or max(current_chapters) < min(next_chapters)
        ):
            reasons.append("chapter_end")
        is_latest = position == len(scenes) - 1
        if is_latest:
            reasons.append("latest")
        if not reasons:
            return
        rows = await self._checkpoints.list_current_for_scene(
            db, novel_id, parse_uuid(str(scene["id"]), "scene_id")
        )
        by_dimension = {item.dimension: item for item in rows}
        if any(
            dimension not in by_dimension or by_dimension[dimension].status != "ready"
            for dimension in SCENE_MEMORY_DIMENSIONS
        ):
            return
        full_state = {
            dimension: deepcopy(by_dimension[dimension].state_json)
            for dimension in SCENE_MEMORY_DIMENSIONS
        }
        await self._snapshots.replace_for_scene(
            db,
            novel_id=novel_id,
            scene_id=parse_uuid(str(scene["id"]), "scene_id"),
            scene_index=scene_index,
            reasons=list(dict.fromkeys(reasons)),
            full_state=full_state,
            source_hash=self._hash(full_state),
            is_latest=is_latest,
        )

    @staticmethod
    def _apply_event(state: dict[str, Any], dimension: str, event: Any) -> None:
        from modules.story.continuity.reducer import StoryStateReducer

        StoryStateReducer.apply_scene_dimension_event(state, dimension, event)

    @staticmethod
    def _manual_state(
        current: MemorySceneCheckpoint,
        request: SceneCheckpointRepairRequest,
    ) -> dict[str, Any]:
        current_state = deepcopy(current.state_json or {})
        confirmed_coverage = dict(current_state.get("_coverage_confirmed") or {})
        for key, value in (current_state.get("_coverage") or {}).items():
            confirmed_coverage[key] = max(
                int(confirmed_coverage.get(key, 0) or 0),
                int(value or 0),
            )
        if request.decision == "keep_current":
            state = current_state
            if confirmed_coverage:
                state["_coverage_confirmed"] = confirmed_coverage
            return state
        if request.decision == "confirm_empty":
            state = SceneMemoryProjectionService._empty_dimension(current.dimension)
            if confirmed_coverage:
                state["_coverage_confirmed"] = confirmed_coverage
            return state
        if not (request.replacement_summary or "").strip():
            raise ValidationError("请填写正确内容", code="replacement_summary_required")
        state = SceneMemoryProjectionService._empty_dimension(current.dimension)
        if confirmed_coverage:
            state["_coverage_confirmed"] = confirmed_coverage
        state["manual_summary"] = request.replacement_summary.strip()
        return state

    @staticmethod
    def _manual_display_summary(
        request: SceneCheckpointRepairRequest, state: dict[str, Any]
    ) -> str:
        if request.decision == "keep_current":
            return "已人工确认保留当前事实"
        if request.decision == "confirm_empty":
            return "已人工确认此阶段没有该维度事实"
        return (
            request.replacement_summary
            or SceneMemoryProjectionService._display_summary(request.dimension, state)
        )

    @staticmethod
    def _display_summary(dimension: str, state: dict[str, Any]) -> str:
        if state.get("manual_summary"):
            return str(state["manual_summary"])
        key = {
            "entities": "entities",
            "relations": "relations",
            "locations": "character_locations",
            "knowledge": "character_knowledge",
            "timeline": "facts",
            "causality": "claims",
        }[dimension]
        count = len(state.get(key) or {})
        changes = len(state.get("changes") or [])
        labels = {
            "entities": "人物与对象",
            "relations": "关系",
            "locations": "人物位置",
            "knowledge": "知识边界",
            "timeline": "时间顺序",
            "causality": "因果与前提",
        }
        suffix = f"，另有 {changes} 条变更" if changes else ""
        return f"{labels[dimension]} {count} 条{suffix}"

    @staticmethod
    def _event_label(event: Any) -> str:
        after = event.snapshot_after or {}
        return str(
            after.get("summary")
            or after.get("new_value")
            or after.get("field_path")
            or event.event_type
        )[:240]

    @staticmethod
    def _chapter_indices(scene: dict[str, Any] | None) -> list[int]:
        if not scene:
            return []
        values: set[int] = set()
        for raw in scene.get("chapter_ids") or []:
            try:
                values.add(int(raw))
            except (TypeError, ValueError):
                continue
        for chunk in scene.get("scene_chunks") or []:
            if not isinstance(chunk, dict):
                continue
            raw = chunk.get("chapter_index") or chunk.get("chapter_id")
            try:
                values.add(int(raw))
            except (TypeError, ValueError):
                continue
        return sorted(values)

    @staticmethod
    async def _ordered_scenes(db: AsyncSession, novel_id: str) -> list[dict[str, Any]]:
        from modules.story.outline_state.facade import get_scenes_by_novel

        scenes = await get_scenes_by_novel(
            db,
            novel_id,
            status_filter=["canonical", "draft"],
        )
        return sorted(
            scenes, key=lambda item: (int(item["scene_index"]), str(item["id"]))
        )

    @staticmethod
    def _scene_ids(scenes: list[dict[str, Any]]) -> list[uuid.UUID]:
        return [parse_uuid(str(scene["id"]), "scene_id") for scene in scenes]

    async def _reconcile_event_order(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scenes: list[dict[str, Any]],
    ) -> None:
        positions = {
            parse_uuid(str(scene["id"]), "scene_id"): int(scene["scene_index"])
            for scene in scenes
        }
        earliest = await self._events.align_scene_indices(db, novel_id, positions)
        if earliest is None:
            return
        await self._checkpoints.supersede_system_from(
            db,
            novel_id,
            earliest,
            list(SCENE_MEMORY_DIMENSIONS),
            include_start=True,
        )
        await self._snapshots.supersede_from(
            db,
            novel_id,
            earliest,
            include_start=True,
        )

    @staticmethod
    def _empty_dimension(dimension: str) -> dict[str, Any]:
        return {
            "entities": {"entities": {}, "changes": []},
            "relations": {"relations": [], "changes": []},
            "locations": {"character_locations": {}, "changes": []},
            "knowledge": {"character_knowledge": [], "changes": []},
            "timeline": {"facts": [], "changes": []},
            "causality": {"claims": [], "changes": []},
        }[dimension]

    @staticmethod
    def _empty_full_state() -> dict[str, Any]:
        return {
            "_contract_version": CURRENT_SCENE_MEMORY_CONTRACT_VERSION,
            **{
                dimension: SceneMemoryProjectionService._empty_dimension(dimension)
                for dimension in SCENE_MEMORY_DIMENSIONS
            },
        }

    @staticmethod
    def _hash(value: Any) -> str:
        return stable_hash(value)

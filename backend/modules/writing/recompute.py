"""改稿失效后的作者重算编排（P2-C C3；零 LLM）。

重算纪律（阶段计划 §3）：改稿保存时已标记失效并把范围展示给作者
（``repositories._changed`` 透传的 ``invalidation`` 公共视图），作者**再**
显式选择重算；编辑保存不自动触发昂贵生成（现状自动入队白名单仅
``rag_index_chapter``，本模块不改它）。本模块只补编排：

- **预览**（``preview``）：独立预览将执行的动作清单、成本分类与受影响
  范围，结构上零正史写入（纯读 + 组装，不落任何域写入）。
- **执行**（``adopt``）：重验来源版本（预览返回的来源指纹，漂移即 409
  并携带可比较数据、保留当前稿）、作者确认（``confirmed=True``）、幂等
  （``operation_id`` + 请求内容指纹双键；执行只落在本身幂等的域动作上，
  重放不产生重复行）。取消/过期 = 不调用 adopt，预览无服务端状态，
  零正史副作用。

执行只走既有白名单能力：``reload_evidence`` → evidence 章索引换源重读
（合法边 writing→evidence）；``rebuild_derived_state`` → story 场景
checkpoint 重建（合法边 writing→story，经 facade，投影重建幂等且保留
历史与作者确认）。``regenerate_prose`` 无既有生成任务白名单支撑本编排，
执行显式 unsupported（不新增 LLM 调用；正文重生成仍走独立生成端点的
既有确认/采用流程）。

契约对齐：三分类枚举值、成本/写入效果表与请求内容指纹
（``recompute_request_hash`` 口径：operation_id + novel/scope/targets/
baseline 指纹，不含 mode）镜像 ``modules/evolution/consumption.py``（C1
重算三分类）。writing 层不能 import evolution（依赖冻结集合无
writing→evolution 边），镜像常量由测试与 C1 契约逐位对拍防漂移
（沿 P2-B 镜像常量先例）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.evidence.facade import read_chapter_index_fingerprint, request_chapter_index
from modules.writing.repositories import (
    WritingDraftRepository,
    WritingRecomputeRepository,
)
from modules.writing.schemas import (
    WritingRecomputeActionItem,
    WritingRecomputeAdoptRequest,
    WritingRecomputeAffectedItem,
    WritingRecomputeOutcomeResponse,
    WritingRecomputePreviewResponse,
    WritingRecomputeRequest,
)
from shared.utils import parse_uuid

#: 重算三分类（镜像 evolution.consumption.RecomputeScope 枚举值）。
RECOMPUTE_SCOPES: tuple[str, ...] = (
    "reload_evidence",
    "rebuild_derived_state",
    "regenerate_prose",
)

#: 各分类覆盖的消费者键（镜像 evolution.consumption.RECOMPUTE_SCOPE_COVERS）。
RECOMPUTE_SCOPE_COVERS: dict[str, tuple[str, ...]] = {
    "reload_evidence": ("evidence_chapter_index",),
    "rebuild_derived_state": ("story_scene_projections",),
    "regenerate_prose": ("prose_generation",),
}

#: 各分类的成本与写入效果（镜像 evolution.consumption.RECOMPUTE_SCOPE_EFFECTS）。
RECOMPUTE_SCOPE_EFFECTS: dict[str, dict[str, str]] = {
    "reload_evidence": {
        "cost": "低：仅重新读取证据/重建章索引，不调用模型、不改状态",
        "write_effect": "替换章索引/证据缓存；不触碰 Scene 状态与正文",
    },
    "rebuild_derived_state": {
        "cost": "中：重算派生状态（Scene checkpoint/投影），可能触发已登记的审查任务",
        "write_effect": "软失效旧派生行并生成新行；作者确认与历史行保留",
    },
    "regenerate_prose": {
        "cost": "高：调用模型重写正文段落，消耗生成额度",
        "write_effect": "产生新草稿版本，须经作者确认采用；旧稿与人工修改保留",
    },
}


def recompute_request_hash(request: WritingRecomputeRequest) -> str:
    """请求内容指纹（幂等第二键；口径镜像 C1，不含 mode/确认字段）。

    与 evolution 消费登记契约的 ``recompute_request_hash`` 对同一逻辑请求
    逐位相等（测试对拍钉死），保证跨层操作标识一致。
    """
    return content_hash(
        {
            "novel_id": request.novel_id,
            "operation_id": request.operation_id,
            "scope": request.scope,
            "targets": [target.model_dump(mode="json") for target in request.targets],
            "baseline_receipt_digest": request.baseline_receipt_digest,
        }
    )


def _scene_chapter_indices(scene: dict[str, Any]) -> set[int]:
    """Scene 的章节锚（chapter_ids + scene_chunks；口径同失效引擎）。"""
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
    return values


class WritingRecomputeService:
    """作者触发的失效重算编排（预览零写入；执行重验 + 幂等域动作）。"""

    def __init__(
        self,
        draft_repo: WritingDraftRepository | None = None,
        operation_repo: WritingRecomputeRepository | None = None,
    ) -> None:
        self._draft_repo = draft_repo or WritingDraftRepository()
        self._operations = operation_repo or WritingRecomputeRepository()

    # ------------------------------------------------------------
    # 跨会话恢复查询（F7：离开再回来仍查得到待重算状态与已完成回执）
    # ------------------------------------------------------------

    async def list_receipts(
        self, db: AsyncSession, novel_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """已完成重算的回执摘要（倒序；作者语言、不含内部结果细节）。"""
        rows = await self._operations.list_operations(
            db, parse_uuid(novel_id, "novel_id"), limit=limit
        )
        return [
            {
                "operation_id": row.operation_id,
                "scope": row.scope,
                "request_hash": row.request_hash,
                "handled_count": len(row.results_json or {}),
                "completed_at": (
                    row.completed_at.isoformat() if row.completed_at else None
                ),
            }
            for row in rows
        ]

    async def list_pending_notices(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        chapter_index: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """待重算的失效提示（保存落库，重算覆盖该章后消解）。"""
        rows = await self._operations.list_open_notices(
            db,
            parse_uuid(novel_id, "novel_id"),
            chapter_index=chapter_index,
            limit=None,
        )
        # ponytail: metadata scan; paginate if retained history grows large.
        pending = []
        for row in rows:
            notice = dict(row.notice_json or {})
            if not await self._notice_completed(db, novel_id, notice):
                notice.pop("_recompute_progress", None)
                pending.append(notice)
                if len(pending) >= limit:
                    break
        return pending

    async def _notice_completed(
        self, db: AsyncSession, novel_id: str, notice: dict
    ) -> bool:
        progress = notice.get("_recompute_progress") or {}
        affected = notice.get("affected") or []
        evidence_required = any(
            item.get("consumer") == "evidence_chapter_index"
            for item in notice.get("invalidated") or []
        )
        if evidence_required:
            chapter = notice.get("chapter_index")
            result = (progress.get("reload_evidence") or {}).get(f"chapter:{chapter}")
            if not result or not result.get("requested_hash"):
                return False
            actual = await read_chapter_index_fingerprint(
                db, novel_id, int(chapter), content_mode="working"
            )
            if (
                not actual
                or actual.get("status") != "succeeded"
                or any(
                    actual.get(indexed) != result.get(requested)
                    for indexed, requested in (
                        ("indexed_hash", "requested_hash"),
                        ("indexed_source_id", "requested_source_id"),
                    )
                )
            ):
                return False
        for item in notice.get("invalidated") or []:
            if item.get("consumer") != "canonical_chapter_index":
                continue
            expected = item.get("detail") or {}
            actual = await read_chapter_index_fingerprint(
                db, novel_id, int(notice["chapter_index"]), content_mode="canonical"
            )
            if (
                not expected.get("requested_hash")
                or not actual
                or actual.get("status") != "succeeded"
                or any(
                    actual.get(indexed) != expected.get(requested)
                    for indexed, requested in (
                        ("indexed_hash", "requested_hash"),
                        ("indexed_source_id", "requested_source_id"),
                    )
                )
            ):
                return False
        scenes = {
            int(item["scene_index"])
            for item in affected
            if item.get("scene_index") is not None
        }
        rebuilt = {
            int(item["scene_index"]): item
            for item in (progress.get("rebuild_derived_state") or {}).values()
        }
        for index in scenes:
            result = rebuilt.get(index)
            if not result or not result.get("scene_id"):
                return False
            try:
                view = await self._story().get_scene_state_view(
                    db, novel_id, result["scene_id"], viewpoint={"kind": "author"}
                )
            except DomainError:
                return False
            if not view.dimensions or any(
                item.status != "ok" for item in view.dimensions
            ):
                return False
        return bool(evidence_required or scenes)

    # ------------------------------------------------------------
    # 目标解析与来源指纹
    # ------------------------------------------------------------

    @staticmethod
    def _story():
        # One lazy domain seam avoids the existing Story→Writing import cycle.
        from modules.story import facade

        return facade

    async def _scene_roster(self, db: AsyncSession, novel_id: str) -> list[dict]:
        return await self._story().get_scenes_by_novel(
            db, novel_id, status_filter=["canonical", "draft"]
        )

    def _resolve_scenes(
        self,
        roster: list[dict],
        request: WritingRecomputeRequest,
    ) -> list[dict]:
        """目标 Scene 集：显式 scene 锚 + 锚定目标章的 Scene（保守扩大）。"""
        selected: dict[str, dict] = {}
        for target in request.targets:
            if target.scene_index is None:
                continue
            scene = next(
                (
                    item
                    for item in roster
                    if int(item["scene_index"]) == target.scene_index
                ),
                None,
            )
            if scene is None:
                raise ValidationError(
                    f"场景 #{target.scene_index} 不存在，无法重算",
                    code="recompute_target_not_found",
                )
            selected[str(scene["id"])] = scene
        chapter_anchors = {
            target.chapter_index
            for target in request.targets
            if target.chapter_index is not None
        }
        for scene in roster:
            if chapter_anchors & _scene_chapter_indices(scene):
                selected[str(scene["id"])] = scene
        return sorted(selected.values(), key=lambda item: int(item["scene_index"]))

    def _resolve_chapters(
        self,
        roster: list[dict],
        request: WritingRecomputeRequest,
    ) -> set[int]:
        """目标章集：显式章锚 + 目标 Scene 的章节锚。"""
        chapters = {
            target.chapter_index
            for target in request.targets
            if target.chapter_index is not None
        }
        selected = self._resolve_scenes(roster, request)
        consumed = selected
        if request.scope == "rebuild_derived_state" and selected:
            # ensure_scene also consumes the inherited historical prefix.
            last = max(int(scene["scene_index"]) for scene in selected)
            consumed = [scene for scene in roster if int(scene["scene_index"]) <= last]
        for scene in consumed:
            chapters |= _scene_chapter_indices(scene)
        if request.scope == "rebuild_derived_state" and chapters:
            # basis reads the complete manuscript manifest between its endpoint chapters.
            chapters.update(range(min(chapters), max(chapters) + 1))
        return chapters

    async def _source_state(
        self,
        db: AsyncSession,
        novel_id: str,
        chapters: set[int],
    ) -> dict[str, Any]:
        """目标章的当前来源锚（最新工作稿版本 + 内容指纹）——adopt 重验依据。"""
        ordered = sorted(chapters)
        drafts = await self._draft_repo.list_latest_by_chapters(
            db,
            parse_uuid(novel_id, "novel"),
            ordered,
        )
        by_chapter = {int(draft.chapter_index): draft for draft in drafts}
        chapter_state: dict[str, Any] = {}
        for chapter in ordered:
            draft = by_chapter.get(chapter)
            chapter_state[str(chapter)] = {
                "draft_id": str(draft.id) if draft is not None else None,
                "version_number": (
                    int(draft.version_number) if draft is not None else None
                ),
                "content_hash": draft.content_hash if draft is not None else None,
            }
        return {"chapters": chapter_state}

    def _source_digest(self, state: dict[str, Any]) -> str:
        return content_hash(state)

    def _bind_scene_roster(
        self, state: dict, roster: list[dict], request: WritingRecomputeRequest
    ) -> None:
        if request.scope == "rebuild_derived_state":
            selected = self._resolve_scenes(roster, request)
            last = max((int(scene["scene_index"]) for scene in selected), default=-1)
            state["scenes"] = [
                {
                    "id": str(scene["id"]),
                    "scene_index": int(scene["scene_index"]),
                    "chapters": sorted(_scene_chapter_indices(scene)),
                    "scene_chunks": scene.get("scene_chunks") or [],
                    "chapter_ids": scene.get("chapter_ids") or [],
                    "status": scene.get("status"),
                }
                for scene in sorted(roster, key=lambda row: int(row["scene_index"]))
                if int(scene["scene_index"]) <= last
            ]

    # ------------------------------------------------------------
    # 预览（零正史写入）
    # ------------------------------------------------------------

    async def preview(
        self,
        db: AsyncSession,
        request: WritingRecomputeRequest,
    ) -> WritingRecomputePreviewResponse:
        roster = await self._scene_roster(db, request.novel_id)
        chapters = self._resolve_chapters(roster, request)
        state = await self._source_state(db, request.novel_id, chapters)
        self._bind_scene_roster(state, roster, request)
        effects = RECOMPUTE_SCOPE_EFFECTS[request.scope]

        if request.scope == "reload_evidence":
            actions, affected = self._preview_reload(chapters)
        elif request.scope == "rebuild_derived_state":
            actions, affected = self._preview_rebuild(roster, request)
        else:
            actions, affected = self._preview_regenerate(chapters)

        return WritingRecomputePreviewResponse(
            novel_id=request.novel_id,
            operation_id=request.operation_id,
            request_hash=recompute_request_hash(request),
            scope=request.scope,
            targets=list(request.targets),
            cost=effects["cost"],
            write_effect=effects["write_effect"],
            covers=list(RECOMPUTE_SCOPE_COVERS[request.scope]),
            executable=request.scope != "regenerate_prose",
            actions=actions,
            affected=affected,
            baseline_receipt_digest=request.baseline_receipt_digest,
            source_digest=self._source_digest(state),
            source_state=state,
        )

    def _preview_reload(
        self,
        chapters: set[int],
    ) -> tuple[list[WritingRecomputeActionItem], list[WritingRecomputeAffectedItem]]:
        actions: list[WritingRecomputeActionItem] = []
        affected: list[WritingRecomputeAffectedItem] = []
        for chapter in sorted(chapters):
            actions.append(
                WritingRecomputeActionItem(
                    action="reload_evidence",
                    chapter_index=chapter,
                    detail=f"以当前工作稿重新读取第 {chapter} 章证据并重建章索引"
                    "（复用既有 rag_index_chapter 索引任务）",
                )
            )
            affected.append(
                WritingRecomputeAffectedItem(
                    consumer="evidence_chapter_index",
                    basis="known",
                    chapter_index=chapter,
                    note="章索引由失效传播确定性重建，重读即恢复新鲜",
                )
            )
        return actions, affected

    def _preview_rebuild(
        self,
        roster: list[dict],
        request: WritingRecomputeRequest,
    ) -> tuple[list[WritingRecomputeActionItem], list[WritingRecomputeAffectedItem]]:
        scenes = self._resolve_scenes(roster, request)
        if not scenes:
            raise ValidationError(
                "重算目标没有锚定任何场景",
                code="recompute_target_not_found",
            )
        explicit_indexes = {
            target.scene_index
            for target in request.targets
            if target.scene_index is not None
        }
        dimensions = {target.dimension for target in request.targets if target.dimension}
        actions: list[WritingRecomputeActionItem] = []
        affected: list[WritingRecomputeAffectedItem] = []
        for scene in scenes:
            scene_index = int(scene["scene_index"])
            scene_id = str(scene["id"])
            actions.append(
                WritingRecomputeActionItem(
                    action="rebuild_derived_state",
                    scene_index=scene_index,
                    scene_id=scene_id,
                    detail="重建该场景的派生状态：软失效旧 checkpoint 行并生成新行，"
                    "历史与作者确认保留",
                )
            )
            affected.append(
                WritingRecomputeAffectedItem(
                    consumer="story_scene_checkpoint",
                    basis="unknown",
                    scene_index=scene_index,
                    scene_id=scene_id,
                    dimension=(sorted(dimensions)[0] if len(dimensions) == 1 else None),
                    note=(
                        "作者显式指定重算该场景；逐场景依赖登记未接入前按保守口径执行"
                        if scene_index in explicit_indexes
                        else "该场景锚定重算目标章，按保守扩大纳入重建"
                    ),
                )
            )
        return actions, affected

    def _preview_regenerate(
        self,
        chapters: set[int],
    ) -> tuple[list[WritingRecomputeActionItem], list[WritingRecomputeAffectedItem]]:
        actions: list[WritingRecomputeActionItem] = []
        affected: list[WritingRecomputeAffectedItem] = []
        for chapter in sorted(chapters):
            actions.append(
                WritingRecomputeActionItem(
                    action="regenerate_prose",
                    chapter_index=chapter,
                    detail="重生成正文（昂贵，消耗生成额度）：须经既有生成任务的"
                    "确认与采用流程；本重算编排不自动执行",
                )
            )
            affected.append(
                WritingRecomputeAffectedItem(
                    consumer="prose_generation",
                    basis="unknown",
                    chapter_index=chapter,
                    note="正文重生成需作者另行经生成端点显式触发并确认采用",
                )
            )
        return actions, affected

    # ------------------------------------------------------------
    # 执行（重验 + 幂等域动作）
    # ------------------------------------------------------------

    async def adopt(
        self,
        db: AsyncSession,
        request: WritingRecomputeAdoptRequest,
    ) -> WritingRecomputeOutcomeResponse:
        if not request.confirmed:
            raise ValidationError(
                "execute requires author confirmation (confirmed=true)",
                code="recompute_confirmation_required",
            )
        # 执行必须携带可重验的预览基线：缺省即失败关闭，不让「没预览过」
        # 的请求直接落域写入（预览后来源漂移返回 409 才有意义）。
        if not (request.expected_source_digest or "").strip():
            raise ValidationError(
                "执行重算须携带预览返回的来源指纹，请先预览这次重算",
                code="recompute_preview_baseline_required",
            )
        if request.scope == "regenerate_prose":
            # 不新增 LLM 调用：正文重生成不在本编排的白名单内，显式拒绝。
            raise ConflictError(
                "正文重生成需经既有生成任务的确认与采用流程，重算编排不支持执行",
                code="recompute_scope_unsupported",
                context={"scope": request.scope, "author_choice_only": True},
            )

        # 双键幂等第一键：同一 operation_id 的已完成操作先回放原回执
        # （来源后来变了也能查回原结果，不必再改一次正文）；同编号但请求
        # 摘要不同 → 那是另一次重算顶替了这次预览，拒绝。
        request_hash = recompute_request_hash(request)
        nid = parse_uuid(request.novel_id, "novel_id")
        await self._operations.lock_operations(db, nid)
        completed = await self._operations.get_operation(db, nid, request.operation_id)
        if completed is not None:
            if (
                completed.request_hash != request_hash
                or completed.expected_source_digest != request.expected_source_digest
            ):
                raise ConflictError(
                    "该操作编号已用于另一次重算，请重新预览后再执行",
                    code="recompute_operation_conflict",
                    context={
                        "operation_id": request.operation_id,
                        "expected_request_hash": completed.request_hash,
                        "requested_request_hash": request_hash,
                    },
                )
            return WritingRecomputeOutcomeResponse(
                novel_id=request.novel_id,
                operation_id=request.operation_id,
                request_hash=completed.request_hash,
                scope=completed.scope,
                confirmed=True,
                domain_write_performed=False,
                results=dict(completed.results_json or {}),
                replayed=True,
            )

        roster = await self._scene_roster(db, request.novel_id)
        chapters = self._resolve_chapters(roster, request)
        await self._draft_repo.lock_version_chapters_for_revalidation(
            db, nid, sorted(chapters)
        )
        if not await self._story().lock_scene_roster_for_revalidation(
            db, request.novel_id
        ):
            raise ConflictError(
                "场景结构正在修改，请稍后基于当前稿重新预览",
                code="recompute_source_drift",
                context={"keep_current_draft": True},
            )
        roster = await self._scene_roster(db, request.novel_id)
        current_chapters = self._resolve_chapters(roster, request)
        if chapters != current_chapters:
            raise ConflictError(
                "重算场景的来源范围已变化，请重新预览",
                code="recompute_source_drift",
                context={"keep_current_draft": True},
            )
        state = await self._source_state(db, request.novel_id, chapters)
        self._bind_scene_roster(state, roster, request)
        current_digest = self._source_digest(state)
        if (
            request.expected_source_digest is not None
            and request.expected_source_digest != current_digest
        ):
            raise ConflictError(
                "重算目标章节在预览后已再次修改，为避免覆盖已保留当前稿；"
                "请基于当前稿重新预览",
                code="recompute_source_drift",
                context={
                    "expected_source_digest": request.expected_source_digest,
                    "current_source_digest": current_digest,
                    "current": state["chapters"],
                    "keep_current_draft": True,
                },
            )

        results: dict[str, Any] = {}
        if request.scope == "reload_evidence":
            for chapter in sorted(chapters):
                index_state = await request_chapter_index(
                    db,
                    request.novel_id,
                    chapter,
                    content_mode="working",
                )
                results[f"chapter:{chapter}"] = {
                    "action": "reload_evidence",
                    "chapter_index": chapter,
                    "requested_hash": index_state.get("requested_hash"),
                    "requested_source_id": index_state.get("requested_source_id"),
                    "status": index_state.get("status"),
                    "task_id": index_state.get("task_id"),
                }
        else:
            # 同上：story 门面保持函数内导入（重建经 facade，投影幂等）。
            for scene in self._resolve_scenes(roster, request):
                scene_id = str(scene["id"])
                rebuilt = await self._story().ensure_scene_checkpoints(
                    db, request.novel_id, scene_id
                )
                results[f"scene:{scene_id}"] = {
                    "action": "rebuild_derived_state",
                    "scene_index": int(scene["scene_index"]),
                    "scene_id": scene_id,
                    "coverage_status": rebuilt.coverage_status,
                    "current_checkpoints": sum(
                        1 for item in rebuilt.items if item.is_current
                    ),
                }

        # 回执落库：跨会话可查、同一编号重复执行走回放（不重复域写入）。
        await self._operations.save_operation(
            db,
            novel_id=nid,
            operation_id=request.operation_id,
            request_hash=request_hash,
            scope=request.scope,
            expected_source_digest=str(request.expected_source_digest),
            results=results,
        )
        await self._operations.record_notice_progress(
            db, nid, request.baseline_receipt_digest, scope=request.scope, results=results
        )

        return WritingRecomputeOutcomeResponse(
            novel_id=request.novel_id,
            operation_id=request.operation_id,
            request_hash=request_hash,
            scope=request.scope,
            confirmed=True,
            domain_write_performed=True,
            results=results,
            replayed=False,
        )

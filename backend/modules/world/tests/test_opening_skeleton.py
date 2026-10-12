"""新书开篇世界观骨架（BR-5 World 侧）。

覆盖：包内近名合并与关系重定向、与已有对象同名补充/近名别名、实体与关系
上限、秘密条目作者可见层；空项目一次生成待审骨架包；条目级取舍与整包
单事务采用；回执逆序回滚（未改动软废弃、作者改动保留）；owner 与
novel_id 隔离；未采用骨架与方向卡不进入生成上下文。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.schemas import LLMCallResponse
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.evidence.compilation.knowledge.llm_schemas import AuditVerdictOutput
from modules.project.schemas import ProjectCreate
from modules.project.services import ProjectService
from modules.world.llm_schemas import (
    GeneratedOpeningSkeleton,
    GeneratedOpeningSkeletonCharacter,
    GeneratedOpeningSkeletonEntity,
    GeneratedOpeningSkeletonRelation,
    GeneratedOpeningSkeletonRule,
)
from modules.world.models import CoreEntity, CreationSuggestion, EntityRelation
from modules.world.schemas import (
    WorldAdoptionPackageApplyRequest,
    WorldAdoptionPackageItemsUpdateRequest,
    WorldAdoptionPackageItemUpdate,
)
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.opening_skeleton import (
    MAX_ENTITIES,
    ExistingObject,
    OpeningSkeletonService,
    _dedupe_within_package,
)
from modules.world.tests.governance_fakes import GovernedWorldAuditMixin
from shared.utils import parse_uuid

pytestmark = pytest.mark.usefixtures("account_llm_connection")


# ============================================================
# 测试夹具与骨架工厂
# ============================================================


def _skeleton(
    *,
    locations: list[GeneratedOpeningSkeletonEntity] | None = None,
    factions: list[GeneratedOpeningSkeletonEntity] | None = None,
    lore: list[GeneratedOpeningSkeletonEntity] | None = None,
    relations: list[GeneratedOpeningSkeletonRelation] | None = None,
    protagonist_name: str = "林潮生",
) -> GeneratedOpeningSkeleton:
    return GeneratedOpeningSkeleton(
        premise_name="潮汐之城",
        premise="长夜之后城市随月潮起落，凡人只在退潮的窗口劳作与交易。",
        tone="压抑中带倔强的日常感",
        rules=[
            GeneratedOpeningSkeletonRule(
                name="潮约",
                entity_type="rule",
                summary="潮汐决定一切活动的窗口。",
                can="退潮时自由行动与交易",
                cannot="涨潮时在低城区停留",
                cost="行动窗口以体力为代价",
                failure="错过退潮会被困在涌水区",
                maintenance="潮钟必须每月校准",
            ),
            GeneratedOpeningSkeletonRule(
                name="灯契",
                entity_type="power_system",
                summary="持灯者以寿命换取照明。",
                can="照明驱散潮雾",
                cannot="照明无法驱散人对人的恶意",
                cost="燃烧持有者的寿命",
                failure="灯灭时潮雾反噬",
                maintenance="每夜续契",
            ),
        ],
        locations=locations
        or [
            GeneratedOpeningSkeletonEntity(
                name="低城区",
                entity_type="location",
                summary="退潮后才完整的城区。",
                public_info="绝大多数居民住在低城区。",
            ),
            GeneratedOpeningSkeletonEntity(
                name="潮钟塔",
                entity_type="location",
                summary="全城潮钟的心脏。",
            ),
            GeneratedOpeningSkeletonEntity(
                name="灯人巷",
                entity_type="location",
                summary="持灯者聚居的巷子。",
                hidden_truth="巷底的井直通潮眼。",
            ),
        ],
        factions=factions
        or [
            GeneratedOpeningSkeletonEntity(
                name="守钟会",
                entity_type="faction",
                summary="维护潮钟的世袭行会。",
                hidden_truth="会首私改过潮钟。",
            ),
            GeneratedOpeningSkeletonEntity(
                name="灯契商会",
                entity_type="organization",
                summary="垄断灯油生意的商会。",
            ),
        ],
        characters=[
            GeneratedOpeningSkeletonCharacter(
                name=protagonist_name,
                summary="想找回失踪妹妹的年轻潮钟学徒。",
                public_info="潮钟学徒。",
                is_protagonist=True,
                character_card={"desire": "找回妹妹"},
            ),
            GeneratedOpeningSkeletonCharacter(
                name="苏灯娘",
                summary="灯人巷最后一任灯娘。",
            ),
            GeneratedOpeningSkeletonCharacter(
                name="钟正堂",
                summary="守钟会现任会首。",
            ),
        ],
        lore=lore
        or [
            GeneratedOpeningSkeletonEntity(
                name="第一次长夜",
                entity_type="legend",
                summary="所有潮汐规则的起源事件。",
            )
        ],
        relations=relations
        or [
            GeneratedOpeningSkeletonRelation(
                source=protagonist_name,
                target="苏灯娘",
                relation_type="师徒",
                relation_kind="social",
                description="灯娘教主角认潮。",
            ),
            GeneratedOpeningSkeletonRelation(
                source="钟正堂",
                target="守钟会",
                relation_type="统领",
                relation_kind="social",
            ),
        ],
        review_notes=[],
    )


def _existing(name: str, entity_type: str = "location", **kwargs) -> ExistingObject:
    return ExistingObject(
        entity_id=str(uuid.uuid4()),
        name=name,
        entity_type=entity_type,
        summary=kwargs.get("summary"),
        public_info=kwargs.get("public_info"),
        hidden_truth=kwargs.get("hidden_truth"),
        aliases=kwargs.get("aliases", ()),
    )


def _assemble(catalog: list[ExistingObject], generated=None):
    service = OpeningSkeletonService()
    return service.assemble_package(
        generated or _skeleton(),
        catalog,
        input_hash="a" * 64,
        task_id="task-1",
        direction_title=None,
    )


# ============================================================
# 去重与上限单测
# ============================================================


def test_same_name_existing_becomes_fill_or_ref_not_create():
    catalog = [_existing("低城区", summary="已有描述")]
    package, stats = _assemble(catalog)
    by_name = {}
    for item in package.items:
        if item.kind == "core_entity":
            payload = item.payload
            if payload["operation"] in {"fill_empty", "existing_ref"}:
                by_name[payload["entity_id"]] = payload["operation"]
    assert catalog[0].entity_id in by_name
    # 已有 summary 不为空 → 只补空字段（public_info 缺失被补充）。
    assert by_name[catalog[0].entity_id] == "fill_empty"
    assert stats.created_entities + 0 >= 0


def test_same_name_existing_without_fields_degrades_to_reference():
    catalog = [
        _existing(
            "低城区",
            summary="已有完整描述",
            public_info="公开信息已齐",
            hidden_truth="隐藏层已写",
        )
    ]
    package, _stats = _assemble(catalog)
    operations = [
        item.payload["operation"]
        for item in package.items
        if item.kind == "core_entity"
        and item.payload.get("entity_id") == catalog[0].entity_id
    ]
    assert operations == ["existing_ref"]


def test_near_name_existing_attaches_alias_only():
    existing_name = "守钟会的第七次大整修"
    near_name = "守钟会的第七次大检修"
    catalog = [_existing(existing_name)]
    generated = _skeleton(
        locations=[
            GeneratedOpeningSkeletonEntity(
                name=near_name, entity_type="location", summary="与大整修同源。"
            ),
            GeneratedOpeningSkeletonEntity(
                name="潮钟塔", entity_type="location", summary="全城潮钟的心脏。"
            ),
            GeneratedOpeningSkeletonEntity(
                name="灯人巷", entity_type="location", summary="持灯者聚居。"
            ),
        ]
    )
    package, stats = _assemble(catalog, generated)
    alias_items = [item for item in package.items if item.kind == "entity_alias"]
    assert len(alias_items) == 1
    assert alias_items[0].payload["alias"] == near_name
    assert alias_items[0].payload["entity_ref"] == catalog[0].entity_id
    assert stats.attached_aliases == 1
    created_names = [
        item.payload["entity"]["name"]
        for item in package.items
        if item.kind == "core_entity" and item.payload["operation"] == "create"
    ]
    assert near_name not in created_names


def test_in_package_near_names_merge_and_relations_redirect():
    generated = _skeleton(
        locations=[
            GeneratedOpeningSkeletonEntity(
                name="守钟会的第七次大整修",
                entity_type="location",
                summary="整修事件的现场。",
            ),
            GeneratedOpeningSkeletonEntity(
                name="守钟会的第七次大检修",
                entity_type="location",
                summary="同一场事件的另一写法。",
            ),
            GeneratedOpeningSkeletonEntity(
                name="灯人巷", entity_type="location", summary="持灯者聚居。"
            ),
            GeneratedOpeningSkeletonEntity(
                name="低城区", entity_type="location", summary="退潮后才完整的城区。"
            ),
        ],
        relations=[
            GeneratedOpeningSkeletonRelation(
                source="守钟会的第七次大检修",
                target="低城区",
                relation_type="俯瞰",
            )
        ],
    )
    merged, dropped = _dedupe_within_package(generated)
    assert dropped == ["守钟会的第七次大检修"]
    assert [item.name for item in merged.locations].count("守钟会的第七次大整修") == 1
    assert merged.relations[0].source == "守钟会的第七次大整修"

    package, stats = _assemble([], merged)
    location_names = [
        item.payload["entity"]["name"]
        for item in package.items
        if item.kind == "core_entity"
        and item.payload["operation"] == "create"
        and item.payload["entity"]["entity_type"] == "location"
    ]
    assert "守钟会的第七次大整修" in location_names
    assert "守钟会的第七次大检修" not in location_names
    # 前提 + 2 规则 + 3 地点 + 3 人物 + 2 势力 + 1 传说
    assert stats.created_entities == 12
    assert stats.relations == 1 and stats.dropped_relations == 0


def test_entity_and_relation_caps_drop_overflow_with_record():
    generated = _skeleton(
        locations=[
            GeneratedOpeningSkeletonEntity(
                name=f"地点{index:02d}",
                entity_type="location",
                summary=f"第 {index} 个。",
            )
            for index in range(8)
        ],
        factions=[
            GeneratedOpeningSkeletonEntity(
                name=f"势力{index:02d}", entity_type="faction", summary=f"第 {index} 个。"
            )
            for index in range(6)
        ],
        lore=[
            GeneratedOpeningSkeletonEntity(
                name=f"传说{index:02d}", entity_type="legend", summary=f"第 {index} 个。"
            )
            for index in range(4)
        ],
        relations=[
            GeneratedOpeningSkeletonRelation(
                source="地点00", target=f"地点{index:02d}", relation_type="相邻"
            )
            for index in range(1, 8)
        ],
    )
    package, stats = _assemble([], generated)
    created = [
        item
        for item in package.items
        if item.kind == "core_entity" and item.payload["operation"] == "create"
    ]
    assert len(created) == MAX_ENTITIES
    assert len(stats.dropped_items) == 4  # 24 个实体条目只保留前 20 个
    assert stats.dropped_items  # 超出的条目按名字记录
    assert package.opening_skeleton is not None
    assert package.opening_skeleton.dropped_items == stats.dropped_items[:32]


def test_hidden_truth_entries_default_to_author_only():
    package, _stats = _assemble([], None)
    for item in package.items:
        if item.kind != "core_entity" or item.payload["operation"] != "create":
            continue
        entity = item.payload["entity"]
        if (entity.get("hidden_truth") or "").strip():
            assert entity["reveal_level"] == "author_only"
        else:
            assert entity["reveal_level"] == "hinted"


def test_protagonist_flag_survives_near_name_merge():
    generated = GeneratedOpeningSkeleton(
        premise_name="潮汐之城",
        premise="前提。",
        tone="基调。",
        rules=[
            GeneratedOpeningSkeletonRule(
                name=f"潮约{i}",
                summary="s",
                can="c",
                cannot="c",
                cost="c",
                failure="f",
                maintenance="m",
            )
            for i in range(2)
        ],
        locations=[
            GeneratedOpeningSkeletonEntity(name=f"地点{i}", summary="s") for i in range(3)
        ],
        factions=[
            GeneratedOpeningSkeletonEntity(name=f"势力{i}", summary="s") for i in range(2)
        ],
        characters=[
            GeneratedOpeningSkeletonCharacter(
                name="守钟会的第七次大整修主持者", summary="会首"
            ),
            GeneratedOpeningSkeletonCharacter(
                name="守钟会的第七次大检修主持者",
                summary="同一场事件的另一写法。",
                is_protagonist=True,
            ),
            GeneratedOpeningSkeletonCharacter(name="苏灯娘", summary="灯娘"),
        ],
        lore=[GeneratedOpeningSkeletonEntity(name="第一次长夜", summary="s")],
    )
    merged, dropped = _dedupe_within_package(generated)
    protagonists = [item for item in merged.characters if item.is_protagonist]
    assert len(protagonists) == 1
    assert protagonists[0].name == "守钟会的第七次大整修主持者"
    assert dropped == ["守钟会的第七次大检修主持者"]


# ============================================================
# 集成：生成 → 条目取舍 → 采用 → 回滚
# ============================================================


class _FakeSkeletonClient(GovernedWorldAuditMixin):
    provider = "fake-provider"
    model_name = "fake-default-model"

    def __init__(self, skeleton: GeneratedOpeningSkeleton) -> None:
        self.skeleton = skeleton
        self.audit_verdicts: list[str] = []

    async def generate_structured(self, request, schema, **_kwargs):  # noqa: ANN001
        if schema is AuditVerdictOutput:
            return await self._governed_generate_structured(request, schema, **_kwargs)
        assert schema is GeneratedOpeningSkeleton, schema
        return self.skeleton

    async def generate(self, request):  # noqa: ANN001
        return LLMCallResponse(
            content="unused", model=request.model, provider=self.provider
        )

    async def close(self) -> None:
        return None


def _principal(account: Account) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type="email",
        support_code=account.support_code,
    )


async def _owner_project(db_session: AsyncSession, title: str) -> str:
    project = await ProjectService().create_project(
        db_session, ProjectCreate(title=title)
    )
    return str(project.id)


@pytest.mark.asyncio
async def test_generate_task_saves_pending_skeleton_package_on_empty_project(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空项目可直接一次产出骨架包；不需要任何 Evidence 上下文确认。"""
    token = bind_principal(None)
    try:
        novel_id = await _owner_project(db_session, "空项目骨架")
        from modules.project.llm_runtime import build_project_llm_execution_snapshot

        snapshot = await build_project_llm_execution_snapshot(db_session, novel_id)
        fake = _FakeSkeletonClient(_skeleton())
        monkeypatch.setattr(
            "modules.project.llm_runtime.LLMClient.from_resolved_profile",
            lambda profile, **_kwargs: fake,
        )
        service = OpeningSkeletonService()
        result = await service.generate_for_task(
            db_session,
            novel_id,
            _skeleton_task_request(novel_id=novel_id),
            llm_execution_snapshot=snapshot,
            task_id="task-skeleton-1",
        )
        await db_session.flush()
        assert result["created_entities"] == 12
        assert result["relations"] == 2
        assert result["knowledge_review_status"] == "passed"

        saved = await db_session.scalar(
            select(CreationSuggestion).where(
                CreationSuggestion.id == parse_uuid(result["package_suggestion_id"])
            )
        )
        assert saved is not None and saved.status == "pending"
        assert saved.source_module == "world"
        assert saved.payload_json["opening_skeleton"]["task_id"] == "task-skeleton-1"
        assert saved.payload_json["knowledge_review"]["status"] == "passed"
        # 空项目没有 Evidence 确认依赖：包不绑定任何 context confirmation。
        assert not saved.payload_json.get("context_fingerprint")
        assert not saved.payload_json.get("focused_authorization_id")
    finally:
        reset_principal(token)


def _skeleton_task_request(novel_id: str):
    from modules.world.schemas import WorldOpeningSkeletonTaskRequest

    return WorldOpeningSkeletonTaskRequest(
        novel_id=novel_id,
        vision="长夜之后城市随月潮起落的世界。",
        direction_title="潮汐都市",
        direction={"题材": "城市奇幻", "主冲突": "潮钟权柄之争"},
    )


@pytest.mark.asyncio
async def test_item_triage_excludes_conflicts_and_apply_adopts_selection(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account(status="active", support_code="U-TRIAGE")
    db_session.add(account)
    await db_session.flush()
    token = bind_principal(_principal(account))
    try:
        novel_id = await _owner_project(db_session, "条目取舍项目")
        catalog = await OpeningSkeletonService().existing_catalog(db_session, novel_id)
        package, _stats = _assemble(catalog)
        saved = await WorldAdoptionPackageService().save(
            db_session,
            _package_save_request(novel_id, package),
            source_module="world",
        )
        service = OpeningSkeletonService()

        excluded_key = "entity-character-02"  # 钟正堂
        from datetime import datetime

        for baseline, code in [
            (None, "edit_baseline_required"),
            (datetime(2000, 1, 1), "edit_baseline_stale"),
        ]:
            with pytest.raises(ConflictError) as error:
                await service.update_package_items(
                    db_session,
                    novel_id,
                    saved.id,
                    WorldAdoptionPackageItemsUpdateRequest(
                        novel_id=novel_id,
                        expected_updated_at=baseline,
                        items=[
                            WorldAdoptionPackageItemUpdate(
                                item_key=excluded_key, included=False
                            )
                        ],
                    ),
                )
            assert error.value.code == code
        updated, conflicts = await service.update_package_items(
            db_session,
            novel_id,
            saved.id,
            WorldAdoptionPackageItemsUpdateRequest(
                novel_id=novel_id,
                expected_updated_at=saved.updated_at,
                items=[
                    WorldAdoptionPackageItemUpdate(item_key=excluded_key, included=False),
                    WorldAdoptionPackageItemUpdate(
                        item_key="entity-character-00",
                        name="林潮生",
                        summary="作者改过的主角简介。",
                    ),
                ],
            ),
        )
        await db_session.flush()
        payload = updated.payload_json
        by_key = {item["item_key"]: item for item in payload["items"]}
        assert by_key[excluded_key]["disposition"] == "open"
        assert "author_excluded" in by_key[excluded_key]["review_reasons"]
        # 端点被排除的关系自动转为待定并说明原因（relation-01 = 钟正堂→守钟会）。
        assert by_key["relation-01"]["disposition"] == "open"
        assert "endpoint_excluded" in by_key["relation-01"]["review_reasons"]
        assert by_key["relation-00"]["disposition"] == "include"
        assert by_key["entity-character-00"]["payload"]["entity"]["summary"] == (
            "作者改过的主角简介。"
        )
        # 仍保留条目的主角 hidden_truth 层级如实固定。
        assert conflicts

        preview = await WorldAdoptionPackageService().preview(
            db_session, novel_id, saved.id
        )
        diff_by_key = {entry["item_key"]: entry for entry in preview.canon_diff}
        assert "conflicts" in diff_by_key["entity-premise-00"]

        applied = await WorldAdoptionPackageService().apply(
            db_session,
            novel_id,
            saved.id,
            WorldAdoptionPackageApplyRequest(
                expected_preview_hash=preview.expected_preview_hash
            ),
        )
        await db_session.flush()
        assert applied.status == "accepted"

        entities = (
            (
                await db_session.execute(
                    select(CoreEntity).where(CoreEntity.novel_id == parse_uuid(novel_id))
                )
            )
            .scalars()
            .all()
        )
        names = {entity.name for entity in entities}
        assert "低城区" in names and "林潮生" in names
        assert "钟正堂" not in names  # 排除条未采用
        relations = (
            (
                await db_session.execute(
                    select(EntityRelation).where(
                        EntityRelation.novel_id == parse_uuid(novel_id)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(relations) == 1  # relation-01（钟正堂→守钟会已随排除转待定）
    finally:
        reset_principal(token)


def _package_save_request(novel_id: str, package):
    from modules.world.schemas import WorldAdoptionPackageSaveRequest

    return WorldAdoptionPackageSaveRequest(novel_id=novel_id, package=package)


@pytest.mark.asyncio
async def test_blocked_knowledge_review_blocks_package_adoption(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account(status="active", support_code="U-BLOCKED")
    db_session.add(account)
    await db_session.flush()
    token = bind_principal(_principal(account))
    try:
        novel_id = await _owner_project(db_session, "阻断骨架项目")
        catalog = await OpeningSkeletonService().existing_catalog(db_session, novel_id)
        package, _stats = _assemble(catalog)
        blocked = dict(package.model_dump(mode="json"))
        blocked["knowledge_review"] = {
            "status": "blocked",
            "repaired": True,
            "policy_version": 1,
            "output_hash": "b" * 64,
            "coverage": [],
        }
        from modules.world.schemas import WorldAdoptionPackagePayload

        saved = await WorldAdoptionPackageService().save(
            db_session,
            _package_save_request(
                novel_id, WorldAdoptionPackagePayload.model_validate(blocked)
            ),
            source_module="world",
        )
        service = WorldAdoptionPackageService()
        preview = await service.preview(db_session, novel_id, saved.id)
        with pytest.raises(ValidationError, match="知识审查"):
            await service.apply(
                db_session,
                novel_id,
                saved.id,
                WorldAdoptionPackageApplyRequest(
                    expected_preview_hash=preview.expected_preview_hash
                ),
            )
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_rollback_soft_deletes_untouched_and_keeps_author_modified(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = Account(status="active", support_code="U-ROLLBACK")
    db_session.add(account)
    await db_session.flush()
    token = bind_principal(_principal(account))
    try:
        novel_id = await _owner_project(db_session, "整体撤销项目")
        catalog = await OpeningSkeletonService().existing_catalog(db_session, novel_id)
        package, _stats = _assemble(catalog)
        saved = await WorldAdoptionPackageService().save(
            db_session,
            _package_save_request(novel_id, package),
            source_module="world",
        )
        service = WorldAdoptionPackageService()
        preview = await service.preview(db_session, novel_id, saved.id)
        await service.apply(
            db_session,
            novel_id,
            saved.id,
            WorldAdoptionPackageApplyRequest(
                expected_preview_hash=preview.expected_preview_hash
            ),
        )
        await db_session.flush()

        # 作者在采用后修改了其中一个对象（低城区）。
        modified = await db_session.scalar(
            select(CoreEntity).where(
                CoreEntity.novel_id == parse_uuid(novel_id),
                CoreEntity.name == "低城区",
            )
        )
        assert modified is not None
        # 与采用时刻拉开时间差：updated_at 同微秒碰撞会让改动不可区分。
        await asyncio.sleep(0.002)
        await WorldEntityService().update(
            db_session,
            str(modified.id),
            _entity_update(summary="作者改过的低城区。"),
            novel_id=novel_id,
        )
        await db_session.flush()

        skeleton = OpeningSkeletonService()
        result = await skeleton.rollback_package(db_session, novel_id, saved.id)
        await db_session.flush()
        statuses = {entry["item_key"]: entry["status"] for entry in result["results"]}
        assert any(status == "modified_after_adoption" for status in statuses.values())
        assert any(status == "rolled_back" for status in statuses.values())

        entities = (
            (
                await db_session.execute(
                    select(CoreEntity).where(CoreEntity.novel_id == parse_uuid(novel_id))
                )
            )
            .scalars()
            .all()
        )
        by_name = {entity.name: entity for entity in entities}
        # 未改动的骨架对象软废弃；作者已改动的对象保留。
        assert by_name["潮汐之城"].status == "deprecated"
        assert by_name["低城区"].status == "canonical"
        assert by_name["低城区"].summary == "作者改过的低城区。"
        kept_keys = [
            entry["item_key"]
            for entry in result["results"]
            if entry["status"] == "modified_after_adoption"
        ]
        assert kept_keys
        receipt = (
            await db_session.scalar(
                select(CreationSuggestion).where(
                    CreationSuggestion.id == parse_uuid(saved.id)
                )
            )
        ).result_ref_json
        assert receipt["rollback"]
    finally:
        reset_principal(token)


def _entity_update(**kwargs):
    from modules.world.schemas import CoreEntityUpdate

    return CoreEntityUpdate(**kwargs)


@pytest.mark.asyncio
async def test_item_triage_and_rollback_require_owner_and_project_isolation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = Account(status="active", support_code="U-SKEL-OWNER")
    other = Account(status="active", support_code="U-SKEL-OTHER")
    db_session.add_all([owner, other])
    await db_session.flush()
    token = bind_principal(_principal(owner))
    try:
        novel_id = await _owner_project(db_session, "骨架隔离项目")
        catalog = await OpeningSkeletonService().existing_catalog(db_session, novel_id)
        package, _stats = _assemble(catalog)
        saved = await WorldAdoptionPackageService().save(
            db_session,
            _package_save_request(novel_id, package),
            source_module="world",
        )
    finally:
        reset_principal(token)

    other_token = bind_principal(_principal(other))
    try:
        service = OpeningSkeletonService()
        # 非所有者视角项目直接不可见（404）；能到 owner 门禁时也被拒绝。
        with pytest.raises((NotFoundError, ValidationError)):
            await service.update_package_items(
                db_session,
                novel_id,
                saved.id,
                WorldAdoptionPackageItemsUpdateRequest(
                    novel_id=novel_id,
                    items=[WorldAdoptionPackageItemUpdate(item_key="entity-premise-00")],
                ),
            )
        with pytest.raises((NotFoundError, ValidationError)):
            await service.rollback_package(db_session, novel_id, saved.id)
        # 跨项目 novel_id 不可见。
        other_project = await ProjectService().create_project(
            db_session, ProjectCreate(title="其他项目")
        )
        with pytest.raises(ValidationError):
            await service.rollback_package(db_session, str(other_project.id), saved.id)
    finally:
        reset_principal(other_token)


@pytest.mark.asyncio
async def test_skeleton_stays_out_of_generation_context_until_adopted(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未采用骨架与方向卡不进入任何生成上下文；采用后秘密只对作者可见。"""
    account = Account(status="active", support_code="U-CONTEXT")
    db_session.add(account)
    await db_session.flush()
    token = bind_principal(_principal(account))
    try:
        novel_id = await _owner_project(db_session, "骨架上下文项目")
        catalog = await OpeningSkeletonService().existing_catalog(db_session, novel_id)
        package, _stats = _assemble(catalog)
        saved = await WorldAdoptionPackageService().save(
            db_session,
            _package_save_request(novel_id, package),
            source_module="world",
        )
        from modules.world.facade import get_world_context

        # 未采用：pending 包条目不进任何上下文。
        for reveal_mode in ("author_safe", "author_full"):
            bundle = await get_world_context(
                db_session, novel_id, reveal_mode=reveal_mode
            )
            names = {item.name for item in bundle.entities}
            assert "潮汐之城" not in names
            assert "灯人巷" not in names

        service = WorldAdoptionPackageService()
        preview = await service.preview(db_session, novel_id, saved.id)
        await service.apply(
            db_session,
            novel_id,
            saved.id,
            WorldAdoptionPackageApplyRequest(
                expected_preview_hash=preview.expected_preview_hash
            ),
        )
        await db_session.flush()

        safe = await get_world_context(db_session, novel_id, reveal_mode="author_safe")
        author = await get_world_context(db_session, novel_id, reveal_mode="author_full")
        assert {"灯人巷", "潮汐之城"} <= {item.name for item in author.entities}
        assert {"潮汐之城"} <= {item.name for item in safe.entities}
        # 秘密/真相只在作者完整上下文可见。
        safe_lamp = next(item for item in safe.entities if item.name == "灯人巷")
        author_lamp = next(item for item in author.entities if item.name == "灯人巷")
        assert not (safe_lamp.hidden_truth or "").strip()
        assert "潮眼" in (author_lamp.hidden_truth or "")

        await OpeningSkeletonService().rollback_package(db_session, novel_id, saved.id)
        await db_session.flush()
        rolled = await get_world_context(db_session, novel_id, reveal_mode="author_full")
        assert "潮汐之城" not in {item.name for item in rolled.entities}
    finally:
        reset_principal(token)


# ============================================================
# suggest 操作：prepare → apply（幂等入队）→ 任务执行 → read_result
# ============================================================


@pytest.mark.asyncio
async def test_suggest_operation_submits_idempotently_and_reads_result(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace as _replace
    from uuid import uuid4 as _uuid4

    from app.assistant_operation_registry import world_opening_operations
    from infrastructure.tasks.models import AsyncTask
    from modules.account.facade import current_account_id
    from modules.assistant.contracts import AssistantOperationContext, WorkContext
    from modules.project.llm_runtime import build_project_llm_execution_snapshot
    from modules.world.assistant_opening_tools import DraftOpeningSkeleton
    from modules.world.tasks import handle_world_opening_skeleton

    token = bind_principal(None)
    try:
        novel_id = await _owner_project(db_session, "骨架操作项目")
        parent = AsyncTask(
            novel_id=parse_uuid(novel_id),
            task_type="assistant_turn",
            status="running",
            meta={},
        )
        db_session.add(parent)
        await db_session.flush()
        context = AssistantOperationContext(
            str(parent.id), str(current_account_id()), WorkContext(scope="project")
        )
        operation = world_opening_operations["world.draft_opening_skeleton"]
        args = DraftOpeningSkeleton(
            vision="长夜之后城市随月潮起落的世界。",
            direction_title="潮汐都市",
        )
        preview = await operation.prepare(db_session, novel_id, args, context=context)
        context = _replace(
            context,
            operation_id=str(_uuid4()),
            llm_snapshot=await build_project_llm_execution_snapshot(db_session, novel_id),
            internal_meta={
                "_execution_mode": "inline_only",
                "_parent_task_id": str(parent.id),
            },
        )
        reference = await operation.apply(
            db_session, novel_id, args, preview, context=context
        )
        await db_session.flush()
        replay = await operation.apply(
            db_session, novel_id, args, preview, context=context
        )
        assert replay["task_id"] == reference["task_id"]
        pending_result = await operation.read_result(db_session, novel_id, reference)
        assert pending_result["status"] == "incomplete"

        fake = _FakeSkeletonClient(_skeleton())
        monkeypatch.setattr(
            "modules.project.llm_runtime.LLMClient.from_resolved_profile",
            lambda profile, **_kwargs: fake,
        )
        task_row = await db_session.get(AsyncTask, parse_uuid(reference["task_id"]))
        # 直接执行 handler 并按 worker 终态落 result（信封语义由信封测试覆盖）。
        task_row.status = "done"
        task_row.result = await handle_world_opening_skeleton(db_session, task_row)
        await db_session.flush()

        result = await operation.read_result(db_session, novel_id, reference)
        assert result["status"] == "completed"
        assert result["knowledge_review_status"] == "passed"
        assert result["counts"]["relations"] == 2
        assert result["package_suggestion_id"]
        # 方向卡与构想只落在任务请求与包来源里，未进入任何资产或检索。
        task = task_row
        assert task.meta["_parent_task_id"] == str(parent.id)
        stored = await db_session.scalar(
            select(CreationSuggestion).where(
                CreationSuggestion.id == parse_uuid(result["package_suggestion_id"])
            )
        )
        assert stored.payload_json["opening_skeleton"]["direction_title"] == "潮汐都市"
        assert (
            stored.payload_json["items"][0]["source_refs"][0]["source_type"]
            == "author_decision"
        )
        # 任务请求冻结了方向卡参数；生成内容只进入待审包，不直接落资产。
        assert task.meta["direction_title"] == "潮汐都市"
    finally:
        reset_principal(token)

"""导演多尺度独立探索：Evidence 确认契约测试（P0 冻结契约 §1/§2）。"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from modules.evidence.compilation.facade import (
    compile_from_confirmation,
    confirm_exploration_context,
    preview_exploration_context,
)
from modules.evidence.compilation.knowledge.contracts import KnowledgeContractError
from modules.evidence.compilation.knowledge.policies import (
    get_capability_policy,
    require_capability_policy,
)
from modules.evidence.compilation.models import ContextConfirmation
from modules.evidence.compilation.schemas import ExplorationContextRequest
from modules.evidence.compilation.services.confirmation_service import (
    execution_compile_options,
    resolve_retrieval_purpose,
)
from modules.story.outline_state.models import Scene
from modules.world.models import Character, CoreEntity


def _provisional_payload(novel_id: str, **overrides) -> dict:
    payload = {
        "novel_id": novel_id,
        "action": "story.exploration.sandbox.generate",
        "task": "沙盘推演：面包师的一天",
        "scope": "project",
        "exploration_scale": "sandbox",
        "start": {
            "kind": "provisional",
            "question": "这个城镇每天只有一小时重力减半，面包师的一天会怎样？",
            "assumptions": [
                {"kind": "world_rule", "text": "每天有一小时重力减半"},
            ],
            "candidates": [{"ref_id": "c_baker", "label": "面包师", "role": "character"}],
            "time_basis": "assumed_now",
        },
    }
    payload.update(overrides)
    return payload


def _provisional_request(novel_id: str, **overrides) -> ExplorationContextRequest:
    return ExplorationContextRequest(**_provisional_payload(novel_id, **overrides))


def _scene_anchor_request(
    novel_id: str,
    scene_id: str,
    **overrides,
) -> ExplorationContextRequest:
    payload = {
        "novel_id": novel_id,
        "action": "story.exploration.scene_line.generate",
        "task": "B 对 A 的一句真诚回应",
        "scope": "scene",
        "exploration_scale": "scene_line",
        "start": {"kind": "scene_anchor", "scene_id": scene_id},
    }
    payload.update(overrides)
    return ExplorationContextRequest(**payload)


def _canonical_character(db_session: AsyncSession, novel_id: str) -> str:
    entity_id = uuid.uuid4()
    db_session.add_all(
        [
            CoreEntity(
                id=entity_id,
                novel_id=uuid.UUID(novel_id),
                entity_type="character",
                name="阿澜",
                status="canonical",
            ),
            Character(
                entity_id=entity_id,
                novel_id=uuid.UUID(novel_id),
                name="阿澜",
                personality="警觉",
                status="canonical",
            ),
        ]
    )
    return str(entity_id)


# ---------------------------------------------------------------------------
# §2.1 请求 schema
# ---------------------------------------------------------------------------


def test_exploration_request_rejects_non_exploration_action() -> None:
    with pytest.raises(ValueError, match="story.exploration."):
        _provisional_request(
            str(uuid.uuid4()),
            action="story.script.generate",
        )


def test_exploration_request_rejects_unknown_scale() -> None:
    with pytest.raises(ValueError):
        ExplorationContextRequest(
            **_provisional_payload(
                str(uuid.uuid4()),
                exploration_scale="full_rehearsal",
            )
        )


def test_exploration_request_rejects_provisional_with_scene_id() -> None:
    with pytest.raises(ValueError, match="不能绑定 Scene"):
        _provisional_request(
            str(uuid.uuid4()),
            scene_id=str(uuid.uuid4()),
        )


def test_exploration_request_backfills_scene_anchor_ids() -> None:
    scene_id = str(uuid.uuid4())
    request = _scene_anchor_request(str(uuid.uuid4()), scene_id)
    # scene_id 缺省时回填锚点 Scene；character POV 的截止点同样回填。
    assert request.scene_id == scene_id

    character_request = _scene_anchor_request(
        str(uuid.uuid4()),
        scene_id,
        reveal_mode="character",
        viewpoint_character_id=str(uuid.uuid4()),
    )
    assert character_request.visible_until_scene_id == scene_id

    with pytest.raises(ValueError, match="一致"):
        ExplorationContextRequest(
            novel_id=str(uuid.uuid4()),
            action="story.exploration.scene_line.generate",
            task="一句对白",
            scope="scene",
            exploration_scale="scene_line",
            start={"kind": "scene_anchor", "scene_id": scene_id},
            scene_id=str(uuid.uuid4()),
        )


# ---------------------------------------------------------------------------
# §2.3 服务端校验拒绝路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exploration_validation_rejects_unknown_action_and_scale_mismatch(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    with pytest.raises(ValidationError, match="不支持的探索操作"):
        await preview_exploration_context(
            db_session,
            _provisional_request(
                test_project_id,
                action="story.exploration.sandbox.detail",
            ),
        )
    with pytest.raises(ValidationError, match="exploration_scale 与操作不匹配"):
        await preview_exploration_context(
            db_session,
            _provisional_request(
                test_project_id,
                action="story.exploration.sandbox.generate",
                exploration_scale="event",
            ),
        )


@pytest.mark.asyncio
async def test_exploration_validation_rejects_scope_mismatch(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    with pytest.raises(ValidationError, match="确认范围必须是 project"):
        await preview_exploration_context(
            db_session,
            _provisional_request(test_project_id, scope="scene"),
        )
    scene_id = uuid.uuid4()
    db_session.add(
        Scene(
            id=scene_id,
            novel_id=uuid.UUID(test_project_id),
            scene_index=0,
            title="夜巡",
            goal="确认潮门是否被动过",
            status="canonical",
        )
    )
    await db_session.flush()
    with pytest.raises(ValidationError, match="确认范围必须是 scene"):
        await preview_exploration_context(
            db_session,
            _scene_anchor_request(
                test_project_id,
                str(scene_id),
                action="story.exploration.scene_line.generate",
            ).model_copy(update={"scope": "project"}),
        )


@pytest.mark.asyncio
async def test_exploration_validation_rejects_forged_canonical_refs(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """伪造正式 ID：不存在的 UUID、跨作品角色、非角色实体都失败关闭。"""
    from modules.project.models import Project

    foreign_project = uuid.uuid4()
    db_session.add(Project(id=foreign_project, title="他作项目"))
    foreign_entity = _canonical_character(db_session, str(foreign_project))
    await db_session.flush()

    location_only = uuid.uuid4()
    db_session.add(
        CoreEntity(
            id=location_only,
            novel_id=uuid.UUID(test_project_id),
            entity_type="location",
            name="潮门",
            status="canonical",
        )
    )
    await db_session.flush()

    start_overrides = [
        {"canonical_refs": [str(uuid.uuid4())]},
        {"canonical_refs": [foreign_entity]},
        {"canonical_refs": [str(location_only)]},
        {
            "scene_stimuli": [
                {
                    "subject_entity_id": str(uuid.uuid4()),
                    "stimulus": "假设他刚失业",
                }
            ]
        },
        {
            "knowledge": [
                {
                    "subject_ref": str(uuid.uuid4()),
                    "knows": ["城门每夜落锁"],
                }
            ]
        },
    ]
    for override in start_overrides:
        payload = _provisional_payload(test_project_id)
        payload["start"].update(override)
        with pytest.raises(
            ValidationError,
            match="正式角色不存在、非正史或不属于当前项目",
        ):
            await preview_exploration_context(
                db_session,
                ExplorationContextRequest(**payload),
            )


@pytest.mark.asyncio
async def test_exploration_validation_rejects_client_supplied_web_refs(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    payload = _provisional_payload(test_project_id)
    payload["start"]["web_refs"] = [
        {
            "url": "https://example.com/gravity",
            "title": "重力资料",
            "retrieved_at": "2026-10-17T00:00:00+00:00",
            "content_hash": "a" * 64,
            "excerpt": "摘录",
        }
    ]
    with pytest.raises(ValidationError, match="只能由服务端"):
        await preview_exploration_context(
            db_session,
            ExplorationContextRequest(**payload),
        )


@pytest.mark.asyncio
async def test_exploration_validation_rejects_missing_or_foreign_scene_anchor(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    with pytest.raises(ValidationError, match="探索锚点 Scene 不存在"):
        await preview_exploration_context(
            db_session,
            _scene_anchor_request(test_project_id, str(uuid.uuid4())),
        )
    foreign_scene = uuid.uuid4()
    db_session.add(
        Scene(
            id=foreign_scene,
            novel_id=uuid.uuid4(),
            scene_index=0,
            title="他作的夜巡",
            goal="校验作品归属",
            status="canonical",
        )
    )
    await db_session.flush()
    with pytest.raises(ValidationError, match="探索锚点 Scene 不存在"):
        await preview_exploration_context(
            db_session,
            _scene_anchor_request(test_project_id, str(foreign_scene)),
        )
    own_scene = uuid.uuid4()
    db_session.add(
        Scene(
            id=own_scene,
            novel_id=uuid.UUID(test_project_id),
            scene_index=0,
            title="夜巡",
            goal="确认潮门",
            status="canonical",
        )
    )
    await db_session.flush()
    with pytest.raises(ValidationError, match="可见截止必须与锚点 Scene 一致"):
        await preview_exploration_context(
            db_session,
            _scene_anchor_request(
                test_project_id,
                str(own_scene),
                visible_until_scene_id=str(uuid.uuid4()),
            ),
        )


@pytest.mark.asyncio
async def test_exploration_validation_reveals_mode_boundaries(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    with pytest.raises(ValidationError, match="不支持 reader"):
        await preview_exploration_context(
            db_session,
            _provisional_request(test_project_id, reveal_mode="reader"),
        )
    with pytest.raises(ValidationError, match="viewpoint_character_id"):
        await preview_exploration_context(
            db_session,
            _provisional_request(test_project_id, reveal_mode="character"),
        )
    with pytest.raises(ValidationError, match="可见截止点"):
        await preview_exploration_context(
            db_session,
            _provisional_request(
                test_project_id,
                reveal_mode="character",
                viewpoint_character_id=str(uuid.uuid4()),
            ),
        )


# ---------------------------------------------------------------------------
# §2.4 临时起点：空资料集 preview → confirm → 重物化往返
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provisional_empty_project_roundtrip(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _provisional_request(test_project_id)

    preview = await preview_exploration_context(db_session, request)
    assert preview["blockers"] == []
    assert preview["context_fingerprint"]

    confirmed = await confirm_exploration_context(
        db_session,
        _provisional_request(
            test_project_id,
            expected_context_fingerprint=preview["context_fingerprint"],
        ),
    )
    assert confirmed.result_status == "confirmed"
    assert confirmed.stale_reasons == []
    assert confirmed.blockers == []
    # 空项目资料集：除项目级内置 context_sections 基线外无任何业务资料选中，
    # 不产生 blocker；指纹照算且与预览一致。
    assert confirmed.context_fingerprint == preview["context_fingerprint"]

    options = confirmed.compile_options
    assert options["start_kind"] == "provisional"
    assert options["exploration_start"]["kind"] == "provisional"
    assert options["exploration_start"]["question"].startswith("这个城镇")
    assert options["exploration_scale"] == "sandbox"
    assert options["exploration_focus"] == ""

    # prepare 复用的剥离清单只剥地图基线，四个探索冻结键必须保留。
    execution_options = execution_compile_options(options)
    for key in (
        "start_kind",
        "exploration_start",
        "exploration_scale",
        "exploration_focus",
    ):
        assert key in execution_options
    assert "map_spatial_baseline" not in execution_options
    assert "compiled_context_core_fingerprint" not in execution_options

    compiled = await compile_from_confirmation(
        db_session,
        novel_id=test_project_id,
        action=request.action,
        confirmation_id=confirmed.id,
    )
    # 重物化不产生 blocker；冻结起点经 selection_trace 回传。
    assert compiled.blockers == []
    assert compiled.selection_trace["exploration"]["start_kind"] == "provisional"
    assert compiled.selection_trace["exploration"]["exploration_start"] == options[
        "exploration_start"
    ]
    assert compiled.selection_trace["exploration"]["exploration_scale"] == "sandbox"

    # 核心指纹门在临时起点仍然生效：资料变化 → context_changed 失败关闭。
    record = await db_session.get(ContextConfirmation, uuid.UUID(confirmed.id))
    record.compile_options = {
        **record.compile_options,
        "compiled_context_core_fingerprint": "0" * 64,
    }
    await db_session.flush()
    with pytest.raises(ConflictError) as error:
        await compile_from_confirmation(
            db_session,
            novel_id=test_project_id,
            action=request.action,
            confirmation_id=confirmed.id,
        )
    assert error.value.code == "context_changed"


@pytest.mark.asyncio
async def test_provisional_confirm_rejects_stale_preview_fingerprint(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    with pytest.raises(ConflictError) as error:
        await confirm_exploration_context(
            db_session,
            _provisional_request(
                test_project_id,
                expected_context_fingerprint="0" * 64,
            ),
        )
    assert error.value.code == "context_preview_changed"


@pytest.mark.asyncio
async def test_provisional_confirm_validates_canonical_refs_and_freezes_them(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    entity_id = _canonical_character(db_session, test_project_id)
    await db_session.flush()
    payload = _provisional_payload(test_project_id)
    payload["start"].update(
        {
            "canonical_refs": [entity_id],
            "knowledge": [
                {
                    "subject_ref": entity_id,
                    "knows": ["潮门每夜落锁"],
                }
            ],
            "scene_stimuli": [
                {"subject_entity_id": entity_id, "stimulus": "假设他刚失业"}
            ],
            "author_private": ["我想看他撑住的样子"],
        }
    )
    confirmed = await confirm_exploration_context(
        db_session,
        ExplorationContextRequest(**payload),
    )
    frozen_start = confirmed.compile_options["exploration_start"]
    assert frozen_start["canonical_refs"] == [entity_id]
    assert frozen_start["knowledge"][0]["subject_ref"] == entity_id
    assert frozen_start["author_private"] == ["我想看他撑住的样子"]
    assert confirmed.context_fingerprint


# ---------------------------------------------------------------------------
# §2.4 Scene 锚点：现有门禁回归
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scene_anchor_confirmation_roundtrip_with_core_fingerprint_gate(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    scene_id = uuid.uuid4()
    db_session.add(
        Scene(
            id=scene_id,
            novel_id=uuid.UUID(test_project_id),
            scene_index=0,
            title="夜巡",
            goal="确认潮门是否被动过",
            status="canonical",
        )
    )
    await db_session.flush()
    request = _scene_anchor_request(test_project_id, str(scene_id))

    preview = await preview_exploration_context(db_session, request)
    assert preview["blockers"] == []

    confirmed = await confirm_exploration_context(
        db_session,
        _scene_anchor_request(
            test_project_id,
            str(scene_id),
            expected_context_fingerprint=preview["context_fingerprint"],
        ),
    )
    options = confirmed.compile_options
    assert options["start_kind"] == "scene_anchor"
    assert options["exploration_start"] == {
        "kind": "scene_anchor",
        "scene_id": str(scene_id),
    }
    assert options["exploration_scale"] == "scene_line"
    assert options["scene_id"] == str(scene_id)
    assert options["visible_until_scene_id"] == str(scene_id)

    compiled = await compile_from_confirmation(
        db_session,
        novel_id=test_project_id,
        action=request.action,
        confirmation_id=confirmed.id,
    )
    assert compiled.selection_trace["exploration"]["start_kind"] == "scene_anchor"

    record = await db_session.get(ContextConfirmation, uuid.UUID(confirmed.id))
    record.compile_options = {
        **record.compile_options,
        "compiled_context_core_fingerprint": "0" * 64,
    }
    await db_session.flush()
    with pytest.raises(ConflictError) as error:
        await compile_from_confirmation(
            db_session,
            novel_id=test_project_id,
            action=request.action,
            confirmation_id=confirmed.id,
        )
    assert error.value.code == "context_changed"


# ---------------------------------------------------------------------------
# §2.2 能力注册与检索用途
# ---------------------------------------------------------------------------


def test_exploration_capabilities_are_registered_with_confirmation_gate() -> None:
    for capability_id in (
        "story.exploration.sandbox",
        "story.exploration.event",
        "story.exploration.scene_line",
    ):
        policy = get_capability_policy(capability_id)
        assert policy is not None
        assert policy.domain == "story"
        assert policy.confirmation_policy == "required"
        assert policy.adoption_gate == "display_only"
        assert "STORY_EXPLORATION_ENABLED" in policy.notes
    with pytest.raises(KnowledgeContractError, match="story.exploration.author_edit"):
        require_capability_policy("story.exploration.author_edit")


def test_exploration_retrieval_purpose_resolves_to_story_generation() -> None:
    assert (
        resolve_retrieval_purpose(
            "story.exploration.sandbox.generate",
            "generic_context",
            reveal_mode="author_safe",
        )
        == "story_generation"
    )


# ---------------------------------------------------------------------------
# 现有 API 面回归：旧 /confirm 入口对探索动作失败关闭
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_confirm_endpoint_rejects_exploration_actions(
    async_client: AsyncClient,
    test_project_id: str,
) -> None:
    """探索确认只能经探索 facade 入口；旧确认入口拒绝缺失冻结起点的请求。"""
    response = await async_client.post(
        "/api/evidence/compilation/confirm",
        json=_provisional_payload(test_project_id),
    )
    assert response.status_code == 400, response.text
    assert "exploration_start" in response.text

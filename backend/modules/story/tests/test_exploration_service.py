"""探索服务骨架：创建校验、save-edit 幂等、比较门与历史过滤（P0 §3.3/§7.6）。"""

from __future__ import annotations

import uuid

import pytest

from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import Assumption, ProvisionalStart, SceneAnchorStart
from modules.story.exploration_schemas import (
    SANDBOX_OUTPUT_KIND,
    EventOutputV1,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    exploration_start_fingerprint,
)
from modules.story.exploration_service import (
    compare_exploration_results,
    create_exploration_root,
    pack_exploration_output,
    read_exploration_history,
    save_exploration_author_edit,
    unpack_exploration_output,
)
from modules.story.models import StorySceneDirectorBranch, StorySceneDirectorRound
from modules.story.world_progression_models import (
    StoryWorldProgressionStep,
)

OWNER_ID = str(LOCAL_OWNER_ID)


_DEFAULT_QUESTION = "这个城镇每天只有一小时重力减半，面包师的一天会怎样？"


def _provisional_start(question: str = _DEFAULT_QUESTION):
    return ProvisionalStart(
        kind="provisional",
        question=question,
        assumptions=[Assumption(kind="world_rule", text="每天只有一小时重力减半")],
        time_basis="assumed_now",
    )


def _scene_start():
    return SceneAnchorStart(kind="scene_anchor", scene_id=str(uuid.uuid4()))


def _sandbox_envelope(**payload_overrides) -> ExplorationOutputEnvelope:
    payload = {
        "question": "重力减半后面包师的一天？",
        "influence_chain": [
            {
                "condition": "揉面时间不变",
                "mechanism": "重力降低让面团发酵更快",
                "effect": "面包更松软",
            }
        ],
        "unknowns": ["精确生产率未知"],
    }
    payload.update(payload_overrides)
    return ExplorationOutputEnvelope(
        output_kind=SANDBOX_OUTPUT_KIND,
        schema_version=1,
        payload=SandboxOutputV1.model_validate(payload),
    )


async def _create_progression_exploration(
    db_session, project_id, *, question: str = None, scale: str = "sandbox"
):
    start = _provisional_start(question or _DEFAULT_QUESTION)
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale=scale,
        start=start,
        context_confirmation_id="ctx-" + str(uuid.uuid4()),
    )
    return root, branch, start


async def _add_progression_result(
    db_session, root, branch, envelope
) -> StoryWorldProgressionStep:
    step = StoryWorldProgressionStep(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        step_number=1,
        source_hash=root.source_hash,
        input_hash="a" * 64,
        output_hash="b" * 64,
        input_json={"mode": "start"},
        result_json=pack_exploration_output(envelope),
        state_json={},
        metrics_json={},
        basis_changed=False,
    )
    db_session.add(step)
    await db_session.flush()
    return step


async def _add_director_result(
    db_session, root, branch, envelope
) -> StorySceneDirectorRound:
    round_row = StorySceneDirectorRound(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        round_number=1,
        source_hash=root.source_hash,
        input_hash="c" * 64,
        output_hash="d" * 64,
        input_json={"mode": "start"},
        output_json=pack_exploration_output(envelope),
        state_json={},
        run_envelope_json={},
    )
    db_session.add(round_row)
    await db_session.flush()
    return round_row


# ---------------------------------------------------------------------------
# 创建校验（起点判别强制）
# ---------------------------------------------------------------------------


async def test_create_provisional_root_forces_no_scene(db_session, project_factory):
    project_id = await project_factory.create_project()
    root, branch, _start = await _create_progression_exploration(db_session, project_id)
    assert root.source_kind == "provisional"
    assert root.scene_id is None
    assert branch.root_id == root.id
    assert branch.branch_kind == "start"
    fingerprint = root.request_json["exploration_start_fingerprint"]
    assert fingerprint == exploration_start_fingerprint(_start, "sandbox")
    assert root.request_json["exploration_scale"] == "sandbox"


async def test_create_scene_anchor_root_keeps_scene(db_session, project_factory):
    project_id = await project_factory.create_project()
    start = _scene_start()
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=start,
    )
    assert root.source_kind == "scene"
    assert str(root.scene_id) == start.scene_id
    # 场景对白走导演链：分支是导演分支，且推进链不要求确认 ID。
    assert isinstance(branch, StorySceneDirectorBranch)


async def test_create_provisional_rejects_scene_binding(db_session, project_factory):
    project_id = await project_factory.create_project()
    from core.errors import DomainError

    with pytest.raises(DomainError):
        await create_exploration_root(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            scale="sandbox",
            start=_provisional_start(),
            scene_id=str(uuid.uuid4()),
        )


async def test_create_scene_anchor_rejects_mismatched_scene(db_session, project_factory):
    project_id = await project_factory.create_project()
    from core.errors import ConflictError

    start = _scene_start()
    with pytest.raises(ConflictError):
        await create_exploration_root(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            scale="scene_line",
            start=start,
            scene_id=str(uuid.uuid4()),
        )


async def test_progression_chain_requires_confirmation(db_session, project_factory):
    project_id = await project_factory.create_project()
    from core.errors import DomainError

    with pytest.raises(DomainError):
        await create_exploration_root(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            scale="sandbox",
            start=_provisional_start(),
        )


async def test_create_rejects_foreign_owner(db_session, project_factory):
    project_id = await project_factory.create_project()
    from core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await create_exploration_root(
            db_session,
            novel_id=str(project_id),
            owner_id=str(uuid.uuid4()),
            scale="sandbox",
            start=_provisional_start(),
            context_confirmation_id="ctx-1",
        )


async def test_create_rejects_unknown_scale(db_session, project_factory):
    project_id = await project_factory.create_project()
    from core.errors import DomainError

    with pytest.raises(DomainError):
        await create_exploration_root(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            scale="novel",
            start=_provisional_start(),
        )


# ---------------------------------------------------------------------------
# 作者编辑保存：新行 + 幂等（零模型调用）
# ---------------------------------------------------------------------------


async def test_save_edit_appends_new_row_and_is_idempotent(db_session, project_factory):
    project_id = await project_factory.create_project()
    root, branch, _start = await _create_progression_exploration(db_session, project_id)
    base = await _add_progression_result(db_session, root, branch, _sandbox_envelope())
    edited = _sandbox_envelope(
        influence_chain=[
            {
                "condition": "揉面时间不变",
                "mechanism": "重力降低让面团发酵更快",
                "effect": "面包明显更松软，作者微调措辞",
            }
        ],
    )

    row, envelope = await save_exploration_author_edit(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(base.id),
        edited_payload=edited.payload,
        edit_note="把结论改得更保守",
    )
    assert row.id != base.id
    assert row.parent_step_id == base.id
    assert row.step_number == base.step_number + 1
    assert envelope.output_kind == "story.exploration.author_edit"
    assert envelope.payload.base_output_kind == SANDBOX_OUTPUT_KIND
    assert envelope.payload.base_result_id == str(base.id)
    assert row.input_json["mode"] == "save_edit"

    again_row, again_envelope = await save_exploration_author_edit(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(base.id),
        edited_payload=edited.payload,
        edit_note="把结论改得更保守",
    )
    assert again_row.id == row.id
    assert again_envelope.model_dump() == envelope.model_dump()

    other_row, _env = await save_exploration_author_edit(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(base.id),
        edited_payload=edited.payload,
        edit_note="换一条编辑说明",
    )
    assert other_row.id != row.id

    await db_session.refresh(base)
    assert base.result_json == pack_exploration_output(_sandbox_envelope())


async def test_save_edit_on_director_chain(db_session, project_factory):
    project_id = await project_factory.create_project()
    start = _scene_start()
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=start,
    )
    from modules.story.exploration_schemas import (
        SCENE_LINE_OUTPUT_KIND,
        SceneLineOutputV1,
    )

    line_envelope = ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "target_ref": "c_b",
                "line": "你要是累了就先回去吧。",
                "rationale": "B 只看见 A 疲惫。",
            }
        ),
    )
    base = await _add_director_result(db_session, root, branch, line_envelope)
    edited_payload = SceneLineOutputV1.model_validate(
        {
            "target_ref": "c_b",
            "line": "你要是累了就先回去吧，别硬撑。",
            "rationale": "B 只看见 A 疲惫；作者改口语气。",
        }
    )
    row, envelope = await save_exploration_author_edit(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(base.id),
        edited_payload=edited_payload,
    )
    assert isinstance(row, StorySceneDirectorRound)
    assert row.round_number == base.round_number + 1
    assert row.parent_round_id == base.id
    assert envelope.payload.base_output_kind == SCENE_LINE_OUTPUT_KIND


async def test_save_edit_rejects_shape_mismatch_and_non_exploration(
    db_session, project_factory
):
    project_id = await project_factory.create_project()
    root, branch, _start = await _create_progression_exploration(db_session, project_id)
    base = await _add_progression_result(db_session, root, branch, _sandbox_envelope())
    from core.errors import ConflictError

    event_payload = EventOutputV1.model_validate(
        {
            "mode": "diagnose",
            "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
            "gaps": [
                {"description": "缺身份来源", "why_needed": "解释送达"}
            ],
        }
    )
    with pytest.raises(ConflictError):
        await save_exploration_author_edit(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            base_result_id=str(base.id),
            edited_payload=event_payload,
        )

    legacy = StoryWorldProgressionStep(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        step_number=9,
        source_hash=root.source_hash,
        input_hash="e" * 64,
        output_hash="f" * 64,
        input_json={},
        result_json={"some": "legacy-settlement"},
        state_json={},
        metrics_json={},
        basis_changed=False,
    )
    db_session.add(legacy)
    await db_session.flush()
    with pytest.raises(ConflictError):
        await save_exploration_author_edit(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            base_result_id=str(legacy.id),
            edited_payload=SandboxOutputV1.model_validate(
                {
                    "question": "q",
                    "influence_chain": [
                        {"condition": "a", "mechanism": "b", "effect": "c"}
                    ],
                }
            ),
        )


# ---------------------------------------------------------------------------
# 比较：起点指纹门
# ---------------------------------------------------------------------------


async def test_compare_same_start_results(db_session, project_factory):
    project_id = await project_factory.create_project()
    root, branch, _start = await _create_progression_exploration(db_session, project_id)
    step_a = await _add_progression_result(db_session, root, branch, _sandbox_envelope())
    step_b = StoryWorldProgressionStep(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        step_number=2,
        source_hash=root.source_hash,
        input_hash="1" * 64,
        output_hash="2" * 64,
        input_json={},
        result_json=pack_exploration_output(
            _sandbox_envelope(question="换个问法的同一轮输出？")
        ),
        state_json={},
        metrics_json={},
        basis_changed=False,
    )
    db_session.add(step_b)
    await db_session.flush()

    result = await compare_exploration_results(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        first_result_id=str(step_a.id),
        second_result_id=str(step_b.id),
    )
    assert result["left"]["result_id"] == str(step_a.id)
    assert result["right"]["result_id"] == str(step_b.id)
    assert result["left"]["envelope"].output_kind == SANDBOX_OUTPUT_KIND


async def test_compare_rejects_different_start(db_session, project_factory):
    project_id = await project_factory.create_project()
    root_a, branch_a, _ = await _create_progression_exploration(db_session, project_id)
    root_b, branch_b, _ = await _create_progression_exploration(
        db_session, project_id, question="如果重力永远消失呢？"
    )
    step_a = await _add_progression_result(
        db_session, root_a, branch_a, _sandbox_envelope()
    )
    step_b = await _add_progression_result(
        db_session, root_b, branch_b, _sandbox_envelope()
    )
    from core.errors import ConflictError

    with pytest.raises(ConflictError):
        await compare_exploration_results(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            first_result_id=str(step_a.id),
            second_result_id=str(step_b.id),
        )


async def test_compare_rejects_non_exploration_rows(db_session, project_factory):
    project_id = await project_factory.create_project()
    root, branch, _start = await _create_progression_exploration(db_session, project_id)
    legacy = StoryWorldProgressionStep(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        step_number=1,
        source_hash=root.source_hash,
        input_hash="3" * 64,
        output_hash="4" * 64,
        input_json={},
        result_json={"legacy": True},
        state_json={},
        metrics_json={},
        basis_changed=False,
    )
    db_session.add(legacy)
    await db_session.flush()
    from core.errors import ConflictError

    with pytest.raises(ConflictError):
        await compare_exploration_results(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            first_result_id=str(legacy.id),
            second_result_id=str(legacy.id),
        )


# ---------------------------------------------------------------------------
# 历史过滤
# ---------------------------------------------------------------------------


async def test_history_lists_provisional_and_scene_exploration_roots(
    db_session, project_factory
):
    import sqlalchemy as sa

    project_id = await project_factory.create_project()
    prov_root, prov_branch, _ = await _create_progression_exploration(
        db_session, project_id
    )
    scene_root, scene_branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=_scene_start(),
    )
    plain_scene_root, plain_branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=_scene_start(),
    )
    # 带 Scene 的旧导演根：只补普通（无 output_kind）回合，不得算作探索输出。
    legacy_scene_root, legacy_branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=_scene_start(),
    )
    await _add_director_result(db_session, scene_root, scene_branch, _sandbox_envelope())
    for branch in (plain_branch, legacy_branch):
        await db_session.execute(
            sa.insert(StorySceneDirectorRound).values(
                novel_id=legacy_scene_root.novel_id,
                root_id=legacy_scene_root.id,
                branch_id=branch.id,
                round_number=1,
                source_hash="5" * 64,
                input_hash="6" * 64,
                output_hash="7" * 64,
                input_json={},
                output_json={"materials": []},
                state_json={},
                run_envelope_json={},
            )
        )

    history = await read_exploration_history(
        db_session, novel_id=str(project_id), owner_id=OWNER_ID
    )
    listed_ids = {item["root_id"] for item in history["items"]}
    assert str(prov_root.id) in listed_ids
    assert str(scene_root.id) in listed_ids
    assert str(plain_scene_root.id) not in listed_ids
    assert str(legacy_scene_root.id) not in listed_ids
    assert history["total"] == 2

    sandbox_only = await read_exploration_history(
        db_session, novel_id=str(project_id), owner_id=OWNER_ID, scale="sandbox"
    )
    assert [item["root_id"] for item in sandbox_only["items"]] == [str(prov_root.id)]

    scene_line_only = await read_exploration_history(
        db_session, novel_id=str(project_id), owner_id=OWNER_ID, scale="scene_line"
    )
    assert [item["root_id"] for item in scene_line_only["items"]] == [str(scene_root.id)]

    paged = await read_exploration_history(
        db_session, novel_id=str(project_id), owner_id=OWNER_ID, limit=1, offset=1
    )
    assert paged["total"] == 2
    assert len(paged["items"]) == 1


async def test_history_rejects_foreign_owner(db_session, project_factory):
    project_id = await project_factory.create_project()
    from core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await read_exploration_history(
            db_session, novel_id=str(project_id), owner_id=str(uuid.uuid4())
        )


# ---------------------------------------------------------------------------
# pack/unpack
# ---------------------------------------------------------------------------


def test_unpack_returns_none_for_legacy_payload():
    class LegacyRow:
        output_json = {"materials": []}
        result_json = None

    assert unpack_exploration_output(LegacyRow()) is None
    envelope = _sandbox_envelope()
    assert unpack_exploration_output(
        type("Row", (), {"output_json": pack_exploration_output(envelope)})()
    ).output_kind == SANDBOX_OUTPUT_KIND

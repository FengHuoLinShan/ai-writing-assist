"""临时探索结果作为正式 Scene 参考副本（M4-C）：保存、防漂移、幂等与 Writing 消费。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

import modules.evidence.facade as evidence_facade
from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.story import director_service
from modules.story.director_schemas import (
    ExplorationReferenceCopy,
    ExplorationSceneReferenceRequest,
)
from modules.story.exploration_schemas import (
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    SceneLineOutputV1,
)
from modules.story.exploration_service import (
    PROVISIONAL_SOURCE_KIND,
    pack_exploration_output,
)
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorReference,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.outline_state.models import Scene
from modules.story.tests.exploration_test_support import scene_line_payload

OWNER_ID = str(LOCAL_OWNER_ID)
LEGACY_SCENE_HASH = "a" * 64


def _scene_line_envelope(
    line: str = "你要是累了就先回去吧。", **overrides
) -> tuple[dict, str]:
    payload = scene_line_payload(line=line)
    payload.update(overrides)
    envelope = ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(payload),
    )
    packed = pack_exploration_output(envelope)
    return packed, content_hash(packed)


def _diagnostic_envelope() -> tuple[dict, str]:
    envelope = ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "target_ref": "",
                "line": "",
                "rationale": "只依据已确认空间资料判断。",
                "spatial_assessment": {
                    "supported": True,
                    "constraints": ["桌边通道只容一人侧身"],
                    "unknowns": [],
                },
            }
        ),
    )
    packed = pack_exploration_output(envelope)
    return packed, content_hash(packed)


def _sandbox_envelope() -> tuple[dict, str]:
    envelope = ExplorationOutputEnvelope(
        output_kind=SANDBOX_OUTPUT_KIND,
        schema_version=1,
        payload=SandboxOutputV1.model_validate(
            {
                "question": "重力减半后面包师的一天？",
                "influence_chain": [
                    {
                        "condition": "揉面时间不变",
                        "mechanism": "重力降低让面团发酵更快",
                        "effect": "面包更松软",
                    }
                ],
            }
        ),
    )
    packed = pack_exploration_output(envelope)
    return packed, content_hash(packed)


async def _seed_provisional_result(
    db, novel_id: str, output_json: dict, output_hash: str
):
    novel = uuid.UUID(novel_id)
    root_id, branch_id, round_id = (uuid4() for _ in range(3))
    db.add_all(
        [
            StorySceneDirectorRoot(
                id=root_id,
                novel_id=novel,
                scene_id=None,
                source_kind=PROVISIONAL_SOURCE_KIND,
                source_hash="e" * 64,
                request_json={
                    "exploration_scale": "scene_line",
                    "exploration_source_kind": "provisional",
                },
                llm_execution_snapshot_json={},
                run_envelope_json={},
                status="ready",
            ),
            StorySceneDirectorBranch(
                id=branch_id,
                novel_id=novel,
                root_id=root_id,
                branch_kind="start",
                source_hash="e" * 64,
                request_json={
                    "context_confirmation_id": "source-confirmation",
                    "confirmation_action": "story.exploration.scene_line.generate",
                },
                pending_round_json={},
                status="complete",
            ),
            StorySceneDirectorRound(
                id=round_id,
                novel_id=novel,
                root_id=root_id,
                branch_id=branch_id,
                round_number=1,
                source_hash="e" * 64,
                input_hash="f" * 64,
                output_hash=output_hash,
                input_json={},
                output_json=output_json,
                state_json={},
                run_envelope_json={},
            ),
        ]
    )
    await db.flush()
    return root_id, round_id


async def _seed_target_scene(db, novel_id: str, title: str = "雨夜站台") -> str:
    scene = Scene(novel_id=uuid.UUID(novel_id), scene_index=1, title=title)
    db.add(scene)
    await db.flush()
    return str(scene.id)


def _confirmation_stub(scene_id: str | None):
    async def fake(db, *, novel_id, action, confirmation_id, **_kwargs):
        assert action in {
            director_service.EXPLORATION_REFERENCE_CONFIRM_ACTION,
            "story.exploration.scene_line.generate",
        }
        return SimpleNamespace(compile_options={"scene_id": scene_id})

    return fake


def _request(
    novel_id: str,
    root_id,
    round_id,
    scene_id: str,
    output_hash: str,
    *,
    line: str = "你要是累了就先回去吧。",
    action: str | None = "把伞往对方那边偏了偏",
    note: str | None = "只借鉴语气",
    origin: str = "author_ui",
) -> ExplorationSceneReferenceRequest:
    return ExplorationSceneReferenceRequest(
        novel_id=novel_id,
        source_root_id=str(root_id),
        source_result_id=str(round_id),
        target_scene_id=scene_id,
        content_copy={"line": line, "action": action, "note": note},
        origin=origin,  # type: ignore[arg-type]
        expected_source_output_hash=output_hash,
        context_confirmation_id=str(uuid4()),
        confirmed=True,
    )


@pytest.fixture
async def exploration_flow(db_session, project_factory, monkeypatch):
    novel_id = str(await project_factory.create_project(title="探索参考"))
    packed, output_hash = _scene_line_envelope()
    root_id, round_id = await _seed_provisional_result(
        db_session, novel_id, packed, output_hash
    )
    scene_id = await _seed_target_scene(db_session, novel_id)
    monkeypatch.setattr(
        evidence_facade, "prepare_confirmed_ai_action", _confirmation_stub(scene_id)
    )
    return SimpleNamespace(
        db=db_session,
        novel_id=novel_id,
        root_id=root_id,
        round_id=round_id,
        scene_id=scene_id,
        output_hash=output_hash,
        owner_id=OWNER_ID,
    )


async def _reference_count(db, novel_id: str) -> int:
    rows = await db.scalars(
        select(StorySceneDirectorReference).where(
            StorySceneDirectorReference.novel_id == uuid.UUID(novel_id)
        )
    )
    return len(rows.all())


async def _round_count(db, novel_id: str) -> int:
    return len(
        (
            await db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.novel_id == uuid.UUID(novel_id)
                )
            )
        ).all()
    )


async def test_save_copies_selected_line_with_provenance_and_keeps_source_untouched(
    exploration_flow,
):
    flow = exploration_flow
    before_rounds = await _round_count(flow.db, flow.novel_id)
    result = await director_service.save_exploration_scene_reference(
        flow.db,
        flow.novel_id,
        flow.owner_id,
        _request(
            flow.novel_id, flow.root_id, flow.round_id, flow.scene_id, flow.output_hash
        ),
    )
    assert result["repeated"] is False
    assert result["advisory_only"] is True
    assert result["adoption_status"] == "not_adopted"
    row = await flow.db.get(StorySceneDirectorReference, uuid.UUID(result["id"]))
    assert str(row.root_id) == str(flow.root_id)
    assert str(row.scene_id) == flow.scene_id
    assert str(row.source_round_id) == str(flow.round_id)
    assert row.source_basis_hash == flow.output_hash
    assert row.material_ids_json == []
    assert row.angle_json == {}
    copy = row.content_copy_json
    assert copy["line"] == "你要是累了就先回去吧。"
    assert copy["action"] == "把伞往对方那边偏了偏"
    assert copy["note"] == "只借鉴语气"
    provenance = copy["provenance"]
    assert provenance["source_kind"] == "exploration"
    assert provenance["output_kind"] == SCENE_LINE_OUTPUT_KIND
    assert provenance["source_result_id"] == str(flow.round_id)
    assert provenance["source_scale"] == "scene_line"
    assert provenance["copied_at"]
    # 原探索不变：结果行未被改写，也没有新增回合行。
    round_row = await flow.db.get(StorySceneDirectorRound, flow.round_id)
    assert round_row.output_json["output_kind"] == SCENE_LINE_OUTPUT_KIND
    assert await _round_count(flow.db, flow.novel_id) == before_rounds


async def test_repeat_save_for_same_result_and_scene_is_idempotent(exploration_flow):
    flow = exploration_flow
    request = _request(
        flow.novel_id, flow.root_id, flow.round_id, flow.scene_id, flow.output_hash
    )
    first = await director_service.save_exploration_scene_reference(
        flow.db, flow.novel_id, flow.owner_id, request
    )
    second = await director_service.save_exploration_scene_reference(
        flow.db, flow.novel_id, flow.owner_id, request
    )
    assert second["id"] == first["id"] and second["repeated"] is True
    assert await _reference_count(flow.db, flow.novel_id) == 1


async def test_line_drift_is_rejected(exploration_flow):
    flow = exploration_flow
    with pytest.raises(ConflictError, match="台词与来源结果不一致"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(
                flow.novel_id,
                flow.root_id,
                flow.round_id,
                flow.scene_id,
                flow.output_hash,
                line="换一句更容易写的话。",
            ),
        )


async def test_action_drift_is_rejected(exploration_flow):
    flow = exploration_flow
    with pytest.raises(ConflictError, match="动作与来源结果不一致"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(
                flow.novel_id,
                flow.root_id,
                flow.round_id,
                flow.scene_id,
                flow.output_hash,
                action="凭空加了新动作",
            ),
        )


async def test_output_hash_mismatch_is_rejected(exploration_flow):
    flow = exploration_flow
    with pytest.raises(ConflictError, match="哈希不匹配"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(flow.novel_id, flow.root_id, flow.round_id, flow.scene_id, "0" * 64),
        )


async def test_cross_novel_source_is_hidden(exploration_flow, project_factory):
    flow = exploration_flow
    other_novel = str(await project_factory.create_project(title="另一本"))
    with pytest.raises(NotFoundError, match="导演历史不存在"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            other_novel,
            flow.owner_id,
            _request(
                other_novel,
                flow.root_id,
                flow.round_id,
                flow.scene_id,
                flow.output_hash,
            ),
        )


async def test_owner_mismatch_is_hidden(exploration_flow):
    flow = exploration_flow
    with pytest.raises(NotFoundError, match="项目不存在"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            str(uuid4()),
            _request(
                flow.novel_id,
                flow.root_id,
                flow.round_id,
                flow.scene_id,
                flow.output_hash,
            ),
        )


async def test_missing_target_scene_is_not_found(exploration_flow):
    flow = exploration_flow
    with pytest.raises(NotFoundError, match="目标 Scene 不存在"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(
                flow.novel_id,
                flow.root_id,
                flow.round_id,
                str(uuid4()),
                flow.output_hash,
            ),
        )


async def test_confirmation_scene_mismatch_is_rejected(exploration_flow, monkeypatch):
    flow = exploration_flow
    monkeypatch.setattr(
        evidence_facade, "prepare_confirmed_ai_action", _confirmation_stub(str(uuid4()))
    )
    with pytest.raises(ConflictError, match="资料确认的 Scene 与目标 Scene 不一致"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(
                flow.novel_id,
                flow.root_id,
                flow.round_id,
                flow.scene_id,
                flow.output_hash,
            ),
        )


async def test_confirmation_action_mismatch_fails_closed(exploration_flow, monkeypatch):
    flow = exploration_flow

    async def wrong_action(db, *, novel_id, action, confirmation_id, **_kwargs):
        raise ValueError("context confirmation action mismatch")

    monkeypatch.setattr(evidence_facade, "prepare_confirmed_ai_action", wrong_action)
    with pytest.raises(ValueError, match="action mismatch"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(
                flow.novel_id,
                flow.root_id,
                flow.round_id,
                flow.scene_id,
                flow.output_hash,
            ),
        )


@pytest.mark.parametrize(
    "output_builder",
    [
        lambda: _sandbox_envelope(),
        lambda: _scene_line_envelope(
            target_ref="",
            line="",
            variants=[
                {"target_ref": "c_a", "line": "第一句。", "rationale": "差异一。"},
                {"target_ref": "c_b", "line": "第二句。", "rationale": "差异二。"},
            ],
        ),
        lambda: _diagnostic_envelope(),
        lambda: ({"performances": [], "materials": []}, "c" * 64),
    ],
    ids=["sandbox", "variants", "spatial_diagnostic", "legacy_round"],
)
async def test_unsupported_result_shapes_are_rejected(
    db_session, project_factory, monkeypatch, output_builder
):
    novel_id = str(await project_factory.create_project(title="形态拒绝"))
    packed, output_hash = output_builder()
    root_id, round_id = await _seed_provisional_result(
        db_session, novel_id, packed, output_hash
    )
    scene_id = await _seed_target_scene(db_session, novel_id)
    monkeypatch.setattr(
        evidence_facade, "prepare_confirmed_ai_action", _confirmation_stub(scene_id)
    )
    with pytest.raises(ConflictError, match="该结果形态暂不支持作为参考副本"):
        await director_service.save_exploration_scene_reference(
            db_session,
            novel_id,
            OWNER_ID,
            _request(novel_id, root_id, round_id, scene_id, output_hash),
        )


async def test_non_provisional_root_is_rejected(db_session, project_factory):
    novel_id = str(await project_factory.create_project(title="旧根拒绝"))
    packed, output_hash = _scene_line_envelope()
    scene_id = await _seed_target_scene(db_session, novel_id)
    root_id, branch_id, round_id = (uuid4() for _ in range(3))
    db_session.add_all(
        [
            StorySceneDirectorRoot(
                id=root_id,
                novel_id=uuid.UUID(novel_id),
                scene_id=uuid.UUID(scene_id),
                source_hash=LEGACY_SCENE_HASH,
                request_json={"character_ids": []},
                llm_execution_snapshot_json={},
                run_envelope_json={},
                status="ready",
            ),
            StorySceneDirectorBranch(
                id=branch_id,
                novel_id=uuid.UUID(novel_id),
                root_id=root_id,
                branch_kind="start",
                source_hash=LEGACY_SCENE_HASH,
                request_json={
                    "context_confirmation_id": "source-confirmation",
                    "confirmation_action": "story.exploration.scene_line.generate",
                },
                pending_round_json={},
                status="complete",
            ),
            StorySceneDirectorRound(
                id=round_id,
                novel_id=uuid.UUID(novel_id),
                root_id=root_id,
                branch_id=branch_id,
                round_number=1,
                source_hash=LEGACY_SCENE_HASH,
                input_hash="b" * 64,
                output_hash=output_hash,
                input_json={},
                output_json=packed,
                state_json={},
                run_envelope_json={},
            ),
        ]
    )
    await db_session.flush()
    with pytest.raises(ConflictError, match="只能来自临时起点探索"):
        await director_service.save_exploration_scene_reference(
            db_session,
            novel_id,
            OWNER_ID,
            _request(novel_id, root_id, round_id, scene_id, output_hash),
        )


async def test_result_under_another_root_is_not_found(exploration_flow):
    flow = exploration_flow
    other_packed, other_hash = _scene_line_envelope(line="另一根的台词。")
    _other_root, other_round = await _seed_provisional_result(
        flow.db, flow.novel_id, other_packed, other_hash
    )
    with pytest.raises(NotFoundError, match="探索结果不存在"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(flow.novel_id, flow.root_id, other_round, flow.scene_id, other_hash),
        )


async def test_copy_must_carry_line_or_action(exploration_flow):
    flow = exploration_flow
    with pytest.raises(ValidationError):
        ExplorationSceneReferenceRequest(
            novel_id=flow.novel_id,
            source_root_id=str(flow.root_id),
            source_result_id=str(flow.round_id),
            target_scene_id=flow.scene_id,
            content_copy={"note": "只有备注"},
            origin="author_ui",
            expected_source_output_hash=flow.output_hash,
            context_confirmation_id=str(uuid4()),
            confirmed=True,
        )


def test_origin_whitelist_is_enforced_by_schema():
    payload = {
        "novel_id": str(uuid4()),
        "source_root_id": str(uuid4()),
        "source_result_id": str(uuid4()),
        "target_scene_id": str(uuid4()),
        "content_copy": {"line": "台词"},
        "origin": "worker",
        "expected_source_output_hash": "0" * 64,
        "context_confirmation_id": "c" * 8,
        "confirmed": True,
    }
    with pytest.raises(ValidationError):
        ExplorationSceneReferenceRequest.model_validate(payload)
    assert ExplorationReferenceCopy.model_validate({"line": "台词"}).line == "台词"


async def test_writing_consumption_hits_by_target_scene_and_stays_advisory(
    exploration_flow,
):
    flow = exploration_flow
    result = await director_service.save_exploration_scene_reference(
        flow.db,
        flow.novel_id,
        flow.owner_id,
        _request(
            flow.novel_id, flow.root_id, flow.round_id, flow.scene_id, flow.output_hash
        ),
    )
    from modules.story.facade import read_scene_director_references_for_writing

    read = await read_scene_director_references_for_writing(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=flow.scene_id,
        reference_ids=[result["id"]],
        consumer_action="writing.generate",
        max_chars=10000,
    )
    items = read.model_dump(mode="json")["items"]
    assert len(items) == 1
    item = items[0]
    assert item["scene_id"] == flow.scene_id
    assert item["advisory_only"] is True
    assert item["adoption_status"] == "not_adopted"
    assert item["source_changed"] is False
    assert item["current_basis_available"] is False
    assert item["content_copy"]["provenance"]["source_kind"] == "exploration"
    assert any("临时探索" in warning for warning in item["warnings"])

    other_scene = await _seed_target_scene(flow.db, flow.novel_id, title="另一场")
    omitted = await read_scene_director_references_for_writing(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=other_scene,
        reference_ids=[result["id"]],
        consumer_action="writing.generate",
        max_chars=10000,
    )
    dumped = omitted.model_dump(mode="json")
    assert dumped["items"] == []
    assert dumped["omission_reasons"] == {result["id"]: "所选副本不属于当前 Scene"}


async def test_soft_deleted_reference_is_omitted_and_resave_creates_new(exploration_flow):
    flow = exploration_flow
    result = await director_service.save_exploration_scene_reference(
        flow.db,
        flow.novel_id,
        flow.owner_id,
        _request(
            flow.novel_id, flow.root_id, flow.round_id, flow.scene_id, flow.output_hash
        ),
    )
    await director_service.delete_director_reference(flow.db, flow.novel_id, result["id"])
    from modules.story.facade import read_scene_director_references_for_writing

    read = await read_scene_director_references_for_writing(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=flow.scene_id,
        reference_ids=[result["id"]],
        consumer_action="writing.generate",
        max_chars=10000,
    )
    dumped = read.model_dump(mode="json")
    assert dumped["items"] == []
    assert (
        dumped["omission_reasons"][result["id"]] == "所选副本当前不可读取或不属于当前作品"
    )

    resaved = await director_service.save_exploration_scene_reference(
        flow.db,
        flow.novel_id,
        flow.owner_id,
        _request(
            flow.novel_id, flow.root_id, flow.round_id, flow.scene_id, flow.output_hash
        ),
    )
    assert resaved["id"] != result["id"] and resaved["repeated"] is False


async def test_legacy_reference_regression_keeps_source_recheck(
    exploration_flow, monkeypatch
):
    flow = exploration_flow
    scene_id = await _seed_target_scene(flow.db, flow.novel_id, title="旧参考场景")
    root_id, branch_id, round_id = (uuid4() for _ in range(3))
    flow.db.add_all(
        [
            StorySceneDirectorRoot(
                id=root_id,
                novel_id=uuid.UUID(flow.novel_id),
                scene_id=uuid.UUID(scene_id),
                source_hash=LEGACY_SCENE_HASH,
                request_json={"character_ids": [], "related_object_ids": []},
                llm_execution_snapshot_json={},
                run_envelope_json={},
                status="ready",
            ),
            StorySceneDirectorBranch(
                id=branch_id,
                novel_id=uuid.UUID(flow.novel_id),
                root_id=root_id,
                branch_kind="start",
                source_hash=LEGACY_SCENE_HASH,
                request_json={
                    "context_confirmation_id": "source-confirmation",
                    "confirmation_action": "story.exploration.scene_line.generate",
                },
                pending_round_json={},
                status="complete",
            ),
            StorySceneDirectorRound(
                id=round_id,
                novel_id=uuid.UUID(flow.novel_id),
                root_id=root_id,
                branch_id=branch_id,
                round_number=1,
                source_hash=LEGACY_SCENE_HASH,
                input_hash="b" * 64,
                output_hash="c" * 64,
                input_json={},
                output_json={"performances": [], "materials": []},
                state_json={},
                run_envelope_json={},
            ),
        ]
    )
    await flow.db.flush()
    record = StorySceneDirectorReference(
        novel_id=uuid.UUID(flow.novel_id),
        root_id=root_id,
        scene_id=uuid.UUID(scene_id),
        source_round_id=round_id,
        source_basis_hash=LEGACY_SCENE_HASH,
        source_deleted=False,
        name="旧式参考",
        content_copy_json={"materials": [], "angle": {}, "performances": []},
        material_ids_json=[],
        angle_json={},
        annotation="",
        origin="author_ui",
    )
    flow.db.add(record)
    await flow.db.flush()

    async def current_source(
        db, *, novel_id, scene_id, character_ids, related_object_ids
    ):
        return {"source_hash": LEGACY_SCENE_HASH}

    monkeypatch.setattr(
        "modules.story.director_context.read_director_source", current_source
    )
    from modules.story.facade import read_scene_director_references_for_writing

    read = await read_scene_director_references_for_writing(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=scene_id,
        reference_ids=[str(record.id)],
        consumer_action="writing.targeted_revision",
        max_chars=10000,
    )
    item = read.model_dump(mode="json")["items"][0]
    assert item["source_changed"] is False
    assert item["current_basis_available"] is True
    assert item["advisory_only"] is True

    async def changed_source(
        db, *, novel_id, scene_id, character_ids, related_object_ids
    ):
        return {"source_hash": "d" * 64}

    monkeypatch.setattr(
        "modules.story.director_context.read_director_source", changed_source
    )
    changed = await read_scene_director_references_for_writing(
        flow.db,
        novel_id=flow.novel_id,
        scene_id=scene_id,
        reference_ids=[str(record.id)],
        consumer_action="writing.generate",
        max_chars=10000,
    )
    changed_item = changed.model_dump(mode="json")["items"][0]
    assert changed_item["source_changed"] is True
    assert any("来源资料指纹已变化" in warning for warning in changed_item["warnings"])
    assert not any("临时探索" in warning for warning in changed_item["warnings"])


async def test_http_endpoint_saves_and_repeats_idempotently(
    exploration_flow, async_client, monkeypatch
):
    from dataclasses import replace

    from core.config import get_settings

    settings = replace(get_settings(), story_scene_director_enabled=True)
    monkeypatch.setattr("modules.story.director_feature.get_settings", lambda: settings)
    flow = exploration_flow
    monkeypatch.setattr(
        evidence_facade, "prepare_confirmed_ai_action", _confirmation_stub(flow.scene_id)
    )
    url = "/api/story/director/references/from-exploration"
    payload = {
        "novel_id": flow.novel_id,
        "source_root_id": str(flow.root_id),
        "source_result_id": str(flow.round_id),
        "target_scene_id": flow.scene_id,
        "content_copy": {
            "line": "你要是累了就先回去吧。",
            "action": "把伞往对方那边偏了偏",
            "note": "只借鉴语气",
        },
        "origin": "author_via_assistant",
        "expected_source_output_hash": flow.output_hash,
        "context_confirmation_id": str(uuid4()),
        "confirmed": True,
    }
    created = await async_client.post(url, json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["scene_id"] == flow.scene_id
    assert body["advisory_only"] is True
    assert body["content_copy"]["provenance"]["source_kind"] == "exploration"
    repeated = await async_client.post(url, json=payload)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == body["id"]
    assert repeated.json()["repeated"] is True

    bad_origin = {**payload, "origin": "worker"}
    rejected = await async_client.post(url, json=bad_origin)
    assert rejected.status_code == 422


async def test_saved_exploration_line_reaches_writing_reference_section(
    exploration_flow, monkeypatch
):
    from modules.evidence.compilation.contracts import (
        CompileOptions,
        StructureContextBundle,
    )
    from modules.evidence.compilation.services.director_reference_config import (
        DIRECTOR_REFERENCE_CAPABILITIES_ENV,
    )
    from modules.evidence.compilation.services.director_reference_sections import (
        DirectorReferenceSectionBuilder,
    )
    from modules.evidence.compilation.services.loaders.director_reference_loader import (
        DirectorReferenceLoader,
    )
    from modules.story.facade import read_scene_director_references_for_writing

    flow = exploration_flow
    saved = await director_service.save_exploration_scene_reference(
        flow.db,
        flow.novel_id,
        flow.owner_id,
        _request(
            flow.novel_id, flow.root_id, flow.round_id, flow.scene_id, flow.output_hash
        ),
    )
    monkeypatch.setenv(DIRECTOR_REFERENCE_CAPABILITIES_ENV, "writing.generate")
    bundle = StructureContextBundle(novel_id=flow.novel_id, task="正文", scope="scene")
    options = CompileOptions(
        novel_id=flow.novel_id,
        task="正文",
        scope="scene",
        scene_id=flow.scene_id,
        consumer_action="writing.generate",
        director_reference_ids=[saved["id"]],
    )
    await DirectorReferenceLoader(reader=read_scene_director_references_for_writing).load(
        flow.db, options, bundle
    )
    section = DirectorReferenceSectionBuilder.build(bundle)[0]
    assert "你要是累了就先回去吧。" in section.content
    assert "把伞往对方那边偏了偏" in section.content
    assert "只借鉴语气" in section.content
    assert section.items[0].source["adoption_status"] == "not_adopted"


async def test_copy_rejects_stale_source_confirmation_before_saving(
    exploration_flow, monkeypatch
):
    flow = exploration_flow
    original = evidence_facade.prepare_confirmed_ai_action

    async def fresh(db, **kwargs):
        if kwargs["confirmation_id"] == "source-confirmation":
            raise ConflictError("源人物知识已变")
        return await original(db, **kwargs)

    monkeypatch.setattr(evidence_facade, "prepare_confirmed_ai_action", fresh)
    with pytest.raises(ConflictError, match="源人物知识"):
        await director_service.save_exploration_scene_reference(
            flow.db,
            flow.novel_id,
            flow.owner_id,
            _request(
                flow.novel_id,
                flow.root_id,
                flow.round_id,
                flow.scene_id,
                flow.output_hash,
            ),
        )
    assert await _reference_count(flow.db, flow.novel_id) == 0

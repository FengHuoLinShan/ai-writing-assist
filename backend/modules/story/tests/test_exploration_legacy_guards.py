"""旧路径 fail-closed 守卫：探索输出行不得进入导演/推进/参考/转 World 旧链（P0 §7）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.errors import ConflictError
from modules.story.exploration_schemas import (
    SANDBOX_OUTPUT_KIND,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
)
from modules.story.exploration_service import (
    PROVISIONAL_SOURCE_KIND,
    pack_exploration_output,
    require_legacy_director_round,
    require_legacy_progression_root,
    require_legacy_reference_source,
    require_legacy_transfer_source,
)


def _exploration_payload_dict() -> dict:
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
    return pack_exploration_output(envelope)


def _legacy_round_row() -> SimpleNamespace:
    return SimpleNamespace(
        output_json={"performances": [], "materials": []}, source_hash="a" * 64
    )


def _exploration_round_row() -> SimpleNamespace:
    return SimpleNamespace(
        output_json=_exploration_payload_dict(), source_hash="a" * 64
    )


def _legacy_step_row() -> SimpleNamespace:
    return SimpleNamespace(
        result_json={"narrative_summary": "人物继续观察。"}, source_hash="a" * 64
    )


def test_director_round_guard_rejects_exploration_row_and_passes_legacy():
    with pytest.raises(ConflictError) as exc:
        require_legacy_director_round(_exploration_round_row())
    assert "紧凑探索结果" in str(exc.value)
    require_legacy_director_round(_legacy_round_row())


def test_progression_root_guard_rejects_provisional_root_and_exploration_step():
    provisional_root = SimpleNamespace(source_kind=PROVISIONAL_SOURCE_KIND)
    with pytest.raises(ConflictError) as root_exc:
        require_legacy_progression_root(provisional_root)
    assert "临时起点" in str(root_exc.value)

    legacy_root = SimpleNamespace(source_kind="scene")
    with pytest.raises(ConflictError) as step_exc:
        # 行上只有 output_json，没有 result_json：守卫须仍能识别探索输出。
        require_legacy_progression_root(legacy_root, step=_exploration_round_row())
    assert "紧凑探索结果" in str(step_exc.value)

    require_legacy_progression_root(legacy_root, step=_legacy_step_row())


def test_progression_root_guard_reads_step_result_json():
    step = SimpleNamespace(result_json=_exploration_payload_dict())
    with pytest.raises(ConflictError):
        require_legacy_progression_root(
            SimpleNamespace(source_kind="scene"), step=step
        )


def test_reference_source_guard_rejects_provisional_root_and_exploration_row():
    with pytest.raises(ConflictError) as root_exc:
        require_legacy_reference_source(
            SimpleNamespace(source_kind=PROVISIONAL_SOURCE_KIND),
            _legacy_round_row(),
        )
    assert "临时起点探索" in str(root_exc.value)

    with pytest.raises(ConflictError) as row_exc:
        require_legacy_reference_source(
            SimpleNamespace(source_kind="scene"),
            _exploration_round_row(),
        )
    assert "不能存为参考剧本" in str(row_exc.value)

    require_legacy_reference_source(
        SimpleNamespace(source_kind="scene"), _legacy_round_row()
    )


def test_transfer_source_guard_rejects_exploration_row():
    with pytest.raises(ConflictError) as exc:
        require_legacy_transfer_source(_exploration_round_row())
    assert "不能转入 World" in str(exc.value)
    require_legacy_transfer_source(_legacy_round_row())

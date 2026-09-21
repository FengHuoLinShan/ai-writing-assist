"""稳定观察身份测试（V4 T06：输出顺序改变、批次合并不重建身份）。"""

from __future__ import annotations

from modules.evolution.contracts import SourceRevisionRef
from modules.evolution.observations import (
    derive_observation_id,
    observation_semantic_fingerprint,
)

NOVEL = "0e0e0e0e-0e0e-4e0e-8e0e-0e0e0e0e0e0e"
HASH_A = "a" * 64


def _source(
    *,
    content_hash: str = HASH_A,
    draft_id: str = "draft-1",
    start: int = 0,
    end: int = 120,
    revision: int = 3,
) -> SourceRevisionRef:
    return SourceRevisionRef(
        novel_id=NOVEL,
        source_kind="chapter_draft",
        draft_id=draft_id,
        content_hash=content_hash,
        chapter_identity="chapter-1",
        start_offset=start,
        end_offset=end,
        range_hash=SourceRevisionRef.compute_range_hash(content_hash, start, end),
        source_revision=revision,
        segmentation_version=1,
        source_visibility="working",
    )


def _identity(
    *,
    source_ref: SourceRevisionRef | None = None,
    predicate: str = "青竹取出铜钥匙",
    modality: str = "event_observed",
    contract_version: int = 1,
) -> str:
    return derive_observation_id(
        source_ref=source_ref or _source(),
        predicate_or_description=predicate,
        modality=modality,  # type: ignore[arg-type]
        observer_contract_version=contract_version,
    )


def test_identity_is_stable_across_calls() -> None:
    assert _identity() == _identity()


def test_reordering_batch_does_not_change_identity() -> None:
    """身份里没有输出位置：逐条推导与批内顺序无关（T06 核心）。"""
    predicates = ["青竹取出铜钥匙", "林舟进入白石城", "钟声响起"]
    forward = [_identity(predicate=item) for item in predicates]
    backward = [_identity(predicate=item) for item in reversed(predicates)]
    assert set(forward) == set(backward)
    assert len(set(forward)) == 3


def test_same_assertion_same_range_deduplicates_across_runs() -> None:
    """观察去重：同一冻结来源上同一断言，换 run 也得到同一身份。"""
    assert _identity() == _identity()
    assert observation_semantic_fingerprint(
        source_ref=_source(),
        predicate_or_description="青竹取出铜钥匙",
        modality="event_observed",
        observer_contract_version=1,
    ) == observation_semantic_fingerprint(
        source_ref=_source(),
        predicate_or_description="青竹取出铜钥匙",
        modality="event_observed",
        observer_contract_version=1,
    )


def test_different_predicate_or_range_changes_identity() -> None:
    assert _identity() != _identity(predicate="青竹收起铜钥匙")
    assert _identity() != _identity(source_ref=_source(start=1, end=121))


def test_same_length_source_edit_changes_identity() -> None:
    """同字数正文修改改变 content_hash，观察身份随之换代（旧观察可对照）。"""
    assert _identity() != _identity(source_ref=_source(content_hash="b" * 64))


def test_method_contract_bump_creates_new_generation() -> None:
    """方法演进（契约版本提升）产生新一代观察，不静默改写旧身份。"""
    assert _identity(contract_version=1) != _identity(contract_version=2)


def test_modality_is_part_of_identity() -> None:
    """同一句话被理解为陈述还是事件，是两个不同的观察。"""
    assert _identity(modality="character_statement") != _identity(
        modality="event_observed"
    )

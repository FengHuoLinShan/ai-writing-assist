"""P2-A 契约先行单元测试：字段注册表 / FieldProvenance / 兼容读取 / timeline 受控时间。

只测本单元定义的纯结构与纯函数，不依赖 A2/A3 的投影接线。
"""

from __future__ import annotations

from dataclasses import asdict

import pytest
from pydantic import ValidationError

from modules.story.continuity.field_provenance import (
    FIELD_PROVENANCE_STATE_KEY,
    MOTIF_FIELD_REGISTRY,
    TIMELINE_WHEN_CONTROLLED_KEYS,
    FieldProvenance,
    ProvenanceSourceRef,
    ProvenanceStatus,
    TimelineWhenClause,
    extract_timeline_when,
    is_registered_motif_field,
    motif_fields_for_dimension,
    provenance_status_for,
    read_field_provenance,
    resolve_field_status,
)


def _source_ref(version_number: int = 3, **overrides: object) -> ProvenanceSourceRef:
    values: dict[str, object] = {
        "draft_id": "draft-0001",
        "chapter_index": 2,
        "version_number": version_number,
        "content_mode": "manuscript",
        "start_offset": 10,
        "end_offset": 48,
        "source_hash": "a" * 64,
        "range_hash": "b" * 64,
    }
    values.update(overrides)
    return ProvenanceSourceRef.model_validate(values)


def _provenance(
    field_key: str = "custody_holder",
    dimension: str = "entities",
    event_id: str = "11111111-1111-1111-1111-111111111111",
    sequence: int = 5,
    version: int = 3,
    with_refs: bool = True,
) -> FieldProvenance:
    return FieldProvenance(
        field_key=field_key,
        dimension=dimension,
        event_id=event_id,
        source_refs=(_source_ref(version_number=version),) if with_refs else (),
        version=version if with_refs else 0,
        recorded_at_sequence=sequence,
    )


# ============================================================
# 注册表
# ============================================================


class TestMotifFieldRegistry:
    def test_three_motifs_covered(self) -> None:
        # 人物位置（locations）
        assert is_registered_motif_field("location_id", "locations")
        assert is_registered_motif_field("text_state", "locations")
        assert is_registered_motif_field("chapter_index", "locations")
        # 物品所有者/保管者（entities）
        assert is_registered_motif_field("custody_owner", "entities")
        assert is_registered_motif_field("custody_holder", "entities")
        # 锁的有限条件（entities 锁对象 + timeline 月相事实）
        assert is_registered_motif_field("opening_key_id", "entities")
        assert is_registered_motif_field("opening_moon_phase", "entities")
        assert is_registered_motif_field("opening_passphrase", "entities")
        assert is_registered_motif_field("moon_phase", "timeline")

    def test_registry_entries_are_complete(self) -> None:
        for field in MOTIF_FIELD_REGISTRY.values():
            assert field.field_key and field.dimension and field.label
            assert field.value_kind in {
                "entity_ref",
                "text",
                "integer",
                "moon_phase_enum",
            }

    def test_unregistered_key_is_false(self) -> None:
        assert not is_registered_motif_field("custody_witness")
        assert not is_registered_motif_field("whatever")

    def test_dimension_must_match(self) -> None:
        assert is_registered_motif_field("custody_holder")
        assert not is_registered_motif_field("custody_holder", "timeline")

    def test_fields_for_dimension(self) -> None:
        timeline_fields = motif_fields_for_dimension("timeline")
        assert [f.field_key for f in timeline_fields] == ["moon_phase"]
        locations = {f.field_key for f in motif_fields_for_dimension("locations")}
        assert locations == {"location_id", "text_state", "chapter_index"}


# ============================================================
# ProvenanceSourceRef（evidence 契约镜像）
# ============================================================


class TestProvenanceSourceRef:
    def test_mirror_matches_evidence_contract(self) -> None:
        from modules.evidence.source_ref_contracts import SourceRangeRefContract

        contract = SourceRangeRefContract(
            draft_id="draft-0001",
            chapter_index=2,
            version_number=3,
            content_mode="manuscript",
            start_offset=10,
            end_offset=48,
            source_hash="a" * 64,
            range_hash="b" * 64,
        )
        mirrored = ProvenanceSourceRef.from_source_range_contract(contract)
        assert mirrored.model_dump() == asdict(contract)
        # 镜像字段集合对拍，防止 evidence 契约演进后漂移。
        assert set(SourceRangeRefContract.__dataclass_fields__) == set(
            ProvenanceSourceRef.model_fields
        )

    def test_rejects_incomplete_input(self) -> None:
        # duck-typed 转换：形状不完整（缺字段）即 ValidationError，
        # 不依赖 evidence 类型本身。
        with pytest.raises(ValidationError):
            ProvenanceSourceRef.from_source_range_contract({"draft_id": "draft-0001"})

    def test_validates_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _source_ref(version_number=0)
        with pytest.raises(ValidationError):
            _source_ref(draft_id="")


# ============================================================
# FieldProvenance 结构
# ============================================================


class TestFieldProvenanceStructure:
    def test_valid_with_refs(self) -> None:
        record = _provenance()
        assert record.field_key == "custody_holder"
        assert record.version == 3
        assert len(record.source_refs) == 1

    def test_valid_without_refs_version_zero(self) -> None:
        record = _provenance(with_refs=False)
        assert record.source_refs == ()
        assert record.version == 0

    def test_unregistered_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not registered"):
            _provenance(field_key="custody_witness")

    def test_wrong_dimension_rejected(self) -> None:
        with pytest.raises(ValidationError, match="belongs to dimension"):
            _provenance(dimension="timeline")

    def test_mismatched_ref_version_rejected(self) -> None:
        with pytest.raises(ValidationError, match="uniform"):
            FieldProvenance(
                field_key="custody_holder",
                dimension="entities",
                event_id="11111111-1111-1111-1111-111111111111",
                source_refs=(_source_ref(version_number=3),),
                version=4,  # 与 ref 的 version_number=3 不一致
                recorded_at_sequence=5,
            )

    def test_inconsistent_ref_versions_rejected(self) -> None:
        with pytest.raises(ValidationError, match="uniform"):
            FieldProvenance(
                field_key="custody_holder",
                dimension="entities",
                event_id="11111111-1111-1111-1111-111111111111",
                source_refs=(
                    _source_ref(version_number=3),
                    _source_ref(version_number=4),
                ),
                version=3,
                recorded_at_sequence=5,
            )


# ============================================================
# status 三态判定纯函数
# ============================================================


class TestResolveFieldStatus:
    def test_empty_returns_none(self) -> None:
        assert resolve_field_status([]) is None

    def test_single_chain_with_refs_is_exact(self) -> None:
        assert resolve_field_status([_provenance()]) is ProvenanceStatus.exact

    def test_single_chain_without_refs_is_unverified(self) -> None:
        assert (
            resolve_field_status([_provenance(with_refs=False)])
            is ProvenanceStatus.unverified
        )

    def test_duplicate_records_are_idempotent(self) -> None:
        record = _provenance()
        assert resolve_field_status([record, record]) is ProvenanceStatus.exact

    def test_same_sequence_distinct_chains_conflict(self) -> None:
        first = _provenance(event_id="11111111-1111-1111-1111-111111111111", sequence=7)
        second = _provenance(event_id="22222222-2222-2222-2222-222222222222", sequence=7)
        assert resolve_field_status([first, second]) is ProvenanceStatus.conflict

    def test_same_sequence_same_event_distinct_refs_conflict(self) -> None:
        first = _provenance()
        second = FieldProvenance(
            field_key="custody_holder",
            dimension="entities",
            event_id=first.event_id,
            source_refs=(_source_ref(version_number=3, range_hash="c" * 64),),
            version=3,
            recorded_at_sequence=5,
        )
        assert resolve_field_status([first, second]) is ProvenanceStatus.conflict

    def test_latest_chain_wins_over_history(self) -> None:
        # 保管转移：旧链（事件序 5）之后新链（事件序 9）胜，历史不算冲突。
        old = _provenance(
            event_id="11111111-1111-1111-1111-111111111111",
            sequence=5,
            version=3,
        )
        new = _provenance(
            event_id="22222222-2222-2222-2222-222222222222",
            sequence=9,
            version=4,
        )
        assert resolve_field_status([old, new]) is ProvenanceStatus.exact

    def test_latest_chain_without_refs_degrades_to_unverified(self) -> None:
        old = _provenance(
            event_id="11111111-1111-1111-1111-111111111111",
            sequence=5,
            with_refs=True,
        )
        new = _provenance(
            event_id="22222222-2222-2222-2222-222222222222",
            sequence=9,
            with_refs=False,
        )
        assert resolve_field_status([old, new]) is ProvenanceStatus.unverified


# ============================================================
# checkpoint 载荷兼容读取
# ============================================================


class TestReadFieldProvenance:
    def test_none_state_returns_empty(self) -> None:
        assert read_field_provenance(None) == []

    def test_non_mapping_state_returns_empty(self) -> None:
        assert read_field_provenance(["not", "a", "mapping"]) == []  # type: ignore[arg-type]

    def test_legacy_dimension_level_state_returns_empty(self) -> None:
        # 第一阶段格式：维度级 state + evidence_refs 集合，无 _field_provenance 键。
        legacy_state = {
            "entities": {
                "key-1": {
                    "id": "key-1",
                    "name": "铜钥匙",
                    "custody_holder": "char-2",
                }
            },
            "_coverage": {"unanchored_memory_event_count": 0},
        }
        assert read_field_provenance(legacy_state) == []
        # 旧格式字段查询不得冒充精确。
        assert provenance_status_for(legacy_state, "custody_holder") is None

    def test_reads_embedded_records(self) -> None:
        record = _provenance()
        state = {FIELD_PROVENANCE_STATE_KEY: [record.model_dump(mode="json")]}
        loaded = read_field_provenance(state)
        assert loaded == [record]
        assert provenance_status_for(state, "custody_holder") is ProvenanceStatus.exact

    def test_corrupt_payload_raises(self) -> None:
        with pytest.raises(ValidationError):
            read_field_provenance({FIELD_PROVENANCE_STATE_KEY: [{"field_key": 1}]})

    def test_status_for_filters_by_dimension(self) -> None:
        record = _provenance()
        state = {FIELD_PROVENANCE_STATE_KEY: [record.model_dump(mode="json")]}
        assert (
            provenance_status_for(state, "custody_holder", "entities")
            is ProvenanceStatus.exact
        )
        assert provenance_status_for(state, "custody_holder", "timeline") is None

    def test_status_for_unknown_field_returns_none(self) -> None:
        record = _provenance()
        state = {FIELD_PROVENANCE_STATE_KEY: [record.model_dump(mode="json")]}
        assert provenance_status_for(state, "not_a_registered_field") is None


# ============================================================
# timeline 受控发生时间
# ============================================================


class TestTimelineWhenClause:
    def test_scene_anchor_extracted(self) -> None:
        clause = extract_timeline_when(
            {"scene_index": 4, "scene_sequence": 12, "moon_phase": "full"}
        )
        assert clause.scene_index == 4
        assert clause.scene_sequence == 12
        assert clause.has_proof
        # 未受控键（moon_phase）不影响提取，也不进入受控子结构。
        assert clause.model_dump().get("moon_phase") is None

    def test_stated_date_kept_verbatim(self) -> None:
        clause = extract_timeline_when({"stated_date": "熙宁三年正月"})
        assert clause.stated_date == "熙宁三年正月"
        assert clause.has_proof

    def test_relative_pair_extracted(self) -> None:
        clause = extract_timeline_when(
            {"relative_to_fact_id": "fact-9", "relative_order": "after"}
        )
        assert clause.relative_order == "after"
        assert clause.has_proof

    def test_half_relative_pair_is_dropped_not_raised(self) -> None:
        clause = extract_timeline_when({"relative_to_fact_id": "fact-9"})
        assert clause.relative_to_fact_id is None
        assert not clause.has_proof

    def test_bad_types_are_tolerated(self) -> None:
        clause = extract_timeline_when(
            {
                "scene_index": True,  # bool 不当 int
                "scene_sequence": "12",  # str 不当 int
                "stated_date": 31,  # 非字符串日期不换算，视为缺失
                "relative_order": ["before"],  # 类型不符
            }
        )
        assert clause == TimelineWhenClause()
        assert not clause.has_proof

    def test_none_payload_returns_empty_clause(self) -> None:
        assert extract_timeline_when(None) == TimelineWhenClause()

    def test_direct_construction_requires_relative_pair(self) -> None:
        # 写入端直接构造时严格校验成对（与容错提取互补）。
        with pytest.raises(ValidationError, match="together"):
            TimelineWhenClause(relative_to_fact_id="fact-9")

    def test_controlled_keys_declared(self) -> None:
        assert TIMELINE_WHEN_CONTROLLED_KEYS == frozenset(
            {
                "scene_index",
                "scene_sequence",
                "relative_to_fact_id",
                "relative_order",
                "stated_date",
            }
        )

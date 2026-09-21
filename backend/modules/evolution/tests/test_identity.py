"""E02 身份解析内核测试：确定性裁决、阈值不合并、观察积累不丢（T01）。"""

from __future__ import annotations

from dataclasses import dataclass

from modules.evolution.contracts import (
    IdentityCandidate,
    MentionRef,
    ObservationEnvelope,
    SourceRevisionRef,
    StoryPosition,
)
from modules.evolution.identity import (
    candidates_from_world_results,
    resolve_mention,
    resolve_observation_mentions,
)

NOVEL = "0e0e0e0e-0e0e-4e0e-8e0e-0e0e0e0e0e0e"
LINZHOU = "2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b"
QINGZHU = "3c3c3c3c-3c3c-4c3c-8c3c-3c3c3c3c3c3c"
SHADOW = "4d4d4d4d-4d4d-4d4d-8d4d-4d4d4d4d4d4d"


def _mention(
    surface: str,
    *,
    resolved: str | None = None,
    unresolved_reason: str | None = None,
) -> MentionRef:
    return MentionRef(
        mention_id=f"m-{surface}",
        surface=surface,
        entity_type="character",
        resolved_entity_id=resolved,
        unresolved_reason=unresolved_reason
        if unresolved_reason is not None
        else (None if resolved else "首次出现未解析"),
    )


def _candidate(
    entity_id: str,
    name: str,
    kind: str | None,
    *,
    same_name: bool = False,
) -> IdentityCandidate:
    return IdentityCandidate(
        entity_id=entity_id,
        evidence=f"{kind}:{name}" if kind else f"similar:{name}",
        evidence_kind=kind,  # type: ignore[arg-type]
        same_name=same_name,
    )


def test_single_exact_match_reuses_existing_identity() -> None:
    resolution = resolve_mention(
        _mention("林舟"),
        [_candidate(LINZHOU, "林舟", "exact_name")],
    )
    assert resolution.outcome == "reuse"
    assert resolution.resolved_entity_id == LINZHOU


def test_same_name_two_people_stay_competing() -> None:
    """同名不同人：保持竞争身份，不靠顺序或分数选边。"""
    resolution = resolve_mention(
        _mention("白石"),
        [
            _candidate(LINZHOU, "白石", "exact_name"),
            _candidate(QINGZHU, "白石", "exact_name"),
        ],
    )
    assert resolution.outcome == "ambiguous"
    assert resolution.resolved_entity_id is None
    assert len(resolution.candidates) == 2


def test_similarity_threshold_never_auto_merges() -> None:
    """高相似度模糊候选不构成自动合并已采用对象的依据。"""
    resolution = resolve_mention(
        _mention("林舟儿"),
        [_candidate(LINZHOU, "林舟", "fuzzy", same_name=False)],
    )
    assert resolution.outcome == "new_candidate"
    assert resolution.resolved_entity_id is None
    assert resolution.candidates[0].entity_id == LINZHOU


def test_no_candidates_proposes_new_identity() -> None:
    resolution = resolve_mention(_mention("铜钥匙"), [])
    assert resolution.outcome == "new_candidate"
    assert resolution.candidates == []


def test_observer_binding_reverified_by_kernel() -> None:
    """观察者自带的 UUID 绑定必须经精确证据重验（E01 MentionRef 防伪造）。"""
    verified = resolve_mention(
        _mention("林舟", resolved=LINZHOU),
        [_candidate(LINZHOU, "林舟", "exact_name")],
    )
    assert verified.outcome == "reuse"
    assert verified.resolved_entity_id == LINZHOU

    unsupported = resolve_mention(
        _mention("林舟", resolved=SHADOW),
        [_candidate(LINZHOU, "林舟", "exact_name")],
    )
    assert unsupported.outcome == "ambiguous"

    fabricated = resolve_mention(_mention("林舟", resolved=SHADOW), [])
    assert fabricated.outcome == "unrelated"


def test_exact_alias_reuses_like_exact_name() -> None:
    resolution = resolve_mention(
        _mention("舟哥"),
        [_candidate(LINZHOU, "林舟", "exact_alias")],
    )
    assert resolution.outcome == "reuse"


# ---------------------------------------------------------------------------
# 观察积累：解析结论不吞并观察
# ---------------------------------------------------------------------------


@dataclass
class _StubPort:
    by_surface: dict[str, list[IdentityCandidate]]

    async def find_candidates(
        self,
        novel_id: str,
        surface: str,
        entity_type: str | None = None,
    ) -> list[IdentityCandidate]:
        assert novel_id == NOVEL
        return self.by_surface.get(surface, [])


def _observation(mentions: list[MentionRef]) -> ObservationEnvelope:
    source = SourceRevisionRef(
        novel_id=NOVEL,
        source_kind="chapter_draft",
        draft_id="draft-1",
        content_hash="a" * 64,
        chapter_identity="chapter-1",
        start_offset=0,
        end_offset=120,
        range_hash=SourceRevisionRef.compute_range_hash("a" * 64, 0, 120),
        source_revision=3,
        segmentation_version=1,
        source_visibility="working",
    )
    return ObservationEnvelope.with_stable_id(
        source_ref=source,
        observer_contract_version=1,
        mention_refs=mentions,
        predicate_or_description="林舟与青竹在白石城会面",
        modality="event_observed",
        learned_at_position=StoryPosition(scene_index=0, chapter_index=1),
        evidence_quotes=[
            {"quote": "林舟在白石城见到了青竹", "source_ref": source.model_dump()}
        ],
        producer_run_id="run-1",
        input_manifest_hash="c" * 64,
    )


async def test_resolution_never_drops_or_rebuilds_observation() -> None:
    """命中已有身份不跳过观察；观察身份（observation_id）与解析结论无关。"""
    observation = _observation(
        [
            _mention("林舟", resolved=LINZHOU),
            _mention("青竹"),
            _mention("铜钥匙"),
        ]
    )
    port = _StubPort(
        {
            "林舟": [_candidate(LINZHOU, "林舟", "exact_name")],
            "青竹": [_candidate(QINGZHU, "青竹", "exact_alias")],
            "铜钥匙": [],
        }
    )

    updated, resolutions = await resolve_observation_mentions(
        observation, candidate_port=port, novel_id=NOVEL
    )

    # 观察本体不变：同一语义身份、照常记录。
    assert updated.observation_id == observation.observation_id
    assert updated.disposition == "recorded"
    assert updated.predicate_or_description == observation.predicate_or_description

    assert {r.outcome for r in resolutions} == {"reuse", "new_candidate"}
    by_surface = {m.surface: m for m in updated.mention_refs}
    assert by_surface["林舟"].resolved_entity_id == LINZHOU
    assert by_surface["青竹"].resolved_entity_id == QINGZHU
    assert by_surface["铜钥匙"].resolved_entity_id is None
    assert by_surface["铜钥匙"].unresolved_reason == (
        "identity:new_candidate; prior=首次出现未解析"
    )


async def test_contradicting_evidence_still_recorded_as_observation() -> None:
    """反证观察照常积累：即使提及与已有身份竞争，也不吞掉该次观察。"""
    observation = _observation([_mention("白石")])
    port = _StubPort(
        {
            "白石": [
                _candidate(LINZHOU, "白石", "exact_name"),
                _candidate(QINGZHU, "白石", "exact_name"),
            ]
        }
    )

    updated, resolutions = await resolve_observation_mentions(
        observation, candidate_port=port, novel_id=NOVEL
    )
    assert updated.observation_id == observation.observation_id
    assert resolutions[0].outcome == "ambiguous"
    assert updated.mention_refs[0].unresolved_reason.startswith("identity:ambiguous")


# ---------------------------------------------------------------------------
# world 适配器
# ---------------------------------------------------------------------------


@dataclass
class _WorldSuggestion:
    existing_entity_id: str
    existing_entity_name: str
    similarity_score: float
    match_method: str


def test_world_adapter_maps_exact_and_fuzzy_evidence() -> None:
    mapped = candidates_from_world_results(
        [
            _WorldSuggestion(LINZHOU, "林舟", 1.0, "exact_name"),
            _WorldSuggestion(QINGZHU, "林舟儿", 0.92, "trgm"),
            _WorldSuggestion(SHADOW, "青竹", 0.88, "semantic_rrf"),
        ]
    )
    kinds = {c.entity_id: c.evidence_kind for c in mapped}
    assert kinds[LINZHOU] == "exact_name"
    assert kinds[QINGZHU] == "fuzzy"
    assert kinds[SHADOW] == "semantic"

    # 经适配器后，高相似度模糊候选仍不自动合并。
    resolution = resolve_mention(
        _mention("林舟儿"), [c for c in mapped if c.entity_id == QINGZHU]
    )
    assert resolution.outcome == "new_candidate"


def test_world_adapter_skips_rows_without_entity_id() -> None:
    assert (
        candidates_from_world_results([_WorldSuggestion("", "无名", 0.9, "trgm")]) == []
    )
    assert candidates_from_world_results(None) == []

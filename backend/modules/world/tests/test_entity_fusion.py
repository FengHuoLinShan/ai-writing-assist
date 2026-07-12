from __future__ import annotations

import uuid
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.entity_fusion import WorldEntityFusionService, _pair_similarity
from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import CoreEntityCreate, EntityFusionApplyItem

pytestmark = [pytest.mark.asyncio]


async def test_entity_fusion_service_has_no_direct_http_exception_dependency() -> None:
    source = (Path(__file__).resolve().parents[1] / "entity_fusion.py").read_text()

    assert "from fastapi import HTTPException" not in source
    assert "raise HTTPException" not in source


async def _create_entity(
    db: AsyncSession,
    novel_id: str,
    *,
    name: str,
    status: str,
    entity_type: str = "character",
    summary: str | None = None,
) -> str:
    repo = CoreEntityRepository()
    entity = await repo.create(
        db,
        uuid.UUID(hex=novel_id),
        CoreEntityCreate(
            name=name,
            entity_type=entity_type,
            summary=summary if summary is not None else f"{name} 摘要",
            status=status,
        ),
    )
    return str(entity.id)


def _fusion_entity(
    *,
    name: str,
    aliases: list[str] | None = None,
    summary: str | None = None,
) -> CoreEntity:
    return CoreEntity(
        name=name,
        entity_type="character",
        status="draft",
        summary=summary,
        content_json={
            "aliases": [{"alias": alias, "type": "name"} for alias in aliases or []]
        },
    )


async def test_pair_similarity_short_circuits_normalized_exact_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_summary_similarity(*args: object, **kwargs: object) -> float:
        raise AssertionError("exact name pair should not compare summaries")

    monkeypatch.setattr(
        "modules.world.entity_fusion._summary_similarity",
        fail_summary_similarity,
    )

    score, method = _pair_similarity(
        _fusion_entity(name=" 克莱恩 "),
        _fusion_entity(name="克莱恩"),
    )

    assert (score, method) == (1.0, "normalized_exact_name")


async def test_pair_similarity_short_circuits_alias_name_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_summary_similarity(*args: object, **kwargs: object) -> float:
        raise AssertionError("alias pair should not compare summaries")

    monkeypatch.setattr(
        "modules.world.entity_fusion._summary_similarity",
        fail_summary_similarity,
    )

    score, method = _pair_similarity(
        _fusion_entity(name="周明瑞"),
        _fusion_entity(name="克莱恩", aliases=["周明瑞"]),
    )

    assert (score, method) == (0.99, "alias_name_match")


async def test_pair_similarity_keeps_summary_comparison_for_substring_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def count_summary_similarity(left: str | None, right: str | None) -> float:
        nonlocal calls
        calls += 1
        assert left == "source summary"
        assert right == "target summary"
        return 0.91

    monkeypatch.setattr(
        "modules.world.entity_fusion._summary_similarity",
        count_summary_similarity,
    )

    score, method = _pair_similarity(
        _fusion_entity(name="林七", summary="source summary"),
        _fusion_entity(name="林七长老", summary="target summary"),
    )

    assert calls == 1
    assert (score, method) == (0.91, "summary_overlap")


async def test_entity_fusion_alias_only_persists_alias(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="周明瑞",
        status="draft",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="canonical",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="alias_only",
                source_entity_id=source_id,
                target_entity_id=target_id,
                alias="周明瑞",
            )
        ],
    )

    assert result["applied"] == 1
    target = await CoreEntityRepository().get(db_session, uuid.UUID(hex=target_id))
    assert target is not None
    aliases = (target.content_json or {}).get("aliases", [])
    assert any(alias.get("alias") == "周明瑞" for alias in aliases)


async def test_entity_fusion_apply_requires_domain_confirmation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        await WorldEntityFusionService().apply(
            db_session,
            novel_id=project_novel_id,
            confirmed=False,
            suggestions=[
                EntityFusionApplyItem(
                    action="alias_only",
                    source_entity_id=str(uuid.uuid4()),
                    target_entity_id=str(uuid.uuid4()),
                )
            ],
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "confirmed=true is required"


async def test_entity_fusion_canonical_merge_requires_explicit_confirmation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    source_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林七",
        status="canonical",
    )
    target_id = await _create_entity(
        db_session,
        project_novel_id,
        name="林柒",
        status="canonical",
    )

    result = await WorldEntityFusionService().apply(
        db_session,
        novel_id=project_novel_id,
        confirmed=True,
        suggestions=[
            EntityFusionApplyItem(
                action="merge",
                source_entity_id=source_id,
                target_entity_id=target_id,
            )
        ],
    )

    assert result["applied"] == 0
    assert result["skipped"] == 1
    assert "二次确认" in result["warnings"][0]


async def test_entity_fusion_apply_prefetches_suggestion_entities(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    pairs = []
    for index in range(3):
        source_id = await _create_entity(
            db_session,
            project_novel_id,
            name=f"林七-{index}",
            status="canonical",
        )
        target_id = await _create_entity(
            db_session,
            project_novel_id,
            name=f"林柒-{index}",
            status="canonical",
        )
        pairs.append((source_id, target_id))

    engine = db_session.bind.sync_engine
    entity_selects: list[str] = []

    def count_entity_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from core_entities" in normalized:
            entity_selects.append(normalized)

    event.listen(engine, "before_cursor_execute", count_entity_selects)
    try:
        result = await WorldEntityFusionService().apply(
            db_session,
            novel_id=project_novel_id,
            confirmed=True,
            suggestions=[
                EntityFusionApplyItem(
                    action="merge",
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                )
                for source_id, target_id in pairs
            ],
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_entity_selects)

    assert result["applied"] == 0
    assert result["skipped"] == 3
    assert len(entity_selects) == 1


async def test_entity_fusion_suggestion_prefers_canonical_target(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    canonical_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="canonical",
    )
    candidate_id = await _create_entity(
        db_session,
        project_novel_id,
        name="克莱恩",
        status="candidate",
    )

    result = await WorldEntityFusionService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=project_novel_id,
        max_suggestions=5,
    )

    suggestion = result["suggestions"][0]
    assert suggestion["source_entity_id"] == candidate_id
    assert suggestion["target_entity_id"] == canonical_id
    assert suggestion["source_status"] == "candidate"
    assert suggestion["target_status"] == "canonical"


async def test_entity_fusion_suggests_same_type_summary_overlap(
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_evidence_search(*args, **kwargs):
        raise AssertionError(
            "summary_overlap suggestions should use entity summary evidence"
        )

    monkeypatch.setattr(
        "modules.context.facade.search_novel_evidence",
        fail_evidence_search,
    )

    shen_lan_id = await _create_entity(
        db_session,
        project_novel_id,
        name="沈澜",
        status="draft",
        summary=(
            "女，28岁。镜局执业修复师，擅长灵镜校准。调查北港失踪案，"
            "隐藏动机是寻找八年前失踪父亲与“归一潮”的真相。"
            "与柳烨旧识，与许筠有师门情分。"
        ),
    )
    mirror_restorer_id = await _create_entity(
        db_session,
        project_novel_id,
        name="北港镜修师",
        status="draft",
        summary=(
            "女，28岁。镜局执业修复师，擅长灵镜校准。调查北港失踪案，"
            "寻找八年前失踪父亲与归一潮真相。与柳烨旧识，与许筠有师门情分。"
        ),
    )

    result = await WorldEntityFusionService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=project_novel_id,
        max_suggestions=5,
    )

    suggestion = result["suggestions"][0]
    assert suggestion["match_method"] == "summary_overlap"
    assert suggestion["action"] == "alias_only"
    assert {
        suggestion["source_entity_id"],
        suggestion["target_entity_id"],
    } == {shen_lan_id, mirror_restorer_id}

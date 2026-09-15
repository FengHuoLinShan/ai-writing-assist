"""批量知识可见性判定测试：优先级矩阵、截止点、标签授予与读者揭示交集。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.world.contracts import KnowledgeVisibilityRequest
from modules.world.facade import check_knowledge_visibility
from modules.world.models import (
    AssetKnowledgeTag,
    CharacterKnowledgeTag,
    CoreEntity,
    KnowledgeTag,
    KnowledgeTagExclusion,
    KnowledgeVisibilityPolicy,
    ReaderRevealPolicy,
)
from modules.world.models.character import CharacterKnowledge
from shared.target_ref import target_hash


async def _add(db: AsyncSession, *rows: object) -> None:
    for row in rows:
        db.add(row)
    await db.flush()


def _known_content(level: str) -> str | None:
    return "角色已知内容" if level in {"full", "partial", "rumor"} else None


def _misconception(level: str) -> str | None:
    return "角色的错误认知" if level in {"false_belief", "misunderstood"} else None


def _request(
    target_id: str,
    character_id: str | None = None,
    *,
    cutoff_chapter: int | None = None,
    apply_reader_reveal: bool = True,
) -> KnowledgeVisibilityRequest:
    return KnowledgeVisibilityRequest(
        target_type="world_entity",
        target_id=target_id,
        character_id=character_id,
        cutoff_chapter=cutoff_chapter,
        apply_reader_reveal=apply_reader_reveal,
    )


async def _entity(db: AsyncSession, novel_id: str, entity_type: str = "item") -> str:
    entity_id = uuid.uuid4()
    await _add(
        db,
        CoreEntity(
            id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type=entity_type,
            name=f"实体-{entity_id.hex[:6]}",
            summary="测试实体",
            status="canonical",
        ),
    )
    return str(entity_id)


def _ref_hash(target_id: str, target_type: str = "world_entity") -> str:
    return target_hash(
        {"target_type": target_type, "target_id": target_id, "target_path": ""}
    )


async def _knowledge(
    db: AsyncSession,
    novel_id: str,
    character_id: str,
    target_id: str,
    level: str,
    *,
    source_chapter_index: int | None = 1,
    is_public_baseline: bool = False,
) -> None:
    await _add(
        db,
        CharacterKnowledge(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=novel_id),
            character_id=uuid.UUID(hex=character_id),
            target_type="entity",
            target_id=uuid.UUID(hex=target_id),
            knowledge_level=level,
            known_content=(
                "角色已知内容" if level in {"full", "partial", "rumor"} else None
            ),
            misconception=(
                "角色的错误认知" if level in {"false_belief", "misunderstood"} else None
            ),
            source_chapter_index=source_chapter_index,
            is_public_baseline=is_public_baseline,
            status="canonical",
        ),
    )


@pytest.mark.asyncio
async def test_default_public_visible_without_any_records(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    target = await _entity(db_session, test_project_id)
    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [KnowledgeVisibilityRequest(target_type="world_entity", target_id=target,
            character_id=test_character_id)],
    )
    assert decisions[0].visible is True
    assert decisions[0].visibility_source == "public_default"
    assert decisions[0].has_reader_policy is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "visible"),
    [
        ("full", True),
        ("partial", True),
        ("rumor", True),
        ("unknown", False),
        ("restricted", False),
        ("false_belief", False),
        ("misunderstood", False),
    ],
)
async def test_character_knowledge_overrides_policy_layer(
    db_session: AsyncSession,
    test_project_id: str,
    test_character_id: str,
    level: str,
    visible: bool,
) -> None:
    target = await _entity(db_session, test_project_id)
    await _knowledge(db_session, test_project_id, test_character_id, target, level)
    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [KnowledgeVisibilityRequest(target_type="world_entity", target_id=target,
            character_id=test_character_id)],
    )
    assert decisions[0].visible is visible
    assert decisions[0].visibility_source == "character_knowledge"
    assert decisions[0].knowledge_level == level


@pytest.mark.asyncio
async def test_future_learning_ignored_before_cutoff(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    target = await _entity(db_session, test_project_id)
    # 第 5 章才学到的知识在 cutoff=3 时不得生效，回落 public default
    await _knowledge(
        db_session,
        test_project_id,
        test_character_id,
        target,
        "full",
        source_chapter_index=5,
    )
    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(
                target_type="world_entity",
                target_id=target,
                character_id=test_character_id,
                cutoff_chapter=3,
            )
        ],
    )
    assert decisions[0].visibility_source == "public_default"
    assert decisions[0].visible is True

    # 同样的知识在 cutoff=6 时覆盖 public default（unknown 场景更直观）
    target2 = await _entity(db_session, test_project_id)
    await _knowledge(
        db_session,
        test_project_id,
        test_character_id,
        target2,
        "unknown",
        source_chapter_index=5,
    )
    decisions2 = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(
                target_type="world_entity",
                target_id=target2,
                character_id=test_character_id,
                cutoff_chapter=6,
            )
        ],
    )
    assert decisions2[0].visible is False
    assert decisions2[0].knowledge_level == "unknown"


@pytest.mark.asyncio
async def test_private_policy_hidden_without_grant(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    target = await _entity(db_session, test_project_id)
    await _add(
        db_session,
        KnowledgeVisibilityPolicy(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            target={"target_type": "world_entity", "target_id": target},
            target_hash=_ref_hash(target),
            visibility_mode="private",
            policy_json={},
            status="canonical",
        ),
    )
    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [_request(target, test_character_id)],
    )
    assert decisions[0].visible is False
    assert decisions[0].visibility_source == "private_policy"
    assert "private_without_grant" in decisions[0].reasons


@pytest.mark.asyncio
async def test_tag_mode_grant_and_exclusion(
    db_session: AsyncSession, test_project_id: str
) -> None:
    target = await _entity(db_session, test_project_id)
    character_a = await _entity(db_session, test_project_id, entity_type="character")
    character_b = await _entity(db_session, test_project_id, entity_type="character")
    tag = KnowledgeTag(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=test_project_id),
        slug="circle-a",
        name="A 阵营知识",
        status="canonical",
    )
    ref_hash = _ref_hash(target)
    await _add(
        db_session,
        tag,
        KnowledgeVisibilityPolicy(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            target={"target_type": "world_entity", "target_id": target},
            target_hash=ref_hash,
            visibility_mode="tag",
            policy_json={},
            status="canonical",
        ),
        AssetKnowledgeTag(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            target={"target_type": "world_entity", "target_id": target},
            target_hash=ref_hash,
            tag_id=tag.id,
        ),
        # character_a 被授予又被作者排除；character_b 正常授予
        CharacterKnowledgeTag(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            character_id=uuid.UUID(hex=character_a),
            tag_id=tag.id,
            grant_source="manual",
            status="canonical",
        ),
        KnowledgeTagExclusion(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            character_id=uuid.UUID(hex=character_a),
            tag_id=tag.id,
        ),
        CharacterKnowledgeTag(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            character_id=uuid.UUID(hex=character_b),
            tag_id=tag.id,
            grant_source="manual",
            status="canonical",
        ),
    )
    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(
                target_type="world_entity", target_id=target, character_id=character_a
            ),
            KnowledgeVisibilityRequest(
                target_type="world_entity", target_id=target, character_id=character_b
            ),
        ],
    )
    assert decisions[0].visible is False, "授予被排除后必须隐藏"
    assert "tag_not_granted" in decisions[0].reasons
    assert decisions[1].visible is True
    assert decisions[1].visibility_source == "tag_grant"


@pytest.mark.asyncio
async def test_reader_reveal_intersects_character_visibility(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    target = await _entity(db_session, test_project_id)
    await _knowledge(db_session, test_project_id, test_character_id, target, "full")
    await _add(
        db_session,
        ReaderRevealPolicy(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            target={"target_type": "world_entity", "target_id": target},
            target_hash=_ref_hash(target),
            reveal_chapter_index=5,
            public_baseline=False,
            status="canonical",
        ),
    )

    # cutoff=3：第 5 章的揭示点未到，即使角色 full 也隐藏
    early = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(
                target_type="world_entity",
                target_id=target,
                character_id=test_character_id,
                cutoff_chapter=3,
            )
        ],
    )
    assert early[0].visible is False
    assert early[0].has_reader_policy is True
    assert early[0].reader_revealed is False
    assert "reader_reveal_pending" in early[0].reasons

    # cutoff=6：揭示点已过（保守：当章不揭示 → 第 5 章 < 6）可见
    late = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(
                target_type="world_entity",
                target_id=target,
                character_id=test_character_id,
                cutoff_chapter=6,
            )
        ],
    )
    assert late[0].visible is True
    assert late[0].reader_revealed is True

    # 关闭读者层的调用方（如 POV 叙事）不受揭示点约束
    skip = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(
                target_type="world_entity",
                target_id=target,
                character_id=test_character_id,
                cutoff_chapter=3,
                apply_reader_reveal=False,
            )
        ],
    )
    assert skip[0].visible is True


@pytest.mark.asyncio
async def test_reader_subject_and_public_baseline(
    db_session: AsyncSession, test_project_id: str
) -> None:
    target = await _entity(db_session, test_project_id)
    await _add(
        db_session,
        ReaderRevealPolicy(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            target={"target_type": "world_entity", "target_id": target},
            target_hash=_ref_hash(target),
            reveal_chapter_index=None,
            public_baseline=True,
            status="canonical",
        ),
    )
    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [KnowledgeVisibilityRequest(target_type="world_entity", target_id=target)],
    )
    assert decisions[0].visible is True
    assert decisions[0].reader_revealed is True


@pytest.mark.asyncio
async def test_conservative_when_cutoff_missing(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    target = await _entity(db_session, test_project_id)
    await _add(
        db_session,
        ReaderRevealPolicy(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=test_project_id),
            target={"target_type": "world_entity", "target_id": target},
            target_hash=_ref_hash(target),
            reveal_chapter_index=2,
            public_baseline=False,
            status="canonical",
        ),
    )
    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(
                target_type="world_entity",
                target_id=target,
                character_id=test_character_id,
            )
        ],
    )
    assert decisions[0].visible is False, "无截止点时只有 public_baseline 可见"


@pytest.mark.asyncio
async def test_batch_decisions_and_novel_isolation(
    db_session: AsyncSession, test_project_id: str
) -> None:

    other_novel = uuid.uuid4().hex
    db_session.add(
        Project(
            id=uuid.UUID(hex=other_novel),
            title="另一本书",
            language="zh",
            default_reveal_policy="author_safe",
            settings={},
        )
    )
    await db_session.flush()

    target_a = await _entity(db_session, test_project_id)
    target_b = await _entity(db_session, test_project_id)
    other_target = await _entity(db_session, other_novel)

    # 另一本书里的 private 策略不得影响本项目判定
    await _add(
        db_session,
        KnowledgeVisibilityPolicy(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=other_novel),
            target={"target_type": "world_entity", "target_id": target_a},
            target_hash=_ref_hash(target_a),
            visibility_mode="private",
            policy_json={},
            status="canonical",
        ),
    )

    decisions = await check_knowledge_visibility(
        db_session,
        test_project_id,
        [
            KnowledgeVisibilityRequest(target_type="world_entity", target_id=target_a),
            KnowledgeVisibilityRequest(target_type="world_entity", target_id=target_b),
            KnowledgeVisibilityRequest(
                target_type="world_entity", target_id=other_target
            ),
        ],
    )
    assert len(decisions) == 3
    assert decisions[0].visible is True, "跨 novel 策略不得泄露隔离"
    assert decisions[1].visible is True
    assert decisions[2].visible is True

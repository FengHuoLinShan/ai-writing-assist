"""Bounded map evaluation vocabulary reads on retained PostgreSQL, without models."""

from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.models import Project
from modules.story.outline_state.models import Scene
from modules.world import map_evaluation_read_service as service
from modules.world.project_vocabulary_models import (
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
)
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("history_size,truncated", [(2, False), (3, True)])
async def test_project_vocabulary_lineage_is_scoped_and_bounded_on_postgres(
    monkeypatch, history_size, truncated
):
    engine = create_async_engine(require_e2e_database_url(), pool_size=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_id, novel_id, scene_id, term_id, other_term_id = (uuid4() for _ in range(5))
    token = bind_principal(
        AccountPrincipal(
            account_id=owner_id,
            status="active",
            identity_type="email",
            support_code=owner_id.hex,
        )
    )
    try:
        async with sessions.begin() as db:
            db.add(Account(id=owner_id, support_code=owner_id.hex))
            db.add(Project(id=novel_id, owner_id=owner_id, title="地图评测只读范围回归"))
            await db.flush()
            db.add(
                Scene(
                    id=scene_id,
                    novel_id=novel_id,
                    scene_index=1,
                    chapter_ids=["1"],
                    status="draft",
                )
            )
            for tid in [term_id, other_term_id]:
                db.add(
                    ProjectVocabularyTerm(
                        id=tid,
                        novel_id=novel_id,
                        kind="feature",
                        source="author",
                        status="active",
                    )
                )
            await db.flush()
            for tid, count in [(other_term_id, 30), (term_id, history_size)]:
                for index in range(count):
                    evidence = [
                        {"scene_id": str(scene_id if tid == term_id else uuid4())}
                    ]
                    if tid == term_id and index > 0:
                        evidence = []
                    db.add(
                        ProjectVocabularyRevision(
                            novel_id=novel_id,
                            term_id=tid,
                            revision_number=index + 1,
                            snapshot_json={"name": "合成类型", "evidence": evidence},
                            content_hash="a" * 64,
                            change_reason="author_edit",
                        )
                    )
        monkeypatch.setattr(service, "MAX_EVALUATION_VOCABULARY_REVISIONS", 2)
        async with sessions.begin() as db:
            result = await service.read_map_spatial_evaluation_artifacts(
                db, str(novel_id), "synthetic-run", [str(scene_id)]
            )
            assert {row["id"] for row in result["vocabulary"]} == {str(term_id)}
            assert [row["revision_number"] for row in result["vocabulary"]] == [1, 2]
            assert result["vocabulary"][1]["snapshot"]["evidence"] == []
            assert result["truncated"] is truncated
            assert result["omitted_count"] == int(truncated)
            assert bool(result["missing"]) is truncated
            assert not db.new and not db.dirty and not db.deleted
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
            await db.execute(delete(Account).where(Account.id == owner_id))
        reset_principal(token)
        await engine.dispose()

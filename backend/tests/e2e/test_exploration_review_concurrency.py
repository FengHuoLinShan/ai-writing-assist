"""Exploration parent CAS under PostgreSQL row locks; synthetic assets only."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import Assumption, ProvisionalStart
from modules.project.models import Project
from modules.story import exploration_tasks
from modules.story.exploration_schemas import (
    SCENE_LINE_OUTPUT_KIND,
    ExplorationOutputEnvelope,
)
from modules.story.exploration_service import (
    create_exploration_root,
    pack_exploration_output,
    save_exploration_author_edit,
)
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.tests.exploration_test_support import scene_line_payload
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("scale", ["sandbox", "event", "scene_line"])
async def test_exploration_root_precedes_branch_foreign_key(scale):
    engine = create_async_engine(DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, owner_id=LOCAL_OWNER_ID, title="Root FK test"))
            await db.flush()
            root, branch = await create_exploration_root(
                db,
                novel_id=str(novel_id),
                owner_id=str(LOCAL_OWNER_ID),
                scale=scale,
                context_confirmation_id="synthetic-empty-confirmation",
                start=ProvisionalStart(
                    kind="provisional",
                    question="候选人物如何回应？",
                    assumptions=[Assumption(kind="state", text="人物在雨夜站台等车")],
                    time_basis="assumed_now",
                ),
            )
            assert branch.root_id == root.id
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_scene_parent_cas_waits_for_committing_author_edit(monkeypatch):
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    writer = None

    async def fresh(*args, **kwargs):
        return None

    monkeypatch.setattr(exploration_tasks, "_revalidate_result_context", fresh)
    output = ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND, payload=scene_line_payload("c_baker")
    )
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, owner_id=LOCAL_OWNER_ID, title="CAS test"))
            await db.flush()
            root, branch = await create_exploration_root(
                db,
                novel_id=str(novel_id),
                owner_id=str(LOCAL_OWNER_ID),
                scale="scene_line",
                start=ProvisionalStart(
                    kind="provisional",
                    question="候选人物如何回应？",
                    assumptions=[Assumption(kind="state", text="人物在雨夜站台等车")],
                    time_basis="assumed_now",
                ),
            )
            base = StorySceneDirectorRound(
                novel_id=novel_id,
                root_id=root.id,
                branch_id=branch.id,
                round_number=1,
                source_hash="a" * 64,
                input_hash="b" * 64,
                output_hash="c" * 64,
                input_json={},
                output_json=pack_exploration_output(output),
                state_json={},
                run_envelope_json={},
            )
            db.add(base)
            await db.flush()
            root_id, branch_id, base_id = root.id, branch.id, base.id

        attempted = asyncio.Event()

        async def write_old_parent():
            async with sessions.begin() as db:
                root = await db.get(StorySceneDirectorRoot, root_id)
                branch = await db.get(StorySceneDirectorBranch, branch_id)
                attempted.set()
                return await exploration_tasks._write_scene_result(
                    db,
                    root=root,
                    branch=branch,
                    parent_id=str(base_id),
                    envelope=output,
                    mode="detail",
                    item_path=None,
                    item_content_hash=None,
                    envelope_run=SimpleNamespace(snapshot=lambda: None),
                )

        async with sessions.begin() as db:
            edited = output.payload.model_copy(deep=True)
            edited.line = "作者刚保存的版本"
            author, _ = await save_exploration_author_edit(
                db,
                novel_id=str(novel_id),
                owner_id=str(LOCAL_OWNER_ID),
                base_result_id=str(base_id),
                edited_payload=edited,
            )
            author_id = author.id
            writer = asyncio.create_task(write_old_parent())
            await asyncio.wait_for(attempted.wait(), timeout=5)
            # The author still owns the branch lock; the worker must not write.
            done, _ = await asyncio.wait({writer}, timeout=0.1)
            assert not done

        with pytest.raises(ConflictError, match="父结果已变化"):
            await asyncio.wait_for(writer, timeout=5)
        async with sessions() as db:
            latest = await db.scalar(
                select(StorySceneDirectorRound)
                .where(StorySceneDirectorRound.branch_id == branch_id)
                .order_by(StorySceneDirectorRound.round_number.desc())
                .limit(1)
            )
            assert latest.id == author_id
    finally:
        if writer is not None:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()

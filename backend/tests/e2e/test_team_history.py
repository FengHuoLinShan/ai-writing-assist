"""PostgreSQL history invariants: 20 rounds, sibling isolation and immutable rows."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from infrastructure.llm.collaboration import content_hash
from modules.account.models import Account
from modules.interaction.ensemble import persist_actor_states, selected_actor_states
from modules.interaction.models import (
    InteractionActorStateRevision,
    InteractionJourney,
    InteractionMessageNode,
    InteractionSourceRevision,
)
from modules.project.models import Project
from modules.story.models import StorySimulationRun, StorySimulationStep

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_twenty_round_actor_state_uses_selected_ancestors_and_never_sibling(
    db_session,
):
    owner = Account(
        id=uuid.uuid4(), status="active", support_code="teams-" + uuid.uuid4().hex[:12]
    )
    db_session.add(owner)
    await db_session.flush()
    source, consumer = [
        Project(
            id=uuid.uuid4(),
            owner_id=owner.id,
            project_kind=kind,
            title="Synthetic team history",
        )
        for kind in ("author", "interaction")
    ]
    db_session.add_all([source, consumer])
    await db_session.flush()
    revision = InteractionSourceRevision(
        source_novel_id=source.id,
        owner_id=owner.id,
        version_number=1,
        title="Frozen source",
        status="ready",
        source_manifest=[],
        anchor_manifest=[],
        reference_manifest=[],
        manifest_hash="a" * 64,
        fingerprint="b" * 64,
    )
    db_session.add(revision)
    await db_session.flush()
    journey = InteractionJourney(
        novel_id=consumer.id,
        owner_id=owner.id,
        title="Journey",
        opening_text="开场",
        source_revision_id=revision.id,
        latest_activity_at=datetime.now(UTC),
    )
    db_session.add(journey)
    await db_session.flush()
    opening = InteractionMessageNode(
        novel_id=consumer.id,
        journey_id=journey.id,
        role="user",
        message_kind="setup",
        content="守住最初的约定",
    )
    db_session.add(opening)
    await db_session.flush()
    nodes, previous_ref = [opening], None
    actor = str(uuid.uuid4())
    for number in range(1, 21):
        node = InteractionMessageNode(
            novel_id=consumer.id,
            journey_id=journey.id,
            parent_node_id=nodes[-1].id,
            role="assistant",
            message_kind="story",
            content=f"第{number}轮仍记得最初约定",
        )
        db_session.add(node)
        await db_session.flush()
        state = {
            "observations": [{"action": "守住最初约定"}, {"round": number}],
            "departed": False,
        }
        attempt = SimpleNamespace(
            response_to_node_id=nodes[-1].id,
            source_revision_id=revision.id,
            agent_checkpoint_json={
                "collaboration": {
                    "protocol": "team_v1",
                    "resolved": True,
                    "source_revision_id": str(revision.id),
                    "actors": {actor: {"parent_id": previous_ref, "state": state}},
                }
            },
        )
        refs = await persist_actor_states(
            db_session, journey=journey, attempt=attempt, node=node
        )
        previous_ref = refs[0]
        nodes.append(node)
        journey.selected_leaf_node_id = node.id
    sibling = InteractionMessageNode(
        novel_id=consumer.id,
        journey_id=journey.id,
        parent_node_id=opening.id,
        role="assistant",
        message_kind="story",
        content="未选支线",
    )
    db_session.add(sibling)
    await db_session.flush()
    await persist_actor_states(
        db_session,
        journey=journey,
        attempt=SimpleNamespace(
            response_to_node_id=opening.id,
            source_revision_id=revision.id,
            agent_checkpoint_json={
                "collaboration": {
                    "protocol": "team_v1",
                    "resolved": True,
                    "source_revision_id": str(revision.id),
                    "actors": {
                        actor: {
                            "parent_id": None,
                            "state": {"observations": ["sibling-secret"]},
                        }
                    },
                }
            },
        ),
        node=sibling,
    )
    selected = await selected_actor_states(db_session, journey, nodes, revision.id)
    assert str(selected[actor].id) == previous_ref
    assert selected[actor].state_json["observations"][-1]["round"] == 20
    assert "sibling-secret" not in str(selected[actor].state_json)
    assert journey.selected_leaf_node_id == nodes[-1].id
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError, match="immutable"):
            await db_session.execute(
                update(InteractionActorStateRevision)
                .where(InteractionActorStateRevision.id == selected[actor].id)
                .values(state_json={})
            )
        await savepoint.rollback()
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError, match="immutable"):
            await db_session.execute(
                delete(InteractionActorStateRevision).where(
                    InteractionActorStateRevision.id == selected[actor].id
                )
            )
        await savepoint.rollback()
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(IntegrityError):
            db_session.add(
                InteractionActorStateRevision(
                    novel_id=source.id,
                    journey_id=journey.id,
                    message_node_id=nodes[-1].id,
                    actor_id=uuid.uuid4(),
                    source_revision_id=revision.id,
                    state_json={},
                    state_hash=content_hash({}),
                )
            )
            await db_session.flush()
        await savepoint.rollback()


async def test_story_completed_round_is_immutable_and_fork_is_scoped(db_session):
    owner = Account(
        id=uuid.uuid4(),
        status="active",
        support_code="rehearsal-" + uuid.uuid4().hex[:10],
    )
    db_session.add(owner)
    await db_session.flush()
    projects = [
        Project(id=uuid.uuid4(), owner_id=owner.id, title="Rehearsal") for _ in range(2)
    ]
    db_session.add_all(projects)
    await db_session.flush()
    root = StorySimulationRun(
        novel_id=projects[0].id, scene_id=uuid.uuid4(), source_hash="a" * 64
    )
    db_session.add(root)
    await db_session.flush()
    step = StorySimulationStep(
        novel_id=root.novel_id,
        run_id=root.id,
        round_number=1,
        input_hash="b" * 64,
        output_hash="c" * 64,
        intents_json={},
        events_json=[{"action": "门仍关闭"}],
        state_json={},
    )
    db_session.add(step)
    await db_session.flush()
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError, match="immutable"):
            await db_session.execute(
                update(StorySimulationStep)
                .where(StorySimulationStep.id == step.id)
                .values(events_json=[])
            )
        await savepoint.rollback()
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(DBAPIError, match="immutable"):
            await db_session.execute(
                delete(StorySimulationStep).where(StorySimulationStep.id == step.id)
            )
        await savepoint.rollback()
    async with db_session.begin_nested() as savepoint:
        with pytest.raises(IntegrityError):
            db_session.add(
                StorySimulationRun(
                    novel_id=projects[1].id,
                    scene_id=root.scene_id,
                    parent_id=root.id,
                    fork_round=1,
                    source_hash=root.source_hash,
                )
            )
            await db_session.flush()
        await savepoint.rollback()
    assert (
        await db_session.scalar(
            select(StorySimulationStep).where(StorySimulationStep.id == step.id)
        )
    ).events_json == [{"action": "门仍关闭"}]

    await db_session.execute(delete(Project).where(Project.id == projects[0].id))
    assert (
        await db_session.scalar(
            select(StorySimulationStep).where(StorySimulationStep.id == step.id)
        )
        is None
    )

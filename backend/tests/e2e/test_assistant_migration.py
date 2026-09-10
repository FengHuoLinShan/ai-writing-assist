"""Upgrade a disposable legacy database and keep discussion identities and links."""

import asyncio
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.base import Base
from core.errors import NotFoundError
from infrastructure.schema_comparison import (
    _compare_schema_type,
    _include_schema_object,
    _validate_migration_managed_indexes,
)
from modules.account.models import Account
from modules.assistant.models import AssistantMessage, AssistantSession
from modules.assistant.sessions import AssistantSessionService
from modules.project.models import Project
from modules.world.models.worldbuilding import CreationSuggestion
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _schema_drift(connection):
    _validate_migration_managed_indexes(connection)
    comments = connection.dialect.supports_comments
    connection.dialect.supports_comments = False
    try:
        differences = compare_metadata(
            MigrationContext.configure(
                connection,
                opts={
                    "compare_type": _compare_schema_type,
                    "include_object": _include_schema_object,
                    "compare_server_default": False,
                },
            ),
            Base.metadata,
        )
    finally:
        connection.dialect.supports_comments = comments
    records = []
    for group in differences:
        for difference in group if isinstance(group, list) else [group]:
            kind = difference[0]
            if kind in {"add_table", "remove_table"}:
                table, name = difference[1].name, ""
            elif kind in {"add_column", "remove_column"}:
                table, name = difference[2], difference[3].name
            elif kind.startswith("modify_"):
                table, name = difference[2], difference[3]
            else:
                table, name = difference[1].table.name, difference[1].name
            owned = (
                table.startswith("assistant_")
                or (
                    table == "interaction_generation_attempts"
                    and name == "agent_checkpoint_json"
                )
                or (table == "interaction_journeys" and name == "web_search_enabled")
            )
            records.append(
                {
                    "table": table,
                    "name": name,
                    "kind": kind,
                    "assistant_owned": owned,
                    "detail": re.sub(r" at 0x[0-9a-fA-F]+", "", repr(difference)),
                }
            )
    return sorted(records, key=lambda item: json.dumps(item, sort_keys=True))


async def test_legacy_discussion_identity_outcomes_and_pagination_survive_upgrade():
    base = make_url(require_e2e_database_url())
    database = "assistant_migration_e2e_" + uuid.uuid4().hex[:16]
    target = base.set(database=database)
    url = target.render_as_string(hide_password=False)
    admin = create_async_engine(base, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(target)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    created = False
    owner, novel, session_id, checkpoint_id = (uuid.uuid4() for _ in range(4))
    message_ids = [uuid.uuid4() for _ in range(43)]

    async def migrate(revision):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", revision],
            env=dict(os.environ, DATABASE_URL=url, APP_ENV="test"),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (result.stdout + result.stderr).replace(
            url, "<disposable database>"
        )

    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database}"'))
        created = True
        await migrate("20260910_world_review_phase4")
        async with engine.connect() as connection:
            before_drift = await connection.run_sync(_schema_drift)
        async with sessions.begin() as db:
            assert (
                await db.scalar(text("SELECT to_regclass('public.assistant_runs')"))
                is None
            )
            db.add(
                Account(
                    id=owner, status="active", support_code="migration-" + owner.hex[:14]
                )
            )
            await db.flush()
            db.add(Project(id=novel, owner_id=owner, title="Synthetic legacy discussion"))
            await db.flush()
            db.add(
                CreationSuggestion(
                    id=checkpoint_id,
                    novel_id=novel,
                    source_module="world",
                    review_group="world_adoption",
                    target_type="world_design_checkpoint",
                    payload_json={"schema_version": "world_design_checkpoint.v1"},
                    evidence_refs_json=[],
                    risk_level="low",
                    status="pending",
                )
            )
            db.add(
                AssistantSession(
                    id=session_id,
                    novel_id=novel,
                    title="保留原共创身份",
                    source_kind="project",
                    workflow_preset="world_core",
                    current_checkpoint_id=checkpoint_id,
                )
            )
            await db.flush()
            origin = datetime(2026, 9, 1, tzinfo=UTC)
            db.add_all(
                [
                    AssistantMessage(
                        id=message_id,
                        novel_id=novel,
                        session_id=session_id,
                        role="author" if index % 2 == 0 else "assistant",
                        content=f"旧讨论第{index + 1}条",
                        created_at=origin + timedelta(seconds=index),
                        outcome_suggestion_id=checkpoint_id if index == 41 else None,
                        outcome_kind="world_design_checkpoint" if index == 41 else None,
                    )
                    for index, message_id in enumerate(message_ids)
                ]
            )
        await migrate("head")
        async with engine.connect() as connection:
            after_drift = await connection.run_sync(_schema_drift)
        assert not [item for item in after_drift if item["assistant_owned"]]
        assert [
            item for item in before_drift if not item["assistant_owned"]
        ] == after_drift
        async with sessions() as db:
            assert (
                await db.scalar(select(func.count()).select_from(AssistantSession)) == 1
            )
            assert (
                await db.scalar(select(func.count()).select_from(AssistantMessage)) == 43
            )
            stored = await db.get(AssistantSession, session_id)
            assert stored.current_checkpoint_id == checkpoint_id
            outcome = await db.get(AssistantMessage, message_ids[41])
            assert outcome.outcome_suggestion_id == checkpoint_id
            service = AssistantSessionService()
            page, total, _offset = await service.list_messages(
                db, novel_id=str(novel), session_id=str(session_id), skip=40, limit=10
            )
            assert total == 43
            assert [str(item.id) for item in page] == [
                str(value) for value in message_ids[40:]
            ]
            with pytest.raises(NotFoundError, match="not found"):
                await service.get_detail(db, str(uuid.uuid4()), str(session_id))
            tables = await db.scalar(
                text(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                    "AND tablename LIKE 'assistant_%'"
                )
            )
            assert tables == 4
        artifact = Path(".test-artifacts/assistant-migration.json")
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text(
            json.dumps(
                {
                    "legacy_revision": "20260910_world_review_phase4",
                    "target_revision": "20260911_assistant_runtime",
                    "sessions_preserved": 1,
                    "messages_preserved": 43,
                    "checkpoint_and_outcome_links_preserved": True,
                    "history_pagination": "passed",
                    "project_isolation": "passed",
                    "new_schema_drift": [],
                    "unchanged_legacy_schema_drift": after_drift,
                    "scope": "schema upgrade and discussion recovery",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    finally:
        await engine.dispose()
        if created:
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        await admin.dispose()

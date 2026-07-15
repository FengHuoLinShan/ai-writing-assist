from __future__ import annotations

import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tools.map_subsystem_reset import (
    _MAP_REF_PATTERN,
    MAP_TABLES,
    NON_MAP_SENTINELS,
    REFERENCE_SCANS,
    Blocker,
    DatabaseIdentity,
    ForeignKeyShape,
    InspectionSnapshot,
    ReferenceFinding,
    TaskFinding,
    _classify_database_target,
    _orm_schema,
    evaluate_snapshot,
    run_backup_restore_drill,
)


def _snapshot() -> InspectionSnapshot:
    orm_tables, orm_foreign_keys = _orm_schema()
    identity = DatabaseIdentity(
        declared_environment="test",
        target_environment_classification="test",
        backend="postgresql",
        host="127.0.0.1",
        port=5432,
        database="map_reset_e2e",
        user="novelist",
        server_version="17.5",
        alembic_revision="revision-1",
        database_fingerprint="a" * 64,
    )
    return InspectionSnapshot(
        identity=identity,
        actual_map_tables=tuple(sorted(MAP_TABLES)),
        orm_map_tables=orm_tables,
        actual_foreign_keys=orm_foreign_keys,
        orm_foreign_keys=orm_foreign_keys,
        map_row_counts={table: 0 for table in MAP_TABLES},
        map_novel_counts={table: 0 for table in MAP_TABLES},
        non_map_counts={table: 0 for table in NON_MAP_SENTINELS},
        missing_reference_registry_tables=(),
        active_references=(),
        retained_references=(),
        blocking_tasks=(),
    )


def _evaluate(snapshot: InspectionSnapshot):
    return evaluate_snapshot(
        snapshot,
        expected_environment="test",
        expected_fingerprint="a" * 64,
    )


def _blocker_codes(report) -> set[str]:
    assert all(isinstance(item, Blocker) for item in report.blockers)
    return {item.code for item in report.blockers}


def test_allowlist_is_exactly_the_16_owned_map_tables() -> None:
    assert len(MAP_TABLES) == 16
    assert len(set(MAP_TABLES)) == 16
    assert set(MAP_TABLES) == {
        "map_configs",
        "map_tiles",
        "map_location_bindings",
        "map_location_layouts",
        "map_terrain_layers",
        "map_path_layers",
        "map_layer_nodes",
        "map_paths",
        "map_path_nodes",
        "map_terrain_regions",
        "map_terrain_patches",
        "map_terrain_bindings",
        "map_markers",
        "map_territory_tiles",
        "map_observations",
        "map_facts",
    }
    assert MAP_TABLES == (
        "map_facts",
        "map_observations",
        "map_path_nodes",
        "map_paths",
        "map_layer_nodes",
        "map_terrain_bindings",
        "map_terrain_patches",
        "map_terrain_regions",
        "map_terrain_layers",
        "map_path_layers",
        "map_markers",
        "map_territory_tiles",
        "map_location_bindings",
        "map_location_layouts",
        "map_tiles",
        "map_configs",
    )


def test_allowlist_order_is_child_first_for_every_cross_table_map_fk() -> None:
    _, foreign_keys = _orm_schema()
    position = {table: index for index, table in enumerate(MAP_TABLES)}

    for foreign_key in foreign_keys:
        if (
            foreign_key.source_table in position
            and foreign_key.target_table in position
            and foreign_key.source_table != foreign_key.target_table
        ):
            assert position[foreign_key.source_table] < position[foreign_key.target_table]


def test_clean_empty_snapshot_is_repeatably_ready_but_never_destructive() -> None:
    first = _evaluate(_snapshot())
    second = _evaluate(_snapshot())

    assert first == second
    assert first.ready_for_future_reset_review is True
    assert first.destructive_actions_available is False
    assert first.blockers == ()


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_is_always_rejected(environment: str) -> None:
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        identity=replace(snapshot.identity, declared_environment=environment),
    )

    report = evaluate_snapshot(
        snapshot,
        expected_environment=environment,
        expected_fingerprint=snapshot.identity.database_fingerprint,
    )

    assert "production_environment" in _blocker_codes(report)
    assert report.ready_for_future_reset_review is False


def test_environment_and_live_fingerprint_must_both_match() -> None:
    report = evaluate_snapshot(
        _snapshot(),
        expected_environment="development",
        expected_fingerprint="b" * 64,
    )

    assert _blocker_codes(report) >= {
        "environment_mismatch",
        "database_environment_mismatch",
        "database_fingerprint_mismatch",
    }


def test_live_production_like_database_is_rejected_despite_declared_test_env() -> None:
    snapshot = _snapshot()
    report = _evaluate(
        replace(
            snapshot,
            identity=replace(
                snapshot.identity,
                database="novel-production",
                target_environment_classification="production",
            ),
        )
    )

    assert "production_environment" in _blocker_codes(report)


def test_unclassified_live_database_target_fails_closed() -> None:
    snapshot = _snapshot()
    report = _evaluate(
        replace(
            snapshot,
            identity=replace(
                snapshot.identity,
                target_environment_classification="unclassified",
            ),
        )
    )

    assert "database_environment_unverified" in _blocker_codes(report)


@pytest.mark.parametrize(
    ("database", "user", "host", "connection_host", "expected"),
    [
        ("novel-production", "novelist", "10.0.0.8", "db.internal", "production"),
        ("novel_e2e", "novelist", "10.0.0.8", "db.internal", "test"),
        ("novel", "novelist", "127.0.0.1", "localhost", "development"),
        ("novel", "novelist", "10.0.0.8", "db.internal", "unclassified"),
    ],
)
def test_live_target_classification_does_not_use_declared_app_env(
    database: str,
    user: str,
    host: str,
    connection_host: str,
    expected: str,
) -> None:
    assert (
        _classify_database_target(
            database=database,
            user=user,
            server_host=host,
            connection_host=connection_host,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("actual_tables", "expected_code"),
    [
        (tuple(sorted(set(MAP_TABLES) - {"map_facts"})), "database_map_schema_drift"),
        (
            tuple(sorted((*MAP_TABLES, "map_unknown_extension"))),
            "database_map_schema_drift",
        ),
    ],
)
def test_database_schema_drift_fails_closed(
    actual_tables: tuple[str, ...],
    expected_code: str,
) -> None:
    report = _evaluate(replace(_snapshot(), actual_map_tables=actual_tables))

    assert expected_code in _blocker_codes(report)


def test_orm_schema_drift_fails_closed() -> None:
    snapshot = _snapshot()
    report = _evaluate(
        replace(
            snapshot,
            orm_map_tables=tuple(
                name for name in snapshot.orm_map_tables if name != "map_facts"
            ),
        )
    )

    assert "orm_map_schema_drift" in _blocker_codes(report)


def test_missing_non_map_sentinel_fails_closed() -> None:
    snapshot = _snapshot()
    report = _evaluate(
        replace(
            snapshot,
            non_map_counts={
                key: value
                for key, value in snapshot.non_map_counts.items()
                if key != "rag_chunks"
            },
        )
    )

    assert "non_map_sentinel_schema_drift" in _blocker_codes(report)


def test_missing_reference_registry_table_fails_closed() -> None:
    report = _evaluate(
        replace(
            _snapshot(),
            missing_reference_registry_tables=("context_confirmations",),
        )
    )

    assert "reference_registry_schema_drift" in _blocker_codes(report)


def test_reference_registry_covers_active_author_surfaces_and_source_refs() -> None:
    registry_keys = {scan.key for scan in REFERENCE_SCANS}

    assert registry_keys >= {
        "published_world_bible_pages",
        "world_bible_working_drafts",
        "current_or_pinned_world_bible_synopsis",
        "current_world_bible_page_projections",
        "active_faction_profiles",
        "active_location_profiles",
        "active_secret_profiles",
        "published_context_activation_profiles",
        "published_context_activation_revisions",
        "active_evidence_links",
        "active_asset_knowledge_tags",
        "active_knowledge_visibility_policies",
        "active_reader_reveal_policies",
        "active_conflict_queue_items",
        "active_creation_suggestions",
    }
    assert re.search(_MAP_REF_PATTERN, '{"source_type":"map_fact"}')
    assert re.search(_MAP_REF_PATTERN, '{"target_type":"map"}')


def test_retained_audit_reference_is_reported_but_does_not_block() -> None:
    retained = ReferenceFinding(
        registry_key="historical_context_confirmations",
        row_count=2,
        novel_count=1,
    )
    report = _evaluate(replace(_snapshot(), retained_references=(retained,)))

    assert report.ready_for_future_reset_review is True
    assert report.retained_references == (retained,)


def test_unknown_external_foreign_key_fails_closed() -> None:
    snapshot = _snapshot()
    external = ForeignKeyShape(
        source_table="plugin_assets",
        source_column="map_id",
        target_table="map_configs",
        target_column="id",
        on_delete="CASCADE",
    )
    report = _evaluate(
        replace(
            snapshot,
            actual_foreign_keys=tuple(sorted((*snapshot.actual_foreign_keys, external))),
        )
    )

    assert "map_foreign_key_drift" in _blocker_codes(report)
    assert "plugin_assets" in next(
        item.detail for item in report.blockers if item.code == "map_foreign_key_drift"
    )


def test_foreign_key_delete_rule_drift_fails_closed() -> None:
    snapshot = _snapshot()
    original = snapshot.actual_foreign_keys[0]
    replacement_rule = "NO ACTION" if original.on_delete != "NO ACTION" else "CASCADE"
    changed = replace(original, on_delete=replacement_rule)
    report = _evaluate(
        replace(
            snapshot,
            actual_foreign_keys=(changed, *snapshot.actual_foreign_keys[1:]),
        )
    )

    assert "map_foreign_key_drift" in _blocker_codes(report)


def test_active_reference_registry_finding_blocks_review() -> None:
    snapshot = replace(
        _snapshot(),
        active_references=(
            ReferenceFinding(
                registry_key="published_world_bible_pages",
                row_count=2,
                novel_count=1,
            ),
        ),
    )

    report = _evaluate(snapshot)

    assert "active_map_references" in _blocker_codes(report)


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
def test_map_writing_or_recovery_task_blocks_review(status: str) -> None:
    snapshot = replace(
        _snapshot(),
        blocking_tasks=(
            TaskFinding(task_type="deep_import", status=status, row_count=1),
        ),
    )

    report = _evaluate(snapshot)

    assert "map_writing_tasks" in _blocker_codes(report)


class _RecordingRunner:
    def __init__(
        self,
        fail_when=None,
        *,
        create_backup: bool = True,
        create_catalog: bool = True,
    ) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str]] = []
        self.fail_when = fail_when
        self.create_backup = create_backup
        self.create_catalog = create_catalog

    def __call__(self, args, *, env):
        command = tuple(args)
        self.commands.append(command)
        self.environments.append(dict(env))
        assert "secret" not in " ".join(command)
        if self.fail_when and self.fail_when(command):
            raise subprocess.CalledProcessError(1, command, stderr="simulated")
        if command[0] == "pg_dump" and self.create_backup:
            output = Path(command[command.index("--file") + 1])
            output.write_bytes(b"custom-format-backup")
        if command[:2] == ("pg_restore", "--list") and self.create_catalog:
            output = Path(command[command.index("--file") + 1])
            output.write_text("TABLE DATA public map_configs\n")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")


def _as_restored_snapshot(
    source: InspectionSnapshot,
    database_url: str,
) -> InspectionSnapshot:
    database = database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    return replace(
        source,
        identity=replace(
            source.identity,
            database=database,
            database_fingerprint="b" * 64,
            target_environment_classification="development",
        ),
    )


@pytest.mark.asyncio
async def test_backup_restore_drill_verifies_temp_database_and_cleans_it_up() -> None:
    source = _snapshot()
    runner = _RecordingRunner()
    loaded_urls: list[str] = []

    async def load_snapshot(database_url: str, environment: str):
        loaded_urls.append(database_url)
        assert environment == "test"
        return _as_restored_snapshot(source, database_url)

    result = await run_backup_restore_drill(
        database_url=(
            "postgresql+asyncpg://novelist:secret@127.0.0.1:5432/map_reset_e2e"
        ),
        environment="test",
        source_snapshot=source,
        command_runner=runner,
        snapshot_loader=load_snapshot,
    )

    assert result["status"] == "passed"
    assert result["backup_size_bytes"] > 0
    assert len(result["backup_sha256"]) == 64
    assert result["backup_catalog_size_bytes"] > 0
    assert "map_reset_drill_" in loaded_urls[0]
    assert [command[0] for command in runner.commands] == [
        "pg_dump",
        "pg_restore",
        "createdb",
        "pg_restore",
        "dropdb",
    ]
    assert "--dbname" in runner.commands[0]
    assert "--" in runner.commands[2]
    assert "--" in runner.commands[-1]
    assert all(env.get("PGPASSWORD") == "secret" for env in runner.environments)
    assert all("PGDATABASE" not in env for env in runner.environments)
    assert "template0" in runner.commands[2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (_RecordingRunner(create_backup=False), "non-empty backup"),
        (_RecordingRunner(create_catalog=False), "create a catalog"),
    ],
)
async def test_backup_restore_drill_rejects_missing_backup_artifacts(
    runner: _RecordingRunner,
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        await run_backup_restore_drill(
            database_url="postgresql+asyncpg://novelist@localhost/map_reset_e2e",
            environment="test",
            source_snapshot=_snapshot(),
            command_runner=runner,
        )

    assert not any(command[0] == "createdb" for command in runner.commands)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["dump", "list", "restore"])
async def test_backup_restore_drill_propagates_command_failures_and_cleans_temp_db(
    failure_stage: str,
) -> None:
    def should_fail(command: tuple[str, ...]) -> bool:
        if failure_stage == "dump":
            return command[0] == "pg_dump"
        if failure_stage == "list":
            return command[:2] == ("pg_restore", "--list")
        return command[0] == "pg_restore" and "--dbname" in command

    runner = _RecordingRunner(should_fail)

    with pytest.raises(subprocess.CalledProcessError):
        await run_backup_restore_drill(
            database_url="postgresql+asyncpg://novelist@localhost/map_reset_e2e",
            environment="test",
            source_snapshot=_snapshot(),
            command_runner=runner,
        )

    created = any(command[0] == "createdb" for command in runner.commands)
    dropped = any(command[0] == "dropdb" for command in runner.commands)
    assert dropped is created


@pytest.mark.asyncio
async def test_backup_restore_drill_rejects_restored_count_mismatch() -> None:
    source = _snapshot()
    restored = replace(
        source,
        non_map_counts={**source.non_map_counts, "projects": 99},
    )
    runner = _RecordingRunner()

    async def load_snapshot(database_url: str, environment: str):
        return _as_restored_snapshot(restored, database_url)

    with pytest.raises(RuntimeError, match="non_map_counts"):
        await run_backup_restore_drill(
            database_url="postgresql+asyncpg://novelist@localhost/map_reset_e2e",
            environment="test",
            source_snapshot=source,
            command_runner=runner,
            snapshot_loader=load_snapshot,
        )

    assert runner.commands[-1][0] == "dropdb"


@pytest.mark.asyncio
async def test_backup_restore_drill_rejects_wrong_restored_database_identity() -> None:
    source = _snapshot()
    runner = _RecordingRunner()

    async def load_snapshot(database_url: str, environment: str):
        return replace(
            source,
            identity=replace(
                source.identity,
                database_fingerprint="b" * 64,
            ),
        )

    with pytest.raises(RuntimeError, match="temporary_database_identity"):
        await run_backup_restore_drill(
            database_url="postgresql+asyncpg://novelist@localhost/map_reset_e2e",
            environment="test",
            source_snapshot=source,
            command_runner=runner,
            snapshot_loader=load_snapshot,
        )

    assert runner.commands[-1][0] == "dropdb"


@pytest.mark.asyncio
async def test_backup_restore_drill_rejects_mismatched_source_database() -> None:
    runner = _RecordingRunner()

    with pytest.raises(RuntimeError, match="Source snapshot"):
        await run_backup_restore_drill(
            database_url="postgresql+asyncpg://novelist@localhost/other_database",
            environment="test",
            source_snapshot=_snapshot(),
            command_runner=runner,
        )

    assert runner.commands == []


def test_tool_and_cli_expose_no_target_reset_branch() -> None:
    repository = Path(__file__).resolve().parents[2]
    tool_source = (repository / "tools/map_subsystem_reset.py").read_text()
    cli_source = (repository / "scripts/reset_map_subsystem.py").read_text()

    combined = f"{tool_source}\n{cli_source}".lower()
    assert "delete from" not in combined
    assert "truncate table" not in combined
    assert "drop table" not in combined
    assert '"--execute"' not in cli_source
    assert '"--yes"' not in cli_source

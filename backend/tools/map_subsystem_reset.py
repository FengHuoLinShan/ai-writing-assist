"""Fail-closed, read-only inspection for a future map subsystem reset.

This module deliberately contains no reset implementation.  It proves that a
database target, schema, references, and task queue are safe enough to discuss
a later reset.  Destructive execution needs a separate design and approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from core.base import Base

# Importing the owning module is the intentional ORM registration seam for this
# development tool.  It does not import another module's repositories/services.
from modules.world import map_models as _map_models  # noqa: F401

# Child-first order is retained for a future, separately approved design.  This
# batch only uses the tuple as a closed inspection allowlist.
MAP_TABLES: tuple[str, ...] = (
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

NON_MAP_SENTINELS: tuple[str, ...] = (
    "projects",
    "core_entities",
    "writing_drafts",
    "imported_chapters",
    "scenes",
    "world_bible_pages",
    "rag_chunks",
    "async_tasks",
)

BLOCKING_TASK_TYPES: tuple[str, ...] = (
    "deep_import",
    "deep_import_resume",
    "scene_auto_extraction",
    "world_object_auto_extraction",
    "world_alias_relation_extraction",
    "world_bible_projection_refresh",
    "world_bible_synopsis_refresh",
)

_PRODUCTION_ENVS = frozenset({"prod", "production"})
_MAP_REF_PATTERN = r'"(?:(?:target|source)_)?type"\s*:\s*"(?:map|map_fact)"'
_ENVIRONMENT_TOKEN_RE = re.compile(
    r"(?:^|[._-])"
    r"(production|prod|staging|stage|qa|testing|test|e2e|ci|"
    r"development|develop|dev|local|preview)"
    r"(?:$|[._-])",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class ForeignKeyShape:
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    on_delete: str


@dataclass(frozen=True)
class DatabaseIdentity:
    declared_environment: str
    target_environment_classification: str
    backend: str
    host: str
    port: int
    database: str
    user: str
    server_version: str
    alembic_revision: str | None
    database_fingerprint: str


@dataclass(frozen=True)
class ReferenceFinding:
    registry_key: str
    row_count: int
    novel_count: int


@dataclass(frozen=True)
class TaskFinding:
    task_type: str
    status: str
    row_count: int


@dataclass(frozen=True)
class InspectionSnapshot:
    identity: DatabaseIdentity
    actual_map_tables: tuple[str, ...]
    orm_map_tables: tuple[str, ...]
    actual_foreign_keys: tuple[ForeignKeyShape, ...]
    orm_foreign_keys: tuple[ForeignKeyShape, ...]
    map_row_counts: Mapping[str, int]
    map_novel_counts: Mapping[str, int]
    non_map_counts: Mapping[str, int]
    missing_reference_registry_tables: tuple[str, ...]
    active_references: tuple[ReferenceFinding, ...]
    retained_references: tuple[ReferenceFinding, ...]
    blocking_tasks: tuple[TaskFinding, ...]


@dataclass(frozen=True)
class Blocker:
    code: str
    detail: str


@dataclass(frozen=True)
class DryRunReport:
    operation: str
    destructive_actions_available: bool
    ready_for_future_reset_review: bool
    identity: DatabaseIdentity
    map_row_counts: Mapping[str, int]
    map_novel_counts: Mapping[str, int]
    non_map_counts: Mapping[str, int]
    active_references: tuple[ReferenceFinding, ...]
    retained_references: tuple[ReferenceFinding, ...]
    blocking_tasks: tuple[TaskFinding, ...]
    blockers: tuple[Blocker, ...]
    backup_restore_drill: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReferenceScan:
    key: str
    required_tables: tuple[str, ...]
    sql: str


REFERENCE_SCANS: tuple[ReferenceScan, ...] = (
    ReferenceScan(
        "published_world_bible_pages",
        ("world_bible_pages",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.world_bible_pages
        WHERE status IN ('active', 'canonical', 'confirmed', 'published')
          AND (
            CAST(linked_asset_refs_json AS text) ~* :map_ref_pattern
            OR CAST(sections_json AS text) ~* :map_ref_pattern
            OR CAST(page_meta_json AS text) ~* :map_ref_pattern
            OR CAST(activation_defaults_json AS text) ~* :map_ref_pattern
          )
        """,
    ),
    ReferenceScan(
        "world_bible_working_drafts",
        ("world_bible_page_drafts",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.world_bible_page_drafts
        WHERE CAST(linked_asset_refs_json AS text) ~* :map_ref_pattern
           OR CAST(sections_json AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "current_or_pinned_world_bible_synopsis",
        ("world_bible_synopsis_heads", "world_bible_synopsis_revisions"),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT r.novel_id) AS novel_count
        FROM public.world_bible_synopsis_heads AS h
        JOIN public.world_bible_synopsis_revisions AS r
          ON r.id IN (h.current_revision_id, h.pinned_revision_id)
        WHERE h.status NOT IN ('archived', 'deleted', 'deprecated')
          AND (
            CAST(r.claims_json AS text) ~* :map_ref_pattern
            OR CAST(r.source_manifest_json AS text) ~* :map_ref_pattern
          )
        """,
    ),
    ReferenceScan(
        "current_world_bible_page_projections",
        ("world_bible_pages", "world_bible_page_projections"),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT pr.novel_id) AS novel_count
        FROM public.world_bible_page_projections AS pr
        JOIN public.world_bible_pages AS p
          ON p.id = pr.page_id AND p.novel_id = pr.novel_id
        WHERE p.status IN ('active', 'canonical', 'confirmed', 'published')
          AND pr.status = 'ready'
          AND pr.stale IS FALSE
          AND pr.source_page_version = p.version_number
          AND (
            CAST(pr.source_spans_json AS text) ~* :map_ref_pattern
            OR COALESCE(pr.content, '') ~* :map_ref_pattern
          )
        """,
    ),
    ReferenceScan(
        "active_faction_profiles",
        ("faction_profiles",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.faction_profiles
        WHERE status IN ('active', 'canonical', 'confirmed', 'published')
          AND CAST(territory_refs_json AS text) NOT IN ('[]', 'null')
        """,
    ),
    ReferenceScan(
        "active_location_profiles",
        ("location_profiles",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.location_profiles
        WHERE status IN ('active', 'canonical', 'confirmed', 'published')
          AND CAST(map_refs_json AS text) NOT IN ('[]', 'null')
        """,
    ),
    ReferenceScan(
        "active_secret_profiles",
        ("secret_profiles",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.secret_profiles
        WHERE status IN ('active', 'canonical', 'confirmed', 'published')
          AND CAST(linked_target_refs_json AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "published_context_activation_profiles",
        ("context_activation_profiles",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.context_activation_profiles
        WHERE status = 'published'
          AND CAST(rules_json AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "published_context_activation_revisions",
        (
            "context_activation_profiles",
            "context_activation_profile_revisions",
        ),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT r.novel_id) AS novel_count
        FROM public.context_activation_profile_revisions AS r
        JOIN public.context_activation_profiles AS p ON p.id = r.profile_id
        WHERE p.status = 'published'
          AND r.version_number = p.version_number
          AND CAST(r.snapshot_json AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "active_evidence_links",
        ("evidence_links",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.evidence_links
        WHERE status = 'active'
          AND CAST(target_ref AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "active_asset_knowledge_tags",
        ("asset_knowledge_tags",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.asset_knowledge_tags
        WHERE COALESCE(status, '') <> 'archived'
          AND CAST(target AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "active_knowledge_visibility_policies",
        ("knowledge_visibility_policies",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.knowledge_visibility_policies
        WHERE COALESCE(status, '') <> 'archived'
          AND (
            CAST(target AS text) ~* :map_ref_pattern
            OR CAST(policy_json AS text) ~* :map_ref_pattern
          )
        """,
    ),
    ReferenceScan(
        "active_reader_reveal_policies",
        ("reader_reveal_policies",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.reader_reveal_policies
        WHERE COALESCE(status, '') <> 'archived'
          AND CAST(target AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "active_conflict_queue_items",
        ("conflict_check_queue",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.conflict_check_queue
        WHERE status IN ('pending', 'open', 'draft', 'active', 'conflicted')
          AND (
            CAST(target AS text) ~* :map_ref_pattern
            OR CAST(evidence_refs_json AS text) ~* :map_ref_pattern
            OR CAST(resolution_json AS text) ~* :map_ref_pattern
          )
        """,
    ),
    ReferenceScan(
        "active_creation_suggestions",
        ("creation_suggestion_queue",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.creation_suggestion_queue
        WHERE status IN ('pending', 'open', 'draft', 'active')
          AND (
            target_type IN ('map', 'map_fact')
            OR CAST(payload_json AS text) ~* :map_ref_pattern
            OR CAST(evidence_refs_json AS text) ~* :map_ref_pattern
            OR CAST(result_ref_json AS text) ~* :map_ref_pattern
          )
        """,
    ),
)


# These immutable/audit rows may retain references after a separately approved
# reset.  They are reported for restore/audit purposes but never treated as
# active product projections.
RETAINED_REFERENCE_SCANS: tuple[ReferenceScan, ...] = (
    ReferenceScan(
        "historical_world_bible_page_revisions",
        ("world_bible_page_revisions",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.world_bible_page_revisions
        WHERE CAST(snapshot_json AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "historical_context_confirmations",
        ("context_confirmations",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.context_confirmations
        WHERE CAST(result_refs AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "historical_context_snapshots",
        ("context_snapshots",),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT novel_id) AS novel_count
        FROM public.context_snapshots
        WHERE CAST(result_refs AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "superseded_context_activation_revisions",
        ("context_activation_profiles", "context_activation_profile_revisions"),
        """
        SELECT COUNT(*) AS row_count, COUNT(DISTINCT r.novel_id) AS novel_count
        FROM public.context_activation_profile_revisions AS r
        JOIN public.context_activation_profiles AS p ON p.id = r.profile_id
        WHERE r.version_number <> p.version_number
          AND CAST(r.snapshot_json AS text) ~* :map_ref_pattern
        """,
    ),
    ReferenceScan(
        "terminal_task_provenance",
        ("async_tasks",),
        """
        SELECT COUNT(*) AS row_count,
               COUNT(DISTINCT NULLIF(meta ->> 'novel_id', '')) AS novel_count
        FROM public.async_tasks
        WHERE status IN ('done', 'failed', 'cancelled')
          AND (
            CAST(meta AS text) ~* :map_ref_pattern
            OR CAST(result AS text) ~* :map_ref_pattern
          )
        """,
    ),
)


class CommandRunner(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


SnapshotLoader = Callable[[str, str], Awaitable[InspectionSnapshot]]


def _default_command_runner(
    args: Sequence[str],
    *,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=True,
        capture_output=True,
        text=True,
        env=dict(env),
    )


def _normalized_url(database_url: str | URL) -> URL:
    url = make_url(database_url) if isinstance(database_url, str) else database_url
    if url.get_backend_name() != "postgresql":
        raise ValueError("Map reset inspection requires PostgreSQL")
    if not url.database:
        raise ValueError("Database name is required")
    return url


def _orm_schema() -> tuple[tuple[str, ...], tuple[ForeignKeyShape, ...]]:
    table_names = tuple(
        sorted(name for name in Base.metadata.tables if name.startswith("map_"))
    )
    foreign_keys: list[ForeignKeyShape] = []
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        for foreign_key in table.foreign_keys:
            target_table, target_column = foreign_key.target_fullname.rsplit(".", 1)
            foreign_keys.append(
                ForeignKeyShape(
                    source_table=table_name,
                    source_column=foreign_key.parent.name,
                    target_table=target_table,
                    target_column=target_column,
                    on_delete=(foreign_key.ondelete or "NO ACTION").upper(),
                )
            )
    return table_names, tuple(sorted(foreign_keys))


def _identity_fingerprint(parts: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        parts,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _environment_family(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "prod": "production",
        "production": "production",
        "test": "test",
        "testing": "test",
        "e2e": "test",
        "ci": "test",
        "stage": "staging",
        "staging": "staging",
        "qa": "staging",
        "dev": "development",
        "develop": "development",
        "development": "development",
        "local": "development",
        "preview": "preview",
    }
    return aliases.get(normalized, normalized)


def _classify_database_target(
    *,
    database: str,
    user: str,
    server_host: str,
    connection_host: str | None,
) -> str:
    """Classify the live target without trusting the caller's APP_ENV value."""

    tokens: list[str] = []
    for value in (database, user, connection_host or ""):
        tokens.extend(
            match.group(1).lower() for match in _ENVIRONMENT_TOKEN_RE.finditer(value)
        )
    families = {_environment_family(token) for token in tokens}
    for family in ("production", "test", "staging", "preview", "development"):
        if family in families:
            return family

    host = server_host.strip().strip("[]")
    try:
        if ipaddress.ip_address(host).is_loopback:
            return "development"
    except ValueError:
        pass
    if host == "<local-socket>" or (connection_host or "").startswith("/"):
        return "development"
    if (connection_host or "").strip().lower() == "localhost":
        return "development"
    return "unclassified"


async def _all_public_tables(connection: AsyncConnection) -> set[str]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                """
            )
        )
    ).scalars()
    return {str(value) for value in rows}


async def _collect_identity(
    connection: AsyncConnection,
    *,
    url: URL,
    environment: str,
) -> DatabaseIdentity:
    row = (
        (
            await connection.execute(
                text(
                    """
                SELECT current_database() AS database,
                       current_user AS database_user,
                       current_setting('server_version') AS server_version,
                       (SELECT oid FROM pg_database
                        WHERE datname = current_database()) AS database_oid,
                       host(inet_server_addr()) AS server_address,
                       inet_server_port() AS server_port
                """
                )
            )
        )
        .mappings()
        .one()
    )
    revision = (
        await connection.execute(
            text(
                """
                SELECT CASE
                    WHEN to_regclass('public.alembic_version') IS NULL THEN NULL
                    ELSE (
                      SELECT string_agg(version_num, ',' ORDER BY version_num)
                      FROM public.alembic_version
                    )
                END
                """
            )
        )
    ).scalar_one_or_none()
    host = str(row["server_address"] or url.host or "<local-socket>")
    port = int(row["server_port"] or url.port or 5432)
    database = str(row["database"])
    user = str(row["database_user"])
    server_version = str(row["server_version"])
    target_environment_classification = _classify_database_target(
        database=database,
        user=user,
        server_host=host,
        connection_host=url.host,
    )
    fingerprint = _identity_fingerprint(
        {
            "backend": "postgresql",
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "server_version": server_version,
            "database_oid": int(row["database_oid"]),
        }
    )
    return DatabaseIdentity(
        declared_environment=environment.strip().lower(),
        target_environment_classification=target_environment_classification,
        backend="postgresql",
        host=host,
        port=port,
        database=database,
        user=user,
        server_version=server_version,
        alembic_revision=str(revision) if revision is not None else None,
        database_fingerprint=fingerprint,
    )


async def _collect_foreign_keys(
    connection: AsyncConnection,
) -> tuple[ForeignKeyShape, ...]:
    rows = (
        await connection.execute(
            text(
                """
                SELECT source_kcu.table_name AS source_table,
                       source_kcu.column_name AS source_column,
                       target_kcu.table_name AS target_table,
                       target_kcu.column_name AS target_column,
                       rc.delete_rule AS on_delete
                FROM information_schema.referential_constraints AS rc
                JOIN information_schema.key_column_usage AS source_kcu
                  ON source_kcu.constraint_catalog = rc.constraint_catalog
                 AND source_kcu.constraint_schema = rc.constraint_schema
                 AND source_kcu.constraint_name = rc.constraint_name
                JOIN information_schema.key_column_usage AS target_kcu
                  ON target_kcu.constraint_catalog = rc.unique_constraint_catalog
                 AND target_kcu.constraint_schema = rc.unique_constraint_schema
                 AND target_kcu.constraint_name = rc.unique_constraint_name
                 AND target_kcu.ordinal_position =
                     source_kcu.position_in_unique_constraint
                WHERE source_kcu.table_schema = 'public'
                  AND target_kcu.table_schema = 'public'
                  AND (
                    source_kcu.table_name LIKE 'map\\_%' ESCAPE '\\'
                    OR target_kcu.table_name LIKE 'map\\_%' ESCAPE '\\'
                  )
                """
            )
        )
    ).mappings()
    return tuple(
        sorted(
            ForeignKeyShape(
                source_table=str(row["source_table"]),
                source_column=str(row["source_column"]),
                target_table=str(row["target_table"]),
                target_column=str(row["target_column"]),
                on_delete=str(row["on_delete"]).upper(),
            )
            for row in rows
        )
    )


async def _table_counts(
    connection: AsyncConnection,
    existing_tables: set[str],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    rows: dict[str, int] = {}
    novels: dict[str, int] = {}
    for table_name in MAP_TABLES:
        if table_name not in existing_tables:
            continue
        result = (
            (
                await connection.execute(
                    text(
                        f"SELECT COUNT(*) AS rows, "
                        f"COUNT(DISTINCT novel_id) AS novels "
                        f'FROM public."{table_name}"'
                    )
                )
            )
            .mappings()
            .one()
        )
        rows[table_name] = int(result["rows"])
        novels[table_name] = int(result["novels"])

    non_map: dict[str, int] = {}
    for table_name in NON_MAP_SENTINELS:
        if table_name not in existing_tables:
            continue
        value = await connection.scalar(
            text(f'SELECT COUNT(*) FROM public."{table_name}"')
        )
        non_map[table_name] = int(value or 0)
    return rows, novels, non_map


async def _reference_findings(
    connection: AsyncConnection,
    existing_tables: set[str],
    scans: Sequence[ReferenceScan],
) -> tuple[tuple[ReferenceFinding, ...], tuple[str, ...]]:
    findings: list[ReferenceFinding] = []
    missing_tables: set[str] = set()
    for scan in scans:
        missing = set(scan.required_tables) - existing_tables
        if missing:
            missing_tables.update(missing)
            continue
        row = (
            (
                await connection.execute(
                    text(scan.sql),
                    {"map_ref_pattern": _MAP_REF_PATTERN},
                )
            )
            .mappings()
            .one()
        )
        row_count = int(row["row_count"])
        if row_count:
            findings.append(
                ReferenceFinding(
                    registry_key=scan.key,
                    row_count=row_count,
                    novel_count=int(row["novel_count"]),
                )
            )
    return tuple(findings), tuple(sorted(missing_tables))


async def _blocking_task_findings(
    connection: AsyncConnection,
    existing_tables: set[str],
) -> tuple[TaskFinding, ...]:
    if "async_tasks" not in existing_tables:
        return ()
    type_literals = ", ".join(f"'{value}'" for value in BLOCKING_TASK_TYPES)
    rows = (
        await connection.execute(
            text(
                rf"""
                SELECT task_type, status, COUNT(*) AS row_count
                FROM public.async_tasks
                WHERE (task_type IN ({type_literals}) OR task_type LIKE 'map\_%')
                  AND (
                    status IN ('pending', 'running')
                    OR (
                      status = 'failed'
                      AND (
                        COALESCE(meta ->> 'recovery_required', 'false') = 'true'
                        OR COALESCE(result ->> 'recovery_required', 'false') = 'true'
                      )
                    )
                  )
                GROUP BY task_type, status
                ORDER BY task_type, status
                """
            )
        )
    ).mappings()
    return tuple(
        TaskFinding(
            task_type=str(row["task_type"]),
            status=str(row["status"]),
            row_count=int(row["row_count"]),
        )
        for row in rows
    )


async def inspect_database(
    database_url: str,
    environment: str,
) -> InspectionSnapshot:
    """Collect one read-only snapshot using an explicit database URL."""

    url = _normalized_url(database_url)
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                existing_tables = await _all_public_tables(connection)
                identity = await _collect_identity(
                    connection,
                    url=url,
                    environment=environment,
                )
                actual_map_tables = tuple(
                    sorted(name for name in existing_tables if name.startswith("map_"))
                )
                actual_foreign_keys = await _collect_foreign_keys(connection)
                row_counts, novel_counts, non_map_counts = await _table_counts(
                    connection,
                    existing_tables,
                )
                references, active_scan_missing = await _reference_findings(
                    connection,
                    existing_tables,
                    REFERENCE_SCANS,
                )
                retained_references, retained_scan_missing = await _reference_findings(
                    connection,
                    existing_tables,
                    RETAINED_REFERENCE_SCANS,
                )
                tasks = await _blocking_task_findings(
                    connection,
                    existing_tables,
                )
    finally:
        await engine.dispose()

    orm_tables, orm_foreign_keys = _orm_schema()
    return InspectionSnapshot(
        identity=identity,
        actual_map_tables=actual_map_tables,
        orm_map_tables=orm_tables,
        actual_foreign_keys=actual_foreign_keys,
        orm_foreign_keys=orm_foreign_keys,
        map_row_counts=row_counts,
        map_novel_counts=novel_counts,
        non_map_counts=non_map_counts,
        missing_reference_registry_tables=tuple(
            sorted(set(active_scan_missing) | set(retained_scan_missing))
        ),
        active_references=references,
        retained_references=retained_references,
        blocking_tasks=tasks,
    )


def evaluate_snapshot(
    snapshot: InspectionSnapshot,
    *,
    expected_environment: str,
    expected_fingerprint: str,
) -> DryRunReport:
    """Evaluate all fail-closed gates without mutating the snapshot or database."""

    blockers: list[Blocker] = []
    actual_environment = snapshot.identity.declared_environment.strip().lower()
    expected_environment = expected_environment.strip().lower()
    target_environment = snapshot.identity.target_environment_classification
    if (
        actual_environment in _PRODUCTION_ENVS
        or expected_environment in _PRODUCTION_ENVS
        or target_environment == "production"
    ):
        blockers.append(Blocker("production_environment", "production is never allowed"))
    if not expected_environment or expected_environment != actual_environment:
        blockers.append(
            Blocker(
                "environment_mismatch",
                (
                    f"expected={expected_environment or '<missing>'}, "
                    f"actual={actual_environment}"
                ),
            )
        )
    expected_family = _environment_family(expected_environment)
    if target_environment == "unclassified":
        blockers.append(
            Blocker(
                "database_environment_unverified",
                "live database target has no non-production environment marker",
            )
        )
    elif target_environment != expected_family:
        blockers.append(
            Blocker(
                "database_environment_mismatch",
                f"expected={expected_family}, live_target={target_environment}",
            )
        )
    if not expected_fingerprint or (
        expected_fingerprint != snapshot.identity.database_fingerprint
    ):
        blockers.append(Blocker("database_fingerprint_mismatch", "fingerprint mismatch"))

    allowlist = set(MAP_TABLES)
    actual_tables = set(snapshot.actual_map_tables)
    orm_tables = set(snapshot.orm_map_tables)
    if actual_tables != allowlist:
        blockers.append(
            Blocker(
                "database_map_schema_drift",
                _set_difference_detail(allowlist, actual_tables),
            )
        )
    if orm_tables != allowlist:
        blockers.append(
            Blocker(
                "orm_map_schema_drift",
                _set_difference_detail(allowlist, orm_tables),
            )
        )
    missing_non_map_sentinels = set(NON_MAP_SENTINELS) - set(snapshot.non_map_counts)
    if missing_non_map_sentinels:
        blockers.append(
            Blocker(
                "non_map_sentinel_schema_drift",
                f"missing={sorted(missing_non_map_sentinels)}",
            )
        )
    if snapshot.missing_reference_registry_tables:
        blockers.append(
            Blocker(
                "reference_registry_schema_drift",
                f"missing={list(snapshot.missing_reference_registry_tables)}",
            )
        )

    actual_foreign_keys = set(snapshot.actual_foreign_keys)
    orm_foreign_keys = set(snapshot.orm_foreign_keys)
    if actual_foreign_keys != orm_foreign_keys:
        blockers.append(
            Blocker(
                "map_foreign_key_drift",
                _foreign_key_difference_detail(
                    expected=orm_foreign_keys,
                    actual=actual_foreign_keys,
                ),
            )
        )
    if snapshot.active_references:
        blockers.append(
            Blocker(
                "active_map_references",
                f"{sum(item.row_count for item in snapshot.active_references)} rows",
            )
        )
    if snapshot.blocking_tasks:
        blockers.append(
            Blocker(
                "map_writing_tasks",
                f"{sum(item.row_count for item in snapshot.blocking_tasks)} tasks",
            )
        )

    return DryRunReport(
        operation="map_subsystem_reset_dry_run",
        destructive_actions_available=False,
        ready_for_future_reset_review=not blockers,
        identity=snapshot.identity,
        map_row_counts=dict(snapshot.map_row_counts),
        map_novel_counts=dict(snapshot.map_novel_counts),
        non_map_counts=dict(snapshot.non_map_counts),
        active_references=snapshot.active_references,
        retained_references=snapshot.retained_references,
        blocking_tasks=snapshot.blocking_tasks,
        blockers=tuple(blockers),
    )


def _set_difference_detail(expected: set[str], actual: set[str]) -> str:
    return f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"


def _foreign_key_difference_detail(
    *,
    expected: set[ForeignKeyShape],
    actual: set[ForeignKeyShape],
) -> str:
    missing = [asdict(item) for item in sorted(expected - actual)]
    extra = [asdict(item) for item in sorted(actual - expected)]
    return json.dumps({"missing": missing, "extra": extra}, sort_keys=True)


def _command_environment(url: URL) -> dict[str, str]:
    environment = dict(os.environ)
    for key in (
        "PGDATABASE",
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGUSER",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGOPTIONS",
        "PGTARGETSESSIONATTRS",
    ):
        environment.pop(key, None)
    if url.password:
        environment["PGPASSWORD"] = url.password
    else:
        environment.pop("PGPASSWORD", None)
    return environment


def _connection_flags(url: URL) -> list[str]:
    flags: list[str] = []
    if url.host:
        flags.extend(("--host", url.host))
    flags.extend(("--port", str(url.port or 5432)))
    if url.username:
        flags.extend(("--username", url.username))
    return flags


def _file_sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


async def run_backup_restore_drill(
    *,
    database_url: str,
    environment: str,
    source_snapshot: InspectionSnapshot,
    command_runner: CommandRunner = _default_command_runner,
    snapshot_loader: SnapshotLoader = inspect_database,
) -> Mapping[str, Any]:
    """Back up and restore into a unique temporary database, never the target."""

    url = _normalized_url(database_url)
    if source_snapshot.identity.database != str(url.database):
        raise RuntimeError("Source snapshot does not match the requested database")
    temporary_database = f"map_reset_drill_{uuid.uuid4().hex[:16]}"
    environment_vars = _command_environment(url)
    flags = _connection_flags(url)
    temp_url = url.set(database=temporary_database)
    restored_created = False

    with tempfile.TemporaryDirectory(prefix="map-reset-drill-") as temp_dir:
        backup_path = Path(temp_dir) / "map-subsystem-reset.dump"
        backup_catalog_path = Path(temp_dir) / "map-subsystem-reset.list"
        try:
            command_runner(
                (
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--file",
                    str(backup_path),
                    *flags,
                    "--dbname",
                    str(url.database),
                ),
                env=environment_vars,
            )
            if not backup_path.is_file() or backup_path.stat().st_size <= 0:
                raise RuntimeError("pg_dump did not create a non-empty backup")
            backup_size, backup_sha256 = _file_sha256(backup_path)
            command_runner(
                (
                    "pg_restore",
                    "--list",
                    "--file",
                    str(backup_catalog_path),
                    str(backup_path),
                ),
                env=environment_vars,
            )
            if (
                not backup_catalog_path.is_file()
                or backup_catalog_path.stat().st_size <= 0
            ):
                raise RuntimeError("pg_restore --list did not create a catalog")
            command_runner(
                (
                    "createdb",
                    *flags,
                    "--template",
                    "template0",
                    "--",
                    temporary_database,
                ),
                env=environment_vars,
            )
            restored_created = True
            command_runner(
                (
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    temporary_database,
                    *flags,
                    str(backup_path),
                ),
                env=environment_vars,
            )
            restored = await snapshot_loader(
                temp_url.render_as_string(hide_password=False),
                environment,
            )
            mismatches: list[str] = []
            if restored.identity.database != temporary_database:
                mismatches.append("temporary_database_identity")
            if (
                restored.identity.database_fingerprint
                == source_snapshot.identity.database_fingerprint
            ):
                mismatches.append("temporary_database_fingerprint")
            for field in ("host", "port", "user", "server_version"):
                if getattr(restored.identity, field) != getattr(
                    source_snapshot.identity,
                    field,
                ):
                    mismatches.append(f"database_identity.{field}")
            if (
                restored.identity.alembic_revision
                != source_snapshot.identity.alembic_revision
            ):
                mismatches.append("alembic_revision")
            if restored.actual_map_tables != source_snapshot.actual_map_tables:
                mismatches.append("actual_map_tables")
            if restored.actual_foreign_keys != source_snapshot.actual_foreign_keys:
                mismatches.append("actual_foreign_keys")
            if dict(restored.map_row_counts) != dict(source_snapshot.map_row_counts):
                mismatches.append("map_row_counts")
            if dict(restored.map_novel_counts) != dict(source_snapshot.map_novel_counts):
                mismatches.append("map_novel_counts")
            if dict(restored.non_map_counts) != dict(source_snapshot.non_map_counts):
                mismatches.append("non_map_counts")
            if (
                restored.missing_reference_registry_tables
                != source_snapshot.missing_reference_registry_tables
            ):
                mismatches.append("reference_registry_schema")
            if restored.active_references != source_snapshot.active_references:
                mismatches.append("active_references")
            if restored.retained_references != source_snapshot.retained_references:
                mismatches.append("retained_references")
            if restored.blocking_tasks != source_snapshot.blocking_tasks:
                mismatches.append("blocking_tasks")
            if mismatches:
                raise RuntimeError(
                    "Restored database verification failed: " + ", ".join(mismatches)
                )
            return {
                "status": "passed",
                "backup_size_bytes": backup_size,
                "backup_sha256": backup_sha256,
                "backup_catalog_size_bytes": backup_catalog_path.stat().st_size,
                "temporary_database": temporary_database,
                "verified": (
                    "temporary_database_identity",
                    "database_server_identity",
                    "alembic_revision",
                    "map_schema",
                    "map_foreign_keys",
                    "map_row_counts",
                    "map_novel_counts",
                    "non_map_counts",
                    "reference_registry",
                    "active_and_retained_references",
                    "blocking_tasks",
                ),
            }
        finally:
            if restored_created:
                command_runner(
                    (
                        "dropdb",
                        "--if-exists",
                        "--force",
                        *flags,
                        "--",
                        temporary_database,
                    ),
                    env=environment_vars,
                )


async def run_dry_run(
    *,
    database_url: str,
    environment: str,
    expected_environment: str,
    expected_fingerprint: str,
    backup_restore_drill: bool = False,
    command_runner: CommandRunner = _default_command_runner,
    snapshot_loader: SnapshotLoader = inspect_database,
) -> DryRunReport:
    snapshot = await snapshot_loader(database_url, environment)
    report = evaluate_snapshot(
        snapshot,
        expected_environment=expected_environment,
        expected_fingerprint=expected_fingerprint,
    )
    if backup_restore_drill:
        if not report.ready_for_future_reset_review:
            return report
        drill = await run_backup_restore_drill(
            database_url=database_url,
            environment=environment,
            source_snapshot=snapshot,
            command_runner=command_runner,
            snapshot_loader=snapshot_loader,
        )
        report = replace(report, backup_restore_drill=drill)
    return report


def report_json(report: DryRunReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def inspect_sync(database_url: str, environment: str) -> InspectionSnapshot:
    """Small synchronous seam for CLI target discovery."""

    return asyncio.run(inspect_database(database_url, environment))

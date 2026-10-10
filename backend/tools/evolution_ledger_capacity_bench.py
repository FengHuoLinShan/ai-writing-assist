"""Issue209 synthetic query/verification counters and PostgreSQL EXPLAIN plans.

Run against an explicitly named dedicated test database at Alembic head:
E2E_DATABASE_URL=postgresql+asyncpg://.../issue209_test uv run --locked --extra ci \
    python tools/evolution_ledger_capacity_bench.py --output /tmp/issue209.json
No provider calls, real manuscripts, schema reset or global statistics reset.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, delete, event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

import modules.account.models  # noqa: F401
from modules.evolution import ledger, pipeline
from modules.evolution.discovery import prepare_discovery
from modules.evolution.freshness import _RESULTS
from modules.evolution.ledger import claim_freshness, list_ledger, persist_discovery_claim
from modules.evolution.reading import require_current_prefix
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tests.issue209_data import seed_history
from modules.project.models import Project
from tests.e2e.config import require_e2e_database_url


async def baseline(db, nid, claim, *, cache=None):
    """PR206 algorithm, including its caller-owned intra-page dictionary."""
    cache = {} if cache is None else cache
    store = PostgresAttemptStore(db, nid)
    grouped = {}
    for dependency in claim.dependencies:
        previous = grouped.get(dependency.run_key)
        if previous is None or dependency.scene_index > previous.scene_index:
            grouped[dependency.run_key] = dependency
    for dep in grouped.values():
        key = (dep.run_key, dep.attempt_id, dep.source_manifest_hash)
        if key not in cache:
            frozen = await store.load_frozen(dep.run_key, dep.attempt_id)
            if frozen is None or frozen.source_manifest_hash != dep.source_manifest_hash:
                return "source_changed"
            await require_current_prefix(db, store, frozen)
            cache[key] = True
    return "current"


class QueryStatistics:
    def __init__(self):
        self.shapes = Counter()
        self.literals = {}
        self.source_verifications = 0

    def record(self, conn, cursor, statement, parameters, context, executemany):
        shape = " ".join(statement.split())
        self.shapes[shape] += 1
        if (
            shape not in self.literals
            and statement.lstrip().upper().startswith("SELECT")
            and context.compiled
        ):
            compiled = context.compiled.statement.compile(
                dialect=conn.dialect, compile_kwargs={"literal_binds": True}
            )
            self.literals[shape] = str(compiled)

    def result(self, elapsed):
        return {
            "queries": sum(self.shapes.values()),
            "source_verifications": self.source_verifications,
            "elapsed_seconds": elapsed,
            "query_shapes": [
                {"sql": sql, "calls": count} for sql, count in self.shapes.items()
            ],
        }


async def measure(engine, operation):
    statistics = QueryStatistics()
    original = pipeline._source_verifier

    def counted(binding):
        statistics.source_verifications += 1
        return original(binding)

    pipeline._source_verifier = counted
    event.listen(engine.sync_engine, "before_cursor_execute", statistics.record)
    started = perf_counter()
    try:
        await operation()
    finally:
        elapsed = perf_counter() - started
        event.remove(engine.sync_engine, "before_cursor_execute", statistics.record)
        pipeline._source_verifier = original
    return statistics, statistics.result(elapsed)


async def scenario(engine, sessions, scenes, themes, width, repeats):
    nid = str(uuid4())
    try:
        async with sessions() as db:
            db.add(
                Project(
                    id=UUID(nid),
                    title="Issue209 专用合成基准",
                    understanding_engine="evolution",
                    understanding_epoch=2,
                    understanding_schema_floor=2,
                )
            )
            await db.flush()
            claims = await seed_history(db, nid, scenes)
            deps = [item.dependencies[0] for item in claims[-min(width, scenes) :]]
            claim = claims[-1].model_copy(update={"dependencies": deps})
            for index in range(themes):
                basis = claims[index % scenes]
                basis_deps = [
                    item.dependencies[0]
                    for item in claims[
                        max(0, index % scenes + 1 - width) : index % scenes + 1
                    ]
                ]
                themed = basis.model_copy(
                    update={
                        "label": f"线索{index}",
                        "statement": f"合成主题{index}。",
                        "dependencies": basis_deps,
                    }
                )
                await persist_discovery_claim(
                    db,
                    nid,
                    {
                        "action": "new",
                        "category": "clue",
                        "label": themed.label,
                        "statement": themed.statement,
                        "confidence": 0.8,
                        "evidence": [
                            {"observation_id": themed.evidence[0].observation_id}
                        ],
                    },
                    themed,
                    operation_key=f"synthetic-{index}",
                    review={"verdict": "supported"},
                )
            await db.commit()
            _RESULTS.pop(engine.sync_engine, None)

            async def baseline_calls():
                for _ in range(repeats):
                    assert await baseline(db, nid, claim) == "current"

            old_stats, old = await measure(engine, baseline_calls)
            _, cold = await measure(engine, lambda: claim_freshness(db, nid, claim))

            async def warm_calls():
                for _ in range(repeats):
                    assert await claim_freshness(db, nid, claim) == "current"

            _, warm = await measure(engine, warm_calls)

            async def pages():
                for offset in range(0, themes, 100):
                    page = await list_ledger(
                        db, nid, through_scene_index=scenes - 1, offset=offset, limit=100
                    )
                    assert len(page["items"]) == min(100, themes - offset)

            original_freshness = ledger.claim_freshness
            ledger.claim_freshness = baseline
            try:
                _, old_pages = await measure(engine, pages)
            finally:
                ledger.claim_freshness = original_freshness
            _, page_stats = await measure(engine, pages)
            store = PostgresAttemptStore(db, nid)
            target = await store.load_frozen(
                claim.dependencies[-1].run_key, claim.dependencies[-1].attempt_id
            )
            preparation = {}

            async def prepare():
                preparation.update(await prepare_discovery(db, store, target))

            _, discovery_stats = await measure(engine, prepare)
            discovery_stats["planned_batches"] = len(preparation["batches"])
            discovery_stats["unsupported_batches"] = preparation["unsupported_batches"]
            plans = []
            for sql in old_stats.literals.values():
                plan = await db.scalar(
                    text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
                )
                plans.append({"sql": sql, "plan": plan})
            # Optional server-side statistics: inspect availability, never reset
            # another benchmark's counters or silently install an extension.
            has_stats = await db.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension "
                    "WHERE extname = 'pg_stat_statements')"
                )
            )
            server_stats = []
            if has_stats:
                server_stats = [
                    dict(row)
                    for row in (
                        await db.execute(
                            text(
                                "SELECT query, calls, rows FROM pg_stat_statements "
                                "WHERE dbid = (SELECT oid FROM pg_database "
                                "WHERE datname = current_database()) "
                                "AND query LIKE '%evolution_%'"
                            )
                        )
                    ).mappings()
                ]
            return {
                "scenes": scenes,
                "themes": themes,
                "history_dependency_width": len(deps),
                "repeated_calls": repeats,
                "baseline": old,
                "cold": cold,
                "warm": warm,
                "baseline_ledger_pages": old_pages,
                "ledger_pages": page_stats,
                "discovery_preparation": discovery_stats,
                "explain_analyze": plans,
                "pg_stat_statements_available": bool(has_stats),
                "pg_stat_statements": server_stats,
            }
    finally:
        async with sessions() as db:
            await db.execute(delete(Project).where(Project.id == UUID(nid)))
            await db.commit()


class SynchronousSessionAdapter:
    """Sequential benchmark only; no claim of async or concurrent validation."""

    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        attribute = getattr(self.session, name)
        if name in {
            "execute",
            "scalar",
            "scalars",
            "get",
            "flush",
            "refresh",
            "commit",
            "rollback",
            "close",
        }:

            async def awaited(*args, **kwargs):
                return attribute(*args, **kwargs)

            return awaited
        return attribute


class SynchronousEngineAdapter:
    def __init__(self, engine):
        self.sync_engine = engine

    @asynccontextmanager
    async def connect(self):
        with self.sync_engine.connect() as connection:
            yield SynchronousSessionAdapter(connection)

    async def dispose(self):
        self.sync_engine.dispose()


def synchronous_sessions(engine):
    factory = sessionmaker(engine.sync_engine, expire_on_commit=False)

    @asynccontextmanager
    async def session():
        with factory() as db:
            yield SynchronousSessionAdapter(db)

    return session


async def run(args):
    url = require_e2e_database_url()
    if args.driver == "psycopg2":
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        engine = SynchronousEngineAdapter(create_engine(url, pool_size=1, max_overflow=0))
        sessions = synchronous_sessions(engine)
    else:
        engine = create_async_engine(url, pool_size=1, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            version = await connection.scalar(text("SELECT version()"))
        results = []
        for scenes in args.scenes:
            result = await scenario(
                engine, sessions, scenes, args.themes, args.history_width, args.repeats
            )
            results.append(result)
            print(
                json.dumps(
                    {
                        "scenes": scenes,
                        "baseline_queries": result["baseline"]["queries"],
                        "warm_queries": result["warm"]["queries"],
                        "baseline_verifications": result["baseline"][
                            "source_verifications"
                        ],
                        "warm_verifications": result["warm"]["source_verifications"],
                    }
                )
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "runtime": args.runtime,
                    "driver": args.driver,
                    "database_version": version,
                    "scenarios": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenes", type=int, nargs="+", default=[1, 10, 100])
    parser.add_argument("--themes", type=int, default=120)
    parser.add_argument("--history-width", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument(
        "--runtime", choices=["native-postgresql", "pglite"], default="native-postgresql"
    )
    parser.add_argument("--driver", choices=["asyncpg", "psycopg2"], default="asyncpg")
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    if min(*options.scenes, options.themes, options.history_width, options.repeats) < 1:
        parser.error("all scales must be positive")
    asyncio.run(run(options))

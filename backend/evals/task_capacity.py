"""Bounded PostgreSQL task probe; requires an explicit dedicated local test database."""

import argparse
import asyncio
import json
import math
import time
import uuid
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from evals.experiment import experiment_evidence


def require_probe_database(value):
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "novelcraft_technical_coverage_test"
    ):
        raise ValueError(
            "probe requires local novelcraft_technical_coverage_test; no fallback"
        )
    return value


def percentile(values, fraction=0.95):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


async def run_phase(database_url, *, rate, count):
    from app.bootstrap import _register_orm_models

    _register_orm_models()
    from infrastructure.tasks.enqueuer import enqueue_task
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.registry import TaskRegistry
    from infrastructure.tasks.worker import TaskWorker
    from modules.project.models import Project

    engine = create_async_engine(
        require_probe_database(database_url),
        pool_size=8,
        max_overflow=0,
        connect_args={"server_settings": {"application_name": "technical-coverage"}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    task_type = f"coverage-probe-{nid.hex}"
    rows, samples, errors = [], [], []
    records = {}
    queue = asyncio.Queue()
    finished = asyncio.Event()
    registry = TaskRegistry()

    async def handler(*, db, task):
        record = records[str(task.id)]
        record["started"] = time.perf_counter()
        # A fixed substitute makes queue/transaction overhead observable. This
        # is not an inference benchmark and has no first-token measurement.
        await asyncio.sleep(0.025)
        return {"synthetic": True}

    registry.register(task_type, handler)
    manager = SimpleNamespace(engine=engine, session_factory=sessions)

    async def consume():
        worker = TaskWorker(db_manager=manager, heartbeat_interval=60)
        while (task_id := await queue.get()) is not None:
            try:
                task = await worker.run_once(task_id=task_id, novel_id=nid)
                records[task_id]["status"] = task.status if task else "not_claimed"
            except Exception as error:
                records[task_id]["status"] = "failed"
                errors.append(type(error).__name__)
            finally:
                records[task_id]["finished"] = time.perf_counter()
                queue.task_done()

    async def monitor():
        while not finished.is_set():
            async with sessions() as db:
                pending = await db.scalar(
                    select(func.count())
                    .select_from(AsyncTask)
                    .where(AsyncTask.novel_id == nid, AsyncTask.status == "pending")
                )
                active = await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE "
                        "application_name = 'technical-coverage' AND state = 'active'"
                    )
                )
                samples.append(
                    {
                        "pending": pending,
                        "active_connections": active,
                        "checked_out": engine.pool.checkedout(),
                    }
                )
            await asyncio.sleep(0.1)

    async def submit(index, epoch):
        await asyncio.sleep(max(0, epoch + index / rate - time.perf_counter()))
        record = {"offered": time.perf_counter(), "status": "offered"}
        rows.append(record)
        try:
            async with sessions.begin() as db:
                task_id = enqueue_task(
                    db, task_type, novel_id=str(nid), meta={"novel_id": str(nid)}
                )
                record["task_id"] = str(task_id)
                records[str(task_id)] = record
            record["accepted"] = time.perf_counter()
            await queue.put(str(task_id))
        except Exception as error:
            record["status"] = "rejected"
            errors.append(type(error).__name__)

    consumers, monitor_task = [], None
    try:
        async with sessions.begin() as db:
            db.add(Project(id=nid, title="Disposable technical capacity probe"))
        consumers = [asyncio.create_task(consume()) for _ in range(3)]
        monitor_task = asyncio.create_task(monitor())
        epoch = time.perf_counter()
        async with asyncio.timeout(60):
            await asyncio.gather(*(submit(i, epoch) for i in range(count)))
            await queue.join()
        elapsed = time.perf_counter() - epoch
        counts = Counter(row["status"] for row in rows)
        result = {
            "target_arrival_rps": rate,
            "offered": len(rows),
            "elapsed_seconds": elapsed,
            "states": dict(counts),
            "success_rate": counts["done"] / count,
            "rejection_rate": counts["rejected"] / count,
            "queue_wait_p95_ms": percentile(
                [
                    (row["started"] - row["accepted"]) * 1000
                    for row in rows
                    if "started" in row
                ]
            ),
            "complete_p95_ms": percentile(
                [
                    (row["finished"] - row["offered"]) * 1000
                    for row in rows
                    if "finished" in row
                ]
            ),
            "first_effective_content_ms": None,
            "max_pending": max((sample["pending"] for sample in samples), default=0),
            "max_active_connections": max(
                (sample["active_connections"] for sample in samples), default=0
            ),
            "max_pool_checked_out": max(
                (sample["checked_out"] for sample in samples), default=0
            ),
            "errors": errors,
            "requests": [
                {key: value for key, value in row.items() if key != "task_id"}
                for row in rows
            ],
        }
        return result
    finally:
        finished.set()
        for consumer in consumers:
            consumer.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
        if monitor_task:
            await monitor_task
        registry.unregister(task_type)
        async with sessions.begin() as db:
            await db.execute(delete(AsyncTask).where(AsyncTask.novel_id == nid))
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()


async def run(database_url):
    results = []
    for rate, count in ((30, 60), (90, 180)):
        results.append(await run_phase(database_url, rate=rate, count=count))
    return {
        "evidence": experiment_evidence(
            dataset={"rates": [30, 90], "counts": [60, 180]},
            source_fingerprints={},
            implementation_files=[Path(__file__)],
            receipts=[],
        ),
        "scope": "PG enqueue/worker only; no HTTP load, real model or 100K DAU claim",
        "workers": 3,
        "pool_size": 8,
        "substitute_delay_ms": 25,
        "phases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.database_url))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    if any(phase["success_rate"] != 1 for phase in report["phases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""演化检查点与回放长度性能测量（V4 E06 / 计划 §9 测量档位）。

按 1k/5k/10k Scene 档位测量已提交回执链的：

- 全量分页回放（页数/扫描行数/耗时）；
- 检查点锚点命中后的增量回放（只扫尾部 ``--tail`` 个 Scene 的页）。

用法（专用空库，勿指向共享/生产库）：

    python -m tools.evolution_checkpoint_bench \
        --database-url postgresql+asyncpg://user:pass@host:5432/benchdb \
        --create-schema --tiers 1000 5000 10000

结果以 Markdown 表输出 stdout；``--json-path`` 另存机器可读结果。
这些是本机测量档位，不是性能承诺（计划 §9）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.base import Base
from modules.evolution.recovery import (
    replay_committed_prefix,
    verify_run_checkpoint,
)
from modules.evolution.store import PostgresAttemptStore


async def _seed(engine, novel_id: uuid.UUID, run_key: str, scenes: int) -> None:
    from app.bootstrap import _register_orm_models
    from modules.evolution.models import (
        EvolutionFrozenAttempt,
        EvolutionReceiptRecord,
        EvolutionRun,
    )
    from modules.project.models import Project

    _register_orm_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        from modules.account.models import Account

        owner_id = uuid.uuid4()
        db.add(Account(id=owner_id, support_code=f"bench-{novel_id.hex[:8]}"))
        await db.flush()
        db.add(Project(id=novel_id, owner_id=owner_id, title="bench", genre="bench"))
        await db.flush()
        db.add(
            EvolutionRun(
                novel_id=novel_id,
                run_key=run_key,
                mode="append",
                owner_epoch=1,
                budget_total=scenes,
                budget_remaining=0,
                committed_scene_index=scenes - 1,
                committed_source_revision=1,
            )
        )
        await db.flush()
        previous: str | None = None
        batch_frozen = []
        batch_receipts = []
        head_id = None
        for scene in range(scenes):
            attempt = uuid.uuid4().hex
            receipt = {
                "run_id": run_key,
                "attempt_id": attempt,
                "owner_epoch": 1,
                "producer_version": "bench",
                "source_manifest_hash": "a" * 64,
                "input_state_receipt": "b" * 64,
                "previous_receipt": previous,
                "previous_committed_prefix": None,
                "observation_dispositions": {},
                "world_result_refs": [],
                "story_result_refs": [],
                "evidence_result_refs": [],
                "pending_decisions": [],
                "coverage": {},
                "committed_prefix": {
                    "through_scene_index": scene,
                    "through_source_revision": 1,
                },
                "blocked_dependencies": [],
                "paid_call_receipts": [],
                "execution_status": "succeeded",
                "outcome_status": "committed",
                "freshness": "fresh",
            }
            frozen = EvolutionFrozenAttempt(
                novel_id=novel_id,
                run_key=run_key,
                attempt_key=attempt,
                owner_epoch=1,
                producer_version="bench",
                source_manifest_hash="a" * 64,
                payload_json={"bench": True},
                status="applied",
            )
            record = EvolutionReceiptRecord(
                novel_id=novel_id,
                run_key=run_key,
                attempt_key=attempt,
                execution_status="succeeded",
                committed_scene_index=scene,
                committed_source_revision=1,
                receipt_json=receipt,
            )
            batch_frozen.append(frozen)
            batch_receipts.append(record)
            previous = attempt
            if len(batch_receipts) >= 500:
                db.add_all(batch_frozen)
                db.add_all(batch_receipts)
                await db.flush()
                head_id = batch_receipts[-1].id
                batch_frozen, batch_receipts = [], []
        if batch_receipts:
            db.add_all(batch_frozen)
            db.add_all(batch_receipts)
            await db.flush()
            head_id = batch_receipts[-1].id
        await db.execute(select(EvolutionRun).where(EvolutionRun.run_key == run_key))
        from sqlalchemy import update

        await db.execute(
            update(EvolutionRun)
            .where(EvolutionRun.run_key == run_key)
            .values(head_attempt_id=head_id)
        )
        await db.commit()


async def _run_tier(engine, tier: int, page_size: int, tail: int) -> dict:
    novel_id = uuid.uuid4()
    run_key = f"bench-{tier}"
    await _seed(engine, novel_id, run_key, tier)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        store = PostgresAttemptStore(db, novel_id)

        start = time.perf_counter()
        prefix, _head = await verify_run_checkpoint(db, store, run_key)
        checkpoint_ms = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        full = await replay_committed_prefix(db, store, run_key, page_size=page_size)
        full_ms = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        incremental = await replay_committed_prefix(
            db,
            store,
            run_key,
            from_scene_index=max(0, tier - tail),
            page_size=page_size,
        )
        incremental_ms = (time.perf_counter() - start) * 1000

        return {
            "tier": tier,
            "page_size": page_size,
            "tail": tail,
            "checkpoint_verify_ms": round(checkpoint_ms, 2),
            "full": {
                "receipts": full.receipt_count,
                "pages": full.pages_read,
                "rows_scanned": full.rows_scanned,
                "ms": round(full_ms, 2),
            },
            "incremental": {
                "receipts": incremental.receipt_count,
                "pages": incremental.pages_read,
                "rows_scanned": incremental.rows_scanned,
                "ms": round(incremental_ms, 2),
            },
            "cursor_prefix": None if prefix is None else prefix.model_dump(),
        }


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--tiers", nargs="+", type=int, default=[1000, 5000, 10000])
    parser.add_argument("--page-size", type=int, default=200)
    parser.add_argument("--tail", type=int, default=100)
    parser.add_argument("--json-path", default=None)
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="在目标库建表（要求空/专用库）",
    )
    args = parser.parse_args(argv)

    engine = create_async_engine(args.database_url)
    results = []
    try:
        for tier in args.tiers:
            result = await _run_tier(engine, tier, args.page_size, args.tail)
            results.append(result)
            print(
                f"tier={tier}: full(pages={result['full']['pages']}, "
                f"rows={result['full']['rows_scanned']}, "
                f"{result['full']['ms']}ms) "
                f"incremental(pages={result['incremental']['pages']}, "
                f"rows={result['incremental']['rows_scanned']}, "
                f"{result['incremental']['ms']}ms)"
            )
    finally:
        await engine.dispose()

    print()
    print("| 档位 | 全量回放 页/行/耗时 | 增量回放(尾部100) 页/行/耗时 | 检查点校验 |")
    print("|---|---|---|---|")
    for item in results:
        print(
            f"| {item['tier']} | {item['full']['pages']} / "
            f"{item['full']['rows_scanned']} / {item['full']['ms']}ms | "
            f"{item['incremental']['pages']} / "
            f"{item['incremental']['rows_scanned']} / "
            f"{item['incremental']['ms']}ms | "
            f"{item['checkpoint_verify_ms']}ms |"
        )
    if args.json_path:
        payload = {
            "measured_at": datetime.now(UTC).isoformat(),
            "page_size": args.page_size,
            "tail": args.tail,
            "results": results,
        }
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

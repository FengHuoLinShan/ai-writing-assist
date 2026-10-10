# Issue #209 validation and remaining acceptance

Only synthetic manuscripts and deterministic samplers were used; no paid model calls.

## Executed

- Final Evolution module regression: 378 passed, 1 real_llm deselected; final focused source/cache/capacity/replay regression: 45 passed. Ruff, module-import/direction gate and diff checks passed; architecture-document impact check passed with the explicit reviewed-but-unchanged governance-doc reason in the PR.

- Fresh Alembic migration to `20261010_evolution_source_epoch` on PostgreSQL 18.3 / PGlite 0.5.8 (WASM), including vector/pgcrypto/pg_trgm; `alembic check` passed before and after downgrade to `20261008_evolution_ledger` and re-upgrade.
- Sequential psycopg2 adapter replayed 13 cases from `tests/e2e/test_evolution_issue209.py`: 1/10/100-Scene warm reads across sessions, same-length source edits, rollback UUID ABA, exact restore vs new source version, Scene reorder, frozen edits, project isolation, bounded cache, absent tokens, unrelated append, newer successful attempts (including another run’s live/shadow transition), changed inherited receipts, and all remaining trigger tables, and raw-SQL mutations of retained receipt/frozen/draft ORM rows.
- Actual SQL counts, source-verifier invocations and ten query-shape `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans per scenario recorded in [artifacts/pglite-benchmark.json](artifacts/pglite-benchmark.json). Large baseline pagination shape listings are excerpted; totals and omitted calls remain exact. `pg_stat_statements` was unavailable. WASM timings are diagnostic only.

Each scenario has 120 themes, history dependency width up to 100, and five independent freshness reads:

| Scenes | Old queries / full source checks | Warm queries / full source checks | Old two-page queries | Warm two-page queries | Preparation batches / unsupported |
| --- | --- | --- | --- | --- | --- |
| 1 | 60 / 5 | 5 / 0 | 32 | 128 | 1 / 0 |
| 10 | 420 / 50 | 5 / 0 | 508 | 128 | 49 / 0 |
| 100 | 4020 / 500 | 5 / 0 | 40808 | 128 | 122 / 0 |

Small histories can have more guard queries than the old intra-page dictionary: each claim reads a fresh transaction-visible guard. The benefit targets repeated full historical verification; no wall-clock native speedup is claimed. Unrelated append needs three token queries once, then one guard query. Cold source validation retains its linear prefix cost. Table row triggers add write work and serialize writes of the same project token; production write contention is unmeasured.

Capacity tests cover 0/1/100/1000 themes, 100/16000/70000-character Scenes, full historical candidate/index membership, exact repeated-quote and cross-chapter offsets, indivisible oversized units (including the first index/context unit without poisoning other batches), deterministic partitions, all-index identity proof and tampering. Actual Scene-handler tests verify successful and settled failed identity journals, replay with no additional sampler calls, and no duplicate adoption. All-index identity reviews can increase model calls; existing root budget remains authoritative and gaps stay explicit.

## Native PostgreSQL commands

Provision a **dedicated native PostgreSQL 17 + pgvector test database**; never use the development or production database. From repository root, set an explicit URL with a database name ending in `_test`:

```bash
export E2E_DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/issue209_test'
export DATABASE_URL="$E2E_DATABASE_URL"
(cd backend && uv run --locked --extra ci alembic upgrade head)
RUN_E2E_TESTS=1 uv --directory backend run --locked --extra ci pytest tests/e2e/test_evolution_issue209.py -m e2e --timeout=120
E2E_DATABASE_URL="$E2E_DATABASE_URL" make test-postgresql-critical
uv --directory backend run --locked --extra ci python tools/evolution_ledger_capacity_bench.py --scenes 1 10 100 1000 --themes 120 --history-width 100 --repeats 5 --output /tmp/issue209-native.json
uv --directory backend run --locked --extra ci python tools/evolution_ledger_capacity_bench.py --scenes 100 --themes 1000 --history-width 1 --repeats 5 --output /tmp/issue209-narrow.json
```

The tool cleans up only its generated projects, never resets global server statistics, and captures `pg_stat_statements` only when already installed. Keep output from each run to compare query counts/shapes and native plans. Vary `--history-width`, `--themes` and `--scenes` for larger experiments; costs of baseline pagination can grow quadratically.

## Remaining before merge

Native initdb could not run as a non-root user in this execution environment; asyncpg against the WASM socket transport did not complete. Native asyncpg execution, the concurrent-writer regression, ORM parity/downgrade and the full PostgreSQL critical target therefore remain unverified. The PR must stay draft until those checks pass. WASM sequential assertions and SQLite module regressions do not substitute for native concurrency acceptance. Issue #208 Scene Projection consumption queries are unchanged.

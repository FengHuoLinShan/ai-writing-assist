"""CLI entry for the G7a import-scan baseline.

Run from backend:
    uv run --locked -- python -m tools.import_scan_baseline.run_baseline \
        --tiers L10,L30,L60 --density-tiers D2500,D5000,D10000

The tool only touches the dedicated G7 PostgreSQL database (default
novel_pg_g7a on 127.0.0.1:5207, or G7A_DATABASE_URL/--database-url with a
standalone 'g7' name marker). It never reads backend/.env and never calls
a model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tools.import_scan_baseline.collector import (
    OUT,
    TierResult,
    ensure_schema,
    import_all_models,
    measure_tier,
    provenance,
    render_markdown,
    resolve_database_url,
    tier_result_to_dict,
)
from tools.import_scan_baseline.synthetic import (
    chapter_equivalent_tiers,
    spec_by_name,
)


def _normalize_tier_names(raw: str | None, defaults: tuple[str, ...]) -> list[str]:
    if raw is None:
        return list(defaults)
    names = [item.strip() for item in raw.split(",") if item.strip()]
    if not names:
        raise SystemExit("empty --tiers/--density-tiers value")
    return names


async def run(args: argparse.Namespace) -> int:
    database_url = resolve_database_url(args.database_url)
    url = make_url(database_url)
    engine = create_async_engine(database_url, pool_size=2, max_overflow=0)
    import_all_models()
    try:
        schema_info = await ensure_schema(
            engine, allow_metadata_fallback=args.create_schema
        )
        chapter_default = tuple(t.name for t in chapter_equivalent_tiers())
        chapter_names = _normalize_tier_names(args.tiers, chapter_default)
        density_names = _normalize_tier_names(args.density_tiers, ())
        specs = [spec_by_name(name) for name in (*chapter_names, *density_names)]

        results: list[TierResult] = []
        for spec in specs:
            print(f"[g7a] tier {spec.name}: seeding {spec.summary()}", flush=True)
            result = await measure_tier(
                engine,
                spec,
                repeats=args.repeats,
                hot_read_repeats=args.hot_read_repeats,
                keep_data=args.keep_data,
            )
            results.append(result)
            print(
                f"[g7a] tier {spec.name}: sql={result.median_statements()} "
                f"db={result.median_db_seconds():.4f}s "
                f"wall={result.median_wall_seconds():.4f}s",
                flush=True,
            )

        report = {
            "kind": "g7a-import-scan-baseline",
            "created_at": datetime.now(UTC).isoformat(),
            "provenance": provenance(),
            "database_name": url.database,
            "schema": schema_info,
            "repeats": args.repeats,
            "hot_read_repeats": args.hot_read_repeats,
            "tiers": [tier_result_to_dict(item) for item in results],
        }
        OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        json_path = OUT / f"baseline-{stamp}.json"
        md_path = OUT / f"baseline-{stamp}.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        md_path.write_text(render_markdown(report))
        latest_json = OUT / "baseline-latest.json"
        latest_md = OUT / "baseline-latest.md"
        latest_json.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        latest_md.write_text(render_markdown(report))
        print(f"[g7a] report: {json_path}", flush=True)
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--tiers",
        default=None,
        help="comma-separated chapter-equivalent tiers (default L10,L30,L60)",
    )
    parser.add_argument(
        "--density-tiers",
        default=None,
        help="comma-separated entity-density tiers (e.g. D2500,D5000,D10000)",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--hot-read-repeats", type=int, default=5)
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="keep the synthetic tier rows for inspection (dedicated DB only)",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="create the schema from ORM metadata when the dedicated DB is empty",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

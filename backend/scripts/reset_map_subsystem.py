"""CLI for the read-only map subsystem reset preflight."""

from __future__ import annotations

import argparse
import asyncio
import json

from core.config import get_settings
from tools.map_subsystem_reset import inspect_database, report_json, run_dry_run


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only map subsystem reset preflight. "
            "This command has no destructive mode."
        )
    )
    parser.add_argument(
        "--show-target",
        action="store_true",
        help="Print the normalized live target and fingerprint, then exit.",
    )
    parser.add_argument("--expected-environment")
    parser.add_argument("--expected-fingerprint")
    parser.add_argument(
        "--backup-restore-drill",
        action="store_true",
        help="Restore a verified backup into a unique temporary database.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (the default dry-run format).",
    )
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    settings = get_settings()
    if args.show_target:
        snapshot = await inspect_database(settings.database_url, settings.app_env)
        print(json.dumps(snapshot.identity.__dict__, indent=2, sort_keys=True))
        unsafe_target = snapshot.identity.declared_environment in {
            "prod",
            "production",
        } or snapshot.identity.target_environment_classification in {
            "production",
            "unclassified",
        }
        return 2 if unsafe_target else 0

    if not args.expected_environment or not args.expected_fingerprint:
        _parser().error(
            "--expected-environment and --expected-fingerprint are required for a dry-run"
        )
    report = await run_dry_run(
        database_url=settings.database_url,
        environment=settings.app_env,
        expected_environment=args.expected_environment,
        expected_fingerprint=args.expected_fingerprint,
        backup_restore_drill=args.backup_restore_drill,
    )
    print(report_json(report))
    return 0 if report.ready_for_future_reset_review else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

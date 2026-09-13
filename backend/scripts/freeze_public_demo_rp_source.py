#!/usr/bin/env python3
"""Materialize or validate a model-free frozen source for public-demo RP.

``--project-id`` defaults to a no-write gate and only creates a revision with
``--execute``. ``--source-revision-id`` is validation-only. Neither path
imports, indexes, calls a model, or changes author source data.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.database import get_manager  # noqa: E402
from modules.interaction.source_service import InteractionSourceService  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project-id")
    target.add_argument("--source-revision-id")
    parser.add_argument("--execute", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    manager = get_manager()
    try:
        async with manager.session() as db:
            service = InteractionSourceService()
            if args.source_revision_id:
                if args.execute:
                    raise ValueError("--execute requires --project-id")
                revision = await service.validate_frozen_source_candidate(
                    db,
                    revision_id=args.source_revision_id,
                )
                created = False
            else:
                revision, created = await service.materialize_frozen_source_candidate(
                    db,
                    project_id=args.project_id,
                    execute=args.execute,
                )
    finally:
        await manager.close()
    if args.execute or args.source_revision_id:
        print(f"PUBLIC_DEMO_RP_SOURCE_REVISION_ID={revision.id}")
    else:
        print(
            "READY_TO_FREEZE "
            f"project_id={args.project_id} fingerprint={revision.fingerprint}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())

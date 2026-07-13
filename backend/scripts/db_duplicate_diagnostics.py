"""Report duplicate-risk keys before creating stricter database indexes."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from core.database import get_manager


@dataclass(frozen=True)
class DuplicateCheck:
    label: str
    sql: str
    blocks_migration: bool = True


CHECKS = [
    DuplicateCheck(
        "core_entities active same name/type/status",
        """
        SELECT novel_id, entity_type, status, lower(trim(name)) AS normalized_name,
               COUNT(*) AS count
        FROM core_entities
        WHERE status != 'deprecated'
        GROUP BY novel_id, entity_type, status, lower(trim(name))
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """,
        blocks_migration=False,
    ),
    DuplicateCheck(
        "entity_relations canonical edge",
        """
        SELECT novel_id, source_id, target_id, relation_type, COUNT(*) AS count
        FROM entity_relations
        WHERE status = 'canonical'
        GROUP BY novel_id, source_id, target_id, relation_type
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """,
    ),
    DuplicateCheck(
        "memory_events chapter sequence",
        """
        SELECT novel_id, chapter_index, sequence, COUNT(*) AS count
        FROM memory_events
        GROUP BY novel_id, chapter_index, sequence
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """,
    ),
    DuplicateCheck(
        "rag_chunks chapter text key",
        """
        SELECT novel_id, source_type, content_mode, chapter_index, chunk_index,
               index_version,
               COUNT(*) AS count
        FROM rag_chunks
        WHERE source_type = 'chapter_text'
          AND chapter_index IS NOT NULL
          AND chunk_index IS NOT NULL
        GROUP BY novel_id, source_type, content_mode, chapter_index, chunk_index,
                 index_version
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """,
    ),
    DuplicateCheck(
        "writing_drafts chapter version",
        """
        SELECT novel_id, chapter_index, version_number, COUNT(*) AS count
        FROM writing_drafts
        GROUP BY novel_id, chapter_index, version_number
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """,
    ),
    DuplicateCheck(
        "scene_chapter_links scene/chapter key",
        """
        SELECT novel_id, scene_id, chapter_index, COUNT(*) AS count
        FROM scene_chapter_links
        GROUP BY novel_id, scene_id, chapter_index
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """,
        blocks_migration=False,
    ),
    DuplicateCheck(
        "map_configs top-level name",
        """
        SELECT novel_id, name, COUNT(*) AS count
        FROM map_configs
        WHERE parent_map_id IS NULL
        GROUP BY novel_id, name
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT 20
        """,
    ),
]


async def run_checks() -> dict[str, list[dict[str, Any]]]:
    manager = get_manager()
    findings: dict[str, list[dict[str, Any]]] = {}
    async with manager.session_factory() as session:
        for check in CHECKS:
            rows = (await session.execute(text(check.sql))).mappings().all()
            findings[check.label] = [dict(row) for row in rows]
    await manager.close()
    return findings


def _print_findings(findings: dict[str, list[dict[str, Any]]]) -> None:
    blocking_by_label = {check.label: check.blocks_migration for check in CHECKS}
    for label, rows in findings.items():
        suffix = "" if blocking_by_label[label] else " (warning-only)"
        print(f"\n[{label}]{suffix}")
        if not rows:
            print("OK")
            continue
        for row in rows:
            print(row)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fail-on-duplicates",
        action="store_true",
        help="Exit 1 when duplicate keys would block newly enforced constraints.",
    )
    args = parser.parse_args()

    findings = await run_checks()
    _print_findings(findings)
    blocking_labels = {check.label for check in CHECKS if check.blocks_migration}
    has_duplicates = any(
        rows for label, rows in findings.items() if label in blocking_labels
    )
    return 1 if args.fail_on_duplicates and has_duplicates else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

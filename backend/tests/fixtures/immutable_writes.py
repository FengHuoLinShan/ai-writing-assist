"""Guard that fails a test when immutable revision rows are rewritten.

The unit-test database is SQLite built from ORM metadata, so the PostgreSQL
immutability triggers never exist there.  This guard watches emitted UPDATE
and DELETE statements directly, which keeps the append-only invariant
enforced on every dialect and would have caught the demo-copy canon delete
before it shipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import Delete, Update, event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

IMMUTABLE_TABLES = frozenset(
    {
        "world_assertions",
        "world_canon_revisions",
        "entity_profile_template_revisions",
        "world_bible_page_revisions",
        "story_outline_revisions",
        "map_atlas_revisions",
        "story_simulation_steps",
        "interaction_actor_state_revisions",
        "cognition_commits",
    }
)


@dataclass
class ImmutableWriteReport:
    violations: list[tuple[str, str]] = field(default_factory=list)

    def assert_clean(self) -> None:
        assert not self.violations, (
            "Immutable revision rows were rewritten: "
            + ", ".join(f"{op} {table}" for op, table in self.violations)
        )


@contextmanager
def forbid_immutable_writes(session: AsyncSession) -> Iterator[ImmutableWriteReport]:
    """Fail the enclosing test on any UPDATE/DELETE hitting immutable tables.

    Mutable pointer tables (heads, cards, nodes, script files) may be updated;
    only the append-only revision tables are guarded here.
    """
    report = ImmutableWriteReport()

    def watch(orm_execute_state) -> None:
        statement = orm_execute_state.statement
        if isinstance(statement, Update | Delete):
            table_name = statement.table.name
            if table_name in IMMUTABLE_TABLES:
                report.violations.append((type(statement).__name__, table_name))

    event.listen(Session, "do_orm_execute", watch)
    try:
        yield report
    finally:
        event.remove(Session, "do_orm_execute", watch)

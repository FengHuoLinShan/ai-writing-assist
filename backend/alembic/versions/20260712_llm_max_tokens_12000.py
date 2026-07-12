"""normalize general LLM max tokens to 12000

Revision ID: 20260712_llm_max_12000
Revises: 20260712_p1_observe_lifecycle
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import sqlalchemy as sa

from alembic import op
from shared.constants import DEFAULT_LLM_MAX_TOKENS

revision = "20260712_llm_max_12000"
down_revision = "20260712_p1_observe_lifecycle"
branch_labels = None
depends_on = None


def _normalized_project_settings(settings: Any) -> dict[str, Any] | None:
    """Set the general LLM budget without touching deep-import settings."""
    if not isinstance(settings, dict):
        return None
    llm = settings.get("llm")
    if not isinstance(llm, dict) or not llm:
        return None
    if llm.get("max_tokens") == DEFAULT_LLM_MAX_TOKENS:
        return None
    normalized = deepcopy(settings)
    normalized["llm"]["max_tokens"] = DEFAULT_LLM_MAX_TOKENS
    return normalized


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "global_llm_defaults" in tables:
        global_defaults = sa.Table(
            "global_llm_defaults",
            sa.MetaData(),
            autoload_with=bind,
        )
        bind.execute(sa.update(global_defaults).values(max_tokens=DEFAULT_LLM_MAX_TOKENS))

    if "projects" not in tables:
        return
    projects = sa.Table(
        "projects",
        sa.MetaData(),
        autoload_with=bind,
    )
    rows = list(bind.execute(sa.select(projects.c.id, projects.c.settings)).mappings())
    for row in rows:
        normalized = _normalized_project_settings(row["settings"])
        if normalized is None:
            continue
        bind.execute(
            sa.update(projects)
            .where(projects.c.id == row["id"])
            .values(settings=normalized)
        )


def downgrade() -> None:
    # Data normalization is intentionally irreversible: old explicit values cannot
    # be distinguished from the former system default after upgrade.
    pass

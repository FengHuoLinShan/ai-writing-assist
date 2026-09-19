"""Fail-closed handoff of source-labelled team artifacts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError


class TeamProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    novel_id: str
    scope_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    recipient: str = Field(min_length=1, max_length=64)
    source_keys: frozenset[str]


def project_team_artifact(
    *,
    artifact: dict[str, Any],
    source_keys: set[str],
    novel_id: str,
    scope_hash: str,
    recipient: TeamProjection,
) -> dict[str, Any]:
    """Source dependencies include ALL inputs, not only the sender's citations.

    A restricted recipient never receives a sender's rewritten summary as a
    substitute. The caller must rematerialize the recipient's own Evidence packet.
    """
    if (
        novel_id != recipient.novel_id
        or scope_hash != recipient.scope_hash
        or not source_keys <= recipient.source_keys
    ):
        raise ConflictError("该成果不在接收者的资料范围内", code="team_projection_denied")
    from copy import deepcopy

    return deepcopy(artifact)

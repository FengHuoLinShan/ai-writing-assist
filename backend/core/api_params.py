"""FastAPI parameter aliases shared by API boundary modules."""

from __future__ import annotations

from typing import Annotated

from fastapi import Form, Path, Query

UUID_PATTERN = (
    r"^(?:[0-9a-fA-F]{32}|"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)

NovelIdQuery = Annotated[
    str,
    Query(..., description="项目 ID", pattern=UUID_PATTERN),
]
NovelIdPath = Annotated[
    str,
    Path(..., description="项目 ID", pattern=UUID_PATTERN),
]
NovelIdForm = Annotated[
    str,
    Form(..., description="项目 ID", pattern=UUID_PATTERN),
]

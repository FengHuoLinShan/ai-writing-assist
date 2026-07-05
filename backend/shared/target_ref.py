"""Stable target references for worldbuilding assets."""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, Field, field_validator

_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_]+(?:\[[0-9]+\])?$")


class TargetRef(BaseModel):
    """Canonical reference to a worldbuilding target or field."""

    target_type: str = Field(..., min_length=1, max_length=64)
    target_id: str = Field(..., min_length=1, max_length=255)
    target_path: str = Field(default="", max_length=512)

    @field_validator("target_path", mode="before")
    @classmethod
    def normalize_path(cls, value: object) -> str:
        if value is None:
            return ""
        path = str(value).strip()
        if not path:
            return ""
        parts = path.split(".")
        if any(not _PATH_SEGMENT_RE.match(part) for part in parts):
            raise ValueError(
                "target_path supports only dot paths with optional numeric indexes",
            )
        return ".".join(parts)

    @field_validator("target_type", "target_id")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    def canonical_dict(self) -> dict[str, str]:
        return {
            "target_id": self.target_id,
            "target_path": self.target_path or "",
            "target_type": self.target_type,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def target_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def normalize_target_ref(value: TargetRef | dict | None) -> TargetRef:
    if isinstance(value, TargetRef):
        return value
    if not value:
        raise ValueError("target ref is required")
    return TargetRef.model_validate(value)


def target_hash(value: TargetRef | dict) -> str:
    return normalize_target_ref(value).target_hash()

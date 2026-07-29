"""Streaming-safe visible story / hidden metadata framing."""

from __future__ import annotations

import json

from pydantic import ValidationError

from modules.interaction.schemas import InteractionResponseMetadata

META_START = "\n<INTERACTION_META_V1>\n"
META_END = "\n</INTERACTION_META_V1>"
MAX_METADATA_CHARS = 8192


class InteractionStreamFramer:
    """Hide a strictly delimited tail block while yielding plain story text."""

    def __init__(self) -> None:
        self._mode = "visible"
        self._pending = ""
        self._metadata = ""
        self._metadata_complete = False
        self._metadata_too_large = False

    def feed(self, content: str) -> str:
        if not content:
            return ""
        self._pending += content
        if self._mode == "visible":
            marker_index = self._pending.find(META_START)
            if marker_index >= 0:
                visible = self._pending[:marker_index]
                self._pending = self._pending[marker_index + len(META_START) :]
                self._mode = "metadata"
                self._consume_metadata()
                return visible
            keep = max(0, len(META_START) - 1)
            if len(self._pending) <= keep:
                return ""
            visible = self._pending[:-keep]
            self._pending = self._pending[-keep:]
            return visible
        if self._mode == "metadata":
            return self._consume_metadata()
        visible = self._pending
        self._pending = ""
        return visible

    def _consume_metadata(self) -> str:
        marker_index = self._pending.find(META_END)
        if marker_index < 0:
            keep = max(0, len(META_END) - 1)
            if len(self._pending) <= keep:
                return ""
            consumable = self._pending[:-keep]
            self._pending = self._pending[-keep:]
            if not self._metadata_too_large:
                self._metadata += consumable
                if len(self._metadata) > MAX_METADATA_CHARS:
                    self._metadata = ""
                    self._metadata_too_large = True
            return ""
        if not self._metadata_too_large:
            self._metadata += self._pending[:marker_index]
            if len(self._metadata) > MAX_METADATA_CHARS:
                self._metadata = ""
                self._metadata_too_large = True
        suffix = self._pending[marker_index + len(META_END) :]
        self._pending = ""
        self._metadata_complete = True
        self._mode = "done"
        return suffix if suffix.strip() else ""

    def finish(self) -> tuple[str, InteractionResponseMetadata | None, str]:
        trailing_visible = ""
        if self._mode == "visible":
            trailing_visible = self._pending
        elif self._mode == "done" and self._pending.strip():
            trailing_visible = self._pending
        self._pending = ""
        metadata = None
        raw_metadata = ""
        if self._metadata_complete and not self._metadata_too_large:
            raw_metadata = self._metadata
            try:
                metadata = InteractionResponseMetadata.model_validate(
                    json.loads(self._metadata)
                )
            except (json.JSONDecodeError, TypeError, ValidationError):
                metadata = None
        return trailing_visible, metadata, raw_metadata

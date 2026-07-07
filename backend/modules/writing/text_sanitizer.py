"""Minimal HTML sanitization for writing draft text."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True)
class SanitizedText:
    text: str | None
    html_removed: bool


_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "pre",
    "section",
    "tr",
}
_RAW_TEXT_TAGS = {"script", "style"}


class _WritingHTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._skip_depth = 0
        self.html_removed = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.html_removed = True
        normalized = tag.lower()
        if normalized in _RAW_TEXT_TAGS:
            self._skip_depth += 1
        elif normalized in _BLOCK_TAGS:
            self._append_newline()

    def handle_endtag(self, tag: str) -> None:
        self.html_removed = True
        normalized = tag.lower()
        if normalized in _RAW_TEXT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif normalized in _BLOCK_TAGS:
            self._append_newline()

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.html_removed = True
        if tag.lower() in _BLOCK_TAGS:
            self._append_newline()

    def handle_comment(self, data: str) -> None:
        self.html_removed = True

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(f"&#{name};")

    def handle_decl(self, decl: str) -> None:
        self.html_removed = True

    def unknown_decl(self, data: str) -> None:
        self.html_removed = True

    def text(self) -> str:
        return "".join(self._parts)

    def _append_newline(self) -> None:
        if not self._parts or self._parts[-1].endswith("\n"):
            return
        self._parts.append("\n")


def sanitize_writing_text(value: str | None) -> SanitizedText:
    """Strip executable/display HTML while preserving ordinary prose text."""
    if value is None:
        return SanitizedText(text=None, html_removed=False)

    stripper = _WritingHTMLStripper()
    stripper.feed(value)
    stripper.close()
    return SanitizedText(text=stripper.text(), html_removed=stripper.html_removed)

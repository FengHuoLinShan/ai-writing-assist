# modules/writing — 正文草稿承载模块
# 当前不是 AI 正文生成模块，而是人工正文草稿和结构化创作成果的承载
# 提供草稿 CRUD、版本管理和章节关联

from __future__ import annotations

from modules.writing.contracts import WritingDraftContract
from modules.writing.facade import get_draft, get_latest_draft_for_chapter, list_chapter_indices
from modules.writing.models import WritingDraft
from modules.writing.schemas import (
    DraftListItem,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
)

__all__ = [
    "WritingDraft",
    "WritingDraftContract",
    "WritingDraftCreate",
    "WritingDraftUpdate",
    "WritingDraftResponse",
    "DraftListItem",
    "get_draft",
    "get_latest_draft_for_chapter",
    "list_chapter_indices",
]

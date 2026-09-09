"""Manuscript selection includes the first character without accepting missing offsets."""

import pytest
from pydantic import ValidationError

from modules.evidence.compilation.schemas import ContextSelectionRefRequest


@pytest.mark.parametrize("start", [0, 1, None, -1, False])
def test_manuscript_selection_start_offset(start):
    ref = {
        "draft_id": "10000000-0000-0000-0000-000000000001",
        "chapter_index": 1,
        "version_number": 1,
        "content_mode": "canonical",
        "start_offset": start,
        "end_offset": 12,
        "source_hash": "a" * 64,
        "range_hash": "b" * 64,
    }
    if start is None or start is False or start == -1:
        with pytest.raises(ValidationError, match="offsets"):
            ContextSelectionRefRequest(kind="source_range", source_ref=ref)
    else:
        selected = ContextSelectionRefRequest(kind="source_range", source_ref=ref)
        assert selected.source_ref["start_offset"] == start

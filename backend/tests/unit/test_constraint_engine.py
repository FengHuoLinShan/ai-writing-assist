"""Unit tests for ConstraintEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from modules.context.services.compiled_context import Tier
from modules.context.services.constraint_engine import ConstraintEngine


@pytest.mark.asyncio
async def test_static_constraints_returns_p0_sections():
    engine = ConstraintEngine()
    sections = await engine._static_constraints("zh")
    assert len(sections) == 1
    s = sections[0]
    assert s.key == "hard_constraints"
    assert s.tier == Tier.P0
    assert s.content.strip() != ""
    assert s.token_count > 0


@pytest.mark.asyncio
async def test_static_constraints_zh_and_en():
    engine = ConstraintEngine()
    zh = await engine._static_constraints("zh")
    en = await engine._static_constraints("en")
    assert zh[0].content != en[0].content
    assert "不得" in zh[0].content
    assert "must not" in en[0].content.lower()


@pytest.mark.asyncio
async def test_compile_constraints_returns_at_least_static():
    engine = ConstraintEngine()
    sections = await engine.compile_constraints(AsyncMock(), "novel-1")
    static = [s for s in sections if s.key == "hard_constraints"]
    assert len(static) == 1
    assert static[0].tier == Tier.P0

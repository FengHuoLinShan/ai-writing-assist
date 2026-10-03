"""规模夹具生成器（B7）确定性测试。"""

from __future__ import annotations

import pytest

from tools.scale_fixtures import (
    TIERS,
    _base_chapters,
    corpus_sha256,
    corpus_summary,
    generate_corpus,
)


def test_fixture_generation_is_deterministic() -> None:
    base = _base_chapters()
    first = corpus_sha256("low", seed=0, base=base)
    second = corpus_sha256("low", seed=0, base=base)
    other_seed = corpus_sha256("low", seed=1, base=base)

    assert first == second
    # seed 参与章节印记，改变 seed 必然改变产出（API 对称且可区分）
    assert first != other_seed


def test_tiers_scale_monotonically() -> None:
    base = _base_chapters()
    summaries = [corpus_summary(tier, base=base) for tier in ("low", "mid")]

    assert summaries[0]["chapters"] < summaries[1]["chapters"]
    assert summaries[0]["chars"] < summaries[1]["chars"]
    assert summaries[0]["chars"] >= TIERS["low"] * 0.95


def test_chapters_have_realistic_length() -> None:
    chapters = generate_corpus("low", base=_base_chapters())

    assert len(chapters) >= 10
    lengths = [
        sum(1 for char in chapter["content"] if not char.isspace())
        for chapter in chapters
    ]
    # 单章约 3500 汉字（打包边界允许少量浮动）
    assert min(lengths) >= 2500
    assert max(lengths) <= 5000


def test_unknown_tier_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        generate_corpus("gigantic")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://localhost/main",
        "postgresql+asyncpg://localhost/ai_novel_acceptance_guimi",
        "sqlite+aiosqlite:///:memory:",
    ],
)
async def test_scale_gate_refuses_unprotected_database_before_connect(url, monkeypatch):
    from types import SimpleNamespace

    from tools.scale_gate_harness import run_gate

    def unexpected_connect(*args, **kwargs):
        raise AssertionError("must reject before engine creation")

    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", unexpected_connect)
    with pytest.raises(RuntimeError, match="dedicated|PostgreSQL"):
        await run_gate(SimpleNamespace(database_url=url))

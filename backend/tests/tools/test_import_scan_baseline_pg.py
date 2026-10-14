"""PG collection test for the G7a import-scan baseline (dedicated database).

Opt-in, mirroring the repository's explicit E2E conventions: the file carries
the ``e2e`` marker (excluded from default suites) and additionally requires
``IMPORT_SCAN_BASELINE_DATABASE_URL`` to point at the dedicated G7 database.
It never runs against a shared or development database and never calls a model.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tools.import_scan_baseline.collector import (
    ensure_schema,
    import_all_models,
    measure_tier,
    resolve_database_url,
    tier_result_to_dict,
)
from tools.import_scan_baseline.synthetic import TierSpec, spec_by_name

pytestmark = pytest.mark.e2e

# 小而完整的档位：3 章即覆盖全部链路，但实体数超过身份候选限额
# （character 6 / world object 16），确保 phase2_identity_top_k 省略真实发生。
_MINI_TIER = TierSpec(
    name="T03",
    chapters=3,
    scenes_per_chapter=3,
    canonical_entities=40,
    review_entities=10,
    relations=6,
)


def _database_url() -> str:
    explicit = os.environ.get("IMPORT_SCAN_BASELINE_DATABASE_URL")
    if not explicit:
        pytest.exit(
            "IMPORT_SCAN_BASELINE_DATABASE_URL 必须显式指向专用 G7 库"
            "（如 postgresql+asyncpg://novelist:…@127.0.0.1:5207/novel_pg_g7a）",
            returncode=2,
        )
    return resolve_database_url(explicit)


async def test_collects_stable_baseline_from_real_prepare_chain() -> None:
    url = _database_url()
    import_all_models()
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    try:
        schema = await ensure_schema(engine)
        assert schema["schema"] in {"alembic-head", "metadata-create-all"}

        result = await measure_tier(
            engine,
            _MINI_TIER,
            repeats=2,
            hot_read_repeats=2,
        )
        payload = tier_result_to_dict(result)

        assert result.seed_rows["chapters"] == 3
        assert result.seed_rows["scenes"] == 9
        assert result.seed_rows["entities"] == _MINI_TIER.entity_count

        # 真实调用链产出可用上下文：身份候选、省略来源与当前 Scene 文本都在。
        last = payload["calls"][-1]
        shape = last["contract_shape"]
        assert shape["identity_candidates"] >= 1
        assert shape["current_scene_chars"] > 0
        assert "current_scene_text_unavailable" not in shape["warnings"]

        # 热点两条查询都被打上专属标签且行数与档位实体数一致。
        by_label = last["trace"]["by_label"]
        assert by_label["select:world_context_entities"]["count"] == 1
        assert by_label["select:entity_terms"]["count"] == 1
        world_rows = {
            item.rows for item in result.hot_reads if item.name == "get_world_context"
        }
        terms_rows = {
            item.rows for item in result.hot_reads if item.name == "list_entity_terms"
        }
        assert world_rows == {_MINI_TIER.entity_count}
        assert terms_rows == {_MINI_TIER.canonical_entities}
        assert shape["omitted_sources"] >= 1

        # 稳态下重复调用的 SQL 条数一致（无随调用增长的查询泄漏）。
        counts = {call["trace"]["statements"] for call in payload["calls"]}
        assert len(counts) == 1

        assert payload["memory"]["tracemalloc_peak_bytes"] > 0
        assert (
            payload["hot_read_summary"]["get_world_context"]["rows"]
            == _MINI_TIER.entity_count
        )
    finally:
        await engine.dispose()


async def test_measure_tier_cleans_up_dedicated_database() -> None:
    from modules.account.models import Account
    from modules.project.models import Project

    url = _database_url()
    import_all_models()
    engine = create_async_engine(url, pool_size=2, max_overflow=0)
    try:
        await ensure_schema(engine)
        spec = spec_by_name("L10")
        await measure_tier(engine, spec, repeats=1, hot_read_repeats=1)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            novels = await db.execute(
                delete(Project).where(
                    Project.title == f"G7a 合成长篇基线 {spec.name}"
                )
            )
            owners = await db.execute(
                delete(Account).where(
                    Account.support_code == f"g7a-{spec.name.casefold()}"
                )
            )
            await db.commit()
        assert novels.rowcount == 0
        assert owners.rowcount == 0
    finally:
        await engine.dispose()

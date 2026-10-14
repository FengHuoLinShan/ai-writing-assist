"""Offline structural tests for the G7a import-scan baseline tooling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from tools.import_scan_baseline import collector, synthetic

PACKAGE_DIR = Path(collector.__file__).resolve().parent


# ---------------------------------------------------------------- generator


def test_same_tier_rebuilds_identical_synthetic_novel() -> None:
    for spec in synthetic.chapter_equivalent_tiers():
        first = synthetic.build_novel(spec)
        second = synthetic.build_novel(spec)
        assert first.content_digest() == second.content_digest()
        assert first.target_scene_id == second.target_scene_id
        assert [item.name for item in first.entities] == [
            item.name for item in second.entities
        ]


def test_chapter_tiers_scale_entities_and_terms_proportionally() -> None:
    l10, l30, l60 = synthetic.chapter_equivalent_tiers()
    assert (l10.chapters, l30.chapters, l60.chapters) == (10, 30, 60)
    for spec in (l10, l30, l60):
        assert spec.canonical_entities == 4 * spec.chapters
        assert spec.review_entities == spec.chapters
        assert spec.alias_term_count == spec.entity_count * 3
        assert spec.relations == 2 * spec.chapters


def test_density_tiers_probe_the_ten_thousand_limit_boundary() -> None:
    d2500, d5000, d10000 = synthetic.density_probe_tiers()
    assert d10000.entity_count == 10_000
    for smaller, larger in ((d2500, d5000), (d5000, d10000)):
        assert smaller.entity_count < larger.entity_count


def test_target_scene_text_mentions_top_entities_for_identity_flow() -> None:
    novel = synthetic.build_novel(synthetic.spec_by_name("L30"))
    target = novel.scenes[novel.target_scene_index]
    assert target.scene_index == len(novel.scenes) - 1
    text = novel.chapter_texts[-1][target.start_offset : target.end_offset]
    mentioned_names = {
        item.name
        for item in novel.entities
        if item.key in novel.mentioned_keys
    }
    assert mentioned_names, "tier must select mentioned entities"
    assert all(name in text for name in mentioned_names)


def test_relations_stay_unique_per_canonical_edge() -> None:
    for spec in (*synthetic.chapter_equivalent_tiers(), *synthetic.density_probe_tiers()):
        novel = synthetic.build_novel(spec)
        edges = {(item.source_key, item.target_key) for item in novel.relations}
        assert len(edges) == len(novel.relations)


def test_synthetic_prose_is_programmatic_and_copyright_free() -> None:
    novel = synthetic.build_novel(synthetic.spec_by_name("L10"))
    allowed_names = {item.name for item in novel.entities}
    for chapter_text in novel.chapter_texts:
        assert len(chapter_text) >= 2_500
        for sentence in chapter_text.split("\n"):
            assert sentence, "no empty paragraphs"
            assert sentence in synthetic._SENTENCES or any(
                name in sentence for name in allowed_names
            ), f"unexpected non-synthetic sentence: {sentence[:40]}"


# ------------------------------------------------------------ SQL labeling


def test_classify_statement_labels_the_hot_path_queries() -> None:
    assert (
        collector.classify_statement(
            "SELECT core_entities.id, core_entities.summary, core_entities.public_info "
            "FROM core_entities WHERE core_entities.novel_id = $1 "
            "AND core_entities.status IN ($2, $3, $4) "
            "ORDER BY core_entities.importance DESC LIMIT 10000"
        )
        == "select:world_context_entities"
    )
    assert (
        collector.classify_statement(
            "SELECT core_entities.id, core_entities.name, core_entities.entity_type, "
            "core_entities.status, core_entities.content_json -> $1 AS aliases "
            "FROM core_entities WHERE core_entities.novel_id = $1 "
            "ORDER BY core_entities.importance DESC LIMIT 10000"
        )
        == "select:entity_terms"
    )
    assert (
        collector.classify_statement(
            "SELECT core_entities.id, core_entities.name FROM core_entities "
            "WHERE core_entities.id IN ($1, $2)"
        )
        == "select:entity_endpoints"
    )
    assert (
        collector.classify_statement(
            "SELECT scenes.id, scenes.title FROM scenes WHERE scenes.novel_id = $1"
        )
        == "select:scenes"
    )
    assert (
        collector.classify_statement("UPDATE scene_spans SET status = $1")
        == "update:scene_spans"
    )
    assert (
        collector.classify_statement("INSERT INTO projects (id) VALUES ($1)")
        == "insert:projects"
    )


def test_sql_trace_counts_and_times_by_label() -> None:
    trace = collector.SqlTrace()
    statement = "SELECT scenes.id FROM scenes"
    trace.before_cursor_execute(None, None, statement, (), None, False)
    trace.after_cursor_execute(None, None, statement, (), None, False)
    trace.before_cursor_execute(None, None, statement, (), None, False)
    trace.after_cursor_execute(None, None, statement, (), None, False)
    report = trace.report()
    assert report["statements"] == 2
    assert report["by_label"]["select:scenes"]["count"] == 2
    assert trace.statement_shapes[statement] == 2


# ------------------------------------------------------- database targeting


def test_default_database_is_the_dedicated_g7_target(monkeypatch) -> None:
    monkeypatch.delenv("G7A_DATABASE_URL", raising=False)
    url = make_url(collector.resolve_database_url(None))
    assert url.database == "novel_pg_g7a"
    assert collector.resolve_database_url(None) == collector.DEFAULT_DATABASE


def test_resolve_database_url_refuses_shared_and_non_g7_targets(
    monkeypatch,
) -> None:
    monkeypatch.delenv("G7A_DATABASE_URL", raising=False)
    for bad in (
        "postgresql+asyncpg://localhost/novel_dev",
        "postgresql+asyncpg://localhost/ai_novel_engine",
        "postgresql+asyncpg://localhost/postgres",
        "postgresql+asyncpg://localhost/novel_production",
        "sqlite+aiosqlite:///:memory:",
    ):
        with pytest.raises(collector.BaselineTargetError):
            collector.resolve_database_url(bad)


def test_resolve_database_url_accepts_explicit_g7_marker(monkeypatch) -> None:
    monkeypatch.setenv("G7A_DATABASE_URL", "postgresql+asyncpg://x/audit_g7_probe")
    assert (
        collector.resolve_database_url(None)
        == "postgresql+asyncpg://x/audit_g7_probe"
    )


# ---------------------------------------------------------- ledger template


def test_ledger_template_keeps_dropped_and_omitted_in_the_denominator() -> None:
    template = json.loads(
        (PACKAGE_DIR / "ledger_template.json").read_text(encoding="utf-8")
    )
    rule = template["denominator_rules"]["units_total"]
    assert "units_dropped" in rule and "units_omitted" in rule
    for stage in template["stages"]:
        for column in (
            "units_total",
            "units_processed",
            "units_dropped",
            "dropped_reasons",
            "units_omitted",
            "omitted_reasons",
            "unknown_requests",
        ):
            assert column in stage, f"{stage['stage']} missing {column}"
    entity_stage = next(
        item for item in template["stages"] if item["stage"] == "entity_extraction"
    )
    assert "phase2_identity_top_k" in entity_stage["omitted_reasons"]


def test_ledger_template_tracks_unknown_and_author_disposition_separately() -> None:
    template = json.loads(
        (PACKAGE_DIR / "ledger_template.json").read_text(encoding="utf-8")
    )
    assert "unknown" in template["denominator_rules"]
    assert "author_disposition" in template["denominator_rules"]
    assert template["author_dispositions"]["transitions"] == {
        "adopted": None,
        "rejected": None,
        "edited_then_adopted": None,
        "deferred": None,
        "expired": None,
    }


def test_ledger_template_model_calls_align_with_meter_conventions() -> None:
    template = json.loads(
        (PACKAGE_DIR / "ledger_template.json").read_text(encoding="utf-8")
    )
    calls = template["model_calls"]
    sample = calls["calls"][0]
    for field in (
        "sequence",
        "status",
        "started_at",
        "cost_upper_usd",
        "request_hash",
        "usage",
        "budget_resolution",
    ):
        assert field in sample
    assert calls["cap_usd"] is None  # G7b 不设上限，但仍全量记账
    assert template["run"]["human_validated"] is False
    assert template["run"]["corpus_unit"]["sources"] == 63
    assert template["run"]["corpus_unit"]["characters"] == 212868


def test_ledger_template_inherits_p4e_evolution_metrics() -> None:
    template = json.loads(
        (PACKAGE_DIR / "ledger_template.json").read_text(encoding="utf-8")
    )
    origins = {
        item["id"]: item.get("origin") for item in template["metric_definitions"]
    }
    assert origins.get("evolution.world_coverage_per_scene") == "P4-E"
    assert origins.get("evolution.category_discovery_coverage") == "P4-E"
    assert origins.get("evolution.redo_scope_after_early_edit") == "P4-E"
    assert origins.get("import_scan.hotspot_sql_baseline") == "G7a"

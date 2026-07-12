"""Command-line entrypoint for local evaluation artifacts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from evals.cache import EvalCache
from evals.codex_executor import CodexStructuredExecutor
from evals.corpus import (
    CorpusSnapshot,
    build_fixture_source_snapshot,
    load_corpus_snapshot,
    source_path_for_variant,
)
from evals.generation import (
    HighQualityEvalLLM,
    JudgeDecision,
    materialize_generated_cases,
)
from evals.qc import run_deterministic_qc
from evals.readiness import (
    BASELINE_SCENARIOS,
    assess_baseline_readiness,
    is_baseline_eligible,
)
from evals.report import (
    build_dataset_report,
    build_result_version_reuse_proof,
    render_markdown_report,
)
from evals.review import (
    ReviewRecord,
    apply_review_records,
    export_review_csv,
    export_review_html,
    export_review_jsonl,
    human_review_quality,
    judge_human_agreement,
    load_review_records,
    select_balanced_review_supplement,
    select_double_review_cases,
    select_review_cases,
)
from evals.scene_gold import repair_scene_gold_cases
from evals.schemas import (
    ALLOWED_CODEX_REVIEW_MODELS,
    EVAL_ADJUDICATOR_MODEL,
    EVAL_REVIEWER_A_MODEL,
    EVAL_REVIEWER_B_MODEL,
    HIGH_QUALITY_LLM_FALLBACK_MODEL,
    DatasetCase,
    DatasetManifest,
    EvalResult,
    EvalSuite,
    QCDecision,
    RiskLevel,
    SystemUnderTestProfile,
)

_SCENARIOS = {
    suite.value: list(scenarios) for suite, scenarios in BASELINE_SCENARIOS.items()
}
PILOT_SUITE_SIZES = {"rag": 160, "scene": 80, "world": 100, "outline": 60}
PILOT_RAW_STEM = "pilot-v0.raw-judged"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    corpus_parser = subparsers.add_parser("corpus-manifest")
    corpus_parser.add_argument(
        "--variant",
        choices=("pilot", "full", "v1"),
        default="pilot",
    )
    corpus_parser.add_argument("--output", type=Path)

    fixture_parser = subparsers.add_parser("fixture-manifest")
    fixture_parser.add_argument("--output", type=Path)

    qc_parser = subparsers.add_parser("qc")
    qc_parser.add_argument("dataset", type=Path)
    qc_parser.add_argument("--variant", choices=("pilot", "full", "v1"), default="pilot")
    qc_parser.add_argument("--output", type=Path)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--suite", choices=tuple(_SCENARIOS), required=True)
    generate_parser.add_argument(
        "--variant",
        choices=("pilot", "full", "v1"),
        default="pilot",
    )
    generate_parser.add_argument("--size", type=int, default=20)
    generate_parser.add_argument("--output", type=Path, required=True)
    generate_parser.add_argument("--cache-dir", type=Path, default=Path("evals/.cache"))
    generate_parser.add_argument("--cache-only", action="store_true")

    judge_parser = subparsers.add_parser("judge")
    judge_parser.add_argument("dataset", type=Path)
    judge_parser.add_argument(
        "--variant", choices=("pilot", "full", "v1"), default="pilot"
    )
    judge_parser.add_argument("--output", type=Path, required=True)
    judge_parser.add_argument("--cache-dir", type=Path, default=Path("evals/.cache"))
    judge_parser.add_argument("--cache-only", action="store_true")

    calibrate_parser = subparsers.add_parser("judge-calibrate")
    calibrate_parser.add_argument("dataset", type=Path)
    calibrate_parser.add_argument("template", type=Path)
    calibrate_parser.add_argument(
        "--variant", choices=("pilot", "full", "v1"), default="pilot"
    )
    calibrate_parser.add_argument("--output", type=Path, required=True)
    calibrate_parser.add_argument("--cache-dir", type=Path, default=Path("evals/.cache"))

    review_export_parser = subparsers.add_parser("review-export")
    review_export_parser.add_argument("dataset", type=Path)
    review_export_parser.add_argument(
        "--variant", choices=("pilot", "full", "v1"), default="pilot"
    )
    review_export_parser.add_argument("--html", type=Path, required=True)
    review_export_parser.add_argument("--jsonl", type=Path, required=True)
    review_export_parser.add_argument("--csv", type=Path)
    review_export_parser.add_argument("--double-html", type=Path)
    review_export_parser.add_argument("--double-jsonl", type=Path)
    review_export_parser.add_argument("--double-csv", type=Path)
    review_export_parser.add_argument("--all", action="store_true")
    review_export_parser.add_argument("--supplement-size", type=int)
    review_export_parser.add_argument(
        "--review-status",
        choices=("unreviewed", "accepted", "edited", "rejected", "ambiguous"),
    )
    review_export_parser.add_argument("--case-id", action="append", default=[])

    review_import_parser = subparsers.add_parser("review-import")
    review_import_parser.add_argument("dataset", type=Path)
    review_import_parser.add_argument("reviews", type=Path)
    review_import_parser.add_argument("--reviewer-version", required=True)
    review_import_parser.add_argument("--output", type=Path, required=True)
    review_import_parser.add_argument("--report", type=Path, required=True)
    review_import_parser.add_argument("--adjudication", action="store_true")

    model_review_parser = subparsers.add_parser("review-model")
    model_review_parser.add_argument("dataset", type=Path)
    model_review_parser.add_argument("template", type=Path)
    model_review_parser.add_argument(
        "--variant", choices=("pilot", "full", "v1"), default="pilot"
    )
    model_review_parser.add_argument(
        "--model",
        choices=(
            "deepseek-v4-flash",
            "gpt-5.6-luna",
            "gpt-5.6-terra",
        ),
        required=True,
    )
    model_review_parser.add_argument("--reviewer-role", required=True)
    model_review_parser.add_argument("--novel-id")
    model_review_parser.add_argument(
        "--suite", choices=("rag", "scene", "world", "outline")
    )
    model_review_parser.add_argument("--output", type=Path, required=True)
    model_review_parser.add_argument(
        "--cache-dir", type=Path, default=Path("evals/.cache")
    )

    scene_gold_parser = subparsers.add_parser("scene-gold-repair")
    scene_gold_parser.add_argument("dataset", type=Path)
    scene_gold_parser.add_argument(
        "--variant", choices=("pilot", "full", "v1"), default="pilot"
    )
    scene_gold_parser.add_argument(
        "--model",
        choices=("gpt-5.3-codex-spark", "gpt-5.6-luna"),
        default="gpt-5.3-codex-spark",
    )
    scene_gold_parser.add_argument(
        "--fallback-model",
        choices=("gpt-5.6-luna",),
        default="gpt-5.6-luna",
    )
    scene_gold_parser.add_argument("--output", type=Path, required=True)
    scene_gold_parser.add_argument("--meta", type=Path, required=True)
    scene_gold_parser.add_argument("--cache-dir", type=Path, default=Path("evals/.cache"))
    scene_gold_parser.add_argument("--cache-only", action="store_true")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("dataset", type=Path)
    report_parser.add_argument(
        "--variant", choices=("pilot", "full", "v1"), default="pilot"
    )
    report_parser.add_argument("--dataset-id", required=True)
    report_parser.add_argument("--dataset-version", required=True)
    report_parser.add_argument("--result", action="append", type=Path, default=[])
    report_parser.add_argument(
        "--result-version-reuse",
        action="append",
        default=[],
        metavar="SUITE:VERSION:DATASET",
        help=(
            "explicitly prove a reused result suite is unchanged from VERSION by "
            "comparing DATASET with the target dataset"
        ),
    )
    report_parser.add_argument("--raw-reviewed-dataset", type=Path)
    report_parser.add_argument("--json", type=Path, required=True)
    report_parser.add_argument("--markdown", type=Path, required=True)

    prepare_rag_parser = subparsers.add_parser("prepare-rag")
    prepare_rag_parser.add_argument("--novel-id", required=True)
    prepare_rag_parser.add_argument("--chapter-from", type=int, required=True)
    prepare_rag_parser.add_argument("--chapter-to", type=int, required=True)
    prepare_rag_parser.add_argument(
        "--content-mode",
        choices=("canonical", "working"),
        default="canonical",
    )
    prepare_rag_parser.add_argument("--force", action="store_true")
    prepare_rag_parser.add_argument("--output", type=Path)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("dataset", type=Path)
    run_parser.add_argument(
        "--suite",
        choices=("rag", "scene", "world", "outline", "all"),
        required=True,
    )
    run_parser.add_argument("--novel-id", required=True)
    run_parser.add_argument("--dataset-id", required=True)
    run_parser.add_argument("--dataset-version", required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--isolated-db", action="store_true")
    run_parser.add_argument(
        "--baseline-tier",
        choices=("pilot", "release"),
        default="pilot",
    )
    run_parser.add_argument("--allow-unfrozen", action="store_true")

    context_planner_parser = subparsers.add_parser("context-planner")
    context_planner_parser.add_argument("dataset", type=Path)
    context_planner_parser.add_argument("--novel-id", required=True)
    context_planner_parser.add_argument("--dataset-version", required=True)
    context_planner_parser.add_argument("--sut-profile", required=True)
    context_planner_parser.add_argument("--output", type=Path, required=True)

    readiness_parser = subparsers.add_parser("baseline-check")
    readiness_parser.add_argument("dataset", type=Path)
    readiness_parser.add_argument(
        "--suite",
        choices=("rag", "scene", "world", "outline", "all"),
        default="all",
    )
    readiness_parser.add_argument(
        "--tier",
        choices=("pilot", "release"),
        default="pilot",
    )
    readiness_parser.add_argument("--output", type=Path)

    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("dataset", type=Path)
    freeze_parser.add_argument(
        "--variant",
        choices=("pilot", "full", "v1"),
        default="pilot",
    )
    freeze_parser.add_argument(
        "--tier",
        choices=("pilot", "release"),
        default="pilot",
    )
    freeze_parser.add_argument("--dataset-id", required=True)
    freeze_parser.add_argument("--dataset-version", required=True)
    freeze_parser.add_argument("--output", type=Path, required=True)
    freeze_parser.add_argument("--manifest", type=Path, required=True)
    freeze_parser.add_argument("--readiness", type=Path, required=True)

    pilot_parser = subparsers.add_parser("pilot")
    pilot_parser.add_argument(
        "--variant", choices=("pilot", "full", "v1"), default="pilot"
    )
    pilot_parser.add_argument(
        "--stage", choices=("generate", "judge", "all"), default="all"
    )
    pilot_parser.add_argument("--output-dir", type=Path, required=True)
    pilot_parser.add_argument("--cache-dir", type=Path, default=Path("evals/.cache"))
    pilot_parser.add_argument("--cache-only", action="store_true")

    args = parser.parse_args()
    if args.command == "corpus-manifest":
        _corpus_manifest(args.variant, args.output)
    elif args.command == "fixture-manifest":
        _fixture_manifest(args.output)
    elif args.command == "qc":
        _qc(args.dataset, args.variant, args.output)
    elif args.command == "generate":
        asyncio.run(
            _generate(
                suite=args.suite,
                variant=args.variant,
                size=args.size,
                output=args.output,
                cache_dir=args.cache_dir,
                cache_only=args.cache_only,
            )
        )
    elif args.command == "judge":
        asyncio.run(
            _judge(
                dataset=args.dataset,
                variant=args.variant,
                output=args.output,
                cache_dir=args.cache_dir,
                cache_only=args.cache_only,
            )
        )
    elif args.command == "judge-calibrate":
        asyncio.run(
            _judge_calibrate(
                dataset=args.dataset,
                template=args.template,
                variant=args.variant,
                output=args.output,
                cache_dir=args.cache_dir,
            )
        )
    elif args.command == "review-export":
        _review_export(
            dataset=args.dataset,
            variant=args.variant,
            html_output=args.html,
            jsonl_output=args.jsonl,
            csv_output=args.csv,
            double_html_output=args.double_html,
            double_jsonl_output=args.double_jsonl,
            double_csv_output=args.double_csv,
            select_all=args.all,
            supplement_size=args.supplement_size,
            review_status=args.review_status,
            case_ids=args.case_id,
        )
    elif args.command == "review-import":
        _review_import(
            dataset=args.dataset,
            reviews=args.reviews,
            reviewer_version=args.reviewer_version,
            output=args.output,
            report=args.report,
            adjudication=args.adjudication,
        )
    elif args.command == "review-model":
        asyncio.run(
            _model_review(
                dataset=args.dataset,
                template=args.template,
                variant=args.variant,
                model=args.model,
                reviewer_role=args.reviewer_role,
                suite=args.suite,
                novel_id=args.novel_id,
                output=args.output,
                cache_dir=args.cache_dir,
            )
        )
    elif args.command == "scene-gold-repair":
        asyncio.run(
            _scene_gold_repair(
                dataset=args.dataset,
                variant=args.variant,
                model=args.model,
                fallback_model=args.fallback_model,
                output=args.output,
                meta_output=args.meta,
                cache_dir=args.cache_dir,
                cache_only=args.cache_only,
            )
        )
    elif args.command == "report":
        _report(
            dataset=args.dataset,
            variant=args.variant,
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            result_paths=args.result,
            result_version_reuse=args.result_version_reuse,
            raw_reviewed_dataset=args.raw_reviewed_dataset,
            json_output=args.json,
            markdown_output=args.markdown,
        )
    elif args.command == "prepare-rag":
        asyncio.run(
            _prepare_rag_index(
                novel_id=args.novel_id,
                chapter_from=args.chapter_from,
                chapter_to=args.chapter_to,
                content_mode=args.content_mode,
                force=args.force,
                output=args.output,
            )
        )
    elif args.command == "run":
        asyncio.run(
            _run_workflow_evaluation(
                dataset=args.dataset,
                suite=args.suite,
                novel_id=args.novel_id,
                dataset_id=args.dataset_id,
                dataset_version=args.dataset_version,
                output_dir=args.output_dir,
                isolated_db=args.isolated_db,
                baseline_tier=args.baseline_tier,
                allow_unfrozen=args.allow_unfrozen,
            )
        )
    elif args.command == "baseline-check":
        report = _baseline_check(
            dataset=args.dataset,
            suite=args.suite,
            tier=args.tier,
            output=args.output,
        )
        if not report["ready"]:
            raise SystemExit(2)
    elif args.command == "context-planner":
        asyncio.run(
            _run_context_planner_evaluation(
                dataset=args.dataset,
                novel_id=args.novel_id,
                dataset_version=args.dataset_version,
                sut_profile=args.sut_profile,
                output=args.output,
            )
        )
    elif args.command == "freeze":
        _freeze_dataset(
            dataset=args.dataset,
            variant=args.variant,
            tier=args.tier,
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            output=args.output,
            manifest_output=args.manifest,
            readiness_output=args.readiness,
        )
    elif args.command == "pilot":
        asyncio.run(
            _pilot(
                variant=args.variant,
                stage=args.stage,
                output_dir=args.output_dir,
                cache_dir=args.cache_dir,
                cache_only=args.cache_only,
            )
        )


def _corpus_manifest(variant: str, output: Path | None) -> None:
    snapshot = load_corpus_snapshot(variant)
    payload = snapshot.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")


def _fixture_manifest(output: Path | None) -> None:
    text = build_fixture_source_snapshot().model_dump_json(indent=2)
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")


async def _run_context_planner_evaluation(
    *,
    dataset: Path,
    novel_id: str,
    dataset_version: str,
    sut_profile: str,
    output: Path,
) -> None:
    from core.database import get_manager
    from evals.runners.context_planner import evaluate_context_planner_cases

    async with get_manager().session_factory() as db:
        report = await evaluate_context_planner_cases(
            db,
            novel_id,
            _load_cases(dataset),
            dataset_version=dataset_version,
            sut_profile=sut_profile,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


async def _scene_gold_repair(
    *,
    dataset: Path,
    variant: str,
    model: str,
    fallback_model: str,
    output: Path,
    meta_output: Path,
    cache_dir: Path,
    cache_only: bool,
) -> None:
    repaired, meta = await repair_scene_gold_cases(
        _load_cases(dataset),
        source_path=source_path_for_variant(variant),
        source_alias=f"lotm-clown-{variant}",
        cache=EvalCache(cache_dir),
        primary_executor=CodexStructuredExecutor(model=model),
        fallback_executor=CodexStructuredExecutor(
            model=fallback_model,
            reasoning_effort="medium",
        ),
        cache_only=cache_only,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        "\n".join(case.model_dump_json() for case in repaired) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    meta_output.parent.mkdir(parents=True, exist_ok=True)
    meta_temporary = meta_output.with_suffix(meta_output.suffix + ".tmp")
    meta_temporary.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    meta_temporary.replace(meta_output)


async def _run_workflow_evaluation(
    *,
    dataset: Path,
    suite: str,
    novel_id: str,
    dataset_id: str,
    dataset_version: str,
    output_dir: Path,
    isolated_db: bool,
    baseline_tier: str = "pilot",
    allow_unfrozen: bool = False,
) -> None:
    if suite != "rag" and not isolated_db:
        raise ValueError(
            "Scene/World/Outline eval runners require --isolated-db",
        )
    cases = _load_cases(dataset)
    selected_suites = _selected_suites(suite)
    readiness = assess_baseline_readiness(
        cases,
        tier=baseline_tier,  # type: ignore[arg-type]
        suites=tuple(EvalSuite),
    )
    if not readiness["ready"] and not allow_unfrozen:
        raise ValueError(
            "dataset is not baseline-ready: "
            + json.dumps(readiness["issues"], ensure_ascii=False),
        )
    selected = tuple(item.value for item in selected_suites)
    from core.database import get_manager

    output_dir.mkdir(parents=True, exist_ok=True)
    container_registered = False
    if "world" in selected:
        from app.bootstrap import register_container_services

        register_container_services(ignore_existing=True)
        container_registered = True
    manager = get_manager()
    try:
        async with manager.session_factory() as db:
            from modules.project.facade import open_project_llm_client

            async with open_project_llm_client(db, novel_id) as profile_client:
                summary = profile_client.profile_summary
            system_under_test = SystemUnderTestProfile(
                provider_id=str(summary.get("provider_id") or "unknown"),
                model=str(summary.get("model") or "unknown"),
                label=(str(summary["label"]) if summary.get("label") else None),
                profile_hash=hashlib.sha256(
                    json.dumps(summary, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            )
            for selected_suite in selected:
                if selected_suite == "rag":
                    from evals.runners.rag import evaluate_rag_cases

                    preflight = await _rag_preflight(db, novel_id, cases)
                    result = await evaluate_rag_cases(
                        db,
                        novel_id,
                        cases,
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                    )
                    result.run_context["rag_preflight"] = preflight
                elif selected_suite == "scene":
                    from evals.runners.scene import run_scene_workflow_cases

                    result = await run_scene_workflow_cases(
                        db,
                        novel_id,
                        cases,
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                        isolated_db=isolated_db,
                    )
                elif selected_suite == "world":
                    from evals.runners.world import run_world_workflow_cases

                    result = await run_world_workflow_cases(
                        db,
                        novel_id,
                        cases,
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                        isolated_db=isolated_db,
                    )
                else:
                    from evals.runners.outline import run_outline_preview_cases

                    result = await run_outline_preview_cases(
                        db,
                        novel_id,
                        cases,
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                        isolated_db=isolated_db,
                    )
                result = result.model_copy(
                    update={"system_under_test": system_under_test}
                )
                if system_under_test.model == "deepseek-v4-flash":
                    result.run_context["model_budget_assumptions"] = {
                        "max_tokens_per_zh_character": 1.0,
                        "source": (
                            "0.75_pilot_still_hit_length_use_non_forcing_upper_bound_1.0"
                        ),
                    }
                if not readiness["ready"]:
                    result.errors.append("unfrozen_dataset_smoke_only")
                _write_eval_result(result, output_dir)
            await db.commit()
    finally:
        from infrastructure.embedding.client import BgeEmbeddingClient

        await BgeEmbeddingClient.close_instance()
        if container_registered:
            from core.container import shutdown

            await shutdown()
        await manager.close()


async def _prepare_rag_index(
    *,
    novel_id: str,
    chapter_from: int,
    chapter_to: int,
    content_mode: str,
    force: bool,
    output: Path | None,
) -> dict[str, object]:
    """Build a reproducible derived RAG index for baseline execution."""
    if chapter_from < 1 or chapter_to < chapter_from:
        raise ValueError("chapter range must satisfy 1 <= from <= to")
    from core.database import get_manager
    from modules.rag.facade import get_index_freshness, index_chapter_with_report
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import list_manuscript_sources

    manager = get_manager()
    chapters = list(range(chapter_from, chapter_to + 1))
    state_service = RagIndexStateService()
    chapter_reports: list[dict[str, object]] = []
    try:
        async with manager.session_factory() as db:
            sources = await list_manuscript_sources(
                db,
                novel_id,
                chapters,
                content_mode=content_mode,
            )
            source_chapters = {int(source.chapter_index) for source in sources}
            missing_sources = sorted(set(chapters) - source_chapters)
            if missing_sources:
                raise ValueError(
                    f"RAG preparation missing {content_mode} sources: {missing_sources}"
                )
            for position, chapter_index in enumerate(chapters, start=1):
                claimed = await state_service.begin_direct(
                    db,
                    novel_id=novel_id,
                    chapter_index=chapter_index,
                    content_mode=content_mode,
                    force=force,
                )
                if not claimed:
                    freshness = await get_index_freshness(
                        db,
                        novel_id,
                        content_mode=content_mode,
                        chapter_from=chapter_index,
                        chapter_to=chapter_index,
                    )
                    if int(freshness.get("fresh", 0)) != 1:
                        raise RuntimeError(
                            f"chapter {chapter_index} index is already running or stale"
                        )
                    chapter_reports.append(
                        {"chapter_index": chapter_index, "status": "already_fresh"}
                    )
                    print(
                        f"[eval-rag-prepare] chapter={position}/{len(chapters)} "
                        "status=already_fresh",
                        flush=True,
                    )
                    continue
                try:
                    report = await index_chapter_with_report(
                        db,
                        novel_id,
                        chapter_index,
                        content_mode=content_mode,
                    )
                    if report.embedding_failed_count:
                        raise RuntimeError(
                            f"chapter {chapter_index} has "
                            f"{report.embedding_failed_count} failed embeddings"
                        )
                    await state_service.finish(db, novel_id=novel_id, report=report)
                    await db.commit()
                except Exception as exc:
                    await state_service.fail(
                        db,
                        novel_id=novel_id,
                        chapter_index=chapter_index,
                        content_mode=content_mode,
                        error=str(exc),
                    )
                    await db.commit()
                    raise
                chapter_reports.append(
                    {
                        "chapter_index": chapter_index,
                        "status": "indexed",
                        "chunks_created": report.chunks_created,
                        "embedding_failed_count": report.embedding_failed_count,
                        "warnings": report.warnings,
                    }
                )
                print(
                    f"[eval-rag-prepare] chapter={position}/{len(chapters)} "
                    f"chunks={report.chunks_created} "
                    f"embedding_failed={report.embedding_failed_count}",
                    flush=True,
                )
            freshness = await get_index_freshness(
                db,
                novel_id,
                content_mode=content_mode,
                chapter_from=chapter_from,
                chapter_to=chapter_to,
            )
    finally:
        from infrastructure.embedding.client import BgeEmbeddingClient

        await BgeEmbeddingClient.close_instance()
        await manager.close()
    result = {
        "novel_id": novel_id,
        "content_mode": content_mode,
        "chapter_from": chapter_from,
        "chapter_to": chapter_to,
        "chapter_count": len(chapters),
        "freshness": freshness,
        "chunks_created": sum(
            int(report.get("chunks_created", 0)) for report in chapter_reports
        ),
        "embedding_failed_count": sum(
            int(report.get("embedding_failed_count", 0)) for report in chapter_reports
        ),
        "chapters": chapter_reports,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        "[eval-rag-prepare] complete "
        f"chapters={len(chapters)} fresh={freshness.get('fresh')} "
        f"output={output or '-'}",
        flush=True,
    )
    return result


async def _rag_preflight(
    db,
    novel_id: str,
    cases: list[DatasetCase],
    *,
    list_sources_fn=None,
    freshness_fn=None,
    index_status_fn=None,
) -> dict[str, object]:
    """Prove that every referenced chapter has a matching fresh RAG index."""
    if list_sources_fn is None:
        from modules.writing.facade import list_manuscript_sources as list_sources_fn
    if freshness_fn is None:
        from modules.rag.facade import get_index_freshness as freshness_fn
    if index_status_fn is None:
        from modules.rag.facade import get_index_status as index_status_fn

    chapters_by_mode: dict[str, set[int]] = {}
    for case in cases:
        if case.suite != EvalSuite.rag:
            continue
        content_mode = str(case.input.get("content_mode") or "canonical")
        refs = [*case.source_refs, *case.hard_negative_refs]
        chapters_by_mode.setdefault(content_mode, set()).update(
            ref.chapter_index for ref in refs
        )
    if not chapters_by_mode or not any(chapters_by_mode.values()):
        raise ValueError("rag preflight failed: dataset has no referenced chapters")

    mode_reports: dict[str, object] = {}
    failed = False
    for content_mode, chapter_set in sorted(chapters_by_mode.items()):
        chapters = sorted(chapter_set)
        sources = await list_sources_fn(
            db,
            novel_id,
            chapters,
            content_mode=content_mode,
        )
        source_chapters = {int(source.chapter_index) for source in sources}
        missing_sources = sorted(chapter_set - source_chapters)
        missing_index: list[int] = []
        stale_index: list[int] = []
        for chapter_index in chapters:
            freshness = await freshness_fn(
                db,
                novel_id,
                content_mode=content_mode,
                chapter_from=chapter_index,
                chapter_to=chapter_index,
            )
            if int(freshness.get("total", 0)) != 1:
                missing_index.append(chapter_index)
            elif int(freshness.get("fresh", 0)) != 1:
                stale_index.append(chapter_index)
        report = {
            "expected_chapter_count": len(chapters),
            "expected_chapters": chapters,
            "source_chapter_count": len(source_chapters & chapter_set),
            "missing_source_chapters": missing_sources,
            "fresh_index_chapter_count": (
                len(chapters) - len(missing_index) - len(stale_index)
            ),
            "missing_index_chapters": missing_index,
            "stale_index_chapters": stale_index,
        }
        mode_reports[content_mode] = report
        failed = failed or bool(missing_sources or missing_index or stale_index)
    index_status = await index_status_fn(db, novel_id)
    embedding_diagnostics = {
        "embedding_failed_count": int(index_status.get("embedding_failed_count", 0)),
        "pending_vectorization": int(index_status.get("pending_vectorization", 0)),
        "embedding_dimension_mismatch": bool(
            index_status.get("embedding_dimension_mismatch")
        ),
        "embedding_provider": index_status.get("embedding_provider"),
        "embedding_model": index_status.get("embedding_model"),
    }
    failed = failed or bool(
        embedding_diagnostics["embedding_failed_count"]
        or embedding_diagnostics["pending_vectorization"]
        or embedding_diagnostics["embedding_dimension_mismatch"]
    )
    result = {
        "ready": not failed,
        "content_modes": mode_reports,
        "embedding": embedding_diagnostics,
    }
    if failed:
        raise ValueError(
            "rag preflight failed: " + json.dumps(result, ensure_ascii=False)
        )
    return result


def _write_eval_result(result: EvalResult, output_dir: Path) -> Path:
    output = output_dir / f"{result.suite.value}.result.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(
        f"[eval-run] suite={result.suite.value} cases={len(result.case_results)} "
        f"output={output}",
        flush=True,
    )
    return output


def _baseline_check(
    *,
    dataset: Path,
    suite: str,
    tier: str,
    output: Path | None,
) -> dict[str, object]:
    report = assess_baseline_readiness(
        _load_cases(dataset),
        tier=tier,  # type: ignore[arg-type]
        suites=_selected_suites(suite),
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        print(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return report


def _selected_suites(suite: str) -> tuple[EvalSuite, ...]:
    if suite == "all":
        return tuple(EvalSuite)
    return (EvalSuite(suite),)


def _freeze_dataset(
    *,
    dataset: Path,
    variant: str,
    tier: str,
    dataset_id: str,
    dataset_version: str,
    output: Path,
    manifest_output: Path,
    readiness_output: Path,
) -> None:
    cases = _load_cases(dataset)
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    deterministic = run_deterministic_qc(
        cases,
        corpora={corpus.source_alias: corpus},
        source_texts={corpus.source_alias: source_text},
    )
    current_errors = deterministic["errors"]
    accepted = [
        case
        for case in cases
        if is_baseline_eligible(case) and not current_errors.get(case.case_id)
    ]
    readiness = assess_baseline_readiness(
        accepted,
        tier=tier,  # type: ignore[arg-type]
        suites=tuple(EvalSuite),
    )
    excluded_ids = sorted(
        set(case.case_id for case in cases) - {case.case_id for case in accepted}
    )
    source_review_quality = human_review_quality(cases)
    accepted_review_quality = human_review_quality(accepted)
    readiness["source_human_review_quality"] = source_review_quality
    readiness["accepted_human_review_quality"] = accepted_review_quality
    if not accepted_review_quality["faithful_gate_passed"]:
        readiness["issues"].append("human_reference_faithful_rate_below_threshold")
    if not accepted_review_quality["invalid_gate_passed"]:
        readiness["issues"].append("human_ambiguous_invalid_rate_above_threshold")
    readiness["ready"] = not readiness["issues"]
    readiness.update(
        {
            "input_case_count": len(cases),
            "excluded_case_count": len(excluded_ids),
            "excluded_case_ids": excluded_ids,
            "deterministic_error_case_count": len(current_errors),
        }
    )
    readiness_output.parent.mkdir(parents=True, exist_ok=True)
    readiness_output.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not readiness["ready"]:
        raise ValueError(
            "accepted dataset is not baseline-ready: "
            + json.dumps(readiness["issues"], ensure_ascii=False),
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        "\n".join(case.model_dump_json() for case in accepted) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    source_dataset_hash = hashlib.sha256(dataset.read_bytes()).hexdigest()
    excluded_ids_hash = hashlib.sha256(
        "\n".join(excluded_ids).encode("utf-8")
    ).hexdigest()
    manifest = DatasetManifest(
        dataset_id=dataset_id,
        version=dataset_version,
        corpus_id=corpus.corpus_id,
        corpus_hash=corpus.file_hash,
        source_aliases=[corpus.source_alias],
        case_count=len(accepted),
        suite_counts=dict(Counter(case.suite for case in accepted)),
        split_counts=dict(Counter(case.split for case in accepted)),
        generator_model=_model_set_label(case.generation_meta.model for case in accepted),
        judge_model=_model_set_label(
            str(decision.get("model"))
            for case in accepted
            for decision in case.qc.judge_decisions
            if decision.get("model")
        ),
        prompt_hashes={
            f"case:{case.case_id}": case.generation_meta.prompt_hash for case in accepted
        },
        generation_runs=_case_generation_run_provenance(accepted),
        judge_runs=_judge_run_provenance(accepted),
        range_locator_runs=_range_locator_run_provenance(accepted),
        selection_meta={
            "baseline_tier": tier,
            "source_dataset_hash": source_dataset_hash,
            "input_case_count": len(cases),
            "accepted_case_count": len(accepted),
            "excluded_case_count": len(excluded_ids),
            "excluded_case_ids_hash": excluded_ids_hash,
            "selection_rule": "stored_decisions_plus_current_deterministic_qc",
            "reviewer_versions": sorted(
                {
                    review.reviewer_version
                    for case in accepted
                    for review in case.human_review.independent_reviews
                }
            ),
        },
    )
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[eval-freeze] accepted={len(accepted)} excluded={len(excluded_ids)} "
        f"output={output} manifest={manifest_output}",
        flush=True,
    )


def _model_set_label(models) -> str:
    values = sorted({str(model) for model in models if model})
    if not values:
        return "unavailable"
    if len(values) == 1:
        return values[0]
    return "mixed:" + ",".join(values)


def _case_generation_run_provenance(cases: list[DatasetCase]) -> list[dict]:
    records = []
    for case in cases:
        meta = case.generation_meta
        records.append(
            {
                "_case_id": case.case_id,
                "step": "case_generation",
                "model": meta.model,
                "reasoning_effort": meta.reasoning_effort,
                "prompt_hash": meta.prompt_hash,
                "executor_hash": meta.profile_hash,
                "seed": meta.seed,
                "source_hash": meta.source_hash,
                "duration_ms": meta.duration_ms,
                "cost_usd": meta.cost_usd,
                "cost_status": meta.cost_status,
                "cached": meta.cached,
            }
        )
    return _summarize_case_runs(records)


def _judge_run_provenance(cases: list[DatasetCase]) -> list[dict]:
    records = []
    for case in cases:
        for decision in case.qc.judge_decisions:
            model = str(decision.get("model") or "")
            reasoning_recorded = "reasoning_effort" in decision
            reasoning_effort = decision.get("reasoning_effort")
            if reasoning_effort is None and model == HIGH_QUALITY_LLM_FALLBACK_MODEL:
                reasoning_effort = "medium"
            executor_hash = str(decision.get("executor_hash") or "")
            executor_recorded = bool(executor_hash)
            if not executor_hash and model:
                try:
                    executor_hash = CodexStructuredExecutor(
                        model=model,
                        reasoning_effort=(
                            str(reasoning_effort) if reasoning_effort else None
                        ),
                    ).meta.executor_hash
                except ValueError:
                    executor_hash = "unavailable"
            duration_recorded = "duration_ms" in decision
            cached_recorded = "cached" in decision
            records.append(
                {
                    "_case_id": case.case_id,
                    "step": f"judge_round_{decision.get('round', 'unknown')}",
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                    "prompt_hash": decision.get("prompt_hash"),
                    "executor_hash": executor_hash,
                    "executor_hash_source": (
                        "recorded"
                        if executor_recorded
                        else "reconstructed_from_model_config"
                    ),
                    "reasoning_effort_source": (
                        "recorded" if reasoning_recorded else "inferred_from_model_policy"
                    ),
                    "duration_ms": decision.get("duration_ms"),
                    "duration_status": (
                        "recorded" if duration_recorded else "unknown_historical"
                    ),
                    "cost_usd": decision.get("cost_usd"),
                    "cost_status": decision.get("cost_status", "unavailable_codex_cli"),
                    "cached": decision.get("cached") if cached_recorded else None,
                    "cached_status": (
                        "recorded" if cached_recorded else "unknown_historical"
                    ),
                    "provenance_status": (
                        "recorded"
                        if all(
                            (
                                executor_recorded,
                                reasoning_recorded,
                                duration_recorded,
                                cached_recorded,
                            )
                        )
                        else "partial_reconstructed"
                    ),
                    "rubric_version": decision.get("rubric_version", "v1"),
                }
            )
    return _summarize_case_runs(records)


def _range_locator_run_provenance(cases: list[DatasetCase]) -> list[dict]:
    records = []
    for case in cases:
        meta = case.reference.get("canonical_range_meta")
        if case.suite != EvalSuite.scene or not isinstance(meta, dict):
            continue
        model = str(meta.get("model") or "")
        reasoning_effort = meta.get("reasoning_effort")
        if reasoning_effort is None and model == HIGH_QUALITY_LLM_FALLBACK_MODEL:
            reasoning_effort = "medium"
        executor_hash = "unavailable"
        if model:
            try:
                executor_hash = CodexStructuredExecutor(model=model).meta.executor_hash
            except ValueError:
                pass
        records.append(
            {
                "_case_id": case.case_id,
                "step": "scene_gold_range_locator",
                "model": model,
                "reasoning_effort": reasoning_effort,
                "prompt_hash": meta.get("prompt_hash"),
                "executor_hash": executor_hash,
                "executor_hash_source": "reconstructed_from_model_config",
                "reasoning_effort_source": "inferred_from_model_policy",
                "duration_ms": None,
                "duration_status": "unknown_historical",
                "cached": None,
                "cached_status": "unknown_historical",
                "provenance_status": "partial_reconstructed",
                "source_hash": case.generation_meta.source_hash,
            }
        )
    return _summarize_case_runs(records)


def _summarize_case_runs(records: list[dict]) -> list[dict]:
    grouped: dict[str, tuple[dict, list[str]]] = {}
    for raw in records:
        record = dict(raw)
        case_id = str(record.pop("_case_id"))
        key = json.dumps(record, ensure_ascii=False, sort_keys=True)
        grouped.setdefault(key, (record, []))[1].append(case_id)
    summaries = []
    for record, case_ids in grouped.values():
        ordered_ids = sorted(case_ids)
        summaries.append(
            {
                **record,
                "case_count": len(ordered_ids),
                "case_ids_hash": hashlib.sha256(
                    "\n".join(ordered_ids).encode("utf-8")
                ).hexdigest(),
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            str(item.get("step")),
            str(item.get("model")),
            str(item.get("prompt_hash")),
        ),
    )


def _deduplicate_run_records(records: list[dict]) -> list[dict]:
    unique = {
        json.dumps(record, ensure_ascii=False, sort_keys=True): record
        for record in records
    }
    return [unique[key] for key in sorted(unique)]


def _qc(dataset_path: Path, variant: str, output: Path | None) -> None:
    cases = _load_cases(dataset_path)
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    report = run_deterministic_qc(
        cases,
        corpora={corpus.source_alias: corpus},
        source_texts={corpus.source_alias: source_text},
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")


async def _generate(
    *,
    suite: str,
    variant: str,
    size: int,
    output: Path,
    cache_dir: Path,
    cache_only: bool = False,
) -> None:
    if size < 1:
        raise ValueError("size must be positive")
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    chapter_batches = [
        corpus.chapters[index : index + 5] for index in range(0, len(corpus.chapters), 5)
    ]
    target_per_batch = max(1, math.ceil(size / len(chapter_batches)))
    generated: list[DatasetCase] = []
    reference_records: list[dict] = []
    generation_runs: list[dict] = []
    evaluator = HighQualityEvalLLM(
        CodexStructuredExecutor(),
        cache=EvalCache(cache_dir),
        cache_only=cache_only,
    )
    reference_output = output.with_suffix(".references.json")
    for batch_number, batch in enumerate(chapter_batches, start=1):
        if len(generated) >= size:
            break
        print(
            f"[eval-generate] suite={suite} batch={batch_number}/"
            f"{len(chapter_batches)} cases={len(generated)}/{size} "
            "step=reference_snapshot",
            flush=True,
        )
        excerpt = "\n\n".join(
            source_text[item.start_offset : item.end_offset][:5000] for item in batch
        )
        target = min(target_per_batch, size - len(generated))
        snapshot, snapshot_meta = await evaluator.generate_reference_snapshot(
            suite=suite,
            source_excerpt=excerpt,
            chapter_indices=[item.chapter_index for item in batch],
            scenarios=_SCENARIOS[suite],
            count=target,
        )
        reference_records.append(
            {
                "batch": batch_number,
                "chapter_indices": [item.chapter_index for item in batch],
                "run_meta": _run_meta_payload(snapshot_meta),
                "snapshot": snapshot.model_dump(mode="json"),
            }
        )
        reference_output.parent.mkdir(parents=True, exist_ok=True)
        reference_output.write_text(
            json.dumps(reference_records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generation_runs.append(
            {"step": "reference_snapshot", **_run_meta_payload(snapshot_meta)}
        )
        print(
            f"[eval-generate] suite={suite} batch={batch_number}/"
            f"{len(chapter_batches)} step=case_generation",
            flush=True,
        )
        rejected_descriptions: list[str] = []
        for diversity_attempt in range(1, 5):
            drafts, run_meta = await evaluator.generate_cases(
                suite=suite,
                source_excerpt=excerpt,
                chapter_indices=[item.chapter_index for item in batch],
                scenarios=_SCENARIOS[suite],
                count=target,
                reference_snapshot=snapshot,
                avoid_cases=[
                    *(_case_description(case) for case in generated),
                    *rejected_descriptions,
                    f"diversity_attempt={diversity_attempt}",
                ],
            )
            materialized = materialize_generated_cases(
                drafts.cases,
                suite=suite,
                corpus=corpus,
                run_meta=run_meta,
                reference_snapshot=snapshot,
                case_offset=len(generated),
            )
            existing_keys = {_case_semantic_key(case) for case in generated}
            materialized_keys = [_case_semantic_key(case) for case in materialized]
            materialized_key_counts = Counter(materialized_keys)
            duplicate_cases = [
                case
                for case in materialized
                if _case_semantic_key(case) in existing_keys
                or materialized_key_counts[_case_semantic_key(case)] > 1
            ]
            if not duplicate_cases:
                generation_runs.append(
                    {"step": "case_generation", **_run_meta_payload(run_meta)}
                )
                generated.extend(materialized)
                break
            rejected_descriptions.extend(
                f"REJECTED_DUPLICATE:{_case_description(case)}"
                for case in duplicate_cases
            )
        else:
            raise RuntimeError(
                f"generator could not produce a cross-batch-unique {suite} batch"
            )
        print(
            f"[eval-generate] suite={suite} batch={batch_number}/"
            f"{len(chapter_batches)} cases={len(generated)}/{size} step=done",
            flush=True,
        )

    generated = generated[:size]
    if len(generated) != size:
        raise RuntimeError(
            f"generator returned {len(generated)} cases, expected exactly {size}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(case.model_dump_json() for case in generated) + "\n",
        encoding="utf-8",
    )
    suite_counts = Counter(case.suite for case in generated)
    split_counts = Counter(case.split for case in generated)
    generator_models = sorted({case.generation_meta.model for case in generated})
    manifest = DatasetManifest(
        dataset_id=f"{suite}-{variant}",
        version="candidate",
        corpus_id=corpus.corpus_id,
        corpus_hash=corpus.file_hash,
        source_aliases=[corpus.source_alias],
        case_count=len(generated),
        suite_counts=dict(suite_counts),
        split_counts=dict(split_counts),
        generator_model=(
            generator_models[0]
            if len(generator_models) == 1
            else "mixed:" + ",".join(generator_models)
        ),
        prompt_hashes={
            f"{run['step']}-{index}": run["prompt_hash"]
            for index, run in enumerate(generation_runs, start=1)
        },
        generation_runs=generation_runs,
    )
    output.with_suffix(".manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"[eval-generate] suite={suite} completed cases={len(generated)} output={output}",
        flush=True,
    )


def _run_meta_payload(meta) -> dict:
    return {
        "model": meta.model,
        "reasoning_effort": meta.reasoning_effort,
        "prompt_hash": meta.prompt_hash,
        "executor_hash": meta.profile_hash,
        "seed": meta.seed,
        "duration_ms": meta.duration_ms,
        "cost_usd": meta.cost_usd,
        "cost_status": meta.cost_status,
        "cached": meta.cached,
    }


def _case_semantic_key(case: DatasetCase) -> str:
    if case.suite == EvalSuite.rag:
        return "".join(
            character
            for character in str(case.input.get("query") or "").casefold()
            if character.isalnum()
        )
    return json.dumps(
        {
            "suite": case.suite.value,
            "scenario": case.scenario,
            "input": case.input,
            "reference": case.reference,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _case_description(case: DatasetCase) -> str:
    return json.dumps(
        {
            "scenario": case.scenario,
            "input": case.input,
            "reference": case.reference,
        },
        ensure_ascii=False,
        sort_keys=True,
    )[:600]


async def _judge(
    *,
    dataset: Path,
    variant: str,
    output: Path,
    cache_dir: Path,
    cache_only: bool = False,
) -> None:
    cases = _load_cases(dataset)
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    deterministic = run_deterministic_qc(
        cases,
        corpora={corpus.source_alias: corpus},
        source_texts={corpus.source_alias: source_text},
    )
    errors = deterministic["errors"]
    evaluator = HighQualityEvalLLM(
        CodexStructuredExecutor(),
        cache=EvalCache(cache_dir),
        cache_only=cache_only,
    )

    eligible: list[DatasetCase] = []
    deterministic_by_id: dict[str, tuple[list[str], list[str]]] = {}
    for case in cases:
        deterministic_errors = list(errors.get(case.case_id, []))
        deterministic_warnings = list(deterministic["warnings"].get(case.case_id, []))
        deterministic_by_id[case.case_id] = (
            deterministic_errors,
            deterministic_warnings,
        )
        llm_blocking_errors = [
            error
            for error in deterministic_errors
            if error != "safety_critical_requires_human_review"
        ]
        if llm_blocking_errors:
            case.qc = QCDecision(
                status="rejected",
                deterministic_errors=deterministic_errors,
                deterministic_warnings=deterministic_warnings,
            )
            continue
        eligible.append(case)

    decision_models: dict[str, list[JudgeDecision]] = {
        case.case_id: [] for case in eligible
    }
    decision_payloads: dict[str, list[dict]] = {case.case_id: [] for case in eligible}
    for batch in _judge_batches(eligible):
        batch_decisions, meta = await evaluator.judge_cases(
            batch,
            source_excerpt=_source_excerpt_for_cases(batch, corpus, source_text),
            judge_round=1,
        )
        for case in batch:
            decision = batch_decisions[case.case_id]
            decision_models[case.case_id].append(decision)
            decision_payloads[case.case_id].append(
                {
                    "round": 1,
                    **_run_meta_payload(meta),
                    **decision.model_dump(mode="json"),
                }
            )

    second_round = [
        case
        for case in eligible
        if case.risk_level == RiskLevel.safety_critical
        or decision_models[case.case_id][0].decision != "accept"
        or bool(decision_models[case.case_id][0].ambiguity)
    ]
    for batch in _judge_batches(second_round):
        batch_decisions, meta = await evaluator.judge_cases(
            batch,
            source_excerpt=_source_excerpt_for_cases(batch, corpus, source_text),
            judge_round=2,
        )
        for case in batch:
            decision = batch_decisions[case.case_id]
            decision_models[case.case_id].append(decision)
            decision_payloads[case.case_id].append(
                {
                    "round": 2,
                    **_run_meta_payload(meta),
                    **decision.model_dump(mode="json"),
                }
            )

    for case in eligible:
        deterministic_errors, deterministic_warnings = deterministic_by_id[case.case_id]
        case.qc = QCDecision(
            status=_judge_status(case, decision_models[case.case_id]),
            deterministic_errors=deterministic_errors,
            deterministic_warnings=deterministic_warnings,
            judge_decisions=decision_payloads[case.case_id],
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(case.model_dump_json() for case in cases) + "\n",
        encoding="utf-8",
    )


def _source_excerpt_for_case(
    case: DatasetCase,
    corpus: CorpusSnapshot,
    source_text: str,
) -> str:
    chapters = {item.chapter_index: item for item in corpus.chapters}
    indices = {ref.chapter_index for ref in [*case.source_refs, *case.hard_negative_refs]}
    if not indices:
        indices = {
            item.chapter_index
            for item in corpus.chapters
            if item.source_group_id == case.source_group_id
        }
    excerpts = []
    for index in sorted(indices):
        chapter = chapters.get(index)
        if chapter is not None:
            excerpts.append(source_text[chapter.start_offset : chapter.end_offset][:5000])
    return "\n\n".join(excerpts)


def _source_excerpt_for_cases(
    cases: list[DatasetCase],
    corpus: CorpusSnapshot,
    source_text: str,
) -> str:
    chapters = {item.chapter_index: item for item in corpus.chapters}
    indices: set[int] = set()
    for case in cases:
        case_indices = {
            ref.chapter_index for ref in [*case.source_refs, *case.hard_negative_refs]
        }
        if not case_indices:
            case_indices = {
                item.chapter_index
                for item in corpus.chapters
                if item.source_group_id == case.source_group_id
            }
        indices.update(case_indices)
    return "\n\n".join(
        source_text[chapters[index].start_offset : chapters[index].end_offset][:5000]
        for index in sorted(indices)
        if index in chapters
    )


def _judge_batches(
    cases: list[DatasetCase],
    *,
    batch_size: int = 10,
) -> list[list[DatasetCase]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    grouped: dict[str, list[DatasetCase]] = {}
    for case in cases:
        grouped.setdefault(case.source_group_id, []).append(case)
    return [
        items[index : index + batch_size]
        for items in grouped.values()
        for index in range(0, len(items), batch_size)
    ]


def _review_export(
    *,
    dataset: Path,
    variant: str,
    html_output: Path,
    jsonl_output: Path,
    select_all: bool,
    csv_output: Path | None = None,
    double_html_output: Path | None = None,
    double_jsonl_output: Path | None = None,
    double_csv_output: Path | None = None,
    supplement_size: int | None = None,
    review_status: str | None = None,
    case_ids: list[str] | None = None,
) -> None:
    if (double_html_output is None) != (double_jsonl_output is None):
        raise ValueError("double review export requires both HTML and JSONL outputs")
    if double_csv_output is not None and double_html_output is None:
        raise ValueError("double review CSV requires the double review package")
    cases = _load_cases(dataset)
    requested_ids = set(case_ids or [])
    selection_modes = sum(
        (
            select_all,
            supplement_size is not None,
            review_status is not None,
            bool(requested_ids),
        )
    )
    if selection_modes > 1:
        raise ValueError(
            "--all, --supplement-size, --review-status, and --case-id are "
            "mutually exclusive"
        )
    if requested_ids:
        available_ids = {case.case_id for case in cases}
        missing = sorted(requested_ids - available_ids)
        if missing:
            raise ValueError(f"review export has unknown case IDs: {missing}")
        selected = [case for case in cases if case.case_id in requested_ids]
    elif review_status is not None:
        selected = [case for case in cases if case.human_review.status == review_status]
    elif supplement_size is not None:
        selected = select_balanced_review_supplement(cases, target=supplement_size)
    else:
        selected = cases if select_all else select_review_cases(cases)
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    excerpts = {
        case.case_id: _source_excerpt_for_case(case, corpus, source_text)
        for case in selected
    }
    export_review_html(selected, html_output, source_excerpts=excerpts)
    export_review_jsonl(selected, jsonl_output)
    if csv_output is not None:
        export_review_csv(selected, csv_output)
    if double_html_output is not None and double_jsonl_output is not None:
        double_selected = select_double_review_cases(selected)
        export_review_html(
            double_selected,
            double_html_output,
            source_excerpts={
                case.case_id: excerpts[case.case_id] for case in double_selected
            },
        )
        export_review_jsonl(double_selected, double_jsonl_output)
        if double_csv_output is not None:
            export_review_csv(double_selected, double_csv_output)


def _review_import(
    *,
    dataset: Path,
    reviews: Path,
    reviewer_version: str,
    output: Path,
    report: Path,
    adjudication: bool = False,
) -> None:
    cases = apply_review_records(
        _load_cases(dataset),
        load_review_records(reviews),
        reviewer_version=reviewer_version,
        adjudication=adjudication,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(case.model_dump_json() for case in cases) + "\n",
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(judge_human_agreement(cases), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


async def _model_review(
    *,
    dataset: Path,
    template: Path,
    variant: str,
    model: str,
    reviewer_role: str,
    suite: str | None,
    novel_id: str | None,
    output: Path,
    cache_dir: Path,
) -> None:
    _validate_review_model_assignment(reviewer_role, model)
    cases_by_id = {case.case_id: case for case in _load_cases(dataset)}
    requested_ids = [record.case_id for record in load_review_records(template)]
    missing = sorted(
        case_id
        for case_id in set(requested_ids) - set(cases_by_id)
        if suite is None or case_id.startswith(f"{suite}-")
    )
    if missing:
        raise ValueError(f"model review template has unknown case IDs: {missing}")
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    selected = [
        cases_by_id[case_id]
        for case_id in requested_ids
        if case_id in cases_by_id
        and (suite is None or cases_by_id[case_id].suite.value == suite)
    ]
    if not selected:
        raise ValueError("model review template has no cases for requested suite")
    async with _open_model_review_evaluator(
        model=model,
        novel_id=novel_id,
        cache_dir=cache_dir,
    ) as evaluator:
        await _execute_model_review(
            selected=selected,
            evaluator=evaluator,
            corpus=corpus,
            source_text=source_text,
            reviewer_role=reviewer_role,
            model=model,
            output=output,
        )


def _validate_review_model_assignment(reviewer_role: str, model: str) -> None:
    normalized = reviewer_role.strip().lower().replace("_", "-")
    if normalized == "reviewer-a" or normalized.endswith("-reviewer-a"):
        expected = EVAL_REVIEWER_A_MODEL
    elif normalized == "reviewer-b" or normalized.endswith("-reviewer-b"):
        expected = EVAL_REVIEWER_B_MODEL
    elif normalized == "adjudicator" or normalized.endswith("-adjudicator"):
        expected = EVAL_ADJUDICATOR_MODEL
    else:
        raise ValueError("reviewer role must be reviewer-a, reviewer-b, or adjudicator")
    if model != expected:
        raise ValueError(
            f"reviewer role {reviewer_role} requires model {expected}, got {model}"
        )


@asynccontextmanager
async def _open_model_review_evaluator(
    *,
    model: str,
    novel_id: str | None,
    cache_dir: Path,
):
    if model != "deepseek-v4-flash":
        yield HighQualityEvalLLM(
            CodexStructuredExecutor(
                model=model,
                allowed_models=ALLOWED_CODEX_REVIEW_MODELS,
            ),
            cache=EvalCache(cache_dir),
            allow_primary_cache_fallback=False,
        )
        return
    if not novel_id:
        raise ValueError("deepseek-v4-flash reviewer requires --novel-id")

    from core.database import DatabaseManager
    from evals.project_executor import ProjectStructuredExecutor
    from infrastructure.llm.profiles import resolve_llm_profile
    from modules.project.facade import get_project_context

    manager = DatabaseManager()
    manager.init()
    try:
        async with manager.session_factory() as db:
            context = await get_project_context(db, novel_id)
            if context is None:
                raise ValueError(f"project not found: {novel_id}")
            profile = resolve_llm_profile(context.settings)
            if profile.model != model:
                raise ValueError(
                    "project reviewer model mismatch: "
                    f"expected={model} actual={profile.model}"
                )
            yield HighQualityEvalLLM(
                ProjectStructuredExecutor(db, novel_id, profile),
                cache=EvalCache(cache_dir),
                allow_primary_cache_fallback=False,
            )
    finally:
        await manager.close()


async def _execute_model_review(
    *,
    selected: list[DatasetCase],
    evaluator: HighQualityEvalLLM,
    corpus: CorpusSnapshot,
    source_text: str,
    reviewer_role: str,
    model: str,
    output: Path,
) -> None:
    records: list[ReviewRecord] = []
    runs: list[dict] = []
    batches = [selected[index : index + 3] for index in range(0, len(selected), 3)]
    for index, batch in enumerate(batches, start=1):
        payloads = [
            {
                "case_id": case.case_id,
                "suite": case.suite.value,
                "scenario": case.scenario,
                "risk_level": case.risk_level.value,
                "visibility": case.visibility.model_dump(mode="json"),
                "input": case.input,
                "reference": case.reference,
                "source_refs": [ref.model_dump(mode="json") for ref in case.source_refs],
                "hard_negative_refs": [
                    ref.model_dump(mode="json") for ref in case.hard_negative_refs
                ],
                "independent_reviews": [
                    review.model_dump(mode="json")
                    for review in case.human_review.independent_reviews
                ],
                "novel_context": _source_excerpt_for_case(case, corpus, source_text),
            }
            for case in batch
        ]
        decisions, meta = await evaluator.review_cases(
            payloads,
            reviewer_role=reviewer_role,
        )
        records.extend(
            ReviewRecord(
                case_id=case.case_id,
                status=decisions[case.case_id].status,
                reason=decisions[case.case_id].reason,
                score=decisions[case.case_id].score,
                corrected_reference=(
                    json.loads(decisions[case.case_id].corrected_reference_json)
                    if decisions[case.case_id].corrected_reference_json is not None
                    else None
                ),
            )
            for case in batch
        )
        runs.append({"batch": index, **_run_meta_payload(meta)})
        print(
            f"[eval-model-review] role={reviewer_role} model={model} "
            f"batch={index}/{len(batches)} cases={len(records)}/{len(selected)}",
            flush=True,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(record.model_dump_json() for record in records) + "\n",
        encoding="utf-8",
    )
    output.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "reviewer_kind": "llm_surrogate",
                "reviewer_role": reviewer_role,
                "model": model,
                "case_count": len(records),
                "runs": runs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


async def _judge_calibrate(
    *,
    dataset: Path,
    template: Path,
    variant: str,
    output: Path,
    cache_dir: Path,
) -> None:
    cases = _load_cases(dataset)
    by_id = {case.case_id: case for case in cases}
    requested_ids = [record.case_id for record in load_review_records(template)]
    missing = sorted(set(requested_ids) - set(by_id))
    if missing:
        raise ValueError(f"judge calibration template has unknown IDs: {missing}")
    selected = [by_id[case_id] for case_id in requested_ids]
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    evaluator = HighQualityEvalLLM(
        CodexStructuredExecutor(model="gpt-5.3-codex-spark"),
        cache=EvalCache(cache_dir),
    )
    processed = 0
    for batch in _judge_batches(selected):
        decisions, meta = await evaluator.judge_cases(
            batch,
            source_excerpt=_source_excerpt_for_cases(batch, corpus, source_text),
            judge_round=3,
        )
        for case in batch:
            decision = decisions[case.case_id]
            case.qc.judge_decisions.append(
                {
                    "round": 3,
                    **_run_meta_payload(meta),
                    "rubric_version": "calibrated-quality-v2",
                    **decision.model_dump(mode="json"),
                }
            )
        processed += len(batch)
        print(
            f"[eval-judge-calibrate] cases={processed}/{len(selected)}",
            flush=True,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(case.model_dump_json() for case in cases) + "\n",
        encoding="utf-8",
    )


def _report(
    *,
    dataset: Path,
    variant: str,
    dataset_id: str,
    dataset_version: str,
    result_paths: list[Path],
    json_output: Path,
    markdown_output: Path,
    result_version_reuse: list[str] | None = None,
    raw_reviewed_dataset: Path | None = None,
) -> None:
    cases = _load_cases(dataset)
    corpus = load_corpus_snapshot(variant)
    source_text = source_path_for_variant(variant).read_text(encoding="utf-8-sig")
    qc = run_deterministic_qc(
        cases,
        corpora={corpus.source_alias: corpus},
        source_texts={corpus.source_alias: source_text},
    )
    eval_results: list[EvalResult] = []
    result_sources: dict[str, dict[str, str]] = {}
    for path in result_paths:
        raw = path.read_bytes()
        result = EvalResult.model_validate_json(raw)
        eval_results.append(result)
        if result.suite.value in result_sources:
            raise ValueError(f"duplicate result path for suite {result.suite.value}")
        result_sources[result.suite.value] = {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    reuse_proofs: dict[str, dict] = {}
    for value in result_version_reuse or []:
        try:
            suite_text, source_version, source_path_text = value.split(":", 2)
            suite_value = EvalSuite(suite_text)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "--result-version-reuse must be SUITE:VERSION:DATASET"
            ) from exc
        if suite_value.value in reuse_proofs:
            raise ValueError(f"duplicate reuse proof for suite {suite_value.value}")
        source_path = Path(source_path_text)
        reuse_proofs[suite_value.value] = build_result_version_reuse_proof(
            cases,
            _load_cases(source_path),
            suite=suite_value,
            source_dataset_version=source_version,
            target_dataset_version=dataset_version,
            source_dataset_path=source_path,
        )
    raw_cases = _load_cases(raw_reviewed_dataset) if raw_reviewed_dataset else None
    raw_source = None
    if raw_reviewed_dataset is not None:
        raw_source = {
            "source_dataset_path": str(raw_reviewed_dataset),
            "source_dataset_hash": hashlib.sha256(
                raw_reviewed_dataset.read_bytes()
            ).hexdigest(),
        }
    report = build_dataset_report(
        cases,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        deterministic_qc=qc,
        eval_results=eval_results,
        result_sources=result_sources,
        version_reuse_proofs=reuse_proofs,
        raw_candidate_cases=raw_cases,
        raw_candidate_source=raw_source,
    )
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(
        render_markdown_report(report),
        encoding="utf-8",
    )


async def _pilot(
    *,
    variant: str,
    stage: str,
    output_dir: Path,
    cache_dir: Path,
    cache_only: bool = False,
) -> None:
    sizes = PILOT_SUITE_SIZES
    candidates_dir = output_dir / "candidates"
    judged_dir = output_dir / "judged"
    if stage in {"generate", "all"}:
        for suite, size in sizes.items():
            print(
                f"[eval-pilot] stage=generate suite={suite} target={size}",
                flush=True,
            )
            await _generate(
                suite=suite,
                variant=variant,
                size=size,
                output=candidates_dir / f"{suite}.jsonl",
                cache_dir=cache_dir,
                cache_only=cache_only,
            )
    if stage == "generate":
        return

    for suite in sizes:
        candidate = candidates_dir / f"{suite}.jsonl"
        if not candidate.is_file():
            raise FileNotFoundError(
                f"missing {candidate}; run pilot --stage generate first"
            )
        judged = judged_dir / f"{suite}.jsonl"
        if judged.is_file() and _judged_matches_candidate(candidate, judged):
            print(
                f"[eval-pilot] stage=judge suite={suite} step=resume-skip",
                flush=True,
            )
            continue
        await _judge(
            dataset=candidate,
            variant=variant,
            output=judged,
            cache_dir=cache_dir,
            cache_only=cache_only,
        )

    combined = [
        case for suite in sizes for case in _load_cases(judged_dir / f"{suite}.jsonl")
    ]
    combined_path = output_dir / f"{PILOT_RAW_STEM}.jsonl"
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined_path.write_text(
        "\n".join(case.model_dump_json() for case in combined) + "\n",
        encoding="utf-8",
    )
    corpus = load_corpus_snapshot(variant)
    candidate_generation_runs = _deduplicate_run_records(
        [
            run
            for suite in sizes
            for run in DatasetManifest.model_validate_json(
                (candidates_dir / f"{suite}.manifest.json").read_text(encoding="utf-8")
            ).generation_runs
        ]
    )
    judge_runs = _judge_run_provenance(combined)
    manifest = DatasetManifest(
        dataset_id="semantic-pilot-raw",
        version="candidate",
        corpus_id=corpus.corpus_id,
        corpus_hash=corpus.file_hash,
        source_aliases=[corpus.source_alias],
        case_count=len(combined),
        suite_counts=dict(Counter(case.suite for case in combined)),
        split_counts=dict(Counter(case.split for case in combined)),
        generator_model=_model_set_label(case.generation_meta.model for case in combined),
        judge_model=_model_set_label(
            str(decision.get("model"))
            for case in combined
            for decision in case.qc.judge_decisions
            if decision.get("model")
        ),
        prompt_hashes={
            f"{case.suite.value}:{case.source_group_id}": (
                case.generation_meta.prompt_hash
            )
            for case in combined
        },
        generation_runs=candidate_generation_runs,
        judge_runs=judge_runs,
        range_locator_runs=_range_locator_run_provenance(combined),
    )
    (output_dir / f"{PILOT_RAW_STEM}.manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    _qc(combined_path, variant, output_dir / f"{PILOT_RAW_STEM}.qc.json")
    _review_export(
        dataset=combined_path,
        variant=variant,
        html_output=output_dir / f"{PILOT_RAW_STEM}.review.html",
        jsonl_output=output_dir / f"{PILOT_RAW_STEM}.review.jsonl",
        select_all=False,
    )
    _report(
        dataset=combined_path,
        variant=variant,
        dataset_id="semantic-pilot-raw",
        dataset_version="candidate",
        result_paths=[],
        json_output=output_dir / f"{PILOT_RAW_STEM}.report.json",
        markdown_output=output_dir / f"{PILOT_RAW_STEM}.report.md",
    )


def _judge_status(case: DatasetCase, decisions: list[object]) -> str:
    labels = [str(getattr(decision, "decision")) for decision in decisions]
    if case.risk_level == RiskLevel.safety_critical:
        return "review"
    if any(getattr(decision, "ambiguity", None) for decision in decisions):
        return "review"
    if len(set(labels)) > 1:
        return "review"
    return {"accept": "accepted", "reject": "rejected"}.get(labels[0], "review")


def _load_cases(path: Path) -> list[DatasetCase]:
    return [
        DatasetCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _judged_matches_candidate(candidate: Path, judged: Path) -> bool:
    candidate_cases = _load_cases(candidate)
    judged_cases = _load_cases(judged)
    if len(candidate_cases) != len(judged_cases):
        return False
    return all(
        (
            left.case_id,
            left.suite,
            left.scenario,
            left.input,
            left.reference,
            left.generation_meta.model,
            left.generation_meta.prompt_hash,
            left.generation_meta.source_hash,
        )
        == (
            right.case_id,
            right.suite,
            right.scenario,
            right.input,
            right.reference,
            right.generation_meta.model,
            right.generation_meta.prompt_hash,
            right.generation_meta.source_hash,
        )
        for left, right in zip(candidate_cases, judged_cases, strict=True)
    )


if __name__ == "__main__":
    main()

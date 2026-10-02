"""B7 三档长篇工程规模门：真实索引/编译、检索、审校分片和任务链。

检索走 PostgreSQL 关键词路径及来源原文回读；模型扩展/重排使用确定性
替身。审校测实际分片/请求构造，任务编排复用六步 Evolution 影子链。
章节位置曲线固定正文长度；章节长度曲线使用真实续写请求。没有模型
语义、文学质量或付费计量结论。三档阈值见 scale_gate_baselines.json。

仅接受显式专用 PostgreSQL test/e2e/audit 库；外层事务撤回全部夹具，
包括影子链内部提交。--json-path 直接导出 B6 release-evidence-v1。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

BASELINES_PATH = Path(__file__).resolve().parent / "scale_gate_baselines.json"

# 每档固定采样的章位置（比例），保证低/中/高档结果可比。
_SAMPLE_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
# Token 数有随机 UUID 身份的小量波动；耗时使用独立绝对上限。
_DEFAULT_TOLERANCE = 1.15


class ScaleGateError(Exception):
    """规模门验证失败。"""


@dataclass
class ChapterProbe:
    chapter_index: int
    compile_seconds: float
    compiled_tokens: int
    section_count: int
    evidence_tokens: int = 0
    continuation_input_tokens: int = 0


@dataclass
class ScaleGateReport:
    tier: str
    chapters: int
    sampled: list[ChapterProbe] = field(default_factory=list)
    growth_ratio: float | None = None
    notes: list[str] = field(default_factory=list)
    indexed_chunks: int = 0
    retrieval_seconds: float = 0.0
    retrieval_hits: int = 0
    review_seconds: float = 0.0
    review_fragments: int = 0
    review_max_tokens: int = 0
    reviewed_chapters: int = 0
    orchestration: dict[str, Any] = field(default_factory=dict)
    length_curve: list[dict[str, int]] = field(default_factory=list)

    @property
    def max_compile_seconds(self) -> float:
        return max((probe.compile_seconds for probe in self.sampled), default=0.0)

    @property
    def max_compiled_tokens(self) -> int:
        return max((probe.compiled_tokens for probe in self.sampled), default=0)


def sample_chapter_indices(chapter_count: int) -> list[int]:
    indices = sorted(
        {
            max(1, min(chapter_count, int(round(fraction * chapter_count))))
            for fraction in _SAMPLE_FRACTIONS
        }
    )
    return indices


def import_all_models() -> None:
    """导入全部 ORM 模型注册到 Base.metadata（清单与 conftest 同步）。"""
    import infrastructure.tasks.models  # noqa: F401
    import modules.account.models  # noqa: F401
    import modules.account.settings_models  # noqa: F401
    import modules.assistant.forecast.models  # noqa: F401
    import modules.assistant.models  # noqa: F401
    import modules.collaboration.models  # noqa: F401
    import modules.evidence.models  # noqa: F401
    import modules.imports.models  # noqa: F401
    import modules.local_agent.models  # noqa: F401
    import modules.project.models  # noqa: F401
    import modules.project.settings_models  # noqa: F401
    import modules.story.continuity.models  # noqa: F401
    import modules.story.models  # noqa: F401
    import modules.story.outline_state.models  # noqa: F401
    import modules.world.map_atlas_models  # noqa: F401
    import modules.world.models  # noqa: F401
    import modules.writing.models  # noqa: F401


async def _create_schema(engine) -> None:
    import_all_models()
    from core.base import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _seed_fixtures(db, *, novel_id, chapters: list[dict[str, str]]) -> None:
    from modules.account.models import Account
    from modules.evidence.indexing.chunk_annotation import build_chunk_create
    from modules.evidence.indexing.chunking import ChunkingService
    from modules.evidence.indexing.repositories import RagChunkRepository
    from modules.project.models import Project
    from modules.writing.models import WritingDraft

    owner_id = uuid4()
    db.add(Account(id=owner_id, support_code=f"scale-{owner_id.hex[:12]}"))
    await db.flush()

    db.add(
        Project(
            id=novel_id,
            owner_id=owner_id,
            title=f"规模门-{uuid4().hex[:6]}",
            language="zh",
            default_reveal_policy="author_safe",
            settings={},
        )
    )
    chunking = ChunkingService()
    repo = RagChunkRepository()
    for index, chapter in enumerate(chapters, start=1):
        draft = WritingDraft(
            novel_id=novel_id,
            chapter_index=index,
            title=chapter["title"],
            content=chapter["content"],
            content_hash=hashlib.sha256(chapter["content"].encode()).hexdigest(),
            version_number=1,
            status="published",
        )
        db.add(draft)
        await db.flush()
        for fragment in chunking.split_chinese_novel(draft.content):
            data = build_chunk_create(
                fragment,
                chapter_index=index,
                source_draft_id=str(draft.id),
                source_content_hash=draft.content_hash,
                chunking=chunking,
                project_terms=[],
                entity_importance_map={},
                scenes_for_chapter=[],
            )
            data.embedding_status = "skipped"
            await repo.create(db, novel_id, data)
    await db.flush()


def _offline_compiler():
    """真实 SQL 检索/回读/编译；仅模型扩展和模型重排使用确定性替身。"""
    from modules.evidence.compilation.services.context_compiler import ContextCompiler
    from modules.evidence.compilation.services.loaders.rag_chunks_loader import (
        RagChunksLoader,
        _FusedRerankExecution,
    )
    from modules.evidence.compilation.services.retrieval_query_planner import (
        QueryPlanExpansionOutcome,
    )
    from modules.evidence.compilation.services.retrieval_trace_service import (
        RetrievalTraceService,
    )

    async def retrieve(*args, **kwargs):
        from modules.evidence.indexing.facade import retrieve as real_retrieve

        kwargs.update(rerank=False, expand_query=False)
        result = await real_retrieve(*args, **kwargs)
        return result

    async def expand(db, options, plan):
        return QueryPlanExpansionOutcome(plan=plan)

    async def rerank(db, options, plan, chunks, scores, **kwargs):
        return _FusedRerankExecution(chunks=chunks)

    loaders = ContextCompiler._default_loaders()
    loaders = [
        RagChunksLoader(
            retrieve_fn=retrieve,
            plan_expander=expand,
            fused_reranker=rerank,
            trace_recorder=RetrievalTraceService().record,
        )
        if loader.name == "rag_chunks"
        else loader
        for loader in loaders
    ]
    return ContextCompiler(loaders=loaders)


def _input_tokens(compiled, chapter_index, base_content):
    from modules.evidence.compilation.markdown_renderer import render_compiled_context
    from modules.evidence.compilation.services.compiled_context import (
        estimate_token_count,
    )
    from modules.writing.pov_generation import GenerationProfile, GenerationProfileInfo
    from modules.writing.services import WritingGenerationService

    confirmed = SimpleNamespace(
        rendered_markdown=render_compiled_context(compiled),
        compile_options={},
    )
    _, request = WritingGenerationService._build_generation_request(
        confirmed_context=confirmed,
        profile=GenerationProfileInfo(profile=GenerationProfile.DEFAULT),
        chapter_index=chapter_index,
        instruction="林舟与星盘，接续当前正文",
        model="offline",
        generation_mode="continue",
        base_content=base_content,
    )
    return sum(estimate_token_count(m.content) for m in request.messages)


async def probe_compilation(
    db, *, novel_id: str, indices: list[int], chapters: list[dict[str, str]] | None = None
) -> list[ChapterProbe]:
    from modules.evidence.compilation.contracts import CompileOptions

    compiler = _offline_compiler()
    probes: list[ChapterProbe] = []
    for chapter_index in indices:
        options = CompileOptions(
            novel_id=novel_id,
            task="林舟与星盘，接续当前正文",
            scope="chapter",
            chapter_index=chapter_index,
            consumer_action="writing.generate",
            reveal_mode="author_safe",
        )
        started = time.perf_counter()
        compiled = await compiler.compile_with_tiers(db, options, budget_tokens=60000)
        elapsed = time.perf_counter() - started
        evidence_tokens = sum(
            s.token_count
            for s in compiled.sections
            if s.key == "retrieval_evidence_packs"
        )
        if evidence_tokens <= 0:
            raise ScaleGateError(f"第 {chapter_index} 章缺少真实正文检索证据")
        base_content = chapters[chapter_index - 1]["content"][:2000] if chapters else ""
        probes.append(
            ChapterProbe(
                chapter_index=chapter_index,
                compile_seconds=round(elapsed, 4),
                compiled_tokens=int(compiled.total_tokens),
                section_count=len(compiled.sections),
                evidence_tokens=evidence_tokens,
                continuation_input_tokens=_input_tokens(
                    compiled, chapter_index, base_content
                ),
            )
        )
    return probes


async def probe_suite(
    db, *, novel_id: str, tier: str, chapters: list[dict[str, str]]
) -> ScaleGateReport:
    from sqlalchemy import func, select

    from modules.evidence.compilation.contracts import CompileOptions
    from modules.evidence.indexing.models import RagChunk
    from modules.evidence.indexing.retrieval import RetrievalOrchestrator
    from modules.writing.facade import list_manuscript_sources
    from modules.writing.semantic_review import WritingSemanticWorkflowService
    from tools.evolution_scale_harness import _assert_exit_criteria, run_harness

    report = ScaleGateReport(tier=tier, chapters=len(chapters))
    report.indexed_chunks = await db.scalar(
        select(func.count()).select_from(RagChunk).where(RagChunk.novel_id == novel_id)
    )
    report.sampled = await probe_compilation(
        db,
        novel_id=novel_id,
        indices=sample_chapter_indices(len(chapters)),
        chapters=chapters,
    )
    evaluate_growth(report)
    start = time.perf_counter()
    result = await RetrievalOrchestrator().retrieve(
        db, UUID(novel_id), "林舟 星盘", top_k=8, rerank=False, expand_query=False
    )
    report.retrieval_seconds = round(time.perf_counter() - start, 4)
    report.retrieval_hits = len(result.chunks)
    if not result.chunks or result.degraded:
        raise ScaleGateError("真实索引检索为空或降级")

    start = time.perf_counter()
    sources = await list_manuscript_sources(
        db, novel_id, list(range(1, len(chapters) + 1)), content_mode="canonical"
    )
    targets = [
        {
            "draft_id": str(s.id),
            "chapter_index": s.chapter_index,
            "title": s.title,
            "content": s.content,
            "content_hash": s.content_hash,
            "role": "target",
        }
        for s in sources
    ]
    groups = WritingSemanticWorkflowService._chunks(targets)
    if len(groups) > 24 or sum(len(g) for g in groups) != len(chapters):
        raise ScaleGateError("审校分片遗漏章节或突破片数上限")
    from modules.evidence.compilation.services.compiled_context import (
        estimate_token_count,
    )

    report.review_fragments = len(groups)
    report.reviewed_chapters = sum(len(g) for g in groups)
    report.review_max_tokens = max(
        sum(
            estimate_token_count(m.content)
            for m in WritingSemanticWorkflowService._review_request(
                model="offline", scope="book", chunk=g, adjacent=[]
            ).messages
        )
        for g in groups
    )
    report.review_seconds = round(time.perf_counter() - start, 4)

    index = len(chapters) // 2 + 1
    compiled = await _offline_compiler().compile_with_tiers(
        db,
        CompileOptions(
            novel_id=novel_id,
            task="林舟与星盘，接续当前正文",
            scope="chapter",
            chapter_index=index,
            consumer_action="writing.generate",
        ),
        budget_tokens=60000,
    )
    text = chapters[index - 1]["content"]
    report.length_curve = [
        {
            "chars": len(text[: int(len(text) * f)]),
            "input_tokens": _input_tokens(compiled, index, text[: int(len(text) * f)]),
        }
        for f in (0.25, 0.5, 1.0)
    ]
    connection = await db.connection()
    orchestration = await run_harness(
        SimpleNamespace(
            database_url="",
            create_schema=False,
            sampler="deterministic",
            limit=6,
            keep=True,
        ),
        connection=connection,
        chapters=chapters,
    )
    _assert_exit_criteria(orchestration)
    report.orchestration = asdict(orchestration)
    report.notes = [
        (
            "四链路均消费本档完整合成语料。检索为真实 PostgreSQL 关键词路径；"
            "未运行向量/模型扩展/重排。"
        ),
        (
            "审校验证真实分片及请求构造；任务编排在完整档位 Scene 表上推进六步影子链，"
            "校验屏障、来源失效、回执及幂等。"
        ),
        "章节位置曲线固定锁定正文为2000字符；章节长度曲线走真实续写请求构造，不代表模型质量或实际收费。",
    ]
    return report


def evaluate_growth(report: ScaleGateReport) -> None:
    """固定锁定正文长度时，真实续写请求的首章→末章输入 token 比率。"""
    if len(report.sampled) < 2:
        return
    first = report.sampled[0].continuation_input_tokens
    last = report.sampled[-1].continuation_input_tokens
    if first > 0:
        report.growth_ratio = round(last / first, 4)


def check_thresholds(report: ScaleGateReport, *, baselines: dict[str, Any]) -> None:
    """阈值回归：token 是确定性量（严格倍数容差）；耗时受机器影响（绝对上限）。"""
    tier_baseline = (baselines.get("tiers") or {}).get(report.tier)
    if not tier_baseline:
        raise ScaleGateError(f"档位 {report.tier} 缺基线：先运行首轮定标并入库")
    tolerance = float(baselines.get("tolerance", _DEFAULT_TOLERANCE))
    problems: list[str] = []

    token_baseline = float(tier_baseline["max_compiled_tokens"])
    if report.max_compiled_tokens > token_baseline * tolerance:
        problems.append(
            f"{report.tier}.max_compiled_tokens={report.max_compiled_tokens} "
            f"超过基线 {token_baseline} 的 {tolerance} 倍容差"
        )
    seconds_cap = float(tier_baseline["compile_seconds_cap"])
    if report.max_compile_seconds > seconds_cap:
        problems.append(
            f"{report.tier}.max_compile_seconds={report.max_compile_seconds} "
            f"超过绝对上限 {seconds_cap}s（防规模退化爆炸）"
        )
    if (
        not report.sampled
        or report.indexed_chunks <= 0
        or any(p.evidence_tokens <= 0 for p in report.sampled)
    ):
        problems.append("编译/索引证据缺失")
    if report.growth_ratio is None or report.growth_ratio > float(
        tier_baseline["position_growth_cap"]
    ):
        problems.append("固定正文长度时章节位置增长超阈值")
    for metric, cap in (
        ("retrieval_seconds", "retrieval_seconds_cap"),
        ("review_seconds", "review_seconds_cap"),
    ):
        if getattr(report, metric) > float(tier_baseline[cap]):
            problems.append(f"{metric} 超绝对上限")
    if (
        report.retrieval_hits <= 0
        or report.reviewed_chapters != report.chapters
        or report.review_fragments <= 0
    ):
        problems.append("检索或审校未覆盖本档正文")
    if report.review_max_tokens > tier_baseline["review_max_tokens"] * tolerance:
        problems.append("审校分片输入超基线")
    if (
        not report.orchestration
        or report.orchestration.get("wall_seconds", float("inf"))
        > tier_baseline["orchestration_seconds_cap"]
    ):
        problems.append("任务编排缺失或超时")
    from tools.evolution_scale_harness import HarnessReport, _assert_exit_criteria

    if report.orchestration:
        _assert_exit_criteria(HarnessReport(**report.orchestration))
    if len(report.length_curve) < 3 or any(
        b["input_tokens"] <= a["input_tokens"]
        for a, b in zip(report.length_curve, report.length_curve[1:])
    ):
        problems.append("章节长度增长未进入真实续写输入")
    if problems:
        raise ScaleGateError("; ".join(problems))


async def run_gate(args: argparse.Namespace) -> ScaleGateReport:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.bootstrap import register_container_services
    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import AccountPrincipal
    from modules.project.models import Project
    from tests.e2e.config import require_e2e_database_url
    from tools.scale_fixtures import corpus_summary, generate_corpus

    database_url = require_e2e_database_url(args.database_url)
    register_container_services(ignore_existing=True)
    engine = create_async_engine(database_url)
    try:
        if args.create_schema:
            await _create_schema(engine)
        novel_id = uuid4()
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with async_sessionmaker(
                    connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )() as db:
                    chapters = generate_corpus(args.tier)
                    await _seed_fixtures(db, novel_id=novel_id, chapters=chapters)
                    project = await db.get(Project, novel_id)
                    token = bind_principal(
                        AccountPrincipal(
                            account_id=project.owner_id,
                            status="active",
                            identity_type="email",
                            support_code="scale-synthetic",
                        )
                    )
                    try:
                        report = await probe_suite(
                            db, novel_id=str(novel_id), tier=args.tier, chapters=chapters
                        )
                    finally:
                        reset_principal(token)
                    summary = corpus_summary(args.tier)
                    report.notes.append(
                        f"fixture sha256={summary['sha256']} chars={summary['chars']}"
                    )
            finally:
                await transaction.rollback()
        if args.baseline_check:
            check_thresholds(report, baselines=json.loads(BASELINES_PATH.read_text()))
        return report
    finally:
        await engine.dispose()


def release_evidence(report: ScaleGateReport) -> dict:
    from tools.scale_fixtures import BASE_CORPUS, corpus_summary

    repo_root = Path(__file__).resolve().parents[2]
    files = [
        BASE_CORPUS,
        Path(__file__),
        Path(__file__).with_name("scale_fixtures.py"),
        Path(__file__).with_name("evolution_scale_harness.py"),
    ]
    return {
        "schema_version": "release-evidence-v1",
        "capability": "storyforge.long_novel_scale",
        "generator_version": "scale-gate-harness-v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True
        ).strip(),
        "dataset": {
            "name": f"synthetic-novel-{report.tier}",
            **corpus_summary(report.tier),
            "files": [
                {
                    "path": p.relative_to(repo_root).as_posix(),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in files
            ],
        },
        "metrics": [
            {"name": name, "value": value}
            for name, value in {
                "max_compiled_tokens": report.max_compiled_tokens,
                "position_growth_ratio": report.growth_ratio,
                "indexed_chunks": report.indexed_chunks,
                "retrieval_hits": report.retrieval_hits,
                "review_fragments": report.review_fragments,
                "review_max_tokens": report.review_max_tokens,
                "task_steps": report.orchestration["scenes_run"],
            }.items()
        ],
        "token_cost": {"paid_calls": 0},
        "blind_review": None,
        "claims_boundary": {
            "proves": [
                "三档中本档真实索引、正文编译、审校分片和六步影子任务链的工程约束及阈值",
                "章节长度与章节位置对真实续写请求输入的不同影响",
            ],
            "does_not_prove": [
                "未验证向量召回、模型扩展/重排、审稿或文学质量及付费成本",
                "合成语料重复基础素材，不能代表真实长篇内容多样性",
                (
                    "生成器文件 hash 锁定本次工作树，commit 为基线身份；"
                    "未合并即不是 main 发布证据"
                ),
            ],
        },
        "scale_report": asdict(report),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("low", "mid", "high"), default="low")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--create-schema", action="store_true")
    parser.add_argument(
        "--baseline-check",
        action="store_true",
        help="与 scale_gate_baselines.json 阈值比对（首轮定标时省略）",
    )
    parser.add_argument("--json-path", default="")
    args = parser.parse_args(argv)

    report = asyncio.run(run_gate(args))
    payload = release_evidence(report)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_path:
        Path(args.json_path).write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

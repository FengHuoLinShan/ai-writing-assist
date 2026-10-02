"""长篇规模分档门 harness（B7）：编译链路确定性探针。

对指定档位的夹具语料建真实 Writing 草稿，采样章逐章走真实
ContextCompiler（chapter scope / writing.generate），测量：

- 每采样章的编译耗时与 compiled token；
- 输入成本随章节位置的增长曲线（报告 §12.5【推断】的测量面：
  prior_prose/sections token 是否随章节位置单调增长）；
- 与 tools/scale_gate_baselines.json 的阈值比对（超阈值即退出码 1）。

检索/审校分片/任务编排链路由 tools/evolution_scale_harness.py 的
既有覆盖承接（低档挂载见 tests/e2e/test_scale_gate_low.py）。

用法（专用库）：
    python -m tools.scale_gate_harness --tier low \
        --database-url postgresql+asyncpg://... --create-schema \
        --json-path out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

BASELINES_PATH = Path(__file__).resolve().parent / "scale_gate_baselines.json"

# 每档固定采样的章位置（比例），保证低/中/高档结果可比。
_SAMPLE_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
# 阈值系数：相对基线的允许上浮（探针测量含机器噪声，留 3 倍余量；
# 首轮基线固化后按实测收紧）。
_DEFAULT_TOLERANCE = 3.0


class ScaleGateError(Exception):
    """规模门验证失败。"""


@dataclass
class ChapterProbe:
    chapter_index: int
    compile_seconds: float
    compiled_tokens: int
    section_count: int


@dataclass
class ScaleGateReport:
    tier: str
    chapters: int
    sampled: list[ChapterProbe] = field(default_factory=list)
    growth_ratio: float | None = None
    notes: list[str] = field(default_factory=list)

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
    from modules.project.models import Project
    from modules.writing.models import WritingDraft

    db.add(
        Project(
            id=novel_id,
            title=f"规模门-{uuid4().hex[:6]}",
            language="zh",
            default_reveal_policy="author_safe",
            settings={},
        )
    )
    for index, chapter in enumerate(chapters, start=1):
        db.add(
            WritingDraft(
                novel_id=novel_id,
                chapter_index=index,
                title=chapter["title"],
                content=chapter["content"],
                content_hash="",
                version_number=1,
                status="published",
            )
        )
    await db.flush()


async def probe_compilation(
    db, *, novel_id: str, indices: list[int]
) -> list[ChapterProbe]:
    from modules.evidence.compilation.contracts import CompileOptions
    from modules.evidence.compilation.services.context_compiler import ContextCompiler

    compiler = ContextCompiler()
    probes: list[ChapterProbe] = []
    for chapter_index in indices:
        options = CompileOptions(
            novel_id=novel_id,
            task="规模门探针：续写本章",
            scope="chapter",
            chapter_index=chapter_index,
            consumer_action="writing.generate",
            reveal_mode="author_safe",
        )
        started = time.perf_counter()
        compiled = await compiler.compile_with_tiers(db, options, budget_tokens=60000)
        elapsed = time.perf_counter() - started
        probes.append(
            ChapterProbe(
                chapter_index=chapter_index,
                compile_seconds=round(elapsed, 4),
                compiled_tokens=int(compiled.total_tokens),
                section_count=len(compiled.sections),
            )
        )
    return probes


def evaluate_growth(report: ScaleGateReport) -> None:
    """单章编译输入成本随章节位置的增长：首章 → 末章 token 比率。"""
    if len(report.sampled) < 2:
        return
    first = report.sampled[0].compiled_tokens
    last = report.sampled[-1].compiled_tokens
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
    if problems:
        raise ScaleGateError("; ".join(problems))


async def run_gate(args: argparse.Namespace) -> ScaleGateReport:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tools.scale_fixtures import corpus_summary, generate_corpus

    engine = create_async_engine(args.database_url)
    try:
        if args.create_schema:
            await _create_schema(engine)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        novel_id = uuid4()
        async with session_factory() as db:
            chapters = generate_corpus(args.tier)
            await _seed_fixtures(db, novel_id=novel_id, chapters=chapters)
            await db.commit()
            indices = sample_chapter_indices(len(chapters))
            report = ScaleGateReport(tier=args.tier, chapters=len(chapters))
            report.sampled = await probe_compilation(
                db, novel_id=str(novel_id), indices=indices
            )
            evaluate_growth(report)
            summary = corpus_summary(args.tier)
            report.notes.append(
                f"fixture sha256={summary['sha256']} chars={summary['chars']}"
            )
            await db.rollback()
        if args.baseline_check:
            check_thresholds(report, baselines=json.loads(BASELINES_PATH.read_text()))
        return report
    finally:
        await engine.dispose()


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
    payload = {
        "schema_version": "scale-gate-v1",
        "generator_version": "scale-gate-harness-v1",
        **asdict(report),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_path:
        Path(args.json_path).write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

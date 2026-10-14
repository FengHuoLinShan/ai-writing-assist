"""PG collector for the G7a import-scan baseline (zero model calls).

Measures the real deep-import Phase 2a context preparation chain
(``modules.evidence.compilation.services.import_activation`` → story/world/
writing facades) on deterministic synthetic long-form data, plus the two
``limit=10_000`` hot reads (``get_world_context`` / ``list_entity_terms``)
in isolation. Records per-call SQL counts by label, DB time, wall time, and
Python peak memory for every scale tier, and writes a JSON + Markdown report.

Fail-closed database targeting: only the dedicated G7 database (or an
explicit URL whose name carries a standalone ``g7`` marker) is accepted; the
tool never reads ``backend/.env`` and never falls back to a shared database.
"""

from __future__ import annotations

import gc
import hashlib
import os
import re
import resource
import sys
import time
import tracemalloc
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from tools.import_scan_baseline.synthetic import (
    SyntheticNovel,
    TierSpec,
    build_novel,
    ident,
)

DEFAULT_DATABASE = (
    "postgresql+asyncpg://novelist:novel_dev_pass@127.0.0.1:5207/novel_pg_g7a"
)
_DEDICATED_MARKER = re.compile(r"(?:^|[_-])g7", re.IGNORECASE)
_FORBIDDEN_DATABASES = {
    "postgres",
    "template0",
    "template1",
    "novel_dev",
    "ai_novel_engine",
}

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".test-artifacts" / "import_scan_baseline"

_WORLD_CONTEXT_HOT_LABEL = "select:world_context_entities"
_ENTITY_TERMS_HOT_LABEL = "select:entity_terms"


class BaselineTargetError(RuntimeError):
    """Refuse a database target that is not the dedicated G7 baseline DB."""


def resolve_database_url(explicit: str | None = None) -> str:
    """Return one explicit dedicated PostgreSQL URL or fail closed."""
    value = explicit or os.environ.get("G7A_DATABASE_URL") or DEFAULT_DATABASE
    try:
        url = make_url(value)
    except Exception as exc:  # noqa: BLE001 - surfaced as target refusal
        raise BaselineTargetError("G7a database URL is not valid") from exc
    if url.get_backend_name() != "postgresql":
        raise BaselineTargetError("G7a baseline requires PostgreSQL (asyncpg URL)")
    database = (url.database or "").strip()
    if not database or database.casefold() in _FORBIDDEN_DATABASES:
        raise BaselineTargetError(
            f"Refusing non-dedicated database target: {database!r}"
        )
    if not _DEDICATED_MARKER.search(database):
        raise BaselineTargetError(
            "G7a baseline database name must carry a standalone 'g7' marker "
            f"(got {database!r}); use the dedicated novel_pg_g7a database"
        )
    return value


def classify_statement(statement: str) -> str:
    """Map one compiled SQL statement to a stable baseline label."""
    sql = " ".join(statement.split())
    lowered = sql.casefold()
    if lowered.startswith(("insert into", "update ", "delete from")):
        verb = lowered.split()[0]
        match = re.search(
            r"(?:insert\s+into|update|delete\s+from)\s+([a-z_][a-z0-9_]*)", lowered
        )
        table = match.group(1) if match else "unknown"
        return f"{verb}:{table}"
    if "core_entities.id in (" in lowered:
        return "select:entity_endpoints"
    if "core_entities.status in (" in lowered:
        return _WORLD_CONTEXT_HOT_LABEL
    if "from core_entities" in lowered and "core_entities.summary" not in lowered:
        return _ENTITY_TERMS_HOT_LABEL
    match = re.search(r"\bfrom\s+([a-z_][a-z0-9_]*)", lowered)
    if match:
        return f"select:{match.group(1)}"
    return "other"


class SqlTrace:
    """Count and time every cursor statement, grouped by classify label."""

    def __init__(self) -> None:
        self.label_counts: Counter[str] = Counter()
        self.label_seconds: dict[str, float] = defaultdict(float)
        self.statement_shapes: Counter[str] = Counter()
        self._starts: deque[float] = deque()
        self.total_seconds = 0.0

    def before_cursor_execute(
        self, _conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        self._starts.append(time.perf_counter())
        self.statement_shapes[" ".join(statement.split())[:240]] += 1

    def after_cursor_execute(
        self, _conn, _cursor, _statement, _parameters, _context, _executemany
    ) -> None:
        if not self._starts:
            return
        elapsed = time.perf_counter() - self._starts.pop()
        label = classify_statement(_statement)
        self.label_counts[label] += 1
        self.label_seconds[label] += elapsed
        self.total_seconds += elapsed

    @property
    def statement_count(self) -> int:
        return sum(self.label_counts.values())

    def report(self) -> dict[str, Any]:
        return {
            "statements": self.statement_count,
            "db_seconds": round(self.total_seconds, 6),
            "by_label": {
                label: {
                    "count": self.label_counts[label],
                    "seconds": round(self.label_seconds[label], 6),
                }
                for label in sorted(self.label_counts)
            },
        }

    def attach(self, sync_engine) -> None:
        event.listen(
            sync_engine, "before_cursor_execute", self.before_cursor_execute
        )
        event.listen(
            sync_engine, "after_cursor_execute", self.after_cursor_execute
        )

    def detach(self, sync_engine) -> None:
        event.remove(
            sync_engine, "before_cursor_execute", self.before_cursor_execute
        )
        event.remove(
            sync_engine, "after_cursor_execute", self.after_cursor_execute
        )


@dataclass
class CallStats:
    repeat: int
    wall_seconds: float
    trace_report: dict[str, Any]
    contract_shape: dict[str, Any]


@dataclass
class HotReadStats:
    name: str
    repeat: int
    rows: int
    db_seconds: float
    statements: int


@dataclass
class TierResult:
    spec: TierSpec
    seed_seconds: float
    seed_rows: dict[str, int]
    corpus_chars: int
    calls: list[CallStats] = field(default_factory=list)
    hot_reads: list[HotReadStats] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    digest: str = ""

    def median_wall_seconds(self) -> float:
        values = sorted(call.wall_seconds for call in self.calls)
        if not values:
            return 0.0
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2

    def median_db_seconds(self) -> float:
        values = sorted(
            call.trace_report["db_seconds"] for call in self.calls
        )
        if not values:
            return 0.0
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2

    def median_statements(self) -> int:
        values = sorted(call.trace_report["statements"] for call in self.calls)
        if not values:
            return 0
        return values[len(values) // 2]


def import_all_models() -> None:
    import infrastructure.tasks.models  # noqa: F401
    import modules.account.models  # noqa: F401
    import modules.evidence.models  # noqa: F401
    import modules.evolution.models  # noqa: F401
    import modules.imports.models  # noqa: F401
    import modules.project.models  # noqa: F401
    import modules.story.continuity.models  # noqa: F401
    import modules.story.models  # noqa: F401
    import modules.story.outline_state.models  # noqa: F401
    import modules.world.map_atlas_models  # noqa: F401
    import modules.world.models  # noqa: F401
    import modules.writing.models  # noqa: F401


async def ensure_schema(engine, *, allow_metadata_fallback: bool = False) -> dict:
    """Require the dedicated database at the current Alembic head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    async with engine.connect() as connection:
        exists = await connection.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        )
        if not exists.scalar():
            if allow_metadata_fallback:
                import_all_models()
                from core.base import Base

                await connection.rollback()
                async with engine.begin() as ddl:
                    await ddl.run_sync(Base.metadata.create_all)
                return {"schema": "metadata-create-all"}
            raise RuntimeError(
                "G7a 专用库为空：先 `cd backend && DATABASE_URL=<url> uv run alembic "
                "upgrade head`，或对本工具传 --create-schema"
            )
        heads = await connection.execute(text("SELECT version_num FROM alembic_version"))
        current = {row[0] for row in heads}
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    expected = set(script.get_heads())
    if current != expected:
        raise RuntimeError(
            "G7a 专用库不在当前 Alembic head："
            f"数据库={sorted(current) or ['<none>']}，期望={sorted(expected)}"
        )
    return {"schema": "alembic-head", "head": sorted(expected)}


async def seed_novel(db, novel: SyntheticNovel) -> dict[str, int]:
    """Persist the synthetic tier as production-shaped ORM rows."""
    from modules.account.models import Account
    from modules.project.models import Project
    from modules.story.outline_state.models import Scene, SceneSpan
    from modules.world.models import CoreEntity, EntityRelation
    from modules.writing.models import WritingDraft
    from modules.writing.source_hashing import hash_text

    owner_id = ident(novel.novel_key, "owner")
    db.add(
        Account(id=owner_id, support_code=f"g7a-{novel.spec.name.casefold()}")
    )
    await db.flush()
    db.add(
        Project(
            id=novel.novel_id,
            owner_id=owner_id,
            title=f"G7a 合成长篇基线 {novel.spec.name}",
            genre="合成语料",
            tone="程序生成",
        )
    )
    await db.flush()

    draft_ids: dict[int, Any] = {}
    for chapter_index, chapter_text in enumerate(novel.chapter_texts, start=1):
        draft = WritingDraft(
            id=ident(novel.novel_key, f"draft-{chapter_index}"),
            novel_id=novel.novel_id,
            chapter_index=chapter_index,
            title=f"第{chapter_index}章",
            content=chapter_text,
            content_hash=hash_text(chapter_text),
            version_number=1,
            status="published",
        )
        db.add(draft)
        draft_ids[chapter_index] = draft
    await db.flush()

    scene_ids: dict[int, Any] = {}
    mentioned_character_ids = sorted(novel.mentioned_keys)[:2]
    for seed in novel.scenes:
        related = (
            mentioned_character_ids
            if seed.scene_index == novel.target_scene_index
            else []
        )
        scene = Scene(
            id=ident(novel.novel_key, f"scene-{seed.scene_index}"),
            novel_id=novel.novel_id,
            scene_index=seed.scene_index,
            title=seed.title,
            goal=seed.goal,
            core_conflict=seed.core_conflict,
            emotional_beat=f"第{seed.scene_index}场的合成情绪节拍",
            must_happen=f"第{seed.scene_index}场必须完成航路核对",
            must_not_happen="不得泄露未登场设定",
            narrative_tag="draft",
            source="deep_import",
            scene_chunks=[
                {
                    "chapter_index": seed.chapter_index,
                    "start_offset": seed.start_offset,
                    "end_offset": seed.end_offset,
                }
            ],
            chapter_ids=[seed.chapter_index],
            structure_meta={
                "narrative_function": "synthetic_baseline",
                **(
                    {"related_character_ids": related} if related else {}
                ),
            },
            status="draft",
        )
        db.add(scene)
        scene_ids[seed.scene_index] = scene
    await db.flush()

    for seed in novel.scenes:
        chapter_text = novel.chapter_texts[seed.chapter_index - 1]
        excerpt = chapter_text[seed.start_offset : seed.end_offset]
        draft = draft_ids[seed.chapter_index]
        db.add(
            SceneSpan(
                id=ident(novel.novel_key, f"span-{seed.scene_index}"),
                novel_id=novel.novel_id,
                scene_id=scene_ids[seed.scene_index].id,
                chapter_index=seed.chapter_index,
                content_mode="canonical",
                source_draft_id=draft.id,
                source_content_hash=draft.content_hash,
                start_offset=seed.start_offset,
                end_offset=seed.end_offset,
                start_paragraph=seed.part,
                end_paragraph=seed.part,
                part_no=seed.part,
                mapping_status="exact",
                anchor_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                anchor_excerpt=excerpt[:256],
                source="deep_import",
                status="draft",
            )
        )
    await db.flush()

    for index, seed in enumerate(novel.entities):
        db.add(
            CoreEntity(
                id=ident(novel.novel_key, seed.key),
                novel_id=novel.novel_id,
                entity_type=seed.entity_type,
                name=seed.name,
                summary=seed.summary,
                public_info=seed.public_info,
                hidden_truth=seed.hidden_truth,
                content_json={"aliases": list(seed.aliases)},
                importance=seed.importance,
                importance_level="core" if seed.importance >= 0.9 else "normal",
                reveal_level="author_only",
                status=seed.status,
                created_by="g7a-synthetic",
            )
        )
        if index and index % 500 == 0:
            await db.flush()
    await db.flush()

    for relation_index, seed in enumerate(novel.relations):
        db.add(
            EntityRelation(
                id=ident(
                    novel.novel_key,
                    f"relation-{relation_index:05d}-{seed.source_key}",
                ),
                novel_id=novel.novel_id,
                source_id=ident(novel.novel_key, seed.source_key),
                target_id=ident(novel.novel_key, seed.target_key),
                relation_type=seed.relation_type,
                relation_kind=seed.relation_kind,
                description=f"{seed.relation_type}关系：合成基线边。",
                strength=0.6,
                review_meta=seed.review_meta,
                status=seed.status,
            )
        )
    await db.flush()
    return {
        "chapters": len(novel.chapter_texts),
        "scenes": len(novel.scenes),
        "spans": len(novel.scenes),
        "entities": len(novel.entities),
        "relations": len(novel.relations),
    }


async def _prepare(db, novel_id: str, scene_id: str):
    from modules.evidence.compilation.services.import_activation import (
        ImportContextActivationService,
    )

    return await ImportContextActivationService().prepare(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        context_mode="working",
        budget_tokens=4_000,
        prior_neighbor_limit=2,
    )


def _contract_shape(activation) -> dict[str, Any]:
    return {
        "identity_candidates": len(activation.identity_candidates),
        "omitted_sources": len(activation.omitted_sources),
        "relation_candidates": len(activation.relation_candidates),
        "sources": len(activation.sources),
        "current_scene_chars": len(activation.current_scene_text or ""),
        "warnings": list(activation.warnings),
    }


async def measure_tier(
    engine,
    spec: TierSpec,
    *,
    repeats: int = 3,
    hot_read_repeats: int = 5,
    keep_data: bool = False,
) -> TierResult:
    """Seed one tier, then measure prepare() and the two hot reads."""
    from sqlalchemy import delete

    from modules.account.models import Account
    from modules.project.models import Project

    novel = build_novel(spec)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    result = TierResult(
        spec=spec,
        seed_seconds=0.0,
        seed_rows={},
        corpus_chars=sum(len(item) for item in novel.chapter_texts),
        digest=novel.content_digest(),
    )

    started = time.perf_counter()
    async with sessions() as db:
        result.seed_rows = await seed_novel(db, novel)
        await db.commit()
    result.seed_seconds = round(time.perf_counter() - started, 3)

    novel_id = str(novel.novel_id)
    scene_id = str(novel.target_scene_id)
    try:
        # 暖身调用并提交：让 working 模式 SceneSpan 克隆落在库里，
        # 之后的测量对应长期顺序导入的稳态。
        async with sessions() as db:
            await _prepare(db, novel_id, scene_id)
            await db.commit()

        for repeat in range(1, repeats + 1):
            async with sessions() as db:
                trace = SqlTrace()
                trace.attach(engine.sync_engine)
                try:
                    mark = time.perf_counter()
                    activation = await _prepare(db, novel_id, scene_id)
                    wall = time.perf_counter() - mark
                    await db.rollback()
                finally:
                    trace.detach(engine.sync_engine)
                result.calls.append(
                    CallStats(
                        repeat=repeat,
                        wall_seconds=round(wall, 6),
                        trace_report=trace.report(),
                        contract_shape=_contract_shape(activation),
                    )
                )

        current_chapter = spec.chapters
        result.hot_reads = await _measure_hot_reads(
            engine,
            novel_id,
            current_chapter=current_chapter,
            repeats=hot_read_repeats,
        )
        result.memory = await _measure_memory(engine, novel_id, scene_id)
    finally:
        if not keep_data:
            async with sessions() as db:
                await db.execute(
                    delete(Project).where(Project.id == novel.novel_id)
                )
                owner_id = ident(novel.novel_key, "owner")
                await db.execute(delete(Account).where(Account.id == owner_id))
                await db.commit()
    return result


async def _measure_hot_reads(
    engine, novel_id: str, *, current_chapter: int, repeats: int
) -> list[HotReadStats]:
    from modules.world.facade import get_world_context, list_entity_terms

    stats: list[HotReadStats] = []
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    probes = (
        ("get_world_context", get_world_context),
        ("list_entity_terms", list_entity_terms),
    )
    for name, func in probes:
        for repeat in range(1, repeats + 1):
            async with sessions() as db:
                trace = SqlTrace()
                trace.attach(engine.sync_engine)
                try:
                    if name == "get_world_context":
                        bundle = await func(
                            db,
                            novel_id,
                            reveal_mode="author_safe",
                            limit=10_000,
                            current_chapter=current_chapter,
                            include_review=True,
                        )
                        rows = len(bundle.entities)
                    else:
                        terms = await func(db, novel_id, limit=10_000)
                        rows = len(terms)
                    await db.rollback()
                finally:
                    trace.detach(engine.sync_engine)
                stats.append(
                    HotReadStats(
                        name=name,
                        repeat=repeat,
                        rows=rows,
                        db_seconds=round(trace.total_seconds, 6),
                        statements=trace.statement_count,
                    )
                )
    return stats


async def _measure_memory(engine, novel_id: str, scene_id: str) -> dict[str, Any]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    gc.collect()
    rss_before = _ru_maxrss_kib()
    tracemalloc.start()
    try:
        async with sessions() as db:
            activation = await _prepare(db, novel_id, scene_id)
            await db.rollback()
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    rss_after = _ru_maxrss_kib()
    return {
        "tracemalloc_current_bytes": current,
        "tracemalloc_peak_bytes": peak,
        "ru_maxrss_kb_before": rss_before,
        "ru_maxrss_kb_after": rss_after,
        "contract_shape": _contract_shape(activation),
    }


def _ru_maxrss_kib() -> int:
    """Normalize getrusage ru_maxrss: bytes on darwin, KiB on Linux."""
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(value / 1024)
    return int(value)


def provenance() -> dict[str, Any]:
    import subprocess

    root = ROOT.parent
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=root).strip()
    )
    sources = {
        "backend/tools/import_scan_baseline/synthetic.py": None,
        "backend/tools/import_scan_baseline/collector.py": None,
        "backend/modules/evidence/compilation/services/import_activation.py": None,
    }
    for name in sources:
        path = root / name
        sources[name] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        )
    return {"commit": commit, "worktree_dirty": dirty, "source_sha256": sources}


def tier_result_to_dict(result: TierResult) -> dict[str, Any]:
    return {
        "spec": result.spec.summary(),
        "digest": result.digest,
        "corpus_chars": result.corpus_chars,
        "seed_seconds": result.seed_seconds,
        "seed_rows": result.seed_rows,
        "median_wall_seconds": round(result.median_wall_seconds(), 6),
        "median_db_seconds": round(result.median_db_seconds(), 6),
        "median_statements": result.median_statements(),
        "calls": [
            {
                "repeat": call.repeat,
                "wall_seconds": call.wall_seconds,
                "trace": call.trace_report,
                "contract_shape": call.contract_shape,
            }
            for call in result.calls
        ],
        "hot_reads": [
            {
                "name": item.name,
                "repeat": item.repeat,
                "rows": item.rows,
                "db_seconds": item.db_seconds,
                "statements": item.statements,
            }
            for item in result.hot_reads
        ],
        "memory": result.memory,
        "hot_read_summary": hot_read_summary(result),
    }


def hot_read_summary(result: TierResult) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for name in ("get_world_context", "list_entity_terms"):
        rows = [item for item in result.hot_reads if item.name == name]
        if not rows:
            continue
        seconds = sorted(item.db_seconds for item in rows)
        summary[name] = {
            "rows": rows[0].rows,
            "median_db_seconds": seconds[len(seconds) // 2],
            "min_db_seconds": seconds[0],
            "max_db_seconds": seconds[-1],
        }
    return summary


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# G7a 导入输入扫描基线（合成数据，零模型）",
        "",
        f"- commit: `{report['provenance']['commit']}`"
        f"（dirty={report['provenance']['worktree_dirty']}）",
        f"- database: `{report['database_name']}`；schema: {report['schema']['schema']}",
        f"- repeats: prepare×{report['repeats']}，hot read×{report['hot_read_repeats']}",
        "",
        "## prepare() 稳态规模曲线",
        "",
        "| 档位 | 章 | Scene | 实体(canonical+review) | 词项 | SQL 数(中位) |"
        " DB 秒(中位) | 墙钟秒(中位) | 内存峰值 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for tier in report["tiers"]:
        memory_peak = tier["memory"].get("tracemalloc_peak_bytes") or 0
        lines.append(
            f"| {tier['spec']['name']} | {tier['spec']['chapters']} "
            f"| {tier['spec']['scenes']} "
            f"| {tier['spec']['canonical_entities']}+{tier['spec']['review_entities']} "
            f"| {tier['spec']['aliases']} | {tier['median_statements']} "
            f"| {tier['median_db_seconds']:.4f} | {tier['median_wall_seconds']:.4f} "
            f"| {memory_peak / 1024:.0f} KiB |"
        )
    lines.extend(
        [
            "",
            "## 热点单查（limit=10_000，隔离测量）",
            "",
            "| 档位 | get_world_context 行数/中位秒 | list_entity_terms 行数/中位秒 |",
            "| --- | --- | --- |",
        ]
    )
    for tier in report["tiers"]:
        hot = tier.get("hot_read_summary", {})
        world = hot.get("get_world_context", {})
        terms = hot.get("list_entity_terms", {})
        lines.append(
            f"| {tier['spec']['name']} "
            f"| {world.get('rows', 0)} / {world.get('median_db_seconds', 0):.4f}s "
            f"| {terms.get('rows', 0)} / {terms.get('median_db_seconds', 0):.4f}s |"
        )
    lines.extend(
        [
            "",
            "## prepare() SQL 标签分解（最后一个测量调用）",
            "",
        ]
    )
    for tier in report["tiers"]:
        if not tier["calls"]:
            continue
        lines.append(f"### {tier['spec']['name']}")
        lines.append("")
        lines.append("| 标签 | 条数 | 秒 |")
        lines.append("| --- | --- | --- |")
        by_label = tier["calls"][-1]["trace"]["by_label"]
        for label, item in by_label.items():
            lines.append(f"| `{label}` | {item['count']} | {item['seconds']:.4f} |")
        lines.append("")
    return "\n".join(lines) + "\n"

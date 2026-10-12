"""远景第一阶段 M0：RP 编译链成本基线测量（可复跑）。

测量目标（主计划 2026-10-06-world-foundation-phase1 §5/§7.3）：
- 首次填充（章节索引 + 真实 embedding 链）的耗时结构；
- 普通 RP 每轮编译（新查询、进程暖、embedding 缓存 miss）的全价成本；
- Agent 补查 lookup_source 同轮重复查询的重复成本与 LRU 命中差异；
- ensemble 每演员一次编译、8K/16K 预算差异、character/reader 视角差异；
- 冷启动：首个 attempt 的 embedding 含 BGE 模型加载（新进程/空 LRU）。

真实链约定：走生产 IndexingService 与 InteractionStoryContextService.compile
（检索 top_k=12、rerank=False 硬编码于 service），embedding 使用本地 bge_onnx
（唯一免费路径；生产 TEI 远程成本不在本 harness 范围，须另行实测）。

隐私与安全：语料全部合成（种子重建），不含用户数据；报告不落正文渲染文本。
数据库只允许 SQLite 临时文件或名称含 e2e/baseline 专用标记的 PostgreSQL 库，
PG 库必须先 alembic upgrade head；不触碰任何真实项目库。

复跑：
    cd backend && uv run --python 3.13 --locked --extra dev -- \
        python -m evals.rp_cost_baseline run --scales s,m \
        --output evals/artifacts/rp-cost-baseline/report.json
    # PG 代表性运行：先建专用库并迁移，再 DATABASE_URL=... 同命令。
"""

from __future__ import annotations

import os

if __name__ == "__main__":
    # CLI（python -m evals.rp_cost_baseline）时必须在仓库 import 之前固定环境，
    # 防止本机 backend/.env 漂移进测量；被 import（含 pytest 收集）时不改进程环境。
    os.environ["EMBEDDING_PROVIDER"] = "bge_onnx"
    os.environ.setdefault("LLM_HEALTH_REQUIRED", "false")
    os.environ.setdefault("RERANKER_ENABLED", "false")
    os.environ.setdefault("RAG_QUERY_PLANNER_ENABLED", "false")
    os.environ.setdefault("RAG_PREWARM_ON_STARTUP", "false")
    os.environ.setdefault(
        "LLM_SETTINGS_ENCRYPTION_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    os.environ.setdefault("DEBUG", "false")
    os.environ.setdefault("ECHO_SQL", "false")

import argparse
import asyncio
import contextlib
import functools
import hashlib
import json
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

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
from app.bootstrap import register_container_services
from core.base import Base
from infrastructure.llm.token_estimation import estimate_token_count
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.evidence.compilation.services.interaction_story_context import (
    InteractionStoryContextService,
)
from modules.evidence.indexing.indexing import IndexingService
from modules.evidence.indexing.metrics import get_metrics
from modules.evidence.indexing.repositories import RagChunkRepository
from modules.project.models import Project
from modules.world.models.core import CoreEntity
from modules.writing.facade import create_published_draft_only

REPORT_KIND = "rp_cost_baseline.v1"

# ── 冻结样本族（样本与场景由此常量 + 种子确定性重建；改动需换种子并留记录） ──

FAMILY_SEED = 20261006

# 实体阵容：与主计划 §3.1 首个验收切片母题对齐（钥匙交接/保管、仅特定人知的秘密、
# 明确开启条件的锁），全部为合成名词，不与任何真实项目共享。
CAST_CHARACTERS = ["沈砚", "顾青梧", "温若", "霍山"]
CAST_ITEM = "铜钥匙"
CAST_LOCATIONS = ["雾渡港", "灯塔", "旧仓库"]

SCALE_CHAPTERS: dict[str, int] = {"s": 12, "m": 36, "l": 60}

# 母题事件固定章号（与章节数无关，缺省由填充段补足）。
MOTIF_KEY_HANDOVER_CHAPTER = 2
MOTIF_SECRET_CHAPTER = 5
MOTIF_LOCK_CONDITION_CHAPTER = 7

# 查询族：固定回顾前缀 + 逐轮变化的当前输入与最近发展（对齐 _source_retrieval_query
# 的组成语义；长度约 1K 字符，低于生产 4K 上限，避免向量长度主导计时）。
_QUERY_RECAP = (
    "当前局面：沈砚身在雾渡港，铜钥匙自交接之后一直由顾青梧保管。"
    "相关人物与势力：顾青梧（保管者，雾渡港商会账房，做事谨慎，从不把话说满）、"
    "温若（灯塔看守，知道灯塔的秘密，只与海鸟和火苗说话）、"
    "霍山（追查钥匙下落的外来商人，出手阔绰，问话却总绕着同一件事）。"
    "未决事项：铜钥匙的下落、旧仓库的锁的开启条件、灯塔的秘密究竟指什么、"
    "霍山的手伸到了哪一步。必须记住：沈砚只把钥匙交给过顾青梧一个人，"
    "温若从未向任何人证实过秘密的内容，商会的账目里没有这把钥匙的任何一笔。"
    "顾青梧把油纸包了三层的钥匙锁进账房最深的抽屉，钥匙孔上积着经年的盐霜。"
    "旧仓库的看门人换了三班，交接簿上的名字越来越潦草。"
    "灯塔彻夜不熄，雾从海面一层一层压进街巷，把所有脚印都抹平。"
    "沈砚抄下的三个条件还折在靴筒里：铜钥匙、月圆之夜、正确的口令，缺一不可。"
    "最近发展："
)
_QUERY_INPUTS = [
    "本轮输入：沈砚向顾青梧当面索要铜钥匙，话说出口之前先看了一眼账房的门。",
    "本轮输入：沈砚旁敲侧击，试探温若是否知道灯塔的秘密，把话头藏在闲聊里。",
    "本轮输入：沈砚核对旧仓库的锁的开启条件，回忆月圆与口令的传闻是否对得上。",
    "本轮输入：沈砚打听霍山的动向，判断他是否已经摸到雾渡港的边。",
    "本轮输入：沈砚决定夜探灯塔，先在码头清点随身物品，把靴筒里的纸条又读一遍。",
    "本轮输入：沈砚与顾青梧在商会密谈，商量如何应付霍山的人。",
]
_QUERY_RECENT = [
    "顾青梧提到，锁要月圆之夜并念对口令才能打开，说完就把账本合上了。",
    "温若只说了一句：灯塔亮起的时候，秘密自己会走到光里，随后不再多言。",
    "旧仓库的看门人换了，钥匙孔里积着盐霜，新来的人对三簧锁一无所知。",
    "霍山的人开始在码头打听一个带铜钥匙的年轻人，赏钱给得很痛快。",
    "灯塔彻夜未熄，雾从海面压进街巷，巡夜人换了两次岗。",
    "商会账房的灯亮到后半夜，顾青梧清点什么，算盘声断断续续。",
]

ENSEMBLE_ACTOR_SUFFIXES = [
    "（以沈砚的视角展开）",
    "（以顾青梧的视角展开）",
    "（以温若的视角展开）",
]
BUDGET_PAIR = (16_000, 8_000)
AGENT_BUDGET = 8_000
ENSEMBLE_BUDGET = 5_000

DEFAULT_ROUNDS = 6
DEFAULT_REPEATS = 3


def build_family_spec() -> dict[str, Any]:
    """返回冻结样本族定义；spec_hash 是族身份，记录在任务与报告中。"""

    return {
        "seed": FAMILY_SEED,
        "cast": {
            "characters": CAST_CHARACTERS,
            "item": CAST_ITEM,
            "locations": CAST_LOCATIONS,
        },
        "scales": dict(SCALE_CHAPTERS),
        "corpus_generator": {
            "beats_range": [36, 52],
            "beat_templates": len(_BEAT_ACTIONS),
            "followup_templates": len(_BEAT_FOLLOWUPS),
            "ambient_templates": len(_AMBIENT),
        },
        "motif_chapters": {
            "key_handover": MOTIF_KEY_HANDOVER_CHAPTER,
            "secret": MOTIF_SECRET_CHAPTER,
            "lock_condition": MOTIF_LOCK_CONDITION_CHAPTER,
        },
        "query_family": {
            "recap_chars": len(_QUERY_RECAP),
            "inputs": len(_QUERY_INPUTS),
            "recent": len(_QUERY_RECENT),
        },
        "scenarios": {
            "rp_normal_fresh": {"rounds": DEFAULT_ROUNDS, "player_mode": "character"},
            "agent_requery_same": {"repeats": DEFAULT_REPEATS, "budget": AGENT_BUDGET},
            "ensemble_actors": {"actors": len(ENSEMBLE_ACTOR_SUFFIXES)},
            "budget_pair": {"budgets": list(BUDGET_PAIR)},
            "reader_mode": {"rounds": 2},
        },
        "retrieval": {"top_k": 12, "rerank": False},
        "embedding_provider": "bge_onnx",
    }


def spec_hash(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── 合成语料生成（确定性） ──


_BEAT_ACTIONS = [
    "把外袍的领口收紧，沿着{where}的石阶走向渡口",
    "在{where}与{other}擦肩而过，两人都没有回头",
    "数着缆绳上的盐粒，想起{other}上月留下的账目",
    "听见{other}在里屋压低声音念着什么，像是一句口令",
    "写信给{other}，落款处犹豫了三次",
    "夜里惊醒，梦里全是灯塔的光柱扫过海面",
]
_BEAT_FOLLOWUPS = [
    "潮声一阵接着一阵，把话说完的余地都吞掉了。",
    "灯芯爆了一个火星，影子在墙上晃了晃。",
    "有人在楼上挪动木箱，声音闷得像是从水底传来。",
    "他数到第七块船板的时候，风忽然停了。",
    "这个念头只停留了一瞬，就被码头的号子打断。",
    "纸上留下的字迹比昨夜更淡，像被雾吸走了一半。",
]
_AMBIENT = [
    "雾渡港的钟声敲过三下，街上只剩巡夜人的脚步。",
    "灯塔的光在雾里晕开一圈一圈的毛边。",
    "旧仓库的看门人换了班，交接簿上多了新的名字。",
    "潮气渗进纸页，字迹边缘洇出细小的绒毛。",
]


def _chapter_text(chapter_index: int) -> str:
    rng = random.Random((FAMILY_SEED << 8) ^ chapter_index)
    paragraphs: list[str] = []
    paragraphs.append(
        f"第{chapter_index}章的雾从海面漫进雾渡港，"
        f"{rng.choice(CAST_CHARACTERS)}在灯下摊开航海图的残页。"
    )
    beats = rng.randint(36, 52)
    for i in range(beats):
        who = rng.choice(CAST_CHARACTERS)
        where = rng.choice(CAST_LOCATIONS)
        other = rng.choice([name for name in CAST_CHARACTERS if name != who])
        beat = rng.choice(_BEAT_ACTIONS).format(who=who, where=where, other=other)
        followups = rng.randint(1, 3)
        paragraph = f"{who}{beat}。"
        for _ in range(followups):
            paragraph += rng.choice(_BEAT_FOLLOWUPS)
        paragraphs.append(paragraph)
        if i % 4 == 3:
            paragraphs.append(rng.choice(_AMBIENT))
    if chapter_index == MOTIF_KEY_HANDOVER_CHAPTER:
        paragraphs.insert(
            3,
            "沈砚把铜钥匙放进顾青梧掌心，说：只借你保管，别告诉任何人。"
            "顾青梧用油纸把铜钥匙包了三层，锁进账房最深的抽屉。"
            "从这一夜起，铜钥匙的所有权证据在沈砚手里，保管证据只在顾青梧手里。",
        )
    if chapter_index == MOTIF_SECRET_CHAPTER:
        paragraphs.insert(
            5,
            "温若独自登上灯塔顶层，对着火苗低声说：还差最后一块。"
            "灯塔的秘密只有温若一个人知道完整的说法，"
            "雾渡港的传闻都只是碎片，没有人能拼出全貌。",
        )
    if chapter_index == MOTIF_LOCK_CONDITION_CHAPTER:
        paragraphs.insert(
            7,
            "旧仓库的锁是匠人特制的三簧锁：要铜钥匙、要月圆之夜、"
            "还要念出正确的口令，三者缺一，锁芯纹丝不动。"
            "沈砚抄下这三个条件，折好塞进靴筒。",
        )
    return "\n\n".join(paragraphs)


def _query_for_round(round_index: int) -> str:
    idx = round_index % len(_QUERY_INPUTS)
    return _QUERY_RECAP + _QUERY_RECENT[idx] + "。" + _QUERY_INPUTS[idx]


def _content_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _query_id(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


# ── 数据库装载 ──


@compiles(PG_UUID, "sqlite")
def _compile_postgres_uuid_as_text_for_sqlite(_type, _compiler, **_kwargs) -> str:
    return "CHAR(32)"


_PG_NAME_MARKERS = ("e2e", "baseline")


def _resolve_database_url(cli_url: str | None, sqlite_path: Path) -> str:
    """缺省读 DATABASE_URL，再缺省用一次性 SQLite 文件（不能用内存库：多连接不共享）。"""

    url = cli_url or os.environ.get("DATABASE_URL") or ""
    if not url:
        return f"sqlite+aiosqlite:///{sqlite_path}"
    if url.startswith("sqlite"):
        return url
    if url.startswith("postgres"):
        name = url.rsplit("/", 1)[-1].split("?")[0].lower()
        if not any(marker in name for marker in _PG_NAME_MARKERS):
            raise SystemExit(
                "拒绝非专用 PostgreSQL 目标：库名必须含 e2e 或 baseline 标记，"
                f"当前为 {name!r}。请使用一次性专用库。"
            )
        return url
    raise SystemExit(f"不支持的数据库 URL：{url.split(':', 1)[0]}")


async def _assert_pg_schema_ready(engine) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    expected = sorted(script.get_heads())
    async with engine.connect() as connection:
        current = sorted(
            (await connection.execute(text("SELECT version_num FROM alembic_version")))
            .scalars()
            .all()
        )
    if current != expected:
        raise SystemExit(
            "PostgreSQL 目标库 schema 不是当前 Alembic head："
            f"库={current or ['<none>']}，期望={expected}。先执行 alembic upgrade head。"
        )


# ── 分段计时（进程内包装真实服务方法；仅本 harness 进程存活） ──


class _SegmentRecorder:
    def __init__(self) -> None:
        self._values: dict[str, list[float]] = {}

    def record(self, label: str, ms: float) -> None:
        self._values.setdefault(label, []).append(ms)

    def consume(self) -> dict[str, Any]:
        result = {}
        for label, values in self._values.items():
            result[label] = {
                "calls": len(values),
                "total_ms": round(sum(values), 2),
            }
        self._values.clear()
        return result


@contextlib.asynccontextmanager
async def _segment_instrumentation(recorder: _SegmentRecorder) -> Iterator[None]:
    from modules.evidence.compilation import novel_evidence
    from modules.evidence.compilation.services import snapshot_service

    targets = (
        (
            novel_evidence.NovelEvidenceService,
            "rehydrate_manuscript_candidates",
            "rehydrate_ms",
        ),
        (novel_evidence.NovelEvidenceService, "read", "evidence_read_ms"),
        (
            snapshot_service.ContextSnapshotService,
            "create_context_snapshot",
            "snapshot_create_ms",
        ),
    )
    installed: list[tuple[type, str, Any]] = []
    try:
        for cls, method_name, label in targets:
            original = getattr(cls, method_name)

            @functools.wraps(original)
            async def timed(
                self,
                *args,
                __original=original,
                __label=label,
                **kwargs,
            ):
                start = time.monotonic()
                try:
                    return await __original(self, *args, **kwargs)
                finally:
                    recorder.record(__label, (time.monotonic() - start) * 1000)

            setattr(cls, method_name, timed)
            installed.append((cls, method_name, original))

        # 缓存命中可观测：fetch 计时 + 命中/未命中事件（material 级）。
        from modules.evidence.compilation.services.interaction_source_cache import (
            InteractionSourceCacheStore,
        )

        cache_cls = InteractionSourceCacheStore
        original_fetch = cache_cls.fetch

        @functools.wraps(original_fetch)
        async def timed_fetch(self, *args, **kwargs):  # noqa: ANN001, ANN003
            start = time.monotonic()
            try:
                result = await original_fetch(self, *args, **kwargs)
            finally:
                recorder.record("cache_fetch_ms", (time.monotonic() - start) * 1000)
            hit = getattr(result, "hit", None)
            if hit is not None:
                recorder.record("source_cache_hit", 0.0)
            else:
                # M4：未命中原因码进入 attempt 记录（主计划 §7.2）
                reason = getattr(result, "miss_reason", None) or "unknown"
                recorder.record("source_cache_miss", 0.0)
                recorder.record(f"source_cache_miss_{reason}", 0.0)
            return result

        setattr(cache_cls, "fetch", timed_fetch)
        installed.append((cache_cls, "fetch", original_fetch))
        yield
    finally:
        for cls, method_name, original in installed:
            setattr(cls, method_name, original)


_METRIC_FIELDS = (
    "query_count",
    "degraded_count",
    "empty_result_count",
    "meaningful_match_fail_count",
    "total_latency_ms",
    "embedding_latency_ms",
    "embedding_latency_count",
    "search_latency_ms",
    "search_latency_count",
    "indexed_chunks_count",
    "indexing_failed_embedding_count",
)


def _metrics_state() -> dict[str, Any]:
    """读 RagMetrics 原始累计字段（snapshot 只暴露均值，无法做差分）。"""

    metrics = get_metrics()
    return {field: getattr(metrics, field) for field in _METRIC_FIELDS}


def _rag_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        field: round(after[field] - before.get(field, 0), 2) for field in _METRIC_FIELDS
    }


def _cache_stats() -> dict[str, Any]:
    from infrastructure.embedding.client import BgeEmbeddingClient

    return dict(BgeEmbeddingClient.runtime_snapshot().get("cache_stats") or {})


def _git_head() -> str:
    try:
        output = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return output.stdout.strip()[:12]
    except Exception:
        return "unknown"


def _environment(database_url: str, dialect: str) -> dict[str, Any]:
    from core.config import get_settings

    settings = get_settings()
    return {
        "git_head": _git_head(),
        "dialect": dialect,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "bge_onnx_device": settings.bge_onnx_device,
        "reranker_enabled": settings.reranker_enabled,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()}/{platform.machine()}",
        "database_url_redacted": database_url.rsplit("@", 1)[-1]
        if "@" in database_url
        else database_url.split(":", 1)[0],
        "started_at": datetime.now(UTC).isoformat(),
    }


# ── 项目装载（source=原作 author，consumer=同 owner 的 interaction） ──


class _Fixture:
    def __init__(
        self,
        source_id: str,
        consumer_id: str,
        source_manifest: list[dict[str, Any]],
        anchor: dict[str, Any],
        reference_manifest: list[dict[str, Any]],
        player_character: dict[str, Any],
        player_reader: dict[str, Any],
        chapters: int,
        chapter_chars: int,
    ) -> None:
        self.source_id = source_id
        self.consumer_id = consumer_id
        self.source_manifest = source_manifest
        self.anchor = anchor
        self.reference_manifest = reference_manifest
        self.player_character = player_character
        self.player_reader = player_reader
        self.chapters = chapters
        self.chapter_chars = chapter_chars


async def _setup_fixture(db: AsyncSession, scale: str) -> _Fixture:
    chapters = SCALE_CHAPTERS[scale]
    source_id = str(uuid.uuid4())
    consumer_id = str(uuid.uuid4())
    # PG 强制外键：默认 owner 指向 bootstrap 账户，需先落行（多档共用，幂等）。
    if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
        db.add(
            Account(
                id=BOOTSTRAP_ACCOUNT_ID,
                status="active",
                support_code=f"U-RPCB-{FAMILY_SEED}",
            )
        )
    db.add_all(
        [
            Project(
                id=uuid.UUID(source_id),
                title=f"成本基线原作-{scale}",
                language="zh",
                project_kind="author",
                default_reveal_policy="author_safe",
                settings={},
            ),
            Project(
                id=uuid.UUID(consumer_id),
                title=f"成本基线旅程-{scale}",
                language="zh",
                project_kind="interaction",
                default_reveal_policy="author_safe",
                settings={},
            ),
        ]
    )
    await db.flush()

    # 世界对象先行：RAG chunk 标注（character_ids/entity_ids）来自项目词典，
    # 与生产「实体抽取 → 索引」顺序一致。
    entity_ids: dict[str, str] = {}
    entity_rows = [
        *((name, "character", f"雾渡港故事中的角色 {name}") for name in CAST_CHARACTERS),
        (CAST_ITEM, "item", "沈砚交出的旧物，匠人特制三簧锁的钥匙"),
        *((name, "location", f"雾渡港故事中的地点 {name}") for name in CAST_LOCATIONS),
    ]
    for name, entity_type, summary in entity_rows:
        entity_id = uuid.uuid4()
        entity_ids[name] = str(entity_id)
        db.add(
            CoreEntity(
                id=entity_id,
                novel_id=uuid.UUID(source_id),
                entity_type=entity_type,
                name=name,
                summary=summary,
                status="canonical",
            )
        )
    await db.flush()

    source_manifest: list[dict[str, Any]] = []
    last_text = ""
    last_title = ""
    for chapter_index in range(1, chapters + 1):
        body = _chapter_text(chapter_index)
        draft = await create_published_draft_only(
            db,
            source_id,
            chapter_index,
            f"第{chapter_index}章",
            body,
        )
        source_manifest.append(
            {
                "draft_id": str(draft.id),
                "source_hash": draft.content_hash,
                "chapter_index": chapter_index,
                "char_count": len(body),
            }
        )
        last_text, last_title = body, f"第{chapters}章"
    await db.commit()

    def _reference(
        key: str,
        name: str,
        entity_type: str,
        first_chapter: int,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "reference_key": key,
            "target_id": entity_ids[name],
            "entity_type": entity_type,
            "label": name,
            "aliases": [],
            "first_chapter_index": first_chapter,
            "first_end_offset": 3,
            **extra,
        }

    reference_manifest = [
        _reference("a" * 64, "沈砚", "character", 1),
        _reference("b" * 64, "顾青梧", "character", 1),
        _reference("c" * 64, "温若", "character", 1),
        _reference("d" * 64, "霍山", "character", 3),
        _reference("e" * 64, CAST_ITEM, "item", MOTIF_KEY_HANDOVER_CHAPTER),
        _reference("f" * 64, "雾渡港", "location", 1),
        _reference("0" * 64, "灯塔", "location", 1),
        {
            "reference_key": "1" * 64,
            "entity_type": "relation",
            "label": "顾青梧保管沈砚的铜钥匙",
            "source_chapter_index": MOTIF_KEY_HANDOVER_CHAPTER,
            "source_target_id": entity_ids["沈砚"],
            "target_target_id": entity_ids["顾青梧"],
        },
    ]
    reference_manifest[0]["knowledge"] = [
        {
            "target_name": "灯塔的秘密",
            "knowledge_level": "unknown",
            "is_public_baseline": True,
        },
        {
            "target_name": CAST_ITEM,
            "knowledge_level": "known",
            "known_content": "已把铜钥匙交给顾青梧保管，钥匙从未离身之外的人只有顾青梧。",
            "source_chapter_index": MOTIF_KEY_HANDOVER_CHAPTER,
            "is_public_baseline": False,
        },
    ]

    player_character = {
        "kind": "source_character",
        "reference_key": "a" * 64,
        "target_id": entity_ids["沈砚"],
        "label": "沈砚",
        "description": "把铜钥匙托付出去的年轻人",
    }
    player_reader = {"kind": "original", "name": "旅人"}
    anchor = {
        "anchor_key": hashlib.sha256(f"{source_id}:end".encode()).hexdigest(),
        "chapter_index": chapters,
        "chapter_title": last_title,
        "label": "全书末尾",
        "end_offset": len(last_text),
        "scene_id": None,
    }
    return _Fixture(
        source_id=source_id,
        consumer_id=consumer_id,
        source_manifest=source_manifest,
        anchor=anchor,
        reference_manifest=reference_manifest,
        player_character=player_character,
        player_reader=player_reader,
        chapters=chapters,
        chapter_chars=len(last_text),
    )


async def _run_indexing(db: AsyncSession, fixture: _Fixture) -> dict[str, Any]:
    service = IndexingService()
    per_chapter_ms: list[float] = []
    chunks_created = 0
    failed_embeddings = 0
    for entry in fixture.source_manifest:
        start = time.monotonic()
        report = await service.index_chapter_with_report(
            db,
            uuid.UUID(fixture.source_id),
            int(entry["chapter_index"]),
            content_mode="canonical",
        )
        await db.commit()
        per_chapter_ms.append((time.monotonic() - start) * 1000)
        chunks_created += report.chunks_created
        failed_embeddings += report.embedding_failed_count
    has_embeddings = await RagChunkRepository().has_embeddings(
        db, uuid.UUID(fixture.source_id)
    )
    return {
        "chapters": fixture.chapters,
        "chunks_created": chunks_created,
        "chunks_per_chapter": round(chunks_created / max(1, fixture.chapters), 2),
        "embedding_failed_count": failed_embeddings,
        "has_embeddings_after_index": has_embeddings,
        "index_wall_ms_total": round(sum(per_chapter_ms), 1),
        "index_wall_ms_per_chapter": [round(value, 1) for value in per_chapter_ms],
        "index_wall_ms_first_chapter": (
            round(per_chapter_ms[0], 1) if per_chapter_ms else None
        ),
    }


# ── 场景执行 ──


class _Runner:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.service = InteractionStoryContextService()
        self.attempt_counter = 0

    async def attempt(
        self,
        fixture: _Fixture,
        *,
        scenario: str,
        query: str,
        budget_tokens: int,
        player: dict[str, Any],
        recorder: _SegmentRecorder,
    ) -> dict[str, Any]:
        self.attempt_counter += 1
        rag_before = _metrics_state()
        cache_before = _cache_stats()
        start = time.monotonic()
        compiled = await self.service.compile(
            self.db,
            source_novel_id=fixture.source_id,
            consumer_novel_id=fixture.consumer_id,
            source_revision_id=fixture.anchor["anchor_key"],
            source_manifest=fixture.source_manifest,
            anchor=fixture.anchor,
            player_identity=player,
            reference_manifest=fixture.reference_manifest,
            ambiguities=[],
            resolutions={},
            reference_policy={"pinned": [], "excluded": []},
            query=query,
            task_id=None,
            model="rp-cost-baseline-probe",
            budget_tokens=budget_tokens,
        )
        compile_ms = (time.monotonic() - start) * 1000
        commit_start = time.monotonic()
        await self.db.commit()
        commit_ms = (time.monotonic() - commit_start) * 1000

        rag = _rag_delta(rag_before, _metrics_state())
        cache_after = _cache_stats()
        segments = recorder.consume()
        attempt = {
            "attempt": self.attempt_counter,
            "scenario": scenario,
            "query_id": _query_id(query),
            "query_chars": len(query),
            "query_token_est": estimate_token_count(query),
            "budget_tokens": budget_tokens,
            "cold_start": self.attempt_counter == 1,
            "compile_ms": round(compile_ms, 1),
            "commit_ms": round(commit_ms, 1),
            "rendered_tokens": compiled.token_count,
            "fingerprint": compiled.fingerprint[:16],
            # 指纹含每次运行随机的 revision/anchor ID，跨运行不可比；
            # rendered_sha 是正文等价性的直接对照物，refs 原始值供 ID 掩码后对比。
            "rendered_sha": _content_sha(compiled.rendered_context),
            "included_refs": [dict(item) for item in compiled.included_refs],
            "source_refs": [dict(item) for item in compiled.source_refs],
            "blockers": list(compiled.blockers),
            "warnings": len(compiled.warnings),
            "degraded": bool(rag.get("degraded_count")),
            "empty_retrieval": bool(rag.get("empty_result_count")),
            "retrieval_queries": int(rag.get("query_count") or 0),
            "rag": rag,
            "embedding_cache": {
                "hits_delta": cache_after.get("hits", 0) - cache_before.get("hits", 0),
                "misses_delta": cache_after.get("misses", 0)
                - cache_before.get("misses", 0),
            },
            # material 级命中：编译复用（预算相同）或从完整材料重裁剪（预算不同）
            "source_cache_hit": bool(segments.get("source_cache_hit", {}).get("calls")),
            "segments": segments,
        }
        return attempt


def _summarize_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts:
        by_scenario.setdefault(attempt["scenario"], []).append(attempt)
    summary: dict[str, Any] = {}
    for scenario, items in by_scenario.items():
        compile_values = [item["compile_ms"] for item in items]
        embedding_values = [
            item["rag"].get("embedding_latency_ms") or 0.0 for item in items
        ]
        search_values = [item["rag"].get("search_latency_ms") or 0.0 for item in items]
        rehydrate_values = [
            item["segments"].get("rehydrate_ms", {}).get("total_ms", 0.0)
            for item in items
        ]
        snapshot_values = [
            item["segments"].get("snapshot_create_ms", {}).get("total_ms", 0.0)
            for item in items
        ]

        def _stats(values: list[float]) -> dict[str, Any]:
            if not values:
                return {}
            ordered = sorted(values)
            return {
                "total": round(sum(ordered), 1),
                "mean": round(statistics.fmean(ordered), 1),
                "median": round(statistics.median(ordered), 1),
                "p95": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 1),
            }

        summary[scenario] = {
            "attempts": len(items),
            "compile_ms": _stats(compile_values),
            "embedding_ms": _stats(embedding_values),
            "search_ms": _stats(search_values),
            "rehydrate_ms": _stats(rehydrate_values),
            "snapshot_create_ms": _stats(snapshot_values),
            "blocked_attempts": sum(1 for item in items if item["blockers"]),
            "degraded_attempts": sum(1 for item in items if item["degraded"]),
            "source_cache_hit_attempts": sum(
                1 for item in items if item.get("source_cache_hit")
            ),
            # 命中尝试的 compile 分布（含预算变体重裁剪；compiled 直用更低）
            "hit_compile_ms": _stats(
                [item["compile_ms"] for item in items if item.get("source_cache_hit")]
            )
            if any(item.get("source_cache_hit") for item in items)
            else {},
            "rendered_tokens_mean": round(
                statistics.fmean(
                    [item["rendered_tokens"] for item in items],
                ),
                1,
            )
            if items
            else 0,
        }
    return summary


async def _run_scale(
    db: AsyncSession,
    scale: str,
    rounds: int,
    repeats: int,
) -> dict[str, Any]:
    fixture = await _setup_fixture(db, scale)
    indexing = await _run_indexing(db, fixture)

    runner = _Runner(db)
    recorder = _SegmentRecorder()
    attempts: list[dict[str, Any]] = []
    async with _segment_instrumentation(recorder):
        for round_index in range(rounds):
            attempts.append(
                await runner.attempt(
                    fixture,
                    scenario="rp_normal_fresh",
                    query=_query_for_round(round_index),
                    budget_tokens=16_000,
                    player=fixture.player_character,
                    recorder=recorder,
                )
            )
        requery = _query_for_round(0)
        for _ in range(repeats):
            attempts.append(
                await runner.attempt(
                    fixture,
                    scenario="agent_requery_same",
                    query=requery,
                    budget_tokens=AGENT_BUDGET,
                    player=fixture.player_character,
                    recorder=recorder,
                )
            )
        for suffix in ENSEMBLE_ACTOR_SUFFIXES:
            attempts.append(
                await runner.attempt(
                    fixture,
                    scenario="ensemble_actors",
                    query=_query_for_round(1) + suffix,
                    budget_tokens=ENSEMBLE_BUDGET,
                    player=fixture.player_character,
                    recorder=recorder,
                )
            )
        for budget in BUDGET_PAIR:
            attempts.append(
                await runner.attempt(
                    fixture,
                    scenario="budget_pair",
                    query=_query_for_round(2),
                    budget_tokens=budget,
                    player=fixture.player_character,
                    recorder=recorder,
                )
            )
        for round_index in range(2):
            attempts.append(
                await runner.attempt(
                    fixture,
                    scenario="reader_mode",
                    query=_query_for_round(round_index + 3),
                    budget_tokens=16_000,
                    player=fixture.player_reader,
                    recorder=recorder,
                )
            )

    invalid_reasons: list[str] = []
    if not indexing["has_embeddings_after_index"]:
        invalid_reasons.append(f"{scale}: 索引后无可用 embedding，检索未走真实向量链")
    if indexing["embedding_failed_count"]:
        invalid_reasons.append(f"{scale}: 索引阶段存在 embedding 失败")
    for attempt in attempts:
        if attempt["degraded"]:
            invalid_reasons.append(
                f"{scale}/attempt{attempt['attempt']}: 检索降级，不可作真实链样本"
            )
        if attempt["blockers"]:
            invalid_reasons.append(
                f"{scale}/attempt{attempt['attempt']}: 编译被阻断 {attempt['blockers']}"
            )

    return {
        "corpus": {
            "chapters": fixture.chapters,
            "manifest_entries": len(fixture.source_manifest),
            "references": len(fixture.reference_manifest),
            "last_chapter_chars": fixture.chapter_chars,
        },
        "indexing": indexing,
        "attempts": attempts,
        "summary": _summarize_attempts(attempts),
        "invalid_reasons": invalid_reasons,
    }


# ── CLI ──


async def _run(args: argparse.Namespace, sqlite_path: Path) -> int:
    database_url = _resolve_database_url(args.database_url, sqlite_path)
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    dialect = engine.dialect.name
    if dialect == "postgresql":
        await _assert_pg_schema_ready(engine)
    else:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    try:
        register_container_services()
        from core.config import get_settings

        if get_settings().embedding_provider != "bge_onnx":
            raise SystemExit(
                "测量要求 EMBEDDING_PROVIDER=bge_onnx（本地免费链）；"
                "远程 embedding 成本须在后续授权阶段单独实测。"
            )

        scales = [item.strip() for item in args.scales.split(",") if item.strip()]
        for scale in scales:
            if scale not in SCALE_CHAPTERS:
                raise SystemExit(f"未知规模档 {scale!r}，可选：{sorted(SCALE_CHAPTERS)}")

        report: dict[str, Any] = {
            "kind": REPORT_KIND,
            "spec": build_family_spec(),
            "spec_hash": spec_hash(build_family_spec()),
            "environment": _environment(database_url, dialect),
            "scales": {},
        }
        factory = async_sessionmaker(engine, expire_on_commit=False)
        for scale in scales:
            async with factory() as db:
                report["scales"][scale] = await _run_scale(
                    db, scale, args.rounds, args.repeats
                )

        invalid: list[str] = []
        for scale_data in report["scales"].values():
            invalid.extend(scale_data.pop("invalid_reasons"))
        report["invalid_reasons"] = invalid
        report["valid"] = not invalid
        report["environment"]["finished_at"] = datetime.now(UTC).isoformat()

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        _print_summary(report, output)
        return 0 if report["valid"] or args.allow_invalid else 2
    finally:
        from infrastructure.embedding.client import BgeEmbeddingClient

        await BgeEmbeddingClient.close_instance()
        await engine.dispose()


def _print_summary(report: dict[str, Any], output: Path) -> None:
    print(f"[rp-cost-baseline] spec_hash={report['spec_hash']}")
    print(
        f"[rp-cost-baseline] dialect={report['environment']['dialect']} "
        f"git={report['environment']['git_head']} → {output}"
    )
    for scale, data in report["scales"].items():
        indexing = data["indexing"]
        print(
            f"  [{scale}] chapters={indexing['chapters']} "
            f"chunks={indexing['chunks_created']} "
            f"index_wall={indexing['index_wall_ms_total']}ms"
        )
        for scenario, stats in data["summary"].items():
            compile_stats = stats["compile_ms"]
            embedding_stats = stats["embedding_ms"]
            print(
                f"    {scenario:<20} n={stats['attempts']} "
                f"compile mean/med/p95="
                f"{compile_stats.get('mean')}/{compile_stats.get('median')}/"
                f"{compile_stats.get('p95')}ms "
                f"embed_total={embedding_stats.get('total')}ms "
                f"tokens~{stats['rendered_tokens_mean']}"
            )
    if report["invalid_reasons"]:
        print(f"[rp-cost-baseline] INVALID（{len(report['invalid_reasons'])} 项）：")
        for reason in report["invalid_reasons"][:10]:
            print(f"  - {reason}")
    else:
        print("[rp-cost-baseline] valid=true")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.rp_cost_baseline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="执行测量并写出 JSON 报告")
    run_parser.add_argument("--scales", default="s,m", help="逗号分隔：s,m,l")
    run_parser.add_argument(
        "--rounds", type=int, default=DEFAULT_ROUNDS, help="普通 RP 新查询轮数"
    )
    run_parser.add_argument(
        "--repeats", type=int, default=DEFAULT_REPEATS, help="Agent 同查询重复次数"
    )
    run_parser.add_argument(
        "--database-url",
        default=None,
        help="缺省读 DATABASE_URL；再缺省用 SQLite 临时文件。PG 库名须含 e2e/baseline",
    )
    run_parser.add_argument(
        "--output",
        default="evals/artifacts/rp-cost-baseline/report.json",
    )
    run_parser.add_argument(
        "--allow-invalid",
        action="store_true",
        help="即使存在降级/阻断也写报告（诊断用，仍标记 invalid）",
    )

    subparsers.add_parser("describe", help="打印冻结样本族定义")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "describe":
        spec = build_family_spec()
        print(f"spec_hash={spec_hash(spec)}")
        print(json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    with tempfile.TemporaryDirectory(prefix="rp-cost-baseline-") as tmp_dir:
        sqlite_path = Path(tmp_dir) / "baseline.db"
        return asyncio.run(_run(args, sqlite_path))


if __name__ == "__main__":
    raise SystemExit(main())

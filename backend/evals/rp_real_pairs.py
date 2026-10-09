"""远景第一阶段 §7.4 真实成对阶段：RP 真实模型成对运行 harness。

复用 v4_live 的 Meter/一次性库模式与 rp_cost_baseline 的冻结样本族（种子
20261006），在一次性 e2e PG 库里走生产 story 链（create_journey →
send_message/regenerate/continue_from_node → TaskWorker 执行真实 LLM），按
§7.3 记录每次尝试的 token/缓存命中/费用，并做 §7.4 的输入布局成对与盲评。

预算与安全（计划 §7.4 + 账本规则）：
- 同一笔预算只用一份累计账本（USD 20 硬顶）；阶段帽 adaptation 3 / dev 9 /
  holdout 6，失败预留 2 不发放。
- 账本目录必须在仓库外私有目录；仓库内只进脱敏快照与结论。
- 源库只读（dev guimi 库仅取已验证 deepseek 凭据密文，密钥不落盘不打印）；
  目标库必须带 e2e 标记，成功后 DROP。
- 未知用量的请求按保留上界阻断后续付费调用；脱敏快照不得继续计费。

复跑（先冻结 dev/holdout 场景脚本，不许在 holdout 结果上调 Prompt）：
    cd backend && \
    set -a; source <主仓>/backend/.env; set +a; \
    uv run --python 3.13 --locked --extra dev -- \
        python -m evals.rp_real_pairs --stage adaptation \
        --ledger-dir ~/.ai_writing_private/rp-real-20261007
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

if __name__ == "__main__":
    # CLI 时在导入仓库模块前固定环境：冻结族用本地 BGE embedding（唯一免费路径），
    # 阻止本机 backend/.env 漂移进测量；被 pytest import 时不改进程环境。
    os.environ["EMBEDDING_PROVIDER"] = "bge_onnx"
    os.environ.setdefault("LLM_HEALTH_REQUIRED", "false")
    os.environ.setdefault("RERANKER_ENABLED", "false")
    os.environ.setdefault("RAG_QUERY_PLANNER_ENABLED", "false")

from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import Settings
from evals.rp_cost_baseline import (
    _QUERY_INPUTS,
    _QUERY_RECAP,
    _QUERY_RECENT,
    FAMILY_SEED,
    _run_indexing,
    _setup_fixture,
)
from evals.v4_live import FLASH_MODELS, Meter, save

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_DB_NAME = "ai_novel_agent_e2e_rp_pairs_20261007"
TOTAL_CAP_USD = 20.0
STAGE_CAPS_USD = {"adaptation": 3.0, "dev": 9.0, "holdout": 6.0}
STAGE_SCALE = {"adaptation": "s", "dev": "s", "holdout": "m"}
STAGE_TURNS = {"adaptation": 3, "dev": 6, "holdout": 6}

# 冻结场景脚本（与样本族同源；holdout 阶段前不得改动）。
OPENING_TEXT = "我在雾渡港的雾里醒来，靴筒里还折着那张抄着三个条件的旧纸条。"
BRANCH_INPUT = "沈砚没有去商会，而是趁着落雾去了灯塔下，等温若换岗。"
PACKET_MARKER = "以下是本轮准备资料"
TASK_WALL_LIMIT_SECONDS = 900


def init_ledger(path: Path) -> None:
    """一次性初始化累计账本；已存在则交由 Meter 校验。"""
    if path.exists():
        return
    save(
        path,
        {
            "cap_usd": TOTAL_CAP_USD,
            "provider": "deepseek",
            "model": "deepseek-flash",
            "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "pricing_verified_at": "2026-10-07",
            "budget": {
                "authorization": (
                    "docs/plans/2026-10-06-world-foundation-phase1.md §7.4；"
                    "用户 2026-10-07 授真实调用（暂不提 PR）"
                ),
                "stage_caps_usd": dict(STAGE_CAPS_USD),
                "failure_reserve_usd": 2.0,
            },
            "calls": [],
        },
    )


class _CacheObservingStream:
    """包住 SDK 流，把 DeepSeek usage 附带的缓存 token 存进 sink。"""

    def __init__(self, inner, sink: dict) -> None:
        self._inner = inner
        self._sink = sink

    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = await self._inner.__anext__()
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            extra = getattr(usage, "model_extra", None) or {}
            for field in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                value = extra.get(field) or getattr(usage, field, None)
                if isinstance(value, int):
                    self._sink[field] = value
        return chunk

    async def aclose(self):
        await self._inner.aclose()


class RPMeter(Meter):
    """累计账本（USD 20 总帽）之上叠加阶段帽与场景标签。"""

    def __init__(self, path: Path, stage: str) -> None:
        super().__init__(path)
        if self.ledger.get("cap_usd") != TOTAL_CAP_USD:
            raise RuntimeError(
                "RP authorization requires the original cumulative USD 20 cap"
            )
        self.stage = stage
        self.label = "unlabeled"

    def _stage_spent(self) -> float:
        return sum(
            call["cost_upper_usd"]
            for call in self.ledger["calls"]
            if call.get("stage") == self.stage
        )

    def _reserve(self, provider, request):
        stage_cap = STAGE_CAPS_USD[self.stage]
        encoded_len = len(
            json.dumps(request.model_dump(mode="json"), ensure_ascii=False).encode()
        )
        approx = ((encoded_len + 4096) * 0.30 + request.max_tokens * 1.20) / 1_000_000
        if self._stage_spent() + approx > stage_cap:
            raise RuntimeError(
                f"USD {stage_cap:g} stage cap reached before the next request"
            )
        call, started, reserve = super()._reserve(provider, request)
        call["stage"] = self.stage
        call["label"] = self.label
        save(self.path, self.ledger)
        return call, started, reserve

    def wrap_stream(self, original):
        meter = self

        async def metered(provider, request):
            call, started, reserve = meter._reserve(provider, request)
            # LLMStreamChunk 不透传 raw usage；缓存 token 只能在 SDK 传输层观测。
            completions = provider._client.chat.completions
            original_create = completions.create
            sink: dict = {}

            async def observing_create(**kwargs):
                stream = await original_create(**kwargs)
                return _CacheObservingStream(stream, sink)

            completions.create = observing_create
            try:
                stream = await original(provider, request)
            except BaseException as error:
                meter._failed(call, error)
                raise
            finally:
                completions.create = original_create

            async def observed():
                usage, finish = None, None
                content = []
                try:
                    async for chunk in stream:
                        if chunk.usage is not None:
                            usage = chunk.usage
                        if chunk.finish_reason is not None:
                            finish = chunk.finish_reason
                        content.append(chunk.content or "")
                        yield chunk
                    call["streamed"] = True
                    call["cache_usage_available"] = bool(sink)
                    meter._settle(
                        call,
                        started,
                        reserve,
                        SimpleNamespace(
                            usage=usage,
                            raw={"usage": dict(sink)},
                            model=request.model,
                            finish_reason=finish,
                            content="".join(content),
                        ),
                    )
                except BaseException as error:
                    meter._failed(call, error)
                    raise
                finally:
                    await stream.aclose()

            return observed()

        return metered


def _call_summary(call: dict) -> dict:
    usage = call.get("usage") or {}
    return {
        "sequence": call["sequence"],
        "label": call.get("label"),
        "streamed": bool(call.get("streamed")),
        "status": call["status"],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cache_usage_available": call.get("cache_usage_available", True),
        "cache_hit_tokens": call.get("cache_hit_tokens"),
        "price_band": call.get("price_band"),
        "cost_upper_usd": call.get("cost_upper_usd"),
        "estimated_cost_usd": call.get("estimated_cost_usd"),
    }


def _ledger_delta(meter: RPMeter, first_sequence: int) -> list[dict]:
    return [
        _call_summary(call)
        for call in meter.ledger["calls"]
        if call["sequence"] > first_sequence
    ]


def _streamed_cache_hit(record: dict) -> int | None:
    """取该尝试真实流式生成的供应商前缀缓存命中 token（不可得返回 None）。"""
    for call in record["metered_calls"]:
        if call["streamed"] and call["status"] == "settled":
            if not call["cache_usage_available"]:
                return None
            return call["cache_hit_tokens"] or 0
    return None


def _judge_messages(*, recap: str, user_input: str, first: str, second: str) -> list:
    from infrastructure.llm.schemas import LLMMessage

    return [
        LLMMessage(
            role="system",
            content=(
                "你是互不关联的两段小说续写的盲评裁判。只依据给定的局面约束与用户输入，"
                "从来源忠实度、规则遵守、连续性、人物质感四个维度比较两段续写。"
                "不知道的情节不要臆断；两段都失败时可以都判不合格。"
                '只输出 JSON：{"verdict":"first|second|tie|both_bad",'
                '"faithfulness":{"first":"pass|fail","second":"pass|fail"},'
                '"rules":{"first":"pass|fail","second":"pass|fail"},'
                '"continuity":{"first":"pass|fail","second":"pass|fail"},'
                '"voice":{"first":"pass|fail","second":"pass|fail"},'
                '"evidence":"一句话依据"}'
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                f"【局面约束（评审依据）】\n{recap}\n\n"
                f"【用户输入】\n{user_input}\n\n"
                f"【续写一】\n{first}\n\n"
                f"【续写二】\n{second}\n\n"
                "请输出 JSON 裁决。"
            ),
        ),
    ]


async def run_stage(stage: str, ledger_dir: Path, keep_db: bool) -> dict:
    from app.bootstrap import register_container_services
    from app.task_runtime import register_task_handlers
    from core.config import get_settings
    from core.errors import ConflictError, ValidationError
    from infrastructure.llm.providers import OpenAIProvider
    from infrastructure.llm.schemas import LLMCallRequest
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.worker import TaskWorker
    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
    from modules.account.settings_models import AccountLLMCredential, GlobalLLMDefaults
    from modules.interaction.models import (
        InteractionGenerationAttempt,
        InteractionSourceRevision,
    )
    from modules.interaction.schemas import (
        InteractionPlayerIdentity,
        JourneyCreateRequest,
        JourneySourceSetup,
    )
    from modules.interaction.services import InteractionService
    from modules.interaction.source_service import (
        InteractionSourceService,
        _fingerprint,
    )
    from modules.project.facade import open_project_llm_client
    from modules.project.models import Project
    from run_worker import (
        _guard_active_task_project_finalize,
        _require_active_task_project,
    )

    scale = STAGE_SCALE[stage]
    turns = STAGE_TURNS[stage]
    report: dict = {
        "kind": "rp_real_pairs.v1",
        "stage": stage,
        "scale": scale,
        "family_seed": FAMILY_SEED,
        "turns_planned": turns,
        "started_at": datetime.now(UTC).isoformat(),
        "database": E2E_DB_NAME,
    }

    def checkpoint(stage_name: str) -> None:
        report["stage_progress"] = stage_name
        save(ledger_dir / f"{stage}-report.json", report)

    # ── 源库只读取凭据（密文原样复制到一次性账户，运行时由应用解密） ──
    source_url = make_url(Settings().database_url)
    if "guimi" not in (source_url.database or ""):
        raise RuntimeError("Source DB must be the dev guimi database (read-only)")
    source = create_async_engine(source_url)
    source_sessions = async_sessionmaker(source, expire_on_commit=False)
    async with source_sessions() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        defaults = await db.scalar(
            select(GlobalLLMDefaults).where(
                GlobalLLMDefaults.owner_id == uuid.UUID(int=0)
            )
        )
        if defaults is None or defaults.provider_id != "deepseek":
            raise RuntimeError("Dev default provider is not deepseek")
        if defaults.model not in FLASH_MODELS:
            raise RuntimeError("Dev default model is not on the priced flash schedule")
        credential = await db.scalar(
            select(AccountLLMCredential).where(
                AccountLLMCredential.owner_id == defaults.owner_id,
                AccountLLMCredential.provider_id == defaults.provider_id,
            )
        )
        if not credential or not credential.verified_at:
            raise RuntimeError("The dev provider connection is not verified")
        profile = {
            key: getattr(defaults, key)
            for key in (
                "provider_id",
                "label",
                "base_url",
                "model",
                "timeout",
                "max_tokens",
                "temperature",
                "top_p",
                "extra",
                "creative_mode",
            )
        }
        secret = {
            key: getattr(credential, key)
            for key in (
                "provider_id",
                "encrypted_api_key",
                "key_fingerprint",
                "verified_at",
            )
        }
    await source.dispose()
    report["provider"] = profile["provider_id"]
    report["model"] = profile["model"]

    # ── 一次性 e2e 库（标记 + 迁移 + 应用组合根） ──
    admin = create_async_engine(
        source_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as connection:
        exists = await connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": E2E_DB_NAME}
        )
        if not exists:
            await connection.execute(text(f'CREATE DATABASE "{E2E_DB_NAME}"'))
    await admin.dispose()
    target_url = source_url.set(database=E2E_DB_NAME)
    os.environ.update(
        DATABASE_URL=target_url.render_as_string(hide_password=False),
        E2E_DATABASE_URL=target_url.render_as_string(hide_password=False),
        ASSISTANT_ENABLED="true",
        COLLABORATION_V2_ENABLED="true",
    )
    get_settings.cache_clear()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    register_container_services(ignore_existing=True)
    register_task_handlers()
    engine = create_async_engine(target_url, pool_size=6, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    # 本机 local/closed_test 鉴权下服务与 worker system scope 都解析到 bootstrap
    # 账户；全部所有权挂 bootstrap，保证 preflight/服务层同一 owner 口径。
    if get_settings().auth_mode not in {"local", "closed_test"}:
        raise RuntimeError("Harness requires local/closed_test auth bootstrap fallback")
    owner = BOOTSTRAP_ACCOUNT_ID
    run_suffix = uuid.uuid4().hex[:8]
    original_generate = OpenAIProvider.generate
    original_stream = OpenAIProvider.generate_stream
    meter = RPMeter(ledger_dir / "paid-calls.json", stage)
    dropped = False
    try:
        # fixture 自带 commit（含 bootstrap 账户行）；所有权补齐单独提交。
        async with sessions() as db:
            fixture = await _setup_fixture(db, scale)
        async with sessions.begin() as db:
            await db.execute(
                update(Project)
                .where(
                    Project.id.in_(
                        [uuid.UUID(fixture.source_id), uuid.UUID(fixture.consumer_id)]
                    )
                )
                .values(owner_id=owner)
            )
        async with sessions() as db:
            index_report = await _run_indexing(db, fixture)
        report["fixture"] = {
            "chapters": fixture.chapters,
            "chapter_chars": fixture.chapter_chars,
            "chunks_created": index_report["chunks_created"],
            "has_embeddings": index_report["has_embeddings_after_index"],
        }
        checkpoint("fixture_indexed")

        async with sessions.begin() as db:
            revision = InteractionSourceRevision(
                id=uuid.uuid4(),
                source_novel_id=uuid.UUID(fixture.source_id),
                owner_id=owner,
                version_number=1,
                title=f"RP 真实成对原作-{scale}",
                status="ready",
                source_manifest=fixture.source_manifest,
                anchor_manifest=[fixture.anchor],
                reference_manifest=fixture.reference_manifest,
                ambiguities=[],
                resolutions={},
                readiness_summary={"message": "冻结样本族直建（真实 manifest）"},
            )
            revision.manifest_hash = _fingerprint(revision.source_manifest)
            InteractionSourceService._set_fingerprint(revision)
            revision.ready_at = datetime.now(UTC)
            db.add(revision)
            db.add(AccountLLMCredential(owner_id=owner, **secret))
            db.add(GlobalLLMDefaults(owner_id=owner, **profile))
        report["revision_fingerprint"] = revision.fingerprint
        checkpoint("revision_seeded")

        OpenAIProvider.generate = meter.wrap(original_generate)
        OpenAIProvider.generate_stream = meter.wrap_stream(original_stream)
        worker = TaskWorker(
            db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
            task_preflight=_require_active_task_project,
            task_commit_guard=_guard_active_task_project_finalize,
            heartbeat_interval=30,
        )

        journey_novel_id: str | None = None

        async def execute(task_id: str) -> float:
            # create_journey 会为旅程建独立 interaction 项目；任务 novel_id
            # 挂旅程项目而非 fixture consumer，领取过滤按任务实际归属传参。
            started = time.monotonic()
            await asyncio.wait_for(
                worker.run_once(task_id=task_id, novel_id=journey_novel_id),
                timeout=TASK_WALL_LIMIT_SECONDS,
            )
            wall_ms = round((time.monotonic() - started) * 1000, 1)
            async with sessions() as check:
                row = await check.get(AsyncTask, uuid.UUID(task_id))
                if row is None or row.status != "done":
                    raise RuntimeError(
                        f"Worker task {task_id} did not finish cleanly: "
                        f"{row.status if row else 'missing'}"
                    )
            return wall_ms

        service = InteractionService()

        async def fetch_attempt(attempt_id: str) -> InteractionGenerationAttempt:
            async with sessions() as db:
                row = await db.get(InteractionGenerationAttempt, uuid.UUID(attempt_id))
                if row is None:
                    raise RuntimeError("Attempt row missing")
                return row

        attempts: list[dict] = []

        def attempt_record(label: str, attempt, wall_ms: float, calls: list[dict]):
            record = {
                "label": label,
                "attempt_id": str(attempt.id),
                "status": attempt.status,
                "request_kind": attempt.request_kind,
                "visible_chars": len(attempt.visible_text or ""),
                "visible_text": attempt.visible_text,
                "usage": dict(attempt.usage or {}),
                "worker_wall_ms": wall_ms,
                "metered_calls": calls,
            }
            attempts.append(record)
            return record

        # ── 开场：真实链创建 source 绑定旅程并生成第一段 ──
        meter.label = "opening"
        before = len(meter.ledger["calls"])
        async with sessions() as db:
            response = await service.create_journey(
                db,
                JourneyCreateRequest(
                    opening_text=OPENING_TEXT,
                    idempotency_key=f"rp-real-{stage}-opening-" + run_suffix,
                    source_setup=JourneySourceSetup(
                        source_revision_id=str(revision.id),
                        progress_anchor_key=fixture.anchor["anchor_key"],
                        player_identity=InteractionPlayerIdentity(
                            kind="source_character",
                            reference_key=fixture.player_character["reference_key"],
                        ),
                    ),
                ),
            )
            await db.commit()
        journey_id = response.journey.id
        journey_novel_id = response.journey.novel_id
        report["journey_id"] = journey_id
        report["journey_novel_id"] = journey_novel_id
        wall = await execute(response.attempt.task_id)
        opening = await fetch_attempt(response.attempt.id)
        attempt_record("opening", opening, wall, _ledger_delta(meter, before))
        checkpoint("opening_done")

        async def current_epoch() -> int:
            # worker 完成会推进 selection_epoch；每次变更前读最新值。
            async with sessions() as db:
                detail = await service.get_journey(db, journey_id)
                return detail.selection_epoch

        # ── 逐轮：send_message → TaskWorker；查询族即冻结场景脚本 ──
        for index in range(turns):
            label = f"turn-{index + 1}"
            content = (
                f"{_QUERY_RECAP}最近发展：{_QUERY_RECENT[index % len(_QUERY_RECENT)]}"
                if index == 0
                else _QUERY_INPUTS[index % len(_QUERY_INPUTS)]
            )
            meter.label = label
            before = len(meter.ledger["calls"])
            async with sessions() as db:
                mutation = await service.send_message(
                    db,
                    journey_id=journey_id,
                    content=content,
                    expected_selection_epoch=await current_epoch(),
                    idempotency_key=f"rp-real-{stage}-{label}-" + run_suffix,
                )
                await db.commit()
            wall = await execute(mutation.attempt.task_id)
            attempt = await fetch_attempt(mutation.attempt.id)
            attempt_record(label, attempt, wall, _ledger_delta(meter, before))
            checkpoint(f"{label}_done")

        # ── 重抽：对最后一轮 assistant 节点 regenerate ──
        meter.label = "regenerate"
        before = len(meter.ledger["calls"])
        async with sessions() as db:
            fresh = await service.get_journey(db, journey_id)
            assistants = [m for m in fresh.messages if m.role == "assistant"]
            if not assistants:
                raise RuntimeError("No assistant node to regenerate")
            mutation = await service.regenerate(
                db,
                journey_id=journey_id,
                assistant_node_id=assistants[-1].id,
                expected_selection_epoch=fresh.selection_epoch,
                idempotency_key=f"rp-real-{stage}-regen-" + run_suffix,
            )
            await db.commit()
        wall = await execute(mutation.attempt.task_id)
        attempt = await fetch_attempt(mutation.attempt.id)
        attempt_record("regenerate", attempt, wall, _ledger_delta(meter, before))
        checkpoint("regenerate_done")

        # ── 分支切换：从首个 assistant 节点另起 ──
        meter.label = "branch"
        before = len(meter.ledger["calls"])
        async with sessions() as db:
            detail = await service.get_journey(db, journey_id)
            first_assistant = next(
                message for message in detail.messages if message.role == "assistant"
            )
            mutation = await service.continue_from_node(
                db,
                journey_id=journey_id,
                node_id=first_assistant.id,
                content=BRANCH_INPUT,
                expected_selection_epoch=detail.selection_epoch,
                idempotency_key=f"rp-real-{stage}-branch-" + run_suffix,
            )
            await db.commit()
        wall = await execute(mutation.attempt.task_id)
        attempt = await fetch_attempt(mutation.attempt.id)
        attempt_record("branch", attempt, wall, _ledger_delta(meter, before))
        checkpoint("branch_done")

        # ── 失效：冻结 manifest 引用的锚点章源稿被移除后必须 fail-closed 且零付费 ──
        # （dev 实测：删非必需章（第 1 章）不影响编译——mandatory reads 只含锚点章
        # 与知识引用章；锚点章（末章）是必需读，删除应触发 缓存复验失败→全量路径
        # 源读失败→blockers fail-closed，且零付费调用。）
        before = len(meter.ledger["calls"])
        invalidation: dict = {"scenario": "frozen_draft_source_removed"}
        from modules.writing.models import WritingDraft

        async with sessions.begin() as db:
            anchor_draft_id = uuid.UUID(fixture.source_manifest[-1]["draft_id"])
            result = await db.execute(
                delete(WritingDraft).where(WritingDraft.id == anchor_draft_id)
            )
            invalidation["draft_rows_deleted"] = result.rowcount
        try:
            async with sessions() as db:
                mutation = await service.send_message(
                    db,
                    journey_id=journey_id,
                    content="沈砚回到账房，想再核对一遍交接当夜的记录。",
                    expected_selection_epoch=await current_epoch(),
                    idempotency_key=f"rp-real-{stage}-inval-" + run_suffix,
                )
                await db.commit()
            # 未在服务层拦截时，任务级 fail-closed 也必须零付费调用。
            try:
                await execute(mutation.attempt.task_id)
                invalidation["task_status"] = "done"
            except RuntimeError as error:
                invalidation["task_status"] = str(error)[-120:]
        except (ConflictError, ValidationError) as error:
            invalidation["service_blocked"] = f"{type(error).__name__}: {error}"[:200]
        invalidation["metered_calls_after"] = len(meter.ledger["calls"]) - before
        invalidation["passed"] = invalidation["metered_calls_after"] == 0 and (
            "service_blocked" in invalidation or invalidation.get("task_status") != "done"
        )
        report["invalidation"] = invalidation
        checkpoint("invalidation_done")

        # ── 输入布局成对：新（包在稳定前缀后）vs 旧（包插在 system 块内） ──
        layout_pair: dict = {"scenario": "packet_position"}
        story_calls = [
            call
            for call in meter.ledger["calls"]
            if call.get("stage") == stage
            and call.get("label") in {"turn-1", "turn-2"}
            and call.get("streamed")
        ]
        turn2_record = next(
            (record for record in attempts if record["label"] == "turn-2"), None
        )
        layout_pair["new_layout_cross_turn_cache_hit"] = (
            _streamed_cache_hit(turn2_record) if turn2_record else None
        )
        if len(story_calls) >= 2:
            base_new = LLMCallRequest.model_validate(story_calls[0]["request"])
            follow_new = LLMCallRequest.model_validate(story_calls[1]["request"])

            def to_old_layout(request: LLMCallRequest) -> LLMCallRequest:
                messages = list(request.messages)
                packet_index = next(
                    (
                        index
                        for index, message in enumerate(messages)
                        if PACKET_MARKER in (message.content or "")
                    ),
                    None,
                )
                if packet_index is None:
                    raise RuntimeError("Packet message not found in captured request")
                packet = messages.pop(packet_index)
                messages.insert(1, packet)
                return request.model_copy(update={"messages": messages})

            async with sessions() as db:
                async with open_project_llm_client(db, journey_novel_id) as client:

                    async def replay(label: str, request: LLMCallRequest) -> dict:
                        meter.label = label
                        first = len(meter.ledger["calls"])
                        response = await client.generate(request)
                        return {
                            "label": label,
                            "calls": _ledger_delta(meter, first),
                            "finish_reason": response.finish_reason,
                            "content_chars": len(response.content or ""),
                            "content": response.content,
                        }

                    old_base_run = await replay(
                        "layout-old-turn-1", to_old_layout(base_new)
                    )
                    old_follow_run = await replay(
                        "layout-old-turn-2", to_old_layout(follow_new)
                    )
                    new_follow_run = await replay("layout-new-turn-2", follow_new)

                    # 盲评：新 vs 旧布局各一次独立生成，匿名随机顺序。
                    order = ["new", "old"]
                    random.Random(FAMILY_SEED + turns).shuffle(order)
                    arms = {
                        "new": new_follow_run["content"],
                        "old": old_follow_run["content"],
                    }
                    meter.label = "layout-judge"
                    first = len(meter.ledger["calls"])
                    judge_response = await client.generate(
                        LLMCallRequest(
                            model=profile["model"],
                            messages=_judge_messages(
                                recap=_QUERY_RECAP,
                                user_input=_QUERY_INPUTS[1],
                                first=arms[order[0]],
                                second=arms[order[1]],
                            ),
                            max_tokens=12000,
                            temperature=0.2,
                            response_format={"type": "json_object"},
                        )
                    )
                    judge_calls = _ledger_delta(meter, first)
            layout_pair["old_layout_cross_request_cache_hit"] = next(
                (
                    call["cache_hit_tokens"]
                    for call in old_follow_run["calls"]
                    if call["cache_hit_tokens"] is not None
                ),
                None,
            )
            layout_pair["new_layout_replay_cache_hit"] = next(
                (
                    call["cache_hit_tokens"]
                    for call in new_follow_run["calls"]
                    if call["cache_hit_tokens"] is not None
                ),
                None,
            )
            layout_pair["judge_order"] = order
            layout_pair["judge_raw"] = judge_response.content
            layout_pair["old_layout_runs"] = [
                {key: value for key, value in run.items() if key != "content"}
                for run in (old_base_run, old_follow_run)
            ]
            layout_pair["new_layout_run"] = {
                key: value for key, value in new_follow_run.items() if key != "content"
            }
            layout_pair["judge_calls"] = judge_calls
        report["attempts"] = attempts
        report["layout_pair"] = layout_pair
        checkpoint("layout_pair_done")

        # ── 确定性质量门 ──
        leak_markers = [
            fixture.source_id,
            fixture.consumer_id,
            journey_id,
            journey_novel_id,
        ]
        report["quality_gates"] = {
            "attempt_statuses": {
                record["label"]: record["status"] for record in attempts
            },
            "no_failed_attempts": not any(
                record["status"] in {"failed", "cancelled", "stopped"}
                for record in attempts
            ),
            "no_project_marker_leak": not any(
                marker in (record["visible_text"] or "")
                for marker in leak_markers
                for record in attempts
            ),
            "invalidation_passed": invalidation["passed"],
        }
        report["cost"] = {
            "total_calls": len(meter.ledger["calls"]),
            "stage_spent_upper_usd": round(meter._stage_spent(), 4),
            "total_spent_upper_usd": round(
                sum(call["cost_upper_usd"] for call in meter.ledger["calls"]), 4
            ),
            "total_estimated_usd": round(
                sum(call.get("estimated_cost_usd", 0) for call in meter.ledger["calls"]),
                4,
            ),
        }
        checkpoint("finished")
    finally:
        OpenAIProvider.generate = original_generate
        OpenAIProvider.generate_stream = original_stream
        await engine.dispose()
        safe_to_drop = keep_db is False and report.get("stage_progress") in {
            "finished",
            "layout_pair_done",
            "invalidation_done",
            "branch_done",
        }
        if safe_to_drop:
            admin = create_async_engine(
                source_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
            )
            async with admin.connect() as connection:
                await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:name AND pid<>pg_backend_pid()"
                    ),
                    {"name": E2E_DB_NAME},
                )
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{E2E_DB_NAME}"'))
            await admin.dispose()
            dropped = True
        else:
            report["database_preserved"] = E2E_DB_NAME
        save(ledger_dir / f"{stage}-report.json", report)
    report["database_dropped"] = dropped
    save(ledger_dir / f"{stage}-report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=sorted(STAGE_CAPS_USD), required=True)
    parser.add_argument(
        "--ledger-dir",
        type=Path,
        required=True,
        help="仓库外私有账本目录（累计 USD 20 硬顶账本所在）",
    )
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args(argv)
    ledger_dir = args.ledger_dir.expanduser().resolve()
    if REPO_ROOT in ledger_dir.parents or ledger_dir == REPO_ROOT:
        raise SystemExit("Ledger dir must live outside the repository")
    ledger_dir.mkdir(parents=True, exist_ok=True)
    init_ledger(ledger_dir / "paid-calls.json")
    # 同一账本一次只允许一个进程消费预算。
    with (ledger_dir / "paid-calls.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = asyncio.run(run_stage(args.stage, ledger_dir, args.keep_db))
    summary = {
        "stage": report["stage"],
        "stage_progress": report.get("stage_progress"),
        "quality_gates": report.get("quality_gates"),
        "cost": report.get("cost"),
        "report": str(ledger_dir / f"{args.stage}-report.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

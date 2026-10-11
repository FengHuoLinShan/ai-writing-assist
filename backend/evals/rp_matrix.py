"""授权后运行：6开发族与3独立留出族各30轮，原路径/候选独立生产旅程。

请求/正文/评阅留在仓库外；沿用rp_real_pairs唯一累计账本。dev不合格时
停止进入holdout，保留原生产布局；不删除失败，不把局部布局收益当整体优化。
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

if __name__ == "__main__":
    os.environ.update(
        EMBEDDING_PROVIDER="bge_onnx",
        LLM_PROXY_URL="",
        RAG_PREWARM_ON_STARTUP="false",
        RAG_QUERY_PLANNER_ENABLED="false",
        RERANKER_ENABLED="false",
    )

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import Settings, get_settings
from evals.rp_cost_baseline import _run_indexing
from evals.rp_real_pairs import RPMeter, _call_summary, _judge_messages
from evals.rp_source_families import FAMILIES, setup_family
from evals.v4_live import FLASH_MODELS, save
from infrastructure.llm.schemas import LLMCallRequest

ARM = ContextVar("rp_eval_arm", default="old")
LABEL = ContextVar("rp_eval_label", default="matrix")
DB_NAME = "ai_novel_agent_e2e_rp_fullmatrix_20261007"
BASELINE_COMMIT = "85fb1c7be35ae687f949863d179f5fd63c53f3c0"
BASELINE_PATH = (
    "backend/modules/evidence/compilation/services/interaction_story_context.py"
)


class MatrixMeter(RPMeter):
    @property
    def label(self):
        return LABEL.get()

    @label.setter
    def label(self, value):
        LABEL.set(value)


class PairJudge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["first", "second", "tie", "both_bad"]
    faithfulness: dict[Literal["first", "second"], Literal["pass", "fail"]]
    rules: dict[Literal["first", "second"], Literal["pass", "fail"]]
    continuity: dict[Literal["first", "second"], Literal["pass", "fail"]]
    voice: dict[Literal["first", "second"], Literal["pass", "fail"]]
    evidence: str


def frozen_spec():
    from dataclasses import asdict

    spec = {
        "kind": "rp_matrix.v2",
        "families": [asdict(family) for family in FAMILIES],
        "turns": {"dev": 30, "holdout": 30},
        "judge_points": {"dev": [1, 5, 10, 20, 30], "holdout": [1, 5, 10, 20, 30]},
        "seed": 20261007,
        "scope": "full_context_pipeline_original_layout",
        "baseline_commit": BASELINE_COMMIT,
        "baseline_path": BASELINE_PATH,
        "concurrency": 3,
        "length_probe": {"turn": 30, "max_tokens": 128, "max_continuations": 1},
        "source_hashes": {
            family.key: [
                hashlib.sha256(family.chapter(i).encode()).hexdigest()
                for i in range(1, 38)
            ]
            for family in FAMILIES
        },
        "input_hashes": {
            family.key: [
                hashlib.sha256(family.input(i).encode()).hexdigest() for i in range(1, 31)
            ]
            for family in FAMILIES
        },
        "judge_ground_truth_hashes": {
            family.key: hashlib.sha256(family.judge_ground_truth.encode()).hexdigest()
            for family in FAMILIES
        },
        "rubric_hash": hashlib.sha256(
            json.dumps(
                [
                    item.model_dump(mode="json")
                    for item in _judge_messages(
                        recap="", user_input="", first="", second=""
                    )
                ],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "harness_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "candidate_hashes": {
            str(path.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for folder in ("modules", "infrastructure", "shared", "core", "app")
            for path in sorted(
                (Path(__file__).resolve().parents[1] / folder).rglob("*.py")
            )
            if "tests" not in path.parts
        },
    }
    spec["sha256"] = hashlib.sha256(
        json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return json.loads(json.dumps(spec, ensure_ascii=False))


def check_source_isolation():
    stages = {
        stage: {
            hashlib.sha256(family.chapter(i).encode()).hexdigest()
            for family in FAMILIES
            if family.stage == stage
            for i in range(1, 37)
        }
        for stage in ("dev", "holdout")
    }
    assert not stages["dev"] & stages["holdout"]
    assert len({family.key for family in FAMILIES}) == 9
    assert len({family.recap for family in FAMILIES}) == 9


def summarize_calls(calls):
    return {
        "calls": len(calls),
        "unknown_calls": sum(call["status"] != "settled" for call in calls),
        "estimated_usd": sum(call.get("estimated_cost_usd", 0) for call in calls),
        "upper_usd": sum(call["cost_upper_usd"] for call in calls),
        "prompt_tokens": sum(
            (call.get("usage") or {}).get("prompt_tokens", 0) for call in calls
        ),
        "completion_tokens": sum(
            (call.get("usage") or {}).get("completion_tokens", 0) for call in calls
        ),
        "cache_hit_tokens": sum(call.get("cache_hit_tokens", 0) or 0 for call in calls),
    }


def source_invalidation_result(attempt, paid_calls):
    return {
        "source_blocked": attempt.status == "failed"
        and attempt.error_kind == "source_context_blocked"
        and paid_calls == 0,
        "status": attempt.status,
        "error_kind": attempt.error_kind,
        "released_story": bool(attempt.visible_text),
        "paid_calls_after": paid_calls,
    }


def source_invalidation_draft_ids(manifest, cutoff_chapter):
    return [
        uuid.UUID(ref["draft_id"])
        for ref in manifest
        if 0 < int(ref["chapter_index"]) <= cutoff_chapter
    ]


async def run_matrix(directory: Path, keep_db: bool):
    from app.bootstrap import register_container_services
    from app.task_runtime import register_task_handlers
    from infrastructure.llm.providers import OpenAIProvider
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.worker import TaskWorker
    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
    from modules.account.models import Account
    from modules.account.settings_models import AccountLLMCredential, GlobalLLMDefaults
    from modules.evidence.compilation import facade as evidence_compilation
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
    from modules.interaction.source_service import InteractionSourceService, _fingerprint
    from modules.project.facade import open_project_llm_client
    from modules.writing.models import WritingDraft
    from run_worker import (
        _guard_active_task_project_finalize,
        _require_active_task_project,
    )

    check_source_isolation()
    spec = frozen_spec()
    spec_path = directory / "matrix-full-frozen-spec.json"
    if spec_path.exists() and json.loads(spec_path.read_text()) != spec:
        raise RuntimeError("Frozen spec changed; no paid holdout rerun is permitted")
    save(spec_path, spec)
    report = {
        "spec_hash": spec["sha256"],
        "scope": spec["scope"],
        "stages": {},
        "human_validated": False,
    }
    report_path = directory / "matrix-full-report.json"
    run_label = f"fullmatrix:{uuid.uuid4().hex[:8]}:"
    report["run_label"] = run_label
    holdout_use = directory / "matrix-full-holdout-used.json"
    if holdout_use.exists() or (
        report_path.exists()
        and "holdout" in json.loads(report_path.read_text()).get("stages", {})
    ):
        raise RuntimeError(
            "These holdout families were already consumed; do not rerun or tune on them"
        )

    def checkpoint():
        save(report_path, report)

    source_url = make_url(Settings().database_url)
    if "guimi" not in (source_url.database or ""):
        raise RuntimeError("Credential source must be the protected Guimi DB, read-only")
    source = create_async_engine(source_url)
    async with async_sessionmaker(source)() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        defaults = await db.scalar(
            select(GlobalLLMDefaults).where(
                GlobalLLMDefaults.owner_id == BOOTSTRAP_ACCOUNT_ID
            )
        )
        credential = await db.scalar(
            select(AccountLLMCredential).where(
                AccountLLMCredential.owner_id == BOOTSTRAP_ACCOUNT_ID,
                AccountLLMCredential.provider_id == "deepseek",
            )
        )
        if (
            not defaults
            or defaults.provider_id != "deepseek"
            or defaults.model not in FLASH_MODELS
            or not credential
            or not credential.verified_at
        ):
            raise RuntimeError("Verified priced owner connection is unavailable")
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
    admin = create_async_engine(
        source_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as connection:
        if await connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": DB_NAME}
        ):
            raise RuntimeError(
                "Matrix database exists; preserve it and investigate before rerun"
            )
        await connection.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    await admin.dispose()
    target = source_url.set(database=DB_NAME)
    os.environ.update(
        DATABASE_URL=target.render_as_string(hide_password=False),
        E2E_DATABASE_URL=target.render_as_string(hide_password=False),
        ASSISTANT_ENABLED="true",
        INTERACTION_AGENT_ENABLED="true",
    )
    get_settings.cache_clear()
    if get_settings().auth_mode not in {"local", "closed_test"}:
        raise RuntimeError("Matrix requires local test auth")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    register_container_services(ignore_existing=True)
    register_task_handlers()
    engine = create_async_engine(target, pool_size=12, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(
                Account(
                    id=BOOTSTRAP_ACCOUNT_ID, status="active", support_code="U-RP-MATRIX"
                )
            )
        db.add(AccountLLMCredential(owner_id=BOOTSTRAP_ACCOUNT_ID, **secret))
        db.add(GlobalLLMDefaults(owner_id=BOOTSTRAP_ACCOUNT_ID, **profile))
    worker = TaskWorker(
        db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
        task_preflight=_require_active_task_project,
        task_commit_guard=_guard_active_task_project_finalize,
        heartbeat_interval=30,
    )
    service = InteractionService()
    original_service = evidence_compilation._interaction_story_context_service
    # 从固定Git对象加载可信基线代码；不执行模型输出，原检索默认参数仍走旧ILIKE路径。
    baseline_source = subprocess.check_output(
        ["git", "show", f"{BASELINE_COMMIT}:{BASELINE_PATH}"]
    )
    baseline_file = directory / "baseline-compiler-85fb.py"
    baseline_file.write_bytes(baseline_source)
    loader_spec = importlib.util.spec_from_file_location(
        "rp_baseline_85fb", baseline_file
    )
    baseline_module = importlib.util.module_from_spec(loader_spec)
    loader_spec.loader.exec_module(baseline_module)
    retrieval_source = subprocess.check_output(
        [
            "git",
            "show",
            f"{BASELINE_COMMIT}:backend/modules/evidence/indexing/retrieval.py",
        ]
    )
    retrieval_file = directory / "baseline-retrieval-85fb.py"
    retrieval_file.write_bytes(retrieval_source)
    retrieval_spec = importlib.util.spec_from_file_location(
        "rp_baseline_retrieval_85fb", retrieval_file
    )
    retrieval_module = importlib.util.module_from_spec(retrieval_spec)
    retrieval_spec.loader.exec_module(retrieval_module)
    baseline_retriever = retrieval_module.RetrievalOrchestrator()

    async def baseline_retrieve(db, novel_id, query, **kwargs):
        if kwargs.get("source_manifest") is not None:
            kwargs["source_manifest"] = {
                uuid.UUID(key): value for key, value in kwargs["source_manifest"].items()
            }
        return await baseline_retriever.retrieve(db, uuid.UUID(novel_id), query, **kwargs)

    baseline_module.retrieve = baseline_retrieve
    report["baseline_retrieval_sha256"] = hashlib.sha256(retrieval_source).hexdigest()
    baseline_service = baseline_module.InteractionStoryContextService()
    report["baseline_compiler_sha256"] = hashlib.sha256(baseline_source).hexdigest()
    original_generate, original_stream = (
        OpenAIProvider.generate,
        OpenAIProvider.generate_stream,
    )
    families_by_source = {}
    context_checks = []
    report["context_checks"] = context_checks

    async def compile_arm(db, **kwargs):
        if ARM.get() == "old":
            kwargs.pop("prompt_name", None)
            packet = await baseline_service.compile(db, **kwargs)
        else:
            packet = await original_service.compile(db, **kwargs)
        family = families_by_source[kwargs["source_novel_id"]]
        label = LABEL.get()
        chapters = {
            int(ref["chapter_index"])
            for ref in packet.source_refs
            if ref.get("chapter_index")
        }
        group = 2
        if ":turn-" in label:
            turn = int(re.search(r":turn-(\d+)", label).group(1))
            group = {1: 2, 2: 3, 3: 7, 4: 10, 5: 9, 0: 2}[turn % 6]
        # 身份的必需证明由编译器blockers约束；不强制使用某章的同名提及。
        missing = sorted({group} - chapters) if not packet.blockers else []
        leaked = (
            family.secret_canary in packet.rendered_context
            or family.future_canary in packet.rendered_context
            or 5 in chapters
            or 37 in chapters
        )
        context_checks.append(
            {
                "label": label,
                "arm": ARM.get(),
                "source_chapters": sorted(chapters),
                "missing_groups": missing,
                "source_blocked": bool(packet.blockers),
                "leaked": leaked,
                "passed": not missing and not leaked,
            }
        )
        if leaked or (missing and ARM.get() == "new"):
            raise RuntimeError(
                "Frozen key-evidence or knowledge-boundary gate failed before generation"
            )
        return packet

    evidence_compilation._interaction_story_context_service = SimpleNamespace(
        compile=compile_arm
    )
    semaphore = asyncio.Semaphore(3)
    finished = False
    try:
        for stage in ("dev", "holdout"):
            if stage == "holdout":
                with holdout_use.open("x") as receipt:
                    json.dump(
                        {
                            "spec_hash": spec["sha256"],
                            "holdout_families": [
                                f.key for f in FAMILIES if f.stage == "holdout"
                            ],
                        },
                        receipt,
                    )
            meter = MatrixMeter(directory / "paid-calls.json", stage)
            OpenAIProvider.generate, OpenAIProvider.generate_stream = (
                meter.wrap(original_generate),
                meter.wrap_stream(original_stream),
            )
            metered_stream = OpenAIProvider.generate_stream

            async def length_probe_stream(provider, request):
                if LABEL.get().endswith(":turn-30"):
                    request = request.model_copy(
                        update={"max_tokens": spec["length_probe"]["max_tokens"]}
                    )
                return await metered_stream(provider, request)

            OpenAIProvider.generate_stream = length_probe_stream
            stage_report = {"families": {}, "passed": False}
            report["stages"][stage] = stage_report
            fixtures = {}
            for family in (f for f in FAMILIES if f.stage == stage):
                async with sessions() as db:
                    fixture = await setup_family(db, family)
                async with sessions() as db:
                    indexing = await _run_indexing(db, fixture)
                    if not indexing["has_embeddings_after_index"]:
                        raise RuntimeError("Source indexing degraded")
                async with sessions.begin() as db:
                    revision = InteractionSourceRevision(
                        id=uuid.uuid4(),
                        source_novel_id=uuid.UUID(fixture.source_id),
                        owner_id=BOOTSTRAP_ACCOUNT_ID,
                        version_number=1,
                        title=family.key,
                        status="ready",
                        source_manifest=fixture.source_manifest,
                        anchor_manifest=[fixture.anchor],
                        reference_manifest=fixture.reference_manifest,
                        ambiguities=[],
                        resolutions={},
                        readiness_summary={"message": "冻结合成来源"},
                    )
                    revision.manifest_hash = _fingerprint(revision.source_manifest)
                    InteractionSourceService._set_fingerprint(revision)
                    db.add(revision)
                fixtures[family.key] = (fixture, revision)
                families_by_source[fixture.source_id] = family
                stage_report["families"][family.key] = {
                    "source_hashes": [
                        item["source_hash"] for item in fixture.source_manifest
                    ],
                    "arms": {},
                    "judges": [],
                }
                checkpoint()

            async def run_arm(family, arm):
                async with semaphore:
                    ARM.set(arm)
                    fixture, revision = fixtures[family.key]
                    arm_report = {"attempts": [], "journey_id": None}
                    stage_report["families"][family.key]["arms"][arm] = arm_report
                    journey_id, journey_novel_id = None, None

                    async def execute(mutation, label, *, allow_continue=True):
                        LABEL.set(f"{run_label}{family.key}:{arm}:{label}")
                        first = len(meter.ledger["calls"])
                        started = time.monotonic()
                        await asyncio.wait_for(
                            worker.run_once(
                                task_id=mutation.attempt.task_id,
                                novel_id=journey_novel_id,
                            ),
                            timeout=900,
                        )
                        async with sessions() as check:
                            task = await check.get(
                                AsyncTask, uuid.UUID(mutation.attempt.task_id)
                            )
                            attempt = await check.get(
                                InteractionGenerationAttempt,
                                uuid.UUID(mutation.attempt.id),
                            )
                            item = {
                                "label": label,
                                "attempt_id": str(attempt.id),
                                "task_id": str(task.id),
                                "result_node_id": str(attempt.result_node_id)
                                if attempt.result_node_id
                                else None,
                                "task_status": task.status,
                                "status": attempt.status,
                                "text": attempt.visible_text,
                                "wall_ms": round((time.monotonic() - started) * 1000, 1),
                                "calls": [
                                    _call_summary(call)
                                    for call in meter.ledger["calls"][first:]
                                    if call.get("label") == LABEL.get()
                                ],
                            }
                        markers = [
                            fixture.source_id,
                            fixture.consumer_id,
                            journey_id,
                            journey_novel_id,
                        ]
                        item["no_project_marker_leak"] = not any(
                            marker in (item["text"] or "") for marker in markers
                        )
                        item["no_secret_or_future_leak"] = not any(
                            marker in (item["text"] or "")
                            for marker in (family.secret_canary, family.future_canary)
                        )
                        arm_report["attempts"].append(item)
                        checkpoint()
                        if (
                            item["status"] not in {"completed", "awaiting_continue"}
                            or not item["no_project_marker_leak"]
                            or not item["no_secret_or_future_leak"]
                        ):
                            raise RuntimeError(
                                "Paid attempt did not complete; no automatic retry"
                            )
                        if item["status"] == "awaiting_continue":
                            if not allow_continue:
                                raise RuntimeError(
                                    "Continuation did not finish; preserve partial output"
                                )
                            async with sessions() as db:
                                detail = await service.get_journey(db, journey_id)
                                continuation = await service.continue_attempt(
                                    db,
                                    journey_id=journey_id,
                                    attempt_id=mutation.attempt.id,
                                    expected_selection_epoch=detail.selection_epoch,
                                    idempotency_key=f"{run_label}{family.key}:{arm}:{label}:continue",
                                )
                                await db.commit()
                            completed = await execute(
                                continuation, label + "-continued", allow_continue=False
                            )
                            item["first_segment_text"] = item["text"]
                            item["text"], item["status"] = (
                                completed["text"],
                                completed["status"],
                            )
                            item["continued"] = True
                            item["wall_ms"] += completed["wall_ms"]
                            checkpoint()
                        return item

                    LABEL.set(f"{run_label}{family.key}:{arm}:opening")
                    async with sessions() as db:
                        opening = await service.create_journey(
                            db,
                            JourneyCreateRequest(
                                opening_text=f"我回到{family.place}，准备核对{family.item}的交接。",
                                idempotency_key=f"{run_label}{family.key}:{arm}",
                                source_setup=JourneySourceSetup(
                                    source_revision_id=str(revision.id),
                                    progress_anchor_key=fixture.anchor["anchor_key"],
                                    player_identity=InteractionPlayerIdentity(
                                        kind="source_character",
                                        reference_key=fixture.player_character[
                                            "reference_key"
                                        ],
                                    ),
                                ),
                            ),
                        )
                        await db.commit()
                    journey_id, journey_novel_id = (
                        opening.journey.id,
                        opening.journey.novel_id,
                    )
                    arm_report.update(journey_id=journey_id, novel_id=journey_novel_id)
                    await execute(opening, "opening")
                    for turn in range(1, spec["turns"][stage] + 1):
                        async with sessions() as db:
                            detail = await service.get_journey(db, journey_id)
                            mutation = await service.send_message(
                                db,
                                journey_id=journey_id,
                                content=family.input(turn),
                                expected_selection_epoch=detail.selection_epoch,
                                idempotency_key=f"{run_label}{family.key}:{arm}:{turn}",
                            )
                            await db.commit()
                        await execute(mutation, f"turn-{turn}")
                    async with sessions() as db:
                        detail = await service.get_journey(db, journey_id)
                        assistants = [
                            message
                            for message in detail.messages
                            if message.role == "assistant"
                        ]
                        mutation = await service.regenerate(
                            db,
                            journey_id=journey_id,
                            assistant_node_id=assistants[-1].id,
                            expected_selection_epoch=detail.selection_epoch,
                            idempotency_key=f"{run_label}{family.key}:{arm}:regenerate",
                        )
                        await db.commit()
                    await execute(mutation, "regenerate")
                    async with sessions() as db:
                        detail = await service.get_journey(db, journey_id)
                        mutation = await service.continue_from_node(
                            db,
                            journey_id=journey_id,
                            node_id=assistants[0].id,
                            content=f"我暂不索要{family.item}，先去核对那次交接的见证。",
                            expected_selection_epoch=detail.selection_epoch,
                            idempotency_key=f"{run_label}{family.key}:{arm}:branch",
                        )
                        await db.commit()
                    await execute(mutation, "branch")

            jobs = [
                (family, arm)
                for family in FAMILIES
                if family.stage == stage
                for arm in ("old", "new")
            ]
            random.Random(20261007).shuffle(jobs)
            results = await asyncio.gather(
                *(run_arm(family, arm) for family, arm in jobs), return_exceptions=True
            )
            errors = [
                type(result).__name__
                for result in results
                if isinstance(result, BaseException)
            ]
            if errors:
                stage_report["execution_errors"] = errors
                checkpoint()
                break
            for family in (f for f in FAMILIES if f.stage == stage):
                family_report = stage_report["families"][family.key]
                for point in spec["judge_points"][stage]:
                    records = {
                        arm: next(
                            item
                            for item in family_report["arms"][arm]["attempts"]
                            if item["label"] == f"turn-{point}"
                        )
                        for arm in ("old", "new")
                    }
                    order = ["old", "new"]
                    random.Random(20261007 + point).shuffle(order)
                    LABEL.set(f"{run_label}{family.key}:judge:{point}")
                    async with sessions() as db:
                        async with open_project_llm_client(
                            db, family_report["arms"]["old"]["novel_id"]
                        ) as client:
                            answer = await client.generate(
                                LLMCallRequest(
                                    model=profile["model"],
                                    messages=_judge_messages(
                                        recap=family.judge_ground_truth
                                        + "\n续写一之前的历史："
                                        + "\n".join(
                                            item["text"]
                                            for item in family_report["arms"][order[0]][
                                                "attempts"
                                            ]
                                            if item["label"] == "opening"
                                            or item["label"]
                                            in {f"turn-{i}" for i in range(1, point)}
                                        )
                                        + "\n续写二之前的历史："
                                        + "\n".join(
                                            item["text"]
                                            for item in family_report["arms"][order[1]][
                                                "attempts"
                                            ]
                                            if item["label"] == "opening"
                                            or item["label"]
                                            in {f"turn-{i}" for i in range(1, point)}
                                        ),
                                        user_input=family.input(point),
                                        first=records[order[0]]["text"],
                                        second=records[order[1]]["text"],
                                    ),
                                    max_tokens=12000,
                                    temperature=0.2,
                                    response_format={"type": "json_object"},
                                ),
                                transport_retries=False,
                            )
                    judge = PairJudge.model_validate_json(answer.content)
                    grades = {
                        arm: [
                            getattr(judge, dimension)[
                                "first" if order[0] == arm else "second"
                            ]
                            for dimension in (
                                "faithfulness",
                                "rules",
                                "continuity",
                                "voice",
                            )
                        ]
                        for arm in order
                    }
                    family_report["judges"].append(
                        {
                            "turn": point,
                            "order": order,
                            "grades": grades,
                            "evidence": judge.evidence,
                            "new_passed": grades["new"] == ["pass"] * 4,
                        }
                    )
                    checkpoint()
                # 两臂同一冻结必需源失效；失败关闭与付费次数分开记录。
                fixture, _ = fixtures[family.key]
                async with sessions.begin() as db:
                    await db.execute(
                        delete(WritingDraft).where(
                            WritingDraft.id.in_(
                                source_invalidation_draft_ids(
                                    fixture.source_manifest,
                                    int(fixture.anchor["chapter_index"]),
                                )
                            ),
                            WritingDraft.novel_id == uuid.UUID(fixture.source_id),
                        )
                    )
                for arm in ("old", "new"):
                    ARM.set(arm)
                    LABEL.set(f"{run_label}{family.key}:{arm}:invalidation")
                    first = len(meter.ledger["calls"])
                    arm_report = family_report["arms"][arm]
                    async with sessions() as db:
                        detail = await service.get_journey(db, arm_report["journey_id"])
                        mutation = await service.send_message(
                            db,
                            journey_id=arm_report["journey_id"],
                            content="我再核对冻结起点的来源记录。",
                            expected_selection_epoch=detail.selection_epoch,
                            idempotency_key=f"{run_label}{family.key}:{arm}:invalidation",
                        )
                        await db.commit()
                    await worker.run_once(
                        task_id=mutation.attempt.task_id, novel_id=arm_report["novel_id"]
                    )
                    async with sessions() as db:
                        attempt = await db.get(
                            InteractionGenerationAttempt, uuid.UUID(mutation.attempt.id)
                        )
                        arm_report["invalidation"] = source_invalidation_result(
                            attempt, len(meter.ledger["calls"]) - first
                        )
                    checkpoint()
            stage_report["quality_passed"] = all(
                judge["new_passed"]
                for family in stage_report["families"].values()
                for judge in family["judges"]
            ) and all(
                not arm["invalidation"]["released_story"]
                and arm["invalidation"]["source_blocked"]
                for family in stage_report["families"].values()
                for arm in family["arms"].values()
            )
            stage_report["quality_passed"] = stage_report["quality_passed"] and all(
                item["passed"]
                for item in context_checks
                if item["arm"] == "new"
                and any(
                    item["label"].startswith(run_label + f.key + ":")
                    for f in FAMILIES
                    if f.stage == stage
                )
            )
            stage_report["continuation_passed"] = all(
                any(
                    item["label"] == "turn-30" and item.get("continued")
                    for item in arm["attempts"]
                )
                for family in stage_report["families"].values()
                for arm in family["arms"].values()
            )
            stage_report["quality_passed"] &= stage_report["continuation_passed"]
            stage_calls = [
                call
                for call in meter.ledger["calls"]
                if call.get("stage") == stage
                and str(call.get("label", "")).startswith(run_label)
            ]
            stage_report["cost_by_arm"] = {
                arm: summarize_calls(
                    [call for call in stage_calls if f":{arm}:" in call.get("label", "")]
                )
                for arm in ("old", "new")
            }
            stage_report["judge_cost"] = summarize_calls(
                [call for call in stage_calls if ":judge:" in call.get("label", "")]
            )
            old_cost, new_cost = (
                stage_report["cost_by_arm"][arm] for arm in ("old", "new")
            )
            stage_report["cost_passed"] = (
                not old_cost["unknown_calls"]
                and not new_cost["unknown_calls"]
                and new_cost["estimated_usd"] < old_cost["estimated_usd"]
            )
            stage_report["passed"] = (
                stage_report["quality_passed"] and stage_report["cost_passed"]
            )
            checkpoint()
            if not stage_report["passed"]:
                report["holdout_not_run_reason"] = (
                    "development_quality_gate_failed"
                    if not stage_report["quality_passed"]
                    else "development_cost_gate_failed"
                )
                break
        finished = "holdout" in report["stages"] and all(
            stage["passed"] for stage in report["stages"].values()
        )
    finally:
        evidence_compilation._interaction_story_context_service = original_service
        OpenAIProvider.generate, OpenAIProvider.generate_stream = (
            original_generate,
            original_stream,
        )
        await engine.dispose()
        report["production_layout"] = "original"
        ledger = json.loads((directory / "paid-calls.json").read_text())
        report["cost"] = {
            "cumulative_calls": len(ledger["calls"]),
            "upper_usd": sum(call["cost_upper_usd"] for call in ledger["calls"]),
            "estimated_usd": sum(
                call.get("estimated_cost_usd", 0) for call in ledger["calls"]
            ),
        }
        report["database_preserved"] = DB_NAME
        checkpoint()
        if finished and not keep_db:
            admin = create_async_engine(
                source_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
            )
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{DB_NAME}"'))
            await admin.dispose()
            report["database_preserved"] = None
            checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args()
    directory = args.ledger_dir.expanduser().resolve()
    if (
        Path(__file__).resolve().parents[2] in directory.parents
        or not (directory / "paid-calls.json").exists()
    ):
        raise SystemExit(
            "Use the existing private cumulative ledger outside this repository"
        )
    with (directory / "paid-calls.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = asyncio.run(run_matrix(directory, args.keep_db))
    print(
        json.dumps(
            {
                "passed": all(stage["passed"] for stage in report["stages"].values())
                and "holdout" in report["stages"],
                "cost": report["cost"],
                "report": str(directory / "matrix-full-report.json"),
            },
            ensure_ascii=False,
        )
    )
    return (
        0
        if "holdout" in report["stages"] and report["stages"]["holdout"]["passed"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())

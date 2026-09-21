"""演化长书规模验证 harness（V4 E09 / 计划 §9 退出标准）。

在**专用空库**上把真实叙事语料（默认 `synthetic_ten_chapters.txt`，含
回归人物林舟/柳青/星盘/钥匙）按章建成真实 Writing 草稿，再以 shadow run
走真实任务 handler（`evolution_scene_step`）逐 Scene 推进，验证计划退出
标准的可审计子集：

- 链完整性：N 个回执按序成链，committed_prefix 单调推进；
- 前序状态注入：后序 Scene 的冻结负载实际携带前序观察摘要（T07）；
- 预算精确：预留恰等于 Scene 数，幂等重跑不再扣减；
- 影子隔离：不写任何正式 MemoryEvent；
- 屏障顺序：跳场被拒；重跑同 Scene 幂等（recovered）；
- 失效关闭：修改章节原文后，旧文本的后续步被 source_changed 拒绝；
- （--sampler real）真实模型子集：schema 化观察、逐字引用、提及有据、
  usage 计量进入回执。

用法（专用库，勿指向共享/生产库）：

    python -m tools.evolution_scale_harness \
        --database-url postgresql+asyncpg://user:pass@host:5432/evoscale \
        --create-schema --sampler deterministic

真实模型（另行授权后；Key 经账户连接种入，业务代码不经环境取凭据）：

    DEEPSEEK_API_KEY=... python -m tools.evolution_scale_harness \
        --database-url ... --sampler real \
        --seed-provider-key-env DEEPSEEK_API_KEY

结果输出 Markdown 报告到 stdout；``--json-path`` 另存机器可读结果。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

RECURRING_CAST = ("林舟", "柳青", "星盘", "钥匙", "青岚城", "白石城", "潮汐")
RUN_KEY = "e09-shadow-chain"


class HarnessError(Exception):
    """退出标准验证失败。"""


@dataclass
class HarnessReport:
    """E09 规模验证的可审计结果。"""

    sampler: str
    chapters: int = 0
    scenes_run: int = 0
    budget_total: int = 0
    budget_remaining_after_chain: int | None = None
    budget_remaining_after_rerun: int | None = None
    memory_events_written: int | None = None
    prior_state_injected_scenes: list[int] = field(default_factory=list)
    barrier_skip_rejected: bool | None = None
    rerun_same_attempt: bool | None = None
    stale_source_rejected: bool | None = None
    observation_count: int = 0
    quote_verbatim: bool | None = None
    mention_grounded: bool | None = None
    usage_recorded: bool | None = None
    wall_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


class GroundedDeterministicSampler:
    """有据采样器：观察、引用与提及全部来自本章真实文本。

    提及只报确实出现在正文中的回归人物/物件名——同一名跨 Scene 重复
    出现，用于验证观察积累不因同名重复建身份（E02/E09 退出标准）。
    """

    def __init__(self, chapter_texts: dict[int, str]) -> None:
        self._texts = chapter_texts

    async def sample(
        self, *, scene_text: str, input_manifest: dict[str, Any]
    ) -> dict[str, Any]:
        scene_index = int(input_manifest.get("scene_index", 0))
        text = self._texts.get(scene_index, scene_text)
        sentences = [s.strip() for s in text.replace("\n", "。").split("。") if s.strip()]
        quote = next((s for s in sentences if 8 <= len(s) <= 120), text[:80])
        mentioned = [name for name in RECURRING_CAST if name in text]
        return {
            "observations": [
                {
                    "predicate": f"第{scene_index + 1}章：{quote[:60]}",
                    "modality": "event_observed",
                    "quote": quote,
                    "start_offset": max(text.find(quote), 0),
                    "end_offset": max(text.find(quote), 0) + len(quote),
                    "mentions": [
                        {"surface": name, "entity_type": "character"}
                        for name in mentioned[:4]
                    ],
                }
            ],
            "scene_events": [],
            "unresolved_parts": [],
        }


def _task(request: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(meta=dict(request), novel_id=request["novel_id"])


def _step_request(
    novel_id: str,
    scene_ids: list[str],
    texts: list[str],
    index: int,
    *,
    provider: str,
    budget_total: int,
    chapter_index: int | None = None,
    scene_text: str | None = None,
    scene_index: int | None = None,
) -> dict[str, Any]:
    return {
        "novel_id": novel_id,
        "run_key": RUN_KEY,
        "scene_index": index if scene_index is None else scene_index,
        "scene_text": (
            texts[min(index, len(texts) - 1)] if scene_text is None else scene_text
        ),
        "scene_id": scene_ids[min(index, len(scene_ids) - 1)],
        "chapter_index": (index + 1) if chapter_index is None else chapter_index,
        "budget_total": budget_total,
        "execution_mode": "shadow",
        "sampler_provider": provider,
    }


def _chapter_text(chapter: dict[str, str]) -> str:
    return f"{chapter.get('title', '')}。{chapter.get('content', '')}"


async def _load_chapters(corpus: str, repeat: int) -> list[dict[str, str]]:
    if corpus != "ten-chapters":
        raise HarnessError(f"unknown corpus {corpus!r}")
    path = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "synthetic_ten_chapters.txt"
    )
    from modules.imports.parsers import parse_txt

    chapters = parse_txt(path.read_bytes())
    if not chapters:
        raise HarnessError("ten-chapters fixture parsed to zero chapters")
    if repeat <= 1:
        return chapters
    repeated: list[dict[str, str]] = []
    for cycle in range(repeat):
        for chapter in chapters:
            repeated.append(
                {
                    "title": f"{chapter.get('title', '')}·{cycle + 1}",
                    "content": f"（第{cycle + 1}轮誊写）{chapter.get('content', '')}",
                }
            )
    return repeated


async def run_harness(args: argparse.Namespace) -> HarnessReport:
    from app.bootstrap import _register_orm_models
    from core.base import Base

    _register_orm_models()
    engine = create_async_engine(args.database_url, pool_size=4, max_overflow=0)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    if args.create_schema:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    report = HarnessReport(sampler=args.sampler)
    chapters = await _load_chapters(args.corpus, args.repeat)
    texts = [_chapter_text(chapter) for chapter in chapters]
    report.chapters = len(chapters)

    if args.sampler == "deterministic":
        from modules.evolution.sampler import register_scene_sampler

        register_scene_sampler(
            "e09-deterministic",
            lambda db, novel_id: GroundedDeterministicSampler(
                dict(enumerate(texts))
            ),
        )
        provider = "e09-deterministic"
    else:
        key = os.environ.get(args.seed_provider_key_env or "")
        if not key:
            raise HarnessError(
                f"环境变量 {args.seed_provider_key_env!r} 未设置（真实模型另行授权）"
            )
        provider = "project_llm"

    # ---- 建项目：真实 Scene/草稿行 ----
    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import AccountPrincipal
    from modules.account.models import Account
    from modules.project.models import Project
    from modules.story.outline_state.models import Scene
    from modules.writing.facade import create_draft_only

    novel_id = str(uuid.uuid4())
    owner_id = uuid.uuid4()
    principal = AccountPrincipal(
        account_id=owner_id,
        status="active",
        identity_type="email",
        support_code=f"evoscale-{novel_id[:12]}",
    )
    principal_token = bind_principal(principal)
    try:
        async with maker() as db:
            db.add(Account(id=owner_id, support_code=f"evoscale-{novel_id[:8]}"))
            await db.flush()
            db.add(
                Project(
                    id=uuid.UUID(novel_id),
                    owner_id=owner_id,
                    title="E09 长书规模验证（影子）",
                    genre="奇幻",
                )
            )
            await db.flush()
            scene_ids: list[str] = []
            for index, chapter in enumerate(chapters):
                item = Scene(
                    novel_id=uuid.UUID(novel_id),
                    scene_index=index,
                    title=chapter.get("title", f"第{index + 1}章"),
                    chapter_ids=[index + 1],
                    scene_chunks=[{"chapter_index": index + 1}],
                    status="draft",
                )
                db.add(item)
                await db.flush()
                scene_ids.append(str(item.id))
                await create_draft_only(
                    db, novel_id, index + 1, chapter.get("title"), texts[index]
                )
            await db.commit()

        if args.sampler == "real":
            async with maker() as db:
                from modules.account.settings_service import SettingsService

                await SettingsService().connect_account_llm_provider(
                    db, "deepseek", key
                )
                await db.commit()

        from modules.evolution.tasks import handle_evolution_scene_step

        budget_total = min(len(texts), args.limit)
        report.budget_total = budget_total
        started = time.monotonic()

        # ---- 链推进（真实 handler，shadow） ----
        attempt_ids: list[str] = []
        async with maker() as db:
            for index in range(budget_total):
                result = await handle_evolution_scene_step(
                    db,
                    _task(
                        _step_request(
                            novel_id, scene_ids, texts, index, provider=provider,
                            budget_total=budget_total,
                        )
                    ),
                )
                attempt_ids.append(result["attempt_id"])
        report.scenes_run = budget_total

        # ---- 断言：预算 / 隔离 / 前序注入 / 引用与提及有据 / 计量 ----
        async with maker() as db:
            from modules.evolution.store import PostgresAttemptStore
            from modules.story.continuity.models import MemoryEvent

            store = PostgresAttemptStore(db, novel_id)
            run = await store.load_run(RUN_KEY)
            if run is None:
                raise HarnessError("shadow run missing after chain")
            report.budget_remaining_after_chain = int(run.budget_remaining)
            report.memory_events_written = int(
                (
                    await db.execute(
                        select(func.count(MemoryEvent.id)).where(
                            MemoryEvent.novel_id == uuid.UUID(novel_id),
                            MemoryEvent.source == "evolution",
                        )
                    )
                ).scalar_one()
            )

            prior_scenes: list[int] = []
            quote_ok = True
            mention_ok = True
            usage_ok: bool | None = None if args.sampler == "deterministic" else True
            for index, attempt_id in enumerate(attempt_ids):
                frozen = await store.load_frozen(RUN_KEY, attempt_id)
                if frozen is None:
                    raise HarnessError(f"scene {index}: frozen attempt missing")
                payload = frozen.payload or {}
                if (payload.get("input_manifest") or {}).get("previous_observations"):
                    prior_scenes.append(index)
                compiled = payload.get("compiled_observations") or []
                report.observation_count += len(compiled)
                for item in compiled:
                    if item.get("quote") and item["quote"] not in texts[index]:
                        quote_ok = False
                    for mention in item.get("mentions") or []:
                        surface = mention.get("surface") or ""
                        if surface and surface not in texts[index]:
                            mention_ok = False
                if args.sampler == "real":
                    receipt = await store.load_receipt(RUN_KEY, attempt_id)
                    entries = receipt.paid_call_receipts if receipt else []
                    usage_ok = usage_ok and bool(entries) and all(
                        (entry.get("usage") or {}).get("completion_tokens")
                        is not None
                        for entry in entries
                    )
            report.prior_state_injected_scenes = prior_scenes
            report.quote_verbatim = quote_ok
            report.mention_grounded = mention_ok
            report.usage_recorded = usage_ok

            # ---- 屏障顺序：跳场被拒 ----
            from modules.evolution.pipeline import BarrierBlockedError

            try:
                await handle_evolution_scene_step(
                    db,
                    _task(
                        _step_request(
                            novel_id,
                            scene_ids,
                            texts,
                            budget_total,  # 占位 index 取末章文本
                            provider=provider,
                            budget_total=budget_total,
                            scene_index=budget_total + 1,  # 跳过下一步
                            chapter_index=len(texts),
                        )
                    ),
                )
                report.barrier_skip_rejected = False
            except BarrierBlockedError:
                report.barrier_skip_rejected = True

            # ---- 幂等重跑：同 Scene 返回原回执，预算不再扣减 ----
            replay = await handle_evolution_scene_step(
                db,
                _task(
                    _step_request(
                        novel_id,
                        scene_ids,
                        texts,
                        budget_total - 1,
                        provider=provider,
                        budget_total=budget_total,
                    )
                ),
            )
            run = await store.load_run(RUN_KEY)
            report.budget_remaining_after_rerun = int(run.budget_remaining)
            report.rerun_same_attempt = replay["attempt_id"] == attempt_ids[-1]

        # ---- 失效关闭：改末章原文 → 旧文本的下一步被拒 ----
        async with maker() as db:
            await create_draft_only(
                db, novel_id, len(texts), "末章（修订）", texts[-1] + "修订补记。"
            )
            await db.commit()
        async with maker() as db:
            from modules.evolution.commit import CommitConflictError

            try:
                await handle_evolution_scene_step(
                    db,
                    _task(
                        _step_request(
                            novel_id,
                            scene_ids,
                            texts,
                            budget_total - 1,
                            provider=provider,
                            budget_total=budget_total,
                            scene_index=budget_total,
                            scene_text=texts[budget_total - 1],
                        )
                    ),
                )
                report.stale_source_rejected = False
            except CommitConflictError:
                report.stale_source_rejected = True

        report.wall_seconds = round(time.monotonic() - started, 2)

        if not args.keep:
            async with maker() as db:
                await db.execute(
                    delete(Project).where(Project.id == uuid.UUID(novel_id))
                )
                await db.commit()
        return report
    finally:
        reset_principal(principal_token)
        await engine.dispose()


def _assert_exit_criteria(report: HarnessReport) -> None:
    """按计划 §9 退出标准逐项判定；任何一项失败即抛错。"""
    failures: list[str] = []
    if report.scenes_run <= 0:
        failures.append("未推进任何 Scene")
    if report.budget_remaining_after_chain != 0:
        failures.append("链后预算剩余应为 0")
    if report.budget_remaining_after_rerun != 0:
        failures.append("幂等重跑后预算剩余应为 0（重跑不得扣减）")
    if report.memory_events_written != 0:
        failures.append("影子运行写入了正式 MemoryEvent")
    if not report.prior_state_injected_scenes:
        failures.append("没有任何后序 Scene 携带前序状态内容")
    if report.barrier_skip_rejected is not True:
        failures.append("跳场未被屏障拒绝")
    if report.rerun_same_attempt is not True:
        failures.append("重跑未幂等返回原回执")
    if report.stale_source_rejected is not True:
        failures.append("过期来源未被提交边界拒绝")
    if report.quote_verbatim is not True:
        failures.append("存在非逐字引用")
    if report.mention_grounded is not True:
        failures.append("存在无据提及")
    if failures:
        raise HarnessError("；".join(failures))


def _render_markdown(report: HarnessReport) -> str:
    return "\n".join(
        [
            "# E09 长书规模验证（影子运行）报告",
            "",
            f"- 采样器：`{report.sampler}`；章节数 {report.chapters}；"
            f"推进 Scene 数 {report.scenes_run}",
            f"- 观察总数 {report.observation_count}；"
            f"前序状态注入 Scene：{report.prior_state_injected_scenes}",
            f"- 预算：总额 {report.budget_total}，"
            f"链后剩余 {report.budget_remaining_after_chain}，"
            f"重跑后剩余 {report.budget_remaining_after_rerun}",
            f"- 影子隔离（正式 MemoryEvent 写入数）：{report.memory_events_written}",
            f"- 屏障跳场拒绝：{report.barrier_skip_rejected}；"
            f"幂等重跑同回执：{report.rerun_same_attempt}；"
            f"过期来源拒绝：{report.stale_source_rejected}",
            f"- 引用逐字：{report.quote_verbatim}；提及有据：{report.mention_grounded}；"
            f"计量入回执：{report.usage_recorded}",
            f"- 总耗时：{report.wall_seconds}s",
            *[f"- ⚠️ {note}" for note in report.notes],
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", required=True, help="专用空库（勿指向共享/生产库）"
    )
    parser.add_argument("--create-schema", action="store_true")
    parser.add_argument("--corpus", default="ten-chapters", choices=["ten-chapters"])
    parser.add_argument("--repeat", type=int, default=1, help="语料轮次复制（规模档）")
    parser.add_argument(
        "--limit", type=int, default=0, help="最多推进的 Scene 数（0=全部）"
    )
    parser.add_argument(
        "--sampler", default="deterministic", choices=["deterministic", "real"]
    )
    parser.add_argument(
        "--seed-provider-key-env",
        default="",
        help="真实模型账户连接种入用的环境变量名（仅名称，不打印值）",
    )
    parser.add_argument("--json-path", default="")
    parser.add_argument("--keep", action="store_true", help="保留库中验证数据")
    args = parser.parse_args()
    if args.limit <= 0:
        args.limit = 10**9

    report = asyncio.run(run_harness(args))
    _assert_exit_criteria(report)
    print(_render_markdown(report))
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()

"""演化场景步组合器（V4 G2 / 计划 §4.1 的推进顺序落地）。

把既有内核按正确顺序串成一个 Scene 的推进步：

    前序屏障（T07） → 预算原子预留（T21） → provider 采样（事务外）
    → 观察（稳定身份） → 身份解析（E02） → 冻结（T10） → 窄提交（E03c/E04）

provider 以 sampler 注入：生产接真实项目 LLM 入口（E07 影子运行/E09 真实
质量验证），本模块与测试用确定性 sampler。**不注册 async_tasks 任务
handler**——deep_import 仍是唯一编排 owner（计划 N03：禁止双写）；E07
切换期由新 handler 调用本组合函数。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from infrastructure.llm.collaboration import content_hash
from modules.evolution.commit import (
    ApplierResult,
    CommitConflictError,
    FrozenAttempt,
    apply_frozen,
    new_attempt_id,
)
from modules.evolution.contracts import (
    CommittedPrefix,
    MentionRef,
    ObservationEnvelope,
    SourceRevisionRef,
    StoryPosition,
)
from modules.evolution.identity import resolve_observation_mentions
from modules.evolution.orchestrator import prepare_scene_input
from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore


class SceneSampler(Protocol):
    """窄任务采样 port：给定冻结来源与前序输入清单，返回本批负载。

    生产实现调用项目 LLM 入口；返回 dict 至少含 ``scene_events``
    （MemoryService 事件形状）与可选 ``observations``。
    """

    def sample(
        self, *, scene_text: str, input_manifest: dict[str, Any]
    ) -> dict[str, Any]: ...


class BarrierBlockedError(Exception):
    """前序 Scene 未提交：本步不推进（不继承未提交的解释）。"""


class PipelineStepResult(BaseModel):
    """一步推进的可验收结果：回执 + 身份解析与观察处置摘要。"""

    model_config = ConfigDict(extra="forbid")

    receipt_attempt_id: str
    committed_prefix: CommittedPrefix
    observation_ids: list[str] = []
    identity_outcomes: dict[str, int] = {}
    input_manifest: dict[str, Any]


async def run_scene_step(
    db,
    store: PostgresAttemptStore,
    *,
    run_key: str,
    scene_index: int,
    scene_text: str,
    sampler: SceneSampler,
    applier: Callable[..., Awaitable[ApplierResult]],
    identity_candidates: Callable[[str, str], Awaitable[list[Any]]] | None = None,
    content_mode: str = "working",
    producer_version: str = "evolution/pipeline",
    observer_contract_version: int = 1,
) -> PipelineStepResult:
    """推进一个 Scene：屏障 → 预算 → 采样 → 观察/身份 → 冻结 → 窄提交。"""
    manifest_hash = content_hash(
        {"run": run_key, "scene": scene_index, "text": scene_text}
    )
    input_manifest = await prepare_scene_input(
        store,
        run_key=run_key,
        scene_index=scene_index,
        source_manifest_hash=manifest_hash,
    )
    if input_manifest.dependency_status != "committed":
        raise BarrierBlockedError(input_manifest.blocked_reason or "前序 Scene 未提交")

    # T21：先原子预留，再允许采样；预算不足不发出请求。
    try:
        await store.reserve_budget(run_key, 1)
    except BudgetExhaustedError:
        raise

    head = await store.load_head_receipt(run_key)
    payload = sampler.sample(
        scene_text=scene_text, input_manifest=input_manifest.model_dump()
    )
    payload = dict(payload)
    payload["input_manifest"] = input_manifest.model_dump(mode="json")

    # 观察：稳定身份 + 身份解析结论进入冻结负载（可审计）。
    observation_ids: list[str] = []
    identity_outcomes: dict[str, int] = {}
    for observation_spec in payload.get("observations") or []:
        source_ref = SourceRevisionRef(
            novel_id=str(store.novel_id),
            source_kind="chapter_draft",
            draft_id=f"{run_key}:{scene_index}",
            content_hash=content_hash({"text": scene_text}),
            chapter_identity=f"scene:{scene_index}",
            start_offset=int(observation_spec.get("start_offset", 0)),
            end_offset=int(observation_spec.get("end_offset", len(scene_text))),
            range_hash=SourceRevisionRef.compute_range_hash(
                content_hash({"text": scene_text}),
                int(observation_spec.get("start_offset", 0)),
                int(observation_spec.get("end_offset", len(scene_text))),
            ),
            source_revision=int(observation_spec.get("source_revision", 1)),
            segmentation_version=1,
            source_visibility=content_mode,  # type: ignore[arg-type]
        )
        envelope = ObservationEnvelope.with_stable_id(
            source_ref=source_ref,
            observer_contract_version=observer_contract_version,
            mention_refs=[
                MentionRef(
                    mention_id=mention["mention_id"],
                    surface=mention["surface"],
                    entity_type=mention.get("entity_type"),
                    unresolved_reason=mention.get("unresolved_reason") or "待解析",
                )
                for mention in observation_spec.get("mentions") or []
            ],
            predicate_or_description=observation_spec["predicate"],
            modality=observation_spec.get("modality", "event_observed"),
            learned_at_position=StoryPosition(scene_index=scene_index),
            evidence_quotes=[
                {
                    "quote": observation_spec.get("quote", scene_text[:80]),
                    "source_ref": source_ref.model_dump(),
                }
            ],
            producer_run_id=run_key,
            input_manifest_hash=manifest_hash,
        )
        observation_ids.append(envelope.observation_id)

        if identity_candidates is not None:
            port = _CandidatePort(identity_candidates)
            _, resolutions = await resolve_observation_mentions(
                envelope, candidate_port=port, novel_id=str(store._novel_id)
            )
            for resolution in resolutions:
                key = resolution.outcome
                identity_outcomes[key] = identity_outcomes.get(key, 0) + 1
    payload["observation_ids"] = observation_ids
    payload["identity_outcomes"] = identity_outcomes

    run = await store.load_run(run_key)
    frozen = FrozenAttempt(
        novel_id=str(store.novel_id),
        run_id=run_key,
        attempt_id=new_attempt_id(),
        owner_epoch=run.owner_epoch if run else 1,
        producer_version=producer_version,
        source_manifest_hash=manifest_hash,
        previous_receipt=head.attempt_id if head else None,
        previous_committed_prefix=head.committed_prefix if head else None,
        payload=payload,
    )
    await store.save_frozen(frozen)
    receipt = await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=applier,
        source_verifier=_manifest_verifier(manifest_hash),
        owner_epoch_provider=store.owner_epoch_provider(run_key),
    )
    return PipelineStepResult(
        receipt_attempt_id=receipt.attempt_id,
        committed_prefix=receipt.committed_prefix,
        observation_ids=observation_ids,
        identity_outcomes=identity_outcomes,
        input_manifest=input_manifest.model_dump(mode="json"),
    )


class _CandidatePort:
    """把 (novel, surface) 候选查询适配为 E02 的 candidate port。"""

    def __init__(self, lookup: Callable[[str, str], Awaitable[list[Any]]]) -> None:
        self._lookup = lookup

    async def find_candidates(
        self, novel_id: str, surface: str, entity_type: str | None = None
    ):
        from modules.evolution.identity import candidates_from_world_results

        return candidates_from_world_results(await self._lookup(novel_id, surface))


def _manifest_verifier(manifest_hash: str):
    async def _verifier(db, frozen: FrozenAttempt) -> None:
        if frozen.source_manifest_hash != manifest_hash:
            raise CommitConflictError(
                "source_changed",
                "scene source manifest drifted after freeze",
            )

    return _verifier

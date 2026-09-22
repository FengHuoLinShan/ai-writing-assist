"""演化场景步组合器（V4 G2 / 计划 §4.1 的推进顺序落地）。

把既有内核按正确顺序串成一个 Scene 的推进步：

    前序屏障（T07，含顺序检查与前序状态内容） → 预算原子预留（T21）
    → 请求前冻结（attempt 身份 + 预算关系先行落库，A07）
    → provider 采样（持久化边界之外，async）
    → 采样结果先行耐久化（sampled 阶段，A07）
    → 观察（稳定身份；提及身份由宿主派生） → 身份解析（E02）
    → 状态操作语义门（A03：证据绑定 + modality 分级 + 主体要求）
    → 编译冻结（compiled 阶段，T10） → 窄提交（E03c/E04，真实来源重验）

事务边界（返修 R4 + A07）：预留先提交持久化；**发出 provider 请求前**先把
attempt 身份与预算关系冻结落库（``sampling`` 阶段）——进程在请求后任何一点
崩溃，恢复都能按阶段区分"结果已取回/费用未知"，不盲目重采样。provider
返回后负载立即以 ``sampled`` 阶段耐久化，观察编译失败时冻结停在 sampled，
恢复走确定性重编译（同一 World 候选 → 同一输出），绝不重采样（T10）。
apply 是最后一笔短事务。域失败回滚不再抹掉预算预留与冻结负载——恢复走
:func:`recover_scene_step`。

执行模式进入冻结/提交协议（A01）：影子 run 的冻结负载盖章
``execution_mode=shadow``，首次执行与恢复走**同一**写入策略解析（任一
来源为 shadow 即强制隔离 applier，不信任调用方传入），且提交边界
(:func:`modules.evolution.commit.apply_frozen`) 拒绝影子负载经正式领域
applier 写入。

provider 以 async sampler 注入：生产接真实项目 LLM 入口（E07 影子运行/
E09 真实质量验证），本模块与测试用确定性 async sampler。**不注册
async_tasks 任务 handler 的流量**——deep_import 仍是唯一编排 owner
（计划 N03：禁止双写）；E07 切换期由新 handler 调用本组合函数。
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

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
from modules.evolution.observations import derive_mention_id
from modules.evolution.orchestrator import prepare_scene_input
from modules.evolution.state_gate import gate_scene_events
from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore


class SceneSampler(Protocol):
    """窄任务采样 port（async）：给定冻结来源与前序输入清单，返回本批负载。

    生产实现调用项目 LLM 入口；返回 dict 至少含 ``observations``
    （提及只带表面名，身份由宿主派生）与可选 ``scene_events``
    （模型提议，须通过一致性门才取得状态效果）。
    """

    def sample(
        self, *, scene_text: str, input_manifest: dict[str, Any]
    ) -> Awaitable[dict[str, Any]]: ...


class SceneSourceBinding(BaseModel):
    """真实来源绑定（返修 R2）：观察与提交都锚定真实正文版本。

    ``content_hash`` 是 Writing 侧草稿内容指纹；采样文本必须能在提交时
    重新对照同一草稿版本——来源漂移即整批作废，不消费旧冻结。
    """

    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1)
    chapter_index: int = Field(ge=1)
    content_hash: str = Field(min_length=32, max_length=64)


class BarrierBlockedError(Exception):
    """前序 Scene 未按顺序提交：本步不推进（不继承未提交的解释）。"""


class SamplePendingReconciliationError(Exception):
    """采样已发起或已失败但无可应用结果：费用可能已发生（unknown_billing）。

    恢复遇到 ``sampling``（请求后崩溃、结果未取回）或 ``failed``（最终
    失败、回执已固化）阶段的冻结负载时抛出——对账依据在冻结负载的
    ``paid_call_receipt`` 里，确认后登记新 run 重来，不自动重采样。
    """

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"{stage}: {detail}")
        self.stage = stage


class PipelineStepResult(BaseModel):
    """一步推进的可验收结果：回执 + 身份解析与观察处置摘要。"""

    model_config = ConfigDict(extra="forbid")

    receipt_attempt_id: str
    committed_prefix: CommittedPrefix
    observation_ids: list[str] = []
    identity_outcomes: dict[str, int] = {}
    gated_scene_events: list[dict[str, Any]] = []
    input_manifest: dict[str, Any]


async def load_current_source_hash(
    db, novel_id: str, binding: SceneSourceBinding
) -> SceneSourceBinding | None:
    """经 Writing facade 读取当前真实草稿指纹（R2 重验数据源）。"""

    from modules.writing.facade import get_draft, get_latest_draft_for_chapter

    draft = await get_draft(db, novel_id, binding.draft_id)
    if draft is None:
        return None
    latest = await get_latest_draft_for_chapter(db, novel_id, binding.chapter_index)
    if latest is None or str(latest.id) != str(draft.id):
        return None
    return SceneSourceBinding(
        draft_id=str(draft.id),
        chapter_index=binding.chapter_index,
        content_hash=str(draft.content_hash),
    )


async def _compile_sample_payload(
    payload: dict[str, Any],
    *,
    novel_id: str,
    run_key: str,
    scene_index: int,
    scene_text: str,
    source: SceneSourceBinding,
    manifest_hash: str,
    content_mode: str,
    observer_contract_version: int,
    identity_candidates: Callable[[str, str], Awaitable[list[Any]]] | None,
) -> dict[str, Any]:
    """把采样输出确定性编译进负载：观察身份、提及身份、身份解析与语义门。

    纯确定性推导（同一输入 + 同一 World 候选 → 同一输出，不接触 provider）：
    恢复路径在 ``sampled`` 阶段负载上重跑本函数即得到同一编译结果（T10）。
    """

    observation_ids: list[str] = []
    compiled_observations: list[dict[str, Any]] = []
    identity_outcomes: dict[str, int] = {}
    resolution_records: list[dict[str, Any]] = []
    for observation_spec in payload.get("observations") or []:
        source_ref = SourceRevisionRef(
            novel_id=novel_id,
            source_kind="chapter_draft",
            draft_id=source.draft_id,
            content_hash=source.content_hash,
            chapter_identity=f"chapter:{source.chapter_index}",
            start_offset=int(observation_spec.get("start_offset", 0)),
            end_offset=int(observation_spec.get("end_offset", len(scene_text))),
            range_hash=SourceRevisionRef.compute_range_hash(
                source.content_hash,
                int(observation_spec.get("start_offset", 0)),
                int(observation_spec.get("end_offset", len(scene_text))),
            ),
            source_revision=int(observation_spec.get("source_revision", 1)),
            segmentation_version=1,
            source_visibility=content_mode,  # type: ignore[arg-type]
        )
        mentions = []
        explicit_mention_ids: set[str] = set()
        for ordinal, mention in enumerate(observation_spec.get("mentions") or []):
            explicit_id = mention.get("mention_id")
            if explicit_id:
                explicit_mention_ids.add(explicit_id)
            mentions.append(
                MentionRef(
                    mention_id=(
                        explicit_id
                        or derive_mention_id(
                            observation_id="pending",
                            surface=mention["surface"],
                            ordinal=ordinal,
                            entity_type=mention.get("entity_type"),
                        )
                    ),
                    surface=mention["surface"],
                    entity_type=mention.get("entity_type"),
                    unresolved_reason=mention.get("unresolved_reason") or "待解析",
                )
            )
        envelope = ObservationEnvelope.with_stable_id(
            source_ref=source_ref,
            observer_contract_version=observer_contract_version,
            mention_refs=mentions,
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
        # 观察身份派生后，把宿主派生提及的占位身份替换为依赖观察身份的
        # 稳定身份；模型/测试显式给出的 mention_id 原样保留。
        mention_refs = [
            (
                mention
                if mention.mention_id in explicit_mention_ids
                else mention.model_copy(
                    update={
                        "mention_id": derive_mention_id(
                            observation_id=envelope.observation_id,
                            surface=mention.surface,
                            ordinal=ordinal,
                            entity_type=mention.entity_type,
                        )
                    }
                )
            )
            for ordinal, mention in enumerate(envelope.mention_refs)
        ]
        envelope = envelope.model_copy(update={"mention_refs": mention_refs})
        observation_ids.append(envelope.observation_id)

        observation_mentions: list[dict[str, Any]] = []
        if identity_candidates is not None:
            port = _CandidatePort(identity_candidates)
            _, resolutions = await resolve_observation_mentions(
                envelope, candidate_port=port, novel_id=novel_id
            )
            resolution_by_surface: dict[str, dict[str, Any]] = {}
            for resolution in resolutions:
                key = resolution.outcome
                identity_outcomes[key] = identity_outcomes.get(key, 0) + 1
                record = {
                    "mention_id": resolution.mention_ref.mention_id,
                    "surface": resolution.mention_ref.surface,
                    "outcome": resolution.outcome,
                    "resolved_entity_id": resolution.resolved_entity_id,
                    "rationale": resolution.rationale,
                }
                resolution_records.append(record)
                resolution_by_surface[resolution.mention_ref.surface] = record
            observation_mentions = [
                {
                    "mention_id": mention.mention_id,
                    "surface": mention.surface,
                    "entity_type": mention.entity_type,
                    "resolution": resolution_by_surface.get(mention.surface),
                }
                for mention in envelope.mention_refs
            ]
        else:
            observation_mentions = [
                {
                    "mention_id": mention.mention_id,
                    "surface": mention.surface,
                    "entity_type": mention.entity_type,
                    "resolution": None,
                }
                for mention in envelope.mention_refs
            ]
        compiled_observations.append(
            {
                "observation_id": envelope.observation_id,
                "predicate": observation_spec["predicate"],
                "modality": observation_spec.get("modality", "event_observed"),
                "quote": observation_spec.get("quote", scene_text[:80]),
                "mentions": observation_mentions,
            }
        )

    # 状态操作语义门（A03）：证据绑定 + modality 分级 + knowledge 主体；
    # 拦下的提议带原因进入 gated_scene_events 待作者裁定，不取得状态效果。
    applied_events, gated_events = gate_scene_events(
        payload.get("scene_events") or [], compiled_observations
    )
    return {
        "observation_ids": observation_ids,
        "compiled_observations": compiled_observations,
        "identity_outcomes": identity_outcomes,
        "identity_resolutions": resolution_records,
        "scene_events": applied_events,
        "gated_scene_events": gated_events,
    }


async def run_scene_step(
    db,
    store: PostgresAttemptStore,
    *,
    run_key: str,
    scene_index: int,
    scene_text: str,
    source: SceneSourceBinding,
    sampler: SceneSampler,
    applier: Callable[..., Awaitable[ApplierResult]],
    identity_candidates: Callable[[str, str], Awaitable[list[Any]]] | None = None,
    content_mode: str = "working",
    producer_version: str = "evolution/pipeline",
    observer_contract_version: int = 1,
) -> PipelineStepResult:
    """推进一个 Scene：屏障 → 预算 → 冻结请求 → 采样 → 编译 → 窄提交。

    事务边界由本函数显式提交（与任务 handler 持有会话的仓库惯例一致）：
    预算持久化、请求前冻结、采样结果冻结、编译冻结、apply 各成一笔；
    provider 调用发生在提交点之间，不携带任何未提交的域事务。
    """
    # 来源与采样文本的一致性先于一切：scene_text 必须逐字来自绑定草稿的
    # 当前内容（sha256 与 writing.source_hashing.hash_text 同法），且该
    # 草稿仍是本章最新版本——来源漂移即整批作废，不消费旧冻结。
    current = await load_current_source_hash(db, str(store.novel_id), source)
    if (
        current is None
        or current.content_hash != source.content_hash
        or hashlib.sha256(scene_text.encode("utf-8")).hexdigest() != source.content_hash
    ):
        raise CommitConflictError(
            "source_changed",
            "scene text source draft is missing, superseded or changed",
        )

    manifest_hash = content_hash(
        {
            "run": run_key,
            "scene": scene_index,
            "text": scene_text,
            "draft_id": source.draft_id,
            "draft_hash": source.content_hash,
        }
    )
    input_manifest = await prepare_scene_input(
        store,
        run_key=run_key,
        scene_index=scene_index,
        source_manifest_hash=manifest_hash,
    )
    if input_manifest.dependency_status != "committed":
        reason = input_manifest.blocked_reason or "前序 Scene 未按顺序提交"
        raise BarrierBlockedError(reason)

    # T21：先原子预留并持久化，再允许采样；预算不足不发出请求。
    try:
        await store.reserve_budget(run_key, 1)
    except BudgetExhaustedError:
        raise
    run_row = await store.load_run(run_key)
    await db.commit()

    # 执行模式以 run 登记为准，并盖章进冻结负载（A01：恢复与提交边界
    # 都以协议内标记为准，不依赖调用方自觉换 applier）。
    execution_mode = run_row.execution_mode if run_row else "live"

    head = await store.load_head_receipt(run_key)

    # A07 请求前冻结：attempt 身份、来源绑定、预算关系（run 行已扣减）在
    # provider 请求发出**之前**耐久化。此后任何一点崩溃，恢复按阶段区分
    # 结果已取回（sampled/compiled）与费用未知（sampling），不盲目重采样。
    frozen = FrozenAttempt(
        novel_id=str(store.novel_id),
        run_id=run_key,
        attempt_id=new_attempt_id(),
        owner_epoch=run_row.owner_epoch if run_row else 1,
        producer_version=producer_version,
        source_manifest_hash=manifest_hash,
        previous_receipt=head.attempt_id if head else None,
        previous_committed_prefix=head.committed_prefix if head else None,
        payload={
            "stage": "sampling",
            "scene_index": scene_index,
            "scene_text": scene_text,
            "source_binding": source.model_dump(mode="json"),
            "execution_mode": execution_mode,
            "observer_contract_version": observer_contract_version,
            "input_manifest": input_manifest.model_dump(mode="json"),
        },
    )
    await store.save_frozen(frozen)
    await db.commit()

    try:
        sampled = await sampler.sample(
            scene_text=scene_text, input_manifest=input_manifest.model_dump()
        )
    except Exception as exc:
        # A07：最终失败也固化回执——请求可能已发出、可能已计费；采样器
        # 失败回执（若有）随冻结负载留档，恢复进入待核对而非重采样。
        frozen = frozen.model_copy(
            update={
                "payload": {
                    **frozen.payload,
                    "stage": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                    "paid_call_receipt": getattr(sampler, "last_call_receipt", None),
                }
            }
        )
        await store.replace_frozen_payload(frozen)
        await db.commit()
        raise

    # provider 结果先于任何领域推导耐久化（A07）：观察构建/身份解析失败
    # 时冻结停在 sampled 阶段，恢复可免采样重编译。
    payload: dict[str, Any] = dict(sampled)
    payload.update(
        {
            "stage": "sampled",
            "scene_index": scene_index,
            "scene_text": scene_text,
            "source_binding": source.model_dump(mode="json"),
            "execution_mode": execution_mode,
            "observer_contract_version": observer_contract_version,
            "input_manifest": input_manifest.model_dump(mode="json"),
        }
    )
    frozen = frozen.model_copy(update={"payload": payload})
    await store.replace_frozen_payload(frozen)
    await db.commit()

    compiled = await _compile_sample_payload(
        payload,
        novel_id=str(store.novel_id),
        run_key=run_key,
        scene_index=scene_index,
        scene_text=scene_text,
        source=source,
        manifest_hash=manifest_hash,
        content_mode=content_mode,
        observer_contract_version=observer_contract_version,
        identity_candidates=identity_candidates,
    )
    payload.update(compiled)
    payload["stage"] = "compiled"
    frozen = frozen.model_copy(update={"payload": payload})
    await store.replace_frozen_payload(frozen)
    await db.commit()

    receipt = await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=_resolve_step_applier(
            run_row=run_row,
            payload=payload,
            scene_index=scene_index,
            chapter_index=source.chapter_index,
            applier=applier,
        ),
        source_verifier=_source_verifier(source),
        owner_epoch_provider=store.owner_epoch_provider(run_key),
    )
    await db.commit()
    return PipelineStepResult(
        receipt_attempt_id=receipt.attempt_id,
        committed_prefix=receipt.committed_prefix,
        observation_ids=compiled["observation_ids"],
        identity_outcomes=compiled["identity_outcomes"],
        gated_scene_events=compiled["gated_scene_events"],
        input_manifest=input_manifest.model_dump(mode="json"),
    )


async def recover_scene_step(
    db,
    store: PostgresAttemptStore,
    *,
    run_key: str,
    scene_index: int,
    applier: Callable[..., Awaitable[ApplierResult]],
    identity_candidates: Callable[[str, str], Awaitable[list[Any]]] | None = None,
    content_mode: str = "working",
) -> Any:
    """故障恢复入口（返修 R4 + A07）：按冻结负载的阶段恢复，绝不重采样。

    - ``compiled``（或无阶段标记的既有负载）：直接重验重提交；
    - ``sampled``：确定性重编译（观察身份/身份解析/语义门）后提交；
    - ``sampling`` / ``failed``：费用可能已发生（unknown_billing），抛
      :class:`SamplePendingReconciliationError` 待对账；
    - 无冻结负载：返回 None，调用方才可重新走 :func:`run_scene_step`。

    写入策略与首次执行同一解析（A01）：影子负载强制隔离 applier，即使
    调用方传入了正式写入器。
    """
    frozen = await store.load_pending_frozen(run_key, scene_index)
    if frozen is None:
        return None
    payload = dict(frozen.payload or {})
    binding_data = payload.get("source_binding") or {}
    source = SceneSourceBinding.model_validate(binding_data) if binding_data else None
    if source is None:
        raise CommitConflictError(
            "frozen_incomplete", "frozen attempt lacks its source binding"
        )
    stage = payload.get("stage")
    if stage in {"sampling", "failed"}:
        raise SamplePendingReconciliationError(
            stage,
            "provider request was initiated or finally failed; reconcile billing "
            "from the frozen receipt (register a new run to retry the scene)",
        )
    # sampled 阶段（结果已耐久化、编译未完成）确定性重编译；无阶段标记的
    # 既有负载在旧协议下总是编译后才冻结，直接应用。
    if stage == "sampled" or "compiled_observations" not in payload:
        scene_text = payload.get("scene_text")
        if not isinstance(scene_text, str) or not scene_text:
            raise CommitConflictError(
                "frozen_incomplete",
                "sampled frozen attempt lacks its scene text for recompilation",
            )
        compiled = await _compile_sample_payload(
            payload,
            novel_id=str(store.novel_id),
            run_key=run_key,
            scene_index=scene_index,
            scene_text=scene_text,
            source=source,
            manifest_hash=frozen.source_manifest_hash,
            content_mode=content_mode,
            observer_contract_version=int(payload.get("observer_contract_version", 1)),
            identity_candidates=identity_candidates,
        )
        payload.update(compiled)
        payload["stage"] = "compiled"
        frozen = frozen.model_copy(update={"payload": payload})
        await store.replace_frozen_payload(frozen)
        await db.commit()

    run_row = await store.load_run(run_key)
    receipt = await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=_resolve_step_applier(
            run_row=run_row,
            payload=frozen.payload,
            scene_index=scene_index,
            chapter_index=source.chapter_index,
            applier=applier,
        ),
        source_verifier=_source_verifier(source),
        owner_epoch_provider=store.owner_epoch_provider(run_key),
    )
    await db.commit()
    return receipt


class _CandidatePort:
    """把 (novel, surface) 候选查询适配为 E02 的 candidate port。"""

    def __init__(self, lookup: Callable[[str, str], Awaitable[list[Any]]]) -> None:
        self._lookup = lookup

    async def find_candidates(
        self, novel_id: str, surface: str, entity_type: str | None = None
    ):
        from modules.evolution.identity import candidates_from_world_results

        return candidates_from_world_results(await self._lookup(novel_id, surface))


def exact_name_candidate_lookup(db) -> Callable[[str, str], Awaitable[list[Any]]]:
    """生产身份候选召回（返修 R2）：经 world facade 精确名解析。

    只提供精确名称/别名证据；模糊候选留待作者裁定，不自动合并。
    """

    async def _lookup(novel_id: str, surface: str) -> list[Any]:
        from modules.world.facade import find_working_entity_ids_by_names

        resolved = await find_working_entity_ids_by_names(db, novel_id, [surface])
        entity_id = resolved.get(surface)
        if not entity_id:
            return []

        class _ExactCandidate:
            def __init__(self, eid: str, name: str) -> None:
                self.existing_entity_id = eid
                self.existing_entity_name = name
                self.similarity_score = 1.0
                self.match_method = "exact_name"

        return [_ExactCandidate(entity_id, surface)]

    return _lookup


def _resolve_step_applier(
    *,
    run_row,
    payload: dict[str, Any] | None,
    scene_index: int,
    chapter_index: int,
    applier: Callable[..., Awaitable[ApplierResult]],
):
    """统一写入策略解析（A01）：run 登记模式与冻结负载盖章任一为 shadow，
    即强制隔离 applier——首次执行与恢复走同一规则，不信任调用方传入。"""

    modes = {
        run_row.execution_mode if run_row is not None else "live",
        str((payload or {}).get("execution_mode") or "live"),
    }
    if "shadow" in modes:
        return _shadow_applier(scene_index, chapter_index)
    return applier


def _shadow_applier(scene_index: int, source_revision: int):
    """E07.b 隔离 applier：不写任何正式领域表，只回执化影子产物。

    影子游标按本步真实位置推进；provider 计量照常进入回执——影子运行
    消耗真实额度，费用必须可审计，只是不产生正式领域写入。
    ``shadow_isolated`` 标记供提交边界（apply_frozen）识别（A01）。
    """

    async def applier(db, frozen) -> ApplierResult:
        payload = dict(frozen.payload or {})
        payload["shadow_isolated"] = True
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=scene_index,
                through_source_revision=source_revision,
            ),
            outcome_status="nothing_to_do",
            coverage={"unsupported": ["production_world_story_writes"]},
            paid_call_receipts=[
                payload["paid_call_receipt"]
                for _ in [1]
                if payload.get("paid_call_receipt")
            ],
        )

    applier.shadow_isolated = True  # type: ignore[attr-defined]
    return applier


def _source_verifier(expected: SceneSourceBinding):
    """提交时真实来源重验（返修 R2）：对照当前 Writing 草稿，非自比较。"""

    async def _verifier(db, frozen: FrozenAttempt) -> None:
        current = await load_current_source_hash(db, frozen.novel_id, expected)
        if current is None or current.content_hash != expected.content_hash:
            raise CommitConflictError(
                "source_changed",
                "scene source draft is missing, superseded or changed after freeze",
            )

    return _verifier

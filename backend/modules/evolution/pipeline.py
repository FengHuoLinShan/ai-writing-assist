"""演化场景步组合器（V4 G2 / 计划 §4.1 的推进顺序落地）。

把既有内核按正确顺序串成一个 Scene 的推进步：

    前序屏障（T07，含顺序检查与前序状态内容） → 预算原子预留（T21）
    → 请求前冻结（attempt 身份 + 预算关系先行落库，A07）
    → provider 采样（持久化边界之外，async）
    → 采样结果先行耐久化（sampled 阶段，A07）
    → 观察（稳定身份；提及身份由宿主派生） → 身份解析（E02）
    → 状态操作结构门（A03：证据绑定 + modality 分级 + 主体要求）
    → 编译冻结（compiled）→ 独立语义复核（verified）→ 窄提交（E03c/E04，真实来源重验）

事务边界（返修 R4 + A07）：预留先提交持久化；**发出 provider 请求前**先把
attempt 身份与预算关系冻结落库（``sampling`` 阶段）——进程在请求后任何一点
崩溃，恢复都能按阶段区分"结果已取回/费用未知"，不盲目重采样。独立复核有自己的阶段日志与预算预留。provider
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
E09 真实质量验证），本模块与测试用确定性 async sampler。
生产由 evolution_scene_step_v2 handler 调用；
Project owner 门禁止与 legacy deep_import 双写。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
from modules.evolution.state_review import (
    SceneCallFailedError,
    paid_call_receipts,
    review_input,
    reviewed_events,
)
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


class SceneSourceRange(BaseModel):
    """真实来源绑定（A02）：整稿版本与 Scene 来源区间分别可验。

    ``content_hash`` 是整稿指纹（版本门）；``start_offset``/``end_offset``
    是 Scene 正文在草稿内的码点区间（来源门，``end_offset=None`` 表示至
    稿尾）。服务端按权威草稿取出精确片段与 scene_text 逐字比对，不信任
    请求独立声称的正文——同一章的前半段与后半段可以是两个不同 Scene，
    各自逐字来自草稿即可推进；整稿换版、区间漂移或片段不再逐字一致都判
    ``source_changed``。区间变化（重排/重分段）即不同绑定、不同 attempt
    身份（``range_hash`` 可选携带，与整稿指纹+区间一致性由模型校验）。
    """

    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1)
    chapter_index: int = Field(ge=1)
    content_hash: str = Field(min_length=32, max_length=64)
    start_offset: int = Field(default=0, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    range_hash: str | None = Field(default=None, min_length=32, max_length=64)

    @model_validator(mode="after")
    def _validate_range(self) -> SceneSourceRange:
        if self.end_offset is not None and self.end_offset < self.start_offset:
            raise ValueError("end_offset must be >= start_offset")
        if self.range_hash is not None and self.end_offset is not None:
            expected = SourceRevisionRef.compute_range_hash(
                self.content_hash, self.start_offset, self.end_offset
            )
            if self.range_hash != expected:
                raise ValueError("range_hash does not match content_hash + offsets")
        return self


class SceneSourceBinding(SceneSourceRange):
    """场景来源按叙事顺序拼接，不插入无来源的分隔符；首段保留旧请求形状。"""

    additional_sources: list[SceneSourceRange] = Field(
        default_factory=list, max_length=15
    )

    def ranges(self) -> list[SceneSourceRange]:
        return [
            SceneSourceRange.model_validate(
                self.model_dump(exclude={"additional_sources"})
            ),
            *self.additional_sources,
        ]

    @model_validator(mode="after")
    def _validate_source_order(self) -> SceneSourceBinding:
        for previous, current in zip(self.ranges(), self.additional_sources):
            if current.chapter_index < previous.chapter_index:
                raise ValueError("source ranges must follow chapter order")
            if current.chapter_index == previous.chapter_index and (
                previous.end_offset is None or current.start_offset < previous.end_offset
            ):
                raise ValueError("source ranges must not overlap")
        return self


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


async def load_current_source(
    db, novel_id: str, binding: SceneSourceBinding
) -> tuple[SceneSourceBinding, str] | None:
    """逐段重验全部来源，任何一段换版/越界都使整个 Scene 失效。"""
    ranges = []
    texts = []
    for source_range in binding.ranges():
        resolved = await _load_current_range(db, novel_id, source_range)
        if resolved is None or resolved[0].content_hash != source_range.content_hash:
            return None
        ranges.append(resolved[0])
        texts.append(resolved[1])
    return SceneSourceBinding(
        **ranges[0].model_dump(), additional_sources=ranges[1:]
    ), "".join(texts)


async def _load_current_range(
    db, novel_id: str, binding: SceneSourceRange
) -> tuple[SceneSourceRange, str] | None:
    """经 Writing facade 重验来源（A02）：整稿版本 + 权威区间切片。

    返回（规范化绑定，权威切片文本）：绑定草稿必须存在且仍是本章最新
    版本；``end_offset=None`` 落定为稿长。返回 None 表示草稿缺失、被新
    版本顶替或区间越界。调用方以返回的切片文本与 scene_text 逐字比对，
    不做自比较。
    """

    from modules.writing.facade import get_draft, get_latest_draft_for_chapter

    draft = await get_draft(db, novel_id, binding.draft_id)
    if draft is None:
        return None
    latest = await get_latest_draft_for_chapter(db, novel_id, binding.chapter_index)
    if latest is None or str(latest.id) != str(draft.id):
        return None
    content = draft.content
    if not isinstance(content, str):
        return None
    end = binding.end_offset if binding.end_offset is not None else len(content)
    if end <= binding.start_offset or end > len(content):
        return None
    if (
        binding.range_hash is not None
        and binding.range_hash
        != SourceRevisionRef.compute_range_hash(
            str(draft.content_hash), binding.start_offset, end
        )
    ):
        return None
    normalized = SceneSourceRange(
        draft_id=str(draft.id),
        chapter_index=binding.chapter_index,
        content_hash=str(draft.content_hash),
        start_offset=binding.start_offset,
        end_offset=end,
    )
    return normalized, content[binding.start_offset : end]


def compute_scene_manifest_hash(
    run_key: str,
    scene_index: int,
    scene_text: str,
    source: SceneSourceBinding,
) -> str:
    """Scene 步请求身份指纹（A08 幂等重放按它判同源）。

    输入 = 调用方传入的**原始**绑定（未规范化），任务层重放判定与管线
    用同一公式，保证同请求重试得到同一指纹；正文/整稿版本/区间任一变化
    都是新身份。
    """

    manifest = {
        "run": run_key,
        "scene": scene_index,
        "text": scene_text,
        "draft_id": source.draft_id,
        "draft_hash": source.content_hash,
        "start_offset": source.start_offset,
        "end_offset": source.end_offset,
    }
    if source.additional_sources:
        manifest["additional_sources"] = [
            item.model_dump(mode="json") for item in source.additional_sources
        ]
    return content_hash(manifest)


def _observation_evidence(
    observation: dict[str, Any],
    *,
    source: SceneSourceBinding,
    scene_text: str,
    novel_id: str,
    content_mode: str,
) -> list[dict[str, Any]]:
    """在冻结正文内精确定位引用，再映射为一或多个草稿绝对区间。"""
    quote = observation.get("quote")
    if not isinstance(quote, str) or not quote:
        raise CommitConflictError(
            "invalid_observation_source", "observation requires a verbatim quote"
        )
    start = observation.get("start_offset")
    end = observation.get("end_offset")
    if start is None and end is None:
        start = scene_text.find(quote)
        if start < 0 or scene_text.find(quote, start + 1) >= 0:
            raise CommitConflictError(
                "invalid_observation_source",
                "quote is missing or ambiguous; exact offsets required",
            )
        end = start + len(quote)
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(scene_text)
        or scene_text[start:end] != quote
    ):
        raise CommitConflictError(
            "invalid_observation_source", "quote does not match its exact scene range"
        )
    evidence = []
    cursor = 0
    for part in source.ranges():
        assert part.end_offset is not None  # load_current_source normalizes every range
        next_cursor = cursor + part.end_offset - part.start_offset
        left, right = max(cursor, start), min(next_cursor, end)
        if left < right:
            absolute_start = part.start_offset + left - cursor
            absolute_end = part.start_offset + right - cursor
            ref = SourceRevisionRef(
                novel_id=novel_id,
                source_kind="chapter_draft",
                draft_id=part.draft_id,
                content_hash=part.content_hash,
                chapter_identity=f"chapter:{part.chapter_index}",
                start_offset=absolute_start,
                end_offset=absolute_end,
                range_hash=SourceRevisionRef.compute_range_hash(
                    part.content_hash, absolute_start, absolute_end
                ),
                source_revision=1,
                segmentation_version=1,
                source_visibility=content_mode,
            )
            evidence.append(
                {"quote": scene_text[left:right], "source_ref": ref.model_dump()}
            )
        cursor = next_cursor
    return evidence


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
    identity_candidates: Callable[[str, str, str | None], Awaitable[list[Any]]] | None,
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
        evidence_quotes = _observation_evidence(
            observation_spec,
            source=source,
            scene_text=scene_text,
            novel_id=novel_id,
            content_mode=content_mode,
        )
        source_ref = SourceRevisionRef.model_validate(evidence_quotes[0]["source_ref"])
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
            evidence_quotes=evidence_quotes,
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
                "source_ref": envelope.source_ref.model_dump(mode="json"),
                "evidence_quotes": [
                    item.model_dump(mode="json") for item in envelope.evidence_quotes
                ],
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
        "proposed_scene_events": payload.get("scene_events") or [],
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
    scene_id: str | None = None,
    sampler: SceneSampler,
    applier: Callable[..., Awaitable[ApplierResult]],
    identity_candidates: Callable[[str, str, str | None], Awaitable[list[Any]]]
    | None = None,
    content_mode: str = "working",
    producer_version: str = "evolution/pipeline",
    observer_contract_version: int = 1,
    state_review_version: int = 1,
    state_reviewer: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    enrichment_version: int = 0,
    world_version: int = 0,
    scene_card: dict[str, Any] | None = None,
    scene_method_caller: Callable[..., Awaitable[dict[str, Any]]] | None = None,
) -> PipelineStepResult:
    """推进一个 Scene：屏障 → 预算 → 冻结请求 → 采样 → 编译 → 窄提交。

    事务边界由本函数显式提交（与任务 handler 持有会话的仓库惯例一致）：
    预算持久化、请求前冻结、采样结果冻结、编译冻结、apply 各成一笔；
    provider 调用发生在提交点之间，不携带任何未提交的域事务。
    """
    await store.require_project_owner(run_key)
    # 来源与采样文本的一致性先于一切（A02）：整稿版本与 Scene 区间分别
    # 验证——服务端按权威草稿取出绑定区间的精确片段，与 scene_text 逐字
    # 比对（非自比较）；草稿缺失、被顶替、换版或区间漂移都判 source_changed。
    # 请求身份指纹取自原始绑定（任务层 A08 重放判定用同一公式）。
    manifest_hash = compute_scene_manifest_hash(run_key, scene_index, scene_text, source)
    from modules.writing.facade import lock_chapter_versions_for_revalidation

    await lock_chapter_versions_for_revalidation(
        db,
        str(store.novel_id),
        sorted({part.chapter_index for part in [source, *source.additional_sources]}),
    )
    # Writing updates take chapter-version locks before invalidating the run.
    await store.load_run(run_key, for_update=True)
    if await store.load_pending_frozen(run_key, scene_index):
        raise CommitConflictError(
            "pending_attempt_exists", "recover the existing attempt without resampling"
        )
    resolved = await load_current_source(db, str(store.novel_id), source)
    if (
        resolved is None
        or resolved[0].content_hash != source.content_hash
        or resolved[1] != scene_text
    ):
        raise CommitConflictError(
            "source_changed",
            "scene text does not verbatim match its bound draft range "
            "(draft missing, superseded, re-versioned, or range drifted)",
        )
    source = resolved[0]
    if scene_id:
        await _verify_scene_binding(
            db, str(store.novel_id), scene_id, scene_index, source
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
    if run_row is not None and run_row.committed_scene_index != scene_index - 1:
        raise CommitConflictError(
            "parent_advanced", "run advanced after input preparation"
        )

    # 执行模式以 run 登记为准，并盖章进冻结负载（A01：恢复与提交边界
    # 都以协议内标记为准，不依赖调用方自觉换 applier）。
    execution_mode = run_row.execution_mode if run_row else "live"

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
        previous_receipt=input_manifest.previous_scene_attempt_id,
        previous_committed_prefix=input_manifest.previous_committed_prefix,
        payload={
            "stage": "sampling",
            "scene_index": scene_index,
            "scene_id": scene_id,
            "scene_text": scene_text,
            "source_binding": source.model_dump(mode="json"),
            "execution_mode": execution_mode,
            "observer_contract_version": observer_contract_version,
            "state_review_version": state_review_version,
            "enrichment_version": enrichment_version,
            "world_version": world_version,
            "scene_card": scene_card,
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
    # Provider output cannot forge host review receipts or protocol stages.
    payload = {
        key: sampled[key]
        for key in (
            "observations",
            "scene_events",
            "unresolved_parts",
            "paid_call_receipt",
        )
        if key in sampled
    }
    payload.update(
        {
            "stage": "sampled",
            "scene_index": scene_index,
            "scene_id": scene_id,
            "scene_text": scene_text,
            "source_binding": source.model_dump(mode="json"),
            "execution_mode": execution_mode,
            "observer_contract_version": observer_contract_version,
            "state_review_version": state_review_version,
            "enrichment_version": enrichment_version,
            "world_version": world_version,
            "scene_card": scene_card,
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

    frozen = await _finish_scene_results(
        db, store, frozen, source, state_reviewer, scene_method_caller
    )
    # Claim/provider transactions have ended. Serialize the short domain commit
    # before taking advisory/run/Scene locks; author mutations hold Project shared
    # and can touch both Scene rows and shared fusion suggestions before runs.
    from modules.project.facade import require_active_project_exclusive

    await require_active_project_exclusive(db, str(store.novel_id))
    payload = frozen.payload
    receipt = await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=_resolve_step_applier(
            run_row=run_row,
            payload=payload,
            scene_index=scene_index,
            chapter_index=source.ranges()[-1].chapter_index,
            applier=applier,
        ),
        source_verifier=_source_verifier(source),
        owner_epoch_provider=store.owner_epoch_provider(run_key),
    )
    await db.commit()
    return PipelineStepResult(
        receipt_attempt_id=receipt.attempt_id,
        committed_prefix=receipt.committed_prefix,
        observation_ids=payload["observation_ids"],
        identity_outcomes=payload["identity_outcomes"],
        gated_scene_events=payload["gated_scene_events"],
        input_manifest=input_manifest.model_dump(mode="json"),
    )


async def recover_scene_step(
    db,
    store: PostgresAttemptStore,
    *,
    run_key: str,
    scene_index: int,
    applier: Callable[..., Awaitable[ApplierResult]],
    identity_candidates: Callable[[str, str, str | None], Awaitable[list[Any]]]
    | None = None,
    content_mode: str = "working",
    source_manifest_hash: str | None = None,
    scene_id: str | None = None,
    state_reviewer: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    scene_method_caller: Callable[..., Awaitable[dict[str, Any]]] | None = None,
) -> Any:
    """故障恢复入口（返修 R4 + A07）：按冻结负载的阶段恢复，绝不重采样。

    - ``verified``：按已冻结复核结果免费重验重提交；
    - ``compiled`` / ``sampled``：必要时重编译，再执行新协议已计划但未调用的
      独立复核；旧协议不补付费调用，未复核提议只进入待决定；
    - ``sampling`` / ``failed``：费用可能已发生（unknown_billing），抛
      :class:`SamplePendingReconciliationError` 待对账；
      复核日志中的 sampling/failed 同样禁止重发；
    - 无冻结负载：返回 None，调用方才可重新走 :func:`run_scene_step`。

    写入策略与首次执行同一解析（A01）：影子负载强制隔离 applier，即使
    调用方传入了正式写入器。
    """
    frozen = await store.load_pending_frozen(run_key, scene_index)
    if frozen is None:
        return None
    await store.require_project_owner(run_key)
    await store.load_run(run_key, for_update=True)
    frozen = await store.load_pending_frozen(run_key, scene_index)
    if frozen is None:
        receipt = await store.load_committed_scene_receipt(
            run_key, scene_index, source_manifest_hash=source_manifest_hash
        )
        await db.commit()
        return receipt
    if (
        source_manifest_hash is not None
        and frozen.source_manifest_hash != source_manifest_hash
    ):
        raise CommitConflictError(
            "request_changed", "pending attempt belongs to a different scene request"
        )
    payload = dict(frozen.payload or {})
    if scene_id is not None and payload.get("scene_id") not in {None, scene_id}:
        raise CommitConflictError(
            "request_changed", "pending attempt belongs to another scene"
        )
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
        resolved = await load_current_source(db, str(store.novel_id), source)
        if resolved is None or resolved[1] != scene_text:
            raise CommitConflictError(
                "source_changed", "sampled source changed before recompilation"
            )
        source = resolved[0]
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

    frozen = await _finish_scene_results(
        db, store, frozen, source, state_reviewer, scene_method_caller
    )
    # Claim/provider transactions have ended. Serialize the short domain commit
    # before taking advisory/run/Scene locks; author mutations hold Project shared
    # and can touch both Scene rows and shared fusion suggestions before runs.
    from modules.project.facade import require_active_project_exclusive

    await require_active_project_exclusive(db, str(store.novel_id))
    run_row = await store.load_run(run_key)
    receipt = await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=_resolve_step_applier(
            run_row=run_row,
            payload=frozen.payload,
            scene_index=scene_index,
            chapter_index=source.ranges()[-1].chapter_index,
            applier=applier,
        ),
        source_verifier=_source_verifier(source),
        owner_epoch_provider=store.owner_epoch_provider(run_key),
    )
    await db.commit()
    return receipt


async def _run_scene_call(
    db, store, frozen, source, *, journal_key, inputs, call_inputs, call
):
    """Execute one registered Scene call under its frozen source and root budget."""
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    payload = dict(frozen.payload)
    journal = payload.get(journal_key) or {}
    if journal:
        if journal.get("stage") != "sampled":
            raise SamplePendingReconciliationError(
                journal_key, "provider result requires reconciliation"
            )
        if journal.get("input_hash") != content_hash(inputs):
            raise CommitConflictError(
                "request_changed", "frozen scene call inputs changed"
            )
        await db.commit()
        return frozen
    # Source/parent/owner are rechecked BEFORE reserving and sending a second call.
    await _source_verifier(source)(db, frozen)
    current = await prepare_scene_input(
        store,
        run_key=frozen.run_id,
        scene_index=payload["scene_index"],
        source_manifest_hash=frozen.source_manifest_hash,
    )
    if (
        current.dependency_status != "committed"
        or current.previous_scene_attempt_id != frozen.previous_receipt
        or current.previous_committed_prefix != frozen.previous_committed_prefix
    ):
        raise CommitConflictError("parent_advanced", "scene call parent changed")
    await store.reserve_budget(frozen.run_id, 1)
    journal = {"stage": "sampling", "input_hash": content_hash(inputs)}
    payload[journal_key] = journal
    frozen = frozen.model_copy(update={"payload": payload})
    await store.replace_frozen_payload(frozen)
    await db.commit()
    try:
        result = await call(**call_inputs)
    except Exception as error:
        journal = {
            **journal,
            "stage": "failed",
            "paid_call_receipt": error.receipt
            if isinstance(error, SceneCallFailedError)
            else None,
        }
        payload[journal_key] = journal
        await store.replace_frozen_payload(frozen.model_copy(update={"payload": payload}))
        await db.commit()
        raise
    journal = {
        **journal,
        "stage": "sampled",
        "result": result["result"],
        "paid_call_receipt": result.get("paid_call_receipt"),
    }
    payload[journal_key] = journal
    frozen = frozen.model_copy(update={"payload": payload})
    await store.replace_frozen_payload(frozen)
    await db.commit()
    return frozen


async def _finish_scene_results(db, store, frozen, source, reviewer, caller):
    from modules.evolution.enrichment import finish_scene_enrichment
    from modules.evolution.world import finish_scene_world

    if frozen.payload.get("world_version", 0) < 2:
        frozen = await _finish_state_review(db, store, frozen, source, reviewer)
    frozen = await finish_scene_enrichment(db, store, frozen, source, caller)
    frozen = await finish_scene_world(db, store, frozen, source, caller)
    if frozen.payload.get("world_version") == 2:
        frozen = await _finish_state_review(db, store, frozen, source, reviewer)
    return frozen


async def _finish_state_review(db, store, frozen, source, reviewer):
    # Two recoveries may have read the same compiled payload. Serialize the claim,
    # then reload before deciding whether a provider call has already started.
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    payload = dict(frozen.payload)
    if payload.get("stage") == "verified":
        await db.commit()  # apply_frozen takes its advisory lock before the run lock
        return frozen
    if payload.get("world_version") == 2 and "state_event_candidates" not in payload:
        from modules.evolution.world import bind_scene_identities

        payload.update(bind_scene_identities(payload))
    candidates = payload.setdefault(
        "state_event_candidates", payload.get("scene_events", [])
    )
    frozen = frozen.model_copy(update={"payload": payload})
    inputs = review_input(frozen)
    if candidates and payload.get("state_review_version") == 1 and reviewer:
        await store.replace_frozen_payload(frozen)
        frozen = await _run_scene_call(
            db,
            store,
            frozen,
            source,
            journal_key="state_review",
            inputs=inputs,
            call_inputs={
                key: inputs[key]
                for key in ("scene_text", "input_manifest", "observations", "events")
            },
            call=reviewer,
        )
        # The call commits before returning. Another recovery may already have
        # advanced this attempt; never replace its subsequent paid-call journal.
        await store.require_project_owner(frozen.run_id)
        await store.load_run(frozen.run_id, for_update=True)
        frozen = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        payload = dict(frozen.payload)
        if payload.get("stage") == "verified":
            await db.commit()
            return frozen
    elif (payload.get("state_review") or {}).get("stage") in {"sampling", "failed"}:
        raise SamplePendingReconciliationError(
            "state_review", "provider result requires reconciliation"
        )
    accepted, gated = reviewed_events(frozen)
    payload = {
        **payload,
        "stage": "verified",
        "scene_events": accepted,
        "gated_scene_events": [*payload.get("gated_scene_events", []), *gated],
    }
    frozen = frozen.model_copy(update={"payload": payload})
    await store.replace_frozen_payload(frozen)
    await db.commit()
    return frozen


class _CandidatePort:
    """把 (novel, surface) 候选查询适配为 E02 的 candidate port。"""

    def __init__(
        self, lookup: Callable[[str, str, str | None], Awaitable[list[Any]]]
    ) -> None:
        self._lookup = lookup

    async def find_candidates(
        self, novel_id: str, surface: str, entity_type: str | None = None
    ):
        from modules.evolution.identity import candidates_from_world_results

        return candidates_from_world_results(
            await self._lookup(novel_id, surface, entity_type)
        )


def exact_name_candidate_lookup(
    db,
) -> Callable[[str, str, str | None], Awaitable[list[Any]]]:
    """生产身份候选召回（返修 R2）：经 world facade 精确名解析。

    只提供精确名称/别名证据；模糊候选留待作者裁定，不自动合并。
    """

    async def _lookup(
        novel_id: str, surface: str, entity_type: str | None = None
    ) -> list[Any]:
        from modules.world.facade import find_exact_identity_candidates

        return await find_exact_identity_candidates(db, novel_id, surface, entity_type)

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
            paid_call_receipts=paid_call_receipts(payload),
        )

    applier.shadow_isolated = True  # type: ignore[attr-defined]
    return applier


async def _verify_scene_binding(db, novel_id, scene_id, scene_index, source):
    from core.errors import ValidationError
    from modules.story.outline_state.facade import validate_scene_source_ranges

    try:
        await validate_scene_source_ranges(
            db,
            novel_id,
            scene_id,
            scene_index,
            [part.model_dump(mode="json") for part in source.ranges()],
        )
    except ValidationError as exc:
        raise CommitConflictError("source_changed", str(exc)) from exc


def _source_verifier(expected: SceneSourceBinding):
    """提交时真实来源重验（返修 R2 + A02）：整稿版本与区间切片都重验。

    对照当前 Writing 草稿取出权威切片，与冻结负载里的 scene_text 逐字
    比对（非自比较）；阶段化之前的存量冻结负载没有 scene_text 时退回
    整稿指纹比对。
    """

    async def _verifier(db, frozen: FrozenAttempt) -> None:
        resolved = await load_current_source(db, frozen.novel_id, expected)
        scene_text = (frozen.payload or {}).get("scene_text")
        if (
            resolved is None
            or resolved[0].content_hash != expected.content_hash
            or (isinstance(scene_text, str) and scene_text and resolved[1] != scene_text)
        ):
            raise CommitConflictError(
                "source_changed",
                "scene source draft is missing, superseded, re-versioned, "
                "or its range drifted after freeze",
            )
        if scene_id := (frozen.payload or {}).get("scene_id"):
            await _verify_scene_binding(
                db, frozen.novel_id, scene_id, frozen.payload["scene_index"], resolved[0]
            )
            if scene_card := frozen.payload.get("scene_card"):
                from dataclasses import asdict

                from modules.story.facade import get_scene_contract

                current = await get_scene_contract(db, frozen.novel_id, scene_id)
                if current is None or content_hash(asdict(current)) != content_hash(
                    scene_card
                ):
                    raise CommitConflictError(
                        "scene_changed", "Scene card changed after freezing"
                    )

    return _verifier

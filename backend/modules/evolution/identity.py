"""身份解析内核（V4 E02，对应 01-EVOLUTION §3.3 / 验收 T01）。

职责分离（W02→E02）：

- **身份去重**：避免为同一人物创建影子身份——只有确定性证据（精确名称或
  别名命中，或作者领域命令）允许自动 reuse。
- **观察积累**：已有身份命中绝不跳过新观察——观察照常记录（观察身份由
  语义指纹决定，与解析结论无关），解析结论作为独立产物返回。

两条硬规则：

1. 相似度阈值永不构成自动合并已采用对象的依据；模糊候选只作为待作者
   裁定的证据随 new_candidate / ambiguous 一起返回。
2. 观察者自带的 resolved_entity_id 绑定必须经内核重验——不被精确证据
   支持时输出 unrelated，绝不静默接受编造或过期的 UUID。

内核是纯确定性函数；候选召回经 ``IdentityCandidatePort`` 注入
（world 适配器见 :func:`candidates_from_world_results`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from modules.evolution.contracts import (
    IdentityCandidate,
    IdentityResolution,
    MentionRef,
    ObservationEnvelope,
)

AUTO_REUSE_EVIDENCE_KINDS = frozenset({"exact_name", "exact_alias"})
"""允许自动 reuse 的证据类别；其余证据只能作为竞争候选供作者裁定。"""


@dataclass(frozen=True)
class IdentityPolicy:
    """确定性解析策略；不允许通过策略放宽为相似度自动合并。"""

    auto_reuse_evidence_kinds: frozenset[str] = AUTO_REUSE_EVIDENCE_KINDS


DEFAULT_IDENTITY_POLICY = IdentityPolicy()


class IdentityCandidatePort(Protocol):
    """候选召回 port：按提及表面（含别名）返回可能存在的实体候选。

    实现方负责 novel_id 隔离与可见性门禁；内核不直接接触数据库。
    """

    async def find_candidates(
        self,
        novel_id: str,
        surface: str,
        entity_type: str | None = None,
    ) -> list[IdentityCandidate]: ...


def resolve_mention(
    mention: MentionRef,
    candidates: list[IdentityCandidate],
    *,
    policy: IdentityPolicy = DEFAULT_IDENTITY_POLICY,
) -> IdentityResolution:
    """确定性身份解析：同一输入永远得到同一结论，无概率成分。"""
    exact = [
        candidate
        for candidate in candidates
        if candidate.evidence_kind in policy.auto_reuse_evidence_kinds
    ]
    if mention.resolved_entity_id is not None:
        bound = [
            candidate
            for candidate in exact
            if candidate.entity_id == mention.resolved_entity_id
        ]
        if bound:
            return IdentityResolution(
                mention_ref=mention,
                outcome="reuse",
                resolved_entity_id=mention.resolved_entity_id,
                candidates=bound,
                rationale="观察者绑定经精确证据重验通过",
            )
        if exact:
            conflicting = [
                candidate
                for candidate in exact
                if candidate.entity_id != mention.resolved_entity_id
            ]
            bound_candidate = IdentityCandidate(
                entity_id=mention.resolved_entity_id,
                evidence="observer_binding:未经精确证据支持",
            )
            return IdentityResolution(
                mention_ref=mention,
                outcome="ambiguous",
                candidates=[*conflicting, bound_candidate],
                rationale=("观察者绑定与精确证据冲突：绑定对象与精确候选保持竞争身份"),
            )
        return IdentityResolution(
            mention_ref=mention,
            outcome="unrelated",
            candidates=list(candidates),
            rationale="观察者绑定无精确证据支持，拒绝静默接受",
        )
    if len(exact) == 1:
        candidate = exact[0]
        return IdentityResolution(
            mention_ref=mention,
            outcome="reuse",
            resolved_entity_id=candidate.entity_id,
            candidates=exact,
            rationale="唯一精确名称/别名证据命中",
        )
    if len(exact) >= 2:
        return IdentityResolution(
            mention_ref=mention,
            outcome="ambiguous",
            candidates=exact,
            rationale="同名/同别名存在多个精确候选，保持竞争身份待作者裁定",
        )
    if candidates:
        return IdentityResolution(
            mention_ref=mention,
            outcome="new_candidate",
            candidates=list(candidates),
            rationale="无精确证据命中；模糊相似候选已记录，待作者裁定是否合并",
        )
    return IdentityResolution(
        mention_ref=mention,
        outcome="new_candidate",
        candidates=[],
        rationale="无任何已有候选，提议新身份",
    )


async def resolve_observation_mentions(
    observation: ObservationEnvelope,
    *,
    candidate_port: IdentityCandidatePort,
    novel_id: str,
    policy: IdentityPolicy = DEFAULT_IDENTITY_POLICY,
) -> tuple[ObservationEnvelope, list[IdentityResolution]]:
    """解析一条观察中的全部提及；观察本身照常记录、身份不变。

    返回的观察副本仅在 mention_refs 上补充解析结论（resolved id 或
    unresolved_reason 审计），observation_id 与语义内容不变——观察积累
    与身份解析互不吞并。同一 mention_id 只解析一次。
    """
    resolutions: list[IdentityResolution] = []
    resolved_by_mention: dict[str, IdentityResolution] = {}
    seen_surfaces: dict[str, list[IdentityCandidate]] = {}
    for mention in observation.mention_refs:
        cache_key = f"{mention.surface}\x00{mention.entity_type or ''}"
        if cache_key in seen_surfaces:
            candidates = seen_surfaces[cache_key]
        else:
            candidates = await candidate_port.find_candidates(
                novel_id,
                mention.surface,
                entity_type=mention.entity_type,
            )
            seen_surfaces[cache_key] = candidates
        resolution = resolve_mention(mention, candidates, policy=policy)
        resolutions.append(resolution)
        resolved_by_mention[mention.mention_id] = resolution

    updated_mentions = []
    for mention in observation.mention_refs:
        resolution = resolved_by_mention.get(mention.mention_id)
        if resolution is None:
            updated_mentions.append(mention)
            continue
        if resolution.outcome == "reuse" and resolution.resolved_entity_id:
            updated_mentions.append(
                mention.model_copy(
                    update={
                        "resolved_entity_id": resolution.resolved_entity_id,
                        "unresolved_reason": None,
                    }
                )
            )
        else:
            prior = mention.unresolved_reason
            reason = (
                f"identity:{resolution.outcome}; prior={prior}"
                if prior
                else f"identity:{resolution.outcome}"
            )
            updated_mentions.append(
                mention.model_copy(update={"unresolved_reason": reason})
            )
    updated = observation.model_copy(update={"mention_refs": updated_mentions})
    return updated, resolutions


_WORLD_EXACT_MATCH_METHODS = {"exact_name", "exact_alias"}


def candidates_from_world_results(results: object) -> list[IdentityCandidate]:
    """把 world 去重候选（结构兼容 ``DuplicateSuggestionResult``）映射为
    evolution 候选；只做结构映射，不引入 world 类型依赖。

    world 的 match_method：exact_name / exact_alias 视为精确证据，其余
    （trgm 级联、语义余弦）一律归为模糊证据——永不触发自动合并。
    """
    candidates: list[IdentityCandidate] = []
    for item in results or []:
        match_method = str(getattr(item, "match_method", "") or "")
        similarity = float(getattr(item, "similarity_score", 0.0) or 0.0)
        name = str(getattr(item, "existing_entity_name", "") or "")
        entity_id = str(getattr(item, "existing_entity_id", "") or "")
        if not entity_id:
            continue
        candidates.append(
            IdentityCandidate(
                entity_id=entity_id,
                evidence=(
                    f"{match_method}:{name}"
                    if match_method
                    else f"similar:{name}:score={similarity:.4f}"
                ),
                evidence_kind=(
                    match_method
                    if match_method in _WORLD_EXACT_MATCH_METHODS
                    else "semantic"
                    if match_method.startswith("semantic")
                    else "fuzzy"
                ),
                same_name=similarity >= 0.999,
                alias_used=None,
            )
        )
    return candidates

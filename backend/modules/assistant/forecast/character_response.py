"""Versioned, POV-bounded performance proposals for Scene forecasts."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, model_validator

from core.errors import ConflictError
from modules.assistant.forecast.contracts import StrictModel

CharacterEvidenceKind = Literal[
    "world_dossier",
    "scene_state",
    "manuscript",
    "author_condition",
    "creative_choice",
]


class PerformanceBasis(StrictModel):
    kind: CharacterEvidenceKind
    evidence_ids: list[str] = Field(default_factory=list, max_length=4)
    quote: str | None = Field(default=None, max_length=500)
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def sourced_basis(self):
        if self.kind != "creative_choice" and (not self.evidence_ids or not self.quote):
            raise ValueError("Evidence-backed bases need an exact quote and evidence IDs")
        if self.kind == "creative_choice" and (self.evidence_ids or self.quote):
            raise ValueError("A creative choice cannot claim source evidence")
        return self


class PerformanceVoice(StrictModel):
    line: str | None = Field(default=None, max_length=1000)
    delivery: str = Field(min_length=1, max_length=500)
    subtext: str = Field(min_length=1, max_length=500)


class PerformanceChange(StrictModel):
    emotion: str = Field(min_length=1, max_length=500)
    relationship: str = Field(min_length=1, max_length=500)
    goal: str = Field(min_length=1, max_length=500)


class CharacterPerformanceOption(StrictModel):
    direction_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    motive: Literal[
        "protect",
        "understand",
        "assert",
        "withdraw",
        "connect",
        "deceive",
        "delay",
        "repair",
        "escape",
        "delegate",
        "accept",
        "resist",
    ]
    motive_reason: str = Field(min_length=1, max_length=800)
    trigger: str = Field(min_length=1, max_length=800)
    behavior: list[str] = Field(min_length=1, max_length=6)
    expression: str = Field(min_length=1, max_length=500)
    body_language: str = Field(min_length=1, max_length=700)
    voice: PerformanceVoice
    psychology: str = Field(min_length=1, max_length=1000)
    psychological_trigger: str = Field(min_length=1, max_length=500)
    defense: str = Field(min_length=1, max_length=500)
    notices: list[str] = Field(default_factory=list, max_length=6)
    overlooks: list[str] = Field(default_factory=list, max_length=6)
    change: PerformanceChange
    basis: list[PerformanceBasis] = Field(min_length=1, max_length=6)
    assumptions: list[str] = Field(default_factory=list, max_length=6)


class CharacterResponseProposal(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    why_now: str = Field(min_length=1, max_length=1200)
    options: list[CharacterPerformanceOption] = Field(min_length=2, max_length=3)
    unknowns: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def distinct_motives(self):
        if len({item.direction_id for item in self.options}) != len(self.options):
            raise ValueError("Performance option IDs must be unique")
        if len({item.motive for item in self.options}) != len(self.options):
            raise ValueError("Performance options must have different motives")
        return self


class LocalCharacterResponseAssessment(StrictModel):
    capability_index: Literal[0] = 0
    question_kind: Literal["reaction"] = "reaction"
    proposal: CharacterResponseProposal


class CharacterResponseForecastOutput(StrictModel):
    """The v2 output contract; forecast_v1 and its frozen schema stay unchanged."""

    items: list[LocalCharacterResponseAssessment] = Field(min_length=1, max_length=1)


class CharacterResponseView(StrictModel):
    schema_version: Literal["character_response.v2"] = "character_response.v2"
    character_name: str = Field(min_length=1, max_length=255)
    cutoff_label: str = Field(min_length=1, max_length=200)
    # A persisted card starts with 2–3 options; author decisions can hide some later.
    options: list[CharacterPerformanceOption] = Field(default_factory=list, max_length=3)
    source_gaps: list[str] = Field(default_factory=list, max_length=20)


def assessments(output, ctx, review):
    """Turn one validated v2 performance card into the frozen forecast row shape."""
    from modules.assistant.forecast.preparation import actions_for
    from modules.assistant.forecast.ranking import stable_issue_key

    if len(output.items) != 1 or not ctx.focus.scene_id:
        raise ConflictError("人物表演候选需要一个明确的场景", code="INVALID_OUTPUT")
    item = output.items[0]
    sources = {row["evidence_id"]: row for row in ctx.sources}
    references = {row.evidence_id: row for row in ctx.evidence}
    fact = None
    fact_ref = None
    for evidence_id, source in sources.items():
        reference = references.get(evidence_id)
        if reference is None or reference.resource_kind != "domain_result":
            continue
        try:
            value = json.loads(source["text"])
        except (TypeError, ValueError):
            continue
        if value.get("capability_id") == "story.character_response.v2":
            if fact is not None:
                raise ConflictError(
                    "人物表演候选不能混入其他领域资料", code="INVALID_OUTPUT"
                )
            fact, fact_ref = value, reference
    if fact is None or fact_ref is None:
        raise ConflictError("人物角色视角资料缺失，请重新获取", code="UNKNOWN_EVIDENCE")
    source = fact.get("source") or {}
    brief = source.get("character_visible_brief") or {}
    available = {
        "world_dossier": bool(brief.get("world_items")),
        "scene_state": bool(brief.get("continuity_items")),
        "author_condition": bool(str(source.get("author_condition") or "").strip()),
        "manuscript": False,
    }
    source_sections = {
        "world_dossier": json.dumps(brief.get("world_items") or [], ensure_ascii=False),
        "scene_state": json.dumps(
            brief.get("continuity_items") or [], ensure_ascii=False
        ),
        "author_condition": str(source.get("author_condition") or ""),
    }
    for basis in (basis for option in item.proposal.options for basis in option.basis):
        if basis.kind == "creative_choice":
            continue
        if basis.kind == "manuscript" or not available.get(basis.kind, False):
            raise ConflictError(
                "候选依据引用了本轮未提供的资料类型", code="UNKNOWN_EVIDENCE"
            )
        if any(
            evidence_id != fact_ref.evidence_id
            or evidence_id not in sources
            or evidence_id not in references
            for evidence_id in basis.evidence_ids
        ):
            raise ConflictError("候选依据超出所选人物的可见资料", code="UNKNOWN_EVIDENCE")
        if basis.quote not in source_sections[basis.kind]:
            raise ConflictError(
                "候选依据中的原文引用不属于标注来源", code="UNKNOWN_EVIDENCE"
            )

    character_name = str(source.get("character") or "人物").strip()
    cutoff = source.get("cutoff") or {}
    scene_index = cutoff.get("scene_index")
    if scene_index is None:
        raise ConflictError("人物表演候选缺少场景截止点", code="INVALID_OUTPUT")
    cutoff_label = f"第 {int(scene_index) + 1} 个场景截止点"
    unknowns = list(
        dict.fromkeys(
            [
                *item.proposal.unknowns,
                *(str(value) for value in brief.get("gaps") or []),
            ]
        )
    )[:20]
    options = item.proposal.options
    direction_labels = {
        "protect": "保护",
        "understand": "先弄清楚",
        "assert": "表明立场",
        "withdraw": "暂时退开",
        "connect": "寻求连接",
        "deceive": "隐瞒或误导",
        "delay": "拖延决定",
        "repair": "修复关系",
        "escape": "脱身",
        "delegate": "交给别人",
        "accept": "接受",
        "resist": "抵抗",
    }
    directions = []
    for option in options:
        detail = "\n".join(
            [
                "动作顺序：" + "；".join(option.behavior),
                "神态：" + option.expression,
                "肢体：" + option.body_language,
                "声音：" + option.voice.delivery,
                *(["台词：" + option.voice.line] if option.voice.line else []),
                "潜台词：" + option.voice.subtext,
                "心理：" + option.psychology,
                "心理触发：" + option.psychological_trigger,
                "防御：" + option.defense,
                "注意：" + ("；".join(option.notices) or "未说明"),
                "忽略：" + ("；".join(option.overlooks) or "未说明"),
                "变化：情绪 "
                + option.change.emotion
                + "；关系 "
                + option.change.relationship
                + "；目标 "
                + option.change.goal,
                "动机：" + option.motive_reason,
            ]
        )
        directions.append(
            {
                "direction_id": option.direction_id,
                "title": direction_labels[option.motive],
                "condition": option.trigger,
                "proposal": detail,
                "possible_effects": [
                    option.change.emotion,
                    option.change.relationship,
                    option.change.goal,
                ],
                "assumptions": option.assumptions,
                "narrative_commitment": "low",
                "may_leave_open": True,
            }
        )
    proposal = {
        "title": item.proposal.title,
        "kind": "creative_opportunity",
        "statements": [
            {
                "text": "这些都是尚未发生的条件式表演候选。",
                "basis": "proposed",
                "evidence_ids": [],
                "assumptions": [],
            }
        ],
        "why_now": item.proposal.why_now,
        "directions": directions,
        "unknowns": unknowns,
        "verdict": "propose",
    }
    from modules.assistant.forecast.contracts import CandidateProposal

    proposal = CandidateProposal.model_validate(proposal)
    issue_key = stable_issue_key(
        "story.character_response.v2",
        ctx.scope.audience_key,
        [f"scene:{ctx.focus.scene_id}", f"character:{character_name}"],
        "reaction",
    )
    return [
        {
            "issue_key": issue_key,
            "capability_id": "story.character_response.v2",
            "tier": "next",
            "payload": {
                "anchor": {
                    "question_kind": "reaction",
                    "resource_kind": "domain_result",
                    "resource_id": str(fact_ref.resource_id),
                    "chapter_index": ctx.chapter_index,
                    "start": 0,
                    "end": 0,
                },
                "proposal": proposal.model_dump(mode="json"),
                "character_response": {
                    "schema_version": "character_response.v2",
                    "character_name": character_name,
                    "cutoff_label": cutoff_label,
                    "options": [option.model_dump(mode="json") for option in options],
                    "source_gaps": unknowns,
                },
                "evidence": [
                    reference.model_dump(mode="json") for reference in ctx.evidence
                ],
                "knowledge_review": {"status": review.get("status", "validated")},
                "ranking": {
                    "window": 2,
                    "task_help": 2,
                    "explicit_relevance": int(bool(ctx.focus.explicit_instruction)),
                    "evidence": sum(
                        len(basis.evidence_ids)
                        for option in options
                        for basis in option.basis
                    ),
                    "executable": int(bool(ctx.focus.draft_id)),
                    "narrative_commitment": 0,
                },
                "navigation": {
                    "page": "scene",
                    "scene_id": str(ctx.focus.scene_id),
                },
                "actions": actions_for(proposal, ctx, "story.character_response.v2"),
            },
        }
    ]

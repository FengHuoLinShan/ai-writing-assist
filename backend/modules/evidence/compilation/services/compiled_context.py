"""CompiledContext IR — Tier-based budget enforcement for context compilation.

Intermediate representation that groups context sections by priority tier
and enforces token budgets through staged eviction.
"""

from __future__ import annotations

import hashlib
import json
from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from infrastructure.llm.token_estimation import estimate_token_count

LINE_ITEM_SOURCE_KEYS = frozenset(
    {
        "world_entities",
        "open_narrative_obligations",
        "outline_analysis_scenes",
        "outline_analysis_arcs",
        "outline_analysis_threads",
        "outline_analysis_foreshadowing",
        "outline_analysis_reveals",
        "retrieval_evidence_packs",
        "pov_knowledge",
    }
)


def selection_ref_from_source(source: dict[str, Any]) -> dict[str, Any] | None:
    source_ref = source.get("source_ref")
    if isinstance(source_ref, dict) and source_ref:
        return {"kind": "source_range", "source_ref": dict(source_ref)}
    source_type = str(source.get("type") or "").strip()
    source_id = str(source.get("id") or "").strip()
    if not source_type or not source_id or source_type in {"task", "compiler"}:
        return None
    return {
        "kind": "target",
        "target_ref": {
            "target_type": source_type,
            "target_id": source_id,
            "target_path": "",
        },
    }


def selection_ref_key(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Tier(IntEnum):
    """Context section priority tiers.

    P0: Mandatory — never evicted (project core, author notes).
    P1: High — Delta compression (keep first/last N items).
    P2: Medium — Per-item truncation (drop individual items).
    P3: Low — Evictable (entire section dropped).
    P4: Filler — Evicted first (color, flavor text).
    """

    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4


class ContextItem(BaseModel):
    """One reviewable unit inside a context section."""

    key: str
    content: str
    token_count: int = 0
    title: str = ""
    preview: str = ""
    status: str = "unknown"
    activation_reason: str = ""
    source: dict[str, Any] = Field(default_factory=dict)
    selection_ref: dict[str, Any] | None = None
    selection_state: Literal[
        "required",
        "automatic",
        "author_pinned",
        "excluded",
        "omitted",
    ] = "automatic"
    can_exclude: bool = True
    omission_reason: str | None = None


class ContextSection(BaseModel):
    """A single section within a compiled context."""

    key: str
    tier: Tier
    content: str
    token_count: int = 0
    truncatable_per_item: bool = False
    max_items: int | None = None
    title: str = ""
    preview: str = ""
    status: str = "unknown"
    activation_reason: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list)
    can_exclude: bool = True
    excluded: bool = False
    truncated_reason: str | None = None
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)
    items: list[ContextItem] = Field(default_factory=list)

    def materialize_items(self) -> ContextSection:
        if self.items:
            return self
        required = self.tier == Tier.P0 or not self.can_exclude
        lines = self.content.splitlines()
        if (
            (self.key in LINE_ITEM_SOURCE_KEYS or self.truncatable_per_item)
            and (not self.sources or len(lines) == len(self.sources))
        ):
            items = [
                ContextItem(
                    key=(
                        f"{self.key}:{index}:"
                        f"{source.get('type', '')}:{source.get('id', '')}"
                    ),
                    content=line,
                    token_count=estimate_token_count(line),
                    title=str(source.get("label") or self.title),
                    preview=str(
                        source.get("summary") or source.get("label") or line
                    )[:160],
                    status=str(source.get("status") or self.status),
                    activation_reason=self.activation_reason,
                    source=dict(source),
                    selection_ref=selection_ref_from_source(source),
                    selection_state="required" if required else "automatic",
                    can_exclude=not required,
                )
                for index, line in enumerate(lines)
                for source in [
                    dict(self.sources[index]) if index < len(self.sources) else {}
                ]
            ]
        else:
            source = dict(self.sources[0]) if len(self.sources) == 1 else {}
            items = [
                ContextItem(
                    key=f"{self.key}:section",
                    content=self.content,
                    token_count=self.token_count,
                    title=self.title,
                    preview=self.preview or self.content[:160],
                    status=self.status,
                    activation_reason=self.activation_reason,
                    source=source,
                    selection_ref=(
                        selection_ref_from_source(source) if source else None
                    ),
                    selection_state="required" if required else "automatic",
                    can_exclude=not required,
                )
            ]
        return self.model_copy(update={"items": items})


class ContextBudgetEvent(BaseModel):
    """Budget enforcement event for UI review."""

    section_key: str
    event_type: str
    reason: str
    before_tokens: int
    after_tokens: int
    tier: int


class CompiledContext(BaseModel):
    """Intermediate representation for a compiled context with budget enforcement."""

    sections: list[ContextSection]
    total_tokens: int = 0
    budget_tokens: int = 0
    compiled_at: str = ""
    evicted_keys: list[str] = Field(default_factory=list)
    truncated_keys: list[str] = Field(default_factory=list)
    budget_events: list[ContextBudgetEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    activation_trace: dict[str, Any] = Field(default_factory=dict)
    selection_trace: dict[str, Any] = Field(default_factory=dict)
    excluded_items: list[ContextItem] = Field(default_factory=list)
    omitted_items: list[ContextItem] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)

    @staticmethod
    def _section_with_items(
        section: ContextSection,
        items: list[ContextItem],
        *,
        truncated_reason: str | None = None,
    ) -> ContextSection:
        content = "\n".join(item.content for item in items)
        return section.model_copy(
            update={
                "content": content,
                "token_count": estimate_token_count(content),
                "preview": next(
                    (item.preview for item in items if item.preview),
                    content[:160],
                ),
                "sources": [item.source for item in items if item.source],
                "items": items,
                "truncated_reason": truncated_reason,
            }
        )

    @staticmethod
    def _sources_for_kept_lines(
        section: ContextSection,
        kept_line_count: int,
    ) -> list[dict[str, Any]]:
        """Keep item provenance aligned with one-line-per-item section content."""
        if section.key not in LINE_ITEM_SOURCE_KEYS:
            return list(section.sources)
        return list(section.sources[:kept_line_count])

    def enforce_budget(self) -> CompiledContext:
        """Evict sections by tier to fit within budget_tokens.

        Strategy:
          - P0 is never evicted.
          - Phase 2: Remove entire sections P4 → P3.
          - Phase 3: Per-item truncation on P2 sections.
          - Phase 4: Delta compression on P1 sections.
        """
        if self.budget_tokens <= 0 or self.total_tokens <= self.budget_tokens:
            return self

        sections = [section.materialize_items() for section in self.sections]
        evicted_keys = list(self.evicted_keys)
        truncated_keys = list(self.truncated_keys)
        budget_events = list(self.budget_events)
        omitted_items = list(self.omitted_items)
        blockers = list(self.blockers)

        # Phase 2: Evict entire sections by tier P4 → P3
        for tier in (Tier.P4, Tier.P3):
            current = sum(s.token_count for s in sections)
            if current <= self.budget_tokens:
                break
            removed = [s for s in sections if s.tier == tier]
            sections = [s for s in sections if s.tier != tier]
            for s in removed:
                omitted_items.extend(
                    item.model_copy(
                        update={
                            "selection_state": "omitted",
                            "omission_reason": "超过 token 预算后按低优先级移除",
                        }
                    )
                    for item in s.items
                )
                if s.key not in evicted_keys:
                    evicted_keys.append(s.key)
                budget_events.append(
                    ContextBudgetEvent(
                        section_key=s.key,
                        event_type="evicted",
                        reason="超过 token 预算后按低优先级移除",
                        before_tokens=s.token_count,
                        after_tokens=0,
                        tier=int(s.tier),
                    )
                )

        # Phase 3: P2 per-item truncation
        current = sum(s.token_count for s in sections)
        if current > self.budget_tokens:
            fixed_cost = sum(
                s.token_count for s in sections if s.tier in (Tier.P0, Tier.P1)
            )
            remaining_p2_budget = max(0, self.budget_tokens - fixed_cost)
            new_sections: list[ContextSection] = []
            for s in sections:
                if s.tier != Tier.P2 or not s.truncatable_per_item:
                    new_sections.append(s)
                    continue

                source_items = s.items or [
                    ContextItem(
                        key=f"{s.key}:content",
                        content=s.content,
                        token_count=s.token_count,
                        title=s.title,
                        preview=s.preview,
                        status=s.status,
                        activation_reason=s.activation_reason,
                        can_exclude=s.can_exclude,
                    )
                ]
                kept: list[ContextItem] = []
                for item in source_items:
                    candidate = "\n".join(
                        [*(kept_item.content for kept_item in kept), item.content]
                    )
                    candidate_tokens = estimate_token_count(candidate)
                    if candidate_tokens <= remaining_p2_budget:
                        kept.append(item)
                    else:
                        break

                if not kept:
                    omitted_items.extend(
                        item.model_copy(
                            update={
                                "selection_state": "omitted",
                                "omission_reason": "超过预算后无可用条目预算",
                            }
                        )
                        for item in source_items
                    )
                    if s.key not in evicted_keys:
                        evicted_keys.append(s.key)
                    budget_events.append(
                        ContextBudgetEvent(
                            section_key=s.key,
                            event_type="evicted",
                            reason="超过预算后无可用条目预算",
                            before_tokens=s.token_count,
                            after_tokens=0,
                            tier=int(s.tier),
                        )
                    )
                    continue

                content = "\n".join(item.content for item in kept)
                used = estimate_token_count(content)
                remaining_p2_budget = max(0, remaining_p2_budget - used)
                if len(kept) == len(source_items) and used == s.token_count:
                    new_sections.append(s)
                    continue

                truncated_reason = "超过预算后按条目裁剪"
                new_sections.append(
                    self._section_with_items(
                        s,
                        kept,
                        truncated_reason=truncated_reason,
                    )
                )
                omitted_items.extend(
                    item.model_copy(
                        update={
                            "selection_state": "omitted",
                            "omission_reason": truncated_reason,
                        }
                    )
                    for item in source_items[len(kept) :]
                )
                if s.key not in truncated_keys:
                    truncated_keys.append(s.key)
                budget_events.append(
                    ContextBudgetEvent(
                        section_key=s.key,
                        event_type="truncated",
                        reason=truncated_reason,
                        before_tokens=s.token_count,
                        after_tokens=used,
                        tier=int(s.tier),
                    )
                )
            sections = new_sections

        # Phase 4: P1 Delta compression
        current = sum(s.token_count for s in sections)
        if current > self.budget_tokens:
            new_sections = []
            for s in sections:
                if s.tier == Tier.P1 and current > self.budget_tokens:
                    if any(
                        item.selection_state == "author_pinned" for item in s.items
                    ):
                        new_sections.append(s)
                        continue
                    available_for_section = max(
                        0,
                        self.budget_tokens - (current - s.token_count),
                    )
                    source_items = s.items or [
                        ContextItem(
                            key=f"{s.key}:content",
                            content=s.content,
                            token_count=s.token_count,
                            title=s.title,
                            preview=s.preview,
                            status=s.status,
                            activation_reason=s.activation_reason,
                            can_exclude=s.can_exclude,
                        )
                    ]
                    kept: list[ContextItem] = []
                    for item in source_items:
                        candidate = "\n".join(
                            [*(kept_item.content for kept_item in kept), item.content]
                        )
                        if estimate_token_count(candidate) <= available_for_section:
                            kept.append(item)
                        else:
                            break
                    content = "\n".join(item.content for item in kept)
                    used = estimate_token_count(content)
                    current = current - s.token_count + used
                    new_sections.append(
                        self._section_with_items(
                            s,
                            kept,
                            truncated_reason="超过预算后保留前段摘要",
                        )
                    )
                    omitted_items.extend(
                        item.model_copy(
                            update={
                                "selection_state": "omitted",
                                "omission_reason": "超过预算后保留前段摘要",
                            }
                        )
                        for item in source_items[len(kept) :]
                    )
                    if s.key not in truncated_keys:
                        truncated_keys.append(s.key)
                    budget_events.append(
                        ContextBudgetEvent(
                            section_key=s.key,
                            event_type="truncated",
                            reason="超过预算后保留前段摘要",
                            before_tokens=s.token_count,
                            after_tokens=used,
                            tier=int(s.tier),
                        )
                    )
                else:
                    new_sections.append(s)
            sections = new_sections

        total = sum(s.token_count for s in sections)
        if self.budget_tokens > 0 and total > self.budget_tokens:
            blockers.append("必需资料和作者添加资料超过本次可用容量")
        return CompiledContext(
            sections=sections,
            total_tokens=total,
            budget_tokens=self.budget_tokens,
            compiled_at=self.compiled_at,
            evicted_keys=evicted_keys,
            truncated_keys=truncated_keys,
            budget_events=budget_events,
            warnings=list(self.warnings),
            activation_trace=dict(self.activation_trace),
            selection_trace=dict(self.selection_trace),
            excluded_items=list(self.excluded_items),
            omitted_items=omitted_items,
            blockers=list(dict.fromkeys(blockers)),
        )


def compiled_context_fingerprint(
    compiled: CompiledContext,
    *,
    option_fingerprint: dict[str, Any] | None = None,
) -> str:
    """Hash the exact provider-visible context and its source identities."""

    payload = {
        "options": option_fingerprint or {},
        "sections": [
            {
                "key": section.key,
                "tier": int(section.tier),
                "content": section.content,
                "sources": section.sources,
                "items": [item.model_dump(mode="json") for item in section.items],
                "truncated_reason": section.truncated_reason,
            }
            for section in compiled.sections
        ],
        "budget_tokens": compiled.budget_tokens,
        "activation_trace": compiled.activation_trace,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

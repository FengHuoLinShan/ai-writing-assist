"""CompiledContext IR — Tier-based budget enforcement for context compilation.

Intermediate representation that groups context sections by priority tier
and enforces token budgets through staged eviction.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field

from infrastructure.llm.token_estimation import estimate_token_count


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
    sources: list[dict[str, str]] = Field(default_factory=list)
    can_exclude: bool = True
    excluded: bool = False
    truncated_reason: str | None = None


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

        sections = list(self.sections)
        evicted_keys = list(self.evicted_keys)
        truncated_keys = list(self.truncated_keys)
        budget_events = list(self.budget_events)

        # Phase 2: Evict entire sections by tier P4 → P3
        for tier in (Tier.P4, Tier.P3):
            current = sum(s.token_count for s in sections)
            if current <= self.budget_tokens:
                break
            removed = [s for s in sections if s.tier == tier]
            sections = [s for s in sections if s.tier != tier]
            for s in removed:
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
            budget_for_p2 = max(0, self.budget_tokens - fixed_cost)
            new_sections: list[ContextSection] = []
            for s in sections:
                if s.tier == Tier.P2 and s.truncatable_per_item and budget_for_p2 > 0:
                    items = s.content.split("\n")
                    kept: list[str] = []
                    for item in items:
                        candidate = "\n".join([*kept, item])
                        candidate_tokens = estimate_token_count(candidate)
                        if candidate_tokens <= budget_for_p2:
                            kept.append(item)
                        else:
                            break
                    if kept:
                        content = "\n".join(kept)
                        used = estimate_token_count(content)
                        truncated_reason = "超过预算后按条目裁剪"
                        new_sections.append(
                            ContextSection(
                                key=s.key,
                                tier=s.tier,
                                content=content,
                                token_count=used,
                                truncatable_per_item=True,
                                max_items=s.max_items,
                                title=s.title,
                                preview=s.preview,
                                status=s.status,
                                activation_reason=s.activation_reason,
                                sources=s.sources,
                                can_exclude=s.can_exclude,
                                excluded=s.excluded,
                                truncated_reason=truncated_reason,
                            )
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
                else:
                    new_sections.append(s)
            sections = new_sections

        # Phase 4: P1 Delta compression
        current = sum(s.token_count for s in sections)
        if current > self.budget_tokens:
            new_sections = []
            for s in sections:
                if s.tier == Tier.P1 and current > self.budget_tokens:
                    available_for_section = max(
                        0,
                        self.budget_tokens - (current - s.token_count),
                    )
                    items = s.content.split("\n")
                    kept: list[str] = []
                    for item in items:
                        candidate = "\n".join([*kept, item])
                        if estimate_token_count(candidate) <= available_for_section:
                            kept.append(item)
                        else:
                            break
                    content = "\n".join(kept)
                    used = estimate_token_count(content)
                    current = current - s.token_count + used
                    new_sections.append(
                        ContextSection(
                            key=s.key,
                            tier=s.tier,
                            content=content,
                            token_count=used,
                            truncatable_per_item=s.truncatable_per_item,
                            max_items=s.max_items,
                            title=s.title,
                            preview=s.preview,
                            status=s.status,
                            activation_reason=s.activation_reason,
                            sources=s.sources,
                            can_exclude=s.can_exclude,
                            excluded=s.excluded,
                            truncated_reason="超过预算后保留前段摘要",
                        )
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
        return CompiledContext(
            sections=sections,
            total_tokens=total,
            budget_tokens=self.budget_tokens,
            compiled_at=self.compiled_at,
            evicted_keys=evicted_keys,
            truncated_keys=truncated_keys,
            budget_events=budget_events,
            warnings=list(self.warnings),
        )

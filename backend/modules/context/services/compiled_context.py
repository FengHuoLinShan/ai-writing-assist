"""CompiledContext IR — Tier-based budget enforcement for context compilation.

Intermediate representation that groups context sections by priority tier
and enforces token budgets through staged eviction.
"""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel


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


class CompiledContext(BaseModel):
    """Intermediate representation for a compiled context with budget enforcement."""

    sections: list[ContextSection]
    total_tokens: int = 0
    budget_tokens: int = 0
    compiled_at: str = ""
    evicted_keys: list[str] = []
    truncated_keys: list[str] = []

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
                    used = 0
                    for item in items:
                        item_tokens = len(item) // 4 + 1
                        if used + item_tokens <= budget_for_p2:
                            kept.append(item)
                            used += item_tokens
                        else:
                            break
                    if kept:
                        content = "\n".join(kept)
                        new_sections.append(
                            ContextSection(
                                key=s.key,
                                tier=s.tier,
                                content=content,
                                token_count=used,
                                truncatable_per_item=True,
                                max_items=s.max_items,
                            )
                        )
                        if s.key not in truncated_keys:
                            truncated_keys.append(s.key)
                else:
                    new_sections.append(s)
            sections = new_sections

        # Phase 4: P1 Delta compression
        current = sum(s.token_count for s in sections)
        if current > self.budget_tokens:
            new_sections = []
            for s in sections:
                if s.tier == Tier.P1:
                    items = s.content.split("\n")
                    compressed = False
                    for limit in (15, 10):
                        if len(items) > limit:
                            kept = items[:limit]
                            content = "\n".join(kept)
                            used = len(content) // 4 + 1
                            new_sections.append(
                                ContextSection(
                                    key=s.key,
                                    tier=s.tier,
                                    content=content,
                                    token_count=used,
                                    truncatable_per_item=s.truncatable_per_item,
                                    max_items=s.max_items,
                                )
                            )
                            compressed = True
                            break
                    if not compressed:
                        new_sections.append(s)
                    if compressed and s.key not in truncated_keys:
                        truncated_keys.append(s.key)
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
        )

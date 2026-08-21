"""Versioned Activation Profile lifecycle, matcher, and deterministic dry-run."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.evidence.compilation.models import (
    ContextActivationProfile,
    ContextActivationProfileRevision,
)
from modules.evidence.compilation.schemas import (
    ActivationRule,
    ContextActivationPreviewRequest,
    ContextActivationProfileCreate,
    ContextActivationProfilePublishRequest,
    ContextActivationProfileResponse,
    ContextActivationProfileRevisionResponse,
    ContextActivationProfileUpdate,
)
from shared.utils import parse_uuid

_SOURCE_WEIGHTS = {
    "explicit": 10_000,
    "page_linked": 6_000,
    "relation": 4_000,
}
_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


class ActivationProfileService:
    """Owns atomic profile drafts and immutable published revisions."""

    async def list_profiles(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        include_archived: bool = False,
    ) -> list[ContextActivationProfileResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(ContextActivationProfile).where(
            ContextActivationProfile.novel_id == nid
        )
        if not include_archived:
            stmt = stmt.where(ContextActivationProfile.status != "archived")
        result = await db.execute(
            stmt.order_by(
                ContextActivationProfile.name,
                ContextActivationProfile.profile_key,
            )
        )
        return [self._response(item) for item in result.scalars().all()]

    async def create_profile(
        self,
        db: AsyncSession,
        data: ContextActivationProfileCreate,
    ) -> ContextActivationProfileResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        existing = await db.scalar(
            select(ContextActivationProfile.id).where(
                ContextActivationProfile.novel_id == nid,
                ContextActivationProfile.profile_key == data.profile_key,
            )
        )
        if existing is not None:
            raise ConflictError("Activation Profile key already exists")
        profile = ContextActivationProfile(
            novel_id=nid,
            profile_key=data.profile_key,
            name=data.name,
            description=data.description,
            applicable_actions_json=data.applicable_actions_json,
            rules_json=[rule.model_dump(mode="json") for rule in data.rules_json],
            budget_hints_json=data.budget_hints_json,
            version_number=1,
            status="draft",
            created_by=data.created_by,
            updated_by=data.created_by,
        )
        db.add(profile)
        await db.flush()
        return self._response(profile)

    async def update_profile(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_id: str,
        data: ContextActivationProfileUpdate,
    ) -> ContextActivationProfileResponse:
        profile = await self._get_profile(
            db,
            novel_id,
            profile_id,
            for_update=True,
        )
        if profile.version_number != data.base_version_number:
            raise ConflictError("Activation Profile version conflict")
        payload = data.model_dump(
            mode="json",
            exclude_unset=True,
            exclude={"base_version_number"},
        )
        next_actions = payload.get(
            "applicable_actions_json",
            profile.applicable_actions_json,
        )
        next_rules = payload.get("rules_json", profile.rules_json)
        self._validate_rule_actions(next_rules, next_actions)
        if not any(getattr(profile, key) != value for key, value in payload.items()):
            return self._response(profile)
        for key, value in payload.items():
            setattr(profile, key, value)
        profile.version_number += 1
        if profile.status != "archived":
            profile.status = "draft"
        await db.flush()
        return self._response(profile)

    async def publish_profile(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_id: str,
        data: ContextActivationProfilePublishRequest,
    ) -> ContextActivationProfileResponse:
        profile = await self._get_profile(
            db,
            novel_id,
            profile_id,
            for_update=True,
        )
        if profile.version_number != data.base_version_number:
            raise ConflictError("Activation Profile version conflict")
        if profile.status == "archived":
            raise ConflictError("Archived Activation Profile cannot be published")
        await self._validate_publish_targets(db, profile)
        existing = await db.scalar(
            select(ContextActivationProfileRevision.id).where(
                ContextActivationProfileRevision.profile_id == profile.id,
                ContextActivationProfileRevision.version_number
                == profile.version_number,
            )
        )
        if existing is not None:
            raise ConflictError("Activation Profile version is already published")
        snapshot = self._snapshot(profile)
        db.add(
            ContextActivationProfileRevision(
                novel_id=profile.novel_id,
                profile_id=profile.id,
                version_number=profile.version_number,
                snapshot_json=snapshot,
                rule_hash=self._rule_hash(snapshot["rules_json"]),
                revision_reason=data.revision_reason,
                created_by=data.published_by,
            )
        )
        profile.status = "published"
        profile.updated_by = data.published_by
        await db.flush()
        return self._response(profile)

    async def list_revisions(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_id: str,
    ) -> list[ContextActivationProfileRevisionResponse]:
        profile = await self._get_profile(db, novel_id, profile_id)
        result = await db.execute(
            select(ContextActivationProfileRevision)
            .where(
                ContextActivationProfileRevision.novel_id == profile.novel_id,
                ContextActivationProfileRevision.profile_id == profile.id,
            )
            .order_by(ContextActivationProfileRevision.version_number.desc())
        )
        return [self._revision_response(item) for item in result.scalars().all()]

    async def restore_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_id: str,
        version_number: int,
        *,
        restored_by: str | None = None,
    ) -> ContextActivationProfileResponse:
        profile = await self._get_profile(
            db,
            novel_id,
            profile_id,
            for_update=True,
        )
        revision = await db.scalar(
            select(ContextActivationProfileRevision).where(
                ContextActivationProfileRevision.novel_id == profile.novel_id,
                ContextActivationProfileRevision.profile_id == profile.id,
                ContextActivationProfileRevision.version_number == version_number,
            )
        )
        if revision is None:
            raise NotFoundError("Activation Profile revision not found")
        snapshot = dict(revision.snapshot_json or {})
        for key in (
            "name",
            "description",
            "applicable_actions_json",
            "rules_json",
            "budget_hints_json",
        ):
            setattr(profile, key, snapshot[key])
        profile.version_number += 1
        profile.status = "draft"
        profile.updated_by = restored_by
        await db.flush()
        return self._response(profile)

    async def preview(
        self,
        db: AsyncSession,
        request: ContextActivationPreviewRequest,
    ) -> dict[str, Any]:
        if not request.profile_id or not request.action:
            raise ValidationError(
                "profile_id and action are required for profile preview"
            )
        profile = await self._get_profile(
            db,
            request.novel_id,
            request.profile_id,
        )
        snapshot, rule_hash, version, status = await self._preview_snapshot(
            db,
            profile,
            request.profile_version,
        )
        return await self._evaluate(
            db,
            request,
            profile_id=str(profile.id),
            profile_key=profile.profile_key,
            version_number=version,
            profile_status=status,
            snapshot=snapshot,
            rule_hash=rule_hash,
        )

    async def resolve_published(
        self,
        db: AsyncSession,
        novel_id: str,
        action: str,
        *,
        profile_id: str | None = None,
        version_number: int | None = None,
    ) -> dict[str, Any] | None:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = (
            select(ContextActivationProfileRevision, ContextActivationProfile)
            .join(
                ContextActivationProfile,
                ContextActivationProfile.id
                == ContextActivationProfileRevision.profile_id,
            )
            .where(
                ContextActivationProfileRevision.novel_id == nid,
                ContextActivationProfile.status != "archived",
            )
        )
        if profile_id:
            stmt = stmt.where(
                ContextActivationProfile.id == parse_uuid(profile_id, "profile_id")
            )
        if version_number:
            stmt = stmt.where(
                ContextActivationProfileRevision.version_number == version_number
            )
        result = await db.execute(
            stmt.order_by(
                ContextActivationProfileRevision.created_at.desc(),
                ContextActivationProfileRevision.version_number.desc(),
                ContextActivationProfileRevision.id,
            )
        )
        for revision, profile in result.all():
            snapshot = dict(revision.snapshot_json or {})
            if action in snapshot.get("applicable_actions_json", []):
                return {
                    "profile_id": str(profile.id),
                    "profile_key": profile.profile_key,
                    "version_number": revision.version_number,
                    "rule_hash": revision.rule_hash,
                    "snapshot": snapshot,
                }
        return None

    async def preview_published(
        self,
        db: AsyncSession,
        request: ContextActivationPreviewRequest,
    ) -> dict[str, Any]:
        if not request.action:
            raise ValidationError("action is required for published profile preview")
        resolved = await self.resolve_published(
            db,
            request.novel_id,
            request.action,
            profile_id=request.profile_id,
            version_number=request.profile_version,
        )
        if resolved is None:
            return self._empty_trace(request, warning="activation_profile_not_found")
        return await self._evaluate(
            db,
            request,
            profile_id=resolved["profile_id"],
            profile_key=resolved["profile_key"],
            version_number=resolved["version_number"],
            profile_status="published",
            snapshot=resolved["snapshot"],
            rule_hash=resolved["rule_hash"],
        )

    async def _evaluate(
        self,
        db: AsyncSession,
        request: ContextActivationPreviewRequest,
        *,
        profile_id: str,
        profile_key: str,
        version_number: int,
        profile_status: str,
        snapshot: dict[str, Any],
        rule_hash: str,
    ) -> dict[str, Any]:
        from modules.world import facade as world_facade

        rules = [ActivationRule.model_validate(item) for item in snapshot["rules_json"]]
        rule_evaluations: list[dict[str, Any]] = []
        included_by_hash: dict[str, dict[str, Any]] = {}
        excluded_items: list[dict[str, Any]] = []
        budget_events: list[dict[str, Any]] = []
        warnings: list[str] = []
        for rule in sorted(rules, key=lambda item: item.rule_id):
            matched, matched_clauses, blocked_clauses, excluded_reason = (
                self._match_rule(rule, request)
            )
            evaluation = {
                "rule_id": rule.rule_id,
                "matched": matched,
                "matched_clauses": matched_clauses,
                "blocked_clauses": blocked_clauses,
                "candidate_count": 0,
            }
            rule_evaluations.append(evaluation)
            if not matched:
                excluded_items.extend(
                    self._rule_target_exclusions(rule, excluded_reason)
                )
                continue
            if request.reveal_mode in {"reader", "character"}:
                reason = (
                    "reader_cutoff"
                    if request.reveal_mode == "reader"
                    else "character_knowledge_hidden"
                )
                evaluation["blocked_clauses"] = [reason]
                evaluation["matched"] = False
                excluded_items.extend(self._rule_target_exclusions(rule, reason))
                continue
            resolution = await world_facade.get_world_bible_projection_candidates(
                db,
                request.novel_id,
                rule.select.target_refs,
                projection_type="context_brief",
                expand_page_links=rule.select.expand_page_links,
                relation_types=rule.select.relation_types,
                max_depth=rule.select.max_depth,
                reveal_mode=request.reveal_mode,
            )
            candidates = [
                self._candidate_dict(item, rule)
                for item in resolution.items
            ]
            evaluation["candidate_count"] = len(candidates)
            for excluded in resolution.excluded_items:
                excluded_items.append(
                    {
                        **self._candidate_dict(excluded, rule),
                        "decision": "excluded",
                        "excluded_reason": excluded.excluded_reason,
                    }
                )
            ranked = sorted(
                candidates,
                key=lambda item: (-item["score"], item["target_hash"]),
            )
            used_tokens = 0
            for index, item in enumerate(ranked):
                if index >= rule.rank.top_k:
                    excluded_items.append(
                        {**item, "decision": "excluded", "excluded_reason": "rule_top_k"}
                    )
                    continue
                if used_tokens + item["token_before"] > rule.rank.token_cap:
                    excluded_items.append(
                        {
                            **item,
                            "decision": "excluded",
                            "excluded_reason": "rule_token_cap",
                        }
                    )
                    budget_events.append(
                        {
                            "rule_id": rule.rule_id,
                            "target_hash": item["target_hash"],
                            "event_type": "evicted",
                            "reason": "rule_token_cap",
                            "before_tokens": item["token_before"],
                            "after_tokens": 0,
                        }
                    )
                    continue
                used_tokens += item["token_before"]
                existing = included_by_hash.get(item["target_hash"])
                if existing is None or item["score"] > existing["score"]:
                    included_by_hash[item["target_hash"]] = item
                for warning in item.pop("warnings", []):
                    if warning not in warnings:
                        warnings.append(warning)

        ranked_items = sorted(
            included_by_hash.values(),
            key=lambda item: (-item["score"], item["target_hash"]),
        )
        for item in ranked_items[request.top_k :]:
            excluded_items.append(
                {**item, "decision": "excluded", "excluded_reason": "rule_top_k"}
            )
        items = ranked_items[: request.top_k]
        return {
            "novel_id": request.novel_id,
            "depth": request.depth,
            "top_k": request.top_k,
            "profile": {
                "id": profile_id,
                "profile_key": profile_key,
                "version": version_number,
                "status": profile_status,
                "rule_hash": rule_hash,
            },
            "rule_evaluations": rule_evaluations,
            "items": items,
            "excluded_items": excluded_items,
            "budget_events": budget_events,
            "warnings": warnings,
        }

    async def _preview_snapshot(
        self,
        db: AsyncSession,
        profile: ContextActivationProfile,
        version_number: int | None,
    ) -> tuple[dict[str, Any], str, int, str]:
        if version_number is None or version_number == profile.version_number:
            snapshot = self._snapshot(profile)
            return (
                snapshot,
                self._rule_hash(snapshot["rules_json"]),
                profile.version_number,
                profile.status,
            )
        revision = await db.scalar(
            select(ContextActivationProfileRevision).where(
                ContextActivationProfileRevision.novel_id == profile.novel_id,
                ContextActivationProfileRevision.profile_id == profile.id,
                ContextActivationProfileRevision.version_number == version_number,
            )
        )
        if revision is None:
            raise NotFoundError("Activation Profile revision not found")
        return (
            dict(revision.snapshot_json or {}),
            revision.rule_hash,
            revision.version_number,
            "published",
        )

    async def _validate_publish_targets(
        self,
        db: AsyncSession,
        profile: ContextActivationProfile,
    ) -> None:
        from modules.world import facade as world_facade

        for raw_rule in profile.rules_json:
            rule = ActivationRule.model_validate(raw_rule)
            resolution = await world_facade.get_world_bible_projection_candidates(
                db,
                str(profile.novel_id),
                rule.select.target_refs,
                max_depth=0,
            )
            if resolution.excluded_items:
                raise ValidationError(
                    "Activation Profile contains missing or unadopted targets"
                )

    @staticmethod
    def _match_rule(
        rule: ActivationRule,
        request: ContextActivationPreviewRequest,
    ) -> tuple[bool, list[str], list[str], str]:
        if not rule.enabled:
            return False, [], ["rule_disabled"], "scope_mismatch"
        if request.action not in rule.scope.actions:
            return False, [], ["action"], "scope_mismatch"
        if request.reveal_mode not in rule.scope.modes:
            return False, [], ["mode"], "scope_mismatch"
        source_values = {
            "task_text": request.task_text,
            "current_scene_text": request.current_scene_text,
            "previous_scene_briefs": "\n".join(request.previous_scene_briefs),
            "explicit_focus": request.explicit_focus,
        }
        haystack = "\n".join(
            source_values[source] for source in rule.scope.match_sources
        )
        positive = [
            ActivationProfileService._term_matches(term, haystack, rule.match.mode)
            for term in rule.match.positive_terms
        ]
        positive_matched = (
            all(positive) if rule.match.positive_logic == "all" else any(positive)
        )
        matched_clauses = [
            f"positive:{rule.match.positive_logic}:{term}"
            for term, matched in zip(rule.match.positive_terms, positive, strict=True)
            if matched
        ]
        if not positive_matched:
            return (
                False,
                matched_clauses,
                ["positive_not_matched"],
                "positive_not_matched",
            )
        negative = [
            ActivationProfileService._term_matches(term, haystack, rule.match.mode)
            for term in rule.match.negative_terms
        ]
        negative_matched = bool(negative) and (
            all(negative) if rule.match.negative_logic == "all" else any(negative)
        )
        if negative_matched:
            blocked = [
                f"negative:{rule.match.negative_logic}:{term}"
                for term, matched in zip(rule.match.negative_terms, negative, strict=True)
                if matched
            ]
            return False, matched_clauses, blocked, "negative_matched"
        return True, matched_clauses, [], ""

    @staticmethod
    def _term_matches(term: str, text: str, mode: str) -> bool:
        needle = ActivationProfileService._normalize_text(term)
        haystack = ActivationProfileService._normalize_text(text)
        if mode == "normalized_substring" or _CJK_RE.search(needle):
            return needle in haystack
        return bool(
            re.search(
                rf"(?<!\w){re.escape(needle)}(?!\w)",
                haystack,
            )
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    @staticmethod
    def _candidate_dict(item, rule: ActivationRule) -> dict[str, Any]:
        payload = asdict(item)
        source_weight = _SOURCE_WEIGHTS.get(item.source_kind, 0)
        score = rule.rank.priority * 10_000 + source_weight + int(
            item.importance * 1000
        )
        return {
            "target": item.target,
            "target_hash": item.target_hash,
            "label": item.label,
            "status": item.status,
            "content": item.content,
            "source": item.source_kind,
            "source_version": item.source_version,
            "source_hash": item.source_hash,
            "decision": "included" if not item.excluded_reason else "excluded",
            "activation_reason": f"rule:{rule.rule_id} -> {item.source_kind}",
            "score": score,
            "token_before": item.token_count,
            "token_after": item.token_count,
            "expanded_from": item.expanded_from,
            "excluded_reason": item.excluded_reason,
            "fallback": item.fallback,
            "warnings": payload["warnings"],
            "rule_id": rule.rule_id,
        }

    @staticmethod
    def _rule_target_exclusions(
        rule: ActivationRule,
        reason: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "target": target,
                "target_hash": "",
                "label": target["target_id"],
                "status": "not_evaluated",
                "content": "",
                "source": "rule",
                "decision": "excluded",
                "activation_reason": f"rule:{rule.rule_id}",
                "score": rule.rank.priority * 10_000,
                "token_before": 0,
                "token_after": 0,
                "expanded_from": None,
                "excluded_reason": reason,
                "rule_id": rule.rule_id,
            }
            for target in rule.select.target_refs
        ]

    @staticmethod
    def _validate_rule_actions(
        rules: list[dict[str, Any]],
        profile_actions: list[str],
    ) -> None:
        allowed = set(profile_actions)
        for raw_rule in rules:
            rule = ActivationRule.model_validate(raw_rule)
            if not set(rule.scope.actions).issubset(allowed):
                raise ValidationError("Rule actions must be declared by the profile")

    async def _get_profile(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_id: str,
        *,
        for_update: bool = False,
    ) -> ContextActivationProfile:
        nid = parse_uuid(novel_id, "novel_id")
        pid = parse_uuid(profile_id, "profile_id")
        stmt = select(ContextActivationProfile).where(
            ContextActivationProfile.novel_id == nid,
            ContextActivationProfile.id == pid,
        )
        if for_update:
            stmt = stmt.with_for_update()
        profile = await db.scalar(stmt)
        if profile is None:
            raise NotFoundError("Activation Profile not found")
        return profile

    @staticmethod
    def _snapshot(profile: ContextActivationProfile) -> dict[str, Any]:
        return {
            "profile_key": profile.profile_key,
            "name": profile.name,
            "description": profile.description,
            "applicable_actions_json": profile.applicable_actions_json,
            "rules_json": profile.rules_json,
            "budget_hints_json": profile.budget_hints_json,
            "version_number": profile.version_number,
        }

    @staticmethod
    def _rule_hash(rules: list[dict[str, Any]]) -> str:
        encoded = json.dumps(
            rules,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _response(
        profile: ContextActivationProfile,
    ) -> ContextActivationProfileResponse:
        return ContextActivationProfileResponse(
            id=str(profile.id),
            novel_id=str(profile.novel_id),
            profile_key=profile.profile_key,
            name=profile.name,
            description=profile.description,
            applicable_actions_json=profile.applicable_actions_json,
            rules_json=profile.rules_json,
            budget_hints_json=profile.budget_hints_json,
            version_number=profile.version_number,
            status=profile.status,
            created_by=profile.created_by,
            updated_by=profile.updated_by,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    @staticmethod
    def _revision_response(
        revision: ContextActivationProfileRevision,
    ) -> ContextActivationProfileRevisionResponse:
        return ContextActivationProfileRevisionResponse(
            id=str(revision.id),
            novel_id=str(revision.novel_id),
            profile_id=str(revision.profile_id),
            version_number=revision.version_number,
            snapshot_json=revision.snapshot_json,
            rule_hash=revision.rule_hash,
            revision_reason=revision.revision_reason,
            created_by=revision.created_by,
            created_at=revision.created_at,
        )

    @staticmethod
    def _empty_trace(
        request: ContextActivationPreviewRequest,
        *,
        warning: str,
    ) -> dict[str, Any]:
        return {
            "novel_id": request.novel_id,
            "depth": request.depth,
            "top_k": request.top_k,
            "profile": None,
            "rule_evaluations": [],
            "items": [],
            "excluded_items": [],
            "budget_events": [],
            "warnings": [warning],
        }


__all__ = ["ActivationProfileService"]

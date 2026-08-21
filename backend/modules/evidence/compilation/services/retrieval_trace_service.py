"""Persistence and aggregation for context retrieval diagnostics."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import ContextRetrievalTraceContract
from modules.evidence.compilation.repositories import ContextRetrievalTraceRepository


class RetrievalTraceService:
    def __init__(self, repository: ContextRetrievalTraceRepository | None = None) -> None:
        self._repo = repository or ContextRetrievalTraceRepository()

    async def record(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        payload: dict,
    ) -> ContextRetrievalTraceContract:
        record = await self._repo.create(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            content_mode=str(payload.get("content_mode") or "canonical"),
            consumer_action=str(payload.get("consumer_action") or "generic"),
            retrieval_purpose=str(payload.get("retrieval_purpose") or "generic_context"),
            reveal_mode=str(payload.get("reveal_mode") or "author"),
            scene_id=payload.get("scene_id"),
            chapter_index=payload.get("chapter_index"),
            plan_version=str(payload.get("plan_version") or "direct-v1"),
            plan_hash=str(payload.get("plan_hash") or ""),
            clause_summaries=list(payload.get("clause_summaries") or []),
            candidate_count=max(0, int(payload.get("candidate_count") or 0)),
            unique_count=max(0, int(payload.get("unique_count") or 0)),
            hydrated_count=max(0, int(payload.get("hydrated_count") or 0)),
            drop_counts=_normalize_drop_counts(payload.get("drop_counts")),
            safe_empty_reason=_normalize_diagnostic_code(
                payload.get("safe_empty_reason")
            ),
            degraded=bool(payload.get("degraded")),
            warning_codes=list(dict.fromkeys(payload.get("warning_codes") or [])),
            latency_metadata={
                str(key): round(max(0.0, float(value or 0.0)), 3)
                for key, value in dict(payload.get("latency_metadata") or {}).items()
            },
        )
        return _to_contract(record)

    async def list(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        content_mode: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContextRetrievalTraceContract]:
        records = await self._repo.list_for_novel(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            content_mode=content_mode,
            limit=max(1, min(limit, 500)),
            offset=max(0, offset),
        )
        return [_to_contract(record) for record in records]

    async def summarize(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        content_mode: str,
        window_hours: int,
    ) -> dict:
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        summary = await self._repo.aggregate_for_novel(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            content_mode=content_mode,
            since=since,
        )
        query_count = summary["query_count"]
        degraded_count = summary["degraded_count"]
        return {
            "query_count": query_count,
            "degraded_count": degraded_count,
            "degraded_rate": (
                round(degraded_count / query_count, 4) if query_count else None
            ),
            "empty_count": summary["empty_count"],
            "drop_counts": dict(sorted(summary["drop_counts"].items())),
            "safe_empty_reasons": dict(sorted(summary["safe_empty_reasons"].items())),
            "unclassified_empty_count": summary["unclassified_empty_count"],
        }

    async def prune(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        retention_days: int = 30,
        retain_latest: int = 10_000,
        dry_run: bool = True,
    ) -> int:
        return await self._repo.prune(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            retention_days=max(1, retention_days),
            retain_latest=max(0, retain_latest),
            dry_run=dry_run,
        )


def _to_contract(record) -> ContextRetrievalTraceContract:
    return ContextRetrievalTraceContract(
        id=str(record.id),
        novel_id=str(record.novel_id),
        content_mode=record.content_mode,
        consumer_action=record.consumer_action,
        retrieval_purpose=record.retrieval_purpose,
        reveal_mode=record.reveal_mode,
        plan_version=record.plan_version,
        plan_hash=record.plan_hash,
        clause_summaries=list(record.clause_summaries or []),
        scene_id=record.scene_id,
        chapter_index=record.chapter_index,
        candidate_count=record.candidate_count,
        unique_count=record.unique_count,
        hydrated_count=record.hydrated_count,
        drop_counts=dict(record.drop_counts or {}),
        safe_empty_reason=record.safe_empty_reason,
        degraded=record.degraded,
        warning_codes=list(record.warning_codes or []),
        latency_metadata=dict(record.latency_metadata or {}),
        created_at=record.created_at.isoformat(),
    )


def contract_dict(contract: ContextRetrievalTraceContract) -> dict:
    return asdict(contract)


_DIAGNOSTIC_CODE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_MAX_DIAGNOSTIC_COUNT = 999_999_999_999_999_999


def _normalize_diagnostic_code(value: object) -> str | None:
    if not isinstance(value, str) or not _DIAGNOSTIC_CODE_PATTERN.fullmatch(value):
        return None
    return value


def _normalize_drop_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, int] = {}
    for raw_key, raw_count in value.items():
        key = _normalize_diagnostic_code(str(raw_key))
        if key is None:
            continue
        try:
            count = int(raw_count or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= count <= _MAX_DIAGNOSTIC_COUNT:
            normalized[key] = count
    return normalized

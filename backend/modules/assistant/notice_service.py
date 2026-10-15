"""Registry-only aggregation and CAS-backed presentation dispositions."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.database import get_manager
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.assistant.notice_contracts import (
    NoticeDispositionRequest,
    NoticeItem,
    NoticeListResponse,
    NoticeOperationCategoryMute,
    NoticeOperationDisposition,
    NoticeScope,
    NoticeSourceUnavailable,
)
from modules.assistant.notice_models import (
    AssistantNoticeCategoryMute,
    AssistantNoticeDisposition,
)

logger = logging.getLogger(__name__)


def _sources() -> dict[str, Any]:
    # The composition root registers this typed DI port; its ServiceKey is owned
    # by app/bootstrap and core/service_keys.
    return get("assistant.notice_sources")


def _public_item(raw: dict[str, Any]) -> NoticeItem:
    public = {key: raw[key] for key in NoticeItem.model_fields if key in raw}
    domain_ref = raw.get("disposition_ref") or {}
    if raw.get("status") in {"unread", "read", "snoozed", "ignored"}:
        public["status"] = raw["status"]
    elif domain_ref.get("status") in {"unread", "read", "snoozed", "ignored"}:
        public["status"] = domain_ref["status"]
    if isinstance(raw.get("row_version"), int):
        public["row_version"] = raw["row_version"]
    elif isinstance(domain_ref.get("row_version"), int):
        public["row_version"] = domain_ref["row_version"]
    return NoticeItem.model_validate(public)


async def _read_source(source: Any, novel_id: str, scope: dict[str, object]):
    async with get_manager().session_factory() as source_db:
        return await asyncio.wait_for(
            source.list_notices(source_db, novel_id, scope),
            timeout=source.timeout_seconds,
        )


async def list_notices(
    db: AsyncSession,
    novel_id: str,
    scope: NoticeScope,
    *,
    sources: dict[str, Any] | None = None,
) -> NoticeListResponse:
    registry = sources if sources is not None else _sources()
    scope_json = scope.model_dump(mode="json")
    tasks = {
        source_id: asyncio.create_task(_read_source(source, novel_id, scope_json))
        for source_id, source in registry.items()
    }
    outcomes = await asyncio.gather(*tasks.values(), return_exceptions=True)
    collected: list[tuple[NoticeItem, dict[str, Any]]] = []
    unavailable: list[NoticeSourceUnavailable] = []
    for (source_id, source), outcome in zip(registry.items(), outcomes, strict=True):
        if isinstance(outcome, (Exception, asyncio.CancelledError)):
            logger.warning(
                "Unified notice source %s unavailable (%s)",
                source_id,
                type(outcome).__name__,
            )
            unavailable.append(
                NoticeSourceUnavailable(
                    source_id=source_id,
                    label=source.label,
                )
            )
            continue
        try:
            values = outcome
            if not isinstance(values, list):
                raise TypeError("Notice source must return a list")
            source_items = []
            seen_keys: set[str] = set()
            for raw in values:
                if not isinstance(raw, dict) or raw.get("source_id") != source_id:
                    raise ValueError("Notice source returned an invalid item")
                item = _public_item(raw)
                if item.notice_key in seen_keys:
                    raise ValueError("Notice source returned a duplicate key")
                seen_keys.add(item.notice_key)
                source_items.append((item, raw))
            collected.extend(source_items)
        except Exception as error:
            logger.warning(
                "Unified notice source %s returned invalid items (%s)",
                source_id,
                type(error).__name__,
            )
            unavailable.append(
                NoticeSourceUnavailable(source_id=source_id, label=source.label)
            )

    novel_uuid = UUID(str(novel_id))
    keys = list(dict.fromkeys(item.notice_key for item, _raw in collected))
    dispositions = (
        (
            await db.scalars(
                select(AssistantNoticeDisposition).where(
                    AssistantNoticeDisposition.novel_id == novel_uuid,
                    AssistantNoticeDisposition.notice_key.in_(keys),
                )
            )
        ).all()
        if keys
        else []
    )
    disposition_by_key = {
        (row.source_id, row.notice_key, row.basis_fingerprint): row
        for row in dispositions
    }
    mutes = (
        await db.scalars(
            select(AssistantNoticeCategoryMute).where(
                AssistantNoticeCategoryMute.novel_id == novel_uuid,
                AssistantNoticeCategoryMute.is_muted.is_(True),
            )
        )
    ).all()
    muted_pairs = {(row.source_id, row.category) for row in mutes}
    now = datetime.now(UTC)
    visible: list[NoticeItem] = []
    for item, raw in collected:
        if (item.source_id, item.category) in muted_pairs:
            continue
        domain_ref = raw.get("disposition_ref") or {}
        generic = disposition_by_key.get(
            (item.source_id, item.notice_key, item.basis_fingerprint)
        )
        if domain_ref.get("status") == "dismissed" or item.status == "ignored":
            continue
        if generic is not None:
            if generic.status == "ignored":
                continue
            if (
                generic.status == "snoozed"
                and generic.wake_at is not None
                and _aware(generic.wake_at) > now
            ):
                continue
            item = item.model_copy(
                update={
                    "status": "unread"
                    if generic.status == "snoozed"
                    and generic.wake_at is not None
                    and _aware(generic.wake_at) <= now
                    else generic.status,
                    "wake_at": generic.wake_at,
                    "row_version": generic.row_version,
                }
            )
        elif (
            item.status == "snoozed"
            and item.wake_at is not None
            and _aware(item.wake_at) <= now
        ):
            item = item.model_copy(update={"status": "unread"})
        elif (
            item.status == "snoozed"
            and item.wake_at is not None
            and _aware(item.wake_at) > now
        ):
            continue
        visible.append(item)
    visible.sort(
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2, "info": 3}[item.severity],
            item.source_id,
            item.category,
            str(item.target.get("chapter_index") or ""),
            str(item.target.get("scene_id") or ""),
            item.notice_key,
        )
    )
    return NoticeListResponse(
        novel_id=novel_uuid,
        scope=scope,
        items=visible,
        unavailable_sources=unavailable,
        muted_categories=[
            {
                "source_id": row.source_id,
                "category": row.category,
                "row_version": row.row_version,
            }
            for row in mutes
        ],
        partial=bool(unavailable),
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _find_current_item(
    db: AsyncSession,
    novel_id: str,
    source_id: str,
    notice_key: str,
    scope: NoticeScope,
    basis_fingerprint: str,
    *,
    sources: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    registry = sources if sources is not None else _sources()
    source = registry.get(source_id)
    if source is None:
        raise NotFoundError("提醒来源不存在")
    try:
        values = await asyncio.wait_for(
            source.list_notices(db, novel_id, scope.model_dump(mode="json")),
            timeout=source.timeout_seconds,
        )
    except Exception as error:
        raise ConflictError(
            "提醒来源暂不可读取，请刷新后重试", code="NOTICE_UNAVAILABLE"
        ) from error
    matches = [
        item
        for item in values
        if isinstance(item, dict) and item.get("notice_key") == notice_key
    ]
    if len(matches) != 1 or matches[0].get("basis_fingerprint") != basis_fingerprint:
        raise ConflictError("提醒依据已变化，请重新读取", code="NOTICE_STALE")
    return source, matches[0]


async def apply_disposition(
    db: AsyncSession,
    request: NoticeDispositionRequest,
    *,
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source, item = await _find_current_item(
        db,
        str(request.novel_id),
        request.source_id,
        request.notice_key,
        request.scope,
        request.basis_fingerprint,
        sources=sources,
    )
    reference = item.get("disposition_ref") or {}
    expected_version = reference.get("row_version", reference.get("notice_version"))
    if not isinstance(expected_version, int):
        current = await db.scalar(
            select(AssistantNoticeDisposition).where(
                AssistantNoticeDisposition.novel_id == request.novel_id,
                AssistantNoticeDisposition.source_id == request.source_id,
                AssistantNoticeDisposition.notice_key == request.notice_key,
                AssistantNoticeDisposition.basis_fingerprint == request.basis_fingerprint,
            )
        )
        expected_version = current.row_version if current else 0
    if request.expected_row_version != expected_version:
        raise ConflictError(
            "提醒处置已被其他页面更新，请刷新", code="NOTICE_VERSION_CONFLICT"
        )
    wake_at = (
        datetime.now(UTC) + timedelta(hours=request.duration_hours)
        if request.action == "snooze" and request.duration_hours is not None
        else None
    )
    if source.decide is not None:
        result = await source.decide(
            db, str(request.novel_id), item, request.action, wake_at
        )
        if result is not None:
            return {"status": result.get("status", request.action), "domain": result}

    novel_uuid = UUID(str(request.novel_id))
    disposition_status = {"snooze": "snoozed", "ignore": "ignored"}.get(
        request.action, request.action
    )
    row = await db.scalar(
        select(AssistantNoticeDisposition)
        .where(
            AssistantNoticeDisposition.novel_id == novel_uuid,
            AssistantNoticeDisposition.source_id == request.source_id,
            AssistantNoticeDisposition.notice_key == request.notice_key,
            AssistantNoticeDisposition.basis_fingerprint == request.basis_fingerprint,
        )
        .with_for_update()
    )
    if row is None:
        if request.expected_row_version != 0:
            raise ConflictError("提醒处置已变化，请刷新", code="NOTICE_VERSION_CONFLICT")
        row = AssistantNoticeDisposition(
            id=uuid4(),
            novel_id=novel_uuid,
            source_id=request.source_id,
            notice_key=request.notice_key,
            basis_fingerprint=request.basis_fingerprint,
            status=disposition_status,
            wake_at=wake_at,
            row_version=1,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError as error:
            raise ConflictError(
                "提醒处置已被其他页面更新，请刷新", code="NOTICE_VERSION_CONFLICT"
            ) from error
    else:
        if row.row_version != request.expected_row_version:
            raise ConflictError(
                "提醒处置已被其他页面更新，请刷新", code="NOTICE_VERSION_CONFLICT"
            )
        result = await db.execute(
            update(AssistantNoticeDisposition)
            .where(
                AssistantNoticeDisposition.novel_id == novel_uuid,
                AssistantNoticeDisposition.source_id == request.source_id,
                AssistantNoticeDisposition.id == row.id,
                AssistantNoticeDisposition.row_version == request.expected_row_version,
            )
            .values(
                status=disposition_status,
                wake_at=wake_at,
                row_version=request.expected_row_version + 1,
                updated_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ConflictError(
                "提醒处置已被其他页面更新，请刷新", code="NOTICE_VERSION_CONFLICT"
            )
        row.row_version = request.expected_row_version + 1
        row.status = disposition_status
        row.wake_at = wake_at
    await db.flush()
    return {"status": row.status, "row_version": row.row_version, "wake_at": row.wake_at}


async def set_category_mute(
    db: AsyncSession,
    novel_id: str,
    source_id: str,
    category: str,
    expected_row_version: int,
    *,
    muted: bool,
    sources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = sources if sources is not None else _sources()
    if source_id not in registry:
        raise NotFoundError("提醒来源不存在")
    novel_uuid = UUID(str(novel_id))
    row = await db.scalar(
        select(AssistantNoticeCategoryMute)
        .where(
            AssistantNoticeCategoryMute.novel_id == novel_uuid,
            AssistantNoticeCategoryMute.source_id == source_id,
            AssistantNoticeCategoryMute.category == category,
        )
        .with_for_update()
    )
    if row is None:
        if not muted:
            raise NotFoundError("静默设置不存在")
        if expected_row_version != 0:
            raise ConflictError(
                "提醒类别设置已变化，请刷新", code="NOTICE_VERSION_CONFLICT"
            )
        row = AssistantNoticeCategoryMute(
            id=uuid4(),
            novel_id=novel_uuid,
            source_id=source_id,
            category=category,
            is_muted=muted,
            row_version=1,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError as error:
            raise ConflictError(
                "提醒类别设置已变化，请刷新", code="NOTICE_VERSION_CONFLICT"
            ) from error
    else:
        if row.row_version != expected_row_version:
            raise ConflictError(
                "提醒类别设置已变化，请刷新", code="NOTICE_VERSION_CONFLICT"
            )
        if row.is_muted != muted:
            result = await db.execute(
                update(AssistantNoticeCategoryMute)
                .where(
                    AssistantNoticeCategoryMute.novel_id == novel_uuid,
                    AssistantNoticeCategoryMute.id == row.id,
                    AssistantNoticeCategoryMute.row_version == expected_row_version,
                )
                .values(
                    is_muted=muted,
                    row_version=expected_row_version + 1,
                    updated_at=datetime.now(UTC),
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise ConflictError(
                    "提醒类别设置已变化，请刷新", code="NOTICE_VERSION_CONFLICT"
                )
            row.is_muted = muted
            row.row_version = expected_row_version + 1
    await db.flush()
    return {
        "source_id": row.source_id,
        "category": row.category,
        "is_muted": row.is_muted,
        "row_version": row.row_version,
    }


async def prepare_disposition(
    db: AsyncSession,
    novel_id: str,
    args: NoticeOperationDisposition,
    *,
    context=None,
) -> dict[str, Any]:
    if context is None:
        raise ValidationError("处理提醒需要作者确认")
    if context.work.scope != "project":
        raise ValidationError("统一提醒仅适用于作者项目")
    source, item = await _find_current_item(
        db,
        novel_id,
        args.source_id,
        args.notice_key,
        args.scope,
        args.basis_fingerprint,
    )
    domain_ref = item.get("disposition_ref") or {}
    current = domain_ref.get("row_version", domain_ref.get("notice_version"))
    if not isinstance(current, int):
        row = await db.scalar(
            select(AssistantNoticeDisposition).where(
                AssistantNoticeDisposition.novel_id == UUID(str(novel_id)),
                AssistantNoticeDisposition.source_id == args.source_id,
                AssistantNoticeDisposition.notice_key == args.notice_key,
                AssistantNoticeDisposition.basis_fingerprint == args.basis_fingerprint,
            )
        )
        current = row.row_version if row else 0
    if args.expected_row_version != current:
        raise ConflictError("提醒处置已变化，请重新读取", code="NOTICE_VERSION_CONFLICT")
    return {
        "notice_key": args.notice_key,
        "basis_fingerprint": args.basis_fingerprint,
        "before": item.get("status") or domain_ref.get("status") or "unread",
        "after": args.action,
        "effect": "只更新这条提醒的展示处置，不修改提醒来源中的业务结论",
        "source_id": args.source_id,
        "row_version": current,
    }


async def apply_disposition_operation(
    db: AsyncSession,
    novel_id: str,
    args: NoticeOperationDisposition,
    preview: dict[str, Any],
    *,
    context=None,
) -> dict[str, Any]:
    if await prepare_disposition(db, novel_id, args, context=context) != preview:
        raise ConflictError("提醒处置已变化，请重新确认", code="NOTICE_STALE")
    request = NoticeDispositionRequest(
        novel_id=UUID(str(novel_id)),
        source_id=args.source_id,
        notice_key=args.notice_key,
        basis_fingerprint=args.basis_fingerprint,
        scope=args.scope,
        expected_row_version=args.expected_row_version,
        action=args.action,
        duration_hours=args.duration_hours,
    )
    return await apply_disposition(db, request)


async def prepare_category_mute(
    db: AsyncSession,
    novel_id: str,
    args: NoticeOperationCategoryMute,
    *,
    context=None,
) -> dict[str, Any]:
    if context is None or context.work.scope != "project":
        raise ValidationError("静默提醒类别需要作者项目授权")
    if args.source_id not in _sources():
        raise NotFoundError("提醒来源不存在")
    row = await db.scalar(
        select(AssistantNoticeCategoryMute).where(
            AssistantNoticeCategoryMute.novel_id == UUID(str(novel_id)),
            AssistantNoticeCategoryMute.source_id == args.source_id,
            AssistantNoticeCategoryMute.category == args.category,
        )
    )
    current = row.row_version if row else 0
    if current != args.expected_row_version:
        raise ConflictError(
            "提醒类别设置已变化，请重新读取", code="NOTICE_VERSION_CONFLICT"
        )
    return {
        "source_id": args.source_id,
        "category": args.category,
        "before": row.is_muted if row else False,
        "after": True,
        "effect": "静默该来源中的同类提醒，直到作者取消",
        "row_version": current,
    }


async def apply_category_mute_operation(
    db: AsyncSession,
    novel_id: str,
    args: NoticeOperationCategoryMute,
    preview: dict[str, Any],
    *,
    context=None,
) -> dict[str, Any]:
    if await prepare_category_mute(db, novel_id, args, context=context) != preview:
        raise ConflictError("提醒类别设置已变化，请重新确认", code="NOTICE_STALE")
    return await set_category_mute(
        db,
        novel_id,
        args.source_id,
        args.category,
        args.expected_row_version,
        muted=True,
    )


async def prepare_category_unmute(
    db: AsyncSession,
    novel_id: str,
    args: NoticeOperationCategoryMute,
    *,
    context=None,
) -> dict[str, Any]:
    if context is None or context.work.scope != "project":
        raise ValidationError("取消静默需要作者项目授权")
    if args.source_id not in _sources():
        raise NotFoundError("提醒来源不存在")
    row = await db.scalar(
        select(AssistantNoticeCategoryMute).where(
            AssistantNoticeCategoryMute.novel_id == UUID(str(novel_id)),
            AssistantNoticeCategoryMute.source_id == args.source_id,
            AssistantNoticeCategoryMute.category == args.category,
        )
    )
    current = row.row_version if row else 0
    if row is None or not row.is_muted:
        raise NotFoundError("静默设置不存在")
    if current != args.expected_row_version:
        raise ConflictError(
            "提醒类别设置已变化，请重新读取", code="NOTICE_VERSION_CONFLICT"
        )
    return {
        "source_id": args.source_id,
        "category": args.category,
        "before": True,
        "after": False,
        "effect": "恢复该来源中的同类提醒",
        "row_version": current,
    }


async def apply_category_unmute_operation(
    db: AsyncSession,
    novel_id: str,
    args: NoticeOperationCategoryMute,
    preview: dict[str, Any],
    *,
    context=None,
) -> dict[str, Any]:
    if await prepare_category_unmute(db, novel_id, args, context=context) != preview:
        raise ConflictError("提醒类别设置已变化，请重新确认", code="NOTICE_STALE")
    return await set_category_mute(
        db,
        novel_id,
        args.source_id,
        args.category,
        args.expected_row_version,
        muted=False,
    )


async def _operation_disposition_preview(db, novel_id, args, *, context=None):
    return await prepare_disposition(db, novel_id, args, context=context)


async def _operation_disposition_apply(db, novel_id, args, preview, *, context=None):
    return await apply_disposition_operation(db, novel_id, args, preview, context=context)


async def _operation_mute_preview(db, novel_id, args, *, context=None):
    return await prepare_category_mute(db, novel_id, args, context=context)


async def _operation_mute_apply(db, novel_id, args, preview, *, context=None):
    return await apply_category_mute_operation(
        db, novel_id, args, preview, context=context
    )


async def _operation_unmute_preview(db, novel_id, args, *, context=None):
    return await prepare_category_unmute(db, novel_id, args, context=context)


async def _operation_unmute_apply(db, novel_id, args, preview, *, context=None):
    return await apply_category_unmute_operation(
        db, novel_id, args, preview, context=context
    )


OPERATIONS_SPEC = {
    "assistant.notice.set_disposition": {
        "label": "处理提醒",
        "schema": NoticeOperationDisposition,
        "prepare": _operation_disposition_preview,
        "apply": _operation_disposition_apply,
    },
    "assistant.notice.mute_category": {
        "label": "静默这一类提醒",
        "schema": NoticeOperationCategoryMute,
        "prepare": _operation_mute_preview,
        "apply": _operation_mute_apply,
    },
    "assistant.notice.unmute_category": {
        "label": "恢复这一类提醒",
        "schema": NoticeOperationCategoryMute,
        "prepare": _operation_unmute_preview,
        "apply": _operation_unmute_apply,
    },
}

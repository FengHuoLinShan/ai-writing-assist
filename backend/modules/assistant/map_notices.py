"""Coalesced, zero-request map notices inside existing standing authorization."""

from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from core.config import get_settings
from core.container import get
from core.errors import DomainError
from core.service_keys import WORLD_READ_MAP_NOTIFICATION_SIGNALS
from modules.assistant.models import AssistantNotice, AssistantRun
from modules.assistant.schemas import ProactivePolicy
from modules.project.facade import get_any_project_context, require_active_project

ASSETS = {
    "map_auto_draft_batch",
    "project_vocabulary_term",
    "map_atlas_node",
    "outline_scene",
}
_LABELS = {
    "tray": "待放置地点",
    "types": "新空间类型",
    "pending": "待审核草图",
    "spatial": "空间提醒",
}


async def _authorized(db, novel_id, watch):
    if (
        watch is None
        or not get_settings().assistant_enabled
        or "assistant.turn" not in get_settings().map_spatial_enabled_capabilities
    ):
        return None
    settings = ProactivePolicy.model_validate(
        (watch.policy_json or {}).get("settings") or {}
    )
    project = await get_any_project_context(db, novel_id)
    if (
        not settings.enabled
        or "world" not in settings.categories
        or project is None
        or project.project_kind != "author"
        or str(project.owner_id) != (watch.policy_json or {}).get("owner_id")
    ):
        return None
    return settings


async def _read(db, novel_id, request):
    try:
        async with db.begin_nested():
            return await get(WORLD_READ_MAP_NOTIFICATION_SIGNALS)(db, novel_id, request)
    except DomainError:
        return None


def _summary(events):
    kinds = {
        kind
        for event in events
        for kind, count in event["signal"]["counts"].items()
        if count
    }
    return (
        "地图有"
        + "、".join(label for kind, label in _LABELS.items() if kind in kinds)
        + "需要核对；可前往地图工作台处理。"
    )


async def record_change(db, novel_id, asset_type, asset_id, scene_ids):
    from modules.assistant import proactive

    if (
        not get_settings().assistant_enabled
        or "assistant.turn" not in get_settings().map_spatial_enabled_capabilities
    ):
        return
    # Match domain writers' project-before-watch lock order, including callers
    # that deliver a source event outside the original write transaction.
    await require_active_project(db, novel_id)
    # Existing row lock serializes changes with revocation and concurrent merges.
    watch = await proactive._watch(db, novel_id, lock=True)
    settings = await _authorized(db, novel_id, watch)
    if settings is None:
        return
    now = proactive._now()
    local_day = now.astimezone(ZoneInfo(settings.timezone)).date()
    key = ["map_changes", str(novel_id), watch.generation, local_day.isoformat()]
    identity = proactive.fingerprint(key)
    row = await db.scalar(
        select(AssistantNotice).where(
            AssistantNotice.novel_id == UUID(str(novel_id)),
            AssistantNotice.fingerprint == identity,
        )
    )
    if row is None:
        # Reuse the standing authorization's daily ceiling; this path never
        # creates an AI run, queue job, workflow budget or provider request.
        day = datetime.combine(
            local_day, time.min, ZoneInfo(settings.timezone)
        ).astimezone(UTC)
        runs = await db.scalar(
            select(func.count())
            .select_from(AssistantRun)
            .where(
                AssistantRun.novel_id == UUID(str(novel_id)),
                AssistantRun.mode == "background",
                AssistantRun.created_at >= day,
            )
        )
        notices = await db.scalar(
            select(func.count())
            .select_from(AssistantNotice)
            .where(
                AssistantNotice.novel_id == UUID(str(novel_id)),
                AssistantNotice.created_at >= day,
            )
        )
        if (runs or 0) + (notices or 0) >= settings.daily_limit:
            return
    request = {
        "asset_type": asset_type,
        "asset_id": str(asset_id),
        "scene_ids": list(dict.fromkeys(str(value) for value in (scene_ids or [])))[:20],
        "excluded_ids": list(settings.excluded_targets),
    }
    event_key = f"{asset_type}:{asset_id}"
    events = (
        [
            event
            for event in (row.result_ref_json or {}).get("events", [])
            if event["key"] != event_key
        ]
        if row
        else []
    )
    previous = (
        next(
            (
                event
                for event in (row.result_ref_json or {}).get("events", [])
                if event["key"] == event_key
            ),
            None,
        )
        if row
        else None
    )
    signal = await _read(db, novel_id, request)
    if signal is not None:
        events.append(
            {
                "key": event_key,
                "request": request,
                "signal": signal,
                "expires_at": (now + timedelta(hours=24)).isoformat(),
            }
        )
    events = events[-20:]
    if not events:
        return
    notice = await proactive._notice(
        db,
        novel_id,
        key=key,
        title="地图资料有待核对",
        summary=_summary(events),
        kind="reminder",
        result_ref={
            "type": "map_changes",
            "page": "map",
            "events": events,
            "authorization_generation": watch.generation,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "automatic_adoption": False,
            "provider_requests": 0,
        },
    )
    if (
        row is not None
        and row.status == "read"
        and signal is not None
        and (
            previous is None or previous["signal"]["fingerprint"] != signal["fingerprint"]
        )
    ):
        notice.status = "unread"
        await db.flush()


async def visible_summary(db, novel_id, row, watch):
    from modules.assistant import proactive

    settings = await _authorized(db, novel_id, watch)
    reference = row.result_ref_json or {}
    if (
        settings is None
        or reference.get("authorization_generation") != watch.generation
        or proactive._aware(datetime.fromisoformat(reference["expires_at"]))
        <= proactive._now()
    ):
        return None
    events = []
    for event in reference.get("events", [])[:20]:
        if (
            proactive._aware(datetime.fromisoformat(event["expires_at"]))
            <= proactive._now()
        ):
            continue
        request = {**event["request"], "excluded_ids": list(settings.excluded_targets)}
        current = await _read(db, novel_id, request)
        if (
            current is not None
            and current["fingerprint"] == event["signal"]["fingerprint"]
        ):
            events.append({**event, "signal": current})
    return (
        {
            "summary": _summary(events),
            "source": {
                "type": "map_changes",
                "page": "map",
                "automatic_adoption": False,
                "provider_requests": 0,
            },
        }
        if events
        else None
    )

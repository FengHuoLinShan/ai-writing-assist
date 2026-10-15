"""Owner-facing, content-free operation trace report aggregation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select

from modules.assistant.operation_trace_models import (
    AssistantOperationSequenceAggregate,
    AssistantOperationTrace,
    AssistantOperationTraceAggregate,
    AssistantOperationTraceLifecycleAggregate,
    AssistantOperationTraceMetricAggregate,
    AssistantOperationTraceParameterAggregate,
)
from modules.assistant.operation_trace_service import (
    _lifecycle_daily_counts,
    _metric_values,
    _parameter_profile,
    _utc_datetime,
    archive_expired_operation_traces,
    operation_trace_sequence_records,
)

_PERIOD_DAYS = {"30d": 30, "90d": 90, "180d": 180}
_LIFECYCLE_FIELDS = (
    "proposed_count",
    "accepted_count",
    "declined_count",
    "edited_accepted_count",
    "unresolved_count",
    "outcome_unknown_count",
    "unmatched_decision_count",
    "ambiguous_count",
    "proposal_event_count",
    "confirmed_event_count",
    "declined_event_count",
    "edited_event_count",
    "outcome_unknown_event_count",
    "failed_event_count",
    "failed_execution_count",
    "unknown_execution_count",
    "restored_event_count",
    "undone_event_count",
    "unlinked_proposal_events",
    "unlinked_decision_events",
    "unlinked_execution_events",
    "unlinked_reversal_events",
    "executed_count",
    "executed_event_count",
    "reversal_event_count",
    "matched_reversal_count",
    "unmatched_reversal_count",
)
_TRACE_LIFECYCLE_EVENTS = frozenset(
    {
        "proposed",
        "confirmed",
        "declined",
        "edited",
        "outcome_unknown",
        "executed",
        "failed",
        "restored",
        "undone",
    }
)
_USAGE_FIELDS = (
    "requests",
    "tool_attempts",
    "web_requests",
    "prompt_tokens",
    "completion_tokens",
    "pending_usage",
)


def _period_window(period: str, as_of: datetime) -> tuple[date | None, date]:
    end = _utc_datetime(as_of).date()
    if period == "all":
        return None, end
    days = _PERIOD_DAYS.get(period)
    if days is None:
        raise ValueError("unsupported operation trace report period")
    return end - timedelta(days=days - 1), end


def _within(day: date, start: date | None, end: date) -> bool:
    return (start is None or day >= start) and day <= end


def _jsonable_profile(profile: dict) -> dict:
    """Rebuild an allow-listed shape so stored JSON never leaks hidden fields."""
    allowed = {"present", "type", "size", "length", "count", "field_count"}
    fields = profile.get("fields")
    if not isinstance(fields, dict):
        return {"fields": {}, "unknown_fields_present": False}
    safe = {}
    for name, values in sorted(fields.items()):
        if not isinstance(name, str) or not isinstance(values, dict):
            continue
        safe[name] = {
            key: value
            for key, value in values.items()
            if key in allowed and (type(value) in {str, bool} or value is None)
        }
    return {
        "fields": safe,
        "unknown_fields_present": profile.get("unknown_fields_present") is True,
    }


def _merge_metric(target: dict, values: dict) -> None:
    for key in (
        "observed_event_count",
        "duration_count",
        "duration_ms_total",
        "usage_event_count",
        "usage_complete_count",
        "usage_unknown_count",
        "usage_pending_count",
    ):
        target[key] += values.get(key, 0)
    for key in ("usage_totals", "usage_field_counts"):
        for field, amount in values.get(key, {}).items():
            target[key][field] += amount


def _empty_metric() -> dict:
    return {
        "observed_event_count": 0,
        "duration_count": 0,
        "duration_ms_total": 0,
        "usage_event_count": 0,
        "usage_complete_count": 0,
        "usage_unknown_count": 0,
        "usage_pending_count": 0,
        "usage_totals": Counter(),
        "usage_field_counts": Counter(),
    }


def _merge_lifecycle(target: dict, values: object) -> None:
    for field in _LIFECYCLE_FIELDS:
        target[field] += int(getattr(values, field, 0) or 0)


def _empty_lifecycle() -> dict:
    return {field: 0 for field in _LIFECYCLE_FIELDS}


def _lifecycle_report(operation: str, counts: dict, event_counts: Counter) -> dict:
    tracked_by_event = {
        "proposed": counts["proposal_event_count"],
        "confirmed": counts["confirmed_event_count"],
        "declined": counts["declined_event_count"],
        "edited": counts["edited_event_count"],
        "outcome_unknown": counts["outcome_unknown_event_count"],
        "executed": counts["executed_event_count"],
        "failed": counts["failed_event_count"],
        "restored": 0,
        "undone": 0,
    }
    tracked_by_event["restored"] = counts["restored_event_count"]
    tracked_by_event["undone"] = counts["undone_event_count"]
    missing = sum(
        max(0, event_counts[(operation, event)] - tracked)
        for event, tracked in tracked_by_event.items()
    )
    unlinked = (
        counts["unlinked_proposal_events"]
        + counts["unlinked_decision_events"]
        + counts["unlinked_execution_events"]
        + counts["unlinked_reversal_events"]
    )
    decision_count = counts["accepted_count"] + counts["declined_count"]
    acceptance = counts["accepted_count"] / decision_count if decision_count else None
    edited_rate = (
        counts["edited_accepted_count"] / counts["accepted_count"]
        if counts["accepted_count"]
        else None
    )
    coverage_status = (
        "not_measurable"
        if decision_count == 0
        else "partial"
        if missing or unlinked or counts["ambiguous_count"]
        else "measurable"
    )
    return {
        "operation": operation,
        "proposals": counts["proposed_count"],
        "accepted": counts["accepted_count"],
        "declined": counts["declined_count"],
        "edited_then_accepted": counts["edited_accepted_count"],
        "unresolved": counts["unresolved_count"],
        "outcome_unknown": counts["outcome_unknown_count"],
        "outcome_unknown_groups": counts["outcome_unknown_count"],
        "ambiguous": counts["ambiguous_count"],
        "unmatched_decisions": counts["unmatched_decision_count"],
        "acceptance_rate": acceptance,
        "acceptance_rate_status": coverage_status,
        "acceptance_rate_denominator": decision_count,
        "edited_acceptance_rate": edited_rate,
        "edited_acceptance_rate_status": (
            coverage_status if counts["accepted_count"] else "not_measurable"
        ),
        "execution_groups": counts["executed_count"],
        "failed_execution_groups": counts["failed_execution_count"],
        "unknown_execution_groups": counts["unknown_execution_count"],
        "restoration_events": counts["reversal_event_count"],
        "restored_events": counts["restored_event_count"],
        "undone_events": counts["undone_event_count"],
        "same_day_matched_restoration_groups": counts["matched_reversal_count"],
        "unmatched_restoration_groups": counts["unmatched_reversal_count"],
        "same_day_correlation_only": True,
        "missing_lifecycle_event_count": missing,
        "unlinked_event_count": unlinked,
        "status": "partial" if missing or unlinked else "recorded_sample",
    }


def _metric_report(
    operation: str,
    event: str,
    values: dict,
    total_event_count: int,
) -> dict:
    observed = values["observed_event_count"]
    missing = max(0, total_event_count - observed)
    duration_count = values["duration_count"]
    duration_status = (
        "not_measurable"
        if duration_count == 0
        else "partial"
        if missing or duration_count < observed
        else "measurable"
    )
    duration = {
        "sample_count": duration_count,
        "observed_event_count": observed,
        "missing_event_count": max(0, observed - duration_count) + missing,
        "average_ms": (
            round(values["duration_ms_total"] / duration_count, 1)
            if duration_count
            else None
        ),
        "status": duration_status,
    }
    usage_count = values["usage_event_count"]
    usage_missing = max(0, total_event_count - usage_count)
    usage_incomplete = max(0, usage_count - values["usage_complete_count"])
    usage_fields = {}
    usage_global_status = (
        "not_measurable"
        if not values["usage_totals"]
        else "partial"
        if missing
        or usage_missing
        or usage_incomplete
        or values["usage_unknown_count"]
        or values["usage_pending_count"]
        else "measurable"
    )
    for name in _USAGE_FIELDS:
        count = values["usage_field_counts"].get(name, 0)
        if not count:
            continue
        incomplete = (
            missing > 0
            or values["usage_unknown_count"] > 0
            or values["usage_pending_count"] > 0
            or count < observed
        )
        usage_fields[name] = {
            "total": values["usage_totals"].get(name, 0),
            "sample_count": count,
            "status": "partial" if incomplete else "measurable",
        }
    usage = {
        "status": usage_global_status,
        "ledger_event_count": usage_count,
        "missing_event_count": usage_missing,
        "incomplete_event_count": usage_incomplete,
        "complete_event_count": values["usage_complete_count"],
        "unknown_event_count": values["usage_unknown_count"],
        "pending_total": (
            values["usage_totals"].get("pending_usage")
            if values["usage_field_counts"].get("pending_usage", 0)
            else None
        ),
        "fields": usage_fields,
    }
    return {
        "operation": operation,
        "event": event,
        "event_count": total_event_count,
        "metrics_observed_event_count": observed,
        "missing_metric_event_count": missing,
        "duration": duration,
        "usage": usage,
    }


def _date_filter(statement, column, start: date | None, end: date):
    if start is not None:
        statement = statement.where(column >= start)
    return statement.where(column <= end)


async def build_operation_trace_report(
    db,
    novel_id: str,
    *,
    period: str = "180d",
    collection_enabled: bool,
) -> dict:
    """Read archives and live details under one retention transaction lock."""
    if period not in {*_PERIOD_DAYS, "all"}:
        raise ValueError("unsupported operation trace report period")
    project_uuid = UUID(str(novel_id))
    postgres = db.get_bind().dialect.name == "postgresql"
    now_value = await db.scalar(select(func.now())) if postgres else datetime.now(UTC)
    as_of = _utc_datetime(now_value)
    start, end = _period_window(period, as_of)

    # This takes the same per-project transaction lock as the retention job.
    # It keeps the archived and still-live halves on one side of the move.
    await archive_expired_operation_traces(db, str(project_uuid), now=as_of)

    event_counts: Counter = Counter()
    archived_events = list(
        (
            await db.scalars(
                _date_filter(
                    select(AssistantOperationTraceAggregate).where(
                        AssistantOperationTraceAggregate.novel_id == project_uuid
                    ),
                    AssistantOperationTraceAggregate.occurred_on,
                    start,
                    end,
                )
            )
        ).all()
    )
    for row in archived_events:
        event_counts[(row.op_id, row.event_type)] += row.event_count

    details_query = select(AssistantOperationTrace).where(
        AssistantOperationTrace.novel_id == project_uuid,
        AssistantOperationTrace.occurred_at <= as_of,
    )
    if start is not None:
        details_query = details_query.where(
            AssistantOperationTrace.occurred_at
            >= datetime.combine(start, time.min, tzinfo=UTC)
        )
    details = list(
        (await db.scalars(details_query.order_by(AssistantOperationTrace.id))).all()
    )
    detail_lifecycle = _lifecycle_daily_counts(details)
    for row in details:
        event_counts[(row.op_id, row.event_type)] += 1

    event_rows = []
    daily_events = Counter()
    for row in archived_events:
        daily_events[(row.occurred_on, row.op_id, row.event_type)] += row.event_count
    for row in details:
        daily_events[
            (_utc_datetime(row.occurred_at).date(), row.op_id, row.event_type)
        ] += 1
    for (day, operation, event), count in sorted(
        daily_events.items(),
        key=lambda item: (-item[1], item[0][1], item[0][2], item[0][0]),
    ):
        event_rows.append(
            {
                "date": day.isoformat(),
                "operation": operation,
                "event": event,
                "count": count,
            }
        )

    sequence_counts: dict[tuple[date, tuple[str, ...]], dict] = {}
    sequence_query = _date_filter(
        select(AssistantOperationSequenceAggregate).where(
            AssistantOperationSequenceAggregate.novel_id == project_uuid
        ),
        AssistantOperationSequenceAggregate.occurred_on,
        start,
        end,
    )
    for row in (await db.scalars(sequence_query)).all():
        key = (row.occurred_on, tuple(row.operation_sequence))
        item = sequence_counts.setdefault(key, {"count": 0, "complete": True})
        item["count"] += row.sequence_count
        item["complete"] = item["complete"] and row.sequence_complete
    for day, sequence, complete in operation_trace_sequence_records(details):
        key = (day, tuple(sequence))
        item = sequence_counts.setdefault(key, {"count": 0, "complete": True})
        item["count"] += 1
        item["complete"] = item["complete"] and complete
    sequences = [
        {
            "date": day.isoformat(),
            "operations": list(sequence),
            "count": item["count"],
            "complete": item["complete"],
        }
        for (day, sequence), item in sorted(
            sequence_counts.items(),
            key=lambda pair: (-pair[1]["count"], pair[0][0], pair[0][1]),
        )
    ]

    metric_totals: dict[tuple[str, str], dict] = defaultdict(_empty_metric)
    metric_rows = await db.scalars(
        _date_filter(
            select(AssistantOperationTraceMetricAggregate).where(
                AssistantOperationTraceMetricAggregate.novel_id == project_uuid
            ),
            AssistantOperationTraceMetricAggregate.occurred_on,
            start,
            end,
        )
    )
    for row in metric_rows:
        _merge_metric(metric_totals[(row.op_id, row.event_type)], row.__dict__)
    for row in details:
        _merge_metric(metric_totals[(row.op_id, row.event_type)], _metric_values(row))
    metrics = [
        _metric_report(
            operation,
            event,
            metric_totals.get((operation, event), _empty_metric()),
            event_counts[(operation, event)],
        )
        for operation, event in sorted(set(metric_totals) | set(event_counts))
    ]

    lifecycle_totals: dict[str, dict] = defaultdict(_empty_lifecycle)
    lifecycle_rows = await db.scalars(
        _date_filter(
            select(AssistantOperationTraceLifecycleAggregate).where(
                AssistantOperationTraceLifecycleAggregate.novel_id == project_uuid
            ),
            AssistantOperationTraceLifecycleAggregate.occurred_on,
            start,
            end,
        )
    )
    for row in lifecycle_rows:
        _merge_lifecycle(lifecycle_totals[row.op_id], row)
    for (_day, operation), counts in detail_lifecycle.items():
        for field, amount in counts.items():
            lifecycle_totals[operation][field] += amount
    lifecycle_operations = set(lifecycle_totals) | {
        operation
        for (operation, event), count in event_counts.items()
        if count and event in _TRACE_LIFECYCLE_EVENTS
    }
    lifecycle = [
        _lifecycle_report(
            operation,
            lifecycle_totals.get(operation, _empty_lifecycle()),
            Counter(
                {
                    (op, event): count
                    for (op, event), count in event_counts.items()
                    if op == operation and event in _TRACE_LIFECYCLE_EVENTS
                }
            ),
        )
        for operation in sorted(lifecycle_operations)
    ]

    parameter_totals: dict[tuple[str, str, str], dict] = {}
    parameter_rows = await db.scalars(
        _date_filter(
            select(AssistantOperationTraceParameterAggregate).where(
                AssistantOperationTraceParameterAggregate.novel_id == project_uuid
            ),
            AssistantOperationTraceParameterAggregate.occurred_on,
            start,
            end,
        )
    )
    for row in parameter_rows:
        key = (row.op_id, row.event_type, row.profile_hash)
        item = parameter_totals.setdefault(
            key, {"profile": _jsonable_profile(row.parameter_profile), "count": 0}
        )
        item["count"] += row.event_count
    for row in details:
        profile = _parameter_profile(row.parameter_summary)
        if profile is None:
            continue
        profile = _jsonable_profile(profile)
        encoded = json.dumps(profile, sort_keys=True, separators=(",", ":"))
        profile_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        key = (row.op_id, row.event_type, profile_hash)
        item = parameter_totals.setdefault(key, {"profile": profile, "count": 0})
        item["count"] += 1
    parameters = [
        {
            "operation": operation,
            "event": event,
            "profile": value["profile"],
            "count": value["count"],
        }
        for (operation, event, _hash), value in sorted(
            parameter_totals.items(), key=lambda pair: (-pair[1]["count"], pair[0])
        )
    ]

    top_operations = Counter()
    for (operation, _event), count in event_counts.items():
        top_operations[operation] += count
    operation_candidates = [
        {"operation": operation, "recorded_event_count": count}
        for operation, count in sorted(
            top_operations.items(), key=lambda pair: (-pair[1], pair[0])
        )
    ]

    observed_days = sorted({date.fromisoformat(row["date"]) for row in event_rows})
    incomplete_sequences = sum(row["count"] for row in sequences if not row["complete"])
    missing_metrics = sum(row["missing_metric_event_count"] for row in metrics)
    missing_durations = sum(row["duration"]["missing_event_count"] for row in metrics)
    unmeasured_usage = sum(row["usage"]["missing_event_count"] for row in metrics)
    incomplete_usage = sum(row["usage"]["incomplete_event_count"] for row in metrics)
    unknown_usage = sum(row["usage"]["unknown_event_count"] for row in metrics)
    pending_usage_samples = [
        row["usage"]["pending_total"]
        for row in metrics
        if row["usage"]["pending_total"] is not None
    ]
    pending_usage = sum(pending_usage_samples) if pending_usage_samples else None
    missing_lifecycle = sum(row["missing_lifecycle_event_count"] for row in lifecycle)
    parameter_coverage: dict[str, dict] = {}
    parameter_counts = Counter()
    for row in parameters:
        parameter_counts[(row["operation"], row["event"])] += row["count"]
    for operation in top_operations:
        total = sum(
            count for (op, _event), count in event_counts.items() if op == operation
        )
        profiles = sum(
            count for (op, _event), count in parameter_counts.items() if op == operation
        )
        missing = max(0, total - profiles)
        parameter_coverage[operation] = {
            "event_count": total,
            "profiled_event_count": profiles,
            "missing_event_count": missing,
            "status": "not_measurable"
            if profiles == 0
            else "partial"
            if missing
            else "measurable",
        }

    return {
        "schema_version": "1",
        "period": period,
        "timezone": "UTC",
        "as_of": as_of.isoformat(),
        "window_start": start.isoformat() if start else None,
        "window_end": end.isoformat(),
        "collection_enabled_now": collection_enabled,
        "events": event_rows,
        "operation_candidates": operation_candidates,
        "sequences": sequences,
        "parameter_profiles": parameters,
        "lifecycle": lifecycle,
        "metrics": metrics,
        "coverage": {
            "status": (
                "no_records"
                if not event_rows
                else "partial"
                if missing_metrics
                or missing_durations
                or unmeasured_usage
                or incomplete_usage
                or unknown_usage
                or pending_usage
                or missing_lifecycle
                or incomplete_sequences
                or any(
                    item["missing_event_count"] for item in parameter_coverage.values()
                )
                else "recorded_sample"
            ),
            "completeness_provable": False,
            "capture_enabled_now": collection_enabled,
            "first_record_date": observed_days[0].isoformat() if observed_days else None,
            "last_record_date": observed_days[-1].isoformat() if observed_days else None,
            "days_with_records": len(observed_days),
            "missing_metric_event_count": missing_metrics,
            "missing_duration_event_count": missing_durations,
            "unmeasured_usage_event_count": unmeasured_usage,
            "incomplete_usage_event_count": incomplete_usage,
            "unknown_usage_event_count": unknown_usage,
            "pending_usage_total": pending_usage,
            "missing_lifecycle_event_count": missing_lifecycle,
            "incomplete_sequence_count": incomplete_sequences,
            "parameter_profile_gap_by_operation": parameter_coverage,
            "legacy_event_aggregates_preserved": True,
            "note": (
                "Observed trace records are a sample. Disabled periods, failed writes, "
                "and history before capture cannot be reconstructed."
            ),
        },
    }


def operation_trace_report_csv(report: dict) -> str:
    """Render only fixed aggregate columns; no IDs or raw parameter values."""
    import csv
    from io import StringIO

    output = StringIO(newline="")
    writer = csv.writer(output)

    def write_row(*values):
        safe = []
        for value in values:
            if isinstance(value, str) and value.lstrip()[:1] in {"=", "+", "-", "@"}:
                value = "'" + value
            safe.append(value)
        writer.writerow(safe)

    writer.writerow(
        (
            "section",
            "date",
            "operation",
            "event",
            "count",
            "complete",
            "parameter_profile",
            "metric",
            "value",
            "status",
        )
    )
    write_row(
        "metadata", "", "", "", "", "", "", "schema_version", report["schema_version"], ""
    )
    write_row("metadata", "", "", "", "", "", "", "period", report["period"], "")
    write_row("metadata", "", "", "", "", "", "", "timezone", report["timezone"], "")
    write_row("metadata", "", "", "", "", "", "", "as_of", report["as_of"], "")
    write_row(
        "metadata",
        "",
        "",
        "",
        "",
        "",
        "",
        "collection_enabled_now",
        report["collection_enabled_now"],
        "",
    )
    write_row(
        "metadata",
        "",
        "",
        "",
        "",
        "",
        "",
        "window_start",
        report["window_start"] or "all",
        "",
    )
    write_row("metadata", "", "", "", "", "", "", "window_end", report["window_end"], "")
    coverage = report["coverage"]
    for name in (
        "status",
        "completeness_provable",
        "capture_enabled_now",
        "first_record_date",
        "last_record_date",
        "days_with_records",
        "missing_metric_event_count",
        "missing_duration_event_count",
        "unmeasured_usage_event_count",
        "incomplete_usage_event_count",
        "unknown_usage_event_count",
        "pending_usage_total",
        "missing_lifecycle_event_count",
        "incomplete_sequence_count",
        "legacy_event_aggregates_preserved",
    ):
        write_row("coverage", "", "", "", "", "", "", name, coverage.get(name), "")
    write_row(
        "coverage",
        "",
        "",
        "",
        "",
        "",
        "",
        "parameter_profile_gap_by_operation",
        json.dumps(
            coverage["parameter_profile_gap_by_operation"],
            sort_keys=True,
            separators=(",", ":"),
        ),
        "",
    )
    write_row("coverage", "", "", "", "", "", "", "note", coverage["note"], "")
    for row in report["events"]:
        write_row(
            "event",
            row["date"],
            row["operation"],
            row["event"],
            row["count"],
            "",
            "",
            "",
            "",
            "",
        )
    for row in report["sequences"]:
        write_row(
            "sequence",
            row["date"],
            " → ".join(row["operations"]),
            "",
            row["count"],
            row["complete"],
            "",
            "",
            "",
            "",
        )
    for row in report["parameter_profiles"]:
        profile = json.dumps(
            row["profile"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        write_row(
            "parameter",
            "",
            row["operation"],
            row["event"],
            row["count"],
            "",
            profile,
            "",
            "",
            "",
        )
    for row in report["lifecycle"]:
        for metric in (
            "proposals",
            "accepted",
            "declined",
            "edited_then_accepted",
            "unresolved",
            "outcome_unknown",
            "acceptance_rate",
            "acceptance_rate_denominator",
            "edited_acceptance_rate",
            "execution_groups",
            "failed_execution_groups",
            "unknown_execution_groups",
            "restoration_events",
            "restored_events",
            "undone_events",
            "same_day_matched_restoration_groups",
            "unmatched_restoration_groups",
        ):
            write_row(
                "lifecycle",
                "",
                row["operation"],
                "",
                row[metric],
                "",
                "",
                metric,
                row[metric],
                row["status"],
            )
    for row in report["metrics"]:
        write_row(
            "duration",
            "",
            row["operation"],
            row["event"],
            row["duration"]["sample_count"],
            "",
            "",
            "average_ms",
            row["duration"]["average_ms"],
            row["duration"]["status"],
        )
        for name, usage in row["usage"]["fields"].items():
            write_row(
                "usage",
                "",
                row["operation"],
                row["event"],
                usage["sample_count"],
                "",
                "",
                name,
                usage["total"],
                usage["status"],
            )
    return output.getvalue()


__all__ = ["build_operation_trace_report", "operation_trace_report_csv"]

"""HTTP adapter that records assistant operation traces around routed writes."""

from __future__ import annotations

import logging
from functools import wraps
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import FastAPI, Request
from fastapi.routing import APIRoute

from core.container import get
from core.service_keys import ASSISTANT_OPERATIONS
from modules.account.facade import current_account_id
from modules.project.facade import require_active_project

logger = logging.getLogger(__name__)


def _trace_route_arguments(
    values: dict,
    argument_map: dict | None = None,
    trace_fields: dict[str, str] | None = None,
) -> dict:
    if trace_fields is not None:
        arguments = {}
        missing = object()
        for field, source in trace_fields.items():
            value = values
            for part in source.split("."):
                value = (
                    value.get(part, missing)
                    if isinstance(value, dict)
                    else getattr(value, part, missing)
                )
                if value is missing:
                    break
            if value is not missing:
                arguments[field] = (
                    value.model_dump(mode="json")
                    if hasattr(value, "model_dump")
                    else value
                )
        return arguments
    arguments = {}
    for name, value in values.items():
        if name in {"db", "response"} or (
            name == "request" and isinstance(value, Request)
        ):
            continue
        if hasattr(value, "model_dump"):
            rendered = value.model_dump(mode="json")
            if isinstance(rendered, dict):
                target = (argument_map or {}).get(name)
                if target:
                    arguments[target] = rendered
                else:
                    arguments.update(rendered)
        else:
            arguments[name] = value
    return arguments


def _trace_result(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return None


def install_operation_trace_route_adapters(application: FastAPI) -> None:
    """Bind operation-marked HTTP writes to the same trace port/transaction."""
    from modules.assistant.evidence_tools import fingerprint
    from modules.assistant.operation_trace_service import (
        bind_operation_trace_context,
        current_operation_trace_context,
        operation_trace_enabled,
        record_operation_trace,
        reset_operation_trace_context,
    )

    def concrete_routes(routes):
        for item in routes:
            if isinstance(item, APIRoute):
                yield item
                continue
            # Included routers use a separate effective route context (and
            # ASGI app) for each inclusion. Wrapping the source APIRoute has
            # no effect on requests dispatched through that context.
            effective_routes = getattr(item, "effective_route_contexts", None)
            if effective_routes is not None:
                for effective in effective_routes():
                    if isinstance(getattr(effective, "original_route", None), APIRoute):
                        yield effective

    operations = get(ASSISTANT_OPERATIONS)

    async def record_reversal(db, *, trace_context, reference, original_op_ids) -> None:
        """Match a completed domain receipt to its original traced execution."""
        from sqlalchemy import String, cast, select

        from modules.assistant.operation_trace_models import AssistantOperationTrace

        if not isinstance(reference, dict):
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        kind, ref_id = reference.get("type"), reference.get("id")
        try:
            ref_id = str(UUID(str(ref_id)))
        except (TypeError, ValueError, AttributeError):
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        if not isinstance(kind, str) or not kind or len(kind) > 80:
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        rows = (
            await db.scalars(
                select(AssistantOperationTrace)
                .where(
                    AssistantOperationTrace.novel_id == UUID(trace_context["novel_id"]),
                    AssistantOperationTrace.owner_id == UUID(trace_context["owner_id"]),
                    AssistantOperationTrace.op_id.in_(original_op_ids),
                    AssistantOperationTrace.event_type == "executed",
                    cast(AssistantOperationTrace.result_refs, String).like(f"%{ref_id}%"),
                )
                .order_by(AssistantOperationTrace.id.desc())
            )
        ).all()
        original = next(
            (
                row
                for row in rows
                if {"type": kind, "id": ref_id} in (row.result_refs or [])
                and row.call_id is not None
            ),
            None,
        )
        if original is None:
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )
            return
        prior_restored = await db.scalar(
            select(AssistantOperationTrace.id)
            .where(
                AssistantOperationTrace.novel_id == original.novel_id,
                AssistantOperationTrace.owner_id == original.owner_id,
                AssistantOperationTrace.op_id == original.op_id,
                AssistantOperationTrace.call_id == original.call_id,
                AssistantOperationTrace.event_type == "restored",
            )
            .limit(1)
        )
        if prior_restored is not None:
            return
        saved = await record_operation_trace(
            db,
            enabled=True,
            novel_id=trace_context["novel_id"],
            owner_id=trace_context["owner_id"],
            operation=operations[original.op_id],
            event_type="restored",
            arguments=trace_context.get("arguments"),
            result={"result_ref": {"type": kind, "id": ref_id}},
            actor_type="ui",
            entrypoint="assistant.http",
            call_id=str(original.call_id),
            parent_call_id=trace_context["call_id"],
        )
        if saved is False:
            trace_context["incomplete_count"] = (
                trace_context.get("incomplete_count", 0) + 1
            )

    for route in concrete_routes(application.routes):
        if getattr(route, "_trace_adapter_installed", False):
            continue
        operation_id = (route.openapi_extra or {}).get("x-novelcraft-operation-id")
        if not operation_id:
            continue
        operation = operations.get(operation_id)
        if operation is None:
            raise RuntimeError(
                f"HTTP route references unknown assistant operation: {operation_id}"
            )
        original_endpoint = route.endpoint
        original_app = route.app
        argument_map = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-argument-map", {}
        )
        trace_fields = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-trace-fields"
        )
        operation_phase = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-phase", "execute"
        )
        if operation_phase not in {"execute", "prepare"}:
            raise RuntimeError(f"Invalid HTTP operation phase: {operation_id}")
        confirmation_field = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-confirmation-field"
        )
        call_id_field = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-call-id-field"
        )
        terminal_event = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-terminal-event"
        )
        reversal_op_ids = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-reversal-op-ids", ()
        )
        reversal_ref_field = (route.openapi_extra or {}).get(
            "x-novelcraft-operation-reversal-ref-field", "result_ref"
        )
        if terminal_event is not None and (
            terminal_event != "restored"
            or operation_phase != "execute"
            or not reversal_op_ids
            or any(op_id not in operations for op_id in reversal_op_ids)
            or not isinstance(reversal_ref_field, str)
        ):
            raise RuntimeError(f"Invalid HTTP reversal declaration: {operation_id}")
        if trace_fields is not None and set(trace_fields) != set(
            operation.schema.model_fields
        ):
            raise RuntimeError(
                f"HTTP route trace fields differ from operation schema: {operation_id}"
            )

        @wraps(original_endpoint)
        async def traced_endpoint(
            *args,
            __endpoint=original_endpoint,
            __operation=operation,
            __argument_map=argument_map,
            __trace_fields=trace_fields,
            __operation_phase=operation_phase,
            __confirmation_field=confirmation_field,
            __call_id_field=call_id_field,
            __terminal_event=terminal_event,
            __reversal_op_ids=tuple(reversal_op_ids),
            __reversal_ref_field=reversal_ref_field,
            **kwargs,
        ):
            trace_context = current_operation_trace_context()
            db = kwargs.get("db")
            if trace_context is None or db is None:
                return await __endpoint(*args, **kwargs)
            try:
                owner_id = str(current_account_id())
            except Exception:
                return await __endpoint(*args, **kwargs)
            arguments = _trace_route_arguments(kwargs, __argument_map, __trace_fields)
            body_novel_id = next(
                (
                    getattr(value, "novel_id", None)
                    for value in kwargs.values()
                    if hasattr(value, "novel_id")
                ),
                None,
            )
            body_author_project_id = next(
                (
                    getattr(value, "author_project_id", None)
                    for value in kwargs.values()
                    if hasattr(value, "author_project_id")
                ),
                None,
            )
            novel_id = str(
                kwargs.get("novel_id")
                or kwargs.get("project_id")
                or body_novel_id
                or body_author_project_id
                or arguments.get("novel_id")
                or arguments.get("author_project_id")
                or arguments.get("project_id")
                or ""
            )
            if novel_id:
                # This wrapper runs before the endpoint's own guard. Trace
                # preference/salt/events must never touch another owner's or
                # a recycled project, even when tracing is disabled.
                await require_active_project(db, novel_id)
            if __call_id_field:
                stable_value = _trace_route_arguments(
                    kwargs, trace_fields={"stable": __call_id_field}
                ).get("stable")
                try:
                    stable_uuid = str(UUID(str(stable_value)))
                except (TypeError, ValueError, AttributeError) as exc:
                    raise RuntimeError(
                        f"HTTP operation stable call field missing: {__operation.op_id}"
                    ) from exc
                normalized = {
                    key: value
                    for key, value in arguments.items()
                    if key != "preview_fingerprint"
                }
                trace_context["call_id"] = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"{novel_id}:{__operation.op_id}:{stable_uuid}:{fingerprint(normalized)}",
                    )
                )
            business_bind = db.get_bind()
            trace_context.update(
                owner_id=owner_id,
                novel_id=novel_id,
                arguments=arguments,
                operation=__operation,
                business_engine=getattr(business_bind, "engine", business_bind),
            )
            if not novel_id or not await operation_trace_enabled(db, owner_id):
                return await __endpoint(*args, **kwargs)
            trace_context["enabled"] = True
            already_terminal = None
            if __call_id_field:
                from sqlalchemy import select

                from modules.assistant.operation_trace_models import (
                    AssistantOperationTrace,
                )

                already_terminal = await db.scalar(
                    select(AssistantOperationTrace.id)
                    .where(
                        AssistantOperationTrace.novel_id == UUID(novel_id),
                        AssistantOperationTrace.owner_id == UUID(owner_id),
                        AssistantOperationTrace.op_id == __operation.op_id,
                        AssistantOperationTrace.call_id == UUID(trace_context["call_id"]),
                        AssistantOperationTrace.event_type == "executed",
                    )
                    .limit(1)
                )
            trace_context["replayed_trace"] = already_terminal is not None
            explicitly_confirmed = (
                _trace_route_arguments(
                    kwargs, trace_fields={"confirmed": __confirmation_field}
                ).get("confirmed")
                is True
                if __confirmation_field
                else True
            )
            if (
                __operation.permission == "confirm"
                and __operation_phase == "execute"
                and explicitly_confirmed
                and already_terminal is None
            ):
                await record_operation_trace(
                    db,
                    enabled=True,
                    novel_id=novel_id,
                    owner_id=owner_id,
                    operation=__operation,
                    event_type="confirmed",
                    arguments=arguments,
                    actor_type="ui",
                    entrypoint="assistant.http",
                    call_id=trace_context["call_id"],
                    parent_call_id=trace_context.get("parent_call_id"),
                )
            try:
                result = await __endpoint(*args, **kwargs)
            except Exception as error:
                trace_context["failure_event"] = (
                    "outcome_unknown"
                    if __operation.transaction_mode == "multi_stage"
                    else "failed"
                )
                trace_context["error_code"] = getattr(
                    error, "code", "operation_http_failed"
                )
                raise
            trace_context["result"] = _trace_result(result)
            if __terminal_event == "restored" and already_terminal is None:
                reference = trace_context["result"]
                for part in __reversal_ref_field.split("."):
                    reference = (
                        reference.get(part) if isinstance(reference, dict) else None
                    )
                try:
                    async with db.begin_nested():
                        await record_reversal(
                            db,
                            trace_context=trace_context,
                            reference=reference,
                            original_op_ids=__reversal_op_ids,
                        )
                except Exception as trace_error:
                    trace_context["incomplete_count"] = (
                        trace_context.get("incomplete_count", 0) + 1
                    )
                    logger.warning(
                        "HTTP reversal trace unavailable op_id=%s error_type=%s",
                        __operation.op_id,
                        type(trace_error).__name__,
                    )
            if __operation.transaction_mode == "single_transaction":
                from sqlalchemy import select

                from modules.assistant.operation_trace_models import (
                    AssistantOperationTrace,
                )

                already_recorded = await db.scalar(
                    select(AssistantOperationTrace.id)
                    .where(
                        AssistantOperationTrace.novel_id == UUID(novel_id),
                        AssistantOperationTrace.owner_id == UUID(owner_id),
                        AssistantOperationTrace.op_id == __operation.op_id,
                        AssistantOperationTrace.call_id == UUID(trace_context["call_id"]),
                        AssistantOperationTrace.event_type.in_(
                            ("previewed", "executed", "outcome_unknown")
                            if __operation_phase == "prepare"
                            else ("executed", "outcome_unknown")
                        ),
                    )
                    .limit(1)
                )
                if already_recorded is None and not trace_context.get("replayed_trace"):
                    await record_operation_trace(
                        db,
                        enabled=True,
                        novel_id=novel_id,
                        owner_id=owner_id,
                        operation=__operation,
                        event_type=(
                            "previewed" if __operation_phase == "prepare" else "executed"
                        ),
                        arguments=arguments,
                        result=trace_context["result"],
                        actor_type="ui",
                        entrypoint="assistant.http",
                        call_id=trace_context["call_id"],
                        parent_call_id=trace_context.get("parent_call_id"),
                    )
            return result

        async def traced_route_app(
            scope, receive, send, *, __app=original_app, __operation=operation
        ):
            if scope.get("type") != "http":
                await __app(scope, receive, send)
                return
            trace_context = {
                "operation_id": __operation.op_id,
                "call_id": str(uuid4()),
                "parent_call_id": None,
            }
            token = bind_operation_trace_context(trace_context)
            status_code = None

            async def capture_status(message):
                nonlocal status_code
                if message.get("type") == "http.response.start":
                    status_code = message.get("status")
                    if trace_context.get("enabled") and status_code >= 400:
                        from core.database import get_manager

                        try:
                            manager = get_manager()
                            if manager.engine.sync_engine is not trace_context.get(
                                "business_engine"
                            ):
                                trace_context["terminal_trace_unavailable"] = True
                                trace_context["incomplete_count"] = (
                                    trace_context.get("incomplete_count", 0) + 1
                                )
                        except Exception as trace_error:
                            trace_context["terminal_trace_unavailable"] = True
                            trace_context["incomplete_count"] = (
                                trace_context.get("incomplete_count", 0) + 1
                            )
                            logger.warning(
                                "HTTP operation terminal trace manager unavailable "
                                "op_id=%s error_type=%s",
                                __operation.op_id,
                                type(trace_error).__name__,
                            )
                    if trace_context.get("incomplete_count"):
                        message = {
                            **message,
                            "headers": [
                                *(message.get("headers") or []),
                                (b"x-novelcraft-operation-trace-incomplete", b"true"),
                            ],
                        }
                await send(message)

            try:
                await __app(scope, receive, capture_status)
            except Exception as error:
                if trace_context.get("enabled"):
                    await _record_http_terminal(
                        trace_context,
                        __operation,
                        "failed"
                        if __operation.transaction_mode == "single_transaction"
                        else "outcome_unknown",
                        getattr(error, "code", "request_commit_failed"),
                    )
                raise
            else:
                if (
                    trace_context.get("enabled")
                    and status_code is not None
                    and status_code >= 400
                ):
                    await _record_http_terminal(
                        trace_context,
                        __operation,
                        trace_context.get("failure_event")
                        or (
                            "outcome_unknown"
                            if __operation.transaction_mode == "multi_stage"
                            else "failed"
                        ),
                        trace_context.get("error_code") or f"http_{status_code}",
                    )
                elif (
                    trace_context.get("enabled")
                    and __operation.transaction_mode == "multi_stage"
                    and not trace_context.get("replayed_trace")
                ):
                    await _record_http_terminal(
                        trace_context,
                        __operation,
                        "executed",
                        None,
                    )
            finally:
                reset_operation_trace_context(token)

        async def _record_http_terminal(trace_context, operation, event_type, error_code):
            if not trace_context.get("novel_id") or not trace_context.get("owner_id"):
                return
            from core.database import get_manager

            try:
                if trace_context.get("terminal_trace_unavailable"):
                    logger.warning(
                        "HTTP operation terminal trace skipped because the request "
                        "database differs from the background trace database op_id=%s",
                        operation.op_id,
                    )
                    return
                manager = get_manager()
                if manager.engine.sync_engine is not trace_context.get("business_engine"):
                    trace_context["incomplete_count"] = (
                        trace_context.get("incomplete_count", 0) + 1
                    )
                    logger.warning(
                        "HTTP operation terminal trace skipped because the request "
                        "database differs from the background trace database op_id=%s",
                        operation.op_id,
                    )
                    return
                async with manager.session_factory() as trace_db:
                    await record_operation_trace(
                        trace_db,
                        enabled=True,
                        novel_id=trace_context["novel_id"],
                        owner_id=trace_context["owner_id"],
                        operation=operation,
                        event_type=event_type,
                        arguments=trace_context.get("arguments"),
                        result=trace_context.get("result"),
                        error_code=error_code,
                        actor_type="ui",
                        entrypoint="assistant.http",
                        call_id=trace_context["call_id"],
                        parent_call_id=trace_context.get("parent_call_id"),
                    )
                    await trace_db.commit()
            except Exception as trace_error:
                trace_context["incomplete_count"] = (
                    trace_context.get("incomplete_count", 0) + 1
                )
                logger.warning(
                    "HTTP operation trace failed op_id=%s error_type=%s",
                    operation.op_id,
                    type(trace_error).__name__,
                )

        route.endpoint = traced_endpoint
        route.dependant.call = traced_endpoint
        route.app = traced_route_app
        route._trace_adapter_installed = True

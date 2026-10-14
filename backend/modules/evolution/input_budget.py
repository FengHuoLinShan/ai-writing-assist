"""Measure the exact native transport contract; legacy preparations keep char rules."""

from infrastructure.llm.capabilities import capability_from_execution_snapshot
from infrastructure.llm.codex_provider import codex_input_tokens
from modules.evolution.llm_sampler import (
    prepare_scene_call_request,
    registered_scene_request,
)


def input_tokens(snapshot, consumer, inputs):
    profile = snapshot["profile"]
    registered = registered_scene_request(consumer, inputs, model=profile["model"])
    if registered is None:
        raise ValueError("unregistered input contract")
    request, schema, method = registered
    request, _ = prepare_scene_call_request(
        request, method, model=profile["model"], provider_id=profile["provider_id"]
    )
    request = request.model_copy(
        update={
            "model": profile["model"],
            "max_tokens": min(
                request.max_tokens or profile.get("max_tokens") or 128000, 128000
            ),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                },
            },
        }
    )
    import json

    from infrastructure.llm.schemas import LLMMessage

    schema_json = json.dumps(
        schema.model_json_schema(), ensure_ascii=False, separators=(",", ":")
    )
    if not any(schema_json in message.content for message in request.messages):
        request.messages.append(
            LLMMessage(
                role="system",
                content="Return one JSON object matching this output schema: "
                + schema_json,
            )
        )
    request.response_format["json_schema"]["strict"] = True
    return codex_input_tokens(
        request, capability=capability_from_execution_snapshot(snapshot)
    )


def fits(snapshot, consumer, inputs, *, reserve=0):
    budget = capability_from_execution_snapshot(snapshot).default_input_budget_tokens
    if budget is None:
        raise ValueError("model input budget missing")
    return input_tokens(snapshot, consumer, inputs) + reserve <= budget

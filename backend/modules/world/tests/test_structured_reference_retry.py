from types import SimpleNamespace

from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.services.worldbuilding.structured_reference_retry import (
    run_structured_with_known_keys,
)


async def test_unknown_keys_get_one_byte_stable_repair_turn() -> None:
    request = LLMCallRequest(
        model="test-model",
        messages=[LLMMessage(role="user", content="original")],
    )
    outputs = [SimpleNamespace(keys=["z", "a"]), SimpleNamespace(keys=["known"])]
    seen_messages: list[list[str]] = []

    async def generate():
        seen_messages.append([message.content for message in request.messages])
        return outputs.pop(0)

    result = await run_structured_with_known_keys(
        SimpleNamespace(provider="test"),
        request,
        generate=generate,
        known_keys={"known"},
        keys_of=lambda output: output.keys,
        repair_note="repair:",
        error_message="unknown keys",
    )

    assert result.keys == ["known"]
    assert seen_messages == [["original"], ["original", 'repair:["a", "z"]']]

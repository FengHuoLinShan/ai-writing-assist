import uuid
from types import SimpleNamespace

import pytest

from core.errors import ConflictError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.story import assistant_generation_tools
from modules.story.assistant_generation_tools import (
    OPERATIONS_SPEC,
    GenerateCharacterCard,
    GenerateCharacterReactions,
)
from modules.story.facade import STORY_CARD_TASK, STORY_CHARACTER_CARD_ACTION
from modules.story.task_submission import validate_story_generation_confirmation


def test_card_and_reaction_operations_are_suggest_only_and_trace_exact_schema_fields():
    assert set(OPERATIONS_SPEC) == {
        "story.character_card.generate",
        "story.reaction.generate",
    }
    for spec in OPERATIONS_SPEC.values():
        assert spec["permission"] == "suggest"
        assert spec["risk_level"] == "R1"
        assert spec["fee_category"] == "possible_model_charge"
        assert spec["transaction_mode"] == "multi_stage"
        assert spec["trace_rule"]["parameter_fields"] == tuple(
            spec["schema"].model_fields
        )
        assert spec["trace_rule"]["parameter_policy"] == "schema_safe"
        assert callable(spec["read_result"])
    assert OPERATIONS_SPEC["story.character_card.generate"]["op_version"] == "1"
    assert OPERATIONS_SPEC["story.reaction.generate"]["op_version"] == "2"


def test_generation_operation_arguments_bind_scene_and_pov_targets():
    card = OPERATIONS_SPEC["story.character_card.generate"]["schema"]
    reaction = OPERATIONS_SPEC["story.reaction.generate"]["schema"]
    assert tuple(card.model_fields) == (
        "scene_id",
        "character_id",
        "additional_notes",
    )
    assert tuple(reaction.model_fields) == (
        "scene_id",
        "character_ids",
        "additional_notes",
    )


def test_story_task_confirmation_rejects_old_or_widened_scope():
    scene_id = str(uuid.uuid4())
    character_id = str(uuid.uuid4())
    card_options = {
        "consumer_action": STORY_CHARACTER_CARD_ACTION,
        "retrieval_purpose": "story_character_card",
        "scope": "scene",
        "scene_id": scene_id,
        "visible_until_scene_id": scene_id,
        "chapter_index": None,
        "visible_until_chapter": None,
        "visible_until_offset": None,
        "content_mode": "canonical",
        "context_mode": "canonical",
        "include_pending_objects": False,
        "budget_tokens": 6000,
        "character_ids": [character_id],
        "reveal_mode": "character",
        "viewpoint_character_id": character_id,
    }
    validate_story_generation_confirmation(
        card_options,
        action=STORY_CHARACTER_CARD_ACTION,
        scene_id=scene_id,
        character_ids=[character_id],
    )

    for key, value in (
        ("consumer_action", "writing.generate"),
        ("retrieval_purpose", "story_character_reaction"),
        ("visible_until_scene_id", str(uuid.uuid4())),
        ("visible_until_chapter", 4),
        ("budget_tokens", 0),
        ("viewpoint_character_id", str(uuid.uuid4())),
        ("character_ids", [str(uuid.uuid4())]),
    ):
        with pytest.raises(ConflictError):
            validate_story_generation_confirmation(
                {**card_options, key: value},
                action=STORY_CHARACTER_CARD_ACTION,
                scene_id=scene_id,
                character_ids=[character_id],
            )

    reaction_action = "story.reaction.generate"
    reaction_options = {
        **card_options,
        "consumer_action": reaction_action,
        "retrieval_purpose": "story_character_reaction",
        "reveal_mode": "author_safe",
        "viewpoint_character_id": None,
    }
    validate_story_generation_confirmation(
        reaction_options,
        action=reaction_action,
        scene_id=scene_id,
        character_ids=[character_id],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prepare", "apply", "args_factory", "action", "task_type"),
    [
        (
            assistant_generation_tools._prepare_card,
            assistant_generation_tools._submit_card,
            lambda scene, character: GenerateCharacterCard(
                scene_id=scene, character_id=character
            ),
            STORY_CHARACTER_CARD_ACTION,
            STORY_CARD_TASK,
        ),
        (
            assistant_generation_tools._prepare_reactions,
            assistant_generation_tools._submit_reactions,
            lambda scene, character: GenerateCharacterReactions(
                scene_id=scene, character_ids=[character]
            ),
            "story.reaction.generate",
            "story_reaction_propose",
        ),
    ],
)
async def test_generation_assistant_prepare_is_free_and_apply_reuses_confirmed_snapshot(
    monkeypatch, prepare, apply, args_factory, action, task_type
):
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    character_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    snapshot = {"novel_id": str(novel_id), "profile": {"model": "run-model"}}
    context = SimpleNamespace(
        operation_id=operation_id,
        work=SimpleNamespace(
            scene_id=str(scene_id),
            context_confirmation_id=None,
            excluded_targets=(),
        ),
        llm_snapshot=snapshot,
        internal_meta={"root_run_id": "root-run"},
    )
    args = args_factory(scene_id, character_id)
    preview_calls = []
    confirmations = []
    enqueues = []

    async def require_targets(*_args, **_kwargs):
        return None

    async def preview_context(_db, options):
        preview_calls.append(options)
        return {"context_fingerprint": "f" * 64, "blockers": []}

    async def confirm(_db, request):
        confirmations.append(request)
        return SimpleNamespace(id="confirmed-context")

    async def enqueue(_db, request, **kwargs):
        enqueues.append((request, kwargs))
        return SimpleNamespace(task_id="queued-task", status="pending")

    monkeypatch.setattr(
        assistant_generation_tools,
        "get",
        lambda key: (
            require_targets if key is ASSISTANT_REQUIRE_OPERATION_TARGETS else None
        ),
    )
    monkeypatch.setattr(
        assistant_generation_tools, "preview_context_confirmation", preview_context
    )
    monkeypatch.setattr(assistant_generation_tools, "confirm_context", confirm)
    monkeypatch.setattr(
        assistant_generation_tools, "enqueue_confirmed_story_task", enqueue
    )

    preview = await prepare(None, str(novel_id), args, context=context)
    assert preview["context_confirmation_id"] is None
    assert preview["context_parameters"]["budget_tokens"] == 6000
    assert len(preview_calls) == 1
    assert confirmations == []
    assert enqueues == []

    result = await apply(None, str(novel_id), args, preview, context=context)

    assert result.task_id == "queued-task"
    assert len(preview_calls) == 2  # apply rematerializes the preview before confirming
    assert len(confirmations) == len(enqueues) == 1
    assert confirmations[0].action == action
    assert confirmations[0].retrieval_purpose in {
        "story_character_card",
        "story_character_reaction",
    }
    assert confirmations[0].expected_context_fingerprint == "f" * 64
    request, metadata = enqueues[0]
    assert request.context_confirmation_id == "confirmed-context"
    assert request.operation_id == operation_id
    assert metadata["action"] == action
    assert metadata["task_type"] == task_type
    assert metadata["llm_execution_snapshot"] == snapshot
    assert metadata["extra_meta"] == {"root_run_id": "root-run"}


@pytest.mark.asyncio
async def test_generation_assistant_apply_stops_when_preview_scope_changes(monkeypatch):
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    character_id = uuid.uuid4()
    context = SimpleNamespace(
        operation_id=uuid.uuid4(),
        work=SimpleNamespace(
            scene_id=str(scene_id),
            context_confirmation_id=None,
            excluded_targets=(),
        ),
        llm_snapshot={"novel_id": str(novel_id)},
    )
    args = GenerateCharacterCard(scene_id=scene_id, character_id=character_id)
    fingerprints = iter(("a" * 64, "b" * 64))
    called = {"confirm": False, "enqueue": False}

    async def require_targets(*_args, **_kwargs):
        return None

    async def preview_context(_db, _options):
        return {"context_fingerprint": next(fingerprints), "blockers": []}

    async def fail_if_called(*_args, **_kwargs):
        called["confirm"] = True
        return None

    async def enqueue(*_args, **_kwargs):
        called["enqueue"] = True
        return None

    monkeypatch.setattr(assistant_generation_tools, "get", lambda _key: require_targets)
    monkeypatch.setattr(
        assistant_generation_tools, "preview_context_confirmation", preview_context
    )
    monkeypatch.setattr(assistant_generation_tools, "confirm_context", fail_if_called)
    monkeypatch.setattr(
        assistant_generation_tools, "enqueue_confirmed_story_task", enqueue
    )

    preview = await assistant_generation_tools._prepare_card(
        None, str(novel_id), args, context=context
    )
    with pytest.raises(ConflictError, match="场景或资料确认已变化"):
        await assistant_generation_tools._submit_card(
            None, str(novel_id), args, preview, context=context
        )
    assert called == {"confirm": False, "enqueue": False}


@pytest.mark.asyncio
async def test_existing_assistant_confirmation_is_revalidated_and_reused(monkeypatch):
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    character_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    context = SimpleNamespace(
        operation_id=operation_id,
        work=SimpleNamespace(
            scene_id=str(scene_id),
            chapter_index=None,
            context_confirmation_id="existing-confirmation",
            context_confirmation_action=STORY_CHARACTER_CARD_ACTION,
            excluded_targets=(),
        ),
        llm_snapshot={"novel_id": str(novel_id)},
    )
    args = GenerateCharacterCard(scene_id=scene_id, character_id=character_id)
    fixed = SimpleNamespace(
        compile_options={
            "consumer_action": STORY_CHARACTER_CARD_ACTION,
            "scope": "scene",
            "scene_id": str(scene_id),
            "visible_until_scene_id": str(scene_id),
            "character_ids": [str(character_id)],
            "reveal_mode": "character",
            "viewpoint_character_id": str(character_id),
            "context_mode": "canonical",
            "content_mode": "canonical",
            "include_pending_objects": False,
            "budget_tokens": 6000,
            "retrieval_purpose": "story_character_card",
        },
        confirmation=SimpleNamespace(context_fingerprint="c" * 64),
    )
    enqueued = []

    async def require_targets(*_args, **_kwargs):
        return None

    async def prepare_confirmed(*_args, **_kwargs):
        return fixed

    async def should_not_preview(*_args, **_kwargs):
        raise AssertionError("confirmed Story scope must not be widened or re-previewed")

    async def should_not_confirm(*_args, **_kwargs):
        raise AssertionError("existing confirmation must be reused")

    async def enqueue(_db, request, **kwargs):
        enqueued.append((request, kwargs))
        return SimpleNamespace(task_id="reused-task", status="pending")

    monkeypatch.setattr(assistant_generation_tools, "get", lambda _key: require_targets)
    monkeypatch.setattr(
        assistant_generation_tools, "prepare_confirmed_ai_action", prepare_confirmed
    )
    monkeypatch.setattr(
        assistant_generation_tools, "preview_context_confirmation", should_not_preview
    )
    monkeypatch.setattr(assistant_generation_tools, "confirm_context", should_not_confirm)
    monkeypatch.setattr(
        assistant_generation_tools, "enqueue_confirmed_story_task", enqueue
    )

    preview = await assistant_generation_tools._prepare_card(
        None, str(novel_id), args, context=context
    )
    result = await assistant_generation_tools._submit_card(
        None, str(novel_id), args, preview, context=context
    )

    assert result.task_id == "reused-task"
    assert len(enqueued) == 1
    assert enqueued[0][0].context_confirmation_id == "existing-confirmation"

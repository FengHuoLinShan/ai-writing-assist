from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import pytest

from modules.story import tasks as story_tasks
from modules.story.generation import (
    STORY_CHARACTER_CARD_ACTION,
    STORY_ONE_CLICK_ACTION,
    STORY_REACTION_ACTION,
    STORY_SCRIPT_ACTION,
)
from modules.story.schemas import (
    CardPreview,
    CharacterCardContent,
    ReactionPreview,
    ScriptPreview,
    StoryCardTaskRequest,
    StoryOneClickTaskRequest,
    StoryTaskRequest,
)
from modules.story.tasks import _character_card_source_hashes, _parse_task_request

NOVEL_ID = str(uuid.uuid4())
SCENE_ID = str(uuid.uuid4())
CHARACTER_ID = str(uuid.uuid4())


@pytest.mark.parametrize(
    ("action", "model", "request_data"),
    [
        (
            STORY_CHARACTER_CARD_ACTION,
            StoryCardTaskRequest,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_id": CHARACTER_ID,
                "context_confirmation_id": "confirmation-card",
                "confirmed": True,
            },
        ),
        (
            STORY_REACTION_ACTION,
            StoryTaskRequest,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_ids": [CHARACTER_ID],
                "context_confirmation_id": "confirmation-reaction",
                "confirmed": True,
            },
        ),
        (
            STORY_SCRIPT_ACTION,
            StoryTaskRequest,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_ids": [CHARACTER_ID],
                "context_confirmation_id": "confirmation-script",
                "confirmed": True,
            },
        ),
        (
            STORY_ONE_CLICK_ACTION,
            StoryOneClickTaskRequest,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_ids": [CHARACTER_ID],
                "submit_authorized": True,
            },
        ),
    ],
)
def test_story_task_request_projection_accepts_v1_and_legacy_flat_meta(
    action: str,
    model: type,
    request_data: dict,
) -> None:
    envelope = {
        "meta_version": 1,
        "request": request_data,
        "action": action,
        "llm_execution_snapshot": {"novel_id": NOVEL_ID},
        "authorization_scope": "preview_only",
    }
    parsed_envelope = _parse_task_request(envelope, model)
    assert parsed_envelope.novel_id == NOVEL_ID

    legacy_flat = {
        **request_data,
        "action": action,
        "llm_execution_snapshot": {"novel_id": NOVEL_ID},
        "authorization_scope": "preview_only",
    }
    parsed_legacy = _parse_task_request(legacy_flat, model)
    assert parsed_legacy.model_dump(mode="json") == parsed_envelope.model_dump(
        mode="json"
    )


def test_character_card_source_hash_uses_stable_per_character_reveal() -> None:
    scene = {"outline_bundle": {"scene_id": SCENE_ID}}
    reveal = {CHARACTER_ID: {"hash": "a" * 64}}
    first = _character_card_source_hashes(
        scene, _Compiled(), "safe", [CHARACTER_ID], reveal
    )
    second = _character_card_source_hashes(
        scene, _Compiled(), "safe", [CHARACTER_ID], reveal
    )
    changed = _character_card_source_hashes(
        scene,
        _Compiled(),
        "safe",
        [CHARACTER_ID],
        {CHARACTER_ID: {"hash": "b" * 64}},
    )
    assert first == second
    assert first[CHARACTER_ID] != changed[CHARACTER_ID]


class _Compiled:
    budget_tokens = 6000
    total_tokens = 10
    warnings: list[str] = []

    def __init__(self) -> None:
        self.sections = [
            SimpleNamespace(
                key="scene",
                tier=1,
                content="safe scene context",
                status="ready",
                token_count=10,
                sources=[],
            )
        ]


class _Db:
    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    def in_transaction(self) -> bool:
        return False

    def expire_all(self) -> None:
        return None


class _Task:
    def __init__(self, task_type: str, meta: dict) -> None:
        self.id = uuid.uuid4()
        self.task_type = task_type
        self.meta = meta
        self.progress: list[float] = []

    def update_progress(self, value: float) -> None:
        self.progress.append(value)


class _StoryGeneration:
    async def card_preview(self, _client, *, character_id, **_kwargs):
        return CardPreview(
            character_id=character_id,
            content=CharacterCardContent(personality="克制"),
        )

    async def reaction_preview(self, _client, *, scene_context, character_ids, **_kwargs):
        return ReactionPreview(scene_id=scene_context["scene_id"], proposals=[])

    async def script_preview(self, _client, *, scene_context, **_kwargs):
        return ScriptPreview(
            scene_id=scene_context["scene_id"],
            script_text="人物做出选择。",
            narrative_plan="先制造压力，再留下代价。",
        )


@pytest.mark.asyncio
async def test_all_story_handlers_start_from_v1_envelope(monkeypatch) -> None:
    compiled = _Compiled()
    story_context = SimpleNamespace(
        context_hash="context-hash",
        model_dump=lambda mode="json": {
            "scene_id": SCENE_ID,
            "context_hash": "context-hash",
            "character_cards": [],
            "script_files": [],
            "outline_bundle": {},
        },
    )
    snapshot_id = uuid.uuid4()

    async def _compile(*_args, **_kwargs):
        return compiled

    async def _prepare(_db, **_kwargs):
        return SimpleNamespace(
            compiled=compiled,
            compile_options={"context_mode": "working", "reveal_mode": "author_safe"},
        )

    async def _restore(*_args, **_kwargs):
        return {"model": "test-model"}

    async def _snapshot(*_args, **_kwargs):
        return SimpleNamespace(id=snapshot_id)

    async def _story_context(*_args, **_kwargs):
        return story_context

    async def _reveals(*_args, **kwargs):
        return {
            str(character_id): {"markdown": "character-safe", "hash": "r" * 64}
            for character_id in kwargs["character_ids"]
        }

    @asynccontextmanager
    async def _client(*_args, **_kwargs):
        yield SimpleNamespace(model_name="test-model", close=lambda: None)

    @contextmanager
    def _provenance():
        yield []

    monkeypatch.setattr(story_tasks, "require_task_checkpoint_session", lambda _db: None)
    monkeypatch.setattr(story_tasks, "compile_with_tiers", _compile)
    monkeypatch.setattr(story_tasks, "prepare_confirmed_ai_action", _prepare)
    monkeypatch.setattr(story_tasks, "create_context_snapshot", _snapshot)
    monkeypatch.setattr(story_tasks, "render_compiled_context", lambda _value: "shared")
    monkeypatch.setattr(story_tasks, "get_scene_story_context", _story_context)
    monkeypatch.setattr(story_tasks, "_compile_character_reveals", _reveals)
    monkeypatch.setattr(story_tasks, "restore_project_llm_execution_settings", _restore)
    monkeypatch.setattr(story_tasks, "_checkpoint_before_provider", _compile)
    monkeypatch.setattr(story_tasks, "_open_client", _client)
    monkeypatch.setattr(story_tasks, "managed_llm_provenance_scope", _provenance)
    monkeypatch.setattr(story_tasks, "StoryGenerationService", _StoryGeneration)
    monkeypatch.setattr(story_tasks, "require_active_project_exclusive", _compile)

    async def _persist(*_args, **_kwargs):
        return [uuid.uuid4()], []

    monkeypatch.setattr(story_tasks, "persist_one_click_character_cards", _persist)

    cases = [
        (
            story_tasks.handle_story_character_card_generate,
            "story_character_card_generate",
            STORY_CHARACTER_CARD_ACTION,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_id": CHARACTER_ID,
                "context_confirmation_id": "card-confirmation",
                "confirmed": True,
            },
        ),
        (
            story_tasks.handle_story_reaction_propose,
            "story_reaction_propose",
            STORY_REACTION_ACTION,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_ids": [CHARACTER_ID],
                "context_confirmation_id": "reaction-confirmation",
                "confirmed": True,
            },
        ),
        (
            story_tasks.handle_story_scene_script_generate,
            "story_scene_script_generate",
            STORY_SCRIPT_ACTION,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_ids": [CHARACTER_ID],
                "context_confirmation_id": "script-confirmation",
                "confirmed": True,
            },
        ),
        (
            story_tasks.handle_story_one_click,
            "story_one_click",
            STORY_ONE_CLICK_ACTION,
            {
                "novel_id": NOVEL_ID,
                "scene_id": SCENE_ID,
                "character_ids": [CHARACTER_ID],
                "submit_authorized": True,
            },
        ),
    ]
    for handler, task_type, action, request_data in cases:
        task = _Task(
            task_type,
            {
                "meta_version": 1,
                "request": request_data,
                "action": action,
                "submit_authorized": request_data.get("submit_authorized", False),
                "llm_execution_snapshot": {
                    "novel_id": NOVEL_ID,
                    "profile": {"model": "test-model"},
                },
            },
        )
        result = await handler(_Db(), task)
        assert result["context_snapshot_id"] == str(snapshot_id)
        assert task.progress[-1] == 1.0

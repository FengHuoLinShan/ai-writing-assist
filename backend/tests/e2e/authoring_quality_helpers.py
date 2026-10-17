"""Prove director evaluation receipts using a normal API and an offline worker."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

from httpx import ASGITransport
from sqlalchemy import select

from app.main import app
from core.database import get_manager
from evals.authoring_quality_guard import ProductReference
from evals.authoring_quality_product import read_product_evidence
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.story import director_tasks
from modules.story.models import StorySceneDirectorRoot, StorySceneDirectorRound
from tests.support.http import XhrAsyncClient


async def assert_director_product_evidence(
    monkeypatch, novel_id, scene_id, actor_id, confirmation_id
):
    class Provider:
        name = "offline-authoring-director"
        calls = 0

        async def generate(self, request):
            self.calls += 1
            data = json.loads(
                next(
                    message.content
                    for message in reversed(request.messages)
                    if message.role == "user"
                )
            )
            if self.calls == 1:
                payload = {"kind": "observe", "action": "停下脚步观察", "effect": "none"}
            elif self.calls == 2:
                payload = {
                    "outcomes": [
                        {"intent_id": item["intent_id"], "outcome": "succeeded"}
                        for item in data["intents"]
                    ]
                }
            elif self.calls == 3:
                payload = {
                    "character_id": str(actor_id),
                    "action": "停步观察",
                    "expression": "眉间收紧",
                    "body_language": "侧身倾听",
                    "voice_and_dialogue": "先等等。",
                    "subtext": "确认环境",
                    "motive_and_emotion": "谨慎",
                    "trigger_and_defense": "陌生标记",
                    "attention": "门前",
                    "ignored": "身后",
                    "change_from_previous": "初次",
                    "basis": [{"source_kind": "director_inference", "note": "合成候选"}],
                }
            elif self.calls == 4:
                payload = {
                    "materials": [],
                    "recommended_angles": [
                        {
                            "angle_id": "close",
                            "label": "人物近景",
                            "viewpoint_kind": "character",
                            "viewpoint_character_id": str(actor_id),
                            "narrative_distance": "close",
                            "focus": "门前",
                            "detail_and_pacing": "放慢",
                            "material_ids": [],
                        },
                        {
                            "angle_id": "wide",
                            "label": "全景",
                            "viewpoint_kind": "omniscient",
                            "narrative_distance": "omniscient",
                            "focus": "停步",
                            "detail_and_pacing": "平稳",
                            "material_ids": [],
                        },
                    ],
                    "alternatives": [
                        {
                            "alternative_id": "wait",
                            "label": "等待",
                            "branch_instruction": "留在原处",
                            "divergence": "conservative",
                        },
                        {
                            "alternative_id": "watch",
                            "label": "观察",
                            "branch_instruction": "谨慎观察",
                            "divergence": "balanced",
                        },
                    ],
                }
            else:
                raise AssertionError("director exceeded the four planned offline calls")
            return LLMCallResponse(
                content=json.dumps(payload, ensure_ascii=False),
                finish_reason="stop",
                model="deepseek-flash",
                provider=self.name,
                usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            )

    provider = Provider()

    @asynccontextmanager
    async def offline_client(_db, _novel_id, _snapshot):
        client = LLMClient.from_project_settings(
            {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
        )
        client._provider = provider
        yield client

    monkeypatch.setattr(
        director_tasks, "open_project_snapshot_llm_client", offline_client
    )
    request = {
        "operation_id": str(uuid4()),
        "novel_id": str(novel_id),
        "scene_id": str(scene_id),
        "character_ids": [str(actor_id)],
        "primary_character_ids": [str(actor_id)],
        "rounds": 1,
    }
    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        preview = await client.post(
            "/api/story/scenes/director/budget-preview", json=request
        )
        assert preview.status_code == 200, preview.text
        started = await client.post(
            f"/api/story/scenes/{scene_id}/director",
            json={
                **request,
                "request_limit": 6,
                "token_limit": 100000,
                "time_budget_seconds": 300,
                "context_confirmation_id": confirmation_id,
                "budget_preview_hash": preview.json()["preview_hash"],
            },
        )
        assert started.status_code == 202, started.text
    task_id = UUID(started.json()["task_id"])
    await TaskWorker(db_manager=get_manager()).run_once(
        task_id=task_id, novel_id=novel_id
    )
    async with get_manager().session_factory() as db:
        task = await db.get(AsyncTask, task_id)
        assert task.status == "done", task.error_message
        assert task.result["status"] == "complete", task.result
        assert provider.calls == 4
        root = await db.get(StorySceneDirectorRoot, UUID(started.json()["root_id"]))
        rows = (
            await db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.root_id == root.id
                )
            )
        ).all()
        assert len(rows) == 1
        reference = ProductReference(
            kind="director",
            scene_id=str(scene_id),
            root_id=str(root.id),
            branch_id=str(rows[0].branch_id),
            task_id=str(task_id),
            source_sha256=rows[0].source_hash,
            output_ids=[str(rows[0].id)],
        )
        evidence = await read_product_evidence(
            db,
            SimpleNamespace(
                project_id=str(novel_id),
                project_snapshot=root.llm_execution_snapshot_json,
            ),
            reference,
        )
        assert evidence["outputs"][0]["output_sha256"] == rows[0].output_hash
        assert evidence["confirmation"]["id"] == confirmation_id

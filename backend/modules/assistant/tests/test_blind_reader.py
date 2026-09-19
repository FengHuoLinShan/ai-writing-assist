"""Reader inputs never contain future prose, titles, goals, or prior answer keys."""

import json
import uuid
from dataclasses import replace

from core.config import get_settings
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.assistant.models import AssistantRun
from modules.assistant.service import AssistantService
from modules.writing.facade import create_draft_only


async def test_blind_reader_unlocks_chapters_and_preserves_guess_before_reveal(
    async_client, db_session, test_project_id, account_llm_connection, monkeypatch
):
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_blind_reader_enabled=True
    )
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    monkeypatch.setattr(db_session, "task_checkpoint_enabled", True, raising=False)
    seen = []

    class Client:
        model_name = "deepseek-flash"

        async def generate(self, request, **kwargs):
            output = next(
                tool for tool in request.tools if tool.name.startswith("final_result")
            )
            body = json.loads(request.messages[-1].content)
            if "known" in output.parameters["properties"]:
                seen.append(body)
                assert "标题透露凶手" not in json.dumps(body, ensure_ascii=False)
                assert "作者知道凶手" not in json.dumps(body, ensure_ascii=False)
                if len(seen) == 1:
                    assert "真正拿走钥匙" not in json.dumps(body, ensure_ascii=False)
                    result = {
                        "guesses": [{"belief": "可能是门卫", "excerpt": "门卫走开了"}],
                        "unanswered": ["钥匙在哪里？"],
                    }
                else:
                    assert (
                        body["prior_beliefs"][0]["guesses"][0]["belief"] == "可能是门卫"
                    )
                    result = {
                        "newly_revealed": [
                            {
                                "belief": "孩子拿走钥匙",
                                "excerpt": "孩子才是真正拿走钥匙的人",
                            }
                        ]
                    }
            else:
                result = {
                    "answer": "此前猜测与后续揭示已分别冻结；这是模拟读者的诊断建议。"
                }
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id=str(uuid.uuid4()),
                        name=output.name,
                        arguments=json.dumps(result),
                    )
                ],
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def close(self):
            pass

    async def govern(client, **kwargs):
        return {
            "status": "passed",
            "text": kwargs["output"],
            "review": {"status": "passed"},
        }

    monkeypatch.setattr(
        "modules.assistant.service.create_project_snapshot_llm_client",
        lambda *a, **kw: Client(),
    )
    monkeypatch.setattr("modules.assistant.service.govern_group_output", govern)
    await create_draft_only(
        db_session,
        test_project_id,
        1,
        title="标题透露凶手",
        content="门卫走开了。钥匙不见了。",
    )
    draft = await create_draft_only(
        db_session, test_project_id, 2, content="孩子才是真正拿走钥匙的人。"
    )
    await db_session.commit()
    session = (
        await async_client.post(
            "/api/assistant/sessions", json={"novel_id": test_project_id}
        )
    ).json()["id"]
    created = await async_client.post(
        f"/api/assistant/sessions/{session}/team-runs",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "blueprint": "blind_reader",
            "message": "作者知道凶手，请检查铺垫",
            "reading_start_chapter": 1,
            "context": {"page": "writing", "draft_id": draft.id, "chapter_index": 2},
        },
    )
    assert created.status_code == 202, created.text
    task = await db_session.get(AsyncTask, uuid.UUID(created.json()["task_id"]))
    await AssistantService().execute(db_session, task)
    run = await db_session.get(AssistantRun, uuid.UUID(created.json()["id"]))
    assert run.status == "completed", run.checkpoint_json.get("failure")
    trail = run.result_json["collaboration"]["reading_nodes"]
    assert len(trail) == 2
    assert trail[0]["beliefs"]["guesses"][0]["belief"] == "可能是门卫"
    assert len(seen) == 2

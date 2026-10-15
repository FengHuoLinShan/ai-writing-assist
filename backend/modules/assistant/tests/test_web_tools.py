from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from core.config import get_settings
from infrastructure.llm import web_search
from infrastructure.llm.agent_runtime import AgentRunBudget
from modules.account.facade import current_account_id
from modules.assistant.evidence_tools import (
    AssistantToolContext,
    author_read_tools,
    project_vocabulary,
    read_web_source,
    search_general_fact,
)
from modules.assistant.operations import validate_agent_answer
from modules.assistant.schemas import AssistantAnswer, WorkContext


@pytest.mark.asyncio
async def test_web_tools_keep_budget_and_references_across_resume(
    db_session, test_project_id, monkeypatch
):
    monkeypatch.setattr(
        web_search,
        "get_settings",
        lambda: replace(get_settings(), web_search_url="http://search:8080"),
    )
    reads = []

    async def search(question, **kwargs):
        await kwargs["before_request"]()
        return {
            "hits": [
                {
                    "url": "https://example.org/water",
                    "title": "水",
                    "coverage": "search_snippet",
                }
            ],
            "omissions": [],
        }

    async def read(url, **kwargs):
        reads.append(url)
        await kwargs["before_request"]()
        return {
            "url": url,
            "title": "水",
            "text": "沸点随压力变化。",
            "coverage": "page_text",
        }

    monkeypatch.setattr(web_search, "search_public_fact", search)
    monkeypatch.setattr(web_search, "read_public_page", read)
    checkpoints = []

    async def checkpoint(value):
        checkpoints.append(dict(value))

    deps = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(),
        None,
        AgentRunBudget(),
        checkpoint,
        allow_web=True,
        web_snapshot=web_search.search_snapshot(),
    )
    ctx = SimpleNamespace(deps=deps)
    result = await search_general_fact(ctx, "水的沸点")
    key = result["hits"][0]["evidence_id"]
    with pytest.raises(ModelRetry):
        validate_agent_answer(ctx, AssistantAnswer(answer="已查证", evidence_ids=[key]))
    page = await read_web_source(ctx, key)
    assert validate_agent_answer(
        ctx, AssistantAnswer(answer="已读取", evidence_ids=[page["evidence_id"]])
    )
    assert deps.budget.web_requests == 2 and deps.budget.requests == 0
    assert deps.budget.usage_complete and checkpoints[-1]["web_requests"] == 2
    restored = replace(
        deps,
        evidence_refs=dict(deps.evidence_refs),
        budget=AgentRunBudget.model_validate(checkpoints[-1]),
    )
    assert await read_web_source(SimpleNamespace(deps=restored), key) == page
    assert len(reads) == 1
    with pytest.raises(ModelRetry):
        await read_web_source(ctx, "https://example.org/arbitrary")
    restored.allow_web = False
    with pytest.raises(ValueError):
        await read_web_source(SimpleNamespace(deps=restored), key)


def test_old_tool_catalog_does_not_acquire_new_search_tools():
    assert "research_fact" in {
        t.name for t in author_read_tools(allow_web=True, version="2")
    }
    assert "search_general_fact" not in {
        t.name for t in author_read_tools(allow_web=True, version="2")
    }
    assert {"search_general_fact", "read_web_source"}.issubset(
        {t.name for t in author_read_tools(allow_web=True, version="3")}
    )


def test_runtime_v4_preserves_the_v3_read_tool_catalog():
    v3 = author_read_tools(allow_web=True, version="3")
    v4 = author_read_tools(allow_web=True, version="4")
    assert {tool.name for tool in v4} == {tool.name for tool in v3} | {
        "project_vocabulary"
    }
    assert {
        tool.name: tool.function_schema.json_schema
        for tool in v4
        if tool.name != "project_vocabulary"
    } == {tool.name: tool.function_schema.json_schema for tool in v3}
    for version in ("1", "2", "3"):
        assert "project_vocabulary" not in {
            tool.name for tool in author_read_tools(allow_web=True, version=version)
        }


@pytest.mark.asyncio
async def test_project_vocabulary_reads_current_ids_and_revisions_with_scope_guards(
    db_session, test_project_id
):
    from uuid import uuid4

    from core.errors import ConflictError, NotFoundError
    from modules.world.project_vocabulary_schemas import VocabularyTermCreate
    from modules.world.project_vocabulary_service import create_project_vocabulary_term

    term = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="space", name="星海", traits={"geometry": ["area"]}),
    )
    await create_project_vocabulary_term(
        db_session, test_project_id, VocabularyTermCreate(kind="space", name="秘境")
    )
    deps = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(scope="project"),
        None,
        AgentRunBudget(),
        None,
    )
    result = await project_vocabulary(SimpleNamespace(deps=deps), kind="space", limit=1)
    assert result["total_count"] == 2 and result["omitted_count"] == 1
    assert set(result["items"][0]) >= {"id", "revision_id", "name", "traits"}
    all_items = await project_vocabulary(SimpleNamespace(deps=deps), kind="space")
    assert any(
        item["id"] == str(term.id) and item["revision_id"] == str(term.revision_id)
        for item in all_items["items"]
    )
    assert not deps.evidence_refs
    deps.owner_id = str(uuid4())
    with pytest.raises(NotFoundError):
        await project_vocabulary(SimpleNamespace(deps=deps))
    deps.owner_id = str(current_account_id())
    deps.work = WorkContext(scope="project", excluded_targets=[f"term:{term.id}"])
    with pytest.raises(ConflictError):
        await project_vocabulary(SimpleNamespace(deps=deps))
    deps.work = WorkContext(scope="current", chapter_index=1)
    with pytest.raises(ModelRetry, match="全书"):
        await project_vocabulary(SimpleNamespace(deps=deps))

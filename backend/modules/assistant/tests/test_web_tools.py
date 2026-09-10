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

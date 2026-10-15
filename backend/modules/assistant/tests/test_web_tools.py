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
    map_spatial_brief,
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


def test_runtime_v5_adds_map_read_without_mutating_v1_through_v4():
    v4 = author_read_tools(allow_web=True, version="4")
    v5 = author_read_tools(allow_web=True, version="5")
    assert {tool.name for tool in v5} == {tool.name for tool in v4} | {
        "map_spatial_brief"
    }
    assert {
        tool.name: tool.function_schema.json_schema
        for tool in v5
        if tool.name != "map_spatial_brief"
    } == {tool.name: tool.function_schema.json_schema for tool in v4}
    for version in ("1", "2", "3", "4"):
        assert "map_spatial_brief" not in {
            tool.name for tool in author_read_tools(allow_web=True, version=version)
        }


@pytest.mark.asyncio
async def test_map_spatial_assistant_tool_is_off_by_default_and_revalidates_sources(
    db_session, test_project_id, monkeypatch
):
    from core import container
    from core.errors import ConflictError
    from core.service_keys import WORLD_READ_MAP_SPATIAL_BRIEF
    from modules.assistant import evidence_tools
    from modules.world.map_spatial_brief_schemas import (
        MapSpatialBriefItem,
        MapSpatialBriefResponse,
    )

    node_id, revision_id = "map-node", "map-revision"
    item = MapSpatialBriefItem(
        node_id=node_id,
        revision_id=revision_id,
        title="海港区",
        content='{"当前地点":[{"label":"白潮港"}]}',
        content_hash="a" * 64,
        revision_hash="b" * 64,
        geometry_hash="c" * 64,
        source_hashes=["d" * 64],
    )
    requests = []
    responses = [
        MapSpatialBriefResponse(items=[item]),
        MapSpatialBriefResponse(items=[item]),
        MapSpatialBriefResponse(items=[item]),
        MapSpatialBriefResponse(
            items=[item.model_copy(update={"content_hash": "e" * 64})]
        ),
    ]

    async def read(_db, request):
        requests.append(request)
        return responses.pop(0)

    get_service = container.get
    monkeypatch.setattr(
        evidence_tools,
        "get",
        lambda key: read if key == WORLD_READ_MAP_SPATIAL_BRIEF else get_service(key),
    )
    base_settings = get_settings()
    monkeypatch.setattr(
        evidence_tools,
        "get_settings",
        lambda: replace(base_settings, map_spatial_enabled_capabilities=()),
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
    ctx = SimpleNamespace(deps=deps)
    disabled = await map_spatial_brief(ctx, "白潮港")
    assert disabled["enabled"] is False and requests == []

    monkeypatch.setattr(
        evidence_tools,
        "get_settings",
        lambda: replace(
            base_settings, map_spatial_enabled_capabilities=("assistant.turn",)
        ),
    )
    deps.work = WorkContext(
        scope="current",
        chapter_index=3,
        excluded_targets=[f"map_spatial:{node_id}:{revision_id}"],
    )
    excluded = await map_spatial_brief(ctx, "白潮港")
    assert excluded["items"] == []
    assert excluded["omitted_count"] == 1
    assert requests[0]["excluded_ids"] == [f"map_spatial:{node_id}:{revision_id}"]

    deps.work = WorkContext(scope="project")
    result = await map_spatial_brief(ctx, "白潮港")
    evidence_id = result["items"][0]["evidence_id"]
    stored = deps.evidence_refs[evidence_id]
    assert stored["map_spatial_guard"]["baseline"][0]["revision_hash"] == "b" * 64
    assert "map_spatial_guard" not in result["items"][0]
    assert validate_agent_answer(
        ctx, AssistantAnswer(answer="白潮港位于海港区。", evidence_ids=[evidence_id])
    )
    await deps.revalidate([evidence_id])
    with pytest.raises(ConflictError, match="地图版本已变化"):
        await deps.revalidate([evidence_id])


@pytest.mark.asyncio
async def test_assistant_map_tool_requires_a_current_scene_or_project_scope(
    db_session, test_project_id, monkeypatch
):
    from pydantic_ai import ModelRetry

    from modules.assistant import evidence_tools

    monkeypatch.setattr(
        evidence_tools,
        "get_settings",
        lambda: replace(
            get_settings(), map_spatial_enabled_capabilities=("assistant.turn",)
        ),
    )
    deps = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(scope="current"),
        None,
        AgentRunBudget(),
        None,
    )
    with pytest.raises(ModelRetry, match="明确章节或 Scene"):
        await map_spatial_brief(SimpleNamespace(deps=deps), "海港在哪里")


def test_assistant_map_reference_is_receipted_as_advisory_without_public_guard():
    from modules.assistant.service import (
        _assistant_evidence_dimensions,
        display_sources,
    )

    guard = {"baseline": [{"revision_id": "revision", "revision_hash": "hash"}]}
    reference = {
        "title": "海港区",
        "snippet": "白潮港位于海港区。",
        "domain_reference": {"type": "map_spatial", "id": "node", "label": "海港区"},
        "map_spatial_guard": guard,
    }
    assert "map_spatial" in _assistant_evidence_dimensions({"map": reference})
    assert "map_spatial" not in _assistant_evidence_dimensions({"world": {}})
    public = display_sources({"map": reference}, ["map"])[0]
    assert public["domain_reference"]["type"] == "map_spatial"
    assert "map_spatial_guard" not in public


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

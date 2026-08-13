from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.project.schemas import ProjectCreate
from modules.project.services import ProjectService
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityRelationCreate,
    WorldBiblePageCreate,
    WorldBiblePageUpdate,
)
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.knowledge_graph_service import (
    WorldKnowledgeGraphService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)


@pytest.mark.asyncio
async def test_knowledge_graph_links_page_entity_and_relation(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    entities = WorldEntityService()
    first = await entities.create(
        db_session, project_novel_id, CoreEntityCreate(entity_type="location", name="甲")
    )
    second = await entities.create(
        db_session, project_novel_id, CoreEntityCreate(entity_type="location", name="乙")
    )
    relation = await EntityRelationService().create(
        db_session,
        project_novel_id,
        EntityRelationCreate(
            source_id=first.id, target_id=second.id, relation_type="road"
        ),
    )
    page = await WorldBibleLifecycleService().create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_type="location",
            title="甲页",
            status="canonical",
            linked_asset_refs_json=[
                {"target_type": "core_entity", "target_id": first.id},
                {"target_type": "entity_relation", "target_id": relation.id},
            ],
        ),
    )
    graph = await WorldKnowledgeGraphService().get(
        db_session,
        project_novel_id,
        scope="local",
        root_type="world_bible_page",
        root_id=page.id,
        depth=2,
    )
    assert {edge.kind for edge in graph.edges} == {
        "page_entity_reference",
        "entity_relation",
    }
    assert str(relation.id) in {edge.id for edge in graph.edges}
    expanded = [edge for edge in graph.edges if edge.via_relation_id == relation.id]
    assert {edge.target_id for edge in expanded} == {first.id, second.id}
    assert all(
        edge.authority == "canonical"
        and edge.source_ref["target_id"] == page.id
        and edge.revision == 1
        and edge.source_hash
        for edge in expanded
    )
    relation_edge = next(edge for edge in graph.edges if edge.id == relation.id)
    assert relation_edge.source_ref == {
        "target_type": "entity_relation",
        "target_id": relation.id,
        "target_path": "",
    }
    assert relation_edge.source_hash
    assert graph.dependency_coverage is False


@pytest.mark.asyncio
async def test_page_reference_depth_reverse_and_cycle(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    lifecycle = WorldBibleLifecycleService()
    pages = [
        await lifecycle.create_page(
            db_session,
            WorldBiblePageCreate(
                novel_id=project_novel_id,
                page_type="location",
                title=name,
                status="canonical",
            ),
        )
        for name in ("p1", "p2", "p3", "p4")
    ]
    for index, page in enumerate(pages[:3]):
        await lifecycle.update_page(
            db_session,
            project_novel_id,
            page.id,
            WorldBiblePageUpdate(
                linked_asset_refs_json=[
                    {
                        "target_type": "world_bible_page",
                        "target_id": pages[(index + 1) % 3].id,
                    },
                    *(
                        [{"target_type": "world_bible_page", "target_id": pages[3].id}]
                        if index == 2
                        else []
                    ),
                ]
            ),
        )
    depth_one = await WorldKnowledgeGraphService().get(
        db_session,
        project_novel_id,
        scope="local",
        root_type="world_bible_page",
        root_id=pages[1].id,
        depth=1,
    )
    graph = await WorldKnowledgeGraphService().get(
        db_session,
        project_novel_id,
        scope="local",
        root_type="world_bible_page",
        root_id=pages[1].id,
        depth=2,
    )
    assert {node.id for node in depth_one.nodes} == {
        pages[0].id,
        pages[1].id,
        pages[2].id,
    }
    assert {node.id for node in graph.nodes} == {page.id for page in pages}


@pytest.mark.asyncio
async def test_graph_excludes_candidates_and_reports_bad_refs(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    entities = WorldEntityService()
    entity = await entities.create(
        db_session, project_novel_id, CoreEntityCreate(entity_type="location", name="ok")
    )
    other = await entities.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="other"),
    )
    candidate_entity = await entities.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="candidate", status="candidate"),
    )
    relations = EntityRelationService()
    canonical_relation = await relations.create(
        db_session,
        project_novel_id,
        EntityRelationCreate(
            source_id=entity.id,
            target_id=other.id,
            relation_type="road",
        ),
    )
    candidate_relation = await relations.create(
        db_session,
        project_novel_id,
        EntityRelationCreate(
            source_id=entity.id,
            target_id=other.id,
            relation_type="rumor",
            status="candidate",
        ),
    )
    lifecycle = WorldBibleLifecycleService()
    page = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_type="location",
            title="ok",
            status="canonical",
            linked_asset_refs_json=[
                {"target_type": "core_entity", "target_id": entity.id}
            ],
        ),
    )
    page_model = await lifecycle.get_page_model(db_session, project_novel_id, page.id)
    # Simulate legacy/corrupt refs that bypass today's lifecycle validation.
    page_model.linked_asset_refs_json = [
        {"target_type": "core_entity", "target_id": entity.id},
        {"target_type": "core_entity", "target_id": "bad"},
        {"target_type": "core_entity", "target_id": candidate_entity.id},
    ]
    candidate_page = await lifecycle.create_page(
        db_session,
        WorldBiblePageCreate(
            novel_id=project_novel_id,
            page_type="location",
            title="candidate page",
            status="draft",
        ),
    )
    graph = await WorldKnowledgeGraphService().get(
        db_session,
        project_novel_id,
        scope="global",
        root_type=None,
        root_id=None,
        depth=1,
    )
    assert graph.omitted_counts["bad_or_unavailable_ref"] == 2
    assert candidate_entity.id not in {node.id for node in graph.nodes}
    assert candidate_page.id not in {node.id for node in graph.nodes}
    assert candidate_relation.id not in {edge.id for edge in graph.edges}
    assert canonical_relation.id in {edge.id for edge in graph.edges}
    with pytest.raises(NotFoundError):
        await WorldKnowledgeGraphService().get(
            db_session,
            project_novel_id,
            scope="local",
            root_type="core_entity",
            root_id=page.id,
            depth=1,
        )


@pytest.mark.asyncio
async def test_graph_truncation_is_deterministic_and_manifest_tracks_revisions(
    db_session: AsyncSession, project_novel_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = WorldKnowledgeGraphService()
    monkeypatch.setattr(service, "_PAGE_SCAN_LIMIT", 2)
    monkeypatch.setattr(service, "_GLOBAL_NODE_CAP", 1)
    lifecycle = WorldBibleLifecycleService()
    pages = [
        await lifecycle.create_page(
            db_session,
            WorldBiblePageCreate(
                novel_id=project_novel_id,
                page_type="location",
                title=name,
                status="canonical",
            ),
        )
        for name in ("a", "b", "c")
    ]
    first = await service.get(
        db_session,
        project_novel_id,
        scope="global",
        root_type=None,
        root_id=None,
        depth=1,
    )
    repeated = await service.get(
        db_session,
        project_novel_id,
        scope="global",
        root_type=None,
        root_id=None,
        depth=1,
    )
    assert repeated.model_dump() == first.model_dump()
    assert set(first.truncation_reasons) == {"page_scan_partial", "result_cap"}
    assert first.omitted_counts["page_scan_overflow"] == 1
    included_page = next(page for page in pages if page.id == first.nodes[0].id)
    await lifecycle.update_page(
        db_session,
        project_novel_id,
        included_page.id,
        WorldBiblePageUpdate(title="updated"),
    )
    second = await service.get(
        db_session,
        project_novel_id,
        scope="global",
        root_type=None,
        root_id=None,
        depth=1,
    )
    assert first.source_hash != second.source_hash
    monkeypatch.setattr(service, "_PAGE_SCAN_LIMIT", 3)
    monkeypatch.setattr(service, "_GLOBAL_NODE_CAP", 10)
    entity_service = WorldEntityService()
    entity = await entity_service.create(
        db_session,
        project_novel_id,
        CoreEntityCreate(entity_type="location", name="before"),
    )
    before_entity_edit = await service.get(
        db_session,
        project_novel_id,
        scope="global",
        root_type=None,
        root_id=None,
        depth=1,
    )
    await entity_service.update(
        db_session,
        entity.id,
        CoreEntityUpdate(name="after"),
        novel_id=project_novel_id,
    )
    after_entity_edit = await service.get(
        db_session,
        project_novel_id,
        scope="global",
        root_type=None,
        root_id=None,
        depth=1,
    )
    assert before_entity_edit.source_hash != after_entity_edit.source_hash


@pytest.mark.asyncio
async def test_graph_uses_bounded_query_count(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    entities = WorldEntityService()
    for index in range(8):
        await entities.create(
            db_session,
            project_novel_id,
            CoreEntityCreate(entity_type="location", name=f"entity-{index}"),
        )
    statements: list[str] = []

    def count_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count_selects)
    try:
        graph = await WorldKnowledgeGraphService().get(
            db_session,
            project_novel_id,
            scope="global",
            root_type=None,
            root_id=None,
            depth=1,
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_selects)
    assert len(graph.nodes) == 8
    assert len(statements) == 3


@pytest.mark.asyncio
async def test_knowledge_graph_api_enforces_owner_and_novel_isolation(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = Account(status="active", support_code="U-GRAPHOWNER")
    other = Account(status="active", support_code="U-GRAPHOTHER")
    db_session.add_all([owner, other])
    await db_session.flush()
    owner_token = bind_principal(_principal(owner))
    try:
        first = await ProjectService().create_project(
            db_session, ProjectCreate(title="关联图 A")
        )
        second = await ProjectService().create_project(
            db_session, ProjectCreate(title="关联图 B")
        )
        lifecycle = WorldBibleLifecycleService()
        first_page = await lifecycle.create_page(
            db_session,
            WorldBiblePageCreate(
                novel_id=first.id,
                page_type="location",
                title="A only",
                status="canonical",
            ),
        )
        second_page = await lifecycle.create_page(
            db_session,
            WorldBiblePageCreate(
                novel_id=second.id,
                page_type="location",
                title="B only",
                status="canonical",
            ),
        )
        response = await async_client.get(
            "/api/world/knowledge-graph", params={"novel_id": first.id}
        )
        assert response.status_code == 200
        node_ids = {node["id"] for node in response.json()["nodes"]}
        assert first_page.id in node_ids
        assert second_page.id not in node_ids
    finally:
        reset_principal(owner_token)

    other_token = bind_principal(_principal(other))
    try:
        response = await async_client.get(
            "/api/world/knowledge-graph", params={"novel_id": first.id}
        )
        assert response.status_code == 404
    finally:
        reset_principal(other_token)


def _principal(account: Account) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type="email",
        support_code=account.support_code,
    )

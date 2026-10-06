"""World library 路由：统一资料列表、主题目录与作者工作区。"""

from __future__ import annotations

import uuid

from fastapi import Query
from fastapi.responses import Response

from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _world_library_service,
    router,
)
from modules.world.relation_schemas import WorldRelationGroupListResponse
from modules.world.schemas import (
    WorldLibraryFavoriteRequest,
    WorldLibraryFavoriteResponse,
    WorldLibraryListResponse,
    WorldLibraryMemberRequest,
    WorldLibraryMemberResponse,
    WorldLibraryMembershipsResponse,
    WorldLibraryOverviewResponse,
    WorldLibraryRecentRequest,
    WorldLibraryTopicArchiveRequest,
    WorldLibraryTopicCreate,
    WorldLibraryTopicMoveRequest,
    WorldLibraryTopicNode,
    WorldLibraryTopicReorderRequest,
    WorldLibraryTopicTreeResponse,
    WorldLibraryTopicUpdate,
    WorldLibraryViewPrefsResponse,
    WorldLibraryViewPrefsUpdate,
)
from shared.constants import MAX_PAGE_SIZE


@router.get("/library/relation-groups", response_model=WorldRelationGroupListResponse)
async def list_world_relation_groups(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    group_view: str = Query(
        ..., description="关系视角：affiliation / location / possessions / event / custom"
    ),
    group_type: str | None = Query(None, description="custom 视角：分组对象类型"),
    member_type: str | None = Query(
        None, description="custom 视角：成员对象类型（可选）"
    ),
    relation_type: str | None = Query(None, description="custom 视角：详细关系"),
    group_side: str | None = Query(
        None, description="custom 视角：分组所在端 source / target"
    ),
    q: str | None = Query(None, description="按组名称或别名搜索"),
    skip: int = Query(default=0, ge=0, description="跳过的分组数"),
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页分组数",
    ),
) -> WorldRelationGroupListResponse:
    return await _world_library_service.list_relation_groups(
        db,
        novel_id,
        group_view=group_view,
        group_type=group_type,
        member_type=member_type,
        relation_type=relation_type,
        group_side=group_side,
        q=q,
        skip=skip,
        limit=limit,
    )


@router.get("/library", response_model=WorldLibraryListResponse)
async def list_world_library(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    q: str | None = Query(None, description="标题、正文或摘要的模糊搜索"),
    target_id: uuid.UUID | None = Query(None, description="项目内精确资料定位"),
    kind: str | None = Query("all", description="资料类别：all / entity / page / draft"),
    item_type: str | None = Query(None, description="实体类型或页面类型"),
    state: str | None = Query(
        None,
        description="作者展示状态：active / review / archived / working",
    ),
    working: bool | None = Query(None, description="是否有未发布工作稿"),
    favorite: bool | None = Query(None, description="是否收藏"),
    topic_id: str | None = Query(None, description="主题过滤"),
    topic_scope: str = Query("subtree", description="主题范围：subtree / topic"),
    unclassified: bool = Query(False, description="只看未加入任何主题的资料"),
    group_view: str | None = Query(None, description="关系视角（进入分组成员浏览）"),
    group_id: str | None = Query(None, description="分组视角：组对象 ID"),
    group_unlinked: bool = Query(False, description="分组视角：只看本视角尚无关联的对象"),
    group_type: str | None = Query(None, description="custom 视角：分组对象类型"),
    member_type: str | None = Query(
        None, description="custom 视角：成员对象类型（可选）"
    ),
    relation_type: str | None = Query(None, description="custom 视角：详细关系"),
    group_side: str | None = Query(
        None, description="custom 视角：分组所在端 source / target"
    ),
    sort: str = Query("updated", description="排序：updated / recent / title / created"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> WorldLibraryListResponse:
    return await _world_library_service.list_library(
        db,
        novel_id,
        q=q,
        target_id=str(target_id) if target_id else None,
        kind=kind,
        item_type=item_type,
        state=state,
        working=working,
        favorite=favorite,
        topic_id=topic_id,
        topic_scope=topic_scope,
        unclassified=unclassified,
        group_view=group_view,
        group_id=group_id,
        group_unlinked=group_unlinked,
        group_type=group_type,
        member_type=member_type,
        relation_type=relation_type,
        group_side=group_side,
        sort=sort,
        skip=skip,
        limit=limit,
    )


@router.get("/library/overview", response_model=WorldLibraryOverviewResponse)
async def get_world_library_overview(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldLibraryOverviewResponse:
    return await _world_library_service.overview(db, novel_id)


@router.post("/library/recents", status_code=204)
async def record_world_library_recent(
    db: DbSession,
    data: WorldLibraryRecentRequest,
) -> Response:
    await require_active_project(db, data.novel_id)
    await _world_library_service.record_recent(
        db,
        data.novel_id,
        data.target_kind,
        data.target_id,
    )
    return Response(status_code=204)


@router.post("/library/favorites", response_model=WorldLibraryFavoriteResponse)
async def add_world_library_favorite(
    db: DbSession,
    data: WorldLibraryFavoriteRequest,
) -> WorldLibraryFavoriteResponse:
    await require_active_project(db, data.novel_id)
    return await _world_library_service.set_favorite(
        db,
        data.novel_id,
        data.target_kind,
        data.target_id,
        favorited=True,
    )


@router.delete("/library/favorites", response_model=WorldLibraryFavoriteResponse)
async def remove_world_library_favorite(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    target_kind: str = Query(..., description="page / draft / entity"),
    target_id: str = Query(..., description="目标 ID"),
) -> WorldLibraryFavoriteResponse:
    return await _world_library_service.set_favorite(
        db,
        novel_id,
        target_kind,
        target_id,
        favorited=False,
    )


@router.get("/library/view-prefs", response_model=WorldLibraryViewPrefsResponse)
async def get_world_library_view_prefs(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldLibraryViewPrefsResponse:
    return await _world_library_service.get_view_prefs(db, novel_id)


@router.put("/library/view-prefs", response_model=WorldLibraryViewPrefsResponse)
async def update_world_library_view_prefs(
    db: DbSession,
    data: WorldLibraryViewPrefsUpdate,
) -> WorldLibraryViewPrefsResponse:
    await require_active_project(db, data.novel_id)
    return await _world_library_service.update_view_prefs(
        db,
        data.novel_id,
        data.view_prefs,
    )


@router.get("/library/topics", response_model=WorldLibraryTopicTreeResponse)
async def list_world_library_topics(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    include_archived: bool = Query(default=False),
) -> WorldLibraryTopicTreeResponse:
    topics = await _world_library_service.list_topic_tree(
        db,
        novel_id,
        include_archived=include_archived,
    )
    return WorldLibraryTopicTreeResponse(topics=topics)


@router.post("/library/topics", response_model=WorldLibraryTopicNode, status_code=201)
async def create_world_library_topic(
    db: DbSession,
    data: WorldLibraryTopicCreate,
) -> WorldLibraryTopicNode:
    await require_active_project(db, data.novel_id)
    return await _world_library_service.create_topic(db, data.novel_id, data)


@router.patch(
    "/library/topics/{topic_id}",
    response_model=WorldLibraryTopicNode,
)
async def update_world_library_topic(
    db: DbSession,
    topic_id: str,
    data: WorldLibraryTopicUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldLibraryTopicNode:
    return await _world_library_service.update_topic(
        db,
        novel_id,
        topic_id,
        data,
    )


@router.post("/library/topics/reorder", response_model=list[WorldLibraryTopicNode])
async def reorder_world_library_topics(
    db: DbSession,
    data: WorldLibraryTopicReorderRequest,
) -> list[WorldLibraryTopicNode]:
    await require_active_project(db, data.novel_id)
    return await _world_library_service.reorder_topics(db, data.novel_id, data)


@router.post(
    "/library/topics/{topic_id}/move",
    response_model=WorldLibraryTopicNode,
)
async def move_world_library_topic(
    db: DbSession,
    topic_id: str,
    data: WorldLibraryTopicMoveRequest,
) -> WorldLibraryTopicNode:
    await require_active_project(db, data.novel_id)
    return await _world_library_service.move_topic(
        db,
        data.novel_id,
        topic_id,
        data,
    )


@router.post(
    "/library/topics/{topic_id}/archive",
    response_model=WorldLibraryTopicNode,
)
async def archive_world_library_topic(
    db: DbSession,
    topic_id: str,
    data: WorldLibraryTopicArchiveRequest,
) -> WorldLibraryTopicNode:
    await require_active_project(db, data.novel_id)
    return await _world_library_service.archive_topic(
        db,
        data.novel_id,
        topic_id,
        archived=data.archived,
    )


@router.post(
    "/library/topics/{topic_id}/members",
    response_model=WorldLibraryMemberResponse,
    status_code=201,
)
async def add_world_library_topic_member(
    db: DbSession,
    topic_id: str,
    data: WorldLibraryMemberRequest,
) -> WorldLibraryMemberResponse:
    await require_active_project(db, data.novel_id)
    added = await _world_library_service.add_member(
        db,
        data.novel_id,
        topic_id,
        data,
    )
    return WorldLibraryMemberResponse(
        topic_id=topic_id,
        target_kind=data.target_kind,
        target_id=data.target_id,
        added=added,
    )


@router.delete("/library/topics/{topic_id}/members/{target_kind}/{target_id}")
async def remove_world_library_topic_member(
    db: DbSession,
    topic_id: str,
    target_kind: str,
    target_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    removed = await _world_library_service.remove_member(
        db,
        novel_id,
        topic_id,
        target_kind,
        target_id,
    )
    return {"topic_id": topic_id, "removed": removed}


@router.get("/library/memberships", response_model=WorldLibraryMembershipsResponse)
async def get_world_library_memberships(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    target_kind: str = Query(..., description="page / draft / entity"),
    target_id: str = Query(..., description="目标 ID"),
) -> WorldLibraryMembershipsResponse:
    topic_ids = await _world_library_service.memberships(
        db,
        novel_id,
        target_kind,
        target_id,
    )
    return WorldLibraryMembershipsResponse(topic_ids=topic_ids)

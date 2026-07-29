from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.project.models import Project, SmartDedupWorkbenchDecision
from modules.project.repositories import SmartDedupWorkbenchDecisionRepository
from modules.project.schemas import SmartDedupApplyRequest
from modules.project.smart_dedup import (
    SmartDedupService,
    _build_world_groups,
    _validate_group_request,
)
from modules.project.tasks import handle_smart_dedup_scan

pytestmark = [pytest.mark.asyncio]


async def test_smart_dedup_scan_api_enqueues_task(
    async_client: AsyncClient,
    account_llm_connection: dict,
) -> None:
    created = await async_client.post("/api/projects", json={"title": "去重测试"})
    assert created.status_code == 201
    project_id = created.json()["id"]

    resp = await async_client.post(
        f"/api/projects/{project_id}/smart-dedup/scan",
        json={"scopes": ["world_entity", "plot_thread"], "max_suggestions": 12},
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["task_id"]
    assert data["status"] == "pending"


async def test_old_pending_scan_materializes_snapshot_before_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    snapshot = {"schema_version": 1, "profile": {"model": "frozen-model"}}
    client = SimpleNamespace(model_name="frozen-model", close=AsyncMock())

    async def build(*args, **kwargs):
        events.append("build")
        return snapshot

    async def commit():
        events.append("checkpoint")

    async def restore(db, novel_id, received):
        events.append("restore")
        assert received == snapshot
        return {"llm": {"model": "frozen-model"}}

    def create(settings, *, novel_id):
        events.append("create")
        return client

    async def scan(self, *args, **kwargs):
        events.append("scan")
        assert kwargs["llm_client"] is client
        return {"schema_version": 2, "groups": [], "suggestions": []}

    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot",
        build,
    )
    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        restore,
    )
    monkeypatch.setattr(
        "modules.project.facade.create_project_snapshot_llm_client",
        create,
    )
    monkeypatch.setattr(SmartDedupService, "scan", scan)
    task = SimpleNamespace(
        meta={"novel_id": "00000000-0000-0000-0000-000000000001"},
        update_progress=lambda value: None,
    )
    db = SimpleNamespace(flush=AsyncMock(), commit=commit)

    await handle_smart_dedup_scan(db, task)

    assert task.meta["llm_execution_snapshot"] == snapshot
    assert events == ["build", "checkpoint", "restore", "create", "scan"]
    client.close.assert_awaited_once_with()


async def test_old_pending_scan_snapshot_survives_llm_stage_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(title="snapshot checkpoint")
    db_session.add(project)
    await db_session.flush()
    task = AsyncTask(
        task_type="smart_dedup_scan",
        status="running",
        meta={"novel_id": str(project.id)},
    )
    db_session.add(task)
    await db_session.commit()
    snapshot = {"schema_version": 1, "profile": {"model": "frozen-before-crash"}}
    client = SimpleNamespace(close=AsyncMock())

    async def fail_scan(*args, **kwargs):
        raise RuntimeError("simulated LLM-stage crash")

    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        AsyncMock(return_value={"llm": {"model": "frozen-before-crash"}}),
    )
    monkeypatch.setattr(
        "modules.project.facade.create_project_snapshot_llm_client",
        lambda *args, **kwargs: client,
    )
    monkeypatch.setattr(SmartDedupService, "scan", fail_scan)

    with pytest.raises(RuntimeError, match="simulated LLM-stage crash"):
        await handle_smart_dedup_scan(db_session, task)

    await db_session.rollback()
    db_session.expunge(task)
    persisted = await db_session.get(AsyncTask, task.id)
    assert persisted is not None
    assert persisted.meta["llm_execution_snapshot"] == snapshot
    client.close.assert_awaited_once_with()


async def test_smart_dedup_apply_request_requires_exactly_one_non_empty_mode() -> None:
    with pytest.raises(PydanticValidationError):
        SmartDedupApplyRequest(confirmed=True, suggestions=[], groups=[])
    with pytest.raises(PydanticValidationError):
        SmartDedupApplyRequest(
            confirmed=True,
            scan_task_id="scan",
            suggestions=[
                {
                    "asset_type": "world_entity",
                    "action": "merge",
                    "source_asset_id": "a",
                    "target_asset_id": "b",
                }
            ],
            groups=[
                {
                    "group_id": "g",
                    "asset_type": "world_entity",
                    "primary_asset_id": "b",
                    "operations": [
                        {
                            "source_asset_id": "a",
                            "action": "merge",
                            "expected_source_execution_fingerprint": "a" * 64,
                            "expected_target_execution_fingerprint": "b" * 64,
                        }
                    ],
                }
            ],
        )


async def test_smart_dedup_apply_dispatches_by_asset_type(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, list] = {"world": [], "outline": []}

    async def fake_world_apply(db, novel_id, *, confirmed, suggestions):
        calls["world"].extend(suggestions)
        return {"applied": len(suggestions), "skipped": 0, "warnings": []}

    async def fake_outline_apply(db, novel_id, *, confirmed, suggestions):
        calls["outline"].extend(suggestions)
        return {"applied": len(suggestions), "skipped": 0, "warnings": []}

    monkeypatch.setattr(
        "modules.world.facade.apply_entity_fusion",
        fake_world_apply,
    )
    monkeypatch.setattr(
        "modules.outline.facade.apply_structure_dedup",
        fake_outline_apply,
    )

    result = await SmartDedupService().apply(
        db_session,
        novel_id="project-1",
        confirmed=True,
        suggestions=[
            {
                "asset_type": "world_entity",
                "action": "alias_only",
                "source_asset_id": "e1",
                "target_asset_id": "e2",
                "alias": "别名",
            },
            {
                "asset_type": "plot_thread",
                "action": "deprecate_duplicate",
                "source_asset_id": "t1",
                "target_asset_id": "t2",
            },
        ],
    )

    assert result["applied"] == 2
    assert calls["world"] == [
        {
            "action": "alias_only",
            "source_entity_id": "e1",
            "target_entity_id": "e2",
            "alias": "别名",
            "allow_canonical_merge": False,
            "allow_canonical_alias": False,
        }
    ]
    assert calls["outline"][0]["asset_type"] == "plot_thread"


async def test_smart_dedup_scan_sets_recommended_primary(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_world_suggest(*args, **kwargs):
        return {
            "total_entities_scanned": 2,
            "suggestion_count": 1,
            "suggestions": [
                {
                    "action": "alias_only",
                    "source_entity_id": "source-world",
                    "source_entity_name": "旧称",
                    "source_status": "candidate",
                    "target_entity_id": "target-world",
                    "target_entity_name": "主体世界对象",
                    "target_status": "canonical",
                    "confidence": 0.91,
                    "reason": "更像别名",
                }
            ],
        }

    async def fake_outline_suggest(*args, **kwargs):
        return {
            "scanned_counts": {"plot_thread": 2},
            "suggestion_count": 1,
            "suggestions": [
                {
                    "asset_type": "plot_thread",
                    "action": "merge",
                    "source_asset_id": "source-outline",
                    "source_title": "重复剧情线",
                    "target_asset_id": "target-outline",
                    "target_title": "主体剧情线",
                }
            ],
        }

    monkeypatch.setattr(
        "modules.world.facade.suggest_entity_fusion",
        fake_world_suggest,
    )
    monkeypatch.setattr(
        "modules.outline.facade.suggest_structure_dedup",
        fake_outline_suggest,
    )

    result = await SmartDedupService().scan(
        db_session,
        novel_id="00000000-0000-0000-0000-000000000001",
        scopes=["world_entity", "plot_thread"],
    )

    world, outline = result["suggestions"]
    assert world["recommended_primary_asset_id"] == "target-world"
    assert world["recommended_primary_title"] == "主体世界对象"
    assert outline["recommended_primary_asset_id"] == "target-outline"
    assert outline["recommended_primary_title"] == "主体剧情线"


async def test_smart_dedup_scan_marks_alias_derived_title_conflict_high_risk(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_world_suggest(*args, **kwargs):
        return {
            "total_entities_scanned": 2,
            "suggestion_count": 1,
            "suggestions": [
                {
                    "action": "merge",
                    "source_entity_id": "shen-lan",
                    "source_entity_name": "沈澜",
                    "source_status": "draft",
                    "target_entity_id": "mirror-restorer",
                    "target_entity_name": "北港镜修师",
                    "target_status": "canonical",
                    "recommended_primary_entity_id": "mirror-restorer",
                    "recommended_primary_entity_name": "北港镜修师",
                    "confidence": 0.99,
                    "match_method": "alias_name_match",
                    "reason": "别名命中",
                }
            ],
        }

    async def fake_outline_suggest(*args, **kwargs):
        return {"scanned_counts": {}, "suggestion_count": 0, "suggestions": []}

    monkeypatch.setattr(
        "modules.world.facade.suggest_entity_fusion",
        fake_world_suggest,
    )
    monkeypatch.setattr(
        "modules.outline.facade.suggest_structure_dedup",
        fake_outline_suggest,
    )

    result = await SmartDedupService().scan(
        db_session,
        novel_id="00000000-0000-0000-0000-000000000001",
        scopes=["world_entity"],
    )

    suggestion = result["suggestions"][0]
    assert suggestion["requires_manual_confirmation"] is True
    assert suggestion["risk_level"] == "high"
    assert suggestion["risk_reason"] == "alias_derived_title_conflict"


async def test_world_triangle_forms_one_cluster_with_all_primary_candidates() -> None:
    suggestions = [
        _world_edge("a", "b", 0.99),
        _world_edge("b", "c", 0.98),
        _world_edge("a", "c", 0.97),
    ]

    groups, deferred = _build_world_groups(suggestions)

    assert deferred == 0
    assert len(groups) == 1
    assert groups[0]["presentation"] == "cluster"
    assert groups[0]["eligible_primary_asset_ids"] == ["a", "b", "c"]


async def test_world_non_star_component_becomes_disjoint_pairs() -> None:
    suggestions = [
        _world_edge("a", "b", 0.99),
        _world_edge("b", "c", 0.98),
        _world_edge("c", "d", 0.97),
    ]

    groups, deferred = _build_world_groups(suggestions)

    assert deferred == 1
    assert [group["presentation"] for group in groups] == ["pair", "pair"]
    assert [set(item["asset_id"] for item in group["members"]) for group in groups] == [
        {"a", "b"},
        {"c", "d"},
    ]


async def test_group_apply_rolls_back_failed_group_and_continues(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(title="before")
    db_session.add(project)
    await db_session.flush()
    project_id = project.id
    server_groups = [
        _server_group("g1", "a", "p1"),
        _server_group("g2", "b", "p2"),
    ]
    task = AsyncTask(
        task_type="smart_dedup_scan",
        status="done",
        meta={"novel_id": str(project.id)},
        result={"schema_version": 2, "groups": server_groups},
    )
    db_session.add(task)
    await db_session.flush()

    async def fake_apply(
        db,
        novel_id,
        *,
        primary_entity_id,
        operations,
        validate_only=False,
        execution_fingerprints_prevalidated=False,
    ):
        if validate_only:
            return []
        assert execution_fingerprints_prevalidated is True
        current = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        if primary_entity_id == "p1":
            current.settings = {"failed_group_leak": True}
            await db.flush()
            raise RuntimeError("forced group failure")
        current.title = "second-group-succeeded"
        await db.flush()
        return [{"action": "merge"}]

    monkeypatch.setattr(
        "modules.world.facade.apply_entity_fusion_group",
        fake_apply,
    )
    requests = [
        _request_group("g1", "a", "p1"),
        _request_group("g2", "b", "p2"),
    ]

    result = await SmartDedupService().apply_groups(
        db_session,
        novel_id=str(project.id),
        scan_task_id=str(task.id),
        groups=requests,
        confirmed=True,
    )

    await db_session.refresh(project)
    assert project.settings == {}
    assert project.title == "second-group-succeeded"
    assert [item["status"] for item in result["group_results"]] == [
        "failed",
        "success",
    ]
    assert result["group_results"][0]["error_code"] == "group_apply_failed"
    assert result["group_results"][0]["message"] == (
        "该裁决组执行失败，请重试或重新扫描。"
    )
    assert "forced group failure" not in result["group_results"][0]["message"]


async def test_group_apply_preflights_all_fingerprints_before_any_group_mutates(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(title="batch preflight")
    db_session.add(project)
    await db_session.flush()
    task = AsyncTask(
        task_type="smart_dedup_scan",
        status="done",
        meta={"novel_id": str(project.id)},
        result={
            "schema_version": 2,
            "groups": [
                _server_group("g1", "a", "p1"),
                _server_group("g2", "b", "p2"),
            ],
        },
    )
    db_session.add(task)
    await db_session.flush()
    state = {"mutated": False, "preflight": [], "applied": []}

    async def fake_apply(
        db,
        novel_id,
        *,
        primary_entity_id,
        operations,
        validate_only=False,
        execution_fingerprints_prevalidated=False,
    ):
        if validate_only:
            assert state["mutated"] is False
            state["preflight"].append(primary_entity_id)
            return []
        assert execution_fingerprints_prevalidated is True
        state["mutated"] = True
        state["applied"].append(primary_entity_id)
        return [{"action": "merge"}]

    monkeypatch.setattr(
        "modules.world.facade.apply_entity_fusion_group",
        fake_apply,
    )

    result = await SmartDedupService().apply_groups(
        db_session,
        novel_id=str(project.id),
        scan_task_id=str(task.id),
        groups=[
            _request_group("g1", "a", "p1"),
            _request_group("g2", "b", "p2"),
        ],
        confirmed=True,
    )

    assert state == {
        "mutated": True,
        "preflight": ["p1", "p2"],
        "applied": ["p1", "p2"],
    }
    assert [item["status"] for item in result["group_results"]] == [
        "success",
        "success",
    ]


async def test_keep_separate_is_idempotent_and_semantic_change_supersedes_it(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(title="keep separate")
    db_session.add(project)
    await db_session.flush()
    server_group = _server_group("g-keep", "a", "p")
    task = AsyncTask(
        task_type="smart_dedup_scan",
        status="done",
        meta={"novel_id": str(project.id)},
        result={"schema_version": 2, "groups": [server_group]},
    )
    db_session.add(task)
    await db_session.flush()
    request = _request_group("g-keep", "a", "p")
    request["operations"][0]["action"] = "keep_separate"

    async def keep_world(*args, **kwargs):
        return [
            {
                "action": "keep_separate",
                "left_asset_id": "a",
                "right_asset_id": "p",
                "left_semantic_fingerprint": "e" * 64,
                "right_semantic_fingerprint": "f" * 64,
            }
        ]

    monkeypatch.setattr(
        "modules.world.facade.apply_entity_fusion_group",
        keep_world,
    )

    for _ in range(2):
        result = await SmartDedupService().apply_groups(
            db_session,
            novel_id=str(project.id),
            scan_task_id=str(task.id),
            groups=[request],
            confirmed=True,
        )
        assert result["group_results"][0]["status"] == "success"

    decisions = list(
        (await db_session.execute(select(SmartDedupWorkbenchDecision))).scalars()
    )
    assert len(decisions) == 1
    assert decisions[0].superseded_at is None
    assert decisions[0].left_semantic_fingerprint == "e" * 64
    assert decisions[0].right_semantic_fingerprint == "f" * 64

    async def changed_world(*args, **kwargs):
        return {
            "total_entities_scanned": 2,
            "suggestions": [
                {
                    "entity_type": "character",
                    "action": "merge",
                    "source_entity_id": "a",
                    "source_entity_name": "A changed",
                    "target_entity_id": "p",
                    "target_entity_name": "P",
                    "source_snapshot": {"asset_id": "a", "title": "A changed"},
                    "target_snapshot": {"asset_id": "p", "title": "P"},
                    "source_semantic_fingerprint": "e" * 64,
                    "target_semantic_fingerprint": "d" * 64,
                    "source_execution_fingerprint": "f" * 64,
                    "target_execution_fingerprint": "b" * 64,
                }
            ],
        }

    monkeypatch.setattr("modules.world.facade.suggest_entity_fusion", changed_world)
    await SmartDedupService().scan(
        db_session,
        novel_id=str(project.id),
        scopes=["world_entity"],
    )

    await db_session.refresh(decisions[0])
    assert decisions[0].superseded_at is not None

    sqlite_fks = (
        await db_session.execute(
            text("PRAGMA foreign_key_list('smart_dedup_workbench_decisions')")
        )
    ).mappings()
    project_fk = next(row for row in sqlite_fks if row["table"] == "projects")
    assert project_fk["on_delete"] == "CASCADE"


async def test_keep_separate_many_loads_only_requested_pairs_once(
    db_session: AsyncSession,
) -> None:
    project = Project(title="batch dispositions")
    db_session.add(project)
    await db_session.flush()
    db_session.add_all(
        [
            SmartDedupWorkbenchDecision(
                novel_id=project.id,
                asset_type="world_entity",
                left_asset_id=f"a{index:03d}",
                right_asset_id=f"z{index:03d}",
                left_semantic_fingerprint="a" * 64,
                right_semantic_fingerprint="b" * 64,
                decision="keep_separate",
                source_scan_task_id="old-scan",
            )
            for index in range(100)
        ]
    )
    await db_session.flush()

    statement_count = 0

    def count_disposition_selects(
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        del conn, cursor, parameters, context, executemany
        nonlocal statement_count
        normalized = statement.lower()
        if (
            normalized.lstrip().startswith("select")
            and "from smart_dedup_workbench_decisions" in normalized
        ):
            statement_count += 1

    assert db_session.bind is not None
    sync_engine = db_session.bind.sync_engine
    event.listen(sync_engine, "before_cursor_execute", count_disposition_selects)
    try:
        results = await SmartDedupWorkbenchDecisionRepository().keep_separate_many(
            db_session,
            novel_id=project.id,
            asset_type="world_entity",
            dispositions=[
                {
                    "left_asset_id": "a001",
                    "right_asset_id": "z001",
                    "left_semantic_fingerprint": "a" * 64,
                    "right_semantic_fingerprint": "b" * 64,
                },
                {
                    "left_asset_id": "z002",
                    "right_asset_id": "a002",
                    "left_semantic_fingerprint": "c" * 64,
                    "right_semantic_fingerprint": "d" * 64,
                },
                {
                    "left_asset_id": "new-left",
                    "right_asset_id": "new-right",
                    "left_semantic_fingerprint": "e" * 64,
                    "right_semantic_fingerprint": "f" * 64,
                },
            ],
            source_scan_task_id="new-scan",
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", count_disposition_selects)

    assert statement_count == 1
    assert len(results) == 3
    assert results[0].source_scan_task_id == "old-scan"
    assert results[1].left_asset_id == "a002"
    assert results[1].left_semantic_fingerprint == "d" * 64
    assert results[1].right_semantic_fingerprint == "c" * 64
    assert results[2].source_scan_task_id == "new-scan"


async def test_keep_separate_many_preserves_duplicate_input_order_and_rejects_conflicts(
    db_session: AsyncSession,
) -> None:
    project = Project(title="batch duplicate order")
    db_session.add(project)
    await db_session.flush()
    repo = SmartDedupWorkbenchDecisionRepository()
    repeated = {
        "left_asset_id": "right",
        "right_asset_id": "left",
        "left_semantic_fingerprint": "b" * 64,
        "right_semantic_fingerprint": "a" * 64,
    }

    results = await repo.keep_separate_many(
        db_session,
        novel_id=project.id,
        asset_type="world_entity",
        dispositions=[
            repeated,
            {
                "left_asset_id": "other-left",
                "right_asset_id": "other-right",
                "left_semantic_fingerprint": "c" * 64,
                "right_semantic_fingerprint": "d" * 64,
            },
            dict(repeated),
        ],
        source_scan_task_id="new-scan",
    )

    assert [item.left_asset_id for item in results] == [
        "left",
        "other-left",
        "left",
    ]
    assert results[0] is results[2]
    assert results[0].left_semantic_fingerprint == "a" * 64
    with pytest.raises(
        ValueError,
        match="conflicting keep_separate pair fingerprints",
    ):
        await repo.keep_separate_many(
            db_session,
            novel_id=project.id,
            asset_type="world_entity",
            dispositions=[
                repeated,
                {
                    **repeated,
                    "right_semantic_fingerprint": "e" * 64,
                },
            ],
            source_scan_task_id="new-scan",
        )


async def test_keep_separate_many_repairs_multiple_active_rows_for_matching_pair(
    db_session: AsyncSession,
) -> None:
    project = Project(title="repair duplicate active dispositions")
    db_session.add(project)
    await db_session.flush()
    matching = SmartDedupWorkbenchDecision(
        novel_id=project.id,
        asset_type="world_entity",
        left_asset_id="left",
        right_asset_id="right",
        left_semantic_fingerprint="a" * 64,
        right_semantic_fingerprint="b" * 64,
        decision="keep_separate",
        source_scan_task_id="matching-scan",
    )
    conflicting = SmartDedupWorkbenchDecision(
        novel_id=project.id,
        asset_type="world_entity",
        left_asset_id="left",
        right_asset_id="right",
        left_semantic_fingerprint="c" * 64,
        right_semantic_fingerprint="d" * 64,
        decision="keep_separate",
        source_scan_task_id="conflicting-scan",
    )
    db_session.add_all([matching, conflicting])
    await db_session.flush()

    result = await SmartDedupWorkbenchDecisionRepository().keep_separate_many(
        db_session,
        novel_id=project.id,
        asset_type="world_entity",
        dispositions=[
            {
                "left_asset_id": "left",
                "right_asset_id": "right",
                "left_semantic_fingerprint": "a" * 64,
                "right_semantic_fingerprint": "b" * 64,
            }
        ],
        source_scan_task_id="new-scan",
    )

    await db_session.refresh(conflicting)
    assert result == [matching]
    assert matching.superseded_at is None
    assert conflicting.superseded_at is not None
    active = list(
        (
            await db_session.execute(
                select(SmartDedupWorkbenchDecision).where(
                    SmartDedupWorkbenchDecision.novel_id == project.id,
                    SmartDedupWorkbenchDecision.superseded_at.is_(None),
                )
            )
        ).scalars()
    )
    assert active == [matching]


async def test_keep_separate_many_changes_roll_back_with_group_savepoint(
    db_session: AsyncSession,
) -> None:
    project = Project(title="batch savepoint")
    db_session.add(project)
    await db_session.flush()
    existing = SmartDedupWorkbenchDecision(
        novel_id=project.id,
        asset_type="world_entity",
        left_asset_id="left",
        right_asset_id="right",
        left_semantic_fingerprint="a" * 64,
        right_semantic_fingerprint="b" * 64,
        decision="keep_separate",
        source_scan_task_id="old-scan",
    )
    db_session.add(existing)
    await db_session.flush()

    with pytest.raises(RuntimeError, match="rollback group"):
        async with db_session.begin_nested():
            await SmartDedupWorkbenchDecisionRepository().keep_separate_many(
                db_session,
                novel_id=project.id,
                asset_type="world_entity",
                dispositions=[
                    {
                        "left_asset_id": "left",
                        "right_asset_id": "right",
                        "left_semantic_fingerprint": "c" * 64,
                        "right_semantic_fingerprint": "d" * 64,
                    }
                ],
                source_scan_task_id="new-scan",
            )
            raise RuntimeError("rollback group")

    rows = list(
        (
            await db_session.execute(
                select(SmartDedupWorkbenchDecision).where(
                    SmartDedupWorkbenchDecision.novel_id == project.id
                )
            )
        ).scalars()
    )
    assert rows == [existing]
    assert existing.superseded_at is None
    assert existing.source_scan_task_id == "old-scan"


async def test_group_request_rejects_duplicate_source_operations() -> None:
    server_group = _server_group("g-duplicate", "a", "p")
    request = _request_group("g-duplicate", "a", "p")
    request["operations"].append(dict(request["operations"][0]))

    with pytest.raises(ValueError, match="invalid_group"):
        _validate_group_request(server_group, request)


def _world_edge(source: str, target: str, confidence: float) -> dict:
    return {
        "asset_type": "world_entity",
        "source_asset_id": source,
        "target_asset_id": target,
        "source_snapshot": {"asset_id": source, "title": source},
        "target_snapshot": {"asset_id": target, "title": target},
        "recommended_primary_asset_id": target,
        "action": "merge",
        "confidence": confidence,
    }


def _server_group(group_id: str, source: str, primary: str) -> dict:
    return {
        "group_id": group_id,
        "asset_type": "world_entity",
        "members": [
            {"asset_id": source, "title": source},
            {"asset_id": primary, "title": primary},
        ],
        "eligible_primary_asset_ids": [primary],
        "edges": [
            {
                "source_asset_id": source,
                "target_asset_id": primary,
                "allowed_actions": ["merge", "keep_separate"],
                "source_execution_fingerprint": "a" * 64,
                "target_execution_fingerprint": "b" * 64,
                "source_semantic_fingerprint": "c" * 64,
                "target_semantic_fingerprint": "d" * 64,
            }
        ],
    }


def _request_group(group_id: str, source: str, primary: str) -> dict:
    return {
        "group_id": group_id,
        "asset_type": "world_entity",
        "primary_asset_id": primary,
        "operations": [
            {
                "source_asset_id": source,
                "action": "merge",
                "expected_source_execution_fingerprint": "a" * 64,
                "expected_target_execution_fingerprint": "b" * 64,
            }
        ],
    }

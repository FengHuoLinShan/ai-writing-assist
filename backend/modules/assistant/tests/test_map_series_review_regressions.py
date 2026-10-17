"""Regression targets from the map-series review (T-20261016-map-series-claude-review).

Each case encodes the specified behavior for a confirmed review finding. Cases are
strict xfail while the defect is open: a fix turns them into an unexpected pass,
which fails the run until the marker is removed and the case becomes a plain
regression test.
"""

from __future__ import annotations

import pytest

from modules.assistant.goal_runs.contracts import GoalPlan


def _goal_catalog():
    from app.bootstrap import _container_services
    from app.task_runtime import register_task_handlers
    from core.service_keys import ASSISTANT_OPERATIONS
    from modules.assistant.goal_runs.service import _goal_planning_catalog

    register_task_handlers()
    operations = dict(_container_services())[ASSISTANT_OPERATIONS]
    available, unavailable = _goal_planning_catalog(operations)
    return (
        operations,
        {item["operation_id"] for item in available},
        {item["operation_id"]: item["reason"] for item in unavailable},
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B8-F1: the goal exclusion checks the 'world.map.' prefix, but map "
        "operations are registered as 'map.*', so author-decision edits are offered"
    ),
)
def test_b8_goal_catalog_routes_map_author_decision_edits_to_workbench():
    """ADR-0038 §6: without a verifiable goal author-decision credential, return.

    Goal runs have no conversation session, so `map.edit_spatial_structure` can
    never read an author decision there. The planner must see it as unavailable
    instead of planning a step that always fails at preparation.
    """
    _operations, offered, omitted = _goal_catalog()

    assert "map.edit_spatial_structure" not in offered
    assert "地图工作台" in omitted.get("map.edit_spatial_structure", "")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B8-F1: map.prepare_tray_placement is offered to the goal planner, but "
        "validate_plan rejects every read operation that declares an apply callback"
    ),
)
def test_b8_goal_catalog_offers_only_operations_validate_plan_accepts():
    """Every operation offered to the planner must survive plan validation.

    Otherwise a plan that uses it fails after the selection and planning requests
    were already paid, and the author only sees a generic planning failure.
    """
    from modules.assistant.goal_runs.planning import validate_plan

    operations, offered, _omitted = _goal_catalog()
    rejected = {}
    for operation_id in sorted(offered):
        plan = GoalPlan.model_validate(
            {
                "title": "目录一致性",
                "steps": [
                    {
                        "step_id": "step",
                        "operation_id": operation_id,
                        "parameters": {},
                        "intent": "只验证目录能力",
                    }
                ],
            }
        )
        try:
            validate_plan(plan, operations, validate_parameters=False)
        except Exception as error:  # noqa: BLE001 - collect every rejection
            rejected[operation_id] = str(error)

    assert rejected == {}

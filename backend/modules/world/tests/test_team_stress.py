"""World owns stress assessments and keeps them outside adoption."""

import json
import uuid

import pytest

from core.errors import ConflictError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import inspect_novel_target
from modules.world.facade import create_entity, update_entity
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)
from modules.world.team_stress import (
    StressDecision,
    WorldStressAssessment,
    decide_stress_scenario,
    read_stress_report,
    review_team_stress,
)


async def test_stress_report_preserves_invalid_counterexample_and_author_choice(
    db_session, test_project_id
):
    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "铜门规则",
            "entity_type": "rule",
            "summary": "铜门只能从里面打开。",
            "status": "canonical",
        },
    )
    target = {"target_type": "world_entity", "target_id": str(entity["id"])}
    inspected = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        content_mode="working",
        visibility=VisibilityContextContract(mode="author"),
    )
    reference = {"target_ref": target, "inspection": inspected}
    key = stable_hash(reference)

    class Client:
        model_name = "deepseek-flash"

        async def generate_structured(self, request, schema, **kwargs):
            if schema is WorldStressAssessment:
                material = json.loads(request.messages[-1].content)
                if material.get("scenarios_to_retest"):
                    assert (
                        material["previous_author_decisions"]["outside"]["disposition"]
                        == "intentional"
                    )
                return schema(
                    summary="外侧推门不满足从里面开启的前提。",
                    scenarios=[
                        {
                            "key": "outside",
                            "title": "外侧推门",
                            "source_keys": [key],
                            "invariant": "只能从里面打开",
                            "assumptions": [],
                            "actions": ["从外侧推门"],
                            "outcome": "门仍关闭",
                            "verdict": "invalid_counterexample",
                            "reason": "未满足内侧开启前提",
                        }
                    ],
                )
            return schema(
                verdict="pass",
                findings=[],
                dimensions=[{"dimension": "world_rules", "checked": True}],
            )

    async def checkpoint():
        await db_session.commit()

    related = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "守门人习惯",
            "entity_type": "rule",
            "summary": "守门人始终值夜",
            "status": "canonical",
        },
    )
    related_target = {"target_type": "world_entity", "target_id": str(related["id"])}
    related_inspection = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref=related_target,
        content_mode="working",
        visibility=VisibilityContextContract(mode="author"),
    )
    related_reference = {"target_ref": related_target, "inspection": related_inspection}
    kwargs = dict(
        novel_id=test_project_id,
        run_id=str(uuid.uuid4()),
        target_ref=target,
        references={key: reference, stable_hash(related_reference): related_reference},
        investigations=[],
        preserved_constraints=["保留城门不便"],
        client=Client(),
        checkpoint=checkpoint,
    )
    result = await review_team_stress(db_session, **kwargs)
    repeated = await review_team_stress(db_session, **kwargs)
    assert repeated["id"] == result["id"]
    report = await read_stress_report(db_session, test_project_id, result["id"])
    assert report["assessment"]["scenarios"][0]["verdict"] == "invalid_counterexample"
    assert report["freshness"] == "fresh"
    saved = await decide_stress_scenario(
        db_session,
        test_project_id,
        result["id"],
        StressDecision(
            expected_hash=report["assessment_hash"],
            scenario_key="outside",
            disposition="intentional",
        ),
    )
    assert saved["dispositions"]["outside"]["disposition"] == "intentional"
    with pytest.raises(ConflictError):
        await decide_stress_scenario(
            db_session,
            test_project_id,
            result["id"],
            StressDecision(
                expected_hash="wrong", scenario_key="outside", disposition="resolved"
            ),
        )
    with pytest.raises(ValidationError, match="read-only"):
        await SuggestionQueueService().confirm(db_session, test_project_id, result["id"])
    assert "api_key" not in json.dumps(report)

    retested = await review_team_stress(
        db_session,
        **{
            **kwargs,
            "run_id": str(uuid.uuid4()),
            "previous_report_id": result["id"],
            "scenario_keys": ["outside"],
        },
    )
    newer = await read_stress_report(db_session, test_project_id, retested["id"])
    assert newer["previous_report_id"] == result["id"]
    assert newer["previous_scenarios"] == report["assessment"]["scenarios"]
    assert (await read_stress_report(db_session, test_project_id, result["id"]))[
        "dispositions"
    ] == saved["dispositions"]
    with pytest.raises(ConflictError):
        await review_team_stress(
            db_session,
            **{
                **kwargs,
                "run_id": str(uuid.uuid4()),
                "previous_report_id": result["id"],
                "scenario_keys": ["invented"],
            },
        )

    await update_entity(
        db_session, test_project_id, str(related["id"]), {"summary": "守门人改为白天值守"}
    )
    changed = await read_stress_report(db_session, test_project_id, result["id"])
    assert changed["freshness"] == "stale"
    assert changed["assessment"] == report["assessment"]

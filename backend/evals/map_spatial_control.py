"""Explicit map evaluation lifecycle commands; no setup or model calls on import."""

from __future__ import annotations

import os
from pathlib import Path

from evals.map_spatial import (
    LIVE_ENV,
    MapSpatialEvalError,
    _case_for,
    _family_for,
    _gate_path,
    _read_private_json,
    _write_private_json,
    load_matrix,
    preflight_project,
    require_private_directory,
    verify_materials,
)
from evals.map_spatial_guard import (
    CALIBRATION_STEP,
    JUDGE_STEP,
    CalibrationResult,
    JudgeResult,
    binding_path,
    calibration_prompt,
    evaluate_development,
    judge_prompt,
    private_lock,
    private_ref,
    product_evidence,
    read_binding,
    require_calibration,
    require_development_gate,
    verify_runtime,
)


def explicit_execution(execute: bool) -> None:
    if not execute or os.environ.get(LIVE_ENV) != "1":
        raise MapSpatialEvalError("默认关闭：需要--execute和地图专用live开关")


async def freeze_binding(
    *, private_root: Path, family_id: str, scopes: Path, execute: bool
) -> dict:
    """Freeze Writing-pair setup after map adoption; never bootstrap cold-start."""
    explicit_execution(execute)
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
    verify_materials(root, matrix)
    if not scopes.resolve().is_relative_to(root):
        raise MapSpatialEvalError("案例scope清单必须放在本次私有目录")
    requested = _read_private_json(scopes)
    source = _read_private_json(private_ref(root, f"{family_id}/source.json"))
    case_ids = {row["case_id"] for row in source["cases"]}
    if len(case_ids) != 5 or set(requested) != case_ids:
        raise MapSpatialEvalError("必须为五个冻结案例逐一绑定Scene")
    cases = {}
    for case_id in sorted(case_ids):
        scope = requested[case_id]
        if set(scope) != {"novel_id", "scene_id", "chapter_index"}:
            raise MapSpatialEvalError("scope只能指定项目、Scene、章截止")
        case = _case_for(source, case_id)
        cases[case_id] = await preflight_project(
            private_root=root,
            family=family,
            source_excerpt=case["source_excerpt"],
            **scope,
        )
    if len({case["novel_id"] for case in cases.values()}) != 1:
        raise MapSpatialEvalError("一个资料族只能使用一个隔离项目")
    if len({case["scene_id"] for case in cases.values()}) != 5:
        raise MapSpatialEvalError("五个案例必须使用不同Scene，避免上下文污染")
    shared = (
        "scene_id",
        "chapter_index",
        "scene_hash",
        "map_snapshot_hash",
        "source_snapshot_hash",
        "map_revision_count",
    )
    binding = {
        key: value
        for key, value in next(iter(cases.values())).items()
        if key not in shared
    }
    if any(
        {key: value for key, value in case.items() if key not in shared} != binding
        for case in cases.values()
    ):
        raise MapSpatialEvalError("案例间项目或冻结版本漂移")
    binding["case_bindings"] = cases
    with private_lock(root):
        path = binding_path(root, family_id)
        if path.exists():
            raise MapSpatialEvalError("隔离绑定已冻结，不能覆盖或复用")
        _write_private_json(path, binding)
    return {
        "status": "frozen",
        "family_id": family_id,
        "cases": 5,
        "human_validated": False,
    }


async def score(
    *, private_root: Path, family_id: str, phase: str, case_id: str, execute: bool
) -> dict:
    explicit_execution(execute)
    root = require_private_directory(private_root)
    binding = read_binding(root, family_id)
    if phase == "holdout_judge":
        require_development_gate(root, load_matrix())
    elif phase != "teacher_calibration":
        require_calibration(root, binding)
    from core.database import get_manager
    from evals.codex_executor import CodexStructuredExecutor, MapSpatialEvaluationScope
    from evals.schemas import EVAL_TEACHER_MODEL, EVAL_TEACHER_REASONING_EFFORT

    async with get_manager().session() as db:
        # Do not fetch task results before checking the actual isolation/owner boundary.
        await verify_runtime(db, binding)
        if phase == "teacher_calibration":
            prompt, schema, step = (
                calibration_prompt(binding),
                CalibrationResult,
                CALIBRATION_STEP,
            )
        else:
            try:
                evidence = await product_evidence(db, root, binding, case_id)
                prompt = judge_prompt(root, binding, case_id, evidence)
            finally:
                await db.rollback()
            schema, step = JudgeResult, JUDGE_STEP
        scope = MapSpatialEvaluationScope(db, root, binding, phase, case_id, execute=True)
        executor = CodexStructuredExecutor(
            model=EVAL_TEACHER_MODEL,
            reasoning_effort=EVAL_TEACHER_REASONING_EFFORT,
            attempts=1,
            calibration=scope,
        )
        await executor.generate_structured(prompt, schema, step_name=step)
    if phase == "teacher_calibration":
        require_calibration(root, binding)
    return {
        "status": "completed",
        "family_id": family_id,
        "phase": phase,
        "case_id": case_id,
        "human_validated": False,
        "usage": "unknown",
    }


def freeze_gate(private_root: Path) -> dict:
    root = require_private_directory(private_root)
    with private_lock(root):
        actual = evaluate_development(root, load_matrix())
        path = _gate_path(root)
        if path.exists():
            raise MapSpatialEvalError("开发gate已冻结，不能覆盖")
        _write_private_json(path, actual)
    return {"status": "completed", "genres": 5, "human_validated": False}

"""Map-only calibration, immutable request journal and evidence-backed gates.

No model calls occur here. The scoped Codex executor owns the actual invocation.
Raw requests, outputs and product receipts always remain outside repositories.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.schemas import EVAL_TEACHER_MODEL, EVAL_TEACHER_REASONING_EFFORT

CALIBRATION_STEP = "eval.map_spatial.teacher_calibration"
JUDGE_STEP = "eval.map_spatial.judge"
SEEDS = (
    {
        "id": "opposite",
        "text": "北门在钟楼北面；北门又在同一钟楼南面。两句均为同场直接观察。",
        "label": "inconsistent",
    },
    {"id": "inverse", "text": "北门在钟楼北面；钟楼在北门南面。", "label": "consistent"},
    {
        "id": "unknown",
        "text": "两地在示意图上相隔很远。正文没有比例、交通方式或时间间隔。",
        "label": "unknown",
    },
    {
        "id": "excluded",
        "text": "角色不知且读者未揭示的密道被作者明确排除，不得用于正文空间判断。",
        "label": "excluded",
    },
)
# Bounds are frozen before any development scoring. Counts/cost remain observable
# requirements, never zeros inferred from absent instrumentation.
BOUNDS = {
    "clue_precision": (0.95, 1),
    "clue_recall": (0.9, 1),
    "non_objective_false_acceptance": (0, 0),
    "hierarchy_accuracy": (0.95, 1),
    "pending_review_ratio": (0, 0.25),
    "existing_type_reuse_ratio": (0.9, 1),
    "duplicate_type_ratio": (0, 0.05),
    "trait_accuracy": (0.95, 1),
    "emerging_activation_ratio": (0, 1),
    "spatial_consistency": (0, 1),
    "prose_quality": (0, 1),
    "spatial_notice_false_positive_ratio": (0, 0.05),
    "target_resolution_accuracy": (0.95, 1),
    "preview_intent_accuracy": (0.95, 1),
    "unauthorized_or_guessed_coordinate_refusal": (1, 1),
    "unknown_answer_accuracy": (0.95, 1),
}


class SeedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    label: Literal["consistent", "inconsistent", "unknown", "excluded"]
    reason: str = Field(min_length=1, max_length=1000)


class CalibrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[SeedDecision] = Field(min_length=4, max_length=4)


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group: Literal["cold_start", "type_emergence", "writing_paired", "assistant"]
    name: str
    status: Literal["observed", "unknown", "not_applicable"]
    numerator: float | None
    denominator: float | None
    without_map: float | None
    evidence_task_ids: list[str]
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_measurement(self):
        if self.status == "observed":
            if (
                self.numerator is None
                or self.denominator is None
                or self.denominator <= 0
                or self.numerator < 0
                or not math.isfinite(self.numerator)
                or not math.isfinite(self.denominator)
            ):
                raise ValueError(
                    "observed metric needs a non-negative numerator "
                    "and positive denominator"
                )
        elif self.status == "not_applicable":
            if (
                self.numerator != 0
                or self.denominator != 0
                or self.without_map is not None
            ):
                raise ValueError(
                    "not_applicable metric must carry zero/zero and no paired score"
                )
        elif (
            self.numerator is not None
            or self.denominator is not None
            or self.without_map is not None
        ):
            raise ValueError(
                "unknown metric cannot replace missing evidence with a number"
            )
        return self


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metrics: list[Metric] = Field(max_length=64)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value) -> str:
    return digest_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )


def rubric() -> dict:
    return {
        "version": "map-spatial-v1",
        "bounds": BOUNDS,
        "missing_is_unknown": True,
        "writing_non_inferiority": True,
        "writing_spatial_improvement": "per_genre_strict",
        "require_all_metrics_and_product_groups": True,
        "human_validated": False,
    }


def rubric_hash() -> str:
    return digest(rubric())


@contextmanager
def private_lock(root: Path):
    from evals.map_spatial import require_private_directory

    root = require_private_directory(root)
    path = root / ".ledger.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def private_ref(root: Path, relative: str) -> Path:
    from evals.map_spatial import MapSpatialEvalError

    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise MapSpatialEvalError("评测引用必须留在本次私有目录")
    if any(
        parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent
    ):
        raise MapSpatialEvalError("评测引用禁止符号链接")
    return path


def binding_path(root: Path, family_id: str) -> Path:
    return private_ref(root, f"bindings/{family_id}.json")


def common_binding_path(root: Path, family_id: str) -> Path:
    return private_ref(root, f"common-bindings/{family_id}.json")


def read_common_binding(root: Path, family_id: str) -> dict:
    """Read the immutable owner/source baseline that precedes the teacher call."""
    from evals.map_spatial import (
        MATRIX_PATH,
        MapSpatialEvalError,
        _read_private_json,
        _sha256_file,
        domain_method_fingerprints,
        load_matrix,
        require_private_directory,
    )

    root = require_private_directory(root)
    family = next(
        (row for row in load_matrix()["families"] if row["family_id"] == family_id), None
    )
    if family is None:
        raise MapSpatialEvalError("地图评测资料族不在冻结manifest中")
    value = _read_private_json(common_binding_path(root, family_id))
    if any(
        value.get(key) != expected
        for key, expected in {
            "schema_version": 1,
            "stage": "common_source_scene_baseline",
            "suite": "map_spatial",
            "family_id": family_id,
            "manifest_sha256": _sha256_file(MATRIX_PATH),
            "rubric_sha256": rubric_hash(),
            "source_sha256": family["source_sha256"],
            "expected_sha256": family["expected_sha256"],
            "split": family["split"],
            "genre": family["genre"],
            "private_root_sha256": digest(str(root.resolve())),
            "human_validated": False,
        }.items()
    ):
        raise MapSpatialEvalError("共同owner/Scene基线与冻结材料不符")
    for name in ("source", "expected"):
        path = private_ref(root, f"{family_id}/{name}.json")
        if (
            not path.is_file()
            or path.stat().st_mode & 0o777 != 0o600
            or _sha256_file(path) != value[f"{name}_sha256"]
        ):
            raise MapSpatialEvalError("冻结资料哈希已经变化")
    from evals.map_spatial import pipeline_hash

    if value.get("pipeline_hash") != pipeline_hash():
        raise MapSpatialEvalError("地图评测管线版本已经变化")
    if value.get("domain_method_fingerprints") != domain_method_fingerprints():
        raise MapSpatialEvalError("Evolution/地图草图/Assistant方法或工具schema已变化")
    setup_path = private_ref(root, f"setups/{family_id}.json")
    scopes_path = private_ref(root, f"scopes/{family_id}.json")
    setup = _read_private_json(setup_path)
    scopes = _read_private_json(scopes_path)
    if (
        setup.get("status") != "completed"
        or setup.get("project_id") != value.get("novel_id")
        or setup.get("source_sha256") != value.get("source_sha256")
        or _sha256_file(setup_path) != value.get("setup_record_sha256")
        or setup.get("scopes_sha256") != _sha256_file(scopes_path)
        or setup.get("scopes_sha256") != value.get("scopes_sha256")
        or not isinstance(scopes, dict)
        or set(scopes) != set(value.get("case_bindings", {}))
    ):
        raise MapSpatialEvalError("共同基线的正常产品setup或Scope已变化")
    if any(
        scopes[case_id].get(key) != case.get(key)
        for case_id, case in value.get("case_bindings", {}).items()
        for key in ("novel_id", "scene_id", "chapter_index")
    ):
        raise MapSpatialEvalError("共同基线Scene与setup scope已变化")
    cases = value.get("case_bindings")
    if not isinstance(cases, dict) or len(cases) != 5:
        raise MapSpatialEvalError("共同基线必须绑定五个独立Scene")
    scene_ids = set()
    for case_id, case in cases.items():
        source_refs = case.get("source_refs") if isinstance(case, dict) else None
        if (
            not isinstance(case, dict)
            or case.get("novel_id") != value.get("novel_id")
            or not case.get("scene_id")
            or not case.get("scene_hash")
            or not case.get("source_snapshot_hash")
            or not isinstance(source_refs, list)
            or len(source_refs) != 1
            or not isinstance(source_refs[0], dict)
            or digest(source_refs) != case.get("source_snapshot_hash")
            or source_refs[0].get("content_mode") != "canonical"
            or not source_refs[0].get("draft_id", source_refs[0].get("source_draft_id"))
            or source_refs[0].get("start_offset") is None
            or source_refs[0].get("end_offset") is None
            or not source_refs[0].get("range_hash")
            or not case.get("vocabulary_snapshot_hash")
            or digest(case.get("vocabulary_snapshot"))
            != case.get("vocabulary_snapshot_hash")
            or case.get("map_revision_count") != 0
        ):
            raise MapSpatialEvalError("共同基线缺少项目、精确Scene来源或空地图证据")
        scene_ids.add(case["scene_id"])
    if len(scene_ids) != 5:
        raise MapSpatialEvalError("五个案例必须绑定不同Scene")
    if value.get("vocabulary_snapshot") != next(iter(cases.values())).get(
        "vocabulary_snapshot"
    ) or value.get("vocabulary_snapshot_hash") != next(iter(cases.values())).get(
        "vocabulary_snapshot_hash"
    ):
        raise MapSpatialEvalError("初始空间词表与共同Scene基线不一致")
    return value


def read_binding(root: Path, family_id: str) -> dict:
    from evals.map_spatial import (
        MATRIX_PATH,
        MapSpatialEvalError,
        _read_private_json,
        _sha256_file,
        domain_method_fingerprints,
        load_matrix,
        require_private_directory,
    )

    root = require_private_directory(root)
    family = next(
        (row for row in load_matrix()["families"] if row["family_id"] == family_id), None
    )
    if family is None:
        raise MapSpatialEvalError("地图评测资料族不在冻结manifest中")
    value = _read_private_json(binding_path(root, family_id))
    common = read_common_binding(root, family_id)
    setup_path = private_ref(root, f"setups/{family_id}.json")
    if any(
        value.get(key) != expected
        for key, expected in {
            "schema_version": 1,
            "stage": "reviewed_map_head",
            "suite": "map_spatial",
            "family_id": family_id,
            "manifest_sha256": _sha256_file(MATRIX_PATH),
            "rubric_sha256": rubric_hash(),
            "source_sha256": family["source_sha256"],
            "expected_sha256": family["expected_sha256"],
            "split": family["split"],
            "genre": family["genre"],
            "private_root_sha256": digest(str(root.resolve())),
            "common_binding_sha256": digest(common),
            "setup_record_sha256": _sha256_file(setup_path),
            "scopes_sha256": common["scopes_sha256"],
            "human_validated": False,
            "domain_method_fingerprints": domain_method_fingerprints(),
        }.items()
    ):
        raise MapSpatialEvalError("地图评测绑定或冻结材料已经漂移")
    for name in ("source", "expected"):
        path = private_ref(root, f"{family_id}/{name}.json")
        if (
            not path.is_file()
            or path.stat().st_mode & 0o777 != 0o600
            or _sha256_file(path) != value[f"{name}_sha256"]
        ):
            raise MapSpatialEvalError("冻结资料哈希已经漂移")
    from evals.map_spatial import pipeline_hash

    if value.get("pipeline_hash") != pipeline_hash():
        raise MapSpatialEvalError("Writing业务prompt/管线代码版本已经漂移")
    cases = value.get("case_bindings")
    baseline_cases = common.get("case_bindings") or {}
    if not isinstance(cases, dict) or set(cases) != set(baseline_cases):
        raise MapSpatialEvalError("Writing绑定没有继承五个共同Scene")
    for case_id, case in cases.items():
        baseline = baseline_cases[case_id]
        if (
            not isinstance(case, dict)
            or case.get("map_revision_count", 0) < 1
            or not case.get("map_snapshot_hash")
            or digest(case.get("vocabulary_snapshot"))
            != case.get("vocabulary_snapshot_hash")
            or not same_source_baseline(case, baseline)
        ):
            raise MapSpatialEvalError("配对绑定缺少审核后地图head或共同来源已漂移")
    expected_heads = digest(
        {
            case_id: {
                "map_snapshot_hash": case["map_snapshot_hash"],
                "map_revision_count": case["map_revision_count"],
            }
            for case_id, case in cases.items()
        }
    )
    if value.get("map_heads_sha256") != expected_heads:
        raise MapSpatialEvalError("实际地图head摘要与冻结记录不符")
    return value


def same_source_baseline(final_case: dict, common_case: dict) -> bool:
    """Keep owner, Scene identity, Project and exact source spans; allow enrichment."""
    fields = (
        "novel_id",
        "owner_id",
        "database_target",
        "scene_id",
        "chapter_index",
        "source_snapshot_hash",
        "source_refs",
        "project_snapshot_hash",
    )
    return all(final_case.get(key) == common_case.get(key) for key in fields)


async def verify_runtime(db, binding: dict) -> None:
    """Use normal owner gates and the actual DB connection, then release reads."""
    from sqlalchemy import select

    from evals.map_spatial import MapSpatialEvalError, _canonical_hash, _database_identity
    from modules.account.facade import current_account_id, require_account_active
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
        restore_project_llm_execution_settings,
    )
    from modules.project.models import Project

    try:
        if (
            os.environ.get("AUTH_MODE") != "local"
            or _database_identity(os.environ.get("DATABASE_URL", ""))
            != binding.get("database_target")
            or _database_identity(str(db.get_bind().url))
            != binding.get("database_target")
        ):
            raise MapSpatialEvalError("运行连接不是冻结的唯一合成隔离数据库")
        owner_id = str(current_account_id())
        if owner_id != binding.get("owner_id"):
            raise MapSpatialEvalError("当前身份不属于冻结的项目owner")
        await require_account_active(db, uuid.UUID(owner_id), allow_local_bootstrap=False)
        await require_active_project(db, binding["novel_id"])
        row = await db.scalar(
            select(Project).where(Project.id == uuid.UUID(binding["novel_id"]))
        )
        if (
            row is None
            or str(row.owner_id) != owner_id
            or row.project_kind != "author"
            or not row.title.startswith(f"MAP-EVAL:{binding['family_id']}:")
        ):
            raise MapSpatialEvalError("隔离项目身份或owner已变化")
        current = await build_project_llm_execution_snapshot(db, binding["novel_id"])
        restored = await restore_project_llm_execution_settings(
            db, binding["novel_id"], current
        )
        profile = current.get("profile") or {}
        if (
            _canonical_hash(current) != binding.get("project_snapshot_hash")
            or current != binding.get("project_snapshot")
            or profile.get("provider_id") != "codex"
            or profile.get("model") != "gpt-6-luna"
            or profile.get("connection_verified") is not True
            or restored.get("llm", {}).get("extra", {}).get("reasoning_effort") != "max"
        ):
            raise MapSpatialEvalError("owner已验证Codex Luna/max snapshot漂移")
    finally:
        await db.rollback()


def calibration_prompt(binding: dict) -> str:
    payload = {
        "suite": "map_spatial",
        "phase": "teacher_calibration",
        "binding_sha256": digest(binding),
        "rubric": rubric(),
        "cases": [{"case_id": row["id"], "source": row["text"]} for row in SEEDS],
        "instruction": (
            "依据原文判断consistent/inconsistent/unknown/excluded；"
            "示意坐标不表示距离，排除与角色/读者边界不能放宽。只给逐项标签和理由。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def request_key(phase: str, case_id: str) -> str:
    if phase not in {"teacher_calibration", "development_judge", "holdout_judge"}:
        raise ValueError("unknown map evaluation phase")
    if not case_id or Path(case_id).name != case_id or case_id in {".", ".."}:
        raise ValueError("invalid evaluation case identity")
    return f"{phase}-{case_id}"


def request_path(root: Path, binding: dict, phase: str, case_id: str) -> Path:
    return private_ref(
        root, f"requests/{binding['family_id']}/{request_key(phase, case_id)}.json"
    )


def evidence_path(root: Path, binding: dict, case_id: str) -> Path:
    return private_ref(
        root,
        f"evidence/{binding['family_id']}/"
        f"{request_key('development_judge', case_id)}.json",
    )


def read_request(root: Path, path: Path, binding: dict) -> tuple[dict, dict]:
    """Reconstruct completion from the exact request and raw response, not passed."""
    from evals.map_spatial import MapSpatialEvalError, _read_private_json, _sha256_file

    row = _read_private_json(path)
    output = private_ref(root, row.get("raw_output", "missing"))
    if (
        row.get("status") != "completed"
        or row.get("binding_sha256") != digest(binding)
        or row.get("model") != EVAL_TEACHER_MODEL
        or row.get("reasoning_effort") != EVAL_TEACHER_REASONING_EFFORT
        or row.get("prompt_sha256") != digest_bytes(str(row.get("prompt", "")).encode())
        or row.get("raw_output_sha256") != _sha256_file(output)
        or not row.get("executor_hash")
        or row.get("human_validated") is not False
    ):
        raise MapSpatialEvalError("评分请求/原始输出账本不完整或已变化")
    if row.get("phase") in {"development_judge", "holdout_judge"}:
        try:
            prompt_data = json.loads(row["prompt"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MapSpatialEvalError("评分输入不是冻结JSON") from exc
        if row.get("evidence_sha256") != prompt_data.get("evidence_sha256"):
            raise MapSpatialEvalError("评分输入未绑定已冻结的产品证据哈希")
        frozen_path = evidence_path(root, binding, row["case_id"])
        frozen_evidence = _read_private_json(frozen_path)
        if frozen_path.stat().st_mode & 0o777 != 0o600 or digest(
            frozen_evidence
        ) != row.get("evidence_sha256"):
            raise MapSpatialEvalError("评分引用的正式产品证据缺失或已变化")
    from evals.codex_executor import CodexStructuredExecutor, _strict_json_schema

    expected_meta = CodexStructuredExecutor(
        attempts=1,
        model=EVAL_TEACHER_MODEL,
        reasoning_effort=EVAL_TEACHER_REASONING_EFFORT,
    ).meta
    model = (
        CalibrationResult if row.get("phase") == "teacher_calibration" else JudgeResult
    )
    if row.get("executor_hash") != expected_meta.executor_hash or row.get(
        "schema_sha256"
    ) != digest(_strict_json_schema(model.model_json_schema())):
        raise MapSpatialEvalError("评分模型executor/schema指纹不符")
    return row, _read_private_json(output)


def require_calibration(root: Path, binding: dict) -> dict:
    from evals.codex_executor import CodexStructuredExecutor
    from evals.map_spatial import MapSpatialEvalError

    common = read_common_binding(root, binding["family_id"])
    if binding.get("split") != "development":
        raise MapSpatialEvalError("仅开发资料族可以进行seeded教师校准")
    if binding.get("common_binding_sha256") not in {None, digest(common)}:
        raise MapSpatialEvalError("最终Writing绑定未继承同一共同基线")
    path = request_path(root, common, "teacher_calibration", "seeded-v1")
    row, raw = read_request(root, path, common)
    expected_meta = CodexStructuredExecutor(
        attempts=1,
        model=EVAL_TEACHER_MODEL,
        reasoning_effort=EVAL_TEACHER_REASONING_EFFORT,
    ).meta
    result = CalibrationResult.model_validate(raw)
    labels = {item.case_id: item.label for item in result.decisions}
    if (
        row.get("step_name") != CALIBRATION_STEP
        or row.get("prompt") != calibration_prompt(common)
        or row.get("executor_hash") != expected_meta.executor_hash
        or len(labels) != len(SEEDS)
        or labels != {seed["id"]: seed["label"] for seed in SEEDS}
    ):
        raise MapSpatialEvalError("真实seeded校准未通过，不能运行地图SUT或评分")
    return row


def start_request(
    root: Path,
    binding: dict,
    phase: str,
    case_id: str,
    prompt: str,
    step_name: str,
    schema: dict,
    meta,
) -> Path:
    from evals.map_spatial import MapSpatialEvalError, _write_private_json

    path = request_path(root, binding, phase, case_id)
    with private_lock(root):
        if path.exists():
            raise MapSpatialEvalError(
                "评分请求已占用；started/pending/unknown/completed均不重发"
            )
        _write_private_json(
            path,
            {
                "suite": "map_spatial",
                "status": "started",
                "phase": phase,
                "case_id": case_id,
                "binding_sha256": digest(binding),
                "step_name": step_name,
                "prompt": prompt,
                "prompt_sha256": digest_bytes(prompt.encode()),
                "schema_sha256": digest(schema),
                "model": meta.model,
                "reasoning_effort": meta.reasoning_effort,
                "executor_hash": meta.executor_hash,
                "human_validated": False,
                "evidence_sha256": (
                    json.loads(prompt).get("evidence_sha256")
                    if phase in {"development_judge", "holdout_judge"}
                    else None
                ),
            },
        )
    return path


def finish_request(
    root: Path, path: Path, payload: str | None, *, completed: bool
) -> None:
    from evals.map_spatial import _read_private_json, _sha256_file, _write_private_json

    with private_lock(root):
        row = _read_private_json(path)
        if row["status"] != "started":
            raise ValueError("scored request cannot be overwritten")
        row["status"] = "unknown"
        if payload is not None:
            output = path.with_name(path.stem + "-raw.json")
            fd = os.open(
                output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            row.update(
                status="completed" if completed else "unknown",
                raw_output=str(output.relative_to(root)),
                raw_output_sha256=_sha256_file(output),
            )
        _write_private_json(path, row)


async def read_writing_evidence(
    db, root: Path, binding: dict, case_id: str, task_ids: list[str]
) -> list[dict]:
    """Real Writing tasks carry scene_id; other product tasks have different contracts."""
    from sqlalchemy import select

    from evals.map_spatial import MapSpatialEvalError, _read_ledger
    from infrastructure.tasks.models import AsyncTask
    from modules.writing.facade import get_draft

    run = _read_ledger(root)["runs"].get(f"{binding['family_id']}/{case_id}", {})
    scope = binding.get("case_bindings", {}).get(case_id)
    if (
        not scope
        or run.get("status") != "completed"
        or len(task_ids) != 2
        or len(set(task_ids)) != 2
        or set(task_ids) != {arm.get("task_id") for arm in run.get("arms", {}).values()}
    ):
        raise MapSpatialEvalError("配对任务不属于该案例已冻结的两臂")
    items = []
    for task_id in task_ids:
        task = await db.scalar(
            select(AsyncTask).where(
                AsyncTask.id == uuid.UUID(task_id),
                AsyncTask.novel_id == uuid.UUID(binding["novel_id"]),
            )
        )
        if (
            task is None
            or task.status != "done"
            or task.task_type != "writing_generate"
            or (task.meta or {}).get("scene_id") != scope["scene_id"]
        ):
            raise MapSpatialEvalError("Writing评分只接受同项目、同Scene已完成的正式任务")
        draft = await get_draft(
            db, binding["novel_id"], str((task.result or {}).get("draft_id") or "")
        )
        if draft is None or not draft.content or draft.status != "candidate":
            raise MapSpatialEvalError("Writing候选缺失或已采用，配对受到污染")
        items.append(
            {
                "task_id": str(task.id),
                "task_type": task.task_type,
                "result": task.result or {},
                "usage": "unknown",
                "cost": "unknown",
                "draft": {
                    "id": str(draft.id),
                    "content": draft.content,
                    "content_hash": draft.content_hash,
                },
            }
        )
    verify_writing_receipts(root, binding, case_id, {"writing_paired": items})
    return items


async def product_evidence(db, root: Path, binding: dict, case_id: str) -> dict:
    """Adapt exact persisted domain receipts; leave undocumented links unknown."""
    from evals.map_spatial import MapSpatialEvalError, _read_private_json

    scope = (binding.get("case_bindings") or {}).get(case_id)
    if not scope:
        raise MapSpatialEvalError("评分案例不在冻结五Scene范围")
    common = read_common_binding(root, binding["family_id"])
    if binding.get("common_binding_sha256") != digest(common):
        raise MapSpatialEvalError("评分地图与共同source/Scene基线不匹配")
    source_path = private_ref(root, f"{binding['family_id']}/source.json")
    source = _read_private_json(source_path)
    source_case = next(
        (item for item in source.get("cases", []) if item.get("case_id") == case_id), None
    )
    if not source_case:
        raise MapSpatialEvalError("评分原文不属于冻结资料族")
    case_scope = common["case_bindings"][case_id]
    if case_scope.get("scene_id") != scope.get("scene_id"):
        raise MapSpatialEvalError("评分Scene与共同基线来源不同")

    evolution_record_path = private_ref(root, f"evolution/{binding['family_id']}.json")
    review_path = private_ref(root, f"author-review/{binding['family_id']}.json")
    assistant_path = private_ref(root, f"assistant/{binding['family_id']}/{case_id}.json")
    evolution_record = _read_private_json(evolution_record_path)
    review = _read_private_json(review_path)
    assistant_record = _read_private_json(assistant_path)
    if (
        evolution_record.get("status") != "completed"
        or evolution_record.get("common_binding_sha256") != digest(common)
        or review.get("status") != "completed"
        or review.get("common_binding_sha256") != digest(common)
        or assistant_record.get("status") != "completed"
        or assistant_record.get("binding_sha256") != digest(binding)
        or assistant_record.get("case_id") != case_id
    ):
        raise MapSpatialEvalError("四组真实产品任务或作者代理审核未完成")
    if not isinstance(review.get("review_events"), list):
        raise MapSpatialEvalError("代理审核缺少不可覆盖的逐步操作回执")

    evolution = await read_evolution_product_evidence(db, root, common, evolution_record)
    scene_evolution = {
        "steps": [
            item
            for item in evolution["steps"]
            if item.get("scene_id") == scope["scene_id"]
        ],
        "attempts": [
            item
            for item in evolution["attempts"]
            if item.get("scene_id") == scope["scene_id"]
        ],
        "clues": [
            item
            for item in evolution["world"]["clues"]
            if item.get("scene_id") == scope["scene_id"]
        ],
        "batches": evolution["world"]["batches"],
        "drafts": evolution["world"]["drafts"],
        "revisions": evolution["world"]["revisions"],
        "nodes": evolution["world"]["nodes"],
        "coverage": [
            item
            for item in evolution["world"]["coverage"]
            if item.get("scene_id") == scope["scene_id"]
        ],
        "missing": evolution["world"]["missing"],
        "operation_attempt_membership": "unknown",
    }
    assistant_evidence = await read_assistant_product_evidence(
        db, root, binding, case_id, assistant_record
    )
    assistant_case = source_case.get("assistant") or {}
    assistant_context = (assistant_evidence.get("request") or {}).get("context") or {}
    if (
        assistant_evidence.get("request", {}).get("message")
        != assistant_case.get("request")
        or assistant_context.get("page") != "map"
        or assistant_context.get("chapter_index") != scope["chapter_index"]
        or assistant_context.get("scene_id") != scope["scene_id"]
        or assistant_context.get("scope") != "current"
    ):
        raise MapSpatialEvalError("Assistant真实请求与冻结案例/Scene context不符")
    from evals.map_spatial import _read_ledger

    ledger = _read_ledger(root)
    writing_run = ledger.get("runs", {}).get(f"{binding['family_id']}/{case_id}", {})
    writing_task_ids = [
        str(arm.get("task_id"))
        for arm in (writing_run.get("arms") or {}).values()
        if arm.get("task_id")
    ]
    writing = await read_writing_evidence(db, root, binding, case_id, writing_task_ids)
    type_change_events = _vocabulary_author_change_events(
        evolution["world"]["vocabulary"], common["case_bindings"]
    )
    evolution_task_ids = [
        item["task_id"] for item in evolution["task_records"] if item.get("task_id")
    ]
    task_ids_by_group = {
        "cold_start": evolution_task_ids,
        "type_emergence": evolution_task_ids,
        "writing_paired": writing_task_ids,
        "assistant": [assistant_record["task_id"]],
    }
    return {
        "schema_version": 1,
        "family_id": binding["family_id"],
        "case_id": case_id,
        "genre": binding["genre"],
        "novel_id": binding["novel_id"],
        "scene_id": scope["scene_id"],
        "scene_hash": scope["scene_hash"],
        "source_snapshot_hash": scope["source_snapshot_hash"],
        "source_excerpt": source_case["source_excerpt"],
        "common_binding_sha256": digest(common),
        "final_binding_sha256": digest(binding),
        "evolution": scene_evolution,
        "task_ids_by_group": task_ids_by_group,
        "family_type_evidence": {
            "initial_vocabulary": common["vocabulary_snapshot"],
            "all_scene_vocabulary": evolution["world"]["vocabulary"],
            "all_scene_clues": evolution["world"]["clues"],
            "author_change_events": type_change_events,
            "scene_ids": [item["scene_id"] for item in common["case_bindings"].values()],
            "source_bindings": [
                {
                    "scene_id": item["scene_id"],
                    "source_snapshot_hash": item["source_snapshot_hash"],
                }
                for item in common["case_bindings"].values()
            ],
            "author_change_counts_for_case": {
                name: sum(
                    1
                    for event in type_change_events
                    if event.get("case_id") == case_id and event.get("kind") == name
                )
                for name in (
                    "author_rename_count",
                    "author_merge_count",
                    "author_archive_count",
                )
            },
        },
        "proxy_author_review": {
            "events": [
                item
                for item in review.get("review_events", [])
                if item.get("case_id") == case_id
            ],
            "reviewed_clue_ids": [
                item.get("clue_id")
                for item in review.get("review_events", [])
                if item.get("case_id") == case_id and item.get("clue_id")
            ],
            "adopted_clue_ids": [
                clue_id
                for clue_id in review.get("adopted_clue_ids", [])
                if any(
                    event.get("clue_id") == clue_id and event.get("case_id") == case_id
                    for event in review.get("review_events", [])
                )
            ],
            "rejected_clue_ids": [
                clue_id
                for clue_id in review.get("rejected_clue_ids", [])
                if any(
                    event.get("clue_id") == clue_id and event.get("case_id") == case_id
                    for event in review.get("review_events", [])
                )
            ],
            "map_candidate_reviews": [
                item
                for item in review.get("map_candidate_reviews", [])
                if case_id
                in [
                    event.get("case_id")
                    for event in review.get("review_events", [])
                    if event.get("revision_id") == item.get("revision_id")
                ]
            ],
            "review_steps": sum(
                1
                for item in review.get("review_events", [])
                if item.get("case_id") == case_id
                and item.get("status") in {"adopted", "rejected", "saved"}
            ),
            "elapsed_seconds": sum(
                item.get("elapsed_seconds", 0.0)
                for item in review.get("review_events", [])
                if item.get("case_id") == case_id
            ),
            "measurement_kind": "synthetic_proxy_author_http_elapsed_not_human_time",
            "family_review_steps": review.get("review_steps"),
            "family_elapsed_seconds": review.get("elapsed_seconds"),
            "human_validated": review.get("human_validated"),
        },
        "writing_paired": writing,
        "assistant": assistant_evidence,
        "telemetry_limits": {
            "evolution_operation_attempt_membership": "unknown",
            "assistant_tool_invocations": assistant_evidence.get(
                "tool_invocations_status", "unknown"
            ),
            "cost": "unknown",
            "human_validated": False,
        },
        "evidence_sha256": digest(
            {
                "evolution": scene_evolution,
                "assistant": assistant_evidence,
                "writing": writing,
                "review": review,
            }
        ),
    }


def _vocabulary_author_change_events(
    vocabulary: list[dict], case_bindings: dict
) -> list[dict]:
    """Count only persisted author revisions with exact Scene evidence lineage."""
    from evals.map_spatial import MapSpatialEvalError

    scene_to_case = {item["scene_id"]: case_id for case_id, item in case_bindings.items()}
    case_order = {case_id: index for index, case_id in enumerate(case_bindings)}
    by_term: dict[str, list[dict]] = {}
    for row in vocabulary:
        if not isinstance(row, dict):
            continue
        by_term.setdefault(str(row.get("id")), []).append(row)
    events = []
    for term_id, revisions in by_term.items():
        revisions.sort(key=lambda item: int(item.get("revision_number") or 0))
        previous_snapshot = None
        for revision in revisions:
            reason = revision.get("change_reason")
            snapshot = revision.get("snapshot") or {}
            kind = None
            if reason == "author_updated" and previous_snapshot is not None:
                if previous_snapshot.get("name") != snapshot.get("name"):
                    kind = "author_rename_count"
            elif reason == "author_merged":
                kind = "author_merge_count"
            elif reason == "author_archived":
                kind = "author_archive_count"
            if kind:
                evidence_scene_ids = [
                    str(item.get("scene_id"))
                    for item in snapshot.get("evidence", [])
                    if str(item.get("scene_id")) in scene_to_case
                ]
                if not evidence_scene_ids:
                    raise MapSpatialEvalError(
                        "author vocabulary change has no requested Scene lineage"
                    )
                scene_id = min(
                    evidence_scene_ids,
                    key=lambda value: case_order[scene_to_case[value]],
                )
                events.append(
                    {
                        "kind": kind,
                        "case_id": scene_to_case[scene_id],
                        "scene_id": scene_id,
                        "term_id": term_id,
                        "revision_id": revision.get("revision_id"),
                        "change_reason": reason,
                    }
                )
            previous_snapshot = snapshot
    return events


async def read_evolution_product_evidence(
    db, root: Path, common: dict, record: dict
) -> dict:
    """Use the Evolution and World pure readers; no task meta scene assumption."""
    from evals.map_spatial import MapSpatialEvalError, _read_private_json
    from modules.evolution.facade import (
        read_map_cold_start_status,
        read_map_spatial_evaluation_receipts,
    )
    from modules.world.facade import read_map_spatial_evaluation_artifacts

    scene_ids = [item["scene_id"] for item in common["case_bindings"].values()]
    run_key, operation_id = record.get("run_key"), record.get("operation_id")
    if not run_key or not operation_id:
        raise MapSpatialEvalError("Evolution产品回执缺少run/operation身份")
    state = await read_map_cold_start_status(
        db, common["novel_id"], run_key, operation_id
    )
    receipts = await read_map_spatial_evaluation_receipts(
        db, common["novel_id"], run_key, operation_id, scene_ids
    )
    if (
        state.get("run_key") != run_key
        or state.get("operation_id") != operation_id
        or state.get("status") != "completed"
        or state.get("total_scenes") != 5
        or state.get("completed_scenes") != 5
        or receipts.get("schema_version") != 1
        or receipts.get("novel_id") != common["novel_id"]
        or receipts.get("run_key") != run_key
        or receipts.get("operation_id") != operation_id
        or set(receipts.get("scene_ids", [])) != set(scene_ids)
        or receipts.get("truncated") is not False
        or receipts.get("omitted_count") != 0
        or receipts.get("human_validated") is not False
        or not isinstance(receipts.get("task_lifecycle"), dict)
    ):
        raise MapSpatialEvalError("Evolution正式运行或固定范围回执不完整")
    expected_request = {
        **(record.get("request") or {}),
        "expected_fingerprint": record.get("preview_fingerprint"),
        "authorization_confirmed": True,
    }
    if (
        record.get("request_sha256") != digest(record.get("request"))
        or record.get("common_binding_sha256") != digest(common)
        or record.get("human_validated") is not False
        or record.get("split") != common.get("split")
        or record.get("request", {}).get("discover_spatial") is not True
        or record.get("request", {}).get("budget_mode") != "bounded"
        or record.get("request", {}).get("request_limit") != record.get("request_limit")
        or receipts.get("request") != expected_request
    ):
        raise MapSpatialEvalError("Evolution执行请求与预览/冻结预算授权不一致")
    lifecycle = receipts["task_lifecycle"]
    if (
        not record.get("task_ids")
        or lifecycle.get("task_id") != record["task_ids"][-1]
        or lifecycle.get("task_type") != "evolution_scene_step_v2"
        or lifecycle.get("status") != "done"
        or lifecycle.get("stale") is not False
        or lifecycle.get("recovery_required") is not False
    ):
        raise MapSpatialEvalError("Evolution最终task生命周期未证明正常完成")
    steps = receipts.get("steps")
    attempts = receipts.get("attempts")
    if (
        not isinstance(steps, list)
        or {item.get("scene_id") for item in steps} != set(scene_ids)
        or not isinstance(attempts, list)
        or {item.get("scene_id") for item in attempts} != set(scene_ids)
        or any(item.get("operation_binding_status") != "unknown" for item in attempts)
    ):
        raise MapSpatialEvalError(
            "Evolution Scene receipt缺失或错误声称attempt/operation关系"
        )
    by_scene = {item["scene_id"]: item for item in common["case_bindings"].values()}
    for step in steps:
        scope = by_scene.get(step.get("scene_id"))
        binding = step.get("source_binding") or {}
        refs = (scope or {}).get("source_refs") or []
        if not scope or not refs or not _source_binding_matches(binding, refs):
            raise MapSpatialEvalError("Evolution冻结source binding与共同Scene基线不符")
    for attempt in attempts:
        scene_id = attempt.get("scene_id")
        scope = by_scene.get(scene_id)
        refs = (scope or {}).get("source_refs") or []
        if (
            not scope
            or not refs
            or not _source_binding_matches(attempt.get("source_binding") or {}, refs)
            or attempt.get("source_manifest_hash") is None
            or attempt.get("spatial_method_fingerprint")
            != common["domain_method_fingerprints"].get("evolution_spatial")
        ):
            raise MapSpatialEvalError("Evolution attempt不匹配精确Scene来源或冻结方法")
        _validate_evolution_optional_stage(attempt)
    attempts_by_key = {
        (item.get("scene_id"), item.get("attempt_id")): item for item in attempts
    }
    if len(attempts_by_key) != len(attempts):
        raise MapSpatialEvalError("Evolution attempt identities are not unique")
    world = await read_map_spatial_evaluation_artifacts(
        db, common["novel_id"], run_key, scene_ids
    )
    if (
        world.get("schema_version") != 1
        or world.get("novel_id") != common["novel_id"]
        or world.get("run_id") != run_key
        or set(world.get("scene_ids", [])) != set(scene_ids)
        or world.get("truncated") is not False
        or world.get("omitted_count") != 0
        or world.get("human_validated") is not False
        or world.get("missing")
    ):
        raise MapSpatialEvalError("World持久空间产物不完整或查询范围变化")
    for clue in world.get("clues", []):
        scene_id = clue.get("scene_id")
        scope = by_scene.get(scene_id)
        attempt = attempts_by_key.get((scene_id, clue.get("attempt_id")))
        if (
            not scope
            or not attempt
            or clue.get("run_id") != run_key
            or clue.get("source_manifest_hash") != attempt.get("source_manifest_hash")
            or clue.get("method_fingerprint")
            != common["domain_method_fingerprints"].get("evolution_spatial")
            or not _source_binding_matches(
                clue.get("source_binding") or {}, scope["source_refs"]
            )
        ):
            raise MapSpatialEvalError("World clue不属于同一run与冻结Scene source")
    task_ids = record.get("task_ids") or []
    if len(task_ids) < 1 or len(set(task_ids)) != len(task_ids):
        raise MapSpatialEvalError("Evolution精确worker账本缺失或重复")
    task_records = []
    for task_id in task_ids:
        path = private_ref(
            root,
            f"task-ledger/evolution/{record['family_id']}/{operation_id}/{task_id}.json",
        )
        row = _read_private_json(path)
        if row.get("status") != "completed" or row.get("task_id") != task_id:
            raise MapSpatialEvalError("Evolution精确task执行账本不是completed")
        task_records.append(
            {
                key: row.get(key)
                for key in ("task_id", "task_type", "result_hash", "status")
            }
        )
    return {
        "state": state,
        "receipts": receipts,
        "steps": steps,
        "attempts": attempts,
        "world": world,
        "task_records": task_records,
        "operation_attempt_membership": "unknown",
        "human_validated": False,
    }


def _source_binding_matches(binding: dict, refs: list[dict]) -> bool:
    """Compare actual Scene range identity, retaining only source-bound fields."""
    if not isinstance(binding, dict) or len(refs) != 1:
        return False
    ref = refs[0]
    aliases = {
        "draft_id": ("draft_id", "source_draft_id"),
        "chapter_index": ("chapter_index",),
        "content_hash": ("content_hash", "source_content_hash", "source_hash"),
        "start_offset": ("start_offset",),
        "end_offset": ("end_offset",),
        "range_hash": ("range_hash",),
    }
    for field, choices in aliases.items():
        expected = next((ref[key] for key in choices if ref.get(key) is not None), None)
        if expected is None or binding.get(field) != expected:
            return False
    return binding.get("content_mode", "canonical") == "canonical"


def _validate_evolution_optional_stage(attempt: dict) -> dict:
    from evals.map_spatial import MapSpatialEvalError

    stage = attempt.get("optional_scene_stage")
    steps = stage.get("steps") if isinstance(stage, dict) else None
    spatial = steps.get("spatial") if isinstance(steps, dict) else None
    details = steps.get("details") if isinstance(steps, dict) else None
    coverage = attempt.get("optional_step_coverage")
    spatial_coverage = coverage.get("spatial") if isinstance(coverage, dict) else None
    allowed_coverage = {"inspected", "not_run", "unknown", "stale"}
    if (
        attempt.get("optional_stage_version") != 1
        or not isinstance(stage, dict)
        or stage.get("version") != 1
        or not attempt.get("attempt_id")
        or stage.get("receipt_attempt_id") != attempt.get("attempt_id")
        or not stage.get("scene_card_hash")
        or not stage.get("main_state_fingerprint")
        or not stage.get("completed_state_fingerprint")
        or not isinstance(spatial, dict)
        or spatial.get("status") != "complete"
        or not isinstance(spatial.get("gaps"), list)
        or not isinstance(details, dict)
        or details.get("status") != "not_run"
        or not isinstance(details.get("gaps"), list)
        or not isinstance(spatial_coverage, dict)
        or spatial_coverage.get("status") not in allowed_coverage
        or not isinstance(spatial_coverage.get("gaps"), list)
        or not isinstance(attempt.get("spatial_stage_result"), (dict, type(None)))
        or not isinstance(attempt.get("spatial_discovery_result"), (dict, type(None)))
    ):
        raise MapSpatialEvalError("Evolution空间可选阶段缺少同attempt的已收尾回执")
    return {
        "version": stage["version"],
        "receipt_attempt_id": stage["receipt_attempt_id"],
        "scene_card_hash": stage["scene_card_hash"],
        "main_state_fingerprint": stage["main_state_fingerprint"],
        "completed_state_fingerprint": stage["completed_state_fingerprint"],
        "steps": {"details": details, "spatial": spatial},
        "spatial_step_coverage": spatial_coverage,
        "spatial_discovery_result": attempt.get("spatial_discovery_result"),
        "spatial_stage_result": attempt.get("spatial_stage_result"),
        "human_validated": False,
    }


async def read_assistant_product_evidence(
    db, root: Path, binding: dict, case_id: str, record: dict
) -> dict:
    """Read a completed Assistant turn by its real run_id and request Scene."""
    from evals.map_spatial import MapSpatialEvalError, _read_private_json
    from modules.assistant.facade import read_map_spatial_evaluation_turn

    run_id = record.get("run_id")
    task_id = record.get("task_id")
    if not run_id or not task_id:
        raise MapSpatialEvalError("Assistant真实回合账本缺run/task id")
    scope = binding["case_bindings"][case_id]
    task_path = private_ref(
        root, f"task-ledger/assistant/{binding['family_id']}/{case_id}/{task_id}.json"
    )
    task_record = _read_private_json(task_path)
    evidence = await read_map_spatial_evaluation_turn(db, binding["novel_id"], run_id)
    if (
        task_record.get("task_type") != "assistant_turn"
        or task_record.get("status") != "completed"
        or task_record.get("run_id") != run_id
        or task_record.get("task_id") != task_id
        or evidence.get("schema_version") != 1
        or evidence.get("novel_id") != binding["novel_id"]
        or evidence.get("run_id") != run_id
        or evidence.get("task_id") != task_id
        or evidence.get("scene_ids") != [scope["scene_id"]]
        or evidence.get("scene_scope_status") != "known"
        or evidence.get("request", {}).get("context", {}).get("scene_id")
        != scope["scene_id"]
        or evidence.get("truncated") is not False
        or evidence.get("omitted_count") != 0
        or evidence.get("human_validated") is not False
        or evidence.get("tool_invocations") is not None
        or evidence.get("tool_invocations_status") != "unknown"
        or digest(evidence) != record.get("evidence_sha256")
    ):
        raise MapSpatialEvalError("Assistant持久回执与真实Scene/run/task不符")
    return evidence


def verify_writing_receipts(
    root: Path, binding: dict, case_id: str, evidence: dict
) -> None:
    from evals.map_spatial import (
        MapSpatialEvalError,
        _read_ledger,
        _read_private_json,
        _sha256_file,
    )

    run = _read_ledger(root)["runs"].get(f"{binding['family_id']}/{case_id}", {})
    arms = run.get("arms") or {}
    if (
        run.get("status") != "completed"
        or set(arms) != {"with_spatial_brief", "without_spatial_brief"}
        or run.get("source_sha256") != binding["source_sha256"]
    ):
        raise MapSpatialEvalError("评分缺少已完成Writing配对原始回执")
    tasks = {ref["task_id"]: ref for ref in evidence.get("writing_paired", [])}
    if set(tasks) != {arm.get("task_id") for arm in arms.values()}:
        raise MapSpatialEvalError("评分输入与真实配对任务不符")
    for name, arm in arms.items():
        path = private_ref(root, f"runs/{binding['family_id']}/{case_id}-{name}.json")
        raw = _read_private_json(path)
        draft = tasks[arm["task_id"]].get("draft") or {}
        if (
            arm.get("status") != "completed"
            or arm.get("raw_output_sha256") != _sha256_file(path)
            or raw.get("draft_hash") != draft.get("content_hash")
            or raw.get("draft_content") != draft.get("content")
        ):
            raise MapSpatialEvalError("Writing原始候选或输出哈希已变化")


def judge_prompt(root: Path, binding: dict, case_id: str, evidence: dict) -> str:
    from evals.map_spatial import _case_for, _read_private_json, load_matrix

    source = _case_for(
        _read_private_json(private_ref(root, f"{binding['family_id']}/source.json")),
        case_id,
    )
    expected = _case_for(
        _read_private_json(private_ref(root, f"{binding['family_id']}/expected.json")),
        case_id,
    )
    payload = {
        "suite": "map_spatial",
        "phase": "judge",
        "binding_sha256": digest(binding),
        "case_id": case_id,
        "source": source,
        "expected": expected,
        "evidence": evidence,
        "evidence_sha256": digest(evidence),
        "rubric": rubric(),
        "metrics": load_matrix()["metrics_by_genre"][binding["genre"]],
        "instruction": (
            "只根据真实产品证据逐指标评分。缺证据、调用量或费用均unknown，不估为零。"
            "某题材/案例对某指标确实没有观察机会时，status=not_applicable且分子分母均为0；"
            "缺失、截断、来源漂移或无法核验时status=unknown且分子分母为null。"
            "比例必须有真实分子/分母及证据task_id。空间一致性和正文质量在同一0到1尺度"
            "分别报告两臂，without_map为未带地图得分。作者修改次数等计数的denominator为1；"
            "author_review_steps与author_review_seconds必须逐字采用本case代理审核events的计数/秒数；"
            "这是隔离合成作品的代理作者HTTP回执耗时，不是人类写作/审核时间。作者类型改名/合并/归档"
            "必须逐字采用持久词表revision lineage计数。"
            "成本只接受实际费用，不从token猜测。"
            "evidence_task_ids只能引用task_ids_by_group中的真实ID；没有必要的任务或来源则unknown。"
            "类型涌现的activation可参考全部五个独立Scene，"
            "但只把原始提案属于本case的唯一type计入分母，"
            "同一类型跨Scene不重复计数。Assistant tool_invocations_status=unknown；"
            "不要从目录或答复文字"
            "推断工具调用，目标解析、预览意图、越权/猜坐标拒绝与unknown正确率只评实际答复、计划、"
            "预览/拒绝回执和来源。只输出度量，不输出passed或审批布尔值。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def evaluate_development(root: Path, matrix: dict) -> dict:
    """Recompute every genre gate from frozen product evidence and raw judge output."""
    from evals.map_spatial import (
        MapSpatialEvalError,
        _read_private_json,
        _sha256_file,
        load_matrix,
    )

    root = Path(root)
    current_matrix = load_matrix()
    if matrix != current_matrix:
        raise MapSpatialEvalError("开发gate输入必须等于当前冻结manifest")
    families = [
        row for row in matrix.get("families", []) if row.get("split") == "development"
    ]
    by_genre = {row["genre"]: row for row in families}
    if len(families) != 5 or set(by_genre) != set(matrix.get("metrics_by_genre", {})):
        raise MapSpatialEvalError("开发集必须恰好覆盖五题材且每题材一个资料族")

    blockers: list[dict] = []
    proofs: list[dict] = []
    genre_rows: dict[str, dict] = {}
    for genre in sorted(by_genre):
        family = by_genre[genre]
        family_id = family["family_id"]
        try:
            source_path = private_ref(root, f"{family_id}/source.json")
            expected_path = private_ref(root, f"{family_id}/expected.json")
            if (
                not source_path.is_file()
                or not expected_path.is_file()
                or source_path.stat().st_mode & 0o777 != 0o600
                or expected_path.stat().st_mode & 0o777 != 0o600
                or _sha256_file(source_path) != family["source_sha256"]
                or _sha256_file(expected_path) != family["expected_sha256"]
            ):
                raise MapSpatialEvalError("冻结资料哈希或权限不符")
            source = _read_private_json(source_path)
            expected = _read_private_json(expected_path)
            if (
                source.get("family_id") != family_id
                or expected.get("family_id") != family_id
                or source.get("split") != "development"
                or expected.get("split") != "development"
                or source.get("human_validated") is not False
                or expected.get("human_validated") is not False
            ):
                raise MapSpatialEvalError("开发材料身份或human_validated标记不符")
            source_cases = {item["case_id"]: item for item in source.get("cases", [])}
            expected_cases = {item["case_id"]: item for item in expected.get("cases", [])}
            if len(source_cases) != 5 or set(source_cases) != set(expected_cases):
                raise MapSpatialEvalError("开发源文与期望没有五个一一对应案例")
            try:
                binding = read_binding(root, family_id)
            except Exception as exc:
                binding = None
                blockers.append(
                    {
                        "genre": genre,
                        "family_id": family_id,
                        "reason": "final_binding_missing_or_drifted",
                        "detail": type(exc).__name__,
                    }
                )
        except Exception as exc:
            source_cases = {}
            expected_cases = {}
            binding = None
            blockers.append(
                {
                    "genre": genre,
                    "family_id": family_id,
                    "reason": "development_material_invalid",
                    "detail": type(exc).__name__,
                }
            )

        case_metrics: dict[str, list[Metric]] = {}
        metric_contract = matrix["metrics_by_genre"][genre]
        expected_metrics = {
            (group, name) for group, names in metric_contract.items() for name in names
        }
        for case_id in sorted(source_cases):
            observed: list[Metric] = []
            if binding is not None:
                request = request_path(root, binding, "development_judge", case_id)
                try:
                    row, raw = read_request(root, request, binding)
                    frozen_path = evidence_path(root, binding, case_id)
                    evidence = _read_private_json(frozen_path)
                    actual_evidence_hash = digest(evidence)
                    if (
                        row.get("phase") != "development_judge"
                        or row.get("case_id") != case_id
                        or row.get("evidence_sha256") != actual_evidence_hash
                        or evidence.get("family_id") != family_id
                        or evidence.get("case_id") != case_id
                        or evidence.get("genre") != genre
                        or evidence.get("novel_id") != binding["novel_id"]
                        or evidence.get("scene_id")
                        != binding["case_bindings"][case_id]["scene_id"]
                        or evidence.get("common_binding_sha256")
                        != digest(read_common_binding(root, family_id))
                        or evidence.get("final_binding_sha256") != digest(binding)
                        or evidence.get("human_validated") is not False
                        or evidence.get("telemetry_limits", {}).get("human_validated")
                        is not False
                    ):
                        raise MapSpatialEvalError("产品证据未绑定冻结族/Scene/owner版本")
                    prompt = judge_prompt(root, binding, case_id, evidence)
                    if row.get("prompt") != prompt:
                        raise MapSpatialEvalError(
                            "教师实际输入与原文/期望/产品证据重算不符"
                        )
                    _validate_evidence_task_ids(root, binding, case_id, evidence)
                    result = JudgeResult.model_validate(raw)
                    values = {(item.group, item.name): item for item in result.metrics}
                    if (
                        len(values) != len(result.metrics)
                        or set(values) != expected_metrics
                    ):
                        raise MapSpatialEvalError("裁判输出缺少、重复或增加了冻结指标")
                    for key, metric in values.items():
                        allowed_ids = set(
                            evidence.get("task_ids_by_group", {}).get(metric.group, [])
                        )
                        if (
                            len(set(metric.evidence_task_ids))
                            != len(metric.evidence_task_ids)
                            or not set(metric.evidence_task_ids) <= allowed_ids
                            or (
                                metric.status == "observed"
                                and not metric.evidence_task_ids
                            )
                        ):
                            raise MapSpatialEvalError(
                                "裁判引用非本组真实task或缺少证据task"
                            )
                        if metric.name == "total_cost":
                            if (
                                evidence.get("telemetry_limits", {}).get("cost")
                                == "unknown"
                                and metric.status != "unknown"
                            ):
                                raise MapSpatialEvalError(
                                    "实际费用不可观测，裁判不得估算或报零"
                                )
                        elif metric.name in {
                            "author_review_steps",
                            "author_review_seconds",
                        }:
                            field = (
                                "review_steps"
                                if metric.name == "author_review_steps"
                                else "elapsed_seconds"
                            )
                            measured = evidence["proxy_author_review"].get(field)
                            if (
                                metric.status != "observed"
                                or not math.isclose(
                                    metric.numerator,
                                    float(measured),
                                    rel_tol=0.0,
                                    abs_tol=0.001,
                                )
                                or metric.denominator != 1
                            ):
                                raise MapSpatialEvalError(
                                    "代理作者审核步数/时间必须等于逐操作回执"
                                )
                        elif metric.name in {
                            "author_rename_count",
                            "author_merge_count",
                            "author_archive_count",
                        }:
                            measured = evidence["family_type_evidence"][
                                "author_change_counts_for_case"
                            ].get(metric.name)
                            if (
                                measured is None
                                or metric.status != "observed"
                                or metric.numerator != measured
                                or metric.denominator != 1
                            ):
                                raise MapSpatialEvalError(
                                    "作者类型变更计数必须等于持久词表revision lineage"
                                )
                        observed.append(metric)
                    proofs.append(
                        {
                            "genre": genre,
                            "family_id": family_id,
                            "case_id": case_id,
                            "request_sha256": _sha256_file(request),
                            "raw_output_sha256": row["raw_output_sha256"],
                            "evidence_sha256": actual_evidence_hash,
                            "human_validated": False,
                        }
                    )
                except Exception as exc:
                    blockers.append(
                        {
                            "genre": genre,
                            "family_id": family_id,
                            "case_id": case_id,
                            "reason": "judge_or_evidence_missing_invalid_unknown",
                            "detail": type(exc).__name__,
                        }
                    )
            case_metrics[case_id] = observed

        metrics: dict[str, dict] = {}
        genre_passed = True
        for group, names in metric_contract.items():
            for name in names:
                rows = [
                    next(
                        (
                            item
                            for item in case_metrics[case_id]
                            if (item.group, item.name) == (group, name)
                        ),
                        None,
                    )
                    for case_id in sorted(source_cases)
                ]
                present = [item for item in rows if item is not None]
                unknown = [item for item in present if item.status == "unknown"]
                applicable = [item for item in present if item.status == "observed"]
                if unknown or len(present) != len(rows):
                    status = "unknown"
                    numerator = denominator = value = without_map = None
                    reason = "至少一个开发案例缺少可验证度量"
                elif not applicable:
                    status = "not_applicable"
                    numerator = denominator = 0.0
                    value = without_map = None
                    reason = "全部案例均无该指标观察机会"
                else:
                    status = "observed"
                    numerator = sum(item.numerator for item in applicable)
                    denominator = sum(item.denominator for item in applicable)
                    value = numerator / denominator if denominator else None
                    without_values = [
                        item for item in applicable if item.without_map is not None
                    ]
                    without_map = (
                        sum(item.without_map for item in without_values)
                        / len(without_values)
                        if len(without_values) == len(applicable)
                        else None
                    )
                    reason = "逐案例真实指标按题材分子/分母聚合"
                threshold = BOUNDS.get(name)
                passed = status == "observed" and value is not None
                if threshold is not None:
                    passed = passed and threshold[0] <= value <= threshold[1]
                if name in {"spatial_consistency", "prose_quality"}:
                    if without_map is None:
                        passed = False
                        reason += "；配对无地图分数缺失"
                    elif name == "spatial_consistency":
                        passed = passed and value > without_map
                        reason += "；要求严格优于无地图"
                    else:
                        passed = passed and value >= without_map
                        reason += "；要求不低于无地图"
                if name == "total_cost" and status != "observed":
                    passed = False
                    reason += "；未观测实际费用不能按零通过"
                metrics[f"{group}.{name}"] = {
                    "group": group,
                    "name": name,
                    "status": status,
                    "numerator": numerator,
                    "denominator": denominator,
                    "value": value,
                    "without_map": without_map,
                    "threshold": list(threshold) if threshold is not None else None,
                    "passed": bool(passed),
                    "case_count": len(rows),
                    "applicable_case_count": len(applicable),
                    "unknown_case_count": len(unknown)
                    + sum(item is None for item in rows),
                    "reason": reason,
                    "evidence_request_hashes": [
                        proof["request_sha256"]
                        for proof in proofs
                        if proof["genre"] == genre
                    ],
                }
                if not passed:
                    genre_passed = False
        if not genre_passed:
            blockers.append(
                {
                    "genre": genre,
                    "family_id": family_id,
                    "reason": (
                        "one_or_more_genre_metrics_not_observed_or_threshold_failed"
                    ),
                }
            )
        genre_rows[genre] = {
            "family_id": family_id,
            "status": "passed" if genre_passed else "blocked",
            "metrics": metrics,
            "human_validated": False,
        }
    passed = not blockers and all(
        row["status"] == "passed" for row in genre_rows.values()
    )
    return {
        "schema_version": 1,
        "stage": "development_gate",
        "suite": "map_spatial",
        "status": "passed" if passed else "blocked",
        "passed": passed,
        "manifest_sha256": digest(matrix),
        "rubric_sha256": rubric_hash(),
        "genres": genre_rows,
        "proofs": proofs,
        "blockers": blockers,
        "human_validated": False,
    }


def _validate_evidence_task_ids(
    root: Path, binding: dict, case_id: str, evidence: dict
) -> None:
    from evals.map_spatial import MapSpatialEvalError, _read_ledger, _read_private_json

    family_id = binding["family_id"]
    evolution_path = private_ref(root, f"evolution/{family_id}.json")
    evolution = _read_private_json(evolution_path)
    operation_id = evolution.get("operation_id")
    evolution_ids = list(evolution.get("task_ids") or [])
    for task_id in evolution_ids:
        item = _read_private_json(
            private_ref(
                root, f"task-ledger/evolution/{family_id}/{operation_id}/{task_id}.json"
            )
        )
        if item.get("task_id") != task_id or item.get("status") != "completed":
            raise MapSpatialEvalError("Evolution task账本不完整")
    assistant = _read_private_json(
        private_ref(root, f"assistant/{family_id}/{case_id}.json")
    )
    assistant_task = assistant.get("task_id")
    assistant_task_record = _read_private_json(
        private_ref(
            root, f"task-ledger/assistant/{family_id}/{case_id}/{assistant_task}.json"
        )
    )
    if assistant_task_record.get("status") != "completed":
        raise MapSpatialEvalError("Assistant task账本不完整")
    ledger = _read_ledger(root)
    run = ledger.get("runs", {}).get(f"{family_id}/{case_id}", {})
    writing_ids = [
        str(arm.get("task_id"))
        for arm in (run.get("arms") or {}).values()
        if arm.get("task_id")
    ]
    if (
        run.get("status") != "completed"
        or len(writing_ids) != 2
        or len(set(writing_ids)) != 2
    ):
        raise MapSpatialEvalError("Writing paired run ledger不完整")
    expected = {
        "cold_start": evolution_ids,
        "type_emergence": evolution_ids,
        "writing_paired": writing_ids,
        "assistant": [assistant_task],
    }
    actual = evidence.get("task_ids_by_group")
    if not isinstance(actual, dict) or any(
        set(actual.get(group, [])) != set(task_ids)
        for group, task_ids in expected.items()
    ):
        raise MapSpatialEvalError("产品证据中的task映射与精确执行账本不符")


def require_development_gate(root: Path, matrix: dict) -> dict:
    from evals.map_spatial import MapSpatialEvalError, _gate_path, _read_private_json

    actual = evaluate_development(root, matrix)
    if actual.get("status") != "passed" or actual.get("passed") is not True:
        raise MapSpatialEvalError("开发集存在未知/缺失指标或阈值未通过；留出保持关闭")
    frozen = _read_private_json(_gate_path(root))
    if frozen != actual:
        raise MapSpatialEvalError("开发gate与真实评分证据不一致")
    return actual

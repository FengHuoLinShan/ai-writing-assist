"""Map-only calibration, immutable request journal and evidence-backed gates.

No model calls occur here. The scoped Codex executor owns the actual invocation.
Raw requests, outputs and product receipts always remain outside repositories.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    status: Literal["observed", "unknown"]
    numerator: float | None
    denominator: float | None
    without_map: float | None
    evidence_task_ids: list[str]
    reason: str = Field(min_length=1, max_length=2000)


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


def read_binding(root: Path, family_id: str) -> dict:
    from evals.map_spatial import (
        MATRIX_PATH,
        MapSpatialEvalError,
        _read_private_json,
        _sha256_file,
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
    if any(
        value.get(key) != expected
        for key, expected in {
            "suite": "map_spatial",
            "family_id": family_id,
            "manifest_sha256": _sha256_file(MATRIX_PATH),
            "rubric_sha256": rubric_hash(),
            "source_sha256": family["source_sha256"],
            "expected_sha256": family["expected_sha256"],
            "split": family["split"],
            "genre": family["genre"],
            "private_root_sha256": digest(str(root.resolve())),
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
    return value


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

    path = request_path(root, binding, "teacher_calibration", "seeded-v1")
    row, raw = read_request(root, path, binding)
    expected_meta = CodexStructuredExecutor(
        attempts=1,
        model=EVAL_TEACHER_MODEL,
        reasoning_effort=EVAL_TEACHER_REASONING_EFFORT,
    ).meta
    result = CalibrationResult.model_validate(raw)
    labels = {item.case_id: item.label for item in result.decisions}
    if (
        row.get("step_name") != CALIBRATION_STEP
        or row.get("prompt") != calibration_prompt(binding)
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


UNSUPPORTED_PRODUCT_GROUPS = ("cold_start", "type_emergence", "assistant")


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
    """Four-group judge stays closed until actual domain receipt adapters exist."""
    from evals.map_spatial import MapSpatialEvalError

    # Assistant tasks carry run_id; Evolution tasks carry run/range identities.
    # Their real facades must resolve those receipts, never fabricate scene_id.
    raise MapSpatialEvalError(
        "not_ready_for_live: 正式证据适配尚缺 " + ", ".join(UNSUPPORTED_PRODUCT_GROUPS)
    )


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
            "比例必须有真实分子/分母及证据task_id。空间一致性和正文质量在同一0到1尺度"
            "分别报告两臂，without_map为未带地图得分。作者修改次数等计数的denominator为1；"
            "只接受真实observations，不估算作者步数/耗时；成本只接受实际费用，不从token猜测。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def evaluate_development(root: Path, matrix: dict) -> dict:
    """A boolean/template cannot substitute missing real product measurements."""
    from evals.map_spatial import MapSpatialEvalError

    raise MapSpatialEvalError(
        "not_ready_for_live: 四组产品证据和作者实际操作/费用计量尚未齐全；"
        "开发gate保持关闭"
    )


def require_development_gate(root: Path, matrix: dict) -> dict:
    from evals.map_spatial import MapSpatialEvalError, _gate_path, _read_private_json

    actual = evaluate_development(root, matrix)
    frozen = _read_private_json(_gate_path(root))
    if frozen != actual:
        raise MapSpatialEvalError("开发gate与真实评分证据不一致")
    return actual

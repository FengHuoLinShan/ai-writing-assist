"""Explicit map evaluation lifecycle commands; no setup or model calls on import."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from evals.map_spatial import (
    LIVE_ENV,
    PROJECT_GENRES,
    MapSpatialEvalError,
    _case_for,
    _database_identity,
    _database_target,
    _family_for,
    _gate_path,
    _read_private_json,
    _sha256_file,
    _write_private_json,
    load_matrix,
    preflight_common_project,
    preflight_project,
    require_private_directory,
    task_execution_budget,
    verify_materials,
)
from evals.map_spatial_guard import (
    CALIBRATION_STEP,
    JUDGE_STEP,
    CalibrationResult,
    JudgeResult,
    _source_binding_matches,
    binding_path,
    calibration_prompt,
    common_binding_path,
    digest,
    evaluate_development,
    evidence_path,
    judge_prompt,
    private_lock,
    private_ref,
    product_evidence,
    read_binding,
    read_common_binding,
    read_evolution_product_evidence,
    request_key,
    require_calibration,
    require_development_gate,
    same_source_baseline,
    verify_runtime,
)


def explicit_execution(execute: bool) -> None:
    if not execute or os.environ.get(LIVE_ENV) != "1":
        raise MapSpatialEvalError("默认关闭：需要--execute和地图专用live开关")
    from app.main import app  # noqa: F401 — before any facade/container use


def _validate_live_api_target(api_base_url: str, timeout_seconds: int) -> None:
    if os.environ.get("APP_ENV") != "test" or os.environ.get("AUTH_MODE") != "local":
        raise MapSpatialEvalError("产品评测要求APP_ENV=test与AUTH_MODE=local")
    _database_target(os.environ.get("DATABASE_URL", ""))
    # No network server can prove it uses this process's isolated database.
    if api_base_url != "http://map-spatial-eval.internal":
        raise MapSpatialEvalError(
            "产品评测只接受同进程ASGI API；拒绝网络地址以避免错库写入"
        )
    if not 1 <= timeout_seconds <= 3600:
        raise MapSpatialEvalError("产品请求超时必须在1到3600秒")


@asynccontextmanager
async def _product_client(api_base_url: str, timeout_seconds: int):
    """Run the real product app against the verified process-local manager."""
    _validate_live_api_target(api_base_url, timeout_seconds)
    from core.database import get_manager

    manager = get_manager()
    if _database_identity(str(manager.engine.url)) != _database_identity(
        os.environ["DATABASE_URL"]
    ):
        raise MapSpatialEvalError("产品API实际数据库与隔离配置不同")
    import httpx

    from app.main import app

    if app.dependency_overrides:
        raise MapSpatialEvalError("评测产品API不得使用未验证的dependency overrides")
    # ASGITransport deliberately skips startup workers/embedding prewarming.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=api_base_url,
        timeout=min(timeout_seconds, 30),
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as client:
        yield client


def _setup_record_path(root: Path, family_id: str) -> Path:
    return private_ref(root, f"setups/{family_id}.json")


def _load_family_source(root: Path, family: dict, *, allow_holdout: bool = False) -> dict:
    if family["split"] == "holdout" and not allow_holdout:
        raise MapSpatialEvalError("留出材料须在开发gate后单独准备")
    source_path = private_ref(root, f"{family['family_id']}/source.json")
    source = _read_private_json(source_path)
    if (
        _sha256_file(source_path) != family["source_sha256"]
        or (source.get("family_id"), source.get("genre"), source.get("split"))
        != (family["family_id"], family["genre"], family["split"])
        or source.get("human_validated") is not False
        or not isinstance(source.get("project_setup"), dict)
    ):
        raise MapSpatialEvalError("开发资料身份、权限或冻结哈希无效")
    cases = source.get("cases")
    if (
        not isinstance(cases, list)
        or len(cases) != 5
        or len({item.get("case_id") for item in cases}) != 5
        or len({item.get("source_excerpt") for item in cases}) != 5
        or any(not isinstance(item.get("source_excerpt"), str) for item in cases)
    ):
        raise MapSpatialEvalError("开发族必须有五段互异的原文")
    return source


def _scope_path(root: Path, family_id: str) -> Path:
    return private_ref(root, f"scopes/{family_id}.json")


def _validated_setup(root: Path, family: dict, source: dict) -> tuple[dict, dict]:
    setup = _read_private_json(_setup_record_path(root, family["family_id"]))
    scopes_path = _scope_path(root, family["family_id"])
    if (
        setup.get("status") != "completed"
        or setup.get("family_id") != family["family_id"]
        or setup.get("source_sha256") != family["source_sha256"]
        or setup.get("scopes_sha256") != _sha256_file(scopes_path)
    ):
        raise MapSpatialEvalError("正常产品API setup未完成或私有scope已变化")
    scopes = _read_private_json(scopes_path)
    cases = {row["case_id"] for row in source["cases"]}
    if set(scopes) != cases or set(setup.get("scenes", {})) != cases:
        raise MapSpatialEvalError("setup没有为冻结五案例保存独立Scene")
    if len({value.get("scene_id") for value in scopes.values()}) != 5:
        raise MapSpatialEvalError("setup Scene重复或缺失")
    for case_id, scope in scopes.items():
        product_scene = setup["scenes"][case_id]
        if (
            set(scope) != {"novel_id", "scene_id", "chapter_index"}
            or scope.get("novel_id") != setup.get("project_id")
            or scope.get("scene_id") != product_scene.get("scene_id")
            or scope.get("chapter_index") != product_scene.get("chapter_index")
        ):
            raise MapSpatialEvalError("scope不是正常产品API setup返回的Scene")
    return setup, scopes


async def _post_product_json(client, path: str, payload: dict) -> dict:
    try:
        response = await asyncio.wait_for(
            client.post(path, json=payload), timeout=client.timeout.read
        )
    except BaseException as exc:
        raise MapSpatialEvalError("产品API请求中断；setup状态保持unknown") from exc
    if not 200 <= response.status_code < 300:
        raise MapSpatialEvalError(
            f"合成项目产品API拒绝请求（HTTP {response.status_code}）；setup不可重试"
        )
    try:
        value = response.json()
    except ValueError as exc:
        raise MapSpatialEvalError("产品API响应无法验证；setup不可重试") from exc
    if not isinstance(value, dict):
        raise MapSpatialEvalError("产品API响应格式无效；setup不可重试")
    return value


async def _setup_family_via_client(
    *, private_root: Path, family_id: str, client, allow_holdout: bool = False
) -> dict:
    """Create synthetic Project/source and exact Scene spans via HTTP APIs."""
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    source = _load_family_source(root, family, allow_holdout=allow_holdout)
    setup_path = _setup_record_path(root, family_id)
    scopes_path = _scope_path(root, family_id)
    with private_lock(root):
        if setup_path.exists() or scopes_path.exists():
            raise MapSpatialEvalError("setup已启动或完成；不可重复创建项目")
        record = {
            "suite": "map_spatial",
            "family_id": family_id,
            "source_sha256": family["source_sha256"],
            "status": "started",
            "human_validated": False,
            "project_id": None,
            "scenes": {},
        }
        _write_private_json(setup_path, record)

    setup = source["project_setup"]
    chapter_index = int(setup.get("chapter_index") or 0)
    if chapter_index < 1:
        raise MapSpatialEvalError("冻结setup缺少有效章节号")
    setup_id = uuid.uuid4().hex[:12]
    try:
        project = await _post_product_json(
            client,
            "/api/projects",
            {
                "title": f"MAP-EVAL:{family_id}:{setup_id}",
                "genre": PROJECT_GENRES[family["genre"]],
                "language": "zh",
                "default_reveal_policy": "author_safe",
            },
        )
        novel_id = str(project.get("id") or "")
        if (
            not novel_id
            or project.get("title") != f"MAP-EVAL:{family_id}:{setup_id}"
            or project.get("genre") != PROJECT_GENRES[family["genre"]]
        ):
            raise MapSpatialEvalError("正常Project API没有返回冻结的题材与项目身份")

        with private_lock(root):
            record = _read_private_json(setup_path)
            record["project_id"] = novel_id
            _write_private_json(setup_path, record)

        reading_response = await asyncio.wait_for(
            client.get(f"/api/evolution/reading?novel_id={novel_id}"),
            timeout=client.timeout.read,
        )
        if reading_response.status_code != 200:
            raise MapSpatialEvalError("新项目理解状态无法读取；setup不可重试")
        reading = reading_response.json()
        engine = reading.get("engine", {})
        epoch = engine.get("epoch")
        if (
            reading.get("run") is not None
            or engine.get("engine") != "legacy"
            or type(epoch) is not int
            or epoch < 1
        ):
            raise MapSpatialEvalError("新项目理解状态不符合预期；不能停止已有流程")
        switched = await _post_product_json(
            client,
            f"/api/evolution/engine?novel_id={novel_id}",
            {
                "engine": "evolution",
                "expected_epoch": epoch,
                "stop_active": False,
                "authorization_confirmed": True,
            },
        )
        if (
            switched.get("engine") != "evolution"
            or switched.get("epoch") != epoch + 1
            or switched.get("schema_floor") != 2
            or any(
                switched.get(key) != 0
                for key in (
                    "stopped_imports",
                    "stopped_evolution_runs",
                    "cancelled_tasks",
                )
            )
        ):
            raise MapSpatialEvalError("正常引擎切换回执不符合空项目约束；setup不可重试")
        with private_lock(root):
            record = _read_private_json(setup_path)
            record["engine_switch"] = switched
            _write_private_json(setup_path, record)

        preset = await _post_product_json(
            client,
            f"/api/world/project-vocabulary/{novel_id}/presets",
            {"preset_ids": [family["genre"]]},
        )
        preset_items = preset.get("items")
        from modules.world.project_vocabulary_presets import PRESETS

        expected_preset_count = len(PRESETS[family["genre"]].items)
        if (
            not isinstance(preset_items, list)
            or len(preset_items) != int(preset.get("applied") or 0)
            or int(preset.get("applied") or 0)
            + int(preset.get("already_applied") or 0)
            + int(preset.get("duplicate_skipped") or 0)
            != expected_preset_count
        ):
            raise MapSpatialEvalError("产品词表预设未能应用")
        with private_lock(root):
            record = _read_private_json(setup_path)
            record.update(
                preset_applied=int(preset.get("applied") or 0),
                preset_already_applied=int(preset.get("already_applied") or 0),
                preset_duplicate_skipped=int(preset.get("duplicate_skipped") or 0),
            )
            _write_private_json(setup_path, record)

        content_parts = []
        offsets = {}
        cursor = 0
        for case in source["cases"]:
            excerpt = case["source_excerpt"]
            if content_parts:
                content_parts.append("\n\n")
                cursor += 2
            start = cursor
            content_parts.append(excerpt)
            cursor += len(excerpt)
            offsets[case["case_id"]] = {"start_offset": start, "end_offset": cursor}
        content = "".join(content_parts)
        published = await _post_product_json(
            client,
            "/api/writing/drafts",
            {
                "novel_id": novel_id,
                "chapter_index": chapter_index,
                "title": f"合成地图评测 {family_id}",
                "content": content,
            },
        )
        draft = published.get("draft") or {}
        draft_id = str(draft.get("id") or "")
        content_hash = str(draft.get("content_hash") or "")
        if (
            not draft_id
            or draft.get("novel_id") != novel_id
            or draft.get("chapter_index") != chapter_index
            or draft.get("status") != "published"
            or content_hash != _sha256_file_bytes(content.encode("utf-8"))
        ):
            raise MapSpatialEvalError("正文发布回执与实际合成正文不符")

        scope_entries = {}
        for index, case in enumerate(source["cases"]):
            case_id = case["case_id"]
            span = offsets[case_id]
            scene = await _post_product_json(
                client,
                f"/api/outline/scenes?novel_id={novel_id}",
                {
                    "scene_index": index,
                    "title": f"地图评测Scene {index + 1}",
                    "source": "manual",
                    "chapter_ids": [str(chapter_index)],
                    "scene_chunks": [
                        {
                            "chapter_index": chapter_index,
                            **span,
                            "source_draft_id": draft_id,
                            "source_content_hash": content_hash,
                        }
                    ],
                    "status": "canonical",
                },
            )
            scene_id = str(scene.get("id") or "")
            if (
                not scene_id
                or scene.get("status") != "canonical"
                or scene.get("chapter_ids") != [str(chapter_index)]
            ):
                raise MapSpatialEvalError("Scene API未返回预期的canonical来源绑定")
            scope_entries[case_id] = {
                "novel_id": novel_id,
                "scene_id": scene_id,
                "chapter_index": chapter_index,
            }
            with private_lock(root):
                record = _read_private_json(setup_path)
                record["scenes"][case_id] = {
                    "scene_id": scene_id,
                    "chapter_index": chapter_index,
                    "draft_id": draft_id,
                    "source_hash": content_hash,
                }
                _write_private_json(setup_path, record)

        if len({row["scene_id"] for row in scope_entries.values()}) != 5:
            raise MapSpatialEvalError("产品API没有创建五个独立Scene")
        with private_lock(root):
            record = _read_private_json(setup_path)
            record.update(
                status="completed",
                project_id=novel_id,
                chapter_index=chapter_index,
                draft_id=draft_id,
                source_hash=content_hash,
                scopes_sha256=None,
            )
            if scopes_path.exists():
                raise MapSpatialEvalError("私有scope文件已存在；不能覆盖")
            _write_private_json(scopes_path, scope_entries)
            record["scopes_sha256"] = _sha256_file(scopes_path)
            _write_private_json(setup_path, record)
        return {
            "status": "completed",
            "family_id": family_id,
            "novel_id": novel_id,
            "scenes": len(scope_entries),
            "scopes": str(scopes_path),
            "human_validated": False,
        }
    except BaseException:
        with private_lock(root):
            record = _read_private_json(setup_path)
            if record.get("status") != "completed":
                record["status"] = "unknown"
                _write_private_json(setup_path, record)
        raise


def _sha256_file_bytes(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


async def setup_family(
    *,
    private_root: Path,
    family_id: str,
    api_base_url: str,
    execute: bool,
    timeout_seconds: int = 30,
) -> dict:
    """Explicit, one-shot product API setup for one synthetic development family."""
    explicit_execution(execute)
    _validate_live_api_target(api_base_url, timeout_seconds)
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
        verify_materials(root, matrix)
    from core.database import get_manager

    if _database_identity(str(get_manager().engine.url)) != _database_identity(
        os.environ["DATABASE_URL"]
    ):
        raise MapSpatialEvalError("setup进程实际数据库与配置不同")
    async with _product_client(api_base_url, timeout_seconds) as client:
        return await _setup_family_via_client(
            private_root=private_root,
            family_id=family_id,
            client=client,
            allow_holdout=family["split"] == "holdout",
        )


def _evolution_record_path(root: Path, family_id: str) -> Path:
    return private_ref(root, f"evolution/{family_id}.json")


def _evolution_preview_path(root: Path, family_id: str, operation_id: str) -> Path:
    try:
        uuid.UUID(operation_id)
    except (ValueError, TypeError) as exc:
        raise MapSpatialEvalError("Evolution preview operation_id格式无效") from exc
    return private_ref(root, f"evolution-previews/{family_id}/{operation_id}.json")


def _evolution_task_path(
    root: Path, family_id: str, operation_id: str, task_id: str
) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", task_id):
        raise MapSpatialEvalError("演化task id格式无效")
    return private_ref(
        root, f"task-ledger/evolution/{family_id}/{operation_id}/{task_id}.json"
    )


def _assistant_record_path(root: Path, family_id: str, case_id: str) -> Path:
    request_key("development_judge", case_id)
    return private_ref(root, f"assistant/{family_id}/{case_id}.json")


def _assistant_task_path(root: Path, family_id: str, case_id: str, task_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", task_id):
        raise MapSpatialEvalError("Assistant task id格式无效")
    request_key("development_judge", case_id)
    return private_ref(
        root, f"task-ledger/assistant/{family_id}/{case_id}/{task_id}.json"
    )


def _review_record_path(root: Path, family_id: str) -> Path:
    return private_ref(root, f"author-review/{family_id}.json")


def _evolution_request(common: dict, operation_id: str, request_limit: int) -> dict:
    scene_ids = [item["scene_id"] for item in common["case_bindings"].values()]
    if len(set(scene_ids)) != 5:
        raise MapSpatialEvalError("共同基线必须包含五个不同Scene")
    return {
        "operation_id": operation_id,
        "mode": "bootstrap",
        "run_key": None,
        "from_scene_index": None,
        "end_chapter": max(
            item["chapter_index"] for item in common["case_bindings"].values()
        ),
        "request_limit": request_limit,
        "budget_mode": "bounded",
        "discover_details": False,
        "discover_spatial": True,
    }


def _validate_evolution_preview(preview: dict, request: dict) -> dict:
    steps = preview.get("optional_steps")
    spatial = steps.get("spatial") if isinstance(steps, dict) else None
    reserve = preview.get("mandatory_request_reserve")
    quota = spatial.get("quota") if isinstance(spatial, dict) else None
    per_scene = spatial.get("per_scene_limit") if isinstance(spatial, dict) else None
    used = spatial.get("used") if isinstance(spatial, dict) else None
    remaining = spatial.get("remaining") if isinstance(spatial, dict) else None
    request_range = spatial.get("request_range") if isinstance(spatial, dict) else None
    if (
        type(request.get("request_limit")) is not int
        or not 1 <= request["request_limit"] <= 1000
        or preview.get("spatial_discovery_enabled") is not True
        or preview.get("scene_count") != 5
        or preview.get("end_chapter") != request["end_chapter"]
        or preview.get("request_limit") != request["request_limit"]
        or preview.get("budget_mode") != "bounded"
        or preview.get("model") != "gpt-6-luna"
        or not isinstance(preview.get("fingerprint"), str)
        or not preview["fingerprint"]
        or type(reserve) is not int
        or reserve < 1
        or type(quota) is not int
        or quota < 1
        or type(per_scene) is not int
        or per_scene < 1
        or quota != per_scene * 5
        or used != 0
        or remaining != quota
        or request_range != {"minimum": 0, "maximum": quota}
    ):
        raise MapSpatialEvalError("Evolution预览未覆盖五个Scene的完整空间子额度")
    required = reserve + quota
    # Seed 1 + judges 5 + Writing 10*14 + Assistant 5*30; no verification here.
    other_stage_calls = 1 + 5 + 10 * 14 + 5 * 30
    return {
        "fingerprint": preview["fingerprint"],
        "scene_count": preview["scene_count"],
        "mandatory_request_reserve": reserve,
        "mandatory_reserve_kind": "static_minimum",
        "spatial_quota": quota,
        "spatial_quota_kind": "child_maximum",
        "spatial_per_scene_limit": per_scene,
        "required_root_limit": required,
        "request_limit": request["request_limit"],
        "extra_headroom": max(0, request["request_limit"] - required),
        "completion_guaranteed": False,
        "total_call_upper_bound": other_stage_calls + request["request_limit"],
        "total_call_upper_bound_with_connection_verification": other_stage_calls
        + 1
        + request["request_limit"],
        "within_root_limit": request["request_limit"] >= required,
    }


async def preview_evolution(
    *,
    private_root: Path,
    family_id: str,
    api_base_url: str,
    request_limit: int,
    execute: bool,
    timeout_seconds: int = 30,
) -> dict:
    """Persist a read-only product preview for root inspection before start."""
    explicit_execution(execute)
    _validate_live_api_target(api_base_url, timeout_seconds)
    if not 1 <= request_limit <= 1000:
        raise MapSpatialEvalError("Evolution request_limit必须在1到1000")
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
    common = read_common_binding(root, family_id)
    if family["split"] == "development":
        require_calibration(root, common)
    from core.database import get_manager

    manager = get_manager()
    async with manager.session() as db:
        await verify_runtime(db, common)

    operation_id = str(uuid.uuid4())
    request = _evolution_request(common, operation_id, request_limit)
    path = _evolution_preview_path(root, family_id, operation_id)
    preview_record = {
        "suite": "map_spatial",
        "family_id": family_id,
        "split": family["split"],
        "common_binding_sha256": digest(common),
        "operation_id": operation_id,
        "request": request,
        "request_sha256": digest(request),
        "status": "previewing",
        "human_validated": False,
    }
    with private_lock(root):
        if _evolution_record_path(root, family_id).exists():
            raise MapSpatialEvalError("Evolution操作已启动；不得覆盖或重新授权")
        if path.exists():
            raise MapSpatialEvalError("Evolution preview身份已占用")
        _write_private_json(path, preview_record)
    try:
        async with _product_client(api_base_url, timeout_seconds) as client:
            preview = await _post_product_json(
                client,
                f"/api/evolution/reading/preview?novel_id={common['novel_id']}",
                request,
            )
        facts = _validate_evolution_preview(preview, request)
        preview_record.update(
            status="previewed" if facts["within_root_limit"] else "budget_insufficient",
            preview_sha256=digest(preview),
            preview=facts,
        )
        with private_lock(root):
            _write_private_json(path, preview_record)
    except BaseException:
        preview_record["status"] = "unknown"
        with private_lock(root):
            _write_private_json(path, preview_record)
        raise
    return {
        "status": preview_record["status"],
        "family_id": family_id,
        "operation_id": operation_id,
        "request_limit": request_limit,
        "mandatory_request_reserve": facts["mandatory_request_reserve"],
        "mandatory_reserve_kind": facts["mandatory_reserve_kind"],
        "spatial_quota": facts["spatial_quota"],
        "spatial_quota_kind": facts["spatial_quota_kind"],
        "required_root_limit": facts["required_root_limit"],
        "extra_headroom": facts["extra_headroom"],
        "completion_guaranteed": facts["completion_guaranteed"],
        "total_call_upper_bound": facts["total_call_upper_bound"],
        "total_call_upper_bound_with_connection_verification": facts[
            "total_call_upper_bound_with_connection_verification"
        ],
        "within_root_limit": facts["within_root_limit"],
        "preview_fingerprint": facts["fingerprint"],
        "start_command": (
            f"start-evolution --family-id {family_id} --operation-id {operation_id}"
            if facts["within_root_limit"]
            else None
        ),
        "human_validated": False,
    }


async def start_evolution(
    *,
    private_root: Path,
    family_id: str,
    operation_id: str,
    api_base_url: str,
    execute: bool,
    timeout_seconds: int = 30,
) -> dict:
    """Start only the exact root-inspected preview without changing its cap."""
    explicit_execution(execute)
    _validate_live_api_target(api_base_url, timeout_seconds)
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
    common = read_common_binding(root, family_id)
    if family["split"] == "development":
        require_calibration(root, common)
    preview_path = _evolution_preview_path(root, family_id, operation_id)
    preview_record = _read_private_json(preview_path)
    record_path = _evolution_record_path(root, family_id)
    if (
        record_path.exists()
        or preview_record.get("status") != "previewed"
        or preview_record.get("operation_id") != operation_id
        or preview_record.get("family_id") != family_id
        or preview_record.get("common_binding_sha256") != digest(common)
        or preview_record.get("request_sha256") != digest(preview_record.get("request"))
        or preview_record.get("preview", {}).get("within_root_limit") is not True
        or type(preview_record.get("request", {}).get("request_limit")) is not int
        or type(preview_record.get("preview", {}).get("required_root_limit")) is not int
        or preview_record.get("request", {}).get("request_limit")
        < preview_record.get("preview", {}).get("required_root_limit")
        or preview_record.get("human_validated") is not False
    ):
        raise MapSpatialEvalError("Evolution preview未通过或已占用；不得重发")
    request = preview_record["request"]
    if request != _evolution_request(common, operation_id, request["request_limit"]):
        raise MapSpatialEvalError("Evolution preview请求与共同Scene范围不符")
    from core.database import get_manager

    manager = get_manager()
    async with manager.session() as db:
        await verify_runtime(db, common)
    try:
        async with _product_client(api_base_url, timeout_seconds) as client:
            current_preview = await _post_product_json(
                client,
                f"/api/evolution/reading/preview?novel_id={common['novel_id']}",
                request,
            )
            current_facts = _validate_evolution_preview(current_preview, request)
            if digest(current_preview) != preview_record.get(
                "preview_sha256"
            ) or current_facts != preview_record.get("preview"):
                raise MapSpatialEvalError("Evolution真实preview与root检查版本漂移")
            async with manager.session() as db:
                await verify_runtime(db, common)
            record = {
                **{
                    key: preview_record[key]
                    for key in (
                        "suite",
                        "family_id",
                        "split",
                        "common_binding_sha256",
                        "operation_id",
                        "request",
                        "request_sha256",
                    )
                },
                "preview_fingerprint": current_facts["fingerprint"],
                "preview_sha256": preview_record["preview_sha256"],
                "preview": current_facts,
                "request_limit": request["request_limit"],
                "status": "starting",
                "task_ids": [],
                "tasks_completed": 0,
                "human_validated": False,
            }
            with private_lock(root):
                if record_path.exists():
                    raise MapSpatialEvalError("Evolution操作已启动；不得覆盖或重新授权")
                latest = _read_private_json(preview_path)
                if latest.get("status") != "previewed":
                    raise MapSpatialEvalError("Evolution preview已被占用；不得重发")
                latest["status"] = "starting"
                _write_private_json(preview_path, latest)
                _write_private_json(record_path, record)
            start_payload = {
                **request,
                "expected_fingerprint": current_facts["fingerprint"],
                "authorization_confirmed": True,
            }
            try:
                response = await _post_product_json(
                    client,
                    f"/api/evolution/reading?novel_id={common['novel_id']}",
                    start_payload,
                )
            except BaseException:
                record["status"] = "unknown"
                _write_private_json(record_path, record)
                latest["status"] = "unknown"
                _write_private_json(preview_path, latest)
                raise
    except BaseException:
        current = _read_private_json(record_path) if record_path.exists() else None
        if current is not None and current.get("status") == "starting":
            current["status"] = "unknown"
            _write_private_json(record_path, current)
        raise
    run = response.get("run") or {}
    expected_run_key = f"reading-{operation_id}"
    task_id = str(run.get("task_id") or "")
    if (
        run.get("run_key") != expected_run_key
        or run.get("status") not in {"pending", "running", "needs_budget"}
        or not task_id
        or run.get("total_scenes") != 5
        or run.get("spatial_discovery_enabled") is not True
    ):
        with private_lock(root):
            record["status"] = "unknown"
            record["response_run_key"] = run.get("run_key")
            record["response_task_id"] = task_id or None
            _write_private_json(record_path, record)
            preview_record["status"] = "unknown"
            _write_private_json(preview_path, preview_record)
        raise MapSpatialEvalError("正常Evolution API未返回唯一冻结运行")
    with private_lock(root):
        record.update(
            status="pending",
            run_key=expected_run_key,
            current_task_id=task_id,
            total_scenes=5,
        )
        _write_private_json(record_path, record)
        preview_record["status"] = "started"
        _write_private_json(preview_path, preview_record)
    return {
        "status": "pending",
        "family_id": family_id,
        "run_key": expected_run_key,
        "operation_id": operation_id,
        "request_limit": request["request_limit"],
        "scene_count": 5,
        "mandatory_request_reserve": current_facts["mandatory_request_reserve"],
        "spatial_quota": current_facts["spatial_quota"],
        "extra_headroom": current_facts["extra_headroom"],
        "completion_guaranteed": False,
        "total_call_upper_bound": current_facts["total_call_upper_bound"],
        "total_call_upper_bound_with_connection_verification": current_facts[
            "total_call_upper_bound_with_connection_verification"
        ],
        "first_task_id": task_id,
        "human_validated": False,
    }


async def run_evolution(
    *,
    private_root: Path,
    family_id: str,
    api_base_url: str,
    max_tasks: int,
    execute: bool,
    timeout_seconds: int = 900,
) -> dict:
    """Run only the exact pending Evolution task ids recorded for this run."""
    explicit_execution(execute)
    _validate_live_api_target(api_base_url, min(timeout_seconds, 3600))
    if not 1 <= max_tasks <= 2:
        raise MapSpatialEvalError("单次Evolution最多精确执行2个任务")
    if not 1 <= timeout_seconds <= 900:
        raise MapSpatialEvalError("Evolution task timeout必须在1到900秒")
    root = require_private_directory(private_root)
    common = read_common_binding(root, family_id)
    if common["split"] == "development":
        require_calibration(root, common)
    else:
        require_development_gate(root, load_matrix())
    path = _evolution_record_path(root, family_id)
    record = _read_private_json(path)
    if (
        record.get("status") != "pending"
        or record.get("common_binding_sha256") != digest(common)
        or not record.get("run_key")
        or not record.get("operation_id")
    ):
        raise MapSpatialEvalError("Evolution未处于可精确续跑的pending状态")
    scene_ids = [item["scene_id"] for item in common["case_bindings"].values()]
    from sqlalchemy import select

    from core.database import get_manager
    from infrastructure.tasks.models import AsyncTask
    from modules.evolution.facade import (
        read_map_cold_start_status,
        read_map_spatial_evaluation_receipts,
    )
    from run_worker import _build_task_worker, _configure_worker_process

    _configure_worker_process()
    worker = _build_task_worker()
    manager = get_manager()
    with private_lock(root):
        latest = _read_private_json(path)
        if latest.get("status") != "pending" or latest.get("operation_id") != record.get(
            "operation_id"
        ):
            raise MapSpatialEvalError("Evolution run已被另一个runner占用")
        record["status"] = "running"
        _write_private_json(path, record)
    started_this_call = 0
    try:
        while True:
            async with manager.session() as db:
                await verify_runtime(db, common)
                state = await read_map_cold_start_status(
                    db,
                    common["novel_id"],
                    record["run_key"],
                    record["operation_id"],
                )
                evidence = await read_map_spatial_evaluation_receipts(
                    db,
                    common["novel_id"],
                    record["run_key"],
                    record["operation_id"],
                    scene_ids,
                )
            if state.get("status") == "completed":
                record["status"] = "completed"
                record["completed_scenes"] = state.get("completed_scenes")
                record["current_task_id"] = None
                _write_private_json(path, record)
                return {
                    "status": "completed",
                    "family_id": family_id,
                    "run_key": record["run_key"],
                    "tasks_completed": record["tasks_completed"],
                    "completed_scenes": state.get("completed_scenes"),
                    "request_limit": record["request_limit"],
                    "usage": "unknown",
                    "human_validated": False,
                }
            if state.get("status") not in {"pending", "running"}:
                raise MapSpatialEvalError(
                    "Evolution进入needs_reconciliation/failed/unknown；停止且不重发"
                )
            task_id = str(evidence.get("task_id") or "")
            if not task_id:
                raise MapSpatialEvalError("Evolution没有可验证的下一精确task id")
            if started_this_call >= max_tasks:
                record.update(status="pending", current_task_id=task_id)
                _write_private_json(path, record)
                return {
                    "status": "pending",
                    "family_id": family_id,
                    "run_key": record["run_key"],
                    "tasks_completed": record["tasks_completed"],
                    "next_task_id": task_id,
                    "request_limit": record["request_limit"],
                    "usage": "unknown",
                    "human_validated": False,
                }
            completed = record.get("tasks_completed", 0)
            if completed >= 6:
                raise MapSpatialEvalError("五Scene及一个结构task已耗尽精确Evolution上限")
            if (
                evidence.get("run_key") != record["run_key"]
                or evidence.get("operation_id") != record["operation_id"]
            ):
                raise MapSpatialEvalError("下一task回执不属于原run/operation")
            task_path = _evolution_task_path(
                root, family_id, record["operation_id"], task_id
            )
            async with manager.session() as db:
                task = await db.scalar(
                    select(AsyncTask).where(
                        AsyncTask.id == uuid.UUID(task_id),
                        AsyncTask.novel_id == uuid.UUID(common["novel_id"]),
                    )
                )
                if (
                    task is None
                    or task.task_type != "evolution_scene_step_v2"
                    or task.status != "pending"
                    or task.attempt != 0
                ):
                    raise MapSpatialEvalError(
                        "Evolution worker只能接管同Project的pending且未尝试精确task"
                    )
                meta = task.meta or {}
                if (
                    meta.get("run_key") != record["run_key"]
                    or state.get("completed_scenes") != min(completed, 5)
                    or (completed == 5 and meta.get("operation") != "structure")
                    or (
                        completed < 5
                        and (
                            meta.get("operation") is not None
                            or meta.get("scene_index") != completed
                            or meta.get("scene_id") not in scene_ids
                        )
                    )
                ):
                    raise MapSpatialEvalError(
                        "精确task不是本run的顺序Scene或最终结构阶段"
                    )
                await verify_runtime(db, common)
            task_record = {
                "family_id": family_id,
                "run_key": record["run_key"],
                "operation_id": record["operation_id"],
                "novel_id": common["novel_id"],
                "task_id": task_id,
                "task_type": "evolution_scene_step_v2",
                "status": "started",
                "timeout_seconds": timeout_seconds,
                "human_validated": False,
            }
            with private_lock(root):
                if task_path.exists():
                    raise MapSpatialEvalError("精确Evolution task已经占用；不再次运行")
                _write_private_json(task_path, task_record)
                record["current_task_id"] = task_id
                _write_private_json(path, record)
            started_this_call += 1
            try:
                await asyncio.wait_for(
                    worker.run_once(task_id=task_id, novel_id=common["novel_id"]),
                    timeout=timeout_seconds,
                )
            except BaseException:
                task_record["status"] = "unknown"
                _write_private_json(task_path, task_record)
                record["status"] = "unknown"
                _write_private_json(path, record)
                raise
            async with manager.session() as db:
                saved_task = await db.scalar(
                    select(AsyncTask).where(
                        AsyncTask.id == uuid.UUID(task_id),
                        AsyncTask.novel_id == uuid.UUID(common["novel_id"]),
                    )
                )
                if saved_task is None or saved_task.status != "done":
                    task_record["status"] = "unknown"
                    _write_private_json(task_path, task_record)
                    record["status"] = "unknown"
                    _write_private_json(path, record)
                    raise MapSpatialEvalError("Evolution精确task未完成；不重发")
                task_record.update(
                    status="completed",
                    result_hash=digest(saved_task.result or {}),
                )
                await verify_runtime(db, common)
            _write_private_json(task_path, task_record)
            record["tasks_completed"] += 1
            record["task_ids"] = [*record["task_ids"], task_id]
            record["status"] = "running"
            _write_private_json(path, record)

    except BaseException:
        if record.get("status") == "running":
            record["status"] = "unknown"
            _write_private_json(path, record)
        raise


async def run_assistant_turn(**kwargs) -> dict:
    from evals.map_spatial import map_capability

    with map_capability("assistant.turn", True):
        return await _run_assistant_turn(**kwargs)


async def _run_assistant_turn(
    *,
    private_root: Path,
    family_id: str,
    case_id: str,
    api_base_url: str,
    execute: bool,
    timeout_seconds: int = 900,
) -> dict:
    """Submit one normal Assistant turn and run only its exact pending task."""
    explicit_execution(execute)
    _validate_live_api_target(api_base_url, min(timeout_seconds, 3600))
    if not 1 <= timeout_seconds <= 900:
        raise MapSpatialEvalError("Assistant task timeout必须在1到900秒")
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
    binding = read_binding(root, family_id)
    if family["split"] == "development":
        require_calibration(root, binding)
    record_path = _assistant_record_path(root, family_id, case_id)
    source = _load_family_source(root, family, allow_holdout=family["split"] == "holdout")
    case = _case_for(source, case_id)
    assistant_case = case.get("assistant")
    message = assistant_case.get("request") if isinstance(assistant_case, dict) else None
    scope = binding.get("case_bindings", {}).get(case_id)
    if not isinstance(message, str) or not message.strip() or not scope:
        raise MapSpatialEvalError("Assistant案例缺少冻结请求或Scene绑定")
    if record_path.exists():
        raise MapSpatialEvalError("Assistant回合已启动；不覆盖或重发")
    operation_id = str(uuid.uuid4())
    request = {
        "operation_id": operation_id,
        "novel_id": binding["novel_id"],
        "message": message,
        "context": {
            "page": "map",
            "chapter_index": scope["chapter_index"],
            "scene_id": scope["scene_id"],
            "task_hint": "unknown",
            "scope": "current",
        },
        "allow_web": False,
        "web_backend": None,
    }
    record = {
        "suite": "map_spatial",
        "family_id": family_id,
        "case_id": case_id,
        "split": family["split"],
        "binding_sha256": digest(binding),
        "request_sha256": digest(request),
        "operation_id": operation_id,
        "status": "started",
        "human_validated": False,
    }
    with private_lock(root):
        if record_path.exists():
            raise MapSpatialEvalError("Assistant回合已启动；不覆盖或重发")
        _write_private_json(record_path, record)

    from sqlalchemy import select

    from core.database import get_manager
    from infrastructure.tasks.models import AsyncTask
    from run_worker import _build_task_worker, _configure_worker_process

    manager = get_manager()
    try:
        async with _product_client(api_base_url, timeout_seconds) as client:
            async with manager.session() as db:
                await verify_runtime(db, binding)
            session = await _post_product_json(
                client,
                "/api/assistant/sessions",
                {"novel_id": binding["novel_id"], "title": f"MAP-EVAL:{case_id}"},
            )
            session_id = str(session.get("id") or "")
            if not session_id:
                raise MapSpatialEvalError("正常Assistant API未返回session id")
            record["session_id"] = session_id
            _write_private_json(record_path, record)

            async with manager.session() as db:
                await verify_runtime(db, binding)
            submitted = await _post_product_json(
                client,
                f"/api/assistant/sessions/{session_id}/turns",
                request,
            )
        task_id = str(submitted.get("task_id") or "")
        run_id = str(submitted.get("id") or "")
        if run_id != operation_id or not task_id or submitted.get("status") != "pending":
            raise MapSpatialEvalError("正常Assistant API未返回唯一pending回合")
        task_path = _assistant_task_path(root, family_id, case_id, task_id)
        task_record = {
            "family_id": family_id,
            "case_id": case_id,
            "novel_id": binding["novel_id"],
            "run_id": run_id,
            "task_id": task_id,
            "task_type": "assistant_turn",
            "status": "started",
            "timeout_seconds": timeout_seconds,
            "human_validated": False,
        }
        with private_lock(root):
            if task_path.exists():
                raise MapSpatialEvalError("精确Assistant task账本已占用")
            _write_private_json(task_path, task_record)
            record.update(run_id=run_id, task_id=task_id, status="running")
            _write_private_json(record_path, record)

        async with manager.session() as db:
            task = await db.scalar(
                select(AsyncTask).where(
                    AsyncTask.id == uuid.UUID(task_id),
                    AsyncTask.novel_id == uuid.UUID(binding["novel_id"]),
                )
            )
            meta = task.meta if task is not None and isinstance(task.meta, dict) else {}
            if (
                task is None
                or task.task_type != "assistant_turn"
                or task.status != "pending"
                or task.attempt != 0
                or meta.get("run_id") != run_id
            ):
                raise MapSpatialEvalError(
                    "Assistant worker只能接管同Project、同run且pending未尝试的task"
                )
            await verify_runtime(db, binding)
            task_record["execution_budget"] = task_execution_budget(
                task, binding["project_snapshot"], timeout_seconds
            )
            _write_private_json(task_path, task_record)
        _configure_worker_process()
        worker = _build_task_worker()
        try:
            await asyncio.wait_for(
                worker.run_once(task_id=task_id, novel_id=binding["novel_id"]),
                timeout=timeout_seconds,
            )
        except BaseException:
            task_record["status"] = "unknown"
            _write_private_json(task_path, task_record)
            record["status"] = "unknown"
            _write_private_json(record_path, record)
            raise

        async with manager.session() as db:
            saved_task = await db.scalar(
                select(AsyncTask).where(
                    AsyncTask.id == uuid.UUID(task_id),
                    AsyncTask.novel_id == uuid.UUID(binding["novel_id"]),
                )
            )
            if saved_task is None or saved_task.status != "done":
                task_record["status"] = "unknown"
                _write_private_json(task_path, task_record)
                record["status"] = "unknown"
                _write_private_json(record_path, record)
                raise MapSpatialEvalError("Assistant精确task未完成；不重发")
            task_record.update(
                status="completed", result_hash=digest(saved_task.result or {})
            )
            await verify_runtime(db, binding)
        async with manager.session() as db:
            from modules.assistant.facade import read_map_spatial_evaluation_turn

            evidence = await read_map_spatial_evaluation_turn(
                db, binding["novel_id"], run_id
            )
            if (
                evidence.get("novel_id") != binding["novel_id"]
                or evidence.get("run_id") != run_id
                or evidence.get("task_id") != task_id
                or evidence.get("scene_ids") != [scope["scene_id"]]
                or evidence.get("scene_scope_status") != "known"
            ):
                raise MapSpatialEvalError("Assistant持久回执与冻结Scene/run不符")
            await verify_runtime(db, binding)
        if evidence.get("status") not in {"completed", "waiting_approval"}:
            raise MapSpatialEvalError("Assistant没有可评分的已完成用户回合")
        task_record.update(status="completed", evidence_sha256=digest(evidence))
        _write_private_json(task_path, task_record)
        record.update(
            status="completed",
            evidence_sha256=digest(evidence),
            answer_status=evidence.get("answer_status"),
            tool_invocations_status=evidence.get("tool_invocations_status"),
        )
        _write_private_json(record_path, record)
    except BaseException:
        current = _read_private_json(record_path)
        if current.get("status") not in {"unknown", "completed"}:
            current["status"] = "unknown"
            _write_private_json(record_path, current)
        raise
    return {
        "status": "completed",
        "family_id": family_id,
        "case_id": case_id,
        "run_id": record["run_id"],
        "answer_status": record["answer_status"],
        "tool_invocations_status": record["tool_invocations_status"],
        "human_validated": False,
    }


async def review_map_family(
    *,
    private_root: Path,
    family_id: str,
    api_base_url: str,
    max_actions: int,
    execute: bool,
    timeout_seconds: int = 30,
) -> dict:
    """Apply bounded proxy-author decisions through the normal World APIs."""
    explicit_execution(execute)
    _validate_live_api_target(api_base_url, timeout_seconds)
    if not 1 <= max_actions <= 20:
        raise MapSpatialEvalError("单次代理作者审核最多20个明确决定")
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
    common = read_common_binding(root, family_id)
    if family["split"] == "development":
        require_calibration(root, common)
    evolution_path = _evolution_record_path(root, family_id)
    evolution_record = _read_private_json(evolution_path)
    if evolution_record.get("status") != "completed":
        raise MapSpatialEvalError("先完成本族精确Evolution run，再审核其真实输出")
    path = _review_record_path(root, family_id)
    if path.exists():
        record = _read_private_json(path)
        if record.get("status") != "pending":
            raise MapSpatialEvalError("代理审核已启动且非pending；不得覆盖或重发")
        if record.get("common_binding_sha256") != digest(common):
            raise MapSpatialEvalError("代理审核不属于当前共同基线")
        with private_lock(root):
            latest = _read_private_json(path)
            if latest.get("status") != "pending":
                raise MapSpatialEvalError("代理审核已被另一个runner占用")
            latest["status"] = "running"
            _write_private_json(path, latest)
            record = latest
    else:
        record = {
            "suite": "map_spatial",
            "family_id": family_id,
            "split": family["split"],
            "common_binding_sha256": digest(common),
            "operation_id": evolution_record["operation_id"],
            "run_key": evolution_record["run_key"],
            "status": "started",
            "reviewed_clue_ids": [],
            "adopted_clue_ids": [],
            "rejected_clue_ids": [],
            "map_candidate_reviews": [],
            "review_events": [],
            "review_steps": 0,
            "elapsed_seconds": 0.0,
            "human_validated": False,
        }
        with private_lock(root):
            if path.exists():
                raise MapSpatialEvalError("代理审核已启动；不得覆盖或重发")
            _write_private_json(path, record)
            record["status"] = "running"
            _write_private_json(path, record)

    from core.database import get_manager

    manager = get_manager()
    elapsed_start = time.monotonic()
    action_count = 0
    try:
        async with manager.session() as db:
            await verify_runtime(db, common)
            evidence = await read_evolution_product_evidence(
                db, root, common, evolution_record
            )
        source = _load_family_source(
            root, family, allow_holdout=family["split"] == "holdout"
        )
        source_by_scene = {
            common["case_bindings"][case["case_id"]]["scene_id"]: case["source_excerpt"]
            for case in source["cases"]
        }
        case_by_scene = {
            item["scene_id"]: case_id for case_id, item in common["case_bindings"].items()
        }
        case_order = {
            case["case_id"]: index for index, case in enumerate(source["cases"])
        }
        reviewed = set(record.get("reviewed_clue_ids", []))
        adopted = set(record.get("adopted_clue_ids", []))
        rejected = set(record.get("rejected_clue_ids", []))
        async with _product_client(api_base_url, timeout_seconds) as client:
            for clue in evidence["world"].get("clues", []):
                clue_id = str(clue.get("id") or "")
                if not clue_id or clue_id in reviewed:
                    continue
                if clue.get("status") not in {
                    "pending_review",
                    "pending_verification",
                }:
                    continue
                if action_count >= max_actions:
                    break
                scene_id = clue.get("scene_id")
                quote = (clue.get("clue_payload") or {}).get("quote")
                review_receipt = (clue.get("clue_payload") or {}).get("review") or {}
                modality = (clue.get("clue_payload") or {}).get("modality")
                source_text = source_by_scene.get(scene_id)
                source_valid = (
                    isinstance(source_text, str)
                    and isinstance(quote, str)
                    and bool(quote)
                    and source_text.count(quote) == 1
                    and _source_binding_matches(
                        clue.get("source_binding") or {},
                        common["case_bindings"][
                            next(
                                case_id
                                for case_id, item in common["case_bindings"].items()
                                if item["scene_id"] == scene_id
                            )
                        ]["source_refs"],
                        world_clue=True,
                    )
                )
                action = (
                    "adopt"
                    if clue.get("status") == "pending_review"
                    and source_valid
                    and review_receipt.get("verdict") == "supported"
                    and modality == "event_observed"
                    else "reject"
                )
                async with manager.session() as db:
                    await verify_runtime(db, common)
                decision_started = time.monotonic()
                response = await _post_product_json(
                    client,
                    f"/api/world/map-atlas/{common['novel_id']}/spatial-clues/{clue_id}/review",
                    {
                        "action": action,
                        "expected_fingerprint": clue["fingerprint"],
                        "confirmed": True,
                        "reason": (
                            "MAP-EVAL synthetic proxy author: verified exact Scene "
                            "source and frozen review policy"
                        ),
                    },
                )
                if (
                    response.get("id") != clue_id
                    or response.get("status")
                    != ("adopted" if action == "adopt" else "rejected")
                    or response.get("fingerprint") != clue["fingerprint"]
                ):
                    raise MapSpatialEvalError("World作者审核API回执与请求不符")
                reviewed.add(clue_id)
                (adopted if action == "adopt" else rejected).add(clue_id)
                event = {
                    "kind": "spatial_clue_review",
                    "case_id": case_by_scene[scene_id],
                    "scene_id": scene_id,
                    "clue_id": clue_id,
                    "action": action,
                    "elapsed_seconds": round(
                        max(0.0, time.monotonic() - decision_started), 3
                    ),
                    "status": response.get("status"),
                    "human_validated": False,
                }
                record.setdefault("review_events", []).append(event)
                record.update(
                    reviewed_clue_ids=sorted(reviewed),
                    adopted_clue_ids=sorted(adopted),
                    rejected_clue_ids=sorted(rejected),
                    review_steps=record.get("review_steps", 0) + 1,
                    status="running",
                )
                action_count += 1
                with private_lock(root):
                    _write_private_json(path, record)

            build = record.get("auto_draft_build")
            if not build and action_count < max_actions:
                steps = evidence["receipts"].get("steps", [])
                if not steps:
                    raise MapSpatialEvalError("Evolution没有可冻结的真实Scene范围")
                last = max(steps, key=lambda item: int(item["scene_index"]))
                build_key = f"map-eval-proxy-review-{evolution_record['operation_id']}"
                record["auto_draft_build"] = {"status": "started", "build_key": build_key}
                with private_lock(root):
                    _write_private_json(path, record)
                async with manager.session() as db:
                    await verify_runtime(db, common)
                built = await _post_product_json(
                    client,
                    f"/api/world/map-atlas/{common['novel_id']}/auto-drafts/build",
                    {
                        "run_id": evolution_record["run_key"],
                        "build_key": build_key,
                        "through_scene_id": last["scene_id"],
                        "through_scene_index": last["scene_index"],
                        "clue_ids": None,
                    },
                )
                build = {
                    "status": built.get("status"),
                    "batch_id": built.get("batch_id"),
                    "fingerprint": built.get("fingerprint"),
                    "build_key": build_key,
                    "through_scene_id": last["scene_id"],
                    "through_scene_index": last["scene_index"],
                }
                record["auto_draft_build"] = build
                record["status"] = "running"
                with private_lock(root):
                    _write_private_json(path, record)
            elif (
                build and build.get("status") == "pending" and action_count < max_actions
            ):
                async with manager.session() as db:
                    await verify_runtime(db, common)
                built = await _post_product_json(
                    client,
                    f"/api/world/map-atlas/{common['novel_id']}/auto-drafts/{build['batch_id']}/resume",
                    {"expected_fingerprint": build["fingerprint"], "confirmed": True},
                )
                build = {
                    **build,
                    "status": built.get("status"),
                    "fingerprint": built.get("fingerprint"),
                }
                record["auto_draft_build"] = build
                record["status"] = "running"
                with private_lock(root):
                    _write_private_json(path, record)
            if build and build.get("status") == "running":
                build["status"] = "pending"
                record["auto_draft_build"] = build
                record["status"] = "pending"
                with private_lock(root):
                    _write_private_json(path, record)
                return {
                    "status": "pending",
                    "family_id": family_id,
                    "review_steps": record["review_steps"],
                    "auto_drafts": "pending",
                    "human_validated": False,
                }
            if build and build.get("status") != "completed":
                raise MapSpatialEvalError("World自动草图未完成或回执状态unknown")

            async with manager.session() as db:
                await verify_runtime(db, common)
                from modules.world.facade import read_map_spatial_evaluation_artifacts

                artifacts = await read_map_spatial_evaluation_artifacts(
                    db,
                    common["novel_id"],
                    evolution_record["run_key"],
                    list(source_by_scene),
                )
            candidate_reviews = record.get("map_candidate_reviews", [])
            reviewed_revisions = {
                item.get("revision_id")
                for item in candidate_reviews
                if item.get("revision_id")
            }
            candidates = []
            for batch in artifacts.get("batches", []):
                for ref in batch.get("result_refs", []):
                    if ref.get("status") == "candidate":
                        candidates.append((batch, ref))
            for batch, ref in candidates:
                revision_id = str(ref.get("revision_id") or "")
                if not revision_id or revision_id in reviewed_revisions:
                    continue
                if action_count >= max_actions:
                    break
                node_id = str(ref.get("node_id") or "")
                node = next(
                    (
                        item
                        for item in artifacts.get("nodes", [])
                        if item.get("id") == node_id
                    ),
                    None,
                )
                revision = next(
                    (
                        item
                        for item in artifacts.get("revisions", [])
                        if item.get("id") == revision_id
                    ),
                    None,
                )
                if not node_id or not revision:
                    raise MapSpatialEvalError("World候选缺少实际node/revision文档")
                base_id = revision.get("base_revision_id")
                source_clue_ids = set(ref.get("source_clue_ids") or [])
                warnings = next(
                    (
                        item.get("warnings", [])
                        for item in artifacts.get("drafts", [])
                        if item.get("revision_id") == revision_id
                    ),
                    [],
                )
                may_adopt = (
                    node.get("status") in {"provisional", "adopted"}
                    and bool(source_clue_ids)
                    and source_clue_ids <= adopted
                    and not warnings
                )
                action = "adopt" if may_adopt else "reject"
                source_scene_ids = sorted(
                    {
                        clue.get("scene_id")
                        for clue in artifacts.get("clues", [])
                        if clue.get("id") in source_clue_ids
                        and clue.get("scene_id") in case_by_scene
                    },
                    key=lambda scene_id: case_order[case_by_scene[scene_id]],
                )
                if not source_scene_ids:
                    raise MapSpatialEvalError("地图候选没有可追溯到共同Scene的线索来源")
                decision_case_id = case_by_scene[source_scene_ids[0]]
                decision_started = time.monotonic()
                async with manager.session() as db:
                    await verify_runtime(db, common)
                if action == "adopt":
                    preview = await _post_product_json(
                        client,
                        f"/api/world/map-atlas/{common['novel_id']}/nodes/{node_id}/revisions/{revision_id}/review-preview",
                        {"base_revision_id": base_id, "action": "adopt"},
                    )
                    keys = preview.get("applied_change_keys")
                    if (
                        preview.get("candidate_revision_id") != revision_id
                        or preview.get("base_revision_id") != base_id
                        or preview.get("candidate_locations_truncated") is True
                        or not isinstance(keys, list)
                    ):
                        raise MapSpatialEvalError("World候选审核预览与实际修订不符")
                    promoted_now = False
                    for location in preview.get("candidate_locations", []):
                        entity_id = str(location.get("entity_id") or "")
                        endpoint = f"/api/world/entities/{entity_id}/promote"
                        if location.get("can_adopt") is not True:
                            continue
                        if (
                            location.get("promotion_endpoint") != endpoint
                            or not location.get("source_hash")
                            or not location.get("name")
                            or not any(
                                location["name"] in source_by_scene[scene_id]
                                for scene_id in source_scene_ids
                            )
                        ):
                            raise MapSpatialEvalError(
                                "代理作者采用地点缺少同Scene原文与正式来源预览"
                            )
                        if action_count >= max_actions:
                            break
                        async with manager.session() as db:
                            await verify_runtime(db, common)
                        promotion_started = time.monotonic()
                        promoted = await _post_product_json(
                            client,
                            f"{endpoint}?novel_id={common['novel_id']}",
                            {"expected_source_hash": location["source_hash"]},
                        )
                        if (
                            promoted.get("entity_id") != entity_id
                            or promoted.get("status") != "canonical"
                        ):
                            raise MapSpatialEvalError(
                                "原World promote未返回同地点的canonical回执"
                            )
                        record.setdefault("review_events", []).append(
                            {
                                "kind": "world_location_promote",
                                "case_id": decision_case_id,
                                "scene_id": source_scene_ids[0],
                                "entity_id": entity_id,
                                "source_hash": location["source_hash"],
                                "response_sha256": digest(promoted),
                                "elapsed_seconds": round(
                                    max(0.0, time.monotonic() - promotion_started), 3
                                ),
                                "human_validated": False,
                            }
                        )
                        record["review_steps"] += 1
                        record.setdefault("promoted_entity_ids", []).append(entity_id)
                        action_count += 1
                        promoted_now = True
                        _write_private_json(path, record)
                    if action_count >= max_actions:
                        break
                    if promoted_now:
                        # World adoption and map adoption are separate author decisions.
                        preview = await _post_product_json(
                            client,
                            f"/api/world/map-atlas/{common['novel_id']}/nodes/{node_id}/revisions/{revision_id}/review-preview",
                            {"base_revision_id": base_id, "action": "adopt"},
                        )
                        if (
                            preview.get("candidate_revision_id") != revision_id
                            or preview.get("base_revision_id") != base_id
                            or preview.get("candidate_locations_truncated") is True
                        ):
                            raise MapSpatialEvalError("地点采用后地图CAS预览漂移")
                        keys = preview.get("applied_change_keys")
                        if not isinstance(keys, list):
                            raise MapSpatialEvalError("地点采用后缺少独立地图审核keys")
                    decision_started = time.monotonic()
                    if not keys:
                        action = "reject"
                    else:
                        async with manager.session() as db:
                            await verify_runtime(db, common)
                        adopted_revision = await _post_product_json(
                            client,
                            f"/api/world/map-atlas/{common['novel_id']}/nodes/{node_id}/revisions/{revision_id}/review",
                            {
                                "base_revision_id": base_id,
                                "action": "adopt",
                                "change_keys": keys,
                            },
                        )
                        if adopted_revision.get("status") != "saved":
                            raise MapSpatialEvalError("World地图版本审核未保存真实head")
                if action == "reject":
                    async with manager.session() as db:
                        await verify_runtime(db, common)
                    adopted_revision = await _post_product_json(
                        client,
                        f"/api/world/map-atlas/{common['novel_id']}/nodes/{node_id}/revisions/{revision_id}/review",
                        {"base_revision_id": base_id, "action": "reject"},
                    )
                    if adopted_revision.get("status") != "rejected":
                        raise MapSpatialEvalError("World候选拒绝回执与请求不符")
                candidate_reviews.append(
                    {
                        "batch_id": batch.get("id"),
                        "node_id": node_id,
                        "revision_id": revision_id,
                        "source_clue_ids": sorted(source_clue_ids),
                        "scene_ids": source_scene_ids,
                        "action": action,
                        "status": adopted_revision.get("status"),
                        "response_sha256": digest(adopted_revision),
                        "human_validated": False,
                    }
                )
                reviewed_revisions.add(revision_id)
                record.setdefault("review_events", []).append(
                    {
                        "kind": "map_revision_review",
                        "case_id": decision_case_id,
                        "scene_id": source_scene_ids[0],
                        "scene_ids": source_scene_ids,
                        "revision_id": revision_id,
                        "action": action,
                        "elapsed_seconds": round(
                            max(0.0, time.monotonic() - decision_started), 3
                        ),
                        "status": adopted_revision.get("status"),
                        "human_validated": False,
                    }
                )
                record["map_candidate_reviews"] = candidate_reviews
                record["review_steps"] = record.get("review_steps", 0) + 1
                record["status"] = "running"
                action_count += 1
                with private_lock(root):
                    _write_private_json(path, record)

        remaining_clues = [
            clue
            for clue in evidence["world"].get("clues", [])
            if clue.get("status") in {"pending_review", "pending_verification"}
            and clue.get("id") not in reviewed
        ]
        remaining_revisions = [
            ref.get("revision_id")
            for batch in artifacts.get("batches", [])
            for ref in batch.get("result_refs", [])
            if ref.get("status") == "candidate"
            and ref.get("revision_id") not in reviewed_revisions
        ]
        record["elapsed_seconds"] = round(
            float(record.get("elapsed_seconds", 0.0))
            + max(0.0, time.monotonic() - elapsed_start),
            3,
        )
        record["status"] = (
            "pending" if remaining_clues or remaining_revisions else "completed"
        )
        record["unreviewed_clue_ids"] = [item.get("id") for item in remaining_clues]
        record["unreviewed_revision_ids"] = remaining_revisions
        record["auto_draft_build"] = build
        with private_lock(root):
            _write_private_json(path, record)
    except BaseException:
        current = _read_private_json(path)
        if current.get("status") not in {"unknown", "completed"}:
            current["status"] = "unknown"
            current["elapsed_seconds"] = round(
                float(current.get("elapsed_seconds", 0.0))
                + max(0.0, time.monotonic() - elapsed_start),
                3,
            )
            _write_private_json(path, current)
        raise
    return {
        "status": record["status"],
        "family_id": family_id,
        "review_steps": record["review_steps"],
        "unreviewed_clues": len(record.get("unreviewed_clue_ids", [])),
        "unreviewed_revisions": len(record.get("unreviewed_revision_ids", [])),
        "elapsed_seconds": record["elapsed_seconds"],
        "human_validated": False,
    }


async def freeze_common_binding(
    *, private_root: Path, family_id: str, execute: bool
) -> dict:
    """Freeze the common empty-map source baseline before seeded calibration."""
    explicit_execution(execute)
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
        verify_materials(root, matrix)
    source = _load_family_source(root, family, allow_holdout=family["split"] == "holdout")
    setup, requested = _validated_setup(root, family, source)
    cases = {}
    for case in source["cases"]:
        case_id = case["case_id"]
        cases[case_id] = await preflight_common_project(
            private_root=root,
            family=family,
            source_excerpt=case["source_excerpt"],
            **requested[case_id],
        )
    shared_fields = (
        "novel_id",
        "owner_id",
        "database_target",
        "manifest_sha256",
        "rubric_sha256",
        "source_sha256",
        "expected_sha256",
        "project_snapshot",
        "project_snapshot_hash",
        "runtime_limits",
        "vocabulary_snapshot",
        "vocabulary_snapshot_hash",
        "pipeline_hash",
        "domain_method_fingerprints",
        "private_root_sha256",
    )
    common = {key: cases[next(iter(cases))][key] for key in shared_fields}
    if any(
        {key: value[key] for key in shared_fields} != common for value in cases.values()
    ):
        raise MapSpatialEvalError("案例间owner、Project snapshot或方法版本漂移")
    if any(
        (value["map_revision_count"], bool(value.get("map_snapshot_hash"))) != (0, True)
        for value in cases.values()
    ):
        raise MapSpatialEvalError("共同基线必须证明五个Scene均来自空地图")
    common.update(
        schema_version=1,
        stage="common_source_scene_baseline",
        suite="map_spatial",
        family_id=family_id,
        genre=family["genre"],
        split=family["split"],
        setup_record_sha256=_sha256_file(_setup_record_path(root, family_id)),
        scopes_sha256=setup["scopes_sha256"],
        case_bindings=cases,
        human_validated=False,
        frozen_at=datetime.now(UTC).isoformat(),
    )
    path = common_binding_path(root, family_id)
    with private_lock(root):
        if path.exists():
            raise MapSpatialEvalError("共同基线已冻结，不能覆盖或复用")
        _write_private_json(path, common)
    return {
        "status": "frozen",
        "family_id": family_id,
        "cases": 5,
        "stage": common["stage"],
        "human_validated": False,
    }


async def freeze_binding(
    *, private_root: Path, family_id: str, scopes: Path, execute: bool
) -> dict:
    """Freeze the post-review map head for the paired Writing stage."""
    explicit_execution(execute)
    root = require_private_directory(private_root)
    matrix = load_matrix()
    family = _family_for(matrix, family_id)
    if family["split"] == "holdout":
        require_development_gate(root, matrix)
    verify_materials(root, matrix)
    expected_scopes_path = _scope_path(root, family_id)
    if scopes.resolve() != expected_scopes_path.resolve():
        raise MapSpatialEvalError("最终绑定只能使用正常产品setup生成的scope清单")
    source = _load_family_source(root, family, allow_holdout=family["split"] == "holdout")
    setup, requested = _validated_setup(root, family, source)
    common = read_common_binding(root, family_id)
    if family["split"] == "development":
        require_calibration(root, common)
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
        baseline = common["case_bindings"][case_id]
        if not same_source_baseline(cases[case_id], baseline):
            raise MapSpatialEvalError(
                f"冷启动期间共同Project/Scene来源发生漂移: {case_id}"
            )
        for key in (
            "source_sha256",
            "expected_sha256",
            "pipeline_hash",
            "domain_method_fingerprints",
        ):
            if cases[case_id].get(key) != baseline.get(key):
                raise MapSpatialEvalError(
                    f"冷启动期间资料或方法版本发生漂移: {case_id}/{key}"
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
        "source_refs",
        "map_revision_count",
        "map_brief_eligibility",
    )
    case_globals = {
        key: value
        for key, value in next(iter(cases.values())).items()
        if key not in shared
    }
    if any(
        {key: value for key, value in case.items() if key not in shared} != case_globals
        for case in cases.values()
    ):
        raise MapSpatialEvalError("案例间项目或冻结版本漂移")
    from evals.map_spatial_guard import writing_eligibility_path

    unavailable = {
        case_id: case["map_brief_eligibility"]
        for case_id, case in cases.items()
        if case.get("map_brief_eligibility", {}).get("status") == "unavailable"
    }
    if unavailable:
        report = {
            "family_id": family_id,
            "status": "not_run",
            "reason": "map_brief_unavailable",
            "common_binding_sha256": digest(common),
            "pipeline_hash": common["pipeline_hash"],
            "cases": {
                case_id: {
                    **{
                        key: case[key]
                        for key in (
                            "scene_id",
                            "scene_hash",
                            "source_snapshot_hash",
                            "map_snapshot_hash",
                            "map_revision_count",
                        )
                    },
                    **case["map_brief_eligibility"],
                    "writing_pair_status": "not_run",
                    "reason": case["map_brief_eligibility"]["reason"]
                    or "family_binding_unavailable",
                }
                for case_id, case in cases.items()
            },
            "human_validated": False,
        }
        with private_lock(root):
            path = writing_eligibility_path(root, family_id)
            if path.exists() or binding_path(root, family_id).exists():
                raise MapSpatialEvalError("配对绑定或eligibility诊断已冻结，不能覆盖")
            _write_private_json(path, report)
        return report
    binding = {
        **{key: value for key, value in common.items() if key != "case_bindings"},
        **case_globals,
    }
    binding.update(
        schema_version=1,
        stage="reviewed_map_head",
        common_binding_sha256=digest(common),
        setup_record_sha256=_sha256_file(_setup_record_path(root, family_id)),
        scopes_sha256=setup["scopes_sha256"],
        case_bindings=cases,
        map_heads_sha256=digest(
            {
                case_id: {
                    "map_snapshot_hash": case["map_snapshot_hash"],
                    "map_revision_count": case["map_revision_count"],
                }
                for case_id, case in cases.items()
            }
        ),
        human_validated=False,
        frozen_at=datetime.now(UTC).isoformat(),
    )
    binding["case_bindings"] = cases
    with private_lock(root):
        path = binding_path(root, family_id)
        if path.exists() or writing_eligibility_path(root, family_id).exists():
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
    if phase == "teacher_calibration":
        binding = read_common_binding(root, family_id)
    else:
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
                frozen_evidence_path = evidence_path(root, binding, case_id)
                with private_lock(root):
                    if frozen_evidence_path.exists():
                        raise MapSpatialEvalError("案例产品证据已冻结；不能重评或替换")
                    _write_private_json(frozen_evidence_path, evidence)
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
        if actual.get("status") != "passed" or actual.get("passed") is not True:
            raise MapSpatialEvalError("开发gate未通过；留出资料保持不可用")
        path = _gate_path(root)
        if path.exists():
            raise MapSpatialEvalError("开发gate已冻结，不能覆盖")
        _write_private_json(path, actual)
    return {"status": "completed", "genres": 5, "human_validated": False}

"""One optional, explicit synthetic-author Scene-location step; no model calls."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from evals.map_spatial import (
    MapSpatialEvalError,
    _as_plain,
    _read_private_json,
    _sha256_file,
    _write_private_json,
    require_private_directory,
)
from evals.map_spatial_guard import (
    binding_path,
    digest,
    private_lock,
    private_ref,
    read_common_binding,
    require_calibration,
    require_development_gate,
    verify_runtime,
    writing_eligibility_path,
)


class LocationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: str
    novel_id: UUID
    scene_id: UUID
    current_scene_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_refs: list[dict] = Field(min_length=1, max_length=1)
    source_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    location_entity_id: UUID
    node_id: UUID
    revision_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class LocationDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    origin: Literal["agent_simulated"]
    human_validated: Literal[False]
    family_id: str
    decisions: list[LocationDecision] = Field(min_length=5, max_length=5)


def ledger_path(root: Path, family_id: str) -> Path:
    return private_ref(root, f"author-scene-locations/{family_id}.json")


def _manifest(root: Path, path: Path, expected: str) -> tuple[dict, str]:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as error:
        raise MapSpatialEvalError("作者决定必须留在本次private-root") from error
    path = private_ref(root, str(relative))
    if not path.is_file() or path.stat().st_mode & 0o777 != 0o600:
        raise MapSpatialEvalError("作者决定必须是private-root内0600普通JSON文件")
    value = _read_private_json(path)
    if value.get("human_validated") is not False:
        raise MapSpatialEvalError("模拟代理作者决定不能标为人类验证")
    try:
        LocationDecisions.model_validate(value)
    except ValueError as error:
        raise MapSpatialEvalError(
            "作者决定必须显式提供五case的完整稳定UUID决定"
        ) from error
    if digest(value) != expected:
        raise MapSpatialEvalError("作者决定canonical digest已漂移")
    return value, str(path.relative_to(root))


def author_binding(root: Path, common: dict, cases: dict) -> dict | None:
    """Pin this optional condition; the ordinary no-manifest path is unchanged."""
    path = ledger_path(root, common["family_id"])
    if not path.exists():
        return None
    record = _read_private_json(path)
    manifest, _ = _manifest(
        root, private_ref(root, record["manifest_path"]), record["manifest_sha256"]
    )
    if (
        record.get("status") != "completed"
        or record.get("origin") != "agent_simulated"
        or record.get("input_kind") != "author_added_scene_setting"
        or record.get("human_validated") is not False
        or record.get("patch_attempt_count") != 5
        or record.get("common_binding_sha256") != digest(common)
        or record.get("manifest_file_sha256")
        != _sha256_file(private_ref(root, record["manifest_path"]))
        or manifest["family_id"] != common["family_id"]
        or set(record.get("cases", {})) != set(cases)
    ):
        raise MapSpatialEvalError("模拟作者输入未完成或冻结hash已漂移")
    for case_id, case in cases.items():
        result = record["cases"][case_id]
        if (
            result.get("status") != "completed"
            or result.get("scene_contract_hash") != case.get("scene_hash")
            or result.get("source_snapshot_hash") != case.get("source_snapshot_hash")
            or result.get("brief_sha256") != case.get("map_snapshot_hash")
            or {"node_id": result["node_id"], "revision_id": result["revision_id"]}
            not in case.get("map_source_refs", [])
        ):
            raise MapSpatialEvalError("模拟作者Scene或所消费地图node/head已漂移")
    return {
        "condition": "author_assisted",
        "input_kind": "author_added_scene_setting",
        "origin": "agent_simulated",
        "human_validated": False,
        "manifest_sha256": record["manifest_sha256"],
        "manifest_file_sha256": record["manifest_file_sha256"],
        "ledger_sha256": _sha256_file(path),
        "extra_author_decisions": 5,
        "patch_attempt_count": record["patch_attempt_count"],
        "elapsed_seconds": record["elapsed_seconds"],
        "model_requests": 0,
    }


async def _json(client, method, path, payload=None):
    response = await asyncio.wait_for(
        client.request(
            method, path, **({"json": payload} if payload is not None else {})
        ),
        timeout=30,
    )
    if response.status_code not in {200, 201}:
        raise MapSpatialEvalError(f"作者设定API拒绝: {method} HTTP{response.status_code}")
    return response.json()


def _scene_response(value):
    # SQLite round-trips UTC timestamps as naive; compare instants, not JSON spelling.
    result = dict(value)
    for key in ("updated_at",):
        if result.get(key):
            instant = datetime.fromisoformat(result[key].replace("Z", "+00:00"))
            result[key] = (
                instant if instant.tzinfo else instant.replace(tzinfo=UTC)
            ).astimezone(UTC)
    return result


async def _idle(client, common, evolution):
    novel_id = common["novel_id"]
    reading = await _json(client, "GET", f"/api/evolution/reading?novel_id={novel_id}")
    run = reading.get("run") or {}
    if (
        run.get("run_key") != evolution["run_key"]
        or run.get("status") != "completed"
        or run.get("completed_scenes") != 5
        or run.get("total_scenes") != 5
        or run.get("preparing_structure") is not False
    ):
        raise MapSpatialEvalError("作者地点选择要求真实五Scene及结构阶段完整完成")
    tasks = await _json(client, "GET", f"/api/tasks?novel_id={novel_id}")
    if tasks.get("active_count", 50) >= 50 or any(
        item.get("status") in {"running", "unknown"}
        or (item.get("status") != "done" and item.get("attempt", 0) > 0)
        or (
            item.get("status") == "pending"
            and (
                item.get("task_type") not in {"publish_chapter", "rag_index_chapter"}
                or item.get("attempt") != 0
            )
        )
        for item in tasks.get("items", [])
    ):
        raise MapSpatialEvalError("存在其他写者或未核清任务，禁止替换Scene metadata")
    return {
        "reading_sha256": digest(reading),
        "tasks_sha256": digest(tasks),
        "deferred_index_tasks": [
            {key: item[key] for key in ("id", "task_type", "status", "attempt")}
            for item in tasks.get("items", [])
            if item.get("status") == "pending"
            and item.get("task_type") in {"publish_chapter", "rag_index_chapter"}
        ],
    }


async def _source_and_contract(common, decision):
    from core.database import get_manager
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import read_novel_evidence
    from modules.story.facade import get_scene_contract, get_scene_spans_for_scene
    from modules.writing.facade import build_manuscript_range_ref

    case = common["case_bindings"][decision["case_id"]]
    async with get_manager().session() as db:
        await verify_runtime(db, common)
        spans = await get_scene_spans_for_scene(
            db, common["novel_id"], decision["scene_id"], content_mode="canonical"
        )
        refs = []
        for span in spans:
            value = _as_plain(span)
            if value.get("mapping_status") not in {"exact", "reanchored"}:
                raise MapSpatialEvalError("Scene来源区间已失效")
            ref = await build_manuscript_range_ref(
                db,
                common["novel_id"],
                draft_id=value["source_draft_id"],
                start_offset=value["start_offset"],
                end_offset=value["end_offset"],
                content_mode="canonical",
            )
            if ref.source_hash != value.get("source_content_hash"):
                raise MapSpatialEvalError("Scene来源稿版本已漂移")
            evidence = await read_novel_evidence(
                db,
                novel_id=common["novel_id"],
                source_ref=ref,
                visibility=VisibilityContextContract(
                    mode="reader",
                    cutoff_chapter=case["chapter_index"],
                    cutoff_scene_id=case["scene_id"],
                ),
                before=0,
                after=0,
            )
            if (evidence.get("visibility_decision") or {}).get("visible") is not True:
                raise MapSpatialEvalError("Scene精确来源不可见")
            refs.append(_as_plain(ref))
        if refs != case["source_refs"] or digest(refs) != case["source_snapshot_hash"]:
            raise MapSpatialEvalError("Scene当前canonical精确来源已漂移")
        scene = await get_scene_contract(db, common["novel_id"], case["scene_id"])
        await db.rollback()
        return digest(_as_plain(scene))


def _nodes(nodes):
    for node in nodes:
        yield node
        yield from _nodes(node.get("children", []))


async def _location(client, common, decision, review):
    novel_id, entity_id = common["novel_id"], decision["location_entity_id"]
    entity = await _json(
        client, "GET", f"/api/world/entities/{entity_id}?novel_id={novel_id}"
    )
    if any(
        entity.get(key) != value
        for key, value in {
            "id": entity_id,
            "novel_id": novel_id,
            "entity_type": "location",
            "status": "canonical",
        }.items()
    ):
        raise MapSpatialEvalError("显式地点UUID不是本作品canonical location")
    atlas = await _json(client, "GET", f"/api/world/map-atlas/{novel_id}/atlas")
    node = next(
        (
            item
            for item in _nodes(atlas.get("nodes", []))
            if item["id"] == decision["node_id"]
        ),
        {},
    )
    if (
        node.get("novel_id") != novel_id
        or node.get("status") != "adopted"
        or node.get("merged_into_node_id")
        or node.get("current_revision_id") != decision["revision_id"]
    ):
        raise MapSpatialEvalError("决定必须指向本作品未合并的adopted地图head")
    saved = await _json(
        client, "GET", f"/api/world/map-atlas/{novel_id}/nodes/{decision['node_id']}/map"
    )
    revision = saved.get("revision") or {}
    if (
        revision.get("status") != "saved"
        or revision.get("id") != decision["revision_id"]
        or revision.get("node_id") != decision["node_id"]
        or not any(
            item.get("node_id") == decision["node_id"]
            and item.get("saved_revision_id") == decision["revision_id"]
            and item.get("status") == "saved"
            and item.get("action") == "adopt"
            for item in review.get("map_candidate_reviews", [])
        )
    ):
        raise MapSpatialEvalError("地点决定缺少同node/revision的真实地图采用回执")
    if node.get("location_entity_id") != entity_id and not any(
        item.get("entity_id") == entity_id
        for item in revision.get("document", {}).get("features", [])
    ):
        raise MapSpatialEvalError("所选UUID不在实际地图head，不能按同名/标签猜身份")
    return {
        "entity_sha256": digest(entity),
        "map_sha256": digest(saved),
        "node_location_matches": node.get("location_entity_id") == entity_id,
    }


async def apply_scene_locations(
    *,
    private_root: Path,
    family_id: str,
    decisions: Path,
    manifest_sha256: str,
    execute: bool,
    api_base_url: str = "http://map-spatial-eval.internal",
    timeout_seconds: int = 30,
):
    from evals.map_spatial_control import (
        _evolution_record_path,
        _product_client,
        _review_record_path,
        _validate_live_api_target,
        explicit_execution,
    )

    explicit_execution(execute)
    _validate_live_api_target(api_base_url, timeout_seconds)
    root = require_private_directory(private_root)
    common = read_common_binding(root, family_id)
    if common["split"] == "holdout":
        from evals.map_spatial import load_matrix

        require_development_gate(root, load_matrix())
    else:
        require_calibration(root, common)
    manifest, relative = _manifest(root, decisions, manifest_sha256)
    choices = {item["case_id"]: item for item in manifest["decisions"]}
    if manifest["family_id"] != family_id or set(choices) != set(common["case_bindings"]):
        raise MapSpatialEvalError("作者决定必须恰好覆盖同common的五case，不得虚构缺例")
    for case_id, choice in choices.items():
        case = common["case_bindings"][case_id]
        if any(
            choice.get(key) != case.get(key)
            for key in ("novel_id", "scene_id", "source_refs", "source_snapshot_hash")
        ):
            raise MapSpatialEvalError("作者决定与共同Scene/Project/精确source不符")
    evolution = _read_private_json(_evolution_record_path(root, family_id))
    review = _read_private_json(_review_record_path(root, family_id))
    if (
        evolution.get("status") != "completed"
        or review.get("status") != "completed"
        or review.get("common_binding_sha256") != digest(common)
        or review.get("run_key") != evolution.get("run_key")
        or review.get("operation_id") != evolution.get("operation_id")
    ):
        raise MapSpatialEvalError("先完成原Evolution及World/地图作者审核")
    record = {
        "status": "started",
        "origin": "agent_simulated",
        "input_kind": "author_added_scene_setting",
        "human_validated": False,
        "common_binding_sha256": digest(common),
        "manifest_path": relative,
        "manifest_sha256": manifest_sha256,
        "manifest_file_sha256": _sha256_file(decisions),
        "cases": {},
        "patch_attempt_count": 0,
        "elapsed_seconds": 0.0,
        "model_requests": 0,
        "atomic_cas": False,
    }
    path = ledger_path(root, family_id)
    with private_lock(root):
        if (
            path.exists()
            or binding_path(root, family_id).exists()
            or writing_eligibility_path(root, family_id).exists()
        ):
            raise MapSpatialEvalError("作者决定已占用或配对已冻结；不得覆盖/重发")
        _write_private_json(path, record)
    started = time.monotonic()
    try:
        async with _product_client(api_base_url, timeout_seconds) as client:
            for case_id, choice in choices.items():
                _manifest(root, decisions, manifest_sha256)
                if _sha256_file(decisions) != record["manifest_file_sha256"]:
                    raise MapSpatialEvalError("作者决定原文件在执行期间已漂移")
                observation = await _idle(client, common, evolution)
                await _source_and_contract(common, choice)
                proof = await _location(client, common, choice, review)
                route = (
                    f"/api/outline/scenes/{choice['scene_id']}"
                    f"?novel_id={common['novel_id']}"
                )
                before = await _json(client, "GET", route)
                if (
                    digest(before) != choice["current_scene_hash"]
                    or before.get("id") != choice["scene_id"]
                    or before.get("novel_id") != common["novel_id"]
                    or before.get("status") != "canonical"
                ):
                    raise MapSpatialEvalError("完整current Scene hash已漂移")
                metadata = before.get("structure_meta") or {}
                if metadata.get("location_id") or metadata.get("location_entity_id"):
                    raise MapSpatialEvalError("Scene已有地点，不得覆盖任一location key")
                payload = {
                    "structure_meta": {
                        **metadata,
                        "location_entity_id": choice["location_entity_id"],
                    }
                }
                event = {
                    "status": "started",
                    "before": before,
                    "before_scene_hash": digest(before),
                    "request": payload,
                    "request_sha256": digest(payload),
                    **proof,
                    **observation,
                    "node_id": choice["node_id"],
                    "revision_id": choice["revision_id"],
                    "source_snapshot_hash": choice["source_snapshot_hash"],
                }
                record["cases"][case_id] = event
                record["patch_attempt_count"] += 1
                _write_private_json(path, record)
                changed = time.monotonic()
                event["response"] = await _json(client, "PATCH", route, payload)
                event["response_sha256"] = digest(event["response"])
                _write_private_json(path, record)
                after = await _json(client, "GET", route)
                event.update(
                    after=after,
                    after_scene_hash=digest(after),
                    elapsed_seconds=round(time.monotonic() - changed, 3),
                )
                if after != {
                    **before,
                    "structure_meta": payload["structure_meta"],
                    "updated_at": after.get("updated_at"),
                } or _scene_response(event["response"]) != _scene_response(after):
                    raise MapSpatialEvalError(
                        "Scene PATCH出现非目标metadata/source变化；无CAS保证，停止"
                    )
                event["scene_contract_hash"] = await _source_and_contract(common, choice)
                from core.database import get_manager
                from modules.world.contracts import MapSpatialBriefRequest
                from modules.world.facade import read_map_spatial_brief

                async with get_manager().session() as db:
                    await verify_runtime(db, common)
                    brief = _as_plain(
                        await read_map_spatial_brief(
                            db,
                            MapSpatialBriefRequest(
                                novel_id=common["novel_id"],
                                scene_id=choice["scene_id"],
                                chapter_index=common["case_bindings"][case_id][
                                    "chapter_index"
                                ],
                                reveal_mode="author_safe",
                            ),
                        )
                    )
                    await db.rollback()
                focused = False
                for item in brief["items"]:
                    if (item["node_id"], item["revision_id"]) != (
                        choice["node_id"],
                        choice["revision_id"],
                    ):
                        continue
                    locations = json.loads(item["content"]).get("当前地点", [])
                    focused = any(
                        location.get("entity_id") == choice["location_entity_id"]
                        for location in locations
                    ) or bool(
                        proof["node_location_matches"]
                        and locations
                        and all("entity_id" not in location for location in locations)
                    )
                    if focused:
                        break
                if not focused:
                    raise MapSpatialEvalError(
                        "模拟作者所选地点UUID未进入同node/head Brief当前地点"
                    )
                event.update(status="completed", brief_sha256=digest(brief))
                _write_private_json(path, record)
        record["status"] = "completed"
    except BaseException:
        record["status"] = "unknown"
        raise
    finally:
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _write_private_json(path, record)
    return {
        "status": "completed",
        "condition": "author_assisted",
        "input_kind": "author_added_scene_setting",
        "origin": "agent_simulated",
        "human_validated": False,
        "patch_attempt_count": record["patch_attempt_count"],
        "model_requests": 0,
        "atomic_cas": False,
        "manifest_sha256": manifest_sha256,
        "ledger_sha256": _sha256_file(path),
    }

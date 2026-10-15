"""Private-material, single-use map spatial evaluation preparation and runner."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = Path(__file__).resolve().parent / "datasets" / "map_spatial" / "matrix.json"
DEFAULT_PRIVATE_ROOT = (
    Path.home() / ".codex" / "private" / "map-spatial-evaluation-20261015"
)
ALLOWED_GENRES = ("xianxia", "fantasy", "urban", "science_fiction", "mystery")
ALLOWED_SPLITS = ("development", "holdout")
LIVE_ENV = "MAP_SPATIAL_EVAL_ALLOW_LIVE"
DATABASE_NAME = "map_spatial_eval_20261015"
PROJECT_GENRES = {
    "xianxia": "修仙",
    "fantasy": "西幻",
    "urban": "都市",
    "science_fiction": "科幻",
    "mystery": "悬疑",
}


class MapSpatialEvalError(RuntimeError):
    """Raised when a frozen dataset or isolated run violates its contract."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_in_repository(path: Path) -> bool:
    resolved = path.resolve()
    if resolved == REPO_ROOT or resolved.is_relative_to(REPO_ROOT):
        return True
    return any((parent / ".git").exists() for parent in (resolved, *resolved.parents))


def require_private_directory(path: Path, *, create: bool = False) -> Path:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise MapSpatialEvalError("私有评测目录禁止符号链接")
    if _is_in_repository(path):
        raise MapSpatialEvalError("原始评测资料与账本必须位于仓库外")
    if create and not path.exists():
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
            parent_fd = os.open(directory.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    if not path.is_dir():
        raise MapSpatialEvalError("私有评测目录不存在")
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise MapSpatialEvalError("私有评测目录权限必须为0700")
    return path.resolve()


def _read_private_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise MapSpatialEvalError("私有评测材料缺失或不是普通文件")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise MapSpatialEvalError("私有评测材料文件权限必须为0600")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MapSpatialEvalError("私有评测材料无法读取") from exc
    if not isinstance(payload, dict):
        raise MapSpatialEvalError("私有评测材料顶层必须是对象")
    return payload


def load_matrix(path: Path | None = None) -> dict[str, Any]:
    matrix = json.loads((path or MATRIX_PATH).read_text(encoding="utf-8"))
    if matrix.get("suite") != "map_spatial" or matrix.get("schema_version") != 2:
        raise MapSpatialEvalError("地图评测矩阵版本不受支持")
    families = matrix.get("families")
    if not isinstance(families, list) or len(families) != 10:
        raise MapSpatialEvalError("矩阵必须含五题材各一开发族和一次性留出族")
    identifiers = [row.get("family_id") for row in families]
    if len(identifiers) != len(set(identifiers)):
        raise MapSpatialEvalError("矩阵存在重复资料族")
    by_genre_split = {(row.get("genre"), row.get("split")) for row in families}
    if by_genre_split != {
        (genre, split) for genre in ALLOWED_GENRES for split in ALLOWED_SPLITS
    }:
        raise MapSpatialEvalError("矩阵题材/分组不完整")
    return matrix


def verify_materials(
    private_root: Path, matrix: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    root = require_private_directory(private_root)
    manifest = matrix or load_matrix()
    seen_source_hashes: set[str] = set()
    seen_expected_hashes: set[str] = set()
    verified = []
    for family in manifest["families"]:
        family_id = family["family_id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,120}", family_id):
            raise MapSpatialEvalError("矩阵资料族 ID 不能包含路径")
        family_dir = root / family_id
        if family_dir.is_symlink() or not family_dir.is_dir():
            raise MapSpatialEvalError(f"缺少冻结资料族 {family_id}")
        if stat.S_IMODE(family_dir.stat().st_mode) != 0o700:
            raise MapSpatialEvalError(f"资料族目录权限必须为0700: {family_id}")
        source_path = family_dir / "source.json"
        expected_path = family_dir / "expected.json"
        for path in (source_path, expected_path):
            if (
                path.is_symlink()
                or not path.is_file()
                or stat.S_IMODE(path.stat().st_mode) != 0o600
            ):
                raise MapSpatialEvalError("冻结材料必须是0600普通文件")
        source_hash = _sha256_file(source_path)
        expected_hash = _sha256_file(expected_path)
        if source_hash != family.get("source_sha256") or expected_hash != family.get(
            "expected_sha256"
        ):
            raise MapSpatialEvalError(f"资料族哈希与冻结矩阵不符: {family_id}")
        if source_hash in seen_source_hashes or expected_hash in seen_expected_hashes:
            raise MapSpatialEvalError("不同资料族不能复用相同正文或期望文件")
        seen_source_hashes.add(source_hash)
        seen_expected_hashes.add(expected_hash)
        if family["split"] == "holdout":
            # Hash-only inspection does not expose holdout text/expectations to a runner.
            for path in (source_path, expected_path):
                if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
                    raise MapSpatialEvalError("留出文件必须是0600普通文件")
            verified.append({**family, "case_count": 5})
            continue
        source = _read_private_json(source_path)
        expected = _read_private_json(expected_path)
        for payload in (source, expected):
            if (payload.get("family_id"), payload.get("genre"), payload.get("split")) != (
                family_id,
                family.get("genre"),
                family.get("split"),
            ):
                raise MapSpatialEvalError(f"资料族身份与矩阵不符: {family_id}")
        source_cases = source.get("cases")
        expected_cases = expected.get("cases")
        if not isinstance(source_cases, list) or not isinstance(expected_cases, list):
            raise MapSpatialEvalError(f"资料族缺少原文或期望案例: {family_id}")
        source_ids = [case.get("case_id") for case in source_cases]
        expected_ids = [case.get("case_id") for case in expected_cases]
        if (
            len(source_ids) != 5
            or source_ids != expected_ids
            or len(set(source_ids)) != 5
        ):
            raise MapSpatialEvalError(f"资料族应有五个配对案例: {family_id}")
        if len({case.get("source_excerpt") for case in source_cases}) != 5:
            raise MapSpatialEvalError(f"资料族案例原文必须彼此不同: {family_id}")
        if (
            source.get("human_validated") is not False
            or expected.get("human_validated") is not False
        ):
            raise MapSpatialEvalError("代理材料不得伪标为人工验证")
        if family.get("review_status") != "not_run":
            raise MapSpatialEvalError("本阶段不回填教师评分或复核状态")
        verified.append(
            {
                "family_id": family_id,
                "genre": family["genre"],
                "split": family["split"],
                "case_count": len(source_cases),
                "source_sha256": source_hash,
                "expected_sha256": expected_hash,
                "review_status": "not_run",
            }
        )
    if len(
        {
            row["source_sha256"] for row in verified if row["split"] == "development"
        }.intersection(
            {row["source_sha256"] for row in verified if row["split"] == "holdout"}
        )
    ):
        raise MapSpatialEvalError("开发集与留出集存在正文复用")
    return verified


def _write_private_json(path: Path, value: Any) -> None:
    require_private_directory(path.parent, create=True)
    if path.is_symlink():
        raise MapSpatialEvalError("私有输出禁止符号链接")
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=".map-eval-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
        # A started claim must survive a crash before any irreversible request.
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def _family_for(matrix: dict[str, Any], family_id: str) -> dict[str, Any]:
    for family in matrix["families"]:
        if family["family_id"] == family_id:
            return family
    raise MapSpatialEvalError("矩阵中没有该资料族")


def _case_for(source: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in source["cases"]:
        if case["case_id"] == case_id:
            return case
    raise MapSpatialEvalError("资料族中没有该案例")


def _gate_path(private_root: Path) -> Path:
    return private_root / "gates" / "development-gate.json"


def _require_development_gate(
    private_root: Path, matrix: dict[str, Any]
) -> dict[str, Any]:
    from evals.map_spatial_guard import require_development_gate

    return require_development_gate(private_root, matrix)


def _ledger_path(private_root: Path) -> Path:
    return private_root / "run-ledger.json"


def _read_ledger(private_root: Path) -> dict[str, Any]:
    path = _ledger_path(private_root)
    if not path.exists():
        return {"schema_version": 1, "human_validated": False, "runs": {}}
    ledger = _read_private_json(path)
    if ledger.get("schema_version") != 1 or not isinstance(ledger.get("runs"), dict):
        raise MapSpatialEvalError("私有评测账本格式无效")
    return ledger


def _run_key(family_id: str, case_id: str) -> str:
    return f"{family_id}/{case_id}"


def claim_case(
    private_root: Path, matrix: dict[str, Any], family: dict[str, Any], case_id: str
) -> dict[str, Any]:
    from evals.map_spatial_guard import private_lock

    with private_lock(private_root):
        return _claim_case(private_root, matrix, family, case_id)


def _claim_case(private_root, matrix, family, case_id):
    if family != _family_for(matrix, family["family_id"]):
        raise MapSpatialEvalError("不能用伪造的资料族身份占用留出")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,180}", case_id):
        raise MapSpatialEvalError("案例ID不能包含路径")
    key = _run_key(family["family_id"], case_id)
    ledger = _read_ledger(private_root)
    if family["split"] == "holdout":
        gate = _require_development_gate(private_root, matrix)
    else:
        gate = None
    if key in ledger["runs"]:
        raise MapSpatialEvalError("该案例已启动、待处理、未知或完成；不自动重发")
    record = {
        "family_id": family["family_id"],
        "genre": family["genre"],
        "split": family["split"],
        "case_id": case_id,
        "status": "started",
        "started_at": datetime.now(UTC).isoformat(),
        "manifest_sha256": _sha256_file(MATRIX_PATH),
        "source_sha256": family["source_sha256"],
        "expected_sha256": family["expected_sha256"],
        "human_validated": False,
        "cost_status": "unknown",
        "development_gate_sha256": _sha256_file(_gate_path(private_root))
        if gate
        else None,
        "arms": {},
    }
    ledger["runs"][key] = record
    _write_private_json(_ledger_path(private_root), ledger)
    return record


def update_run(
    private_root: Path, family_id: str, case_id: str, **updates: Any
) -> dict[str, Any]:
    from evals.map_spatial_guard import private_lock

    with private_lock(private_root):
        return _update_run(private_root, family_id, case_id, updates)


def _update_run(private_root, family_id, case_id, updates):
    ledger = _read_ledger(private_root)
    key = _run_key(family_id, case_id)
    if key not in ledger["runs"]:
        raise MapSpatialEvalError("评测案例未预先占用")
    if any(
        name in updates and updates[name] != ledger["runs"][key].get(name)
        for name in (
            "family_id",
            "case_id",
            "genre",
            "split",
            "manifest_sha256",
            "source_sha256",
            "expected_sha256",
        )
    ):
        raise MapSpatialEvalError("冻结账本身份不可修改")
    if (
        ledger["runs"][key]["status"] in {"unknown", "completed"}
        and updates.get("status", ledger["runs"][key]["status"])
        != ledger["runs"][key]["status"]
    ):
        raise MapSpatialEvalError("unknown/completed不能重置后重发")
    ledger["runs"][key].update(updates)
    _write_private_json(_ledger_path(private_root), ledger)
    return ledger["runs"][key]


def report_template(
    matrix: dict[str, Any], ledger: dict[str, Any] | None = None
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for genre, metric_groups in matrix["metrics_by_genre"].items():
        reports[genre] = {
            group: {
                "status": "not_run",
                "metrics": {
                    name: {"value": None, "denominator": None, "status": "unknown"}
                    for name in names
                },
            }
            for group, names in metric_groups.items()
        }
    for genre in reports:
        for name in reports[genre]["cold_start"]["metrics"]:
            if name == "total_cost":
                reports[genre]["cold_start"]["metrics"][name] = {
                    "value": None,
                    "status": "unknown",
                    "currency": "USD",
                }
    return {
        "schema_version": 1,
        "suite": "map_spatial",
        "status": "not_run",
        "human_validated": False,
        "manifest_sha256": _sha256_file(MATRIX_PATH),
        "teacher_and_judge": {
            "model": "gpt-6.1-sol",
            "reasoning_effort": "xhigh",
            "status": "not_run",
        },
        "genres": reports,
        "run_count": len((ledger or {}).get("runs", {})),
        "results_are_not_default_enablement_evidence": True,
    }


def assert_pair_invariants(without: dict[str, Any], with_map: dict[str, Any]) -> None:
    shared = (
        "source_hash",
        "project_snapshot_hash",
        "scene_hash",
        "map_snapshot_hash",
        "prompt_hash",
        "core_context_hash",
    )
    for key in shared:
        if not without.get(key) or without.get(key) != with_map.get(key):
            raise MapSpatialEvalError(f"配对两臂的冻结输入不同: {key}")
    if without.get("map_enabled") is not False or with_map.get("map_enabled") is not True:
        raise MapSpatialEvalError("配对仅允许切换地图参考开关")


def _require_live_scope_approval(
    private_root: Path,
    matrix: dict[str, Any],
    *,
    execute: bool,
    family_id: str | None = None,
) -> dict:
    if not execute or os.environ.get(LIVE_ENV) != "1":
        raise MapSpatialEvalError(
            f"实时业务请求默认关闭；Sol审查后才可同时指定--execute和{LIVE_ENV}=1"
        )
    if not family_id:
        raise MapSpatialEvalError("not_ready_for_live: 缺少隔离绑定与真实校准证据")
    from evals.map_spatial_guard import read_binding, require_calibration

    binding = read_binding(private_root, family_id)
    if binding["split"] == "holdout":
        _require_development_gate(private_root, matrix)
    else:
        require_calibration(private_root, binding)
    return binding


def _database_target(database_url: str) -> tuple[str, str, str]:
    try:
        url = make_url(database_url)
    except (TypeError, ValueError):
        raise MapSpatialEvalError("DATABASE_URL无效") from None
    if url.get_backend_name() != "postgresql":
        raise MapSpatialEvalError("地图评测只接受独立本地PostgreSQL")
    if url.database != DATABASE_NAME or url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise MapSpatialEvalError(f"评测只接受本地专用数据库 {DATABASE_NAME}")
    if url.query:
        raise MapSpatialEvalError("隔离库URL不能带覆盖连接配置的查询参数")
    return url.get_backend_name(), str(url.host), str(url.database)


def _database_identity(database_url: str) -> dict:
    backend, host, name = _database_target(database_url)
    url = make_url(database_url)
    return {
        "backend": backend,
        "host": host,
        "name": name,
        "port": url.port or 5432,
        "username": url.username,
    }


def _as_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    raise MapSpatialEvalError("产品入口返回了无法冻结的契约对象")


@contextmanager
def writing_arm(enabled: bool):
    """A process-only override; immutable Settings and database flags stay untouched."""
    from core.config import get_settings

    old_env = os.environ.get("MAP_SPATIAL_ENABLED_CAPABILITIES")
    capabilities = tuple(
        value
        for value in get_settings().map_spatial_enabled_capabilities
        if value != "writing.generate"
    )
    os.environ["MAP_SPATIAL_ENABLED_CAPABILITIES"] = ",".join(
        (*capabilities, *(("writing.generate",) if enabled else ()))
    )
    get_settings.cache_clear()
    try:
        yield
    finally:
        if old_env is None:
            os.environ.pop("MAP_SPATIAL_ENABLED_CAPABILITIES", None)
        else:
            os.environ["MAP_SPATIAL_ENABLED_CAPABILITIES"] = old_env
        get_settings.cache_clear()


def pipeline_hash() -> str:
    roots = (
        "backend/modules/writing",
        "backend/modules/evidence/compilation",
        "backend/evals",
    )
    paths = sorted(
        path
        for root in roots
        for path in (REPO_ROOT / root).rglob("*.py")
        if "tests" not in path.parts
    )
    return _canonical_hash(
        {str(path.relative_to(REPO_ROOT)): _sha256_file(path) for path in paths}
    )


async def scene_source_refs(
    db, novel_id: str, scene_id: str, chapter_index: int, source_excerpt: str
) -> list[dict]:
    """Validate precise current Scene ranges through the real Evidence read seam."""
    from core.container import get
    from core.service_keys import STORY_SCENE_SOURCE
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import read_novel_evidence
    from modules.writing.facade import build_manuscript_range_ref

    matched_refs = []
    for span in await get(STORY_SCENE_SOURCE).get_scene_spans_for_scene(
        db, novel_id, scene_id, content_mode="canonical"
    ):
        value = _as_plain(span)
        if (
            value.get("mapping_status") not in {"exact", "reanchored"}
            or not value.get("source_draft_id")
            or value.get("chapter_index", 0) > chapter_index
            or value.get("start_offset") is None
            or value.get("end_offset") is None
        ):
            continue
        ref = await build_manuscript_range_ref(
            db,
            novel_id,
            draft_id=value["source_draft_id"],
            start_offset=value["start_offset"],
            end_offset=value["end_offset"],
            content_mode="canonical",
        )
        if ref.source_hash != value.get("source_content_hash"):
            raise MapSpatialEvalError("Scene精确来源已经漂移")
        evidence = await read_novel_evidence(
            db,
            novel_id=novel_id,
            source_ref=ref,
            visibility=VisibilityContextContract(
                mode="reader", cutoff_chapter=chapter_index, cutoff_scene_id=scene_id
            ),
            before=0,
            after=0,
        )
        if (evidence.get("visibility_decision") or {}).get(
            "visible"
        ) is True and source_excerpt in str(evidence.get("text") or ""):
            matched_refs.append(_as_plain(ref))
    if not matched_refs:
        raise MapSpatialEvalError("冻结原文没有绑定到该Scene的当前canonical可见精确区间")
    return matched_refs


async def preflight_project(
    *,
    private_root: Path,
    family: dict[str, Any],
    novel_id: str,
    scene_id: str,
    chapter_index: int,
    source_excerpt: str,
) -> dict[str, Any]:
    """Read only the exact isolated owner and actual canonical Scene source ranges."""
    _database_target(os.environ.get("DATABASE_URL", ""))
    if os.environ.get("AUTH_MODE") != "local":
        raise MapSpatialEvalError("评测进程必须显式设置AUTH_MODE=local")
    if family["split"] == "holdout":
        _require_development_gate(private_root, load_matrix())
    from sqlalchemy import select

    from app.bootstrap import register_container_services
    from core.database import get_manager
    from evals.map_spatial_guard import rubric_hash
    from modules.account.facade import current_account_id, require_account_active
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
        restore_project_llm_execution_settings,
    )
    from modules.project.models import Project
    from modules.story.facade import get_scene_contract
    from modules.world.contracts import MapSpatialBriefRequest
    from modules.world.facade import read_map_spatial_brief

    register_container_services(ignore_existing=True)
    manager = get_manager()
    target = _database_identity(str(manager.engine.url))
    if target != _database_identity(os.environ["DATABASE_URL"]):
        raise MapSpatialEvalError("配置URL和实际运行数据库不同")
    async with manager.session() as db:
        owner_id = current_account_id()
        await require_account_active(db, owner_id, allow_local_bootstrap=False)
        await require_active_project(db, novel_id)
        project = await db.scalar(
            select(Project).where(Project.id == uuid.UUID(novel_id))
        )
        if (
            project is None
            or str(project.owner_id) != str(owner_id)
            or project.project_kind != "author"
            or not project.title.startswith(f"MAP-EVAL:{family['family_id']}:")
            or project.genre not in {family["genre"], PROJECT_GENRES[family["genre"]]}
        ):
            raise MapSpatialEvalError("项目不是当前owner的该资料族专用合成作者项目")
        snapshot = await build_project_llm_execution_snapshot(db, novel_id)
        restored = await restore_project_llm_execution_settings(db, novel_id, snapshot)
        profile = snapshot.get("profile") or {}
        if (
            profile.get("provider_id") != "codex"
            or profile.get("model") != "gpt-6-luna"
            or profile.get("connection_verified") is not True
            or restored.get("llm", {}).get("extra", {}).get("reasoning_effort") != "max"
        ):
            raise MapSpatialEvalError("项目owner连接未验证为Codex Luna/max")
        scene = await get_scene_contract(db, novel_id, scene_id)
        if scene is None:
            raise MapSpatialEvalError("指定Scene不属于该合成项目")
        scene_data = _as_plain(scene)
        matched_refs = await scene_source_refs(
            db, novel_id, scene_id, chapter_index, source_excerpt
        )
        brief_data = _as_plain(
            await read_map_spatial_brief(
                db,
                MapSpatialBriefRequest(
                    novel_id=novel_id,
                    scene_id=scene_id,
                    chapter_index=chapter_index,
                    reveal_mode="author_safe",
                ),
            )
        )
        if not brief_data.get("items"):
            raise MapSpatialEvalError("World产品入口没有返回已采用的空间简报")
        result = {
            "schema_version": 1,
            "suite": "map_spatial",
            "database_target": target,
            "family_id": family["family_id"],
            "genre": family["genre"],
            "split": family["split"],
            "novel_id": novel_id,
            "owner_id": str(owner_id),
            "scene_id": scene_id,
            "chapter_index": chapter_index,
            "manifest_sha256": _sha256_file(MATRIX_PATH),
            "rubric_sha256": rubric_hash(),
            "source_sha256": family["source_sha256"],
            "expected_sha256": family["expected_sha256"],
            "project_snapshot": snapshot,
            "project_snapshot_hash": _canonical_hash(snapshot),
            "scene_hash": _canonical_hash(scene_data),
            "map_snapshot_hash": _canonical_hash(brief_data),
            "source_snapshot_hash": _canonical_hash(matched_refs),
            "pipeline_hash": pipeline_hash(),
            "map_revision_count": len(brief_data["items"]),
            "human_validated": False,
            "private_root_sha256": _canonical_hash(str(private_root.resolve())),
        }
        await db.rollback()
        return result


async def run_writing_pair(
    *,
    private_root: Path,
    family_id: str,
    case_id: str,
    novel_id: str,
    scene_id: str,
    chapter_index: int,
    execute: bool,
) -> dict[str, Any]:
    """Use actual Evidence confirmation, Writing queue and TaskWorker for both arms."""
    private_root = require_private_directory(private_root)
    matrix = load_matrix()
    binding = _require_live_scope_approval(
        private_root, matrix, execute=execute, family_id=family_id
    )
    case_binding = binding.get("case_bindings", {}).get(case_id, {})
    if (
        case_binding.get("novel_id"),
        case_binding.get("scene_id"),
        case_binding.get("chapter_index"),
    ) != (novel_id, scene_id, chapter_index):
        raise MapSpatialEvalError("运行参数不属于已冻结隔离绑定")
    verified = {row["family_id"]: row for row in verify_materials(private_root, matrix)}
    family = _family_for(matrix, family_id)
    source_path = private_root / family_id / "source.json"
    source = _read_private_json(source_path)
    case = _case_for(source, case_id)
    if verified[family_id]["split"] == "holdout":
        _require_development_gate(private_root, matrix)
    preflight = await preflight_project(
        private_root=private_root,
        family=family,
        novel_id=novel_id,
        scene_id=scene_id,
        chapter_index=chapter_index,
        source_excerpt=case["source_excerpt"],
    )
    if preflight != case_binding:
        raise MapSpatialEvalError("隔离预检、来源、prompt或项目快照漂移")
    initial = claim_case(private_root, matrix, family, case_id)

    from sqlalchemy import select

    from core.database import get_manager
    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.compilation.contracts import ContextConfirmationRequest
    from modules.evidence.facade import confirm_context, prepare_confirmed_ai_action
    from modules.project.facade import build_project_llm_execution_snapshot
    from modules.story.facade import get_scene_contract
    from modules.writing.facade import get_draft
    from modules.writing.generation_service import WritingGenerationService
    from modules.writing.schemas import WritingGenerateRequest
    from run_worker import _build_task_worker, _configure_worker_process

    _configure_worker_process()
    manager = get_manager()
    arms: dict[str, dict[str, Any]] = {}
    requests = {
        "without_spatial_brief": False,
        "with_spatial_brief": True,
    }
    instruction = case["writing_scene_instruction"]
    task_text = f"根据已确认的Scene合同完成本场写作。{instruction}"
    prompt_hash = hashlib.sha256(task_text.encode("utf-8")).hexdigest()
    scene_before = preflight["scene_hash"]
    map_before = preflight["map_snapshot_hash"]
    project_before = preflight["project_snapshot_hash"]
    try:
        async with manager.session() as db:
            snapshot = await build_project_llm_execution_snapshot(db, novel_id)
            if _canonical_hash(snapshot) != project_before:
                raise MapSpatialEvalError("Project快照在预检后发生漂移")
            for arm_name, enabled in requests.items():
                with writing_arm(enabled):
                    scene = await get_scene_contract(db, novel_id, scene_id)
                    if scene is None:
                        raise MapSpatialEvalError("Scene在冻结期间失效")
                    confirmation = await confirm_context(
                        db,
                        ContextConfirmationRequest(
                            novel_id=novel_id,
                            action="writing.generate",
                            task=task_text,
                            scope="scene",
                            chapter_index=chapter_index,
                            scene_id=scene_id,
                            reveal_mode="author_safe",
                            content_mode="canonical",
                            context_mode="canonical",
                        ),
                    )
                    confirmed = await prepare_confirmed_ai_action(
                        db,
                        novel_id=novel_id,
                        action="writing.generate",
                        confirmation_id=confirmation.id,
                    )
                    rendered = confirmed.rendered_markdown
                    if case["source_excerpt"] not in rendered:
                        raise MapSpatialEvalError("冻结原文没有进入实际Writing确认上下文")
                    options = dict(confirmation.compile_options or {})
                    baseline = list(options.get("map_spatial_baseline") or [])
                    if enabled and not baseline:
                        raise MapSpatialEvalError("带地图臂的Writing确认未加载空间版本")
                    if not enabled and baseline:
                        raise MapSpatialEvalError("不带地图臂意外加载了空间版本")
                    response = await WritingGenerationService().submit_generation(
                        db,
                        WritingGenerateRequest(
                            novel_id=novel_id,
                            chapter_index=chapter_index,
                            title=f"地图配对评测 {family_id}",
                            instruction=instruction,
                            context_confirmation_id=confirmation.id,
                            operation_id=uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"map-spatial/{family_id}/{case_id}/{arm_name}/{_sha256_file(MATRIX_PATH)}",
                            ),
                        ),
                        llm_execution_snapshot=snapshot,
                    )
                arms[arm_name] = {
                    "status": "pending",
                    "task_id": response["task_id"],
                    "confirmation_id": confirmation.id,
                    "source_hash": family["source_sha256"],
                    "project_snapshot_hash": project_before,
                    "scene_hash": scene_before,
                    "map_snapshot_hash": map_before,
                    "prompt_hash": prompt_hash,
                    "core_context_hash": options.get("compiled_context_core_fingerprint"),
                    "map_enabled": enabled,
                    "map_revision_count": len(baseline),
                    "model": "gpt-6-luna",
                    "status_detail": "queued",
                }
            assert_pair_invariants(
                arms["without_spatial_brief"], arms["with_spatial_brief"]
            )
            core = dict(confirmation.compile_options or {}).get(
                "compiled_context_core_fingerprint"
            )
            for arm in arms.values():
                if not arm.get("core_context_hash") or arm["core_context_hash"] != core:
                    raise MapSpatialEvalError("两臂的非地图编译上下文指纹不同")
            initial["arms"] = arms
            initial["project_snapshot_hash"] = project_before
            initial["scene_hash"] = scene_before
            initial["map_snapshot_hash"] = map_before
            initial["pair_input_hash"] = _canonical_hash(
                {
                    key: value
                    for key, value in arms["without_spatial_brief"].items()
                    if key
                    not in {"confirmation_id", "task_id", "status", "status_detail"}
                }
            )
            update_run(
                private_root,
                family_id,
                case_id,
                **{
                    key: value
                    for key, value in initial.items()
                    if key not in {"family_id", "case_id"}
                },
            )

        worker = _build_task_worker()
        for arm_name, enabled in requests.items():
            arm = arms[arm_name]
            current_ledger = _read_ledger(private_root)
            current = current_ledger["runs"][_run_key(family_id, case_id)]
            current_arms = dict(current.get("arms") or {})
            current_arms[arm_name] = {
                **arm,
                "status": "started",
                "status_detail": "worker_claim_started",
            }
            update_run(private_root, family_id, case_id, arms=current_arms)
            try:
                with writing_arm(enabled):
                    # Recheck owner/Project immediately before this exact task.
                    from evals.map_spatial_guard import verify_runtime

                    async with manager.session() as runtime_db:
                        await verify_runtime(runtime_db, binding)
                    await worker.run_once(task_id=arm["task_id"], novel_id=novel_id)
            except BaseException:
                current_ledger = _read_ledger(private_root)
                current = current_ledger["runs"][_run_key(family_id, case_id)]
                current_arms = dict(current.get("arms") or {})
                current_arms[arm_name] = {
                    **arm,
                    "status": "unknown",
                    "status_detail": "worker_interrupted_or_failed",
                }
                update_run(
                    private_root, family_id, case_id, arms=current_arms, status="unknown"
                )
                raise
            async with manager.session() as db:
                saved_task = await db.scalar(
                    select(AsyncTask).where(
                        AsyncTask.id == uuid.UUID(arm["task_id"]),
                        AsyncTask.novel_id == uuid.UUID(novel_id),
                    )
                )
                if (
                    saved_task is None
                    or saved_task.status != "done"
                    or not (saved_task.result or {}).get("draft_id")
                ):
                    status = (
                        "pending"
                        if saved_task is not None
                        and saved_task.status == "pending"
                        and saved_task.attempt == 0
                        else "unknown"
                    )
                    current_ledger = _read_ledger(private_root)
                    current = current_ledger["runs"][_run_key(family_id, case_id)]
                    current_arms = dict(current.get("arms") or {})
                    current_arms[arm_name] = {
                        **arm,
                        "status": status,
                        "status_detail": "task_not_completed",
                    }
                    update_run(
                        private_root,
                        family_id,
                        case_id,
                        arms=current_arms,
                        status="unknown" if status == "unknown" else "pending",
                    )
                    raise MapSpatialEvalError(
                        "Writing任务未完成；账本保留pending/unknown且不会自动重发"
                    )
                draft = await get_draft(db, novel_id, str(saved_task.result["draft_id"]))
                if draft is None or not draft.content:
                    raise MapSpatialEvalError("Writing候选缺少正文")
                output = {
                    "family_id": family_id,
                    "case_id": case_id,
                    "arm": arm_name,
                    "status": "completed",
                    "draft_id": draft.id,
                    "draft_hash": draft.content_hash,
                    "draft_content": draft.content,
                    "model": "gpt-6-luna",
                    "usage": "unknown",
                    "cost": "unknown",
                    "human_validated": False,
                }
                output_path = (
                    private_root / "runs" / family_id / f"{case_id}-{arm_name}.json"
                )
                _write_private_json(output_path, output)
                current_ledger = _read_ledger(private_root)
                current = current_ledger["runs"][_run_key(family_id, case_id)]
                current_arms = dict(current.get("arms") or {})
                current_arms[arm_name] = {
                    **arm,
                    "status": "completed",
                    "status_detail": "candidate_created_not_adopted",
                    "draft_sha256": draft.content_hash,
                    "raw_output_sha256": _sha256_file(output_path),
                    "usage": "unknown",
                    "cost": "unknown",
                }
                update_run(private_root, family_id, case_id, arms=current_arms)
            # Candidate adoption would contaminate the second arm's frozen context.
            after = await preflight_project(
                private_root=private_root,
                family=family,
                novel_id=novel_id,
                scene_id=scene_id,
                chapter_index=chapter_index,
                source_excerpt=case["source_excerpt"],
            )
            if after != case_binding:
                raise MapSpatialEvalError("配对臂之间Project/Scene/map版本漂移，停止评测")
        update_run(
            private_root,
            family_id,
            case_id,
            status="completed",
            completed_at=datetime.now(UTC).isoformat(),
        )
        return {
            "family_id": family_id,
            "case_id": case_id,
            "status": "completed",
            "human_validated": False,
            "usage": "unknown",
            "cost": "unknown",
            "raw_outputs": "private",
        }
    except BaseException:
        # The claim is consumed even if validation or queue submission was interrupted.
        current = _read_ledger(private_root)["runs"][_run_key(family_id, case_id)]
        if current["status"] not in {"unknown", "completed", "pending"}:
            update_run(private_root, family_id, case_id, status="unknown")
        raise


def build_report(private_root: Path, output: Path) -> dict[str, Any]:
    require_private_directory(private_root)
    if _is_in_repository(output):
        raise MapSpatialEvalError("评测报告必须写入仓库外私有目录")
    matrix = load_matrix()
    report = report_template(matrix, _read_ledger(private_root))
    report["status"] = "prepared"
    report["output_written_at"] = datetime.now(UTC).isoformat()
    _write_private_json(output, report)
    return {
        "status": report["status"],
        "genres": len(report["genres"]),
        "human_validated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.map_spatial")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify",
        help="verify private frozen materials without reading their text to stdout",
    )
    verify.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    report = commands.add_parser(
        "report", help="write a per-genre report template outside the repository"
    )
    report.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    report.add_argument("--output", type=Path, required=True)
    pair = commands.add_parser(
        "pair-writing", help="run one guarded product Writing pair"
    )
    pair.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    pair.add_argument("--family-id", required=True)
    pair.add_argument("--case-id", required=True)
    pair.add_argument("--novel-id", required=True)
    pair.add_argument("--scene-id", required=True)
    pair.add_argument("--chapter-index", type=int, default=2)
    pair.add_argument(
        "--execute",
        action="store_true",
        help="explicitly requests guarded live SUT calls",
    )
    freeze = commands.add_parser(
        "freeze-binding", help="freeze actual owner/Scene setup; no LLM"
    )
    freeze.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    freeze.add_argument("--family-id", required=True)
    freeze.add_argument("--scopes", type=Path, required=True)
    freeze.add_argument("--execute", action="store_true")
    score = commands.add_parser(
        "score", help="one map-only seeded calibration or judge call"
    )
    score.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    score.add_argument("--family-id", required=True)
    score.add_argument(
        "--phase",
        required=True,
        choices=("teacher_calibration", "development_judge", "holdout_judge"),
    )
    score.add_argument("--case-id", required=True)
    score.add_argument("--execute", action="store_true")
    gate = commands.add_parser(
        "freeze-development-gate", help="freeze recomputed real development evidence"
    )
    gate.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    args = parser.parse_args()
    if args.command == "verify":
        records = verify_materials(args.private_root)
        print(
            json.dumps(
                {
                    "verified_families": len(records),
                    "case_count": sum(row["case_count"] for row in records),
                    "review_status": "not_run",
                    "human_validated": False,
                },
                ensure_ascii=False,
            )
        )
        return
    if args.command == "report":
        result = build_report(args.private_root, args.output)
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.command in {"freeze-binding", "score", "freeze-development-gate"}:
        from evals.map_spatial_control import freeze_binding, freeze_gate
        from evals.map_spatial_control import score as score_request

        options = vars(args).copy()
        options.pop("command")
        try:
            if args.command == "freeze-development-gate":
                result = freeze_gate(args.private_root)
            else:
                action = (
                    freeze_binding if args.command == "freeze-binding" else score_request
                )
                result = asyncio.run(action(**options))
        except MapSpatialEvalError as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False))
        return
    try:
        result = asyncio.run(
            run_writing_pair(
                private_root=args.private_root,
                family_id=args.family_id,
                case_id=args.case_id,
                novel_id=args.novel_id,
                scene_id=args.scene_id,
                chapter_index=args.chapter_index,
                execute=args.execute,
            )
        )
    except MapSpatialEvalError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

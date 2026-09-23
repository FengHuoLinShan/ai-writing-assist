"""Project-wide admission and commit fence for the understanding migration."""

from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError
from modules.project.models import Project

LEGACY_TASK_TYPES = frozenset(
    {
        "deep_import",
        "scene_auto_extraction",
        "world_object_auto_extraction",
        "plot_structure_auto_extraction",
        "targeted_completion",
        "import_review_resolution",
    }
)
OWNER_KEY = "_understanding_owner"
WRITE_SCHEMAS = {"legacy": 1, "evolution": 2}


async def state(db, novel_id):
    from modules.project.facade import require_active_project

    await require_active_project(db, str(novel_id))
    row = (
        await db.execute(
            select(
                Project.understanding_engine,
                Project.understanding_epoch,
                Project.understanding_schema_floor,
            ).where(Project.id == UUID(str(novel_id)))
        )
    ).one()
    return {"engine": row[0], "epoch": row[1], "schema_floor": row[2]}


async def require_writer(db, novel_id, *, engine, epoch=None):
    current = await state(db, novel_id)
    if (
        current["engine"] != engine
        or current["schema_floor"] > WRITE_SCHEMAS[engine]
        or (epoch is not None and epoch != current["epoch"])
    ):
        raise ConflictError(
            "理解流程已切换或暂停；旧任务只能查看历史，请从当前流程继续",
            code="understanding_owner_changed",
        )
    return {
        "engine": engine,
        "epoch": current["epoch"],
        "schema": WRITE_SCHEMAS[engine],
    }


async def validate_token(db, novel_id, *, engine, token):
    # Only the untouched legacy generation can read a pre-migration task.
    expected = (
        token
        if isinstance(token, dict)
        else {"engine": "legacy", "epoch": 1, "schema": 1}
    )
    if (
        expected.get("engine") != engine
        or type(expected.get("epoch")) is not int
        or expected["epoch"] < 1
        or type(expected.get("schema")) is not int
        or expected["schema"] != WRITE_SCHEMAS[engine]
    ):
        raise ConflictError(
            "理解任务缺少兼容的冻结身份", code="understanding_owner_changed"
        )
    return await require_writer(
        db, novel_id, engine=engine, epoch=expected.get("epoch", -1)
    )


async def check_task(db, task):
    task_type = str(task.task_type)
    meta = dict(task.meta or {})
    if task_type == "evolution_scene_step":
        raise ConflictError(
            "旧演化任务协议不能继续写入，请保留历史并重新准备",
            code="incompatible_engine_rollback",
        )
    if task_type in LEGACY_TASK_TYPES:
        engine = "legacy"
    elif (
        task_type == "evolution_scene_step_v2"
        and meta.get("execution_mode", "live") != "shadow"
    ):
        engine = "evolution"
    else:
        return
    await validate_token(db, task.novel_id, engine=engine, token=meta.get(OWNER_KEY))


async def advance(db, novel_id, *, engine, expected_epoch):
    """Called after Evolution drains owners under the exclusive project lock."""
    from modules.project.facade import require_active_project_exclusive

    if engine not in {*WRITE_SCHEMAS, "read_only"}:
        raise ValueError("unsupported understanding engine")
    await require_active_project_exclusive(db, str(novel_id))
    project = (
        await db.execute(
            select(Project)
            .where(Project.id == novel_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if project.understanding_epoch != expected_epoch:
        raise ConflictError(
            "理解流程状态已变化，请重新读取", code="understanding_owner_changed"
        )
    if engine == "legacy" and project.understanding_schema_floor > 1:
        raise ConflictError(
            "新版理解已启用，旧引擎不能继续写入；可暂停并前向修复",
            code="incompatible_engine_rollback",
        )
    project.understanding_engine = engine
    project.understanding_epoch += 1
    project.understanding_schema_floor = max(
        project.understanding_schema_floor, WRITE_SCHEMAS.get(engine, 1)
    )
    await db.flush()
    return {
        "engine": engine,
        "epoch": project.understanding_epoch,
        "schema_floor": project.understanding_schema_floor,
    }

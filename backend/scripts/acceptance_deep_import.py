"""真实 LLM 深度导入验收脚本 — 《诡秘之主 第一部》第 1-3 章。

运行前提：
- PostgreSQL 开发库已启动且 DATABASE_URL 已配置。
- LLM API Key / 模型配置已设置。
- 数据库中已存在《诡秘之主 第一部》项目，或本地小说文件可解析。

用法：
    cd backend
    python scripts/acceptance_deep_import.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# 设置嵌入模型 provider，避免本地 onnx 模型加载
os.environ.setdefault("EMBEDDING_PROVIDER", "openai")

# 必须先把 backend 目录加入路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# 注册 ORM 模型
from sqlalchemy import func, select  # noqa: E402

import modules.imports.models  # noqa: F401, E402
import modules.memory.models  # noqa: F401, E402
import modules.outline.models  # noqa: F401, E402
import modules.project.models  # noqa: F401, E402
import modules.rag.models  # noqa: F401, E402
import modules.world.models  # noqa: F401, E402
import modules.writing.models  # noqa: F401, E402
from core.database import get_manager  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("acceptance_deep_import")

# 项目标题候选
PROJECT_TITLES = [
    "《诡秘之主 第一部》",
    "诡秘之主 第一部",
    "诡秘之主",
]

# 本地小说文件候选（回退导入用）
NOVEL_FILE_CANDIDATES = [
    Path("/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt"),
    Path.home() / "Desktop" / "项目" / "wirting skill" / "诡秘之主_第一部 小丑.txt",
    Path("/tmp/诡秘之主_第一部 小丑.txt"),
]

START_CHAPTER = 1
END_CHAPTER = 3


async def _find_or_prepare_project(db, title_candidates: list[str]) -> str:
    """查找项目；找不到则创建空项目并尝试导入本地文件。"""
    from modules.project.models import Project

    for title in title_candidates:
        result = await db.execute(
            select(Project).where(Project.title == title)
        )
        project = result.scalar_one_or_none()
        if project is not None:
            logger.info("找到项目: %s (id=%s)", project.title, project.id)
            return str(project.id)

    # 创建新项目
    from modules.project.schemas import ProjectCreate
    from modules.project.services import ProjectService

    project = await ProjectService().create_project(
        db,
        ProjectCreate(title="《诡秘之主 第一部》", language="zh", genre="fantasy"),
    )
    novel_id = str(project.id)
    logger.info("创建新项目: %s", novel_id)

    # 尝试导入本地文件
    for path in NOVEL_FILE_CANDIDATES:
        if path.exists():
            logger.info("从本地文件导入: %s", path)
            from modules.imports.facade import import_file

            await import_file(db, novel_id, path.name, path.read_bytes())
            break
    else:
        logger.warning("未找到本地小说文件，请确认数据库中已有第 1-3 章 draft")

    return novel_id


async def _ensure_drafts_exist(db, novel_id: str) -> bool:
    """确认第 1-3 章有 draft 内容。"""
    from modules.writing.models import WritingDraft

    stmt = (
        select(func.count(WritingDraft.id))
        .where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index.between(START_CHAPTER, END_CHAPTER),
            WritingDraft.content.isnot(None),
        )
    )
    result = await db.execute(stmt)
    count = result.scalar() or 0
    logger.info("第 %d-%d 章有效 draft 数: %d", START_CHAPTER, END_CHAPTER, count)
    return count == END_CHAPTER - START_CHAPTER + 1


async def _clear_auto_ingested_range(db, novel_id: str) -> None:
    """清理该范围内的旧自动导入数据，保证验收可重复。"""
    from modules.imports.facade import _deprecate_derived_data

    stats = await _deprecate_derived_data(db, novel_id, START_CHAPTER, END_CHAPTER)
    logger.info("清理旧派生数据: %s", stats)


async def _run_deep_import(db, novel_id: str) -> dict:
    """直接运行 DeepImportWorkflow 三阶段。"""
    from modules.imports.workflow import DeepImportWorkflow
    from modules.imports.workflow_schemas import DeepImportProgress

    workflow = DeepImportWorkflow()
    progress = DeepImportProgress()
    result = await workflow.run_step(
        db,
        novel_id=novel_id,
        start_chapter=START_CHAPTER,
        end_chapter=END_CHAPTER,
        progress=progress,
    )
    return {
        "phase": result.phase,
        "completed_steps": result.completed_steps,
        "message": result.message,
        "degraded": result.degraded,
    }


async def _count_outputs(db, novel_id: str) -> dict:
    """统计各类派生资产数量。"""
    from modules.memory.models import DeltaLog, MemorySnapshot
    from modules.outline.models import (
        ForeshadowingPlan,
        OutlineArc,
        PlotThread,
        RevealPlan,
        Scene,
    )
    from modules.world.models import CoreEntity, EntityRelation

    counts: dict[str, int] = {}
    models = [
        ("scenes", Scene),
        ("entities", CoreEntity),
        ("relations", EntityRelation),
        ("delta_logs", DeltaLog),
        ("memory_snapshots", MemorySnapshot),
        ("plot_threads", PlotThread),
        ("outline_arcs", OutlineArc),
        ("foreshadowing_plans", ForeshadowingPlan),
        ("reveal_plans", RevealPlan),
    ]
    for label, model in models:
        stmt = select(func.count(model.id)).where(model.novel_id == novel_id)
        result = await db.execute(stmt)
        counts[label] = result.scalar() or 0
    return counts


async def main() -> int:
    # app.main 在导入时已自动注册 DI 容器服务
    import app.main  # noqa: F401

    manager = get_manager()
    async with manager.session() as db:
        novel_id = await _find_or_prepare_project(db, PROJECT_TITLES)

        if not await _ensure_drafts_exist(db, novel_id):
            logger.error(
                "项目中缺少第 %d-%d 章正文，无法继续验收。",
                START_CHAPTER,
                END_CHAPTER,
            )
            return 1

        await _clear_auto_ingested_range(db, novel_id)

        run_info = await _run_deep_import(db, novel_id)
        logger.info("Workflow 结果: %s", run_info)

        if run_info["phase"] != "done":
            logger.error("Workflow 未完成: %s", run_info)
            return 1

        counts = await _count_outputs(db, novel_id)
        logger.info("=" * 50)
        logger.info("《诡秘之主 第一部》第 1-3 章深度导入资产统计")
        for label, count in counts.items():
            logger.info("  %s: %d", label, count)
        logger.info("=" * 50)

        if counts["scenes"] == 0 or counts["entities"] == 0:
            logger.error("未生成 Scene 或 Entity，验收失败")
            return 1

        logger.info("验收通过")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

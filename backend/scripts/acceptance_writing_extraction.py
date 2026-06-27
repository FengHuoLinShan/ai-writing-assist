"""真实 LLM 场景卡提取验收脚本 — 《诡秘之主 第一部》第 1-3 章。

运行前提：
- PostgreSQL 开发库已启动且 DATABASE_URL 已配置。
- LLM API Key / 模型配置已设置（backend/.env）。

用法：
    cd backend
    python scripts/acceptance_writing_extraction.py

说明：
- 创建项目《诡秘之主 第一部》并写入第 1-3 章真实正文草稿。
- 直接调用 modules.outline.services.PlotStructureGenerator.generate
  （不走 HTTP，不 mock LLM）。
- 查询 scenes 表并输出核心字段。
- 若 LLM 调用失败，外层最多重试 3 次（指数退避）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# 设置嵌入模型 provider，避免本地 onnx 模型加载
os.environ.setdefault("EMBEDDING_PROVIDER", "openai")

# 必须先把 backend 目录加入路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# app.main 导入时会注册 DI 容器服务
from sqlalchemy import select  # noqa: E402

import app.main  # noqa: F401, E402
from core.config import get_settings  # noqa: E402
from core.container import reset as reset_container  # noqa: E402
from core.database import get_manager  # noqa: E402
from modules.outline.services import PlotStructureGenerator  # noqa: E402
from modules.project.models import Project  # noqa: E402
from modules.writing.models import WritingDraft  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("acceptance_writing_extraction")

SAMPLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "e2e"
    / "samples"
    / "lotm_chapters_1_2_3.txt"
)
PROJECT_TITLE = "诡秘之主 第一部"
START_CHAPTER = 1
END_CHAPTER = 3
MAX_RETRIES = 3
BACKOFF_BASE = 2.0


def _load_chapters() -> list[dict]:
    """从样本文件解析第 1-3 章。"""
    if not SAMPLE_PATH.exists():
        raise FileNotFoundError(f"找不到章节样本: {SAMPLE_PATH}")

    raw = SAMPLE_PATH.read_text(encoding="utf-8")
    parts = [part.strip() for part in raw.split("\n\n---\n\n") if part.strip()]
    chapters = []
    for chapter_index, content in enumerate(parts, start=1):
        lines = content.splitlines()
        title = lines[0].strip() if lines else f"第{chapter_index}章"
        chapters.append(
            {
                "chapter_index": chapter_index,
                "title": title,
                "content": content,
            }
        )
    return chapters


async def _find_or_create_project(db) -> str:
    """查找或创建项目，返回 project_id 字符串。"""
    result = await db.execute(select(Project).where(Project.title == PROJECT_TITLE))
    project = result.scalar_one_or_none()
    if project is not None:
        logger.info("找到已有项目: %s (id=%s)", project.title, project.id)
        return str(project.id)

    project = Project(
        id=uuid.uuid4(),
        title=PROJECT_TITLE,
        genre="西方奇幻",
        tone="维多利亚风格、黑暗、悬疑",
        language="zh",
        target_length="novel",
        current_stage="writing",
    )
    db.add(project)
    await db.flush()
    logger.info("创建新项目: %s (id=%s)", project.title, project.id)
    return str(project.id)


async def _create_writing_drafts(db, novel_id: str) -> None:
    """为项目写入第 1-3 章真实正文草稿。"""
    chapters = _load_chapters()
    for ch in chapters:
        draft = WritingDraft(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(novel_id),
            chapter_index=ch["chapter_index"],
            title=ch["title"],
            content=ch["content"],
            version_number=1,
            status="canonical",
        )
        db.add(draft)
    await db.flush()
    logger.info("已写入 %d 章正文草稿", len(chapters))


async def _ensure_drafts(db, novel_id: str) -> bool:
    """确认项目已存在第 1-3 章草稿。"""
    stmt = (
        select(WritingDraft)
        .where(
            WritingDraft.novel_id == uuid.UUID(novel_id),
            WritingDraft.chapter_index.between(START_CHAPTER, END_CHAPTER),
        )
        .order_by(WritingDraft.chapter_index)
    )
    result = await db.execute(stmt)
    drafts = result.scalars().all()
    valid = [d for d in drafts if d.content]
    logger.info(
        "项目已有第 %d-%d 章草稿: %d 条有效",
        START_CHAPTER,
        END_CHAPTER,
        len(valid),
    )
    return len(valid) == END_CHAPTER - START_CHAPTER + 1


async def _run_generation(db, novel_id: str) -> dict:
    """调用真实 LLM 生成剧情结构，带外层重试。"""
    generator = PlotStructureGenerator()
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            logger.info(
                "开始调用 PlotStructureGenerator (attempt %d/%d)",
                attempt + 1,
                MAX_RETRIES + 1,
            )
            result = await generator.generate(
                db,
                novel_id=novel_id,
                start_chapter=START_CHAPTER,
                end_chapter=END_CHAPTER,
            )
            logger.info(
                "生成完成: %d threads, %d arcs, %d scenes",
                result.get("total_threads", 0),
                result.get("total_arcs", 0),
                result.get("total_scenes", 0),
            )
            return result
        except Exception as exc:
            last_error = exc
            logger.warning(
                "生成调用失败 (attempt %d/%d): %s",
                attempt + 1,
                MAX_RETRIES + 1,
                exc,
            )
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE * (2**attempt)
                logger.info("等待 %.1f 秒后重试...", wait)
                await asyncio.sleep(wait)

    raise RuntimeError(
        f"LLM 生成在 {MAX_RETRIES + 1} 次尝试后均失败: {last_error}"
    ) from last_error


async def _fetch_scenes(db, novel_id: str) -> list[dict]:
    """查询项目的 scenes 表。"""
    from modules.outline.models import Scene

    stmt = (
        select(Scene)
        .where(Scene.novel_id == uuid.UUID(novel_id))
        .order_by(Scene.scene_index)
    )
    result = await db.execute(stmt)
    scenes = result.scalars().all()
    return [
        {
            "scene_index": s.scene_index,
            "title": s.title,
            "goal": s.goal,
            "core_conflict": s.core_conflict,
            "emotional_beat": s.emotional_beat,
            "must_happen": s.must_happen,
            "must_not_happen": s.must_not_happen,
            "narrative_tag": s.narrative_tag,
            "source": s.source,
            "status": s.status,
        }
        for s in scenes
    ]


async def main() -> int:
    reset_container()
    app.main._register_container_services()

    settings = get_settings()
    logger.info("DATABASE_URL: %s", settings.database_url)
    logger.info("LLM_MODEL: %s", settings.llm_model)
    logger.info("LLM_BASE_URL: %s", settings.llm_base_url)

    manager = get_manager()
    # 确保表已创建（开发/验收环境可新建表）
    await manager.create_tables()

    async with manager.session() as db:
        novel_id = await _find_or_create_project(db)

        if not await _ensure_drafts(db, novel_id):
            await _create_writing_drafts(db, novel_id)

        gen_result = await _run_generation(db, novel_id)
        scenes = await _fetch_scenes(db, novel_id)

        # 输出到控制台
        print("\n" + "=" * 60)
        print(f"项目 ID: {novel_id}")
        print(f"项目标题: {PROJECT_TITLE}")
        print(f"生成范围: 第 {START_CHAPTER}-{END_CHAPTER} 章")
        print(f"LLM 模型: {settings.llm_model}")
        print("-" * 60)
        print(f"生成的 PlotThread 数: {gen_result.get('total_threads', 0)}")
        print(f"生成的 OutlineArc 数: {gen_result.get('total_arcs', 0)}")
        print(f"生成的 Scene 数: {gen_result.get('total_scenes', 0)}")
        print(f"scenes 表记录数: {len(scenes)}")
        print("=" * 60)

        gen_scenes = gen_result.get("scenes", [])
        if gen_scenes:
            print("\n生成返回的 Scene 列表:")
            for s in gen_scenes:
                print(
                    f"  - [Scene {s.get('scene_index')}] {s.get('title') or '(无标题)'}"
                )
        else:
            print("\n生成返回的 Scene 列表为空。")

        if scenes:
            print("\nscenes 表详情:")
            for s in scenes:
                print(f"\n[Scene {s['scene_index']}] {s['title'] or '(无标题)'}")
                print(f"  goal: {s['goal'] or '(空)'}")
                print(f"  core_conflict: {s['core_conflict'] or '(空)'}")
                print(f"  emotional_beat: {s['emotional_beat'] or '(空)'}")
                print(f"  must_happen: {s['must_happen'] or '(空)'}")
                print(f"  must_not_happen: {s['must_not_happen'] or '(空)'}")
                print(f"  narrative_tag: {s['narrative_tag']}")
        else:
            print("\nscenes 表为空。")

        warnings = gen_result.get("warnings", [])
        if warnings:
            print("\n生成警告:")
            for w in warnings:
                print(f"  - {w}")

        # 保存到 markdown
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        record_dir = Path(__file__).resolve().parent.parent.parent / "docs" / "acceptance"
        record_dir.mkdir(parents=True, exist_ok=True)
        record_path = record_dir / f"writing-extraction-lotm-ch1-3-{ts}.md"

        lines = [
            "# 手工写作工作台 — 真实 LLM 场景卡提取验收",
            "",
            f"- 项目: {PROJECT_TITLE}",
            f"- 项目 ID: `{novel_id}`",
            f"- 章节范围: 第 {START_CHAPTER}-{END_CHAPTER} 章",
            f"- LLM 模型: `{settings.llm_model}`",
            f"- 运行时间: {datetime.now(UTC).isoformat()}",
            "",
            "## 生成结果统计",
            "",
            f"- PlotThread 生成数: {gen_result.get('total_threads', 0)}",
            f"- OutlineArc 生成数: {gen_result.get('total_arcs', 0)}",
            f"- 生成返回 Scene 数: {gen_result.get('total_scenes', 0)}",
            f"- scenes 表记录数: **{len(scenes)}**",
            "",
        ]

        if warnings:
            lines.extend(["## 警告", ""])
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

        lines.extend(["## Scene 卡详情", ""])
        if scenes:
            for s in scenes:
                lines.append(f"### Scene {s['scene_index']}: {s['title'] or '(无标题)'}")
                lines.append("")
                lines.append(f"- **goal**: {s['goal'] or '(空)'}")
                lines.append(f"- **core_conflict**: {s['core_conflict'] or '(空)'}")
                lines.append(f"- **emotional_beat**: {s['emotional_beat'] or '(空)'}")
                lines.append(f"- **must_happen**: {s['must_happen'] or '(空)'}")
                lines.append(f"- **must_not_happen**: {s['must_not_happen'] or '(空)'}")
                lines.append(f"- **narrative_tag**: {s['narrative_tag']}")
                lines.append("")
        else:
            lines.append("scenes 表为空。\n")

        lines.extend(["## 原始生成返回", "", "```json", str(gen_result), "```", ""])

        record_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n验收记录已保存: {record_path}")

    await manager.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        logger.exception("验收脚本异常退出: %s", exc)
        sys.exit(1)

"""
RAG 混合检索真实数据验收脚本 — 《诡秘之主 第一部》第 1-3 章

本脚本：
- 读取本地《诡秘之主 第一部 小丑.txt》前 3 章；
- 创建临时项目并写入 writing_drafts；
- 重建 RAG 索引；
- 执行若干关键词/人物查询，验证 novel_id 隔离、top_k 上限、降级提示、
  召回结果均来自第 1-3 章。

注意：本脚本使用真实文件路径；若文件不存在会跳过并打印提示。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import modules.rag.models  # noqa: F401
from app.main import _register_container_services
from core.base import Base
from core.config import get_settings
from core.container import reset as reset_container
from modules.project.models import Project
from modules.rag.facade import get_index_status, index_chapter, retrieve
from modules.writing.facade import create_draft

REAL_FILE_PATH = Path("/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt")
CHAPTERS = 3


def _load_chapters() -> list[dict]:
    if not REAL_FILE_PATH.exists():
        return []

    from modules.imports.parsers import parse_txt

    file_bytes = REAL_FILE_PATH.read_bytes()
    all_chapters = parse_txt(file_bytes)
    return all_chapters[:CHAPTERS]


async def _main() -> None:
    reset_container()
    _register_container_services()

    engine = create_async_engine(
        get_settings().database_url,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    chapters = _load_chapters()
    if not chapters:
        print(f"⚠️ 跳过验收：真实文件不存在 {REAL_FILE_PATH}")
        return

    async with factory() as db:
        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="RAG 验收 — 诡秘之主 第一部",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗、悬疑",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db.add(project)
        await db.flush()
        project_id = str(pid)

        for idx, ch in enumerate(chapters, start=1):
            await create_draft(
                db,
                novel_id=project_id,
                chapter_index=idx,
                title=ch.get("title") or f"第{idx}章",
                content=ch.get("content", ""),
            )

        await db.flush()

        total_chunks = 0
        for idx in range(1, CHAPTERS + 1):
            count = await index_chapter(db, project_id, idx)
            total_chunks += count
            print(f"  第 {idx} 章索引完成：{count} 个 chunk")

        status = await get_index_status(db, project_id)
        print(
            f"\n索引状态：total={status['total']}, "
            f"embedding_failed={status['embedding_failed_count']}, "
            f"degraded={status['degraded']}"
        )

        queries = [
            "克莱恩 值夜者",
            "廷根市",
            "源堡",
            "xyzzy_nonexistent_term_42",
        ]
        top_k = 5
        all_pass = True

        for query in queries:
            result = await retrieve(
                db,
                project_id,
                query,
                mode="search",
                top_k=top_k,
            )
            print(f"\n查询：{query!r}")
            print(f"  返回 {len(result.chunks)} 条结果，degraded={result.degraded}")
            if len(result.chunks) > top_k:
                print(f"  ❌ 结果数 {len(result.chunks)} 超过 top_k={top_k}")
                all_pass = False
            for chunk in result.chunks:
                if chunk.novel_id != project_id:
                    print(f"  ❌ 跨 novel_id 泄漏：{chunk.novel_id}")
                    all_pass = False
                if chunk.chapter_index is not None and not (
                    1 <= chunk.chapter_index <= CHAPTERS
                ):
                    print(f"  ❌ 召回章节越界：{chunk.chapter_index}")
                    all_pass = False
            if result.degraded and not result.warnings:
                print("  ❌ degraded=True 但无 warnings")
                all_pass = False

        # 跨 novel_id 隔离：用随机 novel_id 查询应返回空
        other_result = await retrieve(
            db,
            str(uuid.uuid4()),
            "克莱恩",
            mode="search",
            top_k=top_k,
        )
        if other_result.chunks:
            print("\n❌ 跨 novel_id 隔离失败：随机项目返回了结果")
            all_pass = False
        else:
            print("\n✅ 跨 novel_id 隔离通过")

        if all_pass:
            print(f"\n✅ RAG 真实数据验收通过（共 {total_chunks} 个 chunk）")
        else:
            print("\n❌ RAG 真实数据验收未通过")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())

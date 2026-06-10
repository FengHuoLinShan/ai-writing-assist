"""
Context Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.markdown_renderer import (
    render_context_markdown as _render_markdown,
)
from modules.context.services import ContextCompiler

_compiler = ContextCompiler()


def render_context_markdown(context: StructureContextBundle) -> str:
    """将结构化上下文渲染为 Markdown

    同步函数，将 StructureContextBundle 渲染为分层 Markdown，
    适合直接放入 LLM Prompt。

    Args:
        context: Context Compiler 输出的结构化上下文包

    Returns:
        str: 渲染后的 Markdown 文本
    """
    return _render_markdown(context)


async def compile_structure_context(
    db: AsyncSession,
    novel_id: str,
    task: str,
    scope: str,
    chapter_index: int | None = None,
    arc_id: str | None = None,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    enable_geo_filter: bool = False,
    viewpoint_character_id: str | None = None,
) -> StructureContextBundle:
    """编译结构化创作上下文

    Context Compiler 的核心入口。
    根据 scope 从各模块按需加载数据，组装为结构化的上下文包。

    Args:
        db: 数据库 session
        novel_id: 项目 ID (UUID hex string)
        task: 创作任务描述，如「生成章节卡」、「生成剧情线」
        scope: 编译范围
            - project: 只加载项目信息
            - world: 项目 + 世界对象 + 关系
            - world_character: 项目 + 世界对象 + 人物 + 人物知识
            - arc: 加载篇章所有相关上下文
            - chapter: 加载单章所有相关上下文
            - full: 加载所有上下文（有限预算）
        chapter_index: 当前章节索引（scope=chapter 时推荐提供）
        arc_id: 当前篇章 ID（scope=arc 时推荐提供）
        entity_ids: 指定关注的世界对象 ID 列表
        character_ids: 指定关注的人物 ID 列表
        location_ids: 指定关注的地点 ID 列表
        reveal_mode: 揭示模式
            - author_safe: 隐藏 hidden_truth（默认）
            - author_full: 显示所有信息，标注作者视角
            - reader: 只显示读者已知信息
            - character: 按指定角色的知识边界过滤
        enable_geo_filter: 是否启用地缘可达性过滤（默认关闭）
        viewpoint_character_id: 视角人物 ID（reveal_mode="character" 时必填）

    Returns:
        StructureContextBundle — 结构化创作上下文包
    """
    options = CompileOptions(
        novel_id=novel_id,
        task=task,
        scope=scope,
        chapter_index=chapter_index,
        arc_id=arc_id,
        entity_ids=entity_ids,
        character_ids=character_ids,
        location_ids=location_ids,
        reveal_mode=reveal_mode,
        enable_geo_filter=enable_geo_filter,
        viewpoint_character_id=viewpoint_character_id,
    )
    return await _compiler.compile(db, options)

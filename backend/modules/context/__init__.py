# modules/context — 上下文编译模块
# Context Compiler 是系统最核心的智能模块之一。
# RAG 负责找资料，Context Compiler 决定哪些资料真正交给模型。
# 本模块同时拥有 AI 参考资料确认和自动上下文快照审计记录。

from __future__ import annotations

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.facade import (
    compile_structure_context,
    compile_with_tiers,
    render_compiled_context_markdown,
    render_context_markdown,
)
from modules.context.schemas import (
    ContextCompileRequest,
    ContextRenderRequest,
    ContextRenderResponse,
    ContextSectionItem,
    ContextTierCompileResponse,
)

__all__ = [
    "CONTEXT_BUDGET",
    "ContextCompileRequest",
    "ContextRenderRequest",
    "ContextRenderResponse",
    "ContextSectionItem",
    "ContextTierCompileResponse",
    "StructureContextBundle",
    "compile_structure_context",
    "compile_with_tiers",
    "render_compiled_context_markdown",
    "render_context_markdown",
]

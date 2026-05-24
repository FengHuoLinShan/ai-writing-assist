# modules/context — 上下文编译模块
# Context Compiler 是系统最核心的智能模块之一。
# RAG 负责找资料，Context Compiler 决定哪些资料真正交给模型。
# 本模块没有自己的数据表，它是纯组合层。

from __future__ import annotations

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.facade import (
    compile_structure_context,
    render_context_markdown,
)
from modules.context.schemas import (
    ContextCompileRequest,
    ContextCompileResponse,
    ContextRenderRequest,
    ContextRenderResponse,
)

__all__ = [
    "CONTEXT_BUDGET",
    "ContextCompileRequest",
    "ContextCompileResponse",
    "ContextRenderRequest",
    "ContextRenderResponse",
    "StructureContextBundle",
    "compile_structure_context",
    "render_context_markdown",
]

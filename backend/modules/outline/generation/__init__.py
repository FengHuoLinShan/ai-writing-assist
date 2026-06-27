"""Outline AI 剧情结构生成子包。

将 PlotStructureGenerator 拆分为专业化模块：
- context_builder: 加载并组装生成所需的上下文
- models: LLM 输出用的 Pydantic 模型
- parser: 调用 LLM 并解析/校验输出
- persister: 将解析结果持久化到 outline 各表
"""

from modules.outline.generation.context_builder import (
    PlotStructureContext,
    PlotStructureContextBuilder,
)
from modules.outline.generation.models import (
    ForeshadowingPlan,
    GeneratedArc,
    GeneratedOutput,
    GeneratedScene,
    GeneratedThread,
    OffscreenProgress,
    Question,
    RevealPlan,
    Risk,
)
from modules.outline.generation.parser import (
    ParsedPlotStructure,
    PlotStructureParser,
)
from modules.outline.generation.persister import (
    PersistResult,
    PlotStructurePersister,
)

__all__ = [
    "PlotStructureContext",
    "PlotStructureContextBuilder",
    "GeneratedThread",
    "GeneratedArc",
    "GeneratedScene",
    "ForeshadowingPlan",
    "RevealPlan",
    "OffscreenProgress",
    "Risk",
    "Question",
    "GeneratedOutput",
    "ParsedPlotStructure",
    "PlotStructureParser",
    "PersistResult",
    "PlotStructurePersister",
]

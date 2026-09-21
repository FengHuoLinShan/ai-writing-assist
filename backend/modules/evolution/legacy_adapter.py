"""deep_import 入口适配层（V4 E07.e，计划 §7.2 入口重定向）。

旧 deep-import 请求参数映射为演化 run 的注册负载，返回**真实新回执
语义**的响应形状与 deprecation 提示。本层只做映射，不改写旧 API 路由
——实际重定向按计划排在项目级 canary 验证之后（E07.c→E07.e 顺序），
届时旧路由以薄适配调用本层，不再拥有独立编排。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEPRECATION_NOTICE = (
    "deep_import 独立编排已进入退役流程：请求将改由演化引擎（evolution）"
    "执行并返回新回执；本接口保留兼容参数，不再拥有独立运行所有权。"
)


class LegacyDeepImportRequest(BaseModel):
    """旧 deep-import 开始请求的兼容参数面（仅映射，不新增语义）。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    import_mode: str = Field(default="full", pattern="^(full|append)$")
    chapter_indices: list[int] = Field(default_factory=list)
    requested_budget: int = Field(default=10, ge=0)


class AdaptedEvolutionStart(BaseModel):
    """映射结果：演化 run 注册负载 + 真实回执语义的响应形状。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    run_key: str
    evolution_mode: str = Field(description="bootstrap/append/revise/scoped_recompute")
    budget_total: int
    scene_steps: list[dict[str, Any]] = Field(default_factory=list)
    deprecated: bool = True
    deprecation_notice: str = DEPRECATION_NOTICE


_LEGACY_TO_EVOLUTION_MODE = {"full": "bootstrap", "append": "append"}


def adapt_deep_import_start(
    request: LegacyDeepImportRequest,
) -> AdaptedEvolutionStart:
    """把旧 deep-import 请求映射为演化 run 注册负载（E07.e 参数适配）。

    预算严格沿用旧请求的授权值（返修 R6）：预计工作量不变成授权费用——
    章节数超出预算时由演化引擎按预算分批推进/阻塞，不擅自抬额。
    """
    evolution_mode = _LEGACY_TO_EVOLUTION_MODE.get(request.import_mode, "bootstrap")
    run_key = f"legacy-{request.import_mode}-{request.novel_id[:8]}"
    return AdaptedEvolutionStart(
        novel_id=request.novel_id,
        run_key=run_key,
        evolution_mode=evolution_mode,
        budget_total=request.requested_budget,
        scene_steps=[
            {
                "scene_index": index,
                "task_type": "evolution_scene_step",
                "novel_id": request.novel_id,
                "run_key": run_key,
            }
            for index in request.chapter_indices
        ],
    )

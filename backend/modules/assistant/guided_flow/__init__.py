"""Assistant guided_flow — 确定性引导流程编排层（ADR-0032）。

流程与步骤表在服务端注册、带版本号，模型与前端均不可修改；运行期不开放
任何可由模型或前端编写的流程定义。进度由领域产物推导，不存当前步骤索引；
流程运行复用 ``AssistantRun``（运行类型见 ``runtime.PROTOCOL``），只冻结
版本、输入指纹、授权范围与停点原因。停点只在：真实选择、扩大授权、硬性阻断。

依赖方向（ADR-0031，不新增边）：本包只经已注册操作目录或 DI 触达
World/Story/Writing/Evidence；Assistant 禁止直接 import World。
"""

from modules.assistant.guided_flow import flows as _flows  # noqa: F401  注册流程表
from modules.assistant.guided_flow.registry import (
    FLOWS,
    FlowDefinition,
    StepDefinition,
    require_flow,
)
from modules.assistant.guided_flow.runtime import (
    abandon,
    active_run,
    advance,
    available_for,
    enabled,
    save_settings,
    start,
    view,
)

__all__ = [
    "FLOWS",
    "FlowDefinition",
    "StepDefinition",
    "abandon",
    "active_run",
    "advance",
    "available_for",
    "enabled",
    "require_flow",
    "save_settings",
    "start",
    "view",
]

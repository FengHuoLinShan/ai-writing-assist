"""Assistant 操作注册表装配件（AO-5 第二批 / ADR-0031）。

领域插件文件只导出纯数据 ``OPERATIONS_SPEC``（label/schema/prepare/apply 及
可选 permission/read_result/revision），不再 import ``modules.assistant``；
只有本装配件（仅被组合根 ``app/bootstrap.py`` 导入）依赖
``modules.assistant.contracts.AssistantOperation`` 并按原构造语义物化注册表，
容器注册仍只在组合根完成。操作名、参数 schema、目标函数与权限逐字段等于
装配位置移动前的产物，assistant 消费侧零改动。
"""

from modules.assistant.contracts import AssistantOperation
from modules.evidence.forecast import OPERATIONS_SPEC as _EVIDENCE_FORECAST
from modules.project.assistant_dedup_tool import OPERATIONS_SPEC as _PROJECT_DEDUP
from modules.project.assistant_tools import OPERATIONS_SPEC as _PROJECT
from modules.story.assistant_information_tools import (
    OPERATIONS_SPEC as _STORY_INFORMATION,
)
from modules.story.assistant_planning_tools import OPERATIONS_SPEC as _STORY_PLANNING
from modules.story.assistant_structure_workflow import (
    OPERATIONS_SPEC as _STORY_STRUCTURE,
)
from modules.story.assistant_tools import OPERATIONS_SPEC as _STORY
from modules.writing.assistant_candidate_tools import (
    OPERATIONS_SPEC as _WRITING_CANDIDATE,
)
from modules.writing.assistant_generation_tool import (
    OPERATIONS_SPEC as _WRITING_GENERATION,
)
from modules.writing.assistant_tools import OPERATIONS_SPEC as _WRITING

_FIELDS = frozenset(AssistantOperation.__dataclass_fields__)


def _materialize(specs: dict[str, dict]) -> dict[str, AssistantOperation]:
    """按声明数据构造 AssistantOperation；未知字段失败关闭，不静默丢弃。"""
    built: dict[str, AssistantOperation] = {}
    for name, spec in specs.items():
        unknown = set(spec) - _FIELDS
        if unknown:
            raise ValueError(f"操作 {name} 声明了未知字段: {sorted(unknown)}")
        built[name] = AssistantOperation(**spec)
    return built


# 逐项物化；bootstrap 按与改造前完全相同的合并顺序取用。
project_dedup_operations = _materialize(_PROJECT_DEDUP)
story_information_operations = _materialize(_STORY_INFORMATION)
writing_operations = _materialize(_WRITING)
writing_generation_operations = _materialize(_WRITING_GENERATION)
writing_candidate_operations = _materialize(_WRITING_CANDIDATE)
project_operations = _materialize(_PROJECT)
story_operations = _materialize(_STORY)
story_structure_operations = _materialize(_STORY_STRUCTURE)
story_planning_operations = _materialize(_STORY_PLANNING)
evidence_forecast_operations = _materialize(_EVIDENCE_FORECAST)

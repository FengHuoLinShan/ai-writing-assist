"""WorldGenerationCenterService：组合各阶段 mixin 的对外门面。"""

from __future__ import annotations

from typing import Any

from infrastructure.llm.client import LLMClient
from modules.world.contracts import GenerationBackgroundProvider
from modules.world.services.worldbuilding.conflict_queue_service import (
    ConflictQueueService,
)
from modules.world.services.worldbuilding.generation_center.chat import (
    _ChatStageMixin,
)
from modules.world.services.worldbuilding.generation_center.convergence import (
    _ConvergenceStageMixin,
)
from modules.world.services.worldbuilding.generation_center.design_iteration import (
    _WorldDesignStageMixin,
)
from modules.world.services.worldbuilding.generation_center.exploration import (
    _ExplorationStageMixin,
)
from modules.world.services.worldbuilding.generation_center.inspection import (
    _InspectionStageMixin,
)
from modules.world.services.worldbuilding.generation_center.llm_runs import (
    _LlmRunStageMixin,
)
from modules.world.services.worldbuilding.generation_center.preparation import (
    _PrepareStageMixin,
)
from modules.world.services.worldbuilding.generation_center.suggestions import (
    _SuggestionStageMixin,
)
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    GenerationPromptTemplateService,
)
from modules.world.services.worldbuilding.page_template_service import (
    WorldBiblePageTemplateService,
)
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.world_bible_service import WorldBibleService


class WorldGenerationCenterService(
    _PrepareStageMixin,
    _LlmRunStageMixin,
    _SuggestionStageMixin,
    _ConvergenceStageMixin,
    _ExplorationStageMixin,
    _InspectionStageMixin,
    _ChatStageMixin,
    _WorldDesignStageMixin,
):
    def __init__(
        self,
        *,
        suggestion_service: SuggestionQueueService | None = None,
        bible_service: WorldBibleService | None = None,
        lifecycle_service: WorldBibleLifecycleService | None = None,
        page_template_service: WorldBiblePageTemplateService | None = None,
        prompt_template_service: GenerationPromptTemplateService | None = None,
        conflict_service: ConflictQueueService | None = None,
        llm_client: LLMClient | None = None,
        generation_background_provider: GenerationBackgroundProvider | None = None,
    ) -> None:
        self._suggestions = suggestion_service or SuggestionQueueService()
        self._bible = bible_service or WorldBibleService()
        self._lifecycle = lifecycle_service or WorldBibleLifecycleService()
        self._page_templates = page_template_service or WorldBiblePageTemplateService()
        self._prompt_templates = (
            prompt_template_service or GenerationPromptTemplateService()
        )
        self._conflicts = conflict_service or ConflictQueueService()
        self._llm_client = llm_client
        self._generation_background_provider = generation_background_provider
        self.last_design_review_receipt: dict[str, Any] | None = None




# ``_source_refs``（staticmethod）以类名调用同 mixin 的静态方法；
# mixin 不能反向导入本模块，类创建后回填模块级名字供运行时查找，
# 调用点文本保持拆分前原样。
from modules.world.services.worldbuilding.generation_center import (  # noqa: E402
    suggestions as _suggestions_stage,
)

_suggestions_stage.WorldGenerationCenterService = WorldGenerationCenterService

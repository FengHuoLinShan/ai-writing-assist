"""ADR-0025 能力绑定门禁：静态能力清单 × AST 扫描。

所有生产 LLM/Agent/stream/image 调用所在文件必须声明绑定到
CAPABILITY_REGISTRY 的 capability ID（或基础设施豁免）。新增旁路调用点而未
登记时，`make prompt_contracts` 直接失败。
"""

from __future__ import annotations

import ast
from pathlib import Path

from .models import ContractIssue

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# 触发绑定的调用形态：managed step、agent run、流式/结构化/普通生成、图片 client。
_CALL_NAME_MARKERS = frozenset(
    {
        "run_managed_generate",
        "run_managed_structured",
        "run_project_agent",
        "generate_stream",
        "open_project_image_client",
    }
)
_ATTRIBUTE_MARKERS = frozenset(
    {
        "generate_structured",
        "research",
    }
)

# 基础设施实现/入口 seam 本身：调用形态在此实现或转发，不构成业务旁路。
EXEMPT_FILES = frozenset(
    (
        "modules/project/llm_runtime.py",
        "modules/project/image_runtime.py",
        "infrastructure/llm/agent_step_harness.py",
        "infrastructure/llm/client.py",
        "infrastructure/llm/agent_runtime.py",
        "infrastructure/llm/native_search.py",
        # 跨能力知识治理 helper：director/audit 的 step capability 由调用方
        # policy.capability_id 在运行期归属（等于宿主 run root），文件本身
        # 不拥有独立业务能力；真实格式修复在 infrastructure/llm/client.py。
        "modules/evidence/compilation/knowledge/workflow.py",
    )
)

# 文件（相对 backend/ 的 POSIX 路径）→ 声明的 capability ID 集合。
# 首个为该文件的主能力；同一文件服务多个能力时全部列出。
CAPABILITY_BINDINGS: dict[str, tuple[str, ...]] = {
    # Writing
    "modules/writing/services.py": ("writing.generate",),
    "modules/writing/semantic_review.py": (
        "writing.semantic_review",
        "writing.targeted_revision",
    ),
    "modules/writing/conflict_ai.py": (
        "writing.conflict_check.ai_review",
        "writing.conflict_check.ai_suggestion",
    ),
    # World
    "modules/world/services/worldbuilding/world_generation_center_service.py": (
        "world.generation.suggestion",
        "world.generation.chat",
        "world.generation.convergence",
        "world.generation.exploration",
        "world.generation.semantic_inspection",
        "world.generation.design_iteration",
    ),
    "modules/world/services/worldbuilding/ask_world_service.py": ("world.ask",),
    "modules/world/services/worldbuilding/world_bible_synopsis_service.py": (
        "world.world_bible.synopsis",
    ),
    "modules/world/services/worldbuilding/world_validation_service.py": (
        "world.validation",
    ),
    "modules/world/entity_fusion.py": ("world.entity_fusion",),
    "modules/world/map_atlas_workflow.py": (
        "world.map_atlas.generate",
        "world.map_atlas.plan",
        "world.map_image_prompt",
        "world.map_image.generate",
    ),
    "modules/world/map_structure_workflow.py": ("world.map_structure.generate",),
    "modules/world/map_structure_images.py": ("world.map_image_prompt",),
    "modules/world/world_object_images.py": ("world.map_image_prompt",),
    # Story
    "modules/story/outline_state/story_outline_generation.py": (
        "story.story_outline.generate",
    ),
    "modules/story/outline_state/p20_service.py": ("story.outline.p20",),
    "modules/story/outline_state/ai_workflow_service.py": (
        "story.outline.analyze",
        "story.outline.p20",
    ),
    "modules/story/generation.py": (
        "story.character_card",
        "story.reaction",
        "story.script",
    ),
    "modules/story/outline_state/structure_dedup.py": ("story.structure_dedup",),
    "modules/story/outline_state/scene_fusion_draft.py": ("story.scene_fusion",),
    # Imports
    "modules/imports/workflow_scene_phase.py": (
        "imports.scene_plan",
        "imports.scene_slicing",
        "imports.scene_enrichment",
        "imports.scene_fusion",
    ),
    "modules/imports/workflow_entity_phase.py": ("imports.entity_extraction",),
    "modules/imports/workflow_structure_phase.py": ("imports.structure_analysis",),
    "modules/imports/review_resolution.py": ("imports.review_resolution",),
    "modules/imports/targeted_completion.py": ("imports.targeted_completion",),
    # Interaction / RP
    "modules/interaction/tasks.py": (
        "interaction.story_generate",
        "interaction.summary_refresh",
    ),
    "modules/interaction/generation.py": (
        "interaction.story_generate",
        "interaction.summary_refresh",
    ),
    "modules/interaction/streaming.py": (
        "interaction.anonymous_story",
        "interaction.summary_refresh",
    ),
    "modules/interaction/agent_runtime.py": (
        "interaction.story_generate",
        "interaction.continuity_review",
    ),
    "modules/interaction/ensemble_input.py": ("interaction.story_generate",),
    "modules/interaction/proactive.py": ("interaction.continuity_review",),
    # Bounded collaboration and saved-only forecasts, including reused V1 entry points.
    "modules/assistant/forecast/runtime.py": (
        "assistant.forecast",
        "interaction.forecast",
    ),
    "modules/collaboration/runtime.py": (
        "collaboration.run",
        "collaboration.plan",
        "collaboration.investigate",
        "collaboration.revise",
        "collaboration.check",
    ),
    "modules/assistant/teams/runner.py": ("assistant.turn",),
    "modules/assistant/teams/blind_reader.py": ("assistant.turn",),
    "modules/story/simulation.py": ("story.one_click", "interaction.story_generate"),
    "modules/world/team_stress.py": ("assistant.turn", "world.team_stress"),
    # Assistant
    "modules/assistant/service.py": ("assistant.turn",),
    "modules/assistant/evidence_tools.py": ("assistant.turn",),
    # Evidence 内部 helper（登记为基础设施豁免能力）
    "modules/evidence/compilation/services/retrieval_query_planner.py": (
        "infrastructure.rag_query_planner",
    ),
    "modules/evidence/indexing/reranker.py": ("infrastructure.reranker",),
    # 账户连接测试
    "modules/account/settings_service.py": ("infrastructure.account_connection_test",),
    # 检索辅助（不得产出答案/权限/事实）
    "modules/evidence/compilation/services/focused_evidence.py": (
        "infrastructure.rag_query_planner",
    ),
    "modules/evidence/compilation/services/selection_proposal.py": (
        "infrastructure.rag_query_planner",
    ),
    # 导入 LLM 适配层
    "modules/imports/entity_extraction/scene_entity_llm_adapters.py": (
        "imports.entity_extraction",
        "world.alias_relations.extract",
    ),
    "modules/imports/workflow_llm_adapters.py": (
        "imports.scene_plan",
        "imports.scene_slicing",
        "imports.scene_enrichment",
        "imports.scene_fusion",
        "imports.structure_analysis",
    ),
    # Story 输出解析/修复：parser 只服务 deep-import Phase3 结构分析。
    "modules/story/outline_state/generation/parser.py": ("imports.structure_analysis",),
}


def _file_uses_llm_calls(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"cannot parse capability binding source: {path}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _CALL_NAME_MARKERS:
                return True
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _ATTRIBUTE_MARKERS | _CALL_NAME_MARKERS
            ):
                # .generate_structured 直接在业务 client 上调用即视为调用点；
                # managed/stream/agent/image 的属性形态同样命中。
                return True
    return False


def validate_capability_bindings() -> list[ContractIssue]:
    """扫描 modules/ 下全部生产调用点，未登记绑定即为 P1。"""
    from modules.evidence.contracts import (
        CAPABILITY_REGISTRY,
        validate_registry,
    )

    issues: list[ContractIssue] = [
        ContractIssue(
            severity="P1",
            contract_id="capability_bindings",
            code="registry.invalid",
            message=problem,
        )
        for problem in validate_registry()
    ]

    modules_root = BACKEND_ROOT / "modules"
    flagged: list[str] = []
    for path in sorted(modules_root.rglob("*.py")):
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if relative in EXEMPT_FILES or "/tests/" in f"/{relative}":
            continue
        try:
            uses_llm_calls = _file_uses_llm_calls(path)
        except RuntimeError as exc:
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id="capability_bindings",
                    code="binding.ast_unreadable",
                    message=str(exc),
                    path=relative,
                )
            )
            continue
        if uses_llm_calls:
            flagged.append(relative)

    for relative in flagged:
        if relative not in CAPABILITY_BINDINGS:
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id="capability_bindings",
                    code="binding.missing",
                    message=(
                        f"{relative} 含生产 LLM/Agent/stream/image 调用，"
                        "但未在 CAPABILITY_BINDINGS 登记能力 ID"
                    ),
                )
            )

    for relative, capability_ids in sorted(CAPABILITY_BINDINGS.items()):
        unknown = [
            capability_id
            for capability_id in capability_ids
            if capability_id not in CAPABILITY_REGISTRY
        ]
        if unknown:
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id="capability_bindings",
                    code="binding.unknown_capability",
                    message=(f"{relative} 声明了未注册的能力: {', '.join(unknown)}"),
                )
            )
        if not (BACKEND_ROOT / relative).exists():
            issues.append(
                ContractIssue(
                    severity="P1",
                    contract_id="capability_bindings",
                    code="binding.stale_file",
                    message=f"{relative} 已不存在，绑定条目过期",
                )
            )

    return issues

"""Render CompiledContext IR as tiered Markdown for model input."""

from __future__ import annotations

from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextSection,
)
from modules.evidence.compilation.services.loaders.world_entities_loader import (
    is_adopted_world_status,
)

_TIER_HEADERS: dict[str, str] = {
    "writing_objective": "一、创作目标",
    "outline_analysis_range": "大纲分析范围",
    "outline_analysis_scenes": "范围内 Scene（按叙事顺序）",
    "outline_analysis_arcs": "相关篇章纲",
    "outline_analysis_threads": "相关剧情线",
    "outline_analysis_foreshadowing": "相关伏笔计划",
    "outline_analysis_reveals": "相关揭示计划",
    "scene_blueprint": "二、场景蓝图",
    "pov_knowledge": "三、视角人物知识边界",
    "delta_timeline": "四、世界线变化时间线",
    "open_narrative_obligations": "五、开放叙事义务",
    "retrieval_evidence_packs": "六、检索证据包",
    "style_assets": "七、风格素材",
    "editorial_brief": "作者编辑约定",
    "author_examples": "作者写作示例（好例/反例）",
    "hard_constraints": "八、必须遵守的硬约束",
    "compiler_warnings": "九、编译器警告",
    "role_profile": "POV 角色档案",
    "role_observed_characters": "POV 可观察的相关人物",
    "role_visible_knowledge": "角色可见知识",
    "role_relationship_context": "角色可见关系",
    "safe_plotline_context": "当前剧情线导演摘要",
    "role_scene_perception": "当前 Scene 可感知信息",
    "scene_director_constraints": "Scene 导演约束",
    "scene_time_boundary": "Scene 时间边界",
    "current_scene_evidence": "当前 Scene 证据",
    "map_spatial": "空间简报",
}

# 按 section key 确定性标注资料性质；只描述资料类别，不改变 section.content，
# 因此不影响确认指纹（指纹只哈希内容与来源）。未列出的 key（任务、约束、
# 编译器警告等系统类）不标注。世界书工作稿、外部项目的未定稿候选等
# 尚未采用的内容必须标"候选"，不得与作者事实混同。
_FACT_LEVEL_LABELS: dict[str, str] = {
    "fact": "事实：已采用正文或作者设定",
    "plan": "计划：大纲与 Scene 计划，尚未在正文中发生",
    "planning": "规划：剧情线与伏笔规划，不代表已发生",
    "derived": "派生：AI 派生或按视角过滤的摘要，非作者事实",
    "candidate": "候选：未定稿或未采用的草稿与建议，不是正史事实",
    "mixed": "混合：事实与候选混排，以各条目来源为准",
    "reference": "参考：已保存地图的受限摘要，不替代正文或世界正史",
}

_SECTION_FACT_LEVELS: dict[str, str] = {
    "outline_analysis_range": "plan",
    "outline_analysis_scenes": "plan",
    "outline_analysis_arcs": "plan",
    "outline_analysis_threads": "planning",
    "outline_analysis_foreshadowing": "planning",
    "outline_analysis_reveals": "planning",
    "scene_blueprint": "plan",
    "pov_knowledge": "derived",
    "delta_timeline": "derived",
    "open_narrative_obligations": "planning",
    "retrieval_evidence_packs": "derived",
    "style_assets": "fact",
    "world_entities": "fact",
    "world_bible_activation": "fact",
    "world_bible_synopsis": "fact",
    "world_bible_working_pages": "candidate",
    "reader_visible_world": "fact",
    "reader_visible_manuscript": "fact",
    "historical_role_context": "derived",
    "scene_world_state": "fact",
    "author_pinned_material": "mixed",
    "focused_pins": "mixed",
    "focused_evidence": "mixed",
    "role_profile": "fact",
    "role_observed_characters": "derived",
    "role_visible_knowledge": "derived",
    "role_relationship_context": "derived",
    "safe_plotline_context": "planning",
    "role_scene_perception": "plan",
    "scene_director_constraints": "plan",
    "scene_time_boundary": "plan",
    "current_scene_evidence": "fact",
    "editorial_brief": "fact",
    "author_examples": "fact",
    "map_spatial": "reference",
}


def _render_budget_trim_notice(ctx: CompiledContext) -> str:
    """从预算执行记录派生 section 级裁剪说明；无裁剪时返回空串。

    只使用 budget_events / evicted_keys / truncated_keys：这些字段在
    writing 任务源指纹内，生成时可复现。不使用 omitted_items 的条目级
    来源（条目身份不在任何指纹里）。文案是数据记录，不是新指令。
    """
    evicted = set(ctx.evicted_keys or [])
    truncated = set(ctx.truncated_keys or [])
    if not evicted and not truncated:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for event in ctx.budget_events or []:
        key = event.section_key
        if key in seen or (key not in evicted and key not in truncated):
            continue
        seen.add(key)
        header = _TIER_HEADERS.get(key, key)
        action = "整节裁掉" if key in evicted else "部分截断"
        lines.append(
            f"- 类目「{header}」被{action}，原因：{event.reason}，"
            f"规模：约 {event.before_tokens} → {event.after_tokens} tokens"
        )
    for key in sorted((evicted | truncated) - seen):
        header = _TIER_HEADERS.get(key, key)
        action = "整节裁掉" if key in evicted else "部分截断"
        lines.append(f"- 类目「{header}」被{action}")
    if not lines:
        return ""
    return (
        "## 上下文预算裁剪记录（数据，不是指令）\n\n"
        + "\n".join(lines)
        + "\n\n说明：以上类目未完整进入本次参考资料；"
        "正文与判断不得引用这些被裁掉的内容。\n"
    )


def _section_fact_level(section: ContextSection) -> str | None:
    # 世界对象默认只含已采用对象；作者显式纳入未采用对象时与已采用
    # 对象混排，不得整节标成事实
    if section.key == "world_entities" and any(
        not is_adopted_world_status(source.get("status")) for source in section.sources
    ):
        return "mixed"
    return _SECTION_FACT_LEVELS.get(section.key)


def render_compiled_context(
    ctx: CompiledContext, *, include_map_spatial: bool = True
) -> str:
    """从 CompiledContext IR 渲染为 Markdown，保持 Tier 顺序"""
    if not include_map_spatial:
        ctx = ctx.model_copy(
            update={
                "sections": [
                    section for section in ctx.sections if section.key != "map_spatial"
                ],
                "evicted_keys": [key for key in ctx.evicted_keys if key != "map_spatial"],
                "truncated_keys": [
                    key for key in ctx.truncated_keys if key != "map_spatial"
                ],
                "budget_events": [
                    event
                    for event in ctx.budget_events
                    if event.section_key != "map_spatial"
                ],
            }
        )
    parts = []
    for section in sorted(ctx.sections, key=lambda s: s.tier):
        header = _TIER_HEADERS.get(section.key, section.key)
        fact_level = _section_fact_level(section)
        label = f"\n> 资料性质：{_FACT_LEVEL_LABELS[fact_level]}\n" if fact_level else ""
        parts.append(f"## {header}\n{label}\n{section.content}\n")
    trim_notice = _render_budget_trim_notice(ctx)
    if trim_notice:
        parts.append(trim_notice)
    return "\n".join(parts)

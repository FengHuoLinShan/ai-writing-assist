"""
Context Markdown 渲染器

将 StructureContextBundle 渲染为分层 Markdown，适合直接放入 LLM Prompt。

渲染结构：
1. 当前任务
2. 必须遵守的硬约束
3. 当前剧情阶段
4. 相关人物
5. 相关世界对象
6. 相关地理与历史
7. 相关剧情线
8. 相关 Memory
9. 相关伏笔与信息揭示
10. 禁止事项
11. 可用创作素材
12. 风险提示
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass

from modules.evidence.compilation.contracts import StructureContextBundle
from modules.evidence.compilation.services.compiled_context import CompiledContext

# ============================================================
# Section Renderers
# ============================================================

SECTION_TITLES: list[tuple[str, str]] = [
    ("task", "一、当前任务"),
    ("hard_constraints", "二、必须遵守的硬约束"),
    ("story_stage", "三、当前剧情阶段"),
    ("characters", "四、相关人物"),
    ("world_entities", "五、相关世界对象"),
    ("geo_history", "六、相关地理与历史"),
    ("plot_threads", "七、相关剧情线"),
    ("memory", "八、相关 Memory"),
    ("foreshadowing_reveal", "九、相关伏笔与信息揭示"),
    ("forbidden", "十、禁止事项"),
    ("creative_materials", "十一、可用创作素材"),
    ("risks", "十二、风险提示"),
]


def render_context_markdown(context: StructureContextBundle) -> str:
    """将结构化的上下文包渲染为分层 Markdown

    Args:
        context: Context Compiler 输出的结构化上下文包

    Returns:
        str: 渲染后的 Markdown 文本
    """
    sections: list[str] = []
    sections.append("# 结构化创作上下文\n")

    for section_key, section_title in SECTION_TITLES:
        renderer = _get_section_renderer(section_key)
        content = renderer(context)
        sections.append(f"## {section_title}\n")
        sections.append(content)
        sections.append("")

    return "\n".join(sections)


def _get_section_renderer(section_key: str):
    """获取段落渲染函数"""
    renderers = {
        "task": _render_task,
        "hard_constraints": _render_hard_constraints,
        "story_stage": _render_story_stage,
        "characters": _render_characters,
        "world_entities": _render_world_entities,
        "geo_history": _render_geo_history,
        "plot_threads": _render_plot_threads,
        "memory": _render_memory,
        "foreshadowing_reveal": _render_foreshadowing_reveal,
        "forbidden": _render_forbidden,
        "creative_materials": _render_creative_materials,
        "risks": _render_risks,
    }
    return renderers.get(section_key, lambda _: "无相关数据\n")


# ============================================================
# 各段落渲染实现
# ============================================================


def _render_task(context: StructureContextBundle) -> str:
    """渲染当前任务"""
    lines: list[str] = []
    lines.append(f"- **创作任务**: {context.task}")
    lines.append(f"- **编译范围**: {context.scope}")
    if context.chapter_index is not None:
        lines.append(f"- **当前章节**: 第 {context.chapter_index} 章")
    if context.arc_id:
        lines.append(f"- **所属篇章**: {context.arc_id}")
    lines.append(f"- **揭示模式**: {context.reveal_mode}")
    return "\n".join(lines) + "\n"


def _render_hard_constraints(context: StructureContextBundle) -> str:
    """渲染必须遵守的硬约束"""
    lines: list[str] = [
        "1. **不直接生成小说正文**。只生成结构化候选（JSON / 计划数据）。",
        "2. **不擅自改正史**。所有 AI 输出先进入 candidate / proposal 状态。",
        "3. **不提前揭示隐藏真相**。作者视角信息已标注，不得在读者层提前揭示。",
        "4. **不让角色知道不该知道的信息**。严格遵守 character_knowledge 边界。",
        "5. **不凭空增加重大设定**。新设定必须有合理来源或用户确认。",
        "6. **输出必须符合 JSON schema**。",
        (
            "7. **不重要对象不要升级为正史对象**。"
            "别名标记为 alias_of_existing，临时对象标记为 temporary_only。"
        ),
    ]
    return "\n".join(lines) + "\n"


def _render_story_stage(context: StructureContextBundle) -> str:
    """渲染当前剧情阶段"""
    lines: list[str] = []

    # 项目信息
    if context.project:
        p = context.project
        lines.append(f"- **项目**: {p.get('title', '')}")
        if p.get("genre"):
            lines.append(f"- **题材**: {p['genre']}")
        if p.get("tone"):
            lines.append(f"- **风格**: {p['tone']}")
        if p.get("current_stage"):
            lines.append(f"- **创作阶段**: {p['current_stage']}")
        if p.get("target_length"):
            lines.append(f"- **目标规模**: {p['target_length']}")

    # 当前章节
    if context.chapter_card:
        cc = context.chapter_card
        lines.append("")
        lines.append("- **当前章节卡**:")
        if cc.get("title"):
            lines.append(f"  - 标题: {cc['title']}")
        if cc.get("chapter_goal"):
            lines.append(f"  - 章节目标: {cc['chapter_goal']}")
        if cc.get("main_conflict"):
            lines.append(f"  - 主要冲突: {cc['main_conflict']}")
        if cc.get("plot_function"):
            lines.append(f"  - 剧情功能: {cc['plot_function']}")

    # 当前篇章
    if context.outline_arc:
        arc = context.outline_arc
        lines.append("")
        lines.append("- **当前篇章**:")
        if arc.get("title"):
            lines.append(f"  - 标题: {arc['title']}")
        if arc.get("arc_goal"):
            lines.append(f"  - 篇章目标: {arc['arc_goal']}")
        if arc.get("core_conflict"):
            lines.append(f"  - 核心冲突: {arc['core_conflict']}")

    if not lines:
        lines.append("无相关数据")

    return "\n".join(lines) + "\n"


def _render_characters(context: StructureContextBundle) -> str:
    """渲染相关人物"""
    if not context.characters:
        return "无相关数据\n"

    lines: list[str] = []
    for char in context.characters:
        name = char.get("name", "未知")
        lines.append(f"### {name}")
        if char.get("role"):
            lines.append(f"- **定位**: {char['role']}")
        if char.get("current_goal"):
            lines.append(f"- **当前目标**: {char['current_goal']}")
        if char.get("current_state"):
            lines.append(f"- **当前状态**: {char['current_state']}")
        if char.get("current_emotion"):
            lines.append(f"- **当前情绪**: {char['current_emotion']}")
        if char.get("stance"):
            lines.append(f"- **立场**: {char['stance']}")
        if char.get("voice_style"):
            lines.append(f"- **语言风格**: {char['voice_style']}")
        if char.get("behavior_rules"):
            rules = char["behavior_rules"]
            if isinstance(rules, list) and rules:
                lines.append("- **行为规则**:")
                for rule in rules:
                    if isinstance(rule, dict):
                        lines.append(f"  - {rule.get('rule', rule)}")
                    else:
                        lines.append(f"  - {rule}")
        if char.get("relationship_summary"):
            lines.append(f"- **关系摘要**: {char['relationship_summary']}")

        # 知识边界信息
        if char.get("character_id"):
            lines.append("- **知识边界**: 该人物知道的信息受 `character_knowledge` 约束")

        lines.append("")

    return "\n".join(lines)


def _render_world_entities(context: StructureContextBundle) -> str:
    """渲染相关世界对象"""
    if not context.world_entities:
        return "无相关数据\n"

    lines: list[str] = []
    for ent in context.world_entities:
        name = ent.get("name", "未知")
        etype = ent.get("entity_type", "unknown")
        lines.append(f"### [{etype}] {name}")
        if ent.get("summary"):
            lines.append(f"- **概要**: {ent['summary']}")
        if ent.get("public_info"):
            lines.append(f"- **公开信息**: {ent['public_info']}")
        if ent.get("misconception"):
            lines.append(f"- **角色误解（false_belief）**: {ent['misconception']}")
        if ent.get("hidden_truth"):
            lines.append(f"- **隐藏真相**: {ent['hidden_truth']}")
        if ent.get("importance_level"):
            lines.append(f"- **重要性**: {ent['importance_level']}")
        lines.append("")

    return "\n".join(lines)


def _render_geo_history(context: StructureContextBundle) -> str:
    """渲染地理与历史"""
    if not context.geo_locations:
        return "无相关数据\n"

    lines: list[str] = []
    for loc_data in context.geo_locations:
        loc = loc_data.get("location")
        if not loc:
            continue

        loc_name = getattr(loc, "name", loc.get("name", "未知地点"))
        loc_level = getattr(
            loc,
            "location_level",
            loc.get("location_level", "unknown"),
        )
        lines.append(f"### {loc_name} ({loc_level})")

        summary = getattr(loc, "summary", loc.get("summary"))
        if summary:
            lines.append(f"- **概述**: {summary}")
        terrain = getattr(loc, "terrain", loc.get("terrain"))
        if terrain:
            lines.append(f"- **地形**: {terrain}")
        climate = getattr(loc, "climate", loc.get("climate"))
        if climate:
            lines.append(f"- **气候**: {climate}")
        access = getattr(loc, "access_level", loc.get("access_level"))
        if access:
            lines.append(f"- **访问级别**: {access}")

        # 边（通行关系）
        edges = loc_data.get("edges", [])
        if edges:
            lines.append("- **通行关系**:")
            for edge in edges[:5]:  # 最多显示 5 条
                rel_type = getattr(edge, "relation_type", edge.get("relation_type", ""))
                direction = getattr(
                    edge,
                    "direction_label",
                    edge.get("direction_label", ""),
                )
                difficulty = getattr(
                    edge,
                    "difficulty",
                    edge.get("difficulty", ""),
                )
                parts = [rel_type]
                if direction:
                    parts.append(direction)
                if difficulty:
                    parts.append(f"[难度: {difficulty}]")
                lines.append(f"  - {' '.join(parts)}")

        # 父子地点
        parents = loc_data.get("parent_locations", [])
        if parents:
            parent_names = [getattr(p, "name", p.get("name", "?")) for p in parents]
            lines.append(f"- **上级地点**: {' > '.join(parent_names)}")

        children = loc_data.get("child_locations", [])
        if children:
            child_names = [getattr(c, "name", c.get("name", "?")) for c in children[:3]]
            lines.append(f"- **下级地点**: {', '.join(child_names)}")

        # 历史时期
        era = loc_data.get("current_era")
        if era:
            era_name = getattr(era, "name", era.get("name", ""))
            era_summary = getattr(era, "summary", era.get("summary", ""))
            if era_name:
                lines.append(f"- **当前历史时期**: {era_name}")
                if era_summary:
                    lines.append(f"  - {era_summary}")

        lines.append("")

    return "\n".join(lines)


def _render_plot_threads(context: StructureContextBundle) -> str:
    """渲染剧情线"""
    if not context.plot_threads:
        return "无相关数据\n"

    lines: list[str] = []
    for thread in context.plot_threads:
        name = thread.get("name", "未知剧情线")
        ttype = thread.get("thread_type", "main")
        lines.append(f"### [{ttype}] {name}")
        if thread.get("summary"):
            lines.append(f"- **概要**: {thread['summary']}")
        if thread.get("visible_goal"):
            lines.append(f"- **可见目标**: {thread['visible_goal']}")
        if thread.get("current_stage"):
            lines.append(f"- **当前阶段**: {thread['current_stage']}")
        if thread.get("start_chapter") is not None:
            lines.append(f"- **起始章节**: 第 {thread['start_chapter']} 章")
        lines.append("")

    return "\n".join(lines)


def _render_memory(context: StructureContextBundle) -> str:
    """渲染长期记忆（全景格式）"""
    records = context.memory_records

    # 兼容旧格式：list of dicts
    if isinstance(records, list):
        if not records:
            return "无相关数据\n"
        lines: list[str] = []
        for mem in records:
            mtype = mem.get("memory_type", "event")
            title = mem.get("title", "")
            summary = mem.get("summary", "")
            chap = mem.get("chapter_index")
            chap_str = f" (第 {chap} 章)" if chap is not None else ""
            header = f"- **[{mtype}]{chap_str}**: "
            if title:
                header += f"{title} — "
            header += summary
            lines.append(header)
        return "\n".join(lines) + "\n"

    # 新格式：ChapterPanorama dict
    if not records or not isinstance(records, dict):
        return "无相关数据\n"

    lines = []
    entities = records.get("entities", [])
    relations = records.get("relations", [])
    locations = records.get("character_locations", {})
    chapter = records.get("chapter_index", "?")

    lines.append(f"===== 第 {chapter} 章关系全景 =====")

    if entities:
        lines.append("**实体**")
        for e in entities:
            name = e.get("name", "?")
            etype = e.get("entity_type", "?")
            summary = e.get("summary", "")
            importance = e.get("importance", 0.5)
            star = "★" if importance >= 0.8 else "☆" if importance >= 0.5 else ""
            line = f"- {name} ({etype}){star}"
            if summary:
                line += f": {summary}"
            lines.append(line)

    if relations:
        lines.append("**关系**")
        for r in relations:
            src = r.get("source_id", "?")[:8]
            tgt = r.get("target_id", "?")[:8]
            rtype = r.get("relation_type", "?")
            desc = r.get("description", "")
            line = f"- {src} → {tgt} [{rtype}]"
            if desc:
                line += f" {desc}"
            lines.append(line)

    if locations:
        lines.append("**角色位置**")
        loc_map = {}
        for cid, loc in locations.items():
            loc_name = loc.get("location_id", "?")[:8]
            loc_map.setdefault(loc_name, []).append(cid[:8])
        for loc_name, chars in loc_map.items():
            lines.append(f"- {loc_name}: {', '.join(chars)}")

    return "\n".join(lines) + "\n"


def _render_foreshadowing_reveal(context: StructureContextBundle) -> str:
    """渲染伏笔与信息揭示"""
    # 从 plot_threads 和 chapter_card 中提取伏笔信息
    lines: list[str] = []

    # 尝试从 chapter_card 提取伏笔
    if context.chapter_card:
        cc = context.chapter_card
        f_actions = cc.get("foreshadowing_actions", [])
        if f_actions:
            lines.append("- **本章伏笔动作**:")
            for action in f_actions:
                if isinstance(action, dict):
                    desc = action.get("description", action.get("action", str(action)))
                    lines.append(f"  - {desc}")
                else:
                    lines.append(f"  - {action}")

        must_happen = cc.get("must_happen", [])
        if must_happen:
            lines.append("- **本章必须发生**:")
            for item in must_happen:
                lines.append(f"  - {item}")

        must_not = cc.get("must_not_happen", [])
        if must_not:
            lines.append("- **本章禁止发生**:")
            for item in must_not:
                lines.append(f"  - {item}")

    if not lines:
        return "无相关数据\n"

    return "\n".join(lines) + "\n"


def _render_forbidden(context: StructureContextBundle) -> str:
    """渲染禁止事项"""
    lines: list[str] = [
        "1. **不提前揭示 hidden_truth** — 标注为作者视角的信息不得在读者层出现。",
        "2. **不违反角色知识边界** — 角色只能知道 character_knowledge 允许的内容。",
    ]

    # 从 plot_threads 中提取 hidden_truth 防止提前揭示
    hidden_threads = [
        t
        for t in context.plot_threads
        if t.get("thread_type") == "hidden" and t.get("hidden_truth")
    ]
    if hidden_threads:
        lines.append("")
        lines.append("- **以下暗线信息不得提前揭示**:")
        for t in hidden_threads:
            lines.append(f"  - [{t.get('name', '')}]: {t.get('hidden_truth', '')}")

    # 从 chapter_card 获取约束
    if context.chapter_card:
        must_not = context.chapter_card.get("must_not_happen", [])
        if must_not:
            lines.append("")
            lines.append("- **本章卡明确禁止**:")
            for item in must_not:
                lines.append(f"  - {item}")

    return "\n".join(lines) + "\n"


def _render_creative_materials(context: StructureContextBundle) -> str:
    """渲染可用创作素材（含实体标签和篇章信息）"""
    if not context.rag_chunks:
        return "无相关数据\n"

    # 构建实体名称查找表（世界对象 + 人物）
    entity_name_map: dict[str, str] = {}
    for we in context.world_entities:
        if isinstance(we, dict):
            we_dict = we
        elif is_dataclass(we):
            we_dict = asdict(we)
        elif hasattr(we, "model_dump"):
            we_dict = we.model_dump()
        else:
            continue
        eid = we_dict.get("id") or we_dict.get("entity_id")
        ename = we_dict.get("name") or we_dict.get("entity_name")
        if eid and ename:
            entity_name_map[str(eid)] = str(ename)
    # 同样从人物列表中查找
    for char in context.characters:
        if isinstance(char, dict):
            char_dict = char
        elif is_dataclass(char):
            char_dict = asdict(char)
        elif hasattr(char, "model_dump"):
            char_dict = char.model_dump()
        else:
            continue
        cid = char_dict.get("character_id") or char_dict.get("id")
        cname = char_dict.get("name")
        if cid and cname:
            entity_name_map[str(cid)] = str(cname)

    lines: list[str] = []
    for chunk in context.rag_chunks:
        text = chunk.get("text", chunk.get("summary", ""))
        score = chunk.get("score")
        src_type = chunk.get("source_type", "")
        chap = chunk.get("chapter_index")
        meta = chunk.get("meta", {})
        entity_ids = chunk.get("entity_ids", [])
        character_ids = chunk.get("character_ids", [])

        parts = ["- "]
        # 篇章名称
        arc_in_meta = meta.get("arc_name") if isinstance(meta, dict) else None
        if arc_in_meta:
            parts.append(f"[{arc_in_meta}] ")
        if chap is not None:
            parts.append(f"[第 {chap} 章] ")
        if src_type:
            parts.append(f"[{src_type}] ")
        if score is not None:
            parts.append(f"(相关度: {score:.2f}) ")

        # 实体标签
        tags: list[str] = []
        for eid in (entity_ids or [])[:3]:
            name = entity_name_map.get(eid, eid[:8] if eid else "?")
            tags.append(f"#{name}")
        for cid in (character_ids or [])[:2]:
            name = entity_name_map.get(cid, cid[:8] if cid else "?")
            tags.append(f"@{name}")

        if tags:
            parts.append("[" + ", ".join(tags) + "] ")

        parts.append(text[:200])

        lines.append("".join(parts))

    return "\n".join(lines) + "\n"


def _render_risks(context: StructureContextBundle) -> str:
    """渲染风险提示"""
    lines: list[str] = []

    # 编译警告
    if context.warnings:
        for w in context.warnings:
            lines.append(f"- ⚠️ {w}")

    # Budget 警示
    for category, used in context.budget_used.items():
        budget = _get_budget_for_category(category)
        if used >= budget:
            lines.append(
                f"- ⚠️ **{category} 预算已用尽**: {used}/{budget}"
                f"，考虑减少关注范围以提高质量",
            )
        elif used > budget * 0.8:
            lines.append(
                f"- ⚡ **{category} 预算接近上限**: {used}/{budget}",
            )

    if not lines:
        lines.append("无相关风险")

    return "\n".join(lines) + "\n"


def _get_budget_for_category(category: str) -> int:
    """获取分类的预算上限"""
    from modules.evidence.compilation.contracts import CONTEXT_BUDGET

    return CONTEXT_BUDGET.get(category, 10)


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
}


def render_compiled_context(ctx: CompiledContext) -> str:
    """从 CompiledContext IR 渲染为 Markdown，保持 Tier 顺序"""
    parts = []
    for section in sorted(ctx.sections, key=lambda s: s.tier):
        header = _TIER_HEADERS.get(section.key, section.key)
        parts.append(f"## {header}\n\n{section.content}\n")
    return "\n".join(parts)

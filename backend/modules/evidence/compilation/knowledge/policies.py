"""
静态能力知识策略注册表

覆盖全部用户可见 AI 生成/检查能力的知识治理声明：知识主体、必查维度、
confirmation/snapshot 策略、输出权限与采用门禁。query planner、reranker、
格式修复等内部 helper 登记为基础设施豁免——不得产出答案、权限或事实。

注册表是静态事实源：`make prompt-contracts` 与 AST 门禁据此校验所有生产
LLM/Agent/stream/image 调用必须绑定 capability ID 或基础设施豁免。
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.evidence.compilation.knowledge.contracts import (
    KnowledgeContractError,
)

DOMAIN_WRITING = "writing"
DOMAIN_WORLD = "world"
DOMAIN_STORY = "story"
DOMAIN_IMPORTS = "imports"
DOMAIN_EVOLUTION = "evolution"
DOMAIN_INTERACTION = "interaction"
DOMAIN_ASSISTANT = "assistant"
DOMAIN_PROJECT = "project"
DOMAIN_INFRASTRUCTURE = "infrastructure"

CONFIRMATION_REQUIRED = "required"
CONFIRMATION_OPTIONAL = "optional"
CONFIRMATION_NONE = "none"
CONFIRMATION_POLICIES = frozenset(
    {CONFIRMATION_REQUIRED, CONFIRMATION_OPTIONAL, CONFIRMATION_NONE}
)

SNAPSHOT_REQUIRED = "required"
SNAPSHOT_OPTIONAL = "optional"
SNAPSHOT_NONE = "none"
SNAPSHOT_POLICIES = frozenset({SNAPSHOT_REQUIRED, SNAPSHOT_OPTIONAL, SNAPSHOT_NONE})

ADOPTION_REQUIRES_PASS = "adopt_requires_pass"
ADOPTION_REQUIRES_PASS_AND_REVIEW = "adopt_requires_pass_and_review"
ADOPTION_DISPLAY_ONLY = "display_only"
ADOPTION_NONE = "none"
ADOPTION_GATES = frozenset(
    {
        ADOPTION_REQUIRES_PASS,
        ADOPTION_REQUIRES_PASS_AND_REVIEW,
        ADOPTION_DISPLAY_ONLY,
        ADOPTION_NONE,
    }
)

OUTPUT_PROSE = "prose"
OUTPUT_PROPOSAL = "proposal"
OUTPUT_FINDING = "finding"
OUTPUT_ANSWER = "answer"
OUTPUT_INTERNAL = "internal"
OUTPUT_PERMISSIONS = frozenset(
    {OUTPUT_PROSE, OUTPUT_PROPOSAL, OUTPUT_FINDING, OUTPUT_ANSWER, OUTPUT_INTERNAL}
)

OUTPUT_PERMISSION_AUDIT_CLAUSES: dict[str, str] = {
    OUTPUT_PROPOSAL: (
        "本能力输出是向作者提出的候选提案：新增设定、命名、结构或推演不因资料中"
        "没有依据而单独构成 unsupported_fact；但新增内容不得与权威资料矛盾、不得"
        "违反任务指令或作者要求中已锁定的边界，对既有事实的引用必须与资料一致。"
        "任务要求回答既有事实、抽取或忠实整理已有资料时，不能补造原文没有的身份、关系、事件；"
        "候选状态不免除这类任务的来源要求。"
    ),
    OUTPUT_PROSE: (
        "本能力输出是创作正文：在作者授权与情境允许范围内推进动作、对话、感官细节与"
        "新的局部事件，不因这些尚未写过而判 unsupported_fact。对既有事实、人物身份、"
        "世界规则、时间线及明确限定的持有物与数量仍须与资料一致；"
        "不能因职业或场景常识补齐用户明确排除的装备与资源。新增情节不能赋予角色尚未获得的知识，"
        "也不能提前揭示被禁止的真相。"
    ),
    OUTPUT_FINDING: "本能力输出是检查发现：每条发现必须给出资料内依据。",
    OUTPUT_ANSWER: "本能力输出是回答：事实性断言必须有资料依据。",
    OUTPUT_INTERNAL: "本能力输出仅供内部流程使用：按资料一致性审查。",
}
"""输出权限的审查语义；进入审查 prompt，决定 unsupported_fact 的适用范围。"""

KNOWLEDGE_DIMENSIONS: dict[str, str] = {
    "prior_prose": "截止点前正文与选中路径",
    "scene_state": "Scene 四维记忆时点",
    "world_entities": "世界对象与物品",
    "world_rules": "世界规则与激活 profile",
    "world_bible": "世界书页面与简介",
    "character_knowledge": "角色知识边界",
    "reader_reveal": "读者揭示策略",
    "timeline": "时间线",
    "plot_threads": "剧情线与伏笔",
    "outline": "大纲层级",
    "memory": "长期记忆",
    "source_canon": "RP 绑定的同 owner 冻结版本",
    "imported_assets": "导入资产",
    "map_spatial": "空间结构与地理",
}
"""知识维度词表；能力声明的必查维度必须取自此处。"""


@dataclass(frozen=True)
class CapabilityKnowledgePolicy:
    """单个能力的知识治理声明。"""

    capability_id: str
    domain: str
    title: str
    subject_types: tuple[str, ...]
    """允许的知识主体类型（author / reader / character / scene…）"""
    required_dimensions: tuple[str, ...]
    confirmation_policy: str
    snapshot_policy: str
    output_permissions: tuple[str, ...]
    adoption_gate: str
    infrastructure: bool = False
    notes: str = ""


def _policy(
    capability_id: str,
    domain: str,
    title: str,
    *,
    subjects: tuple[str, ...] = ("author",),
    dimensions: tuple[str, ...] = (),
    confirmation: str = CONFIRMATION_OPTIONAL,
    snapshot: str = SNAPSHOT_REQUIRED,
    outputs: tuple[str, ...] = (OUTPUT_PROPOSAL,),
    gate: str = ADOPTION_REQUIRES_PASS,
    infrastructure: bool = False,
    notes: str = "",
) -> CapabilityKnowledgePolicy:
    return CapabilityKnowledgePolicy(
        capability_id=capability_id,
        domain=domain,
        title=title,
        subject_types=subjects,
        required_dimensions=dimensions,
        confirmation_policy=confirmation,
        snapshot_policy=snapshot,
        output_permissions=outputs,
        adoption_gate=gate,
        infrastructure=infrastructure,
        notes=notes,
    )


_WRITING_DIMENSIONS = (
    "prior_prose",
    "scene_state",
    "world_entities",
    "world_rules",
    "character_knowledge",
    "reader_reveal",
    "timeline",
    "plot_threads",
    "memory",
)

CAPABILITY_REGISTRY: dict[str, CapabilityKnowledgePolicy] = {
    entry.capability_id: entry
    for entry in (
        # --- Writing ---
        _policy(
            "writing.generate",
            DOMAIN_WRITING,
            "正文生成与续写（AI 稿候选）",
            subjects=("author", "character"),
            dimensions=_WRITING_DIMENSIONS,
            confirmation=CONFIRMATION_REQUIRED,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_PROSE,),
            gate=ADOPTION_REQUIRES_PASS_AND_REVIEW,
            notes=(
                "角色模式必须同时具备 Scene、POV 人物和截止点；"
                "采用需知识审查与独立审稿同时 PASS。"
            ),
        ),
        _policy(
            "writing.semantic_review",
            DOMAIN_WRITING,
            "正文独立语义审查（检查类）",
            subjects=("author",),
            dimensions=_WRITING_DIMENSIONS,
            confirmation=CONFIRMATION_REQUIRED,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_FINDING,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes=(
                "审查输出逐条 finding 必须绑定精确来源；与知识审查合流复用同一冻结范围。"
            ),
        ),
        _policy(
            "writing.targeted_revision",
            DOMAIN_WRITING,
            "定向返修（最多一次语义返修）",
            subjects=("author", "character"),
            dimensions=_WRITING_DIMENSIONS,
            confirmation=CONFIRMATION_REQUIRED,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_PROSE,),
            gate=ADOPTION_REQUIRES_PASS_AND_REVIEW,
            notes="返修者只收到生成者上下文与脱敏 finding，复审不过则阻断采用。",
        ),
        _policy(
            "writing.comment_revision",
            DOMAIN_WRITING,
            "作者批注约束下的局部正文候选",
            dimensions=("prior_prose",),
            confirmation=CONFIRMATION_OPTIONAL,
            outputs=(OUTPUT_PROSE,),
            gate=ADOPTION_REQUIRES_PASS_AND_REVIEW,
            notes="仅以冻结工作稿与批注修订选区；跨资产修改另交作者确认。",
        ),
        _policy(
            "writing.conflict_check.ai_review",
            DOMAIN_WRITING,
            "冲突软判断（检查类）",
            subjects=("author",),
            dimensions=(
                "prior_prose",
                "scene_state",
                "world_entities",
                "timeline",
                "plot_threads",
            ),
            confirmation=CONFIRMATION_REQUIRED,
            snapshot=SNAPSHOT_OPTIONAL,
            outputs=(OUTPUT_FINDING,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="确定性冲突检查只记录 coverage，不额外调用 LLM。",
        ),
        _policy(
            "writing.conflict_check.ai_suggestion",
            DOMAIN_WRITING,
            "单条冲突修复建议",
            subjects=("author",),
            dimensions=(
                "prior_prose",
                "scene_state",
                "world_entities",
                "timeline",
            ),
            confirmation=CONFIRMATION_REQUIRED,
            snapshot=SNAPSHOT_OPTIONAL,
            outputs=(OUTPUT_FINDING,),
            gate=ADOPTION_DISPLAY_ONLY,
        ),
        # --- Project ---
        _policy(
            "project.smart_dedup",
            DOMAIN_PROJECT,
            "项目级相似资料扫描",
            subjects=("author",),
            dimensions=("world_entities", "outline", "plot_threads", "scene_state"),
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes=(
                "跨 World 与 Story 的 canonical parent；扫描只生成有界候选，"
                "实际处理仍由各资产模块在作者确认后完成。"
            ),
        ),
        # --- World ---
        _policy(
            "world.generation.chat",
            DOMAIN_WORLD,
            "世界设定共创",
            subjects=("author",),
            dimensions=("world_entities", "world_rules", "world_bible", "timeline"),
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="临时回答未通过知识审查不返回不安全正文。",
        ),
        _policy(
            "world.generation.design_iteration",
            DOMAIN_WORLD,
            "共创推演会话",
            subjects=("author",),
            dimensions=(
                "world_entities",
                "world_rules",
                "world_bible",
                "timeline",
                "plot_threads",
            ),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "world.generation.cocreation",
            DOMAIN_WORLD,
            "世界共创回合（聊天/推演）",
            subjects=("author",),
            dimensions=(
                "world_entities",
                "world_rules",
                "world_bible",
                "timeline",
                "plot_threads",
            ),
            confirmation=CONFIRMATION_REQUIRED,
            outputs=(OUTPUT_ANSWER, OUTPUT_PROPOSAL),
            gate=ADOPTION_DISPLAY_ONLY,
            notes=(
                "同一 world_cocreation_turn 的 canonical parent；chat/design 仍按各自"
                "子步骤使用对应知识审查策略。"
            ),
        ),
        _policy(
            "world.generation.convergence",
            DOMAIN_WORLD,
            "设定收束",
            subjects=("author",),
            dimensions=("world_entities", "world_rules", "world_bible", "timeline"),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "world.generation.exploration",
            DOMAIN_WORLD,
            "设定缺口探索",
            subjects=("author",),
            dimensions=("world_entities", "world_rules", "world_bible"),
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
        ),
        _policy(
            "world.generation.semantic_inspection",
            DOMAIN_WORLD,
            "当前页语义检修（检查类）",
            subjects=("author",),
            dimensions=("world_entities", "world_rules", "world_bible"),
            outputs=(OUTPUT_FINDING,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="逐条 finding 验证精确来源；无证据 finding 不得静默保留。",
        ),
        _policy(
            "world.team_stress",
            DOMAIN_WORLD,
            "有限协作规则压力测试",
            subjects=("author",),
            dimensions=("world_entities", "world_rules", "world_bible"),
            outputs=(OUTPUT_FINDING, OUTPUT_PROPOSAL),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="反例须满足原规则前提；额外假设与修订提案不冒充事实，不是形式证明。",
        ),
        _policy(
            "world.generation.suggestion",
            DOMAIN_WORLD,
            "对象/物品与世界书页建议",
            subjects=("author",),
            dimensions=("world_entities", "world_rules", "world_bible", "timeline"),
            outputs=(OUTPUT_PROPOSAL,),
            notes=(
                "无来源新创意必须标记为 proposal，不得冒充既有事实或冲突正史；"
                "阻断建议仍保存为 candidate。"
            ),
        ),
        _policy(
            "world.ask",
            DOMAIN_WORLD,
            "Ask World 世界问答",
            subjects=("author", "character", "reader"),
            dimensions=("world_entities", "world_rules", "world_bible"),
            confirmation=CONFIRMATION_NONE,
            outputs=(OUTPUT_ANSWER,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="引用必须回读，无证据拒答。",
        ),
        _policy(
            "world.world_bible.synopsis",
            DOMAIN_WORLD,
            "世界观简介生成",
            subjects=("author",),
            dimensions=("world_bible", "world_entities"),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "world.validation",
            DOMAIN_WORLD,
            "世界设定校验（检查类）",
            subjects=("author",),
            dimensions=(
                "world_entities",
                "world_rules",
                "world_bible",
                "character_knowledge",
                "timeline",
            ),
            confirmation=CONFIRMATION_NONE,
            outputs=(OUTPUT_FINDING,),
            notes=(
                "findings 作为正史写入门禁；"
                "quality_mode=fast 只省略文学润色，不能跳过知识审查。"
            ),
        ),
        _policy(
            "world.entity_fusion",
            DOMAIN_WORLD,
            "实体融合建议",
            subjects=("author",),
            dimensions=("world_entities", "world_bible"),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "world.alias_relations.extract",
            DOMAIN_WORLD,
            "别名与关系抽取（检查类）",
            subjects=("author",),
            dimensions=(
                "prior_prose",
                "world_entities",
                "world_bible",
                "imported_assets",
            ),
            confirmation=CONFIRMATION_REQUIRED,
            outputs=(OUTPUT_PROPOSAL,),
            notes="实体抽取仅留长期创作资产；别名附着已有对象，不重复建实体。",
        ),
        _policy(
            "world.map_structure.generate",
            DOMAIN_WORLD,
            "地图结构生成",
            subjects=("author",),
            dimensions=(
                "map_spatial",
                "world_entities",
                "world_rules",
                "imported_assets",
            ),
            outputs=(OUTPUT_PROPOSAL,),
            notes="栅格像素不作为事实来源，仍由作者采用。",
        ),
        _policy(
            "world.map_atlas.plan",
            DOMAIN_WORLD,
            "地图图集规划",
            subjects=("author",),
            dimensions=("map_spatial", "world_entities", "world_bible"),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "world.map_atlas.generate",
            DOMAIN_WORLD,
            "地图图集生成运行",
            subjects=("author",),
            dimensions=("map_spatial", "world_entities", "world_bible"),
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes=(
                "地图规划、视觉 brief 与图片请求的 canonical parent；"
                "页级 possible-charge 确认和采用仍由 Map Atlas 领域拥有。"
            ),
        ),
        _policy(
            "world.map_image_prompt",
            DOMAIN_WORLD,
            "地图图片 Prompt（视觉 brief）",
            subjects=("author",),
            dimensions=("map_spatial", "world_bible"),
            outputs=(OUTPUT_PROPOSAL,),
            notes=(
                "图片 Prompt 使用审过的视觉 brief；"
                "supported/visual_fill/conflicts 分区保持。"
            ),
        ),
        _policy(
            "world.map_image.generate",
            DOMAIN_WORLD,
            "地图图片实际生成/编辑（Image API）",
            subjects=("author",),
            dimensions=("map_spatial",),
            outputs=(OUTPUT_PROPOSAL,),
            notes=(
                "表示真实 Image API 请求的运行归属：generate 与 edit 共用本"
                " capability，由运行回执的 call_kind 区分；不与"
                " world.map_image_prompt（视觉 brief）混用。页级"
                " possible-charge 确认语义仍由地图领域拥有。"
            ),
        ),
        # --- Story ---
        _policy(
            "story.story_outline.generate",
            DOMAIN_STORY,
            "总纲生成",
            subjects=("author",),
            dimensions=(
                "outline",
                "world_rules",
                "world_entities",
                "plot_threads",
                "timeline",
                "memory",
                "prior_prose",
            ),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "story.outline.p20",
            DOMAIN_STORY,
            "P20 剧情线/篇章/Scene 生成",
            subjects=("author",),
            dimensions=(
                "outline",
                "world_rules",
                "world_entities",
                "character_knowledge",
                "plot_threads",
                "timeline",
                "scene_state",
                "memory",
                "prior_prose",
            ),
            outputs=(OUTPUT_PROPOSAL,),
            notes=(
                "三类审计读权威包；"
                "层级越权、未来揭示、作者排除项回流或错误引用阻断 apply。"
            ),
        ),
        _policy(
            "story.outline.analyze",
            DOMAIN_STORY,
            "大纲分析（检查类）",
            subjects=("author",),
            dimensions=("outline", "prior_prose", "plot_threads"),
            outputs=(OUTPUT_ANSWER,),
            gate=ADOPTION_DISPLAY_ONLY,
        ),
        _policy(
            "story.character_card",
            DOMAIN_STORY,
            "人物卡生成",
            subjects=("author", "character"),
            dimensions=(
                "character_knowledge",
                "world_entities",
                "world_rules",
                "prior_prose",
                "timeline",
                "memory",
            ),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "story.reaction",
            DOMAIN_STORY,
            "人物反应生成",
            subjects=("author", "character"),
            dimensions=(
                "character_knowledge",
                "world_entities",
                "prior_prose",
                "scene_state",
            ),
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="preview_only；持久化走 character_card 门禁。",
        ),
        _policy(
            "story.script",
            DOMAIN_STORY,
            "剧本生成",
            subjects=("author",),
            dimensions=("outline", "scene_state", "prior_prose", "character_knowledge"),
            outputs=(OUTPUT_PROPOSAL,),
            notes="采用剧本经 basis_hash 追踪；漂移需重新确认。",
        ),
        _policy(
            "story.one_click",
            DOMAIN_STORY,
            "一键人物包（卡→反应→剧本）",
            subjects=("author", "character"),
            dimensions=(
                "character_knowledge",
                "world_entities",
                "world_rules",
                "prior_prose",
                "timeline",
                "memory",
                "outline",
                "scene_state",
            ),
            outputs=(OUTPUT_PROPOSAL,),
            notes="完成持久化前重验 context_hash 与 character_card_source_hashes。",
        ),
        _policy(
            "story.scene_fusion",
            DOMAIN_STORY,
            "Scene 融合草稿",
            subjects=("author",),
            dimensions=(
                "scene_state",
                "prior_prose",
                "outline",
                "character_knowledge",
                "world_rules",
            ),
            outputs=(OUTPUT_PROPOSAL,),
            notes="确定性复审保持；保存需显式 save。",
        ),
        _policy(
            "story.structure_dedup",
            DOMAIN_STORY,
            "结构去重建议",
            subjects=("author",),
            dimensions=("outline", "imported_assets"),
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
        ),
        # --- Imports ---
        _policy(
            "imports.scene_plan",
            DOMAIN_IMPORTS,
            "导入 Phase 0 窗口规划",
            subjects=("author",),
            dimensions=("prior_prose", "imported_assets"),
            outputs=(OUTPUT_PROPOSAL,),
            notes="Phase 1 每窗口冻结一份组级 receipt，组内 LLM step 引用并逐项复核。",
        ),
        _policy(
            "imports.deep_import",
            DOMAIN_IMPORTS,
            "分段式导入整理运行",
            subjects=("author",),
            dimensions=(
                "prior_prose",
                "scene_state",
                "world_entities",
                "outline",
                "imported_assets",
            ),
            confirmation=CONFIRMATION_REQUIRED,
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_REQUIRES_PASS,
            notes=(
                "完整导入及三个独立阶段的 canonical parent；模型产生的工作量"
                "按固定授权段和领域 checkpoint 续算，自动恢复不得扩额。"
            ),
        ),
        _policy(
            "imports.scene_slicing",
            DOMAIN_IMPORTS,
            "导入 Phase 1a Scene 切分",
            subjects=("author",),
            dimensions=("prior_prose", "imported_assets"),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "imports.scene_enrichment",
            DOMAIN_IMPORTS,
            "导入 Phase 1b Scene 充实",
            subjects=("author",),
            dimensions=("prior_prose", "scene_state", "imported_assets"),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "imports.scene_fusion",
            DOMAIN_IMPORTS,
            "导入 Phase 1c Scene 融合",
            subjects=("author",),
            dimensions=("prior_prose", "scene_state", "imported_assets"),
            outputs=(OUTPUT_PROPOSAL,),
        ),
        _policy(
            "imports.entity_extraction",
            DOMAIN_IMPORTS,
            "导入 Phase 2 实体抽取",
            subjects=("author",),
            dimensions=("prior_prose", "world_entities", "imported_assets"),
            outputs=(OUTPUT_PROPOSAL,),
            notes="Phase 2 每 Scene 冻结一份组级 receipt。",
        ),
        _policy(
            "imports.structure_analysis",
            DOMAIN_IMPORTS,
            "导入 Phase 3 结构分析",
            subjects=("author",),
            dimensions=("prior_prose", "imported_assets", "outline"),
            outputs=(OUTPUT_PROPOSAL,),
            notes="Phase 3 每候选组冻结一份组级 receipt。",
        ),
        _policy(
            "imports.review_resolution",
            DOMAIN_IMPORTS,
            "导入审阅裁决",
            subjects=("author",),
            dimensions=("prior_prose", "imported_assets", "world_entities"),
            outputs=(OUTPUT_FINDING,),
            notes="review resolution 每问题组冻结一份 receipt。",
        ),
        _policy(
            "imports.targeted_completion",
            DOMAIN_IMPORTS,
            "定向补全",
            subjects=("author",),
            dimensions=("imported_assets", "world_entities", "prior_prose"),
            outputs=(OUTPUT_PROPOSAL,),
            notes="targeted completion 每问题组冻结一份 receipt。",
        ),
        # --- Evolution ---
        _policy(
            "evolution.scene_observe",
            DOMAIN_EVOLUTION,
            "逐场景来源观察与状态提议",
            subjects=("author", "scene"),
            dimensions=("prior_prose", "scene_state"),
            confirmation=CONFIRMATION_REQUIRED,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_FINDING, OUTPUT_PROPOSAL),
            gate=ADOPTION_REQUIRES_PASS,
            notes="逐字引用与模态经宿主校验；状态提议过语义门后才允许窄提交。",
        ),
        _policy(
            "evolution.state_review",
            DOMAIN_EVOLUTION,
            "独立回读正文核验状态提议",
            subjects=("author", "scene"),
            dimensions=("prior_prose", "scene_state"),
            confirmation=CONFIRMATION_REQUIRED,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_FINDING,),
            gate=ADOPTION_REQUIRES_PASS,
            notes="独立调用逐项复核；冻结来源、前序回执、候选和根预算，漏项或矛盾不得取得状态效果。",
        ),
        # --- Interaction / RP ---
        _policy(
            "interaction.story_generate",
            DOMAIN_INTERACTION,
            "RP 正文生成（source-bound 与 agent 路径）",
            subjects=("reader", "character"),
            dimensions=(
                "source_canon",
                "character_knowledge",
                "reader_reveal",
                "prior_prose",
                "memory",
            ),
            confirmation=CONFIRMATION_OPTIONAL,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_PROSE,),
            notes=(
                "正文先入 attempt buffer 并以 release_state=held 隐藏；"
                "审查通过才创建正式节点并一次性返回全文。"
            ),
        ),
        _policy(
            "interaction.summary_refresh",
            DOMAIN_INTERACTION,
            "RP 回顾总结",
            subjects=("reader",),
            dimensions=("prior_prose", "source_canon", "memory"),
            confirmation=CONFIRMATION_OPTIONAL,
            snapshot=SNAPSHOT_OPTIONAL,
            outputs=(OUTPUT_PROPOSAL,),
            notes="summary 只能看选中路径和有效回顾，不能读未选 sibling。",
        ),
        _policy(
            "interaction.continuity_review",
            DOMAIN_INTERACTION,
            "RP 连续性复核（检查类）",
            subjects=("reader",),
            dimensions=("prior_prose", "source_canon", "memory"),
            confirmation=CONFIRMATION_OPTIONAL,
            snapshot=SNAPSHOT_OPTIONAL,
            outputs=(OUTPUT_FINDING,),
            gate=ADOPTION_DISPLAY_ONLY,
        ),
        _policy(
            "interaction.anonymous_story",
            DOMAIN_INTERACTION,
            "匿名公开演示 RP",
            subjects=("reader",),
            dimensions=("source_canon", "reader_reveal"),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_PROSE,),
            notes=(
                "不得把未揭示原文交给用户提供的临时 Key；"
                "缺少安全 guard manifest 时失败关闭。"
            ),
        ),
        # --- Assistant ---
        _policy(
            "assistant.turn",
            DOMAIN_ASSISTANT,
            "项目助手回答",
            subjects=("author",),
            dimensions=(
                "world_entities",
                "world_rules",
                "world_bible",
                "prior_prose",
                "outline",
                "plot_threads",
                "memory",
            ),
            confirmation=CONFIRMATION_OPTIONAL,
            snapshot=SNAPSHOT_OPTIONAL,
            outputs=(OUTPUT_ANSWER, OUTPUT_PROPOSAL),
            gate=ADOPTION_DISPLAY_ONLY,
            notes=(
                "实质项目事实必须绑定实际工具 evidence；"
                "最终输出独立审查一次；领域生成委托领域工作流。"
            ),
        ),
        *(
            _policy(
                capability,
                "collaboration",
                title,
                subjects=("author", "reader"),
                dimensions=("prior_prose", "world_rules", "outline"),
                confirmation=CONFIRMATION_OPTIONAL,
                snapshot=SNAPSHOT_REQUIRED,
                outputs=(OUTPUT_PROPOSAL, OUTPUT_ANSWER),
                gate=ADOPTION_REQUIRES_PASS_AND_REVIEW,
                notes="授权、预算与精确工作区版本由宿主控制；产物不成为正式事实。",
            )
            for capability, title in (
                ("collaboration.run", "创作试验"),
                ("collaboration.plan", "创作问题规划"),
                ("collaboration.investigate", "创作调查与反证"),
                ("collaboration.revise", "隔离工作区试改"),
                ("collaboration.check", "精确试改检查"),
            )
        ),
        _policy(
            "assistant.forecast",
            DOMAIN_ASSISTANT,
            "保存资料的短期前瞻",
            subjects=("author",),
            dimensions=("prior_prose", "world_rules", "outline"),
            confirmation=CONFIRMATION_OPTIONAL,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="新创意是条件式候选；观察有据、未知保留、不把普通细节变为义务。",
        ),
        _policy(
            "assistant.editorial",
            DOMAIN_ASSISTANT,
            "作者作品的只读编辑意见",
            subjects=("author", "reader"),
            dimensions=("prior_prose", "world_rules", "outline"),
            confirmation=CONFIRMATION_OPTIONAL,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="准确引文与覆盖清单；不写正文或正史，不授予 AI 正文采用资格。",
        ),
        _policy(
            "interaction.forecast",
            DOMAIN_INTERACTION,
            "玩家可见前瞻",
            subjects=("reader",),
            dimensions=("prior_prose", "reader_reveal"),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_REQUIRED,
            outputs=(OUTPUT_PROPOSAL,),
            gate=ADOPTION_DISPLAY_ONLY,
            notes="只能使用当前选中路径、已读内容和玩家可感知资料；不发送玩家行动。",
        ),
        # --- 基础设施豁免：不得产出答案、权限或事实 ---
        _policy(
            "infrastructure.rag_query_planner",
            DOMAIN_INFRASTRUCTURE,
            "RAG 查询规划 helper",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
        _policy(
            "infrastructure.reranker",
            DOMAIN_INFRASTRUCTURE,
            "检索重排 helper",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
        _policy(
            "infrastructure.format_repair",
            DOMAIN_INFRASTRUCTURE,
            "结构化输出格式修复 helper",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
        _policy(
            "infrastructure.embedding",
            DOMAIN_INFRASTRUCTURE,
            "独立 embedding 索引（静态门禁窄例外）",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
        _policy(
            "infrastructure.rag_index_chapter",
            DOMAIN_INFRASTRUCTURE,
            "单章 RAG 索引与 embedding",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
        _policy(
            "infrastructure.rag_reindex_novel",
            DOMAIN_INFRASTRUCTURE,
            "项目级 RAG 全量重建",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
        _policy(
            "infrastructure.rag_retry_embeddings",
            DOMAIN_INFRASTRUCTURE,
            "失败 embedding 批量重试",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
        _policy(
            "infrastructure.account_connection_test",
            DOMAIN_INFRASTRUCTURE,
            "账户连接测试",
            subjects=(),
            dimensions=(),
            confirmation=CONFIRMATION_NONE,
            snapshot=SNAPSHOT_NONE,
            outputs=(OUTPUT_INTERNAL,),
            gate=ADOPTION_NONE,
            infrastructure=True,
        ),
    )
}


def get_capability_policy(capability_id: str) -> CapabilityKnowledgePolicy | None:
    return CAPABILITY_REGISTRY.get(capability_id)


def require_capability_policy(capability_id: str) -> CapabilityKnowledgePolicy:
    policy = CAPABILITY_REGISTRY.get(capability_id)
    if policy is None:
        raise KnowledgeContractError(
            f"capability {capability_id!r} is not registered in CAPABILITY_REGISTRY"
        )
    return policy


def iter_capabilities(domain: str | None = None):
    for capability_id in sorted(CAPABILITY_REGISTRY):
        policy = CAPABILITY_REGISTRY[capability_id]
        if domain is None or policy.domain == domain:
            yield policy


def capability_ids() -> tuple[str, ...]:
    return tuple(sorted(CAPABILITY_REGISTRY))


def validate_registry() -> list[str]:
    """校验注册表自洽性；返回问题列表（空列表表示通过）。"""
    problems: list[str] = []
    for policy in CAPABILITY_REGISTRY.values():
        if policy.confirmation_policy not in CONFIRMATION_POLICIES:
            problems.append(f"{policy.capability_id}: bad confirmation_policy")
        if policy.snapshot_policy not in SNAPSHOT_POLICIES:
            problems.append(f"{policy.capability_id}: bad snapshot_policy")
        if policy.adoption_gate not in ADOPTION_GATES:
            problems.append(f"{policy.capability_id}: bad adoption_gate")
        for permission in policy.output_permissions:
            if permission not in OUTPUT_PERMISSIONS:
                problems.append(
                    f"{policy.capability_id}: bad output permission {permission!r}"
                )
        for dimension in policy.required_dimensions:
            if dimension not in KNOWLEDGE_DIMENSIONS:
                problems.append(
                    f"{policy.capability_id}: unknown dimension {dimension!r}"
                )
        if policy.infrastructure:
            if policy.adoption_gate != ADOPTION_NONE:
                problems.append(
                    f"{policy.capability_id}: infrastructure exemption must not adopt"
                )
            if policy.output_permissions != (OUTPUT_INTERNAL,):
                problems.append(
                    f"{policy.capability_id}: infrastructure outputs must be internal"
                )
            if policy.required_dimensions:
                problems.append(
                    f"{policy.capability_id}: "
                    "infrastructure exemption declares dimensions"
                )
        elif not policy.required_dimensions:
            problems.append(
                f"{policy.capability_id}: user capability must declare dimensions"
            )
    return problems

export const AI_MESSAGE_LIMIT = 40
export const AI_SELECTED_CHAPTER_LIMIT = 20
export const PAGE_SIZE = 50

export const BUILTIN_TEMPLATE_PROMPTS = {
  none: "不预设固定创作框架。围绕作者真正想创造或解决的内容，找出这个对象最核心的概念、辨识度，以及它与现有世界和故事的关系。允许对象暂时跨越多个类别或尚未完成分类，不要套用人物、事件、物品等模板的固定维度。最终先收束为概念建议，作者可在采用前调整类型。",
  character: "把人物设计成一个会作出选择、影响他人并改变局势的人，而不是属性集合。优先理解这个人物在当前故事中追求什么、受到什么阻力、如何作出选择，以及其行为逻辑和重要关系。外貌、能力、恐惧、秘密、声音风格、过去经历等，只发展对当前人物真正有帮助的部分。不要强制人物拥有悲惨过去、隐藏身份、反转或完整人物卡，也不要用性格标签代替具体的行为逻辑。",
  event: "把事件设计成一次具有因果关系的状态变化，而不是静态事件说明。优先理解事件发生前后的差异、推动变化的力量、参与者作出的关键选择，以及它对相关人物和世界产生的实际影响。起因、过程、结果、公开解释、隐藏原因和后续影响只按当前事件需要发展。事件可以失败、中断、持续发酵或仅仅巩固现状；不要强制加入阴谋、隐藏真相、反转或后续钩子。",
  item: "把物品设计成会被使用、保存、争夺、交换或传承的世界组成部分。优先理解人们为什么在意它、它能够或不能做什么、使用和持有它会带来什么，以及它与人物、地点、组织或历史的关系。外观、来源、能力、限制、代价、秘密和风险只按当前物品需要发展。不要默认物品具有超自然能力、诅咒、秘密来源或失控风险。",
  location: "把地点设计成会塑造行动、生活和关系的空间，而不是景观资料表。优先理解空间如何组织、人在其中如何行动和感受、谁能够进入或控制它，以及它为什么在当前世界中存在。历史、资源、危险、势力归属、秘密区域和进入条件只按当前地点需要发展。不要强制每个地点都有危险、秘密区域、特殊资源或剧情任务。",
  faction: "把组织设计成能够持续作出决策和采取行动的集体，而不是组织架构图。优先理解它为什么存在、如何获得资源和合法性、谁能够影响决策、内部如何合作或分裂，以及它实际能够做什么、不能做什么。成员、层级、公开形象、隐藏目标和外部关系只按当前组织需要发展。不要强制组织拥有秘密目标、宿敌、阴谋或完整层级体系。",
  rule: "把规则设计成稳定影响世界运行、人物选择和行为后果的机制，而不是术语密集的说明书。优先理解它约束什么、角色如何认识或验证它、违反或利用它会发生什么，以及它如何改变真实的选择空间。适用范围、限制、代价、边界情况、例外和普遍误解只按当前规则需要发展。不要为了制造戏剧性而强行增加漏洞、例外、代价或伪科学解释；规则应当足够一致，但不要求解释超出故事实际需要的细节。",
}

export const OBJECT_TEMPLATES = [
  ["none", "不带模板", "自由构思，先作为概念建议收束，采用前可调整类型"],
  ["character", "人物", "具有欲望、选择与关系的人物"],
  ["event", "事件", "改变局势或维持秩序的发生过程"],
  ["item", "物品", "被使用、争夺、保存或传承的物品"],
  ["location", "地点", "承载行动与生活的空间"],
  ["faction", "组织", "能够持续行动与决策的集体"],
  ["rule", "规则设定", "约束世界运行与选择后果的机制"],
].map(([value, label, hint]) => ({
  id: `builtin:${value}`,
  value: `builtin:${value}`,
  label,
  hint,
  prompt: BUILTIN_TEMPLATE_PROMPTS[value],
  object_template: value,
  is_builtin: true,
  version_number: 1,
}))

export const TASK_PRESETS = {
  plot: { label: "生成剧情线", task: "基于当前设定梳理主线、支线和伏笔推进。", scope: "arc", reveal_mode: "author_full" },
  polish: { label: "润色正文", task: "保持设定一致，优化语气、节奏和场景细节。", scope: "chapter", reveal_mode: "author_safe" },
  conflict_check: { label: "检查冲突", task: "检查当前章节是否存在人物、世界对象或剧情设定冲突。", scope: "chapter", reveal_mode: "author_full" },
  custom: { label: "自定义任务", task: "", scope: "arc", reveal_mode: "author_safe" },
}

export const SCOPE_OPTIONS = [
  ["project", "项目信息"], ["world", "世界对象"], ["world_character", "世界+人物"],
  ["arc", "篇章"], ["chapter", "章节"], ["full", "全部"],
].map(([value, label]) => ({ value, label }))

export const REVEAL_OPTIONS = [
  ["author_safe", "作者安全模式（隐藏隐藏真相）"],
  ["author_full", "作者全知模式（显示所有信息）"],
  ["reader", "读者模式（仅显示读者已知信息）"],
  ["character", "角色视角模式（按人物知识边界）"],
].map(([value, label]) => ({ value, label }))

export function listItems(data) {
  if (Array.isArray(data)) return data
  for (const key of ["items", "scenes", "threads", "characters"]) {
    if (Array.isArray(data?.[key])) return data[key]
  }
  return []
}

export function characterId(character) {
  return String(character?.entity_id || character?.id || "")
}

export function normalizeTemplate(raw) {
  const allowed = new Set(["none", "character", "event", "item", "location", "faction", "rule", "custom"])
  const objectTemplate = allowed.has(raw?.object_template) ? raw.object_template : "custom"
  return {
    id: raw.id,
    value: raw.id,
    label: raw.name,
    hint: raw.description || "",
    prompt: raw.prompt_text || raw.prompt || "",
    object_template: objectTemplate,
    is_builtin: Boolean(raw.is_builtin),
    version_number: raw.version_number || 1,
  }
}

export function selectedTemplatePayload(templates, selectedTemplateId) {
  const all = templates?.length ? templates : OBJECT_TEMPLATES
  const item = all.find((entry) => entry.value === selectedTemplateId) || all[0]
  return {
    template_id: item.id,
    template_version: item.version_number,
    template: item.object_template,
    template_name: item.label,
    template_prompt: item.is_builtin ? undefined : item.prompt,
  }
}

export function buildWorldPayload(state) {
  const template = selectedTemplatePayload(state.templates, state.selectedTemplateId)
  const profile = state.activationProfiles?.find((item) => item.id === state.activationProfileId)
  const pageTemplate = state.worldPageTemplates?.find((item) => item.template_key === state.newPageTemplateKey)
  const messages = (state.messages || [])
    .filter((item) => !item.pending && !item.error && ["user", "assistant"].includes(item.role))
    .map(({ role, content }) => ({ role, content }))
  const sourceContext = state.sourcePage && state.sourcePageId
    ? {
        kind: "world_bible_page",
        page_id: state.sourcePageId,
        baseline: state.sourceDraft
          ? {
              kind: "draft",
              page_version: state.sourcePage.version_number || 1,
              draft_id: state.sourceDraft.id,
              draft_updated_at: state.sourceDraft.updated_at,
            }
          : { kind: "published", page_version: state.sourcePage.version_number || 1 },
      }
    : { kind: "project" }
  let target
  if (state.targetKind === "world_bible_page") {
    target = { kind: "world_bible_page", page_id: state.sourcePageId }
  } else if (state.targetKind === "world_bible_new_page") {
    target = {
      kind: "world_bible_new_page",
      page_type: state.newPageType || "custom",
      page_template_key: pageTemplate?.template_key || null,
      page_template_version: pageTemplate?.version_number || null,
    }
  } else {
    target = { kind: "core_entity", ...template }
  }
  return {
    novel_id: state.projectId,
    source_context: sourceContext,
    target,
    messages: messages.slice(-AI_MESSAGE_LIMIT),
    selected_chapter_indices: (state.selectedChapters || []).slice(0, AI_SELECTED_CHAPTER_LIMIT).map((item) => item.chapter_index),
    quality_mode: state.qualityMode,
    include_world_synopsis: state.includeWorldSynopsis,
    scene_id: state.selectedSceneId || null,
    thread_ids: state.selectedThreadIds || [],
    character_ids: state.selectedCharacterIds || [],
    entity_ids: state.selectedEntityIds || [],
    selected_asset_refs: [],
    activation_profile_id: state.activationProfileId || null,
    activation_profile_version: profile?.version_number || null,
  }
}

export function sectionDiff(previousSections = [], nextSections = []) {
  const before = new Map(previousSections.map((item) => [item.section_id, item]))
  const after = new Map(nextSections.map((item) => [item.section_id, item]))
  const changes = []
  for (const [sectionId, section] of after) {
    const previous = before.get(sectionId)
    if (!previous) {
      changes.push({ kind: "新增", section, fields: [] })
      continue
    }
    const fields = [
      ["title", "标题"], ["section_type", "类型"], ["body_markdown", "正文"],
      ["projection_policy", "投影策略"], ["sensitivity_hint", "敏感度"], ["linked_asset_ref_hashes", "引用"],
    ].filter(([key]) => JSON.stringify(previous?.[key] ?? null) !== JSON.stringify(section?.[key] ?? null))
      .map(([, label]) => label)
    if (fields.length) changes.push({ kind: "修改", section, fields })
  }
  for (const [sectionId, section] of before) {
    if (!after.has(sectionId)) changes.push({ kind: "删除", section, fields: [] })
  }
  return changes
}

export function createDefaultTaskForm() {
  return {
    task: "", scope: "arc", reveal_mode: "author_safe", budget_tokens: 0,
    entity_ids: [], character_ids: [], viewpoint_character_id: "",
    chapter_index: null, scene_id: "", include_world_synopsis: true,
  }
}

export function applyTaskPreset(form, presetKey) {
  const preset = TASK_PRESETS[presetKey]
  if (!preset) return form
  return {
    ...form,
    task: preset.task,
    scope: preset.scope,
    reveal_mode: preset.reveal_mode,
    viewpoint_character_id: preset.reveal_mode === "character" ? form.viewpoint_character_id : "",
  }
}

export function buildTaskPayload(projectId, form) {
  const viewpoint = form.reveal_mode === "character" ? (form.viewpoint_character_id || undefined) : undefined
  const characterIds = (form.character_ids || []).filter(Boolean)
  const finalCharacterIds = viewpoint ? [...new Set([...characterIds, viewpoint])] : characterIds
  return {
    novel_id: projectId,
    task: String(form.task || "").trim(),
    scope: form.scope || "arc",
    chapter_index: form.chapter_index ? Number(form.chapter_index) : undefined,
    scene_id: form.scene_id || undefined,
    budget_tokens: Number(form.budget_tokens) || 0,
    entity_ids: form.entity_ids?.length ? form.entity_ids : undefined,
    character_ids: finalCharacterIds.length ? finalCharacterIds : undefined,
    reveal_mode: form.reveal_mode || "author_safe",
    viewpoint_character_id: viewpoint,
    include_world_synopsis: !["reader", "character"].includes(form.reveal_mode) && Boolean(form.include_world_synopsis),
  }
}

export function validateTaskPayload(payload) {
  if (!payload.novel_id) return "请先选择项目"
  if (!payload.task) return "请输入任务描述"
  if (payload.reveal_mode === "character" && !payload.viewpoint_character_id) return "角色视角模式必须选择视角人物"
  return null
}

export function buildPovInstruction(instruction, userNote = "") {
  return [
    userNote ? `${userNote}\n` : "",
    String(instruction || "").trim(),
    "请从所选 Scene 的 POV 角色有限认知出发生成正文建议。",
    "用户指令是作者意图，不等于角色知识。",
    "角色判断、台词、内心只能使用确认上下文中该角色可见的信息。",
  ].filter(Boolean).join("\n")
}

export function tierName(key) {
  return ({ core: "核心", standard: "标准", memory: "记忆", rag: "RAG", optional: "可选" })[key] || key
}

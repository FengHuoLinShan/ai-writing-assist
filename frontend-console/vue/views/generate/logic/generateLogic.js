export const AI_MESSAGE_LIMIT = 40
export const AI_SELECTED_CHAPTER_LIMIT = 20
export const AI_SELECTED_WORLD_PAGE_LIMIT = 16
export const EXTERNAL_HANDOFF_PACKET_CHAR_LIMIT = 55_000
export const VISUAL_BRIEF_FIELD_LIMIT = 20_000
export const PAGE_SIZE = 50

export const VISUAL_BRIEF_PURPOSE_OPTIONS = [
  ["overview", "世界／区域总览"],
  ["district", "城区／坊域布局"],
  ["cross_section", "设施／工程剖面"],
  ["scene_route", "场景路线"],
].map(([value, label]) => ({ value, label }))

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
  const availableWorldPageIds = new Set((state.worldPages || []).map((item) => item.id))
  const selectedWorldPageIds = [...new Set(state.selectedWorldPageIds || [])]
    .filter((id) => typeof id === "string" && id !== state.sourcePageId && availableWorldPageIds.has(id))
    .slice(0, AI_SELECTED_WORLD_PAGE_LIMIT)
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
    selected_asset_refs: selectedWorldPageIds.map((id) => ({ type: "world_bible_page", id })),
    activation_profile_id: state.activationProfileId || null,
    activation_profile_version: profile?.version_number || null,
    ...(state.workflowPreset === "world_core" ? { workflow_preset: "world_core" } : {}),
  }
}

const CONVERGENCE_TARGET_LABELS = {
  current_world_target: "当前世界目标",
  world_bible_page: "世界笔记",
  outline: "故事结构",
  map: "地图",
  writing: "正文",
  other: "其他创作入口",
}

const EXTERNAL_DISPOSITION_LABELS = {
  compatible: "可直接兼容",
  repair: "需要修复",
  candidate: "作为候选",
  unmapped: "未能归位",
  exact_duplicate: "完全重复",
}

export function externalDispositionLabel(value) {
  return EXTERNAL_DISPOSITION_LABELS[value] || ""
}

export function externalDispositionCounts(draft) {
  const counts = Object.fromEntries(Object.keys(EXTERNAL_DISPOSITION_LABELS).map((key) => [key, 0]))
  for (const item of (draft?.cards || []).flatMap((card) => card.items || [])) {
    if (item.externalDisposition in counts) counts[item.externalDisposition] += 1
  }
  return counts
}

export function convergenceDraftFromResponse(response, { now = () => Date.now() } = {}) {
  const manifest = new Map((response?.manifest || []).map((item) => [item.key, item]))
  const worldCore = response?.world_core ? {
    ready: Boolean(response.world_core.ready_for_handoff),
    issues: response.world_core.issues || [],
    authorSeedSourceKeys: response.world_core.author_seed_source_keys || [],
    ruleCount: Number(response.world_core.rule_count || 0),
    snapshot: response.world_core.snapshot || null,
    restored: false,
  } : null
  const cards = (response?.decision_cards || []).slice(0, 7).map((card) => ({
    cardId: card.card_id,
    title: card.title,
    commonGround: card.common_ground || [],
    items: (card.items || []).map((item) => ({
      itemId: item.item_id,
      text: item.text,
      disposition: worldCore && item.suggested_disposition === "discard"
        ? "rejected"
        : item.suggested_disposition || "open",
      ruleKey: item.world_core_rule_key || null,
      externalDisposition: item.external_disposition || null,
    })),
    dependencies: card.dependencies || [],
    affectedTargets: card.affected_targets || [],
    sourceRefs: (card.source_keys || []).map((key) => manifest.get(key)).filter(Boolean).map((source) => ({
      key: source.key,
      label: source.label,
      sourceRef: source.source_ref || null,
    })),
    whyNow: card.why_now || "",
  }))
  const draft = {
    schemaVersion: 1,
    generatedAt: new Date(now()).toISOString(),
    manifestHash: response?.coverage?.manifest_hash || "",
    manifest: [...manifest.values()].map((item) => ({
      key: item.key,
      kind: item.kind,
      label: item.label,
      contentHash: item.content_hash,
      sourceRef: item.source_ref || null,
    })),
    sourceSnapshot: response?.source_snapshot || { kind: "project" },
    stale: false,
    coverage: {
      complete: Boolean(response?.coverage?.complete),
      scopeLabel: response?.coverage?.scope_label || "当前可见材料",
      sourceCount: Number(response?.coverage?.source_count || 0),
      coveredSourceCount: (response?.coverage?.covered_source_keys || []).length,
      excludedMessageCount: Number(response?.coverage?.excluded_message_count || 0),
      missingCount: (response?.coverage?.missing_source_keys || []).length,
      issues: response?.coverage?.issues || [],
    },
    detailSummary: response?.detail_summary || { before_grouping: 0, after_deduplication: 0, retained_in_sources: 0 },
    cards,
    nextBoundary: response?.next_boundary || "",
    externalPacket: response?.external_packet ? {
      sha256: response.external_packet.sha256,
      packetIndex: response.external_packet.packet_index,
      packetTotal: response.external_packet.packet_total || null,
    } : null,
    authorMessage: "",
    worldCore,
  }
  draft.authorMessage = compileConvergenceMessage(draft)
  return draft
}

function uniqueBriefLines(values) {
  return [...new Set(values.flatMap((value) => String(value || "").split(/\r?\n/))
    .map((value) => value.replace(/^\s*[-*]\s*/, "").trim()).filter(Boolean))]
}

export function visualBriefFromConvergence(convergenceDraft, { sourceLabel = "当前项目相关资料", sourceTitle = "" } = {}) {
  if (!convergenceDraft?.coverage?.complete || convergenceDraft.stale || !convergenceDraft.manifestHash) return null
  const cards = convergenceDraft.cards || []
  const selected = (disposition) => cards.flatMap((card) => (card.items || [])
    .filter((item) => item.disposition === disposition).map((item) => item.text))
  const mustKeep = uniqueBriefLines([
    ...cards.flatMap((card) => card.commonGround || []),
    ...selected("include"),
  ])
  const openItems = uniqueBriefLines(selected("open"))
  const avoid = uniqueBriefLines([
    ...selected("discard"),
    ...selected("rejected"),
    "不要把仍开放项表现成已确认事实",
    "不要因比例尺、北箭头、标签或画面细节推断设定已被采用",
  ])
  return {
    schemaVersion: 1,
    manifestHash: convergenceDraft.manifestHash,
    sourceLabel,
    purpose: "overview",
    mustKeep: (mustKeep.length ? mustKeep : ["只表现本次来源明确支持的内容；没有依据的细节保持中性"]).join("\n"),
    exactLabels: String(sourceTitle || "").trim(),
    openItems: (openItems.length ? openItems : ["没有额外开放项；仍不得用画面补写未声明事实"]).join("\n"),
    avoid: avoid.join("\n"),
    createdAt: new Date().toISOString(),
    confirmedAt: null,
    stale: false,
  }
}

export function visualBriefMatchesConvergence(visualBrief, convergenceDraft) {
  return Boolean(
    visualBrief && !visualBrief.stale
    && convergenceDraft?.coverage?.complete && !convergenceDraft.stale
    && visualBrief.manifestHash === convergenceDraft.manifestHash,
  )
}

export function buildVisualBriefMarkdown({ handoffMarkdown, visualBrief, convergenceDraft }) {
  if (!handoffMarkdown || !visualBrief?.confirmedAt || !visualBriefMatchesConvergence(visualBrief, convergenceDraft)) return ""
  const purpose = VISUAL_BRIEF_PURPOSE_OPTIONS.find((item) => item.value === visualBrief.purpose)?.label || "单一视觉用途"
  const section = (title, value, fallback) => {
    const lines = uniqueBriefLines([value])
    return `## ${title}\n\n${(lines.length ? lines : [fallback]).map((item) => `- ${item}`).join("\n")}`
  }
  return [
    handoffMarkdown.trimEnd(),
    "---",
    "# 视觉制作简报",
    "- brief_version: world-visual-brief-v1",
    `- 确认时间: ${visualBrief.confirmedAt}`,
    `- 来源状态: ${visualBrief.sourceLabel || "当前项目相关资料"}`,
    `- 来源清单 SHA-256: ${visualBrief.manifestHash}`,
    `- 本次画面用途: ${purpose}`,
    "- 一份简报只服务一种用途；总览、城区和工程剖面需要分别准备。",
    section("必须保留", visualBrief.mustKeep, "只表现来源明确支持的内容"),
    section("必须准确的名称或标签", visualBrief.exactLabels, "没有必须出现在画面中的文字标签"),
    section("仍开放", visualBrief.openItems, "没有额外开放项，但不得自行补写事实"),
    section("不要新增", visualBrief.avoid, "不要新增来源未支持的地点、距离、设施或权威状态"),
    "## 候选图核对\n\n- 文件与尺寸是否可用\n- 名称与标签是否准确\n- 空间关系与方向是否符合来源\n- 是否泄漏开放项或凭空新增细节\n- 是否服务本次画面用途",
    "## 权威边界\n\n这份简报和任何外部候选图都只是参考，不创建图片资产，不确认地点、距离、设施、地图事实或世界设定。需要落回项目的内容必须逐项进入现有地图预览、观察审查或世界建议，由作者再次确认。",
  ].join("\n\n") + "\n"
}

export function externalPacketCharacterCount(value) {
  return [...String(value || "")].length
}

export async function hashExternalPacket(value, cryptoImpl = globalThis.crypto) {
  if (!cryptoImpl?.subtle?.digest) throw new Error("当前浏览器无法计算回包校验码")
  const digest = await cryptoImpl.subtle.digest("SHA-256", new TextEncoder().encode(String(value || "")))
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")
}

export function parseExternalPacketPosition(value, fallbackIndex) {
  const text = String(value || "")
  const number = (name) => {
    const match = text.match(new RegExp("^\\s*(?:[-*]\\s*)?`?packet_" + name + "`?\\s*[:=：]\\s*(\\d+)\\s*$", "im"))
    const parsed = Number(match?.[1])
    return Number.isInteger(parsed) && parsed > 0 && parsed <= 10_000 ? parsed : null
  }
  const packetIndex = number("index") || fallbackIndex
  const packetTotal = number("total")
  return { packetIndex, packetTotal: packetTotal && packetTotal >= packetIndex ? packetTotal : null }
}

export function externalPacketBatchSummary(records = []) {
  const latest = new Map()
  for (const item of records) latest.set(item.packetIndex, item)
  const totals = [...new Set([...latest.values()].map((item) => item.packetTotal).filter(Boolean))]
  if (!totals.length) return { packetTotal: null, complete: false, missingPacketIndexes: [], label: `${latest.size} 份已记录；回包总数未声明` }
  if (totals.length > 1) return { packetTotal: null, complete: false, missingPacketIndexes: [], label: "回包总数不一致，无法确认完整" }
  const packetTotal = totals[0]
  const missingPacketIndexes = Array.from({ length: packetTotal }, (_, index) => index + 1).filter((index) => !latest.has(index))
  const terminal = new Set(["decision_ready", "exact_duplicate"])
  const complete = !missingPacketIndexes.length && Array.from({ length: packetTotal }, (_, index) => latest.get(index + 1)).every((item) => terminal.has(item?.status))
  const progress = `${packetTotal - missingPacketIndexes.length}/${packetTotal}`
  const label = missingPacketIndexes.length
    ? `${progress} 包已收到；缺第 ${missingPacketIndexes.join("、")} 包`
    : complete ? `${progress} 包已完整处理` : `${progress} 包已收到；尚未全部形成作者消息`
  return { packetTotal, complete, missingPacketIndexes, label }
}

const HANDOFF_TARGET_LABELS = {
  core_entity: "世界对象建议",
  world_bible_page: "完善当前世界笔记",
  world_bible_new_page: "新建世界笔记",
}
const HANDOFF_SOURCE_LABELS = {
  conversation: ["本轮对话", "未采用的创作过程"],
  pasted_context: ["外部参考", "未采用的外部材料"],
  source_page: ["当前世界笔记", "权威状态见本页基线"],
  chapter: ["正文摘录", "当前正文参考"],
  asset: ["显式资料", "权威状态以本地来源入口为准"],
  project_background: ["相关项目背景", "相关性选取，不代表全项目"],
}

function handoffPageMarkdown(source) {
  if (!source) return ""
  const parts = [`## 当前目标内容\n\n# ${source.title || "未命名世界笔记"}`]
  if (String(source.free_text || "").trim()) parts.push(String(source.free_text).trim())
  for (const section of [...(source.sections_json || [])].sort((left, right) => Number(left.sort_order || 0) - Number(right.sort_order || 0))) {
    const scope = section.projection_policy === "excluded" ? "不进入普通 AI 上下文" : "可按可见性规则进入 AI 上下文"
    const visibility = { author_only: "仅作者", author_safe: "作者安全", public_baseline: "公开基线" }[section.sensitivity_hint] || "作者资料"
    parts.push(`### ${section.title || "未命名分区"}\n\n> ${scope}；${visibility}\n\n${String(section.body_markdown || "").trim() || "（本分区为空）"}`)
  }
  return parts.join("\n\n")
}

export function buildWorldHandoffMarkdown({ projectTitle, targetKind, sourcePage, sourceDraft, convergenceDraft }) {
  const draft = convergenceDraft
  if (!draft?.coverage?.complete || draft.stale || !draft.manifest?.length) return ""
  const snapshot = draft.sourceSnapshot || { kind: "project" }
  const source = sourceDraft || sourcePage
  const baseline = snapshot.kind === "world_bible_page"
    ? `${snapshot.draft_id ? "服务器工作稿" : "已发布页面"} · v${snapshot.page_version || 1}${snapshot.content_hash ? ` · SHA-256 ${snapshot.content_hash}` : ""}`
    : "当前项目相关资料；P1 无法证明全项目所有来源自本次收束后均未变化"
  const cards = draft.cards.map((card) => {
    const lines = [`### ${card.title}`]
    for (const item of card.commonGround || []) lines.push(`- 共同前提：${item}`)
    const disposition = { include: "本次纳入", open: "继续开放", discard: "明确放弃", rejected: "明确放弃" }
    for (const item of card.items || []) lines.push(`- ${disposition[item.disposition] || "继续开放"}：${item.text}`)
    for (const item of card.dependencies || []) lines.push(`- 依赖／影响：${item}`)
    return lines.join("\n")
  }).join("\n\n")
  const manifest = draft.manifest.map((item) => {
    const [kind, authority] = HANDOFF_SOURCE_LABELS[item.kind] || ["其他来源", "权威状态未声明"]
    return `- ${kind}｜${item.label}｜SHA-256 ${item.contentHash}｜${authority}`
  }).join("\n")
  const omitted = [
    draft.coverage.excludedMessageCount ? `更早的 ${draft.coverage.excludedMessageCount} 条对话` : null,
    "未被本次相关性选择或作者显式选择的项目资料",
    "raw Prompt、token、内部 ID、私有诊断与未打开的来源正文",
    "跨领域自由文本依赖和全项目语义正确性",
  ].filter(Boolean).map((item) => `- ${item}`).join("\n")
  const page = handoffPageMarkdown(source)
  return [
    "# AI 小说创作交接快照",
    `- handoff_version: world-handoff-v1`,
    `- 导出时间: ${draft.generatedAt || "未记录"}`,
    `- 项目: ${projectTitle || "未命名项目"}`,
    `- 当前目标: ${HANDOFF_TARGET_LABELS[targetKind] || "当前世界目标"}`,
    `- 来源基线: ${baseline}`,
    "- 本文件是作者主动导出的参考材料，不会采用或发布任何设定。",
    page,
    `## 当前作者决定\n\n${draft.authorMessage || "尚未形成作者决定消息。"}`,
    `## 决定面\n\n${cards}`,
    `## 来源清单\n\n${manifest}`,
    `## 本地检查回执\n\n- 已运行：来源基线复核；manifest 覆盖校验（${draft.coverage.sourceCount}/${draft.coverage.sourceCount}）。\n- 未运行：全项目一致性检查、跨领域完整依赖检查、外部工具声明的任何检查。\n- 外部回包里的 checks_run、已通过或临时 ID 只作为来源声明，不能成为本地回执或对象 ID。`,
    `## 本次明确遗漏\n\n${omitted}`,
    `## 给外部模型的任务与回包约定\n\n只审查上述单一世界目标，不修改本地项目。回包正文不得超过 ${EXTERNAL_HANDOFF_PACKET_CHAR_LIMIT.toLocaleString("en-US")} 字符；若材料过大，请按当前 target 拆成多包。每包必须列出 packet_index、packet_total、引用的来源标题／SHA-256、checks_run 和 checks_not_run。每项只使用 compatible、repair、candidate、unmapped、exact_duplicate 之一并说明依据。外部编号只是来源标签；不要把未决项写成已确认事实，也不要声称已经运行本地校验。`,
  ].filter(Boolean).join("\n\n") + "\n"
}

export function compileConvergenceMessage(draft) {
  const groups = { include: [], open: [], discard: [], rejected: [] }
  const targets = new Set()
  for (const card of draft?.cards || []) {
    for (const target of card.affectedTargets || []) targets.add(target)
    for (const item of card.items || []) {
      if (groups[item.disposition]) groups[item.disposition].push(item.text)
    }
  }
  const section = (title, values, fallback) => `${title}\n${values.length ? values.map((item) => `- ${item}`).join("\n") : `- ${fallback}`}`
  const otherTargets = [...targets].filter((target) => target !== "current_world_target").map((target) => CONVERGENCE_TARGET_LABELS[target] || CONVERGENCE_TARGET_LABELS.other)
  return [
    "请按以下作者决定继续处理当前世界设定：",
    section("本次纳入：", groups.include, "暂不纳入新的确定内容"),
    section("继续开放（不得写成已确认事实）：", groups.open, "无"),
    section("明确放弃（后续不要恢复）：", [...groups.discard, ...groups.rejected], "无"),
    otherTargets.length ? `另有影响需要分别处理：${[...new Set(otherTargets)].join("、")}。本次只处理当前目标。` : "本次只处理当前世界目标。",
    `本次范围：${draft?.coverage?.scopeLabel || "当前可见材料"}。未列入决定面的细节继续留在原来源。`,
    "这是一条可编辑的作者消息，不代表设定已经采用；最终仍需审阅后续提案。",
  ].join("\n\n")
}

function checkpointSourceRef(manifestItem) {
  const source = manifestItem?.sourceRef || {}
  const sourceType = {
    author_message: "conversation",
    assistant_message: "conversation",
    author_pasted_context: "external",
    world_bible_page: "world_bible_page",
    core_entity: "core_entity",
    writing_chapter: "manuscript",
  }[source.source_type] || "external"
  return {
    source_type: sourceType,
    source_id: manifestItem.key,
    source_version: source.source_version == null ? null : String(source.source_version),
    source_hash: source.source_hash || manifestItem.contentHash,
    ...(Number.isInteger(source.range_start) ? { range_start: source.range_start } : {}),
    ...(Number.isInteger(source.range_end) ? { range_end: source.range_end } : {}),
    ...(source.scene_id ? { scene_id: source.scene_id } : {}),
    ...(source.workflow_id ? { workflow_id: source.workflow_id } : {}),
    ...(source.authorization_ref ? { authorization_ref: source.authorization_ref } : {}),
  }
}

export function buildWorldCoreCheckpointRequest({ novelId, draft, roundNo, action, parentCheckpointId = null }) {
  if (!draft?.worldCore?.ready || !draft.worldCore.snapshot || draft.stale || !draft.manifestHash) return null
  const manifest = new Map((draft.manifest || []).map((item) => [item.key, item]))
  const seedDispositions = new Map((draft.worldCore.snapshot.author_seeds || []).map((item) => [item.source_key, item.disposition]))
  const authorKeys = draft.worldCore.authorSeedSourceKeys || []
  if (authorKeys.some((key) => !manifest.get(key)?.contentHash)) return null
  const atoms = new Map((draft.worldCore.snapshot.rule_atoms || []).map((item) => [item.rule_key, item]))
  const decisions = (draft.cards || []).flatMap((card) => card.items || [])
  const includedRuleKeys = new Set(decisions.filter((item) => item.disposition === "include" && item.ruleKey).map((item) => item.ruleKey))
  const includedAtoms = [...atoms.values()].filter((item) => includedRuleKeys.has(item.rule_key))
  const verticalSlice = draft.worldCore.snapshot.vertical_slice
  if (includedAtoms.length < 3 || includedAtoms.length > 7 || !verticalSlice || !includedRuleKeys.has(verticalSlice.rule_key)) return null
  return {
    novel_id: novelId,
    checkpoint: {
      schema_version: "world_core_checkpoint.v1",
      round_no: Math.max(0, Number(roundNo) || 0),
      action: ["expand", "connect", "pressure", "consolidate"].includes(action) ? action : "consolidate",
      parent_checkpoint_id: parentCheckpointId || null,
      source_manifest_hash: draft.manifestHash,
      seeds: authorKeys.map((key, index) => ({
        seed_key: `seed_${index + 1}`,
        source_ref: checkpointSourceRef(manifest.get(key)),
        disposition: seedDispositions.get(key) || "open",
      })),
      world_core: {
        ...draft.worldCore.snapshot,
        rule_atoms: includedAtoms,
      },
      decisions: decisions.map((item) => ({
        item_key: item.itemId,
        text: item.text,
        disposition: item.disposition === "include" ? "locked" : item.disposition === "open" ? "open" : "rejected",
        rule_key: item.ruleKey || null,
        source_keys: item.ruleKey ? atoms.get(item.ruleKey)?.source_keys || [] : [],
      })),
    },
  }
}

const WORLD_FACETS = [
  "本体法则与不可行域", "地理、生态与气候", "资源、承载力与城市代谢", "技术、魔法与基础设施",
  "故障、维修与韧性", "人口结构与生命历程", "家庭、亲属与照护", "身体、医疗、残障与死亡",
  "劳动、职业与技能传承", "住房、消费与日常时间", "财产、货币、信用、债务与供应链", "正式制度、非正式制度与组织政治",
  "行政能力、裁量与合法性", "法律、证据、申诉与多法域", "阶层、地位、身份与社会边界", "战争、边境、迁徙与外部关系",
  "知识、教育、档案与谣言", "语言、语域、命名与翻译", "宗教、仪式、禁忌与道德经济", "情绪规则、身体经验与物质文化",
  "历史沉积与路径依赖", "网络、集体行动、涌现与反馈",
]
const WORLD_COUPLING_CHAINS = ["权利链", "技术链", "身份链", "证据链", "分配链"]
const WORLD_PRESSURE_TESTS = [
  "主角移除", "普通星期二", "一生", "最贫者", "上层例外", "一项权利",
  "一件商品", "故障与维修", "跨境", "历史来源", "集体行动", "十年后",
]

function gap(reason = "当前 World Core 没有足够证据") {
  return { status: "gap", chain: [], evidence: [], gaps: [reason], reason }
}

function pipeline(status, artifacts = []) {
  return { status, artifacts, invalidated_by: [], notes: [] }
}

export function buildWorldDesignCheckpointRequest({ novelId, projectTitle = "当前世界", draft, roundNo, action, parentCheckpointId = null }) {
  const core = buildWorldCoreCheckpointRequest({ novelId, draft, roundNo, action, parentCheckpointId })
  if (!core) return null
  const checkpoint = core.checkpoint
  const evidence = [...new Set(checkpoint.seeds.map((item) => item.source_ref.source_id))]
  const rules = checkpoint.world_core.rule_atoms.map((rule, index) => ({
    id: `rule:${String(index + 1).padStart(2, "0")}`,
    name: rule.title,
    status: "proposed",
    capability: rule.can,
    impossibility: rule.cannot,
    inputs: [],
    outputs: [],
    costs: [rule.cost],
    losses: [],
    access: [],
    visibility: [],
    scale_limits: [],
    failure_modes: [rule.failure],
    maintenance: [rule.maintenance],
    countermeasures: [],
    knowledge_layer: "author_truth",
    dependencies: [],
    evidence: rule.source_keys,
  }))
  const locked = checkpoint.decisions.filter((item) => item.disposition === "locked")
  const open = checkpoint.decisions.filter((item) => item.disposition === "open")
  const verticalSlice = checkpoint.world_core.vertical_slice
  const ordinaryTuesday = verticalSlice
    ? { status: "partial", scenario: verticalSlice.daily_consequence, actors: [], evidence, contradictions: [], reason: "仅有一条日常纵切，尚未覆盖完整生活系统" }
    : { status: "gap", scenario: "", actors: [], evidence: [], contradictions: [], reason: "尚无日常纵切证据" }
  const state = {
    schema_version: "0.1.0",
    engine_version: "worldbuilding-engine/0.7.0",
    project: {
      id: novelId,
      title: String(projectTitle || "当前世界").slice(0, 500),
      language: "zh-CN",
      seed: locked.map((item) => item.text).join("；").slice(0, 5000),
      mode: checkpoint.action === "expand" ? "expand" : "create",
      status: "developing",
      created_at: null,
      updated_at: null,
    },
    authority: {
      source_of_truth: evidence,
      read_only: [],
      constraints: checkpoint.decisions.filter((item) => item.disposition === "rejected").map((item) => item.text),
      locked_decisions: locked.map((item, index) => ({ id: `decision:locked:${index + 1}`, question: item.text, status: "proposed", evidence: item.source_keys })),
      author_required: [],
      open_questions: open.map((item, index) => ({ id: `decision:open:${index + 1}`, question: item.text, status: "author-required", evidence: item.source_keys })),
    },
    premise: {
      status: "proposed",
      core_difference: locked.map((item) => item.text).join("；").slice(0, 5000),
      human_experience: verticalSlice?.daily_consequence || "",
      scale: "尚待确认",
      aesthetic_surface: [],
      themes: [],
      evidence,
    },
    knowledge_layers: { author_truth: [], expert_models: [], public_beliefs: [], reader_unknowns: [] },
    rules,
    reproduction_loops: Object.fromEntries(["material", "population_care", "economic", "institutional", "knowledge", "meaning_identity"].map((key) => [key, gap()])),
    facets: WORLD_FACETS.map((name, index) => ({ id: `F${String(index + 1).padStart(2, "0")}`, name, status: "gap", maturity: { framework: 0, instance: 0 }, evidence: [], gaps: ["尚未审计"], dependencies: [], reason: "种子 checkpoint 不推断未提供的世界细节" })),
    coupling_chains: WORLD_COUPLING_CHAINS.map((name, index) => ({ id: `C${String(index + 1).padStart(2, "0")}`, name, status: "gap", nodes: [], breaks: [], evidence: [], reason: "尚未建立跨系统因果链" })),
    situated_tests: {
      ordinary_tuesday: ordinaryTuesday,
      seven_day_failure: { status: "gap", scenario: verticalSlice?.failure_consequence || "", actors: [], evidence: [], contradictions: [], reason: "尚未完成七日故障推演" },
      life_course: { status: "gap", scenario: "", actors: [], evidence: [], contradictions: [], reason: "尚未完成人生历程推演" },
      ten_year_feedback: { status: "gap", scenario: "", actors: [], evidence: [], contradictions: [], reason: "尚未完成十年反馈推演" },
    },
    pressure_tests: WORLD_PRESSURE_TESTS.map((name, index) => ({ id: `T${String(index + 1).padStart(2, "0")}`, name, status: "not-run", result: "", evidence: [], failures: [] })),
    actors: [], places: [], institutions: [], history: [],
    fiction_core: {
      world: pipeline("in-progress", rules.map((item) => item.id)),
      character: pipeline("not-started"), story: pipeline("not-started"), outline: pipeline("not-started"),
      prose: pipeline("not-started"), editor: pipeline("not-started"),
    },
    dependencies: [],
    change_log: [{ id: `checkpoint:${Math.max(0, Number(roundNo) || 0)}`, at: null, summary: "作者保存世界设计种子 checkpoint", source: checkpoint.source_manifest_hash, authority: "proposed", changed_ids: rules.map((item) => item.id), invalidated_layers: [] }],
    audit: { last_run_at: null, engine_version: "worldbuilding-engine/0.7.0", valid: null, blocking_gaps: [], warnings: [] },
    extensions: { iteration: { depth: "seed", round_no: checkpoint.round_no, checkpoint_every: 3, action: checkpoint.action } },
  }
  return {
    novel_id: novelId,
    checkpoint: { ...checkpoint, schema_version: "world_design_checkpoint.v1", depth: "seed", world_state: state },
  }
}

export function convergenceDraftFromCheckpoint(artifact, { now = () => Date.now() } = {}) {
  const payload = artifact?.payload_json
  const checkpointSchemas = {
    world_core_checkpoint: "world_core_checkpoint.v1",
    world_design_checkpoint: "world_design_checkpoint.v1",
  }
  if (payload?.schema_version !== checkpointSchemas[artifact?.target_type] || !payload.world_core) return null
  const manifests = (payload.seeds || []).map((seed) => ({
    key: seed.source_ref.source_id,
    kind: seed.source_ref.source_type === "conversation" ? "conversation" : "pasted_context",
    label: `作者种子 ${seed.seed_key.replace(/^seed_/, "")}`,
    contentHash: seed.source_ref.source_hash,
    sourceRef: seed.source_ref,
  }))
  const atoms = payload.world_core.rule_atoms || []
  const cards = [{
    cardId: "checkpoint",
    title: "已保存的世界核心决定",
    commonGround: [],
    items: (payload.decisions || []).map((item) => ({
      itemId: item.item_key,
      text: item.text,
      disposition: item.disposition === "locked" ? "include" : item.disposition,
      ruleKey: item.rule_key || null,
      externalDisposition: null,
    })),
    dependencies: [],
    affectedTargets: ["current_world_target"],
    sourceRefs: manifests.map((item) => ({ key: item.key, label: item.label, sourceRef: item.sourceRef })),
    whyNow: "这是作者显式保存的阶段决定，不包含过时的 AI 聊天正文。",
  }]
  const draft = {
    schemaVersion: 1,
    generatedAt: new Date(now()).toISOString(),
    manifestHash: payload.source_manifest_hash,
    manifest: manifests,
    sourceSnapshot: { kind: "project" },
    stale: false,
    coverage: {
      complete: true,
      scopeLabel: "已保存的作者决定摘要",
      sourceCount: manifests.length,
      coveredSourceCount: manifests.length,
      excludedMessageCount: 0,
      missingCount: 0,
      issues: [],
    },
    detailSummary: { before_grouping: atoms.length, after_deduplication: atoms.length, retained_in_sources: 0 },
    cards,
    nextBoundary: "从已保存的规则和作者决定继续，不重放旧 AI 回复。",
    externalPacket: null,
    authorMessage: "",
    worldCore: {
      ready: true,
      issues: [],
      authorSeedSourceKeys: (payload.world_core.author_seeds || []).map((item) => item.source_key),
      ruleCount: atoms.length,
      snapshot: payload.world_core,
      restored: true,
    },
  }
  draft.authorMessage = compileConvergenceMessage(draft)
  return draft
}

export function buildWorldCoreCheckpointContext(draft) {
  if (!draft?.worldCore?.restored || !draft.worldCore.snapshot) return ""
  const snapshot = draft.worldCore.snapshot
  const decisions = (draft.cards || []).flatMap((card) => card.items || [])
  const group = (disposition) => decisions.filter((item) => item.disposition === disposition).map((item) => item.text)
  const section = (title, values) => `${title}\n${values.length ? values.map((item) => `- ${item}`).join("\n") : "- 无"}`
  return [
    "# 已保存的 World Core 作者决定摘要",
    "这份摘要是作者显式保存的阶段结果，不包含旧 AI 聊天正文。",
    section("纳入当前预览", group("include")),
    section("继续开放", group("open")),
    section("明确否定", [...group("rejected"), ...group("discard")]),
    "## 规则原子",
    ...(snapshot.rule_atoms || []).map((rule) => [
      `### ${rule.title}`,
      `- 可以：${rule.can}`,
      `- 不能：${rule.cannot}`,
      `- 代价：${rule.cost}`,
      `- 故障：${rule.failure}`,
      `- 维护：${rule.maintenance}`,
    ].join("\n")),
    snapshot.vertical_slice
      ? `## 日常＋故障纵切\n- 日常：${snapshot.vertical_slice.daily_consequence}\n- 故障：${snapshot.vertical_slice.failure_consequence}`
      : "",
    "继续生长时不得复活明确否定项，开放项不得写成已采用事实。",
  ].filter(Boolean).join("\n\n")
}

export function convergenceSourceMatchesPayload(draft, payload) {
  const snapshot = draft?.sourceSnapshot || {}
  const source = payload?.source_context || { kind: "project" }
  if (snapshot.kind !== source.kind) return false
  if (source.kind === "project") return true
  const baseline = source.baseline || {}
  return snapshot.page_id === source.page_id
    && Number(snapshot.page_version || 0) === Number(baseline.page_version || 0)
    && (snapshot.draft_id || null) === (baseline.draft_id || null)
    && (snapshot.draft_updated_at || null) === (baseline.draft_updated_at || null)
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

export function authorDecisionPresentation(state) {
  if (!state || typeof state !== "object") return null
  const unique = (values) => [...new Set(values.filter((value) => String(value || "").trim()).map((value) => String(value).trim()))]
  const naming = {
    allowed: "可以命名",
    unnamed_placeholder: "暂不命名，只使用描述性占位",
    uncertain: "是否命名尚不确定",
  }[state.naming_policy] || "命名方式尚未确认"
  const rows = [
    ["本轮目标", [state.current_author_goal]],
    ["必须保留", state.confirmed_requirements],
    ["可以发展", state.supported_developments],
    ["不要再出现", [...(state.rejected_elements || []), ...(state.forbidden_exact_terms || [])]],
    ["仍由我决定", state.unresolved_choices],
    ["命名边界", [naming]],
    ["谁能知道 / 如何表达", state.knowledge_expression_boundaries],
  ].map(([label, values]) => ({ label, items: unique(Array.isArray(values) ? values : []) }))
    .filter((row) => row.items.length)
  const confidence = state.confidence === null || state.confidence === undefined ? Number.NaN : Number(state.confidence)
  return {
    rows,
    needsReview: Boolean(state.unresolved_choices?.length)
      || (Number.isFinite(confidence) && confidence < 0.5),
  }
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

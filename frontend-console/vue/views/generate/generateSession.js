import {
  AI_MESSAGE_LIMIT,
  AI_SELECTED_CHAPTER_LIMIT,
  AI_SELECTED_WORLD_PAGE_LIMIT,
  REVEAL_OPTIONS,
  SCOPE_OPTIONS,
  TASK_PRESETS,
  VISUAL_BRIEF_FIELD_LIMIT,
  VISUAL_BRIEF_PURPOSE_OPTIONS,
  createDefaultTaskForm,
} from "./logic/generateLogic.js"
import { normalizePageProposalDraft } from "./pageProposalSession.js"

export const GENERATE_STATE_STORAGE_PREFIX = "generate_world_workspace_state_v2_"
export const GENERATE_STATE_MAX_PROJECTS = 5
export const GENERATE_STATE_MAX_BYTES = 512 * 1024
export const GENERATE_INTERRUPTED_CHAT_MESSAGE = "上次回复在离开或刷新时尚未返回，本页已停止等待。请确认后再重试，避免重复请求。"
export const CREATIVE_CONTINUATION_STORAGE_PREFIX = "novel_creative_continuation_v1:"
const CREATIVE_CONTINUATION_DESTINATIONS = new Set(["generate", "world_bible_draft", "world_suggestion_review"])
const GENERATE_TARGETS = new Set(["core_entity", "world_bible_page", "world_bible_new_page"])
const CONVERGENCE_DISPOSITIONS = new Set(["include", "open", "discard", "rejected"])
const EXTERNAL_PACKET_STATUSES = new Set(["previewed", "incomplete", "decision_ready", "exact_duplicate"])
const EXTERNAL_DISPOSITIONS = new Set(["compatible", "repair", "candidate", "unmapped", "exact_duplicate"])
const EXTERNAL_PACKET_HISTORY_LIMIT = 20
const SHA256_RE = /^[0-9a-f]{64}$/
const VISUAL_BRIEF_PURPOSES = new Set(VISUAL_BRIEF_PURPOSE_OPTIONS.map((item) => item.value))
const TASK_SCOPES = new Set(SCOPE_OPTIONS.map((item) => item.value))
const TASK_REVEAL_MODES = new Set(REVEAL_OPTIONS.map((item) => item.value))
const contextPreviews = new Map()
const CONTEXT_PREVIEW_STORAGE_PREFIX = "generate_context_preview_v1:"

function boundedText(value, max = 20_000) {
  return typeof value === "string" ? value.slice(0, max) : ""
}

function boundedIds(value) {
  return Array.isArray(value)
    ? value.filter((item) => typeof item === "string" && item).slice(0, 20)
    : []
}

export function normalizeTaskForm(value) {
  const fallback = createDefaultTaskForm()
  if (!value || typeof value !== "object" || Array.isArray(value)) return fallback
  const chapterIndex = Number(value.chapter_index)
  const budgetTokens = Number(value.budget_tokens)
  return {
    task: boundedText(value.task),
    scope: TASK_SCOPES.has(value.scope) ? value.scope : fallback.scope,
    entity_ids: boundedIds(value.entity_ids),
    character_ids: boundedIds(value.character_ids),
    scene_id: boundedText(value.scene_id, 256),
    chapter_index: Number.isInteger(chapterIndex) && chapterIndex > 0 ? chapterIndex : null,
    reveal_mode: TASK_REVEAL_MODES.has(value.reveal_mode) ? value.reveal_mode : fallback.reveal_mode,
    viewpoint_character_id: boundedText(value.viewpoint_character_id, 256),
    budget_tokens: Number.isFinite(budgetTokens) ? Math.max(0, Math.min(1_000_000, Math.trunc(budgetTokens))) : 0,
    include_world_synopsis: value.include_world_synopsis !== false,
  }
}

export function normalizePovForm(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { chapterIndex: null, sceneId: "", viewpointCharacterId: "", instruction: "" }
  }
  const chapterIndex = Number(value.chapterIndex)
  return {
    chapterIndex: Number.isInteger(chapterIndex) && chapterIndex > 0 ? chapterIndex : null,
    sceneId: boundedText(value.sceneId, 256),
    viewpointCharacterId: boundedText(value.viewpointCharacterId, 256),
    instruction: boundedText(value.instruction),
  }
}

function emptyContextPreview() {
  return {
    bundle: null,
    markdown: "",
    source: null,
    request: null,
  }
}

export function readGenerateContextPreview(projectId, { storage = globalThis.sessionStorage } = {}) {
  const key = projectId || "none"
  if (contextPreviews.has(key)) return contextPreviews.get(key)
  const storageKey = `${CONTEXT_PREVIEW_STORAGE_PREFIX}${key}`
  try {
    const raw = storage?.getItem(storageKey)
    if (!raw) return emptyContextPreview()
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("invalid context preview")
    if (parsed.bundle && parsed.bundle.novel_id !== projectId) throw new Error("mismatched context preview")
    if (parsed.request && parsed.request.novel_id !== projectId) throw new Error("mismatched context request")
    const preview = {
      bundle: parsed.bundle && typeof parsed.bundle === "object" && !Array.isArray(parsed.bundle) ? parsed.bundle : null,
      markdown: typeof parsed.markdown === "string" ? parsed.markdown : "",
      source: ["task", "world"].includes(parsed.source) ? parsed.source : null,
      request: parsed.request && typeof parsed.request === "object" && !Array.isArray(parsed.request) ? parsed.request : null,
    }
    contextPreviews.set(key, preview)
    return preview
  } catch {
    try { storage?.removeItem(storageKey) } catch {}
    return emptyContextPreview()
  }
}

export function writeGenerateContextPreview(projectId, value = {}, { storage = globalThis.sessionStorage } = {}) {
  const key = projectId || "none"
  const storageKey = `${CONTEXT_PREVIEW_STORAGE_PREFIX}${key}`
  const preview = {
    bundle: value.bundle || null,
    markdown: value.markdown || "",
    source: value.source || null,
    request: value.request || null,
  }
  if (!preview.bundle && !preview.markdown && !preview.source && !preview.request) {
    contextPreviews.delete(key)
    try { storage?.removeItem(storageKey) } catch {}
    return
  }
  contextPreviews.delete(key)
  contextPreviews.set(key, preview)
  try {
    let serialized = JSON.stringify(preview)
    if (byteLength(serialized) > GENERATE_STATE_MAX_BYTES && preview.markdown) {
      serialized = JSON.stringify({ ...preview, markdown: "" })
    }
    if (byteLength(serialized) <= GENERATE_STATE_MAX_BYTES) storage?.setItem(storageKey, serialized)
    else storage?.removeItem(storageKey)
  } catch {}
  while (contextPreviews.size > GENERATE_STATE_MAX_PROJECTS) {
    contextPreviews.delete(contextPreviews.keys().next().value)
  }
}

export function generateSessionKey(projectId, sourcePageId = null, targetKind = "core_entity", preset = "custom") {
  const suffix = preset === "world_core" ? "_world_core" : ""
  return `${GENERATE_STATE_STORAGE_PREFIX}${projectId || "none"}_${sourcePageId || "project"}_${targetKind || "core_entity"}${suffix}`
}

export function emptyGenerateSession() {
  return {
    composer: "",
    selectedTemplateId: "builtin:none",
    messages: [],
    selectedChapters: [],
    qualityMode: "fast",
    includeWorldSynopsis: true,
    activationProfileId: null,
    selectedSceneId: "",
    selectedThreadIds: [],
    selectedCharacterIds: [],
    selectedEntityIds: [],
    selectedWorldPageIds: [],
    newPageType: "custom",
    newPageTemplateKey: "",
    suggestionId: null,
    pageProposalDraft: null,
    convergenceDraft: null,
    visualBrief: null,
    externalPacketDraft: "",
    externalPackets: [],
    successfulRounds: 0,
    worldCoreAction: "expand",
    checkpointId: null,
    checkpointRound: 0,
    checkpointDepth: null,
    taskPreset: "custom",
    taskForm: createDefaultTaskForm(),
    povForm: normalizePovForm(),
  }
}

export function normalizeConvergenceDraft(value) {
  if (value == null) return null
  if (
    typeof value !== "object" || Array.isArray(value) || value.schemaVersion !== 1
    || typeof value.manifestHash !== "string" || !value.manifestHash
    || typeof value.stale !== "boolean" || !Array.isArray(value.cards) || value.cards.length > 7
    || typeof value.authorMessage !== "string"
  ) return null
  if (value.externalPacketHash != null && !SHA256_RE.test(value.externalPacketHash)) return null
  if (value.manifest != null && (!Array.isArray(value.manifest) || value.manifest.some((item) => (
    !item || typeof item.key !== "string" || typeof item.kind !== "string" || typeof item.label !== "string" || !SHA256_RE.test(item.contentHash)
  )))) return null
  for (const card of value.cards) {
    if (!card || typeof card !== "object" || typeof card.cardId !== "string" || typeof card.title !== "string" || !Array.isArray(card.items) || !card.items.length) return null
    for (const item of card.items) {
      if (!item || typeof item.itemId !== "string" || typeof item.text !== "string" || !CONVERGENCE_DISPOSITIONS.has(item.disposition) || (item.externalDisposition != null && !EXTERNAL_DISPOSITIONS.has(item.externalDisposition))) return null
    }
  }
  return value
}

export function normalizeExternalPackets(value) {
  if (!Array.isArray(value)) return []
  return value.filter((item) => (
    item && typeof item === "object" && !Array.isArray(item)
    && SHA256_RE.test(item.hash)
    && Number.isInteger(item.packetIndex) && item.packetIndex > 0 && item.packetIndex <= 10_000
    && (item.packetTotal == null || (Number.isInteger(item.packetTotal) && item.packetTotal >= item.packetIndex && item.packetTotal <= 10_000))
    && Number.isInteger(item.characterCount) && item.characterCount >= 0 && item.characterCount <= 55_000
    && EXTERNAL_PACKET_STATUSES.has(item.status)
    && (item.manifestHash == null || SHA256_RE.test(item.manifestHash))
    && (item.sourceCount == null || (Number.isInteger(item.sourceCount) && item.sourceCount >= 0))
    && (item.coveredSourceCount == null || (Number.isInteger(item.coveredSourceCount) && item.coveredSourceCount >= 0 && (item.sourceCount == null || item.coveredSourceCount <= item.sourceCount)))
    && (item.dispositionCounts == null || (typeof item.dispositionCounts === "object" && !Array.isArray(item.dispositionCounts) && [...EXTERNAL_DISPOSITIONS].every((key) => Number.isInteger(item.dispositionCounts[key]) && item.dispositionCounts[key] >= 0)))
  )).slice(-EXTERNAL_PACKET_HISTORY_LIMIT).map((item) => ({
    hash: item.hash,
    packetIndex: item.packetIndex,
    packetTotal: item.packetTotal || null,
    characterCount: item.characterCount,
    status: item.status,
    previewedAt: Number.isFinite(item.previewedAt) ? item.previewedAt : null,
    ...(item.manifestHash ? { manifestHash: item.manifestHash } : {}),
    ...(item.sourceCount != null ? { sourceCount: item.sourceCount } : {}),
    ...(item.coveredSourceCount != null ? { coveredSourceCount: item.coveredSourceCount } : {}),
    ...(item.dispositionCounts ? { dispositionCounts: Object.fromEntries([...EXTERNAL_DISPOSITIONS].map((key) => [key, item.dispositionCounts[key]])) } : {}),
  }))
}

export function normalizeVisualBrief(value) {
  if (value == null) return null
  const textFields = ["sourceLabel", "mustKeep", "exactLabels", "openItems", "avoid"]
  if (
    typeof value !== "object" || Array.isArray(value) || value.schemaVersion !== 1
    || !SHA256_RE.test(value.manifestHash) || !VISUAL_BRIEF_PURPOSES.has(value.purpose)
    || typeof value.stale !== "boolean"
    || textFields.some((key) => typeof value[key] !== "string" || value[key].length > VISUAL_BRIEF_FIELD_LIMIT)
    || typeof value.createdAt !== "string" || value.createdAt.length > 64
    || (value.confirmedAt != null && (typeof value.confirmedAt !== "string" || value.confirmedAt.length > 64))
  ) return null
  return {
    schemaVersion: 1,
    manifestHash: value.manifestHash,
    sourceLabel: value.sourceLabel,
    purpose: value.purpose,
    mustKeep: value.mustKeep,
    exactLabels: value.exactLabels,
    openItems: value.openItems,
    avoid: value.avoid,
    createdAt: value.createdAt,
    confirmedAt: value.confirmedAt || null,
    stale: value.stale,
  }
}

function persistedShape(value) {
  return {
    savedAt: Date.now(),
    composer: typeof value.composer === "string" ? value.composer : "",
    selectedTemplateId: value.selectedTemplateId || "builtin:none",
    // A live pending bubble remains pending in the mounted UI. Its snapshot is
    // deliberately terminal so a reload cannot leave the author's last user
    // message looking unanswered or cause an implicit retry.
    messages: (value.messages || []).map((item) => item.pending
      ? { role: "assistant", content: GENERATE_INTERRUPTED_CHAT_MESSAGE, error: true, interrupted: true }
      : item),
    selectedChapters: (value.selectedChapters || []).slice(0, AI_SELECTED_CHAPTER_LIMIT),
    qualityMode: value.qualityMode || "fast",
    includeWorldSynopsis: value.includeWorldSynopsis !== false,
    activationProfileId: value.activationProfileId || null,
    selectedSceneId: value.selectedSceneId || "",
    selectedThreadIds: value.selectedThreadIds || [],
    selectedCharacterIds: value.selectedCharacterIds || [],
    selectedEntityIds: value.selectedEntityIds || [],
    selectedWorldPageIds: (value.selectedWorldPageIds || []).slice(0, AI_SELECTED_WORLD_PAGE_LIMIT),
    newPageType: value.newPageType || "custom",
    newPageTemplateKey: value.newPageTemplateKey || "",
    suggestionId: value.suggestionId || null,
    pageProposalDraft: normalizePageProposalDraft(value.pageProposalDraft),
    convergenceDraft: normalizeConvergenceDraft(value.convergenceDraft),
    visualBrief: normalizeVisualBrief(value.visualBrief),
    externalPacketDraft: typeof value.externalPacketDraft === "string" ? value.externalPacketDraft : "",
    externalPackets: normalizeExternalPackets(value.externalPackets),
    successfulRounds: Math.max(0, Math.min(999, Number(value.successfulRounds) || 0)),
    worldCoreAction: ["expand", "connect", "pressure", "consolidate"].includes(value.worldCoreAction) ? value.worldCoreAction : "expand",
    checkpointId: typeof value.checkpointId === "string" && value.checkpointId ? value.checkpointId : null,
    checkpointRound: Math.max(0, Math.min(999, Number(value.checkpointRound) || 0)),
    checkpointDepth: ["seed", "candidate", "instance"].includes(value.checkpointDepth) ? value.checkpointDepth : null,
    taskPreset: TASK_PRESETS[value.taskPreset] ? value.taskPreset : "custom",
    taskForm: normalizeTaskForm(value.taskForm),
    povForm: normalizePovForm(value.povForm),
  }
}

function isArrayShape(value) {
  return ["messages", "selectedChapters", "selectedThreadIds", "selectedCharacterIds", "selectedEntityIds", "selectedWorldPageIds", "externalPackets"]
    .every((key) => !(key in value) || Array.isArray(value[key]))
}

function isSessionShape(value) {
  return isArrayShape(value) && (!("composer" in value) || typeof value.composer === "string")
}

function byteLength(value) {
  return new TextEncoder().encode(value).byteLength
}

function storageEntries(storage, excludeKey = null) {
  const entries = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (!key?.startsWith(GENERATE_STATE_STORAGE_PREFIX) || key === excludeKey) continue
    let savedAt = 0
    try { savedAt = Number(JSON.parse(storage.getItem(key))?.savedAt) || 0 } catch {}
    entries.push({ key, savedAt })
  }
  return entries.sort((left, right) => left.savedAt - right.savedAt || left.key.localeCompare(right.key))
}

export function readGenerateSession(key, { storage = globalThis.localStorage, notify = () => {} } = {}) {
  const fallback = emptyGenerateSession()
  let raw
  try { raw = storage?.getItem(key) } catch {
    notify("read-failed", "无法读取生成中心本地会话；当前数据库内容不受影响。")
    return fallback
  }
  if (!raw) return fallback
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || !isSessionShape(parsed)) {
      throw new Error("invalid local state")
    }
    const pageProposalDraft = "pageProposalDraft" in parsed ? normalizePageProposalDraft(parsed.pageProposalDraft) : null
    const convergenceDraft = "convergenceDraft" in parsed ? normalizeConvergenceDraft(parsed.convergenceDraft) : null
    const visualBrief = "visualBrief" in parsed ? normalizeVisualBrief(parsed.visualBrief) : null
    if ("pageProposalDraft" in parsed && !pageProposalDraft && parsed.pageProposalDraft !== null) {
      try { storage?.setItem(key, JSON.stringify({ ...parsed, pageProposalDraft: null })) } catch {}
      notify("invalid-page-proposal-draft", "上次未应用的提案编辑无法恢复，已忽略该本地副本；当前数据库内容不受影响。")
    }
    if ("convergenceDraft" in parsed && !convergenceDraft && parsed.convergenceDraft !== null) {
      try { storage?.setItem(key, JSON.stringify({ ...parsed, pageProposalDraft, convergenceDraft: null })) } catch {}
      notify("invalid-convergence-draft", "上次收束预览无法恢复，已忽略该本地副本；对话和项目内容仍保留。")
    }
    if ("visualBrief" in parsed && !visualBrief && parsed.visualBrief !== null) {
      try { storage?.setItem(key, JSON.stringify({ ...parsed, pageProposalDraft, convergenceDraft, visualBrief: null })) } catch {}
      notify("invalid-visual-brief", "上次视觉简报无法恢复，已忽略该本地副本；项目内容不受影响。")
    }
    return {
      ...fallback,
      ...parsed,
      pageProposalDraft,
      convergenceDraft,
      visualBrief,
      externalPacketDraft: typeof parsed.externalPacketDraft === "string" ? parsed.externalPacketDraft : "",
      externalPackets: normalizeExternalPackets(parsed.externalPackets),
      messages: parsed.messages || [],
      selectedChapters: (parsed.selectedChapters || []).slice(0, AI_SELECTED_CHAPTER_LIMIT),
      selectedWorldPageIds: (parsed.selectedWorldPageIds || []).slice(0, AI_SELECTED_WORLD_PAGE_LIMIT),
      successfulRounds: Math.max(0, Math.min(999, Number(parsed.successfulRounds) || 0)),
      worldCoreAction: ["expand", "connect", "pressure", "consolidate"].includes(parsed.worldCoreAction) ? parsed.worldCoreAction : "expand",
      checkpointId: typeof parsed.checkpointId === "string" && parsed.checkpointId ? parsed.checkpointId : null,
      checkpointRound: Math.max(0, Math.min(999, Number(parsed.checkpointRound) || 0)),
      checkpointDepth: ["seed", "candidate", "instance"].includes(parsed.checkpointDepth) ? parsed.checkpointDepth : null,
      taskPreset: TASK_PRESETS[parsed.taskPreset] ? parsed.taskPreset : "custom",
      taskForm: normalizeTaskForm(parsed.taskForm),
      povForm: normalizePovForm(parsed.povForm),
    }
  } catch {
    try { storage?.removeItem(key) } catch {}
    notify("invalid-state", "生成中心本地会话已损坏，已忽略该缓存；当前数据库内容不受影响。")
    return fallback
  }
}

export function hasGenerateSession(key, options = {}) {
  const storage = options.storage || globalThis.localStorage
  try {
    if (!storage?.getItem(key)) return false
  } catch {
    return false
  }
  readGenerateSession(key, { ...options, storage })
  try {
    return Boolean(storage?.getItem(key))
  } catch {
    return false
  }
}

export function serializeGenerateSession(value) {
  const payload = persistedShape(value)
  let serialized = JSON.stringify(payload)
  let compactedConvergence = false
  if (byteLength(serialized) > GENERATE_STATE_MAX_BYTES && payload.convergenceDraft) {
    payload.convergenceDraft = {
      ...payload.convergenceDraft,
      nextBoundary: "",
      cards: payload.convergenceDraft.cards.map((card) => ({
        ...card,
        commonGround: [],
        dependencies: [],
        whyNow: "",
      })),
    }
    compactedConvergence = true
    serialized = JSON.stringify(payload)
  }
  let droppedMessages = 0
  if (byteLength(serialized) > GENERATE_STATE_MAX_BYTES && payload.messages.length > AI_MESSAGE_LIMIT) {
    droppedMessages = payload.messages.length - AI_MESSAGE_LIMIT
    payload.messages = payload.messages.slice(-AI_MESSAGE_LIMIT)
    serialized = JSON.stringify(payload)
  }
  return { serialized: byteLength(serialized) <= GENERATE_STATE_MAX_BYTES ? serialized : null, droppedMessages, compactedConvergence }
}

export function writeGenerateSession(key, value, { storage = globalThis.localStorage, notify = () => {} } = {}) {
  const bounded = serializeGenerateSession(value)
  if (!bounded.serialized) {
    notify("too-large", "生成中心本地会话超过 512 KiB 保存上限；当前页面内容仍在，请精简或复制重要内容。")
    return false
  }
  let evictions = 0
  while (true) {
    try {
      storage.setItem(key, bounded.serialized)
      break
    } catch (err) {
      const quota = err?.name === "QuotaExceededError" || err?.name === "NS_ERROR_DOM_QUOTA_REACHED" || err?.code === 22 || err?.code === 1014
      const oldest = quota ? storageEntries(storage, key)[0] : null
      if (!oldest) {
        notify("save-failed", "生成中心本地会话保存失败；当前页面内容仍在，请复制重要内容后重试。")
        return false
      }
      try { storage.removeItem(oldest.key) } catch {}
      if (storage.getItem(oldest.key) !== null) {
        notify("save-failed", "生成中心本地会话保存失败；当前页面内容仍在，请复制重要内容后重试。")
        return false
      }
      evictions += 1
    }
  }
  const entries = storageEntries(storage, key)
  while (entries.length + 1 > GENERATE_STATE_MAX_PROJECTS) {
    const oldest = entries.shift()
    try { storage.removeItem(oldest.key); evictions += 1 } catch { break }
  }
  if (bounded.droppedMessages) notify("compacted", "生成中心本地会话较大，已仅保留最近 40 条对话。")
  if (bounded.compactedConvergence) notify("compacted-convergence", "收束预览较大，已保留来源、选择和作者消息，并省略可重建的展开说明。")
  if (evictions) notify("evicted", "本地生成会话已达到容量边界，已清理最久未使用的项目缓存。")
  return true
}

function continuationKey(projectId) {
  return `${CREATIVE_CONTINUATION_STORAGE_PREFIX}${projectId}`
}

function continuationId(value, { optional = false } = {}) {
  if (value == null && optional) return null
  return typeof value === "string" && value.length > 0 && value.length <= 256 ? value : undefined
}

function normalizeContinuation(projectId, value) {
  if (!projectId || !value || typeof value !== "object" || Array.isArray(value)) return null
  if (value.schema_version !== 1 || value.project_id !== projectId || !CREATIVE_CONTINUATION_DESTINATIONS.has(value.destination)) return null
  if (!Number.isFinite(value.last_meaningful_at) || value.last_meaningful_at <= 0) return null
  const route = value.route
  if (!route || typeof route !== "object" || Array.isArray(route)) return null
  const base = {
    schema_version: 1,
    project_id: projectId,
    destination: value.destination,
    last_meaningful_at: value.last_meaningful_at,
  }
  if (value.destination === "generate") {
    const sourcePageId = continuationId(route.source_page_id, { optional: true })
    if (sourcePageId === undefined || !GENERATE_TARGETS.has(route.target)) return null
    const preset = route.preset === "world_core" ? "world_core" : null
    const checkpointId = continuationId(route.checkpoint_id, { optional: true })
    if (checkpointId === undefined || (checkpointId && preset !== "world_core")) return null
    return {
      ...base,
      route: {
        source_page_id: sourcePageId,
        target: route.target,
        ...(preset ? { preset } : {}),
        ...(checkpointId ? { checkpoint_id: checkpointId } : {}),
      },
    }
  }
  if (value.destination === "world_bible_draft") {
    const draftId = continuationId(route.draft_id)
    const pageId = continuationId(route.page_id, { optional: true })
    if (!draftId || pageId === undefined) return null
    return { ...base, route: { draft_id: draftId, page_id: pageId } }
  }
  const suggestionId = continuationId(route.suggestion_id)
  return suggestionId ? { ...base, route: { suggestion_id: suggestionId } } : null
}

export function readCreativeContinuation(projectId, {
  storage = globalThis.localStorage,
  notify = () => {},
} = {}) {
  if (!projectId) return null
  const key = continuationKey(projectId)
  let raw
  try { raw = storage?.getItem(key) } catch { return null }
  if (!raw) return null
  try {
    const value = normalizeContinuation(projectId, JSON.parse(raw))
    if (!value) throw new Error("invalid continuation")
    return value
  } catch {
    try { storage?.removeItem(key) } catch {}
    notify("invalid-continuation", "上次世界设定创作位置已失效，请从当前可用入口重新选择。")
    return null
  }
}

export function writeCreativeContinuation(projectId, value, {
  storage = globalThis.localStorage,
  now = Date.now,
} = {}) {
  const normalized = normalizeContinuation(projectId, {
    schema_version: 1,
    project_id: projectId,
    destination: value?.destination,
    route: value?.route,
    last_meaningful_at: now(),
  })
  if (!normalized) return false
  try {
    storage?.setItem(continuationKey(projectId), JSON.stringify(normalized))
    return true
  } catch {
    return false
  }
}

export function clearCreativeContinuation(projectId, { storage = globalThis.localStorage } = {}) {
  try {
    storage?.removeItem(continuationKey(projectId))
    return true
  } catch {
    return false
  }
}

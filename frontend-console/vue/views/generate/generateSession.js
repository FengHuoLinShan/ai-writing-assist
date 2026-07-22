import { AI_MESSAGE_LIMIT, AI_SELECTED_CHAPTER_LIMIT } from "./logic/generateLogic.js"

export const GENERATE_STATE_STORAGE_PREFIX = "generate_world_workspace_state_v2_"
export const GENERATE_STATE_MAX_PROJECTS = 5
export const GENERATE_STATE_MAX_BYTES = 512 * 1024
const composerDrafts = new Map()
const contextPreviews = new Map()

export function readGenerateComposerDraft(key) { return composerDrafts.get(key) || "" }
export function writeGenerateComposerDraft(key, value) {
  if (value) composerDrafts.set(key, value)
  else composerDrafts.delete(key)
}

export function readGenerateContextPreview(projectId) {
  return contextPreviews.get(projectId || "none") || {
    bundle: null,
    markdown: "",
    source: null,
    request: null,
  }
}

export function writeGenerateContextPreview(projectId, value = {}) {
  const key = projectId || "none"
  const preview = {
    bundle: value.bundle || null,
    markdown: value.markdown || "",
    source: value.source || null,
    request: value.request || null,
  }
  if (!preview.bundle && !preview.markdown && !preview.source && !preview.request) {
    contextPreviews.delete(key)
    return
  }
  contextPreviews.delete(key)
  contextPreviews.set(key, preview)
  while (contextPreviews.size > GENERATE_STATE_MAX_PROJECTS) {
    contextPreviews.delete(contextPreviews.keys().next().value)
  }
}

export function generateSessionKey(projectId, sourcePageId = null, targetKind = "core_entity") {
  return `${GENERATE_STATE_STORAGE_PREFIX}${projectId || "none"}_${sourcePageId || "project"}_${targetKind || "core_entity"}`
}

export function emptyGenerateSession() {
  return {
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
    newPageType: "custom",
    newPageTemplateKey: "",
    suggestionId: null,
  }
}

function persistedShape(value) {
  return {
    savedAt: Date.now(),
    selectedTemplateId: value.selectedTemplateId || "builtin:none",
    messages: (value.messages || []).filter((item) => !item.pending),
    selectedChapters: (value.selectedChapters || []).slice(0, AI_SELECTED_CHAPTER_LIMIT),
    qualityMode: value.qualityMode || "fast",
    includeWorldSynopsis: value.includeWorldSynopsis !== false,
    activationProfileId: value.activationProfileId || null,
    selectedSceneId: value.selectedSceneId || "",
    selectedThreadIds: value.selectedThreadIds || [],
    selectedCharacterIds: value.selectedCharacterIds || [],
    selectedEntityIds: value.selectedEntityIds || [],
    newPageType: value.newPageType || "custom",
    newPageTemplateKey: value.newPageTemplateKey || "",
    suggestionId: value.suggestionId || null,
  }
}

function isArrayShape(value) {
  return ["messages", "selectedChapters", "selectedThreadIds", "selectedCharacterIds", "selectedEntityIds"]
    .every((key) => !(key in value) || Array.isArray(value[key]))
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
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || !isArrayShape(parsed)) {
      throw new Error("invalid local state")
    }
    return { ...fallback, ...parsed, messages: parsed.messages || [], selectedChapters: (parsed.selectedChapters || []).slice(0, AI_SELECTED_CHAPTER_LIMIT) }
  } catch {
    try { storage?.removeItem(key) } catch {}
    notify("invalid-state", "生成中心本地会话已损坏，已忽略该缓存；当前数据库内容不受影响。")
    return fallback
  }
}

export function serializeGenerateSession(value) {
  const payload = persistedShape(value)
  let serialized = JSON.stringify(payload)
  let droppedMessages = 0
  if (byteLength(serialized) > GENERATE_STATE_MAX_BYTES && payload.messages.length > AI_MESSAGE_LIMIT) {
    droppedMessages = payload.messages.length - AI_MESSAGE_LIMIT
    payload.messages = payload.messages.slice(-AI_MESSAGE_LIMIT)
    serialized = JSON.stringify(payload)
  }
  return { serialized: byteLength(serialized) <= GENERATE_STATE_MAX_BYTES ? serialized : null, droppedMessages }
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
  if (evictions) notify("evicted", "本地生成会话已达到容量边界，已清理最久未使用的项目缓存。")
  return true
}

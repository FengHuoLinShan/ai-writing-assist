import { getRouter } from "../../bridge/index.js"

export const SCENE_RUNTIME_TABS = Object.freeze([
  { id: "management", label: "管理", description: "筛选、编辑和整理场景" },
  { id: "characters", label: "人物卡", description: "查看本场人物与当前状态" },
  { id: "simulation", label: "推演", description: "整理人物反应和剧情走向" },
  { id: "script", label: "剧本区", description: "保存本场剧本草稿并回到写作" },
])

const TAB_IDS = new Set(SCENE_RUNTIME_TABS.map((item) => item.id))
const sessions = new Map()
const STORAGE_PREFIX = "scene_runtime_draft:v1:"
const MAX_DRAFT_BYTES = 256 * 1024

function sessionKey(projectId, sceneId) {
  return `${String(projectId || "none")}:${String(sceneId || "none")}`
}

function storageKey(projectId, sceneId) {
  return `${STORAGE_PREFIX}${encodeURIComponent(String(projectId || "none"))}:${encodeURIComponent(String(sceneId || "none"))}`
}

function blankSession() {
  return {
    activeTab: "management",
    activeScriptFileId: null,
    selectedCharacterId: null,
    scriptDraft: "",
    scriptDrafts: {},
    simulation: null,
    scriptPreview: null,
    scriptDraftSource: null,
    updatedAt: null,
  }
}

function readStoredDraft(projectId, sceneId) {
  try {
    const raw = localStorage.getItem(storageKey(projectId, sceneId))
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== "object") return {}
    return {
      scriptDraft: typeof parsed.scriptDraft === "string" ? parsed.scriptDraft.slice(0, MAX_DRAFT_BYTES) : "",
      activeScriptFileId: typeof parsed.activeScriptFileId === "string" ? parsed.activeScriptFileId : null,
      scriptDrafts: parsed.scriptDrafts && typeof parsed.scriptDrafts === "object"
        ? Object.fromEntries(Object.entries(parsed.scriptDrafts).slice(0, 24).map(([key, value]) => [String(key), String(value || "").slice(0, MAX_DRAFT_BYTES)]))
        : {},
      simulation: asSerializableSimulation(parsed.simulation),
      scriptPreview: parsed.scriptPreview && typeof parsed.scriptPreview === "object"
        ? {
          content: typeof parsed.scriptPreview.content === "string" ? parsed.scriptPreview.content.slice(0, 200000) : "",
          plan: typeof parsed.scriptPreview.plan === "string" ? parsed.scriptPreview.plan.slice(0, 16000) : "",
          beats: Array.isArray(parsed.scriptPreview.beats) ? parsed.scriptPreview.beats.slice(0, 16).map((item) => ({
            id: String(item?.id || item?.beat_id || "").slice(0, 120),
            beat_id: String(item?.beat_id || item?.id || "").slice(0, 120),
            title: String(item?.title || item?.purpose || "Beat").slice(0, 160),
            purpose: String(item?.purpose || item?.title || "推进场景").slice(0, 160),
            detail: String(item?.detail || "").slice(0, 500),
            action: String(item?.action || "").slice(0, 500),
            consequence: String(item?.consequence || "").slice(0, 500),
            actors: Array.isArray(item?.actors) ? item.actors.slice(0, 24).map((value) => String(value).slice(0, 120)) : [],
            hard_anchor: Boolean(item?.hard_anchor || item?.hardAnchor),
          })) : [],
          warnings: Array.isArray(parsed.scriptPreview.warnings) ? parsed.scriptPreview.warnings.slice(0, 16).map((value) => String(value).slice(0, 500)) : [],
          sourceTaskId: typeof parsed.scriptPreview.sourceTaskId === "string" ? parsed.scriptPreview.sourceTaskId.slice(0, 120) : null,
          contextSnapshotId: typeof parsed.scriptPreview.contextSnapshotId === "string" ? parsed.scriptPreview.contextSnapshotId.slice(0, 160) : null,
        }
        : null,
      scriptDraftSource: parsed.scriptDraftSource && typeof parsed.scriptDraftSource === "object"
        ? {
          sourceTaskId: typeof parsed.scriptDraftSource.sourceTaskId === "string" ? parsed.scriptDraftSource.sourceTaskId.slice(0, 120) : null,
          contextSnapshotId: typeof parsed.scriptDraftSource.contextSnapshotId === "string" ? parsed.scriptDraftSource.contextSnapshotId.slice(0, 160) : null,
        }
        : null,
      selectedCharacterId: typeof parsed.selectedCharacterId === "string" ? parsed.selectedCharacterId : null,
      notes: parsed.notes && typeof parsed.notes === "object" ? Object.fromEntries(
        Object.entries(parsed.notes).slice(0, 24).map(([key, value]) => [String(key), String(value || "").slice(0, 4000)]),
      ) : {},
      updatedAt: parsed.updatedAt || null,
    }
  } catch {
    return {}
  }
}

function asSerializableScriptPreview(preview) {
  if (!preview || typeof preview !== "object") return null
  return {
    content: typeof preview.content === "string" ? preview.content.slice(0, 200000) : "",
    plan: typeof preview.plan === "string" ? preview.plan.slice(0, 16000) : "",
    beats: Array.isArray(preview.beats) ? preview.beats.slice(0, 16).map((item) => ({
      id: String(item?.id || item?.beat_id || "").slice(0, 120),
      beat_id: String(item?.beat_id || item?.id || "").slice(0, 120),
      title: String(item?.title || item?.purpose || "Beat").slice(0, 160),
      purpose: String(item?.purpose || item?.title || "推进场景").slice(0, 160),
      detail: String(item?.detail || "").slice(0, 500),
      action: String(item?.action || "").slice(0, 500),
      consequence: String(item?.consequence || "").slice(0, 500),
      actors: Array.isArray(item?.actors) ? item.actors.slice(0, 24).map((value) => String(value).slice(0, 120)) : [],
      hard_anchor: Boolean(item?.hard_anchor || item?.hardAnchor),
    })) : [],
    warnings: Array.isArray(preview.warnings) ? preview.warnings.slice(0, 16).map((value) => String(value).slice(0, 500)) : [],
    sourceTaskId: typeof preview.sourceTaskId === "string" ? preview.sourceTaskId.slice(0, 120) : null,
    contextSnapshotId: typeof preview.contextSnapshotId === "string" ? preview.contextSnapshotId.slice(0, 160) : null,
  }
}

function asSerializableScriptDraftSource(source) {
  if (!source || typeof source !== "object") return null
  return {
    sourceTaskId: typeof source.sourceTaskId === "string" ? source.sourceTaskId.slice(0, 120) : null,
    contextSnapshotId: typeof source.contextSnapshotId === "string" ? source.contextSnapshotId.slice(0, 160) : null,
  }
}

function asSerializableSimulation(simulation) {
  if (!simulation || typeof simulation !== "object") return null
  return {
    status: simulation.status || "draft",
    plan: typeof simulation.plan === "string" ? simulation.plan.slice(0, 16000) : "",
    scriptText: typeof simulation.scriptText === "string" ? simulation.scriptText.slice(0, 200000) : "",
    sourceTaskId: typeof simulation.sourceTaskId === "string" ? simulation.sourceTaskId.slice(0, 120) : null,
    contextSnapshotId: typeof simulation.contextSnapshotId === "string" ? simulation.contextSnapshotId.slice(0, 160) : null,
    reactions: Array.isArray(simulation.reactions)
      ? simulation.reactions.slice(0, 24).map((item) => ({
        id: String(item?.id || "").slice(0, 120),
        characterId: String(item?.characterId || "").slice(0, 120),
        name: String(item?.name || "人物").slice(0, 120),
        stance: String(item?.stance || "").slice(0, 240),
        trigger: String(item?.trigger || "").slice(0, 240),
        action: String(item?.action || "").slice(0, 240),
        knownInformation: Array.isArray(item?.knownInformation) ? item.knownInformation.slice(0, 40).map((value) => String(value).slice(0, 240)) : [],
        subjectiveJudgment: String(item?.subjectiveJudgment || "").slice(0, 240),
        goal: String(item?.goal || "").slice(0, 240),
        immediateReaction: String(item?.immediateReaction || "").slice(0, 240),
        actionChoices: Array.isArray(item?.actionChoices) ? item.actionChoices.slice(0, 12).map((value) => String(value).slice(0, 240)) : [],
        dialogueTendency: String(item?.dialogueTendency || "").slice(0, 240),
        conflict: String(item?.conflict || "").slice(0, 240),
        confidence: Number(item?.confidence || 0),
        knowledgeBasis: Array.isArray(item?.knowledgeBasis) ? item.knowledgeBasis.slice(0, 20).map((value) => String(value).slice(0, 240)) : [],
        alternatives: Array.isArray(item?.alternatives) ? item.alternatives.slice(0, 8).map((value) => String(value).slice(0, 240)) : [],
        status: ["candidate", "kept", "rejected"].includes(item?.status) ? item.status : "candidate",
      }))
      : [],
    beats: Array.isArray(simulation.beats)
      ? simulation.beats.slice(0, 16).map((item) => ({
        id: String(item?.id || "").slice(0, 120),
        beatId: String(item?.beatId || item?.id || "").slice(0, 120),
        title: String(item?.title || "Beat").slice(0, 160),
        detail: String(item?.detail || "").slice(0, 500),
        action: String(item?.action || "").slice(0, 500),
        consequence: String(item?.consequence || "").slice(0, 500),
        actors: Array.isArray(item?.actors) ? item.actors.slice(0, 24).map((value) => String(value).slice(0, 120)) : [],
        hardAnchor: Boolean(item?.hardAnchor),
      }))
      : [],
    generatedAt: simulation.generatedAt || null,
  }
}

function serializedDraftWithinLimit(next) {
  const serialized = JSON.stringify(next)
  if (serialized.length <= MAX_DRAFT_BYTES) return serialized

  const bounded = {
    ...next,
    scriptDrafts: {},
    simulation: next.simulation
      ? asSerializableSimulation({ ...next.simulation, reactions: [] })
      : null,
  }
  if (JSON.stringify(bounded).length > MAX_DRAFT_BYTES) {
    bounded.simulation = null
    bounded.scriptPreview = null
  }
  if (JSON.stringify(bounded).length > MAX_DRAFT_BYTES) bounded.notes = {}

  let output = JSON.stringify(bounded)
  if (output.length > MAX_DRAFT_BYTES) {
    const overflow = output.length - MAX_DRAFT_BYTES
    bounded.scriptDraft = bounded.scriptDraft.slice(0, Math.max(0, bounded.scriptDraft.length - overflow - 1))
    output = JSON.stringify(bounded)
  }

  for (const [key, value] of Object.entries(next.scriptDrafts).reverse()) {
    if (key === next.activeScriptFileId) continue
    bounded.scriptDrafts[key] = value
    const candidate = JSON.stringify(bounded)
    if (candidate.length > MAX_DRAFT_BYTES) delete bounded.scriptDrafts[key]
    else output = candidate
  }
  return output
}

export function sceneRuntimeSession(projectId, sceneId) {
  const key = sessionKey(projectId, sceneId)
  if (!sessions.has(key)) {
    sessions.set(key, { ...blankSession(), ...readStoredDraft(projectId, sceneId) })
  }
  return sessions.get(key)
}

export function resetSceneRuntimeSession(projectId, sceneId) {
  sessions.delete(sessionKey(projectId, sceneId))
}

export function sceneRuntimeDraftKey(projectId, sceneId) {
  return storageKey(projectId, sceneId)
}

export function persistSceneRuntimeDraft(projectId, sceneId, patch = {}) {
  const session = sceneRuntimeSession(projectId, sceneId)
  const next = {
    activeScriptFileId: typeof patch.activeScriptFileId === "string"
      ? patch.activeScriptFileId
      : session.activeScriptFileId || null,
    scriptDraft: typeof patch.scriptDraft === "string"
      ? patch.scriptDraft.slice(0, MAX_DRAFT_BYTES)
      : session.scriptDraft || "",
    scriptDrafts: patch.scriptDrafts && typeof patch.scriptDrafts === "object"
      ? Object.fromEntries(Object.entries(patch.scriptDrafts).slice(0, 24).map(([key, value]) => [String(key), String(value || "").slice(0, MAX_DRAFT_BYTES)]))
      : { ...(session.scriptDrafts || {}) },
    simulation: asSerializableSimulation(patch.simulation ?? session.simulation),
    scriptPreview: asSerializableScriptPreview(patch.scriptPreview ?? session.scriptPreview),
    scriptDraftSource: asSerializableScriptDraftSource(patch.scriptDraftSource ?? session.scriptDraftSource),
    selectedCharacterId: typeof patch.selectedCharacterId === "string"
      ? patch.selectedCharacterId
      : session.selectedCharacterId || null,
    notes: patch.notes && typeof patch.notes === "object"
      ? Object.fromEntries(Object.entries(patch.notes).slice(0, 24).map(([key, value]) => [String(key), String(value || "").slice(0, 4000)]))
      : { ...(session.notes || {}) },
    updatedAt: new Date().toISOString(),
  }
  Object.assign(session, next)
  try {
    localStorage.setItem(storageKey(projectId, sceneId), serializedDraftWithinLimit(next))
  } catch {
    // 草稿持久化失败不阻断当前编辑；内存 session 仍保留本轮内容。
  }
  return next
}

export function normalizeSceneRuntimeTab(value) {
  const candidate = String(value || "").trim()
  return TAB_IDS.has(candidate) ? candidate : "management"
}

export function runtimeTabFromQuery(query = null) {
  const source = query || getRouter()?.getCurrentQuery?.() || new URLSearchParams()
  return normalizeSceneRuntimeTab(source.get("tab") || source.get("scene_tab"))
}

function currentHashQuery(router = getRouter()) {
  const routeQuery = router?.getCurrentQuery?.()
  if (routeQuery) return new URLSearchParams(routeQuery.toString())
  if (typeof window === "undefined") return new URLSearchParams()
  const index = window.location.hash.indexOf("?")
  return new URLSearchParams(index >= 0 ? window.location.hash.slice(index + 1) : "")
}

export function commitSceneRuntimeTab(projectId, sceneId, tab, mode = "push", router = getRouter()) {
  const query = currentHashQuery(router)
  const normalized = normalizeSceneRuntimeTab(tab)
  if (sceneId) query.set("scene_id", String(sceneId))
  if (normalized === "management") query.delete("tab")
  else query.set("tab", normalized)
  query.delete("scene_tab")
  if (router?.commitCurrentQuery?.(query, mode) === true) return true
  if (typeof window === "undefined" || !window.history) return false
  const base = `#workbench/${encodeURIComponent(projectId)}/outline/scenes`
  const hash = query.toString() ? `${base}?${query.toString()}` : base
  window.history[mode === "push" ? "pushState" : "replaceState"](
    { view: "outline", subView: "scenes", projectId },
    "",
    hash,
  )
  return true
}

export function tabLabel(tab) {
  return SCENE_RUNTIME_TABS.find((item) => item.id === normalizeSceneRuntimeTab(tab))?.label || "管理"
}

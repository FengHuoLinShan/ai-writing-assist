import { structureAssetDisplay } from "../../../shared/assetDisplayState.js"
import { getApi, getAppState, getRouter } from "../../bridge/index.js"

export const HEALTH_ORDER = [
  ["unreviewed", "未复核"],
  ["unassigned", "未关联章节"],
  ["missing_setup", "缺设定"],
  ["needs_organize", "待整理"],
]

export const STATUS_OPTIONS = [
  ["draft", "工作稿"],
  ["candidate", "待处理"],
  ["canonical", "已采用"],
  ["deprecated", "历史"],
]

export const SOURCE_OPTIONS = [
  ["manual", "手动"],
  ["deep_import", "深度导入"],
  ["ai_generated", "AI 生成"],
  ["manual_fusion", "融合结果"],
]

export const BOUNDARY_STATUS_OPTIONS = [["uncertain", "边界不确定"]]
export const PHASE_OPTIONS = [
  ["phase1a_fallback", "Phase 1A fallback"],
  ["phase1b_fusion", "Phase 1B fusion"],
]
export const CONFIDENCE_BAND_OPTIONS = [
  ["low", "低于 0.5"],
  ["medium", "0.5-0.8"],
  ["high", "0.8 以上"],
]

export const TAG_OPTIONS = [
  ["draft", "未标注"],
  ["hook", "钩子"],
  ["inciting_incident", "激励事件"],
  ["rising_action", "冲突升级"],
  ["climax", "阶段高潮"],
  ["valley", "低谷"],
  ["transition", "过渡"],
  ["payoff", "爽点"],
]

export const SCENE_FILTER_DEFAULTS = Object.freeze({
  health: "",
  q: "",
  status: "",
  source: "",
  workflow_id: "",
  needs_review: "",
  boundary_status: "",
  phase: "",
  phase1a_fallback: false,
  chapter_from: "",
  chapter_to: "",
  confidence_band: "",
  segment: "",
  skip: 0,
  limit: 20,
})

const sessions = new Map()

export function sceneSession(projectId) {
  const key = String(projectId || "none")
  if (!sessions.has(key)) {
    sessions.set(key, {
      filters: { ...SCENE_FILTER_DEFAULTS },
      activeHealth: null,
      advancedFiltersOpen: false,
    })
  }
  return sessions.get(key)
}

export function resetSceneSession(projectId) {
  sessions.delete(String(projectId || "none"))
}

export function sceneQuery() {
  return new URLSearchParams(getRouter()?.getCurrentQuery?.()?.toString() || "")
}

export function sceneIdFromQuery(query = sceneQuery()) {
  return query.get("scene_id") || null
}

export function sceneModePreferenceKey(projectId) {
  return `novel_view_mode:${projectId || "none"}:scene-workbench`
}

export function initialSceneMode(projectId, query = sceneQuery()) {
  const requested = query.get("mode")
  if (requested === "normal" || requested === "hot") return requested
  try {
    const stored = localStorage.getItem(sceneModePreferenceKey(projectId))
    if (stored === "normal" || stored === "hot") return stored
  } catch {
    // localStorage 不可用时使用热点默认值。
  }
  return "hot"
}

export function rememberSceneMode(projectId, mode) {
  try {
    localStorage.setItem(sceneModePreferenceKey(projectId), mode)
  } catch {
    // 偏好写入失败不阻断工作台。
  }
}

export function hasManagementFilters(filters) {
  return [
    "health", "q", "status", "source", "workflow_id", "needs_review",
    "boundary_status", "phase", "chapter_from", "chapter_to", "confidence_band",
  ].some((key) => Boolean(filters?.[key])) || Boolean(filters?.phase1a_fallback)
}

export function sceneWorkbenchParams({ filters, viewMode, selectedSceneId = null }) {
  const params = {
    skip: Number(filters?.skip || 0),
    limit: Number(filters?.limit || 20),
    view_mode: viewMode,
  }
  for (const key of [
    "health", "q", "status", "source", "workflow_id", "needs_review",
    "boundary_status", "phase", "chapter_from", "chapter_to", "confidence_band",
  ]) {
    const value = filters?.[key]
    if (value === "true") params[key] = true
    else if (value === "false") params[key] = false
    else if (value) params[key] = value
  }
  if (filters?.phase1a_fallback) params.phase1a_fallback = true
  if (viewMode === "hot") {
    if (filters?.segment) params.segment = filters.segment
    const shouldAnchorLatest = !selectedSceneId
      && !filters?.segment
      && Number(filters?.skip || 0) === 0
      && !hasManagementFilters(filters)
    if (shouldAnchorLatest) params.anchor = "latest"
  }
  return params
}

function replaceSceneIdInHash(projectId, query) {
  if (typeof window === "undefined" || !window.history) return
  const base = `#workbench/${encodeURIComponent(projectId)}/outline/scenes`
  const hash = query.toString() ? `${base}?${query.toString()}` : base
  window.history.replaceState(
    { view: "outline", subView: "scenes", projectId },
    "",
    hash,
  )
}

export async function loadSceneWorkbenchProps(projectId) {
  const api = getApi()
  const query = sceneQuery()
  const selectedSceneId = sceneIdFromQuery(query)
  const session = sceneSession(projectId)
  if (selectedSceneId) {
    session.filters = { ...SCENE_FILTER_DEFAULTS }
    session.activeHealth = null
  }
  const viewMode = initialSceneMode(projectId, query)
  const params = sceneWorkbenchParams({
    filters: session.filters,
    viewMode,
    selectedSceneId,
  })
  let workbench
  try {
    workbench = await api.outline.getSceneWorkbench(projectId, selectedSceneId, params)
  } catch (err) {
    const state = getAppState()
    const canRecover = selectedSceneId
      && state?.currentView === "outline"
      && state?.currentSubView === "scenes"
      && err?.status === 404
      && err?.detail === "Scene not found"
    if (!canRecover) throw err
    query.delete("scene_id")
    replaceSceneIdInHash(projectId, query)
    workbench = await api.outline.getSceneWorkbench(
      projectId,
      null,
      sceneWorkbenchParams({ filters: session.filters, viewMode }),
    )
  }

  const effectiveSkip = Number(workbench?.skip)
  if (Number.isInteger(effectiveSkip) && effectiveSkip >= 0) {
    session.filters.skip = effectiveSkip
  }
  const pending = Number(workbench?.fusion_suggestions?.pending_count || 0)
  const fusionSuggestions = []
  if (pending > 0 && api.outline.listFusionSuggestions) {
    let skip = 0
    let total = pending
    while (skip < total) {
      const result = await api.outline.listFusionSuggestions(projectId, { skip, limit: 50 })
      const items = Array.isArray(result?.items) ? result.items : []
      fusionSuggestions.push(...items)
      total = Number(result?.total ?? total) || 0
      if (!items.length) break
      skip += items.length
    }
  }
  return {
    projectId,
    workbench,
    fusionSuggestions,
    viewMode,
    selectedSceneId: sceneIdFromQuery(query),
    sceneFilters: { ...session.filters },
    activeHealth: session.activeHealth,
    advancedFiltersOpen: session.advancedFiltersOpen,
    sceneLoadError: null,
  }
}

export function filteredSceneItems(workbench, filters) {
  const items = workbench?.items || []
  if (filters?.status) return items
  return items.filter((item) => !structureAssetDisplay(item.scene || {}).isHistory)
}

export function sceneReviewState(item) {
  const meta = item?.scene?.structure_meta || {}
  const health = item?.health || []
  const reviewedAt = meta.reviewed_at || null
  return {
    reviewed: Boolean(reviewedAt),
    reviewedAt,
    needsReview: Boolean(meta.needs_review) || health.includes("unreviewed"),
  }
}

export function healthReasons(item) {
  return item?.health_details?.needs_organize || []
}

export function sceneContextAction(item, healthKey = null) {
  const scene = item?.scene || {}
  const health = item?.health || []
  const reasons = healthReasons(item)
  const reviewState = sceneReviewState(item)
  const display = structureAssetDisplay(scene)
  const suggestion = reasons.find((reason) => reason.code === "pending_scene_fusion_suggestion")
  const sourceMapping = reasons.find((reason) => [
    "source_mapping_chapter_only", "source_mapping_unresolved",
  ].includes(reason.code))
  const structure = reasons.find((reason) => [
    "manual_organize", "duplicate_chapter", "overlapping_span", "chunk_chapter_mismatch",
  ].includes(reason.code))
  const reviewAction = {
    key: "review",
    action: "context-review-scene",
    label: display.displayState === "active" ? "标记已检查" : "采用",
  }
  if (healthKey === "unreviewed") return reviewAction
  if (healthKey === "needs_organize") {
    if (suggestion) return { key: "suggestion", action: "context-open-fusion-suggestion", label: "查看融合建议", suggestionId: suggestion.suggestion_id }
    if (sourceMapping) return { key: "source_mapping", action: "context-confirm-source-mapping", label: "确认章节定位", fingerprint: sourceMapping.fingerprint }
    if (structure) return { key: "organize", action: "context-organize-mapping", label: "整理映射" }
  }
  if (healthKey === "unassigned") return { key: "assign", action: "context-assign-chapters", label: "关联章节" }
  if (healthKey === "missing_setup") return { key: "missing_setup", action: "context-complete-setup", label: "补全设定" }
  if (!healthKey && (health.includes("unreviewed") || reviewState.needsReview || display.displayState !== "active")) return reviewAction
  if (!healthKey && (suggestion || sourceMapping || structure)) return sceneContextAction(item, "needs_organize")
  if (!healthKey && health.includes("unassigned")) return sceneContextAction(item, "unassigned")
  if (!healthKey && health.includes("missing_setup")) return sceneContextAction(item, "missing_setup")
  return { key: "edit", action: "edit-workbench-scene", label: "编辑" }
}

export function sceneStatusLabel(scene) {
  if (scene?.status !== "deprecated") return structureAssetDisplay(scene || {}).label
  const meta = scene?.structure_meta || {}
  if (meta.deprecated_reason !== "scene_replacement") return "历史"
  const previous = meta.previous_status === "canonical" ? "原已采用" : "原工作稿"
  return `${previous} · 重复提取替换`
}

export function sceneSourceLabel(sceneOrSource) {
  const scene = sceneOrSource && typeof sceneOrSource === "object" ? sceneOrSource : null
  const source = scene ? scene.source : sceneOrSource
  const meta = scene?.structure_meta || {}
  if (meta.semantic_origin === "mechanical_fusion") {
    const original = Object.fromEntries(SOURCE_OPTIONS)[source] || source || "手动"
    return `${original} · 机械融合`
  }
  if (meta.fusion_kind === "llm_scene_workbench") return "AI 融合"
  return Object.fromEntries(SOURCE_OPTIONS)[source] || source || "手动"
}

export function sceneChapterLabel(scene) {
  const chapterIds = scene?.chapter_ids || []
  if (!chapterIds.length) return "未关联章节"
  return chapterIds.map((id) => `第 ${String(id)} 章`).join(" / ")
}

export function spanSummaryLabel(summary) {
  const rangeLabel = String(summary?.range_label || "").trim()
  const mappingLabel = String(summary?.mapping_status_label || "").trim()
  if (rangeLabel && mappingLabel && !rangeLabel.includes(mappingLabel)) return `${rangeLabel} · ${mappingLabel}`
  if (rangeLabel) return rangeLabel
  const chapter = Number(summary?.chapter_index)
  return [Number.isInteger(chapter) && chapter > 0 ? `第 ${chapter} 章` : "", mappingLabel].filter(Boolean).join(" · ")
}

export function overlapCounterpartLabel(detail) {
  return String(detail?.counterpart_scene_label || detail?.counterpart_scene_title || "未命名 Scene").trim() || "未命名 Scene"
}

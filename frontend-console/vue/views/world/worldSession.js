/**
 * worldSession — world 视图的会话级 UI 状态（reactive 单例）。
 *
 * 对应 vanilla worldView 的模块单例字段。island 在 query-only 路由变化时会
 * 卸载重挂载（评审教训：会话状态必须放 reactive 模块，不能挂组件实例）。
 *
 * 进入协调（reconcileWorldEntry）：vanilla 只在完整 onEnter 时重置草稿/批量选择/
 * 筛选面板，query-only 的 render() 不重置（worldView.js:234-283 vs render L713-742）。
 * island 每次重挂载都跑 load()，因此用 _route 区分：
 * - 完整进入（离开过 world / 项目切换 / 子标签切换）→ 重置草稿与批量、重读筛选面板；
 * - query-only 重挂载（同子标签筛选/分页变化）→ 保留。
 */
import { reactive } from "vue"
import { WORLD_FILTER_PANEL_DEFAULTS } from "./logic/worldQuery.js"

export const worldSession = reactive({
  advancedFiltersOpen: false,
  filterPanelsOpen: { ...WORLD_FILTER_PANEL_DEFAULTS },
  autoExtractOpen: false,
  objectFilterDraft: null,

  // 审查工作区草稿与错误（vanilla _relationReviewDrafts 等）
  relationReviewDrafts: {},
  aliasReviewDrafts: {},
  relationReviewErrors: {},
  aliasReviewErrors: {},
  processingReviewIds: {},
  reviewReceipt: null,

  // 批量选择：scope -> Set<string>
  bulkSelections: {},

  // 正式关系和别名都以 URL 恢复搜索与分页。
  relationListFilters: { q: "", skip: 0, limit: 20 },
  aliasListFilters: { q: "", skip: 0, limit: 20 },

  // bible 会话（vanilla worldBibleView 模块单例：跨进入保留"上次页面"）。
  // activePageId 只存 id；匹配不到已加载页面时由组件回退到 pages[0]
  // （vanilla 保留陈旧对象引用，此处按 id 匹配更稳妥，见计划决策 9）。
  bible: {
    activePageId: null,
    activeDraftId: null,
    editorBaseline: null,
    editorBaselineKey: null,
  },

  _route: { active: false, projectId: null, subView: null },
})

export function filterPanelStorageKey(projectId) {
  return projectId ? `novel_world_filter_panels:${projectId}` : null
}

/** 对应 vanilla _loadFilterPanelState（worldView.js:4045-4060）。 */
export function loadFilterPanelState(projectId) {
  worldSession.filterPanelsOpen = { ...WORLD_FILTER_PANEL_DEFAULTS }
  const storageKey = filterPanelStorageKey(projectId)
  if (!storageKey) return
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "null")
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return
    for (const key of Object.keys(WORLD_FILTER_PANEL_DEFAULTS)) {
      if (typeof saved[key] === "boolean") worldSession.filterPanelsOpen[key] = saved[key]
    }
  } catch {
    try { localStorage.removeItem(storageKey) } catch {}
  }
}

/** 对应 vanilla _saveFilterPanelState（worldView.js:4062-4075）。 */
export function saveFilterPanelState(projectId) {
  const storageKey = filterPanelStorageKey(projectId)
  if (!storageKey) return
  try {
    const stateToSave = Object.fromEntries(
      Object.keys(WORLD_FILTER_PANEL_DEFAULTS).map((key) => [
        key,
        worldSession.filterPanelsOpen?.[key] === true,
      ]),
    )
    localStorage.setItem(storageKey, JSON.stringify(stateToSave))
  } catch {
    // localStorage 不可用时保留当前会话内状态。
  }
}

/** island onLeave 时调用：标记已离开 world，下次进入按完整进入重置。 */
export function markWorldLeft() {
  worldSession._route.active = false
}

/**
 * island load() 开头调用。返回是否完整进入（完整进入已执行重置）。
 */
export function reconcileWorldEntry(projectId, subView) {
  const route = worldSession._route
  const normalizedProjectId = projectId || null
  const projectChanged = route.projectId !== normalizedProjectId
  const fullEnter = !route.active
    || projectChanged
    || route.subView !== subView
  if (fullEnter) {
    worldSession.relationReviewDrafts = {}
    worldSession.aliasReviewDrafts = {}
    worldSession.relationReviewErrors = {}
    worldSession.aliasReviewErrors = {}
    worldSession.processingReviewIds = {}
    worldSession.reviewReceipt = null
    worldSession.bulkSelections = {}
    worldSession.objectFilterDraft = null
    loadFilterPanelState(normalizedProjectId)
  }
  // Bible 的“上次页面”只能在同一项目内保留。跨项目复用旧 id /
  // baseline 会把旧项目的编辑会话短暂带入新项目。
  if (projectChanged) {
    worldSession.bible = {
      activePageId: null,
      activeDraftId: null,
      editorBaseline: null,
      editorBaselineKey: null,
    }
  }
  worldSession._route = { active: true, projectId: normalizedProjectId, subView }
  return fullEnter
}

/** 测试辅助：整体复位（对应 vanilla 测试的字段逐个重置）。 */
export function resetWorldSession() {
  worldSession.advancedFiltersOpen = false
  worldSession.filterPanelsOpen = { ...WORLD_FILTER_PANEL_DEFAULTS }
  worldSession.autoExtractOpen = false
  worldSession.objectFilterDraft = null
  worldSession.relationReviewDrafts = {}
  worldSession.aliasReviewDrafts = {}
  worldSession.relationReviewErrors = {}
  worldSession.aliasReviewErrors = {}
  worldSession.processingReviewIds = {}
  worldSession.reviewReceipt = null
  worldSession.bulkSelections = {}
  worldSession.relationListFilters = { q: "", skip: 0, limit: 20 }
  worldSession.aliasListFilters = { q: "", skip: 0, limit: 20 }
  worldSession.bible = {
    activePageId: null,
    activeDraftId: null,
    editorBaseline: null,
    editorBaselineKey: null,
  }
  worldSession._route = { active: false, projectId: null, subView: null }
}

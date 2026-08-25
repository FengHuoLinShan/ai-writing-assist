/**
 * outlineStructure — outline 视图的结构资产筛选/分页与数据预取（纯函数 + load）。
 *
 * 筛选变更一律写 URL query，由 island router.navigate 触发重挂载，
 * loadStructureProps 解码 query → filters → API 参数。
 */

import { getApi } from "../../../bridge/index.js"

// ============================================================
// 结构资产常量
// ============================================================

export const SCENE_ALLOWED_TAGS = new Set(["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"])
export const ENTITY_ALLOWED_STATUSES = new Set(["canonical", "draft", "candidate", "deprecated"])
export const FORESHADOWING_STATUSES = ["draft", "planted", "triggered", "resolved", "abandoned"]
export const REVEAL_STATUSES = ["draft", "planned", "revealed", "resolved", "abandoned"]

export const FORESHADOWING_STATUS_LABELS = { draft: "工作稿", planted: "已埋下", triggered: "已触发", resolved: "已兑现", abandoned: "历史" }
export const REVEAL_STATUS_LABELS = { draft: "工作稿", planned: "计划中", revealed: "已揭示", resolved: "已解决", abandoned: "历史" }
export const P20_TARGET_LABELS = {
  plot_thread: "剧情线",
  outline_arc: "篇章",
  planned_scene: "细纲",
}
export const P20_TARGET_BY_SUBVIEW = {
  threads: "plot_thread",
  arcs: "outline_arc",
  scenes: "planned_scene",
}

export const STRUCTURE_FILTER_DEFAULTS = { status: "", source: "", workflow_id: "", needs_review: "", skip: 0, limit: 50 }
export const STRUCTURE_SOURCE_OPTIONS = [
  ["deep_import", "深度导入"],
  ["manual", "手动"],
  ["ai_generated", "AI 生成"],
]

export const STRUCTURE_QUERY_KEYS = ["status", "source", "workflow_id", "needs_review"]

// ============================================================
// filter↔URL codec（纯函数，参照 worldQuery.js）
// ============================================================

/**
 * 从 URL query 解码结构筛选（对应 vanilla _structureFilterFor + URL 读取）。
 * 筛选状态存模块级内存，但初始化时从 query 读取；URL 是事实源。
 * 返回一个包含 STRUCTURE_FILTER_DEFAULTS 合并 query 结果的对象。
 */
export function structureFiltersFromQuery(subView, query) {
  const filters = { ...STRUCTURE_FILTER_DEFAULTS }
  if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return filters
  for (const key of STRUCTURE_QUERY_KEYS) {
    const val = query.get(key)
    if (val !== null) filters[key] = val
  }
  const page = Math.max(1, Number.parseInt(query.get("page") || "1", 10) || 1)
  filters.skip = (page - 1) * filters.limit
  return filters
}

/**
 * 把筛选状态编码为 URL query（对应 vanilla _structureFilterParams 的逆操作 + page）。
 * 空值不写入；URL.search 设为空时不写无用 key。
 */
export function structureQueryFromState(subView, filters) {
  const query = new URLSearchParams()
  if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return query
  for (const key of STRUCTURE_QUERY_KEYS) {
    const val = (filters[key] ?? "").toString().trim()
    if (val) query.set(key, val)
  }
  const page = Math.floor((filters.skip || 0) / filters.limit) + 1
  if (page > 1) query.set("page", String(page))
  return query
}

/**
 * 构造 API 筛选参数字典（对应 vanilla _structureFilterParams L833-848）。
 * 返回 plain object 作为 fetch options。
 */
export function structureFilterParams(subView, filters) {
  if (!["threads", "arcs", "foreshadowing", "reveals"].includes(subView)) return {}
  const params = { skip: filters.skip, limit: filters.limit }
  if (filters.status) params.status = filters.status
  if (filters.source) params.source = filters.source
  if (filters.workflow_id) params.workflow_id = filters.workflow_id
  if (filters.needs_review === "true") params.needs_review = true
  if (filters.needs_review === "false") params.needs_review = false
  return params
}

// ============================================================
// 全量加载辅助（对应 vanilla _loadAllOutlineItems L850-873）
// ============================================================

/**
 * 循环翻页拉取所有匹配项（用于 unassigned 等不分页展示场景）。
 */
export async function loadAllOutlineItems(fetchPage, baseParams = {}) {
  const items = []
  const pageSize = 50
  let skip = 0
  let total = Number.POSITIVE_INFINITY
  while (skip < total) {
    const result = await fetchPage({ ...baseParams, skip, limit: pageSize })
    const pageItems = Array.isArray(result?.items)
      ? result.items
      : (Array.isArray(result) ? result : [])
    items.push(...pageItems)
    const serverTotal = Number(result?.total)
    total = Number.isFinite(serverTotal) && serverTotal >= 0
      ? serverTotal
      : items.length
    if (!pageItems.length) break
    skip += pageItems.length
    if (!Number.isFinite(serverTotal) && pageItems.length < pageSize) break
  }
  return {
    items,
    total: Number.isFinite(total) ? total : items.length,
  }
}

// ============================================================
// 状态选项（对应 vanilla _structureStatusOptions L875-888）
// ============================================================

export function structureStatusOptions(subView) {
  if (subView === "foreshadowing") {
    return FORESHADOWING_STATUSES.map((status) => [status, FORESHADOWING_STATUS_LABELS[status] || status])
  }
  if (subView === "reveals") {
    return REVEAL_STATUSES.map((status) => [status, REVEAL_STATUS_LABELS[status] || status])
  }
  return [
    ["canonical", "已采用"],
    ["draft", "工作稿"],
    ["candidate", "待处理"],
    ["deprecated", "历史"],
  ]
}

// ============================================================
// loadStructureProps — island 预取用（对应 vanilla onEnter L162-262）
// ============================================================

/**
 * 为给定 subView 预取结构数据，返回平坦 props（岛挂载时传入）。
 *
 * @param {Object} options
 * @param {string} options.projectId
 * @param {string} options.subView — "threads" | "arcs" | "foreshadowing" | "reveals"
 * @param {Object} options.filters — 当前筛选（来自 structureFiltersFromQuery）
 * @param {number} [options.loadRequestId=0] — 请求 ID，用于竞态守卫（island 内用）
 * @returns {Promise<Object>} 平坦 props 对象
 *
 * 返回的 key 清单（island 集成用）：
 * - threads: Array — 剧情线列表
 * - arcs: Array — 篇章列表
 * - foreshadowing: Array — 伏笔列表
 * - reveals: Array — 揭示列表
 * - unassignedForeshadowing: Array — 未归入剧情线的伏笔
 * - unassignedReveals: Array — 未归入剧情线的揭示
 * - structureTotals: { threads: number, arcs: number, foreshadowing: number, reveals: number }
 * - structureLoadErrors: { [subView]: string | null }
 */
export async function loadStructureProps({ projectId, subView, filters }) {
  const api = getApi()
  const props = {
    threads: [],
    arcs: [],
    foreshadowing: [],
    reveals: [],
    unassignedForeshadowing: [],
    unassignedReveals: [],
    structureTotals: { threads: 0, arcs: 0, foreshadowing: 0, reveals: 0 },
    structureLoadErrors: {},
  }

  if (!projectId || !api?.outline) return props

  const fetchThreads = subView === "threads"
  const fetchArcs = subView === "arcs"
  const fetchForeshadowing = subView === "threads"
  const fetchReveals = subView === "threads"
  const params = structureFilterParams(subView, filters)
  const setError = (sv, err) => {
    const labels = { threads: "剧情线", arcs: "篇章", foreshadowing: "伏笔", reveals: "揭示" }
    props.structureLoadErrors[sv] = (err?.message || "").trim() || `${labels[sv] || "结构数据"}加载失败`
  }

  const promises = []
  if (fetchThreads) {
    promises.push(
      api.outline.listThreads(projectId, params)
        .then((data) => {
          const items = data.items || data || []
          props.threads = items
          props.structureTotals.threads = Number(data.total ?? props.threads.length) || 0
        })
        .catch((err) => {
          props.threads = []
          props.structureTotals.threads = 0
          setError("threads", err)
        }),
    )
  }
  if (fetchArcs) {
    promises.push(
      api.outline.listArcs(projectId, params)
        .then((data) => {
          const items = data.items || data || []
          props.arcs = items
          props.structureTotals.arcs = Number(data.total ?? props.arcs.length) || 0
        })
        .catch((err) => {
          props.arcs = []
          props.structureTotals.arcs = 0
          setError("arcs", err)
        }),
    )
  }
  if (fetchForeshadowing) {
    promises.push(
      Promise.all([
        loadAllOutlineItems((p) => api.outline.listForeshadowing(projectId, p)),
        loadAllOutlineItems((p) => api.outline.listForeshadowing(projectId, p), { unassigned: true }),
      ])
        .then(([data, unassigned]) => {
          const items = data.items || data || []
          props.foreshadowing = items
          props.unassignedForeshadowing = unassigned.items || unassigned || []
          props.structureTotals.foreshadowing = Number(data.total ?? props.foreshadowing.length) || 0
        })
        .catch((err) => {
          props.foreshadowing = []
          props.structureTotals.foreshadowing = 0
          setError("foreshadowing", err)
        }),
    )
  }
  if (fetchReveals) {
    promises.push(
      Promise.all([
        loadAllOutlineItems((p) => api.outline.listReveals(projectId, p)),
        loadAllOutlineItems((p) => api.outline.listReveals(projectId, p), { unassigned: true }),
      ])
        .then(([data, unassigned]) => {
          const items = data.items || data || []
          props.reveals = items
          props.unassignedReveals = unassigned.items || unassigned || []
          props.structureTotals.reveals = Number(data.total ?? props.reveals.length) || 0
        })
        .catch((err) => {
          props.reveals = []
          props.structureTotals.reveals = 0
          setError("reveals", err)
        }),
    )
  }

  if (promises.length > 0) {
    await Promise.all(promises)
  }
  return props
}

/**
 * rag 检索会话状态 — 对应 vanilla ragView 单例的检索字段。
 *
 * 为什么需要它：vanilla 用 renderer 单例字段在整视图重渲染间保留结果；
 * Vue island 在 router 每次 render（含 query-only 变化、子标签切换）后都会
 * 卸载重挂，组件内状态会丢失。会话模块替代单例：路由往返/重挂载期间保留，
 * 同项目子标签往返时保留，项目变化时重置；新 URL 状态优先覆盖旧草稿。
 * URL query 仍是已执行检索条件的权威来源。
 */
import { reactive } from "vue"

export const ragSearchSession = reactive({
  ownerProjectId: null,
  hits: [],
  visibleCount: 0,
  total: 0,
  resultMeta: null,
  query: "",
  lastSearchPayload: null,
  lastExecutedRouteSignature: "",
  formState: null,
  formRouteSignature: "",
  drawerRefs: [],
  // 索引维护：重建/重试进度（跨重挂载保留，与 vanilla 单例一致）
  rebuildProgress: null,
  rebuildInfo: null,
  taskRetryPending: false,
  // 预热状态（vanilla 单例字段，onEnter 不重置）
  prewarmState: "idle",
  prewarmWarning: "",
  // 预热结果回写（prewarmManager 写入；RagView 应用到 statusFields）
  prewarmResult: null,
})

/**
 * RAG 模块状态只允许在同一项目内跨 island 重挂载保留。
 * 项目变化时清理工作流与预热投影，避免旧项目元数据进入新工作区。
 */
export function scopeRagSessionToProject(projectId) {
  const nextProjectId = projectId || null
  if (ragSearchSession.ownerProjectId === nextProjectId) return false
  ragSearchSession.ownerProjectId = nextProjectId
  resetRagSearchSession()
  ragSearchSession.rebuildProgress = null
  ragSearchSession.rebuildInfo = null
  ragSearchSession.taskRetryPending = false
  ragSearchSession.prewarmState = "idle"
  ragSearchSession.prewarmWarning = ""
  ragSearchSession.prewarmResult = null
  return true
}

export function resetRagSearchSession() {
  ragSearchSession.hits = []
  ragSearchSession.visibleCount = 0
  ragSearchSession.total = 0
  ragSearchSession.resultMeta = null
  ragSearchSession.query = ""
  ragSearchSession.lastSearchPayload = null
  ragSearchSession.lastExecutedRouteSignature = ""
  ragSearchSession.formState = null
  ragSearchSession.formRouteSignature = ""
  ragSearchSession.drawerRefs = []
  ragSearchSession.taskRetryPending = false
}

/**
 * rag 检索会话状态 — 对应 vanilla ragView 单例的检索字段。
 *
 * 为什么需要它：vanilla 用 renderer 单例字段在整视图重渲染间保留结果；
 * Vue island 在 router 每次 render（含 query-only 变化、子标签切换）后都会
 * 卸载重挂，组件内状态会丢失。会话模块替代单例：路由往返/重挂载期间保留，
 * island load()（对应 vanilla onEnter）调用 resetRagSearchSession() 重置
 * （对应 vanilla _resetSearchState），URL query 仍是检索条件权威来源。
 */
import { reactive } from "vue"

export const ragSearchSession = reactive({
  hits: [],
  visibleCount: 0,
  total: 0,
  resultMeta: null,
  query: "",
  lastSearchPayload: null,
  lastExecutedRouteSignature: "",
  drawerRefs: [],
  // 索引维护：重建/重试进度（跨重挂载保留，与 vanilla 单例一致）
  rebuildProgress: null,
  rebuildInfo: null,
  taskRetryPending: false,
  // 预热状态（vanilla 单例字段，onEnter 不重置）
  prewarmState: "idle",
  prewarmWarning: "",
})

export function resetRagSearchSession() {
  ragSearchSession.hits = []
  ragSearchSession.visibleCount = 0
  ragSearchSession.total = 0
  ragSearchSession.resultMeta = null
  ragSearchSession.query = ""
  ragSearchSession.lastSearchPayload = null
  ragSearchSession.lastExecutedRouteSignature = ""
  ragSearchSession.drawerRefs = []
  ragSearchSession.taskRetryPending = false
}

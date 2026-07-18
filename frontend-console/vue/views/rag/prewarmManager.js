/**
 * 按项目一次性预热 — 模块级管理，不受 island 重挂载影响（P2 评审修复）。
 *
 * 背景：island 在 query-only 路由变化（每次 RAG 搜索提交）时也会卸载重挂，
 * 若预热请求挂在组件生命周期内，会被反复 abort/重启，长期无法完成。
 * 这里把预热移出组件生命周期，并按项目键控：
 * - 同项目 in-flight 或已 ready 的请求不重复发起（对应 vanilla 仅在
 *   totalChunks>0 且 worker 未就绪时触发的语义）；
 * - 项目切换时 abort 旧项目的在途请求（对应 vanilla onEnter 的 abort）；
 * - 结果回写 ragSearchSession.prewarmResult（dim/runtime/cache_stats），
 *   对应 vanilla _prewarm 的字段回写；HTTP 成功即回写（含非 ready 状态）。
 */
import { getApi, getAppState } from "../../bridge/index.js"
import { ragSearchSession } from "./ragSearchSession.js"

const manager = {
  projectId: null,
  controller: null,
  generation: 0,
  ready: false,
}

/**
 * 确保当前项目已完成一次预热。
 * @param {{force?: boolean}} options force=true 用于手动"预热检索引擎"按钮
 * @returns {Promise<object|null>} 重复发起被去重时返回 null
 */
export async function ensurePrewarm({ force = false } = {}) {
  const projectId = getAppState()?.currentProjectId
  if (!projectId) return null

  const sameProject = manager.projectId === projectId
  if (sameProject && !force && (manager.controller || manager.ready)) return null

  if (manager.controller && (!sameProject || force)) manager.controller.abort()

  const controller = new AbortController()
  const generation = ++manager.generation
  manager.projectId = projectId
  manager.controller = controller
  manager.ready = false

  const isCurrent = () => manager.controller === controller && manager.generation === generation

  ragSearchSession.prewarmState = "running"
  ragSearchSession.prewarmWarning = ""

  try {
    const result = await getApi().rag.prewarm({ signal: controller.signal })
    if (!isCurrent()) return null
    ragSearchSession.prewarmState = result.status === "ready" ? "ready" : "failed"
    ragSearchSession.prewarmWarning = result.warning || ""
    // 对应 vanilla _prewarm 的字段回写（HTTP 成功即回写，无论 ready 与否）
    ragSearchSession.prewarmResult = {
      embedding_dim: result.embedding_dim ?? null,
      embedding_runtime: {
        started: true,
        healthy: result.status === "ready",
        cache_stats: result.cache_stats || {},
      },
    }
    manager.ready = result.status === "ready"
    return result
  } catch (err) {
    if (!isCurrent() || err?.name === "AbortError") return null
    ragSearchSession.prewarmState = "failed"
    ragSearchSession.prewarmWarning = err.message || "预热失败"
    return null
  } finally {
    if (manager.controller === controller) manager.controller = null
  }
}

/**
 * guidedFlowController — 引导流程（ADR-0032 流程 2 v1）写作页宿主控制器。
 *
 * 只编排展示与推进：资料确认复用 shared/aiReferenceModal 既有弹窗，
 * 候选打开与采用交给写作页既有能力；生成/审查在途时轮询推进自动步骤，
 * 有停点或终态时不自动推进。开关关闭或无活动流程时宿主保持隐藏。
 */

import { reactive } from "vue"

import { confirmAsync } from "../../../../shared/confirmAsync.js"
import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"

const POLL_INTERVAL_MS = 4000
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"])

export function createGuidedFlowController({
  api,
  toast,
  getProjectId,
  getSceneId = () => null,
  onOpenCandidate = () => {},
  // 默认走外壳 modal 二次确认；结束流程不落原生 confirm（与全站确认体验一致）。
  confirmDialog = (message, confirmText) => confirmAsync(message, confirmText),
}) {
  let pollTimer = null
  let disposed = false
  let polling = false
  // 必须是响应式对象：宿主组件的 computed 依赖 state.view，异步 applyView
  // 赋值后要触发重渲染（普通对象会让流程宿主永远不出现）。
  const state = reactive({
    view: null,
    visible: false,
    busy: false,
    error: null,
  })

  function stopPoll() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  function applyView(view) {
    if (!view?.run_id) return null
    state.view = view
    state.visible = true
    state.error = null
    if (TERMINAL_STATUSES.has(view.status)) stopPoll()
    else schedulePoll()
    return view
  }

  function schedulePoll() {
    if (pollTimer || disposed || !state.view) return
    pollTimer = setTimeout(async () => {
      pollTimer = null
      if (disposed || !state.view) return
      if (polling) {
        schedulePoll()
        return
      }
      polling = true
      try {
        // 无停点 = 自动步骤可能就绪（生成/审查完成），推进一次并刷新；
        // 有停点时不自动推进，只刷新（作者可能在候选面板采用，流程随之完成）。
        if (!state.view.stop) await advance({})
        if (state.view && !TERMINAL_STATUSES.has(state.view.status)) {
          const fresh = await api.assistant.guidedFlow(getProjectId(), state.view.run_id)
          applyView(fresh)
        }
      } catch {
        // 单次刷新失败不结束流程，下一轮重试。
      } finally {
        polling = false
      }
      schedulePoll()
    }, POLL_INTERVAL_MS)
  }

  async function refresh() {
    if (!state.view || disposed) return null
    try {
      return applyView(await api.assistant.guidedFlow(getProjectId(), state.view.run_id))
    } catch {
      return null
    }
  }

  async function advance(input = {}) {
    if (!state.view || state.busy) return null
    state.busy = true
    try {
      const view = await api.assistant.guidedFlowAdvance(state.view.run_id, {
        novel_id: getProjectId(),
        ...input,
      })
      return applyView(view)
    } catch (error) {
      state.error = error?.message || "流程推进失败，请稍后重试"
      toast(state.error, "error")
      return null
    } finally {
      state.busy = false
    }
  }

  async function attachRun(runId) {
    try {
      return applyView(await api.assistant.guidedFlow(getProjectId(), runId))
    } catch (error) {
      state.visible = false
      toast(error?.message || "流程入口已失效", "warning")
      return null
    }
  }

  async function probeActive() {
    // 刷新或换设备回到同一停点：只查活动流程；未开启或无流程时静默隐藏。
    if (state.view || disposed) return null
    try {
      const active = await api.assistant.guidedFlowActive(getProjectId())
      return active?.run_id ? applyView(active) : null
    } catch {
      return null
    }
  }

  async function confirmReference() {
    const view = state.view
    if (!view || view.stop?.step_id !== "confirm_reference" || state.busy) return null
    try {
      const confirmation = await confirmAiReference({
        novel_id: getProjectId(),
        action: "writing.generate",
        task: "继续写下一场：按本章资料生成正文候选",
        scope: "chapter",
        chapter_index: view.chapter_index,
        scene_id: getSceneId() || undefined,
        include_pending_objects: false,
      })
      if (!confirmation?.id) return null
      return await advance({ context_confirmation_id: confirmation.id })
    } catch (error) {
      if (!String(error?.message || "").includes("取消")) {
        toast(error?.message || "资料确认未完成", "warning")
      }
      return null
    }
  }

  async function saveSettings(semanticReview) {
    if (!state.view || state.busy) return null
    state.busy = true
    try {
      const view = await api.assistant.guidedFlowSettings(state.view.run_id, {
        novel_id: getProjectId(),
        semantic_review: Boolean(semanticReview),
      })
      return applyView(view)
    } catch (error) {
      toast(error?.message || "流程设置暂时无法保存", "warning")
      return refresh()
    } finally {
      state.busy = false
    }
  }

  async function abandonFlow() {
    if (!state.view || state.busy) return null
    const confirmed = await confirmDialog(
      "结束本续写流程？已生成的候选会保留在候选列表中，不会丢失。",
      "结束流程",
    )
    if (!confirmed) return null
    try {
      const result = await api.assistant.guidedFlowAbandon(getProjectId(), state.view.run_id)
      stopPoll()
      state.view = { ...state.view, ...result, status: "cancelled" }
      state.visible = true
      return state.view
    } catch (error) {
      toast(error?.message || "流程结束失败，请稍后重试", "error")
      return null
    }
  }

  function openCandidate() {
    const candidate = state.view?.candidate
    if (!candidate?.draft_id) return
    onOpenCandidate(candidate)
  }

  function dismiss() {
    stopPoll()
    state.visible = false
    state.view = null
  }

  function reset() {
    stopPoll()
    polling = false
    state.visible = false
    state.view = null
    state.busy = false
    state.error = null
  }

  function dispose() {
    disposed = true
    stopPoll()
  }

  return {
    state,
    attachRun,
    probeActive,
    refresh,
    advance,
    confirmReference,
    saveSettings,
    abandonFlow,
    openCandidate,
    dismiss,
    reset,
    dispose,
  }
}

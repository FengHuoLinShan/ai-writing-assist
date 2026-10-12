/**
 * guidedFlowController — 引导流程（ADR-0032）写作页宿主控制器。
 *
 * 只编排展示与推进：资料确认复用 shared/aiReferenceModal 既有弹窗，
 * 候选打开与采用交给写作页既有能力；生成/审查在途时轮询推进自动步骤，
 * 有停点或终态时不自动推进。开关关闭或无活动流程时宿主保持隐藏。
 *
 * state 必须是 reactive：普通对象会让宿主组件的 computed 不响应异步
 * applyView 赋值，流程宿主在真实运行中永不渲染。
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
  confirmDialog = (message, confirmText) => confirmAsync(message, confirmText),
}) {
  let pollTimer = null
  let disposed = false
  let polling = false
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

  /** 作者选择停点的推进：choice 由服务端按当前停点校验。 */
  async function choose(stepId, payload = {}) {
    return advance({ choice: { step_id: stepId, ...payload } })
  }

  /** 开始一个流程（服务端注册表限定 flow_id）；开始本身不产生任务或费用。 */
  async function startFlow(flowId, { chapterIndex = null, input = null, settings = null } = {}) {
    if (state.busy) return null
    state.busy = true
    try {
      const view = await api.assistant.guidedFlowStart({
        novel_id: getProjectId(),
        flow_id: flowId,
        ...(chapterIndex ? { chapter_index: chapterIndex } : {}),
        ...(input ? { input } : {}),
        ...(settings ? { settings } : {}),
      })
      return applyView(view)
    } catch (error) {
      state.error = error?.message || "流程暂时无法开始"
      toast(state.error, "warning")
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
    if (!view || (view.stop?.step_id !== "confirm_reference" && !view.stop?.step_id?.startsWith("confirm_rolling_")) || state.busy) return null
    try {
      const rolling = view.stop?.step_id?.startsWith("confirm_rolling_")
      const window = view.panel?.rolling?.window || {}
      const confirmation = await confirmAiReference({
        novel_id: getProjectId(),
        action: rolling ? "outline.generate" : "writing.generate",
        budget_tokens: rolling ? 0 : undefined,
        planning_window_end: rolling ? Math.min(window.end, view.stop.step_id.endsWith("scenes") ? window.start + 1 : window.end) : undefined,
        task: rolling ? "滚动规划：核对本层完整结构资料" : "继续写下一场：按本章资料生成正文候选",
        scope: rolling ? "full" : "chapter",
        chapter_index: rolling ? window.start : view.chapter_index,
        scene_id: rolling ? undefined : getSceneId() || undefined,
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

  async function saveSettings(semanticReview, planningWindow = null) {
    if (!state.view || state.busy) return null
    state.busy = true
    try {
      const view = await api.assistant.guidedFlowSettings(state.view.run_id, {
        novel_id: getProjectId(),
        semantic_review: Boolean(semanticReview),
        ...(planningWindow ? { planning_window: planningWindow } : {}),
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
      "结束本流程？已生成的候选与已确认资料都会保留，不会丢失。",
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
    choose,
    startFlow,
    confirmReference,
    saveSettings,
    abandonFlow,
    openCandidate,
    dismiss,
    reset,
    dispose,
  }
}

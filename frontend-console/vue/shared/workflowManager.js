import { reactive } from "vue"
import { getApi, getAppState } from "../bridge/index.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../shared/workflowProgress.js"

export function createWorkflowManager({
  workflowType,
  label,
  view,
  destinationLabel,
  matchRecovered,
  onTerminal,
  onUpdate,
  pollNovelId = null,
  clearOnDone = true,
  clearOnFailed = true,
  clearTaskOnFailed = clearOnFailed,
  matchesActiveScope = null,
  onScopeReset = null,
  restartActiveOnRecover = false,
  skipRecover = null,
  prepare: exposePrepare = false,
  transformRecoveredMeta = (meta) => meta || null,
  requireActiveProjectOnAdopt = true,
  claimProjectOnRecover = false,
  initialState = {},
  onRecovered = null,
}) {
  const state = reactive({
    taskId: null,
    status: "就绪",
    meta: null,
    progress: null,
    ownerProjectId: null,
    cancelPending: false,
    submitting: false,
    ...initialState,
  })
  let poller = null
  let submissionGeneration = 0
  let terminalHandler = null

  function stop() {
    if (poller?.stop) poller.stop()
    poller = null
  }

  function resetMemoryScope() {
    submissionGeneration += 1
    stop()
    state.taskId = null
    state.status = "就绪"
    state.meta = null
    state.progress = null
    state.ownerProjectId = null
    state.cancelPending = false
    state.submitting = false
    onScopeReset?.(state)
  }

  function beginSubmission(projectId) {
    if (!projectId || state.submitting || (state.taskId && state.progress && !state.progress.terminal)) return null
    if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemoryScope()
    const token = { generation: ++submissionGeneration, projectId }
    state.ownerProjectId = projectId
    state.submitting = true
    return token
  }

  function endSubmission(token) {
    if (token?.generation === submissionGeneration) state.submitting = false
  }

  async function handleTerminal(progress, task, ownerProjectId, ownedTaskId) {
    if (state.ownerProjectId !== ownerProjectId || state.taskId !== ownedTaskId) return
    const shouldClearReceipt = progress.done ? clearOnDone : clearOnFailed
    const shouldClearTask = progress.done ? clearOnDone : clearTaskOnFailed
    if (shouldClearReceipt) clearActiveWorkflow(progress.taskId || ownedTaskId)
    stop()
    if (shouldClearTask) state.taskId = null
    state.progress = progress
    await onTerminal?.(progress, state, task, ownerProjectId)
    await terminalHandler?.(progress, state.meta)
  }

  function startPolling(taskId, ownerProjectId) {
    stop()
    const opts = {
      taskId,
      workflowType,
      apiClient: getApi(),
      onUpdate: (progress) => {
        if (state.ownerProjectId !== ownerProjectId || state.taskId !== taskId) return
        state.progress = progress
        state.status = progress.statusLabel || progress.status || "运行中"
        onUpdate?.(progress)
      },
      onDone: (progress, task) => { void handleTerminal(progress, task, ownerProjectId, taskId) },
      onFailed: (progress, task) => { void handleTerminal(progress, task, ownerProjectId, taskId) },
    }
    const novelId = pollNovelId?.(state, ownerProjectId)
    if (novelId) opts.novelId = novelId
    poller = pollTaskProgress(opts)
  }

  function prepare(taskId, meta = null, projectId = getAppState()?.currentProjectId || null) {
    if (!taskId || !projectId) return false
    persistActiveWorkflow({ taskId, workflowType, label, projectId, view, meta: meta || undefined })
    return true
  }

  function adopt(result, meta = null, projectId = getAppState()?.currentProjectId || null) {
    if (!result?.task_id || !projectId) return false
    persistActiveWorkflow({ taskId: result.task_id, workflowType, label, projectId, view, meta: meta || undefined })
    if (requireActiveProjectOnAdopt && getAppState()?.currentProjectId !== projectId) return false
    if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemoryScope()
    state.taskId = result.task_id
    state.status = "运行中"
    state.meta = meta || state.meta || null
    state.ownerProjectId = projectId
    state.progress = normalizeTaskProgress({ ...result, task_type: workflowType, meta: state.meta || {} }, workflowType)
    startPolling(result.task_id, projectId)
    return state
  }

  function recover(projectId) {
    if (!projectId) return resetMemoryScope()
    const scopeMatches = (!state.ownerProjectId || state.ownerProjectId === projectId)
      && (!matchesActiveScope || matchesActiveScope(state, projectId))
    if (state.ownerProjectId && !scopeMatches) resetMemoryScope()
    if (claimProjectOnRecover) state.ownerProjectId = projectId
    if (state.taskId && state.progress && !state.progress.terminal && scopeMatches) {
      state.ownerProjectId = projectId
      if (restartActiveOnRecover && !poller) startPolling(state.taskId, projectId)
      return
    }
    if (skipRecover?.(state, scopeMatches)) return
    const workflow = matchRecovered(recoverActiveWorkflows(projectId), state, projectId)
    if (!workflow?.taskId) return
    state.taskId = workflow.taskId
    state.status = "运行中"
    state.meta = transformRecoveredMeta(workflow.meta) || state.meta || null
    state.ownerProjectId = projectId
    state.progress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: workflow.workflowType || workflowType,
      status: "running",
      meta: workflow.meta || {},
    }, workflow.workflowType || workflowType)
    onRecovered?.(state, workflow, projectId)
    startPolling(workflow.taskId, projectId)
  }

  async function cancel(projectId) {
    const taskId = state.taskId
    if (!taskId || state.ownerProjectId !== projectId || state.cancelPending) return false
    stop()
    state.cancelPending = true
    try {
      await getApi().tasks.cancel(taskId, projectId)
      if (state.ownerProjectId !== projectId || state.taskId !== taskId) return false
      state.cancelPending = false
      state.progress = normalizeTaskProgress({
        task_id: taskId,
        task_type: workflowType,
        status: "cancelled",
        result: { message: "任务已取消" },
        meta: state.meta,
      }, workflowType)
      return true
    } catch (error) {
      if (state.ownerProjectId === projectId && state.taskId === taskId) {
        state.cancelPending = false
        startPolling(taskId, projectId)
      }
      throw error
    }
  }

  function dismiss(projectId) {
    if (state.ownerProjectId !== projectId) return
    stop()
    clearActiveWorkflow(state.taskId)
    state.taskId = null
    state.progress = null
    state.meta = null
    state.cancelPending = false
  }

  function subscribeTerminal(handler) {
    terminalHandler = typeof handler === "function" ? handler : null
    return () => {
      if (terminalHandler === handler) terminalHandler = null
    }
  }

  return {
    state,
    workflowType,
    label,
    ...(destinationLabel === undefined ? {} : { destinationLabel }),
    adopt,
    cancel,
    dismiss,
    ...(exposePrepare ? { prepare } : {}),
    recover,
    subscribeTerminal,
    stop,
    resetMemoryScope,
    beginSubmission,
    endSubmission,
  }
}

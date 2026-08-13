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
  matchesActiveScope = null,
  onScopeReset = null,
  restartActiveOnRecover = false,
  skipRecover = null,
  prepare: exposePrepare = false,
}) {
  const state = reactive({
    taskId: null,
    status: "就绪",
    meta: null,
    progress: null,
    ownerProjectId: null,
    submitting: false,
  })
  let poller = null
  let submissionGeneration = 0

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
    if (!progress.done || clearOnDone) clearActiveWorkflow(progress.taskId || ownedTaskId)
    if (state.ownerProjectId !== ownerProjectId || state.taskId !== ownedTaskId) return
    stop()
    if (!progress.done || clearOnDone) state.taskId = null
    state.progress = progress
    await onTerminal?.(progress, state, task, ownerProjectId)
  }

  function startPolling(taskId, ownerProjectId) {
    stop()
    const opts = {
      taskId,
      workflowType,
      apiClient: getApi(),
      onUpdate: (progress) => {
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
    if (getAppState()?.currentProjectId !== projectId) return false
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
    if (state.taskId && state.progress && !state.progress.terminal && scopeMatches) {
      state.ownerProjectId = projectId
      if (restartActiveOnRecover && !poller) startPolling(state.taskId, projectId)
      return
    }
    if (skipRecover?.(state, scopeMatches)) return
    const workflow = matchRecovered(recoverActiveWorkflows(projectId))
    if (!workflow?.taskId) return
    state.taskId = workflow.taskId
    state.status = "运行中"
    state.meta = workflow.meta || state.meta || null
    state.ownerProjectId = projectId
    state.progress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: workflow.workflowType || workflowType,
      status: "running",
      meta: workflow.meta || {},
    }, workflow.workflowType || workflowType)
    startPolling(workflow.taskId, projectId)
  }

  return {
    state,
    workflowType,
    label,
    ...(destinationLabel === undefined ? {} : { destinationLabel }),
    adopt,
    ...(exposePrepare ? { prepare } : {}),
    recover,
    stop,
    resetMemoryScope,
    beginSubmission,
    endSubmission,
  }
}

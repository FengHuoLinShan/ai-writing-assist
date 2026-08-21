import { reactive } from "vue"
import { getApi, getAppState, getToast } from "../../bridge/index.js"
import {
  clearActiveWorkflow,
  createOperationId,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"

const WORKFLOW_TYPE = "scene_simulation_runtime"

const state = reactive({
  ownerProjectId: null,
  ownerSceneId: null,
  taskId: null,
  progress: null,
  result: null,
  meta: null,
  submitting: false,
  cancelPending: false,
})

let poller = null
let terminalHandler = null
let generation = 0

function stop() {
  poller?.stop?.()
  poller = null
}

function resetMemory() {
  generation += 1
  stop()
  Object.assign(state, {
    ownerProjectId: null,
    ownerSceneId: null,
    taskId: null,
    progress: null,
    result: null,
    meta: null,
    submitting: false,
    cancelPending: false,
  })
}

function owned(projectId, sceneId, token = generation) {
  return Boolean(projectId && sceneId)
    && token === generation
    && state.ownerProjectId === projectId
    && state.ownerSceneId === sceneId
}

function beginSubmission(projectId, sceneId, stage = "simulation") {
  if (!projectId || !sceneId || state.submitting || (state.taskId && state.progress && !state.progress.terminal)) return null
  if (state.ownerProjectId !== projectId || state.ownerSceneId !== sceneId) resetMemory()
  const token = { generation: ++generation, projectId, sceneId, stage, operationId: createOperationId() }
  Object.assign(state, {
    ownerProjectId: projectId,
    ownerSceneId: sceneId,
    taskId: null,
    progress: null,
    result: null,
    meta: { stage },
    submitting: true,
    cancelPending: false,
  })
  return token
}

function endSubmission(token) {
  if (!token || token.generation !== generation) return
  state.submitting = false
}

function setResult(result, projectId = state.ownerProjectId, sceneId = state.ownerSceneId) {
  if (!owned(projectId, sceneId)) return false
  state.result = result || null
  state.progress = null
  state.taskId = null
  state.submitting = false
  return true
}

function startPolling(taskId, projectId, sceneId, meta) {
  stop()
  const token = generation
  const stageLabel = {
    "character-card": "人物卡建议",
    reaction: "人物反应建议",
    script: "剧本建议",
    simulation: "场景推演",
  }[meta?.stage] || "场景任务"
  poller = pollTaskProgress({
    taskId,
    workflowType: WORKFLOW_TYPE,
    novelId: projectId,
    apiClient: getApi(),
    onUpdate: (progress) => {
      if (!owned(projectId, sceneId, token) || state.taskId !== taskId) return
      state.progress = progress
    },
    onDone: async (progress) => {
      if (!owned(projectId, sceneId, token) || state.taskId !== taskId) return
      clearActiveWorkflow(progress.taskId || taskId)
      state.progress = progress
      state.result = progress.result
        || progress.output
        || progress.data
        || progress.preview
        || progress.raw?.result
        || progress.raw?.output
        || progress.raw?.data
        || progress.raw?.preview
        || null
      state.taskId = null
      state.submitting = false
      getToast()(`${stageLabel}已完成，结果仍是待确认草稿`, "success")
      await terminalHandler?.(progress, meta)
    },
    onFailed: async (progress) => {
      if (!owned(projectId, sceneId, token) || state.taskId !== taskId) return
      state.progress = progress
      state.taskId = null
      state.submitting = false
      getToast()(progress.cancelled ? `${stageLabel}已取消` : `${stageLabel}失败：${progress.errorMessage || "未知错误"}`, progress.cancelled ? "warning" : "error")
      await terminalHandler?.(progress, meta)
    },
  })
}

function adopt(result, meta = {}, projectId = getAppState()?.currentProjectId, sceneId = meta.sceneId || null) {
  if (!result?.task_id || !projectId || !sceneId) return false
  if (state.ownerProjectId !== projectId || state.ownerSceneId !== sceneId) resetMemory()
  state.ownerProjectId = projectId
  state.ownerSceneId = sceneId
  state.taskId = result.task_id
  state.meta = { ...meta, sceneId }
  state.cancelPending = false
  state.submitting = false
  state.progress = normalizeTaskProgress({
    ...result,
    task_type: WORKFLOW_TYPE,
    meta: state.meta,
  }, WORKFLOW_TYPE)
  persistActiveWorkflow({
    taskId: result.task_id,
    workflowType: WORKFLOW_TYPE,
    label: "场景推演",
    projectId,
    view: "outline",
    meta: state.meta,
  })
  startPolling(result.task_id, projectId, sceneId, state.meta)
  return true
}

function recover(projectId, sceneId = null) {
  if (!projectId) return null
  if (state.ownerProjectId && (state.ownerProjectId !== projectId || (sceneId && state.ownerSceneId !== sceneId))) resetMemory()
  state.ownerProjectId = projectId
  const current = state.taskId && state.ownerSceneId
    ? { taskId: state.taskId, sceneId: state.ownerSceneId, meta: state.meta }
    : null
  const workflow = current || recoverActiveWorkflows(projectId)
    .filter((item) => item.workflowType === WORKFLOW_TYPE && item.view === "outline")
    .filter((item) => !sceneId || item.meta?.sceneId === sceneId)
    .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0]
  if (!workflow?.taskId || !workflow.sceneId && !workflow.meta?.sceneId) return null
  const effectiveSceneId = workflow.sceneId || workflow.meta.sceneId
  state.ownerSceneId = effectiveSceneId
  state.taskId = workflow.taskId
  state.meta = { ...(workflow.meta || {}), sceneId: effectiveSceneId }
  state.progress = normalizeTaskProgress({
    task_id: workflow.taskId,
    task_type: WORKFLOW_TYPE,
    status: "running",
    meta: state.meta,
  }, WORKFLOW_TYPE)
  startPolling(workflow.taskId, projectId, effectiveSceneId, state.meta)
  return effectiveSceneId
}

async function cancel(projectId, sceneId = state.ownerSceneId) {
  const taskId = state.taskId
  if (!taskId || !owned(projectId, sceneId) || state.cancelPending) return false
  stop()
  state.cancelPending = true
  try {
    await getApi().tasks.cancel(taskId, projectId)
    if (!owned(projectId, sceneId) || state.taskId !== taskId) return false
    state.cancelPending = false
    state.progress = normalizeTaskProgress({
      task_id: taskId,
      task_type: WORKFLOW_TYPE,
      status: "cancelled",
      result: { message: "任务已取消" },
      meta: state.meta,
    }, WORKFLOW_TYPE)
    clearActiveWorkflow(taskId)
    state.taskId = null
    return true
  } catch (err) {
    if (owned(projectId, sceneId) && state.taskId === taskId) {
      state.cancelPending = false
      startPolling(taskId, projectId, sceneId, state.meta)
    }
    throw err
  }
}

function dismiss(projectId, sceneId = state.ownerSceneId) {
  if (!owned(projectId, sceneId)) return
  stop()
  clearActiveWorkflow(state.taskId)
  Object.assign(state, { taskId: null, progress: null, result: null, meta: null, cancelPending: false })
}

function subscribeTerminal(handler) {
  terminalHandler = typeof handler === "function" ? handler : null
  return () => {
    if (terminalHandler === handler) terminalHandler = null
  }
}

export { WORKFLOW_TYPE }
export const sceneRuntimeManager = {
  state,
  adopt,
  beginSubmission,
  cancel,
  dismiss,
  endSubmission,
  recover,
  resetMemory,
  setResult,
  stop,
  subscribeTerminal,
}

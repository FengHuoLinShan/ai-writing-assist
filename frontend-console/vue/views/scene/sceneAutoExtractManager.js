import { reactive } from "vue"
import { getApi, getAppState, getToast } from "../../bridge/index.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"

const state = reactive({
  ownerProjectId: null,
  taskId: null,
  progress: null,
  meta: null,
  cancelPending: false,
})

let poller = null
let terminalHandler = null

function stop() {
  poller?.stop?.()
  poller = null
}

function resetMemory() {
  stop()
  state.ownerProjectId = null
  state.taskId = null
  state.progress = null
  state.meta = null
  state.cancelPending = false
}

function owned(projectId) {
  return Boolean(projectId) && state.ownerProjectId === projectId
}

function startPolling(taskId, projectId) {
  stop()
  const api = getApi()
  poller = pollTaskProgress({
    taskId,
    workflowType: "scene_auto_extraction",
    novelId: projectId,
    apiClient: api,
    onUpdate: (progress) => {
      if (!owned(projectId) || state.taskId !== taskId) return
      state.progress = progress
    },
    onDone: async (progress) => {
      if (!owned(projectId) || state.taskId !== taskId) return
      clearActiveWorkflow(progress.taskId || taskId)
      state.taskId = null
      state.progress = progress
      getToast()("从正文提取 Scene 完成", "success")
      await terminalHandler?.(progress)
    },
    onFailed: async (progress) => {
      if (!owned(projectId) || state.taskId !== taskId) return
      state.progress = progress
      getToast()(
        progress.cancelled
          ? "当前正文 Scene 提取任务已取消"
          : `从正文提取 Scene 失败: ${progress.errorMessage || "未知错误"}`,
        progress.cancelled ? "warning" : "error",
      )
      await terminalHandler?.(progress)
    },
  })
}

function recover(projectId) {
  if (!projectId) return
  if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemory()
  state.ownerProjectId = projectId
  if (state.taskId && state.progress && !state.progress.terminal) {
    if (!poller) startPolling(state.taskId, projectId)
    return
  }
  const workflow = recoverActiveWorkflows(projectId)
    .filter((item) => item.projectId === projectId)
    .find((item) => item.workflowType === "scene_auto_extraction")
  if (!workflow?.taskId) return
  state.taskId = workflow.taskId
  state.meta = {
    start_chapter: workflow.meta?.start_chapter ?? workflow.meta?.startChapter ?? 1,
    end_chapter: workflow.meta?.end_chapter ?? workflow.meta?.endChapter ?? 10,
    highQuality: Boolean(workflow.meta?.highQuality),
  }
  state.cancelPending = false
  state.progress = normalizeTaskProgress({
    task_id: workflow.taskId,
    task_type: "scene_auto_extraction",
    status: "running",
    meta: state.meta,
  }, "scene_auto_extraction")
  startPolling(workflow.taskId, projectId)
}

function adopt(result, meta, projectId = getAppState()?.currentProjectId) {
  if (!result?.task_id || !projectId) return false
  if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemory()
  state.ownerProjectId = projectId
  state.taskId = result.task_id
  state.meta = { ...meta }
  state.cancelPending = false
  state.progress = normalizeTaskProgress({
    ...result,
    task_type: "scene_auto_extraction",
    meta: state.meta,
  }, "scene_auto_extraction")
  persistActiveWorkflow({
    taskId: result.task_id,
    workflowType: "scene_auto_extraction",
    label: "从正文提取 Scene",
    projectId,
    view: "outline",
    meta: state.meta,
  })
  startPolling(result.task_id, projectId)
  return true
}

async function cancel(projectId) {
  const taskId = state.taskId
  if (!taskId || !owned(projectId) || state.cancelPending) return false
  stop()
  state.cancelPending = true
  try {
    await getApi().tasks.cancel(taskId, projectId)
    if (!owned(projectId) || state.taskId !== taskId) return false
    state.cancelPending = false
    state.progress = normalizeTaskProgress({
      task_id: taskId,
      task_type: "scene_auto_extraction",
      status: "cancelled",
      result: { message: "任务已取消" },
      meta: state.meta,
    }, "scene_auto_extraction")
    return true
  } catch (err) {
    if (owned(projectId) && state.taskId === taskId) {
      state.cancelPending = false
      startPolling(taskId, projectId)
    }
    throw err
  }
}

function dismiss(projectId) {
  if (!owned(projectId)) return
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

export const sceneAutoExtractManager = {
  state,
  adopt,
  cancel,
  dismiss,
  recover,
  resetMemory,
  stop,
  subscribeTerminal,
}

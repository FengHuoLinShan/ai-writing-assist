import { getAppState, getToast } from "../../bridge/index.js"
import { createWorkflowManager } from "../../shared/workflowManager.js"
import { clearActiveWorkflow, createOperationId } from "../../../shared/workflowProgress.js"

const WORKFLOW_TYPE = "scene_simulation_runtime"
const stageLabel = (stage) => ({
  "character-card": "人物卡建议",
  reaction: "人物反应建议",
  script: "剧本建议",
  simulation: "场景推演",
}[stage] || "场景任务")

const manager = createWorkflowManager({
  workflowType: WORKFLOW_TYPE,
  label: "场景推演",
  view: "outline",
  pollNovelId: (_state, projectId) => projectId,
  restartActiveOnRecover: true,
  claimProjectOnRecover: true,
  clearOnFailed: false,
  clearTaskOnFailed: true,
  initialState: { ownerSceneId: null, result: null },
  onScopeReset: (state) => {
    state.ownerSceneId = null
    state.result = null
  },
  matchRecovered: (workflows, state) => workflows
    .filter((item) => item.workflowType === WORKFLOW_TYPE && item.view === "outline")
    .filter((item) => !state.ownerSceneId || item.meta?.sceneId === state.ownerSceneId)
    .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0],
  transformRecoveredMeta: (meta) => ({ ...meta, sceneId: meta?.sceneId || null }),
  onRecovered: (state) => { state.ownerSceneId = state.meta?.sceneId || null },
  onTerminal: (progress, state) => {
    const label = stageLabel(state.meta?.stage)
    state.submitting = false
    if (progress.done) {
      state.result = progress.result
        || progress.output
        || progress.data
        || progress.preview
        || progress.raw?.result
        || progress.raw?.output
        || progress.raw?.data
        || progress.raw?.preview
        || null
      getToast()(`${label}已完成，结果仍是待确认草稿`, "success")
      return
    }
    getToast()(
      progress.cancelled ? `${label}已取消` : `${label}失败：${progress.errorMessage || "未知错误"}`,
      progress.cancelled ? "warning" : "error",
    )
  },
})

function resetMemory() {
  manager.resetMemoryScope()
}

function beginSubmission(projectId, sceneId, stage = "simulation") {
  if (!projectId || !sceneId) return null
  if (manager.state.ownerProjectId !== projectId || manager.state.ownerSceneId !== sceneId) resetMemory()
  const token = manager.beginSubmission(projectId)
  if (!token) return null
  Object.assign(token, { sceneId, stage, operationId: createOperationId() })
  Object.assign(manager.state, {
    ownerSceneId: sceneId,
    result: null,
    meta: { stage },
    cancelPending: false,
  })
  return token
}

function adopt(result, meta = {}, projectId = getAppState()?.currentProjectId, sceneId = meta.sceneId || null) {
  if (!result?.task_id || !projectId || !sceneId) return false
  if (manager.state.ownerProjectId !== projectId || manager.state.ownerSceneId !== sceneId) resetMemory()
  manager.state.ownerSceneId = sceneId
  manager.state.submitting = false
  return Boolean(manager.adopt(result, { ...meta, sceneId }, projectId))
}

function recover(projectId, sceneId = null) {
  if (!projectId) return null
  if (manager.state.ownerProjectId && (
    manager.state.ownerProjectId !== projectId
    || (sceneId && manager.state.ownerSceneId !== sceneId)
  )) resetMemory()
  if (sceneId) manager.state.ownerSceneId = sceneId
  manager.recover(projectId)
  return manager.state.taskId ? manager.state.ownerSceneId : null
}

function setResult(result, projectId = manager.state.ownerProjectId, sceneId = manager.state.ownerSceneId) {
  if (manager.state.ownerProjectId !== projectId || manager.state.ownerSceneId !== sceneId) return false
  Object.assign(manager.state, { result: result || null, progress: null, taskId: null, submitting: false })
  return true
}

async function cancel(projectId, sceneId = manager.state.ownerSceneId) {
  if (manager.state.ownerSceneId !== sceneId) return false
  const taskId = manager.state.taskId
  const cancelled = await manager.cancel(projectId)
  if (cancelled) {
    clearActiveWorkflow(taskId)
    manager.state.taskId = null
  }
  return cancelled
}

function dismiss(projectId, sceneId = manager.state.ownerSceneId) {
  if (manager.state.ownerSceneId !== sceneId) return
  manager.dismiss(projectId)
  manager.state.result = null
}

export { WORKFLOW_TYPE }
export const sceneRuntimeManager = {
  ...manager,
  adopt,
  beginSubmission,
  cancel,
  dismiss,
  recover,
  resetMemory,
  setResult,
}

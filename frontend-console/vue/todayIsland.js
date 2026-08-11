import { clearActiveWorkflow, normalizeTaskProgress, recoverActiveWorkflows } from "../shared/workflowProgress.js"
import { getApi, getAppState, getRouter } from "./bridge/index.js"
import { mountIsland } from "./mountIsland.js"
import TodayView from "./views/today/TodayView.vue"

const WORKFLOW_LIMIT = 3

async function loadWorkflow(api, workflow, projectId) {
  try {
    const task = await api.tasks.get(workflow.taskId, projectId)
    const progress = normalizeTaskProgress(task, workflow.workflowType)
    if (progress.done || progress.cancelled) {
      clearActiveWorkflow(workflow.taskId)
      return null
    }
    return {
      ...progress,
      view: workflow.view || null,
    }
  } catch {
    return {
      taskId: workflow.taskId,
      workflowType: workflow.workflowType || "task",
      view: workflow.view || null,
      status: "unknown",
      statusLabel: "状态暂不可用",
      percent: null,
      failed: false,
      stateUnknown: true,
    }
  }
}

export async function loadTodayProps() {
  const state = getAppState()
  const api = getApi()
  const projectId = state?.currentProjectId || null
  const project = state?.currentProject || null
  if (!projectId) {
    return {
      project: null,
      summary: null,
      workflows: [],
      loadError: "请先选择一部作品。",
    }
  }

  const summaryResult = await Promise.allSettled([
    api.projects.getWorkspaceSummary(projectId),
  ])
  const stored = recoverActiveWorkflows(projectId)
    .sort((left, right) => String(right.updatedAt || right.createdAt || "").localeCompare(String(left.updatedAt || left.createdAt || "")))
    .slice(0, WORKFLOW_LIMIT)
  const workflows = (await Promise.all(
    stored.map((workflow) => loadWorkflow(api, workflow, projectId)),
  )).filter(Boolean)

  return {
    project,
    summary: summaryResult[0].status === "fulfilled" ? summaryResult[0].value : null,
    workflows,
    loadError: summaryResult[0].status === "rejected"
      ? (summaryResult[0].reason?.message || "作品概览暂时无法加载。")
      : null,
  }
}

export function registerTodayIsland() {
  const router = getRouter()
  if (!router) {
    console.error("todayIsland: router 尚未就绪，island 注册跳过")
    return null
  }
  const island = mountIsland({
    viewName: "today",
    component: TodayView,
    load: loadTodayProps,
  })
  router.registerView("today", island)
  return island
}

registerTodayIsland()

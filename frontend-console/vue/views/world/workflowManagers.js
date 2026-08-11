/**
 * workflowManagers — world 视图两条工作流轮询线的模块级管理器。
 *
 * 对应 vanilla worldView 的 _autoExtract*（worldView.js:876-1119）与
 * _fusion*（L941-1036）字段组。按 prewarmManager 评审教训：轮询不挂组件
 * 生命周期（island 在 query-only 变化时重挂载，不能打断轮询）；模块级
 * reactive state 暴露给组件，进度卡由响应式绑定渲染。
 *
 * 生命周期对齐 vanilla：
 * - island load() → recover(projectId)（localStorage 恢复未终结任务）；
 * - island onLeave → stop()（vanilla onLeave 停轮询，worldView.js:696-706）；
 * - 终态 clearActiveWorkflow；autoExtract done 额外 toast + router.refresh()
 *   重拉列表与 batches（对齐 vanilla _handleAutoExtractTerminal 的 reload）。
 */
import { reactive } from "vue"
import { getApi, getAppState, getRouter, getToast } from "../../bridge/index.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"
import { importAuthorizationPayload } from "../../../shared/importAuthorization.js"

function createWorkflowManager({
  workflowType,
  label,
  destinationLabel,
  matchRecovered,
  onTerminal,
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

  async function handleTerminal(progress) {
    stop()
    clearActiveWorkflow(progress.taskId || state.taskId)
    state.taskId = null
    state.progress = progress
    await onTerminal?.(progress, state)
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
  }

  function beginSubmission(projectId) {
    if (
      !projectId
      || state.submitting
      || (state.taskId && state.progress && !state.progress.terminal)
    ) return null
    if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemoryScope()
    const token = { generation: ++submissionGeneration, projectId }
    state.ownerProjectId = projectId
    state.submitting = true
    return token
  }

  function endSubmission(token) {
    if (!token || token.generation !== submissionGeneration) return
    state.submitting = false
  }

  function startPolling(taskId, projectId) {
    stop()
    const api = getApi()
    poller = pollTaskProgress({
      taskId,
      workflowType,
      novelId: projectId,
      apiClient: api,
      onUpdate: (progress) => {
        state.progress = progress
        state.status = progress.statusLabel || progress.status || "运行中"
      },
      onDone: (progress) => { void handleTerminal(progress) },
      onFailed: (progress) => { void handleTerminal(progress) },
    })
  }

  /** 提交成功后接管任务：写 localStorage 并开始轮询（对应 vanilla submit 后半段）。 */
  function adopt(result, meta = null, projectId = getAppState()?.currentProjectId || null) {
    if (!result?.task_id || !projectId) return false
    persistActiveWorkflow({
      taskId: result.task_id,
      workflowType,
      label,
      projectId,
      view: "world",
      meta: meta || undefined,
    })
    if (getAppState()?.currentProjectId !== projectId) return false
    if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemoryScope()
    state.taskId = result.task_id
    state.status = "运行中"
    state.meta = meta || state.meta || null
    state.ownerProjectId = projectId
    state.progress = normalizeTaskProgress({
      ...result,
      task_type: workflowType,
      meta: state.meta || {},
    }, workflowType)
    startPolling(result.task_id, projectId)
    return state
  }

  /** island load() 调用：从 localStorage 恢复未终结任务（对应 vanilla _recoverXxxWorkflow）。 */
  function recover(projectId) {
    if (!projectId) {
      resetMemoryScope()
      return
    }
    if (state.ownerProjectId && state.ownerProjectId !== projectId) resetMemoryScope()
    if (state.taskId && state.progress && !state.progress.terminal) {
      state.ownerProjectId = projectId
      if (!poller) startPolling(state.taskId, projectId)
      return
    }
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
    destinationLabel,
    adopt,
    recover,
    stop,
    resetMemoryScope,
    beginSubmission,
    endSubmission,
  }
}

function refreshWorldIfActive() {
  const appState = getAppState()
  if (appState?.currentView !== "world") return
  const router = getRouter()
  router?.refresh?.()
}

/** 世界对象与别名/关系自动提取（world_objects 阶段）。 */
export const autoExtractManager = createWorkflowManager({
  workflowType: "world_object_auto_extraction",
  label: "整理人物、设定与关系",
  destinationLabel: "完成后查看世界对象、别名和待处理关系。",
  matchRecovered: (workflows) => (
    workflows.find((item) => item.workflowType === "world_object_auto_extraction" && item.view === "world")
    || workflows.find((item) => item.workflowType === "world_object_auto_extraction")
  ),
  onTerminal: async (progress) => {
    const toast = getToast()
    if (progress.done) {
      toast("人物、设定与关系已整理完成", "success")
      // vanilla 在此重拉 entities/candidates/batches 并 navigate；refresh 触发
      // island onEnter → load() 全量重取，等价。
      refreshWorldIfActive()
      return
    }
    if (progress.failed || progress.cancelled) {
      const message = progress.cancelled ? "提取任务已取消" : `提取任务失败: ${progress.errorMessage || "未知错误"}`
      toast(message, progress.cancelled ? "warning" : "error")
    }
  },
})

/** 世界对象 AI 合并建议。 */
export const fusionManager = createWorkflowManager({
  workflowType: "world_entity_fusion_suggestions",
  label: "世界对象 AI 合并建议",
  destinationLabel: "完成后可选择合并或登记别名",
  matchRecovered: (workflows) => (
    workflows.find((item) => item.workflowType === "world_entity_fusion_suggestions")
  ),
  onTerminal: async (progress) => {
    const toast = getToast()
    if (progress.done) {
      toast("世界对象 AI 合并建议已生成", "success")
    } else if (progress.failed || progress.cancelled) {
      toast(`世界对象 AI 合并建议失败: ${progress.errorMessage || "未知错误"}`, "error")
    }
    // 终态 progress 保留在 state（done 时组件渲染"查看建议"按钮），
    // 由响应式绑定更新界面，无需 vanilla 的 renderCurrentView 整刷。
  },
})

/** 对应 vanilla _submitAutoExtract（worldView.js:876-921）；章节范围由组件传入。 */
export async function submitAutoExtract(start, end) {
  const toast = getToast()
  const appState = getAppState()
  if (!appState?.currentProjectId) {
    toast("请先选择项目", "warning")
    return false
  }
  if (start > end) {
    toast("起始章节不能大于结束章节", "warning")
    return false
  }
  const projectId = appState.currentProjectId
  const submission = autoExtractManager.beginSubmission(projectId)
  if (!submission) {
    toast("世界对象提取正在提交，请稍候", "info")
    return false
  }
  try {
    const result = await getApi().imports.startStage(
      "world_objects",
      projectId,
      start,
      end,
      false,
      false,
      importAuthorizationPayload(),
    )
    const adopted = autoExtractManager.adopt(
      result,
      { start_chapter: start, end_chapter: end },
      projectId,
    )
    if (adopted) toast("已开始整理人物、设定与关系", "info")
    return true
  } catch (err) {
    if (getAppState()?.currentProjectId === projectId) {
      autoExtractManager.state.status = `失败: ${err.message}`
      toast(err.message || "提交失败", "error")
    }
    return false
  } finally {
    autoExtractManager.endSubmission(submission)
  }
}

/** 对应 vanilla _startEntityFusionSuggestions（worldView.js:981-1009）。 */
export async function startEntityFusionSuggestions(entityType = "") {
  const toast = getToast()
  const appState = getAppState()
  if (!appState?.currentProjectId) {
    toast("请先选择项目", "warning")
    return false
  }
  const projectId = appState.currentProjectId
  const submission = fusionManager.beginSubmission(projectId)
  if (!submission) {
    toast("世界对象 AI 合并建议正在提交，请稍候", "info")
    return false
  }
  try {
    const result = await getApi().world.createEntityFusionSuggestions({
      novel_id: projectId,
      entity_type: entityType || undefined,
    })
    const adopted = fusionManager.adopt(result, null, projectId)
    if (adopted) toast("世界对象 AI 合并建议任务已提交", "success")
    return true
  } catch (err) {
    if (getAppState()?.currentProjectId === projectId) {
      toast(err.message || "提交失败", "error")
    }
    return false
  } finally {
    fusionManager.endSubmission(submission)
  }
}

import { computed, reactive } from "vue"
import { getApi, getAppState, getToast } from "../../bridge/index.js"
import { importAuthorizationPayload } from "../../../shared/importAuthorization.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"

const WORKFLOW_TYPE = "map_observation_enrichment"

export function useMapEnrichment({ projectId, onDone } = {}) {
  const api = getApi()
  const appState = getAppState()
  const toast = getToast()
  const state = reactive({
    taskId: null,
    progress: null,
    startChapter: 1,
    endChapter: "",
    highQuality: true,
    submitting: false,
  })
  let disposed = false
  let poller = null

  const running = computed(() => Boolean(
    state.submitting || (state.taskId && !state.progress?.terminal),
  ))

  function ownsProject() {
    return !disposed && appState?.currentProjectId === projectId
  }

  function stopPolling() {
    poller?.stop?.()
    poller = null
  }

  function startPolling(taskId) {
    stopPolling()
    poller = pollTaskProgress({
      taskId,
      workflowType: WORKFLOW_TYPE,
      novelId: projectId,
      apiClient: api,
      onUpdate: (progress) => {
        if (ownsProject() && state.taskId === taskId) state.progress = progress
      },
      onDone: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        if (!ownsProject() || state.taskId !== taskId) return
        state.taskId = null
        state.progress = progress
        await onDone?.(progress)
        if (ownsProject()) toast("地图事实补充完成；请在收件箱或对应地图中复核", "success")
      },
      onFailed: (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        if (!ownsProject() || state.taskId !== taskId) return
        state.taskId = null
        state.progress = progress
        toast(`地图事实补充失败：${progress.errorMessage || "未知错误"}`, "error")
      },
    })
    return poller
  }

  function recover() {
    if (!projectId || state.taskId) return false
    const workflow = recoverActiveWorkflows(projectId)
      .find((item) => item.workflowType === WORKFLOW_TYPE)
    if (!workflow?.taskId) return false
    const meta = workflow.meta || {}
    state.taskId = workflow.taskId
    state.startChapter = Number(meta.start_chapter || 1)
    state.endChapter = Number(meta.end_chapter || 0) || ""
    state.highQuality = meta.high_quality !== false
    state.progress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: WORKFLOW_TYPE,
      status: "running",
      meta,
    }, WORKFLOW_TYPE)
    startPolling(workflow.taskId)
    return true
  }

  function scopePayload() {
    const startChapter = Number.parseInt(String(state.startChapter || "1"), 10)
    const rawEnd = String(state.endChapter ?? "").trim()
    const endChapter = rawEnd ? Number.parseInt(rawEnd, 10) : 0
    if (!Number.isInteger(startChapter) || startChapter < 1) {
      throw new Error("起始章必须是大于等于 1 的整数")
    }
    if (rawEnd && (!Number.isInteger(endChapter) || endChapter < 1)) {
      throw new Error("结束章必须是大于等于 1 的整数，或留空使用最后一章")
    }
    if (endChapter && startChapter > endChapter) {
      throw new Error("起始章不能大于结束章")
    }
    return { startChapter, endChapter, highQuality: state.highQuality !== false }
  }

  async function submit() {
    if (!ownsProject()) {
      toast("当前项目已切换，请返回原项目重新提交", "warning")
      return false
    }
    let scope
    try {
      scope = scopePayload()
    } catch (error) {
      toast(error.message, "warning")
      return false
    }
    state.submitting = true
    try {
      const result = await api.imports.startMapObservationEnrichment(
        projectId,
        scope.startChapter,
        scope.endChapter,
        scope.highQuality,
        importAuthorizationPayload(),
      )
      const meta = {
        start_chapter: scope.startChapter,
        end_chapter: scope.endChapter,
        high_quality: scope.highQuality,
      }
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: WORKFLOW_TYPE,
        label: "地图事实补充",
        projectId,
        view: "map",
        meta,
      })
      if (!ownsProject()) {
        state.taskId = null
        state.progress = null
        toast("地图事实补充已提交到原项目；返回原项目后可继续查看进度", "info")
        return false
      }
      state.taskId = result.task_id
      state.progress = normalizeTaskProgress({
        ...result,
        task_type: WORKFLOW_TYPE,
        meta,
      }, WORKFLOW_TYPE)
      startPolling(result.task_id)
      toast("地图事实补充任务已提交；不会重跑深度导入", "success")
      return true
    } catch (error) {
      if (ownsProject()) toast(error.message || "地图事实补充提交失败", "error")
      return false
    } finally {
      state.submitting = false
    }
  }

  function dispose() {
    disposed = true
    stopPolling()
  }

  return { state, running, recover, submit, dispose, scopePayload, startPolling }
}

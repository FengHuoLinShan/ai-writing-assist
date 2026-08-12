/**
 * RAG 索引工作流 composable — 对应 vanilla ragView 的 _rebuildIndex /
 * _retryEmbeddings / _retryFailedTask / _recoverRebuildWorkflow
 * 与轮询管理（_startRebuildPolling/_stopRebuildPolling）。
 * （预热由 ./prewarmManager.js 模块级管理，不在组件生命周期内。）
 * 进度写入 ragSearchSession（跨 island 重挂载存活）；scope 销毁时停止轮询。
 * 创建任务的写请求不随视图取消，避免服务端已入队但客户端丢失 task_id。
 */
import { computed, getCurrentScope, onScopeDispose, ref } from "vue"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"
import { useWorkflowPolling } from "../../composables/useWorkflowPolling.js"
import { getApi, getAppState, getToast } from "../../bridge/index.js"
import { ragSearchSession } from "./ragSearchSession.js"

/**
 * 创建索引工作流。
 * @param {{statusFields: object, refreshStatus?: () => Promise<void>}} options
 *   statusFields 为 RagView 持有的 reactive 状态字段（totalChunks/
 *   embeddingFailedCount/retryableEmbeddingCount/statusWarnings/statusDegraded）；
 *   refreshStatus 用于工作流完成后刷新状态页数据。
 */
export function useRagWorkflow({ statusFields, refreshStatus } = {}) {
  const polling = useWorkflowPolling()
  let pollerStarted = false
  let disposed = false
  const maintenanceSubmitting = ref(false)
  let maintenanceSubmissionGeneration = 0

  const maintenanceBusy = computed(() => {
    const progress = ragSearchSession.rebuildProgress
    return maintenanceSubmitting.value || Boolean(progress && !progress.terminal)
  })

  function beginMaintenanceSubmission() {
    if (disposed || maintenanceBusy.value) return null
    const token = ++maintenanceSubmissionGeneration
    maintenanceSubmitting.value = true
    return token
  }

  function endMaintenanceSubmission(token) {
    if (disposed || token !== maintenanceSubmissionGeneration) return
    maintenanceSubmitting.value = false
  }

  function ownsProject(projectId) {
    const ownerProjectId = ragSearchSession.ownerProjectId
    return !disposed
      && getAppState()?.currentProjectId === projectId
      && (!ownerProjectId || ownerProjectId === projectId)
  }

  /** onUpdate → session.rebuildProgress；onDone/onFailed → 状态落账（对应 _handleRebuildDone）。 */
  function startRebuildPolling(
    taskId,
    workflowType,
    projectId,
  ) {
    const ownsPollingProject = () => ownsProject(projectId)
    if (!ownsPollingProject()) return false
    pollerStarted = true
    polling.start({
      taskId,
      workflowType,
      novelId: projectId,
      onUpdate: (progress) => {
        if (!ownsPollingProject()) return
        ragSearchSession.rebuildProgress = progress
        ragSearchSession.rebuildInfo = null
      },
      onDone: (progress, task) => {
        if (!ownsPollingProject()) return
        const result = task?.result || progress.raw?.result || {}
        void handleRebuildDone(taskId, workflowType, result, projectId)
      },
      onFailed: () => {
        // 失败/取消状态保留在 rebuildProgress 中展示（vanilla 仅刷新 DOM）
      },
    })
    return true
  }

  async function applyRagRebuildResult(result = {}, projectId) {
    if (!ownsProject(projectId)) return false
    if (result.chunks_created != null) {
      statusFields.totalChunks = result.chunks_created
    } else if (result.total_chapters != null) {
      statusFields.totalChunks = null
      await refreshStatus?.()
    }
    if (result.embedding_failed_count != null) {
      statusFields.embeddingFailedCount = result.embedding_failed_count
    }
    if (Array.isArray(result.warnings)) {
      statusFields.statusWarnings = result.warnings
      statusFields.statusDegraded = result.warnings.length > 0 || Boolean(result.embedding_failed_count)
    }
    return ownsProject(projectId)
  }

  async function handleRebuildDone(taskId, workflowType, result = {}, projectId) {
    if (!ownsProject(projectId)) return
    try {
      if (workflowType === "rag_retry_embeddings") {
        const remaining = result.remaining_retryable_count ?? result.failed ?? 0
        statusFields.retryableEmbeddingCount = remaining
        statusFields.embeddingFailedCount = remaining
        await refreshStatus?.()
      } else {
        await applyRagRebuildResult(result, projectId)
      }
    } catch (err) {
      if (ownsProject(projectId)) {
        getToast()(`索引任务已完成，但状态刷新失败：${err.message || "未知错误"}`, "warning")
      }
    } finally {
      clearActiveWorkflow(taskId)
    }
  }

  /** 恢复跨刷新的活动工作流（对应 _recoverRebuildWorkflow）。 */
  function recoverRebuildWorkflow() {
    const state = getAppState()
    const projectId = state?.currentProjectId
    if (!projectId || pollerStarted || !ownsProject(projectId)) return
    const workflows = recoverActiveWorkflows(projectId)
    const ragWorkflowTypes = new Set(["rag_reindex_novel", "rag_retry_embeddings"])
    const workflow = workflows.find((item) => ragWorkflowTypes.has(item.workflowType) && item.view === "rag")
      || workflows.find((item) => ragWorkflowTypes.has(item.workflowType))
    if (!workflow?.taskId) return
    const workflowType = workflow.workflowType || "rag_reindex_novel"
    ragSearchSession.rebuildInfo = null
    ragSearchSession.rebuildProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: workflowType,
      status: "running",
      meta: workflow.meta || {},
    }, workflowType)
    startRebuildPolling(workflow.taskId, workflowType, projectId)
  }

  /** 重建索引（对应 _rebuildIndex；form = {contentMode, start, end}）。 */
  async function rebuildIndex(form) {
    const toast = getToast()
    const state = getAppState()
    if (disposed) return false
    if (!state?.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    const projectId = state.currentProjectId
    const rawStartChapter = String(form?.start ?? "").trim()
    const rawEndChapter = String(form?.end ?? "").trim()
    let chapterRange = null
    if (rawStartChapter || rawEndChapter) {
      if (!rawStartChapter || !rawEndChapter) {
        toast("请同时填写起始章节和结束章节", "warning")
        return false
      }
      const startChapter = Number(rawStartChapter)
      const endChapter = Number(rawEndChapter)
      if (
        !Number.isInteger(startChapter)
        || !Number.isInteger(endChapter)
        || startChapter < 1
        || endChapter < 1
      ) {
        toast("章节范围必须是大于等于 1 的整数", "warning")
        return false
      }
      if (startChapter > endChapter) {
        toast("结束章节不能小于起始章节", "warning")
        return false
      }
      chapterRange = { startChapter, endChapter }
    }
    const submission = beginMaintenanceSubmission()
    if (!submission) {
      toast("索引维护任务正在处理", "info")
      return false
    }
    try {
      toast("正在重建索引...", "info")
      const payload = { novel_id: projectId }
      if (form?.contentMode) payload.content_mode = form.contentMode
      if (chapterRange) {
        payload.start_chapter = chapterRange.startChapter
        payload.end_chapter = chapterRange.endChapter
      }
      const result = await getApi().rag.rebuild(payload)
      getApi().clearCache()
      if (result.task_id) {
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "rag_reindex_novel",
          projectId,
          view: "rag",
          meta: { start_chapter: payload.start_chapter, end_chapter: payload.end_chapter },
        })
        if (!ownsProject(projectId)) return true
        ragSearchSession.rebuildInfo = null
        ragSearchSession.rebuildProgress = normalizeTaskProgress({
          ...result,
          task_type: "rag_reindex_novel",
        }, "rag_reindex_novel")
        startRebuildPolling(result.task_id, "rag_reindex_novel", projectId)
        toast("索引重建任务已提交", "success")
      } else if (!ownsProject(projectId)) {
        return true
      } else if (result.total > 0 || (result.task_ids || []).length > 0) {
        ragSearchSession.rebuildInfo = "索引重建请求已处理。"
        ragSearchSession.rebuildProgress = null
        toast("索引重建任务已提交", "success")
      } else {
        ragSearchSession.rebuildProgress = null
        ragSearchSession.rebuildInfo = "暂无可索引工作稿"
        toast("暂无可索引工作稿", "info")
      }
      for (const warning of (result.warnings || [])) {
        toast(warning, "warning")
      }
      return true
    } catch (err) {
      if (ownsProject(projectId)) {
        toast(err.message || "重建失败", "error")
      }
      return false
    } finally {
      endMaintenanceSubmission(submission)
    }
  }

  /** 重试失败向量（对应 _retryEmbeddings）。 */
  async function retryEmbeddings() {
    const toast = getToast()
    const state = getAppState()
    if (disposed) return false
    if (!state?.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    if (!statusFields.retryableEmbeddingCount) {
      toast("暂无可重试的失败向量", "info")
      return
    }
    const projectId = state.currentProjectId
    const submission = beginMaintenanceSubmission()
    if (!submission) {
      toast("索引维护任务正在处理", "info")
      return false
    }
    try {
      const result = await getApi().rag.retryEmbeddings({
        novel_id: projectId,
        statuses: ["failed", "pending_vectorization"],
      })
      getApi().clearCache()
      if (result.task_id) {
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "rag_retry_embeddings",
          projectId,
          view: "rag",
        })
        if (!ownsProject(projectId)) return true
        ragSearchSession.rebuildInfo = null
        ragSearchSession.rebuildProgress = normalizeTaskProgress({
          ...result,
          task_type: "rag_retry_embeddings",
        }, "rag_retry_embeddings")
        startRebuildPolling(result.task_id, "rag_retry_embeddings", projectId)
        toast("失败向量重试任务已提交", "success")
      }
      return true
    } catch (err) {
      if (ownsProject(projectId)) {
        toast(err.message || "重试失败", "error")
      }
      return false
    } finally {
      endMaintenanceSubmission(submission)
    }
  }

  /** 重试失败任务（对应 _retryFailedTask）。 */
  async function retryFailedTask() {
    if (disposed) return false
    const toast = getToast()
    const progress = ragSearchSession.rebuildProgress
    const taskId = progress?.taskId
    const state = getAppState()
    if (
      !taskId
      || !state?.currentProjectId
      || ragSearchSession.taskRetryPending
      || !progress.availableActions?.includes("retry")
    ) return false
    const projectId = state.currentProjectId
    const ownsRetryScope = () => (
      ownsProject(projectId)
      && ragSearchSession.rebuildProgress?.taskId === taskId
    )
    ragSearchSession.taskRetryPending = true
    try {
      const result = await getApi().tasks.retry(taskId, projectId)
      if (!ownsRetryScope()) return true
      const workflowType = progress.workflowType || progress.taskType || "rag_reindex_novel"
      ragSearchSession.rebuildProgress = normalizeTaskProgress({
        ...progress.raw,
        ...result,
        task_id: taskId,
        task_type: workflowType,
        status: result.status || "pending",
        error_message: null,
        result: {
          ...(progress.raw?.result || {}),
          error: null,
          error_message: null,
        },
        available_actions: ["cancel"],
      }, workflowType)
      startRebuildPolling(taskId, workflowType, projectId)
      toast("任务已重新加入队列", "success")
      return true
    } catch (err) {
      if (ownsRetryScope()) {
        toast(err.message || "重试任务失败", "error")
      }
      return false
    } finally {
      if (ragSearchSession.rebuildProgress?.taskId === taskId) {
        ragSearchSession.taskRetryPending = false
      }
    }
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true
      maintenanceSubmissionGeneration += 1
      maintenanceSubmitting.value = false
      polling.stopAll()
    })
  }

  return {
    maintenanceBusy,
    maintenanceSubmitting,
    rebuildIndex,
    retryEmbeddings,
    retryFailedTask,
    recoverRebuildWorkflow,
    startRebuildPolling,
  }
}

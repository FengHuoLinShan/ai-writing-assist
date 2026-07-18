/**
 * RAG 索引工作流 composable — 对应 vanilla ragView 的 _rebuildIndex /
 * _retryEmbeddings / _retryFailedTask / _recoverRebuildWorkflow / _prewarm
 * 与轮询管理（_startRebuildPolling/_stopRebuildPolling）。
 * 进度写入 ragSearchSession（跨 island 重挂载存活）；scope 销毁时停止轮询并
 * abort 在途请求（对应 vanilla onLeave 清理）。
 */
import { getCurrentScope, onScopeDispose } from "vue"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../../../shared/workflowProgress.js"
import { useWorkflowPolling } from "../../composables/useWorkflowPolling.js"
import { getApi, getAppState, getToast } from "../../bridge/index.js"
import { ragSearchSession } from "./ragSearchSession.js"

export function useRagWorkflow({ refreshStatus } = {}) {
  const polling = useWorkflowPolling()
  let abortController = new AbortController()
  let pollerStarted = false

  function ensureAbortController() {
    if (!abortController) abortController = new AbortController()
    return abortController
  }

  /** onUpdate → session.rebuildProgress；onDone/onFailed → 状态落账（对应 _handleRebuildDone）。 */
  function startRebuildPolling(taskId, workflowType = "rag_reindex_novel") {
    pollerStarted = true
    polling.start({
      taskId,
      workflowType,
      onUpdate: (progress) => {
        ragSearchSession.rebuildProgress = progress
        ragSearchSession.rebuildInfo = null
      },
      onDone: (progress, task) => {
        const result = task?.result || progress.raw?.result || {}
        void handleRebuildDone(taskId, workflowType, result)
      },
      onFailed: () => {
        // 失败/取消状态保留在 rebuildProgress 中展示（vanilla 仅刷新 DOM）
      },
    })
  }

  async function applyRagRebuildResult(result = {}) {
    const state = getAppState()
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
    void state
  }

  async function handleRebuildDone(taskId, workflowType, result = {}) {
    if (workflowType === "rag_retry_embeddings") {
      const remaining = result.remaining_retryable_count ?? result.failed ?? 0
      statusFields.retryableEmbeddingCount = remaining
      statusFields.embeddingFailedCount = remaining
      await refreshStatus?.()
    } else {
      await applyRagRebuildResult(result)
    }
    clearActiveWorkflow(taskId)
  }

  /** 由 RagView 持有的状态字段容器（reactive），在 setup 时注入。 */
  const statusFields = {
    totalChunks: null,
    embeddingFailedCount: 0,
    retryableEmbeddingCount: 0,
    statusWarnings: [],
    statusDegraded: false,
  }

  /** 恢复跨刷新的活动工作流（对应 _recoverRebuildWorkflow）。 */
  function recoverRebuildWorkflow() {
    const state = getAppState()
    if (!state?.currentProjectId || pollerStarted) return
    const workflows = recoverActiveWorkflows(state.currentProjectId)
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
    startRebuildPolling(workflow.taskId, workflowType)
  }

  /** 重建索引（对应 _rebuildIndex；form = {contentMode, start, end}）。 */
  async function rebuildIndex(form) {
    const toast = getToast()
    const state = getAppState()
    if (!state?.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      toast("正在重建索引...", "info")
      const payload = { novel_id: state.currentProjectId }
      if (form?.contentMode) payload.content_mode = form.contentMode
      const startChapter = Number(form?.start)
      const endChapter = Number(form?.end)
      if (!Number.isNaN(startChapter) && !Number.isNaN(endChapter) && startChapter >= 1 && endChapter >= 1 && startChapter <= endChapter) {
        payload.start_chapter = startChapter
        payload.end_chapter = endChapter
      }
      const result = await getApi().rag.rebuild(payload, { signal: ensureAbortController().signal })
      getApi().clearCache()
      if (result.task_id) {
        ragSearchSession.rebuildInfo = null
        ragSearchSession.rebuildProgress = normalizeTaskProgress({
          ...result,
          task_type: "rag_reindex_novel",
        }, "rag_reindex_novel")
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "rag_reindex_novel",
          projectId: state.currentProjectId,
          view: "rag",
          meta: { start_chapter: payload.start_chapter, end_chapter: payload.end_chapter },
        })
        startRebuildPolling(result.task_id)
        toast("索引重建任务已提交", "success")
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
    } catch (err) {
      toast(err.message || "重建失败", "error")
    }
  }

  /** 重试失败向量（对应 _retryEmbeddings）。 */
  async function retryEmbeddings() {
    const toast = getToast()
    const state = getAppState()
    if (!state?.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    if (!statusFields.retryableEmbeddingCount) {
      toast("暂无可重试的失败向量", "info")
      return
    }
    try {
      const result = await getApi().rag.retryEmbeddings({
        novel_id: state.currentProjectId,
        statuses: ["failed", "pending_vectorization"],
      }, { signal: ensureAbortController().signal })
      getApi().clearCache()
      if (result.task_id) {
        ragSearchSession.rebuildInfo = null
        ragSearchSession.rebuildProgress = normalizeTaskProgress({
          ...result,
          task_type: "rag_retry_embeddings",
        }, "rag_retry_embeddings")
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "rag_retry_embeddings",
          projectId: state.currentProjectId,
          view: "rag",
        })
        startRebuildPolling(result.task_id, "rag_retry_embeddings")
        toast("失败向量重试任务已提交", "success")
      }
    } catch (err) {
      toast(err.message || "重试失败", "error")
    }
  }

  /** 重试失败任务（对应 _retryFailedTask）。 */
  async function retryFailedTask() {
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
    ragSearchSession.taskRetryPending = true
    try {
      const result = await getApi().tasks.retry(taskId, state.currentProjectId)
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
      ragSearchSession.taskRetryPending = false
      startRebuildPolling(taskId, workflowType)
      toast("任务已重新加入队列", "success")
      return true
    } catch (err) {
      ragSearchSession.taskRetryPending = false
      toast(err.message || "重试任务失败", "error")
      return false
    }
  }

  /** 预热检索引擎（对应 _prewarm；background 模式由调用方决定是否触发 UI 刷新）。 */
  async function prewarm() {
    const session = ragSearchSession
    session.prewarmState = "running"
    session.prewarmWarning = ""
    try {
      const result = await getApi().rag.prewarm({ signal: ensureAbortController().signal })
      session.prewarmState = result.status === "ready" ? "ready" : "failed"
      session.prewarmWarning = result.warning || ""
      return result
    } catch (err) {
      session.prewarmState = "failed"
      session.prewarmWarning = err.message || "预热失败"
      return null
    }
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      polling.stopAll()
      if (abortController) {
        abortController.abort()
        abortController = null
      }
    })
  }

  return {
    statusFields,
    rebuildIndex,
    retryEmbeddings,
    retryFailedTask,
    recoverRebuildWorkflow,
    startRebuildPolling,
    prewarm,
  }
}

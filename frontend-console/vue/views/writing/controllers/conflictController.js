import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import {
  clearActiveWorkflow,
  createOperationId,
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"

const ABORTED = Symbol("conflict-controller-aborted")

export function createConflictController({ api, toast, getProjectId, getCheck, onCheck, onProgress = () => {} }) {
  const receiptStorage = globalThis.sessionStorage
  let generation = 0
  let disposed = false
  let timer = null

  function guard(token, projectId) {
    if (disposed || token !== generation || getProjectId() !== projectId) throw ABORTED
  }

  function wait(token, projectId, delay = 1000) {
    return new Promise((resolve, reject) => {
      timer = setTimeout(() => {
        timer = null
        try { guard(token, projectId); resolve() } catch (err) { reject(err) }
      }, delay)
    })
  }

  function replaceItem(updated) {
    const check = getCheck()
    if (!check || !updated?.id) return check
    const next = { ...check, items: (check.items || []).map((item) => item.id === updated.id ? { ...item, ...updated } : item) }
    onCheck(next)
    return next
  }

  function activeWorkflow(projectId = getProjectId()) {
    return recoverActiveWorkflows(projectId, receiptStorage)
      .filter((item) => item.view === "writing" && ["writing_conflict_ai_review", "writing_conflict_item_ai_suggestion"].includes(item.workflowType))
      .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0] || null
  }

  async function updateStatus(itemId, status) {
    const projectId = getProjectId()
    try {
      const updated = await api.writing.updateConflictItem(itemId, projectId, { status })
      if (getProjectId() !== projectId || disposed) return null
      replaceItem({ id: itemId, ...updated, status: updated?.status || status })
      toast("问题状态已更新", "success")
      return updated
    } catch (err) { toast(err?.message || "状态更新失败", "error"); return null }
  }

  async function waitForTask(taskId, projectId, token, workflowType) {
    while (true) {
      let task
      try { task = await api.tasks.get(taskId, projectId) } catch (err) {
        if (Number(err?.status) === 404) {
          clearActiveWorkflow(taskId, receiptStorage)
          onProgress({ taskId, progress: normalizeTaskProgress({ id: taskId, task_type: workflowType, status: "failed", error_message: "未找到原任务，请重新开始。" }, workflowType) })
          throw Object.assign(new Error("未找到原任务，请重新开始。"), { workflowProgressVisible: true })
        }
        await wait(token, projectId); continue
      }
      guard(token, projectId)
      onProgress({ taskId, progress: normalizeTaskProgress(task, workflowType) })
      if (task?.status === "done") { clearActiveWorkflow(taskId, receiptStorage); return task }
      if (task?.status === "failed" || task?.status === "cancelled") {
        clearActiveWorkflow(taskId, receiptStorage)
        throw Object.assign(new Error(task.error_message || "AI 任务失败"), { workflowProgressVisible: true })
      }
      await wait(token, projectId)
    }
  }

  function persistConflictTask(taskId, workflowType, meta) {
    persistActiveWorkflow({ taskId, workflowType, label: workflowType === "writing_conflict_ai_review" ? "AI 软冲突判断" : "AI 修复建议", projectId: getProjectId(), view: "writing", meta }, receiptStorage)
    onProgress({ taskId, progress: normalizeTaskProgress({ id: taskId, task_type: workflowType, status: "pending" }, workflowType) })
  }

  async function submitTask({ workflowType, meta, submit, token, projectId }) {
    const operationId = createOperationId()
    persistConflictTask(operationId, workflowType, meta)
    let started
    try { started = await submit(operationId) } catch (err) {
      if (Number(err?.status) >= 400 && Number(err?.status) < 500) { clearActiveWorkflow(operationId, receiptStorage); onProgress({ taskId: null, progress: null }); throw err }
      started = { task_id: operationId, status: "pending" }
    }
    guard(token, projectId)
    const taskId = started?.task_id || operationId
    if (taskId !== operationId) { clearActiveWorkflow(operationId, receiptStorage); persistConflictTask(taskId, workflowType, meta) }
    return { started, task: await waitForTask(taskId, projectId, token, workflowType) }
  }

  async function runAiReview() {
    const check = getCheck(); const projectId = getProjectId()
    if (!check?.id || !projectId) return null
    if (activeWorkflow(projectId)) { toast("已有 AI 冲突任务正在进行", "info"); return null }
    const token = ++generation
    try {
      const confirmation = await confirmAiReference({ novel_id: projectId, action: "writing.conflict_check.ai_review", task: "writing conflict AI review", scope: "chapter", chapter_index: check.chapter_index, scene_id: check.scene_id, context_mode: "canonical", include_pending_objects: Boolean(check.include_candidates), budget_tokens: 0 })
      guard(token, projectId)
      const { started, task } = await submitTask({ workflowType: "writing_conflict_ai_review", meta: { checkId: check.id, kind: "review" }, token, projectId, submit: (operationId) => api.writing.enqueueConflictAiReview(check.id, { novel_id: projectId, context_confirmation_id: confirmation.id, operation_id: operationId }) })
      onCheck(started?.check || { ...check, ai_review_status: "running", ai_review_confirmation_id: confirmation.id })
      const updated = await api.writing.getConflictCheck(task.result?.check_id || check.id, projectId)
      guard(token, projectId); onCheck(updated); return updated
    } catch (err) { if (err === ABORTED || disposed || token !== generation || err?.message === "已取消 AI 参考资料确认") return null; if (!err?.workflowProgressVisible) toast(err?.message || "AI 软冲突判断失败", "error"); return null }
  }

  async function requestSuggestion(itemId) {
    const check = getCheck(); const projectId = getProjectId()
    if (!check?.id || !itemId || !projectId) return null
    if (activeWorkflow(projectId)) { toast("已有 AI 冲突任务正在进行", "info"); return null }
    const token = ++generation
    try {
      const confirmation = await confirmAiReference({ novel_id: projectId, action: "writing.conflict_check.ai_suggestion", task: "writing conflict AI suggestion", scope: "chapter", chapter_index: check.chapter_index, scene_id: check.scene_id, context_mode: "canonical", include_pending_objects: Boolean(check.include_candidates), budget_tokens: 0 })
      guard(token, projectId)
      const { task } = await submitTask({ workflowType: "writing_conflict_item_ai_suggestion", meta: { checkId: check.id, itemId, kind: "suggestion" }, token, projectId, submit: (operationId) => api.writing.enqueueConflictAiSuggestion(itemId, { novel_id: projectId, context_confirmation_id: confirmation.id, operation_id: operationId }) })
      const updated = task?.result || await api.writing.getConflictCheck(check.id, projectId).then((value) => value.items?.find((item) => item.id === itemId))
      guard(token, projectId); replaceItem({ id: itemId, ...updated }); return updated
    } catch (err) { if (err === ABORTED || disposed || token !== generation || err?.message === "已取消 AI 参考资料确认") return null; if (!err?.workflowProgressVisible) toast(err?.message || "AI 建议生成失败", "error"); return null }
  }

  async function recover() {
    const projectId = getProjectId(); const workflow = activeWorkflow(projectId)
    if (!workflow) return false
    const token = ++generation
    try { const task = await waitForTask(workflow.taskId, projectId, token, workflow.workflowType); guard(token, projectId); const check = await api.writing.getConflictCheck(workflow.meta?.checkId, projectId); guard(token, projectId); onCheck(check); return task } catch (err) { if (err !== ABORTED && !disposed && token === generation && !err?.workflowProgressVisible) toast(err?.message || "AI 冲突任务恢复失败", "error"); return false }
  }
  async function cancel() { const workflow = activeWorkflow(); if (!workflow) return false; try { await api.tasks.cancel(workflow.taskId, getProjectId()) } catch (err) { toast(err?.message || "取消任务失败", "error"); return false } return true }
  function dismiss() { const workflow = activeWorkflow(); if (workflow) clearActiveWorkflow(workflow.taskId, receiptStorage); onProgress({ taskId: null, progress: null }) }
  function dispose() { disposed = true; generation += 1; if (timer) clearTimeout(timer); timer = null }

  return { updateStatus, runAiReview, requestSuggestion, recover, cancel, dismiss, dispose }
}

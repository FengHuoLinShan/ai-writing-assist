import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"

const ABORTED = Symbol("conflict-controller-aborted")

export function createConflictController({ api, toast, getProjectId, getCheck, onCheck }) {
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
    const next = {
      ...check,
      items: (check.items || []).map((item) => item.id === updated.id ? { ...item, ...updated } : item),
    }
    onCheck(next)
    return next
  }

  async function updateStatus(itemId, status) {
    const projectId = getProjectId()
    try {
      const updated = await api.writing.updateConflictItem(itemId, projectId, { status })
      if (getProjectId() !== projectId || disposed) return null
      replaceItem({ id: itemId, ...updated, status: updated?.status || status })
      toast("问题状态已更新", "success")
      return updated
    } catch (err) {
      toast(err?.message || "状态更新失败", "error")
      return null
    }
  }

  async function waitForReview(taskId, check, projectId, token) {
    if (!taskId) return { ...check, ai_review_status: "running" }
    for (let attempt = 0; attempt < 90; attempt += 1) {
      const task = await api.tasks.get(taskId, projectId)
      guard(token, projectId)
      if (task?.status === "done") {
        const updated = await api.writing.getConflictCheck(task.result?.check_id || check.id, projectId)
        guard(token, projectId)
        return updated
      }
      if (task?.status === "failed" || task?.status === "cancelled") {
        throw new Error(task.error_message || task.result?.error_message || "AI 软冲突判断失败")
      }
      await wait(token, projectId)
    }
    return { ...check, ai_review_status: "running" }
  }

  async function runAiReview() {
    const check = getCheck()
    const projectId = getProjectId()
    if (!check?.id || !projectId) return null
    const token = ++generation
    try {
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "writing.conflict_check.ai_review",
        task: "writing conflict AI review",
        scope: "chapter",
        chapter_index: check.chapter_index,
        scene_id: check.scene_id,
        context_mode: "canonical",
        include_pending_objects: Boolean(check.include_candidates),
        budget_tokens: 0,
      })
      guard(token, projectId)
      const payload = { novel_id: projectId, context_confirmation_id: confirmation.id }
      let updated
      if (typeof api.writing.enqueueConflictAiReview === "function") {
        const started = await api.writing.enqueueConflictAiReview(check.id, payload)
        guard(token, projectId)
        onCheck(started?.check || { ...check, ai_review_status: "running", ai_review_confirmation_id: confirmation.id })
        updated = await waitForReview(started?.task_id, check, projectId, token)
      } else {
        updated = await api.writing.runConflictAiReview(check.id, payload)
      }
      guard(token, projectId)
      onCheck(updated)
      if (updated?.ai_review_status === "running") {
        toast("AI 软冲突判断仍在后台运行，可稍后重新打开检查记录", "warning")
      } else if (updated?.ai_review_status === "partial") {
        toast("AI 软冲突判断部分生成", "warning")
      } else {
        toast("AI 软冲突判断已生成", "success")
      }
      return updated
    } catch (err) {
      if (err === ABORTED || disposed || token !== generation || err?.message === "已取消 AI 参考资料确认") return null
      toast(err?.message || "AI 软冲突判断失败", "error")
      return null
    }
  }

  async function requestSuggestion(itemId) {
    const check = getCheck()
    const projectId = getProjectId()
    if (!check?.id || !itemId || !projectId) return null
    const token = ++generation
    try {
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "writing.conflict_check.ai_suggestion",
        task: "writing conflict AI suggestion",
        scope: "chapter",
        chapter_index: check.chapter_index,
        scene_id: check.scene_id,
        context_mode: "canonical",
        include_pending_objects: Boolean(check.include_candidates),
        budget_tokens: 0,
      })
      guard(token, projectId)
      const updated = await api.writing.requestConflictAiSuggestion(itemId, {
        novel_id: projectId,
        context_confirmation_id: confirmation.id,
      })
      guard(token, projectId)
      replaceItem({ id: itemId, ...updated })
      toast(updated?.suggestion_status === "failed" ? (updated.suggestion_error || "AI 建议生成失败") : "AI 修复建议已生成", updated?.suggestion_status === "failed" ? "error" : "success")
      return updated
    } catch (err) {
      if (err === ABORTED || disposed || token !== generation || err?.message === "已取消 AI 参考资料确认") return null
      toast(err?.message || "AI 建议生成失败", "error")
      return null
    }
  }

  function dispose() {
    disposed = true
    generation += 1
    if (timer) clearTimeout(timer)
    timer = null
  }

  return { updateStatus, runAiReview, requestSuggestion, dispose }
}

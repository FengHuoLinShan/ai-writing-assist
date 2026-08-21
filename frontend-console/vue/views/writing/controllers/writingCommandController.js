import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import {
  clearActiveWorkflow,
  createOperationId,
  normalizeTaskProgress,
  persistActiveWorkflow,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"

const ABORTED = Symbol("writing-command-aborted")
const MANAGED_WRITING_TYPES = new Set([
  "writing_generate",
  "writing_semantic_review",
  "writing_targeted_revision",
])

export function createWritingCommandController({
  api,
  toast,
  getProjectId,
  getChapter,
  getScene = () => null,
  editor,
  onResult,
  onLoadingChange = () => {},
  onProgress = () => {},
}) {
  const receiptStorage = globalThis.sessionStorage
  let generation = 0
  let generating = false
  let disposed = false
  let waitTimer = null
  let readyResult = null
  let pendingStaleStoryScript = null

  function staleStoryScriptError(error) {
    const values = [
      error?.code,
      error?.error,
      error?.error_code,
      error?.detail?.code,
      error?.detail?.error,
      error?.detail?.error_code,
      error?.response?.data?.code,
      error?.response?.data?.error,
      error?.response?.data?.error_code,
      error?.body?.code,
      error?.body?.error,
      error?.body?.error_code,
      error?.body?.detail?.code,
      error?.body?.detail?.error,
      error?.body?.detail?.error_code,
    ].map((value) => String(value || "").toLowerCase())
    const text = [error?.message, error?.detail, error?.detail?.message, error?.response?.data?.message, error?.response?.data?.detail, error?.body?.message, error?.body?.detail]
      .map((value) => String(value || "").toLowerCase())
      .join(" ")
    const stableCode = values.some((value) => ["stale_story_assets", "stale_story_script"].includes(value))
    const workerMessage = (text.includes("stale") && (text.includes("script") || text.includes("asset")))
      || (text.includes("剧本") && (text.includes("过期") || text.includes("变化")))
    const status = Number(error?.status ?? error?.response?.status ?? error?.detail?.status)
    return stableCode || (status === 409 && workerMessage)
  }

  function reportStaleStoryScript(mode, error) {
    pendingStaleStoryScript = { mode }
    onProgress({
      taskId: null,
      progress: null,
      result: null,
      staleStoryScript: {
        message: "采用的场景剧本已经过期。请确认是否仍要使用这个旧剧本继续生成。",
        detail: error?.message || "场景剧本已变化",
      },
    })
  }

  function context() {
    const chapter = getChapter()
    return {
      projectId: getProjectId(),
      chapter,
      scene: getScene(),
    }
  }

  function wait(delay, token) {
    return new Promise((resolve, reject) => {
      waitTimer = setTimeout(() => {
        waitTimer = null
        if (disposed || token !== generation) reject(ABORTED)
        else resolve()
      }, delay)
    })
  }

  async function waitForDraft(submitted, projectId, token) {
    if (submitted?.draft_id) return submitted
    if (!submitted?.task_id) throw new Error("正文建议未能开始，请稍后重试")
    while (!disposed && token === generation) {
      let task = null
      try {
        task = await api.tasks.get(submitted.task_id, projectId)
      } catch (err) {
        if (Number(err?.status) === 404) {
          clearActiveWorkflow(submitted.task_id, receiptStorage)
          onProgress({ taskId: submitted.task_id, progress: normalizeTaskProgress({ id: submitted.task_id, task_type: "writing_generate", status: "failed", error_message: "未找到原任务，请重新开始。" }, "writing_generate") })
          throw Object.assign(new Error("未找到原任务，请重新开始。"), { workflowProgressVisible: true })
        }
        await wait(1500, token)
        continue
      }
      if (disposed || token !== generation || getProjectId() !== projectId) throw ABORTED
      onProgress({ taskId: submitted.task_id, progress: normalizeTaskProgress(task, "writing_generate") })
      if (task?.status === "done") {
        const draftId = task.result?.draft_id
        if (!draftId) throw new Error("任务已完成，但未返回正文建议 ID")
        return { ...submitted, ...task.result }
      }
      if (task?.status === "failed" || task?.status === "cancelled") {
        clearActiveWorkflow(submitted.task_id, receiptStorage)
        throw Object.assign(
          new Error(task.error_message || task.result?.error_message || (task.status === "cancelled" ? "正文生成已取消" : "正文生成失败")),
          { workflowProgressVisible: true },
        )
      }
      await wait(1500, token)
    }
    throw ABORTED
  }

  async function waitForManagedTask(submitted, projectId, token, workflowType) {
    if (!submitted?.task_id) throw new Error("任务未能开始，请稍后重试")
    while (!disposed && token === generation) {
      let task
      try {
        task = await api.tasks.get(submitted.task_id, projectId)
      } catch (err) {
        if (Number(err?.status) === 404) {
          clearActiveWorkflow(submitted.task_id, receiptStorage)
          onProgress({ taskId: submitted.task_id, progress: normalizeTaskProgress({ id: submitted.task_id, task_type: workflowType, status: "failed", error_message: "未找到原任务，请重新开始。" }, workflowType) })
          throw Object.assign(new Error("未找到原任务，请重新开始。"), { workflowProgressVisible: true })
        }
        await wait(1500, token)
        continue
      }
      if (disposed || token !== generation || getProjectId() !== projectId) throw ABORTED
      onProgress({ taskId: submitted.task_id, progress: normalizeTaskProgress(task, workflowType), result: task?.result || null })
      if (task?.status === "done") return task
      if (["failed", "cancelled"].includes(task?.status)) {
        clearActiveWorkflow(submitted.task_id, receiptStorage)
        throw Object.assign(new Error(task.error_message || (
          task.status === "cancelled" ? "任务已取消" : "任务执行失败"
        )), { workflowProgressVisible: true })
      }
      await wait(1500, token)
    }
    throw ABORTED
  }

  async function runCandidateWorkflow(workflowType) {
    const projectId = getProjectId()
    const draftId = editor.getDraftId()
    const provenance = editor.getProvenance?.() || {}
    if (!projectId || !draftId || editor.getStatus?.() !== "candidate") {
      toast("请先打开一份待处理正文建议", "warning")
      return null
    }
    if (generating) {
      toast("已有正文任务在运行", "warning")
      return null
    }
    const review = provenance.independent_review
    if (workflowType === "writing_targeted_revision" && (
      !review?.review_task_id || !review?.finding_ids?.length
    )) {
      toast("当前没有可定向返修的审查问题", "warning")
      return null
    }
    generating = true
    onLoadingChange(true)
    const token = ++generation
    const operationId = createOperationId()
    const chapter = getChapter()
    const label = workflowType === "writing_semantic_review" ? "独立语义审查" : "定向返修"
    const meta = { chapter, draftId }
    persistActiveWorkflow({ taskId: operationId, workflowType, label, projectId, view: "writing", meta }, receiptStorage)
    onProgress({ taskId: operationId, progress: normalizeTaskProgress({ id: operationId, task_type: workflowType, status: "pending" }, workflowType), result: null })
    try {
      const payload = workflowType === "writing_semantic_review"
        ? { novel_id: projectId, draft_ids: [draftId], scope: "selection", operation_id: operationId }
        : { novel_id: projectId, draft_id: draftId, review_task_id: review.review_task_id, finding_ids: review.finding_ids, operation_id: operationId }
      const submitted = workflowType === "writing_semantic_review"
        ? await api.writing.semanticReview(payload)
        : await api.writing.targetedRevision(payload)
      if (disposed || token !== generation) return null
      if (submitted.task_id !== operationId) {
        clearActiveWorkflow(operationId, receiptStorage)
        persistActiveWorkflow({ taskId: submitted.task_id, workflowType, label, projectId, view: "writing", meta }, receiptStorage)
      }
      const task = await waitForManagedTask(submitted, projectId, token, workflowType)
      clearActiveWorkflow(submitted.task_id, receiptStorage)
      if (workflowType === "writing_targeted_revision") {
        readyResult = { chapter_index: chapter, draft_id: task.result?.draft_id }
        await openResult()
      } else {
        readyResult = { chapter_index: chapter, draft_id: draftId }
        await openResult()
      }
      onProgress({ taskId: submitted.task_id, progress: normalizeTaskProgress(task, workflowType), result: task.result || null })
      return task
    } catch (err) {
      if (err !== ABORTED && !disposed && token === generation && !err?.workflowProgressVisible) {
        toast(err?.message || `${label}失败`, "error")
      }
      return null
    } finally {
      if (token === generation) {
        generating = false
        onLoadingChange(false)
      }
    }
  }

  async function generate(mode = "draft", { confirmStaleStoryAssets = false } = {}) {
    const { projectId, chapter, scene } = context()
    if (!projectId || !chapter) {
      toast("请先选择章节", "warning")
      return null
    }
    if (generating) {
      toast("正文建议正在生成，请稍候", "warning")
      return null
    }
    const pendingResult = recoverActiveWorkflows(projectId, receiptStorage).find((item) => item.workflowType === "writing_generate" && item.view === "writing")
    if (pendingResult) { toast("已有正文建议待处理，请先在进度卡中查看或关闭", "info"); return null }
    if (editor.isReadonly()) {
      toast("当前内容只读；待处理建议不会作为工作稿参考", "warning")
      return null
    }
    if (mode === "continue" && !editor.getContent().trim()) {
      toast("当前正文为空，请先写入并暂存正文，再续写", "warning")
      return null
    }
    if (mode === "continue" && (!editor.getDraftId() || editor.getContent() !== editor.getLoadedContent())) {
      toast("正文有未保存修改，请先暂存后再续写", "warning")
      return null
    }
    if (mode === "pov" && !scene?.pov_character_id) {
      toast(scene ? "当前场景还没有设置视角人物" : "当前章节还没有关联场景", "warning")
      return null
    }
    generating = true
    readyResult = null
    pendingStaleStoryScript = null
    onProgress({ staleStoryScript: null })
    onLoadingChange(true)
    const token = ++generation
    try {
      const pov = mode === "pov"
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "writing.generate",
        task: pov ? "基于当前场景的视角人物认知生成正文建议" : mode === "continue" ? "从当前正式正文末尾续写" : "生成正文建议预览",
        scope: "chapter",
        chapter_index: chapter,
        scene_id: scene?.id,
        reveal_mode: pov ? "character" : undefined,
        viewpoint_character_id: pov ? scene.pov_character_id : undefined,
        character_ids: pov ? [scene.pov_character_id] : undefined,
        include_pending_objects: false,
      })
      if (disposed || token !== generation) return null
      const instruction = pov
        ? `${confirmation.user_note ? `${confirmation.user_note}\n\n` : ""}请严格使用视角人物在当前场景可见的信息生成正文建议。`
        : (confirmation.user_note || "")
      const operationId = createOperationId()
      const workflowMeta = {
        chapter,
        mode,
        sceneId: scene?.id || null,
        ...(confirmStaleStoryAssets ? { confirm_stale_story_assets: true } : {}),
      }
      const editorBaseline = { chapter, sceneId: scene?.id || null, draftId: editor.getDraftId(), content: editor.getContent() }
      persistActiveWorkflow({ taskId: operationId, workflowType: "writing_generate", label: pov ? "AI 角色视角建议" : mode === "continue" ? "AI 续写" : "AI 正文建议", projectId, view: "writing", meta: workflowMeta }, receiptStorage)
      onProgress({ taskId: operationId, progress: normalizeTaskProgress({ id: operationId, task_type: "writing_generate", status: "pending" }, "writing_generate") })
      let submitted
      try { submitted = await api.writing.generate({ novel_id: projectId, chapter_index: chapter, title: editor.getTitle() || `第 ${chapter} 章`, instruction, context_confirmation_id: confirmation.id, generation_mode: mode === "continue" ? "continue" : undefined, base_draft_id: mode === "continue" ? editor.getDraftId() : undefined, operation_id: operationId, ...(confirmStaleStoryAssets ? { confirm_stale_story_assets: true } : {}) }) } catch (err) {
        if (staleStoryScriptError(err)) {
          clearActiveWorkflow(operationId, receiptStorage)
          reportStaleStoryScript(mode, err)
          return null
        }
        if (Number(err?.status) >= 400 && Number(err?.status) < 500) { clearActiveWorkflow(operationId, receiptStorage); onProgress({ taskId: null, progress: null, result: null }); throw err }
        submitted = { task_id: operationId, status: "pending" }
      }
      if (disposed || token !== generation) return null
      if (submitted?.task_id && submitted.task_id !== operationId) {
        clearActiveWorkflow(operationId, receiptStorage)
        persistActiveWorkflow({ taskId: submitted.task_id, workflowType: "writing_generate", label: pov ? "AI 角色视角建议" : mode === "continue" ? "AI 续写" : "AI 正文建议", projectId, view: "writing", meta: workflowMeta }, receiptStorage)
      }
      const completed = await waitForDraft(submitted, projectId, token)
      if (disposed || token !== generation) return null
      readyResult = { chapter_index: chapter, draft_id: completed.draft_id }
      onProgress({
        taskId: submitted.task_id || operationId,
        progress: normalizeTaskProgress({
          id: submitted.task_id || operationId,
          task_type: "writing_generate",
          status: "done",
        }, "writing_generate"),
        result: readyResult,
      })
      const editorUnchanged = getChapter() === editorBaseline.chapter
        && (getScene()?.id || null) === editorBaseline.sceneId
        && editor.getDraftId() === editorBaseline.draftId
        && editor.getContent() === editorBaseline.content
      if (editorUnchanged) { await openResult(); toast("正文建议已生成，已打开待审阅版本", "success") } else toast("正文建议已生成，已保留当前编辑内容", "success")
      return completed
    } catch (err) {
      if (err === ABORTED || disposed || token !== generation) return null
      if (staleStoryScriptError(err)) {
        const active = recoverActiveWorkflows(projectId, receiptStorage)
          .find((item) => item.workflowType === "writing_generate" && item.view === "writing")
        if (active) clearActiveWorkflow(active.taskId, receiptStorage)
        reportStaleStoryScript(mode, err)
        return null
      }
      if (String(err?.message || "").includes("取消")) return null
      if (!err?.workflowProgressVisible) toast(err?.message || "正文建议生成失败", "error")
      return null
    } finally {
      if (token === generation) {
        generating = false
        onLoadingChange(false)
      }
    }
  }

  function retryUsingStaleStoryScript() {
    if (!pendingStaleStoryScript || generating) return null
    const { mode } = pendingStaleStoryScript
    pendingStaleStoryScript = null
    return generate(mode, { confirmStaleStoryAssets: true })
  }

  async function recover() {
    const projectId = getProjectId()
    const workflow = recoverActiveWorkflows(projectId, receiptStorage).filter((item) => MANAGED_WRITING_TYPES.has(item.workflowType) && item.view === "writing").sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0]
    if (!workflow || generating) return false
    generating = true; onLoadingChange(true); const token = ++generation
    try {
      if (workflow.workflowType === "writing_generate") {
        const completed = await waitForDraft({ task_id: workflow.taskId }, projectId, token)
        readyResult = { chapter_index: workflow.meta?.chapter, draft_id: completed.draft_id }
        onProgress({ taskId: workflow.taskId, progress: normalizeTaskProgress({ id: workflow.taskId, task_type: "writing_generate", status: "done" }, "writing_generate"), result: readyResult })
      } else {
        const task = await waitForManagedTask({ task_id: workflow.taskId }, projectId, token, workflow.workflowType)
        readyResult = { chapter_index: workflow.meta?.chapter, draft_id: task.result?.draft_id || workflow.meta?.draftId }
        onProgress({ taskId: workflow.taskId, progress: normalizeTaskProgress(task, workflow.workflowType), result: task.result || null })
      }
      return true
    } catch (err) {
      if (err !== ABORTED && !disposed && token === generation && !err?.workflowProgressVisible) {
        toast(err?.message || "正文任务恢复失败", "error")
      }
      return false
    } finally {
      if (token === generation) { generating = false; onLoadingChange(false) }
    }
  }
  async function cancel() { const workflow = recoverActiveWorkflows(getProjectId(), receiptStorage).filter((item) => MANAGED_WRITING_TYPES.has(item.workflowType) && item.view === "writing").sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0]; if (!workflow) return false; try { await api.tasks.cancel(workflow.taskId, getProjectId()) } catch (err) { toast(err?.message || "取消任务失败", "error"); return false } return true }
  function dismiss() { const workflow = recoverActiveWorkflows(getProjectId(), receiptStorage).find((item) => MANAGED_WRITING_TYPES.has(item.workflowType) && item.view === "writing"); if (workflow) clearActiveWorkflow(workflow.taskId, receiptStorage); readyResult = null; pendingStaleStoryScript = null; onProgress({ taskId: null, progress: null, result: null, staleStoryScript: null }) }
  async function openResult() { if (!readyResult || disposed || !getProjectId()) return false; await onResult(readyResult); const workflow = recoverActiveWorkflows(getProjectId(), receiptStorage).filter((item) => MANAGED_WRITING_TYPES.has(item.workflowType) && item.view === "writing").sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0]; if (workflow) clearActiveWorkflow(workflow.taskId, receiptStorage); return true }

  function dispose() {
    disposed = true
    generation += 1
    generating = false
    onLoadingChange(false)
    if (waitTimer) clearTimeout(waitTimer)
    waitTimer = null
  }

  return {
    generateDraft: () => generate("draft"),
    generateContinuation: () => generate("continue"),
    generatePovDraft: () => generate("pov"),
    reviewCandidate: () => runCandidateWorkflow("writing_semantic_review"),
    reviseCandidate: () => runCandidateWorkflow("writing_targeted_revision"),
    recover,
    openResult,
    retryUsingStaleStoryScript,
    cancel,
    dismiss,
    dispose,
  }
}

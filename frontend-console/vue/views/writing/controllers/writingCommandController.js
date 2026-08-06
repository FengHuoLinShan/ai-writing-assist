import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import { findCurrentScene } from "../../../../shared/sceneLocator.js"

const ABORTED = Symbol("writing-command-aborted")

export function createWritingCommandController({
  api,
  toast,
  getProjectId,
  getChapter,
  getScenes,
  editor,
  onResult,
  onLoadingChange = () => {},
}) {
  let generation = 0
  let generating = false
  let disposed = false
  let waitTimer = null

  function context() {
    const chapter = getChapter()
    return {
      projectId: getProjectId(),
      chapter,
      scene: findCurrentScene({
        scenes: getScenes(),
        chapterIndex: chapter,
        cursorOffset: editor.getCursorOffset(),
      }),
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
      } catch {
        await wait(1500, token)
        continue
      }
      if (disposed || token !== generation || getProjectId() !== projectId) throw ABORTED
      if (task?.status === "done") {
        const draftId = task.result?.draft_id
        if (!draftId) throw new Error("任务已完成，但未返回正文建议 ID")
        return { ...submitted, ...task.result }
      }
      if (task?.status === "failed") throw new Error(task.error_message || task.result?.error_message || "正文生成失败")
      if (task?.status === "cancelled") throw new Error("正文生成已取消")
      await wait(1500, token)
    }
    throw ABORTED
  }

  async function generate(mode = "draft") {
    const { projectId, chapter, scene } = context()
    if (!projectId || !chapter) {
      toast("请先选择章节", "warning")
      return null
    }
    if (generating) {
      toast("正文建议正在生成，请稍候", "warning")
      return null
    }
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
      const submitted = await api.writing.generate({
        novel_id: projectId,
        chapter_index: chapter,
        title: editor.getTitle() || `第 ${chapter} 章`,
        instruction,
        context_confirmation_id: confirmation.id,
        generation_mode: mode === "continue" ? "continue" : undefined,
        base_draft_id: mode === "continue" ? editor.getDraftId() : undefined,
      })
      if (disposed || token !== generation) return null
      toast(`${pov ? "AI 角色视角建议" : mode === "continue" ? "AI 续写" : "AI 正文建议"}任务已提交`, "success")
      const completed = await waitForDraft(submitted, projectId, token)
      if (disposed || token !== generation) return null
      await onResult({ chapter_index: chapter, draft_id: completed.draft_id })
      toast("正文建议已生成，已打开待审阅版本", "success")
      return completed
    } catch (err) {
      if (err === ABORTED || disposed || token !== generation) return null
      if (String(err?.message || "").includes("取消")) return null
      toast(err?.message || "正文建议生成失败", "error")
      return null
    } finally {
      if (token === generation) {
        generating = false
        onLoadingChange(false)
      }
    }
  }

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
    dispose,
  }
}

import { onBeforeUnmount, ref, watch } from "vue"
import { getApi, openProjectAssistant } from "../../bridge/index.js"
import { createOperationId } from "../../../shared/workflowProgress.js"

export function useWritingComments(projectId, editorState, selectChapter, selectRange, scrollToRange) {
  const comments = ref([])
  const selection = ref(null)
  const task = ref(null)
  const busy = ref(false)
  const error = ref("")
  let generation = 0
  let timer = null
  const storageKey = () => `writing-comment-run:${projectId}:${editorState.chapter}`

  async function load() {
    const token = ++generation
    const draftId = editorState.draftId
    if (!draftId || editorState.loading) { comments.value = []; return }
    try {
      const result = await getApi().writing.listComments(draftId, projectId)
      if (token !== generation || editorState.draftId !== draftId) return
      comments.value = result.items || []
      error.value = ""
      let saved = null
      try { saved = localStorage.getItem(storageKey()) } catch { /* task remains in memory */ }
      if (saved && saved !== task.value?.task_id) void poll(saved)
    } catch (cause) {
      if (token === generation) error.value = cause.message || "批注暂时无法读取"
    }
  }

  function prepare(focus) {
    if (!focus?.selection || editorState.dirty || editorState.saving || !editorState.contentHash) {
      error.value = "请先保存正文，再选择要批注的原文"
      return false
    }
    selection.value = focus
    error.value = ""
    return true
  }

  async function create(note) {
    const focus = selection.value
    if (!focus || busy.value || editorState.dirty) return false
    busy.value = true
    try {
      await getApi().writing.createComment(editorState.draftId, {
        novel_id: projectId,
        source_hash: editorState.contentHash,
        start_offset: focus.selection_start,
        end_offset: focus.selection_end,
        excerpt: focus.selection,
        body: note.trim(),
      })
      selection.value = null
      await load()
      return true
    } catch (cause) {
      error.value = cause.message || "保存批注失败"
      return false
    } finally { busy.value = false }
  }

  async function setStatus(item, status) {
    if (busy.value) return
    busy.value = true
    try {
      await getApi().writing.updateComment(item.id, { novel_id: projectId, status })
      await load()
    } catch (cause) { error.value = cause.message || "更新批注失败" }
    finally { busy.value = false }
  }

  function locate(item) {
    if (item.status === "stale") return false
    const chars = Array.from(editorState.content || "")
    const start = chars.slice(0, item.start_offset).join("").length
    const end = chars.slice(0, item.end_offset).join("").length
    if (!selectRange(start, end)) return false
    scrollToRange(start)
    return true
  }

  async function poll(taskId) {
    if (!taskId || !editorState.chapter) return
    clearTimeout(timer)
    const chapter = editorState.chapter
    try {
      const result = await getApi().tasks.get(taskId, projectId)
      if (editorState.chapter !== chapter) return
      task.value = result
      error.value = ""
      if (["pending", "running"].includes(result.status)) {
        timer = setTimeout(() => poll(taskId), 2000)
      } else {
        await load()
      }
    } catch (cause) {
      if (editorState.chapter === chapter) error.value = cause.message || "任务状态暂时无法读取"
    }
  }

  async function run(commentIds, includeAiReview = false) {
    if (busy.value || editorState.dirty || editorState.saving || !editorState.draftId || editorState.readonly) {
      error.value = "保存当前工作稿后再执行批注"
      return false
    }
    busy.value = true
    try {
      const result = await getApi().writing.runComments({
        novel_id: projectId,
        draft_id: editorState.draftId,
        comment_ids: commentIds,
        include_ai_review: includeAiReview,
        operation_id: createOperationId(),
      })
      try { localStorage.setItem(storageKey(), result.task_id) } catch { /* polling still continues */ }
      task.value = { task_id: result.task_id, status: result.status }
      void poll(result.task_id)
      error.value = ""
      return true
    } catch (cause) {
      error.value = cause.message || "批注任务提交失败"
      return false
    } finally { busy.value = false }
  }

  async function openCandidate(draftId) {
    if (editorState.dirty) { error.value = "请先保存当前正文"; return false }
    return selectChapter(editorState.chapter, { draftId, isReadonly: true })
  }

  async function openProposals(reference) {
    try {
      await openProjectAssistant({ projectId, sessionId: reference.session_id, runId: reference.run_id })
    } catch (cause) { error.value = cause.message || "相关资料提案暂时无法打开" }
  }

  watch(() => [editorState.draftId, editorState.updatedAt, editorState.loading], () => {
    selection.value = null
    clearTimeout(timer)
    task.value = null
    void load()
  }, { immediate: true })
  onBeforeUnmount(() => { clearTimeout(timer); generation += 1 })

  return { comments, selection, task, busy, error, prepare, create, setStatus, locate, run, poll, openCandidate, openProposals }
}

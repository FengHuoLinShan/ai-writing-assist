const pages = new Set(["today", "world", "writing", "outline", "scene", "map", "rag", "project", "generate"])
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function captureWorkContext(state, router, projectId, page, activeElement, selection, workspace) {
  const context = { page: pages.has(page) ? page : "today", scope: "current", selection: "", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai" }
  if (!projectId || state?.currentProjectId !== projectId) return context
  const owns = node => {
    const element = node?.nodeType === 3 ? node.parentElement : node
    return workspace?.contains(node) && element?.closest?.(".vue-island")?.dataset.projectId === projectId
  }
  if (page === "writing" && state.viewStates?.writing?.projectId === projectId) {
    const chapter = Number(state._currentChapter)
    if (Number.isInteger(chapter) && chapter > 0) context.chapter_index = chapter
    if (uuid.test(state._currentDraftId || "")) context.draft_id = state._currentDraftId
    if (uuid.test(state._currentSceneId || "")) context.scene_id = state._currentSceneId
    const editor = activeElement?.id === "writing-editor" ? activeElement : workspace?.querySelector?.("#writing-editor")
    if (editor?.tagName === "TEXTAREA" && owns(editor)) {
      context.selection = editor.value.slice(editor.selectionStart, editor.selectionEnd)
    }
  }
  const query = router?.getCurrentQuery?.()
  if ((page === "scene" || page === "outline") && uuid.test(query?.get("scene_id") || "")) context.scene_id = query.get("scene_id")
  for (const [param, type] of [["entity_id", "world_entity"], ["page_id", "world_bible_page"], ["node_id", "map_atlas_node"], ["thread_id", "plot_thread"], ["arc_id", "outline_arc"]]) {
    const id = query?.get(param)
    if (uuid.test(id || "")) { context.target = { target_type: type, target_id: id }; break }
  }
  if (page === "world" && uuid.test(query?.get("draft_id") || "")) context.target = { target_type: "world_bible_page_draft", target_id: query.get("draft_id") }
  if (page === "outline" && uuid.test(query?.get("plan_id") || "") && ["foreshadowing", "reveals"].includes(query?.get("information"))) context.target = { target_type: query.get("information") === "foreshadowing" ? "foreshadowing_plan" : "reveal_plan", target_id: query.get("plan_id") }
  if (!context.selection && ["world", "writing", "outline", "scene", "map", "rag"].includes(page)
    && selection?.rangeCount && owns(selection.getRangeAt(0).commonAncestorContainer)) {
    context.selection = selection.toString()
  }
  if (context.selection.length > 30000) throw new Error("选区过长，请缩小范围后再提问。")
  return context
}

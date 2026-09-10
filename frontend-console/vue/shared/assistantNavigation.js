import { getRouter, getToast, openSmartDedupTask } from "../bridge/index.js"

export function openAssistantDestination(destination, context = {}) {
  const routes = {
    project_import: ["project", null, { open: "import" }], writing: ["writing"],
    world: ["world", "bible"], world_review: ["world", "review"], story: ["outline", "story-outline"],
    map: ["map"], references: ["rag", "search"], model_settings: ["settings"],
    project_settings: ["project-settings"], world_generation: ["generate", null, { tab: "world" }],
    writing_generation: ["generate", null, { tab: "pov_prose" }],
  }
  if (!Object.hasOwn(routes, destination)) return false
  const route = routes[destination]
  const query = new URLSearchParams(route[2] || {})
  if (["writing", "writing_generation"].includes(destination)) {
    if (context.chapter_index) query.set("chapter_index", context.chapter_index)
    if (context.scene_id) query.set("scene_id", context.scene_id)
  }
  return getRouter().navigate(route[0], route[1] || null, true, query)
}

export function locateAssistantSource(source) {
  const location = source.location || source.source_ref || source
  const target = source.target || source.target_ref || (source.source_ref ? { type: "writing_draft", id: source.source_ref.draft_id } : source)
  const type = target.type || target.target_type
  const id = target.id || target.target_id
  const query = new URLSearchParams()
  let page, subview = null
  if (type === "smart_dedup_scan") {
    if (!source.task_id && !id) return false
    void openSmartDedupTask(source.task_id || id).catch(error => getToast()(error.message, "error"))
    return true
  }
  if (type === "outline_generate") {
    const taskId = source.task_id || id
    const views = { plot_thread: "threads", outline_arc: "arcs", planned_scene: "scenes" }
    subview = views[source.target_kind]
    if (!taskId || !subview) return false
    page = "outline"; query.set("review", "ai"); query.set("source_task_id", taskId)
  } else if (source.type === "world_validation" || type === "world_validation" || location.review_id) {
    const reviewId = location.review_id || source.id
    if (!reviewId) return false
    page = "world"; subview = "bible"; query.set("validation_run_id", reviewId)
  } else if (type === "world_adoption_package" || type === "world_suggestion") {
    page = "world"; subview = "bible"
    query.set(type === "world_adoption_package" ? "adoption_package_id" : "suggestion_id", id)
    if (type === "world_suggestion") query.set("open", "suggestions")
  } else if (type === "import_workflow" || location.workflow_id) {
    const taskId = source.task_id || source.workflow?.task_id || location.source_task_id
    if (!taskId) return false
    page = "writing"; query.set("import_task_id", taskId)
    if (location.chapter_index) query.set("chapter_index", location.chapter_index)
  } else if (["writing_draft", "writing_candidate"].includes(type) || location.draft_id) {
    page = "writing"
    if (location.chapter_index || target.chapter_index) query.set("chapter_index", location.chapter_index || target.chapter_index)
    if (location.draft_id || id) query.set("draft_id", location.draft_id || id)
  } else if (["core_entity", "world_entity", "entity"].includes(type)) {
    page = "world"; subview = "objects"; query.set("entity_id", id)
  } else if (type === "world_bible_page_history") {
    page = "world"; subview = "bible"; query.set("page_id", id); query.set("history", "1")
    if (target.target_path || source.version_number) query.set("history_version", target.target_path || source.version_number)
  } else if (["world_bible_page", "world_bible_page_draft", "world_bible_draft"].includes(type)) {
    page = "world"; subview = "bible"; query.set(type === "world_bible_page" ? "page_id" : "draft_id", id)
    if (type === "world_bible_page" && source.version_number) { query.set("history", "1"); query.set("history_version", source.version_number) }
  } else if (["story_character_card", "story_scene_script"].includes(type) && source.scene_id) {
    page = "scene"; subview = source.scene_id
    query.set("tab", type === "story_character_card" ? "characters" : "script")
    query.set(type === "story_character_card" ? "card_id" : "file_id", id)
    if (source.revision_id) query.set("revision_id", source.revision_id)
  } else if (source.scene_id || location.scene_id || ["scene", "outline_scene", "scene_story_assets"].includes(type)) {
    page = "scene"; subview = source.scene_id || location.scene_id || id
  } else if (type === "story_outline") { page = "outline"; subview = "story-outline"; if (source.revision_id) query.set("revision_id", source.revision_id) }
  else if (type === "plot_thread") { page = "outline"; subview = "threads"; query.set("thread_id", id) }
  else if (type === "outline_arc") { page = "outline"; subview = "arcs"; query.set("arc_id", id) }
  else if (["foreshadowing_plan", "reveal_plan"].includes(type)) { page = "outline"; subview = "threads"; query.set("information", type === "foreshadowing_plan" ? "foreshadowing" : "reveals"); query.set("plan_id", id) }
  else if (type === "world_checkpoint") { page = "generate"; query.set("checkpoint_id", id); query.set("preset", "world_core") }
  else if (type === "map_atlas_node") { page = "map"; query.set("node_id", id); if (source.revision_id) query.set("revision_id", source.revision_id) }
  else if (type === "map_atlas_page") { page = "map"; query.set("atlas_view", "review"); query.set("page_id", id); if (source.run_id) query.set("run_id", source.run_id); if (source.node_id) query.set("node_id", source.node_id) }
  else if (type === "author_task") { page = "writing"; query.set("home", "1"); query.set("panel", "tasks") }
  if (!page) return false
  return getRouter().navigate(page, subview, true, query)
}

const SOURCE_KINDS = new Set([
  "world_page",
  "world_entity",
  "writing_chapter",
  "outline_scene",
])

export function authorTaskSourceFromQuery(query) {
  const kind = query?.get?.("task_source_kind") || ""
  const id = query?.get?.("task_source_id") || ""
  if (!SOURCE_KINDS.has(kind) || !id) return null
  return {
    kind,
    id,
    taskTitle: String(query?.get?.("task_title") || "").trim().slice(0, 255),
  }
}

export function authorTaskPanelQuery(source = null) {
  const query = new URLSearchParams({ home: "1", panel: "tasks", scope: "inbox" })
  if (source && SOURCE_KINDS.has(source.kind) && source.id) {
    query.set("task_source_kind", source.kind)
    query.set("task_source_id", String(source.id))
    if (source.title) query.set("task_title", String(source.title).trim().slice(0, 255))
  }
  return query
}

export function openAuthorTaskSource(source, router) {
  if (!source?.available || !source.id || !router) return false
  const query = new URLSearchParams()
  if (source.kind === "world_page") {
    query.set("page_id", source.id)
    router.navigate("world", "bible", true, query)
  } else if (source.kind === "world_entity") {
    query.set("kind", "entity")
    query.set("entity_id", source.id)
    router.navigate("world", "bible", true, query)
  } else if (source.kind === "writing_chapter") {
    query.set("chapter_index", source.id)
    router.navigate("writing", null, true, query)
  } else if (source.kind === "outline_scene") {
    query.set("scene_id", source.id)
    router.navigate("outline", "scenes", true, query)
  } else {
    return false
  }
  return true
}

/**
 * RAG 检索路由状态纯逻辑 — 从 ragView._searchRouteState / _searchRouteQuery 移植。
 * URL query 是检索条件的权威来源（前进/后退恢复、深链）。
 */

export const RAG_RESULT_PAGE_SIZE = 20
export const RAG_RESULT_FETCH_LIMIT = 100
export const RAG_SEARCH_SCOPES = Object.freeze(["manuscript", "world", "outline"])

/**
 * 解析当前 URL query 为检索路由状态（含 signature）。
 * @param {URLSearchParams} current
 */
export function parseRouteQuery(current) {
  const query = new URLSearchParams(current?.toString ? current.toString() : "")
  const positiveInteger = (name) => {
    const value = Number(query.get(name))
    return Number.isInteger(value) && value >= 1 ? value : null
  }
  const nonNegativeInteger = (name) => {
    const raw = query.get(name)
    if (raw == null || raw === "") return null
    const value = Number(raw)
    return Number.isInteger(value) && value >= 0 ? value : null
  }
  const rawScopes = query.getAll("scope").filter((scope) => RAG_SEARCH_SCOPES.includes(scope))
  return {
    query: query.get("q") || "",
    searchKind: query.get("kind") === "literal" ? "literal" : "smart",
    contentMode: query.get("content_mode") === "working" ? "working" : "canonical",
    visibilityMode: ["reader", "character"].includes(query.get("visibility"))
      ? query.get("visibility")
      : "author",
    chapterFrom: positiveInteger("chapter_from"),
    chapterTo: positiveInteger("chapter_to"),
    cutoffChapter: positiveInteger("cutoff_chapter"),
    cutoffSceneId: query.get("cutoff_scene_id") || "",
    cutoffOffset: nonNegativeInteger("cutoff_offset"),
    characterId: query.get("character_id") || "",
    scopes: rawScopes.length ? [...new Set(rawScopes)] : ["manuscript"],
    includePending: query.get("include_pending") === "1",
    signature: query.toString(),
  }
}

/**
 * 由关键词 + payload 构造回写 URL 的 query（对应 _searchRouteQuery）。
 * payload 结构同 buildEvidencePayload 输出。
 */
export function buildRouteQuery(query, payload) {
  const route = new URLSearchParams()
  route.set("q", query)
  route.set("kind", payload.search_kind)
  route.set("content_mode", payload.content_mode)
  route.set("visibility", payload.visibility.mode)
  for (const scope of payload.scopes) route.append("scope", scope)
  if (payload.chapter_from != null) route.set("chapter_from", String(payload.chapter_from))
  if (payload.chapter_to != null) route.set("chapter_to", String(payload.chapter_to))
  if (payload.visibility.cutoff_chapter != null) {
    route.set("cutoff_chapter", String(payload.visibility.cutoff_chapter))
  }
  if (payload.visibility.cutoff_scene_id) {
    route.set("cutoff_scene_id", payload.visibility.cutoff_scene_id)
  }
  if (payload.visibility.cutoff_offset != null) {
    route.set("cutoff_offset", String(payload.visibility.cutoff_offset))
  }
  if (payload.visibility.character_id) {
    route.set("character_id", payload.visibility.character_id)
  }
  if (payload.include_pending_objects) route.set("include_pending", "1")
  return route
}

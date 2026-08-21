/**
 * worldQuery — world 视图筛选与 URL query 的双向编解码（纯函数）。
 *
 * 逐行对应 vanilla views/worldView.js 的同名方法（L37-163 常量、L423-557 编解码），
 * URL 是筛选的唯一事实源：island load() 解码 query → filters；用户改筛选 →
 * 编码后 router.navigate 写 query。
 */

export const WORLD_FILTER_DEFAULTS = {
  entity_type: "",
  display_state: "active",
  q: "",
  source: "",
  workflow_id: "",
  needs_review: "",
  auto_ingested: "",
  focus: "",
  skip: 0,
  limit: 20,
}

const WORLD_LIST_DEFAULTS = {
  skip: 0,
  limit: 20,
}

export const WORLD_CANDIDATE_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
  q: "",
  entity_type: "",
  suggested_action: "",
  source: "",
  workflow_id: "",
  scene_index: "",
  source_chapter_index: "",
  confidence_min: "",
  confidence_max: "",
}

export const WORLD_ALIAS_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
  q: "",
  source: "",
  workflow_id: "",
  scene_index: "",
  source_chapter_index: "",
  confidence_min: "",
  confidence_max: "",
  has_quote: "",
  type_kind: "",
  multi_alias_only: "",
}

export const WORLD_RELATION_FILTER_DEFAULTS = {
  ...WORLD_LIST_DEFAULTS,
  relation_type: "",
  q: "",
  source_chapter_id: "",
  scene_index: "",
  source_chapter_index: "",
  strength_min: "",
  strength_max: "",
  has_quote: "",
  type_kind: "",
  multi_type_only: "",
  has_reverse_candidates: "",
  has_canonical_relation: "",
}

export const REVIEW_ALIAS_TYPE_FALLBACK = [
  ["name", "名称"], ["title", "称号"], ["nickname", "昵称"],
  ["alias", "别名"], ["translation", "译名"], ["abbreviation", "缩写"],
].map(([value, label]) => ({ value, label, category: "别名", synonyms: [] }))

export const REVIEW_RELATION_TYPE_FALLBACK = [
  ["friend_of", "朋友"], ["enemy_of", "敌人"], ["ally_of", "盟友"],
  ["member_of", "成员"], ["leader_of", "领导者"], ["located_at", "位于"],
  ["contains", "包含"], ["related_to", "相关"],
].map(([value, label]) => ({ value, label, category: "常用", synonyms: [] }))

export const WORLD_FILTER_PANEL_DEFAULTS = {
  objects: false,
  review: false,
  "review-objects": false,
  "review-aliases": false,
  "review-relations": false,
}

export const WORLD_SUGGESTED_ACTION_LABELS = {
  create_new: "创建新对象",
  link_to_existing: "设为别名",
  alias_of_existing: "设为别名",
  merge_with_existing: "合并到已有对象",
  temporary_only: "设为临时",
  ignore: "忽略",
  needs_user_decision: "需要作者决定",
}

export const WORLD_OBJECT_QUERY_KEYS = [
  "entity_type",
  "display_state",
  "q",
  "source",
  "workflow_id",
  "needs_review",
  "auto_ingested",
  "focus",
]

export const CUSTOM_ENTITY_TYPE_SENTINEL = "__custom_entity_type__"

export const SYSTEM_ENTITY_TYPE_FALLBACK = [
  ["character", "人物"], ["location", "地点"], ["faction", "势力/派系"],
  ["organization", "组织"], ["species", "种族"], ["group", "群体"],
  ["item", "物品"], ["object", "物体"], ["event", "事件"], ["rule", "规则"],
  ["power_system", "力量体系"], ["secret", "秘密/真相"], ["legend", "传说/神话"],
  ["resource", "资源/材料"], ["concept", "概念"], ["creature", "生物/怪物"],
  ["skill", "技能"], ["ability", "能力"], ["artifact", "神器/遗物"], ["other", "其他"],
].map(([value, label]) => ({ value, label, kind: "system" }))

export const WORLD_CANDIDATE_QUERY_KEYS = [
  "q",
  "entity_type",
  "suggested_action",
  "source",
  "workflow_id",
  "scene_index",
  "source_chapter_index",
  "confidence_min",
  "confidence_max",
]

export const WORLD_ALIAS_QUERY_KEYS = [
  "q", "source", "workflow_id", "scene_index", "source_chapter_index",
  "confidence_min", "confidence_max", "has_quote", "type_kind", "multi_alias_only",
]

export const WORLD_RELATION_QUERY_KEYS = [
  "q", "relation_type", "scene_index", "source_chapter_index", "strength_min",
  "strength_max", "has_quote", "type_kind", "multi_type_only",
  "has_reverse_candidates", "has_canonical_relation",
]

/** 对应 vanilla _normalizeReviewSubView（worldView.js:748-754）。 */
export function normalizeReviewSubView(subView = "") {
  if (["review", "candidates", "review-objects", "review-aliases", "review-relations"].includes(subView)) return "review"
  return ""
}

export function reviewKindFromRoute(subView = "", query = new URLSearchParams()) {
  const requested = query.get("kind") || ""
  if (["objects", "aliases", "relations"].includes(requested)) return requested
  if (["candidates", "review-objects"].includes(subView)) return "objects"
  if (subView === "review-aliases") return "aliases"
  if (subView === "review-relations") return "relations"
  return "all"
}

/** 对应 vanilla _queryPageSkip（L423-426）。 */
export function queryPageSkip(query, limit) {
  const page = Math.max(1, Number.parseInt(query.get("page") || "1", 10) || 1)
  return (page - 1) * limit
}

/** 对应 vanilla _filtersEqual（L428-432）。 */
export function filtersEqual(a, b, keys) {
  return keys.every((key) => String(a[key] ?? "") === String(b[key] ?? ""))
    && Number(a.skip || 0) === Number(b.skip || 0)
    && Number(a.limit || 0) === Number(b.limit || 0)
}

/** 对应 vanilla _objectFiltersFromQuery（L434-447），含 legacy status 映射。 */
export function objectFiltersFromQuery(query) {
  const filters = { ...WORLD_FILTER_DEFAULTS }
  for (const key of WORLD_OBJECT_QUERY_KEYS) {
    filters[key] = query.get(key) || filters[key]
  }
  const legacyStatus = query.get("status") || ""
  if (!query.has("display_state") && legacyStatus) {
    if (["canonical", "active", "confirmed"].includes(legacyStatus)) filters.display_state = "active"
    else if (["deprecated", "merged", "ignored", "rolled_back"].includes(legacyStatus)) filters.display_state = "archived"
    else filters.display_state = "review"
  }
  filters.skip = queryPageSkip(query, filters.limit)
  return filters
}

/** 对应 vanilla _candidateFiltersFromQuery（L449-456）。 */
export function candidateFiltersFromQuery(query) {
  const filters = { ...WORLD_CANDIDATE_FILTER_DEFAULTS }
  for (const key of WORLD_CANDIDATE_QUERY_KEYS) {
    filters[key] = query.get(key) || ""
  }
  filters.skip = queryPageSkip(query, filters.limit)
  return filters
}

/** 对应 vanilla _reviewFiltersFromQuery（L458-465）。 */
export function reviewFiltersFromQuery(defaults, keys, query) {
  const filters = { ...defaults }
  for (const key of keys) filters[key] = query.get(key) || ""
  const requestedLimit = Number.parseInt(query.get("page_size") || "20", 10)
  filters.limit = requestedLimit === 50 ? 50 : 20
  filters.skip = queryPageSkip(query, filters.limit)
  return filters
}

/** 对应 vanilla _hasAdvancedObjectFilters（L510-517）。 */
export function hasAdvancedObjectFilters(filters) {
  return Boolean(
    filters.source
    || filters.workflow_id
    || filters.needs_review
    || filters.auto_ingested,
  )
}

/** 对应 vanilla _setQueryValue（L519-522）。 */
export function setQueryValue(query, key, value) {
  const normalized = String(value ?? "").trim()
  if (normalized) query.set(key, normalized)
}

/** 对应 vanilla _objectQueryFromState（L524-534）。 */
export function objectQueryFromState(filters, viewMode, discoveryMode) {
  const query = new URLSearchParams()
  for (const key of WORLD_OBJECT_QUERY_KEYS) {
    setQueryValue(query, key, filters[key])
  }
  const page = Math.floor((filters.skip || 0) / filters.limit) + 1
  if (page > 1) query.set("page", String(page))
  query.set("view", viewMode === "table" ? "table" : "card")
  query.set("mode", discoveryMode)
  return query
}

/** 对应 vanilla _candidateQueryFromState（L536-544）。 */
export function candidateQueryFromState(candidateFilters) {
  const query = new URLSearchParams()
  for (const key of WORLD_CANDIDATE_QUERY_KEYS) {
    setQueryValue(query, key, candidateFilters[key])
  }
  const page = Math.floor((candidateFilters.skip || 0) / candidateFilters.limit) + 1
  if (page > 1) query.set("page", String(page))
  return query
}

/** 对应 vanilla _reviewQueryFromState（L546-553）。 */
export function reviewQueryFromState(filters, keys) {
  const query = new URLSearchParams()
  for (const key of keys) setQueryValue(query, key, filters[key])
  const page = Math.floor((filters.skip || 0) / filters.limit) + 1
  if (page > 1) query.set("page", String(page))
  if (Number(filters.limit) === 50) query.set("page_size", "50")
  return query
}

const SENSITIVE_KEY = /(secret|token|password|api[_-]?key|authorization|cookie|prompt)/i
const SOURCE_REF_KEYS = new Set([
  "source",
  "source_type",
  "source_id",
  "workflow",
  "workflow_id",
  "task_id",
  "scene_id",
  "scene_index",
  "chapter_id",
  "chapter_index",
  "issue_key",
  "observation_id",
  "fact_id",
  "map_id",
  "entity_id",
  "path_id",
  "layer_node_id",
  "revision",
])

function cleanString(value) {
  const text = String(value)
  try {
    const url = new URL(text)
    return `${url.origin}${url.pathname}${url.hash || ""}`
  } catch {
    return text.replace(/[a-z][a-z0-9+.-]*:\/\/[^\s<>"']+/gi, (rawUrl) => {
      try {
        const url = new URL(rawUrl)
        return `${url.origin}${url.pathname}${url.hash || ""}`
      } catch {
        return rawUrl.replace(/\?.*?(?=#|$)/, "")
      }
    })
  }
}

function cleanScalar(value) {
  if (value == null || typeof value === "boolean" || typeof value === "number") return value
  return cleanString(value)
}

function cleanAllowedScalar(value) {
  if (value == null) return null
  if (!["string", "number", "boolean"].includes(typeof value)) return null
  return cleanScalar(value)
}

function cleanSourceRef(value, depth = 0) {
  if (!value || typeof value !== "object" || depth > 3) return undefined
  if (Array.isArray(value)) {
    return value.slice(0, 20).map((item) => (
      item && typeof item === "object" ? cleanSourceRef(item, depth + 1) : cleanScalar(item)
    )).filter((item) => item !== undefined)
  }
  const result = {}
  for (const [key, child] of Object.entries(value)) {
    if (SENSITIVE_KEY.test(key) || !SOURCE_REF_KEYS.has(key)) continue
    const cleaned = child && typeof child === "object"
      ? cleanSourceRef(child, depth + 1)
      : cleanScalar(child)
    if (cleaned !== undefined) result[key] = cleaned
  }
  return result
}

export function buildMapDiagnosticInfo(item = {}, { mapId = null } = {}) {
  const kind = item.item_kind === "fact" ? "fact" : "observation"
  const result = {
    kind,
    map_id: cleanAllowedScalar(mapId || item.map_id || null),
    observation_id: cleanAllowedScalar(
      kind === "observation" ? (item.item_id || item.id || null) : null,
    ),
    fact_id: cleanAllowedScalar(
      kind === "fact" ? (item.item_id || item.id || null) : null,
    ),
    entity_id: cleanAllowedScalar(item.target_entity_id || item.entity_id || null),
    normalization_state: cleanAllowedScalar(item.normalization_state || null),
    normalization_error: cleanAllowedScalar(
      item.normalization_error || item.normalization_message || null,
    ),
    revision: cleanAllowedScalar(
      item.revision ?? item.content_revision ?? item.editor_revision ?? null,
    ),
    source_ref: cleanSourceRef(item.source_ref || {}),
  }
  return Object.fromEntries(
    Object.entries(result).filter(([, value]) => value != null && (
      typeof value !== "object" || Object.keys(value).length > 0
    )),
  )
}

export function formatMapDiagnosticInfo(item, context = {}) {
  return JSON.stringify(buildMapDiagnosticInfo(item, context), null, 2)
}

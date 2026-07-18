/**
 * worldEntityHelpers — world 实体/候选的纯函数助手（对应 vanilla worldView 同名方法）。
 * 被 objects/review/relations+aliases tabs 与 worldEntityOps 共用。
 */
import { worldAssetDisplay } from "../../../../shared/assetDisplayState.js"

/** 对应 vanilla _entityId。 */
export function entityId(entity) {
  return entity?.id || entity?.entity_id || ""
}

/** 对应 vanilla _suggestionId（仅 draft/candidate 且 compatibility_shadow）。 */
export function suggestionId(entity) {
  const meta = entity?.content_json?._meta || {}
  if (!["draft", "candidate"].includes(entity?.status)) return ""
  if (meta.compatibility_shadow !== true) return ""
  return String(meta.suggestion_id || "")
}

export function isSuggestionShadow(entity) {
  return Boolean(suggestionId(entity))
}

/** 对应 vanilla _entityNeedsReview。 */
export function entityNeedsReview(entity) {
  return entity?.needs_review === true
    || entity?.content_json?._meta?.needs_review === true
}

/** 对应 vanilla _entityReviewContent（标记/取消人工检查的 content_json 构造）。 */
export function entityReviewContent(entity, reviewed, reviewedFrom = "world_objects") {
  const content = { ...(entity?.content_json || {}) }
  const meta = { ...(content._meta || {}) }
  if (reviewed) {
    meta.needs_review = false
    meta.reviewed_at = new Date().toISOString()
    meta.reviewed_by = "manual"
    meta.reviewed_from = reviewedFrom
  } else {
    meta.needs_review = true
    delete meta.reviewed_at
    delete meta.reviewed_by
    delete meta.reviewed_from
  }
  content._meta = meta
  return content
}

export function candidateMeta(candidate) {
  return (candidate?.content_json || {})._meta || {}
}

export function candidateAction(candidate) {
  return candidate?.suggested_action
    || candidateMeta(candidate).suggested_action
    || "create_new"
}

export function candidateTargetName(candidate) {
  return candidate?.suggested_existing_entity_name
    || candidateMeta(candidate).suggested_existing_entity_name
    || ""
}

export function candidateTargetId(candidate) {
  return candidate?.suggested_existing_entity_id
    || candidateMeta(candidate).suggested_existing_entity_id
    || ""
}

export function hasResolvedCandidateTarget(candidate) {
  const targetId = candidateTargetId(candidate)
  return Boolean(targetId) && targetId !== entityId(candidate)
}

/** 对应 vanilla _isTargetedAliasCandidate。 */
export function isTargetedAliasCandidate(candidate) {
  return ["link_to_existing", "alias_of_existing"].includes(candidateAction(candidate))
    && hasResolvedCandidateTarget(candidate)
}

/** 对应 vanilla _entityAvatarColor。 */
export function entityAvatarColor(entity) {
  const source = `${entity?.entity_type || ""}:${entity?.name || ""}`
  let hash = 0
  for (let i = 0; i < source.length; i++) {
    hash = ((hash << 5) - hash) + source.charCodeAt(i)
    hash |= 0
  }
  const hue = Math.abs(hash) % 360
  return `hsl(${hue} 58% 38%)`
}

/** 对应 vanilla _entityReferenceItem（referencePicker 条目）。 */
export function entityReferenceItem(entity) {
  const display = worldAssetDisplay(entity)
  return {
    kind: "entity",
    id: entityId(entity),
    label: entity?.name || "未命名对象",
    description: [entity?.entity_type || "世界对象", entity?.summary || entity?.public_info].filter(Boolean).join(" · "),
    status: display.label,
    unavailable: display.isHistory,
  }
}

/** 对应 vanilla _isAliasTargetEntity。 */
export function isAliasTargetEntity(entity) {
  return ["draft", "canonical", "candidate"].includes(entity?.status)
    && !entity?.content_json?._meta?.compatibility_shadow
}

/** 对应 vanilla _isMergeTargetEntity。 */
export function isMergeTargetEntity(entity) {
  return entity?.status === "canonical"
}

/** 对应 vanilla _fusionSuggestionKey。 */
export function fusionSuggestionKey(item) {
  return [
    item.action || "needs_review",
    item.source_entity_id || "",
    item.target_entity_id || "",
  ].map((part) => encodeURIComponent(String(part))).join("::")
}

/** 对应 vanilla _formatBatchTime。 */
export function formatBatchTime(isoStr) {
  if (!isoStr) return ""
  try {
    const d = new Date(isoStr)
    if (Number.isNaN(d.getTime())) return isoStr
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const pad = (n) => String(n).padStart(2, "0")
    const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`
    if (diffMs >= 0 && diffMs < 60 * 1000) return "刚刚"
    if (diffMs >= 0 && diffMs < 60 * 60 * 1000) return `${Math.max(1, Math.floor(diffMs / (60 * 1000)))} 分钟前`
    if (diffMs >= 0 && diffMs < 24 * 60 * 60 * 1000) return `${Math.max(1, Math.floor(diffMs / (60 * 60 * 1000)))} 小时前`
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    if (
      d.getFullYear() === yesterday.getFullYear()
      && d.getMonth() === yesterday.getMonth()
      && d.getDate() === yesterday.getDate()
    ) {
      return `昨天 ${time}`
    }
    if (d.getFullYear() === now.getFullYear()) {
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
    }
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
  } catch { return isoStr }
}

/** 对应 vanilla _formatBatchTimeFull。 */
export function formatBatchTimeFull(isoStr) {
  if (!isoStr) return ""
  try {
    const d = new Date(isoStr)
    if (Number.isNaN(d.getTime())) return isoStr
    const pad = (n) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch { return isoStr }
}

/** 对应 vanilla _isFreshBatch。 */
export function isFreshBatch(isoStr) {
  if (!isoStr) return false
  const d = new Date(isoStr)
  if (Number.isNaN(d.getTime())) return false
  const diffMs = Date.now() - d.getTime()
  return diffMs >= 0 && diffMs < 24 * 60 * 60 * 1000
}

/** 对应 vanilla _createConflictDetail（409 相似对象冲突解析）。 */
export function createConflictDetail(err) {
  if (!err || !(err.status === 409 || (err.message && err.message.includes("409")))) {
    return null
  }
  let detail = err.detail ?? err.body?.detail ?? err.body?.message ?? null
  if (typeof detail === "string") {
    try { detail = JSON.parse(detail) } catch { /* keep string */ }
  }
  if (detail && typeof detail === "object" && detail.requires_confirmation) {
    return detail
  }
  return null
}

/** 对应 vanilla _formatSimilarEntities。 */
export function formatSimilarEntities(entities) {
  if (!Array.isArray(entities)) return ""
  return entities
    .map((item) => {
      if (!item || typeof item !== "object") return String(item || "").trim()
      const name = item.name || item.title || item.id || "未命名对象"
      const type = item.entity_type || item.type
      const score = item.similarity_score ?? item.score ?? item.confidence
      const parts = [name]
      if (type) parts.push(type)
      if (score != null) parts.push(`相似度 ${score}`)
      return parts.join(" / ")
    })
    .filter(Boolean)
    .join("；")
}

/** 对应 vanilla _affectedIdsFromMutationResult。 */
export function affectedIdsFromMutationResult(result) {
  const ids = [
    ...(Array.isArray(result?.affected_ids) ? result.affected_ids : []),
    ...(Array.isArray(result?.merged_ids) ? result.merged_ids : []),
    result?.candidate_entity_id,
  ]
  return Array.from(new Set(ids.filter(Boolean).map(String)))
}

/**
 * useWorldReview — world review（待处理）三队列的逻辑层。
 *
 * 对应 vanilla worldView 的候选分组/动作可见性（1710-1886）、证据摘要
 * （2032-2043, 2232-2258）、别名/关系就地决策与批量复核（4165-4270 +
 * 决策表单）。列表数据是 island props（只读），批量动作需要按 id 查找，
 * 因此维护 reviewRegistry（WorldReviewTab 在 props 变化时同步）。
 * 草稿/错误/批量选择落 worldSession（见 worldSession.js 进入协调语义）。
 */
import { getApi, getAppState, getCloseModal, getConfirmAction, getEsc, getRouter, getShowModalHtml, getToast } from "../../../bridge/index.js"
import { worldSession } from "../worldSession.js"
import {
  WORLD_SUGGESTED_ACTION_LABELS,
  WORLD_ALIAS_QUERY_KEYS,
  WORLD_RELATION_QUERY_KEYS,
  REVIEW_ALIAS_KIND_FALLBACK,
  REVIEW_ALIAS_TYPE_FALLBACK,
  REVIEW_RELATION_KIND_FALLBACK,
  REVIEW_RELATION_TYPE_FALLBACK,
  candidateQueryFromState,
  reviewQueryFromState,
} from "./worldQuery.js"
import { getBulkSelection, runBulkAction, bulkResultMessage, selectedItemsFrom, clearBulkSelection } from "./worldBulkSelection.js"
import {
  candidateAction,
  candidateTargetId,
  candidateTargetName,
  entityId,
  hasResolvedCandidateTarget,
  isSuggestionShadow,
  isTargetedAliasCandidate,
} from "./worldEntityHelpers.js"
import { adoptEntity, ignoreEntity, mountEntityReferencePickerForReview } from "./worldEntityOps.js"
import {
  bindTypeKindControls,
  detailTypeLabel,
  detailTypeOptionsHtml,
  kindLabel,
  kindOptionsHtml,
  kindOrTypeDefault,
  readDetailType,
} from "./worldTypeCatalog.js"

// ============================================================
// 注册表（WorldReviewTab 同步 props）
// ============================================================

export const reviewRegistry = {
  aliases: [],
  relationGroups: [],
  relations: [],
  entities: [],
  candidates: [],
  entityTypes: [],
  reviewTypeCatalog: {
    alias_kinds: REVIEW_ALIAS_KIND_FALLBACK,
    alias_types: REVIEW_ALIAS_TYPE_FALLBACK,
    relation_kinds: REVIEW_RELATION_KIND_FALLBACK,
    relation_types: REVIEW_RELATION_TYPE_FALLBACK,
  },
  // advance* 页码回退所需（vanilla _relationFilters/_aliasFilters/_relationGroupTotal/_aliasGroupTotal）
  relationFilters: { skip: 0, limit: 20 },
  aliasFilters: { skip: 0, limit: 20 },
  relationGroupTotal: 0,
  aliasGroupTotal: 0,
}

export function syncReviewRegistry(partial = {}) {
  if (Array.isArray(partial.aliases)) reviewRegistry.aliases = partial.aliases
  if (Array.isArray(partial.relationGroups)) reviewRegistry.relationGroups = partial.relationGroups
  if (Array.isArray(partial.relations)) reviewRegistry.relations = partial.relations
  if (Array.isArray(partial.entities)) reviewRegistry.entities = partial.entities
  if (Array.isArray(partial.candidates)) reviewRegistry.candidates = partial.candidates
  if (Array.isArray(partial.entityTypes)) reviewRegistry.entityTypes = partial.entityTypes
  if (partial.reviewTypeCatalog) reviewRegistry.reviewTypeCatalog = partial.reviewTypeCatalog
  if (partial.relationFilters) reviewRegistry.relationFilters = partial.relationFilters
  if (partial.aliasFilters) reviewRegistry.aliasFilters = partial.aliasFilters
  if (Number.isFinite(partial.relationGroupTotal)) reviewRegistry.relationGroupTotal = partial.relationGroupTotal
  if (Number.isFinite(partial.aliasGroupTotal)) reviewRegistry.aliasGroupTotal = partial.aliasGroupTotal
}

/** 对应 vanilla _aliasKey。 */
export function aliasKey(alias) {
  if (!alias) return ""
  return `${alias.entity_id || ""}::${alias.alias || ""}`
}

function reviewDraftStorageKey(kind, key) {
  const projectId = getAppState()?.currentProjectId || "none"
  return `novel_world_review_draft:${projectId}:${kind}:${key}`
}

function loadReviewDraft(kind, key, fingerprint, inMemoryDraft) {
  try {
    const stored = JSON.parse(sessionStorage.getItem(reviewDraftStorageKey(kind, key)) || "null")
    const drafts = [inMemoryDraft, stored].filter((draft) => draft && typeof draft === "object")
    const draft = drafts.find((item) => item.expected_execution_fingerprint === fingerprint) || null
    return { draft, stale: !draft && drafts.length > 0 }
  } catch {
    return { draft: null, stale: false }
  }
}

function reviewDecisionPayload(draft) {
  const { _kind_explicit: _ignored, separate_relations: separateRelations, ...payload } = draft
  return separateRelations
    ? {
        ...payload,
        separate_relations: separateRelations.map(({ _kind_explicit: _separateIgnored, ...item }) => item),
      }
    : payload
}

function storeReviewDraft(kind, key, draft) {
  try { sessionStorage.setItem(reviewDraftStorageKey(kind, key), JSON.stringify(draft)) } catch {}
}

function clearStoredReviewDraft(kind, key) {
  try { sessionStorage.removeItem(reviewDraftStorageKey(kind, key)) } catch {}
}

// ============================================================
// 候选分组（vanilla 1738-1802）
// ============================================================

export function normalizedCandidateName(candidate) {
  return String(candidate?.name || "")
    .normalize("NFKC")
    .toLocaleLowerCase("zh-CN")
    .replace(/[\s·•・._\-—–:：'’"“”()（）[\]【】]/g, "")
}

export function candidateNamesAreSimilar(left, right) {
  if ((left?.entity_type || "") !== (right?.entity_type || "")) return false
  const a = normalizedCandidateName(left)
  const b = normalizedCandidateName(right)
  if (!a || !b) return false
  if (a === b) return true
  const shorter = a.length <= b.length ? a : b
  const longer = a.length > b.length ? a : b
  if (shorter.length >= 3 && longer.includes(shorter)) return true
  if (shorter.length < 3) return false
  const aPairs = new Set(Array.from({ length: a.length - 1 }, (_, index) => a.slice(index, index + 2)))
  const bPairs = new Set(Array.from({ length: b.length - 1 }, (_, index) => b.slice(index, index + 2)))
  const overlap = Array.from(aPairs).filter((pair) => bPairs.has(pair)).length
  return (2 * overlap) / (aPairs.size + bPairs.size) >= 0.72
}

export function groupSimilarNameCandidates(candidates) {
  const groups = []
  const assigned = new Set()
  for (let index = 0; index < candidates.length; index += 1) {
    if (assigned.has(index)) continue
    const group = [candidates[index]]
    assigned.add(index)
    for (let other = index + 1; other < candidates.length; other += 1) {
      if (assigned.has(other)) continue
      if (group.some((item) => candidateNamesAreSimilar(item, candidates[other]))) {
        group.push(candidates[other])
        assigned.add(other)
      }
    }
    if (group.length > 1) groups.push(group)
  }
  return groups
}

/** 候选列表三段拆分（vanilla _renderCandidatesList 1909-1920）。 */
export function splitCandidateGroups(candidates) {
  const targetedAliasCandidates = candidates.filter((candidate) => isTargetedAliasCandidate(candidate))
  const aliasUngroupedCandidates = candidates.filter((candidate) => !isTargetedAliasCandidate(candidate))
  const similarNameGroups = groupSimilarNameCandidates(aliasUngroupedCandidates)
  const similarNameIds = new Set(similarNameGroups.flat().map((item) => entityId(item)))
  const regularCandidates = aliasUngroupedCandidates.filter((candidate) => !similarNameIds.has(entityId(candidate)))
  return { targetedAliasCandidates, similarNameGroups, regularCandidates }
}

/** 目标别名候选按目标分组（vanilla _renderTargetedAliasCandidateGroups 1804-1813）。 */
export function groupTargetedAliasCandidates(candidates) {
  const groups = new Map()
  for (const candidate of candidates) {
    const targetId = candidateTargetId(candidate)
    const targetName = candidateTargetName(candidate)
    const key = targetId || `name:${targetName}`
    if (!groups.has(key)) groups.set(key, { targetId, targetName, candidates: [] })
    groups.get(key).candidates.push(candidate)
  }
  return Array.from(groups.values())
}

/** 建议动作标签（vanilla 1949-1958）。 */
export function candidateActionLabel(candidate) {
  const action = candidateAction(candidate)
  const targetName = candidateTargetName(candidate)
  let actionLabel = WORLD_SUGGESTED_ACTION_LABELS[action] || action
  if (targetName && ["link_to_existing", "alias_of_existing"].includes(action)) {
    actionLabel = hasResolvedCandidateTarget(candidate)
      ? `作为${targetName}别名`
      : `疑似关联${targetName}（目标未解析）`
  } else if (targetName && action === "merge_with_existing") {
    actionLabel = `合并到${targetName}`
  }
  return { action, label: actionLabel }
}

/** 行内动作可见性（vanilla _candidateActionsHtml 1710-1735）。 */
export function candidateActionVisibility(candidate, { allowAlias = false, allowMerge = false } = {}) {
  const action = candidateAction(candidate)
  const isTemporary = action === "temporary_only"
  const shadow = isSuggestionShadow(candidate)
  const unresolvedAliasTarget = ["link_to_existing", "alias_of_existing"].includes(action)
    && !hasResolvedCandidateTarget(candidate)
  const canAccept = shadow || ![
    "temporary_only",
    "ignore",
    "link_to_existing",
    "alias_of_existing",
    "merge_with_existing",
  ].includes(action) || unresolvedAliasTarget
  const canAlias = allowAlias || shadow || ["link_to_existing", "alias_of_existing"].includes(action)
  const canMerge = allowMerge || shadow || action === "merge_with_existing"
  return { canAccept, canAlias, canMerge, isTemporary }
}

// ============================================================
// 证据与类型标签（vanilla 2226-2258, 2032-2043）
// ============================================================

export function reviewTypeLabel(kind, value) {
  return detailTypeLabel(reviewRegistry.reviewTypeCatalog, kind, value)
}

export function reviewKindLabel(kind, value) {
  return kindLabel(reviewRegistry.reviewTypeCatalog, kind, value)
}

function reviewSourceLabel(source) {
  return {
    deep_import: "深度导入",
    manual: "手动整理",
    manual_edit: "手动编辑",
    manual_rollback: "手动回滚",
    ai_generated: "AI 工具",
    ai_import: "AI 导入整理",
    ai_world_generation_center: "设定共创",
    worldbook_import: "世界书导入",
  }[source] || (source ? "其他来源" : "")
}

/** 对应 vanilla _reviewEvidenceSummaryHtml；返回渲染模型而非 HTML。 */
export function reviewEvidenceSummary(item = {}, kind = "alias", numericValue = null) {
  const source = reviewSourceLabel(item.source)
  const summary = [
    source,
    item.scene_index != null ? `场景 ${item.scene_index}` : "",
    item.source_chapter_index != null ? `第 ${item.source_chapter_index} 章` : "",
    numericValue != null ? `${kind === "relation" ? "强度" : "置信度"} ${Math.round(Number(numericValue) * 100)}%` : "",
  ].filter(Boolean).join(" · ")
  const diagnostic = JSON.stringify({
    workflow_id: item.workflow_id || null,
    scene_id: item.scene_id || null,
    scene_index: item.scene_index ?? null,
    source_chapter_index: item.source_chapter_index ?? null,
    evidence_refs: item.evidence_refs || [],
  })
  return {
    summary: summary || "无来源摘要",
    quote: item.quote || "",
    diagnostic,
  }
}

export function recommendedRelationDecision(group) {
  const members = group?.members || []
  const primary = members[0]
  if (!primary) return null
  const suggested = primary.suggested_relation_type
  const selected = members.filter((item) => (
    (suggested && item.suggested_relation_type === suggested)
    || (!suggested && item.relation_type === primary.relation_type)
  ))
  const selectedMembers = selected.length ? selected : [primary]
  return {
    client_decision_id: group.group_id,
    action: selectedMembers.length > 1 ? "merge" : "accept",
    group_id: group.group_id,
    member_relation_ids: selectedMembers.map((item) => item.id),
    primary_relation_id: primary.id,
    expected_execution_fingerprint: group.execution_fingerprint,
    unselected_action: "keep_pending",
    source_id: group.source_id,
    target_id: group.target_id,
    relation_kind: primary.relation_kind || "",
    relation_type: suggested || primary.relation_type,
    description: primary.description || "",
    strength: Number(primary.strength ?? 0.5),
  }
}

function relationDecisionReusesCanonical(group, decision) {
  const outputs = decision.action === "accept_separately"
    ? decision.separate_relations || []
    : [decision]
  return outputs.some((output) => (group?.canonical_relations || []).some((relation) => (
    relation.source_id === output.source_id
    && relation.target_id === output.target_id
    && relation.relation_type === output.relation_type
  )))
}

/** 对应 vanilla _inlineEvidenceHtml；返回键值对数组供模板渲染。 */
export function inlineEvidencePairs(item = {}) {
  return [
    ["来源", reviewSourceLabel(item.source)],
    ["处理批次", item.workflow_id],
    ["章节", item.source_chapter_index],
    ["场景", item.scene_index || item.scene_id],
    ["置信度", item.confidence != null ? `${(Number(item.confidence) * 100).toFixed(0)}%` : ""],
    ["引用", item.quote],
  ].filter(([, value]) => value != null && String(value).trim() !== "")
}

/** 对应 vanilla _inlineRelationEvidenceHtml（2318-2349）。 */
export function inlineRelationEvidencePairs(relation = {}) {
  const reviewMeta = relation.review_meta && typeof relation.review_meta === "object"
    ? relation.review_meta
    : {}
  const sceneLabel = [
    reviewMeta.scene_id,
    reviewMeta.scene_index != null ? `序号 ${reviewMeta.scene_index}` : "",
  ].filter(Boolean).join("（")
  const normalizedSceneLabel = sceneLabel && reviewMeta.scene_id && reviewMeta.scene_index != null
    ? `${sceneLabel}）`
    : sceneLabel
  const evidenceRefs = Array.isArray(reviewMeta.evidence_refs)
    ? reviewMeta.evidence_refs.map((ref) => {
      if (ref == null) return ""
      if (typeof ref !== "object") return String(ref)
      const refScene = ref.scene_id || (ref.scene_index != null ? `场景 ${ref.scene_index}` : "")
      const refChapter = ref.source_chapter_index != null ? `章节 ${ref.source_chapter_index}` : ""
      return [refScene, refChapter, ref.quote || ref.evidence || ""].filter(Boolean).join(" · ")
    }).filter(Boolean).join("；")
    : ""
  return [
    ["来源", reviewSourceLabel(reviewMeta.source)],
    ["处理批次", reviewMeta.workflow_id],
    ["场景", normalizedSceneLabel],
    ["章节", reviewMeta.source_chapter_index ?? relation.source_chapter_id],
    ["强度", relation.strength != null ? `${Math.round(Number(relation.strength) * 100)}%` : ""],
    ["引用", relation.quote || reviewMeta.quote],
    ["证据", evidenceRefs],
  ].filter(([, value]) => value != null && String(value).trim() !== "")
}

/** 复制诊断信息（vanilla copy-review-diagnostic 绑定语义）。 */
export async function copyReviewDiagnostic(diagnostic) {
  const toast = getToast()
  try {
    await navigator.clipboard.writeText(diagnostic || "{}")
    toast("诊断信息已复制", "success")
  } catch {
    toast("复制失败", "error")
  }
}

// ============================================================
// 筛选导航（URL 是事实源；vanilla 3736-3861）
// ============================================================

function navigateReview(subView, query, { replace = false } = {}) {
  const router = getRouter()
  const kind = {
    "review-objects": "objects",
    "review-aliases": "aliases",
    "review-relations": "relations",
  }[subView] || "all"
  const unifiedQuery = new URLSearchParams(query?.toString?.() || "")
  if (kind !== "all") unifiedQuery.set("kind", kind)
  if (replace && router?.replace) {
    return router.replace("world", "review", unifiedQuery)
  }
  return router?.navigate("world", "review", true, unifiedQuery)
}

export function applyCandidateReviewFilters(form) {
  const filters = {
    q: String(form.q || "").trim(),
    entity_type: form.entity_type || "",
    suggested_action: form.suggested_action || "",
    source: String(form.source || "").trim(),
    workflow_id: String(form.workflow_id || "").trim(),
    scene_index: String(form.scene_index || "").trim(),
    source_chapter_index: String(form.source_chapter_index || "").trim(),
    confidence_min: String(form.confidence_min || "").trim(),
    confidence_max: String(form.confidence_max || "").trim(),
    skip: 0,
    limit: 20,
  }
  return navigateReview("review-objects", candidateQueryFromState(filters))
}

export function resetCandidateReviewFilters() {
  return navigateReview("review-objects", candidateQueryFromState({ skip: 0, limit: 20 }))
}

export function applyAliasReviewFilters(form, previousFilters) {
  const filters = {
    q: String(form.q || "").trim(),
    source: String(form.source || "").trim(),
    workflow_id: String(form.workflow_id || "").trim(),
    scene_index: String(form.scene_index || "").trim(),
    source_chapter_index: String(form.source_chapter_index || "").trim(),
    confidence_min: String(form.confidence_min || "").trim(),
    confidence_max: String(form.confidence_max || "").trim(),
    type_kind: form.type_kind || "",
    alias_kind: form.alias_kind || "",
    has_quote: form.has_quote ?? previousFilters.has_quote,
    multi_alias_only: previousFilters.multi_alias_only,
    skip: 0,
    limit: Number(form.limit || previousFilters.limit || 20),
  }
  return navigateReview("review-aliases", reviewQueryFromState(filters, WORLD_ALIAS_QUERY_KEYS))
}

export function resetAliasReviewFilters() {
  return navigateReview("review-aliases", reviewQueryFromState({ skip: 0, limit: 20 }, WORLD_ALIAS_QUERY_KEYS))
}

export function applyRelationReviewFilters(form, previousFilters) {
  const filters = {
    q: String(form.q || "").trim(),
    relation_type: String(form.relation_type || "").trim(),
    relation_kind: form.relation_kind || "",
    source_chapter_id: "",
    scene_index: String(form.scene_index || "").trim(),
    source_chapter_index: String(form.source_chapter_index || "").trim(),
    strength_min: String(form.strength_min || "").trim(),
    strength_max: String(form.strength_max || "").trim(),
    has_quote: form.has_quote ?? previousFilters.has_quote,
    type_kind: form.type_kind || "",
    multi_type_only: previousFilters.multi_type_only,
    has_reverse_candidates: previousFilters.has_reverse_candidates,
    has_canonical_relation: previousFilters.has_canonical_relation,
    skip: 0,
    limit: Number(form.limit || previousFilters.limit || 20),
  }
  return navigateReview("review-relations", reviewQueryFromState(filters, WORLD_RELATION_QUERY_KEYS))
}

export function resetRelationReviewFilters() {
  return navigateReview("review-relations", reviewQueryFromState({ skip: 0, limit: 20 }, WORLD_RELATION_QUERY_KEYS))
}

/** 对应 vanilla _setReviewQuickFilter。 */
export function setReviewQuickFilter(kind, key, value, currentFilters) {
  const filters = {
    ...currentFilters,
    [key]: String(currentFilters[key] ?? "") === String(value) ? "" : value,
    skip: 0,
  }
  const keys = kind === "alias" ? WORLD_ALIAS_QUERY_KEYS : WORLD_RELATION_QUERY_KEYS
  return navigateReview(`review-${kind === "alias" ? "aliases" : "relations"}`, reviewQueryFromState(filters, keys))
}

/** 对应 vanilla _removeReviewFilter。 */
export function removeReviewFilter(kind, key, currentFilters) {
  if (!(key in currentFilters)) return
  const filters = { ...currentFilters, [key]: "", skip: 0 }
  if (kind === "candidate") {
    return navigateReview("review-objects", candidateQueryFromState(filters))
  }
  const keys = kind === "alias" ? WORLD_ALIAS_QUERY_KEYS : WORLD_RELATION_QUERY_KEYS
  return navigateReview(`review-${kind === "alias" ? "aliases" : "relations"}`, reviewQueryFromState(filters, keys))
}

export function setCandidateTaskFilter(value, currentFilters) {
  const filters = {
    ...currentFilters,
    suggested_action: currentFilters.suggested_action === value ? "" : value,
    skip: 0,
  }
  return navigateReview("review-objects", candidateQueryFromState(filters))
}

/** 分页（vanilla _changeListPage 3832-3861；候选走 candidateQueryFromState）。 */
export function changeReviewPage(kind, delta, currentFilters, total) {
  const newSkip = currentFilters.skip + delta * currentFilters.limit
  if (newSkip < 0) return
  if (newSkip >= total) return
  const filters = { ...currentFilters, skip: newSkip }
  if (kind === "candidates") {
    return navigateReview("review-objects", candidateQueryFromState(filters))
  }
  if (kind === "alias") {
    return navigateReview("review-aliases", reviewQueryFromState(filters, WORLD_ALIAS_QUERY_KEYS))
  }
  return navigateReview("review-relations", reviewQueryFromState(filters, WORLD_RELATION_QUERY_KEYS))
}

// ============================================================
// 审阅决策（草稿落 worldSession）
// ============================================================

function aliasEvidenceHtml(item = {}) {
  const esc = getEsc()
  const evidence = inlineEvidencePairs(item)
  if (!evidence.length) return ""
  return `
    <div class="form-group">
      <label>证据</label>
      <div style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px;color:var(--text-muted);font-size:12px;">
        ${evidence.map(([label, value]) => `<div><strong>${esc(label)}：</strong>${esc(value)}</div>`).join("")}
      </div>
    </div>
  `
}

function findAlias(entityIdParam, aliasText) {
  return reviewRegistry.aliases.find((item) => item.entity_id === entityIdParam && item.alias === aliasText) || null
}

/** 加载可恢复的单条别名决策草稿。 */
export function prepareAliasReviewDecision(alias) {
  const key = aliasKey(alias)
  const draftState = loadReviewDraft("alias", key, alias.execution_fingerprint, worldSession.aliasReviewDrafts[key])
  if (draftState.stale) {
    delete worldSession.aliasReviewDrafts[key]
    clearStoredReviewDraft("alias", key)
    worldSession.aliasReviewErrors[key] = "内容已变化，请重新核对"
  }
  const draft = draftState.draft
  const selectedAliasType = draft && Object.hasOwn(draft, "alias_type")
    ? draft.alias_type
    : (alias.alias_type || "name")
  const aliasKindExplicit = draft ? Boolean(draft._kind_explicit) : Boolean(alias.alias_kind)
  const selectedAliasKind = draft && Object.hasOwn(draft, "alias_kind")
    ? draft.alias_kind
    : kindOrTypeDefault(reviewRegistry.reviewTypeCatalog, "alias", alias.alias_kind, selectedAliasType)
  return {
    stale: draftState.stale,
    draft: {
      target_entity_id: draft?.target_entity_id || alias.entity_id,
      alias: draft && Object.hasOwn(draft, "alias") ? draft.alias : alias.alias,
      alias_kind: selectedAliasKind,
      alias_type: selectedAliasType,
      _kind_explicit: aliasKindExplicit,
    },
  }
}

/** 持久化右侧决策区的当前别名草稿。 */
export function persistAliasReviewDecision(alias, draft) {
  const key = aliasKey(alias)
  const next = {
    expected_execution_fingerprint: alias.execution_fingerprint,
    target_entity_id: draft.target_entity_id || "",
    alias: draft.alias ?? "",
    alias_kind: draft.alias_kind || "",
    alias_type: draft.alias_type || "",
    _kind_explicit: Boolean(draft._kind_explicit),
  }
  worldSession.aliasReviewDrafts[key] = next
  storeReviewDraft("alias", key, next)
  return next
}

/** 加载可恢复的单组关系决策；首次进入只预填关系内容，端点由作者配对。 */
export function prepareRelationReviewDecision(group) {
  const key = group?.group_id || ""
  const fallback = recommendedRelationDecision(group)
  if (!key || !fallback) return { stale: false, draft: null }
  const draftState = loadReviewDraft("relation", key, group.execution_fingerprint, worldSession.relationReviewDrafts[key])
  if (draftState.stale) {
    delete worldSession.relationReviewDrafts[key]
    clearStoredReviewDraft("relation", key)
    worldSession.relationReviewErrors[key] = "内容已变化，请重新核对"
  }
  const draft = draftState.draft
  const relationType = draft && Object.hasOwn(draft, "relation_type")
    ? draft.relation_type
    : fallback.relation_type
  const kindExplicit = draft ? Boolean(draft._kind_explicit) : Boolean(fallback.relation_kind)
  const relationKind = draft && Object.hasOwn(draft, "relation_kind")
    ? draft.relation_kind
    : kindOrTypeDefault(reviewRegistry.reviewTypeCatalog, "relation", fallback.relation_kind, relationType)
  return {
    stale: draftState.stale,
    draft: {
      ...fallback,
      source_id: draft && Object.hasOwn(draft, "source_id") ? draft.source_id : "",
      target_id: draft && Object.hasOwn(draft, "target_id") ? draft.target_id : "",
      relation_kind: relationKind,
      relation_type: relationType,
      description: draft && Object.hasOwn(draft, "description") ? draft.description : fallback.description,
      strength: Number(draft?.strength ?? fallback.strength),
      _kind_explicit: kindExplicit,
    },
  }
}

/** 持久化右侧决策区的当前关系草稿，处理范围沿用本组推荐结果。 */
export function persistRelationReviewDecision(group, draft) {
  const fallback = recommendedRelationDecision(group)
  if (!fallback) return null
  const next = {
    ...fallback,
    expected_execution_fingerprint: group.execution_fingerprint,
    source_id: draft?.source_id || "",
    target_id: draft?.target_id || "",
    relation_kind: draft?.relation_kind || "",
    relation_type: draft?.relation_type || "",
    description: draft?.description ?? "",
    strength: Number(draft?.strength ?? 0.5),
    _kind_explicit: Boolean(draft?._kind_explicit),
  }
  worldSession.relationReviewDrafts[group.group_id] = next
  storeReviewDraft("relation", group.group_id, next)
  return next
}

/** 对应 vanilla showAliasReviewEditForm。 */
export function showAliasReviewEditForm(entityIdParam, aliasText) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const alias = findAlias(entityIdParam, aliasText)
  if (!alias) {
    toast("未找到目标别名", "error")
    return
  }
  const selectedAliasType = alias.alias_type || "name"
  const selectedAliasKind = kindOrTypeDefault(reviewRegistry.reviewTypeCatalog, "alias", alias.alias_kind, selectedAliasType)
  const formHtml = `
    <div class="form-group">
      <label>目标对象 *</label>
      <div id="alias-target-picker"></div>
      <input type="hidden" id="alias-target-id" data-modal-dirty-track value="${esc(entityIdParam)}" />
    </div>
    <div class="form-group">
      <label>别名文本 *</label>
      <input class="form-input" id="alias-edit-text" value="${esc(alias.alias || "")}" />
    </div>
    <div class="form-group">
      <label for="alias-edit-kind">别名分类</label>
      <select class="form-select" id="alias-edit-kind" aria-describedby="alias-edit-kind-help">${kindOptionsHtml(reviewRegistry.reviewTypeCatalog, "alias", selectedAliasKind, esc)}</select>
      <div class="form-help" id="alias-edit-kind-help">用于 AI 检索的通用分类。</div>
    </div>
    <div class="form-group">
      <label for="alias-edit-type">详细类型</label>
      <select class="form-select" id="alias-edit-type">${detailTypeOptionsHtml(reviewRegistry.reviewTypeCatalog, "alias", selectedAliasType, esc)}</select>
      <div id="alias-edit-type-custom-wrap" hidden><label for="alias-edit-type-custom">自定义详细类型</label><input class="form-input" id="alias-edit-type-custom" maxlength="20" value="${esc(selectedAliasType)}" /></div>
    </div>
    ${aliasEvidenceHtml(alias)}
  `
  showModalHtml("编辑后采用别名", formHtml, [{
    text: "保存并采用",
    class: "btn-primary",
    handler: async () => {
      const targetId = document.getElementById("alias-target-id")?.value
      const text = document.getElementById("alias-edit-text")?.value?.trim()
      const aliasKind = document.getElementById("alias-edit-kind")?.value || ""
      const type = readDetailType(document.getElementById("alias-edit-type"), document.getElementById("alias-edit-type-custom"))
      if (!targetId || !text || !aliasKind || !type) {
        toast("请选择目标对象、别名分类并输入别名和详细类型", "warning")
        return false
      }
      try {
        await getApi().world.editAlias(entityIdParam, aliasText, {
          target_entity_id: targetId,
          alias: text,
          alias_kind: aliasKind,
          alias_type: type,
          confirm_review: true,
        }, { novel_id: getAppState()?.currentProjectId })
        toast("别名已保存并采用", "success")
        getRouter()?.refresh?.()
      } catch (err) {
        toast(err.message || "保存失败", "error")
        return false
      }
    },
  }])
  bindTypeKindControls({
    typeSelect: document.getElementById("alias-edit-type"),
    customInput: document.getElementById("alias-edit-type-custom"),
    customContainer: document.getElementById("alias-edit-type-custom-wrap"),
    kindSelect: document.getElementById("alias-edit-kind"),
    kindHelp: document.getElementById("alias-edit-kind-help"),
    catalog: reviewRegistry.reviewTypeCatalog,
    domain: "alias",
    kindExplicit: Boolean(alias.alias_kind),
  })
  mountEntityReferencePickerForReview({
    rootId: "alias-target-picker",
    inputId: "alias-target-id",
    selectedId: entityIdParam,
    selectedName: alias.entity_name || "当前对象",
  })
  globalThis.refreshModalFormBaseline?.()
}

/** 模态内复制诊断按钮绑定（vanilla _bindReviewDiagnosticCopyButtons）。 */
function bindDiagnosticCopyButtons(root = document) {
  root?.querySelectorAll?.('[data-action="copy-review-diagnostic"]').forEach((button) => {
    if (button.dataset.reviewDiagnosticBound === "true") return
    button.dataset.reviewDiagnosticBound = "true"
    button.addEventListener("click", async (event) => {
      event.preventDefault()
      await copyReviewDiagnostic(button.getAttribute("data-diagnostic") || "{}")
    })
  })
}


/** 对应 vanilla showRelationReviewEditForm。 */
export function showRelationReviewEditForm(relationId) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const relation = reviewRegistry.relations.find((item) => (item.id || item.relationship_id) === relationId)
  if (!relation) {
    toast("未找到目标关系", "error")
    return
  }
  const selectedType = relation.relation_type || ""
  const selectedKind = kindOrTypeDefault(reviewRegistry.reviewTypeCatalog, "relation", relation.relation_kind, selectedType)
  const optionsHtml = (selectedId) => relationEntityOptionsHtml(selectedId)
  const evidence = reviewEvidenceSummary({
    ...(relation.review_meta || {}),
    source_chapter_index: relation.review_meta?.source_chapter_index ?? relation.source_chapter_id,
    quote: relation.quote || relation.review_meta?.quote,
  }, "relation", relation.strength)
  const formHtml = `
    <div class="form-group">
      <label>源对象</label>
      <select class="form-select" id="rel-review-source">${optionsHtml(relation.source_id)}</select>
    </div>
    <div class="form-group">
      <label for="rel-review-kind">关系分类</label>
      <select class="form-select" id="rel-review-kind" aria-describedby="rel-review-kind-help">${kindOptionsHtml(reviewRegistry.reviewTypeCatalog, "relation", selectedKind, esc)}</select>
      <div class="form-help" id="rel-review-kind-help">用于 AI 检索的通用分类。</div>
    </div>
    <div class="form-group">
      <label for="rel-review-type">详细类型</label>
      <select class="form-select" id="rel-review-type">${detailTypeOptionsHtml(reviewRegistry.reviewTypeCatalog, "relation", selectedType, esc)}</select>
      <div id="rel-review-type-custom-wrap" hidden><label for="rel-review-type-custom">自定义详细类型</label><input class="form-input" id="rel-review-type-custom" value="${esc(selectedType)}" /></div>
    </div>
    <div class="form-group">
      <label>目标对象</label>
      <select class="form-select" id="rel-review-target">${optionsHtml(relation.target_id)}</select>
    </div>
    <div class="form-group">
      <label>描述</label>
      <textarea class="form-textarea" id="rel-review-description" rows="3">${esc(relation.description || "")}</textarea>
    </div>
    <div class="form-group">
      <label>强度</label>
      <input class="form-input" id="rel-review-strength" type="number" min="0" max="1" step="0.01" value="${esc(relation.strength ?? 0.5)}" />
    </div>
    <div class="review-evidence-summary">
      <span>${esc(evidence.summary)}</span>
      ${evidence.quote ? `<blockquote>${esc(evidence.quote)}</blockquote>` : '<span class="world-text-dim">无原文引用</span>'}
      <details>
        <summary>诊断信息</summary>
        <pre>${esc(evidence.diagnostic)}</pre>
        <button class="btn btn-sm" data-action="copy-review-diagnostic" data-diagnostic="${esc(evidence.diagnostic)}">复制诊断信息</button>
      </details>
    </div>
  `
  showModalHtml("编辑后采用关系", formHtml, [{
    text: "采用", class: "btn-primary", handler: async () => {
      const sourceId = document.getElementById("rel-review-source")?.value || ""
      const targetId = document.getElementById("rel-review-target")?.value || ""
      const relationKind = document.getElementById("rel-review-kind")?.value || ""
      const relationType = readDetailType(document.getElementById("rel-review-type"), document.getElementById("rel-review-type-custom"))
      if (!sourceId || !targetId || !relationKind || !relationType) {
        toast("请填写源对象、目标对象、关系分类和详细类型", "warning")
        return false
      }
      try {
        await getApi().world.reviewEditRelationship(relationId, {
          source_id: sourceId,
          target_id: targetId,
          relation_kind: relationKind,
          relation_type: relationType,
          description: document.getElementById("rel-review-description")?.value?.trim() || "",
          strength: Number(document.getElementById("rel-review-strength")?.value || 0.5),
          confirm_review: true,
        }, getAppState()?.currentProjectId)
        closeModal()
        toast("关系已采用", "success")
        getRouter()?.refresh?.()
      } catch (err) {
        toast(err.message || "采用关系失败", "error")
        return false
      }
    },
  }])
  bindTypeKindControls({
    typeSelect: document.getElementById("rel-review-type"),
    customInput: document.getElementById("rel-review-type-custom"),
    customContainer: document.getElementById("rel-review-type-custom-wrap"),
    kindSelect: document.getElementById("rel-review-kind"),
    kindHelp: document.getElementById("rel-review-kind-help"),
    catalog: reviewRegistry.reviewTypeCatalog,
    domain: "relation",
    kindExplicit: Boolean(relation.relation_kind),
  })
  bindDiagnosticCopyButtons(document.getElementById("modal-body"))
}

/** 对应 vanilla _relationEntityOptionsHtml（候选+实体合并去重、排除历史态）。 */
function relationEntityOptionsHtml(selectedId = "") {
  const esc = getEsc()
  const items = [...reviewRegistry.entities, ...reviewRegistry.candidates]
    .filter((item) => !["merged", "ignored", "deprecated"].includes(item.status))
  const seen = new Set()
  const options = []
  for (const item of items) {
    const id = entityId(item)
    if (!id || seen.has(id)) continue
    seen.add(id)
    const label = `${item.name || id} (${item.entity_type || "-"})`
    options.push(`<option value="${esc(id)}" ${id === selectedId ? "selected" : ""}>${esc(label)}</option>`)
  }
  if (!seen.has(selectedId) && selectedId) {
    options.unshift(`<option value="${esc(selectedId)}" selected>${esc(selectedId)}</option>`)
  }
  return options.length ? options.join("") : `<option value="">暂无对象</option>`
}

// ============================================================
// 批量复核（vanilla 4165-4270 + candidates 批量 4354-4420）
// ============================================================

/** 对应 vanilla _reviewBatchToast。 */
function reviewBatchToast(result, noun) {
  const toast = getToast()
  const succeeded = Number(result?.succeeded_count || 0)
  const stale = Number(result?.stale_count || 0)
  const failed = Number(result?.failed_count || 0)
  const message = `已处理 ${succeeded} 个${noun}${stale ? `，${stale} 个已过期` : ""}${failed ? `，${failed} 个失败` : ""}`
  toast(message, stale || failed ? "warning" : "success")
}

/** 对应 vanilla _reviewBatchItemError。 */
function reviewBatchItemError(item) {
  const prefix = item?.status === "stale" ? "已过期" : "处理失败"
  return `${prefix}：${item?.message || item?.error_code || "请刷新后重试"}`
}

export async function acceptAliasReviewDecision(item, draft) {
  const key = aliasKey(item)
  const targetId = String(draft?.target_entity_id || "").trim()
  const text = String(draft?.alias || "").trim()
  const aliasKind = String(draft?.alias_kind || "").trim()
  const aliasType = String(draft?.alias_type || "").trim()
  if (!targetId || !text || !aliasKind || !aliasType) {
    getToast()("请选择目标对象、别名分类并填写别名和详细类型", "warning")
    return false
  }
  const decision = {
    client_decision_id: `alias-${String(item.entity_id || "").slice(0, 16)}-${Date.now().toString(36)}`.slice(0, 64),
    action: "accept",
    entity_id: item.entity_id,
    original_alias: item.alias,
    expected_execution_fingerprint: item.execution_fingerprint,
    target_entity_id: targetId,
    alias: text,
    alias_kind: aliasKind,
    alias_type: aliasType,
  }
  persistAliasReviewDecision(item, { ...draft, ...decision })
  worldSession.processingReviewIds[key] = true
  try {
    const result = await getApi().world.reviewAliasesBatch({ confirmed: true, decisions: [decision] }, getAppState()?.currentProjectId)
    const response = result?.results?.[0]
    if (response && response.status !== "success") {
      worldSession.aliasReviewErrors[key] = reviewBatchItemError(response)
      getToast()(worldSession.aliasReviewErrors[key], "warning")
      return false
    }
    delete worldSession.aliasReviewErrors[key]
    delete worldSession.aliasReviewDrafts[key]
    clearStoredReviewDraft("alias", key)
    worldSession.reviewReceipt = { targetKey: key, title: "别名已完成", detail: `“${text}”已归属到${draft?.target_entity_name || item.entity_name || "选定对象"}。` }
    getToast()("别名已采用", "success")
    await getRouter()?.refresh?.()
    return true
  } catch (err) {
    worldSession.aliasReviewErrors[key] = err.message || "处理失败，请重试"
    getToast()(worldSession.aliasReviewErrors[key], "error")
    return false
  } finally {
    delete worldSession.processingReviewIds[key]
  }
}

export async function acceptAliasReviewItem(item) {
  if (!item.alias_kind) {
    getToast()("请先选择别名分类", "warning")
    return false
  }
  return acceptAliasReviewDecision(item, {
    target_entity_id: item.entity_id,
    target_entity_name: item.entity_name,
    alias: item.alias,
    alias_kind: item.alias_kind,
    alias_type: item.alias_type,
  })
}

export function acceptRelationReviewDecision(group, draft) {
  const decision = persistRelationReviewDecision(group, draft)
  if (!decision) return false
  if (!decision.source_id || !decision.target_id || !decision.relation_kind || !decision.relation_type) {
    getToast()("请完成两个人物的配对，并选择关系分类和详细类型", "warning")
    return false
  }
  if (decision.source_id === decision.target_id) {
    getToast()("关系两端不能是同一个对象", "warning")
    return false
  }
  const run = async () => {
    worldSession.processingReviewIds[group.group_id] = true
    try {
      const result = await getApi().world.reviewRelationsBatch({ confirmed: true, decisions: [reviewDecisionPayload(decision)] }, getAppState()?.currentProjectId)
      const response = result?.results?.[0]
      if (response && response.status !== "success") {
        worldSession.relationReviewErrors[group.group_id] = reviewBatchItemError(response)
        getToast()(worldSession.relationReviewErrors[group.group_id], "warning")
        return false
      }
      delete worldSession.relationReviewErrors[group.group_id]
      delete worldSession.relationReviewDrafts[group.group_id]
      clearStoredReviewDraft("relation", group.group_id)
      const adopted = response?.canonical_relation_ids?.length || (response?.canonical_relation_id ? 1 : 0)
      const reused = response?.reused_canonical_relation_ids?.length || 0
      const remaining = response?.remaining_candidate_ids?.length ?? Math.max(0, (group.members || []).length - decision.member_relation_ids.length)
      worldSession.reviewReceipt = {
        targetKey: group.group_id,
        title: "关系已完成",
        detail: `采用 ${adopted || 1} 条${reused ? `，复用已有 ${reused} 条` : ""}，仍待处理 ${remaining} 条。`,
      }
      getToast()("关系决策已保存", "success")
      await getRouter()?.refresh?.()
      return true
    } catch (err) {
      worldSession.relationReviewErrors[group.group_id] = err.message || "处理失败，请重试"
      getToast()(worldSession.relationReviewErrors[group.group_id], "error")
      return false
    } finally {
      delete worldSession.processingReviewIds[group.group_id]
    }
  }
  if (decision.action === "merge" || relationDecisionReusesCanonical(group, decision)) {
    const message = decision.action === "merge"
      ? `将 ${decision.member_relation_ids.length} 条证据归并为一条正式关系，确定继续吗？`
      : "将候选证据并入已有正式关系，确定继续吗？"
    getConfirmAction()(message, run, "确认采用")
    return false
  }
  return run()
}

export function acceptRecommendedRelation(group) {
  return acceptRelationReviewDecision(group, recommendedRelationDecision(group))
}

/** 组清空后回退到最后一个有效页；下一组仍由作者在队列中选择。 */
async function advanceRelationReview() {
  const groups = reviewRegistry.relationGroups
  if (!groups.length && reviewRegistry.relationGroupTotal > 0 && reviewRegistry.relationFilters.skip > 0) {
    const content = document.getElementById("workspace-content")
    const scrollTop = content?.scrollTop || 0
    const skip = Math.max(0, Math.floor((reviewRegistry.relationGroupTotal - 1) / reviewRegistry.relationFilters.limit) * reviewRegistry.relationFilters.limit)
    await navigateReview("review-relations", reviewQueryFromState({ ...reviewRegistry.relationFilters, skip }, WORLD_RELATION_QUERY_KEYS), { replace: true })
    const liveContent = document.getElementById("workspace-content")
    if (liveContent) liveContent.scrollTop = scrollTop
  }
}

/** 当前页别名处理完后回退到最后一个有效页。 */
async function advanceAliasReview() {
  const aliases = reviewRegistry.aliases
  if (!aliases.length && reviewRegistry.aliasGroupTotal > 0 && reviewRegistry.aliasFilters.skip > 0) {
    const content = document.getElementById("workspace-content")
    const scrollTop = content?.scrollTop || 0
    const skip = Math.max(0, Math.floor((reviewRegistry.aliasGroupTotal - 1) / reviewRegistry.aliasFilters.limit) * reviewRegistry.aliasFilters.limit)
    await navigateReview("review-aliases", reviewQueryFromState({ ...reviewRegistry.aliasFilters, skip }, WORLD_ALIAS_QUERY_KEYS), { replace: true })
    const liveContent = document.getElementById("workspace-content")
    if (liveContent) liveContent.scrollTop = scrollTop
  }
}

/** 对应 vanilla _applyRelationReviewBatch。 */
export function applyRelationReviewBatch(groups, ignoreAll = false) {
  const toast = getToast()
  const decisions = []
  let hasStaleDraft = false
  for (const group of groups) {
    if (ignoreAll) {
      decisions.push({
        client_decision_id: group.group_id,
        action: "ignore",
        group_id: group.group_id,
        member_relation_ids: (group.members || []).map((item) => item.id),
        expected_execution_fingerprint: group.execution_fingerprint,
      })
    } else if (worldSession.relationReviewDrafts[group.group_id]) {
      const draft = worldSession.relationReviewDrafts[group.group_id]
      if (draft.expected_execution_fingerprint !== group.execution_fingerprint) {
        hasStaleDraft = true
      } else {
        decisions.push(reviewDecisionPayload(draft))
      }
    }
  }
  if (hasStaleDraft) {
    toast("所选关系的内容已变化，请重新打开并确认决策", "warning")
    return
  }
  if (!ignoreAll && decisions.length !== groups.length) {
    toast("所选关系组中仍有未准备决策的项目", "warning")
    return
  }
  if (!ignoreAll && decisions.some((decision) => (
    ["accept", "merge"].includes(decision.action)
      ? !decision.relation_kind
      : decision.action === "accept_separately" && (decision.separate_relations || []).some((item) => !item.relation_kind)
  ))) {
    toast("所选关系决策中有待分类项，请先选择关系分类", "warning")
    return
  }
  const relationCount = decisions.reduce((sum, decision) => sum + (decision.member_relation_ids || []).length, 0)
  if (decisions.length > 20 || relationCount > 50) {
    toast(`单次最多处理 20 个关系决策、50 条所选关系；当前为 ${decisions.length} 个决策、${relationCount} 条关系。请减少选择后重试。`, "warning")
    return
  }
  getConfirmAction()(
    ignoreAll
      ? `确定忽略所选 ${groups.length} 个关系组吗？候选会进入历史并保留审计。`
      : `确定应用所选 ${decisions.length} 个关系决策吗？请确认归并范围和最终类型。`,
    async () => {
      const toast2 = getToast()
      try {
        const result = await getApi().world.reviewRelationsBatch({ confirmed: true, decisions }, getAppState()?.currentProjectId)
        const selection = getBulkSelection("world-relation-groups")
        for (const item of result.results || []) {
          if (item.status === "success") {
            delete worldSession.relationReviewDrafts[item.client_decision_id]
            delete worldSession.relationReviewErrors[item.client_decision_id]
            clearStoredReviewDraft("relation", item.client_decision_id)
            selection.delete(item.client_decision_id)
          } else {
            worldSession.relationReviewErrors[item.client_decision_id] = reviewBatchItemError(item)
          }
        }
        reviewBatchToast(result, "关系组")
        getRouter()?.refresh?.()
        await advanceRelationReview()
      } catch (err) {
        for (const group of groups) worldSession.relationReviewErrors[group.group_id] = err.message || "网络异常，请重试"
        toast2(err.message || "关系批量复核失败，已保留当前决策草稿", "error")
        getRouter()?.refresh?.()
      }
    },
    ignoreAll ? "确认忽略" : "确认应用",
  )
}

/** 对应 vanilla _applyAliasReviewBatch。 */
export function applyAliasReviewBatch(items, action) {
  const toast = getToast()
  if (items.length > 50) {
    toast(`单次最多处理 50 条别名；当前已选 ${items.length} 条。请减少选择后重试。`, "warning")
    return
  }
  const drafts = new Map(items.map((item) => [aliasKey(item), worldSession.aliasReviewDrafts[aliasKey(item)] || null]))
  if (action === "accept" && items.some((item) => {
    const draft = drafts.get(aliasKey(item))
    return draft && draft.expected_execution_fingerprint !== item.execution_fingerprint
  })) {
    toast("所选别名的内容已变化，请重新打开并确认", "warning")
    return
  }
  if (action === "accept" && items.some((item) => {
    const draft = drafts.get(aliasKey(item))
    const effectiveKind = draft && Object.hasOwn(draft, "alias_kind") ? draft.alias_kind : item.alias_kind
    return !effectiveKind
  })) {
    toast("所选别名中有待分类项，请先选择别名分类", "warning")
    return
  }
  const decisionKeys = new Map()
  const decisions = items.map((item, index) => {
    const key = aliasKey(item)
    const draft = reviewDecisionPayload(drafts.get(key) || {})
    const clientDecisionId = `alias-${index}-${String(item.entity_id || "").slice(0, 16)}`
    decisionKeys.set(clientDecisionId, key)
    return {
      client_decision_id: clientDecisionId,
      action,
      entity_id: item.entity_id,
      original_alias: item.alias,
      expected_execution_fingerprint: item.execution_fingerprint,
      ...(action === "accept" ? {
        target_entity_id: item.entity_id,
        alias: item.alias,
        alias_kind: item.alias_kind,
        alias_type: item.alias_type,
        ...draft,
      } : {}),
    }
  })
  getConfirmAction()(
    action === "ignore"
      ? `确定忽略所选 ${items.length} 个别名吗？条目会进入历史并保留证据。`
      : `确定采用所选 ${items.length} 个别名吗？未编辑条目会原样采用。`,
    async () => {
      try {
        const result = await getApi().world.reviewAliasesBatch({ confirmed: true, decisions }, getAppState()?.currentProjectId)
        const selection = getBulkSelection("world-aliases")
        for (const item of result.results || []) {
          const key = decisionKeys.get(item.client_decision_id)
          if (item.status === "success") {
            delete worldSession.aliasReviewDrafts[key]
            delete worldSession.aliasReviewErrors[key]
            clearStoredReviewDraft("alias", key)
            selection.delete(key)
          } else if (key) {
            worldSession.aliasReviewErrors[key] = reviewBatchItemError(item)
          }
        }
        if (items.length === 1 && result?.results?.[0]?.status === "success") {
          const item = items[0]
          worldSession.reviewReceipt = {
            targetKey: aliasKey(item),
            title: "别名已完成",
            detail: action === "ignore"
              ? `“${item.alias}”已忽略，来源证据已保留。`
              : `“${item.alias}”已归属到${item.entity_name || "当前对象"}。`,
          }
        }
        reviewBatchToast(result, "别名")
        getRouter()?.refresh?.()
        await advanceAliasReview()
      } catch (err) {
        for (const item of items) worldSession.aliasReviewErrors[aliasKey(item)] = err.message || "网络异常，请重试"
        getToast()(err.message || "别名批量复核失败，已保留当前编辑草稿", "error")
        getRouter()?.refresh?.()
      }
    },
    action === "ignore" ? "确认忽略" : "确认采用",
  )
}

/** 对应 vanilla _executeBulkAction 的 candidates 分支（accept-candidates/ignore-candidates）。 */
async function executeCandidatesBulkAction(action, items) {
  const toast = getToast()
  const label = action === "accept-candidates" ? "批量采用" : "批量忽略/设为临时"
  let actionable = items
  if (action === "accept-candidates") {
    actionable = items.filter((item) => {
      const action2 = candidateAction(item)
      const unresolvedAliasTarget = ["link_to_existing", "alias_of_existing"].includes(action2)
        && !hasResolvedCandidateTarget(item)
      return isSuggestionShadow(item)
        || unresolvedAliasTarget
        || !["temporary_only", "ignore", "link_to_existing", "alias_of_existing", "merge_with_existing"].includes(action2)
    })
  }
  if (actionable.length === 0) {
    toast("所选项目没有可执行的批量动作", "warning")
    return
  }
  const result = await runBulkAction(actionable, async (item) => {
    if (action === "accept-candidates") {
      await adoptEntity(item)
    } else {
      await ignoreEntity(item)
    }
  })
  toast(bulkResultMessage(result, label, (item) => item.name || entityId(item)), result.failed.length ? "warning" : "success")
  clearBulkSelection("world-candidates")
  getRouter()?.refresh?.()
}

/** review 侧的 _runBulkAction 分派（vanilla 4085-4124）。 */
export function runReviewBulkAction(scope, action, visibleItems) {
  const toast = getToast()
  const selection = getBulkSelection(scope)
  const idGetter = scope === "world-relation-groups"
    ? (item) => item.group_id
    : scope === "world-aliases"
      ? (item) => aliasKey(item)
      : (item) => entityId(item)
  const items = selectedItemsFrom(visibleItems, selection, idGetter)
  if (items.length === 0) {
    toast("请先选择要处理的项目", "warning")
    return
  }
  if (scope === "world-relation-groups" && ["apply-relation-decisions", "ignore-relation-groups"].includes(action)) {
    applyRelationReviewBatch(items, action === "ignore-relation-groups")
    return
  }
  if (scope === "world-aliases" && ["review-aliases-batch", "ignore-aliases-batch"].includes(action)) {
    applyAliasReviewBatch(items, action === "ignore-aliases-batch" ? "ignore" : "accept")
    return
  }
  const labelByAction = {
    "accept-candidates": "批量采用",
    "ignore-candidates": "批量忽略/设为临时",
  }
  const danger = action?.includes("delete") || action?.includes("ignore")
  getConfirmAction()(
    `确定对选中的 ${items.length} 项执行「${labelByAction[action] || action}」吗？`,
    async () => {
      await executeCandidatesBulkAction(action, items)
    },
    danger ? "确认执行" : "确认",
  )
}

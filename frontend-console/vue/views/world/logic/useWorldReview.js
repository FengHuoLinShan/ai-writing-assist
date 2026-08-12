/**
 * useWorldReview — world review（待处理）三队列的逻辑层。
 *
 * 对应 vanilla worldView 的候选分组/动作可见性（1710-1886）、证据摘要
 * （2032-2043, 2232-2258）、别名/关系决策模态与批量复核（4165-4270 +
 * 决策表单）。列表数据是 island props（只读），模态需要按 id 查找，
 * 因此维护 reviewRegistry（WorldReviewTab 在 props 变化时同步）。
 * 草稿/错误/批量选择落 worldSession（见 worldSession.js 进入协调语义）。
 */
import { getApi, getAppState, getCloseModal, getConfirmAction, getEsc, getRouter, getShowModalHtml, getToast } from "../../../bridge/index.js"
import { worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { worldSession } from "../worldSession.js"
import {
  WORLD_SUGGESTED_ACTION_LABELS,
  WORLD_ALIAS_QUERY_KEYS,
  WORLD_RELATION_QUERY_KEYS,
  REVIEW_ALIAS_TYPE_FALLBACK,
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
  reviewTypeCatalog: { alias_types: REVIEW_ALIAS_TYPE_FALLBACK, relation_types: REVIEW_RELATION_TYPE_FALLBACK },
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
  const catalog = reviewRegistry.reviewTypeCatalog || {}
  const items = kind === "alias" ? catalog.alias_types : catalog.relation_types
  const match = (items || []).find((item) => item.value === value)
  return match ? `${match.label} (${value})` : value || "-"
}

/** 对应 vanilla _reviewEvidenceSummaryHtml；返回渲染模型而非 HTML。 */
export function reviewEvidenceSummary(item = {}, kind = "alias", numericValue = null) {
  const source = item.source === "deep_import" ? "深度导入" : item.source
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

/** 对应 vanilla _inlineEvidenceHtml；返回键值对数组供模板渲染。 */
export function inlineEvidencePairs(item = {}) {
  return [
    ["来源", item.source === "deep_import" ? "深度导入" : item.source],
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
    ["来源", reviewMeta.source === "deep_import" ? "深度导入" : reviewMeta.source],
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
  if (replace && router?.replace) {
    return router.replace("world", subView, query)
  }
  return router?.navigate("world", subView, true, query)
}

export function applyCandidateReviewFilters(form) {
  const filters = {
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
    confidence_max: previousFilters.confidence_max || "",
    type_kind: form.type_kind || "",
    has_quote: previousFilters.has_quote,
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
    source_chapter_id: "",
    scene_index: String(form.scene_index || "").trim(),
    source_chapter_index: String(form.source_chapter_index || "").trim(),
    strength_min: String(form.strength_min || "").trim(),
    strength_max: previousFilters.strength_max,
    has_quote: previousFilters.has_quote,
    type_kind: form.type_kind || "",
    multi_type_only: previousFilters.multi_type_only,
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
  const filters = { ...currentFilters, [key]: value, skip: 0 }
  const keys = kind === "alias" ? WORLD_ALIAS_QUERY_KEYS : WORLD_RELATION_QUERY_KEYS
  return navigateReview(`review-${kind === "alias" ? "aliases" : "relations"}`, reviewQueryFromState(filters, keys))
}

/** 对应 vanilla _removeReviewFilter。 */
export function removeReviewFilter(kind, key, currentFilters) {
  if (!(key in currentFilters)) return
  const filters = { ...currentFilters, [key]: "", skip: 0 }
  const keys = kind === "alias" ? WORLD_ALIAS_QUERY_KEYS : WORLD_RELATION_QUERY_KEYS
  return navigateReview(`review-${kind === "alias" ? "aliases" : "relations"}`, reviewQueryFromState(filters, keys))
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
// 决策模态（草稿落 worldSession）
// ============================================================

function aliasTypeOptionsHtml(selected = "alias") {
  const esc = getEsc()
  const types = [...(reviewRegistry.reviewTypeCatalog.alias_types || REVIEW_ALIAS_TYPE_FALLBACK)]
  if (selected && !types.some((item) => item.value === selected)) {
    types.unshift({ value: selected, label: `保留原类型：${selected}`, category: "自定义" })
  }
  return types
    .map((item) => `<option value="${esc(item.value)}" ${selected === item.value ? "selected" : ""}>${esc(item.label)}${item.category === "自定义" ? "" : ` (${esc(item.value)})`}</option>`)
    .join("")
}

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

/** 对应 vanilla showAliasReviewDecisionForm。 */
export function showAliasReviewDecisionForm(entityIdParam, aliasText) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const alias = findAlias(entityIdParam, aliasText)
  if (!alias) {
    toast("未找到目标别名", "error")
    return
  }
  const key = aliasKey(alias)
  const draft = worldSession.aliasReviewDrafts[key]
  const selectedTargetId = draft?.target_entity_id || entityIdParam
  const suggested = alias.suggested_alias_type && alias.suggested_alias_type !== alias.alias_type
    ? `<button class="btn btn-sm" type="button" id="alias-use-type-suggestion">使用建议：${esc(reviewTypeLabel("alias", alias.suggested_alias_type))}</button>`
    : ""
  const evidence = reviewEvidenceSummary(alias, "alias", alias.confidence)
  const body = `
    <div class="review-decision-layout">
    <div class="form-group"><label>目标对象</label><div id="alias-target-picker"></div><input type="hidden" id="alias-target-id" value="${esc(selectedTargetId)}" /></div>
    <div class="form-group"><label for="alias-edit-text">别名文本</label><input class="form-input" id="alias-edit-text" value="${esc(draft?.alias || alias.alias)}" /></div>
    <div class="form-group"><label for="alias-edit-type">别名类型</label><select class="form-select" id="alias-edit-type">${aliasTypeOptionsHtml(draft?.alias_type || alias.alias_type || "alias")}</select>${suggested}</div>
    <div class="review-evidence-summary">
      <span>${esc(evidence.summary)}</span>
      ${evidence.quote ? `<blockquote>${esc(evidence.quote)}</blockquote>` : '<span class="world-text-dim">无原文引用</span>'}
      <details>
        <summary>诊断信息</summary>
        <pre>${esc(evidence.diagnostic)}</pre>
        <button class="btn btn-sm" data-action="copy-review-diagnostic" data-diagnostic="${esc(evidence.diagnostic)}">复制诊断信息</button>
      </details>
    </div>
    <p class="form-help">来源、场景、引用和置信度只读；保存这里只准备决策，最后仍需批量确认。</p>
    </div>
  `
  showModalHtml("准备别名复核决策", body, [{
    text: "保存决策",
    class: "btn-primary",
    handler: async () => {
      const targetId = document.getElementById("alias-target-id")?.value || ""
      const text = document.getElementById("alias-edit-text")?.value?.trim() || ""
      const aliasType = document.getElementById("alias-edit-type")?.value || ""
      if (!targetId || !text || !aliasType) {
        toast("请选择目标对象并填写别名和类型", "warning")
        return false
      }
      worldSession.aliasReviewDrafts[key] = {
        target_entity_id: targetId,
        alias: text,
        alias_type: aliasType,
      }
      delete worldSession.aliasReviewErrors[key]
      closeModal()
    },
  }], { size: "large" })
  bindDiagnosticCopyButtons()
  mountEntityReferencePickerForReview({
    rootId: "alias-target-picker",
    inputId: "alias-target-id",
    selectedId: selectedTargetId,
    selectedName: alias.entity_name || "当前对象",
  })
  globalThis.refreshModalFormBaseline?.()
  const suggestionButton = document.getElementById("alias-use-type-suggestion")
  if (suggestionButton) {
    suggestionButton.onclick = () => {
      const select = document.getElementById("alias-edit-type")
      if (select) select.value = alias.suggested_alias_type
    }
  }
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
  const formHtml = `
    <div class="form-group">
      <label>目标对象 *</label>
      <div id="alias-target-picker"></div>
      <input type="hidden" id="alias-target-id" value="${esc(entityIdParam)}" />
    </div>
    <div class="form-group">
      <label>别名文本 *</label>
      <input class="form-input" id="alias-edit-text" value="${esc(alias.alias || "")}" />
    </div>
    <div class="form-group">
      <label>别名类型</label>
      <select class="form-select" id="alias-edit-type">${aliasTypeOptionsHtml(alias.alias_type || "alias")}</select>
    </div>
    ${aliasEvidenceHtml(alias)}
  `
  showModalHtml("编辑后采用别名", formHtml, [{
    text: "保存并采用",
    class: "btn-primary",
    handler: async () => {
      const targetId = document.getElementById("alias-target-id")?.value
      const text = document.getElementById("alias-edit-text")?.value?.trim()
      const type = document.getElementById("alias-edit-type")?.value || "alias"
      if (!targetId || !text) {
        toast("请选择目标对象并输入别名", "warning")
        return false
      }
      try {
        await getApi().world.editAlias(entityIdParam, aliasText, {
          target_entity_id: targetId,
          alias: text,
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

/** 对应 vanilla _reviewEntityOptionsHtml。 */
function reviewEntityOptions(items = [], selectedId = "") {
  const byId = new Map()
  for (const item of items) {
    const id = entityId(item)
    if (id) byId.set(id, item)
  }
  if (selectedId && !byId.has(selectedId)) {
    byId.set(selectedId, { id: selectedId, name: "当前对象", entity_type: "-", status: "canonical" })
  }
  return Array.from(byId.values()).map((item) => {
    const id = entityId(item)
    return { id, label: `${item.name || "未命名对象"} · ${item.entity_type || "-"} · ${item.status || "-"}`, selected: id === selectedId }
  })
}

function reviewEntityOptionsHtml(items = [], selectedId = "") {
  const esc = getEsc()
  return reviewEntityOptions(items, selectedId).map((item) => (
    `<option value="${esc(item.id)}" ${item.selected ? "selected" : ""}>${esc(item.label)}</option>`
  )).join("")
}

function replaceReviewEntityOptions(select, items, selectedId) {
  select.replaceChildren(...reviewEntityOptions(items, selectedId).map((item) => {
    const option = document.createElement("option")
    option.value = item.id
    option.textContent = item.label
    option.selected = item.selected
    return option
  }))
}

/** 对应 vanilla _bindReviewEntitySearch。 */
function bindReviewEntitySearch(prefix, selectedId = "") {
  const toast = getToast()
  const button = document.getElementById(`${prefix}-search`)
  const input = document.getElementById(`${prefix}-query`)
  const select = document.getElementById(`${prefix}-select`)
  if (!button || !input || !select) return
  let searchGeneration = 0
  button.onclick = async () => {
    const generation = ++searchGeneration
    const projectId = getAppState()?.currentProjectId
    try {
      const data = await getApi().world.listEntities({
        novel_id: projectId,
        q: input.value || "",
        skip: 0,
        limit: 20,
      })
      if (
        generation !== searchGeneration
        || getAppState()?.currentProjectId !== projectId
        || !select.isConnected
      ) return
      const items = (data.items || data || []).filter((item) => (
        ["canonical", "draft", "candidate"].includes(item.status)
        && !item.content_json?._meta?.compatibility_shadow
      ))
      replaceReviewEntityOptions(select, items, select.value || selectedId)
    } catch (err) {
      if (
        generation !== searchGeneration
        || getAppState()?.currentProjectId !== projectId
        || !select.isConnected
      ) return
      toast(err.message || "搜索对象失败", "error")
    }
  }
}

/** 对应 vanilla showRelationGroupReviewForm（含预览联动）。 */
export function showRelationGroupReviewForm(groupId) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const group = reviewRegistry.relationGroups.find((item) => item.group_id === groupId)
  if (!group) {
    toast("未找到目标关系组", "error")
    return
  }
  const members = group.members || []
  const existingDraft = worldSession.relationReviewDrafts[groupId]
  const primary = members.find((item) => item.id === existingDraft?.primary_relation_id) || members[0]
  const suggested = primary?.suggested_relation_type
  const defaultSelected = members.filter((item) => (
    (suggested && item.suggested_relation_type === suggested)
    || (!suggested && item.relation_type === primary?.relation_type)
  ))
  const selectedIds = new Set(existingDraft?.member_relation_ids || defaultSelected.map((item) => item.id))
  const defaultAction = existingDraft?.action || (selectedIds.size > 1 ? "merge" : "accept")
  const entitySeed = [
    { id: group.source_id, name: group.source_name, entity_type: "-", status: "canonical" },
    { id: group.target_id, name: group.target_name, entity_type: "-", status: "canonical" },
  ]
  const relationTypes = reviewRegistry.reviewTypeCatalog.relation_types || REVIEW_RELATION_TYPE_FALLBACK
  const suggestions = Array.from(new Set(members.map((item) => item.suggested_relation_type).filter(Boolean)))
  const body = `
    <div class="review-decision-layout">
      <div class="form-group">
        <label for="relation-review-action">处理方式</label>
        <select class="form-select" id="relation-review-action">
          <option value="accept" ${defaultAction === "accept" ? "selected" : ""}>独立采用一条</option>
          <option value="merge" ${defaultAction === "merge" ? "selected" : ""}>归并所选证据</option>
          <option value="ignore" ${defaultAction === "ignore" ? "selected" : ""}>忽略所选</option>
        </select>
      </div>
      <fieldset class="review-candidate-fieldset">
        <legend>选择参与本次决策的候选</legend>
        ${members.map((item) => `
          <label class="review-candidate-option">
            <input type="checkbox" name="relation-review-member" value="${esc(item.id)}" ${selectedIds.has(item.id) ? "checked" : ""} />
            <input type="radio" name="relation-review-primary" value="${esc(item.id)}" ${item.id === (existingDraft?.primary_relation_id || primary?.id) ? "checked" : ""} aria-label="设为主关系" />
            <span><strong>${esc(reviewTypeLabel("relation", item.relation_type))}</strong><small>${esc(item.description || item.evidence_summary?.quote || "无描述")}</small></span>
          </label>
        `).join("")}
        <p class="form-help">复选框决定处理范围；单选圆点决定归并后保留的主关系。</p>
      </fieldset>
      <div class="form-group">
        <label>源对象</label>
        <div class="review-search-control"><input class="form-input" id="relation-source-query" value="${esc(group.source_name || "")}" /><button class="btn btn-sm" id="relation-source-search" type="button">搜索</button></div>
        <select class="form-select" id="relation-source-select">${reviewEntityOptionsHtml(entitySeed, existingDraft?.source_id || group.source_id)}</select>
      </div>
      <div class="form-group">
        <label>目标对象</label>
        <div class="review-search-control"><input class="form-input" id="relation-target-query" value="${esc(group.target_name || "")}" /><button class="btn btn-sm" id="relation-target-search" type="button">搜索</button></div>
        <select class="form-select" id="relation-target-select">${reviewEntityOptionsHtml(entitySeed, existingDraft?.target_id || group.target_id)}</select>
      </div>
      <div class="form-group">
        <label for="relation-final-type">最终关系类型</label>
        <input class="form-input" id="relation-final-type" list="relation-review-type-list" value="${esc(existingDraft?.relation_type || primary?.relation_type || "")}" />
        <datalist id="relation-review-type-list">${relationTypes.map((item) => `<option value="${esc(item.value)}">${esc(item.label)}</option>`).join("")}</datalist>
        ${suggestions.length ? `<div class="review-suggestion-actions">${suggestions.map((value) => `<button class="btn btn-sm" type="button" data-relation-type-suggestion="${esc(value)}">使用建议：${esc(reviewTypeLabel("relation", value))}</button>`).join("")}</div>` : ""}
      </div>
      <div class="form-group"><label for="relation-final-description">描述</label><textarea class="form-textarea" id="relation-final-description" rows="3">${esc(existingDraft?.description ?? primary?.description ?? "")}</textarea></div>
      <div class="form-group"><label for="relation-final-strength">强度</label><input class="form-input" id="relation-final-strength" type="number" min="0" max="1" step="0.01" value="${esc(existingDraft?.strength ?? primary?.strength ?? 0.5)}" /></div>
      ${(group.canonical_relations || []).length ? `<div class="review-warning">采用相同端点和类型时会复用已有正式关系，不创建重复记录。</div>` : ""}
      <section class="review-result-preview" id="relation-review-preview" aria-live="polite"></section>
    </div>
  `
  showModalHtml("准备关系复核决策", body, [{
    text: "保存决策",
    class: "btn-primary",
    handler: async () => {
      const action = document.getElementById("relation-review-action")?.value || "accept"
      const selected = Array.from(document.querySelectorAll('input[name="relation-review-member"]:checked')).map((input) => input.value)
      const primaryId = document.querySelector('input[name="relation-review-primary"]:checked')?.value || ""
      if (!selected.length || (action === "accept" && selected.length !== 1) || (action === "merge" && selected.length < 2)) {
        toast(action === "merge" ? "归并至少需要选择两条关系" : "独立采用只能选择一条关系", "warning")
        return false
      }
      if (["accept", "merge"].includes(action) && !selected.includes(primaryId)) {
        toast("主关系必须在本次选择范围内", "warning")
        return false
      }
      const relationType = document.getElementById("relation-final-type")?.value?.trim() || ""
      if (["accept", "merge"].includes(action) && !relationType) {
        toast("请填写最终关系类型", "warning")
        return false
      }
      worldSession.relationReviewDrafts[groupId] = {
        client_decision_id: groupId,
        action,
        group_id: groupId,
        member_relation_ids: selected,
        primary_relation_id: ["accept", "merge"].includes(action) ? primaryId : null,
        expected_execution_fingerprint: group.execution_fingerprint,
        ...(["accept", "merge"].includes(action) ? {
          source_id: document.getElementById("relation-source-select")?.value,
          target_id: document.getElementById("relation-target-select")?.value,
          relation_type: relationType,
          description: document.getElementById("relation-final-description")?.value?.trim() || "",
          strength: Number(document.getElementById("relation-final-strength")?.value || 0.5),
        } : {}),
      }
      delete worldSession.relationReviewErrors[groupId]
      closeModal()
    },
  }], { size: "large" })
  bindReviewEntitySearch("relation-source", existingDraft?.source_id || group.source_id)
  bindReviewEntitySearch("relation-target", existingDraft?.target_id || group.target_id)
  const updatePreview = () => updateRelationReviewPreview(group)
  document.querySelectorAll("#relation-review-action, input[name='relation-review-member'], input[name='relation-review-primary'], #relation-source-select, #relation-target-select, #relation-final-type, #relation-final-description, #relation-final-strength").forEach((control) => {
    control.addEventListener("input", updatePreview)
    control.addEventListener("change", updatePreview)
  })
  document.querySelectorAll("[data-relation-type-suggestion]").forEach((button) => {
    button.onclick = () => {
      const input = document.getElementById("relation-final-type")
      if (input) input.value = button.getAttribute("data-relation-type-suggestion") || input.value
      updatePreview()
    }
  })
  updatePreview()
}

/** 对应 vanilla _updateRelationReviewPreview。 */
function updateRelationReviewPreview(group) {
  const preview = document.getElementById("relation-review-preview")
  if (!preview) return
  preview.replaceChildren()
  const heading = document.createElement("h4")
  const action = document.getElementById("relation-review-action")?.value || "accept"
  const selectedIds = Array.from(document.querySelectorAll('input[name="relation-review-member"]:checked')).map((input) => input.value)
  if (action === "ignore") {
    heading.textContent = "处理结果预览"
    const paragraph = document.createElement("p")
    paragraph.textContent = `将把 ${selectedIds.length} 条所选候选移入历史；未选中候选保持待处理。`
    preview.append(heading, paragraph)
    return
  }
  const sourceSelect = document.getElementById("relation-source-select")
  const targetSelect = document.getElementById("relation-target-select")
  const sourceId = sourceSelect?.value || ""
  const targetId = targetSelect?.value || ""
  const relationType = document.getElementById("relation-final-type")?.value?.trim() || ""
  const strength = document.getElementById("relation-final-strength")?.value || ""
  const description = document.getElementById("relation-final-description")?.value?.trim() || "无描述"
  const sourceLabel = sourceSelect?.selectedOptions?.[0]?.textContent || "未选择源对象"
  const targetLabel = targetSelect?.selectedOptions?.[0]?.textContent || "未选择目标对象"
  const canonical = (group.canonical_relations || []).find((item) => (
    item.source_id === sourceId && item.target_id === targetId && item.relation_type === relationType
  ))
  heading.textContent = "采用后结果预览"
  const endpoints = document.createElement("p")
  const source = document.createElement("strong")
  source.textContent = sourceLabel
  const target = document.createElement("strong")
  target.textContent = targetLabel
  endpoints.append(source, document.createTextNode(" → "), target)

  const summary = document.createElement("p")
  summary.textContent = `类型：${reviewTypeLabel("relation", relationType)} · 强度：${strength} · 所选证据：${selectedIds.length} 条`
  const descriptionNode = document.createElement("p")
  descriptionNode.textContent = description
  const disposition = document.createElement("p")
  disposition.className = canonical ? "review-warning" : "world-text-dim"
  disposition.textContent = canonical
    ? "将复用已有正式关系，关系 ID 只会记录在诊断与审计信息中。"
    : "将采用主关系作为正式关系；服务端提交前会再检查是否存在可复用关系。"
  preview.append(heading, endpoints, summary, descriptionNode, disposition)
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
      <label>关系类型</label>
      <input class="form-input" id="rel-review-type" value="${esc(relation.relation_type || "")}" />
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
      const relationType = document.getElementById("rel-review-type")?.value?.trim() || ""
      if (!sourceId || !targetId || !relationType) {
        toast("请填写源对象、目标对象和关系类型", "warning")
        return false
      }
      try {
        await getApi().world.reviewEditRelationship(relationId, {
          source_id: sourceId,
          target_id: targetId,
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

/** 对应 vanilla _advanceRelationReview（组清空后回退页码 + 打开下一组）。 */
async function advanceRelationReview(anchorIndex = 0, openNext = true) {
  const groups = reviewRegistry.relationGroups
  if (!groups.length && reviewRegistry.relationGroupTotal > 0 && reviewRegistry.relationFilters.skip > 0) {
    const content = document.getElementById("workspace-content")
    const scrollTop = content?.scrollTop || 0
    const skip = Math.max(0, Math.floor((reviewRegistry.relationGroupTotal - 1) / reviewRegistry.relationFilters.limit) * reviewRegistry.relationFilters.limit)
    await navigateReview("review-relations", reviewQueryFromState({ ...reviewRegistry.relationFilters, skip }, WORLD_RELATION_QUERY_KEYS), { replace: true })
    const liveContent = document.getElementById("workspace-content")
    if (liveContent) liveContent.scrollTop = scrollTop
  }
  const next = reviewRegistry.relationGroups[Math.min(anchorIndex, Math.max(0, reviewRegistry.relationGroups.length - 1))]
  if (openNext && next) showRelationGroupReviewForm(next.group_id)
}

/** 对应 vanilla _advanceAliasReview。 */
async function advanceAliasReview(anchorIndex = 0, openNext = true) {
  const aliases = reviewRegistry.aliases
  if (!aliases.length && reviewRegistry.aliasGroupTotal > 0 && reviewRegistry.aliasFilters.skip > 0) {
    const content = document.getElementById("workspace-content")
    const scrollTop = content?.scrollTop || 0
    const skip = Math.max(0, Math.floor((reviewRegistry.aliasGroupTotal - 1) / reviewRegistry.aliasFilters.limit) * reviewRegistry.aliasFilters.limit)
    await navigateReview("review-aliases", reviewQueryFromState({ ...reviewRegistry.aliasFilters, skip }, WORLD_ALIAS_QUERY_KEYS), { replace: true })
    const liveContent = document.getElementById("workspace-content")
    if (liveContent) liveContent.scrollTop = scrollTop
  }
  const next = reviewRegistry.aliases[Math.min(anchorIndex, Math.max(0, reviewRegistry.aliases.length - 1))]
  if (openNext && next) showAliasReviewDecisionForm(next.entity_id, next.alias)
}

/** 对应 vanilla _applyRelationReviewBatch。 */
export function applyRelationReviewBatch(groups, ignoreAll = false) {
  const toast = getToast()
  const anchorIndex = Math.max(0, Math.min(...groups.map((group) => reviewRegistry.relationGroups.findIndex((item) => item.group_id === group.group_id)).filter((index) => index >= 0)))
  const decisions = []
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
      decisions.push(worldSession.relationReviewDrafts[group.group_id])
    }
  }
  if (!ignoreAll && decisions.length !== groups.length) {
    toast("所选关系组中仍有未准备决策的项目", "warning")
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
            selection.delete(item.client_decision_id)
          } else {
            worldSession.relationReviewErrors[item.client_decision_id] = reviewBatchItemError(item)
          }
        }
        reviewBatchToast(result, "关系组")
        getRouter()?.refresh?.()
        await advanceRelationReview(anchorIndex, groups.length === 1)
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
  const anchorIndex = Math.max(0, Math.min(...items.map((item) => reviewRegistry.aliases.findIndex((current) => aliasKey(current) === aliasKey(item))).filter((index) => index >= 0)))
  const decisionKeys = new Map()
  const decisions = items.map((item, index) => {
    const key = aliasKey(item)
    const draft = worldSession.aliasReviewDrafts[key] || {}
    const clientDecisionId = `alias-${index}-${String(item.entity_id || "").slice(0, 16)}`
    decisionKeys.set(clientDecisionId, key)
    return {
      client_decision_id: clientDecisionId,
      action,
      entity_id: item.entity_id,
      original_alias: item.alias,
      expected_execution_fingerprint: item.execution_fingerprint,
      ...(action === "accept" ? draft : {}),
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
            selection.delete(key)
          } else if (key) {
            worldSession.aliasReviewErrors[key] = reviewBatchItemError(item)
          }
        }
        reviewBatchToast(result, "别名")
        getRouter()?.refresh?.()
        await advanceAliasReview(anchorIndex, items.length === 1)
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

const HISTORY_STATUSES = new Set([
  "ignored",
  "merged",
  "deprecated",
  "rolled_back",
  "abandoned",
])

const ACTIVE_STATUSES = new Set([
  "active",
  "canonical",
  "confirmed",
  "published",
])

const ATTENTION_REASON_LABELS = {
  conflicted: "存在冲突",
  conflict: "存在冲突",
  low_confidence: "低置信度",
  pov_risk: "POV 信息风险",
  needs_disambiguation: "需要消歧",
  unresolved_spatial_anchor: "空间位置未解析",
  uncertain_boundary: "边界不确定",
  phase1a_fallback: "自动提取已降级",
  needs_review: "需要人工检查",
}

function rawStatus(asset = {}) {
  return asset.status || asset.review_state || asset.fact_status || ""
}

function unique(values) {
  return [...new Set(values.filter(Boolean))]
}

export function assetAttentionReasons(asset = {}) {
  const meta = asset.structure_meta || asset.provenance_meta || asset.content_json?._meta || {}
  const explicit = [
    ...(Array.isArray(asset.attention_reasons) ? asset.attention_reasons : []),
    ...(Array.isArray(meta.attention_reasons) ? meta.attention_reasons : []),
  ]
  const reasons = explicit.map((reason) => ATTENTION_REASON_LABELS[reason] || reason)
  const state = asset.review_state || meta.review_state
  if (state === "conflicted" || rawStatus(asset) === "conflicted") reasons.push(ATTENTION_REASON_LABELS.conflicted)
  const confidence = asset.confidence ?? meta.confidence
  if (confidence !== null && confidence !== undefined && Number(confidence) < 0.5) {
    reasons.push(ATTENTION_REASON_LABELS.low_confidence)
  }
  if (asset.boundary_status === "uncertain" || meta.boundary_status === "uncertain") {
    reasons.push(ATTENTION_REASON_LABELS.uncertain_boundary)
  }
  if (asset.phase1a_fallback || meta.phase1a_fallback) {
    reasons.push(ATTENTION_REASON_LABELS.phase1a_fallback)
  }
  const povStatus = asset.pov_validation?.status || meta.pov_validation?.status
  if (povStatus === "failed" || povStatus === "warning") reasons.push(ATTENTION_REASON_LABELS.pov_risk)
  if ((asset.needs_review === true || meta.needs_review === true) && reasons.length === 0) {
    reasons.push(ATTENTION_REASON_LABELS.needs_review)
  }
  return unique(reasons)
}

function display(displayState, label, asset, extra = {}) {
  return {
    displayState,
    label,
    attentionReasons: assetAttentionReasons(asset),
    isHistory: displayState === "archived",
    ...extra,
  }
}

export function worldAssetDisplay(asset = {}) {
  const status = rawStatus(asset)
  if (asset.display_state === "archived" || HISTORY_STATUSES.has(status)) {
    return display("archived", "历史", asset)
  }
  if (asset.display_state === "review") {
    return display("review", "待处理", asset)
  }
  if (asset.display_state === "active") {
    return display("active", "已采用", asset)
  }
  if (ACTIVE_STATUSES.has(status)) return display("active", "已采用", asset)
  return display("review", "待处理", asset)
}

export function structureAssetDisplay(asset = {}) {
  const status = rawStatus(asset)
  if (asset.display_state === "archived" || HISTORY_STATUSES.has(status)) {
    return display("archived", "历史", asset)
  }
  if (asset.display_state === "review" || status === "candidate") {
    return display("review", "待处理", asset)
  }
  if (asset.display_state === "active" || ACTIVE_STATUSES.has(status)) {
    return display("active", "已采用", asset)
  }
  return display("working", "工作稿", asset)
}

export function writingAssetDisplay(asset = {}) {
  const status = rawStatus(asset)
  if (asset.display_state === "archived" || HISTORY_STATUSES.has(status)) {
    return display("archived", "历史", asset)
  }
  if (asset.display_state === "review" || status === "candidate") {
    return display("review", "待处理", asset)
  }
  if (status === "published" || asset.published === true) {
    return display("published", "已发布", asset)
  }
  return display("working", "工作稿", asset)
}

export function mapAssetDisplay(item = {}) {
  const isFact = item.item_kind === "fact" || Boolean(item.fact_status)
  const status = isFact ? (item.fact_status || "confirmed") : (item.review_state || "candidate")
  if (HISTORY_STATUSES.has(status)) return display("archived", "历史", item, { isFact })
  if (isFact) return display("active", "已采用", item, { isFact })
  return display("review", "待处理", item, { isFact })
}

export function contextContentModeLabel(mode, { compact = false } = {}) {
  if (mode === "working") return compact ? "工作稿" : "工作稿内容"
  if (mode === "candidate" || mode === "review") return compact ? "待处理" : "待处理内容"
  return compact ? "已发布" : "已发布内容"
}

export function authorFacingStateText(value) {
  return String(value ?? "")
    .replaceAll("候选", "待处理")
    .replaceAll("待确认后", "处理后")
    .replaceAll("待确认", "待处理")
    .replaceAll("已确认", "已采用")
    .replaceAll("正史", "已采用")
    .replaceAll("未复核", "需要人工检查")
    .replaceAll("需复核", "需要人工检查")
}

export function displayStateBadgeClass(displayState) {
  return {
    active: "badge-canonical",
    published: "badge-canonical",
    review: "badge-candidate",
    working: "badge-draft",
    archived: "badge-deprecated",
  }[displayState] || ""
}

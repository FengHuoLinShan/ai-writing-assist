/**
 * WorkflowProgressCard 纯逻辑 — 从 shared/progressRenderer.js 移植的框架无关部分。
 * DOM 契约（class 名、标签文案、截断数量）与原实现保持一致。
 */

export const PHASE_DISPLAY_LABELS = {
  phase0_plan: "阶段 1 · 规划场景范围",
  phase1a_scene_slicing: "阶段 2 · 划分场景边界",
  phase1b_enrichment: "阶段 3 · 补充场景资料",
  phase1c_scene_fusion: "阶段 4 · 整理相邻场景",
  scene_commit: "最后一步 · 保存整理结果",
  entity_extraction: "世界对象与关系提取",
  structure_analysis: "剧情结构分析",
}

export const ERROR_KIND_LABELS = {
  timeout: "处理超时",
  schema_failure: "结果格式未通过校验",
  schema_validation: "结果格式未通过校验",
  invalid_response: "未得到有效结果",
  phase_failed: "阶段执行失败",
  transport_failure: "服务暂时不可用",
  connection_error: "服务暂时不可用",
  provider_error: "服务暂时不可用",
  proxy_error: "服务暂时不可用",
  empty_output: "未生成可用结果",
  missing_world_object_context: "缺少必要的世界设定上下文",
  fallback: "已使用降级结果",
  degraded: "已使用降级结果",
}

export function errorKindLabel(value) {
  const text = String(value || "").trim()
  if (!text) return "需要人工检查"
  if (ERROR_KIND_LABELS[text]) return ERROR_KIND_LABELS[text]
  return /^[a-z0-9_.:-]+$/i.test(text) ? "需要人工检查" : text
}

const ERROR_FIELD_LABELS = {
  error_kind: "原因",
  bulk_error_kind: "批量处理原因",
  supplemental_error_kind: "补充处理原因",
  final_error_type: "最终失败原因",
}

function isErrorKindField(key) {
  return key === "error_kind"
    || key.endsWith("_error_kind")
    || key === "final_error_type"
    || key.endsWith("_error_type")
}

function authorFacingDiagnosticKey(key) {
  if (!isErrorKindField(key)) return key
  return ERROR_FIELD_LABELS[key] || "处理失败原因"
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

export function authorFacingDiagnosticText(value, { fallbackForCode = false } = {}) {
  let text = String(value ?? "").trim()
  if (!text) return ""
  text = text.replace(
    /(?:health\.)?error_kind\s*[:=]\s*([a-z0-9_.:-]+)/gi,
    (_match, kind) => `原因：${errorKindLabel(kind)}`,
  )
  for (const [kind, label] of Object.entries(ERROR_KIND_LABELS)) {
    text = text.replace(new RegExp(`\\b${escapeRegExp(kind)}\\b`, "gi"), label)
  }
  if (fallbackForCode && /^[a-z0-9_.:-]+$/i.test(text)) return "任务执行失败，请稍后重试或查看恢复操作"
  return text
}

export function authorFacingDiagnosticValue(value) {
  if (Array.isArray(value)) return value.map((item) => authorFacingDiagnosticValue(item))
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => (
      isErrorKindField(key)
        ? [authorFacingDiagnosticKey(key), errorKindLabel(item)]
        : [key, authorFacingDiagnosticValue(item)]
    )))
  }
  if (typeof value === "string") return authorFacingDiagnosticText(value)
  return value
}

export function formatAuthorFacingDiagnostic(value) {
  const safe = authorFacingDiagnosticValue(value)
  if (safe == null) return "-"
  if (typeof safe === "object") {
    try { return JSON.stringify(safe) } catch { return String(safe) }
  }
  return String(safe)
}

export const PHASE_STATUS_LABELS = {
  completed: "已完成",
  running: "运行中",
  degraded: "降级完成",
  failed: "失败",
  blocked: "已阻止",
}

export function phaseDisplayLabel(phase) {
  return PHASE_DISPLAY_LABELS[phase] || phase || "phase"
}

export function phaseStatusLabel(status) {
  return PHASE_STATUS_LABELS[status] || status || "未知"
}

export function classesFor(progress, extra = "") {
  const classes = ["workflow-progress"]
  if (progress.failed) classes.push("workflow-progress--failed")
  if (progress.done) classes.push("workflow-progress--done")
  if (progress.cancelled) classes.push("workflow-progress--cancelled")
  if (progress.indeterminate) classes.push("workflow-progress--indeterminate")
  if (extra) classes.push(extra)
  return classes.join(" ")
}

export function metaBits(progress, options = {}) {
  const bits = []
  if (progress.hasPercent) bits.push(`${progress.percent}%`)
  if (progress.statusLabel) bits.push(progress.statusLabel)
  if (options.showTaskId === true && progress.taskId) bits.push(`任务 ${progress.taskId}`)
  if (options.elapsedText) bits.push(options.elapsedText)
  return bits
}

export function artifactItems(artifacts = {}) {
  if (!artifacts || typeof artifacts !== "object") return []
  return Object.entries(artifacts)
    .filter(([, artifact]) => artifact && typeof artifact === "object")
    .slice(0, 4)
    .map(([phase, artifact]) => {
      const coverage = artifact.coverage && typeof artifact.coverage === "object" ? artifact.coverage : {}
      const repair = artifact.repair && typeof artifact.repair === "object" ? artifact.repair : {}
      const counts = artifact.counts && typeof artifact.counts === "object" ? artifact.counts : {}
      const missing = Array.isArray(coverage.missing_chapters) ? coverage.missing_chapters : []
      const countBits = []
      if (counts.candidate_count != null) countBits.push(`待处理 ${counts.candidate_count}`)
      if (counts.total_scenes != null) countBits.push(`场景 ${counts.total_scenes}`)
      if (counts.total_created != null) countBits.push(`对象 ${counts.total_created}`)
      if (counts.total_threads != null) countBits.push(`剧情线 ${counts.total_threads}`)
      if (repair.attempts) countBits.push(`修复 ${repair.attempts}`)
      if (missing.length) countBits.push(`缺章 ${missing.slice(0, 6).join(",")}`)
      return {
        phase,
        label: phaseDisplayLabel(phase),
        status: phaseStatusLabel(artifact.status),
        detail: countBits.length ? ` · ${countBits.join(" · ")}` : "",
      }
    })
}

export function hasAssetSummary(summary) {
  if (!summary || typeof summary !== "object") return false
  return ["adopted", "review", "not_adopted"].some(
    (key) => summary[key] !== undefined && summary[key] !== null,
  )
}

export function compactValue(value) {
  if (value === null || value === undefined) return ""
  if (Array.isArray(value)) return value.slice(0, 8).join(", ")
  if (typeof value === "object") {
    return Object.entries(value)
      .slice(0, 6)
      .map(([key, item]) => `${key}: ${compactValue(item)}`)
      .join(" · ")
  }
  return typeof value === "string" ? authorFacingDiagnosticText(value) : String(value)
}

export function keyValueItems(details = {}) {
  if (!details || typeof details !== "object") return []
  return Object.entries(authorFacingDiagnosticValue(details))
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .slice(0, 8)
    .map(([key, value]) => ({ key, text: compactValue(value) }))
}

export function timelineItems(timeline = []) {
  if (!Array.isArray(timeline)) return []
  return timeline.slice(-8).map((item) => {
    const bits = []
    if (item.status) bits.push(phaseStatusLabel(item.status))
    if (item.duration_s != null) bits.push(`${item.duration_s}s`)
    const errorEntry = Object.entries(item).find(([key]) => isErrorKindField(key))
    if (errorEntry) bits.push(errorKindLabel(errorEntry[1]))
    return { phase: phaseDisplayLabel(item.phase), detail: bits.join(" · ") }
  })
}

export function eventItems(events = []) {
  if (!Array.isArray(events)) return []
  return events.slice(-10).map((event) => ({
    level: event.level || "info",
    label: [
      event.phase ? phaseDisplayLabel(event.phase) : null,
      event.event,
      event.status ? phaseStatusLabel(event.status) : null,
    ]
      .filter(Boolean).join(" · ") || "事件",
    message: authorFacingDiagnosticText(event.message || "", { fallbackForCode: true }),
    details: keyValueItems(event.details),
  }))
}

export function checkItems(checks = []) {
  if (!Array.isArray(checks)) return []
  return checks.slice(-10).map((check) => ({
    ok: Boolean(check.ok),
    label: [check.phase ? phaseDisplayLabel(check.phase) : null, check.name]
      .filter(Boolean).join(" · ") || "检查",
    message: authorFacingDiagnosticText(check.message || "", { fallbackForCode: true }),
    details: keyValueItems(check.details),
  }))
}

export function errorItems(errors = []) {
  if (!Array.isArray(errors)) return []
  return errors.slice(-6).map((error) => ({
    phase: phaseDisplayLabel(error.phase),
    kind: errorKindLabel(
      Object.entries(error).find(([key]) => isErrorKindField(key))?.[1],
    ),
    message: authorFacingDiagnosticText(error.message || "", { fallbackForCode: true }),
  }))
}

export function warningItems(warnings = []) {
  return Array.isArray(warnings)
    ? warnings.slice(0, 3).map((warning) => authorFacingDiagnosticValue(warning))
    : []
}

export function diagnosticItems(progress) {
  const diagnostics = progress.diagnosticCounts && typeof progress.diagnosticCounts === "object"
    ? progress.diagnosticCounts
    : {}
  return keyValueItems(diagnostics)
}

/** 卡片级折叠存储键（与原 data-collapse-storage-key 一致）。 */
export function collapseStorageKey(progress, options = {}) {
  return options.collapseStorageKey || (progress.taskId ? `workflow-progress-card:${progress.taskId}` : null)
}

/** 详情级折叠存储键（与原 data-details-storage-key 一致）。 */
export function detailsStorageKey(progress, options = {}) {
  return options.detailsStorageKey || (progress.taskId ? `workflow-progress-details:${progress.taskId}` : null)
}

function _readStoredOpenImpl(storageKey) {
  if (!storageKey || !globalThis.sessionStorage) return null
  try {
    return globalThis.sessionStorage.getItem(storageKey)
  } catch {
    return null
  }
}

/** 读取折叠存储选择（"open" | "closed" | null=用户未选择）。 */
export function readStoredOpen(storageKey) {
  return _readStoredOpenImpl(storageKey)
}

export function persistStoredOpen(storageKey, open) {
  if (!storageKey || !globalThis.sessionStorage) return
  try {
    globalThis.sessionStorage.setItem(storageKey, open ? "open" : "closed")
  } catch {
    // 存储失败仅影响折叠记忆，不影响本次渲染
  }
}

/** 卡片初始开合：存储优先，回退 defaultExpanded ?? (failed || attentionRequired)。 */
export function initialCardOpen(progress, options = {}) {
  const stored = readStoredOpen(collapseStorageKey(progress, options))
  const fallback = typeof options.defaultExpanded === "boolean"
    ? options.defaultExpanded
    : Boolean(progress.failed || options.attentionRequired)
  return stored === "open" || (stored !== "closed" && fallback)
}

/** 详情初始开合：存储优先，回退 detailLevel === "detailed"。 */
export function initialDetailsOpen(progress, options = {}) {
  const stored = readStoredOpen(detailsStorageKey(progress, options))
  return stored === "open" || (stored !== "closed" && options.detailLevel === "detailed")
}

/**
 * WorkflowProgressCard 纯逻辑 — 从 shared/progressRenderer.js 移植的框架无关部分。
 * DOM 契约（class 名、标签文案、截断数量）与原实现保持一致。
 */

export const PHASE_DISPLAY_LABELS = {
  phase0_plan: "Phase 0 · Scene 窗口规划",
  phase1a_scene_slicing: "Phase 1a · Scene 边界切分",
  phase1b_enrichment: "Phase 1b · Scene 字段补全",
  scene_commit: "Scene commit · 正式写入",
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
  if (options.showTaskId !== false && progress.taskId) bits.push(`任务 ${progress.taskId}`)
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
      if (counts.total_scenes != null) countBits.push(`Scene ${counts.total_scenes}`)
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
  return String(value)
}

export function keyValueItems(details = {}) {
  if (!details || typeof details !== "object") return []
  return Object.entries(details)
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
    if (item.error_kind) bits.push(item.error_kind)
    return { phase: phaseDisplayLabel(item.phase), detail: bits.join(" · ") }
  })
}

export function eventItems(events = []) {
  if (!Array.isArray(events)) return []
  return events.slice(-10).map((event) => ({
    level: event.level || "info",
    label: [event.phase, event.event, event.status].filter(Boolean).join(" · ") || "event",
    message: event.message || "",
    details: keyValueItems(event.details),
  }))
}

export function checkItems(checks = []) {
  if (!Array.isArray(checks)) return []
  return checks.slice(-10).map((check) => ({
    ok: Boolean(check.ok),
    label: [check.phase, check.name].filter(Boolean).join(" · ") || "check",
    message: check.message || "",
    details: keyValueItems(check.details),
  }))
}

export function errorItems(errors = []) {
  if (!Array.isArray(errors)) return []
  return errors.slice(-6).map((error) => ({
    phase: error.phase || "phase",
    kind: error.error_kind || "error",
    message: error.message || "",
  }))
}

export function warningItems(warnings = []) {
  return Array.isArray(warnings) ? warnings.slice(0, 3) : []
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

function readStoredOpen(storageKey) {
  if (!storageKey || !globalThis.sessionStorage) return null
  try {
    return globalThis.sessionStorage.getItem(storageKey)
  } catch {
    return null
  }
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

function escapeHtml(value) {
  if (typeof globalThis.esc === "function") return globalThis.esc(value)
  if (value === null || value === undefined) return ""
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

function classesFor(progress, extra = "") {
  const classes = ["workflow-progress"]
  if (progress.failed) classes.push("workflow-progress--failed")
  if (progress.done) classes.push("workflow-progress--done")
  if (progress.cancelled) classes.push("workflow-progress--cancelled")
  if (progress.indeterminate) classes.push("workflow-progress--indeterminate")
  if (extra) classes.push(extra)
  return classes.join(" ")
}

function renderWarnings(warnings = []) {
  if (!Array.isArray(warnings) || warnings.length === 0) return ""
  const items = warnings.slice(0, 3).map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")
  return `<ul class="workflow-progress__warnings">${items}</ul>`
}

function renderProgressBar(progress) {
  if (progress.indeterminate) {
    return `
      <div class="workflow-progress__bar" aria-hidden="true">
        <div class="workflow-progress__fill workflow-progress__fill--indeterminate"></div>
      </div>
    `
  }
  const percent = progress.percent ?? 0
  return `
    <div class="workflow-progress__bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}">
      <div class="workflow-progress__fill" style="width:${percent}%;"></div>
    </div>
  `
}

function renderMeta(progress, options = {}) {
  const bits = []
  if (progress.hasPercent) bits.push(`${progress.percent}%`)
  if (progress.statusLabel) bits.push(progress.statusLabel)
  if (options.showTaskId !== false && progress.taskId) bits.push(`任务 ${progress.taskId}`)
  if (options.elapsedText) bits.push(options.elapsedText)
  return bits.length ? `<div class="workflow-progress__meta">${bits.map(escapeHtml).join(" · ")}</div>` : ""
}

export function renderInlineProgress(progress, options = {}) {
  if (!progress) return ""
  const title = options.title || progress.label
  const message = options.message || progress.message
  const summary = progress.resultSummary ? `<div class="workflow-progress__summary">${escapeHtml(progress.resultSummary)}</div>` : ""
  const error = progress.errorMessage ? `<div class="workflow-progress__error">${escapeHtml(progress.errorMessage)}</div>` : ""
  const actionHtml = options.actionsHtml || ""

  return `
    <div class="${classesFor(progress, options.className || "")}">
      <div class="workflow-progress__header">
        <div class="workflow-progress__title">${escapeHtml(title)}</div>
        <div class="workflow-progress__status">${escapeHtml(progress.statusLabel || "")}</div>
      </div>
      <div class="workflow-progress__message">${escapeHtml(message)}</div>
      ${renderProgressBar(progress)}
      ${renderMeta(progress, options)}
      ${summary}
      ${error}
      ${renderWarnings(progress.warnings)}
      ${actionHtml}
    </div>
  `
}

export function renderFixedProgress(progress, options = {}) {
  if (!progress) return ""
  const offset = Number(options.offset || 0)
  const style = offset ? ` style="bottom:${offset}px;"` : ""
  return `
    <div class="workflow-progress-fixed"${style}>
      ${renderInlineProgress(progress, {
        ...options,
        className: `workflow-progress--fixed ${options.className || ""}`.trim(),
      })}
    </div>
  `
}

export function renderWorkflowCard(progress, options = {}) {
  if (!progress) return ""
  const destination = options.destinationLabel
    ? `<div class="workflow-progress__destination">${escapeHtml(options.destinationLabel)}</div>`
    : ""
  return renderInlineProgress(progress, {
    ...options,
    actionsHtml: `${destination}${options.actionsHtml || ""}`,
    className: `workflow-progress--card ${options.className || ""}`.trim(),
  })
}

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

function renderAssetSummary(summary = {}) {
  if (!summary || typeof summary !== "object") return ""
  const hasSummary = ["adopted", "review", "not_adopted"]
    .some((key) => summary[key] !== undefined && summary[key] !== null)
  if (!hasSummary) return ""
  const adopted = Number(summary.adopted || 0)
  const review = Number(summary.review || 0)
  const notAdopted = Number(summary.not_adopted || 0)
  return `
    <div class="workflow-progress__asset-summary" aria-label="资产处理结果">
      <span>已采用 ${escapeHtml(adopted)}</span>
      <span>待处理 ${escapeHtml(review)}</span>
      <span>未采用 ${escapeHtml(notAdopted)}</span>
    </div>
  `
}

function renderPhaseArtifacts(artifacts = {}) {
  if (!artifacts || typeof artifacts !== "object") return ""
  const items = Object.entries(artifacts)
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
      const detail = countBits.length ? ` · ${countBits.join(" · ")}` : ""
      return `<li>${escapeHtml(phase)}：${escapeHtml(artifact.status || "unknown")}${escapeHtml(detail)}</li>`
    })
  if (!items.length) return ""
  return `<ul class="workflow-progress__artifacts">${items.join("")}</ul>`
}

function compactValue(value) {
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

function renderKeyValues(details = {}) {
  if (!details || typeof details !== "object") return ""
  const items = Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .slice(0, 8)
    .map(([key, value]) => (
      `<span class="workflow-progress__kv"><b>${escapeHtml(key)}</b>: ${escapeHtml(compactValue(value))}</span>`
    ))
  return items.length ? `<div class="workflow-progress__details-kv">${items.join("")}</div>` : ""
}

function renderTimeline(timeline = []) {
  if (!Array.isArray(timeline) || timeline.length === 0) return ""
  const items = timeline.slice(-8).map((item) => {
    const bits = []
    if (item.status) bits.push(item.status)
    if (item.duration_s != null) bits.push(`${item.duration_s}s`)
    if (item.error_kind) bits.push(item.error_kind)
    return `<li>${escapeHtml(item.phase || "phase")}：${escapeHtml(bits.join(" · "))}</li>`
  })
  return `<section class="workflow-progress__detail-section"><h4>阶段时间线</h4><ul>${items.join("")}</ul></section>`
}

function renderEvents(events = []) {
  if (!Array.isArray(events) || events.length === 0) return ""
  const items = events.slice(-10).map((event) => {
    const label = [event.phase, event.event, event.status].filter(Boolean).join(" · ")
    return `
      <li class="workflow-progress__event workflow-progress__event--${escapeHtml(event.level || "info")}">
        <div>${escapeHtml(label || "event")}</div>
        ${event.message ? `<div>${escapeHtml(event.message)}</div>` : ""}
        ${renderKeyValues(event.details)}
      </li>
    `
  })
  return `<section class="workflow-progress__detail-section"><h4>事件</h4><ul>${items.join("")}</ul></section>`
}

function renderChecks(checks = []) {
  if (!Array.isArray(checks) || checks.length === 0) return ""
  const items = checks.slice(-10).map((check) => {
    const status = check.ok ? "通过" : "未通过"
    const label = [check.phase, check.name].filter(Boolean).join(" · ")
    return `
      <li class="${check.ok ? "workflow-progress__check" : "workflow-progress__check workflow-progress__check--failed"}">
        <div>${escapeHtml(label || "check")}：${escapeHtml(status)}</div>
        ${check.message ? `<div>${escapeHtml(check.message)}</div>` : ""}
        ${renderKeyValues(check.details)}
      </li>
    `
  })
  return `<section class="workflow-progress__detail-section"><h4>门禁检查</h4><ul>${items.join("")}</ul></section>`
}

function renderErrors(errors = []) {
  if (!Array.isArray(errors) || errors.length === 0) return ""
  const items = errors.slice(-6).map((error) => (
    `<li>${escapeHtml(error.phase || "phase")}：${escapeHtml(error.error_kind || "error")} · ${escapeHtml(error.message || "")}</li>`
  ))
  return `<section class="workflow-progress__detail-section"><h4>错误与降级</h4><ul>${items.join("")}</ul></section>`
}

function renderDiagnostics(progress) {
  const diagnostics = progress.diagnosticCounts && typeof progress.diagnosticCounts === "object"
    ? progress.diagnosticCounts
    : {}
  if (!Object.keys(diagnostics).length) return ""
  return `<section class="workflow-progress__detail-section"><h4>诊断摘要</h4>${renderKeyValues(diagnostics)}</section>`
}

function renderDetailedProgress(progress, options = {}) {
  const content = [
    renderTimeline(progress.phaseTimeline),
    renderEvents(progress.progressEvents),
    renderChecks(progress.acceptanceChecks),
    renderErrors(progress.phaseErrors),
    renderDiagnostics(progress),
  ].filter(Boolean).join("")
  if (!content) return ""
  const storageKey = options.detailsStorageKey || (
    progress.taskId ? `workflow-progress-details:${progress.taskId}` : null
  )
  let storedOpen = null
  if (storageKey && globalThis.sessionStorage) {
    try {
      storedOpen = globalThis.sessionStorage.getItem(storageKey)
    } catch {
      storedOpen = null
    }
  }
  const shouldOpen = storedOpen === "open"
    || (storedOpen !== "closed" && options.detailLevel === "detailed")
  const open = shouldOpen ? " open" : ""
  const storageAttr = storageKey
    ? ` data-details-storage-key="${escapeHtml(storageKey)}"`
    : ""
  return `
    <details class="workflow-progress__details"${storageAttr}${open}>
      <summary>详细进度</summary>
      ${content}
    </details>
  `
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
  return bits.length ? `<span class="workflow-progress__meta">${bits.map(escapeHtml).join(" · ")}</span>` : ""
}

function progressCollapseState(progress, options = {}) {
  const storageKey = options.collapseStorageKey || (
    progress.taskId ? `workflow-progress-card:${progress.taskId}` : null
  )
  let stored = null
  if (storageKey && globalThis.sessionStorage) {
    try {
      stored = globalThis.sessionStorage.getItem(storageKey)
    } catch {
      stored = null
    }
  }
  const fallbackOpen = typeof options.defaultExpanded === "boolean"
    ? options.defaultExpanded
    : Boolean(progress.failed || options.attentionRequired)
  return {
    open: stored === "open" || (stored !== "closed" && fallbackOpen),
    storageKey,
  }
}

export function renderInlineProgress(progress, options = {}) {
  if (!progress) return ""
  const title = options.title || progress.label
  const message = options.message || progress.message
  const summary = progress.resultSummary ? `<div class="workflow-progress__summary">${escapeHtml(progress.resultSummary)}</div>` : ""
  const error = progress.errorMessage ? `<div class="workflow-progress__error">${escapeHtml(progress.errorMessage)}</div>` : ""
  const actionHtml = options.actionsHtml || ""
  const collapsible = options.collapsible !== false
  const collapseState = progressCollapseState(progress, options)
  const className = classesFor(progress, options.className || "")
  const compactHeader = `
    <span class="workflow-progress__header">
      <span class="workflow-progress__title">${escapeHtml(title)}</span>
      <span class="workflow-progress__status">${escapeHtml(progress.statusLabel || "")}</span>
    </span>
    ${renderProgressBar(progress)}
    ${renderMeta(progress, options)}
  `
  const body = `
    <div class="workflow-progress__body">
      ${message ? `<div class="workflow-progress__message">${escapeHtml(message)}</div>` : ""}
      ${summary}
      ${renderAssetSummary(progress.assetSummary)}
      ${renderPhaseArtifacts(progress.phaseArtifacts)}
      ${renderDetailedProgress(progress, options)}
      ${error}
      ${renderWarnings(progress.warnings)}
      ${actionHtml}
    </div>
  `

  if (!collapsible) {
    return `<div class="${className} workflow-progress--expanded"><div class="workflow-progress__compact">${compactHeader}</div>${body}</div>`
  }

  const storageAttr = collapseState.storageKey
    ? ` data-collapse-storage-key="${escapeHtml(collapseState.storageKey)}"`
    : ""

  return `
    <details class="${className}"${storageAttr}${collapseState.open ? " open" : ""}>
      <summary class="workflow-progress__compact" aria-label="${collapseState.open ? "收起" : "展开"}${escapeHtml(title)}进度">
        ${compactHeader}
        <span class="workflow-progress__chevron" aria-hidden="true"></span>
      </summary>
      ${body}
    </details>
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
  const canRetry = options.enableRetry === true
    && Array.isArray(progress.availableActions)
    && progress.availableActions.includes("retry")
  const retryAction = canRetry
    ? `<div class="workflow-progress__actions"><button class="btn btn-sm" data-action="retry-task" data-task-id="${escapeHtml(progress.taskId || "")}" ${options.retryPending ? "disabled" : ""}>${options.retryPending ? "重试中..." : "重试任务"}</button></div>`
    : ""
  return renderInlineProgress(progress, {
    ...options,
    actionsHtml: `${destination}${retryAction}${options.actionsHtml || ""}`,
    className: `workflow-progress--card ${options.className || ""}`.trim(),
  })
}

if (!globalThis.__workflowProgressDetailsBound) {
  globalThis.__workflowProgressDetailsBound = true
  globalThis.document?.addEventListener("toggle", (event) => {
    const details = event.target
    if (!details?.matches?.(".workflow-progress__details, .workflow-progress")) return
    const isCard = details.matches(".workflow-progress")
    const storageKey = isCard
      ? details.getAttribute("data-collapse-storage-key")
      : details.getAttribute("data-details-storage-key")
    if (!storageKey || !globalThis.sessionStorage) return
    try {
      globalThis.sessionStorage.setItem(storageKey, details.open ? "open" : "closed")
    } catch {
      // Ignore storage failures; the details element still works for this render.
    }
    if (isCard) {
      const summary = details.querySelector(":scope > .workflow-progress__compact")
      const title = details.querySelector(":scope > .workflow-progress__compact .workflow-progress__title")?.textContent || "任务"
      summary?.setAttribute("aria-label", `${details.open ? "收起" : "展开"}${title}进度`)
    }
  }, true)
}

export function renderContextSummary(summary = {}) {
  const selected = summary.selected_asset_ids || {}
  const warnings = summary.warnings || []
  const refs = summary.result_refs || []
  const sections = Array.isArray(summary.sections) ? summary.sections : []
  const budgetEvents = Array.isArray(summary.budget_events) ? summary.budget_events : []
  const totalTokens = sections.reduce((sum, section) => sum + (Number(section.token_count) || 0), 0)
  const optionLines = [
    ["模式", summary.context_mode === "working" ? "工作稿" : "正史"],
    ["待确认对象", summary.include_pending_objects ? "包含" : "不包含"],
    ["范围", summary.scope || "-"],
    ["Token", totalTokens ? `${totalTokens}` : "-"],
    ["确认时间", summary.compiled_at || "-"],
  ]

  return `
    <div class="ai-ref-summary">
      <div class="ai-ref-summary-grid">
        ${optionLines.map(([label, value]) => `
          <div class="ai-ref-summary-item">
            <span>${esc(label)}</span>
            <strong>${esc(value)}</strong>
          </div>
        `).join("")}
      </div>
      <div class="ai-ref-section">
        <div class="ai-ref-section-title">参考资料摘要</div>
        ${renderAssetCounts(selected)}
        ${summary.include_pending_objects ? '<div class="ai-ref-warning-note">包含待确认对象，结果需复核</div>' : ""}
      </div>
      ${sections.length ? `
        <div class="ai-ref-section">
          <div class="ai-ref-section-title">参考资料清单</div>
          <div class="ai-ref-section-list">
            ${sections.map(renderSectionItem).join("")}
          </div>
        </div>
      ` : ""}
      ${budgetEvents.length ? `
        <div class="ai-ref-section">
          <div class="ai-ref-section-title">预算裁剪</div>
          <ul class="ai-ref-list">
            ${budgetEvents.map(renderBudgetEvent).join("")}
          </ul>
        </div>
      ` : ""}
      ${warnings.length ? `
        <div class="ai-ref-section">
          <div class="ai-ref-section-title">警告</div>
          <ul class="ai-ref-list">${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${refs.length ? `
        <div class="ai-ref-section">
          <div class="ai-ref-section-title">结果引用</div>
          <ul class="ai-ref-list">${refs.map((r) => `<li>${esc(r.type || "-")} ${esc(r.id || "")}</li>`).join("")}</ul>
        </div>
      ` : ""}
    </div>
  `
}

function renderSectionItem(section) {
  const key = section.key || ""
  const title = section.title || key || "未命名资料"
  const status = renderStatus(section.status)
  const tokenCount = Number(section.token_count) || 0
  const truncated = section.truncated || section.truncated_reason
  const sources = Array.isArray(section.sources) ? section.sources : []
  return `
    <div class="ai-ref-source-card ${section.excluded ? "is-excluded" : ""}">
      <div class="ai-ref-source-head">
        <div>
          <strong>${esc(title)}</strong>
          <span>${esc(key)}</span>
        </div>
        <div class="ai-ref-source-actions">
          <span class="ai-ref-chip">${esc(status)}</span>
          <span class="ai-ref-chip">${tokenCount} tokens</span>
          ${section.can_exclude ? `<button type="button" class="btn btn-ghost btn-xs" data-ai-ref-exclude-section="${escAttr(key)}">本次排除</button>` : ""}
        </div>
      </div>
      ${section.activation_reason ? `<div class="ai-ref-source-reason">${esc(section.activation_reason)}</div>` : ""}
      ${section.preview ? `<div class="ai-ref-source-preview">${esc(section.preview)}</div>` : ""}
      ${truncated ? `<div class="ai-ref-warning-note">已裁剪：${esc(section.truncated_reason || "超过预算")}</div>` : ""}
      ${sources.length ? `
        <div class="ai-ref-source-meta">
          来源 ${sources.length}：
          ${sources.slice(0, 4).map((source) => `<span>${esc(source.label || source.id || source.type || "-")}</span>`).join("")}
        </div>
      ` : '<div class="ai-ref-muted">暂无来源明细</div>'}
    </div>
  `
}

function renderBudgetEvent(event) {
  const label = event.event_type === "evicted" ? "已移除" : "已裁剪"
  const before = Number(event.before_tokens) || 0
  const after = Number(event.after_tokens) || 0
  return `<li>${esc(label)} ${esc(event.section_key || "-")}：${before} → ${after} tokens，${esc(event.reason || "")}</li>`
}

function renderStatus(status) {
  const labels = {
    system: "系统",
    canonical: "正史",
    working: "工作稿",
    candidate: "待确认",
    mixed: "混合",
    unknown: "未知",
  }
  return labels[status] || status || "未知"
}

function renderAssetCounts(selected) {
  const entries = Object.entries(selected)
  if (!entries.length) {
    return '<div class="ai-ref-muted">暂无已选资料</div>'
  }
  return `
    <div class="ai-ref-chip-row">
      ${entries.map(([key, values]) => {
        const count = Array.isArray(values) ? values.length : 0
        return `<span class="ai-ref-chip">${esc(key)}: ${count}</span>`
      }).join("")}
    </div>
  `
}

function escAttr(value) {
  return esc(value).replace(/"/g, "&quot;")
}

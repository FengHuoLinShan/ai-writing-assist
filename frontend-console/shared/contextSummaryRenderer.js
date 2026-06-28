export function renderContextSummary(summary = {}) {
  const selected = summary.selected_asset_ids || {}
  const warnings = summary.warnings || []
  const refs = summary.result_refs || []
  const optionLines = [
    ["模式", summary.context_mode === "working" ? "工作稿" : "正史"],
    ["待确认对象", summary.include_pending_objects ? "包含" : "不包含"],
    ["范围", summary.scope || "-"],
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
      </div>
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

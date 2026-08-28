export function publishImpactHtml(impact, esc) {
  const affected = Array.isArray(impact?.affected_pages) ? impact.affected_pages : []
  const automatic = Array.isArray(impact?.automatic_actions) ? impact.automatic_actions : []
  const notChecked = Array.isArray(impact?.not_checked) ? impact.not_checked : []
  const omissions = Array.isArray(impact?.omissions) ? impact.omissions : []
  const affectedHtml = affected.length
    ? `<ul>${affected.map((item) => {
        const path = (item.path || []).map((node) => node.title || "未命名页面").join(" ← ")
        const sections = item.path?.at(-1)?.section_titles || []
        return `<li><strong>${esc(item.title || "未命名页面")}</strong> · v${Number(item.version_number || 1)}${sections.length ? ` · 分区：${sections.map(esc).join("、")}` : ""}<details><summary>查看显式引用路径</summary><p>${esc(path)}</p></details></li>`
      }).join("")}</ul>`
    : `<p class="world-bible-empty-hint">未发现显式引用；自由文本和其他创作领域未检查。</p>`
  const omissionLabels = {
    invalid_page_reference: "页面引用格式损坏",
    unavailable_page_reference: "页面引用不可用或不在当前项目",
    response_limit: "显式下游未在本次列表展开",
  }
  const omissionHtml = omissions.length
    ? `<div role="alert"><strong>本次预演不完整</strong><ul>${omissions.map((item) => `<li>${Number(item.count || 1)} 条${esc(omissionLabels[item.reason] || "引用未能检查")}</li>`).join("")}</ul><p>这些遗漏不代表没有影响；仍由你决定是否发布。</p></div>`
    : ""
  return `<section class="world-bible-impact-preview">
    <p><strong>${esc(impact?.source?.title || "当前页面")}</strong>${impact?.source?.page_version ? ` · 当前已发布 v${Number(impact.source.page_version)}` : " · 新页面"}</p>
    <p>本次显式引用变化：新增 ${Number(impact?.added_outgoing_refs || 0)}，移除 ${Number(impact?.removed_outgoing_refs || 0)}。</p>
    <h3>发布后会自动处理</h3><ul>${automatic.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
    <h3>建议核对（${affected.length}）</h3>${affectedHtml}
    ${omissionHtml}
    <h3>本次未检查</h3><ul>${notChecked.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
  </section>`
}

export function publishReceiptHtml(receipt, esc) {
  const checked = Array.isArray(receipt?.checked) ? receipt.checked : []
  const notChecked = Array.isArray(receipt?.not_checked) ? receipt.not_checked : []
  const omissions = Array.isArray(receipt?.omissions) ? receipt.omissions : []
  return `<section class="world-bible-impact-preview">
    <p><strong>定向检查</strong> · ${esc(receipt?.scope_label || "当前页面")} · 已发布 v${Number(receipt?.source_version || 1)}</p>
    <p>这份回执只证明下列本地检查实际运行，不表示整个世界观语义完全正确。</p>
    <h3>已检查</h3><ul>${checked.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
    <h3>未检查</h3><ul>${notChecked.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
    <h3>本次遗漏</h3>${omissions.length ? `<ul>${omissions.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : "<p>已列范围内无结构遗漏；未运行项仍见上方。</p>"}
  </section>`
}

import { contextContentModeLabel } from "./assetDisplayState.js"

export function renderContextSummary(summary = {}, options = {}) {
  const selected = summary.selected_asset_ids || {}
  const warnings = summary.warnings || []
  const refs = summary.result_refs || []
  const sections = Array.isArray(summary.sections) ? summary.sections : []
  const budgetEvents = Array.isArray(summary.budget_events) ? summary.budget_events : []
  const blockers = Array.isArray(summary.blockers) ? summary.blockers : []
  const characterPreview = sections.some((section) => section.key === "role_profile" || section.key === "role_visible_knowledge")
  const hasVisibleKnowledge = sections.some((section) => section.key === "role_visible_knowledge")
  const totalTokens = sections.reduce((sum, section) => sum + (Number(section.token_count) || 0), 0)
  const optionLines = [
    ["模式", contextContentModeLabel(summary.context_mode)],
    ["待处理内容", summary.include_pending_objects ? "包含" : "不包含"],
    ["范围", ({ project: "当前项目", chapter: "当前章节", arc: "当前篇章", full: "全部可用资料" })[summary.scope] || "未指定"],
    ...(options.diagnostic ? [["Token", totalTokens ? `${totalTokens}` : "-"]] : []),
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
        ${characterPreview && options.knowledgeRepairHref && !hasVisibleKnowledge ? `
          <div class="ai-ref-warning-note">当前没有可展示的角色知识。</div>
          <a class="btn btn-ghost btn-xs" href="${escAttr(options.knowledgeRepairHref)}" target="_blank" rel="noopener">修正人物知识</a>
        ` : ""}
        ${summary.include_pending_objects ? '<div class="ai-ref-warning-note">包含待处理内容，结果需要人工检查</div>' : ""}
      </div>
      ${renderSections(sections, { ...options, characterPreview })}
      ${renderSelectionItems(summary, options)}
      ${budgetEvents.length ? `
        <div class="ai-ref-section">
          <div class="ai-ref-section-title">预算裁剪</div>
          <ul class="ai-ref-list">
            ${budgetEvents.map((event) => renderBudgetEvent(event, sections, options)).join("")}
          </ul>
        </div>
      ` : ""}
      ${warnings.length ? `
        <div class="ai-ref-section">
          <div class="ai-ref-section-title">警告</div>
          <ul class="ai-ref-list">${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${blockers.length ? `
        <div class="ai-ref-section ai-ref-blockers" role="alert">
          <div class="ai-ref-section-title">开始前需要处理</div>
          <ul class="ai-ref-list">${blockers.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${refs.length ? `
        <div class="ai-ref-section">
          <div class="ai-ref-section-title">结果引用</div>
          ${options.diagnostic
            ? `<ul class="ai-ref-list">${refs.map((r) => `<li>${esc(r.type || "-")} ${esc(r.id || "")}</li>`).join("")}</ul>`
            : `<div class="ai-ref-muted">已记录 ${refs.length} 条结果来源</div>`}
        </div>
      ` : ""}
    </div>
  `
}

function renderSections(sections, options) {
  if (sections.some((section) => Array.isArray(section.items) && section.items.length)) return ""
  if (!sections.length) return ""
  if (!options.characterPreview) {
    return renderSectionGroup("参考资料清单", sections, options)
  }
  const modelSections = sections.filter((section) => section.status !== "director_only")
  const authorSections = sections.filter((section) => section.status === "director_only")
  return [
    renderSectionGroup("会交给角色视角模型", modelSections, options),
    renderSectionGroup("仅供作者约束，不是角色知识", authorSections, options),
  ].join("")
}

function renderSelectionItems(summary, options = {}) {
  const sections = Array.isArray(summary.sections) ? summary.sections : []
  const included = sections.flatMap((section) => (section.items || []).map((item) => ({ ...item, section_title: section.title })))
  const excluded = summary.selection_state?.excluded_items || []
  const omitted = summary.selection_state?.omitted_items || []
  if (!included.length && !excluded.length && !omitted.length) return ""
  return [
    renderItemGroup("必须使用", included.filter((item) => item.selection_state === "required"), options),
    renderItemGroup("我添加的", included.filter((item) => item.selection_state === "author_pinned"), options),
    renderItemGroup("系统找到", included.filter((item) => !["required", "author_pinned"].includes(item.selection_state)), options),
    renderItemGroup("本次不用", excluded, { ...options, restore: true }),
    renderItemGroup("本次未能加入", omitted, { ...options, restore: true, omitted: true }),
  ].join("")
}

function renderItemGroup(title, items, options = {}) {
  if (!items.length) return ""
  return `
    <div class="ai-ref-section">
      <div class="ai-ref-section-title">${esc(title)} <span class="ai-ref-count">${items.length}</span></div>
      <div class="ai-ref-section-list">${items.map((item) => renderContextItem(item, options)).join("")}</div>
    </div>
  `
}

function renderContextItem(item, options = {}) {
  const source = item.source || {}
  const title = item.title || item.section_title || "参考资料"
  return `
    <article class="ai-ref-source-card ${options.restore || options.omitted ? "is-excluded" : ""}">
      <div class="ai-ref-source-head">
        <div><strong>${esc(title)}</strong><span>${esc(item.activation_reason || "")}</span></div>
        <div class="ai-ref-source-actions">
          ${item.status ? `<span class="ai-ref-chip">${esc(renderStatus(item.status))}</span>` : ""}
          ${options.restore && item.selection_ref ? `<button type="button" class="btn btn-ghost btn-xs" data-ai-ref-restore-item="${escAttr(item.key)}">${options.omitted ? "加入本次资料" : "恢复使用"}</button>` : ""}
          ${!options.restore && !options.omitted && item.can_exclude && item.selection_ref ? `<button type="button" class="btn btn-ghost btn-xs" data-ai-ref-exclude-item="${escAttr(item.key)}">本次不用</button>` : ""}
        </div>
      </div>
      ${item.preview ? `<div class="ai-ref-source-preview">${esc(item.preview)}</div>` : ""}
      ${source.label ? `<div class="ai-ref-source-meta">来源：${esc(source.label)}</div>` : ""}
      ${item.omission_reason ? `<div class="ai-ref-warning-note">${esc(item.omission_reason)}</div>` : ""}
    </article>
  `
}

function renderSectionGroup(title, sections, options) {
  if (!sections.length) return ""
  return `
    <div class="ai-ref-section">
      <div class="ai-ref-section-title">${esc(title)}</div>
      <div class="ai-ref-section-list">${sections.map((section) => renderSectionItem(section, options)).join("")}</div>
    </div>
  `
}

function renderSectionItem(section, options = {}) {
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
          ${options.diagnostic ? `<span>${esc(key)}</span>` : ""}
        </div>
        <div class="ai-ref-source-actions">
          <span class="ai-ref-chip">${esc(status)}</span>
          ${options.diagnostic ? `<span class="ai-ref-chip">${tokenCount} tokens</span>` : ""}
          ${section.key === "role_visible_knowledge" && options.knowledgeRepairHref ? `<a class="btn btn-ghost btn-xs" href="${escAttr(options.knowledgeRepairHref)}" target="_blank" rel="noopener">修正人物知识</a>` : ""}
          ${section.can_exclude ? `<button type="button" class="btn btn-ghost btn-xs" data-ai-ref-exclude-section="${escAttr(key)}">本次排除</button>` : ""}
        </div>
      </div>
      ${section.activation_reason ? `<div class="ai-ref-source-reason">${esc(section.activation_reason)}</div>` : ""}
      ${section.key === "scene_world_state"
        ? renderSceneWorldState(section, options)
        : section.key === "role_visible_knowledge" && section.content
        ? `<div class="ai-ref-source-preview">${esc(section.content).replace(/\n/g, "<br>")}</div>`
        : section.preview ? `<div class="ai-ref-source-preview">${esc(section.preview)}</div>` : ""}
      ${section.key === "role_visible_knowledge" && options.knowledgeRepairHref ? '<div class="ai-ref-source-reason">修改后回到这里点“重新整理”；不会自动再次生成正文。</div>' : ""}
      ${truncated ? `<div class="ai-ref-warning-note">已裁剪：${esc(section.truncated_reason || "超过预算")}</div>` : ""}
      ${sources.length ? `
        <div class="ai-ref-source-meta">
          来源 ${sources.length}：
          ${sources.slice(0, 4).map((source) => `<span>${esc(source.label || sourceTypeLabel(source.type))}</span>`).join("")}
        </div>
      ` : '<div class="ai-ref-muted">暂无来源明细</div>'}
    </div>
  `
}

function renderSceneWorldState(section, options) {
  const metadata = section.retrieval_metadata || {}
  const dimensions = Array.isArray(metadata.dimensions) ? metadata.dimensions : []
  const omissions = Array.isArray(metadata.omissions) ? metadata.omissions : []
  return `
    <div class="ai-ref-source-preview">
      <strong>当时可证</strong>：${esc(metadata.coverage_label || "Scene 时点证据不完整")}
    </div>
    ${dimensions.length ? `<div class="ai-ref-chip-row">${dimensions.map((item) => `<span class="ai-ref-chip">${esc(item.label || "状态")} · ${esc(item.state_label || "尚无时间锚")}</span>`).join("")}</div>` : ""}
    ${omissions.length ? `
      <div class="ai-ref-warning-note"><strong>尚未覆盖</strong>：${omissions.slice(0, 8).map((item) => `${esc(item.label || "相关对象")}（${esc(item.reason || "尚无时间锚")}）`).join("、")}</div>
    ` : ""}
    <div class="ai-ref-source-reason"><strong>人物所信</strong>：以上属于环境约束，人物的判断仍以“角色可见知识”为准。</div>
    <div class="ai-ref-source-reason"><strong>当前正典</strong>：${esc(metadata.current_canon_note || "只作为修复参考，不回填过去。")}</div>
    ${options.sceneStateRepairHref ? `<a class="btn btn-ghost btn-xs" href="${escAttr(options.sceneStateRepairHref)}" target="_blank" rel="noopener">核对 Scene 时点</a><div class="ai-ref-source-reason">修复后回到这里点“重新整理”；不会自动再次生成正文。</div>` : ""}
  `
}

function renderBudgetEvent(event, sections, options) {
  const label = event.event_type === "evicted" ? "已移除" : "已裁剪"
  const title = sections.find((section) => section.key === event.section_key)?.title || "一组参考资料"
  if (!options.diagnostic) return `<li>${esc(label)}${esc(title)}：${esc(event.reason || "超出本次可用范围")}</li>`
  const before = Number(event.before_tokens) || 0
  const after = Number(event.after_tokens) || 0
  return `<li>${esc(label)} ${esc(event.section_key || "-")}：${before} → ${after} tokens，${esc(event.reason || "")}</li>`
}

function renderStatus(status) {
  const labels = {
    system: "系统",
    canonical: contextContentModeLabel("canonical", { compact: true }),
    working: contextContentModeLabel("working", { compact: true }),
    candidate: contextContentModeLabel("candidate", { compact: true }),
    mixed: "混合",
    director_only: "作者约束",
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
        const label = ({ project: "项目资料", context_sections: "参考分区", characters: "人物", world_entities: "世界资料", scenes: "场景", chapters: "章节", threads: "剧情线" })[key] || "参考资料"
        return `<span class="ai-ref-chip">${esc(label)}: ${count}</span>`
      }).join("")}
    </div>
  `
}

function sourceTypeLabel(type) {
  return ({ character: "人物", entity: "世界资料", rag: "检索资料", chapter: "章节", scene: "场景" })[type] || "来源"
}

function escAttr(value) {
  return esc(value).replace(/"/g, "&quot;")
}

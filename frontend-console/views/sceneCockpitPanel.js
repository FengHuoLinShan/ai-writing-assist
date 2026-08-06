const DEFAULT_ORDER = [
  "scene_header",
  "goal",
  "must_happen",
  "must_not_happen",
  "core_conflict",
  "map_summary",
  "continuity",
  "references",
  "foreshadowing",
]

const LABELS = {
  scene_header: "场景",
  goal: "目标",
  must_happen: "必须发生",
  must_not_happen: "禁止发生",
  core_conflict: "核心冲突",
  map_summary: "地图摘要 / 世界状态风险",
  continuity: "前后连续性摘要",
  references: "参考资料",
  foreshadowing: "伏笔 / 揭示",
}

const COCKPIT_TABS = ["alerts", "people", "place", "lore", "map"]

const ALERT_SEVERITY = {
  high: { label: "高", symbol: "!" },
  medium: { label: "中", symbol: "!" },
  low: { label: "提示", symbol: "·" },
  info: { label: "信息", symbol: "i" },
}

function normalizeActiveTab(tab) {
  return COCKPIT_TABS.includes(tab) ? tab : "lore"
}

export function sceneCockpitOrderKey(projectId) {
  return `writing_scene_cockpit_order:${projectId || "default"}`
}

export function saveSceneCockpitOrder(projectId, order) {
  try {
    localStorage.setItem(sceneCockpitOrderKey(projectId), JSON.stringify(order))
  } catch {
    // localStorage unavailable; keep default order.
  }
}

export function loadSceneCockpitOrder(projectId) {
  try {
    const raw = localStorage.getItem(sceneCockpitOrderKey(projectId))
    if (!raw) return DEFAULT_ORDER
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return DEFAULT_ORDER
    const known = parsed.filter((key) => DEFAULT_ORDER.includes(key))
    return [...known, ...DEFAULT_ORDER.filter((key) => !known.includes(key))]
  } catch {
    return DEFAULT_ORDER
  }
}

export function renderSceneCockpitPanel({
  projectId,
  scene,
  people: explicitPeople,
  location: explicitLocation,
  mapSummaryHtml = "",
  compact = false,
  activeTab = "lore",
  alerts = [],
  alertLoading = false,
  alertError = null,
  latestCheck = null,
} = {}) {
  const selectedTab = normalizeActiveTab(activeTab)
  const order = loadSceneCockpitOrder(projectId)
  const modules = order
    .filter((key) => key !== "map_summary")
    .map((key) => renderModule(key, scene, "", compact))
    .filter(Boolean)
    .join("")
  const people = Array.isArray(explicitPeople)
    ? explicitPeople
    : (Array.isArray(scene?.scene_characters) ? scene.scene_characters : [])
  const location = explicitLocation !== undefined
    ? explicitLocation
    : (scene?.primary_location || scene?.location || scene?.location_id || null)

  return `
    <div class="scene-cockpit" data-scene-cockpit-project="${esc(projectId || "")}">
      <div class="scene-cockpit__title">
        <span>写作副驾驶</span>
        <button class="btn btn-sm scene-cockpit-organize" data-action="open-scene-workbench">整理</button>
      </div>
      ${scene ? renderAlertSummary(alerts, alertLoading) : ""}
      ${!scene ? `
        <div class="scene-cockpit-empty">
          当前章节未关联场景。${projectId ? "请从左侧选择场景，或到故事结构中整理。" : ""}
        </div>
      ` : ""}
      ${scene ? `
        <div class="cockpit-tabs" role="tablist" aria-label="场景参考">
          <button class="cockpit-tab ${selectedTab === "alerts" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="alerts" type="button">警报</button>
          <button class="cockpit-tab ${selectedTab === "people" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="people" type="button">人物</button>
          <button class="cockpit-tab ${selectedTab === "place" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="place" type="button">地点</button>
          <button class="cockpit-tab ${selectedTab === "lore" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="lore" type="button">设定</button>
          <button class="cockpit-tab ${selectedTab === "map" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="map" type="button">地图</button>
        </div>
        <div class="cockpit-body">
          <section class="cockpit-panel ${selectedTab === "alerts" ? "" : "hidden"}" data-panel="alerts">
            ${renderAlertPanel({ alerts, alertLoading, alertError, latestCheck })}
          </section>
          <section class="cockpit-panel ${selectedTab === "people" ? "" : "hidden"}" data-panel="people">
            ${renderPeoplePanel(people)}
          </section>
          <section class="cockpit-panel ${selectedTab === "place" ? "" : "hidden"}" data-panel="place">
            ${renderPlacePanel(location)}
          </section>
          <section class="cockpit-panel ${selectedTab === "lore" ? "" : "hidden"}" data-panel="lore">
            ${modules || '<div class="cockpit-empty">暂无关联设定</div>'}
          </section>
          <section class="cockpit-panel ${selectedTab === "map" ? "" : "hidden"}" data-panel="map">
            ${mapSummaryHtml || '<div class="cockpit-empty">暂无地图摘要</div>'}
          </section>
        </div>
      ` : ""}
    </div>
  `
}

function renderAlertSummary(alerts, loading) {
  const safeAlerts = Array.isArray(alerts) ? alerts : []
  const summary = summarizeAlerts(safeAlerts)
  if (loading && summary.actionableCount === 0) {
    return '<div class="scene-alert-summary scene-alert-summary--loading" aria-live="polite">警报加载中…</div>'
  }
  if (summary.actionableCount === 0) {
    return `
      <div class="scene-alert-summary scene-alert-summary--clear" aria-live="polite">
        <span class="scene-alert-summary__mark" aria-hidden="true">✓</span>
        <span>当前未发现确定性警报</span>
      </div>
    `
  }
  const severity = ALERT_SEVERITY[summary.highestSeverity] || ALERT_SEVERITY.info
  return `
    <div class="scene-alert-summary scene-alert-summary--${esc(summary.highestSeverity)}" aria-live="polite">
      <span class="scene-alert-summary__mark" aria-hidden="true">${esc(severity.symbol)}</span>
      <span>${esc(summary.actionableCount)} 项警报 · 最高${esc(severity.label)}严重度${summary.hasStaleCheck ? " · 最近校验已过期" : ""}</span>
    </div>
  `
}

function renderAlertPanel({ alerts, alertLoading, alertError, latestCheck }) {
  const safeAlerts = Array.isArray(alerts) ? alerts : []
  const groups = ["high", "medium", "low", "info"].map((severity) => {
    const entries = safeAlerts.filter((item) => item?.severity === severity)
    if (!entries.length) return ""
    const severityMeta = ALERT_SEVERITY[severity]
    return `
      <section class="scene-alert-group scene-alert-group--${esc(severity)}">
        <div class="scene-alert-group__title">${esc(severityMeta.label)}严重度 · ${esc(entries.length)}</div>
        ${entries.map((item) => `
          <article class="scene-alert-card scene-alert-card--${esc(severity)}">
            <div class="scene-alert-card__head">
              <span class="scene-alert-card__source">${esc(item.source || "现场")}</span>
              ${item.stale ? '<span class="scene-alert-card__stale">已过期</span>' : ""}
            </div>
            <div class="scene-alert-card__message">${esc(item.message || "")}</div>
            ${item.detail ? `<div class="scene-alert-card__detail">${esc(item.detail)}</div>` : ""}
          </article>
        `).join("")}
      </section>
    `
  }).join("")

  const hasMatchingErrorAlert = alertError && safeAlerts.some((item) => (
    item?.source === "最近校验" && String(item?.message || "") === String(alertError)
  ))
  const status = alertError && !hasMatchingErrorAlert
    ? `<div class="scene-alert-load-error">${esc(alertError)}</div>`
    : (alertLoading ? '<div class="scene-alert-loading">正在刷新最近校验…</div>' : "")
  return `
    <div class="scene-alert-panel">
      ${status}
      ${groups || (alertLoading ? "" : '<div class="cockpit-empty">当前未发现确定性警报</div>')}
      <p class="scene-alert-disclaimer">现场警报只做字面和状态检查，不代表正文没有其他问题，也不会自动运行 AI。</p>
      <div class="scene-alert-actions">
        ${latestCheck ? '<button class="btn btn-sm" data-action="open-cockpit-conflict-check" type="button">查看最近校验</button>' : ""}
        <button class="btn btn-sm btn-primary" data-action="run-cockpit-conflict-check" type="button">运行规则检查</button>
      </div>
    </div>
  `
}

function summarizeAlerts(alerts) {
  const counts = { high: 0, medium: 0, low: 0, info: 0 }
  for (const item of alerts || []) {
    if (item?.severity in counts) counts[item.severity] += 1
  }
  const actionableCount = counts.high + counts.medium + counts.low
  const highestSeverity = ["high", "medium", "low"].find((severity) => counts[severity] > 0) || "info"
  return {
    counts,
    actionableCount,
    highestSeverity,
    hasStaleCheck: (alerts || []).some((item) => item?.stale === true),
  }
}

function renderPeoplePanel(people) {
  if (!people.length) return '<div class="cockpit-empty">暂无关联人物</div>'
  return `
    <div class="cockpit-people-list">
      ${people.map((person) => {
        const name = person.name || person.title || "未命名"
        return `
          <article class="cockpit-person-card">
            <div class="person-avatar" style="background:${avatarColor(name)}">${esc(name.slice(0, 1) || "?")}</div>
            <div class="person-info">
              <div class="person-name">${esc(name)}</div>
              <div class="person-status">${esc(person.role || person.summary || person.status || "暂无摘要")}</div>
            </div>
            <button class="btn btn-sm btn-insert" data-action="insert-person" data-name="${esc(name)}" type="button">插入</button>
          </article>
        `
      }).join("")}
    </div>
  `
}

function renderPlacePanel(location) {
  if (!location) return '<div class="cockpit-empty">暂无地点信息</div>'
  if (typeof location === "string") {
    return `<div class="cockpit-place-card"><div class="place-name">${esc(location)}</div></div>`
  }
  return `
    <div class="cockpit-place-card">
      <div class="place-name">${esc(location.name || location.title || "未知地点")}</div>
      <div class="place-desc">${esc(location.description || location.summary || "")}</div>
    </div>
  `
}

function avatarColor(name) {
  const colors = ["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899"]
  let hash = 0
  for (let i = 0; i < (name || "").length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return colors[Math.abs(hash) % colors.length]
}

function renderModule(key, scene, mapSummaryHtml, compact) {
  if (!scene && key !== "map_summary") return ""
  const body = moduleBody(key, scene, mapSummaryHtml)
  if (!body) return ""
  const tail = ["continuity", "references", "foreshadowing"].includes(key)
  const collapsed = compact && tail
  return `
    <section class="scene-cockpit-module ${collapsed ? "is-collapsed" : ""}"
      data-cockpit-module="${esc(key)}" draggable="true">
      <button class="scene-cockpit-module__head" data-action="toggle-cockpit-module" data-module="${esc(key)}">
        <span>${esc(LABELS[key] || key)}</span>
        <span class="scene-cockpit-module__handle" title="拖拽排序">⋮⋮</span>
      </button>
      <div class="scene-cockpit-module__body">${body}</div>
    </section>
  `
}

function moduleBody(key, scene, mapSummaryHtml) {
  if (key === "scene_header") {
    return `
      <div class="scene-cockpit-scene-title">${esc(scene?.title || "未命名场景")}</div>
      <div class="scene-cockpit-meta">
        <span>#${esc(scene?.scene_index ?? "-")}</span>
        <span>${esc(scene?.narrative_tag || "draft")}</span>
      </div>
    `
  }
  if (key === "map_summary") return mapSummaryHtml || '<div class="muted">暂无地图摘要</div>'
  const value = {
    goal: scene?.goal,
    must_happen: scene?.must_happen,
    must_not_happen: scene?.must_not_happen,
    core_conflict: scene?.core_conflict,
    continuity: scene?.emotional_beat,
    references: scene?.source,
    foreshadowing: scene?.foreshadowing || scene?.reveals,
  }[key]
  return value
    ? `<div class="scene-cockpit-text">${esc(value)}</div>`
    : '<div class="muted">暂无</div>'
}

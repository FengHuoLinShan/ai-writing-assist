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
  scene_header: "Scene",
  goal: "目标",
  must_happen: "必须发生",
  must_not_happen: "禁止发生",
  core_conflict: "核心冲突",
  map_summary: "地图摘要 / 世界状态风险",
  continuity: "前后连续性摘要",
  references: "参考资料",
  foreshadowing: "伏笔 / 揭示",
}

const COCKPIT_TABS = ["people", "place", "lore", "map"]

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
      ${!scene ? `
        <div class="scene-cockpit-empty">
          当前章节未关联 Scene。${projectId ? "请从左侧选择 Scene 或到场景工作台整理。" : ""}
        </div>
      ` : ""}
      ${scene ? `
        <div class="cockpit-tabs" role="tablist" aria-label="Scene 参考">
          <button class="cockpit-tab ${selectedTab === "people" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="people" type="button">人物</button>
          <button class="cockpit-tab ${selectedTab === "place" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="place" type="button">地点</button>
          <button class="cockpit-tab ${selectedTab === "lore" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="lore" type="button">设定</button>
          <button class="cockpit-tab ${selectedTab === "map" ? "active" : ""}" data-action="switch-cockpit-tab" data-tab="map" type="button">地图</button>
        </div>
        <div class="cockpit-body">
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
      <div class="scene-cockpit-scene-title">${esc(scene?.title || "未命名 Scene")}</div>
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

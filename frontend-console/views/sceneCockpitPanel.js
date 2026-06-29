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
  mapSummaryHtml = "",
  compact = false,
} = {}) {
  const order = loadSceneCockpitOrder(projectId)
  const modules = order
    .map((key) => renderModule(key, scene, mapSummaryHtml, compact))
    .filter(Boolean)
    .join("")

  return `
    <div class="scene-cockpit" data-scene-cockpit-project="${esc(projectId || "")}">
      <div class="scene-cockpit__title">Scene 驾驶舱</div>
      ${scene ? modules : `
        <div class="scene-cockpit-empty">
          当前章节未关联 Scene。${projectId ? "请从左侧选择 Scene 或到大纲管理。" : ""}
        </div>
      `}
      <button class="btn btn-sm scene-cockpit-outline" data-action="open-outline">管理大纲</button>
    </div>
  `
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

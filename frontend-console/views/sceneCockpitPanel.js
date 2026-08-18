const DEFAULT_ORDER = [
  "scene_header", "goal", "must_happen", "must_not_happen", "core_conflict",
  "continuity", "references", "foreshadowing",
]

export function sceneCockpitOrderKey(projectId) {
  return `writing_scene_cockpit_order:${projectId || "default"}`
}

export function saveSceneCockpitOrder(projectId, order) {
  try { localStorage.setItem(sceneCockpitOrderKey(projectId), JSON.stringify(order)) } catch { /* use defaults */ }
}

export function loadSceneCockpitOrder(projectId) {
  try {
    const raw = localStorage.getItem(sceneCockpitOrderKey(projectId))
    if (!raw) return [...DEFAULT_ORDER]
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return [...DEFAULT_ORDER]
    const known = parsed.filter((key) => DEFAULT_ORDER.includes(key))
    return [...known, ...DEFAULT_ORDER.filter((key) => !known.includes(key))]
  } catch {
    return [...DEFAULT_ORDER]
  }
}

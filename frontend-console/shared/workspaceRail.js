function escapeHtml(value) {
  if (typeof globalThis.esc === "function") return globalThis.esc(value)
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

function readStoredState(key) {
  if (!key || !globalThis.sessionStorage) return null
  try {
    return globalThis.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

export function workspaceRailKey(view, projectId, rail) {
  return `workspace-rail:${projectId || "global"}:${view}:${rail}`
}

export function renderWorkspaceRail({
  key,
  title,
  content,
  className = "",
  defaultOpen = true,
}) {
  const stored = readStoredState(key)
  const open = stored === "open" || (stored !== "closed" && defaultOpen)
  const stateLabel = open ? "收起" : "展开"
  return `
    <details class="workspace-rail ${escapeHtml(className)}" data-workspace-rail-key="${escapeHtml(key)}"${open ? " open" : ""}>
      <summary class="workspace-rail__summary" aria-label="${stateLabel}${escapeHtml(title)}">
        <span class="workspace-rail__icon" aria-hidden="true"></span>
        <span class="workspace-rail__title">${escapeHtml(title)}</span>
        <span class="workspace-rail__state">${stateLabel}</span>
      </summary>
      <div class="workspace-rail__body">${content}</div>
    </details>
  `
}

if (!globalThis.__workspaceRailToggleBound) {
  globalThis.__workspaceRailToggleBound = true
  globalThis.document?.addEventListener("toggle", (event) => {
    const rail = event.target
    if (!rail?.matches?.(".workspace-rail")) return
    const key = rail.getAttribute("data-workspace-rail-key")
    if (key && globalThis.sessionStorage) {
      try {
        globalThis.sessionStorage.setItem(key, rail.open ? "open" : "closed")
      } catch {
        // The rail still works when browser storage is unavailable.
      }
    }
    const title = rail.querySelector(".workspace-rail__title")?.textContent || "辅助栏"
    const stateLabel = rail.open ? "收起" : "展开"
    const summary = rail.querySelector(".workspace-rail__summary")
    const state = rail.querySelector(".workspace-rail__state")
    if (summary) summary.setAttribute("aria-label", `${stateLabel}${title}`)
    if (state) state.textContent = stateLabel
  }, true)
}

import { getAppState } from "../../../bridge/index.js"

export function captureWorldOperationScope() {
  const state = getAppState()
  return {
    projectId: state?.currentProjectId || null,
    view: state?.currentView || null,
    subView: state?.currentSubView || null,
  }
}

export function ownsWorldOperationScope(scope) {
  const state = getAppState()
  return Boolean(
    scope
    && state
    && (state.currentProjectId || null) === scope.projectId
    && (state.currentView || null) === scope.view
    && (state.currentSubView || null) === scope.subView,
  )
}

export function captureModalOwner(node = null) {
  const body = document.getElementById("modal-body")
  const overlay = document.getElementById("modal-overlay")
  return {
    body,
    overlay,
    node: node || body?.firstElementChild || null,
    open: Boolean(overlay && !overlay.classList.contains("hidden")),
  }
}

export function ownsModalOwner(owner) {
  if (!owner?.body || !owner?.overlay) return true
  if (document.getElementById("modal-body") !== owner.body || document.getElementById("modal-overlay") !== owner.overlay) return false
  if (!owner.open) {
    return owner.overlay.classList.contains("hidden") && owner.body.firstElementChild === owner.node
  }
  return Boolean(
    owner.node?.isConnected
    && owner.body.contains(owner.node)
    && !owner.overlay.classList.contains("hidden"),
  )
}

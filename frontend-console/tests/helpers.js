const defaultTestState = Object.freeze({
  currentProjectId: null,
  currentProject: null,
  currentView: "project",
  currentSubView: null,
  selectedItem: null,
  projects: [],
  viewStates: {},
  loading: false,
  error: null,
  toast: null,
  backendConnected: true,
})

export function resetState(overrides = {}) {
  if (!globalThis.state) globalThis.state = {}
  for (const key of Object.keys(globalThis.state)) delete globalThis.state[key]
  Object.assign(globalThis.state, structuredClone(defaultTestState), overrides)
}

export function clearDocument() {
  if (typeof document !== "undefined") document.body.innerHTML = ""
}

export function latestModal() {
  const call = showModal.mock.calls.at(-1)
  if (!call) return null
  const [title, body, buttons = []] = call
  return { title, body, buttons }
}

/**
 * State side-effect helpers split out from state.js.
 *
 * This file is loaded as a classic script before state.js so it can keep the
 * existing global state API stable while Vitest imports it for side effects.
 */
(function () {
  function projectStorageSummary(project) {
    if (!project || typeof project !== "object") return null
    const summary = {}
    for (const key of ["id", "title", "name"]) {
      if (Object.prototype.hasOwnProperty.call(project, key)) {
        summary[key] = project[key]
      }
    }
    return Object.keys(summary).length > 0 ? summary : null
  }

  function applyProjectStateSideEffects(key, value, oldValue, target) {
    if (key === "currentProjectId") {
      if (target.viewStates?.writing && oldValue !== value) {
        delete target.viewStates.writing
      }
      try {
        if (value) localStorage.setItem("novel_currentProjectId", value)
        else localStorage.removeItem("novel_currentProjectId")
      } catch {}
    }
    if (key === "currentProject") {
      try {
        const summary = projectStorageSummary(value)
        if (summary) localStorage.setItem("novel_currentProject", JSON.stringify(summary))
        else localStorage.removeItem("novel_currentProject")
      } catch {}
    }
  }

  function notifyStateListeners(listeners, key, value, oldValue) {
    for (const listener of listeners) {
      try {
        listener(key, value, oldValue)
      } catch (e) {
        console.error("State listener error:", e)
      }
    }
  }

  function applyStateSideEffects({ key, value, oldValue, target }) {
    applyProjectStateSideEffects(key, value, oldValue, target)
  }

  const exported = Object.freeze({
    projectStorageSummary,
    applyProjectStateSideEffects,
    applyStateSideEffects,
    notifyStateListeners,
  })

  if (typeof window !== "undefined") {
    window.stateSlices = exported
  }
  if (typeof globalThis !== "undefined") {
    globalThis.stateSlices = exported
  }
})()

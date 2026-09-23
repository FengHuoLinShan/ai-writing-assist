import { createForecast } from "./useForecast.js"
import { ACCOUNT_MARKER_KEY } from "../../shared/accountStorage.js"

const stores = new Map()
let sequence = 0

// One account/project feed. The foremost active host supplies this tab's focus.
export function subscribeForecast(projectId) {
  const key = `${localStorage.getItem(ACCOUNT_MARKER_KEY) || "local"}:${projectId}`
  let entry = stores.get(key)
  if (!entry) {
    entry = { readers: new Map(), owner: null, signature: null, focused: null, configuration: Promise.resolve() }
    entry.forecast = createForecast({ editor: () => entry.owner?.editor, composing: () => entry.owner?.composing })
    entry.timer = setInterval(() => {
      const { state } = entry.forecast
      if (entry.owner && state.available && !state.loading && !entry.owner.composing) {
        void entry.forecast.refresh().catch(error => { state.error = error.message || "资料暂时无法刷新。" })
      }
    }, 15000)
    stores.set(key, entry)
  }
  const id = Symbol()
  function selectOwner() {
    const focused = entry.readers.get(entry.focused)
    entry.owner = focused?.active ? focused : [...entry.readers.values()].filter(value => value.active)
      .sort((a, b) => b.priority - a.priority || b.sequence - a.sequence)[0] || null
    if (!entry.owner) { entry.signature = null; return }
    const { context, editor, composing } = entry.owner
    if (composing && entry.forecast.state.projectId === projectId) return
    const signature = JSON.stringify([context, editor?.draftId, editor?.sceneId, editor?.dirty, editor?.saving, editor?.lastSavedContent ?? editor?.savedContent])
    if (signature === entry.signature) return entry.configuration
    entry.signature = signature
    entry.configuration = entry.forecast.configure(projectId, context)
    return entry.configuration
  }
  return {
    forecast: entry.forecast,
    update(value) { entry.readers.set(id, { ...value, sequence: ++sequence }); selectOwner() },
    async activate() {
      entry.focused = id
      const configuration = selectOwner()
      await configuration
      return entry.focused === id && entry.owner === entry.readers.get(id) && entry.configuration === configuration
    },
    release() {
      entry.readers.delete(id)
      if (entry.readers.size) selectOwner()
      else { clearInterval(entry.timer); entry.forecast.dispose(); stores.delete(key) }
    },
  }
}

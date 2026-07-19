import { onBeforeUnmount, onMounted, reactive } from "vue"

const SAVE_STATES = new Set(["saving", "unsaved", "saved"])

export function useWordcountDashboard() {
  const dashboard = reactive({
    chapterIndex: null,
    chapterWords: 0,
    todayWords: 0,
    saveState: "saved",
  })

  function update({ chapterIndex = null, chapterWords = 0, todayWords = 0, saveState = "saved" } = {}) {
    dashboard.chapterIndex = chapterIndex == null ? null : Number(chapterIndex)
    dashboard.chapterWords = Number(chapterWords || 0)
    dashboard.todayWords = Number(todayWords || 0)
    dashboard.saveState = SAVE_STATES.has(saveState) ? saveState : "saved"
  }

  function onDashboardUpdate(event) { update(event?.detail || {}) }
  onMounted(() => globalThis.window?.addEventListener("writing:dashboard-update", onDashboardUpdate))
  onBeforeUnmount(() => globalThis.window?.removeEventListener("writing:dashboard-update", onDashboardUpdate))

  return { dashboard, update }
}

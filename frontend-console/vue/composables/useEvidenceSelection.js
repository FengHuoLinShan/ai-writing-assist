import { ref, watch } from "vue"
import { getToast } from "../bridge/index.js"

// Only source references are retained here; the server revalidates them at confirmation.
export function useEvidenceSelection(scopeKey) {
  const refs = ref([])
  const key = () => `novel_focused_refs:${scopeKey()}`
  watch(scopeKey, () => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(key()) || "[]")
      refs.value = Array.isArray(stored) ? stored.filter(item => item && ["target", "source_range"].includes(item.kind)) : []
    } catch { refs.value = [] }
  }, { immediate: true, flush: "sync" })
  function add(value) {
    if (!value || refs.value.some(item => JSON.stringify(item) === JSON.stringify(value))) return
    refs.value = [...refs.value, value]
    try { sessionStorage.setItem(key(), JSON.stringify(refs.value)) }
    catch { getToast()("资料已加入当前页面；本机暂时无法保留选择，请在离开前完成资料确认。", "warning") }
  }
  function clear() {
    refs.value = []
    try { sessionStorage.removeItem(key()) }
    catch { getToast()("当前选择已清空；本机记录暂时不可用。", "warning") }
  }
  return { refs, add, clear }
}

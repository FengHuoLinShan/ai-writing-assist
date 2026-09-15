import { computed, ref, watch } from "vue"
import { getToast } from "../bridge/index.js"

// Only source references are retained here; the server revalidates them at confirmation.
export function useEvidenceSelection(scopeKey) {
  const storedRefs = ref([])
  const withoutRole = ({ selection_role: _selectionRole, ...item }) => item
  const refs = computed(() => storedRefs.value.filter(item => item.selection_role !== "audit").map(withoutRole))
  const auditRefs = computed(() => storedRefs.value.filter(item => item.selection_role === "audit").map(withoutRole))
  const key = () => `novel_focused_refs:${scopeKey()}`
  watch(scopeKey, () => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(key()) || "[]")
      storedRefs.value = Array.isArray(stored) ? stored.filter(item => item && ["target", "source_range"].includes(item.kind)) : []
    } catch { storedRefs.value = [] }
  }, { immediate: true, flush: "sync" })
  function add(value, selectionRole = "generation") {
    if (!value) return
    const next = { ...value, selection_role: selectionRole === "audit" ? "audit" : "generation" }
    if (storedRefs.value.some(item => JSON.stringify(item) === JSON.stringify(next))) return
    storedRefs.value = [...storedRefs.value, next]
    try { sessionStorage.setItem(key(), JSON.stringify(storedRefs.value)) }
    catch { getToast()("资料已加入当前页面；本机暂时无法保留选择，请在离开前完成资料确认。", "warning") }
  }
  function addAudit(value) { add(value, "audit") }
  function clear() {
    storedRefs.value = []
    try { sessionStorage.removeItem(key()) }
    catch { getToast()("当前选择已清空；本机记录暂时不可用。", "warning") }
  }
  return { refs, auditRefs, add, addAudit, clear }
}

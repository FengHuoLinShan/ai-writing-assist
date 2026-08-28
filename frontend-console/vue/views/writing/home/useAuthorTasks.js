import { onMounted, ref } from "vue"
import { getApi, getToast } from "../../../bridge/index.js"

export function localAuthorDate() {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60_000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

export function useAuthorTasks(projectId, scope) {
  const api = getApi()
  const toast = getToast()
  const items = ref([])
  const counts = ref({ today: 0, inbox: 0, later: 0, completed: 0 })
  const loading = ref(false)
  const loadError = ref("")
  const busyIds = ref(new Set())
  let loadGeneration = 0

  async function load() {
    const generation = ++loadGeneration
    loading.value = true
    loadError.value = ""
    try {
      const result = await api.projects.listAuthorTasks(projectId, {
        scope,
        on_date: localAuthorDate(),
        limit: 100,
      })
      if (generation !== loadGeneration) return
      items.value = Array.isArray(result?.items) ? result.items : []
      counts.value = result?.counts || counts.value
    } catch (error) {
      if (generation !== loadGeneration) return
      loadError.value = error?.message || "任务暂时无法加载"
    } finally {
      if (generation === loadGeneration) loading.value = false
    }
  }

  async function create(payload) {
    loading.value = true
    try {
      await api.projects.createAuthorTask(projectId, payload)
      toast("任务已添加", "success")
      await load()
      return true
    } catch (error) {
      toast(error?.message || "任务保存失败", "error")
      return false
    } finally {
      loading.value = false
    }
  }

  async function patch(task, payload) {
    if (!task?.id || busyIds.value.has(task.id)) return null
    busyIds.value = new Set([...busyIds.value, task.id])
    try {
      const updated = await api.projects.patchAuthorTask(projectId, task.id, {
        ...payload,
        expected_updated_at: task.updated_at || undefined,
      })
      await load()
      return updated
    } catch (error) {
      toast(error?.message || "任务更新失败", "error")
      if (error?.status === 409) await load()
      return null
    } finally {
      const next = new Set(busyIds.value)
      next.delete(task.id)
      busyIds.value = next
    }
  }

  onMounted(load)
  return { items, counts, loading, loadError, busyIds, load, create, patch }
}

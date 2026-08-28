import { onMounted, ref } from "vue"
import { getApi, getToast } from "../../../bridge/index.js"

const TASK_SCOPES = ["today", "inbox", "later", "completed", "archived"]

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
  const conflict = ref(null)
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
      return items.value
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
      const expectedUpdatedAt = conflict.value?.taskId === task.id
        ? conflict.value.updatedAt
        : task.updated_at
      if (!expectedUpdatedAt) return null
      const updated = await api.projects.patchAuthorTask(projectId, task.id, {
        ...payload,
        expected_updated_at: expectedUpdatedAt,
      })
      conflict.value = null
      await load()
      return updated
    } catch (error) {
      if (error?.status === 409) {
        const currentItems = await load()
        let latest = currentItems?.find((item) => item.id === task.id) || null
        for (const nextScope of TASK_SCOPES) {
          if (latest) break
          if (nextScope === scope) continue
          try {
            const result = await api.projects.listAuthorTasks(projectId, {
              scope: nextScope,
              on_date: localAuthorDate(),
              limit: 100,
            })
            latest = result?.items?.find((item) => item.id === task.id) || null
          } catch {
            // The current list remains usable; another scope may still resolve the baseline.
          }
        }
        conflict.value = {
          taskId: task.id,
          updatedAt: latest?.updated_at || null,
          message: latest
            ? "任务已在其他位置更新。你的输入已保留，请确认后再次保存。"
            : "任务状态已变化，请关闭表单后重新打开。",
        }
      } else {
        toast(error?.message || "任务更新失败", "error")
      }
      return null
    } finally {
      const next = new Set(busyIds.value)
      next.delete(task.id)
      busyIds.value = next
    }
  }

  function clearConflict() {
    conflict.value = null
  }

  onMounted(load)
  return { items, counts, loading, loadError, busyIds, conflict, load, create, patch, clearConflict }
}

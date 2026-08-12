/**
 * outlineBulkSelection — outline 视图结构子标签的批量选择管理。
 *
 * 参照 worldBulkSelection.js，状态落 outlineSession（Vue reactive），
 * 纯函数 runBulkAction / bulkResultMessage / selectedItemsFrom 从 shared 复用。
 * DOM 契约（data-action/data-scope/data-id、.selection-checkbox）由组件模板保留。
 */
import { reactive } from "vue"

export { runBulkAction, bulkResultMessage, selectedItemsFrom } from "../../../../shared/bulkSelection.js"

/** outline 会话级批量选择状态（scope → Set<string>）。 */
export const outlineBulkSelections = reactive({})
export const outlineFilterDrafts = reactive({})
let ownerProjectId = null

/**
 * 把模块级选择会话绑定到当前项目。相同项目的 island 重挂载保留选择；
 * 跨项目时确定性清空，避免旧资产 ID 进入新项目的批量或 AI 请求。
 */
export function scopeBulkSelectionsToProject(projectId) {
  const nextProjectId = projectId || null
  if (ownerProjectId === nextProjectId) return false
  clearAllBulkSelections()
  for (const key of Object.keys(outlineFilterDrafts)) delete outlineFilterDrafts[key]
  ownerProjectId = nextProjectId
  return true
}

/** 获取某 scope 的 selection Set，惰性初始化。 */
export function getBulkSelection(scope) {
  if (!outlineBulkSelections[scope]) {
    outlineBulkSelections[scope] = new Set()
  }
  return outlineBulkSelections[scope]
}

export function clearBulkSelection(scope) {
  getBulkSelection(scope).clear()
}

export function clearAllBulkSelections() {
  for (const key of Object.keys(outlineBulkSelections)) {
    delete outlineBulkSelections[key]
  }
}

export function clearOutlineFilterDrafts() {
  for (const key of Object.keys(outlineFilterDrafts)) delete outlineFilterDrafts[key]
}

export function toggleBulkSelection(scope, id, checked) {
  if (!id) return
  const selection = getBulkSelection(scope)
  if (checked) selection.add(String(id))
  else selection.delete(String(id))
}

export function toggleAllBulkSelection(scope, ids, checked) {
  const selection = getBulkSelection(scope)
  for (const id of ids.filter(Boolean).map(String)) {
    if (checked) selection.add(id)
    else selection.delete(id)
  }
}

/** 移除已选中但当前不可见的 id（对应 shared reconcileBulkSelection）。 */
export function reconcileBulkSelection(scope, visibleIds) {
  const visible = new Set(visibleIds.filter(Boolean).map(String))
  const selection = getBulkSelection(scope)
  for (const id of Array.from(selection)) {
    if (!visible.has(id)) selection.delete(id)
  }
}

/** 全选框状态：checked / indeterminate / disabled。 */
export function selectAllState(scope, ids) {
  const cleanIds = ids.filter(Boolean).map(String)
  const selection = getBulkSelection(scope)
  const selectedVisibleCount = cleanIds.filter((id) => selection.has(id)).length
  const checked = cleanIds.length > 0 && selectedVisibleCount === cleanIds.length
  const indeterminate = selectedVisibleCount > 0 && !checked
  return { checked, indeterminate, disabled: cleanIds.length === 0 }
}

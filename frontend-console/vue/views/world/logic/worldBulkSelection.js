/**
 * worldBulkSelection — world 视图批量选择的 Vue 化实现。
 *
 * 语义逐行对应 shared/bulkSelection.js 的状态函数，但状态落在
 * worldSession.bulkSelections（reactive），checkbox/工具条由模板绑定驱动，
 * 不再需要 syncBulkSelectionUi 的命令式 DOM 同步（与 Vue 渲染冲突）。
 * DOM 契约（data-action/data-scope/data-id、.bulk-toolbar 结构）由组件模板保留。
 * shared/bulkSelection.js 不动（outline/writing 仍消费）；纯函数
 * runBulkAction / bulkResultMessage / selectedItemsFrom 直接从 shared 复用。
 */
import { worldSession } from "../worldSession.js"

export { runBulkAction, bulkResultMessage, selectedItemsFrom } from "../../../../shared/bulkSelection.js"

export function getBulkSelection(scope) {
  if (!worldSession.bulkSelections[scope]) {
    worldSession.bulkSelections[scope] = new Set()
  }
  return worldSession.bulkSelections[scope]
}

export function clearBulkSelection(scope) {
  getBulkSelection(scope).clear()
}

export function clearAllBulkSelections() {
  worldSession.bulkSelections = {}
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

/** 全选框状态：对应 shared renderSelectionHeader 的 checked/indeterminate/disabled。 */
export function selectAllState(scope, ids) {
  const cleanIds = ids.filter(Boolean).map(String)
  const selection = getBulkSelection(scope)
  const selectedVisibleCount = cleanIds.filter((id) => selection.has(id)).length
  const checked = cleanIds.length > 0 && selectedVisibleCount === cleanIds.length
  const indeterminate = selectedVisibleCount > 0 && !checked
  return { checked, indeterminate, disabled: cleanIds.length === 0 }
}

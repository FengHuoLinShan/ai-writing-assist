/**
 * Shared helpers for list-page selection and bulk actions.
 *
 * The helpers keep state on the view instance so each view can decide when to
 * reset selection without introducing a global store.
 */

export function getBulkSelection(view, scope) {
  if (!view._bulkSelections) view._bulkSelections = {}
  if (!view._bulkSelections[scope]) view._bulkSelections[scope] = new Set()
  return view._bulkSelections[scope]
}

export function clearBulkSelection(view, scope) {
  getBulkSelection(view, scope).clear()
}

export function clearAllBulkSelections(view) {
  view._bulkSelections = {}
}

export function toggleBulkSelection(view, scope, id, checked) {
  if (!id) return
  const selection = getBulkSelection(view, scope)
  if (checked) selection.add(String(id))
  else selection.delete(String(id))
}

export function toggleAllBulkSelection(view, scope, ids, checked) {
  const selection = getBulkSelection(view, scope)
  for (const id of ids.filter(Boolean).map(String)) {
    if (checked) selection.add(id)
    else selection.delete(id)
  }
}

export function reconcileBulkSelection(view, scope, visibleIds) {
  const visible = new Set(visibleIds.filter(Boolean).map(String))
  const selection = getBulkSelection(view, scope)
  for (const id of Array.from(selection)) {
    if (!visible.has(id)) selection.delete(id)
  }
}

export function selectedItemsFrom(items, selectedIds, idGetter = (item) => item.id) {
  const selected = new Set(Array.from(selectedIds || []).map(String))
  return items.filter((item) => selected.has(String(idGetter(item))))
}

export async function runBulkAction(items, handler, options = {}) {
  const concurrency = Math.max(1, Number(options.concurrency || 4))
  const result = { total: items.length, success: [], failed: [] }
  let nextIndex = 0

  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      const item = items[index]
      try {
        await handler(item, index)
        result.success.push(item)
      } catch (error) {
        result.failed.push({ item, error })
      }
    }
  }

  await Promise.all(Array.from(
    { length: Math.min(concurrency, Math.max(1, items.length)) },
    () => worker(),
  ))
  return result
}

export function bulkResultMessage(result, actionLabel, itemLabel = (item) => item?.name || item?.title || item?.id || item) {
  const parts = [`${actionLabel}完成：成功 ${result.success.length} / ${result.total}`]
  if (result.failed.length) {
    const names = result.failed.slice(0, 5).map(({ item }) => itemLabel(item)).filter(Boolean).join("、")
    parts.push(`失败 ${result.failed.length}${names ? `：${names}` : ""}`)
  }
  return parts.join("；")
}

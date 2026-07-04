/**
 * Shared helpers for list-page selection and bulk actions.
 *
 * The helpers keep state on the view instance so each view can decide when to
 * reset selection without introducing a global store.
 */

function escHtml(value) {
  if (value === null || value === undefined) return ""
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

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

export function renderSelectionHeader(view, scope, ids, label = "选择当前页") {
  const cleanIds = ids.filter(Boolean).map(String)
  const selection = getBulkSelection(view, scope)
  const selectedVisibleCount = cleanIds.filter((id) => selection.has(id)).length
  const checked = cleanIds.length > 0 && selectedVisibleCount === cleanIds.length
  const indeterminate = selectedVisibleCount > 0 && !checked ? "data-indeterminate=\"true\"" : ""
  return `
    <label class="selection-checkbox" title="${escHtml(label)}">
      <input type="checkbox"
        data-action="bulk-toggle-all"
        data-scope="${escHtml(scope)}"
        ${checked ? "checked" : ""}
        ${indeterminate}
        ${cleanIds.length === 0 ? "disabled" : ""}
      />
      <span class="sr-only">${escHtml(label)}</span>
    </label>
  `
}

export function renderSelectionCell(view, scope, id, label = "选择") {
  const checked = getBulkSelection(view, scope).has(String(id))
  return `
    <label class="selection-checkbox" title="${escHtml(label)}">
      <input type="checkbox"
        data-action="bulk-toggle-one"
        data-scope="${escHtml(scope)}"
        data-id="${escHtml(id)}"
        ${checked ? "checked" : ""}
      />
      <span class="sr-only">${escHtml(label)}</span>
    </label>
  `
}

export function renderBulkToolbar(view, scope, actions, options = {}) {
  const count = getBulkSelection(view, scope).size
  const noun = options.noun || "项"
  const title = options.title || `已选择 ${count} ${noun}`
  const actionHtml = actions.map((action) => `
    <button
      class="btn btn-sm ${escHtml(action.className || "")}"
      data-action="bulk-run"
      data-scope="${escHtml(scope)}"
      data-bulk-action="${escHtml(action.action)}"
      data-bulk-static-disabled="${action.disabled ? "true" : "false"}"
      ${count === 0 || action.disabled ? "disabled" : ""}
    >${escHtml(action.label)}</button>
  `).join("")
  return `
    <div class="bulk-toolbar" data-scope="${escHtml(scope)}">
      <div class="bulk-toolbar__status">
        <strong>${escHtml(count)}</strong>
        <span>${escHtml(noun)}已选</span>
        ${options.hint ? `<span class="bulk-toolbar__hint">${escHtml(options.hint)}</span>` : ""}
      </div>
      <div class="bulk-toolbar__actions">
        ${actionHtml}
        <button class="btn btn-sm" data-action="bulk-clear" data-scope="${escHtml(scope)}" ${count === 0 ? "disabled" : ""}>清空</button>
      </div>
      <span class="sr-only">${escHtml(title)}</span>
    </div>
  `
}

export function syncBulkSelectionUi(view, scope = null) {
  if (typeof document === "undefined") return
  const scopes = scope ? [scope] : Object.keys(view._bulkSelections || {})
  for (const itemScope of scopes) {
    const selection = getBulkSelection(view, itemScope)
    const visibleInputs = Array.from(document.querySelectorAll('input[data-action="bulk-toggle-one"]'))
      .filter((input) => input.getAttribute("data-scope") === itemScope)
    const visibleIds = visibleInputs
      .map((input) => input.getAttribute("data-id"))
      .filter(Boolean)

    for (const input of visibleInputs) {
      input.checked = selection.has(String(input.getAttribute("data-id")))
    }

    const selectedVisibleCount = visibleIds.filter((id) => selection.has(String(id))).length
    const allVisibleSelected = visibleIds.length > 0 && selectedVisibleCount === visibleIds.length
    const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected
    document.querySelectorAll('input[data-action="bulk-toggle-all"]').forEach((input) => {
      if (input.getAttribute("data-scope") !== itemScope) return
      input.checked = allVisibleSelected
      input.indeterminate = someVisibleSelected
      if (someVisibleSelected) input.setAttribute("data-indeterminate", "true")
      else input.removeAttribute("data-indeterminate")
      input.disabled = visibleIds.length === 0
    })

    document.querySelectorAll(".bulk-toolbar").forEach((toolbar) => {
      if (toolbar.getAttribute("data-scope") !== itemScope) return
      const count = selection.size
      const countNode = toolbar.querySelector(".bulk-toolbar__status strong")
      if (countNode) countNode.textContent = String(count)
      toolbar.querySelectorAll('[data-action="bulk-run"]').forEach((button) => {
        button.disabled = count === 0 || button.getAttribute("data-bulk-static-disabled") === "true"
      })
      toolbar.querySelectorAll('[data-action="bulk-clear"]').forEach((button) => {
        button.disabled = count === 0
      })
    })
  }
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

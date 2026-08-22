/**
 * Author-facing reference picker.
 *
 * IDs remain the stable wire value, while labels and descriptions are display-only.
 * Providers must keep project isolation and return normalized reference items.
 */

const DEFAULT_DEBOUNCE_MS = 200
let pickerSequence = 0

function escapeHtml(value) {
  if (value == null) return ""
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

function refKey(kind, id) {
  return `${String(kind || "reference")}::${String(id ?? "")}`
}

export function normalizeReferenceItem(item, fallbackKind = "reference") {
  const id = String(item?.id ?? item?.entity_id ?? item?.target_id ?? "")
  if (!id) return null
  const displayLabel = item?.label || item?.name || item?.title
  return {
    kind: String(item?.kind || item?.type || fallbackKind),
    id,
    label: String(displayLabel || "不可用引用"),
    description: String(item?.description || item?.summary || ""),
    status: String(item?.status || ""),
    unavailable: Boolean(item?.unavailable || !displayLabel),
  }
}

export function createReferencePicker({
  root,
  projectId,
  sources,
  mode = "single",
  maxItems = mode === "single" ? 1 : Infinity,
  initialItems = [],
  placeholder = "按名称搜索",
  ariaLabel = placeholder,
  emptyText = "没有匹配的对象",
  debounceMs = DEFAULT_DEBOUNCE_MS,
  onChange = () => {},
  onOpen = null,
} = {}) {
  if (!root || typeof root.querySelector !== "function") {
    throw new Error("referencePicker requires a root element")
  }
  const availableSources = (Array.isArray(sources) ? sources : [])
    .filter((source) => source?.kind && typeof source.search === "function")
    .map((source) => ({ ...source, kind: String(source.kind) }))
  if (!availableSources.length) {
    throw new Error("referencePicker requires at least one searchable source")
  }

  const pickerId = `reference-picker-${++pickerSequence}`
  const selectionLimit = mode === "single"
    ? 1
    : (Number.isFinite(Number(maxItems)) ? Math.max(0, Math.floor(Number(maxItems))) : Infinity)
  let currentProjectId = String(projectId || "")
  let activeKind = availableSources[0].kind
  let query = ""
  let results = []
  let loading = false
  let error = ""
  let highlightedIndex = -1
  let timer = null
  let requestGeneration = 0
  let abortController = null
  let destroyed = false
  const selected = new Map()

  for (const raw of Array.isArray(initialItems) ? initialItems : []) {
    const item = normalizeReferenceItem(raw, raw?.kind || activeKind)
    if (item) selected.set(refKey(item.kind, item.id), item)
  }

  root.classList.add("reference-picker")
  root.innerHTML = `
    <div class="reference-picker__selected" data-reference-selected></div>
    <div class="reference-picker__search-row">
      ${availableSources.length > 1 ? `
        <label class="sr-only" for="${pickerId}-kind">引用类型</label>
        <select class="form-select reference-picker__kind" data-reference-kind id="${pickerId}-kind">
          ${availableSources.map((source) => `<option value="${escapeHtml(source.kind)}">${escapeHtml(source.label || source.kind)}</option>`).join("")}
        </select>
      ` : ""}
      <div class="reference-picker__combobox">
        <input class="form-input" data-reference-query type="search" autocomplete="off"
          role="combobox" aria-autocomplete="list" aria-expanded="false"
          aria-controls="${pickerId}-results"
          aria-label="${escapeHtml(ariaLabel)}"
          placeholder="${escapeHtml(placeholder)}" />
        <div class="reference-picker__results" data-reference-results
          id="${pickerId}-results" role="listbox" hidden></div>
      </div>
    </div>
    <div class="reference-picker__status" data-reference-status aria-live="polite"></div>
  `

  const queryInput = root.querySelector("[data-reference-query]")
  const kindSelect = root.querySelector("[data-reference-kind]")
  const resultsRoot = root.querySelector("[data-reference-results]")
  const selectedRoot = root.querySelector("[data-reference-selected]")
  const statusRoot = root.querySelector("[data-reference-status]")

  function currentSource() {
    return availableSources.find((source) => source.kind === activeKind) || availableSources[0]
  }

  function selectedItems() {
    return Array.from(selected.values())
  }

  function notify() {
    onChange(selectedItems(), selectedItems().map(({ kind, id }) => ({ kind, id })))
  }

  function renderSelected() {
    const items = selectedItems()
    selectedRoot.innerHTML = items.length ? items.map((item) => `
      <span class="reference-picker__chip ${item.unavailable ? "is-unavailable" : ""}" data-reference-chip="${escapeHtml(refKey(item.kind, item.id))}">
        <span>
          <strong>${escapeHtml(item.label)}</strong>
          ${item.description ? `<small>${escapeHtml(item.description)}</small>` : ""}
          ${item.unavailable ? "<small>不可用引用：原引用已归档或无法解析；移除前不会自动丢失</small>" : ""}
        </span>
        ${typeof onOpen === "function" && !item.unavailable ? `<button type="button" class="reference-picker__open" data-reference-open="${escapeHtml(refKey(item.kind, item.id))}" aria-label="打开 ${escapeHtml(item.label)}">打开</button>` : ""}
        <button type="button" class="reference-picker__remove" data-reference-remove="${escapeHtml(refKey(item.kind, item.id))}" aria-label="移除 ${escapeHtml(item.label)}">×</button>
      </span>
    `).join("") : ""
  }

  function syncHighlightedOption({ scroll = false } = {}) {
    const options = resultsRoot.querySelectorAll("[data-reference-result]")
    options.forEach((option, index) => {
      option.classList.toggle("is-active", index === highlightedIndex)
    })
    const activeOption = highlightedIndex >= 0 ? options[highlightedIndex] : null
    if (activeOption) {
      queryInput.setAttribute("aria-activedescendant", activeOption.id)
      if (scroll) activeOption.scrollIntoView?.({ block: "nearest" })
    } else {
      queryInput.removeAttribute("aria-activedescendant")
    }
  }

  function renderResults() {
    if (destroyed) return
    if (loading) {
      statusRoot.textContent = "正在搜索…"
    } else if (error) {
      statusRoot.textContent = error
    } else {
      statusRoot.textContent = ""
    }
    const visible = results.filter((item) => !selected.has(refKey(item.kind, item.id)))
    if (!visible.length) highlightedIndex = -1
    else if (highlightedIndex >= visible.length) highlightedIndex = visible.length - 1
    if (highlightedIndex >= 0 && visible[highlightedIndex]?.unavailable) {
      highlightedIndex = visible.findIndex((item) => !item.unavailable)
    }
    resultsRoot.innerHTML = visible.length ? visible.map((item, index) => `
      <button type="button" class="reference-picker__option"
        id="${pickerId}-option-${index}" data-reference-result="${escapeHtml(refKey(item.kind, item.id))}" role="option"
        aria-selected="false" ${item.unavailable ? "aria-disabled=\"true\" disabled" : ""}>
        <strong>${escapeHtml(item.label)}</strong>
        <span>${escapeHtml([item.description, item.status, item.unavailable ? "不可用" : ""].filter(Boolean).join(" · "))}</span>
      </button>
    `).join("") : `<div class="reference-picker__empty">${escapeHtml(emptyText)}</div>`
    resultsRoot.hidden = false
    queryInput.setAttribute("aria-expanded", "true")
    queryInput.toggleAttribute("aria-busy", loading)
    syncHighlightedOption()
  }

  function closeResults() {
    highlightedIndex = -1
    resultsRoot.hidden = true
    queryInput.setAttribute("aria-expanded", "false")
    queryInput.removeAttribute("aria-activedescendant")
    queryInput.removeAttribute("aria-busy")
  }

  function cancelPending() {
    if (timer) clearTimeout(timer)
    timer = null
    requestGeneration += 1
    abortController?.abort()
    abortController = null
    loading = false
  }

  async function runSearch() {
    if (destroyed || !currentProjectId) return
    const source = currentSource()
    const searchKind = source.kind
    const searchQuery = query
    const searchProjectId = currentProjectId
    const generation = ++requestGeneration
    abortController?.abort()
    const controller = new AbortController()
    abortController = controller
    loading = true
    error = ""
    renderResults()
    try {
      const raw = await source.search(searchQuery, {
        projectId: searchProjectId,
        signal: controller.signal,
        limit: 20,
      })
      if (destroyed || generation !== requestGeneration) return
      const items = Array.isArray(raw) ? raw : (raw?.items || [])
      results = items
        .map((item) => normalizeReferenceItem(item, searchKind))
        .filter(Boolean)
      highlightedIndex = results.findIndex((item) => !item.unavailable)
    } catch (err) {
      if (destroyed || generation !== requestGeneration || err?.name === "AbortError") return
      error = err?.message || "搜索失败，请重试"
      results = []
      highlightedIndex = -1
    } finally {
      if (!destroyed && generation === requestGeneration) {
        loading = false
        if (abortController === controller) abortController = null
        renderResults()
      }
    }
  }

  function scheduleSearch() {
    if (destroyed) return
    cancelPending()
    timer = setTimeout(runSearch, Math.max(0, Number(debounceMs) || 0))
  }

  function add(item) {
    if (!item || selected.has(refKey(item.kind, item.id))) return false
    if (item.unavailable) {
      error = "该引用当前不可用"
      renderResults()
      return false
    }
    if (mode === "single") {
      selected.clear()
    } else if (selected.size >= selectionLimit) {
      error = `最多选择 ${selectionLimit} 项`
      statusRoot.textContent = error
      return false
    }
    selected.set(refKey(item.kind, item.id), item)
    error = ""
    renderSelected()
    notify()
    query = ""
    queryInput.value = ""
    closeResults()
    return true
  }

  function addHighlighted() {
    const visible = results.filter((item) => !selected.has(refKey(item.kind, item.id)))
    const item = visible[highlightedIndex]
    if (item) add(item)
  }

  function handleInput() {
    query = queryInput.value.trim()
    results = []
    highlightedIndex = -1
    error = ""
    closeResults()
    statusRoot.textContent = ""
    scheduleSearch()
  }

  function handleFocus() {
    scheduleSearch()
  }

  function handleKeydown(event) {
    const visible = results.filter((item) => !selected.has(refKey(item.kind, item.id)))
    const enabledIndexes = visible
      .map((item, index) => item.unavailable ? -1 : index)
      .filter((index) => index >= 0)
    const currentEnabledPosition = enabledIndexes.indexOf(highlightedIndex)
    if (event.key === "ArrowDown" && enabledIndexes.length) {
      event.preventDefault()
      highlightedIndex = enabledIndexes[(currentEnabledPosition + 1 + enabledIndexes.length) % enabledIndexes.length]
      syncHighlightedOption({ scroll: true })
    } else if (event.key === "ArrowUp" && enabledIndexes.length) {
      event.preventDefault()
      const previousPosition = currentEnabledPosition < 0 ? 0 : currentEnabledPosition
      highlightedIndex = enabledIndexes[(previousPosition - 1 + enabledIndexes.length) % enabledIndexes.length]
      syncHighlightedOption({ scroll: true })
    } else if (event.key === "Enter" && !resultsRoot.hidden) {
      event.preventDefault()
      addHighlighted()
    } else if (event.key === "Escape") {
      cancelPending()
      statusRoot.textContent = ""
      closeResults()
    }
  }

  function handleKindChange() {
    activeKind = kindSelect.value
    results = []
    highlightedIndex = -1
    error = ""
    closeResults()
    statusRoot.textContent = ""
    scheduleSearch()
  }

  queryInput.addEventListener("input", handleInput)
  queryInput.addEventListener("focus", handleFocus)
  queryInput.addEventListener("keydown", handleKeydown)
  kindSelect?.addEventListener("change", handleKindChange)

  function handleRootClick(event) {
    const open = event.target.closest?.("[data-reference-open]")
    if (open) {
      const item = selected.get(open.getAttribute("data-reference-open"))
      if (item && typeof onOpen === "function") onOpen(item)
      return
    }
    const remove = event.target.closest?.("[data-reference-remove]")
    if (remove) {
      selected.delete(remove.getAttribute("data-reference-remove"))
      error = ""
      statusRoot.textContent = ""
      renderSelected()
      notify()
      queryInput.focus({ preventScroll: true })
      return
    }
    const option = event.target.closest?.("[data-reference-result]")
    if (!option) return
    const key = option.getAttribute("data-reference-result")
    const item = results.find((candidate) => refKey(candidate.kind, candidate.id) === key)
    if (add(item)) queryInput.focus({ preventScroll: true })
  }

  root.addEventListener("click", handleRootClick)

  renderSelected()

  return {
    getItems: selectedItems,
    getRefs: () => selectedItems().map(({ kind, id }) => ({ kind, id })),
    setProjectId(nextProjectId) {
      const next = String(nextProjectId || "")
      if (next === currentProjectId) return
      currentProjectId = next
      cancelPending()
      results = []
      highlightedIndex = -1
      error = ""
      query = ""
      queryInput.value = ""
      selected.clear()
      renderSelected()
      closeResults()
      statusRoot.textContent = ""
      notify()
    },
    setItems(items, { notifyChange = false } = {}) {
      selected.clear()
      for (const raw of Array.isArray(items) ? items : []) {
        const item = normalizeReferenceItem(raw, raw?.kind || activeKind)
        if (item) selected.set(refKey(item.kind, item.id), item)
      }
      renderSelected()
      if (notifyChange) notify()
    },
    async resolve(refs) {
      cancelPending()
      error = ""
      closeResults()
      statusRoot.textContent = ""
      const grouped = new Map()
      for (const ref of Array.isArray(refs) ? refs : []) {
        if (!ref?.id) continue
        const kind = String(ref.kind || activeKind)
        if (!grouped.has(kind)) grouped.set(kind, [])
        grouped.get(kind).push(String(ref.id))
      }
      const generation = ++requestGeneration
      const resolveProjectId = currentProjectId
      const controller = new AbortController()
      abortController = controller
      const resolved = []
      for (const [kind, ids] of grouped.entries()) {
        if (destroyed || generation !== requestGeneration || controller.signal.aborted) return []
        const source = availableSources.find((candidate) => candidate.kind === kind)
        let items = []
        if (source?.resolve) {
          try {
            const raw = await source.resolve(ids, { projectId: resolveProjectId, signal: controller.signal })
            items = Array.isArray(raw) ? raw : (raw?.items || [])
          } catch (err) {
            if (err?.name === "AbortError" || destroyed || generation !== requestGeneration) return []
            items = []
          }
        }
        if (destroyed || generation !== requestGeneration || resolveProjectId !== currentProjectId) return []
        const byId = new Map(items.map((item) => [String(item.id ?? item.entity_id ?? item.target_id ?? ""), item]))
        for (const id of ids) {
          resolved.push(normalizeReferenceItem(byId.get(id) || {
            kind,
            id,
            label: "不可用引用",
            unavailable: true,
          }, kind))
        }
      }
      if (!destroyed && generation === requestGeneration) {
        selected.clear()
        for (const item of resolved) {
          if (item) selected.set(refKey(item.kind, item.id), item)
        }
        renderSelected()
      }
      if (abortController === controller) abortController = null
      return resolved
    },
    destroy() {
      if (destroyed) return
      destroyed = true
      cancelPending()
      root.removeEventListener("click", handleRootClick)
      queryInput.removeEventListener("input", handleInput)
      queryInput.removeEventListener("focus", handleFocus)
      queryInput.removeEventListener("keydown", handleKeydown)
      kindSelect?.removeEventListener("change", handleKindChange)
      root.innerHTML = ""
      root.classList.remove("reference-picker")
    },
  }
}

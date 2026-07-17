/**
 * 模态框系统
 *
 * 支持标题 + 内容 + 自定义按钮。
 * 自动附加取消按钮（如未提供）。
 */

let _previouslyFocusedElement = null
let _unsavedFormBaseline = null
let _closeAttemptCount = 0
let _modalGeneration = 0
const _activeActionGenerations = new Map()
let _userCloseGeneration = null

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])",
].join(",")

function _isModalOpen() {
  const overlay = document.getElementById("modal-overlay")
  return Boolean(overlay && !overlay.classList.contains("hidden"))
}

function _focusableElements() {
  const contentEl = document.getElementById("modal-content")
  if (!contentEl) return []
  return Array.from(contentEl.querySelectorAll(FOCUSABLE_SELECTOR)).filter((element) => {
    if (element.matches(":disabled") || element.closest("[hidden], [aria-hidden='true'], [inert]")) {
      return false
    }

    // getComputedStyle(element) does not expose an ancestor hidden with CSS, so
    // walk up to the dialog boundary before admitting the element to the trap.
    for (let current = element; current && current !== contentEl; current = current.parentElement) {
      const style = window.getComputedStyle(current)
      if (style.display === "none" || style.visibility === "hidden") return false
    }
    return true
  })
}

function _focusInitialElement() {
  const contentEl = document.getElementById("modal-content")
  if (!contentEl) return

  const bodyEl = document.getElementById("modal-body")
  const footerEl = document.getElementById("modal-footer")
  const focusable = _focusableElements()
  const target = focusable.find((element) => element.hasAttribute("autofocus"))
    || focusable.find((element) => bodyEl?.contains(element))
    || focusable.find((element) => footerEl?.contains(element))
    || focusable.find((element) => element.id === "modal-close")
    || contentEl

  if (target === contentEl && !contentEl.hasAttribute("tabindex")) {
    contentEl.setAttribute("tabindex", "-1")
  }
  target.focus()
}

function _editableControls() {
  const bodyEl = document.getElementById("modal-body")
  if (!bodyEl) return []
  return Array.from(bodyEl.querySelectorAll([
    "input:not([type='button']):not([type='submit']):not([type='reset']):not([type='hidden'])",
    "textarea",
    "select",
    "[contenteditable]:not([contenteditable='false'])",
  ].join(",")))
}

function _isUserEditable(element) {
  if (element.matches(":disabled")) return false
  if (element.matches("input[readonly], textarea[readonly]")) return false
  if (element.closest("[hidden], [aria-hidden='true'], [inert]")) return false

  const bodyEl = document.getElementById("modal-body")
  for (let current = element; current && current !== bodyEl; current = current.parentElement) {
    const style = window.getComputedStyle(current)
    if (style.display === "none" || style.visibility === "hidden") return false
  }
  return true
}

function _editableControlValue(element) {
  if (element.matches("input[type='checkbox'], input[type='radio']")) {
    return [element.value, element.checked]
  }
  if (element.tagName === "SELECT" && element.multiple) {
    return Array.from(element.options)
      .map((option, index) => option.selected ? [index, option.value] : null)
      .filter(Boolean)
  }
  if (element.hasAttribute("contenteditable")) {
    return element.innerHTML
  }
  return element.value
}

function _formSnapshot() {
  const controls = _editableControls()
  return {
    entries: controls.map((element) => ({
      element,
      userEditable: _isUserEditable(element),
      value: JSON.stringify(_editableControlValue(element)),
    })),
  }
}

function _hasUnsavedFormChanges() {
  if (_unsavedFormBaseline === null) return false

  const currentControls = _editableControls()
  const currentSet = new Set(currentControls)
  const baselineByElement = new Map(
    _unsavedFormBaseline.entries.map((entry) => [entry.element, entry]),
  )

  for (const baseline of _unsavedFormBaseline.entries) {
    if (!currentSet.has(baseline.element)) {
      if (baseline.userEditable) return true
      continue
    }
    if (
      (baseline.userEditable || _isUserEditable(baseline.element))
      && JSON.stringify(_editableControlValue(baseline.element)) !== baseline.value
    ) {
      return true
    }
  }

  return currentControls.some((element) => (
    !baselineByElement.has(element) && _isUserEditable(element)
  ))
}

function _confirmDiscardUnsavedChanges() {
  if (typeof window.confirm !== "function") return false
  return window.confirm("有未保存的更改，确定放弃并关闭吗？")
}

/**
 * 在调用方完成同步挂载的动态表单控件后，重新记录未保存基线。
 *
 * showModal 只能记录它直接渲染的控件；引用选择器等组件会在弹窗显示后
 * 再挂载输入框。如果不刷新基线，未修改的动态控件也会被误判为用户编辑。
 */
function refreshModalFormBaseline() {
  if (!_isModalOpen()) return false
  _unsavedFormBaseline = _formSnapshot()
  return true
}

function _isDomEvent(value) {
  return Boolean(
    value
    && typeof value.preventDefault === "function"
    && typeof value.stopImmediatePropagation === "function"
    && typeof value.type === "string",
  )
}

function _beginAction(generation) {
  _activeActionGenerations.set(generation, (_activeActionGenerations.get(generation) || 0) + 1)
}

function _endAction(generation) {
  const remaining = (_activeActionGenerations.get(generation) || 1) - 1
  if (remaining > 0) {
    _activeActionGenerations.set(generation, remaining)
  } else {
    _activeActionGenerations.delete(generation)
  }
}

function _handleModalKeydown(event) {
  if (!_isModalOpen()) return

  if (event.key === "Escape") {
    event.preventDefault()
    event.stopImmediatePropagation()
    closeModal(event)
    return
  }

  if (event.key !== "Tab") return

  const focusable = _focusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    document.getElementById("modal-content")?.focus()
    return
  }

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (event.shiftKey && (active === first || !focusable.includes(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !focusable.includes(active))) {
    event.preventDefault()
    first.focus()
  }
}

const MODAL_KEYDOWN_BINDING = "__aiWritingAssistModalKeydownHandler"
const previousKeydownHandler = document[MODAL_KEYDOWN_BINDING]
if (typeof previousKeydownHandler === "function") {
  document.removeEventListener("keydown", previousKeydownHandler, true)
}
document.addEventListener("keydown", _handleModalKeydown, true)
document[MODAL_KEYDOWN_BINDING] = _handleModalKeydown

/**
 * 显示模态框
 * @param {string} title - 标题
 * @param {string|HTMLElement|{html:string}} body - 内容：字符串使用 textContent；HTMLElement 作为可信节点附加；{html:string} 使用 innerHTML
 * @param {Array<{text:string, class?:string, handler:function}>} buttons - 按钮
 * @param {{size?: "large"|"full", protectUnsaved?: boolean}} options - 视觉与关闭保护选项
 */
function showModal(title, body, buttons = [], options = {}) {
  const overlay = document.getElementById("modal-overlay")
  const contentEl = document.getElementById("modal-content")
  const titleEl = document.getElementById("modal-title")
  const bodyEl = document.getElementById("modal-body")
  const footerEl = document.getElementById("modal-footer")

  if (!overlay || !titleEl || !bodyEl || !footerEl) return

  const generation = ++_modalGeneration

  if (overlay.classList.contains("hidden")) {
    _previouslyFocusedElement = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
  }

  if (contentEl) {
    contentEl.classList.remove("modal-content--large", "modal-content--full")
    delete contentEl.dataset.modalSize
    if (options.size === "large" || options.size === "full") {
      contentEl.classList.add(`modal-content--${options.size}`)
      contentEl.dataset.modalSize = options.size
    }
  }

  titleEl.textContent = title

  bodyEl.innerHTML = ""
  if (typeof body === "string") {
    bodyEl.textContent = body
  } else if (body instanceof HTMLElement) {
    bodyEl.appendChild(body)
  } else if (body && typeof body === "object" && typeof body.html === "string") {
    bodyEl.innerHTML = body.html
  } else if (body !== undefined && body !== null) {
    bodyEl.textContent = String(body)
  }

  footerEl.innerHTML = ""
  for (const btn of buttons) {
    const el = document.createElement("button")
    const isPrimary = !btn.class || btn.class.includes("primary") || btn.text === "保存" || btn.text === "创建" || btn.text === "确认"
    el.className = "btn " + (btn.class || (isPrimary ? "btn-primary" : "btn-ghost"))
    el.textContent = btn.text
    el.addEventListener("click", async (event) => {
      if (_isCloseButton(btn)) {
        const closeAttemptsBeforeHandler = _closeAttemptCount
        const previousUserCloseGeneration = _userCloseGeneration
        _userCloseGeneration = generation
        let pendingResult
        try {
          pendingResult = btn.handler?.(event)
        } catch (err) {
          _toastHandlerError(err)
          return
        } finally {
          _userCloseGeneration = previousUserCloseGeneration
        }
        try {
          await Promise.resolve(pendingResult)
        } catch (err) {
          _toastHandlerError(err)
          return
        }
        if (
          _modalGeneration === generation
          && _isModalOpen()
          && _closeAttemptCount === closeAttemptsBeforeHandler
        ) {
          closeModal(event)
        }
        return
      }

      _beginAction(generation)
      try {
        const result = await Promise.resolve(btn.handler?.())
        if (result !== false && _modalGeneration === generation) {
          closeModal({ force: true })
        }
      } catch (err) {
        _toastHandlerError(err)
      } finally {
        _endAction(generation)
      }
    })
    footerEl.appendChild(el)
  }

  // 如果没有取消/关闭按钮，自动追加一个
  if (!buttons.some((b) => b.text === "取消" || b.text === "关闭")) {
    const cancel = document.createElement("button")
    cancel.className = "btn btn-ghost"
    cancel.textContent = "取消"
    cancel.addEventListener("click", closeModal)
    footerEl.appendChild(cancel)
  }

  _unsavedFormBaseline = options.protectUnsaved === false ? null : _formSnapshot()
  overlay.classList.remove("hidden")
  _focusInitialElement()
}

function _isCloseButton(btn) {
  return btn?.text === "取消" || btn?.text === "关闭"
}

function _toastHandlerError(err) {
  const message = err?.message || "未知错误"
  if (typeof toast === "function") toast(`操作失败：${message}`, "error")
}

/**
 * 关闭模态框。
 * @param {{force?: boolean}|Event} options - 内部成功 action 可强制关闭；DOM 事件参数不会绕过保护
 * @returns {boolean} 是否已关闭
 */
function closeModal(options = {}) {
  const overlay = document.getElementById("modal-overlay")
  if (!overlay || overlay.classList.contains("hidden")) return true

  const isDomEvent = _isDomEvent(options)
  const isExplicitlyForced = options?.force === true
  const currentActionIsActive = _activeActionGenerations.has(_modalGeneration)
  if (
    !isDomEvent
    && !isExplicitlyForced
    && _activeActionGenerations.size > 0
    && !currentActionIsActive
  ) {
    return false
  }

  _closeAttemptCount += 1
  const force = isExplicitlyForced || (
    !isDomEvent
    && _userCloseGeneration !== _modalGeneration
    && currentActionIsActive
  )
  if (!force && _hasUnsavedFormChanges() && !_confirmDiscardUnsavedChanges()) {
    if (isDomEvent) {
      options.preventDefault()
      options.stopImmediatePropagation()
    }
    return false
  }

  overlay.classList.add("hidden")
  _unsavedFormBaseline = null
  const focusTarget = _previouslyFocusedElement
  _previouslyFocusedElement = null
  if (focusTarget?.isConnected && typeof focusTarget.focus === "function") {
    focusTarget.focus()
  }
  return true
}

/**
 * 显示 HTML 模态框（调用方负责转义动态内容）
 * @param {string} title - 标题
 * @param {string} htmlString - HTML 字符串
 * @param {Array<{text:string, class?:string, handler:function}>} buttons - 按钮
 * @param {{size?: "large"|"full", protectUnsaved?: boolean}} options - 视觉与关闭保护选项
 */
function showModalHtml(title, htmlString, buttons = [], options = {}) {
  showModal(title, { html: htmlString }, buttons, options)
}

/**
 * 显示确认对话框
 * @param {string} message - 确认消息
 * @param {function} onConfirm - 确认回调
 * @param {string} confirmText - 确认按钮文字
 */
function confirmAction(message, onConfirm, confirmText = "确认") {
  const p = document.createElement("p")
  p.textContent = message
  showModal("确认操作", p, [
    { text: confirmText, class: "btn-danger", handler: onConfirm },
    { text: "取消", class: "btn-ghost", handler: closeModal },
  ])
}

// 导出到全局，保持与 script 标签加载行为一致，也便于测试 import
window.showModal = showModal
window.closeModal = closeModal
window.showModalHtml = showModalHtml
window.confirmAction = confirmAction
window.refreshModalFormBaseline = refreshModalFormBaseline

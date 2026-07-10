/**
 * 模态框系统
 *
 * 支持标题 + 内容 + 自定义按钮。
 * 自动附加取消按钮（如未提供）。
 */

/**
 * 显示模态框
 * @param {string} title - 标题
 * @param {string|HTMLElement|{html:string}} body - 内容：字符串使用 textContent；HTMLElement 作为可信节点附加；{html:string} 使用 innerHTML
 * @param {Array<{text:string, class?:string, handler:function}>} buttons - 按钮
 * @param {{size?: "large"|"full"}} options - 视觉选项
 */
function showModal(title, body, buttons = [], options = {}) {
  const overlay = document.getElementById("modal-overlay")
  const contentEl = document.getElementById("modal-content")
  const titleEl = document.getElementById("modal-title")
  const bodyEl = document.getElementById("modal-body")
  const footerEl = document.getElementById("modal-footer")

  if (!overlay || !titleEl || !bodyEl || !footerEl) return

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
    el.addEventListener("click", async () => {
      if (_isCloseButton(btn)) {
        try {
          await Promise.resolve(btn.handler?.())
        } catch (err) {
          _toastHandlerError(err)
        }
        closeModal()
        return
      }

      try {
        const result = await Promise.resolve(btn.handler?.())
        if (result !== false) closeModal()
      } catch (err) {
        _toastHandlerError(err)
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

  overlay.classList.remove("hidden")
}

function _isCloseButton(btn) {
  return btn?.text === "取消" || btn?.text === "关闭"
}

function _toastHandlerError(err) {
  const message = err?.message || "未知错误"
  if (typeof toast === "function") toast(`操作失败：${message}`, "error")
}

/** 关闭模态框 */
function closeModal() {
  const overlay = document.getElementById("modal-overlay")
  if (overlay) overlay.classList.add("hidden")
}

/**
 * 显示 HTML 模态框（调用方负责转义动态内容）
 * @param {string} title - 标题
 * @param {string} htmlString - HTML 字符串
 * @param {Array<{text:string, class?:string, handler:function}>} buttons - 按钮
 * @param {{size?: "large"|"full"}} options - 视觉选项
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

/**
 * 模态框系统
 *
 * 支持标题 + 内容 + 自定义按钮。
 * 自动附加取消按钮（如未提供）。
 */

/**
 * 显示模态框
 * @param {string} title - 标题
 * @param {string|HTMLElement} body - 内容
 * @param {Array<{text:string, class?:string, handler:function}>} buttons - 按钮
 */
function showModal(title, body, buttons = []) {
  const overlay = document.getElementById("modal-overlay")
  const titleEl = document.getElementById("modal-title")
  const bodyEl = document.getElementById("modal-body")
  const footerEl = document.getElementById("modal-footer")

  if (!overlay || !titleEl || !bodyEl || !footerEl) return

  titleEl.textContent = title

  if (typeof body === "string") {
    bodyEl.innerHTML = body
  } else {
    bodyEl.innerHTML = ""
    bodyEl.appendChild(body)
  }

  footerEl.innerHTML = ""
  for (const btn of buttons) {
    const el = document.createElement("button")
    el.className = "btn " + (btn.class || "")
    el.textContent = btn.text
    el.addEventListener("click", () => {
      btn.handler()
      closeModal()
    })
    footerEl.appendChild(el)
  }

  // 如果没有取消/关闭按钮，自动追加一个
  if (!buttons.some((b) => b.text === "取消" || b.text === "关闭")) {
    const cancel = document.createElement("button")
    cancel.className = "btn"
    cancel.textContent = "取消"
    cancel.addEventListener("click", closeModal)
    footerEl.appendChild(cancel)
  }

  overlay.classList.remove("hidden")
}

/** 关闭模态框 */
function closeModal() {
  const overlay = document.getElementById("modal-overlay")
  if (overlay) overlay.classList.add("hidden")
}

/**
 * 显示确认对话框
 * @param {string} message - 确认消息
 * @param {function} onConfirm - 确认回调
 * @param {string} confirmText - 确认按钮文字
 */
function confirmAction(message, onConfirm, confirmText = "确认") {
  showModal("确认操作", `<p>${message}</p>`, [
    { text: confirmText, class: "btn-danger", handler: onConfirm },
    { text: "取消", handler: closeModal },
  ])
}

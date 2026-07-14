/**
 * 将全局 confirmAction 包装为返回 Promise 的异步二次确认。
 *
 * 自动处理关闭按钮、遮罩点击、Esc 键和 modal 隐藏时的取消逻辑。
 */
export function confirmAsync(
  message,
  confirmText,
  { confirmAction = globalThis.confirmAction, closeModal = globalThis.closeModal } = {},
) {
  return new Promise((resolve) => {
    let settled = false
    let observer = null
    let cancelButton = null

    const settle = (value) => {
      if (settled) return
      settled = true
      cleanup()
      resolve(value)
    }
    const onConfirm = () => settle(true)
    const onCancel = () => settle(false)

    const modalClose = document.getElementById("modal-close")
    const modalOverlay = document.getElementById("modal-overlay")
    const onCloseClick = onCancel
    const onOverlayClick = (event) => {
      if (event.target === event.currentTarget) onCancel()
    }
    const onKeyDown = (event) => {
      if (event.key === "Escape") onCancel()
    }

    const cleanup = () => {
      modalClose?.removeEventListener("click", onCloseClick)
      modalOverlay?.removeEventListener("click", onOverlayClick)
      document.removeEventListener("keydown", onKeyDown, true)
      cancelButton?.removeEventListener("click", onCancel)
      observer?.disconnect()
      cancelButton = null
    }

    confirmAction(message, onConfirm, confirmText)
    // A test double or alternate modal implementation may confirm
    // synchronously. In that case settle() has already run cleanup(), so do
    // not attach listeners that can no longer be removed.
    if (settled) return

    cancelButton = Array.from(document.querySelectorAll("#modal-footer button"))
      .find((button) => ["取消", "关闭"].includes(button.textContent?.trim())) || null
    cancelButton?.addEventListener("click", onCancel)

    modalClose?.addEventListener("click", onCloseClick)
    modalOverlay?.addEventListener("click", onOverlayClick)
    document.addEventListener("keydown", onKeyDown, true)

    if (modalOverlay && typeof MutationObserver !== "undefined") {
      observer = new MutationObserver(() => {
        if (modalOverlay.classList.contains("hidden")) onCancel()
      })
      observer.observe(modalOverlay, { attributes: true, attributeFilter: ["class"] })
    }
  })
}

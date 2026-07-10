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
    let cancelButtonTimer = null

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
      observer?.disconnect()
      if (cancelButtonTimer !== null) clearTimeout(cancelButtonTimer)
      cancelButtonTimer = null
    }

    confirmAction(message, onConfirm, confirmText)
    if (!settled) {
      cancelButtonTimer = setTimeout(() => {
        if (settled || typeof document === "undefined") return
        const cancelBtn = document.querySelector(".modal-content .btn:not(.btn-primary)")
        if (cancelBtn) cancelBtn.onclick = onCancel
      }, 50)
    }

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

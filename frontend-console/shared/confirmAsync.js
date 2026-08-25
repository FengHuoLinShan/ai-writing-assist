/**
 * 将全局 confirmAction 包装为返回 Promise 的异步二次确认。
 *
 * 自动处理关闭按钮、遮罩点击、Esc 键和 modal 隐藏时的取消逻辑。
 */
export function confirmAsync(
  message,
  confirmText,
  { confirmAction = globalThis.confirmAction } = {},
) {
  return new Promise((resolve) => {
    let settled = false
    let observer = null
    let sessionObserver = null
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
      sessionObserver?.disconnect()
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

      // The imperative global modal is a singleton.  If another caller
      // replaces its content while the overlay remains visible, this promise
      // no longer owns the visible confirmation and must not confirm it.
      const modalContent = document.getElementById("modal-content")
      const modalFooter = document.getElementById("modal-footer")
      sessionObserver = new MutationObserver((records) => {
        if (
          document.getElementById("modal-overlay") !== modalOverlay
          || document.getElementById("modal-content") !== modalContent
          || document.getElementById("modal-footer") !== modalFooter
        ) onCancel()
        else if (records.some((record) => modalContent?.contains(record.target) || modalFooter?.contains(record.target))) onCancel()
      })
      if (modalContent) sessionObserver.observe(modalContent, { childList: true, subtree: true, characterData: true })
      if (modalFooter && modalFooter !== modalContent) sessionObserver.observe(modalFooter, { childList: true, subtree: true, characterData: true })
      // The service host normally lives below #app > .vue-shell-root, so a
      // route replacement can detach the whole nested host without changing
      // document.body's direct children.  Identity checks keep unrelated
      // subtree mutations outside this modal from cancelling the request.
      sessionObserver.observe(document.body, { childList: true, subtree: true })
    }
  })
}

/**
 * Toast 通知系统
 *
 * 支持 info / success / warning / error 四种类型。
 * 最多同时显示 3 条，超出则排队。不同类型有不同显示时长。
 */

const TOAST_DURATIONS = {
  success: 1500,
  info: 3000,
  warning: 4000,
  error: 5000,
}
const MAX_VISIBLE_TOASTS = 3
let _toastQueue = []
let _visibleToasts = 0

function _showNextToast() {
  if (_toastQueue.length === 0 || _visibleToasts >= MAX_VISIBLE_TOASTS) return

  const { message, type } = _toastQueue.shift()
  const container = document.getElementById("toast-container")
  if (!container) return

  _visibleToasts++

  const el = document.createElement("div")
  el.className = "toast " + (type || "info")
  el.setAttribute("role", "alert")
  el.setAttribute("aria-live", "polite")
  el.textContent = message
  container.appendChild(el)

  const duration = TOAST_DURATIONS[type] || 3000
  setTimeout(() => {
    if (el.parentNode) {
      el.style.opacity = "0"
      el.style.transition = "opacity 0.3s"
      setTimeout(() => {
        if (el.parentNode) el.parentNode.removeChild(el)
        _visibleToasts--
        _showNextToast()
      }, 300)
    }
  }, duration)
}

/**
 * 显示 Toast 通知
 * @param {{message:string, type?:string}|null} toast
 */
function showToastNotification(toast) {
  if (!toast || !toast.message) return

  _toastQueue.push({ message: toast.message, type: toast.type || "info" })
  _showNextToast()
}

/**
 * 显示 Toast 通知的便捷函数
 * @param {string} message - 消息内容
 * @param {"info"|"success"|"warning"|"error"} type - 消息类型
 */
function toast(message, type = "info") {
  window.appState.toast = { message, type }
}

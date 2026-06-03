/**
 * Toast 通知系统
 *
 * 支持 info / success / warning / error 四种类型。
 * 自动 3 秒后淡出消失，同一时间只显示一条。
 */

/**
 * 显示 Toast 通知
 * @param {{message:string, type?:string}|null} toast
 */
function showToastNotification(toast) {
  if (!toast || !toast.message) return

  const container = document.getElementById("toast-container")
  if (!container) return

  // 清除旧的定时器和 toast 元素
  const app = window.appState
  if (app && app._toastTimer !== null) {
    clearTimeout(app._toastTimer)
    app._toastTimer = null
  }
  const existingToasts = container.querySelectorAll(".toast")
  existingToasts.forEach((t) => {
    if (t.parentNode) t.parentNode.removeChild(t)
  })

  const el = document.createElement("div")
  el.className = "toast " + (toast.type || "info")
  el.textContent = toast.message
  container.appendChild(el)

  // 3 秒后自动消失
  if (app) {
    app._toastTimer = setTimeout(() => {
      if (el.parentNode) {
        el.style.opacity = "0"
        el.style.transition = "opacity 0.3s"
        setTimeout(() => {
          if (el.parentNode) el.parentNode.removeChild(el)
          if (app) app._toastTimer = null
        }, 300)
      }
    }, 3000)
  }
}

/**
 * 显示 Toast 通知的便捷函数
 * @param {string} message - 消息内容
 * @param {"info"|"success"|"warning"|"error"} type - 消息类型
 */
function toast(message, type = "info") {
  window.appState.toast = { message, type }
}

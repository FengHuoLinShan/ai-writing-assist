/**
 * 错误日志系统
 *
 * 自动拦截 toast error/warning 和 API 请求失败，按编号记入 localStorage。
 * 前端只显示错误计数，AI 通过编号查询完整记录。
 *
 * 用法：
 *   window.__errorLog          → 返回全部日志数组
 *   window.__errorLogById(id)  → 返回单条日志
 *   window.__clearErrorLog()   → 清空日志 + 刷新 badge
 *   window.__latestErrorId     → 最新错误编号
 */
;(function () {
  const STORAGE_KEY = "_errorLog"
  const MAX_ENTRIES = 50
  let _idCounter = 0

  // ── 从 localStorage 恢复计数器 ──
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const entries = JSON.parse(saved)
      if (Array.isArray(entries) && entries.length > 0) {
        _idCounter = Math.max(...entries.map((e) => e.id || 0))
      }
    }
  } catch {}

  // ── 内部读写 ──
  function _read() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      return raw ? JSON.parse(raw) : []
    } catch {
      return []
    }
  }

  function _write(entries) {
    // 只保留最近的 MAX_ENTRIES 条
    const trimmed = entries.slice(-MAX_ENTRIES)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
    } catch {}
    _updateBadge(trimmed.length)
    return trimmed
  }

  function _add(entry) {
    _idCounter++
    const full = {
      id: _idCounter,
      timestamp: new Date().toISOString(),
      view: (typeof _state !== "undefined" && _state.currentView) || "",
      subView: (typeof _state !== "undefined" && _state.currentSubView) || "",
      ...entry,
    }
    const entries = _read()
    entries.push(full)
    _write(entries)
    return full
  }

  // ── 页面小 badge ──
  function _updateBadge(count) {
    let badge = document.getElementById("error-log-badge")
    if (count === 0) {
      if (badge) badge.style.display = "none"
      return
    }
    if (!badge) {
      badge = document.createElement("div")
      badge.id = "error-log-badge"
      badge.title = "错误日志。引用编号通知 AI 查看详情"
      badge.style.cssText =
        "position:fixed;bottom:4px;right:4px;z-index:9999;" +
        "background:#dc2626;color:#fff;font-size:10px;font-family:monospace;" +
        "padding:2px 6px;border-radius:8px;cursor:pointer;opacity:0.5;" +
        "line-height:1.4;"
      badge.addEventListener("click", () => {
        const log = _read()
        const last5 = log.slice(-5)
        const text = last5
          .map((e) => `#${e.id} [${e.level}] ${e.message} (${e.timestamp.slice(11, 19)})`)
          .join("\n")
        if (confirm(
          `错误日志（共 ${log.length} 条）\n---\n${text}\n---\n点击「确定」清空所有日志\n点击「取消」关闭`,
        )) {
          window.__clearErrorLog()
        }
      })
      badge.addEventListener("contextmenu", (e) => {
        e.preventDefault()
        window.__clearErrorLog()
      })
      document.body.appendChild(badge)
    }
    badge.style.display = "block"
    badge.textContent = `⚠ ${count}`
  }

  // ── 拦截 toast ──
  const _origToast = typeof window.toast === "function" ? window.toast : null

  function _patchedToast(message, type) {
    if (type === "error" || type === "warning") {
      const reqCtx = window.__lastFailedRequest || undefined
      window.__lastFailedRequest = undefined // 消费后清除
      _add({
        type: reqCtx ? "api_error" : type === "error" ? "runtime" : "validation",
        level: type,
        message: String(message),
        request: reqCtx,
        stack: new Error().stack?.split("\n").slice(2, 5).join("\n") || "",
      })
    }
    if (_origToast) _origToast(message, type)
  }

  // 延迟挂载 patch（state.js 先加载，toast 定义在后）
  function _installToastPatch() {
    if (typeof window.toast === "function" && window.toast !== _patchedToast) {
      window._origToast = window.toast
      window.toast = _patchedToast
    }
  }

  // ── 捕获未处理的 Promise 异常 ──
  window.addEventListener("unhandledrejection", (event) => {
    const msg = event.reason?.message || String(event.reason)
    _add({
      type: "runtime",
      level: "error",
      message: msg,
      stack: event.reason?.stack || "",
    })
  })

  // ── window.onerror ──
  window.addEventListener("error", (event) => {
    _add({
      type: "runtime",
      level: "error",
      message: event.message || String(event.error?.message || ""),
      stack: event.error?.stack || "",
    })
  })

  // ── 公开 API ──
  window.__errorLog = _read()
  window.__clearErrorLog = function () {
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {}
    _idCounter = 0
    _updateBadge(0)
  }
  window.__errorLogById = function (id) {
    const entries = _read()
    return entries.find((e) => e.id === id) || null
  }
  Object.defineProperty(window, "__latestErrorId", {
    get: () => _idCounter || null,
  })

  // ── 初始化 ──
  _installToastPatch()
  // setInterval 兜底：state.js 可能还未加载
  const _retryInt = setInterval(() => {
    if (typeof window.toast === "function") {
      _installToastPatch()
      clearInterval(_retryInt)
    }
  }, 100)
  setTimeout(() => clearInterval(_retryInt), 5000)

  const count = _read().length
  _updateBadge(count)

  console.log("[error-logger] 已加载，当前日志数:", count)
})()

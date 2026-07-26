import { resolveApiBaseUrl } from "./shared/apiBaseUrl.js"

/**
 * 错误日志系统
 *
 * 自动拦截 toast error 和 API 请求失败，按编号记入 localStorage。
 * 前端只显示错误计数，AI 通过编号查询完整记录。
 *
 * 用法：
 *   window.errorLog.getAll()          → 返回全部日志数组
 *   window.errorLog.getById(id)       → 返回单条日志
 *   window.errorLog.clear()           → 清空日志 + 刷新 badge
 *   window.errorLog.latestId          → 最新错误编号
 */
;(function () {
  const LEGACY_STORAGE_KEY = "_errorLog"
  const STORAGE_PREFIX = "_errorLog:"
  const MAX_ENTRIES = 50
  let _isUnloading = false

  function _isSensitiveLogKey(key) {
    const normalized = String(key || "").toLowerCase().replace(/[^a-z0-9]/g, "")
    return normalized === "auth"
      || normalized.includes("authorization")
      || normalized.includes("apikey")
      || normalized.endsWith("token")
      || normalized.includes("secret")
      || normalized.includes("password")
      || normalized.includes("passwd")
      || normalized.includes("credential")
      || normalized.includes("cookie")
  }

  function _redactLogText(value) {
    return String(value)
      .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
      .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, "[REDACTED]")
      .replace(
        /((?:api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|credential)\s*[:=]\s*["']?)([^"',;\s}&]+)/gi,
        "$1[REDACTED]",
      )
  }

  function _hasSensitiveLogLocation(value) {
    return Array.isArray(value?.loc)
      && value.loc.some((segment) => _isSensitiveLogKey(segment))
  }

  function _redactLogValue(value, seen = new WeakSet()) {
    if (typeof value === "string") return _redactLogText(value)
    if (value == null || typeof value !== "object") return value
    if (seen.has(value)) return "[Circular]"
    seen.add(value)
    if (Array.isArray(value)) return value.map((item) => _redactLogValue(item, seen))
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      key,
      _isSensitiveLogKey(key)
        || (key === "input" && _hasSensitiveLogLocation(value))
        ? "[REDACTED]"
        : _redactLogValue(item, seen),
    ]))
  }

  function _safeResponseDiagnostic(response) {
    if (typeof response !== "string") return _redactLogValue(response)
    if (!response) return response
    try {
      return JSON.stringify(_redactLogValue(JSON.parse(response)))
    } catch {
      return "[REDACTED]"
    }
  }

  function _safeRequestContext(request) {
    if (!request || typeof request !== "object") return undefined
    const safe = _redactLogValue(request)
    return Object.fromEntries(["method", "url", "status", "response"]
      .filter((key) => safe[key] !== undefined)
      .map((key) => [
        key,
        key === "response" ? _safeResponseDiagnostic(request.response) : safe[key],
      ]))
  }

  function _sanitizeLogEntry(entry) {
    const safe = _redactLogValue(entry)
    if (safe && typeof safe === "object" && Object.hasOwn(safe, "request")) {
      safe.request = _safeRequestContext(entry.request)
    }
    return safe
  }

  function _currentProjectId() {
    return (typeof state !== "undefined" && state.currentProjectId) || null
  }

  function _scopeId() {
    return _currentProjectId() || "global"
  }

  function _storageKey(scopeId = _scopeId()) {
    return `${STORAGE_PREFIX}${scopeId}`
  }

  function _latestId(entries = _read()) {
    if (!Array.isArray(entries) || entries.length === 0) return null
    return Math.max(...entries.map((e) => Number(e?.id) || 0)) || null
  }

  function _migrateLegacyLog() {
    try {
      const legacyRaw = localStorage.getItem(LEGACY_STORAGE_KEY)
      if (!legacyRaw) return
      const legacyEntries = JSON.parse(legacyRaw)
      if (Array.isArray(legacyEntries) && legacyEntries.length > 0) {
        const globalEntries = _read("global")
        _write([...globalEntries, ...legacyEntries], "global")
      }
      localStorage.removeItem(LEGACY_STORAGE_KEY)
    } catch {
      try { localStorage.removeItem(LEGACY_STORAGE_KEY) } catch {}
    }
  }

  // ── 内部读写 ──
  function _read(scopeId = _scopeId()) {
    try {
      const raw = localStorage.getItem(_storageKey(scopeId))
      const parsed = raw ? JSON.parse(raw) : []
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }

  function _write(entries, scopeId = _scopeId()) {
    // 只保留最近的 MAX_ENTRIES 条
    const trimmed = entries.map(_sanitizeLogEntry).slice(-MAX_ENTRIES)
    try {
      localStorage.setItem(_storageKey(scopeId), JSON.stringify(trimmed))
    } catch {}
    if (scopeId === _scopeId()) _updateBadge(trimmed.length)
    return trimmed
  }

  function _add(entry) {
    const entries = _read()
    const full = _sanitizeLogEntry({
      id: (_latestId(entries) || 0) + 1,
      timestamp: new Date().toISOString(),
      view: (typeof state !== "undefined" && state.currentView) || "",
      subView: (typeof state !== "undefined" && state.currentSubView) || "",
      ...entry,
      projectId: _currentProjectId(),
    })
    entries.push(full)
    _write(entries)
    _syncToBackend(full)
    return full
  }

  function _debugApiBaseUrl() {
    const apiBaseUrl = resolveApiBaseUrl(
      typeof API_HOST !== "undefined" ? API_HOST : "",
    )
    return `${apiBaseUrl}/debug`
  }

  function _syncToBackend(entry) {
    if (!entry || entry.level !== "error" || typeof fetch !== "function") return
    const payload = _redactLogValue({
      frontendId: entry.id,
      level: entry.level,
      type: entry.type || "runtime",
      message: String(entry.message || ""),
      timestamp: entry.timestamp,
      view: entry.view || "",
      subView: entry.subView || "",
      stack: entry.stack || "",
      request: _safeRequestContext(entry.request),
      page: {
        url: window.location?.href || "",
        title: document.title || "",
      },
      browser: {
        userAgent: navigator.userAgent || "",
        language: navigator.language || "",
      },
    })

    if (typeof window.api?.reportFrontendError === "function") {
      window.api.reportFrontendError(payload).catch(() => {})
      return
    }

    // api.js 是 module script；极早期启动错误发生在其执行前时仍允许无令牌上报。
    fetch(`${_debugApiBaseUrl()}/frontend-errors`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {})
  }

  function _isFixedBulkSelectionExportError(entry) {
    const message = String(entry?.message || "")
    return message.includes("bulkSelection.js")
      && message.includes("syncBulkSelectionUi")
      && message.includes("does not provide an export named")
  }

  async function _pruneFixedStartupErrors() {
    const entries = _read()
    if (!entries.some(_isFixedBulkSelectionExportError)) return

    try {
      const bulkSelection = await import("./shared/bulkSelection.js")
      if (typeof bulkSelection.syncBulkSelectionUi !== "function") return
    } catch {
      return
    }

    const kept = entries.filter((entry) => !_isFixedBulkSelectionExportError(entry))
    if (kept.length !== entries.length) _write(kept)
  }

  function _pruneNonErrorEntries() {
    const entries = _read()
    const kept = entries.filter((entry) => entry?.level === "error")
    if (kept.length !== entries.length) _write(kept)
    return kept
  }

  function _sanitizeStoredBuckets() {
    try {
      const keys = []
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index)
        if (key?.startsWith(STORAGE_PREFIX)) keys.push(key)
      }
      for (const key of keys) {
        const entries = JSON.parse(localStorage.getItem(key) || "[]")
        if (!Array.isArray(entries)) continue
        localStorage.setItem(key, JSON.stringify(entries.map(_sanitizeLogEntry).slice(-MAX_ENTRIES)))
      }
    } catch {}
  }

  function _hidePanel() {
    const panel = document.getElementById("error-log-panel")
    if (panel) panel.remove()
  }

  function _appendText(parent, tagName, text, style = "") {
    const node = document.createElement(tagName)
    if (style) node.style.cssText = style
    node.textContent = text
    parent.appendChild(node)
    return node
  }

  function _showPanel() {
    _hidePanel()

    const log = _read()
    const panel = document.createElement("div")
    panel.id = "error-log-panel"
    panel.style.cssText =
      "position:fixed;right:12px;bottom:32px;z-index:9999;width:min(520px,calc(100vw - 24px));" +
      "max-height:min(440px,calc(100vh - 80px));overflow:auto;background:var(--bg,#fff);" +
      "color:var(--text,#111827);border:1px solid var(--border,#d1d5db);border-radius:var(--radius-md);" +
      "box-shadow:0 16px 40px rgba(15,23,42,0.24);font:12px/1.5 system-ui,sans-serif;"

    const header = document.createElement("div")
    header.style.cssText =
      "position:sticky;top:0;display:flex;align-items:center;gap:8px;justify-content:space-between;" +
      "padding:10px 12px;background:var(--bg,#fff);border-bottom:1px solid var(--border,#d1d5db);"
    _appendText(header, "strong", `错误日志（共 ${log.length} 条）`)

    const actions = document.createElement("div")
    actions.style.cssText = "display:flex;gap:6px;"
    const clearButton = document.createElement("button")
    clearButton.type = "button"
    clearButton.textContent = "清空"
    clearButton.style.cssText = "font-size:12px;padding:4px 8px;cursor:pointer;"
    clearButton.addEventListener("click", () => {
      window.errorLog.clear()
      _hidePanel()
    })
    const closeButton = document.createElement("button")
    closeButton.type = "button"
    closeButton.textContent = "关闭"
    closeButton.style.cssText = "font-size:12px;padding:4px 8px;cursor:pointer;"
    closeButton.addEventListener("click", _hidePanel)
    actions.append(clearButton, closeButton)
    header.appendChild(actions)
    panel.appendChild(header)

    const body = document.createElement("div")
    body.style.cssText = "padding:10px 12px;display:grid;gap:8px;"
    for (const entry of log.slice(-10).reverse()) {
      const item = document.createElement("article")
      item.style.cssText = "border:1px solid var(--border,#e5e7eb);border-radius:var(--radius-md);padding:8px;background:rgba(15,23,42,0.03);"
      _appendText(item, "div", `#${entry.id} [${entry.level}] ${entry.timestamp || ""}`, "font-weight:600;margin-bottom:4px;")
      _appendText(item, "div", String(entry.message || ""))
      if (entry.request) {
        _appendText(item, "pre", JSON.stringify(entry.request, null, 2), "white-space:pre-wrap;margin:6px 0 0;color:var(--text-secondary,#4b5563);")
      }
      if (entry.stack) {
        _appendText(item, "pre", String(entry.stack), "white-space:pre-wrap;margin:6px 0 0;color:var(--text-secondary,#4b5563);")
      }
      body.appendChild(item)
    }
    panel.appendChild(body)
    document.body.appendChild(panel)
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
        "padding:2px 6px;border-radius:var(--radius-md);cursor:pointer;opacity:0.5;" +
        "line-height:1.4;"
      badge.addEventListener("click", () => {
        _showPanel()
      })
      badge.addEventListener("contextmenu", (e) => {
        e.preventDefault()
        window.errorLog.clear()
      })
      document.body.appendChild(badge)
    }
    badge.style.display = "block"
    badge.textContent = `⚠ ${count}`
  }

  // ── 记录 error toast ──
  function _recordToastError(message, type) {
    if (type === "error") {
      if (_isUnloading) return
      const reqCtx = window.errorLog._lastApiError || undefined
      window.errorLog._lastApiError = null // 消费后清除
      _add({
        type: reqCtx ? "api_error" : "runtime",
        level: type,
        message: String(message),
        request: reqCtx,
        stack: new Error().stack?.split("\n").slice(2, 5).join("\n") || "",
      })
    }
  }

  function _installToastStateListener() {
    if (typeof onStateChange !== "function") return
    onStateChange((key, value) => {
      if (key === "toast") _recordToastError(value?.message, value?.type)
      if (key === "error" && value) _recordToastError(String(value), "error")
      if (key === "currentProjectId") {
        _hidePanel()
        _updateBadge(_read().length)
      }
    })
  }

  // ── 捕获未处理的 Promise 异常 ──
  window.addEventListener("unhandledrejection", (event) => {
    if (_isUnloading) return
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
    if (_isUnloading) return
    _add({
      type: "runtime",
      level: "error",
      message: event.message || String(event.error?.message || ""),
      stack: event.error?.stack || "",
    })
  })

  window.addEventListener("beforeunload", () => {
    _isUnloading = true
  })
  window.addEventListener("pagehide", () => {
    _isUnloading = true
  })

  // ── 公开 API ──
  window.errorLog = {
    getAll() { return _read() },
    getById(id) { return _read().find((e) => e.id === id) || null },
    clear() {
      try { localStorage.removeItem(_storageKey()) } catch {}
      _updateBadge(0)
      _hidePanel()
    },
    get latestId() { return _latestId() },
    // 内部跨模块数据通道（api.js 写入请求上下文）
    _lastApiError: null,
  }

  // ── 初始化 ──
  _migrateLegacyLog()
  _sanitizeStoredBuckets()
  _installToastStateListener()

  const count = _pruneNonErrorEntries().length
  _updateBadge(count)
  _pruneFixedStartupErrors()

  console.log("[errorLogger] 已加载，当前日志数:", count)
})()

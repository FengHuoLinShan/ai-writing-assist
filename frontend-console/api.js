/**
 * API 封装 — 与后端 REST API 通信
 *
 * 基础 URL 可配置，统一错误处理，超时控制。
 * 所有函数返回 Promise<Object>。
 */

import { forceAccountSafeReload } from "./shared/accountStorage.js"
import { resolveApiBaseUrl } from "./shared/apiBaseUrl.js"

const API_BASE_URL = resolveApiBaseUrl(
  typeof API_HOST !== "undefined" ? API_HOST : "",
)
const API_TIMEOUT = 15000
const API_CACHE_TTL = 30000
const API_CACHE_MAX_ENTRIES = 128
// 封闭测试服令牌只保存在当前页面的 module scope 中。刷新后重新输入，避免
// bearer credential 暴露在可枚举、可跨页面生命周期读取的 Web Storage 中。
let _accessToken = ""
let _accessTokenRequestPromise = null
let _authMode = "closed_test"

function _cookieValue(name) {
  if (typeof document === "undefined") return ""
  const prefix = `${name}=`
  const item = document.cookie.split(";").map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : ""
}

function _setAccessToken(token) {
  _accessToken = typeof token === "string" ? token.trim() : ""
  return Boolean(_accessToken)
}

function _clearAccessToken() {
  _accessToken = ""
}

function _handleUnauthorizedResponse({ invalidateAccount = true } = {}) {
  _clearAccessToken()
  if (!invalidateAccount || _authMode !== "public") return
  _clearRequestCache()
  forceAccountSafeReload({ reason: "public-unauthorized" })
}

function _requestAccessToken() {
  if (_accessTokenRequestPromise) return _accessTokenRequestPromise
  if (typeof window === "undefined" || typeof window.showModalHtml !== "function") {
    return Promise.resolve("")
  }
  _accessTokenRequestPromise = new Promise((resolve) => {
    let settled = false
    let observer = null
    const settle = (value = "") => {
      if (settled) return
      settled = true
      observer?.disconnect()
      resolve(typeof value === "string" ? value.trim() : "")
    }
    window.showModalHtml(
      "访问令牌",
      `<div class="form-group"><label for="closed-test-access-token">封闭测试访问令牌</label><input class="form-input" id="closed-test-access-token" type="password" autocomplete="off" /></div>`,
      [
        {
          text: "继续",
          class: "btn-primary",
          handler: () => {
            const value = document.getElementById("closed-test-access-token")?.value?.trim() || ""
            if (!value) {
              if (typeof window.toast === "function") window.toast("请输入访问令牌", "warning")
              return false
            }
            settle(value)
            return true
          },
        },
        { text: "取消", class: "btn-ghost", handler: () => settle("") },
      ],
      { protectUnsaved: false },
    )
    const overlay = document.getElementById("modal-overlay")
    if (overlay && typeof MutationObserver !== "undefined") {
      observer = new MutationObserver(() => {
        if (overlay.classList.contains("hidden")) settle("")
      })
      observer.observe(overlay, { attributes: true, attributeFilter: ["class"] })
    }
  }).finally(() => {
    _accessTokenRequestPromise = null
  })
  return _accessTokenRequestPromise
}

function _authorizationHeaders(headers = {}) {
  const result = { ...headers }
  // 保留 request() 原有的调用方 header 优先级；显式 Authorization
  // 可用于窄范围的临时凭据，且不应被封闭测试令牌静默覆盖。
  const hasExplicitAuthorization = Object.keys(result)
    .some((name) => name.toLowerCase() === "authorization")
  if (_accessToken && !hasExplicitAuthorization) {
    result.Authorization = `Bearer ${_accessToken}`
  }
  return result
}

const _apiCache = new Map()
const _pendingRequests = new Map()
const _cacheGenerations = new Map()

function _cacheKey(path, options) {
  const method = (options.method || "GET").toUpperCase()
  return `${method}:${path}`
}

function _collectionRoot(path) {
  const base = String(path || "").split("?")[0]
  const firstSegment = base.split("/").filter(Boolean)[0]
  return firstSegment ? `/${firstSegment}` : "/"
}

function _cacheGeneration(path) {
  const collectionRoot = _collectionRoot(path)
  let generation = _cacheGenerations.get(collectionRoot)
  if (!generation) {
    generation = {}
    _cacheGenerations.set(collectionRoot, generation)
  }
  return generation
}

function _isRelatedCacheKey(key, collectionRoot) {
  const keyPath = key.slice(key.indexOf(":") + 1)
  return keyPath === collectionRoot
    || keyPath.startsWith(collectionRoot + "/")
    || keyPath.startsWith(collectionRoot + "?")
}

function _invalidateRelatedCache(path) {
  // 失效该资源集合的所有 GET 缓存。
  // 写操作(含 /{id}/restore、/{id}/permanent 这类子动作)都会影响同一集合的列表,
  // 因此按集合根(第一路径段,如 /projects)清除,避免子路径动作遗漏集合级列表(如 recycle-bin)缓存。
  const collectionRoot = _collectionRoot(path)
  // 代次先于写请求的 JSON 解析完成切换：既有 GET 即使晚到，也不能
  // 在写操作成功后重新回填旧缓存。
  _cacheGenerations.set(collectionRoot, {})
  for (const requestStore of [_apiCache, _pendingRequests]) {
    for (const key of requestStore.keys()) {
      if (_isRelatedCacheKey(key, collectionRoot)) requestStore.delete(key)
    }
  }
}

function _clearRequestCache() {
  _apiCache.clear()
  _pendingRequests.clear()
  // 清空 token 映射也会使正在返回的旧 GET 与后续新 token 失配，
  // 避免账号切换或显式清缓存后被晚到响应回填。
  _cacheGenerations.clear()
}

function _getCached(key) {
  const entry = _apiCache.get(key)
  if (!entry) return null
  if (Date.now() - entry.time > API_CACHE_TTL) {
    _apiCache.delete(key)
    return null
  }
  // Map 保留插入顺序；命中后移到末尾，使容量淘汰遵循 LRU。
  _apiCache.delete(key)
  _apiCache.set(key, entry)
  return entry.data
}

function _setCache(key, data) {
  const now = Date.now()
  for (const [cachedKey, entry] of _apiCache) {
    if (now - entry.time > API_CACHE_TTL) _apiCache.delete(cachedKey)
  }
  _apiCache.delete(key)
  _apiCache.set(key, { data, time: now })
  while (_apiCache.size > API_CACHE_MAX_ENTRIES) {
    _apiCache.delete(_apiCache.keys().next().value)
  }
}

function _isSensitiveDiagnosticKey(key) {
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

function _redactDiagnosticText(value) {
  return String(value)
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, "[REDACTED]")
    .replace(
      /((?:api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|credential)\s*[:=]\s*["']?)([^"',;\s}&]+)/gi,
      "$1[REDACTED]",
    )
}

function _hasSensitiveDiagnosticLocation(value) {
  return Array.isArray(value?.loc)
    && value.loc.some((segment) => _isSensitiveDiagnosticKey(segment))
}

function _redactDiagnosticValue(value, seen = new WeakSet()) {
  if (typeof value === "string") return _redactDiagnosticText(value)
  if (value == null || typeof value !== "object") return value
  if (seen.has(value)) return "[Circular]"
  seen.add(value)
  if (Array.isArray(value)) {
    return value.map((item) => _redactDiagnosticValue(item, seen))
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key,
    _isSensitiveDiagnosticKey(key)
      || (key === "input" && _hasSensitiveDiagnosticLocation(value))
      ? "[REDACTED]"
      : _redactDiagnosticValue(item, seen),
  ]))
}

function _stringifyDiagnostic(value, maxLength = 500) {
  try {
    return JSON.stringify(_redactDiagnosticValue(value)).slice(0, maxLength)
  } catch {
    return ""
  }
}

function _formatErrorValue(value) {
  if (value == null) return ""
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  if (Array.isArray(value)) {
    return value.map((item) => _formatErrorValue(item)).filter(Boolean).join(", ")
  }
  if (typeof value === "object") {
    const preferred = [
      value.name,
      value.title,
      value.message,
      value.msg,
      value.detail,
      value.id,
    ].find((item) => item != null && item !== "")
    if (preferred != null) {
      const score = value.similarity_score ?? value.score ?? value.confidence
      const suffix = score != null ? ` (${score})` : ""
      return `${_formatErrorValue(preferred)}${suffix}`
    }
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

function _formatErrorDetail(rawDetail) {
  if (Array.isArray(rawDetail)) {
    return rawDetail
      .map((item) => {
        if (typeof item === "string") return item
        if (item && typeof item === "object") {
          const parts = []
          if (item.loc && Array.isArray(item.loc)) parts.push(item.loc.join("."))
          if (item.msg) parts.push(item.msg)
          if (item.type) parts.push(`(${item.type})`)
          return parts.length ? parts.join(" — ") : _formatErrorValue(item)
        }
        return _formatErrorValue(item)
      })
      .filter(Boolean)
      .join("；")
  }
  if (rawDetail && typeof rawDetail === "object") {
    return Object.entries(rawDetail)
      .map(([key, value]) => `${key}: ${_formatErrorValue(value)}`)
      .filter(Boolean)
      .join("；")
  }
  return String(rawDetail || "")
}

/**
 * 通用请求函数
 * @param {string} path - API 路径（不含基础 URL）
 * @param {Object} [options] - fetch 选项
 * @returns {Promise<any>}
 */
async function request(path, options = {}) {
  const {
    timeout,
    signal: externalSignal,
    _retriedAuth,
    _suppressAccountInvalidation = false,
    ...fetchOptions
  } = options
  const url = `${API_BASE_URL}${path}`
  const controller = new AbortController()
  const timeoutMs = timeout || API_TIMEOUT
  let timeoutFired = false
  const timeoutId = setTimeout(() => {
    timeoutFired = true
    controller.abort()
  }, timeoutMs)
  const cleanup = () => {
    clearTimeout(timeoutId)
    if (externalAbortHandler && externalSignal) {
      externalSignal.removeEventListener("abort", externalAbortHandler)
    }
  }

  let signal = controller.signal
  let externalAbortHandler = null
  if (externalSignal) {
    if (typeof AbortSignal !== "undefined" && AbortSignal.any) {
      signal = AbortSignal.any([controller.signal, externalSignal])
    } else {
      externalAbortHandler = () => controller.abort()
      if (externalSignal.aborted) {
        controller.abort()
      } else {
        externalSignal.addEventListener("abort", externalAbortHandler, { once: true })
      }
    }
  }

  const headers = {
    "Accept": "application/json",
  }

  const method = (fetchOptions.method || "GET").toUpperCase()
  const isFormData = fetchOptions.body instanceof FormData
  if (method !== "GET" && method !== "HEAD") {
    headers["X-Requested-With"] = "XMLHttpRequest"
    const csrfToken = _cookieValue("aaw_csrf")
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken
  }
  if (method !== "GET" && method !== "HEAD" && !isFormData) {
    headers["Content-Type"] = "application/json"
  }

  const cacheKey = _cacheKey(path, fetchOptions)
  // `no-store` is also honored by our in-memory cache.  Passing it only to
  // fetch would still allow a stale application-cache hit before fetch runs,
  // and an obsolete response could be written back after a project switch.
  const shouldUseResponseCache = method === "GET" && fetchOptions.cache !== "no-store"
  const shouldSharePending = shouldUseResponseCache && !externalSignal
  const responseCacheGeneration = shouldUseResponseCache
    ? _cacheGeneration(path)
    : null

  if (shouldUseResponseCache) {
    const cached = _getCached(cacheKey)
    if (cached !== null) {
      cleanup()
      return cached
    }

    // 外部 AbortSignal 不共享 pending：第一个调用者 abort 不应影响后续调用者
    if (shouldSharePending) {
      const pending = _pendingRequests.get(cacheKey)
      if (pending) {
        cleanup()
        return pending
      }
    }
  }

  const requestPromise = (async () => {
    try {
      const resp = await fetch(url, {
        ...fetchOptions,
        credentials: fetchOptions.credentials || "include",
        headers: _authorizationHeaders({ ...headers, ...fetchOptions.headers }),
        signal,
      })
      // Native fetch rejects on abort, but keep the contract deterministic for
      // test doubles/polyfills and for an abort racing with response delivery.
      if (signal.aborted) {
        const abortError = new Error("Aborted")
        abortError.name = "AbortError"
        throw abortError
      }

      if (!resp.ok) {
        if (resp.status === 401) {
          _handleUnauthorizedResponse({
            invalidateAccount: !_suppressAccountInvalidation,
          })
        }
        if (resp.status === 401 && !_retriedAuth && _authMode === "closed_test") {
          const token = await _requestAccessToken()
          if (_setAccessToken(token)) {
            // 首次 GET 仍登记在 pending map 中；认证重试必须绕过该条目，
            // 否则递归请求会等待尚未结束的自己。
            return request(path, { ...options, cache: "no-store", _retriedAuth: true })
          }
        }
        const errorMap = {
          400: "请求参数错误",
          401: "未授权，请检查后端认证配置",
          404: "请求的资源不存在",
          409: "请求冲突",
          422: "数据格式校验失败",
          500: "后端服务器错误",
          502: "后端服务不可用",
          503: "后端服务暂时不可用",
        }
        let detail = "", responseBody = "", errorBody = null, rawDetail = ""
        try {
          errorBody = await resp.json()
          errorBody = _redactDiagnosticValue(errorBody)
          rawDetail = errorBody.detail || errorBody.message || ""
          responseBody = _stringifyDiagnostic(errorBody)
          detail = _formatErrorDetail(rawDetail)
        } catch (e) { console.warn("解析错误响应失败", e) }

        const msg = errorMap[resp.status] || `请求失败 (${resp.status})`

        // 只记录无凭据的诊断元数据。请求体可能包含 API Key，禁止进入错误日志。
        if (window.errorLog) {
          window.errorLog._lastApiError = {
            method, url: _redactDiagnosticText(path),
            status: resp.status,
            response: responseBody,
          }
        }

        const err = new Error(detail ? `${msg}：${detail}` : msg)
        err.status = resp.status
        err.detail = rawDetail
        err.body = errorBody
        err.responseBody = responseBody
        throw err
      }

      // 只在写操作成功后才失效相关 GET 缓存，避免失败请求清空有效缓存。
      if (method !== "GET") {
        _invalidateRelatedCache(path)
      }

      if (resp.status === 204) {
        if (shouldUseResponseCache) {
          if (_cacheGeneration(path) !== responseCacheGeneration) {
            return request(path, options)
          }
          _setCache(cacheKey, null)
        }
        return null
      }

      const data = await resp.json()
      if (shouldUseResponseCache) {
        if (_cacheGeneration(path) !== responseCacheGeneration) {
          return request(path, options)
        }
        _setCache(cacheKey, data)
      }
      return data
    } catch (err) {
      if (err.name === "AbortError") {
        if (timeoutFired) {
          throw new Error("请求超时，请检查后端服务是否运行")
        }
        if (externalSignal?.aborted) {
          throw new Error("请求已取消")
        }
        throw err
      }

      if (!err.status && (err.message === "Failed to fetch" || err.message.includes("fetch"))) {
        throw new Error("无法访问 API 服务，请检查开发代理、浏览器网络策略或后端状态")
      }

      throw err
    } finally {
      cleanup()
      if (shouldSharePending && _pendingRequests.get(cacheKey) === requestPromise) {
        _pendingRequests.delete(cacheKey)
      }
    }
  })()

  if (shouldSharePending) _pendingRequests.set(cacheKey, requestPromise)

  return requestPromise
}

/**
 * 构建查询字符串
 * @param {Object} params - 查询参数
 * @returns {string}
 */
function buildQueryString(params = {}) {
  const parts = []
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    }
  }
  return parts.length ? "?" + parts.join("&") : ""
}

function withQuery(path, params = {}) {
  return path + buildQueryString(params)
}

function jsonRequest(path, method, payload, options = {}) {
  const requestOptions = {
    method,
    ...options,
  }
  if (payload !== undefined) requestOptions.body = JSON.stringify(payload)
  return request(path, requestOptions)
}

function post(path, payload, options = {}) {
  return jsonRequest(path, "POST", payload, options)
}

function put(path, payload, options = {}) {
  return jsonRequest(path, "PUT", payload, options)
}

function patch(path, payload, options = {}) {
  return jsonRequest(path, "PATCH", payload, options)
}

function deleteRequest(path) {
  return request(path, { method: "DELETE" })
}

function uploadImportFile(file, novelId, onProgress = null, options = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const signal = options?.signal
    const formData = new FormData()
    formData.append("file", file)
    formData.append("novel_id", novelId)

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || typeof onProgress !== "function") return
      onProgress(Math.round((event.loaded / event.total) * 100))
    }
    const cleanup = () => signal?.removeEventListener?.("abort", abortUpload)
    const abortUpload = () => xhr.abort()
    if (signal?.aborted) {
      reject(new DOMException("上传已取消", "AbortError"))
      return
    }
    signal?.addEventListener?.("abort", abortUpload, { once: true })
    xhr.onload = () => {
      cleanup()
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          reject(new Error("上传响应格式错误"))
        }
        return
      }
      if (xhr.status === 401) _handleUnauthorizedResponse()
      try {
        const error = JSON.parse(xhr.responseText)
        reject(new Error(error.detail || "上传失败"))
      } catch {
        reject(new Error("上传失败"))
      }
    }
    xhr.onerror = () => {
      cleanup()
      reject(new Error("网络错误"))
    }
    xhr.onabort = () => {
      cleanup()
      reject(new DOMException("上传已取消", "AbortError"))
    }
    xhr.open("POST", `${API_BASE_URL}/imports/upload`)
    xhr.withCredentials = true
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest")
    const csrfToken = _cookieValue("aaw_csrf")
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken)
    if (_accessToken) xhr.setRequestHeader("Authorization", `Bearer ${_accessToken}`)
    xhr.send(formData)
  })
}

function reportFrontendError(payload) {
  if (typeof fetch !== "function") return Promise.resolve()
  return fetch(`${API_BASE_URL}/debug/frontend-errors`, {
    method: "POST",
    credentials: "include",
    headers: _authorizationHeaders({
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    }),
    body: JSON.stringify(_redactDiagnosticValue(payload)),
    keepalive: true,
  }).then((response) => {
    if (response.status === 401) _handleUnauthorizedResponse()
    return response
  })
}

const apiContractHelpers = globalThis.apiContracts
if (!apiContractHelpers) {
  throw new Error("apiContracts.js must load before api.js")
}

function contractPath(name, params = {}, query = {}) {
  return apiContractHelpers.contractPath(name, params, query)
}

function contractFetch(name, params = {}, query = {}, options = {}) {
  const contractRequest = apiContractHelpers.contractRequest(
    name,
    params,
    query,
    options,
  )
  return request(contractRequest.path, contractRequest.options)
}

function contractJson(name, params = {}, query = {}, payload, options = {}) {
  const contractRequest = apiContractHelpers.contractRequest(
    name,
    params,
    query,
    { ...options, body: payload },
  )
  return request(contractRequest.path, contractRequest.options)
}

async function* streamSse(path, { signal } = {}) {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method: "GET",
    credentials: "include",
    cache: "no-store",
    headers: _authorizationHeaders({
      "Accept": "text/event-stream",
    }),
    signal,
  })
  if (!resp.ok) {
    if (resp.status === 401) _handleUnauthorizedResponse()
    let detail = ""
    try {
      const body = _redactDiagnosticValue(await resp.json())
      detail = _formatErrorDetail(body?.detail || body?.message || "")
    } catch {}
    const error = new Error(detail || `流式连接失败 (${resp.status})`)
    error.status = resp.status
    throw error
  }
  if (!resp.body?.getReader) throw new Error("当前浏览器不支持流式故事")
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ""
      for (const frame of frames) {
        let event = "message"
        let id = null
        const data = []
        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith(":")) continue
          if (line.startsWith("event:")) event = line.slice(6).trim()
          else if (line.startsWith("id:")) id = line.slice(3).trim()
          else if (line.startsWith("data:")) data.push(line.slice(5).trimStart())
        }
        if (!data.length) continue
        let payload = data.join("\n")
        try { payload = JSON.parse(payload) } catch {}
        yield { event, id, data: payload }
      }
      if (done) break
    }
  } finally {
    reader.releaseLock?.()
  }
}

// ============================================================
// API 对象
// ============================================================

const api = {
  setAccessToken: _setAccessToken,
  clearAccessToken: _clearAccessToken,
  reportFrontendError,
  auth: {
    async config() {
      const config = await request("/auth/config", { cache: "no-store" })
      _authMode = config.auth_mode || "local"
      return config
    },
    me: () => request("/auth/me", {
      cache: "no-store",
      _suppressAccountInvalidation: true,
    }),
    requestEmailCode: (email) =>
      post("/auth/email/request-code", { email }, { cache: "no-store" }),
    verifyEmail: (payload) =>
      post("/auth/email/verify", payload, { cache: "no-store" }),
    requestReauthEmailCode: (email) =>
      post("/auth/reauth/email/request-code", { email }, { cache: "no-store" }),
    verifyReauthEmail: (payload) =>
      post("/auth/reauth/email/verify", payload, { cache: "no-store" }),
    logout: () => post("/auth/logout", undefined, {
      cache: "no-store",
      _suppressAccountInvalidation: true,
    }),
    deletion: () => request("/account/deletion", { cache: "no-store" }),
    requestDeletion: () =>
      post("/account/deletion", undefined, { cache: "no-store" }),
    cancelDeletion: () =>
      request("/account/deletion", { method: "DELETE", cache: "no-store" }),
    wechatStartUrl(config, purpose = "login") {
      const host = API_BASE_URL.slice(0, -4)
      if (purpose === "reauth") return `${host}/api/auth/reauth/wechat/start`
      const query = buildQueryString({ accept_terms: true, accept_privacy: true })
      return `${host}/api/auth/wechat/start${query}`
    },
  },

  // ============================================================
  // 项目
  // ============================================================
  projects: {
    async list() {
      return contractFetch("projects.list")
    },

    async create(payload) {
      return contractJson("projects.create", {}, {}, payload)
    },

    async get(id, options = {}) {
      return contractFetch("projects.get", { id }, {}, options)
    },

    async getWorkspaceSummary(id, options = {}) {
      return contractFetch("projects.getWorkspaceSummary", { id }, {}, options)
    },

    async update(id, payload) {
      return contractJson("projects.update", { id }, {}, payload)
    },

    async remove(id) {
      return deleteRequest(`/projects/${id}`)
    },
    async listDeleted(skip = 0, limit = 20) {
      return request(withQuery("/projects/recycle-bin", { skip, limit }))
    },
    async restore(id) {
      return post(`/projects/${id}/restore`)
    },
    async permanentDelete(id) {
      return deleteRequest(withQuery(`/projects/${id}/permanent`, { confirmed: true }))
    },
    async permanentDeleteMany(projectIds) {
      return post("/projects/recycle-bin/permanent-delete", {
        project_ids: projectIds,
        confirmed: true,
      })
    },
    async listLlmProviderTemplates() {
      return request("/projects/llm/provider-templates")
    },
    async getLlmSettings(id) {
      return contractFetch("projects.getLlmSettings", { id })
    },
    async updateLlmSettings(id, payload) {
      return contractJson("projects.updateLlmSettings", { id }, {}, payload)
    },
    async startSmartDedupScan(id, payload = {}) {
      return post(`/projects/${id}/smart-dedup/scan`, payload)
    },
    async applySmartDedup(id, payload) {
      return post(`/projects/${id}/smart-dedup/apply`, payload)
    },
  },

  interactions: {
    listJourneys(params = {}) {
      return contractFetch("interactions.listJourneys", {}, params, {
        cache: "no-store",
      })
    },
    createJourney(payload) {
      return contractJson("interactions.createJourney", {}, {}, payload)
    },
    getJourney(journeyId, options = {}) {
      return contractFetch(
        "interactions.getJourney",
        { journeyId },
        {},
        { cache: "no-store", ...options },
      )
    },
    getMessages(journeyId, params = {}) {
      return contractFetch(
        "interactions.getMessages",
        { journeyId },
        params,
        { cache: "no-store" },
      )
    },
    getPathIndex(journeyId) {
      return contractFetch(
        "interactions.getPathIndex",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    sendMessage(journeyId, payload) {
      return contractJson(
        "interactions.sendMessage",
        { journeyId },
        {},
        payload,
      )
    },
    continueFromNode(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.continueFromNode",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    regenerate(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.regenerate",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    editUserMessage(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.editUserMessage",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    selectBranch(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.selectBranch",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    listBranches(journeyId, nodeId) {
      return contractFetch(
        "interactions.listBranches",
        { journeyId, nodeId },
        {},
        { cache: "no-store" },
      )
    },
    getTree(journeyId) {
      return contractFetch(
        "interactions.getTree",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    getAttempt(journeyId, attemptId) {
      return contractFetch(
        "interactions.getAttempt",
        { journeyId, attemptId },
        {},
        { cache: "no-store" },
      )
    },
    streamAttempt(journeyId, attemptId, offset = 0, options = {}) {
      return streamSse(contractPath(
        "interactions.streamAttempt",
        { journeyId, attemptId },
        { offset },
      ), options)
    },
    stopAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.stopAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    keepAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.keepAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    continueAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.continueAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    retryAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.retryAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    updateModes(journeyId, payload) {
      return contractJson(
        "interactions.updateModes",
        { journeyId },
        {},
        payload,
      )
    },
    heartbeat(journeyId) {
      return contractFetch(
        "interactions.heartbeat",
        { journeyId },
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    leaveJourney(journeyId) {
      return contractFetch(
        "interactions.leaveJourney",
        { journeyId },
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    updateTitle(journeyId, payload) {
      return contractJson(
        "interactions.updateTitle",
        { journeyId },
        {},
        payload,
      )
    },
    getOverview(journeyId) {
      return contractFetch(
        "interactions.getOverview",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    updateOverview(journeyId, payload) {
      return contractJson(
        "interactions.updateOverview",
        { journeyId },
        {},
        payload,
      )
    },
    retryOverview(journeyId) {
      return contractFetch(
        "interactions.retryOverview",
        { journeyId },
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    listGenerationRecords(journeyId) {
      return contractFetch(
        "interactions.listGenerationRecords",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    archiveJourney(journeyId) {
      return contractJson(
        "interactions.archiveJourney",
        { journeyId },
        {},
        { confirmed: true },
      )
    },
    getPreferences() {
      return contractFetch(
        "interactions.getPreferences",
        {},
        {},
        { cache: "no-store" },
      )
    },
    acknowledgeSeeSeaNotice() {
      return contractFetch(
        "interactions.acknowledgeSeeSeaNotice",
        {},
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    restoreJourney(journeyId) {
      return contractFetch(
        "interactions.restoreJourney",
        { journeyId },
        {},
        { method: "POST" },
      )
    },
    deleteJourney(journeyId, titleConfirmation) {
      return contractJson(
        "interactions.deleteJourney",
        { journeyId },
        {},
        { title_confirmation: titleConfirmation },
      )
    },
    exportJourney(journeyId, params = {}) {
      return contractFetch(
        "interactions.exportJourney",
        { journeyId },
        params,
        { cache: "no-store" },
      )
    },
  },

  memory: {
    async getSceneCheckpoints(novelId, sceneId) {
      return request(withQuery(`/novels/${novelId}/memories/scene-checkpoints`, {
        scene_id: sceneId,
      }))
    },
    async ensureSceneCheckpoints(novelId, sceneId) {
      return post(`/novels/${novelId}/memories/scene-checkpoints/ensure`, {
        scene_id: sceneId,
      })
    },
    async repairSceneCheckpoint(novelId, payload) {
      return post(`/novels/${novelId}/memories/scene-checkpoints/repair`, payload)
    },
  },

  // ============================================================
  // 世界对象
  // ============================================================
  world: {
    async listEntities(params = {}) {
      return contractFetch("world.listEntities", {}, params)
    },

    async getReviewTypeCatalog() {
      return contractFetch("world.getReviewTypeCatalog")
    },

    async listRelationReviewGroups(params = {}) {
      return contractFetch("world.listRelationReviewGroups", {}, params)
    },

    async reviewRelationsBatch(payload, novelId) {
      return contractJson("world.reviewRelationsBatch", {}, { novel_id: novelId }, payload)
    },

    async listAliasReviewGroups(params = {}) {
      return contractFetch("world.listAliasReviewGroups", {}, params)
    },

    async reviewAliasesBatch(payload, novelId) {
      return contractJson("world.reviewAliasesBatch", {}, { novel_id: novelId }, payload)
    },

    async listEntityTypes(novelId) {
      return request(withQuery("/world/entity-types", { novel_id: novelId }))
    },

    async listCharacters(params = {}) {
      return request(withQuery("/world/characters", params))
    },

    async getEntity(id, novelId) {
      return contractFetch("world.getEntity", { id }, { novel_id: novelId })
    },

    async listProfiles(params = {}) {
      return request(withQuery("/world/profiles", params))
    },

    async getProfile(entityId, novelId) {
      return request(withQuery(`/world/profiles/${entityId}`, { novel_id: novelId }))
    },

    async upsertProfile(entityId, payload, novelId) {
      return put(withQuery(`/world/profiles/${entityId}`, { novel_id: novelId }), payload)
    },

    async migrateGenericProfile(entityId, novelId) {
      return post(withQuery(`/world/profiles/${entityId}/migrate-generic`, { novel_id: novelId }))
    },

    async listBiblePages(params = {}) {
      return request(withQuery("/world/bible/pages", params))
    },

    async createBiblePage(payload) {
      return post("/world/bible/pages", payload)
    },

    async getBiblePage(pageId, novelId) {
      return request(withQuery(`/world/bible/pages/${pageId}`, { novel_id: novelId }))
    },

    async updateBiblePage(pageId, payload, novelId) {
      return patch(withQuery(`/world/bible/pages/${pageId}`, { novel_id: novelId }), payload)
    },

    async listBibleCategories(novelId, includeArchived = false) {
      return request(withQuery("/world/bible/categories", {
        novel_id: novelId,
        include_archived: includeArchived,
      }))
    },

    async createBibleCategory(payload) {
      return post("/world/bible/categories", payload)
    },

    async updateBibleCategory(categoryId, payload, novelId) {
      return patch(withQuery(`/world/bible/categories/${categoryId}`, { novel_id: novelId }), payload)
    },

    async listBibleDrafts(novelId) {
      return request(withQuery("/world/bible/drafts", { novel_id: novelId }))
    },

    async createBibleDraft(payload) {
      return post("/world/bible/drafts", payload)
    },

    async updateBibleDraft(draftId, payload, novelId) {
      return patch(withQuery(`/world/bible/drafts/${draftId}`, { novel_id: novelId }), payload)
    },

    async discardBibleDraft(draftId, novelId) {
      return deleteRequest(withQuery(`/world/bible/drafts/${draftId}`, {
        novel_id: novelId,
        confirmed: true,
      }))
    },

    async previewBibleDraftPublishImpact(draftId, novelId) {
      return request(withQuery(`/world/bible/drafts/${draftId}/publish-impact`, { novel_id: novelId }))
    },

    async publishBibleDraft(draftId, novelId, expectedImpactScopeHash = null) {
      return post(withQuery(`/world/bible/drafts/${draftId}/publish`, {
        novel_id: novelId,
        expected_impact_scope_hash: expectedImpactScopeHash || undefined,
      }))
    },

    async listBiblePageRevisions(pageId, novelId) {
      return request(withQuery(`/world/bible/pages/${pageId}/revisions`, { novel_id: novelId }))
    },

    async restoreBiblePageRevision(pageId, version, novelId) {
      return post(withQuery(`/world/bible/pages/${pageId}/revisions/${version}/restore-draft`, {
        novel_id: novelId,
      }))
    },

    async getBibleSynopsis(novelId) {
      return request(withQuery("/world/bible/synopsis", { novel_id: novelId }))
    },

    async refreshBibleSynopsis(novelId) {
      return post(withQuery("/world/bible/synopsis/refresh", { novel_id: novelId }))
    },

    async setBibleSynopsisAutoRefresh(novelId, enabled) {
      return patch(withQuery("/world/bible/synopsis/auto-refresh", { novel_id: novelId }), { enabled })
    },

    async listBibleSynopsisRevisions(novelId) {
      return request(withQuery("/world/bible/synopsis/revisions", { novel_id: novelId }))
    },

    async restoreBibleSynopsisRevision(revisionId, novelId) {
      return post(withQuery(`/world/bible/synopsis/revisions/${revisionId}/restore`, { novel_id: novelId }))
    },

    async unpinBibleSynopsis(novelId) {
      return post(withQuery("/world/bible/synopsis/unpin", { novel_id: novelId }))
    },

    async listBibleTemplates() {
      return request("/world/bible/templates")
    },

    async listBiblePageTemplates(novelId, includeArchived = false) {
      return request(withQuery("/world/bible/page-templates", {
        novel_id: novelId,
        include_archived: includeArchived,
      }))
    },

    async createBiblePageTemplate(payload) {
      return post("/world/bible/page-templates", payload)
    },

    async updateBiblePageTemplate(templateId, payload, novelId) {
      return patch(withQuery(`/world/bible/page-templates/${templateId}`, {
        novel_id: novelId,
      }), payload)
    },

    async listBiblePageTemplateRevisions(templateId, novelId) {
      return request(withQuery(`/world/bible/page-templates/${templateId}/revisions`, {
        novel_id: novelId,
      }))
    },

    async restoreBiblePageTemplateRevision(templateId, version, novelId) {
      return post(withQuery(
        `/world/bible/page-templates/${templateId}/revisions/${version}/restore-draft`,
        { novel_id: novelId },
      ))
    },

    async applyBiblePageTemplate(draftId, payload, novelId) {
      return post(withQuery(`/world/bible/drafts/${draftId}/apply-template`, {
        novel_id: novelId,
      }), payload)
    },

    async refreshBibleProjection(pageId, novelId, projectionType = "context_brief", force = false) {
      return post(withQuery(`/world/bible/pages/${pageId}/refresh-projection`, {
        novel_id: novelId,
        projection_type: projectionType,
        force,
      }))
    },

    async organizeBiblePage(pageId, novelId) {
      return post(withQuery(`/world/bible/pages/${pageId}/organize`, { novel_id: novelId }))
    },

    async listSuggestions(params = {}) {
      return request(withQuery("/world/suggestions", params))
    },

    async confirmSuggestion(suggestionId, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/confirm`, { novel_id: novelId }))
    },

    async editAndConfirmSuggestion(suggestionId, payload, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/edit-confirm`, { novel_id: novelId }), payload)
    },

    async mergeSuggestion(suggestionId, targetEntityId, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/merge`, { novel_id: novelId }), { target_entity_id: targetEntityId })
    },

    async resolveSuggestionAsAlias(suggestionId, payload, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/resolve-as-alias`, { novel_id: novelId }), payload)
    },

    async rejectSuggestion(suggestionId, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/reject`, { novel_id: novelId }))
    },

    async listWorldConflicts(params = {}) {
      return request(withQuery("/world/conflicts", params))
    },

    async resolveWorldConflict(conflictId, payload, novelId) {
      return post(withQuery(`/world/conflicts/${conflictId}/resolve`, { novel_id: novelId }), payload)
    },

    async createEntity(payload, novelId) {
      return contractJson("world.createEntity", {}, { novel_id: novelId }, payload)
    },

    async updateEntity(id, payload, novelId) {
      return contractJson("world.updateEntity", { id }, { novel_id: novelId }, payload)
    },

    async promoteEntity(id, novelId, payload = {}) {
      return post(withQuery(`/world/entities/${id}/promote`, { novel_id: novelId }), payload)
    },

    async extractAliasRelations(payload) {
      return post("/world/alias-relations/extract", payload)
    },

    async deleteEntity(id, novelId) {
      return contractFetch("world.deleteEntity", { id }, { novel_id: novelId })
    },

    async listEntityBatches(params = {}) {
      return request(withQuery("/world/entity-batches", params))
    },

    async listRelationships(params = {}) {
      return request(withQuery("/world/relations", params))
    },

    async createRelationship(payload, novelId) {
      return post(withQuery("/world/relations", { novel_id: novelId }), payload)
    },

    async updateRelationship(id, payload, novelId) {
      return put(withQuery(`/world/relations/${id}`, { novel_id: novelId }), payload)
    },

    async reviewEditRelationship(id, payload, novelId) {
      return patch(withQuery(`/world/relations/${id}/review-edit`, { novel_id: novelId }), payload)
    },

    async deleteRelationship(id, params = {}) {
      return deleteRequest(withQuery(`/world/relations/${id}`, params))
    },

    async listAliases(params = {}) {
      return request(withQuery("/world/aliases", params))
    },

    async createAlias(payload, novelId) {
      return post(withQuery("/world/aliases", { novel_id: novelId }), payload)
    },

    async updateAlias(entityId, alias, payload, params = {}) {
      params.alias = alias
      return patch(withQuery(`/world/entities/${entityId}/aliases`, params), payload)
    },

    async editAlias(entityId, alias, payload, params = {}) {
      params.alias = alias
      return patch(withQuery(`/world/entities/${entityId}/aliases/edit`, params), payload)
    },

    async deleteAlias(entityId, alias, params = {}) {
      params.alias = alias
      return deleteRequest(withQuery(`/world/entities/${entityId}/aliases`, params))
    },

    async mergeEntity(candidateId, targetEntityId, novelId) {
      return post(withQuery(`/world/entities/${candidateId}/merge`, { novel_id: novelId }), { target_entity_id: targetEntityId })
    },

    async resolveEntityAsAlias(candidateId, payload, novelId) {
      return post(withQuery(`/world/entities/${candidateId}/resolve-as-alias`, { novel_id: novelId }), payload)
    },

    async createEntityFusionSuggestions(data) {
      return post("/world/entities/fusion-suggestions", data)
    },

    async applyEntityFusionSuggestions(data) {
      return post("/world/entities/fusion-suggestions/apply", data)
    },

    async rollbackEntity(entityId, targetSceneIndex, novelId) {
      return post(withQuery(`/world/entities/${entityId}/rollback`, { novel_id: novelId }), { target_scene_index: targetSceneIndex })
    },

    async listKnowledge(characterId, novelId) {
      return request(withQuery(`/world/characters/${characterId}/knowledge`, { novel_id: novelId }))
    },

    async createKnowledge(characterId, payload, novelId) {
      return post(withQuery(`/world/characters/${characterId}/knowledge`, { novel_id: novelId }), payload)
    },

    async updateKnowledge(knowledgeId, payload, novelId) {
      return put(withQuery(`/world/knowledge/${knowledgeId}`, { novel_id: novelId }), payload)
    },

    // ============================================================
    // 动态地图（PRD §6，/api/world/maps）
    // ============================================================

    async listMaps(params = {}) {
      return contractFetch("world.listMaps", {}, params)
    },
    async getMap(mapId, novelId) {
      return request(withQuery(`/world/maps/${mapId}`, { novel_id: novelId }))
    },
    async createMap(payload, novelId) {
      return post(withQuery("/world/maps", { novel_id: novelId }), payload)
    },
    async updateMap(mapId, payload, novelId) {
      return patch(withQuery(`/world/maps/${mapId}`, { novel_id: novelId }), payload)
    },
    async deleteMap(mapId, novelId) {
      return deleteRequest(withQuery(`/world/maps/${mapId}`, { novel_id: novelId }))
    },
    async getMapArchiveImpact(mapId, novelId) {
      return contractFetch("world.getMapArchiveImpact", { mapId }, { novel_id: novelId })
    },
    async archiveMap(mapId, novelId) {
      return contractJson("world.archiveMap", { mapId }, { novel_id: novelId })
    },
    async restoreMap(mapId, payload, novelId) {
      return contractJson("world.restoreMap", { mapId }, { novel_id: novelId }, payload || {})
    },
    async applyMapEditor(mapId, payload, novelId) {
      return contractJson("world.applyMapEditor", { mapId }, { novel_id: novelId }, payload)
    },
    async listMapVisualRevisions(mapId, novelId, { skip = 0, limit = 50 } = {}) {
      return request(withQuery(`/world/maps/${mapId}/revisions`, {
        novel_id: novelId,
        skip,
        limit,
      }))
    },
    async restoreMapVisualRevision(mapId, revisionNumber, expectedRevision, novelId) {
      return post(
        withQuery(`/world/maps/${mapId}/revisions/${revisionNumber}/restore`, {
          novel_id: novelId,
        }),
        { expected_revision: expectedRevision },
      )
    },
    async getMapLayerTree(mapId, novelId) {
      return contractFetch("world.getMapLayerTree", { mapId }, { novel_id: novelId })
    },
    async getMapPaths(mapId, novelId, status = "active") {
      return contractFetch("world.getMapPaths", { mapId }, {
        novel_id: novelId,
        status,
      })
    },
    async getMapPathArchiveImpact(mapId, pathId, novelId) {
      return contractFetch("world.getMapPathArchiveImpact", { mapId, pathId }, {
        novel_id: novelId,
      })
    },
    async getEntityMapPresence(entityId, novelId, includeCandidates = false) {
      return contractFetch("world.getEntityMapPresence", { id: entityId }, {
        novel_id: novelId,
        include_candidates: includeCandidates || undefined,
      })
    },
    async generateMap(mapId, novelId) {
      return post(withQuery(`/world/maps/${mapId}/generate`, { novel_id: novelId }))
    },
    async getMapState(mapId, novelId, sceneId = null) {
      const params = { novel_id: novelId }
      if (sceneId) params.scene_id = sceneId
      return contractFetch("world.getMapState", { mapId }, params)
    },
    async getMapDynamicState(mapId, novelId, sceneId = null) {
      const params = { novel_id: novelId }
      if (sceneId) params.scene_id = sceneId
      return request(withQuery(`/world/maps/${mapId}/state/dynamic`, params))
    },
    async getMapDashboard(mapId, novelId, sceneId = null, focusEntityId = null, focusItemId = null) {
      const params = {
        novel_id: novelId,
        scene_id: sceneId,
        focus_entity_id: focusEntityId,
        focus_item_id: focusItemId,
      }
      return contractFetch("world.getMapDashboard", { mapId }, params)
    },
    async getMapPlayback(mapId, novelId, sceneId = null, focusEntityId = null, includeCandidates = true) {
      const params = {
        novel_id: novelId,
        scene_id: sceneId,
        focus_entity_id: focusEntityId,
        include_candidates: includeCandidates,
      }
      return contractFetch("world.getMapPlayback", { mapId }, params)
    },
    async getMapTimeline(mapId, novelId, options = {}) {
      const tracks = Array.isArray(options.tracks)
        ? options.tracks.join(",")
        : options.tracks
      return contractFetch("world.getMapTimeline", { mapId }, {
        novel_id: novelId,
        from_scene_index: options.fromSceneIndex ?? options.from_scene_index,
        to_scene_index: options.toSceneIndex ?? options.to_scene_index,
        focus_entity_id: options.focusEntityId ?? options.focus_entity_id,
        tracks: tracks || undefined,
        include_candidates: options.includeCandidates ?? options.include_candidates ?? undefined,
        skip: options.skip,
        limit: options.limit,
      })
    },
    async getMapStateAt(mapId, novelId, sceneIndex, options = {}) {
      const tracks = Array.isArray(options.tracks)
        ? options.tracks.join(",")
        : options.tracks
      return contractFetch("world.getMapStateAt", { mapId }, {
        novel_id: novelId,
        scene_index: sceneIndex,
        focus_entity_id: options.focusEntityId ?? options.focus_entity_id,
        tracks: tracks || undefined,
        skip: options.skip,
        limit: options.limit,
      })
    },
    async getMapOpenTarget(novelId, { sceneId = null, focusEntityId = null } = {}) {
      return request(withQuery("/world/maps/open-target", {
        novel_id: novelId,
        scene_id: sceneId,
        focus_entity_id: focusEntityId,
      }))
    },
    async getMapSceneSummary(novelId, sceneId) {
      return request(withQuery("/world/maps/scene-summary", {
        novel_id: novelId,
        scene_id: sceneId,
      }))
    },
    async getMapQuickCreateContext(novelId, includeCandidates = false) {
      return request(withQuery("/world/maps/quick-create/context", {
        novel_id: novelId,
        include_candidates: includeCandidates,
      }))
    },
    async previewQuickCreateMap(payload, novelId) {
      return contractJson("world.previewQuickCreateMap", {}, { novel_id: novelId }, payload)
    },
    async confirmQuickCreateMap(payload, novelId) {
      return contractJson("world.confirmQuickCreateMap", {}, { novel_id: novelId }, payload)
    },
    async listLocationLayouts(mapId, novelId) {
      return request(withQuery(`/world/maps/${mapId}/location-layouts`, { novel_id: novelId }))
    },
    async replaceLocationLayouts(mapId, payload, novelId) {
      return contractJson("world.replaceLocationLayouts", { mapId }, { novel_id: novelId }, payload)
    },
    async getMapTerrain(mapId, novelId, includeCandidates = false) {
      return request(withQuery(`/world/maps/${mapId}/terrain`, {
        novel_id: novelId,
        include_candidates: includeCandidates || undefined,
      }))
    },
    async replaceTerrainLayerPatches(mapId, layerId, payload, novelId) {
      return contractJson("world.replaceTerrainLayerPatches", { mapId, layerId }, { novel_id: novelId }, payload)
    },
    async updateTerrainLayer(mapId, layerId, payload, novelId) {
      return contractJson("world.updateTerrainLayer", { mapId, layerId }, { novel_id: novelId }, payload)
    },
    async deleteTerrainLayer(mapId, layerId, novelId) {
      return contractFetch("world.deleteTerrainLayer", { mapId, layerId }, { novel_id: novelId })
    },
    async createTerrainBinding(mapId, regionId, payload, novelId) {
      return post(withQuery(`/world/maps/${mapId}/terrain/regions/${regionId}/bindings`, { novel_id: novelId }), payload)
    },
    async updateTerrainBinding(mapId, bindingId, payload, novelId) {
      return patch(withQuery(`/world/maps/${mapId}/terrain/bindings/${bindingId}`, { novel_id: novelId }), payload)
    },
    async batchUpdateTiles(mapId, payload, novelId) {
      return patch(withQuery(`/world/maps/${mapId}/tiles`, { novel_id: novelId }), payload)
    },
    async createLocationBindings(mapId, payload, novelId) {
      return post(withQuery(`/world/maps/${mapId}/location-bindings`, { novel_id: novelId }), payload)
    },
    async updateLocationBinding(mapId, bindingId, payload, novelId) {
      return patch(withQuery(`/world/maps/${mapId}/location-bindings/${bindingId}`, { novel_id: novelId }), payload)
    },
    async deleteLocationBinding(mapId, bindingId, novelId) {
      return deleteRequest(withQuery(`/world/maps/${mapId}/location-bindings/${bindingId}`, { novel_id: novelId }))
    },
    async listMapMarkers(mapId, novelId, sceneId = null) {
      const params = { novel_id: novelId }
      if (sceneId) params.scene_id = sceneId
      return request(withQuery(`/world/maps/${mapId}/markers`, params))
    },
    async createMapMarker(mapId, data, novelId) {
      return post(withQuery(`/world/maps/${mapId}/markers`, { novel_id: novelId }), data)
    },
    async updateMapMarker(mapId, markerId, data, novelId) {
      return patch(withQuery(`/world/maps/${mapId}/markers/${markerId}`, { novel_id: novelId }), data)
    },
    async deleteMapMarker(mapId, markerId, novelId) {
      return deleteRequest(withQuery(`/world/maps/${mapId}/markers/${markerId}`, { novel_id: novelId }))
    },
    async getFocusState(mapId, factionEntityId, novelId) {
      return request(withQuery(`/world/maps/${mapId}/focus`, { novel_id: novelId, faction_entity_id: factionEntityId }))
    },
    async createTerritories(mapId, payload, novelId) {
      return post(withQuery(`/world/maps/${mapId}/territories`, { novel_id: novelId }), payload)
    },
    async deleteTerritoriesByFaction(mapId, factionEntityId, novelId) {
      return deleteRequest(withQuery(`/world/maps/${mapId}/territories`, { novel_id: novelId, faction_entity_id: factionEntityId }))
    },
    async deleteMapTerritory(mapId, territoryId, novelId) {
      return deleteRequest(withQuery(`/world/maps/${mapId}/territories/${territoryId}`, { novel_id: novelId }))
    },
    async listMapObservations(mapId, novelId, reviewState = null) {
      return contractFetch("world.listMapObservations", { mapId }, { novel_id: novelId, review_state: reviewState })
    },
    async listProjectMapObservationInbox(novelId, filters = {}) {
      return contractFetch("world.listProjectMapObservationInbox", {}, {
        novel_id: novelId,
        dynamic_type: filters.dynamicType || null,
        scene_id: filters.sceneId || null,
        source: filters.source || null,
        confidence: filters.confidence || null,
        eligibility: filters.eligibility || null,
        skip: filters.skip || 0,
        limit: filters.limit || 100,
      })
    },
    async updateProjectMapObservation(observationId, novelId, payload) {
      return contractJson(
        "world.updateProjectMapObservation",
        { observationId },
        { novel_id: novelId },
        payload,
      )
    },
    async assignProjectMapObservation(observationId, novelId, mapId, expectedUpdatedAt) {
      return contractJson(
        "world.assignProjectMapObservation",
        { observationId },
        { novel_id: novelId },
        { map_id: mapId || null, expected_updated_at: expectedUpdatedAt },
      )
    },
    async ignoreProjectMapObservation(observationId, novelId, expectedUpdatedAt) {
      return contractJson(
        "world.ignoreProjectMapObservation",
        { observationId },
        { novel_id: novelId },
        { expected_updated_at: expectedUpdatedAt },
      )
    },
    async createMapObservation(mapId, payload, novelId) {
      return post(withQuery(`/world/maps/${mapId}/observations`, { novel_id: novelId }), payload)
    },
    async updateMapObservationReview(mapId, observationId, novelId, reviewState) {
      const payload = reviewState && typeof reviewState === "object"
        ? reviewState
        : { review_state: reviewState }
      return patch(withQuery(`/world/maps/${mapId}/observations/${observationId}`, { novel_id: novelId }), payload)
    },
    async batchReviewMapObservations(mapId, observationItems, action, novelId) {
      return post(withQuery(`/world/maps/${mapId}/observations/batch-review`, { novel_id: novelId }), { items: observationItems, action })
    },
    async runMapBatchAction(mapId, novelId, payload) {
      return post(withQuery(`/world/maps/${mapId}/batch-actions`, { novel_id: novelId }), payload)
    },
    async confirmMapObservation(mapId, observationId, novelId, expectedUpdatedAt) {
      return contractJson(
        "world.confirmMapObservation",
        { mapId, observationId },
        { novel_id: novelId },
        { expected_updated_at: expectedUpdatedAt },
      )
    },
    async ignoreMapObservation(mapId, observationId, novelId, expectedUpdatedAt) {
      return post(
        withQuery(`/world/maps/${mapId}/observations/${observationId}/ignore`, { novel_id: novelId }),
        { expected_updated_at: expectedUpdatedAt },
      )
    },
    async listMapFacts(mapId, novelId, factStatus = "confirmed") {
      return request(withQuery(`/world/maps/${mapId}/facts`, { novel_id: novelId, fact_status: factStatus }))
    },
    async updateMapFactStatus(mapId, factId, novelId, factStatus) {
      return contractJson("world.updateMapFactStatus", { mapId, factId }, { novel_id: novelId }, { fact_status: factStatus })
    },
  },

  // ============================================================
  // 世界对象（含人物，人物 API 已迁入 /api/world/characters）
  // ============================================================

  // ============================================================
  // RAG 检索
  // ============================================================
  rag: {
    async search(payload, novelId, options = {}) {
      return contractJson("rag.search", {}, { novel_id: novelId }, payload, options)
    },

    async rebuild(payload, options = {}) {
      const { novel_id, content_mode, start_chapter, end_chapter } = payload || {}
      if (!novel_id) throw new Error("重建索引需要先选择项目")
      return post("/rag/rebuild", { novel_id, content_mode, start_chapter, end_chapter }, options)
    },

    async prewarm(options = {}) {
      return contractJson("rag.prewarm", {}, {}, {}, options)
    },

    async retryEmbeddings(payload, options = {}) {
      const { novel_id, start_chapter, end_chapter, statuses } = payload || {}
      if (!novel_id) throw new Error("重试失败向量需要先选择项目")
      return post("/rag/retry-embeddings", { novel_id, start_chapter, end_chapter, statuses }, options)
    },

    async status(projectId) {
      return request(withQuery("/rag/chunks", { novel_id: projectId }))
    },

    async metrics() {
      return request("/rag/metrics")
    },
  },

  // ============================================================
  // 上下文
  // ============================================================
  context: {
    async grepEvidence(payload, options = {}) {
      return contractJson("context.grepEvidence", {}, {}, payload, options)
    },

    async searchEvidence(payload, options = {}) {
      return contractJson("context.searchEvidence", {}, {}, payload, options)
    },

    async readEvidence(payload, options = {}) {
      return contractJson("context.readEvidence", {}, {}, payload, options)
    },

    async inspectEvidence(payload, options = {}) {
      return post("/context/evidence/inspect", payload, options)
    },

    async traceEvidence(payload, options = {}) {
      return post("/context/evidence/trace", payload, options)
    },

    async compile(payload, options = {}) {
      return contractJson("context.compile", {}, {}, payload, options)
    },

    async render(payload, options = {}) {
      return contractJson("context.render", {}, {}, payload, options)
    },

    async confirm(payload) {
      return contractJson("context.confirm", {}, {}, payload)
    },

    async listSnapshots(params = {}) {
      return contractFetch("context.listSnapshots", {}, params)
    },

    async getSnapshot(snapshotId, params = {}) {
      return contractFetch("context.getSnapshot", { snapshotId }, params)
    },

    async activationPreview(params = {}) {
      return contractFetch("context.activationPreview", {}, params)
    },

    async previewActivationProfile(payload) {
      return post("/context/activation-preview", payload)
    },

    async listActivationProfiles(novelId, includeArchived = false) {
      return request(withQuery("/context/activation-profiles", {
        novel_id: novelId,
        include_archived: includeArchived,
      }))
    },

    async createActivationProfile(payload) {
      return post("/context/activation-profiles", payload)
    },

    async updateActivationProfile(profileId, payload, novelId) {
      return patch(withQuery(`/context/activation-profiles/${profileId}`, {
        novel_id: novelId,
      }), payload)
    },

    async publishActivationProfile(profileId, payload, novelId) {
      return post(withQuery(`/context/activation-profiles/${profileId}/publish`, {
        novel_id: novelId,
      }), payload)
    },

    async listActivationProfileRevisions(profileId, novelId) {
      return request(withQuery(`/context/activation-profiles/${profileId}/revisions`, {
        novel_id: novelId,
      }))
    },

    async restoreActivationProfileRevision(profileId, version, payload, novelId) {
      return post(withQuery(
        `/context/activation-profiles/${profileId}/revisions/${version}/restore-draft`,
        { novel_id: novelId },
      ), payload)
    },

    async evidenceHealth(novelId, contentMode = "canonical", windowHours = 24) {
      return contractFetch("context.evidenceHealth", {}, {
        novel_id: novelId,
        content_mode: contentMode,
        window_hours: windowHours,
      })
    },

    async listRetrievalTraces(novelId, params = {}) {
      return contractFetch("context.listRetrievalTraces", {}, {
        novel_id: novelId,
        ...params,
      })
    },
  },

  // ============================================================
  // 草稿
  // ============================================================
  writing: {
    async publish(payload) {
      return contractJson("writing.publish", {}, {}, payload)
    },

    async autosave(draftId, payload, novelId) {
      return contractJson("writing.autosave", { draftId }, { novel_id: novelId }, payload)
    },

    async checkpoint(draftId, payload, novelId) {
      return contractJson("writing.checkpoint", { draftId }, { novel_id: novelId }, payload)
    },

    async discard(draftId, novelId, expected = {}) {
      return contractJson("writing.discard", { draftId }, {
        novel_id: novelId,
        expected_version: expected.expected_version,
        expected_updated_at: expected.expected_updated_at,
      })
    },

    async adoptDraftCandidate(draftId, novelId) {
      return contractJson("writing.adoptDraftCandidate", { draftId }, { novel_id: novelId })
    },

    async autosaveDraftOnly(payload) {
      return post("/writing/drafts/autosave", payload)
    },

    async getDraft(chapterIndex, novelId) {
      return contractFetch("writing.getDraft", { chapterIndex }, { novel_id: novelId })
    },

    async get(draftId, novelId) {
      return request(withQuery(`/writing/drafts/${draftId}`, { novel_id: novelId }))
    },

    async deleteDraft(draftId, novelId) {
      return deleteRequest(withQuery(`/writing/drafts/${draftId}`, { novel_id: novelId }))
    },

    async deleteChapter(chapterIndex, novelId) {
      return deleteRequest(withQuery(`/writing/chapters/${chapterIndex}`, { novel_id: novelId }))
    },

    async listChapters(novelId) {
      return request(withQuery("/writing/chapters", { novel_id: novelId }))
    },

    async getVersionHistory(chapterIndex, novelId) {
      return request(withQuery(`/writing/chapters/${chapterIndex}/versions`, { novel_id: novelId }))
    },

    async generate(payload) {
      return contractJson("writing.generate", {}, {}, payload)
    },

    async createConflictCheck(payload) {
      return contractJson("writing.createConflictCheck", {}, {}, payload)
    },

    async listConflictChecks(params = {}) {
      return request(withQuery("/writing/conflict-checks", params))
    },

    async getConflictCheck(checkId, novelId) {
      return request(withQuery(`/writing/conflict-checks/${checkId}`, { novel_id: novelId }))
    },

    async updateConflictItem(itemId, novelId, payload) {
      return patch(withQuery(`/writing/conflict-check-items/${itemId}`, { novel_id: novelId }), payload)
    },

    async runConflictAiReview(checkId, payload) {
      return contractJson("writing.runConflictAiReview", { checkId }, {}, payload)
    },

    async enqueueConflictAiReview(checkId, payload) {
      return contractJson("writing.enqueueConflictAiReview", { checkId }, {}, payload)
    },

    async requestConflictAiSuggestion(itemId, payload) {
      return contractJson(
        "writing.requestConflictAiSuggestion",
        { itemId },
        {},
        payload,
      )
    },
  },

  // ============================================================
  // 生成中心
  // ============================================================
  generate: {
    async listPromptTemplates(novelId, options = {}) {
      return request(withQuery("/world/generation-prompt-templates", {
        novel_id: novelId,
        include_archived: options.include_archived || false,
      }))
    },

    async createPromptTemplate(payload) {
      return post("/world/generation-prompt-templates", payload)
    },

    async updatePromptTemplate(templateId, novelId, payload) {
      return put(withQuery(`/world/generation-prompt-templates/${templateId}`, { novel_id: novelId }), payload)
    },

    async archivePromptTemplate(templateId, novelId) {
      return deleteRequest(withQuery(`/world/generation-prompt-templates/${templateId}`, { novel_id: novelId }))
    },

    async copyPromptTemplate(templateId, payload) {
      return post(`/world/generation-prompt-templates/${templateId}/copy`, payload)
    },

    async listPromptTemplateRevisions(templateId, novelId) {
      return contractFetch("generate.listPromptTemplateRevisions", { templateId }, { novel_id: novelId })
    },

    async validatePromptTemplate(payload) {
      return post("/world/generation-prompt-templates/validate", payload)
    },

    async previewPromptTemplate(payload) {
      return post("/world/generation-prompt-templates/preview", payload)
    },

    async worldChat(payload, options = {}) {
      return contractJson("generate.worldChat", {}, {}, payload, options)
    },

    async convergeWorld(payload, options = {}) {
      return contractJson("generate.convergeWorld", {}, {}, payload, options)
    },

    async exploreWorld(payload, options = {}) {
      return contractJson("generate.exploreWorld", {}, {}, payload, options)
    },

    async inspectWorldPage(payload, options = {}) {
      return contractJson("generate.inspectWorldPage", {}, {}, payload, options)
    },

    async askWorld(payload, options = {}) {
      return contractJson("generate.askWorld", {}, {}, payload, options)
    },

    async openAskWorldCitation(payload, options = {}) {
      return contractJson("generate.openAskWorldCitation", {}, {}, payload, options)
    },

    async saveAskWorldSuggestion(payload, options = {}) {
      return contractJson("generate.saveAskWorldSuggestion", {}, {}, payload, options)
    },

    async generateWorldSuggestion(payload, options = {}) {
      return contractJson("generate.generateWorldSuggestion", {}, {}, payload, options)
    },

    async applyWorldPageDraft(suggestionId, payload, novelId, options = {}) {
      return contractJson(
        "generate.applyWorldPageDraft",
        { suggestionId },
        { novel_id: novelId },
        payload,
        options,
      )
    },
  },

  // ============================================================
  // 健康检查
  // ============================================================
  async healthCheck() {
    try {
      // 健康检查必须绕过 GET 缓存，否则短时间内多次检查会命中同一份缓存。
      await request(withQuery("/health", { _ts: Date.now() }))
      return true
    } catch {
      return false
    }
  },

  // ============================================================
  // 导入
  // ============================================================
  imports: {
    async uploadFile(file, novelId, onProgress = null, options = {}) {
      return uploadImportFile(file, novelId, onProgress, options)
    },

    async upload(novelId, file) {
      const formData = new FormData()
      formData.append("novel_id", novelId)
      formData.append("file", file)
      return request("/imports/upload", {
        method: "POST",
        body: formData,
      })
    },

    async list(params = {}) {
      return request(withQuery("/imports", params))
    },

    async get(recordId, params = {}) {
      return request(withQuery(`/imports/${recordId}`, params))
    },

    async deepImport(novelId, startChapter, endChapter, force = false, highQuality = false, authorization = {}) {
      if (authorization.authorization_confirmed !== true) {
        throw new Error("整理导入内容前必须获得用户授权")
      }
      return contractJson("imports.deepImport", {}, {}, {
        novel_id: novelId,
        start_chapter: startChapter,
        end_chapter: endChapter,
        force,
        high_quality: highQuality,
        adoption_policy: authorization.adoption_policy || "user_authorized_pipeline",
        authorization_confirmed: true,
      })
    },

    async startStage(stage, novelId, startChapter, endChapter, force = false, highQuality = false, authorization = {}) {
      if (authorization.authorization_confirmed !== true) {
        throw new Error("启动自动提取前必须获得用户授权")
      }
      return contractJson("imports.startStage", { stage }, {}, {
        novel_id: novelId,
        start_chapter: startChapter,
        end_chapter: endChapter,
        force,
        high_quality: highQuality,
        adoption_policy: authorization.adoption_policy || "user_authorized_pipeline",
        authorization_confirmed: true,
      })
    },

    async startMapObservationEnrichment(novelId, startChapter, endChapter, highQuality = true, authorization = {}) {
      if (authorization.authorization_confirmed !== true) {
        throw new Error("启动地图事实补充前必须获得用户授权")
      }
      return contractJson("imports.startMapObservationEnrichment", {}, {}, {
        novel_id: novelId,
        start_chapter: startChapter,
        end_chapter: endChapter,
        high_quality: highQuality,
        adoption_policy: authorization.adoption_policy || "user_authorized_pipeline",
        authorization_confirmed: true,
      })
    },

    async resumeDeepImport(taskId) {
      return contractJson("imports.resumeDeepImport", {}, {}, { task_id: taskId })
    },

    async abandonDeepImport(taskId) {
      return contractJson("imports.abandonDeepImport", {}, {}, { task_id: taskId })
    },
  },

  // ============================================================
  // 大纲
  // ============================================================
  outline: {
    async getStoryOutline(novelId) {
      return contractFetch("outline.getStoryOutline", {}, { novel_id: novelId })
    },

    async listStoryOutlineRevisions(novelId, skip = 0, limit = 20) {
      return contractFetch(
        "outline.listStoryOutlineRevisions",
        {},
        { novel_id: novelId, skip, limit },
      )
    },

    async getStoryOutlineRevision(revisionId, novelId) {
      return contractFetch(
        "outline.getStoryOutlineRevision",
        { revisionId },
        { novel_id: novelId },
      )
    },

    async createStoryOutlineRevision(novelId, payload) {
      return contractJson(
        "outline.createStoryOutlineRevision",
        {},
        { novel_id: novelId },
        payload,
      )
    },

    async restoreStoryOutlineRevision(revisionId, novelId, payload) {
      return contractJson(
        "outline.restoreStoryOutlineRevision",
        { revisionId },
        { novel_id: novelId },
        payload,
      )
    },

    async generateStoryOutline(payload) {
      return contractJson("outline.generateStoryOutline", {}, {}, payload)
    },

    async applyStoryOutlinePreview(payload) {
      return contractJson("outline.applyStoryOutlinePreview", {}, {}, payload)
    },

    async listThreads(novelId, params = {}) {
      return request(withQuery("/outline/threads", { novel_id: novelId, ...params }))
    },

    async createThread(novelId, data) {
      return post(withQuery("/outline/threads", { novel_id: novelId }), data)
    },

    async updateThread(threadId, novelId, data) {
      return patch(withQuery(`/outline/threads/${threadId}`, { novel_id: novelId }), data)
    },

    async deleteThread(threadId, novelId) {
      return deleteRequest(withQuery(`/outline/threads/${threadId}`, { novel_id: novelId }))
    },

    async listArcs(novelId, params = {}) {
      return request(withQuery("/outline/arcs", { novel_id: novelId, ...params }))
    },

    async createArc(novelId, data) {
      return post(withQuery("/outline/arcs", { novel_id: novelId }), data)
    },
    async updateArc(arcId, novelId, data) {
      return patch(withQuery(`/outline/arcs/${arcId}`, { novel_id: novelId }), data)
    },
    async deleteArc(arcId, novelId) {
      return deleteRequest(withQuery(`/outline/arcs/${arcId}`, { novel_id: novelId }))
    },

    async analyze(payload) {
      return contractJson("outline.analyze", {}, {}, payload)
    },

    async generate(payload) {
      return contractJson("outline.generate", {}, {}, payload)
    },

    async applyStructurePreview(payload) {
      return contractJson("outline.applyStructurePreview", {}, {}, payload)
    },

    // ---- Scene 卡 ----
    async listScenes(novelId, skip = 0, limit = 50) {
      return request(withQuery("/outline/scenes", { novel_id: novelId, skip, limit }))
    },
    async getScene(sceneId, novelId) {
      return request(withQuery(`/outline/scenes/${sceneId}`, { novel_id: novelId }))
    },
    async createScene(novelId, data) {
      return post(withQuery("/outline/scenes", { novel_id: novelId }), data)
    },
    async updateScene(sceneId, novelId, data) {
      return patch(withQuery(`/outline/scenes/${sceneId}`, { novel_id: novelId }), data)
    },
    async deleteScene(sceneId, novelId) {
      return deleteRequest(withQuery(`/outline/scenes/${sceneId}`, { novel_id: novelId }))
    },
    async listScenesOrdered(novelId) {
      return request(withQuery("/outline/scenes/ordered", { novel_id: novelId }))
    },
    async listScenesByChapter(novelId, chapterIndex) {
      return request(withQuery("/outline/scenes/by-chapter", { novel_id: novelId, chapter_index: chapterIndex }))
    },
    async reorderScenes(novelId, sceneIds) {
      return post(withQuery("/outline/scenes/reorder", { novel_id: novelId }), { scene_ids: sceneIds })
    },
    async splitChapters(novelId, chapterIndex, targetSceneId) {
      return post(withQuery("/outline/scenes/split", { novel_id: novelId }), { chapter_index: chapterIndex, target_scene_id: targetSceneId || null })
    },
    async getSceneWorkbench(novelId, selectedSceneId = null, params = {}) {
      return request(withQuery("/outline/scene-workbench", {
        novel_id: novelId,
        selected_scene_id: selectedSceneId,
        ...params,
      }))
    },
    async updateSceneWorkbenchMapping(novelId, sceneId, data) {
      return patch(withQuery(`/outline/scene-workbench/scenes/${sceneId}/mapping`, { novel_id: novelId }), data)
    },
    async reviewSceneWorkbench(novelId, data) {
      return post(withQuery("/outline/scene-workbench/review", { novel_id: novelId }), data)
    },
    async reviewSceneSourceMappings(novelId, data) {
      return post(withQuery("/outline/scene-workbench/source-mapping/review", { novel_id: novelId }), data)
    },
    async previewSceneMerge(novelId, data) {
      return post(withQuery("/outline/scene-workbench/merge/preview", { novel_id: novelId }), data)
    },
    async mergeScenes(novelId, data) {
      return post(withQuery("/outline/scene-workbench/merge", { novel_id: novelId }), data)
    },
    async previewSceneFusion(novelId, data) {
      return contractJson(
        "outline.previewSceneFusion",
        {},
        { novel_id: novelId },
        data,
      )
    },
    async saveSceneFusion(novelId, data) {
      return post(withQuery("/outline/scene-workbench/fusion/save", { novel_id: novelId }), data)
    },
    async listFusionSuggestions(novelId, params = {}) {
      return request(withQuery("/outline/scene-workbench/fusion-suggestions", { novel_id: novelId, ...params }))
    },
    async dismissFusionSuggestions(novelId, data) {
      return post(withQuery("/outline/scene-workbench/fusion-suggestions/dismiss", { novel_id: novelId }), data)
    },
    async applySceneReplacement(novelId, data) {
      return post(withQuery("/outline/scene-workbench/replacement-suggestions/apply", { novel_id: novelId }), data)
    },
    async previewSceneSplit(novelId, data) {
      return post(withQuery("/outline/scene-workbench/split/preview", { novel_id: novelId }), data)
    },
    async splitScene(novelId, data) {
      return post(withQuery("/outline/scene-workbench/split", { novel_id: novelId }), data)
    },

    async listForeshadowing(novelId, params = {}) {
      return request(withQuery("/outline/foreshadowing", { novel_id: novelId, ...params }))
    },
    async createForeshadowing(novelId, payload) {
      return post(withQuery("/outline/foreshadowing", { novel_id: novelId }), payload)
    },
    async updateForeshadowing(id, novelId, payload) {
      return patch(withQuery(`/outline/foreshadowing/${id}`, { novel_id: novelId }), payload)
    },
    async deleteForeshadowing(id, novelId) {
      return deleteRequest(withQuery(`/outline/foreshadowing/${id}`, { novel_id: novelId }))
    },
    async listReveals(novelId, params = {}) {
      return request(withQuery("/outline/reveals", { novel_id: novelId, ...params }))
    },
    async createReveal(novelId, payload) {
      return post(withQuery("/outline/reveals", { novel_id: novelId }), payload)
    },
    async updateReveal(id, novelId, payload) {
      return patch(withQuery(`/outline/reveals/${id}`, { novel_id: novelId }), payload)
    },
    async deleteReveal(id, novelId) {
      return deleteRequest(withQuery(`/outline/reveals/${id}`, { novel_id: novelId }))
    },
  },

  // ============================================================
  // 缓存清除（跨模块写操作后需要刷新 GET 缓存）
  // ============================================================
  clearCache() {
    _clearRequestCache()
  },

  // ============================================================
  // 任务（异步操作）
  // ============================================================
  tasks: {
    async submit(taskType, meta = {}) {
      return post("/tasks", { task_type: taskType, meta })
    },

    async getStatus(taskId, novelId = null) {
      const resolvedNovelId = novelId || globalThis.appState?.currentProjectId
      const params = { _ts: Date.now() }
      if (resolvedNovelId) params.novel_id = resolvedNovelId
      const query = buildQueryString(params)
      return request(`/tasks/${taskId}${query}`)
    },

    async get(taskId, novelId = null) {
      return this.getStatus(taskId, novelId)
    },

    async cancel(taskId, novelId = null) {
      const resolvedNovelId = novelId || globalThis.appState?.currentProjectId
      return contractFetch("tasks.cancel", { taskId }, { novel_id: resolvedNovelId })
    },

    async retry(taskId, novelId = null) {
      const resolvedNovelId = novelId || globalThis.appState?.currentProjectId
      return contractFetch("tasks.retry", { taskId }, { novel_id: resolvedNovelId })
    },
  },

  // 底层请求入口（测试用，业务代码优先使用领域方法）
  request,
}

// Settings API — 全局默认 + 项目覆盖 + effective 视图（D1-D25 见 spec）
const settingsApi = {
  // 全局 LLM 默认（不含 Key）
  listGlobalLLMDefaults: () => contractFetch("settings.listGlobalLLMDefaults"),
  updateGlobalLLMDefaults: (payload) =>
    contractJson("settings.updateGlobalLLMDefaults", {}, {}, payload),
  listLLMConnections: () => contractFetch("settings.listLLMConnections"),
  connectLLMProvider: (providerId, apiKey) =>
    contractJson(
      "settings.connectLLMProvider",
      { providerId },
      {},
      { api_key: apiKey },
    ),
  activateLLMProvider: (providerId) =>
    contractFetch("settings.activateLLMProvider", { providerId }),
  clearLLMProvider: (providerId) =>
    deleteRequest(`/settings/llm-connections/${providerId}`),
  listLLMBalances: () => contractFetch("settings.listLLMBalances"),

  // 全局作者偏好
  listGlobalAuthorPrefs: () => request("/settings/author-preferences"),
  updateGlobalAuthorPrefs: (payload) => put("/settings/author-preferences", payload),

  // 引用此默认的项目聚合（D18/D19）
  listProjectsUsingDefaults: (params = {}) =>
    request(withQuery("/settings/projects-using-defaults", params)),

  // 调试端点：通知客户端刷新（D16）
  refreshSettings: () => post("/settings/refresh"),

  // 项目级作者偏好覆盖
  getProjectAuthorPrefs: (projectId) =>
    contractFetch("settings.getProjectAuthorPrefs", { projectId }),
  updateProjectAuthorPrefs: (projectId, payload) =>
    contractJson("settings.updateProjectAuthorPrefs", { projectId }, {}, payload),
  resetProjectAuthorPrefsField: (projectId, field) =>
    deleteRequest(`/settings/projects/${projectId}/author-preferences/field/${field}`),

  // 项目 effective 视图（含 source 标签）
  getEffectiveLLMSettings: (projectId) =>
    contractFetch("settings.getEffectiveLLMSettings", { projectId }),
  getEffectiveAuthorPrefs: (projectId) =>
    request(`/projects/${projectId}/effective-author-preferences`),

  // 项目 LLM 字段级 reset
  resetLLMSettingsField: (projectId, field) =>
    deleteRequest(`/projects/${projectId}/llm-settings/field/${field}`),
}

api.settings = settingsApi

// 导出到全局
window.api = api

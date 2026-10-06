/**
 * API 封装 — 与后端 REST API 通信
 *
 * 基础 URL 可配置，统一错误处理，超时控制。
 * 所有函数返回 Promise<Object>。
 *
 * AO-13 拆分：本文件是各 api/<domain>.js 模块共享的请求底座
 * （request/contractFetch/缓存/认证令牌），实现自 api.js 原样移动，
 * 行为不变；api.js 保留为组装层。
 */

import { forceAccountSafeReload } from "../shared/accountStorage.js"
import { clearEphemeralDeepSeekKey } from "../shared/ephemeralDeepSeekKey.js"
import { resolveApiBaseUrl } from "../shared/apiBaseUrl.js"
import {
  redactSensitiveText as _redactDiagnosticText,
  redactSensitiveValue as _redactDiagnosticValue,
} from "../shared/redactSensitive.js"

export const API_BASE_URL = resolveApiBaseUrl(
  typeof API_HOST !== "undefined" ? API_HOST : "",
)
const API_TIMEOUT = globalThis.apiContracts?.DEFAULT_TIMEOUT
const API_CACHE_TTL = 30000
const API_CACHE_MAX_ENTRIES = 128
// 封闭测试服令牌只保存在当前页面的 module scope 中。刷新后重新输入，避免
// bearer credential 暴露在可枚举、可跨页面生命周期读取的 Web Storage 中。
let _accessToken = ""
let _accessTokenRequestPromise = null
let _authMode = "closed_test"

export function _cookieValue(name) {
  if (typeof document === "undefined") return ""
  const prefix = `${name}=`
  const item = document.cookie.split(";").map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : ""
}

function _isDemoRpRequest(path) {
  return Boolean(
    globalThis.publicDemoRpMode
    && String(path).split("?", 1)[0].startsWith("/interactions/"),
  )
}

export function _setAccessToken(token) {
  _accessToken = typeof token === "string" ? token.trim() : ""
  return Boolean(_accessToken)
}

export function _clearAccessToken() {
  _accessToken = ""
}

export function _setAuthMode(mode) {
  _authMode = mode
}

function _handleUnauthorizedResponse({ invalidateAccount = true } = {}) {
  _clearAccessToken()
  // Anonymous RP keys are page-session credentials.  A rejected session must
  // not leave one around for a later account or anonymous session.
  clearEphemeralDeepSeekKey()
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
const _biblePublishAttempts = new Map()

function _biblePublishAttemptKey(novelId, draftId) {
  return `worldBiblePublishAttempt:${novelId}:${draftId}`
}

export function _readBiblePublishAttempt(novelId, draftId) {
  const key = _biblePublishAttemptKey(novelId, draftId)
  let raw
  try {
    raw = sessionStorage.getItem(key)
  } catch {
    return _biblePublishAttempts.get(key) || null
  }
  if (!raw) return _biblePublishAttempts.get(key) || null
  try {
    const parsed = JSON.parse(raw)
    if (parsed?.expectedCanonHead && parsed?.decisionId) {
      _biblePublishAttempts.set(key, parsed)
      return parsed
    }
  } catch { /* clear corrupt record below */ }
  _biblePublishAttempts.delete(key)
  try {
    sessionStorage.removeItem(key)
  } catch {
    // The invalid in-memory copy is already gone.
  }
  return null
}

export function _writeBiblePublishAttempt(novelId, draftId, attempt) {
  const key = _biblePublishAttemptKey(novelId, draftId)
  _biblePublishAttempts.set(key, attempt)
  try { sessionStorage.setItem(key, JSON.stringify(attempt)) } catch { /* unavailable */ }
}

export function _clearBiblePublishAttempt(novelId, draftId) {
  const key = _biblePublishAttemptKey(novelId, draftId)
  _biblePublishAttempts.delete(key)
  try { sessionStorage.removeItem(key) } catch { /* unavailable */ }
}

function _cacheKey(path, options) {
  const method = (options.method || "GET").toUpperCase()
  return `${method}:${path}`
}

const PUBLIC_DEMO_READONLY_POST_PATHS = new Set([
  "/evidence/compilation/evidence/grep",
  "/evidence/compilation/evidence/search",
  "/evidence/compilation/evidence/read",
])

function _withPublicDemoQuery(path, method) {
  if (!globalThis.publicDemoMode || globalThis.publicDemoRpMode) return path
  const [pathname, query = ""] = String(path).split("?", 2)
  const readonlyPost = method === "POST" && PUBLIC_DEMO_READONLY_POST_PATHS.has(pathname)
  if (method !== "GET" && !readonlyPost) return path
  const params = new URLSearchParams(query)
  if (!params.has("demo")) params.set("demo", "1")
  return `${pathname}?${params.toString()}`
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
  // These confirmations can write several domain collections in one request.
  if (/^\/(?:collaboration\/workspaces\/[^/]+\/merge|assistant\/batches\/[^/]+\/decide)(?:\?|$)/.test(path)) {
    _clearRequestCache()
    return
  }
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

export function _clearRequestCache() {
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
  _apiCache.delete(key)
  _apiCache.set(key, { data, time: now })
  while (_apiCache.size > API_CACHE_MAX_ENTRIES) {
    _apiCache.delete(_apiCache.keys().next().value)
  }
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
export async function request(path, options = {}) {
  const {
    timeout,
    signal: externalSignal,
    _retriedAuth,
    _suppressAccountInvalidation = false,
    _responseType = "json",
    ...fetchOptions
  } = options
  const controller = new AbortController()
  const timeoutMs = timeout ?? API_TIMEOUT
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
  const requestPath = _withPublicDemoQuery(path, method)
  const url = `${API_BASE_URL}${requestPath}`
  const isFormData = fetchOptions.body instanceof FormData
  const demoRpRequest = _isDemoRpRequest(requestPath)
  if (demoRpRequest) headers["X-Demo-RP-Session"] = "1"
  if (method !== "GET" && method !== "HEAD") {
    headers["X-Requested-With"] = "XMLHttpRequest"
    const csrfToken = demoRpRequest
      ? _cookieValue("aaw_demo_rp_csrf") || _cookieValue("aaw_csrf")
      : _cookieValue("aaw_csrf")
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken
  }
  if (method !== "GET" && method !== "HEAD" && !isFormData) {
    headers["Content-Type"] = "application/json"
  }

  const cacheKey = _cacheKey(requestPath, fetchOptions)
  // `no-store` is also honored by our in-memory cache.  Passing it only to
  // fetch would still allow a stale application-cache hit before fetch runs,
  // and an obsolete response could be written back after a project switch.
  const shouldUseResponseCache = method === "GET" && fetchOptions.cache !== "no-store"
  const shouldSharePending = shouldUseResponseCache && !externalSignal
  const responseCacheGeneration = shouldUseResponseCache
    ? _cacheGeneration(requestPath)
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
        if (
          resp.status === 401
          && !(globalThis.publicDemoMode && !globalThis.publicDemoRpMode)
        ) {
          _handleUnauthorizedResponse({
            invalidateAccount: !(_suppressAccountInvalidation || demoRpRequest),
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
        _invalidateRelatedCache(requestPath)
      }

      if (resp.status === 204) {
        if (shouldUseResponseCache) {
          if (_cacheGeneration(requestPath) !== responseCacheGeneration) {
            return request(path, options)
          }
          _setCache(cacheKey, null)
        }
        return null
      }

      const data = _responseType === "blob" ? await resp.blob() : await resp.json()
      if (shouldUseResponseCache) {
        if (_cacheGeneration(requestPath) !== responseCacheGeneration) {
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

export function withQuery(path, params = {}) {
  return path + apiContractHelpers.queryString(params)
}

function jsonRequest(path, method, payload, options = {}) {
  const requestOptions = {
    method,
    ...options,
  }
  if (payload !== undefined) requestOptions.body = JSON.stringify(payload)
  return request(path, requestOptions)
}

export function post(path, payload, options = {}) {
  return jsonRequest(path, "POST", payload, options)
}

export function put(path, payload, options = {}) {
  return jsonRequest(path, "PUT", payload, options)
}

export function patch(path, payload, options = {}) {
  return jsonRequest(path, "PATCH", payload, options)
}

export function deleteRequest(path) {
  return request(path, { method: "DELETE" })
}

export function uploadMultipart(path, formData, onProgress = null, options = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const signal = options?.signal
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
        const body = JSON.parse(xhr.responseText)
        const detail = body.detail
        const message = typeof detail === "string" ? detail : detail?.message || body.message || "上传失败"
        const error = new Error(message)
        error.status = xhr.status
        error.body = body
        reject(error)
      } catch {
        const error = new Error("上传失败")
        error.status = xhr.status
        reject(error)
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
    xhr.open(options?.method || "POST", `${API_BASE_URL}${path}`)
    xhr.withCredentials = true
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest")
    const csrfToken = _cookieValue("aaw_csrf")
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken)
    if (_accessToken) xhr.setRequestHeader("Authorization", `Bearer ${_accessToken}`)
    xhr.send(formData)
  })
}

export function uploadImportFile(file, novelId, onProgress = null, options = {}) {
  const formData = new FormData()
  formData.append("file", file)
  formData.append("novel_id", novelId)
  return uploadMultipart("/imports/upload", formData, onProgress, options)
}

export function uploadInteractionSource(path, payload, onProgress = null, options = {}) {
  const formData = new FormData()
  formData.append("file", payload.file)
  formData.append("title", payload.title)
  formData.append("mode", payload.mode || "full")
  if (payload.projectId) formData.append("project_id", payload.projectId)
  if (payload.expectedPreviewHash) {
    formData.append("expected_preview_hash", payload.expectedPreviewHash)
  }
  if (payload.destructiveConfirmed != null) {
    formData.append("destructive_confirmed", String(payload.destructiveConfirmed))
  }
  if (payload.authorizationConfirmed != null) {
    formData.append("authorization_confirmed", String(payload.authorizationConfirmed))
  }
  return uploadMultipart(path, formData, onProgress, options)
}

export function reportFrontendError(payload) {
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

export const apiContractHelpers = globalThis.apiContracts
if (!apiContractHelpers) {
  throw new Error("apiContracts.js must load before api.js")
}

export function contractPath(name, params = {}, query = {}) {
  return apiContractHelpers.contractPath(name, params, query)
}

export function contractFetch(name, params = {}, query = {}, options = {}) {
  const contractRequest = apiContractHelpers.contractRequest(
    name,
    params,
    query,
    options,
  )
  return request(contractRequest.path, contractRequest.options)
}

export function contractJson(name, params = {}, query = {}, payload, options = {}) {
  const contractRequest = apiContractHelpers.contractRequest(
    name,
    params,
    query,
    { ...options, body: payload },
  )
  return request(contractRequest.path, contractRequest.options)
}

export async function* streamSse(path, {
  signal,
  method = "GET",
  headers = {},
  suppressAccountInvalidation = false,
} = {}) {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method,
    credentials: "include",
    cache: "no-store",
    headers: _authorizationHeaders({
      "Accept": "text/event-stream",
      ...headers,
    }),
    signal,
  })
  if (!resp.ok) {
    if (resp.status === 401) {
      _handleUnauthorizedResponse({ invalidateAccount: !suppressAccountInvalidation })
    }
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

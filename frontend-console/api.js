/**
 * API 封装 — 与后端 REST API 通信
 *
 * 基础 URL 可配置，统一错误处理，超时控制。
 * 所有函数返回 Promise<Object>。
 */

const API_BASE_URL = (typeof API_HOST !== "undefined" ? API_HOST : "http://localhost:8000") + "/api"
const API_TIMEOUT = 15000
const RAG_SEARCH_TIMEOUT = 60000
const RAG_PREWARM_TIMEOUT = 75000
const CONTEXT_CONFIRM_TIMEOUT = 90000
const LLM_GENERATE_TIMEOUT = 90000
const API_CACHE_TTL = 30000
// 封闭测试服令牌只保存在当前页面的 module scope 中。刷新后重新输入，避免
// bearer credential 暴露在可枚举、可跨页面生命周期读取的 Web Storage 中。
let _accessToken = ""

function _setAccessToken(token) {
  _accessToken = typeof token === "string" ? token.trim() : ""
  return Boolean(_accessToken)
}

function _clearAccessToken() {
  _accessToken = ""
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

function _cacheKey(path, options) {
  const method = (options.method || "GET").toUpperCase()
  return `${method}:${path}`
}

function _invalidateRelatedCache(path) {
  // 失效该资源集合的所有 GET 缓存。
  // 写操作(含 /{id}/restore、/{id}/permanent 这类子动作)都会影响同一集合的列表,
  // 因此按集合根(第一路径段,如 /projects)清除,避免子路径动作遗漏集合级列表(如 recycle-bin)缓存。
  const base = path.split("?")[0]
  const collectionRoot = "/" + base.split("/").filter(Boolean)[0]
  for (const key of _apiCache.keys()) {
    // key 形如 "GET:/projects/recycle-bin?..." — 取出其路径部分按集合根匹配
    const keyPath = key.slice(key.indexOf(":") + 1)
    if (keyPath === collectionRoot || keyPath.startsWith(collectionRoot + "/") || keyPath.startsWith(collectionRoot + "?")) {
      _apiCache.delete(key)
    }
  }
}

function _getCached(key) {
  const entry = _apiCache.get(key)
  if (!entry) return null
  if (Date.now() - entry.time > API_CACHE_TTL) {
    _apiCache.delete(key)
    return null
  }
  return entry.data
}

function _setCache(key, data) {
  _apiCache.set(key, { data, time: Date.now() })
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
  const { timeout, signal: externalSignal, _retriedAuth, ...fetchOptions } = options
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
  }
  if (method !== "GET" && method !== "DELETE" && !isFormData) {
    headers["Content-Type"] = "application/json"
  }

  const cacheKey = _cacheKey(path, fetchOptions)
  // `no-store` is also honored by our in-memory cache.  Passing it only to
  // fetch would still allow a stale application-cache hit before fetch runs,
  // and an obsolete response could be written back after a project switch.
  const shouldUseResponseCache = method === "GET" && fetchOptions.cache !== "no-store"
  const shouldSharePending = shouldUseResponseCache && !externalSignal

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
        if (resp.status === 401) _clearAccessToken()
        if (resp.status === 401 && !_retriedAuth && typeof window !== "undefined" && typeof window.prompt === "function") {
          const token = window.prompt("请输入封闭测试访问令牌")
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
          rawDetail = errorBody.detail || errorBody.message || ""
          responseBody = JSON.stringify(errorBody).slice(0, 500)
          detail = _formatErrorDetail(rawDetail)
        } catch (e) { console.warn("解析错误响应失败", e) }

        const msg = errorMap[resp.status] || `请求失败 (${resp.status})`

        // 记录请求详情供 error-logger 使用
        if (window.errorLog) {
          window.errorLog._lastApiError = {
            method, url: path,
            status: resp.status,
            response: responseBody,
            body: fetchOptions.body ? String(fetchOptions.body).slice(0, 200) : undefined,
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
        if (shouldUseResponseCache) _setCache(cacheKey, null)
        return null
      }

      const data = await resp.json()
      if (shouldUseResponseCache) _setCache(cacheKey, data)
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
        throw new Error("无法连接到后端服务，请确认后端已启动")
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

function uploadImportFile(file, novelId, onProgress = null) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const formData = new FormData()
    formData.append("file", file)
    formData.append("novel_id", novelId)

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || typeof onProgress !== "function") return
      onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          reject(new Error("上传响应格式错误"))
        }
        return
      }
      if (xhr.status === 401) _clearAccessToken()
      try {
        const error = JSON.parse(xhr.responseText)
        reject(new Error(error.detail || "上传失败"))
      } catch {
        reject(new Error("上传失败"))
      }
    }
    xhr.onerror = () => reject(new Error("网络错误"))
    xhr.open("POST", `${API_BASE_URL}/imports/upload`)
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest")
    if (_accessToken) xhr.setRequestHeader("Authorization", `Bearer ${_accessToken}`)
    xhr.send(formData)
  })
}

function reportFrontendError(payload) {
  if (typeof fetch !== "function") return Promise.resolve()
  return fetch(`${API_BASE_URL}/debug/frontend-errors`, {
    method: "POST",
    headers: _authorizationHeaders({
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    }),
    body: JSON.stringify(payload),
    keepalive: true,
  }).then((response) => {
    if (response.status === 401) _clearAccessToken()
    return response
  })
}

const apiContractHelpers = globalThis.apiContracts
if (!apiContractHelpers) {
  throw new Error("apiContracts.js must load before api.js")
}

function contractOptions(name, options = {}) {
  const contract = apiContractHelpers.getApiContract(name)
  return {
    timeout: contract.timeout,
    ...options,
  }
}

function contractPath(name, params = {}, query = {}) {
  return apiContractHelpers.contractPath(name, params, query)
}

function contractFetch(name, params = {}, query = {}, options = {}) {
  const contract = apiContractHelpers.getApiContract(name)
  return request(contractPath(name, params, query), {
    method: contract.method,
    ...contractOptions(name, options),
  })
}

function contractJson(name, params = {}, query = {}, payload, options = {}) {
  const contract = apiContractHelpers.getApiContract(name)
  return jsonRequest(contractPath(name, params, query), contract.method, payload, contractOptions(name, options))
}

// ============================================================
// API 对象
// ============================================================

const api = {
  setAccessToken: _setAccessToken,
  clearAccessToken: _clearAccessToken,
  reportFrontendError,

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

  // ============================================================
  // 世界对象
  // ============================================================
  world: {
    async listEntities(params = {}) {
      return contractFetch("world.listEntities", {}, params)
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

    async listBibleTemplates() {
      return request("/world/bible/templates")
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

    async generateBiblePageAi(pageId, payload, novelId, options = {}) {
      return post(
        withQuery(`/world/bible/pages/${pageId}/ai-generate`, { novel_id: novelId }),
        payload,
        { timeout: LLM_GENERATE_TIMEOUT, ...options },
      )
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

    async extractEntities(payload) {
      return post("/world/entities/extract", payload)
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

    // ============================================================
    // 动态地图（PRD §6，/api/world/maps）
    // ============================================================

    async listMaps(params = {}) {
      return request(withQuery("/world/maps", params))
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
      return post(withQuery("/world/maps/quick-create/preview", { novel_id: novelId }), payload)
    },
    async confirmQuickCreateMap(payload, novelId) {
      return post(withQuery("/world/maps/quick-create/confirm", { novel_id: novelId }), payload)
    },
    async listLocationLayouts(mapId, novelId) {
      return request(withQuery(`/world/maps/${mapId}/location-layouts`, { novel_id: novelId }))
    },
    async replaceLocationLayouts(mapId, payload, novelId) {
      return put(withQuery(`/world/maps/${mapId}/location-layouts`, { novel_id: novelId }), payload)
    },
    async getMapTerrain(mapId, novelId, includeCandidates = false) {
      return request(withQuery(`/world/maps/${mapId}/terrain`, {
        novel_id: novelId,
        include_candidates: includeCandidates || undefined,
      }))
    },
    async replaceTerrainLayerPatches(mapId, layerId, payload, novelId) {
      return put(withQuery(`/world/maps/${mapId}/terrain/layers/${layerId}/patches`, { novel_id: novelId }), payload)
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
    async deleteLocationBinding(bindingId, mapId, novelId) {
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
    async listMapObservations(mapId, novelId, reviewState = null) {
      return contractFetch("world.listMapObservations", { mapId }, { novel_id: novelId, review_state: reviewState })
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
    async batchReviewMapObservations(mapId, observationIds, action, novelId) {
      return post(withQuery(`/world/maps/${mapId}/observations/batch-review`, { novel_id: novelId }), { observation_ids: observationIds, action })
    },
    async runMapBatchAction(mapId, novelId, payload) {
      return post(withQuery(`/world/maps/${mapId}/batch-actions`, { novel_id: novelId }), payload)
    },
    async confirmMapObservation(mapId, observationId, novelId) {
      return contractJson("world.confirmMapObservation", { mapId, observationId }, { novel_id: novelId })
    },
    async ignoreMapObservation(mapId, observationId, novelId) {
      return post(withQuery(`/world/maps/${mapId}/observations/${observationId}/ignore`, { novel_id: novelId }))
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
      return post("/context/evidence/grep", payload, options)
    },

    async searchEvidence(payload, options = {}) {
      return post("/context/evidence/search", payload, options)
    },

    async readEvidence(payload, options = {}) {
      return post("/context/evidence/read", payload, options)
    },

    async inspectEvidence(payload, options = {}) {
      return post("/context/evidence/inspect", payload, options)
    },

    async traceEvidence(payload, options = {}) {
      return post("/context/evidence/trace", payload, options)
    },

    async compile(payload, options = {}) {
      return post("/context/compile", payload, options)
    },

    async render(payload, options = {}) {
      return post("/context/render", payload, options)
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

    async splitChapter(chapterIndex, payload, novelId) {
      return post(withQuery(`/writing/chapters/${chapterIndex}/split`, { novel_id: novelId }), payload)
    },

    async generate(payload) {
      return post("/writing/generate", payload)
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
      return post(`/writing/conflict-check-items/${itemId}/ai-suggestion`, payload)
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

    async objectDraftChat(payload, options = {}) {
      return post("/world/object-draft-chat", payload, { timeout: LLM_GENERATE_TIMEOUT, ...options })
    },

    async generateObjectDraft(payload, options = {}) {
      return post("/world/object-drafts/generate", payload, { timeout: LLM_GENERATE_TIMEOUT, ...options })
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
    async uploadFile(file, novelId, onProgress = null) {
      return uploadImportFile(file, novelId, onProgress)
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
        throw new Error("启动深度导入前必须获得用户授权")
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
      return post("/outline/analyze", payload)
    },

    async generate(payload) {
      return post("/outline/generate", payload)
    },

    async applyStructurePreview(payload) {
      return contractJson("outline.applyStructurePreview", {}, {}, payload)
    },

    async extractChapterScenes(payload) {
      return post("/outline/chapter-scenes/extract", payload)
    },

    async applyChapterScenePreview(payload) {
      return contractJson("outline.applyChapterScenePreview", {}, {}, payload)
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
    _apiCache.clear()
    _pendingRequests.clear()
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

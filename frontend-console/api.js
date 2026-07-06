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
const API_CACHE_TTL = 30000

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
  const url = `${API_BASE_URL}${path}`
  const controller = new AbortController()
  const timeoutMs = options.timeout || API_TIMEOUT
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  const headers = {
    "Accept": "application/json",
  }

  const method = (options.method || "GET").toUpperCase()
  const isFormData = options.body instanceof FormData
  if (method !== "GET" && method !== "DELETE" && !isFormData) {
    headers["Content-Type"] = "application/json"
  }

  const cacheKey = _cacheKey(path, options)

  if (method === "GET") {
    const cached = _getCached(cacheKey)
    if (cached !== null) return cached

    const pending = _pendingRequests.get(cacheKey)
    if (pending) return pending
  }

  if (method !== "GET") {
    _invalidateRelatedCache(path)
  }

  let fetchPromise
  try {
    fetchPromise = fetch(url, {
      ...options,
      headers: { ...headers, ...options.headers },
      signal: controller.signal,
    })

    if (method === "GET") _pendingRequests.set(cacheKey, fetchPromise)

    const resp = await fetchPromise

    clearTimeout(timeoutId)

    if (!resp.ok) {
      const errorMap = {
        400: "请求参数错误",
        401: "未授权，请检查后端认证配置",
        404: "请求的资源不存在",
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
          body: options.body ? String(options.body).slice(0, 200) : undefined,
        }
      }

      const err = new Error(detail ? `${msg}：${detail}` : msg)
      err.status = resp.status
      err.detail = rawDetail
      err.body = errorBody
      err.responseBody = responseBody
      throw err
    }

    if (resp.status === 204) {
      if (method === "GET") _setCache(cacheKey, null)
      return null
    }

    const data = await resp.json()
    if (method === "GET") _setCache(cacheKey, data)
    return data
  } catch (err) {
    clearTimeout(timeoutId)

    if (err.name === "AbortError") {
      throw new Error("请求超时，请检查后端服务是否运行")
    }

    if (!err.status && (err.message === "Failed to fetch" || err.message.includes("fetch"))) {
      throw new Error("无法连接到后端服务，请确认后端已启动")
    }

    throw err
  } finally {
    if (method === "GET") _pendingRequests.delete(cacheKey)
  }
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

// ============================================================
// API 对象
// ============================================================

const api = {
  // ============================================================
  // 项目
  // ============================================================
  projects: {
    async list() {
      return request("/projects")
    },

    async create(payload) {
      return post("/projects", payload)
    },

    async get(id) {
      return request(`/projects/${id}`)
    },

    async update(id, payload) {
      return put(`/projects/${id}`, payload)
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
      return deleteRequest(`/projects/${id}/permanent`)
    },
    async listLlmProviderTemplates() {
      return request("/projects/llm/provider-templates")
    },
    async getLlmSettings(id) {
      return request(`/projects/${id}/llm-settings`)
    },
    async updateLlmSettings(id, payload) {
      return put(`/projects/${id}/llm-settings`, payload)
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
      return request(withQuery("/world/entities", params))
    },

    async getEntity(id, novelId) {
      return request(withQuery(`/world/entities/${id}`, { novel_id: novelId }))
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

    async listSuggestions(params = {}) {
      return request(withQuery("/world/suggestions", params))
    },

    async confirmSuggestion(suggestionId, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/confirm`, { novel_id: novelId }))
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
      return post(withQuery("/world/entities", { novel_id: novelId }), payload)
    },

    async updateEntity(id, payload, novelId) {
      return put(withQuery(`/world/entities/${id}`, { novel_id: novelId }), payload)
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
      return deleteRequest(withQuery(`/world/entities/${id}`, { novel_id: novelId }))
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

    async deleteAlias(entityId, alias, params = {}) {
      params.alias = alias
      return deleteRequest(withQuery(`/world/entities/${entityId}/aliases`, params))
    },

    async mergeEntity(candidateId, targetEntityId, novelId) {
      return post(withQuery(`/world/entities/${candidateId}/merge`, { novel_id: novelId }), { target_entity_id: targetEntityId })
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
      return request(withQuery(`/world/maps/${mapId}/state`, params))
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
      return request(withQuery(`/world/maps/${mapId}/dashboard`, params))
    },
    async getMapPlayback(mapId, novelId, sceneId = null, focusEntityId = null, includeCandidates = true) {
      const params = {
        novel_id: novelId,
        scene_id: sceneId,
        focus_entity_id: focusEntityId,
        include_candidates: includeCandidates,
      }
      return request(withQuery(`/world/maps/${mapId}/playback`, params))
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
    async getMapTerrain(mapId, novelId) {
      return request(withQuery(`/world/maps/${mapId}/terrain`, { novel_id: novelId }))
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
      return request(withQuery(`/world/maps/${mapId}/observations`, { novel_id: novelId, review_state: reviewState }))
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
      return post(withQuery(`/world/maps/${mapId}/observations/${observationId}/confirm`, { novel_id: novelId }))
    },
    async ignoreMapObservation(mapId, observationId, novelId) {
      return post(withQuery(`/world/maps/${mapId}/observations/${observationId}/ignore`, { novel_id: novelId }))
    },
    async listMapFacts(mapId, novelId, factStatus = "confirmed") {
      return request(withQuery(`/world/maps/${mapId}/facts`, { novel_id: novelId, fact_status: factStatus }))
    },
    async updateMapFactStatus(mapId, factId, novelId, factStatus) {
      return patch(withQuery(`/world/maps/${mapId}/facts/${factId}`, { novel_id: novelId }), { fact_status: factStatus })
    },
  },

  // ============================================================
  // 世界对象（含人物，人物 API 已迁入 /api/world/characters）
  // ============================================================

  // ============================================================
  // RAG 检索
  // ============================================================
  rag: {
    async search(payload, novelId) {
      return post(withQuery("/rag/retrieve", { novel_id: novelId }), payload, { timeout: RAG_SEARCH_TIMEOUT })
    },

    async rebuild(payload) {
      const { novel_id, start_chapter, end_chapter } = payload || {}
      if (!novel_id) throw new Error("重建索引需要先选择项目")
      return post("/rag/rebuild", { novel_id, start_chapter, end_chapter })
    },

    async prewarm() {
      return post("/rag/prewarm", {}, { timeout: RAG_PREWARM_TIMEOUT })
    },

    async retryEmbeddings(payload) {
      const { novel_id, start_chapter, end_chapter, statuses } = payload || {}
      if (!novel_id) throw new Error("重试失败向量需要先选择项目")
      return post("/rag/retry-embeddings", { novel_id, start_chapter, end_chapter, statuses })
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
    async compile(payload) {
      return post("/context/compile", payload)
    },

    async render(payload) {
      return post("/context/render", payload)
    },

    async confirm(payload) {
      return post("/context/confirm", payload, { timeout: CONTEXT_CONFIRM_TIMEOUT })
    },

    async listSnapshots(params = {}) {
      return request(withQuery("/context/snapshots", params))
    },

    async getSnapshot(snapshotId, params = {}) {
      return request(withQuery(`/context/snapshots/${snapshotId}`, params))
    },

    async activationPreview(params = {}) {
      return request(withQuery("/context/activation-preview", params))
    },
  },

  // ============================================================
  // 草稿
  // ============================================================
  writing: {
    async publish(payload) {
      return post("/writing/drafts", payload)
    },

    async autosave(draftId, payload, novelId) {
      return put(withQuery(`/writing/drafts/${draftId}`, { novel_id: novelId }), payload)
    },

    async autosaveDraftOnly(payload) {
      return post("/writing/drafts/autosave", payload)
    },

    async getDraft(chapterIndex, novelId) {
      return request(withQuery(`/writing/chapters/${chapterIndex}/draft`, { novel_id: novelId }))
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
      return post("/writing/conflict-checks", payload)
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
      return post(`/writing/conflict-checks/${checkId}/ai-review`, payload)
    },

    async enqueueConflictAiReview(checkId, payload) {
      return post(`/writing/conflict-checks/${checkId}/ai-review-task`, payload)
    },

    async requestConflictAiSuggestion(itemId, payload) {
      return post(`/writing/conflict-check-items/${itemId}/ai-suggestion`, payload)
    },
  },

  // ============================================================
  // 生成中心
  // ============================================================
  generate: {
    async worldCharacter(payload) {
      return post("/world/entities/extract", payload)
    },

    async plotStructure(payload) {
      return post("/outline/generate", payload)
    },

    async chapterScene(payload) {
      return post("/outline/chapter-scenes/extract", payload)
    },
  },

  // ============================================================
  // 健康检查
  // ============================================================
  async healthCheck() {
    try {
      await request("/health")
      return true
    } catch {
      return false
    }
  },

  // ============================================================
  // 导入
  // ============================================================
  imports: {
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

    async deepImport(novelId, startChapter, endChapter, force = false, highQuality = false) {
      return post("/imports/deep", { novel_id: novelId, start_chapter: startChapter, end_chapter: endChapter, force, high_quality: highQuality })
    },

    async startStage(stage, novelId, startChapter, endChapter, force = false, highQuality = false) {
      const endpoints = {
        scenes: "/imports/stages/scenes",
        world_objects: "/imports/stages/world-objects",
        plot_structure: "/imports/stages/plot-structure",
      }
      const endpoint = endpoints[stage]
      if (!endpoint) throw new Error(`unsupported import stage: ${stage}`)
      return post(endpoint, { novel_id: novelId, start_chapter: startChapter, end_chapter: endChapter, force, high_quality: highQuality })
    },

    async resumeDeepImport(taskId) {
      return post("/imports/deep/resume", { task_id: taskId })
    },

    async abandonDeepImport(taskId) {
      return post("/imports/deep/abandon", { task_id: taskId })
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

    async extractChapterScenes(payload) {
      return post("/outline/chapter-scenes/extract", payload)
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
    async previewSceneMerge(novelId, data) {
      return post(withQuery("/outline/scene-workbench/merge/preview", { novel_id: novelId }), data)
    },
    async mergeScenes(novelId, data) {
      return post(withQuery("/outline/scene-workbench/merge", { novel_id: novelId }), data)
    },
    async previewSceneFusion(novelId, data) {
      return post(withQuery("/outline/scene-workbench/fusion/preview", { novel_id: novelId }), data)
    },
    async saveSceneFusion(novelId, data) {
      return post(withQuery("/outline/scene-workbench/fusion/save", { novel_id: novelId }), data)
    },
    async detectCrossChapterScenes(data) {
      return post("/outline/scene-workbench/cross-chapter/detect", data)
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
  },
}

// 导出到全局
window.api = api

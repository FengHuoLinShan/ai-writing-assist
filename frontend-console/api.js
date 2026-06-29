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
      let detail = "", responseBody = ""
      try {
        const errBody = await resp.json()
        const rawDetail = errBody.detail || errBody.message || ""
        responseBody = JSON.stringify(errBody).slice(0, 500)

        // FastAPI 校验错误 detail 可能是对象或数组；提取可读消息
        if (Array.isArray(rawDetail)) {
          detail = rawDetail
            .map((item) => {
              if (typeof item === "string") return item
              if (item && typeof item === "object") {
                const parts = []
                if (item.loc && Array.isArray(item.loc)) parts.push(item.loc.join("."))
                if (item.msg) parts.push(item.msg)
                if (item.type) parts.push(`(${item.type})`)
                return parts.filter(Boolean).join(" — ")
              }
              return String(item)
            })
            .join("；")
        } else if (rawDetail && typeof rawDetail === "object") {
          detail = Object.entries(rawDetail)
            .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
            .join("；")
        } else {
          detail = String(rawDetail || "")
        }
      } catch (e) { console.warn("解析错误响应失败", e) }

      const msg = errorMap[resp.status] || `请求失败 (${resp.status})`

      // 记录请求详情供 error-logger 使用
      window.errorLog._lastApiError = {
        method, url: path,
        status: resp.status,
        response: responseBody,
        body: options.body ? String(options.body).slice(0, 200) : undefined,
      }

      const err = new Error(detail ? `${msg}：${detail}` : msg)
      err.status = resp.status
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

    if (err.message === "Failed to fetch" || err.message.includes("fetch")) {
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

// ============================================================
// API 对象
// ============================================================

const api = {
  // ============================================================
  // 项目
  // ============================================================
  projects: {
    /** 获取项目列表 */
    async list() {
      return request("/projects")
    },

    /** 创建项目 */
    async create(payload) {
      return request("/projects", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 获取项目详情 */
    async get(id) {
      return request(`/projects/${id}`)
    },

    /** 更新项目 */
    async update(id, payload) {
      return request(`/projects/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 删除项目（软删除，移至回收站） */
    async remove(id) {
      return request(`/projects/${id}`, { method: "DELETE" })
    },
    /** 获取回收站项目列表 */
    async listDeleted(skip = 0, limit = 20) {
      return request("/projects/recycle-bin" + buildQueryString({ skip, limit }))
    },
    /** 从回收站恢复项目 */
    async restore(id) {
      return request(`/projects/${id}/restore`, { method: "POST" })
    },
    /** 永久删除项目（不可恢复） */
    async permanentDelete(id) {
      return request(`/projects/${id}/permanent`, { method: "DELETE" })
    },
  },

  // ============================================================
  // 世界对象
  // ============================================================
  world: {
    /** 获取世界对象列表 */
    async listEntities(params = {}) {
      return request("/world/entities" + buildQueryString(params))
    },

    /** 获取世界对象详情 */
    async getEntity(id, novelId) {
      return request(`/world/entities/${id}${buildQueryString({ novel_id: novelId })}`)
    },

    /** 创建世界对象 */
    async createEntity(payload, novelId) {
      return request(`/world/entities${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 更新世界对象 */
    async updateEntity(id, payload, novelId) {
      return request(`/world/entities/${id}${buildQueryString({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 将草稿/候选世界对象提升为正史 */
    async promoteEntity(id, novelId, payload = {}) {
      return request(`/world/entities/${id}/promote${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 提交世界对象补抽任务 */
    async extractEntities(payload) {
      return request("/world/entities/extract", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 删除世界对象 */
    async deleteEntity(id, novelId) {
      return request(`/world/entities/${id}${buildQueryString({ novel_id: novelId })}`, { method: "DELETE" })
    },

    /** 获取自动入库批次分组列表 */
    async listEntityBatches(params = {}) {
      return request("/world/entity-batches" + buildQueryString(params))
    },

    /** 获取关系列表 */
    async listRelationships(params = {}) {
      return request("/world/relations" + buildQueryString(params))
    },

    /** 创建关系 */
    async createRelationship(payload, novelId) {
      return request(`/world/relations${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 删除关系 */
    async deleteRelationship(id, params = {}) {
      return request(`/world/relations/${id}` + buildQueryString(params), { method: "DELETE" })
    },

    /** 获取别名列表 */
    async listAliases(params = {}) {
      return request("/world/aliases" + buildQueryString(params))
    },

    /** 创建别名 */
    async createAlias(payload, novelId) {
      return request(`/world/aliases${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 删除别名（core_entities.aliases JSONB） */
    async deleteAlias(entityId, alias, params = {}) {
      params.alias = alias
      return request(`/world/entities/${entityId}/aliases` + buildQueryString(params), { method: "DELETE" })
    },

    /** 合并候选实体到目标实体 */
    async mergeEntity(candidateId, targetEntityId, novelId) {
      return request(`/world/entities/${candidateId}/merge${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify({ target_entity_id: targetEntityId }),
      })
    },

    /** 回滚实体到指定场景索引 */
    async rollbackEntity(entityId, targetSceneIndex, novelId) {
      return request(`/world/entities/${entityId}/rollback${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify({ target_scene_index: targetSceneIndex }),
      })
    },

    /** 列出人物知识边界 */
    async listKnowledge(characterId, novelId) {
      return request(`/world/characters/${characterId}/knowledge${buildQueryString({ novel_id: novelId })}`)
    },

    /** 创建人物知识边界 */
    async createKnowledge(characterId, payload, novelId) {
      return request(`/world/characters/${characterId}/knowledge${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    // ============================================================
    // 动态地图（PRD §6，/api/world/maps）
    // ============================================================

    /** 列出地图 */
    async listMaps(params = {}) {
      return request("/world/maps" + buildQueryString(params))
    },
    /** 获取单个地图 */
    async getMap(mapId, novelId) {
      return request(`/world/maps/${mapId}${buildQueryString({ novel_id: novelId })}`)
    },
    /** 创建地图 */
    async createMap(payload, novelId) {
      return request(`/world/maps${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },
    /** 更新地图 */
    async updateMap(mapId, payload, novelId) {
      return request(`/world/maps/${mapId}${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
    },
    /** 删除地图（危险操作，前端二次确认） */
    async deleteMap(mapId, novelId) {
      return request(`/world/maps/${mapId}${buildQueryString({ novel_id: novelId })}`, {
        method: "DELETE",
      })
    },
    /** 快速生成详图地形 */
    async generateMap(mapId, novelId) {
      return request(`/world/maps/${mapId}/generate${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
      })
    },
    /** 获取地图聚合状态（map + 面包屑 + 地形 + 地点绑定） */
    async getMapState(mapId, novelId, sceneId = null) {
      const params = { novel_id: novelId }
      if (sceneId) params.scene_id = sceneId
      return request(`/world/maps/${mapId}/state${buildQueryString(params)}`)
    },
    async getMapDashboard(mapId, novelId, sceneId = null, focusEntityId = null) {
      const params = { novel_id: novelId, scene_id: sceneId, focus_entity_id: focusEntityId }
      return request(`/world/maps/${mapId}/dashboard${buildQueryString(params)}`)
    },
    async getMapPlayback(mapId, novelId, sceneId = null, focusEntityId = null, includeCandidates = true) {
      const params = {
        novel_id: novelId,
        scene_id: sceneId,
        focus_entity_id: focusEntityId,
        include_candidates: includeCandidates,
      }
      return request(`/world/maps/${mapId}/playback${buildQueryString(params)}`)
    },
    /** 获取写作页 Scene 地图摘要 */
    async getMapSceneSummary(novelId, sceneId) {
      return request("/world/maps/scene-summary" + buildQueryString({
        novel_id: novelId,
        scene_id: sceneId,
      }))
    },
    /** 批量更新地形 */
    async batchUpdateTiles(mapId, payload, novelId) {
      return request(`/world/maps/${mapId}/tiles${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
    },
    /** 批量创建地点绑定 */
    async createLocationBindings(mapId, payload, novelId) {
      return request(`/world/maps/${mapId}/location-bindings${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },
    /** 更新单个地点绑定 */
    async updateLocationBinding(mapId, bindingId, payload, novelId) {
      return request(`/world/maps/${mapId}/location-bindings/${bindingId}${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
    },
    /** 删除地点绑定 */
    async deleteLocationBinding(bindingId, mapId, novelId) {
      return request(`/world/maps/${mapId}/location-bindings/${bindingId}${buildQueryString({ novel_id: novelId })}`, {
        method: "DELETE",
      })
    },
    async listMapMarkers(mapId, novelId, sceneId = null) {
      const params = { novel_id: novelId }
      if (sceneId) params.scene_id = sceneId
      return request(`/world/maps/${mapId}/markers${buildQueryString(params)}`)
    },
    async createMapMarker(mapId, data, novelId) {
      return request(`/world/maps/${mapId}/markers${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(data),
      })
    },
    async updateMapMarker(mapId, markerId, data, novelId) {
      return request(`/world/maps/${mapId}/markers/${markerId}${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      })
    },
    async deleteMapMarker(mapId, markerId, novelId) {
      return request(`/world/maps/${mapId}/markers/${markerId}${buildQueryString({ novel_id: novelId })}`, {
        method: "DELETE",
      })
    },
    /** 获取聚焦模式地图状态（仅含指定组织势力范围） */
    async getFocusState(mapId, factionEntityId, novelId) {
      return request(`/world/maps/${mapId}/focus${buildQueryString({ novel_id: novelId, faction_entity_id: factionEntityId })}`)
    },
    /** 批量创建势力范围地块 */
    async createTerritories(mapId, payload, novelId) {
      return request(`/world/maps/${mapId}/territories${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },
    /** 按组织删除全部势力范围 */
    async deleteTerritoriesByFaction(mapId, factionEntityId, novelId) {
      return request(`/world/maps/${mapId}/territories${buildQueryString({ novel_id: novelId, faction_entity_id: factionEntityId })}`, {
        method: "DELETE",
      })
    },
    async listMapObservations(mapId, novelId, reviewState = null) {
      return request(`/world/maps/${mapId}/observations${buildQueryString({ novel_id: novelId, review_state: reviewState })}`)
    },
    async updateMapObservationReview(mapId, observationId, novelId, reviewState) {
      return request(`/world/maps/${mapId}/observations/${observationId}${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        body: JSON.stringify({ review_state: reviewState }),
      })
    },
    async batchReviewMapObservations(mapId, observationIds, action, novelId) {
      return request(`/world/maps/${mapId}/observations/batch-review${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify({ observation_ids: observationIds, action }),
      })
    },
    async confirmMapObservation(mapId, observationId, novelId) {
      return request(`/world/maps/${mapId}/observations/${observationId}/confirm${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
      })
    },
    async ignoreMapObservation(mapId, observationId, novelId) {
      return request(`/world/maps/${mapId}/observations/${observationId}/ignore${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
      })
    },
    async listMapFacts(mapId, novelId, factStatus = "confirmed") {
      return request(`/world/maps/${mapId}/facts${buildQueryString({ novel_id: novelId, fact_status: factStatus })}`)
    },
    async updateMapFactStatus(mapId, factId, novelId, factStatus) {
      return request(`/world/maps/${mapId}/facts/${factId}${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        body: JSON.stringify({ fact_status: factStatus }),
      })
    },
  },

  // ============================================================
  // 世界对象（含人物，人物 API 已迁入 /api/world/characters）
  // ============================================================

  // ============================================================
  // RAG 检索
  // ============================================================
  rag: {
    /** 搜索 RAG */
    async search(payload, novelId) {
      return request(`/rag/retrieve${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
        timeout: RAG_SEARCH_TIMEOUT,
      })
    },

    /** 重建索引 */
    async rebuild(payload) {
      const { novel_id, start_chapter, end_chapter } = payload || {}
      if (!novel_id) throw new Error("重建索引需要先选择项目")
      return request("/rag/rebuild", {
        method: "POST",
        body: JSON.stringify({ novel_id, start_chapter, end_chapter }),
      })
    },

    /** 预热 RAG embedding worker */
    async prewarm() {
      return request("/rag/prewarm", {
        method: "POST",
        body: JSON.stringify({}),
        timeout: RAG_PREWARM_TIMEOUT,
      })
    },

    /** 重试失败 embedding */
    async retryEmbeddings(payload) {
      const { novel_id, start_chapter, end_chapter, statuses } = payload || {}
      if (!novel_id) throw new Error("重试失败向量需要先选择项目")
      return request("/rag/retry-embeddings", {
        method: "POST",
        body: JSON.stringify({ novel_id, start_chapter, end_chapter, statuses }),
      })
    },

    /** 获取索引状态 */
    async status(projectId) {
      return request("/rag/chunks" + buildQueryString({ novel_id: projectId }))
    },

    /** 获取 RAG 运行指标 */
    async metrics() {
      return request("/rag/metrics")
    },
  },

  // ============================================================
  // 上下文
  // ============================================================
  context: {
    /** 编译上下文 */
    async compile(payload) {
      return request("/context/compile", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 渲染上下文 Markdown */
    async render(payload) {
      return request("/context/render", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 确认 AI 参考资料 */
    async confirm(payload) {
      return request("/context/confirm", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 列出上下文快照审计记录 */
    async listSnapshots(params = {}) {
      return request("/context/snapshots" + buildQueryString(params))
    },

    /** 获取上下文快照审计详情 */
    async getSnapshot(snapshotId, params = {}) {
      return request(`/context/snapshots/${snapshotId}` + buildQueryString(params))
    },
  },

  // ============================================================
  // 草稿
  // ============================================================
  writing: {
    /** 发布章节（创建新版本 + RAG 索引 + memory 快照） */
    async publish(payload) {
      return request("/writing/drafts", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 暂存草稿（原地更新最新版本，不创建新版本） */
    async autosave(draftId, payload, novelId) {
      return request(`/writing/drafts/${draftId}${buildQueryString({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 获取章节最新草稿 */
    async getDraft(chapterIndex, novelId) {
      return request(`/writing/chapters/${chapterIndex}/draft${buildQueryString({ novel_id: novelId })}`)
    },

    /** 获取指定草稿 */
    async get(draftId, novelId) {
      return request(`/writing/drafts/${draftId}${buildQueryString({ novel_id: novelId })}`)
    },

    /** 删除单个版本 */
    async deleteDraft(draftId, novelId) {
      return request(`/writing/drafts/${draftId}${buildQueryString({ novel_id: novelId })}`, {
        method: "DELETE",
      })
    },

    /** 删除整章所有版本 */
    async deleteChapter(chapterIndex, novelId) {
      return request(`/writing/chapters/${chapterIndex}${buildQueryString({ novel_id: novelId })}`, {
        method: "DELETE",
      })
    },

    /** 获取有草稿的章节索引列表 */
    async listChapters(novelId) {
      return request(`/writing/chapters${buildQueryString({ novel_id: novelId })}`)
    },

    /** 获取章节版本历史 */
    async getVersionHistory(chapterIndex, novelId) {
      return request(`/writing/chapters/${chapterIndex}/versions${buildQueryString({ novel_id: novelId })}`)
    },

    /** 断章：从当前章节指定 offset 切分为新章节 */
    async splitChapter(chapterIndex, payload, novelId) {
      return request(`/writing/chapters/${chapterIndex}/split${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 提交 AI 正文候选草稿生成任务 */
    async generate(payload) {
      return request("/writing/generate", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },
  },

  // ============================================================
  // 生成中心
  // ============================================================
  generate: {
    /** 生成世界与人物结构 */
    async worldCharacter(payload) {
      return request("/world/entities/extract", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 生成剧情结构 */
    async plotStructure(payload) {
      return request("/outline/generate", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 生成章节与场景结构 */
    async chapterScene(payload) {
      return request("/outline/chapter-scenes/extract", {
        method: "POST",
        body: JSON.stringify(payload),
      })
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
    /** 上传并导入小说文件 */
    async upload(novelId, file) {
      const formData = new FormData()
      formData.append("novel_id", novelId)
      formData.append("file", file)
      return request("/imports/upload", {
        method: "POST",
        body: formData,
      })
    },

    /** 获取导入记录列表 */
    async list(params = {}) {
      return request("/imports" + buildQueryString(params))
    },

    /** 获取导入记录详情 */
    async get(recordId, params = {}) {
      return request(`/imports/${recordId}` + buildQueryString(params))
    },

    /** 提交深度导入任务（全自动三步：抽取 + 人物同步 + 剧情生成） */
    async deepImport(novelId, startChapter, endChapter, force = false) {
      return request("/imports/deep", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          novel_id: novelId,
          start_chapter: startChapter,
          end_chapter: endChapter,
          force,
        }),
      })
    },
  },

  // ============================================================
  // 大纲
  // ============================================================
  outline: {
    /** 列出剧情线 */
    async listThreads(novelId) {
      return request("/outline/threads" + buildQueryString({ novel_id: novelId }))
    },

    /** 创建剧情线 */
    async createThread(novelId, data) {
      return request(`/outline/threads?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data),
      })
    },

    /** 更新剧情线 */
    async updateThread(threadId, novelId, data) {
      return request(`/outline/threads/${threadId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data),
      })
    },

    /** 删除剧情线 */
    async deleteThread(threadId, novelId) {
      return request(`/outline/threads/${threadId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "DELETE",
      })
    },

    /** 列出篇章纲 */
    async listArcs(novelId) {
      return request("/outline/arcs" + buildQueryString({ novel_id: novelId }))
    },

    /** 创建篇章纲 */
    async createArc(novelId, data) {
      return request(`/outline/arcs?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data),
      })
    },
    /** 更新篇章纲 */
    async updateArc(arcId, novelId, data) {
      return request(`/outline/arcs/${arcId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data),
      })
    },
    /** 删除篇章纲 */
    async deleteArc(arcId, novelId) {
      return request(`/outline/arcs/${arcId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "DELETE",
      })
    },

    /** 提交剧情分析任务 */
    async analyze(payload) {
      return request("/outline/analyze", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 提交剧情结构生成任务 */
    async generate(payload) {
      return request("/outline/generate", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 提交章节/Scene 卡提取任务 */
    async extractChapterScenes(payload) {
      return request("/outline/chapter-scenes/extract", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    // ---- Scene 卡 ----
    /** 列出场景卡 */
    async listScenes(novelId, skip = 0, limit = 50) {
      return request("/outline/scenes" + buildQueryString({ novel_id: novelId, skip, limit }))
    },
    /** 获取单个场景卡 */
    async getScene(sceneId, novelId) {
      return request(`/outline/scenes/${sceneId}?novel_id=${encodeURIComponent(novelId)}`)
    },
    /** 创建场景卡 */
    async createScene(novelId, data) {
      return request(`/outline/scenes?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data),
      })
    },
    /** 更新场景卡 */
    async updateScene(sceneId, novelId, data) {
      return request(`/outline/scenes/${sceneId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data),
      })
    },
    /** 删除场景卡 */
    async deleteScene(sceneId, novelId) {
      return request(`/outline/scenes/${sceneId}?novel_id=${encodeURIComponent(novelId)}`, {
        method: "DELETE",
      })
    },
    /** 按顺序列出所有场景卡 */
    async listScenesOrdered(novelId) {
      return request("/outline/scenes/ordered?novel_id=" + encodeURIComponent(novelId))
    },
    /** 按章节列出场景卡 */
    async listScenesByChapter(novelId, chapterIndex) {
      return request(`/outline/scenes/by-chapter?novel_id=${encodeURIComponent(novelId)}&chapter_index=${chapterIndex}`)
    },
    /** 批量重排 Scene 顺序 */
    async reorderScenes(novelId, sceneIds) {
      return request(`/outline/scenes/reorder?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ scene_ids: sceneIds }),
      })
    },
    /** 断章：从 chapter_index 开始将章节移到目标 Scene */
    async splitChapters(novelId, chapterIndex, targetSceneId) {
      return request(`/outline/scenes/split?novel_id=${encodeURIComponent(novelId)}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ chapter_index: chapterIndex, target_scene_id: targetSceneId || null }),
      })
    },

    /** 列出伏笔计划 */
    async listForeshadowing(novelId) {
      return request("/outline/foreshadowing" + buildQueryString({ novel_id: novelId }))
    },
    /** 创建伏笔计划 */
    async createForeshadowing(novelId, payload) {
      return request("/outline/foreshadowing" + buildQueryString({ novel_id: novelId }), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    },
    /** 更新伏笔计划 */
    async updateForeshadowing(id, novelId, payload) {
      return request(`/outline/foreshadowing/${id}${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    },
    /** 删除伏笔计划 */
    async deleteForeshadowing(id, novelId) {
      return request(`/outline/foreshadowing/${id}${buildQueryString({ novel_id: novelId })}`, {
        method: "DELETE",
      })
    },
    /** 列出揭示计划 */
    async listReveals(novelId) {
      return request("/outline/reveals" + buildQueryString({ novel_id: novelId }))
    },
    /** 创建揭示计划 */
    async createReveal(novelId, payload) {
      return request("/outline/reveals" + buildQueryString({ novel_id: novelId }), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    },
    /** 更新揭示计划 */
    async updateReveal(id, novelId, payload) {
      return request(`/outline/reveals/${id}${buildQueryString({ novel_id: novelId })}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    },
    /** 删除揭示计划 */
    async deleteReveal(id, novelId) {
      return request(`/outline/reveals/${id}${buildQueryString({ novel_id: novelId })}`, {
        method: "DELETE",
      })
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
    /** 提交异步任务 */
    async submit(taskType, meta = {}) {
      return request("/tasks", {
        method: "POST",
        body: JSON.stringify({ task_type: taskType, meta }),
      })
    },

    /** 查询任务状态 */
    async getStatus(taskId) {
      return request(`/tasks/${taskId}`)
    },

    /** 查询任务详情（getStatus 的别名，供长轮询流程使用） */
    async get(taskId) {
      return this.getStatus(taskId)
    },
  },
}

// 导出到全局
window.api = api

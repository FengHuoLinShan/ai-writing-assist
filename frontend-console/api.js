/**
 * API 封装 — 与后端 REST API 通信
 *
 * 基础 URL 可配置，统一错误处理，超时控制。
 * 所有函数返回 Promise<Object>。
 */

const API_BASE_URL = (typeof API_HOST !== "undefined" ? API_HOST : "http://localhost:8000") + "/api"
const API_TIMEOUT = 15000
const API_CACHE_TTL = 30000

const _apiCache = new Map()
const _pendingRequests = new Map()

function _cacheKey(path, options) {
  const method = (options.method || "GET").toUpperCase()
  return `${method}:${path}`
}

function _invalidateRelatedCache(path) {
  const base = path.split("?")[0]
  for (const key of _apiCache.keys()) {
    if (key.includes(base) || key.includes(base.split("/").slice(0, -1).join("/"))) {
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
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT)

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
        detail = errBody.detail || errBody.message || ""
        responseBody = JSON.stringify(errBody).slice(0, 500)
      } catch (e) { console.warn("解析错误响应失败", e) }

      const msg = errorMap[resp.status] || `请求失败 (${resp.status})`

      // 记录请求详情供 error-logger 使用
      window.errorLog._lastApiError = {
        method, url: path,
        status: resp.status,
        response: responseBody,
        body: options.body ? String(options.body).slice(0, 200) : undefined,
      }

      throw new Error(detail ? `${msg}：${detail}` : msg)
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

    /** 删除项目 */
    async remove(id) {
      return request(`/projects/${id}`, { method: "DELETE" })
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
      return request("/world/relationships" + buildQueryString(params))
    },

    /** 创建关系 */
    async createRelationship(payload, novelId) {
      return request(`/world/relationships${buildQueryString({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 删除关系 */
    async deleteRelationship(id, params = {}) {
      return request(`/world/relationships/${id}` + buildQueryString(params), { method: "DELETE" })
    },

    /** 获取别名列表 */
    async listAliases(params = {}) {
      return request("/world/aliases" + buildQueryString(params))
    },

    /** 创建别名 */
    async createAlias(payload) {
      return request("/world/aliases", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 删除别名（core_entities.aliases JSONB） */
    async deleteAlias(entityId, alias, params = {}) {
      params.alias = alias
      return request(`/world/entities/${entityId}/aliases` + buildQueryString(params), { method: "DELETE" })
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
      })
    },

    /** 重建索引 */
    async rebuild(payload) {
      const novelId = payload?.novel_id
      if (!novelId) throw new Error("重建索引需要先选择项目")
      const task = await request("/tasks", {
        method: "POST",
        body: JSON.stringify({
          task_type: "rag_reindex_novel",
          meta: { novel_id: novelId, force: true },
        }),
      })
      return {
        status: task.status || "pending",
        total: task.task_id ? 1 : 0,
        task_id: task.task_id,
        task_ids: task.task_id ? [task.task_id] : [],
        warnings: task.warnings || [],
      }
    },

    /** 获取索引状态 */
    async status(projectId) {
      return request("/rag/chunks" + buildQueryString({ novel_id: projectId }))
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
  },

  // ============================================================
  // 生成中心
  // ============================================================
  generate: {
    /** 生成世界与人物结构 */
    async worldCharacter(payload) {
      return request("/tasks", {
        method: "POST",
        body: JSON.stringify({ task_type: "world_entity_extraction", meta: payload }),
      })
    },

    /** 生成剧情结构 */
    async plotStructure(payload) {
      return request("/tasks", {
        method: "POST",
        body: JSON.stringify({ task_type: "plot_structure_generate", meta: payload }),
      })
    },

    /** 生成章节与场景结构 */
    async chapterScene(payload) {
      return request("/tasks", {
        method: "POST",
        body: JSON.stringify({ task_type: "chapter_card_extraction", meta: payload }),
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
    async deepImport(novelId, startChapter, endChapter) {
      return request("/imports/deep", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          novel_id: novelId,
          start_chapter: startChapter,
          end_chapter: endChapter,
        }),
      })
    },
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

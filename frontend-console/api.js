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
      window.__lastFailedRequest = {
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
function qs(params = {}) {
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
      return request("/world/entities" + qs(params))
    },

    /** 获取世界对象详情 */
    async getEntity(id, novelId) {
      return request(`/world/entities/${id}${qs({ novel_id: novelId })}`)
    },

    /** 创建世界对象 */
    async createEntity(payload, novelId) {
      return request(`/world/entities${qs({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 更新世界对象 */
    async updateEntity(id, payload, novelId) {
      return request(`/world/entities/${id}${qs({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 删除世界对象 */
    async deleteEntity(id, novelId) {
      return request(`/world/entities/${id}${qs({ novel_id: novelId })}`, { method: "DELETE" })
    },

    /** 获取候选对象列表 */
    async listCandidates(params = {}) {
      return request("/world/candidates" + qs(params))
    },

    /** 对候选对象进行去重检查 */
    async dedupCandidate(id, novelId) {
      return request(`/world/candidates/${id}/dedup${qs({ novel_id: novelId })}`, { method: "POST" })
    },

    /** 确认候选对象（晋升正史） */
    async confirmCandidate(id, actionPayload, novelId) {
      return request(`/world/candidates/${id}${qs({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify(actionPayload),
      })
    },

    /** 接受候选对象：根据 suggested_action 创建实体/别名/合并 */
    async acceptCandidate(id, novelId) {
      return request(`/world/candidates/${id}/accept${qs({ novel_id: novelId })}`, {
        method: "POST",
      })
    },

    /** 获取关系列表 */
    async listRelationships(params = {}) {
      return request("/world/relationships" + qs(params))
    },

    /** 创建关系 */
    async createRelationship(payload, novelId) {
      return request(`/world/relationships${qs({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 删除关系 */
    async deleteRelationship(id, params = {}) {
      return request(`/world/relationships/${id}` + qs(params), { method: "DELETE" })
    },

    /** 获取别名列表 */
    async listAliases(params = {}) {
      return request("/world/aliases" + qs(params))
    },

    /** 创建别名 */
    async createAlias(payload) {
      return request("/world/aliases", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 删除别名 */
    async deleteAlias(id, params = {}) {
      return request(`/world/aliases/${id}` + qs(params), { method: "DELETE" })
    },

    /** 将候选合并到正史对象（候选名称成为别名，信息合并） */
    async mergeCandidate(entityId, candidateId, params = {}) {
      return request(`/world/entities/${entityId}/merge-from-candidate/${candidateId}` + qs(params), {
        method: "POST",
      })
    },
  },

  // ============================================================
  // 地理历史
  // ============================================================
  geo: {
    /** 获取地点列表 */
    async listLocations(params = {}) {
      return request("/geo/locations" + qs(params))
    },

    /** 获取地点树 */
    async getTree(projectId) {
      return request(`/geo/locations/tree${qs({ novel_id: projectId })}`)
    },

    /** 获取地理关系边列表 */
    async listEdges(params = {}) {
      return request("/geo/edges" + qs(params))
    },

    /** 获取简易地图（使用地点树数据） */
    async getMap(projectId) {
      // 地图数据复用地点树，前端自行渲染 ASCII 地图
      return this.getTree(projectId)
    },

    /** 获取历史时期列表 */
    async listEras(projectId) {
      return request("/geo/eras" + qs({ novel_id: projectId }))
    },

    /** 创建地点 */
    async createLocation(payload, novelId) {
      return request(`/geo/locations${qs({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    getLocationFactions: (locationId, novelId) =>
      request(`/api/geo/location/${locationId}/factions?novel_id=${encodeURIComponent(novelId)}`),

    getLocationCharacters: (locationId, novelId) =>
      request(`/api/geo/location/${locationId}/characters?novel_id=${encodeURIComponent(novelId)}`),
  },

  // ============================================================
  // 人物档案
  // ============================================================
  character: {
    /** 获取人物列表 */
    async list(params = {}) {
      return request("/characters" + qs(params))
    },

    /** 获取人物详情 */
    async get(id, novelId) {
      return request(`/characters/${id}${qs({ novel_id: novelId })}`)
    },

    /** 更新人物 */
    async update(id, payload, novelId) {
      return request(`/characters/${id}${qs({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 获取人物知识边界 */
    async listKnowledge(characterId, novelId) {
      return request(`/characters/${characterId}/knowledge${qs({ novel_id: novelId })}`)
    },

    /** 创建知识边界条目 */
    async createKnowledge(characterId, payload, novelId) {
      return request(`/characters/${characterId}/knowledge`, {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          novel_id: novelId || payload.novel_id,
          character_id: characterId,
        }),
      })
    },

    /** 更新知识边界条目 */
    async updateKnowledge(knowledgeId, payload, novelId) {
      return request(`/characters/knowledge/${knowledgeId}${qs({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 删除知识边界条目 */
    async deleteKnowledge(knowledgeId, novelId) {
      return request(`/characters/knowledge/${knowledgeId}${qs({ novel_id: novelId })}`, {
        method: "DELETE",
      })
    },

    /** 创建人物 */
    async create(payload) {
      return request("/characters", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 提交单个人物抽取任务 */
    async extract(id, novelId) {
      return request(`/characters/${id}/extract${qs({ novel_id: novelId })}`, {
        method: "POST",
      })
    },

    /** 提交所有人物的抽取任务 */
    async extractAll(novelId) {
      return request(`/characters/extract-all${qs({ novel_id: novelId })}`, {
        method: "POST",
      })
    },

    /** 获取人物的 AI 抽取建议 */
    async getSuggestions(id, novelId) {
      return request(`/characters/${id}/suggestions${qs({ novel_id: novelId })}`)
    },

    /** 应用 AI 建议到人物字段 */
    async applySuggestions(id, novelId, fields = []) {
      return request(`/characters/${id}/apply-suggestions${qs({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify({ fields }),
      })
    },
  },

  // ============================================================
  // 长期记忆
  // ============================================================
  memory: {
    /** 获取记忆记录列表 */
    async listRecords(params = {}) {
      if (!params.novel_id) throw new Error("获取记忆记录需要提供 novel_id")
      return request(`/novels/${params.novel_id}/memories/records${qs({
        skip: params.skip,
        limit: params.limit,
        memory_type: params.memory_type,
        status: params.status,
        before_chapter: params.before_chapter,
      })}`)
    },

    /** 获取记忆提案列表 */
    async listProposals(novelId, params = {}) {
      return request(`/novels/${novelId}/memories/proposals/pending${qs({
        skip: params.skip,
        limit: params.limit,
      })}`)
    },

    /** 确认记忆提案 */
    async confirmProposal(novelId, proposalId, payload) {
      return request(`/novels/${novelId}/memories/proposals/${proposalId}/decide`, {
        method: "POST",
        body: JSON.stringify({ ...payload, decision: "approved" }),
      })
    },

    /** 拒绝记忆提案 */
    async rejectProposal(novelId, proposalId, decidedBy) {
      return request(`/novels/${novelId}/memories/proposals/${proposalId}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision: "rejected", decided_by: decidedBy || "user" }),
      })
    },
  },

  // ============================================================
  // 时间线
  // ============================================================
  timeline: {
    /** 获取时间线事件列表 */
    async listEvents(params = {}) {
      if (!params.novel_id) throw new Error("获取时间线事件需要提供 novel_id")
      return request(`/novels/${params.novel_id}/timeline/events${qs({
        skip: params.skip,
        limit: params.limit,
      })}`)
    },

    /** 创建时间线事件 */
    async createEvent(payload) {
      return request(`/novels/${payload.novel_id}/timeline/events`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 更新时间线事件 */
    async updateEvent(novelId, eventId, payload) {
      return request(`/novels/${novelId}/timeline/events/${eventId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 调整事件顺序 */
    async reorder(novelId, eventId, direction) {
      // 后端的 reorder 通过 update order_index 实现
      return request(`/novels/${novelId}/timeline/events/${eventId}`, {
        method: "PUT",
        body: JSON.stringify({ order_index: direction }),
      })
    },
  },

  // ============================================================
  // 剧情结构
  // ============================================================
  outline: {
    /** 获取剧情线列表 */
    async listThreads(params = {}) {
      return request("/outline/threads" + qs(params))
    },
    /** 创建剧情线 */
    async createThread(payload, novelId) {
      return request(`/outline/threads${qs({ novel_id: novelId })}`, { method: "POST", body: JSON.stringify(payload) })
    },
    /** 删除剧情线 */
    async deleteThread(id, params = {}) {
      return request(`/outline/threads/${id}` + qs(params), { method: "DELETE" })
    },

    /** 获取篇章纲列表 */
    async listArcs(params = {}) {
      return request("/outline/arcs" + qs(params))
    },
    /** 创建篇章纲 */
    async createArc(payload, novelId) {
      return request(`/outline/arcs${qs({ novel_id: novelId })}`, { method: "POST", body: JSON.stringify(payload) })
    },
    /** 删除篇章纲 */
    async deleteArc(id, params = {}) {
      return request(`/outline/arcs/${id}` + qs(params), { method: "DELETE" })
    },

    /** 获取章节卡列表 */
    async listChapterCards(params = {}) {
      return request("/outline/chapters" + qs(params))
    },
    /** 获取章节卡详情 */
    async getChapterCard(id, novelId) {
      return request(`/outline/chapters/${id}${qs({ novel_id: novelId })}`)
    },
    /** 按章节号获取章节卡 */
    async getChapterCardByIndex(index, novelId) {
      return request(`/outline/chapters/by-index/${index}${qs({ novel_id: novelId })}`)
    },
    /** 创建章节卡 */
    async createChapterCard(payload, novelId) {
      return request(`/outline/chapters${qs({ novel_id: novelId })}`, { method: "POST", body: JSON.stringify(payload) })
    },
    /** 更新章节卡 */
    async updateChapterCard(id, payload, novelId) {
      const query = novelId ? qs({ novel_id: novelId }) : ""
      return request(`/outline/chapters/${id}${query}`, { method: "PUT", body: JSON.stringify(payload) })
    },
    /** 删除章节卡 */
    async deleteChapterCard(id, params = {}) {
      return request(`/outline/chapters/${id}` + qs(params), { method: "DELETE" })
    },

    /** 获取伏笔计划列表 */
    async listForeshadowing(params = {}) {
      return request("/outline/foreshadowing" + qs(params))
    },
    /** 创建伏笔 */
    async createForeshadowing(payload, novelId) {
      return request(`/outline/foreshadowing${qs({ novel_id: novelId })}`, { method: "POST", body: JSON.stringify(payload) })
    },
    /** 删除伏笔 */
    async deleteForeshadowing(id, params = {}) {
      return request(`/outline/foreshadowing/${id}` + qs(params), { method: "DELETE" })
    },

    /** 获取揭示计划列表 */
    async listReveals(params = {}) {
      return request("/outline/reveals" + qs(params))
    },
    /** 创建揭示计划 */
    async createReveal(payload, novelId) {
      return request(`/outline/reveals${qs({ novel_id: novelId })}`, { method: "POST", body: JSON.stringify(payload) })
    },
    /** 删除揭示计划 */
    async deleteReveal(id, params = {}) {
      return request(`/outline/reveals/${id}` + qs(params), { method: "DELETE" })
    },
  },

  // ============================================================
  // RAG 检索
  // ============================================================
  rag: {
    /** 搜索 RAG */
    async search(payload, novelId) {
      return request(`/rag/retrieve${qs({ novel_id: novelId })}`, {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 重建索引 */
    async rebuild(payload) {
      const novelId = payload?.novel_id
      if (!novelId) throw new Error("重建索引需要先选择项目")
      const chapters = await request(`/writing/chapters${qs({ novel_id: novelId })}`)
      const indices = chapters.chapter_indices || []
      const tasks = []
      for (const chapterIndex of indices) {
        tasks.push(await request("/tasks", {
          method: "POST",
          body: JSON.stringify({
            task_type: "rag_index_chapter",
            meta: { novel_id: novelId, chapter_index: chapterIndex },
          }),
        }))
      }
      return {
        status: tasks.length ? "pending" : "empty",
        total: tasks.length,
        task_ids: tasks.map((task) => task.task_id),
      }
    },

    /** 获取索引状态 */
    async status(projectId) {
      return request("/rag/chunks" + qs({ novel_id: projectId }))
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
  // 结构复查
  // ============================================================
  review: {
    /** 运行复查 */
    async run(payload) {
      return request("/review", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 获取复查报告列表 */
    async listReports(params = {}) {
      return request("/review" + qs(params))
    },

    /** 获取复查报告详情 */
    async getReport(id, novelId) {
      return request(`/review/${id}${qs({ novel_id: novelId })}`)
    },
  },

  // ============================================================
  // 草稿
  // ============================================================
  writing: {
    /** 获取章节草稿 */
    async getDraft(chapterIndex, novelId) {
      return request(`/writing/chapters/${chapterIndex}/draft${qs({ novel_id: novelId })}`)
    },

    /** 保存草稿 */
    async saveDraft(payload) {
      return request("/writing/drafts", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 导出 */
    async export(payload) {
      // 导出功能通过 API 或直接生成
      return request("/writing/drafts" + qs(payload))
    },

    /** 获取有草稿的章节索引列表 */
    async listChapters(novelId) {
      return request(`/writing/chapters${qs({ novel_id: novelId })}`)
    },

    /** 更新草稿状态 */
    async updateDraftStatus(draftId, status, novelId) {
      return request(`/writing/drafts/${draftId}${qs({ novel_id: novelId })}`, {
        method: "PUT",
        body: JSON.stringify({ status }),
      })
    },

    async saveAndAnalyze(novelId, chapterIndex, content) {
      return request("/api/writing/save-and-analyze", {
        method: "POST",
        body: JSON.stringify({ novel_id: novelId, chapter_index: chapterIndex, content }),
      })
    },

    /** 获取章节版本历史 */
    async getVersionHistory(chapterIndex, novelId) {
      return request(`/writing/chapters/${chapterIndex}/versions${qs({ novel_id: novelId })}`)
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

    /** 结构复查与状态抽取 */
    async reviewMemory(payload) {
      return request("/review", {
        method: "POST",
        body: JSON.stringify({
          novel_id: payload.novel_id,
          target_type: "chapter_cards",
          candidate_payload: payload,
        }),
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
      return request("/imports" + qs(params))
    },

    /** 获取导入记录详情 */
    async get(recordId, params = {}) {
      return request(`/imports/${recordId}` + qs(params))
    },

    /** 提交深度导入任务 */
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

    /** 继续深度导入（在用户确认候选后） */
    async resumeDeepImport(taskId) {
      return request("/imports/deep/resume", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({task_id: taskId}),
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

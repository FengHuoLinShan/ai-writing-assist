/**
 * API 封装 — 与后端 REST API 通信
 *
 * 基础 URL 可配置，统一错误处理，超时控制。
 * 所有函数返回 Promise<Object>。
 */

const API_BASE_URL = "http://localhost:8000/api"
const API_TIMEOUT = 15000

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

  // 只在 POST/PUT/PATCH 请求时添加 Content-Type
  const method = (options.method || "GET").toUpperCase()
  if (method !== "GET" && method !== "DELETE") {
    headers["Content-Type"] = "application/json"
  }

  try {
    const resp = await fetch(url, {
      ...options,
      headers: { ...headers, ...options.headers },
      signal: controller.signal,
    })

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
      let detail = ""
      try {
        const errBody = await resp.json()
        detail = errBody.detail || errBody.message || ""
      } catch {}

      const msg = errorMap[resp.status] || `请求失败 (${resp.status})`
      throw new Error(detail ? `${msg}：${detail}` : msg)
    }

    // 204 No Content
    if (resp.status === 204) {
      return null
    }

    return await resp.json()
  } catch (err) {
    clearTimeout(timeoutId)

    if (err.name === "AbortError") {
      throw new Error("请求超时，请检查后端服务是否运行")
    }

    // 网络错误
    if (err.message === "Failed to fetch" || err.message.includes("fetch")) {
      throw new Error("无法连接到后端服务，请确认后端已启动")
    }

    throw err
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
    async getEntity(id) {
      return request(`/world/entities/${id}`)
    },

    /** 创建世界对象 */
    async createEntity(payload) {
      return request("/world/entities", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 更新世界对象 */
    async updateEntity(id, payload) {
      return request(`/world/entities/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 删除世界对象 */
    async deleteEntity(id) {
      return request(`/world/entities/${id}`, { method: "DELETE" })
    },

    /** 获取候选对象列表 */
    async listCandidates(params = {}) {
      return request("/world/candidates" + qs(params))
    },

    /** 对候选对象进行去重检查 */
    async dedupCandidate(id) {
      return request(`/world/candidates/${id}/dedup`, { method: "POST" })
    },

    /** 确认候选对象（晋升正史） */
    async confirmCandidate(id, actionPayload) {
      return request(`/world/candidates/${id}`, {
        method: "PUT",
        body: JSON.stringify(actionPayload),
      })
    },

    /** 获取关系列表 */
    async listRelationships(entityId) {
      const params = entityId ? { source_id: entityId, target_id: entityId } : {}
      return request("/world/relationships" + qs(params))
    },

    /** 创建关系 */
    async createRelationship(payload) {
      return request("/world/relationships", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 获取别名列表 */
    async listAliases(entityId) {
      return request("/world/aliases" + qs({ entity_id: entityId }))
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
    async listEdges(locationId) {
      return request("/geo/edges" + qs({ location_id: locationId }))
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
    async createLocation(payload) {
      return request("/geo/locations", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },
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
    async get(id) {
      return request(`/characters/${id}`)
    },

    /** 更新人物 */
    async update(id, payload) {
      return request(`/characters/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 获取人物知识边界 */
    async listKnowledge(characterId) {
      return request(`/characters/${characterId}/knowledge`)
    },

    /** 创建人物 */
    async create(payload) {
      return request("/characters", {
        method: "POST",
        body: JSON.stringify(payload),
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

    /** 获取篇章纲列表 */
    async listArcs(params = {}) {
      return request("/outline/arcs" + qs(params))
    },

    /** 获取章节卡列表 */
    async listChapterCards(params = {}) {
      return request("/outline/chapters" + qs(params))
    },

    /** 获取章节卡详情 */
    async getChapterCard(id) {
      return request(`/outline/chapters/${id}`)
    },

    /** 更新章节卡 */
    async updateChapterCard(id, payload) {
      return request(`/outline/chapters/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      })
    },

    /** 获取伏笔计划列表 */
    async listForeshadowing(params = {}) {
      return request("/outline/foreshadowing" + qs(params))
    },

    /** 获取揭示计划列表 */
    async listReveals(params = {}) {
      return request("/outline/reveals" + qs(params))
    },
  },

  // ============================================================
  // RAG 检索
  // ============================================================
  rag: {
    /** 搜索 RAG */
    async search(payload) {
      return request("/rag/retrieve", {
        method: "POST",
        body: JSON.stringify(payload),
      })
    },

    /** 重建索引 */
    async rebuild(payload) {
      return request("/rag/chunks/split", {
        method: "POST",
        body: JSON.stringify(payload),
      })
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
    async getReport(id) {
      return request(`/review/${id}`)
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
  },

  // ============================================================
  // 生成中心
  // ============================================================
  generate: {
    /** 生成世界与人物结构 */
    async worldCharacter(payload) {
      // 需要调用 LLM，目前先返回任务创建
      return request("/tasks", {
        method: "POST",
        body: JSON.stringify({ task_type: "world_structure_generate", meta: payload }),
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
        body: JSON.stringify({ task_type: "chapter_scene_generate", meta: payload }),
      })
    },

    /** 结构复查与状态抽取 */
    async reviewMemory(payload) {
      return request("/tasks", {
        method: "POST",
        body: JSON.stringify({ task_type: "memory_extract", meta: payload }),
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
}

// 导出到全局
window.api = api

/**
 * api/projects.js — api.projects 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  deleteRequest,
  contractFetch,
  contractJson,
} from "./_shared.js"

  // ============================================================
  // 项目
  // ============================================================

export const projects = {
    editorialBrief: (id) => request(`/projects/${encodeURIComponent(id)}/editorial-brief`, { cache: "no-store" }),
    saveEditorialBrief: (id, body) => request(`/projects/${encodeURIComponent(id)}/editorial-brief`, { method: "PUT", body: JSON.stringify(body) }),
    editorialBriefForWriting: (id) => request(`/projects/${encodeURIComponent(id)}/editorial-brief/for-writing`, { cache: "no-store" }),
    aiUsage: (id, days = 30) => request(withQuery(`/projects/${encodeURIComponent(id)}/ai-usage`, { days }), { cache: "no-store" }),
    setEditorialBriefForWriting: (id, enabled) => request(`/projects/${encodeURIComponent(id)}/editorial-brief/for-writing`, { method: "PUT", body: JSON.stringify({ enabled }) }),
    authorExamples: (id) => request(`/projects/${encodeURIComponent(id)}/author-examples`, { cache: "no-store" }),
    saveAuthorExamples: (id, body) => request(`/projects/${encodeURIComponent(id)}/author-examples`, { method: "PUT", body: JSON.stringify(body) }),
    authorExamplesForWriting: (id) => request(`/projects/${encodeURIComponent(id)}/author-examples/for-writing`, { cache: "no-store" }),
    llmCostSaving: (id) => request(`/projects/${encodeURIComponent(id)}/llm-cost-saving`, { cache: "no-store" }),
    setLLMCostSaving: (id, enabled) => request(`/projects/${encodeURIComponent(id)}/llm-cost-saving`, { method: "PUT", body: JSON.stringify({ enabled }) }),
    setAuthorExamplesForWriting: (id, enabled) => request(`/projects/${encodeURIComponent(id)}/author-examples/for-writing`, { method: "PUT", body: JSON.stringify({ enabled }) }),
    demoCopy: () => post("/projects/demo-copy", undefined, { cache: "no-store" }),
    async smartDedupReviewState(id, taskId) { return request(`/projects/${encodeURIComponent(id)}/smart-dedup/scans/${encodeURIComponent(taskId)}/review-state`) },
    async recentSmartDedupScans(id) { return request(`/projects/${encodeURIComponent(id)}/smart-dedup/scans`) },
    async list() {
      return contractFetch("projects.list")
    },

    async create(payload) {
      return contractJson("projects.create", {}, {}, payload)
    },

    async get(id, options = {}) {
      return contractFetch("projects.get", { id }, {}, options)
    },

    async getWorkspaceSummary(id, query = {}, options = {}) {
      return contractFetch("projects.getWorkspaceSummary", { id }, query, options)
    },

    async listAuthorTasks(id, query = {}, options = {}) {
      return contractFetch("projects.listAuthorTasks", { id }, query, options)
    },

    async createAuthorTask(id, payload, options = {}) {
      return contractJson("projects.createAuthorTask", { id }, {}, payload, options)
    },

    async patchAuthorTask(id, taskId, payload, options = {}) {
      return contractJson("projects.patchAuthorTask", { id, taskId }, {}, payload, options)
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
};

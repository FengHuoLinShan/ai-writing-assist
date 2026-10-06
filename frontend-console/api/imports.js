/**
 * api/imports.js — api.imports 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  put,
  deleteRequest,
  uploadMultipart,
  uploadImportFile,
  contractFetch,
  contractJson,
} from "./_shared.js"

  // ============================================================
  // 导入
  // ============================================================

export const imports = {
    async reviewSummary(novelId) { return request(withQuery('/imports/review-summary', { novel_id: novelId })) },
    async decideReview(taskId, novelId, payload) { return post(withQuery(`/imports/review-resolutions/${taskId}/decisions`, { novel_id: novelId }), payload) },
    async applyReviewSceneGroup(taskId, groupKey, novelId, payload) { return post(withQuery(`/imports/review-resolutions/${taskId}/scene-groups/${groupKey}/apply`, { novel_id: novelId }), payload) },
    async resolveReview(payload) { return post('/imports/review-resolutions', payload) },
    async rollbackReviewResolution(taskId, novelId) { return post(withQuery(`/imports/review-resolutions/${taskId}/rollback`, { novel_id: novelId }), { confirmed: true }) },
    async workflowImpact(novelId, assetId) { return request(withQuery('/imports/workflows/impact', { novel_id: novelId, asset_id: assetId })) },
    async recentWorkflows(novelId, skip = 0) { return request(withQuery('/imports/workflows/recent', { novel_id: novelId, skip, limit: 20 })) },
    async previewCancelledCleanup(taskId, novelId) {
      return contractFetch("imports.previewCancelledCleanup", { taskId }, { novel_id: novelId })
    },
    async cleanupCancelled(taskId, payload) {
      return contractJson("imports.cleanupCancelled", { taskId }, {}, payload)
    },
    async deferTargetedCompletion(taskId) { return post(`/imports/targeted-completions/${taskId}/defer`, {}) },

    async targetedCompletion(payload) {
      return post("/imports/targeted-completions", payload)
    },

    async rollbackTargetedCompletion(taskId, novelId) {
      return post(withQuery(`/imports/targeted-completions/${taskId}/rollback`, { novel_id: novelId }), { confirmed: true })
    },

    async uploadFile(file, novelId, onProgress = null, options = {}) {
      return uploadImportFile(file, novelId, onProgress, options)
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
        ...(authorization.review_resolution?.enabled ? { review_resolution: authorization.review_resolution } : {}),
        ...(authorization.targeted_completion?.enabled ? { targeted_completion: { enabled: true } } : {}),
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
        ...(authorization.review_resolution?.enabled ? { review_resolution: authorization.review_resolution } : {}),
        ...(authorization.targeted_completion?.enabled ? { targeted_completion: { enabled: true } } : {}),
      })
    },

    async resumeDeepImport(taskId, options = {}) {
      return contractJson("imports.resumeDeepImport", {}, {}, { task_id: taskId, ...options })
    },

    async abandonDeepImport(taskId) {
      return contractJson("imports.abandonDeepImport", {}, {}, { task_id: taskId })
    },

    migrations: {
      async create(novelId, files, onProgress = null, options = {}) {
        const formData = new FormData()
        formData.append("novel_id", novelId)
        for (const file of Array.from(files || [])) {
          formData.append("files", file, file.name)
        }
        return uploadMultipart("/imports/migrations", formData, onProgress, options)
      },
      async list(params = {}) {
        return request(withQuery("/imports/migrations", params))
      },
      async get(sessionId, params = {}) {
        return request(withQuery(`/imports/migrations/${sessionId}`, params))
      },
      async rows(sessionId, params = {}) {
        return request(withQuery(`/imports/migrations/${sessionId}/rows`, params))
      },
      async saveMapping(sessionId, payload) {
        return put(`/imports/migrations/${sessionId}/mapping`, payload)
      },
      async startAi(sessionId, payload) {
        return contractJson("imports.migrations.startAi", { sessionId }, {}, payload)
      },
      async saveDecisions(sessionId, payload) {
        return put(`/imports/migrations/${sessionId}/decisions`, payload)
      },
      async rollbackPreview(sessionId, params = {}) {
        return request(withQuery(`/imports/migrations/${sessionId}/rollback-preview`, params))
      },
      async apply(sessionId, payload) {
        return contractJson("imports.migrations.apply", { sessionId }, {}, payload)
      },
      async rollback(sessionId, payload) {
        return contractJson("imports.migrations.rollback", { sessionId }, {}, payload)
      },
      async remove(sessionId, params = {}) {
        return deleteRequest(withQuery(`/imports/migrations/${sessionId}`, params))
      },
    },
};

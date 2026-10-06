/**
 * api/rag.js — api.rag 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  contractJson,
} from "./_shared.js"

  // ============================================================
  // RAG 检索
  // ============================================================

export const rag = {
    async search(payload, novelId, options = {}) {
      return contractJson("rag.search", {}, { novel_id: novelId }, payload, options)
    },

    async rebuild(payload, options = {}) {
      const { novel_id, content_mode, start_chapter, end_chapter } = payload || {}
      if (!novel_id) throw new Error("重建索引需要先选择项目")
      return post("/evidence/indexing/rebuild", { novel_id, content_mode, start_chapter, end_chapter }, options)
    },

    async prewarm(options = {}) {
      return contractJson("rag.prewarm", {}, {}, {}, options)
    },

    async retryEmbeddings(payload, options = {}) {
      const { novel_id, start_chapter, end_chapter, statuses } = payload || {}
      if (!novel_id) throw new Error("重试失败向量需要先选择项目")
      return post("/evidence/indexing/retry-embeddings", { novel_id, start_chapter, end_chapter, statuses }, options)
    },

    async status(projectId) {
      return request(withQuery("/evidence/indexing/chunks", { novel_id: projectId }))
    },

    async metrics() {
      return request("/evidence/indexing/metrics")
    },
};

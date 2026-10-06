/**
 * api/writing.js — api.writing 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  patch,
  deleteRequest,
  contractFetch,
  contractJson,
} from "./_shared.js"

  // ============================================================
  // 草稿
  // ============================================================

export const writing = {
    markEditorialReady: (draftId, novelId, expectedContentHash) => post(withQuery(`/writing/drafts/${encodeURIComponent(draftId)}/editorial-ready`, { novel_id: novelId }), { expected_content_hash: expectedContentHash }),
    authorExampleStats: (novelId, days = 30) => request(withQuery(`/writing/author-example-stats/${encodeURIComponent(novelId)}`, { days }), { cache: "no-store" }),
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

    async regenerationContext(draftId, novelId) {
      return request(withQuery(`/writing/drafts/${draftId}/regeneration-context`, { novel_id: novelId }))
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

    async generate(payload) {
      return contractJson("writing.generate", {}, {}, payload)
    },

    semanticReviewResult: (novelId, taskId) => request(withQuery(`/writing/semantic-reviews/${taskId}`, { novel_id: novelId }), { cache: "no-store" }),

    async semanticReview(payload) {
      return contractJson("writing.semanticReview", {}, {}, payload)
    },

    async targetedRevision(payload) {
      return contractJson("writing.targetedRevision", {}, {}, payload)
    },

    exportAdopted: (novelId, format, chapterIndex = null) => request(withQuery("/writing/export", {
      novel_id: novelId,
      format,
      ...(chapterIndex ? { chapter_index: chapterIndex } : {}),
    }), { cache: "no-store", _responseType: "blob", timeout: 120000 }),

    listComments: (draftId, novelId) => contractFetch("writing.listComments", { draftId }, { novel_id: novelId }),
    createComment: (draftId, payload) => contractJson("writing.createComment", { draftId }, {}, payload),
    updateComment: (commentId, payload) => contractJson("writing.updateComment", { commentId }, {}, payload),
    runComments: (payload) => contractJson("writing.runComments", {}, {}, payload),

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

    async confirmContinuity(itemId, payload) {
      return contractJson("writing.confirmContinuity", { itemId }, {}, payload)
    },

    async enqueueConflictAiReview(checkId, payload) {
      return contractJson("writing.enqueueConflictAiReview", { checkId }, {}, payload)
    },

    async enqueueConflictAiSuggestion(itemId, payload) {
      return contractJson("writing.enqueueConflictAiSuggestion", { itemId }, {}, payload)
    },

};

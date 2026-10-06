/**
 * api/context.js — api.context 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  patch,
  contractFetch,
  contractJson,
} from "./_shared.js"

  // ============================================================
  // 上下文
  // ============================================================

export const context = {
    async startFocusedSearch(payload) {
      return post("/evidence/compilation/focused-search", payload)
    },

    async getFocusedSearch(taskId, novelId) {
      return request(withQuery(`/evidence/compilation/focused-search/${taskId}`, { novel_id: novelId }), { cache: "no-store" })
    },

    async resumeFocusedSearch(taskId, novelId) {
      return post(withQuery(`/evidence/compilation/focused-search/${taskId}/resume`, { novel_id: novelId }), {})
    },

    async grepEvidence(payload, options = {}) {
      return contractJson("context.grepEvidence", {}, {}, payload, options)
    },

    async searchEvidence(payload, options = {}) {
      return contractJson("context.searchEvidence", {}, {}, payload, options)
    },

    async readEvidence(payload, options = {}) {
      return contractJson("context.readEvidence", {}, {}, payload, options)
    },

    async inspectEvidence(payload, options = {}) {
      return post("/evidence/compilation/evidence/inspect", payload, options)
    },

    async traceEvidence(payload, options = {}) {
      return post("/evidence/compilation/evidence/trace", payload, options)
    },

    async compile(payload, options = {}) {
      return contractJson("context.compile", {}, {}, payload, options)
    },

    async render(payload, options = {}) {
      return contractJson("context.render", {}, {}, payload, options)
    },

    async sceneLens(payload, options = {}) {
      return contractJson("context.sceneLens", {}, {}, payload, options)
    },

    async confirm(payload) {
      return contractJson("context.confirm", {}, {}, payload)
    },

    async getConfirmation(confirmationId, novelId) {
      return contractFetch("context.getConfirmation", { confirmationId }, { novel_id: novelId }, { cache: "no-store" })
    },

    async proposeSelection(payload, options = {}) {
      return contractJson("context.proposeSelection", {}, {}, payload, options)
    },

    async listSnapshots(params = {}) {
      return contractFetch("context.listSnapshots", {}, params)
    },

    async getSnapshot(snapshotId, params = {}) {
      return contractFetch("context.getSnapshot", { snapshotId }, params)
    },

    async previewActivationProfile(payload) {
      return post("/evidence/compilation/activation-preview", payload)
    },

    async listActivationProfiles(novelId, includeArchived = false) {
      return request(withQuery("/evidence/compilation/activation-profiles", {
        novel_id: novelId,
        include_archived: includeArchived,
      }))
    },

    async createActivationProfile(payload) {
      return post("/evidence/compilation/activation-profiles", payload)
    },

    async updateActivationProfile(profileId, payload, novelId) {
      return patch(withQuery(`/evidence/compilation/activation-profiles/${profileId}`, {
        novel_id: novelId,
      }), payload)
    },

    async publishActivationProfile(profileId, payload, novelId) {
      return post(withQuery(`/evidence/compilation/activation-profiles/${profileId}/publish`, {
        novel_id: novelId,
      }), payload)
    },

    async listActivationProfileRevisions(profileId, novelId) {
      return request(withQuery(`/evidence/compilation/activation-profiles/${profileId}/revisions`, {
        novel_id: novelId,
      }))
    },

    async restoreActivationProfileRevision(profileId, version, payload, novelId) {
      return post(withQuery(
        `/evidence/compilation/activation-profiles/${profileId}/revisions/${version}/restore-draft`,
        { novel_id: novelId },
      ), payload)
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
};

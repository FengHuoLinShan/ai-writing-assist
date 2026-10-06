/**
 * api/generate.js — api.generate 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  put,
  deleteRequest,
  contractFetch,
  contractJson,
} from "./_shared.js"

  // ============================================================
  // 生成中心
  // ============================================================

export const generate = {
    async listPromptTemplates(novelId, options = {}) {
      return request(withQuery("/world/generation-prompt-templates", {
        novel_id: novelId,
        include_archived: options.include_archived || false,
      }))
    },

    async createPromptTemplate(payload) {
      return post("/world/generation-prompt-templates", payload)
    },

    async updatePromptTemplate(templateId, novelId, payload) {
      return put(withQuery(`/world/generation-prompt-templates/${templateId}`, { novel_id: novelId }), payload)
    },

    async archivePromptTemplate(templateId, novelId) {
      return deleteRequest(withQuery(`/world/generation-prompt-templates/${templateId}`, { novel_id: novelId }))
    },

    async copyPromptTemplate(templateId, payload) {
      return post(`/world/generation-prompt-templates/${templateId}/copy`, payload)
    },

    async listPromptTemplateRevisions(templateId, novelId) {
      return contractFetch("generate.listPromptTemplateRevisions", { templateId }, { novel_id: novelId })
    },

    async worldChat(payload, options = {}) {
      return contractJson("generate.worldChat", {}, {}, payload, options)
    },

    async convergeWorld(payload, options = {}) {
      return contractJson("generate.convergeWorld", {}, {}, payload, options)
    },

    async exploreWorld(payload, options = {}) {
      return contractJson("generate.exploreWorld", {}, {}, payload, options)
    },

    async inspectWorldPage(payload, options = {}) {
      return contractJson("generate.inspectWorldPage", {}, {}, payload, options)
    },

    async askWorld(payload, options = {}) {
      return contractJson("generate.askWorld", {}, {}, payload, options)
    },

    async openAskWorldCitation(payload, options = {}) {
      return contractJson("generate.openAskWorldCitation", {}, {}, payload, options)
    },

    async saveAskWorldSuggestion(payload, options = {}) {
      return contractJson("generate.saveAskWorldSuggestion", {}, {}, payload, options)
    },

    async generateWorldSuggestion(payload, options = {}) {
      return contractJson("generate.generateWorldSuggestion", {}, {}, payload, options)
    },

    async enqueueWorldSuggestion(payload) {
      return contractJson("generate.enqueueWorldSuggestion", {}, {}, payload)
    },

    async applyWorldPageDraft(suggestionId, payload, novelId, options = {}) {
      return contractJson(
        "generate.applyWorldPageDraft",
        { suggestionId },
        { novel_id: novelId },
        payload,
        options,
      )
    },
};

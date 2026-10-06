/**
 * api/outline.js — api.outline 命名空间（AO-13 自 api.js 按命名空间拆分）。
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
  // 大纲
  // ============================================================

export const outline = {
    async getStoryOutline(novelId) {
      return contractFetch("outline.getStoryOutline", {}, { novel_id: novelId })
    },

    async listStoryOutlineRevisions(novelId, skip = 0, limit = 20) {
      return contractFetch(
        "outline.listStoryOutlineRevisions",
        {},
        { novel_id: novelId, skip, limit },
      )
    },

    async getStoryOutlineRevision(revisionId, novelId) {
      return contractFetch(
        "outline.getStoryOutlineRevision",
        { revisionId },
        { novel_id: novelId },
      )
    },

    async createStoryOutlineRevision(novelId, payload) {
      return contractJson(
        "outline.createStoryOutlineRevision",
        {},
        { novel_id: novelId },
        payload,
      )
    },

    async restoreStoryOutlineRevision(revisionId, novelId, payload) {
      return contractJson(
        "outline.restoreStoryOutlineRevision",
        { revisionId },
        { novel_id: novelId },
        payload,
      )
    },

    async generateStoryOutline(payload) {
      return contractJson("outline.generateStoryOutline", {}, {}, payload)
    },

    async applyStoryOutlinePreview(payload) {
      return contractJson("outline.applyStoryOutlinePreview", {}, {}, payload)
    },

    async listThreads(novelId, params = {}) {
      return request(withQuery("/outline/threads", { novel_id: novelId, ...params }))
    },

    async getThread(threadId, novelId) {
      return request(withQuery(`/outline/threads/${threadId}`, { novel_id: novelId }))
    },

    async createThread(novelId, data) {
      return post(withQuery("/outline/threads", { novel_id: novelId }), data)
    },

    async updateThread(threadId, novelId, data) {
      return patch(withQuery(`/outline/threads/${threadId}`, { novel_id: novelId }), data)
    },

    async deleteThread(threadId, novelId) {
      return deleteRequest(withQuery(`/outline/threads/${threadId}`, { novel_id: novelId }))
    },

    async listArcs(novelId, params = {}) {
      return request(withQuery("/outline/arcs", { novel_id: novelId, ...params }))
    },

    async getArc(arcId, novelId) {
      return request(withQuery(`/outline/arcs/${arcId}`, { novel_id: novelId }))
    },

    async createArc(novelId, data) {
      return post(withQuery("/outline/arcs", { novel_id: novelId }), data)
    },
    async updateArc(arcId, novelId, data) {
      return patch(withQuery(`/outline/arcs/${arcId}`, { novel_id: novelId }), data)
    },
    async deleteArc(arcId, novelId) {
      return deleteRequest(withQuery(`/outline/arcs/${arcId}`, { novel_id: novelId }))
    },

    async analyze(payload) {
      return contractJson("outline.analyze", {}, {}, payload)
    },

    async generate(payload) {
      return contractJson("outline.generate", {}, {}, payload)
    },

    async applyStructurePreview(payload) {
      return contractJson("outline.applyStructurePreview", {}, {}, payload)
    },

    // ---- Scene 卡 ----
    async listScenes(novelId, skip = 0, limit = 50) {
      return request(withQuery("/outline/scenes", { novel_id: novelId, skip, limit }))
    },
    async getScene(sceneId, novelId) {
      return request(withQuery(`/outline/scenes/${sceneId}`, { novel_id: novelId }))
    },
    async createScene(novelId, data) {
      return post(withQuery("/outline/scenes", { novel_id: novelId }), data)
    },
    async updateScene(sceneId, novelId, data) {
      return patch(withQuery(`/outline/scenes/${sceneId}`, { novel_id: novelId }), data)
    },
    async deleteScene(sceneId, novelId) {
      return deleteRequest(withQuery(`/outline/scenes/${sceneId}`, { novel_id: novelId }))
    },
    async listScenesOrdered(novelId) {
      return request(withQuery("/outline/scenes/ordered", { novel_id: novelId }))
    },
    async listScenesByChapter(novelId, chapterIndex) {
      return request(withQuery("/outline/scenes/by-chapter", { novel_id: novelId, chapter_index: chapterIndex }))
    },
    async reorderScenes(novelId, sceneIds) {
      return post(withQuery("/outline/scenes/reorder", { novel_id: novelId }), { scene_ids: sceneIds })
    },
    async splitChapters(novelId, chapterIndex, targetSceneId) {
      return post(withQuery("/outline/scenes/split", { novel_id: novelId }), { chapter_index: chapterIndex, target_scene_id: targetSceneId || null })
    },
    async getSceneWorkbench(novelId, selectedSceneId = null, params = {}) {
      return request(withQuery("/outline/scene-workbench", {
        novel_id: novelId,
        selected_scene_id: selectedSceneId,
        ...params,
      }))
    },
    async updateSceneWorkbenchMapping(novelId, sceneId, data) {
      return patch(withQuery(`/outline/scene-workbench/scenes/${sceneId}/mapping`, { novel_id: novelId }), data)
    },
    async associateSceneWithChapter(novelId, chapterIndex, sceneId) {
      return post(withQuery(`/outline/scene-workbench/chapters/${chapterIndex}/scenes/${sceneId}`, { novel_id: novelId }))
    },
    async createSceneForChapter(novelId, chapterIndex, title) {
      return post(withQuery(`/outline/scene-workbench/chapters/${chapterIndex}/scenes`, { novel_id: novelId }), { title })
    },
    async reviewSceneWorkbench(novelId, data) {
      return post(withQuery("/outline/scene-workbench/review", { novel_id: novelId }), data)
    },
    async reviewSceneSourceMappings(novelId, data) {
      return post(withQuery("/outline/scene-workbench/source-mapping/review", { novel_id: novelId }), data)
    },
    async previewSceneMerge(novelId, data) {
      return post(withQuery("/outline/scene-workbench/merge/preview", { novel_id: novelId }), data)
    },
    async mergeScenes(novelId, data) {
      return post(withQuery("/outline/scene-workbench/merge", { novel_id: novelId }), data)
    },
    async previewSceneFusion(novelId, data) {
      return contractJson(
        "outline.previewSceneFusion",
        {},
        { novel_id: novelId },
        data,
      )
    },
    async previewSceneFusionTask(novelId, data) {
      return contractJson(
        "outline.previewSceneFusionTask",
        {},
        { novel_id: novelId },
        data,
      )
    },
    async saveSceneFusion(novelId, data) {
      return post(withQuery("/outline/scene-workbench/fusion/save", { novel_id: novelId }), data)
    },
    async listFusionSuggestions(novelId, params = {}) {
      return request(withQuery("/outline/scene-workbench/fusion-suggestions", { novel_id: novelId, ...params }))
    },
    async dismissFusionSuggestions(novelId, data) {
      return post(withQuery("/outline/scene-workbench/fusion-suggestions/dismiss", { novel_id: novelId }), data)
    },
    async applySceneReplacement(novelId, data) {
      return post(withQuery("/outline/scene-workbench/replacement-suggestions/apply", { novel_id: novelId }), data)
    },
    async previewSceneSplit(novelId, data) {
      return post(withQuery("/outline/scene-workbench/split/preview", { novel_id: novelId }), data)
    },
    async splitScene(novelId, data) {
      return post(withQuery("/outline/scene-workbench/split", { novel_id: novelId }), data)
    },

    async listForeshadowing(novelId, params = {}) {
      return request(withQuery("/outline/foreshadowing", { novel_id: novelId, ...params }))
    },
    async createForeshadowing(novelId, payload) {
      return post(withQuery("/outline/foreshadowing", { novel_id: novelId }), payload)
    },
    async updateForeshadowing(id, novelId, payload) {
      return patch(withQuery(`/outline/foreshadowing/${id}`, { novel_id: novelId }), payload)
    },
    async deleteForeshadowing(id, novelId) {
      return deleteRequest(withQuery(`/outline/foreshadowing/${id}`, { novel_id: novelId }))
    },
    async listReveals(novelId, params = {}) {
      return request(withQuery("/outline/reveals", { novel_id: novelId, ...params }))
    },
    async createReveal(novelId, payload) {
      return post(withQuery("/outline/reveals", { novel_id: novelId }), payload)
    },
    async updateReveal(id, novelId, payload) {
      return patch(withQuery(`/outline/reveals/${id}`, { novel_id: novelId }), payload)
    },
    async deleteReveal(id, novelId) {
      return deleteRequest(withQuery(`/outline/reveals/${id}`, { novel_id: novelId }))
    },
};

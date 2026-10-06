/**
 * api/story.js — api.story 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
} from "./_shared.js"

  // ============================================================
  // Story 场景辅助（人物卡、推演候选与场景脚本）
  // ============================================================
  // Story 端点保持在 API facade 内；页面只通过 bridge 读取这一组方法。
  // 页面只消费作者可见的卡片、预览任务与剧本版本契约。

export const story = {
    startRehearsal: (sceneId, payload) => post(`/story/scenes/${sceneId}/rehearsals`, payload),
    replayRehearsal: (novelId, runId) => post(withQuery(`/story/rehearsals/${runId}/replay`, { novel_id: novelId })),
    rehearsal: (novelId, runId, actorId = null) => request(withQuery(`/story/rehearsals/${runId}`, { novel_id: novelId, actor_id: actorId }), { cache: "no-store" }),
    forkRehearsal: (runId, payload) => post(`/story/rehearsals/${runId}/forks`, payload),
    async getSceneContext(novelId, sceneId) {
      return request(withQuery(`/story/scenes/${sceneId}/story-context`, { novel_id: novelId }))
    },
    async listCharacterCards(novelId, sceneId, params = {}) {
      return request(withQuery("/story/character-cards", { novel_id: novelId, scene_id: sceneId, ...params }))
    },
    async getCharacterCard(characterId, novelId) {
      return request(withQuery(`/story/character-cards/${characterId}`, { novel_id: novelId }))
    },
    async startSceneSimulation(novelId, sceneId, payload = {}) {
      return post("/story/tasks/one-click", { novel_id: novelId, scene_id: sceneId, ...payload })
    },
    async listSceneScripts(novelId, sceneId, params = {}) {
      return request(withQuery(`/story/scenes/${sceneId}/script-files`, { novel_id: novelId, ...params }))
    },
    async createSceneScriptFile(novelId, sceneId, payload = {}) {
      return post(`/story/scenes/${sceneId}/script-files`, {
        novel_id: novelId,
        scene_id: sceneId,
        confirmed: true,
        ...payload,
      })
    },
    async saveSceneScript(novelId, sceneId, payload = {}) {
      return post(`/story/scenes/${sceneId}/script-revisions`, { novel_id: novelId, scene_id: sceneId, ...payload })
    },
    async listCharacterCardRevisions(cardId, novelId) {
      return request(withQuery(`/story/character-cards/${cardId}/revisions`, { novel_id: novelId }))
    },
    async saveCharacterCard(novelId, sceneId, characterId, payload = {}) {
      const path = payload.card_id
        ? `/story/character-cards/${payload.card_id}/revisions`
        : "/story/character-cards"
      const { card_id: _cardId, ...body } = payload
      return post(path, {
        novel_id: novelId,
        scene_id: sceneId,
        character_id: characterId,
        ...body,
      })
    },
    async restoreCharacterCardRevision(cardId, novelId, payload = {}) {
      return post(`/story/character-cards/${cardId}/restore`, { novel_id: novelId, ...payload })
    },
    async startCharacterCardTask(payload = {}) {
      return post("/story/tasks/character-card", payload)
    },
    async startReactionTask(payload = {}) {
      return post("/story/tasks/reaction", payload)
    },
    async startScriptTask(payload = {}) {
      return post("/story/tasks/script", payload)
    },
    async startOneClickTask(payload = {}) {
      return post("/story/tasks/one-click", { ...payload, submit_authorized: true })
    },
    async listSceneScriptRevisions(fileId, novelId) {
      return request(withQuery(`/story/script-files/${fileId}/revisions`, { novel_id: novelId }))
    },
    async getSceneScriptFile(fileId, novelId) {
      return request(withQuery(`/story/script-files/${fileId}`, { novel_id: novelId }))
    },
    async adoptSceneScriptRevision(fileId, revisionId, novelId, expectedRevisionId = null) {
      return post(`/story/script-files/${fileId}/revisions/${revisionId}/adopt`, {
        novel_id: novelId,
        expected_revision_id: expectedRevisionId,
        confirmed: true,
      })
    },
    async unadoptSceneScriptFile(fileId, novelId, expectedRevisionId) {
      return post(`/story/script-files/${fileId}/unadopt`, {
        novel_id: novelId,
        expected_revision_id: expectedRevisionId,
        confirmed: true,
      })
    },
    async archiveSceneScriptRevision(fileId, revisionId, novelId) {
      return post(`/story/script-files/${fileId}/revisions/${revisionId}/archive`, {
        novel_id: novelId,
        confirmed: true,
      })
    },
};

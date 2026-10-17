/**
 * api/story.js — api.story 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  patch,
  put,
} from "./_shared.js"

  // ============================================================
  // Story 场景辅助（人物卡、推演候选与场景脚本）
  // ============================================================
  // Story 端点保持在 API facade 内；页面只通过 bridge 读取这一组方法。
  // 页面只消费作者可见的卡片、预览任务与剧本版本契约。

export const story = {
    compareSceneStateTrial: (novelId, payload) => post(`/novels/${novelId}/memories/scene-state-trial`, payload),
    sceneCheckpoints: (novelId, sceneId) => request(withQuery(`/novels/${novelId}/memories/scene-checkpoints`, { scene_id: sceneId }), { cache: "no-store" }),
    sceneCheckpointRecord: (novelId, checkpointId) => request(`/novels/${novelId}/memories/scene-checkpoints/${checkpointId}`, { cache: "no-store" }),
    sceneCheckpointHistory: (novelId, sceneId) => request(withQuery(`/novels/${novelId}/memories/scene-checkpoints/history`, { scene_id: sceneId }), { cache: "no-store" }),
    ensureSceneCheckpoints: (novelId, sceneId) => post(`/novels/${novelId}/memories/scene-checkpoints/ensure`, { scene_id: sceneId }),
    confirmCustomTextState: (novelId, payload) => post(`/novels/${novelId}/memories/custom-text-state`, payload),
    confirmMapDeclarationState: (novelId, payload) => post(`/novels/${novelId}/memories/map-declaration-state`, payload),
    memoryEventsByIds: (novelId, ids) => request(`/novels/${novelId}/memories/events/by-id?${new URLSearchParams(ids.map(id => ["event_ids", id]))}`, { cache: "no-store" }),
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
    async previewSceneDirectorBudget(novelId, payload = {}) {
      return post("/story/scenes/director/budget-preview", { novel_id: novelId, ...payload })
    },
    async startSceneDirector(novelId, sceneId, payload = {}) {
      return post(`/story/scenes/${sceneId}/director`, { novel_id: novelId, scene_id: sceneId, ...payload })
    },
    async previewSceneDirectorContinuation(rootId, payload = {}) {
      return post(`/story/director/roots/${rootId}/budget-preview`, payload)
    },
    async previewSceneDirectorResume(rootId, payload = {}) {
      return post(`/story/director/roots/${rootId}/budget-preview`, payload)
    },
    async resumeSceneDirector(rootId, payload = {}) {
      return post(`/story/director/roots/${rootId}/branches`, payload)
    },
    async continueSceneDirector(rootId, payload = {}) {
      return post(`/story/director/roots/${rootId}/branches`, payload)
    },
    async advanceSceneDirector(rootId, payload = {}) {
      return post(`/story/director/roots/${rootId}/advance`, payload)
    },
    async sceneDirectorHistory(novelId, sceneId) {
      return request(withQuery(`/story/scenes/${sceneId}/director/history`, { novel_id: novelId }), { cache: "no-store" })
    },
    async updateSceneDirectorRound(roundId, payload = {}) {
      return patch(`/story/director/rounds/${roundId}`, payload)
    },
    async transferDirectorCandidate(roundId, payload = {}) {
      return post(`/story/director/rounds/${roundId}/world-candidates`, payload)
    },
    async updateSceneDirectorBranch(branchId, payload = {}) {
      return patch(`/story/director/branches/${branchId}`, payload)
    },
    async deleteSceneDirectorBranch(branchId, payload = {}) {
      return post(`/story/director/branches/${branchId}/delete`, payload)
    },
    async restoreSceneDirectorBranch(branchId, payload = {}) {
      return post(`/story/director/branches/${branchId}/restore`, payload)
    },
    async deleteUnstarredSceneDirectorBranches(sceneId, payload = {}) {
      return post(`/story/scenes/${sceneId}/director/delete-unstarred`, { scene_id: sceneId, ...payload })
    },
    async saveSceneDirectorReference(roundId, payload = {}) {
      return post(`/story/director/rounds/${roundId}/references`, { source_round_id: roundId, ...payload })
    },
    async updateSceneDirectorReference(referenceId, payload = {}) {
      return patch(`/story/director/references/${referenceId}`, payload)
    },
    async deleteSceneDirectorReference(referenceId, payload = {}) {
      return post(`/story/director/references/${referenceId}/delete`, payload)
    },
    async restoreSceneDirectorReference(referenceId, payload = {}) {
      return post(`/story/director/references/${referenceId}/restore`, payload)
    },
    async getSceneDirectorPreferences(novelId) {
      return request(withQuery("/story/director/preferences", { novel_id: novelId }), { cache: "no-store" })
    },
    async setSceneDirectorPreferences(novelId, payload = {}) {
      return put("/story/director/preferences", { novel_id: novelId, ...payload })
    },
    async previewWorldProgressionBudget(novelId, payload = {}) {
      return post("/story/world-progression/budget-preview", { novel_id: novelId, ...payload })
    },
    // ============================================================
    // 导演多尺度独立探索（第一批）——端点契约见任务 P0-CONTRACTS.md §8。
    // POST body 直传（novel_id 由调用方放入 payload）；
    // start/detail/revise 返回 202 {task_id,...}，调用方用 pollTaskProgress 轮询到终态。
    // ============================================================
    explorationPreview: (payload) => post("/story/exploration/preview", payload),
    explorationConfirmationPreview: (payload) => post("/story/exploration/confirmation/preview", payload),
    explorationConfirm: (payload) => post("/story/exploration/confirmation", payload),
    explorationStart: (payload) => post("/story/exploration/start", payload),
    explorationDetail: (resultId, payload) => post(`/story/exploration/results/${resultId}/detail`, payload),
    explorationRevise: (resultId, payload) => post(`/story/exploration/results/${resultId}/revise`, payload),
    explorationSaveEdit: (resultId, payload) => post(`/story/exploration/results/${resultId}/save-edit`, payload),
    // M3-A3 锁定：payload 含 {novel_id, operation_id, lock, item_path, item_text?}；
    // 202/200 返回 {result_id, output_kind:"story.exploration.lock_set", payload:{locked_items:[...]}}，
    // 409 时 error.message 为服务端中文原因，调用方原样展示。
    explorationLock: (resultId, payload) => post(`/story/exploration/results/${resultId}/lock`, payload),
    // M4-A 跨尺度移交：payload 含 {novel_id, operation_id, target_scale, reason?}；
    // 200 返回 {derived_start, source_fingerprint, requires_confirmation, preview_hint}，
    // derived_start 作为后续 confirmation/preview、confirmation、start 请求的 start。
    explorationHandoff: (resultId, payload) => post(`/story/exploration/results/${resultId}/handoff`, payload),
    explorationCompare: (payload) => post("/story/exploration/compare", payload),
    explorationHistory: (params = {}) => request(withQuery("/story/exploration/history", params), { cache: "no-store" }),
    async startWorldProgression(novelId, payload = {}) {
      return post("/story/world-progression/roots", { novel_id: novelId, ...payload })
    },
    async advanceWorldProgression(rootId, payload = {}) {
      return post(`/story/world-progression/roots/${rootId}/steps`, payload)
    },
    async resumeWorldProgression(rootId, branchId, payload = {}) {
      return post(`/story/world-progression/roots/${rootId}/branches/${branchId}/resume`, payload)
    },
    async worldProgressionHistory(novelId, params = {}) {
      return request(withQuery("/story/world-progression/history", { novel_id: novelId, ...params }), { cache: "no-store" })
    },
    async compareWorldProgressionSteps(novelId, firstStepId, secondStepId) {
      return post("/story/world-progression/compare", {
        novel_id: novelId,
        first_step_id: firstStepId,
        second_step_id: secondStepId,
      })
    },
    async updateWorldProgressionBranch(branchId, payload = {}) {
      return post(`/story/world-progression/branches/${branchId}/metadata`, payload)
    },
    async deleteWorldProgressionBranch(branchId, payload = {}) {
      return post(`/story/world-progression/branches/${branchId}/delete`, payload)
    },
    async restoreWorldProgressionBranch(branchId, payload = {}) {
      return post(`/story/world-progression/branches/${branchId}/restore`, payload)
    },
    async previewWorldProgressionHook(payload = {}) {
      return post("/story/world-progression/hooks/preview", payload)
    },
    async adoptWorldProgressionHook(payload = {}) {
      return post("/story/world-progression/hooks/adopt", payload)
    },
    async readWorldProgressionContinuousAuthorization(novelId, rootId, branchId) {
      return request(withQuery(
        `/story/world-progression/roots/${rootId}/branches/${branchId}/continuous-authorization`,
        { novel_id: novelId },
      ), { cache: "no-store" })
    },
    async setWorldProgressionContinuousAuthorization(rootId, branchId, payload = {}) {
      return put(
        `/story/world-progression/roots/${rootId}/branches/${branchId}/continuous-authorization`,
        payload,
      )
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

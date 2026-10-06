/**
 * api/world.js — api.world 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  put,
  patch,
  deleteRequest,
  uploadMultipart,
  contractPath,
  contractFetch,
  contractJson,
  _readBiblePublishAttempt,
  _writeBiblePublishAttempt,
  _clearBiblePublishAttempt,
} from "./_shared.js"

  // ============================================================
  // 世界对象（含人物，人物 API 已迁入 /api/world/characters）
  // ============================================================
  // ============================================================
  // 世界对象
  // ============================================================

export const world = {
    async listEntities(params = {}) {
      return contractFetch("world.listEntities", {}, params)
    },

    async getReviewTypeCatalog() {
      return contractFetch("world.getReviewTypeCatalog")
    },

    async listRelationReviewGroups(params = {}) {
      return contractFetch("world.listRelationReviewGroups", {}, params)
    },

    async reviewRelationsBatch(payload, novelId) {
      return contractJson("world.reviewRelationsBatch", {}, { novel_id: novelId }, payload)
    },

    async listAliasReviewGroups(params = {}) {
      return contractFetch("world.listAliasReviewGroups", {}, params)
    },

    async reviewAliasesBatch(payload, novelId) {
      return contractJson("world.reviewAliasesBatch", {}, { novel_id: novelId }, payload)
    },

    async listEntityTypes(novelId) {
      return request(withQuery("/world/entity-types", { novel_id: novelId }))
    },

    async listCharacters(params = {}) {
      return request(withQuery("/world/characters", params))
    },

    async getEntityRelations(id, novelId) { return request(withQuery(`/world/entities/${id}/relations`, { novel_id: novelId })) },
    async getEntityRevisions(id, novelId, options = {}) {
      const { skip = 0, limit = 20 } = options
      return request(withQuery(`/world/entities/${id}/revisions`, { novel_id: novelId, skip, limit }))
    },
    async rollbackEntityToRevision(entityId, payload, novelId) {
      return post(withQuery(`/world/entities/${entityId}/rollback-by-revision`, { novel_id: novelId }), payload)
    },
    async setRevisionNote(payload, novelId) {
      return put(withQuery("/world/revision-notes", { novel_id: novelId }), payload)
    },
    async listWorldChangeHistory(novelId, options = {}) {
      const { kinds, cursor, limit } = options
      return request(withQuery("/world/change-history", { novel_id: novelId, kinds, cursor, limit }))
    },
    async getEntity(id, novelId, options = {}) {
      return contractFetch("world.getEntity", { id }, { novel_id: novelId }, options)
    },

    async getCharacter(id, novelId) {
      return contractFetch("world.getCharacter", { id }, { novel_id: novelId })
    },

    async updateCharacter(id, payload, novelId) {
      return contractJson("world.updateCharacter", { id }, { novel_id: novelId }, payload)
    },

    async fetchEntityImage(id, novelId, variant = "full", options = {}) {
      const { expectedVersion, ...requestOptions } = options
      return contractFetch(
        "world.fetchEntityImage",
        { id },
        { novel_id: novelId, variant, expected_version: expectedVersion },
        { cache: "no-store", _responseType: "blob", ...requestOptions },
      )
    },

    async uploadEntityImage(id, file, novelId, onProgress = null, options = {}) {
      const body = new FormData()
      body.append("image", file)
      return uploadMultipart(
        contractPath("world.uploadEntityImage", { id }, { novel_id: novelId }),
        body,
        onProgress,
        { ...options, method: "PUT" },
      )
    },

    async imageGeneration(entityId, novelId) {
      return contractFetch("world.imageGeneration", { id: entityId }, { novel_id: novelId }, { cache: "no-store" })
    },

    async createImageCandidate(entityId, novelId, prompt, forceRefresh = false) {
      return contractJson("world.createImageCandidate", { id: entityId }, {}, { novel_id: novelId, prompt, force_refresh: forceRefresh })
    },

    async imageCandidate(candidateId, novelId) {
      return contractFetch("world.imageCandidate", { candidateId }, { novel_id: novelId }, { cache: "no-store" })
    },

    async fetchImageCandidateImage(candidateId, novelId) {
      return contractFetch("world.fetchImageCandidateImage", { candidateId }, { novel_id: novelId }, { cache: "no-store", _responseType: "blob" })
    },

    async adoptImageCandidate(candidateId, novelId) {
      return contractJson("world.adoptImageCandidate", { candidateId }, {}, { novel_id: novelId })
    },

    async discardImageCandidate(candidateId, novelId) {
      return contractJson("world.discardImageCandidate", { candidateId }, {}, { novel_id: novelId })
    },

    async listProfiles(params = {}) {
      return request(withQuery("/world/profiles", params))
    },

    async getProfile(entityId, novelId) {
      return request(withQuery(`/world/profiles/${entityId}`, { novel_id: novelId }))
    },

    async upsertProfile(entityId, payload, novelId) {
      return put(withQuery(`/world/profiles/${entityId}`, { novel_id: novelId }), payload)
    },

    async migrateGenericProfile(entityId, novelId) {
      return post(withQuery(`/world/profiles/${entityId}/migrate-generic`, { novel_id: novelId }))
    },

    async listBiblePages(params = {}) {
      return request(withQuery("/world/bible/pages", params))
    },

    async listLibraryChoices(params) {
      const result = await request(withQuery("/world/library", { state: "active", limit: 30, ...params }))
      return { total: result.total, items: result.items.map(item => ({ id: item.id, title: item.title, name: item.title, page_type: item.item_type, entity_type: item.item_type, status: item.status })) }
    },

    async getKnowledgeGraph(params = {}, options = {}) {
      return contractFetch("world.getKnowledgeGraph", {}, params, options)
    },

    async createBiblePage(payload) {
      return post("/world/bible/pages", payload)
    },

    async getBiblePage(pageId, novelId) {
      return request(withQuery(`/world/bible/pages/${pageId}`, { novel_id: novelId }))
    },

    async updateBiblePage(pageId, payload, novelId) {
      return patch(withQuery(`/world/bible/pages/${pageId}`, { novel_id: novelId }), payload)
    },

    async listBibleCategories(novelId, includeArchived = false) {
      return request(withQuery("/world/bible/categories", {
        novel_id: novelId,
        include_archived: includeArchived,
      }))
    },

    async createBibleCategory(payload) {
      return post("/world/bible/categories", payload)
    },

    async updateBibleCategory(categoryId, payload, novelId) {
      return patch(withQuery(`/world/bible/categories/${categoryId}`, { novel_id: novelId }), payload)
    },

    async listBibleDrafts(novelId, params = {}) {
      return request(withQuery("/world/bible/drafts", { novel_id: novelId, ...params }))
    },

    async getBibleDraft(draftId, novelId) {
      return request(withQuery(`/world/bible/drafts/${draftId}`, { novel_id: novelId }), { cache: "no-store" })
    },

    async getBibleDraftPublication(draftId, novelId) {
      return request(withQuery(`/world/bible/drafts/${draftId}/publication`, { novel_id: novelId }))
    },

    async listWorldLibrary(params = {}) {
      return request(withQuery("/world/library", params))
    },

    async listRelationGroups(params = {}) {
      return request(withQuery("/world/library/relation-groups", params))
    },

    async applyRelationMembershipBatch(payload, novelId) {
      return post(withQuery("/world/relations/membership-batch", { novel_id: novelId }), payload)
    },

    async getWorldLibraryOverview(novelId) {
      return request(withQuery("/world/library/overview", { novel_id: novelId }))
    },

    async recordWorldLibraryRecent(novelId, targetKind, targetId) {
      return post("/world/library/recents", {
        novel_id: novelId,
        target_kind: targetKind,
        target_id: targetId,
      })
    },

    async addWorldLibraryFavorite(novelId, targetKind, targetId) {
      return post("/world/library/favorites", {
        novel_id: novelId,
        target_kind: targetKind,
        target_id: targetId,
      })
    },

    async removeWorldLibraryFavorite(novelId, targetKind, targetId) {
      return deleteRequest(withQuery("/world/library/favorites", {
        novel_id: novelId,
        target_kind: targetKind,
        target_id: targetId,
      }))
    },

    async getWorldLibraryViewPrefs(novelId) {
      return request(withQuery("/world/library/view-prefs", { novel_id: novelId }))
    },

    async updateWorldLibraryViewPrefs(novelId, viewPrefs) {
      return put("/world/library/view-prefs", {
        novel_id: novelId,
        view_prefs: viewPrefs || {},
      })
    },

    async listWorldLibraryTopics(novelId, includeArchived = false) {
      return request(withQuery("/world/library/topics", {
        novel_id: novelId,
        include_archived: includeArchived,
      }))
    },

    async createWorldLibraryTopic(novelId, payload = {}) {
      return post("/world/library/topics", { novel_id: novelId, ...payload })
    },

    async updateWorldLibraryTopic(topicId, payload, novelId) {
      return patch(withQuery(`/world/library/topics/${topicId}`, { novel_id: novelId }), payload)
    },

    async moveWorldLibraryTopic(topicId, payload, novelId) {
      return post(withQuery(`/world/library/topics/${topicId}/move`, { novel_id: novelId }), payload)
    },

    async reorderWorldLibraryTopics(novelId, parentId, orderedIds) {
      return post("/world/library/topics/reorder", {
        novel_id: novelId,
        parent_id: parentId || null,
        ordered_ids: orderedIds,
      })
    },

    async archiveWorldLibraryTopic(topicId, novelId, archived = true) {
      return post(withQuery(`/world/library/topics/${topicId}/archive`, { novel_id: novelId }), {
        novel_id: novelId,
        archived,
      })
    },

    async addWorldLibraryTopicMember(topicId, novelId, targetKind, targetId) {
      return post(withQuery(`/world/library/topics/${topicId}/members`, { novel_id: novelId }), {
        novel_id: novelId,
        target_kind: targetKind,
        target_id: targetId,
      })
    },

    async removeWorldLibraryTopicMember(topicId, novelId, targetKind, targetId) {
      return deleteRequest(withQuery(
        `/world/library/topics/${topicId}/members/${targetKind}/${targetId}`,
        { novel_id: novelId },
      ))
    },

    async getWorldLibraryMemberships(novelId, targetKind, targetId) {
      return request(withQuery("/world/library/memberships", {
        novel_id: novelId,
        target_kind: targetKind,
        target_id: targetId,
      }))
    },

    async createBibleDraft(payload) {
      return post("/world/bible/drafts", payload)
    },

    async updateBibleDraft(draftId, payload, novelId) {
      return patch(withQuery(`/world/bible/drafts/${draftId}`, { novel_id: novelId }), payload)
    },

    async discardBibleDraft(draftId, novelId) {
      return deleteRequest(withQuery(`/world/bible/drafts/${draftId}`, {
        novel_id: novelId,
        confirmed: true,
      }))
    },

    async previewBibleDraftPublishImpact(draftId, novelId) {
      return request(withQuery(`/world/bible/drafts/${draftId}/publish-impact`, { novel_id: novelId }))
    },

    async publishBibleDraft(draftId, novelId, expectedImpactScopeHash = null, validationRunId = null) {
      let attempt = _readBiblePublishAttempt(novelId, draftId)
      if (!attempt) {
        const head = await request(withQuery("/world/canon/head", { novel_id: novelId }), { cache: "no-store" })
        if (!head?.current_revision?.id) throw new Error("暂时无法确认世界设定版本，请稍后重试")
        attempt = {
          expectedCanonHead: head.current_revision.id,
          decisionId: crypto.randomUUID(),
          expectedImpactScopeHash: expectedImpactScopeHash || null,
          validationRunId: validationRunId || null,
        }
        _writeBiblePublishAttempt(novelId, draftId, attempt)
      }
      try {
        const result = await post(withQuery(`/world/bible/drafts/${draftId}/publish`, {
          novel_id: novelId,
          expected_canon_head: attempt.expectedCanonHead,
          canon_decision_id: attempt.decisionId,
          expected_impact_scope_hash: attempt.expectedImpactScopeHash || undefined,
          validation_run_id: attempt.validationRunId || undefined,
        }))
        _clearBiblePublishAttempt(novelId, draftId)
        return result
      } catch (error) {
        if (Number(error?.status) >= 400 && Number(error?.status) < 500) {
          _clearBiblePublishAttempt(novelId, draftId)
        }
        throw error
      }
    },

    async listBiblePageRevisions(pageId, novelId) {
      return request(withQuery(`/world/bible/pages/${pageId}/revisions`, { novel_id: novelId }))
    },

    async restoreBiblePageRevision(pageId, version, novelId) {
      return post(withQuery(`/world/bible/pages/${pageId}/revisions/${version}/restore-draft`, {
        novel_id: novelId,
      }))
    },

    async getBibleSynopsis(novelId) {
      return request(withQuery("/world/bible/synopsis", { novel_id: novelId }))
    },

    async refreshBibleSynopsis(novelId, contextConfirmationId) {
      return post(withQuery("/world/bible/synopsis/refresh", { novel_id: novelId, context_confirmation_id: contextConfirmationId }))
    },

    async setBibleSynopsisAutoRefresh(novelId, enabled) {
      return patch(withQuery("/world/bible/synopsis/auto-refresh", { novel_id: novelId }), { enabled })
    },

    async listBibleSynopsisRevisions(novelId) {
      return request(withQuery("/world/bible/synopsis/revisions", { novel_id: novelId }))
    },

    async restoreBibleSynopsisRevision(revisionId, novelId) {
      return post(withQuery(`/world/bible/synopsis/revisions/${revisionId}/restore`, { novel_id: novelId }))
    },

    async unpinBibleSynopsis(novelId) {
      return post(withQuery("/world/bible/synopsis/unpin", { novel_id: novelId }))
    },

    async listBibleTemplates() {
      return request("/world/bible/templates")
    },

    async listBiblePageTemplates(novelId, includeArchived = false) {
      return request(withQuery("/world/bible/page-templates", {
        novel_id: novelId,
        include_archived: includeArchived,
      }))
    },

    async createBiblePageTemplate(payload) {
      return post("/world/bible/page-templates", payload)
    },

    async updateBiblePageTemplate(templateId, payload, novelId) {
      return patch(withQuery(`/world/bible/page-templates/${templateId}`, {
        novel_id: novelId,
      }), payload)
    },

    async listBiblePageTemplateRevisions(templateId, novelId) {
      return request(withQuery(`/world/bible/page-templates/${templateId}/revisions`, {
        novel_id: novelId,
      }))
    },

    async restoreBiblePageTemplateRevision(templateId, version, novelId) {
      return post(withQuery(
        `/world/bible/page-templates/${templateId}/revisions/${version}/restore-draft`,
        { novel_id: novelId },
      ))
    },

    async applyBiblePageTemplate(draftId, payload, novelId) {
      return post(withQuery(`/world/bible/drafts/${draftId}/apply-template`, {
        novel_id: novelId,
      }), payload)
    },

    async refreshBibleProjection(pageId, novelId, projectionType = "context_brief", force = false) {
      return post(withQuery(`/world/bible/pages/${pageId}/refresh-projection`, {
        novel_id: novelId,
        projection_type: projectionType,
        force,
      }))
    },

    async organizeBiblePage(pageId, novelId) {
      return post(withQuery(`/world/bible/pages/${pageId}/organize`, { novel_id: novelId }))
    },

    async listSuggestions(params = {}) {
      return request(withQuery("/world/suggestions", params))
    },

    async getWorldSuggestion(suggestionId, novelId) {
      return request(withQuery(`/world/suggestions/${suggestionId}`, { novel_id: novelId }), { cache: "no-store" })
    },

    async saveCoreCheckpoint(payload) {
      return post("/world/core-checkpoints", payload)
    },

    async saveDesignCheckpoint(payload) {
      return post("/world/design-checkpoints", payload)
    },

    async reviseDesignCheckpoint(payload) {
      return post("/world/design-checkpoints/revisions", payload)
    },


    async listCocreationSessions(novelId, params = {}) {
      return request(withQuery("/world/cocreation-sessions", { novel_id: novelId, ...params }), { cache: "no-store" })
    },

    async createCocreationSession(payload) {
      return post("/world/cocreation-sessions", payload)
    },

    async getCocreationSession(sessionId, novelId) {
      return request(withQuery(`/world/cocreation-sessions/${sessionId}`, { novel_id: novelId }), { cache: "no-store" })
    },

    async updateCocreationSession(sessionId, payload) {
      return patch(`/world/cocreation-sessions/${sessionId}`, payload)
    },

    async listCocreationMessages(sessionId, novelId, params = {}) {
      return request(withQuery(`/world/cocreation-sessions/${sessionId}/messages`, { novel_id: novelId, ...params }), { cache: "no-store" })
    },

    async appendCocreationMessage(sessionId, payload) {
      return post(`/world/cocreation-sessions/${sessionId}/messages`, payload)
    },

    async advanceCocreationCheckpoint(sessionId, payload) {
      return post(`/world/cocreation-sessions/${sessionId}/checkpoint`, payload)
    },

    async cocreationChat(sessionId, payload, options = {}) {
      return contractJson("world.cocreationChat", { sessionId }, {}, payload, options)
    },

    async enqueueCocreationTurn(payload) {
      return contractJson("world.enqueueCocreationTurn", {}, {}, payload)
    },

    // manifest v2：显式格式、资料集身份与提交语义一并进入预览指纹
    // （m1-contract 第 1/2/3/5 条）；dataset_key 由服务端派生，不接收客户端值。
    async previewWorldbookImport(novelId, manifest) {
      return post(withQuery("/world/bible/imports/preview", { novel_id: novelId }), {
        schema_version: "world_worldbook_import.v2",
        source_format: manifest.source_format || "auto",
        dataset_name: manifest.dataset_name ?? null,
        dataset_intent: manifest.dataset_intent || "continue",
        commit_mode: manifest.commit_mode || "full_snapshot",
        files: manifest.files,
      })
    },

    async getWorldbookImport(suggestionId, novelId) {
      return request(withQuery(`/world/bible/imports/${suggestionId}`, { novel_id: novelId }))
    },

    async applyWorldbookImport(suggestionId, novelId, expectedPreviewHash) {
      return post(withQuery(`/world/bible/imports/${suggestionId}/apply`, { novel_id: novelId }), {
        expected_preview_hash: expectedPreviewHash,
      })
    },

    async createWorldValidationRun(payload) {
      return post("/world/bible/validation-runs", payload)
    },

    async getWorldValidationPolicyStatus(novelId) {
      return request(withQuery("/world/bible/validation-policy", { novel_id: novelId }))
    },

    async activateWorldValidationPolicy(novelId) {
      return post(withQuery("/world/bible/validation-policy/activate", { novel_id: novelId }))
    },

    async listWorldValidationRuns(novelId, limit = 10) {
      return request(withQuery("/world/bible/validation-runs", { novel_id: novelId, limit }))
    },

    async getLatestWorldValidationRun(novelId, params = {}) {
      return request(withQuery("/world/bible/validation-runs/latest", {
        novel_id: novelId,
        ...params,
      }))
    },

    async getWorldValidationRun(runId, novelId) {
      return request(withQuery(`/world/bible/validation-runs/${runId}`, { novel_id: novelId }))
    },

    async acceptWorldValidationWarnings(runId, novelId, payload) {
      return post(withQuery(`/world/bible/validation-runs/${runId}/accept-warnings`, {
        novel_id: novelId,
      }), payload)
    },

    async listWorldValidationFindings(runId, novelId, params = {}) {
      return request(withQuery(`/world/bible/validation-runs/${runId}/findings`, {
        novel_id: novelId,
        ...params,
      }))
    },

    async createWorldValidationReviewItems(runId, novelId, payload) {
      return post(withQuery(`/world/bible/validation-runs/${runId}/review-items`, {
        novel_id: novelId,
      }), payload)
    },

    async continueWorldValidationRun(runId, novelId, payload = {}) {
      return post(withQuery(`/world/bible/validation-runs/${runId}/continue`, {
        novel_id: novelId,
      }), payload)
    },

    async saveWorldValidationPolicyDraft(novelId, payload) {
      return post(withQuery("/world/bible/validation-policy/draft", {
        novel_id: novelId,
      }), payload)
    },

    async readWorldImpactSource(payload) {
      return post("/world/impact-preview/source", payload)
    },

    async readWorldValidationSource(runId, novelId, sourceKey) {
      return request(withQuery(`/world/bible/validation-runs/${runId}/source`, { novel_id: novelId, source_key: sourceKey }))
    },

    stressReport: (novelId, reportId) => request(withQuery(`/world/stress-reports/${reportId}`, { novel_id: novelId }), { cache: "no-store" }),
    decideStressScenario: (novelId, reportId, payload) => post(withQuery(`/world/stress-reports/${reportId}/decisions`, { novel_id: novelId }), payload),

    async previewWorldImpact(params = {}) {
      return request(withQuery("/world/impact-preview", params))
    },

    async getAdoptionArtifact(suggestionId, novelId) {
      return request(withQuery(`/world/adoption-packages/${suggestionId}`, { novel_id: novelId }))
    },

    async previewAdoptionPackage(suggestionId, novelId) {
      return request(withQuery(`/world/adoption-packages/${suggestionId}/preview`, { novel_id: novelId }))
    },

    async applyAdoptionPackage(suggestionId, novelId, expectedPreviewHash, validationRunId = null) {
      return post(withQuery(`/world/adoption-packages/${suggestionId}/apply`, { novel_id: novelId }), {
        expected_preview_hash: expectedPreviewHash,
        validation_run_id: validationRunId || undefined,
      })
    },

    async confirmSuggestion(suggestionId, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/confirm`, { novel_id: novelId }))
    },

    async editAndConfirmSuggestion(suggestionId, payload, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/edit-confirm`, { novel_id: novelId }), payload)
    },

    async mergeSuggestion(suggestionId, targetEntityId, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/merge`, { novel_id: novelId }), { target_entity_id: targetEntityId })
    },

    async resolveSuggestionAsAlias(suggestionId, payload, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/resolve-as-alias`, { novel_id: novelId }), payload)
    },

    async rejectSuggestion(suggestionId, novelId) {
      return post(withQuery(`/world/suggestions/${suggestionId}/reject`, { novel_id: novelId }))
    },

    async listWorldConflicts(params = {}) {
      return request(withQuery("/world/conflicts", params))
    },

    async resolveWorldConflict(conflictId, payload, novelId) {
      return post(withQuery(`/world/conflicts/${conflictId}/resolve`, { novel_id: novelId }), payload)
    },

    async createEntity(payload, novelId) {
      return contractJson("world.createEntity", {}, { novel_id: novelId }, payload)
    },

    async updateEntity(id, payload, novelId) {
      return contractJson("world.updateEntity", { id }, { novel_id: novelId }, payload)
    },

    async promoteEntity(id, novelId, payload = {}) {
      return post(withQuery(`/world/entities/${id}/promote`, { novel_id: novelId }), payload)
    },

    async extractAliasRelations(payload) {
      return post("/world/alias-relations/extract", payload)
    },

    async deleteEntity(id, novelId) {
      return contractFetch("world.deleteEntity", { id }, { novel_id: novelId })
    },

    async listEntityBatches(params = {}) {
      return request(withQuery("/world/entity-batches", params))
    },

    async listRelationships(params = {}) {
      return request(withQuery("/world/relations", params))
    },

    async createRelationship(payload, novelId) {
      return post(withQuery("/world/relations", { novel_id: novelId }), payload)
    },

    async updateRelationship(id, payload, novelId) {
      return put(withQuery(`/world/relations/${id}`, { novel_id: novelId }), payload)
    },

    async reviewEditRelationship(id, payload, novelId) {
      return patch(withQuery(`/world/relations/${id}/review-edit`, { novel_id: novelId }), payload)
    },

    async deleteRelationship(id, params = {}) {
      return deleteRequest(withQuery(`/world/relations/${id}`, params))
    },

    async listAliases(params = {}) {
      return request(withQuery("/world/aliases", params))
    },

    async createAlias(payload, novelId) {
      return post(withQuery("/world/aliases", { novel_id: novelId }), payload)
    },

    async updateAlias(entityId, alias, payload, params = {}) {
      params.alias = alias
      return patch(withQuery(`/world/entities/${entityId}/aliases`, params), payload)
    },

    async editAlias(entityId, alias, payload, params = {}) {
      params.alias = alias
      return patch(withQuery(`/world/entities/${entityId}/aliases/edit`, params), payload)
    },

    async deleteAlias(entityId, alias, params = {}) {
      params.alias = alias
      return deleteRequest(withQuery(`/world/entities/${entityId}/aliases`, params))
    },

    async mergeEntity(candidateId, targetEntityId, novelId) {
      return post(withQuery(`/world/entities/${candidateId}/merge`, { novel_id: novelId }), { target_entity_id: targetEntityId })
    },

    async resolveEntityAsAlias(candidateId, payload, novelId) {
      return post(withQuery(`/world/entities/${candidateId}/resolve-as-alias`, { novel_id: novelId }), payload)
    },

    async createEntityFusionSuggestions(data) {
      return post("/world/entities/fusion-suggestions", data)
    },

    async applyEntityFusionSuggestions(data) {
      return post("/world/entities/fusion-suggestions/apply", data)
    },

    async rollbackEntity(entityId, targetSceneIndex, novelId) {
      return post(withQuery(`/world/entities/${entityId}/rollback`, { novel_id: novelId }), { target_scene_index: targetSceneIndex })
    },

    async listKnowledge(characterId, novelId) {
      return request(withQuery(`/world/characters/${characterId}/knowledge`, { novel_id: novelId }))
    },

    async createKnowledge(characterId, payload, novelId) {
      return post(withQuery(`/world/characters/${characterId}/knowledge`, { novel_id: novelId }), payload)
    },

    async updateKnowledge(knowledgeId, payload, novelId) {
      return put(withQuery(`/world/knowledge/${knowledgeId}`, { novel_id: novelId }), payload)
    },

    // ============================================================
    // AI 地图册
    async createMapNode(novelId, payload) {
      return contractJson("world.createMapNode", { novelId }, {}, payload)
    },
    async getNodeMap(novelId, nodeId) {
      return contractFetch("world.getNodeMap", { novelId, nodeId }, {}, { cache: "no-store" })
    },
    async getMapSceneContext(novelId, nodeId, sceneId) {
      return request(withQuery(`/world/map-atlas/${novelId}/nodes/${nodeId}/scene-context`, { scene_id: sceneId, view: 'author' }), { cache: 'no-store' })
    },
    async saveMapRevision(novelId, nodeId, payload) {
      return contractJson("world.saveMapRevision", { novelId, nodeId }, {}, payload)
    },
    async listMapRevisions(novelId, nodeId) {
      return contractFetch("world.listMapRevisions", { novelId, nodeId }, {}, { cache: "no-store" })
    },
    async previewMapRevision(novelId, nodeId, revisionId) {
      return request(`/world/map-atlas/${novelId}/nodes/${nodeId}/revisions/${revisionId}/preview`, { cache: 'no-store' })
    },
    async layoutMap(novelId, nodeId, payload) {
      return contractJson("world.layoutMap", { novelId, nodeId }, {}, payload)
    },
    async generateMapStructure(novelId, nodeId, payload) {
      return contractJson("world.generateMapStructure", { novelId, nodeId }, {}, payload)
    },
    async reviewMapRevision(novelId, nodeId, revisionId, payload) {
      return contractJson("world.reviewMapRevision", { novelId, nodeId, revisionId }, {}, payload)
    },
    async previewReaderMap(novelId, nodeId, chapter, revisionId) {
      return contractFetch("world.previewReaderMap", { novelId, nodeId }, { chapter, revision_id: revisionId }, { cache: "no-store" })
    },
    async fetchReaderMapImage(novelId, nodeId, pageId, chapter, revisionId) {
      return request(withQuery(`/world/map-atlas/${novelId}/nodes/${nodeId}/reader-preview/images/${pageId}`, { chapter, revision_id: revisionId }), { cache: "no-store", _responseType: "blob" })
    },
    async getMapAtlas(novelId) {
      return contractFetch("world.getMapAtlas", { novelId }, {}, { cache: "no-store" })
    },

    async getMapCapabilities(novelId) {
      return request(withQuery("/world/map-atlas/capabilities", { novel_id: novelId }))
    },
    async findMapLinks(novelId, filters = {}) {
      return request(withQuery(`/world/map-atlas/${novelId}/map-links`, filters), { cache: "no-store" })
    },
    async previewMapReview(novelId, nodeId, revisionId, payload) {
      return post(`/world/map-atlas/${novelId}/nodes/${nodeId}/revisions/${revisionId}/review-preview`, payload)
    },
    async getMapAtlasPageHistory(novelId) {
      return request(`/world/map-atlas/${novelId}/pages/history`, { cache: "no-store" })
    },
    async createMapAtlasRun(novelId, payload) {
      return contractJson("world.createMapAtlasRun", { novelId }, {}, payload)
    },
    async getMapAtlasRun(novelId, runId) {
      return contractFetch("world.getMapAtlasRun", { novelId, runId }, {}, { cache: "no-store" })
    },
    async getLatestMapAtlasRun(novelId) {
      return contractFetch("world.getLatestMapAtlasRun", { novelId }, {}, { cache: "no-store" })
    },
    async getMapAtlasRunResults(novelId, runId) {
      return contractFetch("world.getMapAtlasRunResults", { novelId, runId }, {}, { cache: "no-store" })
    },
    async getMapAtlasPagePrompt(novelId, pageId) {
      return request(`/world/map-atlas/${novelId}/pages/${pageId}/prompt`, { cache: "no-store" })
    },
    async updateMapAtlasPagePrompt(novelId, pageId, payload) {
      return patch(`/world/map-atlas/${novelId}/pages/${pageId}/prompt`, payload)
    },
    async confirmMapAtlasPrompts(novelId, runId, pages) {
      return post(`/world/map-atlas/${novelId}/runs/${runId}/confirm-prompts`, { pages })
    },
    async uploadMapAtlasPage(novelId, payload, onProgress = null, options = {}) {
      const body = new FormData()
      body.append("image", payload.image)
      for (const [key, value] of Object.entries(payload)) {
        if (key !== "image" && value !== undefined && value !== null && value !== "") body.append(key, String(value))
      }
      return uploadMultipart(`/world/map-atlas/${novelId}/pages/upload`, body, onProgress, options)
    },
    async updateMapAtlasNode(novelId, nodeId, payload) {
      return patch(`/world/map-atlas/${novelId}/nodes/${nodeId}`, payload)
    },
    async stopMapAtlasRun(novelId, runId) {
      return post(`/world/map-atlas/${novelId}/runs/${runId}/stop`, {})
    },
    async resumeMapAtlasRun(novelId, runId, confirmPossibleDuplicateCharge = false) {
      return post(`/world/map-atlas/${novelId}/runs/${runId}/resume`, {
        confirm_possible_duplicate_charge: confirmPossibleDuplicateCharge,
      })
    },
    async reviewMapAtlasPage(novelId, pageId, action, payload = {}) {
      return contractJson("world.reviewMapAtlasPage", { novelId, pageId, action }, {}, payload)
    },
    async retryMapAtlasPage(novelId, pageId, confirmPossibleDuplicateCharge = false) {
      return post(`/world/map-atlas/${novelId}/pages/${pageId}/retry`, {
        confirm_possible_duplicate_charge: confirmPossibleDuplicateCharge,
      })
    },
    async regenerateMapAtlasPage(novelId, pageId, payload = {}) {
      return post(`/world/map-atlas/${novelId}/pages/${pageId}/regenerate`, payload)
    },
    async editMapAtlasPage(novelId, pageId, { instruction, referencePageIds = [], mask = null, sourceMapRevisionId = null, contextConfirmationId = null }) {
      const body = new FormData()
      body.append("instruction", instruction)
      if (referencePageIds.length) body.append("reference_page_ids", JSON.stringify(referencePageIds))
      if (mask) body.append("mask", mask)
      if (sourceMapRevisionId) body.append("source_map_revision_id", sourceMapRevisionId)
      if (contextConfirmationId) body.append("context_confirmation_id", contextConfirmationId)
      return request(`/world/map-atlas/${novelId}/pages/${pageId}/edit`, { method: "POST", body })
    },
    async updateMapAtlasAnnotation(novelId, annotationId, payload) {
      return patch(`/world/map-atlas/${novelId}/annotations/${annotationId}`, payload)
    },
    async fetchMapAtlasImage(novelId, pageId) {
      return request(`/world/map-atlas/${novelId}/pages/${pageId}/image`, {
        cache: "no-store",
        _responseType: "blob",
      })
    },
};

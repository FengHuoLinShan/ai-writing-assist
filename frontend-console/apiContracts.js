/**
 * Shared frontend API contracts.
 *
 * This file intentionally stays classic-script compatible because index.html
 * loads api.js as a classic script and api.js needs these helpers synchronously.
 * Vitest can import it for side effects and read window.apiContracts.
 */
(function () {
  const DEFAULT_TIMEOUT = 15000
  // Optional P21 evidence reranking may use the full 30-minute managed LLM
  // budget, including schema repair. Keep delivery headroom in the browser so
  // a valid backend result is not discarded at the old five-minute boundary.
  const RAG_SEARCH_TIMEOUT = 2100000
  const RAG_PREWARM_TIMEOUT = 600000
  const CONTEXT_COMPILE_TIMEOUT = 600000
  const CONTEXT_CONFIRM_TIMEOUT = 600000
  // The backend may use its full 30-minute generation budget. Keep client-side
  // headroom for prompt preparation, persistence, and response delivery.
  const LLM_GENERATE_TIMEOUT = 2100000
  // Async AI endpoints normally return after durable enqueue, but preparing a
  // confirmed full-project snapshot can still be expensive. Submission gets
  // its own generous window; the subsequent poll loop follows task terminal
  // state and deliberately has no frontend total deadline.
  const AI_TASK_SUBMIT_TIMEOUT = 600000
  // Adopting an AI preview recompiles the confirmed context and verifies every
  // source fingerprint before the transactional write. Large projects can
  // legitimately spend tens of seconds here, so this must not inherit CRUD's
  // short timeout.
  const AI_PREVIEW_APPLY_TIMEOUT = 600000

  function queryString(query = {}) {
    const parts = []
    for (const [key, value] of Object.entries(query || {})) {
      if (value !== undefined && value !== null && value !== "") {
        parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
      }
    }
    return parts.length ? `?${parts.join("&")}` : ""
  }

  function required(value, name, contractName) {
    if (value === undefined || value === null || value === "") {
      throw new Error(`Missing required API contract value ${name} for ${contractName}`)
    }
    return value
  }

  function requiredBodyField(body, name, contractName) {
    if (
      !body
      || !Object.prototype.hasOwnProperty.call(body, name)
      || body[name] === undefined
    ) {
      throw new Error(`Missing required API contract value ${name} for ${contractName}`)
    }
  }

  function stagePath(params, contractName) {
    const stage = required(params.stage, "stage", contractName)
    const endpoints = {
      scenes: "/imports/stages/scenes",
      world_objects: "/imports/stages/world-objects",
      plot_structure: "/imports/stages/plot-structure",
    }
    const endpoint = endpoints[stage]
    if (!endpoint) throw new Error(`unsupported import stage: ${stage}`)
    return endpoint
  }

  function define(method, path, {
    requiredParams = [],
    requiredQuery = [],
    requiredBody = [],
    hasBody = false,
    timeout = DEFAULT_TIMEOUT,
    timeoutKind = "default",
  } = {}) {
    return Object.freeze({
      method,
      path,
      requiredParams,
      requiredQuery,
      requiredBody,
      hasBody,
      timeout,
      timeoutKind,
    })
  }

  const API_CONTRACTS = Object.freeze({
    "projects.list": define("GET", () => "/projects"),
    "projects.get": define("GET", ({ id }) => `/projects/${required(id, "id", "projects.get")}`, {
      requiredParams: ["id"],
    }),
    "projects.getWorkspaceSummary": define("GET", ({ id }) => `/projects/${required(id, "id", "projects.getWorkspaceSummary")}/workspace-summary`, {
      requiredParams: ["id"],
    }),
    "projects.create": define("POST", () => "/projects", { hasBody: true }),
    "projects.update": define("PUT", ({ id }) => `/projects/${required(id, "id", "projects.update")}`, {
      requiredParams: ["id"],
      hasBody: true,
    }),
    "projects.getLlmSettings": define("GET", ({ id }) => `/projects/${required(id, "id", "projects.getLlmSettings")}/llm-settings`, {
      requiredParams: ["id"],
    }),
    "projects.updateLlmSettings": define("PUT", ({ id }) => `/projects/${required(id, "id", "projects.updateLlmSettings")}/llm-settings`, {
      requiredParams: ["id"],
      hasBody: true,
    }),

    "interactions.listJourneys": define("GET", () => "/interactions/journeys"),
    "interactions.createJourney": define("POST", () => "/interactions/journeys", {
      hasBody: true,
      requiredBody: ["opening_text", "idempotency_key"],
    }),
    "interactions.getJourney": define("GET", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.getJourney")}`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.getMessages": define("GET", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.getMessages")}/messages`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.getPathIndex": define("GET", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.getPathIndex")}/path-index`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.sendMessage": define("POST", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.sendMessage")}/messages`, {
      requiredParams: ["journeyId"],
      hasBody: true,
      requiredBody: ["content", "expected_selection_epoch", "idempotency_key"],
    }),
    "interactions.continueFromNode": define("POST", ({ journeyId, nodeId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.continueFromNode")}/nodes/${required(nodeId, "nodeId", "interactions.continueFromNode")}/continue-from-here`, {
      requiredParams: ["journeyId", "nodeId"],
      hasBody: true,
      requiredBody: ["content", "expected_selection_epoch", "idempotency_key"],
    }),
    "interactions.regenerate": define("POST", ({ journeyId, nodeId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.regenerate")}/nodes/${required(nodeId, "nodeId", "interactions.regenerate")}/regenerate`, {
      requiredParams: ["journeyId", "nodeId"],
      hasBody: true,
      requiredBody: ["expected_selection_epoch", "idempotency_key"],
    }),
    "interactions.editUserMessage": define("POST", ({ journeyId, nodeId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.editUserMessage")}/nodes/${required(nodeId, "nodeId", "interactions.editUserMessage")}/edit`, {
      requiredParams: ["journeyId", "nodeId"],
      hasBody: true,
      requiredBody: ["content", "expected_selection_epoch", "idempotency_key"],
    }),
    "interactions.selectBranch": define("POST", ({ journeyId, nodeId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.selectBranch")}/nodes/${required(nodeId, "nodeId", "interactions.selectBranch")}/select`, {
      requiredParams: ["journeyId", "nodeId"],
      hasBody: true,
      requiredBody: ["expected_selection_epoch"],
    }),
    "interactions.listBranches": define("GET", ({ journeyId, nodeId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.listBranches")}/nodes/${required(nodeId, "nodeId", "interactions.listBranches")}/branches`, {
      requiredParams: ["journeyId", "nodeId"],
    }),
    "interactions.getTree": define("GET", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.getTree")}/tree`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.getAttempt": define("GET", ({ journeyId, attemptId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.getAttempt")}/attempts/${required(attemptId, "attemptId", "interactions.getAttempt")}`, {
      requiredParams: ["journeyId", "attemptId"],
    }),
    "interactions.listGenerationRecords": define("GET", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.listGenerationRecords")}/generation-records`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.streamAttempt": define("GET", ({ journeyId, attemptId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.streamAttempt")}/attempts/${required(attemptId, "attemptId", "interactions.streamAttempt")}/events`, {
      requiredParams: ["journeyId", "attemptId"],
    }),
    "interactions.stopAttempt": define("POST", ({ journeyId, attemptId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.stopAttempt")}/attempts/${required(attemptId, "attemptId", "interactions.stopAttempt")}/stop`, {
      requiredParams: ["journeyId", "attemptId"],
      hasBody: true,
      requiredBody: ["expected_selection_epoch"],
    }),
    "interactions.keepAttempt": define("POST", ({ journeyId, attemptId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.keepAttempt")}/attempts/${required(attemptId, "attemptId", "interactions.keepAttempt")}/keep`, {
      requiredParams: ["journeyId", "attemptId"],
      hasBody: true,
      requiredBody: ["expected_selection_epoch"],
    }),
    "interactions.continueAttempt": define("POST", ({ journeyId, attemptId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.continueAttempt")}/attempts/${required(attemptId, "attemptId", "interactions.continueAttempt")}/continue`, {
      requiredParams: ["journeyId", "attemptId"],
      hasBody: true,
      requiredBody: ["expected_selection_epoch", "idempotency_key"],
    }),
    "interactions.retryAttempt": define("POST", ({ journeyId, attemptId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.retryAttempt")}/attempts/${required(attemptId, "attemptId", "interactions.retryAttempt")}/retry`, {
      requiredParams: ["journeyId", "attemptId"],
      hasBody: true,
      requiredBody: ["expected_selection_epoch", "idempotency_key"],
    }),
    "interactions.updateModes": define("PATCH", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.updateModes")}/modes`, {
      requiredParams: ["journeyId"],
      hasBody: true,
      requiredBody: ["expected_selection_epoch"],
    }),
    "interactions.heartbeat": define("POST", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.heartbeat")}/heartbeat`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.leaveJourney": define("POST", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.leaveJourney")}/leave`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.updateTitle": define("PATCH", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.updateTitle")}/title`, {
      requiredParams: ["journeyId"],
      hasBody: true,
      requiredBody: ["title"],
    }),
    "interactions.getOverview": define("GET", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.getOverview")}/overview`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.updateOverview": define("PUT", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.updateOverview")}/overview`, {
      requiredParams: ["journeyId"],
      hasBody: true,
      requiredBody: ["sections", "expected_overview_epoch", "expected_selection_epoch", "base_revision_id", "base_selected_leaf_node_id", "base_selected_path_hash"],
    }),
    "interactions.retryOverview": define("POST", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.retryOverview")}/overview/retry`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.archiveJourney": define("POST", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.archiveJourney")}/archive`, {
      requiredParams: ["journeyId"],
      hasBody: true,
      requiredBody: ["confirmed"],
    }),
    "interactions.restoreJourney": define("POST", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.restoreJourney")}/restore`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.deleteJourney": define("DELETE", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.deleteJourney")}`, {
      requiredParams: ["journeyId"],
      hasBody: true,
      requiredBody: ["title_confirmation"],
    }),
    "interactions.exportJourney": define("GET", ({ journeyId }) => `/interactions/journeys/${required(journeyId, "journeyId", "interactions.exportJourney")}/export`, {
      requiredParams: ["journeyId"],
    }),
    "interactions.getPreferences": define("GET", () => "/interactions/preferences"),
    "interactions.acknowledgeSeeSeaNotice": define("POST", () => "/interactions/preferences/see-sea-notice"),

    "settings.listGlobalLLMDefaults": define("GET", () => "/settings/llm-defaults"),
    "settings.updateGlobalLLMDefaults": define("PUT", () => "/settings/llm-defaults", { hasBody: true }),
    "settings.listLLMConnections": define("GET", () => "/settings/llm-connections"),
    "settings.connectLLMProvider": define("PUT", ({ providerId }) => `/settings/llm-connections/${required(providerId, "providerId", "settings.connectLLMProvider")}`, {
      requiredParams: ["providerId"],
      hasBody: true,
    }),
    "settings.activateLLMProvider": define("POST", ({ providerId }) => `/settings/llm-connections/${required(providerId, "providerId", "settings.activateLLMProvider")}/activate`, {
      requiredParams: ["providerId"],
    }),
    "settings.listLLMBalances": define("GET", () => "/settings/llm-balances"),
    "settings.getEffectiveLLMSettings": define("GET", ({ projectId }) => `/projects/${required(projectId, "projectId", "settings.getEffectiveLLMSettings")}/effective-llm-settings`, {
      requiredParams: ["projectId"],
    }),
    "settings.getProjectAuthorPrefs": define("GET", ({ projectId }) => `/settings/projects/${required(projectId, "projectId", "settings.getProjectAuthorPrefs")}/author-preferences`, {
      requiredParams: ["projectId"],
    }),
    "settings.updateProjectAuthorPrefs": define("PUT", ({ projectId }) => `/settings/projects/${required(projectId, "projectId", "settings.updateProjectAuthorPrefs")}/author-preferences`, {
      requiredParams: ["projectId"],
      hasBody: true,
    }),

    "imports.deepImport": define("POST", () => "/imports/deep", {
      hasBody: true,
      requiredBody: ["adoption_policy", "authorization_confirmed"],
    }),
    "imports.startStage": define("POST", (params) => stagePath(params || {}, "imports.startStage"), {
      requiredParams: ["stage"],
      hasBody: true,
      requiredBody: ["adoption_policy", "authorization_confirmed"],
    }),
    "imports.startMapObservationEnrichment": define("POST", () => "/imports/stages/map-observations", {
      hasBody: true,
      requiredBody: ["novel_id", "start_chapter", "end_chapter", "high_quality", "adoption_policy", "authorization_confirmed"],
    }),
    "imports.resumeDeepImport": define("POST", () => "/imports/deep/resume", { hasBody: true }),
    "imports.abandonDeepImport": define("POST", () => "/imports/deep/abandon", { hasBody: true }),

    "context.confirm": define("POST", () => "/context/confirm", {
      hasBody: true,
      timeout: CONTEXT_CONFIRM_TIMEOUT,
      timeoutKind: "contextConfirm",
    }),
    "context.compile": define("POST", () => "/context/compile", {
      hasBody: true,
      timeout: CONTEXT_COMPILE_TIMEOUT,
      timeoutKind: "contextCompile",
    }),
    "context.render": define("POST", () => "/context/render", {
      hasBody: true,
      timeout: CONTEXT_COMPILE_TIMEOUT,
      timeoutKind: "contextCompile",
    }),
    "context.listSnapshots": define("GET", () => "/context/snapshots"),
    "context.getSnapshot": define("GET", ({ snapshotId }) => `/context/snapshots/${required(snapshotId, "snapshotId", "context.getSnapshot")}`, {
      requiredParams: ["snapshotId"],
    }),
    "context.activationPreview": define("GET", () => "/context/activation-preview"),
    "context.evidenceHealth": define("GET", () => "/context/evidence-health", {
      requiredQuery: ["novel_id"],
    }),
    "context.listRetrievalTraces": define("GET", () => "/context/retrieval-traces", {
      requiredQuery: ["novel_id"],
    }),

    "generate.listPromptTemplateRevisions": define("GET", ({ templateId }) => `/world/generation-prompt-templates/${required(templateId, "templateId", "generate.listPromptTemplateRevisions")}/revisions`, {
      requiredParams: ["templateId"],
      requiredQuery: ["novel_id"],
    }),
    "generate.worldChat": define("POST", () => "/world/generation-center/chat", {
      hasBody: true,
      timeout: LLM_GENERATE_TIMEOUT,
      timeoutKind: "llmGenerate",
    }),
    "generate.generateWorldSuggestion": define("POST", () => "/world/generation-center/suggestions", {
      hasBody: true,
      timeout: LLM_GENERATE_TIMEOUT,
      timeoutKind: "llmGenerate",
    }),
    "generate.applyWorldPageDraft": define("POST", ({ suggestionId }) => `/world/generation-center/suggestions/${required(suggestionId, "suggestionId", "generate.applyWorldPageDraft")}/apply-page-draft`, {
      requiredParams: ["suggestionId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
      timeout: AI_PREVIEW_APPLY_TIMEOUT,
      timeoutKind: "aiPreviewApply",
    }),

    "tasks.cancel": define("POST", ({ taskId }) => `/tasks/${required(taskId, "taskId", "tasks.cancel")}/cancel`, {
      requiredParams: ["taskId"],
      requiredQuery: ["novel_id"],
    }),
    "tasks.retry": define("POST", ({ taskId }) => `/tasks/${required(taskId, "taskId", "tasks.retry")}/retry`, {
      requiredParams: ["taskId"],
      requiredQuery: ["novel_id"],
    }),

    "world.listEntities": define("GET", () => "/world/entities"),
    "world.getReviewTypeCatalog": define("GET", () => "/world/review-type-catalog"),
    "world.listRelationReviewGroups": define("GET", () => "/world/relations/review-groups", {
      requiredQuery: ["novel_id"],
    }),
    "world.reviewRelationsBatch": define("POST", () => "/world/relations/review-batch", {
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["confirmed", "decisions"],
    }),
    "world.listAliasReviewGroups": define("GET", () => "/world/aliases/review-groups", {
      requiredQuery: ["novel_id"],
    }),
    "world.reviewAliasesBatch": define("POST", () => "/world/aliases/review-batch", {
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["confirmed", "decisions"],
    }),
    "world.getEntity": define("GET", ({ id }) => `/world/entities/${required(id, "id", "world.getEntity")}`, {
      requiredParams: ["id"],
      requiredQuery: ["novel_id"],
    }),
    "world.createEntity": define("POST", () => "/world/entities", {
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.updateEntity": define("PUT", ({ id }) => `/world/entities/${required(id, "id", "world.updateEntity")}`, {
      requiredParams: ["id"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.deleteEntity": define("DELETE", ({ id }) => `/world/entities/${required(id, "id", "world.deleteEntity")}`, {
      requiredParams: ["id"],
      requiredQuery: ["novel_id"],
    }),
    "world.getEntityMapPresence": define("GET", ({ id }) => `/world/entities/${required(id, "id", "world.getEntityMapPresence")}/map-presence`, {
      requiredParams: ["id"],
      requiredQuery: ["novel_id"],
    }),
    "world.listMaps": define("GET", () => "/world/maps", {
      requiredQuery: ["novel_id"],
    }),
    "world.getMapArchiveImpact": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapArchiveImpact")}/archive-impact`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.archiveMap": define("POST", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.archiveMap")}/archive`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.restoreMap": define("POST", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.restoreMap")}/restore`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.applyMapEditor": define("POST", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.applyMapEditor")}/editor/apply`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["expected_revision", "commands"],
    }),
    "world.getMapLayerTree": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapLayerTree")}/layer-tree`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.getMapPaths": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapPaths")}/paths`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.getMapPathArchiveImpact": define("GET", ({ mapId, pathId }) => `/world/maps/${required(mapId, "mapId", "world.getMapPathArchiveImpact")}/paths/${required(pathId, "pathId", "world.getMapPathArchiveImpact")}/archive-impact`, {
      requiredParams: ["mapId", "pathId"],
      requiredQuery: ["novel_id"],
    }),
    "world.getMapState": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapState")}/state`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.getMapDashboard": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapDashboard")}/dashboard`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.getMapPlayback": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapPlayback")}/playback`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.getMapTimeline": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapTimeline")}/timeline`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.getMapStateAt": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.getMapStateAt")}/state-at`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id", "scene_index"],
    }),
    "world.listMapObservations": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.listMapObservations")}/observations`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.listProjectMapObservationInbox": define("GET", () => "/world/maps/project-observations/inbox", {
      requiredQuery: ["novel_id"],
    }),
    "world.updateProjectMapObservation": define("PATCH", ({ observationId }) => `/world/maps/project-observations/${required(observationId, "observationId", "world.updateProjectMapObservation")}`, {
      requiredParams: ["observationId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["expected_updated_at"],
    }),
    "world.assignProjectMapObservation": define("POST", ({ observationId }) => `/world/maps/project-observations/${required(observationId, "observationId", "world.assignProjectMapObservation")}/assign`, {
      requiredParams: ["observationId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["map_id", "expected_updated_at"],
    }),
    "world.ignoreProjectMapObservation": define("POST", ({ observationId }) => `/world/maps/project-observations/${required(observationId, "observationId", "world.ignoreProjectMapObservation")}/ignore`, {
      requiredParams: ["observationId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["expected_updated_at"],
    }),
    "world.confirmMapObservation": define("POST", ({ mapId, observationId }) => `/world/maps/${required(mapId, "mapId", "world.confirmMapObservation")}/observations/${required(observationId, "observationId", "world.confirmMapObservation")}/confirm`, {
      requiredParams: ["mapId", "observationId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["expected_updated_at"],
    }),
    "world.updateMapFactStatus": define("PATCH", ({ mapId, factId }) => `/world/maps/${required(mapId, "mapId", "world.updateMapFactStatus")}/facts/${required(factId, "factId", "world.updateMapFactStatus")}`, {
      requiredParams: ["mapId", "factId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.previewQuickCreateMap": define("POST", () => "/world/maps/quick-create/preview", {
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.confirmQuickCreateMap": define("POST", () => "/world/maps/quick-create/confirm", {
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.replaceLocationLayouts": define("PUT", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.replaceLocationLayouts")}/location-layouts`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.replaceTerrainLayerPatches": define("PUT", ({ mapId, layerId }) => `/world/maps/${required(mapId, "mapId", "world.replaceTerrainLayerPatches")}/terrain/layers/${required(layerId, "layerId", "world.replaceTerrainLayerPatches")}/patches`, {
      requiredParams: ["mapId", "layerId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.updateTerrainLayer": define("PATCH", ({ mapId, layerId }) => `/world/maps/${required(mapId, "mapId", "world.updateTerrainLayer")}/terrain/layers/${required(layerId, "layerId", "world.updateTerrainLayer")}`, {
      requiredParams: ["mapId", "layerId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "world.deleteTerrainLayer": define("DELETE", ({ mapId, layerId }) => `/world/maps/${required(mapId, "mapId", "world.deleteTerrainLayer")}/terrain/layers/${required(layerId, "layerId", "world.deleteTerrainLayer")}`, {
      requiredParams: ["mapId", "layerId"],
      requiredQuery: ["novel_id"],
    }),

    "writing.publish": define("POST", () => "/writing/drafts", { hasBody: true }),
    "writing.autosave": define("PUT", ({ draftId }) => `/writing/drafts/${required(draftId, "draftId", "writing.autosave")}`, {
      requiredParams: ["draftId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "writing.checkpoint": define("POST", ({ draftId }) => `/writing/drafts/${required(draftId, "draftId", "writing.checkpoint")}/checkpoint`, {
      requiredParams: ["draftId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),
    "writing.discard": define("POST", ({ draftId }) => `/writing/drafts/${required(draftId, "draftId", "writing.discard")}/discard`, {
      requiredParams: ["draftId"],
      requiredQuery: ["novel_id"],
    }),
    "writing.adoptDraftCandidate": define("POST", ({ draftId }) => `/writing/drafts/${required(draftId, "draftId", "writing.adoptDraftCandidate")}/adopt`, {
      requiredParams: ["draftId"],
      requiredQuery: ["novel_id"],
    }),
    "writing.getDraft": define("GET", ({ chapterIndex }) => `/writing/chapters/${required(chapterIndex, "chapterIndex", "writing.getDraft")}/draft`, {
      requiredParams: ["chapterIndex"],
      requiredQuery: ["novel_id"],
    }),
    "writing.createConflictCheck": define("POST", () => "/writing/conflict-checks", { hasBody: true }),
    "writing.runConflictAiReview": define("POST", ({ checkId }) => `/writing/conflict-checks/${required(checkId, "checkId", "writing.runConflictAiReview")}/ai-review`, {
      requiredParams: ["checkId"],
      hasBody: true,
      timeout: LLM_GENERATE_TIMEOUT,
      timeoutKind: "llmGenerate",
    }),
    "writing.enqueueConflictAiReview": define("POST", ({ checkId }) => `/writing/conflict-checks/${required(checkId, "checkId", "writing.enqueueConflictAiReview")}/ai-review-task`, {
      requiredParams: ["checkId"],
      hasBody: true,
      timeout: AI_TASK_SUBMIT_TIMEOUT,
      timeoutKind: "aiTaskSubmit",
    }),
    "writing.requestConflictAiSuggestion": define("POST", ({ itemId }) => `/writing/conflict-check-items/${required(itemId, "itemId", "writing.requestConflictAiSuggestion")}/ai-suggestion`, {
      requiredParams: ["itemId"],
      hasBody: true,
      timeout: LLM_GENERATE_TIMEOUT,
      timeoutKind: "llmGenerate",
    }),
    "writing.generate": define("POST", () => "/writing/generate", {
      hasBody: true,
      timeout: AI_TASK_SUBMIT_TIMEOUT,
      timeoutKind: "aiTaskSubmit",
    }),

    "outline.analyze": define("POST", () => "/outline/analyze", {
      hasBody: true,
      timeout: AI_TASK_SUBMIT_TIMEOUT,
      timeoutKind: "aiTaskSubmit",
    }),
    "outline.generate": define("POST", () => "/outline/generate", {
      hasBody: true,
      timeout: AI_TASK_SUBMIT_TIMEOUT,
      timeoutKind: "aiTaskSubmit",
    }),
    "outline.applyStructurePreview": define("POST", () => "/outline/generate/apply", {
      hasBody: true,
      requiredBody: ["novel_id", "context_confirmation_id", "source_task_id", "draft_structure", "confirmed"],
      timeout: AI_PREVIEW_APPLY_TIMEOUT,
      timeoutKind: "aiPreviewApply",
    }),
    "outline.getStoryOutline": define("GET", () => "/outline/story-outline", {
      requiredQuery: ["novel_id"],
    }),
    "outline.listStoryOutlineRevisions": define("GET", () => "/outline/story-outline/revisions", {
      requiredQuery: ["novel_id", "skip", "limit"],
    }),
    "outline.getStoryOutlineRevision": define("GET", ({ revisionId }) => `/outline/story-outline/revisions/${required(revisionId, "revisionId", "outline.getStoryOutlineRevision")}`, {
      requiredParams: ["revisionId"],
      requiredQuery: ["novel_id"],
    }),
    "outline.createStoryOutlineRevision": define("POST", () => "/outline/story-outline/revisions", {
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["title", "creative_core", "outline_markdown", "major_storylines", "macro_movements", "open_decisions", "base_revision_id", "idempotency_key"],
    }),
    "outline.restoreStoryOutlineRevision": define("POST", ({ revisionId }) => `/outline/story-outline/revisions/${required(revisionId, "revisionId", "outline.restoreStoryOutlineRevision")}/apply`, {
      requiredParams: ["revisionId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
      requiredBody: ["base_revision_id", "idempotency_key", "confirmed"],
    }),
    "outline.generateStoryOutline": define("POST", () => "/outline/story-outline/generate", {
      hasBody: true,
      requiredBody: ["novel_id", "author_intent", "planned_scale", "coverage", "selected_character_ids", "selected_entity_ids", "include_current_outline"],
      timeout: AI_TASK_SUBMIT_TIMEOUT,
      timeoutKind: "aiTaskSubmit",
    }),
    "outline.applyStoryOutlinePreview": define("POST", () => "/outline/story-outline/generate/apply", {
      hasBody: true,
      requiredBody: ["novel_id", "source_task_id", "title", "creative_core", "outline_markdown", "major_storylines", "macro_movements", "open_decisions", "base_revision_id", "idempotency_key", "confirmed"],
      timeout: AI_PREVIEW_APPLY_TIMEOUT,
      timeoutKind: "aiPreviewApply",
    }),
    "outline.previewSceneFusion": define("POST", () => "/outline/scene-workbench/fusion/preview", {
      requiredQuery: ["novel_id"],
      hasBody: true,
      timeout: LLM_GENERATE_TIMEOUT,
      timeoutKind: "llmGenerate",
    }),

    "context.searchEvidence": define("POST", () => "/context/evidence/search", {
      hasBody: true,
      timeout: RAG_SEARCH_TIMEOUT,
      timeoutKind: "ragSearch",
    }),
    "context.grepEvidence": define("POST", () => "/context/evidence/grep", {
      hasBody: true,
      timeout: RAG_SEARCH_TIMEOUT,
      timeoutKind: "ragSearch",
    }),
    "context.readEvidence": define("POST", () => "/context/evidence/read", {
      hasBody: true,
      timeout: RAG_SEARCH_TIMEOUT,
      timeoutKind: "ragSearch",
    }),

    "rag.search": define("POST", () => "/rag/retrieve", {
      requiredQuery: ["novel_id"],
      hasBody: true,
      timeout: RAG_SEARCH_TIMEOUT,
      timeoutKind: "ragSearch",
    }),
    "rag.prewarm": define("POST", () => "/rag/prewarm", {
      hasBody: true,
      timeout: RAG_PREWARM_TIMEOUT,
      timeoutKind: "ragPrewarm",
    }),
  })

  function getApiContract(name) {
    const contract = API_CONTRACTS[name]
    if (!contract) throw new Error(`Unknown API contract: ${name}`)
    return contract
  }

  function validatePathRequired(contractName, contract, params, query) {
    for (const key of contract.requiredParams) required(params?.[key], key, contractName)
    for (const key of contract.requiredQuery) required(query?.[key], key, contractName)
  }

  function validateRequired(contractName, contract, params, query, body) {
    validatePathRequired(contractName, contract, params, query)
    for (const key of contract.requiredBody) requiredBodyField(body, key, contractName)
  }

  function contractPath(name, params = {}, query = {}) {
    const contract = getApiContract(name)
    validatePathRequired(name, contract, params, query)
    return contract.path(params || {}) + queryString(query || {})
  }

  function contractRequest(name, params = {}, query = {}, options = {}) {
    const contract = getApiContract(name)
    const { body, ...transportOptions } = options || {}
    validateRequired(name, contract, params, query, body)
    const requestOptions = {
      ...transportOptions,
      method: contract.method,
      timeout: transportOptions.timeout ?? contract.timeout,
    }
    if (body !== undefined) requestOptions.body = JSON.stringify(body)
    return {
      path: contractPath(name, params, query),
      method: contract.method,
      options: requestOptions,
    }
  }

  const exported = Object.freeze({
    API_CONTRACTS,
    getApiContract,
    contractPath,
    contractRequest,
    queryString,
  })

  if (typeof window !== "undefined") {
    window.apiContracts = exported
  }
  if (typeof globalThis !== "undefined") {
    globalThis.apiContracts = exported
  }
})()

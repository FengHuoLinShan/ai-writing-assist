/**
 * Shared frontend API contracts.
 *
 * This file intentionally stays classic-script compatible because index.html
 * loads api.js as a classic script and api.js needs these helpers synchronously.
 * Vitest can import it for side effects and read window.apiContracts.
 */
(function () {
  const DEFAULT_TIMEOUT = 15000
  const RAG_SEARCH_TIMEOUT = 60000
  const RAG_PREWARM_TIMEOUT = 75000
  const CONTEXT_CONFIRM_TIMEOUT = 90000

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

    "settings.listGlobalLLMDefaults": define("GET", () => "/settings/llm-defaults"),
    "settings.updateGlobalLLMDefaults": define("PUT", () => "/settings/llm-defaults", { hasBody: true }),
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
    "imports.resumeDeepImport": define("POST", () => "/imports/deep/resume", { hasBody: true }),
    "imports.abandonDeepImport": define("POST", () => "/imports/deep/abandon", { hasBody: true }),

    "context.confirm": define("POST", () => "/context/confirm", {
      hasBody: true,
      timeout: CONTEXT_CONFIRM_TIMEOUT,
      timeoutKind: "contextConfirm",
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

    "tasks.retry": define("POST", ({ taskId }) => `/tasks/${required(taskId, "taskId", "tasks.retry")}/retry`, {
      requiredParams: ["taskId"],
      requiredQuery: ["novel_id"],
    }),

    "world.listEntities": define("GET", () => "/world/entities"),
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
    "world.listMapObservations": define("GET", ({ mapId }) => `/world/maps/${required(mapId, "mapId", "world.listMapObservations")}/observations`, {
      requiredParams: ["mapId"],
      requiredQuery: ["novel_id"],
    }),
    "world.confirmMapObservation": define("POST", ({ mapId, observationId }) => `/world/maps/${required(mapId, "mapId", "world.confirmMapObservation")}/observations/${required(observationId, "observationId", "world.confirmMapObservation")}/confirm`, {
      requiredParams: ["mapId", "observationId"],
      requiredQuery: ["novel_id"],
    }),
    "world.updateMapFactStatus": define("PATCH", ({ mapId, factId }) => `/world/maps/${required(mapId, "mapId", "world.updateMapFactStatus")}/facts/${required(factId, "factId", "world.updateMapFactStatus")}`, {
      requiredParams: ["mapId", "factId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
    }),

    "writing.publish": define("POST", () => "/writing/drafts", { hasBody: true }),
    "writing.autosave": define("PUT", ({ draftId }) => `/writing/drafts/${required(draftId, "draftId", "writing.autosave")}`, {
      requiredParams: ["draftId"],
      requiredQuery: ["novel_id"],
      hasBody: true,
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
    }),
    "writing.enqueueConflictAiReview": define("POST", ({ checkId }) => `/writing/conflict-checks/${required(checkId, "checkId", "writing.enqueueConflictAiReview")}/ai-review-task`, {
      requiredParams: ["checkId"],
      hasBody: true,
    }),

    "outline.applyStructurePreview": define("POST", () => "/outline/generate/apply", {
      hasBody: true,
      requiredBody: ["novel_id", "context_confirmation_id", "source_task_id", "draft_structure", "confirmed"],
    }),
    "outline.applyChapterScenePreview": define("POST", () => "/outline/chapter-scenes/apply", {
      hasBody: true,
      requiredBody: ["novel_id", "context_confirmation_id", "source_task_id", "draft_scenes", "confirmed"],
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

  function validateRequired(contractName, contract, params, query) {
    for (const key of contract.requiredParams) required(params?.[key], key, contractName)
    for (const key of contract.requiredQuery) required(query?.[key], key, contractName)
  }

  function contractPath(name, params = {}, query = {}) {
    const contract = getApiContract(name)
    validateRequired(name, contract, params, query)
    return contract.path(params || {}) + queryString(query || {})
  }

  function contractRequest(name, params = {}, query = {}, options = {}) {
    const contract = getApiContract(name)
    return {
      path: contractPath(name, params, query),
      method: contract.method,
      options: {
        method: contract.method,
        timeout: contract.timeout,
        ...options,
      },
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

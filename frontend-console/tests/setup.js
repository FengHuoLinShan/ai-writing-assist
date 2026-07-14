/**
 * Vitest 全局 setup — 模拟浏览器环境 + 全局变量
 *
 * 各视图依赖的全局变量在此提供 mock 实现，
 * 避免每个测试文件重复 setup。
 */

import { beforeEach, vi } from "vitest"

// ============================================================
// 模拟状态系统 (state.js Proxy)
// ============================================================
const appState = {
  currentProjectId: null,
  currentProject: null,
  currentView: "project",
  currentSubView: null,
  selectedItem: null,
  selectedItems: [],
  mode: "NORMAL",
  projects: [],
  viewStates: {},
  loading: false,
  error: null,
  toast: null,
  backendConnected: true,
  cache: {},
}

globalThis.state = new Proxy(appState, {
  get(target, key) {
    return target[key]
  },
  set(target, key, value) {
    const old = target[key]
    if (old === value) return true
    target[key] = value
    return true
  },
})

// ============================================================
// 模拟工具函数 (state.js)
// ============================================================
globalThis.esc = (str) => {
  if (str == null) return ""
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

globalThis.toast = vi.fn()
globalThis.showModal = vi.fn()
globalThis.showModalHtml = vi.fn((title, htmlString, buttons, options) => {
  if (options === undefined) {
    globalThis.showModal(title, { html: htmlString }, buttons)
    return
  }
  globalThis.showModal(title, { html: htmlString }, buttons, options)
})
globalThis.confirmAction = vi.fn()
globalThis.closeModal = vi.fn()
globalThis.prompt = vi.fn()
globalThis.onStateChange = vi.fn(() => vi.fn()) // returns unsubscribe
globalThis.updateRightPanelForView = vi.fn()

// ============================================================
// 模拟 Router (router.js)
// ============================================================
const _lastSubViewMap = {}
let _currentQuery = new URLSearchParams()

globalThis.router = {
  _lastSubViewMap,
  getLastSubView(viewName) {
    return _lastSubViewMap[viewName] || null
  },
  initRouter: vi.fn(),
  navigate: vi.fn((viewName, subView = null, _pushHistory = true, query = null) => {
    state.currentView = viewName
    state.currentSubView = subView
    _currentQuery = query && typeof query.toString === "function"
      ? new URLSearchParams(query.toString())
      : new URLSearchParams()
  }),
  refresh: vi.fn(),
  registerView: vi.fn(),
  getCurrentView: vi.fn(() => state.currentView),
  getCurrentQuery: vi.fn(() => _currentQuery),
  onNavigate: vi.fn(),
  renderCurrentView: vi.fn(),
}

beforeEach(() => {
  _currentQuery = new URLSearchParams()
  for (const key of Object.keys(_lastSubViewMap)) delete _lastSubViewMap[key]
})

// ============================================================
// 模拟 API (api.js)
// ============================================================
globalThis.api = {
  healthCheck: vi.fn(),
  clearCache: vi.fn(),
  setAccessToken: vi.fn(),
  clearAccessToken: vi.fn(),
  reportFrontendError: vi.fn(async () => null),
  projects: {
    list: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    listLlmProviderTemplates: vi.fn(),
    getLlmSettings: vi.fn(),
    updateLlmSettings: vi.fn(),
    restore: vi.fn(),
    permanentDelete: vi.fn(),
    permanentDeleteMany: vi.fn(),
    startSmartDedupScan: vi.fn(),
    applySmartDedup: vi.fn(),
  },
  rag: {
    search: vi.fn(),
    rebuild: vi.fn(),
    status: vi.fn(),
    prewarm: vi.fn(),
    retryEmbeddings: vi.fn(),
  },
  context: {
    compile: vi.fn(),
    render: vi.fn(),
    confirm: vi.fn(),
    listSnapshots: vi.fn(),
    getSnapshot: vi.fn(),
    evidenceHealth: vi.fn(),
    listRetrievalTraces: vi.fn(),
  },
  generate: {
    listPromptTemplates: vi.fn(),
    createPromptTemplate: vi.fn(),
    updatePromptTemplate: vi.fn(),
    archivePromptTemplate: vi.fn(),
    copyPromptTemplate: vi.fn(),
    listPromptTemplateRevisions: vi.fn(),
    validatePromptTemplate: vi.fn(),
    previewPromptTemplate: vi.fn(),
    objectDraftChat: vi.fn(),
    generateObjectDraft: vi.fn(),
  },
  outline: {
    listScenes: vi.fn(),
    listScenesOrdered: vi.fn(),
    listScenesByChapter: vi.fn(),
    getScene: vi.fn(),
    createScene: vi.fn(),
    updateScene: vi.fn(),
    deleteScene: vi.fn(),
    reorderScenes: vi.fn(),
    listThreads: vi.fn(),
    createThread: vi.fn(),
    updateThread: vi.fn(),
    deleteThread: vi.fn(),
    listArcs: vi.fn(),
    createArc: vi.fn(),
    updateArc: vi.fn(),
    deleteArc: vi.fn(),
    generate: vi.fn(),
    applyStructurePreview: vi.fn(),
    analyze: vi.fn(),
    extractChapterScenes: vi.fn(),
    applyChapterScenePreview: vi.fn(),
    getSceneWorkbench: vi.fn(),
    updateSceneWorkbenchMapping: vi.fn(),
    reviewSceneWorkbench: vi.fn(),
    reviewSceneSourceMappings: vi.fn(),
    previewSceneFusion: vi.fn(),
    saveSceneFusion: vi.fn(),
    previewSceneMerge: vi.fn(),
    mergeScenes: vi.fn(),
    previewSceneSplit: vi.fn(),
    splitScene: vi.fn(),
    listFusionSuggestions: vi.fn(),
    dismissFusionSuggestions: vi.fn(),
    listForeshadowing: vi.fn(),
    createForeshadowing: vi.fn(),
    updateForeshadowing: vi.fn(),
    deleteForeshadowing: vi.fn(),
    listReveals: vi.fn(),
    createReveal: vi.fn(),
    updateReveal: vi.fn(),
    deleteReveal: vi.fn(),
  },
  writing: {
    listChapters: vi.fn(),
    getDraft: vi.fn(),
    get: vi.fn(),
    autosave: vi.fn(),
    checkpoint: vi.fn(),
    discard: vi.fn(),
    autosaveDraftOnly: vi.fn(),
    saveDraft: vi.fn(),
    publish: vi.fn(),
    adoptDraftCandidate: vi.fn(),
    updateDraftStatus: vi.fn(),
    getVersionHistory: vi.fn(),
    deleteDraft: vi.fn(),
    deleteChapter: vi.fn(),
    splitChapter: vi.fn(),
    generate: vi.fn(),
    createConflictCheck: vi.fn(),
    listConflictChecks: vi.fn(),
    getConflictCheck: vi.fn(),
    updateConflictItem: vi.fn(),
    runConflictAiReview: vi.fn(),
    requestConflictAiSuggestion: vi.fn(),
  },
  world: {
    listEntities: vi.fn(),
    listCharacters: vi.fn(),
    getEntity: vi.fn(),
    listEntityBatches: vi.fn(),
    listRelationships: vi.fn(),
    listAliases: vi.fn(),
    createEntity: vi.fn(),
    updateEntity: vi.fn(),
    promoteEntity: vi.fn(),
    extractEntities: vi.fn(),
    extractAliasRelations: vi.fn(),
    deleteEntity: vi.fn(),
    createRelationship: vi.fn(),
    updateRelationship: vi.fn(),
    reviewEditRelationship: vi.fn(),
    deleteRelationship: vi.fn(),
    createAlias: vi.fn(),
    updateAlias: vi.fn(),
    editAlias: vi.fn(),
    deleteAlias: vi.fn(),
    mergeEntity: vi.fn(),
    applyEntityFusionSuggestions: vi.fn(),
    resolveEntityAsAlias: vi.fn(),
    rollbackEntity: vi.fn(),
    listKnowledge: vi.fn(),
    createKnowledge: vi.fn(),
    listBiblePages: vi.fn(),
    createBiblePage: vi.fn(),
    updateBiblePage: vi.fn(),
    refreshBibleProjection: vi.fn(),
    generateBiblePageAi: vi.fn(),
    listSuggestions: vi.fn(),
    confirmSuggestion: vi.fn(),
    editAndConfirmSuggestion: vi.fn(),
    mergeSuggestion: vi.fn(),
    resolveSuggestionAsAlias: vi.fn(),
    rejectSuggestion: vi.fn(),
    listWorldConflicts: vi.fn(),
    // 动态地图
    listMaps: vi.fn(),
    getMap: vi.fn(),
    createMap: vi.fn(),
    updateMap: vi.fn(),
    deleteMap: vi.fn(),
    generateMap: vi.fn(),
    getMapState: vi.fn(),
    getMapDynamicState: vi.fn(),
    getMapDashboard: vi.fn(),
    getMapPlayback: vi.fn(),
    getMapOpenTarget: vi.fn(),
    getMapSceneSummary: vi.fn(),
    getMapQuickCreateContext: vi.fn(),
    previewQuickCreateMap: vi.fn(),
    confirmQuickCreateMap: vi.fn(),
    listLocationLayouts: vi.fn(),
    replaceLocationLayouts: vi.fn(),
    getMapTerrain: vi.fn(),
    replaceTerrainLayerPatches: vi.fn(),
    createTerrainBinding: vi.fn(),
    updateTerrainBinding: vi.fn(),
    batchUpdateTiles: vi.fn(),
    createLocationBindings: vi.fn(),
    updateLocationBinding: vi.fn(),
    deleteLocationBinding: vi.fn(),
    listMapMarkers: vi.fn(),
    createMapMarker: vi.fn(),
    updateMapMarker: vi.fn(),
    deleteMapMarker: vi.fn(),
    getFocusState: vi.fn(),
    createTerritories: vi.fn(),
    deleteTerritoriesByFaction: vi.fn(),
    listMapObservations: vi.fn(),
    createMapObservation: vi.fn(),
    updateMapObservationReview: vi.fn(),
    batchReviewMapObservations: vi.fn(),
    runMapBatchAction: vi.fn(),
    confirmMapObservation: vi.fn(),
    ignoreMapObservation: vi.fn(),
    listMapFacts: vi.fn(),
    updateMapFactStatus: vi.fn(),
  },
  tasks: {
    submit: vi.fn(),
    getStatus: vi.fn(),
    get: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(),
  },
  imports: {
    upload: vi.fn(),
    uploadFile: vi.fn(),
    list: vi.fn(),
    deepImport: vi.fn(),
    startStage: vi.fn(),
    resumeDeepImport: vi.fn(),
    abandonDeepImport: vi.fn(),
  },
  settings: {
    listGlobalLLMDefaults: vi.fn(async () => null),
    updateGlobalLLMDefaults: vi.fn(async (payload) => payload),
    listGlobalAuthorPrefs: vi.fn(async () => null),
    updateGlobalAuthorPrefs: vi.fn(async (payload) => payload),
    listProjectsUsingDefaults: vi.fn(async () => ({ items: [], total: 0, truncated: false })),
    refreshSettings: vi.fn(async () => ({ ok: true })),
    getProjectAuthorPrefs: vi.fn(async () => ({ daily_goal: null, editor_font: null, default_focus_mode: null })),
    updateProjectAuthorPrefs: vi.fn(async (_pid, payload) => payload),
    resetProjectAuthorPrefsField: vi.fn(async () => ({ field: "", reset: true })),
    getEffectiveLLMSettings: vi.fn(async () => null),
    getEffectiveAuthorPrefs: vi.fn(async () => null),
    resetLLMSettingsField: vi.fn(async () => ({ field: "", reset: true })),
  },
}

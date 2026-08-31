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
  mode: "NORMAL",
  projects: [],
  viewStates: {},
  loading: false,
  error: null,
  toast: null,
  backendConnected: true,
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
globalThis.__vitestDefaultState = globalThis.state

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

// ============================================================
// 模拟 Router (router.js)
// ============================================================
const _lastSubViewMap = {}
let _currentQuery = new URLSearchParams()

globalThis.router = {
  _lastSubViewMap,
  _resetTestState() {
    _currentQuery = new URLSearchParams()
    for (const key of Object.keys(_lastSubViewMap)) delete _lastSubViewMap[key]
  },
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
  replace: vi.fn((viewName, subView = null, query = null) => {
    state.currentView = viewName
    state.currentSubView = subView
    _currentQuery = query && typeof query.toString === "function"
      ? new URLSearchParams(query.toString())
      : new URLSearchParams()
  }),
  refresh: vi.fn(),
  registerView: vi.fn(),
  registerViewLoader: vi.fn(),
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
    getWorkspaceSummary: vi.fn(),
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
    proposeSelection: vi.fn(),
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
    worldChat: vi.fn(),
    convergeWorld: vi.fn(),
    exploreWorld: vi.fn(),
    inspectWorldPage: vi.fn(),
    askWorld: vi.fn(),
    openAskWorldCitation: vi.fn(),
    saveAskWorldSuggestion: vi.fn(),
    generateWorldSuggestion: vi.fn(),
    applyWorldPageDraft: vi.fn(),
  },
  outline: {
    getStoryOutline: vi.fn(),
    listStoryOutlineRevisions: vi.fn(),
    getStoryOutlineRevision: vi.fn(),
    createStoryOutlineRevision: vi.fn(),
    restoreStoryOutlineRevision: vi.fn(),
    generateStoryOutline: vi.fn(),
    applyStoryOutlinePreview: vi.fn(),
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
    semanticReview: vi.fn(),
    targetedRevision: vi.fn(),
    applyStructurePreview: vi.fn(),
    analyze: vi.fn(),
    getSceneWorkbench: vi.fn(),
    updateSceneWorkbenchMapping: vi.fn(),
    associateSceneWithChapter: vi.fn(),
    createSceneForChapter: vi.fn(),
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
    listEntityTypes: vi.fn(),
    getReviewTypeCatalog: vi.fn(),
    listRelationReviewGroups: vi.fn(),
    reviewRelationsBatch: vi.fn(),
    listAliasReviewGroups: vi.fn(),
    reviewAliasesBatch: vi.fn(),
    listCharacters: vi.fn(),
    getEntity: vi.fn(),
    fetchEntityImage: vi.fn(),
    uploadEntityImage: vi.fn(),
    listEntityBatches: vi.fn(),
    listRelationships: vi.fn(),
    listAliases: vi.fn(),
    createEntity: vi.fn(),
    updateEntity: vi.fn(),
    promoteEntity: vi.fn(),
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
    updateKnowledge: vi.fn(),
    listBiblePages: vi.fn(),
    createBiblePage: vi.fn(),
    updateBiblePage: vi.fn(),
    listBibleCategories: vi.fn(),
    createBibleCategory: vi.fn(),
    updateBibleCategory: vi.fn(),
    listBibleDrafts: vi.fn(),
    createBibleDraft: vi.fn(),
    updateBibleDraft: vi.fn(),
    discardBibleDraft: vi.fn(),
    previewBibleDraftPublishImpact: vi.fn(),
    publishBibleDraft: vi.fn(),
    listBiblePageRevisions: vi.fn(),
    restoreBiblePageRevision: vi.fn(),
    getBibleSynopsis: vi.fn(),
    refreshBibleSynopsis: vi.fn(),
    setBibleSynopsisAutoRefresh: vi.fn(),
    listBibleSynopsisRevisions: vi.fn(),
    restoreBibleSynopsisRevision: vi.fn(),
    unpinBibleSynopsis: vi.fn(),
    listBibleTemplates: vi.fn(),
    listBiblePageTemplates: vi.fn(),
    refreshBibleProjection: vi.fn(),
    listSuggestions: vi.fn(),
    confirmSuggestion: vi.fn(),
    editAndConfirmSuggestion: vi.fn(),
    mergeSuggestion: vi.fn(),
    resolveSuggestionAsAlias: vi.fn(),
    rejectSuggestion: vi.fn(),
    listWorldConflicts: vi.fn(),
    getMapAtlas: vi.fn(async () => ({ nodes: [], total_pages: 0 })),
    getMapAtlasPageHistory: vi.fn(async () => []),
    createMapAtlasRun: vi.fn(),
    getMapAtlasRun: vi.fn(),
    getLatestMapAtlasRun: vi.fn(async () => null),
    getMapAtlasRunResults: vi.fn(async () => ({ nodes: [], total_pages: 0 })),
    getMapAtlasPagePrompt: vi.fn(),
    updateMapAtlasPagePrompt: vi.fn(),
    confirmMapAtlasPrompts: vi.fn(),
    uploadMapAtlasPage: vi.fn(),
    updateMapAtlasNode: vi.fn(),
    stopMapAtlasRun: vi.fn(),
    resumeMapAtlasRun: vi.fn(),
    reviewMapAtlasPage: vi.fn(),
    retryMapAtlasPage: vi.fn(),
    regenerateMapAtlasPage: vi.fn(),
    editMapAtlasPage: vi.fn(),
    updateMapAtlasAnnotation: vi.fn(),
    fetchMapAtlasImage: vi.fn(),
  },
  tasks: {
    submit: vi.fn(),
    get: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(),
  },
  imports: {
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
    listLLMConnections: vi.fn(async () => ({
      active_provider_id: "deepseek",
      providers: [
        {
          provider_id: "deepseek",
          label: "DeepSeek",
          model: "deepseek-v4-flash",
          connected: false,
          active: true,
          verified_at: null,
        },
        {
          provider_id: "kimi",
          label: "Kimi",
          model: "kimi-k3",
          connected: false,
          active: false,
          verified_at: null,
        },
      ],
    })),
    getImageConnection: vi.fn(async () => ({
      connected: false,
      model: "gpt-image-2",
    })),
    connectImageProvider: vi.fn(async () => ({
      connected: true,
      model: "gpt-image-2",
    })),
    clearImageProvider: vi.fn(async () => ({
      connected: false,
      model: "gpt-image-2",
    })),
    connectLLMProvider: vi.fn(async () => ({})),
    activateLLMProvider: vi.fn(async () => ({})),
    clearLLMProvider: vi.fn(async () => ({})),
    listLLMBalances: vi.fn(async () => ({ items: [] })),
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

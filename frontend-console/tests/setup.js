/**
 * Vitest 全局 setup — 模拟浏览器环境 + 全局变量
 *
 * 各视图依赖的全局变量在此提供 mock 实现，
 * 避免每个测试文件重复 setup。
 */

import { vi } from "vitest"

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
  const div = globalThis.document?.createElement("div")
  if (div) {
    div.textContent = String(str)
    return div.innerHTML
  }
  return String(str)
}

globalThis.toast = vi.fn()
globalThis.showModal = vi.fn()
globalThis.confirmAction = vi.fn()
globalThis.closeModal = vi.fn()
globalThis.prompt = vi.fn()
globalThis.onStateChange = vi.fn(() => vi.fn()) // returns unsubscribe
globalThis.updateRightPanelForView = vi.fn()

// ============================================================
// 模拟 Router (router.js)
// ============================================================
const _lastSubViewMap = {}

globalThis.router = {
  _lastSubViewMap,
  getLastSubView(viewName) {
    return _lastSubViewMap[viewName] || null
  },
  navigate: vi.fn((viewName) => {
    state.currentView = viewName
  }),
  refresh: vi.fn(),
  registerView: vi.fn(),
  getCurrentView: vi.fn(() => state.currentView),
  onNavigate: vi.fn(),
  renderCurrentView: vi.fn(),
}

// ============================================================
// 模拟 API (api.js)
// ============================================================
globalThis.api = {
  projects: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
  rag: {
    search: vi.fn(),
    rebuild: vi.fn(),
    status: vi.fn(),
  },
  context: {
    compile: vi.fn(),
    render: vi.fn(),
  },
  generate: {
    worldCharacter: vi.fn(),
    plotStructure: vi.fn(),
    chapterScene: vi.fn(),
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
    listForeshadowing: vi.fn(),
    updateForeshadowing: vi.fn(),
    listReveals: vi.fn(),
    updateReveal: vi.fn(),
  },
  writing: {
    listChapters: vi.fn(),
    getDraft: vi.fn(),
    get: vi.fn(),
    autosave: vi.fn(),
    saveDraft: vi.fn(),
    publish: vi.fn(),
    updateDraftStatus: vi.fn(),
    getVersionHistory: vi.fn(),
    deleteDraft: vi.fn(),
    deleteChapter: vi.fn(),
    splitChapter: vi.fn(),
  },
  world: {
    listEntities: vi.fn(),
    listEntityBatches: vi.fn(),
    listRelationships: vi.fn(),
    listAliases: vi.fn(),
    createEntity: vi.fn(),
    updateEntity: vi.fn(),
    deleteEntity: vi.fn(),
    createRelationship: vi.fn(),
    deleteRelationship: vi.fn(),
    createAlias: vi.fn(),
    deleteAlias: vi.fn(),
    mergeEntity: vi.fn(),
    rollbackEntity: vi.fn(),
    listKnowledge: vi.fn(),
    createKnowledge: vi.fn(),
  },
  tasks: {
    submit: vi.fn(),
    getStatus: vi.fn(),
    get: vi.fn(),
    cancel: vi.fn(),
  },
  imports: {
    upload: vi.fn(),
    list: vi.fn(),
    deepImport: vi.fn(),
  },
}

/**
 * 全局状态管理 — 使用 Proxy 实现响应式状态
 *
 * 状态变化时触发 onStateChange 回调，视图可监听状态变化刷新。
 * 所有 UI 状态集中管理，避免分散在各个视图中。
 *
 * esc() — shared/esc.js
 * toast / showToastNotification — ui/toast.js
 * showModal / closeModal / confirmAction — ui/modal.js
 */

const appState = {
  /** @type {string|null} 当前项目 ID */
  currentProjectId: null,

  /** @type {Object|null} 当前项目对象 */
  currentProject: null,

  /** @type {string} 当前视图名称 */
  currentView: "project",

  /** @type {string|null} 当前子视图 */
  currentSubView: null,

  /** @type {Object|null} 当前选中的列表项 */
  selectedItem: null,

  /** @type {Array<Object>} 批量选中的列表项 */
  selectedItems: [],

  /** @type {"NORMAL"|"COMMAND"|"SEARCH"|"INSERT"} 当前交互模式 */
  mode: "NORMAL",

  /** @type {string} 命令栏输入 */
  commandInput: "",

  /** @type {string} 搜索查询 */
  searchQuery: "",

  /** @type {{title:string, content:string, type:string}} 右侧批注状态 */
  rightPanel: { title: "帮助说明", content: "", type: "help" },

  /** @type {{message:string, type:string}|null} Toast 通知 */
  toast: null,

  /** @type {boolean} 加载状态 */
  loading: false,

  /** @type {Object<string, any>} 缓存数据 */
  cache: {},

  /** @type {Array<Object>} 项目列表 */
  projects: [],

  /** @type {string|null} 错误信息 */
  error: null,

  /** @type {boolean} 后端连接状态 */
  backendConnected: false,

  /** @type {number} Toast 定时器 ID */
  _toastTimer: null,

  /** @type {Object<string, any>} 各视图保存的状态（切回时恢复用） */
  viewStates: {},

  /** @type {Object|null} 全局设置缓存（多标签同步失效） */
  globalSettingsCache: null,
}

/**
 * 状态变更回调列表
 * @type {Array<function>}
 */
const _stateListeners = []

/**
 * 注册状态变更监听器
 * @param {function} listener - 接收 (key, newValue, oldValue) 的回调
 * @returns {function} 取消监听的函数
 */
function onStateChange(listener) {
  _stateListeners.push(listener)
  return () => {
    const idx = _stateListeners.indexOf(listener)
    if (idx >= 0) _stateListeners.splice(idx, 1)
  }
}

const stateSliceHelpers = globalThis.stateSlices
if (!stateSliceHelpers) {
  throw new Error("stateSlices.js must load before state.js")
}

const stateController = stateSliceHelpers.createStateController({
  listeners: _stateListeners,
  updateUIForState,
})

/**
 * 状态代理 — 拦截 set 操作触发通知
 */
const state = new Proxy(appState, {
  set(target, key, value) {
    const oldValue = target[key]
    if (oldValue === value) return true

    target[key] = value

    stateController.applyStateSideEffects({ key, value, oldValue, target })
    stateController.notifyStateListeners(key, value, oldValue)
    stateController.syncStateDom(key, value)

    return true
  },
  get(target, key) {
    return target[key]
  },
})

/**
 * 保留全局通知/错误服务副作用。静态 shell 的 DOM 投影由 Vue 订阅
 * onStateChange 完成，state 不再直接改写顶部栏、导航或 route host。
 */
function updateUIForState(key, value) {
  switch (key) {
    case "toast": {
      showToastNotification(value)
      break
    }
    case "error": {
      if (value) {
        showToastNotification({ message: String(value), type: "error" })
      }
      break
    }
  }
}

// 导出到全局
window.appState = state
window.onStateChange = onStateChange
window.projectStorageSummary = stateSliceHelpers.projectStorageSummary

// D21: 监听跨标签页 global_settings_cache_version 变更，失效本标签的缓存
stateSliceHelpers.installGlobalSettingsCacheStorageHandler(state)

/**
 * D20-D22: 一次性迁移 localStorage 旧作者偏好到后端项目覆盖。
 * 仅在后端项目偏好行不存在或全字段 NULL 时迁移；后端已有覆盖时跳过并清旧 key。
 * 后端不可达时保留旧 key 不抛。
 * @param {string} projectId
 */
async function tryMigrateLocalAuthorPreferences(projectId) {
  if (!projectId) return
  const key = `novel_author_preferences:${projectId}`
  const raw = localStorage.getItem(key)
  if (!raw) return
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch {
    return
  }
  try {
    const existing = await api.settings.getProjectAuthorPrefs(projectId)
    if (
      existing &&
      (existing.daily_goal !== null ||
        existing.editor_font !== null ||
        existing.default_focus_mode !== null)
    ) {
      localStorage.removeItem(key)
      return
    }
    await api.settings.updateProjectAuthorPrefs(projectId, {
      daily_goal: parsed.dailyGoal ?? null,
      editor_font: parsed.editorFont ?? null,
      default_focus_mode: Boolean(parsed.defaultFocusMode ?? false),
    })
    localStorage.removeItem(key)
  } catch {
    // 后端不可达时保留旧 key
  }
}
window.tryMigrateLocalAuthorPreferences = tryMigrateLocalAuthorPreferences

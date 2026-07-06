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

/**
 * 状态代理 — 拦截 set 操作触发通知
 */
const state = new Proxy(appState, {
  set(target, key, value) {
    const oldValue = target[key]
    if (oldValue === value) return true

    target[key] = value

    // 自动保存项目选择到 localStorage
    if (key === "currentProjectId") {
      if (target.viewStates?.writing && oldValue !== value) {
        delete target.viewStates.writing
      }
      try {
        if (value) localStorage.setItem("novel_currentProjectId", value)
        else localStorage.removeItem("novel_currentProjectId")
      } catch {}
    }
    if (key === "currentProject") {
      try {
        if (value) localStorage.setItem("novel_currentProject", JSON.stringify(value))
        else localStorage.removeItem("novel_currentProject")
      } catch {}
    }

    // 触发监听器
    for (const listener of _stateListeners) {
      try {
        listener(key, value, oldValue)
      } catch (e) {
        console.error("State listener error:", e)
      }
    }

    // 更新 UI 元素
    updateUIForState(key, value)

    return true
  },
  get(target, key) {
    return target[key]
  },
})

/**
 * 根据状态变化更新 UI
 * @param {string} key - 变化的键名
 * @param {*} value - 新值
 */
function updateUIForState(key, value) {
  switch (key) {
    case "currentView": {
      const titleEl = document.getElementById("view-title")
      const moduleEl = document.getElementById("topbar-module")
      if (titleEl) {
        const route = router.getRoute(value)
        titleEl.textContent = route ? route.title : value
      }
      if (moduleEl) {
        const route = router.getRoute(value)
        moduleEl.textContent = route ? route.title : value
      }
      // 更新导航高亮
      document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
        item.classList.toggle("active", item.dataset.view === value)
      })
      updateTopbarSubmodule(value, state.currentSubView)
      updateRightPanelForView(value)
      break
    }
    case "currentSubView": {
      document.querySelectorAll(".subnav-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.subview === value)
      })
      updateTopbarSubmodule(state.currentView, value)
      break
    }
    case "currentProject": {
      const el = document.getElementById("topbar-project")
      if (el) el.textContent = value ? (value.title || value.name || "") : ""
      break
    }
    case "mode": {
      const modeLabel = document.getElementById("command-mode")
      const cmdInput = document.getElementById("command-input")
      if (modeLabel) {
        if (value === "COMMAND") {
          modeLabel.textContent = "命令模式"
          modeLabel.className = "command-mode-label command"
        } else if (value === "SEARCH") {
          modeLabel.textContent = "搜索模式"
          modeLabel.className = "command-mode-label search"
        } else {
          modeLabel.className = "command-mode-label"
        }
      }
      if (cmdInput) {
        if (value === "COMMAND") {
          cmdInput.placeholder = "输入命令..."
        } else if (value === "SEARCH") {
          cmdInput.placeholder = "搜索..."
        } else {
          cmdInput.placeholder = "按 : 命令 / 搜索"
        }
      }
      break
    }
    case "backendConnected": {
      const dot = document.getElementById("topbar-status-dot")
      const text = document.getElementById("topbar-status")
      if (dot) {
        dot.className = "status-indicator " + (value ? "connected" : "disconnected")
      }
      if (text) {
        text.textContent = value ? "已连接" : "未连接"
      }
      break
    }
    case "toast": {
      showToastNotification(value)
      break
    }
    case "loading": {
      const content = document.getElementById("workspace-content")
      if (content && value) {
        if (!content.querySelector(".data-table, .card, .empty-state, .project-grid")) {
          content.innerHTML = '<div class="loading">加载中</div>'
        }
      }
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

/**
 * 更新顶部面包屑子视图名称
 * @param {string} viewName - 父视图名称
 * @param {string} subViewName - 子视图名称
 */
function updateTopbarSubmodule(viewName, subViewName) {
  const el = document.getElementById("topbar-submodule")
  if (!el) return
  const title = router.getSubViewTitle?.(viewName, subViewName)
  if (title) {
    el.textContent = "· " + title
    el.classList.remove("hidden")
  } else {
    el.textContent = ""
    el.classList.add("hidden")
  }
}

const topbarHelpTexts = {
  project: "项目是其他所有模块的根。点击项目卡片即可进入创作流程。",
  world: "管理小说中的人物、地点、物品等长期创作资产。",
  writing: "按章节撰写正文。支持暂存、发布、版本管理。",
  rag: "测试向量检索，验证知识库召回效果。",
  context: "根据当前世界状态编译 LLM 上下文。",
}

function updateTopbarHelpForView(viewName) {
  document.getElementById("topbar-view-note")?.remove()

  const text = topbarHelpTexts[viewName]
  if (!text) return

  const moduleEl = document.getElementById("topbar-module")
  if (!moduleEl) return

  const note = document.createElement("span")
  note.id = "topbar-view-note"
  note.className = "topbar-view-note"
  note.textContent = text
  moduleEl.insertAdjacentElement("afterend", note)
}

/**
 * 根据当前视图更新右侧批注区内容
 * @param {string} viewName - 视图名称
 */
function updateRightPanelForView(viewName) {
  const notes = document.getElementById("contextual-notes")
  updateTopbarHelpForView(viewName)
  if (notes) notes.innerHTML = ""
}

// 导出到全局
window.appState = state
window.onStateChange = onStateChange
window.updateRightPanelForView = updateRightPanelForView

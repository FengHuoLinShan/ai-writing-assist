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

  /** @type {{title:string, content:string, type:string}} 右侧信息栏状态 */
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
      try { localStorage.setItem("novel_currentProjectId", value || "") } catch {}
    }
    if (key === "currentProject" && value) {
      try { localStorage.setItem("novel_currentProject", JSON.stringify(value)) } catch {}
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
      const el = document.getElementById("view-title")
      if (el) {
        const route = router.getRoute(value)
        el.textContent = route ? route.title : value
      }
      // 更新导航高亮
      document.querySelectorAll(".nav-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.view === value)
      })
      break
    }
    case "currentSubView": {
      // 子标签高亮
      document.querySelectorAll(".subnav-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.subview === value)
      })
      break
    }
    case "currentProject": {
      const el = document.getElementById("topbar-project")
      if (el) el.textContent = value ? `项目：${value.title || value.name || ""}` : ""
      break
    }
    case "mode": {
      const el = document.getElementById("topbar-mode")
      if (el) {
        const modeMap = { NORMAL: "浏览", COMMAND: "命令", SEARCH: "搜索", INSERT: "编辑" }
        el.textContent = `模式：${modeMap[value] || value}`
      }
      // 命令栏提示
      const cmdInput = document.getElementById("command-input")
      const cmdPrompt = document.getElementById("command-prompt")
      if (cmdInput && cmdPrompt) {
        if (value === "COMMAND") {
          cmdPrompt.textContent = ":"
          cmdInput.placeholder = "输入命令..."
        } else if (value === "SEARCH") {
          cmdPrompt.textContent = "/"
          cmdInput.placeholder = "搜索..."
        } else {
          cmdPrompt.textContent = ":"
          cmdInput.placeholder = "(:help 查看帮助, / 搜索)"
        }
      }
      break
    }
    case "backendConnected": {
      const el = document.getElementById("topbar-status")
      if (el) {
        el.textContent = value ? "后端：已连接" : "后端：未连接"
        el.className = "topbar-segment topbar-status " + (value ? "connected" : "disconnected")
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
        // 只在内容区为空时显示加载
        if (!content.querySelector(".data-table, .card, .empty-state")) {
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
 * 根据当前视图更新右侧信息栏内容
 * @param {string} viewName - 视图名称
 */
function updateRightPanelForView(viewName) {
  const panelContent = document.getElementById("right-panel-content")
  const panelTitle = document.getElementById("right-panel-title")
  if (!panelContent || !panelTitle) return

  const helpTexts = {
    project: {
      title: "项目管理",
      content: '<div class="help-section"><h4>小说项目</h4><p>项目是其他所有模块的根。</p><h4>创作流程</h4><ol><li>创建项目</li><li>导入正文 → 世界对象自动抽取</li><li>查阅 RAG 知识索引</li><li>编译上下文 → 导出草稿</li></ol></div>',
    },
    world: {
      title: "世界对象",
      content: '<div class="help-section"><h4>世界对象</h4><p>AI 抽取的创作资产直接以正史状态入库。</p><p>通过手动 CRUD 修正和细化。</p></div>',
    },

    writing: {
      title: "手动工作台",
      content: '<div class="help-section"><h4>手动工作台</h4><p>按章节撰写正文。支持暂存、发布、版本管理。</p><p>发布时自动存入 RAG 索引并创建世界状态快照。</p></div>',
    },
    generate: {
      title: "生成中心",
      content: '<div class="help-section"><h4>生成中心</h4><p>按流程生成结构化资产。</p></div>',
    },
  }

  const help = helpTexts[viewName]
  if (help) {
    panelTitle.textContent = help.title
    panelContent.innerHTML = help.content
  }
  const panel = document.getElementById("right-panel")
  if (panel) panel.style.display = ""
}

// 导出到全局
window.appState = state
window.onStateChange = onStateChange
window.updateRightPanelForView = updateRightPanelForView

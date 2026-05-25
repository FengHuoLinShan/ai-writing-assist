/**
 * HTML 转义函数 — 防止 XSS
 * 将用户/LLM/API 数据安全地插入 innerHTML
 * 在所有脚本之前定义，所有视图均可使用
 */
function esc(str) {
  if (str === null || str === undefined) return ""
  var div = document.createElement("div")
  div.textContent = String(str)
  return div.innerHTML
}

/**
 * 全局状态管理 — 使用 Proxy 实现响应式状态
 *
 * 状态变化时触发 onStateChange 回调，视图可监听状态变化刷新。
 * 所有 UI 状态集中管理，避免分散在各个视图中。
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
const _state = new Proxy(appState, {
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
 * 显示 Toast 通知
 * @param {{message:string, type?:string}|null} toast
 */
function showToastNotification(toast) {
  if (!toast || !toast.message) return

  const container = document.getElementById("toast-container")
  if (!container) return

  // 清除旧的定时器和 toast 元素
  if (appState._toastTimer !== null) {
    clearTimeout(appState._toastTimer)
    appState._toastTimer = null
  }
  const existingToasts = container.querySelectorAll(".toast")
  existingToasts.forEach((t) => {
    if (t.parentNode) t.parentNode.removeChild(t)
  })

  const el = document.createElement("div")
  el.className = "toast " + (toast.type || "info")
  el.textContent = toast.message
  container.appendChild(el)

  // 3 秒后自动消失
  appState._toastTimer = setTimeout(() => {
    if (el.parentNode) {
      el.style.opacity = "0"
      el.style.transition = "opacity 0.3s"
      setTimeout(() => {
        if (el.parentNode) el.parentNode.removeChild(el)
        appState._toastTimer = null
      }, 300)
    }
  }, 3000)
}

/**
 * 显示 Toast 通知的便捷函数
 * @param {string} message - 消息内容
 * @param {"info"|"success"|"warning"|"error"} type - 消息类型
 */
function toast(message, type = "info") {
  _state.toast = { message, type }
}

/**
 * 显示模态框
 * @param {string} title - 标题
 * @param {string|HTMLElement} body - 内容
 * @param {Array<{text:string, class?:string, handler:function}>} buttons - 按钮
 */
function showModal(title, body, buttons = []) {
  const overlay = document.getElementById("modal-overlay")
  const titleEl = document.getElementById("modal-title")
  const bodyEl = document.getElementById("modal-body")
  const footerEl = document.getElementById("modal-footer")

  if (!overlay || !titleEl || !bodyEl || !footerEl) return

  titleEl.textContent = title

  if (typeof body === "string") {
    bodyEl.innerHTML = body
  } else {
    bodyEl.innerHTML = ""
    bodyEl.appendChild(body)
  }

  footerEl.innerHTML = ""
  for (const btn of buttons) {
    const el = document.createElement("button")
    el.className = "btn " + (btn.class || "")
    el.textContent = btn.text
    el.addEventListener("click", () => {
      btn.handler()
      closeModal()
    })
    footerEl.appendChild(el)
  }

  // 如果有取消按钮，加在最后
  if (!buttons.some((b) => b.text === "取消" || b.text === "关闭")) {
    const cancel = document.createElement("button")
    cancel.className = "btn"
    cancel.textContent = "取消"
    cancel.addEventListener("click", closeModal)
    footerEl.appendChild(cancel)
  }

  overlay.classList.remove("hidden")
}

/** 关闭模态框 */
function closeModal() {
  const overlay = document.getElementById("modal-overlay")
  if (overlay) overlay.classList.add("hidden")
}

/**
 * 显示确认对话框
 * @param {string} message - 确认消息
 * @param {function} onConfirm - 确认回调
 * @param {string} confirmText - 确认按钮文字
 */
function confirmAction(message, onConfirm, confirmText = "确认") {
  showModal("确认操作", `<p>${message}</p>`, [
    { text: confirmText, class: "btn-danger", handler: onConfirm },
    { text: "取消", handler: closeModal },
  ])
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
      content: '<div class="help-section"><h4>小说项目</h4><p>项目是其他所有模块的根。</p><h4>创作流程</h4><ol><li>创建项目</li><li>构建世界对象与人物</li><li>设计地理与宏观历史</li><li>生成剧情结构</li><li>复查结构</li><li>确认候选入正史</li></ol></div>',
    },
    world: {
      title: "世界对象",
      content: '<div class="help-section"><h4>世界对象</h4><p>AI 抽取的对象先进入候选池，经过去重和确认后才成为正史。</p><h4>候选清洗</h4><ul><li>低重要度对象设为临时</li><li>疑似别名合并到已有对象</li></ul></div>',
    },
    geo: {
      title: "地理历史",
      content: '<div class="help-section"><h4>地理与宏观历史</h4><p>管理地点层级、通行关系、历史时期变化。</p></div>',
    },
    character: {
      title: "人物档案",
      content: '<div class="help-section"><h4>人物档案</h4><p>记录人物的欲望、恐惧、秘密、当前状态。</p><h4>知识边界</h4><p>知识等级：未知→传闻→部分知道→完全知道→错误认知</p></div>',
    },
    memory: {
      title: "长期记忆",
      content: '<div class="help-section"><h4>长期记忆</h4><p>记录小说推进中的状态变化。AI 只生成提案。</p></div>',
    },
    timeline: {
      title: "时间线",
      content: '<div class="help-section"><h4>轻量时间线</h4><p>维护事件顺序，防止剧情冲突。</p></div>',
    },
    outline: {
      title: "剧情结构",
      content: '<div class="help-section"><h4>结构化剧情</h4><ul><li>剧情线：主线/暗线</li><li>篇章纲：8-15 章闭环</li><li>章节卡：目标+冲突+变化</li><li>伏笔计划：埋设→强化→收束</li></ul></div>',
    },
    rag: {
      title: "RAG 检索",
      content: '<div class="help-section"><h4>检索增强</h4><p>从知识库中检索相关信息。用于调试。</p></div>',
    },
    context: {
      title: "上下文编译",
      content: '<div class="help-section"><h4>Context Compiler</h4><p>按需加载、预算控制、防止剧透。</p></div>',
    },
    review: {
      title: "结构复查",
      content: '<div class="help-section"><h4>结构复查</h4><ul><li>Schema 校验</li><li>引用检查</li><li>提前揭示检测</li><li>知识边界验证</li><li>时间线/地理冲突</li></ul></div>',
    },
    writing: {
      title: "草稿导出",
      content: '<div class="help-section"><h4>草稿与导出</h4><p>承载手写正文，导出创作包。</p></div>',
    },
    generate: {
      title: "生成中心",
      content: '<div class="help-section"><h4>生成中心</h4><p>按流程生成结构化资产。先候选，后入正史。</p></div>',
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
window.appState = _state
window.onStateChange = onStateChange
window.toast = toast
window.showModal = showModal
window.closeModal = closeModal
window.confirmAction = confirmAction
window.updateRightPanelForView = updateRightPanelForView

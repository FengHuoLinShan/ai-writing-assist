/**
 * 应用主入口 — 初始化所有子系统，绑定事件
 *
 * 作为单页应用的启动器，负责：
 * 1. 初始化状态管理
 * 2. 初始化路由
 * 3. 注册全局快捷键
 * 4. 绑定命令栏事件
 * 5. 检查后端连接状态
 * 6. 激活默认视图
 */

const App = {
  /** @type {boolean} */
  _initialized: false,

  /**
   * 初始化应用
   */
  async init() {
    if (this._initialized) return
    this._initialized = true

    // 绑定全局 UI 事件
    this._bindNavigation()
    this._bindCommandBar()
    this._bindKeyboard()
    this._bindModalClose()
    this._bindHelpClose()
    this._bindRightPanelClose()

    // 从 localStorage 恢复项目选择
    this._restoreProjectState()

    // 初始化路由
    router.initRouter()

    // 检查后端连接
    this._checkBackendHealth()

    // 定期检查（每 30 秒）
    setInterval(() => this._checkBackendHealth(), 30000)

    console.log("小说结构化创作控制台 v1.0 已启动")
  },

  /**
   * 绑定导航菜单点击
   */
  _bindNavigation() {
    document.querySelectorAll(".nav-item[data-view]").forEach((el) => {
      el.addEventListener("click", () => {
        const viewName = el.dataset.view
        const route = router.getRoute(viewName)
        const lastSub = router.getLastSubView(viewName)
        router.navigate(viewName, lastSub || (route && route.subViews.length > 0 ? route.subViews[0] : null))
      })
    })
  },

  /**
   * 绑定命令栏事件
   */
  _bindCommandBar() {
    const input = document.getElementById("command-input")
    const prompt = document.getElementById("command-prompt")
    const hint = document.getElementById("command-hint")

    if (!input) return

    // 聚焦/失焦
    input.addEventListener("focus", () => {
      state.mode = "COMMAND"
    })

    input.addEventListener("blur", () => {
      if (!input.value) {
        state.mode = "NORMAL"
      }
    })

    // 回车执行
    input.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        e.preventDefault()
        const value = input.value.trim()
        input.value = ""
        state.mode = "NORMAL"

        if (value) {
          await commands.execute(value)
        }

        input.blur()
        document.getElementById("workspace")?.focus()
      }

      if (e.key === "Escape") {
        input.value = ""
        input.blur()
        state.mode = "NORMAL"
      }

      // 自动补全建议（Tab）
      if (e.key === "Tab") {
        e.preventDefault()
        const value = input.value.trim()
        if (value.startsWith(":")) {
          const prefix = value.slice(1)
          const suggestions = commands.getSuggestions(prefix)
          if (suggestions.length > 0) {
            input.value = `:${suggestions[0].name.slice(1)} `
          }
        }
      }

      // 实时提示
      if (e.key === "Backspace" || e.key.length === 1) {
        setTimeout(() => this._updateHint(input, hint), 50)
      }
    })

    // 输入提示
    input.addEventListener("input", () => {
      this._updateHint(input, hint)
    })
  },

  /**
   * 更新命令栏提示
   */
  _updateHint(input, hint) {
    if (!hint) return
    const value = input.value.trim()

    if (!value) {
      hint.textContent = ""
      return
    }

    if (value.startsWith(":")) {
      const prefix = value.slice(1)
      const suggestions = commands.getSuggestions(prefix)
      if (suggestions.length > 0) {
        hint.textContent = `建议：${suggestions.map((s) => s.name).join(" ")}`
      } else {
        hint.textContent = "没有匹配的命令"
      }
    } else if (value.startsWith("/")) {
      hint.textContent = "按 Enter 搜索"
    } else {
      hint.textContent = ""
    }
  },

  /**
   * 绑定全局快捷键
   */
  _bindKeyboard() {
    document.addEventListener("keydown", (e) => {
      // 忽略输入框中的快捷键
      const tag = e.target.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        // Esc 退出输入
        if (e.key === "Escape") {
          e.target.blur()
          state.mode = "NORMAL"
        }
        return
      }

      switch (e.key) {
        case "?":
          e.preventDefault()
          this._showHelp()
          break

        case ":":
          e.preventDefault()
          this._focusCommandBar()
          break

        case "/":
          e.preventDefault()
          this._focusCommandBar("/")
          break

        case "Escape":
          if (!document.getElementById("modal-overlay").classList.contains("hidden")) {
            closeModal()
          } else if (!document.getElementById("help-overlay").classList.contains("hidden")) {
            document.getElementById("help-overlay").classList.add("hidden")
          } else {
            // 返回上一级
            if (state.currentSubView) {
              const route = router.getRoute(state.currentView)
              router.navigate(state.currentView, null)
            }
          }
          break

        case "n":
          // 新建 — 触发视图中的新建按钮
          this._triggerAction("new")
          break

        case "e":
          this._triggerAction("edit")
          break

        case "s":
          // 触发保存：检查当前视图是否有 editCharacter 或 saveDraft 等方法
          if (typeof window.characterView?.editCharacter === "function" && state.selectedItem) {
            window.characterView.editCharacter(state.selectedItem.id || state.selectedItem.character_id)
          } else if (typeof window.writingView?.saveDraft === "function") {
            window.writingView.saveDraft()
          } else {
            this._triggerAction("save") || toast("没有可保存的内容", "info")
          }
          break

        case "g":
          this._triggerAction("generate")
          break

        case "r":
          this._triggerAction("review")
          break

        case "c":
          this._triggerAction("confirm")
          break

        case "i":
          this._triggerAction("ignore")
          break

        case "x":
          this._triggerAction("delete")
          break

        case "j":
          e.preventDefault()
          this._moveSelection(1)
          break

        case "k":
          e.preventDefault()
          this._moveSelection(-1)
          break

        case "h":
          e.preventDefault()
          this._focusSidebar()
          break

        case "l":
          e.preventDefault()
          this._focusRightPanel()
          break

        case "Enter":
          this._triggerAction("select")
          break
      }
    })
  },

  /**
   * 聚焦命令栏
   * @param {string} [prefix] - 前缀
   */
  _focusCommandBar(prefix = ":") {
    const input = document.getElementById("command-input")
    if (input) {
      input.value = prefix
      input.focus()
      // 将光标移到末尾
      const len = input.value.length
      input.setSelectionRange(len, len)
    }
  },

  /**
   * 触发视图中的操作按钮
   * @param {string} action
   */
  _triggerAction(action) {
    const btn = document.querySelector(`[data-action="${action}"]`)
    if (btn) {
      btn.click()
    } else {
      // 尝试从视图操作区找对应按钮
      const actions = document.getElementById("view-actions")
      if (actions) {
        const candidates = actions.querySelectorAll(".btn")
        const actionMap = {
          new: ["新建", "创建", "新增"],
          edit: ["编辑"],
          generate: ["生成"],
          review: ["复查"],
          confirm: ["确认"],
          ignore: ["忽略"],
          delete: ["删除", "废弃"],
          select: ["打开", "查看"],
        }
        const texts = actionMap[action] || []
        for (const btn of candidates) {
          if (texts.some((t) => btn.textContent.includes(t))) {
            btn.click()
            return
          }
        }
      }
    }
  },

  /**
   * 移动选中行
   * @param {number} direction - 1 向下, -1 向上
   */
  _moveSelection(direction) {
    const rows = document.querySelectorAll(".data-table tr.clickable, .data-table tr[data-id]")
    if (rows.length === 0) return

    let currentIdx = -1
    let currentId = null
    if (state.selectedItem) {
      currentId = state.selectedItem.id || state.selectedItem.value
    }

    rows.forEach((row, i) => {
      const rowId = row.dataset.id || row.dataset.value
      if (rowId && rowId === currentId) {
        currentIdx = i
      }
    })

    let nextIdx
    if (currentIdx < 0) {
      nextIdx = direction > 0 ? 0 : rows.length - 1
    } else {
      nextIdx = currentIdx + direction
      if (nextIdx < 0) nextIdx = rows.length - 1
      if (nextIdx >= rows.length) nextIdx = 0
    }

    rows.forEach((row) => row.classList.remove("selected"))
    rows[nextIdx].classList.add("selected")
    rows[nextIdx].scrollIntoView({ block: "nearest" })

    // 更新选中状态
    state.selectedItem = { id: rows[nextIdx].dataset.id || rows[nextIdx].dataset.value }
  },

  /**
   * 聚焦左侧导航
   */
  _focusSidebar() {
    const active = document.querySelector(".nav-item.active")
    const target = active || document.querySelector(".nav-item")
    if (target) {
      if (!target.hasAttribute("tabindex")) {
        target.setAttribute("tabindex", "-1")
      }
      target.focus()
    }
  },

  /**
   * 聚焦右侧信息栏
   */
  _focusRightPanel() {
    const content = document.getElementById("right-panel-content")
    if (content) {
      content.focus()
    }
  },

  /**
   * 显示快捷键帮助
   */
  _showHelp() {
    document.getElementById("help-overlay").classList.remove("hidden")
  },

  /**
   * 绑定模态框关闭
   */
  _bindModalClose() {
    document.getElementById("modal-close")?.addEventListener("click", closeModal)
    document.getElementById("modal-overlay")?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeModal()
    })
  },

  /**
   * 绑定帮助弹窗关闭
   */
  _bindHelpClose() {
    document.getElementById("help-close")?.addEventListener("click", () => {
      document.getElementById("help-overlay").classList.add("hidden")
    })
    document.getElementById("help-overlay")?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) {
        document.getElementById("help-overlay").classList.add("hidden")
      }
    })
  },

  /**
   * 绑定右侧信息栏关闭
   */
  _bindRightPanelClose() {
    document.getElementById("right-panel-close")?.addEventListener("click", () => {
      const panel = document.getElementById("right-panel")
      if (panel) panel.style.display = "none"
    })
  },

  /**
   * 从 localStorage 恢复项目选择状态
   */
  _restoreProjectState() {
    try {
      const savedId = localStorage.getItem("novel_currentProjectId")
      if (savedId) {
        state.currentProjectId = savedId
      }
      const savedProject = localStorage.getItem("novel_currentProject")
      if (savedProject) {
        state.currentProject = JSON.parse(savedProject)
      }
    } catch {}
  },

  /**
   * 检查后端健康状态
   */
  async _checkBackendHealth() {
    const connected = await api.healthCheck()
    state.backendConnected = connected
  },
}

/**
 * 切换"更多"导航折叠
 */
function toggleMoreNav() {
  const container = document.getElementById("more-nav-items")
  const toggle = document.getElementById("more-toggle")
  if (!container || !toggle) return
  const isHidden = container.style.display === "none" || !container.style.display
  container.style.display = isHidden ? "block" : "none"
  toggle.textContent = isHidden ? "▾" : "▸"
}

// 页面加载完成后启动
document.addEventListener("DOMContentLoaded", () => {
  App.init()
})

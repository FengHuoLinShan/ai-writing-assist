/**
 * 路由系统 — 基于 URL hash 的简单前端路由
 *
 * 支持视图切换、子视图、浏览器历史记录。
 * 路由变化时自动更新状态并触发视图渲染。
 */

/**
 * 路由配置
 * 每个路由包含：标题、视图对象、子视图列表
 * @type {Object<string, {title:string, subViews:string[]}>}
 */
const routes = {
  project: { title: "项目", subViews: [] },
  world: { title: "世界对象", subViews: ["objects", "relations", "aliases"] },
  rag: { title: "RAG 检索", subViews: ["status", "search"] },
  context: { title: "上下文", subViews: [] },
  outline: { title: "大纲", subViews: ["scenes", "threads", "arcs"] },
  writing: { title: "手动工作台", subViews: [] },
  generate: { title: "生成中心", subViews: [] },
}

/**
 * 视图渲染器映射
 * 每个视图模块提供 render() 函数
 * @type {Object<string, {render: function, onEnter?: function, onLeave?: function}>}
 */
const viewRenderers = {}

/**
 * 注册视图渲染器
 * @param {string} name - 视图名称
 * @param {Object} renderer - { render(), onEnter?(), onLeave?() }
 */
function registerView(name, renderer) {
  viewRenderers[name] = renderer
}

/**
 * 获取路由配置
 * @param {string} name - 路由名称
 * @returns {{title:string, subViews:string[]}|undefined}
 */
function getRoute(name) {
  return routes[name]
}

/**
 * 获取当前路由
 * @returns {string}
 */
function getCurrentView() {
  return state.currentView
}

/**
 * 视图变更监听器
 * @type {Array<function>}
 */
const _navListeners = []

/**
 * 注册导航监听
 * @param {function} listener
 */
function onNavigate(listener) {
  _navListeners.push(listener)
}

/**
 * 渲染当前视图
 */
let _prevView = null
let _prevRenderedView = null
let _prevRenderedSubView = null

/** @type {Object<string, string|null>} 各视图最后访问的子标签 */
const _lastSubViewMap = {}

/** @type {Object<string, DocumentFragment>} 各视图缓存的 DOM */
const _viewDomCache = {}

/** @type {Set<string>} 标记为 KeepAlive 的视图 */
const _keepAliveViews = new Set(["writing", "outline"])

/**
 * 根据当前是否选择了项目，构造路由 hash
 * 有项目时: #workbench/:pid/:view[/:subView]
 * 无项目时: #:view[/:subView]
 */
function _buildHash(viewName, subView) {
  if (state.currentProjectId && viewName !== "project") {
    const base = `workbench/${state.currentProjectId}/${viewName}`
    return subView ? `${base}/${subView}` : base
  }
  return subView ? `${viewName}/${subView}` : viewName
}

/**
 * 解析 hash，支持两种格式：
 * - workbench/:pid/:view[/:subView]
 * - :view[/:subView]
 */
function _parseHash(hash) {
  const parts = hash.split("/")
  if (parts[0] === "workbench" && parts.length >= 3) {
    return {
      projectId: parts[1],
      viewName: parts[2],
      subView: parts[3] || null,
    }
  }
  return {
    projectId: null,
    viewName: parts[0] || "project",
    subView: parts[1] || null,
  }
}

/**
 * 获取视图最后访问的子标签
 * @param {string} viewName
 * @returns {string|null}
 */
function getLastSubView(viewName) {
  return _lastSubViewMap[viewName] || null
}

async function renderCurrentView() {
  const viewName = state.currentView
  const content = document.getElementById("workspace-content")

  if (!content) return

  // 离开旧视图
  if (_prevView && _prevView !== viewName) {
    const prevRenderer = viewRenderers[_prevView]
    if (prevRenderer) {
      if (_keepAliveViews.has(_prevView) && prevRenderer.onDeactivate) {
        try { prevRenderer.onDeactivate() } catch (e) { console.error(e) }
      }
      if (prevRenderer.onLeave) {
        try { prevRenderer.onLeave() } catch (e) { console.error(e) }
      }
    }
    if (_keepAliveViews.has(_prevView)) {
      const frag = document.createDocumentFragment()
      while (content.firstChild) {
        frag.appendChild(content.firstChild)
      }
      const cacheKey = `${_prevView}:${_prevRenderedSubView || ""}`
      _viewDomCache[cacheKey] = frag
    }
  }
  _prevView = viewName

  const isSameRender = _prevRenderedView === viewName && _prevRenderedSubView === (state.currentSubView || "")
  const renderer = viewRenderers[viewName]

  state.loading = true

  try {
    if (renderer) {
      const cacheKey = `${viewName}:${state.currentSubView || ""}`
      const cached = _viewDomCache[cacheKey]
      if (cached && _keepAliveViews.has(viewName)) {
        content.innerHTML = ""
        content.appendChild(cached)
        delete _viewDomCache[cacheKey]
        if (renderer.onActivate) {
          await renderer.onActivate()
        }
      } else {
        if (!isSameRender && renderer.onEnter) {
          await renderer.onEnter()
        }
        const html = await renderer.render()
        content.innerHTML = html
      }
    } else {
      const route = routes[viewName]
      content.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">&#9744;</div>
          <p>${route ? route.title : viewName} 页面</p>
          <p style="color:var(--text-dim);font-size:12px;">此模块正在开发中，敬请期待</p>
        </div>
      `
    }
  } catch (err) {
    console.error("View render error:", err)
    content.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon" style="color:var(--danger);">&#9888;</div>
        <p style="color:var(--danger);">页面加载失败</p>
        <p style="color:var(--text-dim);font-size:12px;">${err.message}</p>
      </div>
    `
  } finally {
    state.loading = false
    _prevRenderedView = viewName
    _prevRenderedSubView = state.currentSubView || ""
  }

  updateRightPanelForView(viewName)

  for (const listener of _navListeners) {
    try { listener(viewName, state.currentSubView) } catch (e) { console.error(e) }
  }
}

function navigate(viewName, subView = null, pushHistory = true) {
  if (!routes[viewName]) {
    console.warn(`未知路由: ${viewName}`)
    return
  }

  if (state.currentView && state.currentView !== viewName) {
    _lastSubViewMap[state.currentView] = state.currentSubView
  }

  const isSameView = state.currentView === viewName

  state.currentView = viewName
  state.currentSubView = subView

  if (!isSameView) {
    state.selectedItem = null
    state.selectedItems = []
  }

  // 更新 URL hash
  if (pushHistory) {
    const hash = "#" + _buildHash(viewName, subView)
    if (window.location.hash !== hash) {
      window.history.pushState({ view: viewName, subView, projectId: state.currentProjectId }, "", hash)
    }
  }

  // 渲染
  renderCurrentView()
}

/**
 * 根据当前 hash 初始化路由
 */
function initRouter() {
  const hash = window.location.hash.slice(1) || "project"
  const parsed = _parseHash(hash)

  if (parsed.projectId) {
    if (parsed.projectId !== state.currentProjectId) {
      Object.keys(_viewDomCache).forEach((k) => delete _viewDomCache[k])
    }
    state.currentProjectId = parsed.projectId
  }

  if (routes[parsed.viewName]) {
    state.currentView = parsed.viewName
    state.currentSubView = parsed.subView
  } else {
    state.currentView = "project"
  }

  // 监听浏览器前进/后退
  window.addEventListener("popstate", (e) => {
    const hash = window.location.hash.slice(1) || "project"
    const parsed = _parseHash(hash)

    const projectId = parsed.projectId || (e.state && e.state.projectId) || null
    if (projectId) {
      if (projectId !== state.currentProjectId) {
        Object.keys(_viewDomCache).forEach((k) => delete _viewDomCache[k])
      }
      state.currentProjectId = projectId
    }

    const targetView = (e.state && e.state.view) ? e.state.view : parsed.viewName
    const targetSubView = (e.state && e.state.subView !== undefined) ? e.state.subView : parsed.subView

    if (routes[targetView]) {
      state.currentView = targetView
      state.currentSubView = targetSubView
      renderCurrentView()
    }
  })

  renderCurrentView()
}

// 导出
window.router = { navigate, getCurrentView, getRoute, registerView, onNavigate, initRouter, getLastSubView }

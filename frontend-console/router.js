/**
 * 路由系统 — 基于 URL hash 的简单前端路由
 *
 * 支持视图切换、子视图、浏览器历史记录。
 * 路由变化时自动更新状态并触发视图渲染。
 */

/**
 * 路由配置
 * 每个路由包含：标题、视图对象、子视图列表、项目作用域
 * @type {Object<string, {title:string, subViews:string[], requiresProject?: boolean, defaultSubView?: string, dynamicSubView?: boolean}>}
 */
const routes = {
  project: { title: "项目", subViews: [], requiresProject: false },
  world: { title: "世界对象", requiresProject: true, defaultSubView: "objects", subViews: ["objects", "candidates", "review-objects", "review-aliases", "review-relations", "relations", "aliases", "bible", "map"], subViewTitles: { objects: "对象库", candidates: "待处理", "review-objects": "待处理 · 对象", "review-aliases": "待处理 · 别名", "review-relations": "待处理 · 关系", relations: "关系", aliases: "别名", bible: "世界书", map: "地图" } },
  rag: { title: "小说检索", requiresProject: true, defaultSubView: "search", subViews: ["search", "status"], subViewTitles: { search: "检索", status: "索引维护" } },
  outline: { title: "大纲", requiresProject: true, defaultSubView: "scenes", subViews: ["scenes", "threads", "arcs", "foreshadowing", "reveals"], subViewTitles: { scenes: "场景卡", threads: "剧情线", arcs: "篇章纲", foreshadowing: "伏笔", reveals: "揭示" } },
  scene: { title: "场景", subViews: [], requiresProject: true, dynamicSubView: true },
  writing: { title: "写作台", subViews: [], requiresProject: true },
  map: { title: "地图", subViews: [], requiresProject: true },
  generate: { title: "生成中心", subViews: [], requiresProject: true },
  llm: { title: "LLM 设置", subViews: [], requiresProject: false },
  settings: { title: "全局设置", subViews: [], requiresProject: false },
  "project-settings": { title: "项目设置", subViews: [], requiresProject: true },
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
 * 获取子视图标题
 * @param {string} viewName - 父视图名称
 * @param {string} subViewName - 子视图名称
 * @returns {string}
 */
function getSubViewTitle(viewName, subViewName) {
  const route = routes[viewName]
  if (!route || !subViewName) return ""
  return route.subViewTitles?.[subViewName] || subViewName
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
let _prevRenderedProjectId = null

/** @type {Object<string, string|null>} 各视图最后访问的子标签 */
const _lastSubViewMap = {}

/** @type {Object<string, Set<string>>} 不应作为一级导航恢复目标的兼容子标签 */
const _nonRestorableSubViews = {
  world: new Set(["map"]),
}

/** @type {Object<string, DocumentFragment>} 各视图缓存的 DOM */
const _viewDomCache = {}

/** @type {Set<string>} 标记为 KeepAlive 的视图 */
const _keepAliveViews = new Set(["writing", "outline", "scene"])

/** @type {URLSearchParams} 当前 hash 的 query 参数 */
let _currentQuery = new URLSearchParams()

function _viewCacheKey(viewName, subView = null, projectId = state.currentProjectId) {
  return `${projectId || "global"}:${viewName}:${subView || ""}`
}

/**
 * 根据当前是否选择了项目，构造路由 hash
 * 有项目时: #workbench/:pid/:view[/:subView]
 * 无项目时: #:view[/:subView]
 */
function _buildHash(viewName, subView, query = null, projectId = state.currentProjectId) {
  let base
  const route = routes[viewName]
  if (projectId && route?.requiresProject) {
    base = `workbench/${projectId}/${viewName}`
    if (subView) base += `/${subView}`
  } else {
    base = subView ? `${viewName}/${subView}` : viewName
  }
  const q = query || _currentQuery
  const qs = q && q.toString ? q.toString() : ""
  return qs ? `${base}?${qs}` : base
}

/**
 * 获取当前 hash 的 query 参数
 * @returns {URLSearchParams}
 */
function getCurrentQuery() {
  return _currentQuery
}

/**
 * 解析 hash，支持两种格式：
 * - workbench/:pid/:view[/:subView]
 * - :view[/:subView]
 */
function _parseHash(hash) {
  const queryIndex = hash.indexOf("?")
  const path = queryIndex >= 0 ? hash.slice(0, queryIndex) : hash
  const queryString = queryIndex >= 0 ? hash.slice(queryIndex + 1) : ""
  const query = new URLSearchParams(queryString)
  const parts = path.split("/")
  if (parts[0] === "workbench" && parts.length >= 3) {
    return {
      projectId: parts[1],
      viewName: parts[2],
      subView: parts[3] || null,
      query,
    }
  }
  return {
    projectId: null,
    viewName: parts[0] || "project",
    subView: parts[1] || null,
    query,
  }
}

function _projectRedirectResult(query = new URLSearchParams()) {
  return {
    projectId: null,
    viewName: "project",
    subView: null,
    query,
    redirectedToProject: true,
  }
}

function _normalizeRoute({ projectId = null, viewName = "project", subView = null, query = new URLSearchParams() }) {
  let targetProjectId = projectId || null
  let targetView = viewName || "project"
  let targetSubView = subView || null
  let targetQuery = query || new URLSearchParams()

  if (targetView === "context") {
    targetView = "generate"
    targetSubView = null
    targetQuery = new URLSearchParams(targetQuery)
    targetQuery.set("tab", "task")
  }

  if (targetView === "llm") {
    const effectiveProjectId = targetProjectId || state.currentProjectId || null
    targetView = effectiveProjectId ? "project-settings" : "settings"
    targetProjectId = effectiveProjectId
    targetSubView = null
  }

  let route = routes[targetView]
  if (!route) {
    targetProjectId = null
    targetView = "project"
    targetSubView = null
    targetQuery = new URLSearchParams()
    route = routes.project
  }

  if (route.requiresProject) {
    targetProjectId = targetProjectId || state.currentProjectId || null
    if (!targetProjectId) {
      return _projectRedirectResult(new URLSearchParams())
    }
  } else {
    targetProjectId = null
  }

  if (route.subViews && route.subViews.length > 0) {
    if (!targetSubView || !route.subViews.includes(targetSubView)) {
      targetSubView = route.defaultSubView || route.subViews[0]
    }
  } else if (!route.dynamicSubView) {
    targetSubView = null
  }

  return {
    projectId: targetProjectId,
    viewName: targetView,
    subView: targetSubView,
    query: targetQuery,
    redirectedToProject: false,
  }
}

function _hashForRoute(routeState) {
  return "#" + _buildHash(routeState.viewName, routeState.subView, routeState.query, routeState.projectId)
}

async function _applyRoute(routeState) {
  await _syncCurrentProject(routeState.projectId)
  state.currentView = routeState.viewName
  state.currentSubView = routeState.subView
  _currentQuery = routeState.query || new URLSearchParams()
}

/**
 * 获取视图最后访问的子标签
 * @param {string} viewName
 * @returns {string|null}
 */
function getLastSubView(viewName) {
  return _lastSubViewMap[viewName] || null
}

function _rememberSubView(viewName, subView) {
  if (!viewName || !subView) return
  if (_nonRestorableSubViews[viewName]?.has(subView)) return
  _lastSubViewMap[viewName] = subView
}

/**
 * 同步当前项目状态：当 projectId 变化时，清空缓存并加载项目元数据。
 * 避免面包屑/标题显示旧项目名或为空。
 */
async function _syncCurrentProject(projectId, force) {
  // 无 projectId 时保留当前选择（例如项目列表视图），不要清空 localStorage 恢复的状态
  if (!projectId) {
    return
  }

  const changed = state.currentProjectId !== projectId
  if (changed) {
    Object.keys(_viewDomCache).forEach((k) => delete _viewDomCache[k])
    state.currentProjectId = projectId
    state.currentProject = null
  }

  const hasCompleteProject = state.currentProject
    && state.currentProject.id === projectId
    && !state.currentProject.summaryOnly

  // 当前项目对象已存在且 ID 一致时避免重复请求，refresh() 可通过 force 强制刷新
  if (!changed && hasCompleteProject && !force) {
    return
  }

  try {
    const project = await api.projects.get(projectId)
    state.currentProject = project
  } catch (err) {
    console.warn("加载项目信息失败:", err)
    state.currentProject = null
    toast("项目信息加载失败，可稍后重试", "warning")
  }
}

/** @type {boolean} 下一次渲染强制重新执行 onEnter（用于增删改后刷新当前视图） */
let _forceRefresh = false

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
      const cacheKey = _viewCacheKey(_prevView, _prevRenderedSubView, _prevRenderedProjectId)
      _viewDomCache[cacheKey] = frag
    }
  }
  _prevView = viewName

  const forceRefresh = _forceRefresh
  _forceRefresh = false
  const currentProjectId = state.currentProjectId || null
  const isSameRender = !forceRefresh
    && _prevRenderedView === viewName
    && _prevRenderedSubView === (state.currentSubView || "")
    && _prevRenderedProjectId === currentProjectId
  const renderer = viewRenderers[viewName]

  state.loading = true

  try {
    if (renderer) {
      const cacheKey = _viewCacheKey(viewName, state.currentSubView, currentProjectId)
      const cached = _viewDomCache[cacheKey]
      if (cached && _keepAliveViews.has(viewName) && !forceRefresh) {
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
    const stateEl = document.createElement("div")
    stateEl.className = "empty-state"
    const icon = document.createElement("div")
    icon.className = "empty-icon"
    icon.style.color = "var(--danger)"
    icon.textContent = "!"
    const title = document.createElement("p")
    title.style.color = "var(--danger)"
    title.textContent = "页面加载失败"
    const message = document.createElement("p")
    message.style.cssText = "color:var(--text-dim);font-size:12px;"
    message.textContent = err.message || ""
    stateEl.append(icon, title, message)
    content.replaceChildren(stateEl)
  } finally {
    state.loading = false
    _prevRenderedView = viewName
    _prevRenderedSubView = state.currentSubView || ""
    _prevRenderedProjectId = currentProjectId
  }

  updateRightPanelForView(viewName)

  for (const listener of _navListeners) {
    try { listener(viewName, state.currentSubView) } catch (e) { console.error(e) }
  }
}

async function navigate(viewName, subView = null, pushHistory = true, query = null) {
  const routeState = _normalizeRoute({
    projectId: state.currentProjectId || null,
    viewName,
    subView,
    query: query || new URLSearchParams(),
  })

  if (routeState.redirectedToProject) {
    toast("请先选择项目后再进入该页面", "warning")
  }

  if (state.currentView) {
    if (state.currentView !== routeState.viewName || state.currentSubView !== routeState.subView) {
      _rememberSubView(state.currentView, state.currentSubView)
    }
  }

  const isSameView = state.currentView === routeState.viewName
  await _applyRoute(routeState)

  if (!isSameView) {
    state.selectedItem = null
    state.selectedItems = []
  }

  // 更新 URL hash
  if (pushHistory) {
    const hash = _hashForRoute(routeState)
    if (window.location.hash !== hash) {
      window.history.pushState({ view: routeState.viewName, subView: routeState.subView, projectId: routeState.projectId }, "", hash)
    }
  }

  // 渲染
  await renderCurrentView()
}

/**
 * 强制刷新当前视图：重新执行 onEnter()（重新拉取数据）并重渲染。
 * 用于增删改操作后刷新列表 —— navigate 到当前位置会因 isSameRender 跳过 onEnter，
 * 导致界面显示旧数据，refresh 绕过该优化。
 */
async function refresh() {
  _forceRefresh = true
  const cacheKey = _viewCacheKey(state.currentView, state.currentSubView)
  delete _viewDomCache[cacheKey]
  await _syncCurrentProject(state.currentProjectId, true)
  await renderCurrentView()
}

/**
 * 根据当前 hash 初始化路由
 */
async function initRouter() {
  let hash = window.location.hash.slice(1) || "project"
  let parsed = _parseHash(hash)
  let routeState = _normalizeRoute(parsed)
  let canonicalHash = _hashForRoute(routeState)
  if (window.location.hash !== canonicalHash) {
    window.history.replaceState({ view: routeState.viewName, subView: routeState.subView, projectId: routeState.projectId }, "", canonicalHash)
  }
  await _applyRoute(routeState)

  // 监听浏览器前进/后退
  window.addEventListener("popstate", async (e) => {
    try {
      const hash = window.location.hash.slice(1) || "project"
      const parsed = _parseHash(hash)
      const routeState = _normalizeRoute(parsed)
      const canonicalHash = _hashForRoute(routeState)
      if (window.location.hash !== canonicalHash) {
        window.history.replaceState({ view: routeState.viewName, subView: routeState.subView, projectId: routeState.projectId }, "", canonicalHash)
      }
      await _applyRoute(routeState)
      await renderCurrentView()
    } catch (err) {
      console.warn("路由切换失败", err)
      if (typeof toast === "function") toast(`路由切换失败：${err.message || "未知错误"}`, "error")
    }
  })

  await renderCurrentView()
}

// 导出
window.router = { navigate, refresh, getCurrentView, getRoute, getSubViewTitle, registerView, onNavigate, initRouter, getLastSubView, renderCurrentView, getCurrentQuery }

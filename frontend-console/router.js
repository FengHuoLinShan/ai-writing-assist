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
  outline: { title: "大纲", requiresProject: true, defaultSubView: "story-outline", subViews: ["story-outline", "arcs", "threads", "scenes", "foreshadowing", "reveals"], subViewTitles: { "story-outline": "小说总纲", arcs: "篇章纲", threads: "剧情线", scenes: "场景工作台", foreshadowing: "伏笔", reveals: "揭示" } },
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
 * @type {Object<string, {render: function, onEnter?: function, onRendered?: function, onActivate?: function, onDeactivate?: function, canLeave?: function, onLeave?: function}>}
 */
const viewRenderers = {}

/**
 * 注册视图渲染器
 * @param {string} name - 视图名称
 * @param {Object} renderer - { render(), onEnter?(), onRendered?(), onActivate?(), onDeactivate?(), canLeave?(), onLeave?() }
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

function _queueMapTelemetry(routeState) {
  if (routeState?.viewName !== "map") {
    delete globalThis.__mapTelemetryPendingNavigation
    return
  }
  const mapId = routeState.query?.get?.("map_id") || null
  if (!mapId) {
    delete globalThis.__mapTelemetryPendingNavigation
    return
  }
  globalThis.__mapTelemetryPendingNavigation = {
    mapId,
    route: _hashForRoute(routeState),
    startedAt: globalThis.performance?.now?.() ?? Date.now(),
  }
}

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
const _keepAliveViews = new Set(["writing", "outline"])

/** @type {URLSearchParams} 当前 hash 的 query 参数 */
let _currentQuery = new URLSearchParams()

/** 当前项目元数据同步的取消与代次边界，防止快速切换时旧响应回写。 */
let _projectSyncController = null
let _projectSyncGeneration = 0

function _viewCacheKey(viewName, subView = null, projectId = state.currentProjectId) {
  return `${projectId || "global"}:${viewName}:${subView || ""}`
}

function _shouldKeepAlive(viewName, subView = null) {
  return _keepAliveViews.has(viewName) && !(viewName === "outline" && subView === "scenes")
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

  // Scene 工作台已并入大纲页。保留旧 scene 路由兼容外部链接和现有调用方。
  if (targetView === "scene") {
    targetQuery = new URLSearchParams(targetQuery)
    if (targetSubView) targetQuery.set("scene_id", targetSubView)
    targetView = "outline"
    targetSubView = "scenes"
  }

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

function _renderedRouteState() {
  const renderedMatchesState = _prevRenderedView === state.currentView
  return {
    projectId: renderedMatchesState
      ? _prevRenderedProjectId
      : (state.currentProjectId || null),
    viewName: renderedMatchesState
      ? _prevRenderedView
      : state.currentView,
    subView: renderedMatchesState
      ? (_prevRenderedSubView || null)
      : (state.currentSubView || null),
    query: _currentQuery,
  }
}

function _isRouteTransition(routeState) {
  const current = _renderedRouteState()
  return current.viewName !== routeState.viewName
    || current.subView !== (routeState.subView || null)
    || current.projectId !== (routeState.projectId || null)
    || current.query.toString() !== (routeState.query || new URLSearchParams()).toString()
}

function _canLeaveCurrentRoute(routeState) {
  if (!_isRouteTransition(routeState)) return true
  const current = _renderedRouteState()
  const renderer = viewRenderers[current.viewName]
  if (!renderer?.canLeave) return true
  try {
    return renderer.canLeave() !== false
  } catch (err) {
    console.error(err)
    return false
  }
}

function _restoreRenderedRouteHash() {
  const current = _renderedRouteState()
  const hash = _hashForRoute(current)
  if (window.location.hash === hash) return
  window.history.pushState({
    view: current.viewName,
    subView: current.subView,
    projectId: current.projectId,
  }, "", hash)
}

async function _applyRoute(routeState) {
  const isCurrent = await _syncCurrentProject(routeState.projectId)
  if (!isCurrent) return false
  state.currentView = routeState.viewName
  state.currentSubView = routeState.subView
  _currentQuery = routeState.query || new URLSearchParams()
  return true
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
  const generation = ++_projectSyncGeneration
  if (_projectSyncController) {
    _projectSyncController.abort()
    _projectSyncController = null
  }

  // 无 projectId 时保留当前选择（例如项目列表视图），不要清空 localStorage 恢复的状态
  if (!projectId) {
    return true
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
    return true
  }

  const controller = new AbortController()
  _projectSyncController = controller
  try {
    const project = await api.projects.get(projectId, {
      signal: controller.signal,
      cache: "no-store",
    })
    if (generation !== _projectSyncGeneration || state.currentProjectId !== projectId) return false
    state.currentProject = project
    return true
  } catch (err) {
    if (controller.signal.aborted || generation !== _projectSyncGeneration) return false
    console.warn("加载项目信息失败:", err)
    state.currentProject = null
    toast("项目信息加载失败，可稍后重试", "warning")
    return true
  } finally {
    if (_projectSyncController === controller) {
      _projectSyncController = null
    }
  }
}

/** @type {boolean} 下一次渲染强制重新执行 onEnter（用于增删改后刷新当前视图） */
let _forceRefresh = false
let _renderGeneration = 0

async function renderCurrentView() {
  const renderGeneration = ++_renderGeneration
  const viewName = state.currentView
  const subView = state.currentSubView || ""
  const content = document.getElementById("workspace-content")
  if (!content) return
  // Keep visual scoping independent from rendered copy and business data. The
  // editorial theme uses these route markers to tune dense workspaces without
  // changing their DOM contracts or interaction handlers.
  content.dataset.workspaceView = viewName || "unknown"
  content.dataset.workspaceSubview = subView || "root"
  const isCurrentRender = () => (
    renderGeneration === _renderGeneration
    && state.currentView === viewName
    && (state.currentSubView || "") === subView
  )

  // 离开旧视图
  if (_prevView && _prevView !== viewName) {
    const prevRenderer = viewRenderers[_prevView]
    if (prevRenderer) {
      const keepAlive = _shouldKeepAlive(_prevView, _prevRenderedSubView)
      if (keepAlive && prevRenderer.onDeactivate) {
        try { prevRenderer.onDeactivate() } catch (e) { console.error(e) }
      }
      // Keep-alive views retain their renderer instances and DOM. `onLeave`
      // tears down that instance, so calling it here leaves restored DOM bound
      // to cleared module state on the next activation.
      if (!keepAlive && prevRenderer.onLeave) {
        try { prevRenderer.onLeave() } catch (e) { console.error(e) }
      }
    }
    if (_shouldKeepAlive(_prevView, _prevRenderedSubView)) {
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
      if (cached && _shouldKeepAlive(viewName, state.currentSubView) && !forceRefresh) {
        if (!isCurrentRender()) return false
        content.innerHTML = ""
        content.appendChild(cached)
        delete _viewDomCache[cacheKey]
        if (renderer.onActivate) {
          await renderer.onActivate()
          if (!isCurrentRender()) return false
        }
      } else {
        if (!isSameRender && renderer.onEnter) {
          await renderer.onEnter()
          if (!isCurrentRender()) return false
        }
        const html = await renderer.render()
        if (!isCurrentRender()) return false
        content.innerHTML = html
        if (renderer.onRendered) {
          await renderer.onRendered()
          if (!isCurrentRender()) return false
        }
      }
    } else {
      if (!isCurrentRender()) return false
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
    if (!isCurrentRender()) return false
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
    if (isCurrentRender()) {
      state.loading = false
      _prevRenderedView = viewName
      _prevRenderedSubView = subView
      _prevRenderedProjectId = currentProjectId
    }
  }

  if (!isCurrentRender()) return false
  updateRightPanelForView(viewName)

  for (const listener of _navListeners) {
    try { listener(viewName, state.currentSubView) } catch (e) { console.error(e) }
  }
  return true
}

async function _navigateWithHistory(viewName, subView, query, historyMode) {
  const routeState = _normalizeRoute({
    projectId: state.currentProjectId || null,
    viewName,
    subView,
    query: query || new URLSearchParams(),
  })

  if (routeState.redirectedToProject) {
    toast("请先选择项目后再进入该页面", "warning")
  }

  if (!_canLeaveCurrentRoute(routeState)) return false
  _queueMapTelemetry(routeState)

  if (state.currentView) {
    if (state.currentView !== routeState.viewName || state.currentSubView !== routeState.subView) {
      _rememberSubView(state.currentView, state.currentSubView)
    }
  }

  const isSameView = state.currentView === routeState.viewName
  const isCurrent = await _applyRoute(routeState)
  if (!isCurrent) return false

  if (!isSameView) {
    state.selectedItem = null
    state.selectedItems = []
  }

  // 更新 URL hash
  if (historyMode !== "none") {
    const hash = _hashForRoute(routeState)
    if (window.location.hash !== hash) {
      const method = historyMode === "replace" ? "replaceState" : "pushState"
      window.history[method]({
        view: routeState.viewName,
        subView: routeState.subView,
        projectId: routeState.projectId,
      }, "", hash)
    }
  }

  // 渲染
  await renderCurrentView()
  return true
}

async function navigate(viewName, subView = null, pushHistory = true, query = null) {
  return _navigateWithHistory(
    viewName,
    subView,
    query || new URLSearchParams(),
    pushHistory ? "push" : "none",
  )
}

async function replace(viewName, subView = null, query = null) {
  return _navigateWithHistory(
    viewName,
    subView,
    query || new URLSearchParams(),
    "replace",
  )
}

/**
 * 强制刷新当前视图：重新执行 onEnter()（重新拉取数据）并重渲染。
 * 用于增删改操作后刷新列表 —— navigate 到当前位置会因 isSameRender 跳过 onEnter，
 * 导致界面显示旧数据，refresh 绕过该优化。
 */
async function refresh() {
  const isCurrent = await _syncCurrentProject(state.currentProjectId, true)
  if (!isCurrent) return false
  _forceRefresh = true
  const cacheKey = _viewCacheKey(state.currentView, state.currentSubView)
  delete _viewDomCache[cacheKey]
  await renderCurrentView()
  return true
}

let _popstateBound = false

async function _handlePopState() {
  try {
    const hash = window.location.hash.slice(1) || "project"
    const parsed = _parseHash(hash)
    const routeState = _normalizeRoute(parsed)
    if (!_canLeaveCurrentRoute(routeState)) {
      _restoreRenderedRouteHash()
      return false
    }
    _queueMapTelemetry(routeState)
    const canonicalHash = _hashForRoute(routeState)
    if (window.location.hash !== canonicalHash) {
      window.history.replaceState({ view: routeState.viewName, subView: routeState.subView, projectId: routeState.projectId }, "", canonicalHash)
    }
    const isCurrent = await _applyRoute(routeState)
    if (!isCurrent) return
    await renderCurrentView()
  } catch (err) {
    console.warn("路由切换失败", err)
    if (typeof toast === "function") toast(`路由切换失败：${err.message || "未知错误"}`, "error")
  }
}

/**
 * 根据当前 hash 初始化路由
 */
async function initRouter() {
  // Bind before the initial metadata await so an immediate browser back/forward
  // invalidates the initializing route instead of being missed.
  if (!_popstateBound) {
    window.addEventListener("popstate", _handlePopState)
    _popstateBound = true
  }

  let hash = window.location.hash.slice(1) || "project"
  let parsed = _parseHash(hash)
  let routeState = _normalizeRoute(parsed)
  _queueMapTelemetry(routeState)
  let canonicalHash = _hashForRoute(routeState)
  if (window.location.hash !== canonicalHash) {
    window.history.replaceState({ view: routeState.viewName, subView: routeState.subView, projectId: routeState.projectId }, "", canonicalHash)
  }
  const isCurrent = await _applyRoute(routeState)
  if (!isCurrent) return false

  await renderCurrentView()
  return true
}

// 导出
window.router = { navigate, replace, refresh, getCurrentView, getRoute, getSubViewTitle, registerView, onNavigate, initRouter, getLastSubView, renderCurrentView, getCurrentQuery }

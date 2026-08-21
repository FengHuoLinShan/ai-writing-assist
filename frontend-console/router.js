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
  home: { title: "选择使用方式", subViews: [], requiresProject: false },
  project: { title: "作品档案", subViews: [], requiresProject: false },
  journeys: { title: "互动故事", subViews: [], requiresProject: false, dynamicSubView: true },
  interaction: { title: "互动故事", subViews: [], requiresProject: false, dynamicSubView: true },
  // Today is now the compatibility name for the writing home.  Keeping the
  // route entry lets old bookmarks resolve without keeping a second page.
  today: { title: "写作首页", subViews: [], requiresProject: true },
  world: { title: "人物与世界", requiresProject: true, defaultSubView: "objects", subViews: ["objects", "candidates", "review-objects", "review-aliases", "review-relations", "relations", "aliases", "bible"], subViewTitles: { objects: "人物与设定", candidates: "需要处理", "review-objects": "需要处理 · 人物与设定", "review-aliases": "需要处理 · 别名", "review-relations": "需要处理 · 关系", relations: "关系", aliases: "人物与设定 · 别名", bible: "世界笔记" } },
  rag: { title: "查找", requiresProject: true, defaultSubView: "search", subViews: ["search", "status"], subViewTitles: { search: "查找", status: "索引诊断" } },
  outline: { title: "故事结构", requiresProject: true, defaultSubView: "story-outline", subViews: ["story-outline", "arcs", "threads", "scenes"], subViewTitles: { "story-outline": "故事总览", arcs: "篇章", threads: "剧情线", scenes: "场景" } },
  scene: { title: "场景", subViews: [], requiresProject: true, dynamicSubView: true },
  writing: { title: "写作", subViews: [], requiresProject: true },
  map: { title: "地图", subViews: [], requiresProject: true },
  generate: { title: "高级生成工具", subViews: [], requiresProject: true },
  llm: { title: "模型连接", subViews: [], requiresProject: false },
  settings: { title: "账户与模型连接", subViews: [], requiresProject: false },
  "project-settings": { title: "项目偏好", subViews: [], requiresProject: true },
}

/**
 * 视图渲染器映射
 * 每个视图模块提供 render() 函数
 * @type {Object<string, {render: function, onEnter?: function, onRendered?: function, canLeave?: function, onLeave?: function}>}
 */
const viewRenderers = new Map()

/**
 * Route-level module loaders. A loaded module self-registers its renderer via
 * registerView(), preserving the existing island registration contract.
 * @type {Object<string, () => Promise<unknown>>}
 */
const viewLoaders = new Map()

/** @type {Object<string, Promise<Object>>} */
const pendingViewLoaders = new Map()

const SAFE_REGISTRY_KEY_RE = /^[a-z][a-z0-9-]{0,63}$/
const UNSAFE_REGISTRY_KEYS = new Set(["__proto__", "prototype", "constructor"])

function isSafeRegistryKey(name) {
  return typeof name === "string"
    && SAFE_REGISTRY_KEY_RE.test(name)
    && !UNSAFE_REGISTRY_KEYS.has(name)
}

/**
 * 注册视图渲染器
 * @param {string} name - 视图名称
 * @param {Object} renderer - { render(), onEnter?(), onRendered?(), canLeave?(), onLeave?() }
 */
function registerView(name, renderer) {
  if (!isSafeRegistryKey(name) || !renderer || typeof renderer !== "object") return
  viewRenderers.set(name, renderer)
}

/**
 * Register a route module loader. Existing renderers always take precedence,
 * so this remains backward compatible for eager/legacy registrations.
 * @param {string} name - normalized route name
 * @param {() => Promise<unknown>} loader - module import which self-registers the renderer
 */
function registerViewLoader(name, loader) {
  if (!isSafeRegistryKey(name) || typeof loader !== "function") return
  viewLoaders.set(name, loader)
}

function _loadViewRenderer(viewName) {
  if (!isSafeRegistryKey(viewName)) return Promise.resolve(null)
  if (viewRenderers.has(viewName)) return Promise.resolve(viewRenderers.get(viewName))
  const loader = viewLoaders.get(viewName)
  if (!loader) return Promise.resolve(null)

  let pending = pendingViewLoaders.get(viewName)
  if (!pending) {
    pending = Promise.resolve()
      .then(() => loader())
      .then(() => {
        const renderer = viewRenderers.get(viewName)
        if (!renderer) {
          throw new Error(`Route module did not register renderer: ${viewName}`)
        }
        return renderer
      })
    pendingViewLoaders.set(viewName, pending)
    const clearPending = () => {
      if (pendingViewLoaders.get(viewName) === pending) pendingViewLoaders.delete(viewName)
    }
    pending.then(clearPending, clearPending)
  }
  return pending
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
  return () => {
    const index = _navListeners.indexOf(listener)
    if (index >= 0) _navListeners.splice(index, 1)
  }
}

function _showRouteLoadingSkeleton(content) {
  const status = document.createElement("div")
  status.className = "loading-skeleton"
  status.setAttribute("role", "status")
  status.setAttribute("aria-live", "polite")
  status.setAttribute("aria-busy", "true")

  const label = document.createElement("span")
  label.className = "sr-only"
  label.textContent = "工作区加载中..."
  status.append(label)

  for (const className of [
    "skeleton loading-skeleton__heading",
    "skeleton loading-skeleton__line",
    "skeleton loading-skeleton__line loading-skeleton__line--medium",
    "skeleton loading-skeleton__line loading-skeleton__line--short",
  ]) {
    const bar = document.createElement("div")
    bar.className = className
    bar.setAttribute("aria-hidden", "true")
    status.append(bar)
  }
  content.replaceChildren(status)
}

function _showProjectLoadFailure(content, failure) {
  const inaccessible = failure?.kind === "inaccessible"
  const stateEl = document.createElement("div")
  stateEl.className = "empty-state project-route-failure"
  stateEl.setAttribute("role", "alert")

  const icon = document.createElement("div")
  icon.className = "empty-icon"
  icon.textContent = inaccessible ? "×" : "!"

  const title = document.createElement("h2")
  title.className = "project-route-failure__title"
  title.tabIndex = -1
  title.textContent = inaccessible ? "无法打开这部作品" : "作品暂时加载失败"

  const message = document.createElement("p")
  message.className = "project-route-failure__message"
  message.textContent = inaccessible
    ? "作品不存在，或你没有访问权限。"
    : "当前页面没有加载完成，可以重试或返回项目列表。"

  const actions = document.createElement("div")
  actions.className = "actions project-route-failure__actions"

  if (!inaccessible) {
    const retry = document.createElement("button")
    retry.type = "button"
    retry.className = "btn btn-primary"
    retry.dataset.action = "retry-project-route"
    retry.textContent = "重试"
    retry.addEventListener("click", () => {
      void _retryFailedProjectRoute(failure)
    })
    actions.append(retry)
  }

  const back = document.createElement("button")
  back.type = "button"
  back.className = inaccessible ? "btn btn-primary" : "btn"
  back.dataset.action = "return-project-list"
  back.textContent = "返回作品档案"
  back.addEventListener("click", () => {
    void _returnFromFailedProjectRoute(failure)
  })
  actions.append(back)

  stateEl.append(icon, title, message, actions)
  content.replaceChildren(stateEl)
  title.focus()
}

/**
 * 渲染当前视图
 */
let _mountedRoute = null
let _pendingRoute = null
let _failureRoute = null
let _renderingRoute = null
let _routeTransitionGeneration = 0

/** @type {Object<string, string|null>} 各视图最后访问的子标签 */
const _lastSubViewMap = new Map()

/** @type {URLSearchParams} 当前 hash 的 query 参数 */
let _currentQuery = new URLSearchParams()

/** 当前项目元数据同步的取消与代次边界，防止快速切换时旧响应回写。 */
let _projectSyncController = null
let _projectSyncGeneration = 0

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

/** 更新当前页的 query，不重新执行 onEnter/render。 */
function commitCurrentQuery(query, historyMode = "replace") {
  const mounted = _currentMountedRoute()
  if (!mounted || _pendingRoute || _currentFailureRoute()) return false
  if (historyMode !== "replace" && historyMode !== "push") return false
  const route = mounted.route
  if (
    route.viewName !== state.currentView
    || (route.subView || null) !== (state.currentSubView || null)
    || (route.projectId || null) !== (state.currentProjectId || null)
  ) return false
  const nextQuery = new URLSearchParams(query?.toString?.() || "")
  _currentQuery = nextQuery
  route.query = new URLSearchParams(nextQuery)
  const hash = _hashForRoute(route)
  if (window.location.hash !== hash) {
    window.history[historyMode === "push" ? "pushState" : "replaceState"]({
      view: route.viewName,
      subView: route.subView,
      projectId: route.projectId,
    }, "", hash)
  }
  return true
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
    viewName: parts[0] || "home",
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

  // The old Today entry is a thin alias.  The writing island owns the home
  // state so a chapter is never implicitly selected by a mobile redirect.
  if (targetView === "today") {
    targetView = "writing"
    targetSubView = null
    targetQuery = new URLSearchParams(targetQuery)
    targetQuery.set("home", "1")
  }

  // Scene 工作台已并入大纲页。保留旧 scene 路由兼容外部链接和现有调用方。
  if (targetView === "scene") {
    targetQuery = new URLSearchParams(targetQuery)
    if (targetSubView) targetQuery.set("scene_id", targetSubView)
    targetView = "outline"
    targetSubView = "scenes"
  }

  // 伏笔与揭示已归并为剧情线的信息推进。旧链接仍可定位到归并后的区域。
  if (targetView === "outline" && ["foreshadowing", "reveals"].includes(targetSubView)) {
    targetQuery = new URLSearchParams(targetQuery)
    targetQuery.set("information", targetSubView)
    targetSubView = "threads"
  }

  if (targetView === "context") {
    targetView = "generate"
    targetSubView = null
    targetQuery = new URLSearchParams(targetQuery)
    targetQuery.set("tab", "task")
  }

  // Generate remains a compatibility alias.  The owner page opens its
  // contextual drawer and reuses the old GenerateView session/controller.
  if (targetView === "generate") {
    const generateQuery = new URLSearchParams(targetQuery)
    const generateTab = generateQuery.get("tab") || "world"
    targetView = generateTab === "world" ? "world" : "writing"
    targetSubView = generateTab === "world"
      ? (generateQuery.get("source_page_id") ? "bible" : "objects")
      : null
    generateQuery.set("owner_ai", "1")
    generateQuery.set("owner_ai_mode", generateTab)
    targetQuery = generateQuery
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

function _copyRouteState(routeState) {
  return {
    projectId: routeState?.projectId || null,
    viewName: routeState?.viewName || "project",
    subView: routeState?.subView || null,
    query: new URLSearchParams(routeState?.query?.toString?.() || ""),
    redirectedToProject: Boolean(routeState?.redirectedToProject),
  }
}

function _routeStateFromAppState() {
  const viewName = state.currentView || "project"
  return {
    projectId: routes[viewName]?.requiresProject
      ? (state.currentProjectId || null)
      : null,
    viewName,
    subView: state.currentSubView || null,
    query: new URLSearchParams(_currentQuery.toString()),
    redirectedToProject: false,
  }
}

function _sameRoute(left, right) {
  if (!left || !right) return false
  return left.viewName === right.viewName
    && (left.subView || null) === (right.subView || null)
    && (left.projectId || null) === (right.projectId || null)
    && (left.query || new URLSearchParams()).toString()
      === (right.query || new URLSearchParams()).toString()
}

function _captureFocusedControl(content) {
  const active = document.activeElement
  if (!active || !content.contains(active)) return null
  if (active.id) return { elementId: active.id }
  const action = active.dataset?.action
  if (!action) return null
  return { action, dataId: active.dataset.id || null }
}

function _restoreFocusedControl(content, owner) {
  if (!owner) return
  const control = owner.elementId
    ? content.querySelector(`#${CSS.escape(owner.elementId)}`)
    : Array.from(content.querySelectorAll(`[data-action="${CSS.escape(owner.action)}"]`))
      .find((item) => (item.dataset.id || null) === owner.dataId)
  if (control && !control.disabled) control.focus({ preventScroll: true })
}

function _currentMountedRoute() {
  if (!_mountedRoute) return null
  const content = document.getElementById("workspace-content")
  if (
    !_mountedRoute.host?.isConnected
    || !content
    || _mountedRoute.host !== content
  ) {
    _mountedRoute = null
    return null
  }
  return _mountedRoute
}

function _currentFailureRoute() {
  if (!_failureRoute) return null
  const content = document.getElementById("workspace-content")
  if (
    _failureRoute.host
    && (!_failureRoute.host.isConnected || _failureRoute.host !== content)
  ) {
    _failureRoute = null
    return null
  }
  return _failureRoute
}

function _representedRouteState() {
  const mounted = _currentMountedRoute()
  if (mounted) return _copyRouteState(mounted.route)
  const failure = _currentFailureRoute()
  if (failure) return _copyRouteState(failure.route)
  if (_pendingRoute) return _copyRouteState(_pendingRoute.route)
  return _routeStateFromAppState()
}

function _isRouteTransition(routeState) {
  return !_sameRoute(_representedRouteState(), routeState)
}

function _canLeaveMountedRoute(routeState) {
  if (!_isRouteTransition(routeState)) return true
  const mounted = _currentMountedRoute()
  const renderer = mounted?.renderer || (
    !_pendingRoute && !_currentFailureRoute()
      ? viewRenderers.get(state.currentView)
      : null
  )
  if (!renderer?.canLeave) return true
  try {
    return renderer.canLeave() !== false
  } catch (err) {
    console.error(err)
    return false
  }
}

function _isProjectOwnershipBoundary(routeState) {
  const sourceProjectId = _currentMountedRoute()?.route?.projectId || null
  return Boolean(
    sourceProjectId
    && sourceProjectId !== (routeState.projectId || null),
  )
}

function _prepareRouteTransition(routeState) {
  if (!_canLeaveMountedRoute(routeState)) return false
  if (!_isProjectOwnershipBoundary(routeState)) return true
  if (typeof closeModal !== "function") return true
  try {
    return closeModal({ reason: "project-navigation" }) !== false
  } catch (err) {
    console.error(err)
    return false
  }
}

function _restoreMountedRouteHash() {
  const mounted = _currentMountedRoute()
  if (!mounted) return
  const current = mounted.route
  const hash = _hashForRoute(current)
  if (window.location.hash === hash) return
  window.history.pushState({
    view: current.viewName,
    subView: current.subView,
    projectId: current.projectId,
  }, "", hash)
}

function _callRendererOnLeave(renderer) {
  if (!renderer?.onLeave) return
  try {
    renderer.onLeave()
  } catch (err) {
    console.error(err)
  }
}

function _disposeMountedRoute({ invalidateRender = true } = {}) {
  const mounted = _currentMountedRoute()
  if (!mounted) return false

  // 先清 owner 再调用外部 cleanup，避免 cleanup 重入或快速 A→B→C 时重复 onLeave。
  _mountedRoute = null
  if (_renderingRoute?.renderer === mounted.renderer) {
    _renderingRoute = null
  }
  if (invalidateRender) _renderGeneration += 1
  _callRendererOnLeave(mounted.renderer)
  return true
}

function _disposeRenderingRoute({ invalidateRender = true } = {}) {
  const rendering = _renderingRoute
  if (!rendering) return false

  // force refresh / 同 renderer 重入时，mounted 与 rendering 共享同一个资源 owner；
  // 统一交给 mounted cleanup，避免对同一实例执行两次 onLeave。
  const mounted = _currentMountedRoute()
  if (mounted?.renderer === rendering.renderer) {
    return _disposeMountedRoute({ invalidateRender })
  }

  _renderingRoute = null
  if (invalidateRender) _renderGeneration += 1
  _callRendererOnLeave(rendering.renderer)
  return true
}

function _showProjectTransition(routeState) {
  const content = document.getElementById("workspace-content")
  if (!content) return
  state.loading = true
  content.dataset.workspaceView = "loading"
  content.dataset.workspaceSubview = "project-transition"
  _showRouteLoadingSkeleton(content)
}

function _beginProjectScopeTransition(routeState) {
  if (!_isProjectOwnershipBoundary(routeState)) return false

  // preflight 已确认。onLeave 必须在旧 project state 和旧 DOM 仍存在时完成，
  // 之后才能提交中性 loading host 并切换 state.currentProjectId。
  const mounted = _currentMountedRoute()
  const sourceProjectId = mounted?.route?.projectId || null
  if (sourceProjectId) {
    state.currentProjectId = sourceProjectId
    if (mounted.project?.id === sourceProjectId) {
      state.currentProject = mounted.project
    }
  }
  _disposeMountedRoute()
  _failureRoute = null
  state.selectedItem = null
  _showProjectTransition(routeState)
  return true
}

function _projectSyncFailureKind(error) {
  const status = Number(error?.status || error?.statusCode || 0)
  if (status === 401) return "account"
  if (
    status === 0
    || status === 408
    || status === 425
    || status === 429
    || status >= 500
  ) {
    return "temporary"
  }
  if (status >= 400 && status < 500) return "inaccessible"
  return "temporary"
}

async function _applyRoute(routeState, { forceProject = false, showNeutral = false } = {}) {
  const route = _copyRouteState(routeState)
  const transitionGeneration = ++_routeTransitionGeneration
  const crossedProjectBoundary = _beginProjectScopeTransition(route)
  const interruptedRenderer = _disposeRenderingRoute()
  if ((showNeutral || interruptedRenderer) && !crossedProjectBoundary) {
    _failureRoute = null
    _showProjectTransition(route)
  }
  _pendingRoute = {
    generation: transitionGeneration,
    route,
  }

  const outcome = await _syncCurrentProject(route.projectId, {
    force: forceProject,
    preserveCurrentOnTemporary: false,
  })
  if (
    transitionGeneration !== _routeTransitionGeneration
    || _pendingRoute?.generation !== transitionGeneration
    || outcome.status === "stale"
  ) {
    return false
  }

  _pendingRoute = null
  if (outcome.status === "account") return false

  state.currentView = routeState.viewName
  state.currentSubView = routeState.subView
  _currentQuery = routeState.query || new URLSearchParams()

  if (outcome.status === "temporary" || outcome.status === "inaccessible") {
    _failureRoute = {
      generation: transitionGeneration,
      route,
      kind: outcome.status,
      host: null,
    }
    if (outcome.status === "temporary") {
      toast("项目信息加载失败，可稍后重试", "warning")
    }
  } else {
    _failureRoute = null
  }
  return true
}

/**
 * 获取视图最后访问的子标签
 * @param {string} viewName
 * @returns {string|null}
 */
function getLastSubView(viewName) {
  return _lastSubViewMap.get(viewName) || null
}

function _rememberSubView(viewName, subView) {
  if (!viewName || !subView) return
  _lastSubViewMap.set(viewName, subView)
}

/**
 * 同步当前项目状态：当 projectId 变化时加载项目元数据。
 * 避免面包屑/标题显示旧项目名或为空。
 */
async function _syncCurrentProject(
  projectId,
  { force = false, preserveCurrentOnTemporary = false } = {},
) {
  const generation = ++_projectSyncGeneration
  if (_projectSyncController) {
    _projectSyncController.abort()
    _projectSyncController = null
  }

  // 无 projectId 时保留当前选择（例如项目列表视图），不要清空 localStorage 恢复的状态
  if (!projectId) {
    return { status: "ok" }
  }

  const changed = state.currentProjectId !== projectId
  const previousProject = state.currentProject
  if (changed) {
    state.currentProjectId = projectId
    state.currentProject = null
  }

  const hasCompleteProject = state.currentProject
    && state.currentProject.id === projectId
    && !state.currentProject.summaryOnly

  // 当前项目对象已存在且 ID 一致时避免重复请求，refresh() 可通过 force 强制刷新
  if (!changed && hasCompleteProject && !force) {
    return { status: "ok" }
  }

  const controller = new AbortController()
  _projectSyncController = controller
  try {
    const project = await api.projects.get(projectId, {
      signal: controller.signal,
      cache: "no-store",
    })
    if (generation !== _projectSyncGeneration || state.currentProjectId !== projectId) {
      return { status: "stale" }
    }
    state.currentProject = project
    return { status: "ok" }
  } catch (err) {
    if (controller.signal.aborted || generation !== _projectSyncGeneration) {
      return { status: "stale" }
    }
    console.warn("加载项目信息失败:", err)
    const kind = _projectSyncFailureKind(err)
    if (kind === "temporary") {
      if (
        preserveCurrentOnTemporary
        && !changed
        && previousProject?.id === projectId
      ) {
        state.currentProject = previousProject
      } else {
        state.currentProject = null
      }
      return { status: "temporary", error: err }
    }
    if (kind === "inaccessible") {
      if (state.currentProjectId === projectId) {
        state.currentProjectId = null
        state.currentProject = null
      }
      return { status: "inaccessible", error: err }
    }
    return { status: "account", error: err }
  } finally {
    if (_projectSyncController === controller) {
      _projectSyncController = null
    }
  }
}

/** @type {boolean} 下一次渲染强制重新执行 onEnter（用于增删改后刷新当前视图） */
let _forceRefresh = false
let _renderGeneration = 0

function _notifyRouteSettled(viewName, subView) {
  for (const listener of _navListeners) {
    try {
      listener(viewName, subView)
    } catch (err) {
      console.error(err)
    }
  }
}

function _renderGenericFailure(content) {
  const stateEl = document.createElement("div")
  stateEl.className = "empty-state"
  stateEl.setAttribute("role", "alert")

  const icon = document.createElement("div")
  icon.className = "empty-icon"
  icon.style.color = "var(--danger)"
  icon.textContent = "!"

  const title = document.createElement("p")
  title.style.color = "var(--danger)"
  title.textContent = "页面加载失败"

  const message = document.createElement("p")
  message.style.cssText = "color:var(--text-dim);font-size:12px;"
  message.textContent = "你的项目内容没有受到影响。请先重试；若仍无法打开，可刷新应用。未保存的输入可能会丢失。"

  const retry = document.createElement("button")
  retry.type = "button"
  retry.className = "btn btn-primary"
  retry.dataset.action = "retry-route-render"
  retry.textContent = "重试"
  retry.addEventListener("click", () => {
    void _retryCurrentRouteRender()
  })

  const refresh = document.createElement("button")
  refresh.type = "button"
  refresh.className = "btn"
  refresh.dataset.action = "refresh-application"
  refresh.textContent = "刷新应用"
  refresh.addEventListener("click", () => {
    if (globalThis.confirm("刷新会丢失未保存的输入。确定要刷新应用吗？")) {
      globalThis.location.reload()
    }
  })

  const actions = document.createElement("div")
  actions.className = "actions"
  actions.append(retry, refresh)
  stateEl.append(icon, title, message, actions)
  content.replaceChildren(stateEl)
}

async function renderCurrentView() {
  const content = document.getElementById("workspace-content")
  if (!content) return
  const failure = _currentFailureRoute()
  const routeState = failure
    ? _copyRouteState(failure.route)
    : _routeStateFromAppState()
  const viewName = routeState.viewName
  const subView = routeState.subView || ""
  let renderer = viewRenderers.get(viewName)
  const mounted = _currentMountedRoute()

  // 视图或项目 owner 变化时统一走同一个 cleanup seam。项目边界通常已经在
  // _applyRoute 的同步阶段卸载；这里同时保护直接 renderCurrentView 的兼容调用。
  if (
    mounted
    && (
      mounted.route.viewName !== viewName
      || (mounted.route.projectId || null) !== (routeState.projectId || null)
    )
  ) {
    _disposeMountedRoute()
  }
  // 兼容直接、可重入的 renderCurrentView 调用；新 render 必须先使旧的半启动 renderer 失效。
  _disposeRenderingRoute()

  const renderGeneration = ++_renderGeneration
  // Keep visual scoping independent from rendered copy and business data. The
  // editorial theme uses these route markers to tune dense workspaces without
  // changing their DOM contracts or interaction handlers.
  content.dataset.workspaceView = failure ? "project-error" : (viewName || "unknown")
  content.dataset.workspaceSubview = failure ? failure.kind : (subView || "root")
  const isCurrentRender = () => (
    renderGeneration === _renderGeneration
    && state.currentView === viewName
    && (state.currentSubView || "") === subView
    && content.isConnected
    && document.getElementById("workspace-content") === content
    && (!failure || _failureRoute === failure)
  )
  const ownsRenderingRoute = () => (
    _renderingRoute?.generation === renderGeneration
  )

  const forceRefresh = _forceRefresh
  _forceRefresh = false
  const currentMounted = _currentMountedRoute()
  const preservedScrollTop = forceRefresh
    && !failure
    && _sameRoute(currentMounted?.route, routeState)
    ? content.scrollTop
    : null
  const preservedFocus = preservedScrollTop === null
    ? null
    : _captureFocusedControl(content)
  const isSameRender = !forceRefresh
    && !failure
    && _sameRoute(currentMounted?.route, routeState)

  state.loading = true
  if (!isSameRender) _showRouteLoadingSkeleton(content)

  try {
    if (failure) {
      // metadata 失败页不拥有业务 renderer；任何仍存在的 mounted owner 都必须先退出。
      if (_currentMountedRoute()) _disposeMountedRoute({ invalidateRender: false })
      failure.host = content
      _showProjectLoadFailure(content, failure)
    } else {
      // A configured loader is only invoked for an actually rendered route.
      // Pending calls are shared; rejected calls are cleared for a later retry.
      if (!renderer && viewLoaders.has(viewName)) {
        renderer = await _loadViewRenderer(viewName)
        if (!isCurrentRender()) return false
      }

      if (renderer) {
        _renderingRoute = {
          generation: renderGeneration,
          renderer,
          route: _copyRouteState(routeState),
        }
        if (!isSameRender && renderer.onEnter) {
          await renderer.onEnter()
          if (!isCurrentRender() || !ownsRenderingRoute()) return false
        }
        const html = await renderer.render()
        if (!isCurrentRender() || !ownsRenderingRoute()) return false
        content.innerHTML = html
        if (renderer.onRendered) {
          await renderer.onRendered()
          if (!isCurrentRender() || !ownsRenderingRoute()) return false
        }
        _renderingRoute = null
        _mountedRoute = {
          host: content,
          renderer,
          route: _copyRouteState(routeState),
          project: routeState.projectId ? state.currentProject : null,
        }
      } else {
        if (!isCurrentRender()) return false
        const route = routes[viewName]
        const emptyState = document.createElement("div")
        emptyState.className = "empty-state"
        const emptyIcon = document.createElement("div")
        emptyIcon.className = "empty-icon"
        emptyIcon.textContent = "☐"
        const label = document.createElement("p")
        label.textContent = `${route ? route.title : viewName} 页面`
        const copy = document.createElement("p")
        copy.style.color = "var(--text-dim)"
        copy.style.fontSize = "12px"
        copy.textContent = "此模块正在开发中，敬请期待"
        emptyState.replaceChildren(emptyIcon, label, copy)
        content.replaceChildren(emptyState)
        _mountedRoute = {
          host: content,
          renderer: null,
          route: _copyRouteState(routeState),
          project: routeState.projectId ? state.currentProject : null,
        }
      }
      if (preservedScrollTop !== null) {
        content.scrollTop = preservedScrollTop
        _restoreFocusedControl(content, preservedFocus)
      }
    }
  } catch (err) {
    if (!isCurrentRender()) return false
    console.error("View render error:", err)
    const activeMounted = _currentMountedRoute()
    if (activeMounted?.renderer === renderer) {
      _disposeMountedRoute({ invalidateRender: false })
    } else if (ownsRenderingRoute()) {
      _disposeRenderingRoute({ invalidateRender: false })
    } else {
      _callRendererOnLeave(renderer)
    }
    _mountedRoute = null
    _renderGenericFailure(content)
  } finally {
    if (ownsRenderingRoute() && !isCurrentRender()) {
      _disposeRenderingRoute({ invalidateRender: false })
    }
    if (isCurrentRender()) {
      state.loading = false
    }
  }

  if (!isCurrentRender()) return false
  _notifyRouteSettled(viewName, state.currentSubView)
  return true
}

async function _retryCurrentRouteRender() {
  return (await renderCurrentView()) !== false
}

async function _navigateWithHistory(viewName, subView, query, historyMode) {
  const routeState = _normalizeRoute({
    projectId: state.currentProjectId || null,
    viewName,
    subView,
    query: query || new URLSearchParams(),
  })

  if (routeState.redirectedToProject) {
    toast("请先选择作品后再进入该页面", "warning")
  }

  const sourceRoute = _representedRouteState()
  if (!_prepareRouteTransition(routeState)) return false

  if (sourceRoute.viewName) {
    if (
      sourceRoute.viewName !== routeState.viewName
      || sourceRoute.subView !== routeState.subView
    ) {
      _rememberSubView(sourceRoute.viewName, sourceRoute.subView)
    }
  }

  const isCurrent = await _applyRoute(routeState)
  if (!isCurrent) return false

  if (
    sourceRoute.viewName !== routeState.viewName
    || (sourceRoute.projectId || null) !== (routeState.projectId || null)
  ) {
    state.selectedItem = null
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
  return (await renderCurrentView()) !== false
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

async function _retryFailedProjectRoute(failure) {
  if (
    _currentFailureRoute() !== failure
    || failure?.kind !== "temporary"
  ) {
    return false
  }
  const isCurrent = await _applyRoute(failure.route, {
    forceProject: true,
    showNeutral: true,
  })
  if (!isCurrent) return false
  return (await renderCurrentView()) !== false
}

async function _returnFromFailedProjectRoute(failure) {
  if (_currentFailureRoute() !== failure) return false
  const failedProjectId = failure?.route?.projectId || null
  if (failedProjectId && state.currentProjectId === failedProjectId) {
    state.currentProjectId = null
    state.currentProject = null
  }
  _failureRoute = null
  return navigate("project")
}

/**
 * 强制刷新当前视图：重新执行 onEnter()（重新拉取数据）并重渲染。
 * 用于增删改操作后刷新列表 —— navigate 到当前位置会因 isSameRender 跳过 onEnter，
 * 导致界面显示旧数据，refresh 绕过该优化。
 */
async function refresh() {
  const activeFailure = _currentFailureRoute()
  if (activeFailure) return false

  const routeBeforeRefresh = _copyRouteState(
    _currentMountedRoute()?.route || _routeStateFromAppState(),
  )
  const outcome = await _syncCurrentProject(state.currentProjectId, {
    force: true,
    preserveCurrentOnTemporary: true,
  })
  if (outcome.status === "stale" || outcome.status === "account") return false

  if (outcome.status === "temporary") {
    toast("项目信息加载失败，当前页面已保留，可稍后重试", "warning")
    return false
  }

  if (outcome.status === "inaccessible" && routeBeforeRefresh.projectId) {
    if (typeof closeModal === "function") {
      try {
        closeModal({ force: true })
      } catch (err) {
        console.error(err)
      }
    }
    _disposeMountedRoute()
    const failure = {
      generation: ++_routeTransitionGeneration,
      route: routeBeforeRefresh,
      kind: "inaccessible",
      host: null,
    }
    _failureRoute = failure
    await renderCurrentView()
    return false
  }

  // 无项目页面即使选中的项目刚失效，也只需清除选择并正常重载页面本身。
  _failureRoute = null
  _forceRefresh = true
  const rendered = await renderCurrentView()
  return outcome.status === "ok" && rendered !== false
}

let _popstateBound = false

async function _handlePopState() {
  try {
    const hash = window.location.hash.slice(1) || "home"
    const parsed = _parseHash(hash)
    const routeState = _normalizeRoute(parsed)
    const sourceRoute = _representedRouteState()
    if (!_prepareRouteTransition(routeState)) {
      _restoreMountedRouteHash()
      return false
    }
    const canonicalHash = _hashForRoute(routeState)
    if (window.location.hash !== canonicalHash) {
      window.history.replaceState({ view: routeState.viewName, subView: routeState.subView, projectId: routeState.projectId }, "", canonicalHash)
    }
    const isCurrent = await _applyRoute(routeState)
    if (!isCurrent) return false
    if (
      sourceRoute.viewName !== routeState.viewName
      || (sourceRoute.projectId || null) !== (routeState.projectId || null)
    ) {
      state.selectedItem = null
    }
    return (await renderCurrentView()) !== false
  } catch (err) {
    console.warn("路由切换失败", err)
    if (typeof toast === "function") toast("路由切换失败，请重试", "error")
    return false
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

  let hash = window.location.hash.slice(1) || "home"
  let parsed = _parseHash(hash)
  let routeState = _normalizeRoute(parsed)
  if (!_prepareRouteTransition(routeState)) {
    _restoreMountedRouteHash()
    return false
  }
  let canonicalHash = _hashForRoute(routeState)
  if (window.location.hash !== canonicalHash) {
    window.history.replaceState({ view: routeState.viewName, subView: routeState.subView, projectId: routeState.projectId }, "", canonicalHash)
  }
  const isCurrent = await _applyRoute(routeState)
  if (!isCurrent) return false

  return (await renderCurrentView()) !== false
}

// 导出
window.router = { navigate, replace, refresh, commitCurrentQuery, getCurrentView, getRoute, getSubViewTitle, registerView, registerViewLoader, onNavigate, initRouter, getLastSubView, renderCurrentView, getCurrentQuery }

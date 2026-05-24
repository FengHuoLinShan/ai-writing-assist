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
  world: { title: "世界对象", subViews: ["objects", "candidates", "relations", "aliases"] },
  geo: { title: "地理历史", subViews: ["tree", "edges", "eras", "history", "map"] },
  character: { title: "人物档案", subViews: ["list", "detail", "knowledge"] },
  memory: { title: "长期记忆", subViews: ["records", "proposals", "by_chapter", "by_entity"] },
  timeline: { title: "时间线", subViews: [] },
  outline: { title: "剧情结构", subViews: ["threads", "arcs", "chapters", "foreshadowing", "reveals"] },
  rag: { title: "RAG 检索", subViews: ["status", "search"] },
  context: { title: "上下文", subViews: [] },
  review: { title: "结构复查", subViews: [] },
  writing: { title: "草稿导出", subViews: [] },
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
  return _state.currentView
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

async function renderCurrentView() {
  const viewName = _state.currentView
  const content = document.getElementById("workspace-content")

  if (!content) return

  // 调用上一个视图的 onLeave（不是当前视图的）
  if (_prevView && _prevView !== viewName) {
    const prevRenderer = viewRenderers[_prevView]
    if (prevRenderer && prevRenderer.onLeave) {
      try { prevRenderer.onLeave() } catch (e) { console.error(e) }
    }
  }
  _prevView = viewName

  _state.loading = true

  try {
    if (viewRenderers[viewName]) {
      // 调用视图的 onEnter
      if (viewRenderers[viewName].onEnter) {
        await viewRenderers[viewName].onEnter()
      }
      // 渲染
      const html = await viewRenderers[viewName].render()
      content.innerHTML = html
    } else {
      // 视图尚未实现
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
    _state.loading = false
  }

  // 更新右侧信息栏
  updateRightPanelForView(viewName)

  // 触发导航监听
  for (const listener of _navListeners) {
    try { listener(viewName, _state.currentSubView) } catch (e) { console.error(e) }
  }
}

/**
 * 切换视图
 * @param {string} viewName - 视图名称
 * @param {string|null} [subView] - 子视图名称
 * @param {boolean} [pushHistory=true] - 是否写入浏览器历史
 */
function navigate(viewName, subView = null, pushHistory = true) {
  if (!routes[viewName]) {
    console.warn(`未知路由: ${viewName}`)
    return
  }

  _state.currentView = viewName
  _state.currentSubView = subView

  // 清空选择
  _state.selectedItem = null
  _state.selectedItems = []

  // 更新 URL hash
  if (pushHistory) {
    const hash = subView ? `#${viewName}/${subView}` : `#${viewName}`
    if (window.location.hash !== hash) {
      window.history.pushState({ view: viewName, subView }, "", hash)
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
  const parts = hash.split("/")
  const viewName = parts[0]
  const subView = parts[1] || null

  if (routes[viewName]) {
    _state.currentView = viewName
    _state.currentSubView = subView
  } else {
    _state.currentView = "project"
  }

  // 监听浏览器前进/后退
  window.addEventListener("popstate", (e) => {
    // 从 hash 中读取当前视图（降级处理 e.state 为 null 的情况）
    const hash = window.location.hash.slice(1) || "project"
    const parts = hash.split("/")
    const viewFromHash = parts[0]
    const subFromHash = parts[1] || null

    const targetView = (e.state && e.state.view) ? e.state.view : viewFromHash
    const targetSubView = (e.state && e.state.subView !== undefined) ? e.state.subView : subFromHash

    if (routes[targetView]) {
      // 调用旧视图的 onLeave
      if (_prevView && _prevView !== targetView) {
        const prevRenderer = viewRenderers[_prevView]
        if (prevRenderer && prevRenderer.onLeave) {
          try { prevRenderer.onLeave() } catch (e) { console.error(e) }
        }
      }
      _prevView = targetView
      _state.currentView = targetView
      _state.currentSubView = targetSubView
      renderCurrentView()
    }
  })

  renderCurrentView()
}

// 导出
window.router = { navigate, getCurrentView, getRoute, registerView, onNavigate, initRouter }

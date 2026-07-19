import mapView from "../../../../views/mapView.js"
import { getAppState } from "../../../bridge/index.js"

// mapView 仍是单例渲染器。路由更换 Vue island 时，旧组件可能在新组件开始
// mount 后才执行 dispose。按 renderer 记录当前所有者，避免旧 controller 卸载
// 已被新路由实例接管的视口。
const rendererOwners = new WeakMap()

/**
 * Leaflet/Canvas 的窄命令式接缝。
 *
 * Vue 拥有地图工作台与挂载节点；旧 mapView 只允许操作传入节点的内部 DOM。
 * generation + project owner 双门禁防止异步 mount 在路由/项目切换后提交。
 */
export function createMapViewportController({
  renderer = mapView,
  getState = getAppState,
} = {}) {
  const ownership = {}
  let generation = 0
  let host = null
  let mounted = false
  let ownerProjectId = null

  function isCurrent(token, element, projectId) {
    return token === generation
      && host === element
      && element?.isConnected !== false
      && ownerProjectId === projectId
      && rendererOwners.get(renderer) === ownership
      && (!projectId || getState()?.currentProjectId === projectId)
  }

  async function mount(element, context = {}) {
    if (!(element instanceof HTMLElement)) {
      throw new TypeError("map viewport mount requires an HTMLElement")
    }

    const token = ++generation
    rendererOwners.set(renderer, ownership)
    renderer.unmount?.()
    mounted = false
    host = element
    ownerProjectId = context.projectId || getState()?.currentProjectId || null

    // mapView 仍有少量内部刷新固定查找 map-root；controller 保证该 ID
    // 只存在于当前 Vue viewport 内，Phase 5 不允许页面其他区域复用。
    element.id = "map-root"
    const didMount = await renderer.mount("map-root", {
      ...context,
      projectId: ownerProjectId,
    })

    if (!isCurrent(token, element, ownerProjectId)) {
      if (rendererOwners.get(renderer) === ownership) {
        renderer.unmount?.()
        rendererOwners.delete(renderer)
      }
      return false
    }
    mounted = didMount !== false
    return mounted
  }

  function dispose() {
    generation += 1
    if (rendererOwners.get(renderer) === ownership) {
      renderer.unmount?.()
      rendererOwners.delete(renderer)
    }
    mounted = false
    ownerProjectId = null
    host = null
  }

  function canLeave() {
    return renderer.canLeave?.() !== false
  }

  function setTimelineProjection(projection) {
    if (!mounted) return false
    renderer.setTimelineProjection?.(projection)
    return true
  }

  function clearTimelineProjection() {
    if (!mounted) return false
    renderer.clearTimelineProjection?.()
    return true
  }

  function forward(name, ...args) {
    if (!mounted || typeof renderer[name] !== "function") return false
    return renderer[name](...args)
  }

  return {
    mount,
    dispose,
    canLeave,
    setTimelineProjection,
    clearTimelineProjection,
    focusPath: (...args) => forward("focusPath", ...args),
    focusTimelineAnchor: (...args) => forward("focusTimelineAnchor", ...args),
    clearPathFocus: (...args) => forward("clearPathFocus", ...args),
    selectInspectorObject: (...args) => forward("selectInspectorObject", ...args),
    timelineEntityOptions: () => mounted ? (renderer.timelineEntityOptions?.() || []) : [],
    timelinePathOptions: () => mounted ? (renderer.timelinePathOptions?.() || []) : [],
    pathRevisionMismatch: (...args) => mounted ? Boolean(renderer.pathRevisionMismatch?.(...args)) : false,
    get mounted() { return mounted },
    get projectId() { return ownerProjectId },
  }
}

/**
 * mountIsland — 将 Vue 根组件包装为 vanilla router 的视图契约对象
 * （{ onEnter, render, onRendered, onLeave }），实现 strangler-fig 共存：
 * 外壳与路由仍归 vanilla，Vue 视图以"岛屿"形式挂载进 #workspace-content。
 *
 * 生命周期契约（router.js renderCurrentView）：
 * - onEnter 在每次渲染前被 await（同视图 forceRefresh 也会触发）：island 在此
 *   执行 load() 预取数据，结果作为 props 传给根组件，保证首屏即带数据，
 *   与 vanilla 视图"onEnter 取数 → render 出 HTML"的节奏一致。
 * - render() 返回挂载点 HTML 字符串，router 以 innerHTML 注入。
 * - onRendered 在注入后触发：挂载新实例；同视图 forceRefresh 不调 onLeave，
 *   因此挂载前先卸载残留实例。
 * - onLeave 在导航到其他视图时触发：卸载实例。
 *
 * settings/project-settings 不在 router 的 keep-alive 名单内，无需处理
 * DocumentFragment 缓存搬运；后续迁移 keep-alive 视图时再扩展该策略。
 *
 * canLeave：router 的路由守卫契约（router.js _canLeaveCurrentRoute，同步返回
 * false 阻断导航）。组件经 useLeaveGuard(fn) 注册同步守卫（如 worldBible 的
 * 未保存确认）；单槽位，后注册覆盖先注册，组件卸载时注销。
 *
 * query-only 导航兜底：router 的 isSameRender 优化在同视图+同子视图+同项目
 * 时跳过 onEnter（render/onRendered 仍执行）。world 等 query 驱动视图靠
 * onRendered() 挂载前的 query 漂移检测补载数据，vanilla 视图不受影响
 * （它们的数据加载本就在 render 阶段）；render() 保持同步纯挂载点契约。
 */
import { createApp } from "vue"
import { createPinia } from "pinia"
import { getRouter } from "./bridge/index.js"

/** provide key：island 内向组件暴露守卫注册器（useLeaveGuard 使用）。 */
export const ISLAND_LEAVE_GUARD = Symbol("vue-island-leave-guard")

export function mountIsland({ viewName, component, load = null }) {
  let app = null
  let loadedProps = {}
  let leaveGuard = null
  let loadedQuery = null

  function unmount() {
    if (app) {
      app.unmount()
      app = null
    }
    leaveGuard = null
  }

  async function reload() {
    loadedProps = load ? (await load()) || {} : {}
    loadedQuery = getRouter()?.getCurrentQuery?.()?.toString() ?? null
  }

  return {
    async onEnter() {
      await reload()
    },

    render() {
      return `<div class="vue-island" data-vue-island="${viewName}"></div>`
    },

    async onRendered() {
      if (load) {
        const query = getRouter()?.getCurrentQuery?.()?.toString() ?? null
        if (query !== loadedQuery) await reload()
      }
      unmount()
      const el = document.querySelector(`#workspace-content [data-vue-island="${viewName}"]`)
      if (!el) {
        console.error(`vue island mount point missing: ${viewName}`)
        return
      }
      app = createApp(component, loadedProps)
      app.use(createPinia())
      app.provide(ISLAND_LEAVE_GUARD, (fn) => { leaveGuard = fn || null })
      app.mount(el)
    },

    onLeave() {
      unmount()
    },

    canLeave() {
      if (!leaveGuard) return true
      return leaveGuard() !== false
    },
  }
}

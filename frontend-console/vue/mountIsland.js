/**
 * mountIsland — 将 Vue 视图包装为既有 hash router 的视图契约对象
 * （{ onEnter, render, onRendered, onLeave }）。Vue shell 拥有静态应用 DOM，
 * hash router 继续命令式拥有 #workspace-content 子树，各业务视图挂载到该 route host。
 *
 * 生命周期契约（router.js renderCurrentView）：
 * - onEnter 在每次渲染前被 await（同视图 forceRefresh 也会触发）：island 在此
 *   执行 load() 预取数据，结果作为 props 传给根组件，保证首屏即带数据，
 *   与既有视图"onEnter 取数 → render 提交"的节奏一致。
 * - render() 返回挂载点 HTML 字符串，router 以 innerHTML 注入。
 * - onRendered 在注入后触发：挂载新实例；同视图 forceRefresh 不调 onLeave，
 *   因此挂载前先卸载残留实例。
 * - onLeave 在导航到其他视图时触发：卸载实例。
 *
 * router 不再缓存 DocumentFragment。离开任何业务视图都会执行 onLeave，
 * 需要恢复的编辑会话由所属视图显式持久化，不依赖存活 DOM。
 *
 * canLeave：router 的路由守卫契约（router.js _canLeaveCurrentRoute，同步返回
 * false 阻断导航）。组件经 useLeaveGuard(fn) 注册同步守卫（如 worldBible 的
 * 未保存确认）；单槽位，后注册覆盖先注册，组件卸载时注销。
 *
 * query-only 导航兜底：router 的 isSameRender 优化在同视图+同子视图+同项目
 * 时跳过 onEnter（render/onRendered 仍执行）。world 等 query 驱动视图靠
 * onRendered() 挂载前的 query 漂移检测补载数据；render() 保持同步纯挂载点契约。
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
  let loadGeneration = 0

  function unmount() {
    if (app) {
      app.unmount()
      app = null
    }
    leaveGuard = null
  }

  async function reload() {
    const generation = ++loadGeneration
    const nextProps = load ? (await load()) || {} : {}
    if (generation !== loadGeneration) return false
    loadedProps = nextProps
    loadedQuery = getRouter()?.getCurrentQuery?.()?.toString() ?? null
    return true
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
        if (query !== loadedQuery && !(await reload())) return
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
      // 使仍在途的 onEnter/query 补载结果失效，避免项目或子视图切换后
      // 晚到响应覆盖下一次进入已经加载的新 props。
      loadGeneration += 1
      unmount()
    },

    canLeave() {
      if (!leaveGuard) return true
      return leaveGuard() !== false
    },
  }
}

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
 */
import { createApp } from "vue"
import { createPinia } from "pinia"

export function mountIsland({ viewName, component, load = null }) {
  let app = null
  let loadedProps = {}

  function unmount() {
    if (app) {
      app.unmount()
      app = null
    }
  }

  return {
    async onEnter() {
      loadedProps = load ? (await load()) || {} : {}
    },

    render() {
      return `<div class="vue-island" data-vue-island="${viewName}"></div>`
    },

    async onRendered() {
      unmount()
      const el = document.querySelector(`#workspace-content [data-vue-island="${viewName}"]`)
      if (!el) {
        console.error(`vue island mount point missing: ${viewName}`)
        return
      }
      app = createApp(component, loadedProps)
      app.use(createPinia())
      app.mount(el)
    },

    onLeave() {
      unmount()
    },
  }
}

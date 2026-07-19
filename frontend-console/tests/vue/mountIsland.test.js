/**
 * mountIsland 生命周期测试 — 对应 router.js 的视图契约。
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { h } from "vue"
import { mountIsland } from "../../vue/mountIsland.js"
import { useLeaveGuard } from "../../vue/composables/useLeaveGuard.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../vue/bridge/index.js"

const Probe = {
  name: "Probe",
  props: { message: { type: String, default: "" } },
  render() {
    return h("div", { class: "probe" }, this.message)
  },
}

function setupWorkspace() {
  document.body.innerHTML = '<div id="workspace-content"></div>'
  return document.getElementById("workspace-content")
}

describe("mountIsland", () => {
  let content
  beforeEach(() => {
    content = setupWorkspace()
  })

  afterEach(() => {
    resetBridgeOverrides()
  })

  it("render() 返回带 data-vue-island 标记的挂载点", () => {
    const island = mountIsland({ viewName: "settings", component: Probe })
    expect(island.render()).toContain('data-vue-island="settings"')
    expect(island.render()).toContain("vue-island")
  })

  it("onEnter 执行 load 并将结果作为 props 传给组件", async () => {
    const island = mountIsland({
      viewName: "settings",
      component: Probe,
      load: async () => ({ message: "预取数据" }),
    })
    await island.onEnter()
    content.innerHTML = island.render()
    await island.onRendered()
    expect(content.querySelector(".probe")?.textContent).toBe("预取数据")
    island.onLeave()
  })

  it("并发 onEnter 只提交最新一次 load 结果", async () => {
    const pending = []
    const island = mountIsland({
      viewName: "world",
      component: Probe,
      load: () => new Promise((resolve) => pending.push(resolve)),
    })

    const firstEnter = island.onEnter()
    const secondEnter = island.onEnter()
    pending[1]({ message: "new project" })
    await secondEnter
    pending[0]({ message: "stale project" })
    await firstEnter

    content.innerHTML = island.render()
    await island.onRendered()
    expect(content.querySelector(".probe")?.textContent).toBe("new project")
    island.onLeave()
  })

  it("onLeave 使在途 load 失效", async () => {
    setBridgeOverrides({ router: { getCurrentQuery: () => null } })
    let resolveLoad
    const island = mountIsland({
      viewName: "world",
      component: Probe,
      load: () => new Promise((resolve) => { resolveLoad = resolve }),
    })

    const entering = island.onEnter()
    island.onLeave()
    resolveLoad({ message: "late response" })
    await entering

    content.innerHTML = island.render()
    // 下一次进入之前不应提交已失效的 props。
    await island.onRendered()
    expect(content.querySelector(".probe")?.textContent).toBe("")
    island.onLeave()
  })

  it("重复 onRendered（同视图 forceRefresh 场景）先卸载旧实例再挂载", async () => {
    const island = mountIsland({
      viewName: "settings",
      component: Probe,
      load: async () => ({ message: "v1" }),
    })
    await island.onEnter()
    content.innerHTML = island.render()
    await island.onRendered()
    expect(content.querySelectorAll(".probe")).toHaveLength(1)

    // forceRefresh：不调用 onLeave，直接重渲染 innerHTML 后再 onRendered
    content.innerHTML = island.render()
    await island.onRendered()
    expect(content.querySelectorAll(".probe")).toHaveLength(1)
    island.onLeave()
  })

  it("onLeave 卸载实例", async () => {
    const island = mountIsland({ viewName: "settings", component: Probe })
    content.innerHTML = island.render()
    await island.onRendered()
    expect(content.querySelectorAll(".probe")).toHaveLength(1)
    island.onLeave()
    // 卸载后再次 onRendered（router 重放场景）可重新挂载
    content.innerHTML = island.render()
    await island.onRendered()
    expect(content.querySelectorAll(".probe")).toHaveLength(1)
    island.onLeave()
  })

  it("挂载点缺失时记录错误而不抛出", async () => {
    const island = mountIsland({ viewName: "settings", component: Probe })
    document.body.innerHTML = "<div></div>"
    await expect(island.onRendered()).resolves.toBeUndefined()
  })

  it("query 漂移时 onRendered 补载（router isSameRender 跳过 onEnter 场景）", async () => {
    let query = new URLSearchParams("skip=0")
    setBridgeOverrides({ router: { getCurrentQuery: () => query } })
    let calls = 0
    const island = mountIsland({
      viewName: "world",
      component: Probe,
      load: async () => {
        calls += 1
        return { message: `q${calls}` }
      },
    })
    await island.onEnter()
    content.innerHTML = island.render()
    await island.onRendered()
    expect(content.querySelector(".probe")?.textContent).toBe("q1")

    // query-only 导航：router 的 isSameRender 优化跳过 onEnter，直接 render + onRendered
    query = new URLSearchParams("skip=20")
    content.innerHTML = island.render()
    await island.onRendered()
    expect(calls).toBe(2)
    expect(content.querySelector(".probe")?.textContent).toBe("q2")

    // query 未漂移：不补载
    content.innerHTML = island.render()
    await island.onRendered()
    expect(calls).toBe(2)
    island.onLeave()
  })

  it("canLeave 默认放行；组件注册守卫后由守卫决定", async () => {
    let allow = true
    const GuardedProbe = {
      name: "GuardedProbe",
      setup() {
        useLeaveGuard(() => allow)
        return () => h("div", { class: "probe" }, "guarded")
      },
    }
    const island = mountIsland({ viewName: "world", component: GuardedProbe })
    content.innerHTML = island.render()

    expect(island.canLeave()).toBe(true) // 未挂载时无守卫

    await island.onRendered()
    expect(island.canLeave()).toBe(true)
    allow = false
    expect(island.canLeave()).toBe(false)

    island.onLeave()
    expect(island.canLeave()).toBe(true) // 卸载后守卫注销
  })
})

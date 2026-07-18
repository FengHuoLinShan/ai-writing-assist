/**
 * mountIsland 生命周期测试 — 对应 router.js 的视图契约。
 */
import { describe, it, expect, beforeEach } from "vitest"
import { h } from "vue"
import { mountIsland } from "../../vue/mountIsland.js"

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
})

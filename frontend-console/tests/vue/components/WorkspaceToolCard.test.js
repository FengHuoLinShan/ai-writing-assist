import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import WorkspaceToolCard from "../../../vue/components/WorkspaceToolCard.vue"
import { focusWorkspaceTool } from "../../../vue/components/workspaceTools.js"

enableAutoUnmount(afterEach)
describe("workspace workflow tools", () => {
  let media, change
  beforeEach(() => {
    document.body.innerHTML = '<div id="main-layout"><aside><div id="sidebar-context-slot"></div></aside><main id="workspace"></main><button id="outside">正文</button></div>'
    media = { matches: false, addEventListener: vi.fn((_event, handler) => { change = handler }), removeEventListener: vi.fn() }
    vi.spyOn(window, "matchMedia").mockReturnValue(media)
  })
  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = "" })
  const create = (extra = {}) => mount(WorkspaceToolCard, {
    attachTo: document.getElementById("workspace"),
    props: { title: "地图工具", context: "临江城", actions: [{ key: "add", label: "添加地点", primary: true }], ...extra },
  })
  const button = (action) => document.querySelector(`[data-action="workspace-tool-${action}"]`)

  it("owns one responsive card, closes the mobile drawer before dispatch and cleans up the sidebar", async () => {
    const selected = vi.fn(() => expect(document.querySelector('[role="dialog"]')).toBeNull())
    const wrapper = create({ onSelect: selected })
    expect(document.querySelector("#sidebar-context-slot .workspace-tools")).not.toBeNull()
    media.matches = true; change(); await flushPromises()
    expect(document.querySelector("#sidebar-context-slot").children).toHaveLength(0)
    expect(document.querySelector(".workspace-tools")).toBeNull()
    document.querySelector(".workspace-tools-trigger").click(); await flushPromises()
    expect(document.querySelectorAll(".workspace-tools")).toHaveLength(1)
    button("add").click(); await flushPromises()
    expect(selected).toHaveBeenCalledExactlyOnceWith("add")
    wrapper.unmount()
    expect(document.querySelector(".workspace-tools")).toBeNull()
    expect(media.removeEventListener).toHaveBeenCalled()
  })

  it("keeps a focused action stable while rechecking current availability before executing", async () => {
    const wrapper = create()
    button("add").focus(); await flushPromises()
    await wrapper.setProps({ actions: [{ key: "progress", label: "查看进度", primary: true }] })
    expect(button("add")).not.toBeNull()
    button("add").click(); await flushPromises()
    expect(wrapper.emitted("select")).toBeUndefined()
    document.getElementById("outside").focus(); await flushPromises()
    expect(button("progress").textContent).toBe("查看进度")
  })

  it("keeps disabled explanations visible and never invents pending counts", async () => {
    const wrapper = create({ actions: [{ key: "generate", label: "整理空间关系", primary: true, disabled: true, hint: "请先保存当前地图", badge: 0 }] })
    expect(button("generate").disabled).toBe(true)
    expect(document.querySelector(".today-count")).toBeNull()
    expect(document.getElementById(button("generate").getAttribute("aria-describedby")).textContent).toContain("请先保存")
    button("generate").click(); await flushPromises()
    expect(wrapper.emitted("select")).toBeUndefined()
  })

  it("opens More outside the scrolling sidebar, supports keyboard activation and restores focus", async () => {
    const wrapper = create({ moreActions: [{ key: "history", label: "地图历史" }] })
    const trigger = document.querySelector(".action-menu-btn")
    trigger.focus(); trigger.click(); await flushPromises()
    const list = document.querySelector('[role="menu"]')
    expect(list.closest("#sidebar-context-slot")).toBeNull()
    expect(document.activeElement).toBe(button("history"))
    button("history").dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    await flushPromises()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(document.activeElement).toBe(trigger)
    trigger.click(); await flushPromises()
    button("history").click(); await flushPromises()
    expect(wrapper.emitted("select")).toEqual([["history"]])
  })

  it("closes a floating menu when its anchor scrolls outside the viewport", async () => {
    create({ moreActions: [{ key: "history", label: "地图历史" }] })
    const trigger = document.querySelector(".action-menu-btn")
    trigger.click(); await flushPromises()
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({ top: -100, bottom: -56, left: 0, right: 100 })
    document.dispatchEvent(new Event("scroll"))
    await flushPromises()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("opens the original nested panel and focuses its input", async () => {
    const root = document.getElementById("workspace")
    root.innerHTML = '<details><summary>地图</summary><details><summary>地点</summary><div id="source"><input aria-label="查证地点" /></div></details></details>'
    expect(await focusWorkspaceTool(root, "#source")).toBe(true)
    expect([...root.querySelectorAll("details")].every(item => item.open)).toBe(true)
    expect(document.activeElement.getAttribute("aria-label")).toBe("查证地点")
    expect(await focusWorkspaceTool(root, "#missing")).toBe(false)
  })
})

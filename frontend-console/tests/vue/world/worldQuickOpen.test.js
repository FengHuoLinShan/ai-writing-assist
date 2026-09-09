import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import WorldQuickOpen from "../../../vue/views/world/library/WorldQuickOpen.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

let host
let navigateMock
let listWorldLibrary

beforeEach(() => {
  host = document.createElement("div")
  host.id = "workspace-content"
  document.body.appendChild(host)
  navigateMock = vi.fn(() => true)
  listWorldLibrary = vi.fn(async () => ({
    items: [
      { kind: "entity", id: "entity-1", title: "雾港灯塔", state: "active", working: false, item_type: "location", summary: "北境地标" },
      { kind: "page", id: "page-1", title: "世界基本背景", state: "active", working: true, draft_id: "draft-1", item_type: "background", summary: "" },
    ],
    total: 2,
  }))
  setBridgeOverrides({
    api: {
      world: {
        listWorldLibrary,
        recordWorldLibraryRecent: vi.fn(async () => null),
      },
    },
    router: { navigate: navigateMock },
    toast: vi.fn(),
  })
})

afterEach(() => {
  resetBridgeOverrides()
  host.remove()
  document.body.innerHTML = ""
})

function openDialog() {
  const event = new CustomEvent("shell:quickopen-request", { bubbles: false, cancelable: true })
  host.dispatchEvent(event)
  return event
}

describe("WorldQuickOpen 快速打开资料", () => {
  it("shell:quickopen-request 打开对话框，默认展示最近使用", async () => {
    const wrapper = mount(WorldQuickOpen, { props: { projectId: "p1" }, attachTo: document.body })

    const event = openDialog()
    expect(event.defaultPrevented).toBe(true)
    await wrapper.vm.$nextTick()
    const dialog = document.querySelector(".world-quick-open")
    expect(dialog).not.toBeNull()

    await vi.waitFor(() => expect(listWorldLibrary).toHaveBeenCalled())
    await vi.waitFor(() => expect(dialog.textContent).toContain("雾港灯塔"))
    expect(dialog.textContent).toContain("工作稿")
  })

  it("输入关键词走统一资料列表搜索", async () => {
    const wrapper = mount(WorldQuickOpen, { props: { projectId: "p1" }, attachTo: document.body })
    openDialog()
    await wrapper.vm.$nextTick()
    await vi.waitFor(() => expect(listWorldLibrary).toHaveBeenCalled())
    listWorldLibrary.mockClear()

    const dialog = document.querySelector(".world-quick-open")
    const input = dialog.querySelector("[data-action='world-quick-open-input']")
    input.value = "灯塔"
    input.dispatchEvent(new Event("input", { bubbles: true }))
    await wrapper.vm.$nextTick()
    await vi.waitFor(() => expect(listWorldLibrary).toHaveBeenCalledWith(expect.objectContaining({ q: "灯塔" })))
  })

  it("↑↓ 移动选择，Enter 打开资料并记录最近访问", async () => {
    const recordRecent = vi.fn(async () => null)
    setBridgeOverrides({
      api: { world: { listWorldLibrary, recordWorldLibraryRecent: recordRecent } },
      router: { navigate: navigateMock },
      toast: vi.fn(),
    })
    const wrapper = mount(WorldQuickOpen, { props: { projectId: "p1" }, attachTo: document.body })
    openDialog()
    await wrapper.vm.$nextTick()
    const dialog = document.querySelector(".world-quick-open")
    await vi.waitFor(() => expect(dialog.textContent).toContain("世界基本背景"))
    await vi.waitFor(() => expect(dialog.textContent).toContain("世界基本背景"))
    const input = dialog.querySelector("[data-action='world-quick-open-input']")

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }))
    await wrapper.vm.$nextTick()
    const activeRow = dialog.querySelector(".world-quick-open__row--active")
    expect(activeRow?.textContent).toContain("世界基本背景")
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }))
    await wrapper.vm.$nextTick()

    expect(navigateMock).toHaveBeenCalledTimes(1)
    const [view, subView, , params] = navigateMock.mock.calls[0]
    expect([view, subView]).toEqual(["world", "bible"])
    expect(params.get("draft_id")).toBe("draft-1")
    expect(recordRecent).toHaveBeenCalledWith("p1", "page", "page-1")
    expect(document.querySelector(".world-quick-open")).toBeNull()
  })

  it("没有项目时不打开并提示", () => {
    const toast = vi.fn()
    setBridgeOverrides({
      api: { world: {} },
      router: { navigate: navigateMock },
      toast,
    })
    mount(WorldQuickOpen, { props: { projectId: "" }, attachTo: document.body })
    const event = openDialog()
    expect(event.defaultPrevented).toBe(true)
    expect(toast).toHaveBeenCalledWith("请先选择一个作品", "info")
    expect(document.querySelector(".world-quick-open")).toBeNull()
  })
})
